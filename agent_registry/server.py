# agent_registry/server.py
"""
Agent Registry Service - RESTful API for managing AI Agent cards.

This module provides a FastAPI application with endpoints for registering
and querying agents. It includes rate limiting, request size checks,
and persistence using a JSON file.
"""

import asyncio
from functools import partial, lru_cache
from typing import List, Optional

from a2a.types import AgentCard
from fastapi import FastAPI, HTTPException, Query, Request, Depends, status
from loguru import logger
from limits import strategies, storage, parse_many
from starlette.responses import Response

from agent_registry.config import (
    PERSISTENCE_FILE,
    MAX_REQUEST_BODY_SIZE,
    MAX_URL_LENGTH,
    MAX_REQUEST_RATE,
)
from agent_registry.core import RegistryCore
from agent_registry.middleware import ConnectionLimitMiddleware, TimeoutMiddleware
from agent_registry.model.validated_agentcard import ValidatedAgentCard
from common.util.config_util import get_conf

# ---------- Rate Limiter Setup (In-Memory) ----------
# Use in-memory storage for single-node deployments. Counts reset on restart.
sync_storage = storage.MemoryStorage()
# Moving window strategy provides smoother rate limiting.
limiter = strategies.MovingWindowRateLimiter(sync_storage)


def parse_rate_limit(rate_string: str):
    """
    Parse a rate limit string like "10/minute" into a RateLimitItem.
    Returns None if parsing fails.
    """
    items = parse_many(rate_string)
    return items[0] if items else None


# Global default rate limit from configuration.
DEFAULT_RATE = parse_rate_limit(MAX_REQUEST_RATE)


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

    def __init__(self, rate_string: str = None):
        self.rate_item = parse_rate_limit(rate_string) if rate_string else DEFAULT_RATE
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
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_SIZE:
                    return Response(
                        content="Payload Too Large",
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    )
            except ValueError:
                # If content-length header is malformed, let FastAPI handle it.
                pass

    # URL length check (full URL including scheme and host)
    # Using str(request.url) gives the complete URL string.
    if len(str(request.url)) > MAX_URL_LENGTH:
        return Response(
            content="URI Too Long",
            status_code=status.HTTP_414_URI_TOO_LONG,
        )

    return await call_next(request)


# ---------- Routes ----------
@app.post(
    "/rest/a2a-t/v1/agents/register",
    response_model=bool,
    summary="Register a new agent",
)
async def register_agent(
    agent: ValidatedAgentCard,
    _: None = Depends(RateLimiter()),  # Apply rate limiting
    registry: RegistryCore = Depends(get_registry),
):
    """
    Register a new agent.
    The combination (name, provider.organization) must be unique.
    Returns True if registered, False if duplicate.
    """
    try:
        success = await registry.register(agent)
        return success
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error in register: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e


@app.get(
    "/rest/a2a-t/v1/agents/query",
    response_model=List[AgentCard],
    summary="Exact search",
)
async def list_agents_exact(
    name: Optional[str] = Query(None, description="Exact agent name"),
    organization: Optional[str] = Query(None, description="Exact organization"),
    registry: RegistryCore = Depends(get_registry),
):
    """
    Search agents by exact fields (AND combination).
    All parameters are optional. If none provided, returns all agents.
    """
    try:
        agents = registry.find_exact(name=name, organization=organization)
        return agents
    except Exception as e:
        logger.error(f"Error in exact search: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from e