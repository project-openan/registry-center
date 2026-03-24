# agent_registry/server.py
"""
Agent Registry Service - RESTful API for managing AI Agent cards.

This module provides a FastAPI application with endpoints for registering
and querying agents. It includes rate limiting, request size checks,
and persistence using a JSON file.
"""

import asyncio
from functools import partial, lru_cache
from typing import List, Optional, Tuple, Any

import anyio
from a2a.types import AgentCard
from fastapi import FastAPI, HTTPException, Query, Request, Depends, status
from fastapi.responses import JSONResponse
from loguru import logger
from limits import strategies, storage, parse_many
from starlette.responses import Response

from agent_registry.config import (
    PERSISTENCE_FILE,
    MAX_REQUEST_BODY_SIZE,
    MAX_URL_LENGTH,
)
from agent_registry.core import RegistryCore
from agent_registry.middleware import ConnectionLimitMiddleware, TimeoutMiddleware
from agent_registry.model.validated_agentcard import ValidatedAgentCard
from common.log.audit_logger import audit_logger, OperationResult, LogLevel, OperatorObject, OperationName
from common.util.config_util import get_conf

# ---------- Rate Limiter Setup (In-Memory) ----------
# Use in-memory storage for single-node deployments. Counts reset on restart.
sync_storage = storage.MemoryStorage()
# Moving window strategy provides smoother rate limiting.
limiter = strategies.MovingWindowRateLimiter(sync_storage)


def parse_rate_limit(interface_name: str):
    """
    Parse rate limit for the given interface name and return a RateLimitItem.
    Returns None if parsing fails or interface is unknown.
    The rate value is read from config with a default of 10, and unit is fixed to "/second".
    """
    # Mapping from interface name to config key and default value
    config_map = {
        "register": ("flowcontrol.ratelimit.register", 10),
        "query": ("flowcontrol.ratelimit.query", 10),
    }

    # Get the corresponding config entry
    entry = config_map.get(interface_name)
    if entry is None:
        logger.warning(f"Unknown interface '{interface_name}', cannot get rate limit")
        return None

    key, default_value = entry
    try:
        # Read config value and convert to int; fallback to default if invalid
        rate_value = int(config.get(key, default_value))
    except (ValueError, TypeError):
        logger.error(f"Config key '{key}' has invalid value, using default {default_value}")
        rate_value = default_value

    rate_string = f"{rate_value}/second"
    try:
        items = parse_many(rate_string)
        return items[0] if items else None
    except Exception as e:
        logger.error(f"Failed to parse rate limit string '{rate_string}': {e}")
        return None


async def async_hit(rate_item, *identifiers: str, cost=1) -> bool:
    """
    Asynchronously call the synchronous limiter.hit() using a thread pool.
    This prevents blocking the event loop, though the operation is fast in memory.
    """
    func = partial(limiter.hit, rate_item, *identifiers, cost=cost)
    return await asyncio.to_thread(func)


class RateLimiter:
    """
    FastAPI dependency for rate limiting requests based on client IP.
    Uses X-Forwarded-For header when behind a proxy.
    """

    def __init__(self, interface_name: str = None):
        self.rate_item = parse_rate_limit(interface_name)
        if not self.rate_item:
            raise ValueError("Invalid rate limit configuration")

    async def __call__(self, request: Request):
        # Determine client identifier: prefer X-Forwarded-For, fallback to direct IP.
        identifier = request.client.host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            identifier = forwarded.split(",")[0].strip()

        # Check rate limit; if exceeded, raise 429.
        if not await async_hit(self.rate_item, identifier):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too Many Requests"
            )
        return True


class SizeValidator:
    """大小验证器"""

    def __init__(self, max_size: int = 500 * 1024):
        self.max_size = max_size

    async def __call__(self, request: Request):
        body = await request.body()
        if len(body) > self.max_size:
            raise HTTPException(
                status_code=413,
                detail=f"Request body is too large, maximum allowed {self.max_size // 1024}KB"
            )
        return request


# ---------- FastAPI Application ----------
app = FastAPI(
    title="Agent Registry Service",
    description="RESTful API for managing AI Agent cards with persistence and semantic search.",
    version="2.0.0",
)

config = get_conf()

app.add_middleware(
    ConnectionLimitMiddleware,
    max_connections=int(config.get("connection.max", 11))
)

app.add_middleware(
    TimeoutMiddleware,
    timeout_seconds=int(config.get("connection.timeout", 30))
)

register_semaphore = anyio.Semaphore(int(config.get("flowcontrol.parallelism.registe", 1)))
query_semaphore = anyio.Semaphore(int(config.get("flowcontrol.parallelism.query", 10)))


# ---------- Dependency: Registry Core (Singleton) ----------
@lru_cache(maxsize=1)
def get_registry() -> RegistryCore:
    """
    Return a singleton instance of RegistryCore.
    The @lru_cache ensures the same instance is reused across requests,
    avoiding repeated loading of the persistence file.
    """
    return RegistryCore(persistence_file=PERSISTENCE_FILE)


# ---------- Middleware ----------
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """
    Middleware for basic security checks:
    - Limit request body size for POST/PUT.
    - Limit total URL length.
    """
    # Body size check for write methods
    if request.method in ("POST", "PUT"):
        try:
            body = await request.body()
            if len(body) > MAX_REQUEST_BODY_SIZE:
                return Response(
                    content="Payload Too Large",
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                )
            request._body = body
        except Exception:
            return Response(
                content="Bad Request",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    # URL length check (full URL including scheme and host)
    # Using str(request.url) gives the complete URL string.
    if len(str(request.url)) > MAX_URL_LENGTH:
        return Response(
            content="URI Too Long",
            status_code=status.HTTP_414_URI_TOO_LONG,
        )

    return await call_next(request)


# ---------- Routes ----------
def _check_agent_limit(registry: RegistryCore, client_ip: str, details: dict) -> None:
    """检查注册数量是否超过上限，若超过则记录审计日志并抛出异常。"""
    if len(registry.get_agents()) >= int(config.get('agent.num.max', 40)):
        details["message"] = "Agent registration limit exceeded."
        audit_logger.audit({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Agent registration limit exceeded.",
        )


def _check_duplicate_agent(agent: ValidatedAgentCard, registry: RegistryCore, client_ip: str, details: dict) -> None:
    """检查是否已存在相同 (name, organization) 的 agent，若存在则记录并抛出异常。"""
    key = _make_agent_key(agent.name, agent.provider.organization)
    if key in registry.get_agents():
        details["message"] = "Registration skipped: duplicate agent."
        audit_logger.audit({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Registration skipped: duplicate agent ({agent.name}, {agent.provider.organization})",
        )


async def _perform_registration(
        agent: ValidatedAgentCard,
        registry: RegistryCore,
        client_ip: str,
        details: dict,
) -> bool:
    """执行实际的注册操作，处理可能的 ValueError 和其他异常，并记录对应日志。"""
    try:
        success = await registry.register(agent)
        audit_logger.audit({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.SUCCESS,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        return success
    except ValueError as e:
        details["message"] = str(e)
        audit_logger.audit({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        audit_logger.audit({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        logger.error(f"Unexpected error in register: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@app.post(
    "/rest/a2a-t/v1/agents/register",
    response_model=bool,
    summary="Register a new agent",
    status_code=status.HTTP_201_CREATED,
)
async def register_agent(
        agent: ValidatedAgentCard,
        request: Request = Depends(SizeValidator(max_size=500 * 1024)),
        _: Any = Depends(RateLimiter('register')),
        registry: RegistryCore = Depends(get_registry),
):
    """
    Register a new agent.
    The combination (name, provider.organization) must be unique.
    Returns True if registered, False if duplicate.
    """
    client_ip = request.client.host
    details = {
        "agentName": agent.name,
        "organization": agent.provider.organization,
        "url": agent.provider.url,
    }

    try:
        register_semaphore.acquire_nowait()
        _check_agent_limit(registry, client_ip, details)
        _check_duplicate_agent(agent, registry, client_ip, details)
        result = await _perform_registration(agent, registry, client_ip, details)
        return JSONResponse(
            content=result,
            status_code=status.HTTP_201_CREATED,
        )

    except anyio.WouldBlock:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy")
    finally:
        register_semaphore.release()


@app.get(
    "/rest/a2a-t/v1/agents/query",
    response_model=List[AgentCard],
    summary="Exact search",
)
async def list_agents_exact(
        name: Optional[str] = Query(None, description="Exact agent name"),
        organization: Optional[str] = Query(None, description="Exact organization"),
        registry: RegistryCore = Depends(get_registry), _: Any = Depends(RateLimiter('query')),  #
):
    """
    Search agents by exact fields (AND combination).
    All parameters are optional. If none provided, returns all agents.
    """
    try:
        query_semaphore.acquire_nowait()
    except anyio.WouldBlock:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy")
    try:
        agents = registry.find_exact(name=name, organization=organization)
        return agents
    except Exception as e:
        logger.error(f"Error in exact search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e
    finally:
        query_semaphore.release()


def _make_agent_key(name: str, organization: str) -> Tuple[str, str]:
    """Create a normalized key for indexing."""
    return name.strip(), organization.strip()
