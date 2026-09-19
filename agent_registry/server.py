# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# agent_registry/server.py
"""
Agent Registry Service - RESTful API for managing AI Agent cards.

This module provides a FastAPI application with endpoints for registering
and querying agents. It includes rate limiting, request size checks,
and persistence using a JSON file.
"""

import asyncio
import json
import time
from functools import partial
from typing import Optional, Tuple, Any, Dict

import anyio
from a2a.types import AgentCard
from fastapi import FastAPI, HTTPException, Query, Request, Depends, status, Path
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.responses import StreamingResponse
from google.protobuf.json_format import Parse, MessageToDict
from loguru import logger
from limits import strategies, storage, parse_many
from urllib.parse import urlparse

from starlette.responses import Response

from agent_registry.agent_registry.jwk_provider import JWKProvider, CertLoadError
from agent_registry.agent_registry.agent_card_signer import AgentCardSigner
from agent_registry.config import (
    MAX_REQUEST_BODY_SIZE,
    MAX_URL_LENGTH, CONN_TIMEOUT, CONN_MAX, FLOW_CTL_PARALLEL_REGISTER, FLOW_CTL_PARALLEL_QUERY, FLOW_CTL_REGISTER,
    FLOW_CTL_QUERY, AGENT_NUM_MAX, FLOW_CTL_PARALLEL_UPDATE, FLOW_CTL_PARALLEL_GET, FLOW_CTL_PARALLEL_RETRIEVE,
    FLOW_CTL_PARALLEL_DEREGISTER, FLOW_CTL_UPDATE, FLOW_CTL_GET, FLOW_CTL_RETRIEVE, FLOW_CTL_DEREGISTER,
    FLOW_CTL_JWK, FLOW_CTL_PARALLEL_JWK, OWNER_ISOLATION_ENABLED, OWNER_VALIDATION_MODE,
    FLOW_CTL_HEARTBEAT, FLOW_CTL_PARALLEL_HEARTBEAT, FLOW_CTL_SUBSCRIPTION, FLOW_CTL_PARALLEL_SUBSCRIPTION,
    BROADCAST_ALLOW_HTTP_CALLBACKS, BROADCAST_CALLBACK_ALLOWLIST,
)
from contextlib import asynccontextmanager

from agent_registry.core import RegistryCore, make_agent_key
from agent_registry.broadcast import get_broadcast_service, initialize_broadcast_service
from agent_registry.broadcast.events import EventType, utc_now_iso
from agent_registry.broadcast.subscriptions import Subscription
from agent_registry.health import get_health_service, initialize_health_service
from agent_registry.health.state import HealthStatus
from agent_registry.model.validated_agentcard import validate_agent_card
from agent_registry.registry_instance import get_registry, initialize_registry
from agent_registry.middleware import ConnectionLimitMiddleware, TimeoutMiddleware
from agent_registry.signature.agent_card_signature_validator import AgentCardSignatureValidator
from agent_registry.signature.jwk_fetcher import JWKFetcher
from agent_registry.signature.public_key_manager import PublicKeyManager

from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import OperationResult, LogLevel, OperatorObject, OperationName
from common.util.app_config import get_conf
from common.cert.cert_cn_parser import validate_cn

# Import knowledge graph router
from agent_registry.knowledge_graph_api import knowledge_graph_router, close_neo4j_driver

# ---------- Rate Limiter Setup (In-Memory) ----------
# Use in-memory storage for single-node deployments. Counts reset on restart.
sync_storage = storage.MemoryStorage()
# Moving window strategy provides smoother rate limiting.
limiter = strategies.MovingWindowRateLimiter(sync_storage)

audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)

_signature_validator: Optional[AgentCardSignatureValidator] = None
_registry_signer: Optional[AgentCardSigner] = None


def get_signature_validator() -> AgentCardSignatureValidator:
    """Get or create signature validator instance"""
    global _signature_validator
    if _signature_validator is None:
        public_key_manager = PublicKeyManager()
        jwk_fetcher = JWKFetcher(
            public_key_manager,
            jwk_allowlist=config.get('jwk_allowlist', ''),
        )
        validation_enabled = config.get('signature_validation_enabled', 'true').lower() == 'true'
        _signature_validator = AgentCardSignatureValidator(jwk_fetcher, signature_validation_enabled=validation_enabled)
    return _signature_validator


def get_registry_signer() -> Optional[AgentCardSigner]:
    """Get or create registry signer instance based on config"""
    global _registry_signer
    if _registry_signer is None:
        sign_enabled_raw = config.get('registry.sign.enabled', 'false')
        sign_enabled = sign_enabled_raw.lower() == 'true'
        logger.info(f"registry.sign.enabled raw value: '{sign_enabled_raw}', parsed: {sign_enabled}")
        
        if sign_enabled:
            private_key_path = config.get('jwk_private_key_path', '')
            cert_path = config.get('jwk_cert_path', '')
            password_path = config.get('jwk_private_key_password', '')
            
            ip = config.get('ip', '127.0.0.1')
            port = config.get('port', '5000')
            jku_url = f"https://{ip}:{port}/rest/v1/registry-center/keys"
            
            logger.info(f"private_key_path: '{private_key_path}', cert_path: '{cert_path}', password_path: '{password_path}'")
            logger.info(f"jku_url: '{jku_url}' (ip='{ip}', port='{port}')")
            
            if private_key_path and cert_path:
                try:
                    _registry_signer = AgentCardSigner(
                        private_key_path=private_key_path,
                        cert_path=cert_path,
                        password_path=password_path if password_path else None,
                        jku_url=jku_url,
                        sign_enabled=True
                    )
                    logger.info("Registry signer initialized successfully")
                except Exception as e:
                    logger.error(f"Failed to initialize registry signer: {e}")
                    _registry_signer = AgentCardSigner(sign_enabled=False)
            else:
                logger.warning("Registry signer disabled: missing private_key_path or cert_path")
                _registry_signer = AgentCardSigner(sign_enabled=False)
        else:
            logger.info("registry.sign.enabled is false, creating disabled signer")
            _registry_signer = AgentCardSigner(sign_enabled=False)
            logger.info("disabled signer created successfully")
    
    if _registry_signer:
        logger.info(f"registry_signer.is_enabled(): {_registry_signer.is_enabled()}")
    return _registry_signer


def parse_rate_limit(interface_name: str):
    """
    Parse rate limit for the given interface name and return a RateLimitItem.
    Returns None if parsing fails or interface is unknown.
    The rate value is read from config with a default of 10, and unit is fixed to "/second".
    """
    # Mapping from interface name to config key and default value
    config_map = {
        "register": (FLOW_CTL_REGISTER, 50),
        "query": (FLOW_CTL_QUERY, 100),
        "update": (FLOW_CTL_UPDATE, 100),
        "get": (FLOW_CTL_GET, 100),
        "retrieve": (FLOW_CTL_RETRIEVE, 100),
        "deregister": (FLOW_CTL_DEREGISTER, 50),
        "jwk": (FLOW_CTL_JWK, 10),
        "heartbeat": (FLOW_CTL_HEARTBEAT, 100),
        "subscription": (FLOW_CTL_SUBSCRIPTION, 50),
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


@asynccontextmanager
async def semaphore_guard(sem: anyio.Semaphore):
    """Acquire a semaphore, yield, then release. Raises 503 if semaphore is at capacity."""
    try:
        sem.acquire_nowait()
        acquired = True
    except anyio.WouldBlock:
        acquired = False
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy")
    try:
        yield
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in endpoint: {e}")
        raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error") from e
    finally:
        if acquired:
            sem.release()


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
        # Check rate limit; if exceeded, raise 429.
        if not await async_hit(self.rate_item, identifier):
            raise CustomHTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too Many Requests")
        return True


# ---------- FastAPI Application ----------
app = FastAPI(
    title="Agent Registry Service",
    description="RESTful API for managing AI Agent cards with persistence and semantic search.",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

def _get_int_config(config: dict, key: str, default: int) -> int:
    """Safely parse integer config values, falling back to default on error."""
    try:
        return int(config.get(key, default))
    except (ValueError, TypeError):
        logger.warning(f"Invalid integer value for '{key}', using default {default}")
        return default


config = get_conf()

app.add_middleware(
    ConnectionLimitMiddleware,
    max_connections=_get_int_config(config, CONN_MAX, 500)
)

app.add_middleware(
    TimeoutMiddleware,
    timeout_seconds=_get_int_config(config, CONN_TIMEOUT, 300)
)

register_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_REGISTER, 50))
query_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_QUERY, 100))
update_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_UPDATE, 100))
get_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_GET, 100))
retrieve_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_RETRIEVE, 100))
deregister_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_DEREGISTER, 50))
jwk_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_JWK, 1))
heartbeat_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_HEARTBEAT, 100))
subscription_semaphore = anyio.Semaphore(_get_int_config(config, FLOW_CTL_PARALLEL_SUBSCRIPTION, 50))

class CustomHTTPException(HTTPException):
    def __init__(self, status_code: int, error_message: str, extra: Optional[dict] = None):
        super().__init__(status_code=status_code, detail=error_message)
        self.extra = extra

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    content = {
        "errors": {
            "error": [
                {
                    "errorMessage": exc.detail
                }
            ]
        }
    }
    if getattr(exc, "extra", None):
        content.update(exc.extra)
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    error_messages = "; ".join(
        "{}: {}".format(".".join(str(loc) for loc in error.get("loc", [])), error.get("msg", ""))
        for error in exc.errors()
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "errors": {
                "error": [
                    {
                        "errorMessage": error_messages or "Request validation failed"
                    }
                ]
            }
        },
    )

# ---------- Middleware ----------
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """
    Middleware for basic security checks:
    - Limit request body size for POST/PUT.
    - Limit total URL length.
    """
    # URL length check (full URL including scheme and host)
    # Using str(request.url) gives the complete URL string.
    if len(str(request.url)) > MAX_URL_LENGTH:
        return Response(
            content="URI Too Long",
            status_code=status.HTTP_414_URI_TOO_LONG,
        )
    # Body size check for write methods
    if request.method in ("POST", "PUT", "PATCH"):
        total_size = 0
        body_chunks = []

        try:
            # Stream body in chunks
            async for chunk in request.stream():
                total_size += len(chunk)

                # Early exit if size exceeds limit
                if total_size > MAX_REQUEST_BODY_SIZE:
                    return Response(
                        content=f"Request body is too large, maximum allowed {MAX_REQUEST_BODY_SIZE // 1024} KB",
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    )

                body_chunks.append(chunk)
            request._body = b''.join(body_chunks)
        except Exception as e:
            logger.error(f"Error reading request body: {e}")
            return Response(
                content="Bad Request",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return await call_next(request)


# ---------- Routes ----------
async def _audit_result(op_name: OperationName, success: bool, details: dict, client_ip: str):
    """Log audit entry for operation result."""
    await audit_handle.handle({
        "operation_name": op_name,
        "level": LogLevel.MINOR,
        "result": OperationResult.SUCCESS if success else OperationResult.FAILURE,
        "object_name": OperatorObject.AGENT,
        "details": details,
        "client_ip": client_ip
    })


async def _audit_failure(op_name: OperationName, details: dict, client_ip: str):
    """Log audit entry for operation failure."""
    await _audit_result(op_name, False, details, client_ip)


def _get_owner_from_request(request: Request) -> Optional[str]:
    """
    Extract owner (CN) from request header X-SSL-Client-DN.
    Parses CN from the DN string format: CN=username,O=Org,C=US

    Returns:
        CN value (None if not present or if owner isolation is disabled)
    """
    if not OWNER_ISOLATION_ENABLED:
        return None

    dn = request.headers.get('X-SSL-Client-DN')
    if dn:
        # Parse CN from DN string (format: CN=username,O=Org,C=US)
        dn = dn.strip()
        cn_value = None
        for part in dn.split(','):
            part = part.strip()
            if part.upper().startswith('CN='):
                cn_value = part[3:].strip()
                break

        if cn_value:
            if OWNER_VALIDATION_MODE == 'strict':
                if not validate_cn(cn_value):
                    logger.warning(f"Invalid CN format: {cn_value}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid CN format: {cn_value}"
                    )
            return cn_value
    return None


async def _verify_owner_permission(
    request: Request,
    name: str,
    organization: str,
    registry: RegistryCore
) -> Optional[str]:
    """
    Verify owner permission for update/delete operations.

    Flow:
    1. Extract CN from request as current_owner
    2. Query agent to get stored_owner
    3. Check if stored_owner is None/empty (public agent) - allow any user
    4. If stored_owner is set, verify current_owner matches

    Returns:
        current_owner (if verification succeeds)

    Raises:
        HTTPException: If permission denied or agent not found
    """
    if not OWNER_ISOLATION_ENABLED:
        return None

    current_owner = _get_owner_from_request(request)

    agent_record = registry.get_by_key_with_owner(name, organization)
    if not agent_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent ({name}, {organization}) not found"
        )

    stored_owner = agent_record.owner

    if stored_owner is None or stored_owner == '':
        return current_owner

    if current_owner != stored_owner:
        logger.warning(f"Permission denied: current_owner={current_owner}, stored_owner={stored_owner}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: agent belongs to {stored_owner}"
        )

    return current_owner


async def _check_agent_limit(registry: RegistryCore, client_ip: str, details: dict) -> None:
    """Check if registration count exceeds the limit, log and raise an exception if so."""
    if registry.count() >= _get_int_config(config, AGENT_NUM_MAX, 100):
        details["message"] = "Agent registration limit exceeded."
        await _audit_failure(OperationName.REGISTER_AGENT, details, client_ip)
        raise CustomHTTPException(status.HTTP_409_CONFLICT, "Agent registration limit exceeded.")


async def _check_duplicate_agent(agent: AgentCard, registry: RegistryCore, client_ip: str,
                                 details: dict) -> None:
    """Check if an agent with same (name, organization) already exists, log and raise if found."""
    key = make_agent_key(agent.name, agent.provider.organization)
    if key in registry.get_agents():
        details["message"] = "Registration skipped: duplicate agent."
        await _audit_failure(OperationName.REGISTER_AGENT, details, client_ip)
        raise CustomHTTPException(status.HTTP_409_CONFLICT,
                                  f"Registration skipped: duplicate agent ({agent.name}, {agent.provider.organization})")


def _is_hidden_unhealthy(name: str, organization: str) -> bool:
    """When heartbeat detection hides unhealthy agents, suspect/offline vanish from queries."""
    try:
        health_service = get_health_service()
        if not health_service.enabled or not health_service.hide_unhealthy_results:
            return False
        health = health_service.status_of(name, organization)
        return health in (HealthStatus.SUSPECT.value, HealthStatus.OFFLINE.value)
    except Exception:
        return False


def _validate_callback_url(url: str) -> None:
    """Webhook SSRF guard: scheme restriction plus an optional hostname allowlist."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                  "callback_url must be a valid http(s) URL")
    allow_http = str(get_conf().get(BROADCAST_ALLOW_HTTP_CALLBACKS, "false")).lower() == "true"
    if parsed.scheme == "http" and not allow_http:
        raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                  "HTTP callbacks are disabled; use an HTTPS callback_url")
    allowlist = str(get_conf().get(BROADCAST_CALLBACK_ALLOWLIST, "")).strip()
    if allowlist:
        allowed_hosts = [h.strip() for h in allowlist.split(",") if h.strip()]
        if parsed.hostname not in allowed_hosts:
            raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                      f"callback host '{parsed.hostname}' is not in the allowlist")


async def _perform_registration(
        agent: AgentCard,
        client_ip: str,
        details: dict,
        initial_status: str = 'published',
        owner: Optional[str] = None,
) -> bool:
    """Execute the actual registration, handle ValueError and other exceptions, log accordingly."""
    try:
        save_handle = HandlerRegistry.get_handler(InterfaceType.INSERT)
        success = await save_handle.handle(agent, initial_status=initial_status, owner=owner)
        return success
    except ValueError as e:
        details["message"] = str(e)
        await _audit_failure(OperationName.REGISTER_AGENT, details, client_ip)
        logger.error(f"Register agent failed: name={agent.name}, org={agent.provider.organization}, reason={e}")
        raise CustomHTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except Exception as e:
        details["message"] = "Internal server error"
        await _audit_failure(OperationName.REGISTER_AGENT, details, client_ip)
        logger.exception(f"Unexpected error in register: name={agent.name}, org={agent.provider.organization}")
        raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,"Internal server error") from e


async def _perform_update(
        client_ip: str,
        name: str,
        organization: str,
        data: dict,
        details: dict,
        owner: Optional[str] = None,
) -> bool:
    """Execute the actual update, handle ValueError and other exceptions, log accordingly."""
    try:
        update_handle = HandlerRegistry.get_handler(InterfaceType.UPDATE)
        success = await update_handle.handle(name, organization, data, owner=owner)
        if success:
            await _audit_result(OperationName.UPDATE_AGENT, True, details, client_ip)
        return success
    except ValueError as e:
        details["message"] = str(e)
        await _audit_failure(OperationName.UPDATE_AGENT, details, client_ip)
        logger.error(f"Update agent failed: name={name}, org={organization}, reason={e}")
        raise CustomHTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except Exception as e:
        details["message"] = "Internal server error"
        await _audit_failure(OperationName.UPDATE_AGENT, details, client_ip)
        logger.exception(f"Unexpected error in update: name={name}, org={organization}")
        raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,"Internal server error") from e


@app.post(
    "/rest/v1/registry-center/agent-cards",
    summary="Register a new agent",
    status_code=status.HTTP_201_CREATED,
)
async def register_agent(
        request: Request,
        _: Any = Depends(RateLimiter('register')),
        registry: RegistryCore = Depends(get_registry),
        signature_validator: AgentCardSignatureValidator = Depends(get_signature_validator),
        registry_signer: Optional[AgentCardSigner] = Depends(get_registry_signer),
):
    """
    Register a new agent.
    The combination (name, provider.organization) must be unique.
    On success returns 201 with a per-card result list:
    {"results": [{"name", "organization", "status", "registrySigned"}]},
    where "status" is "published" or "registered" (pending approval).
    On failure the error response additionally carries "registeredAgents" with the
    cards already registered by this request (partial success visibility).
    """
    body = await request.json()
    agent_cards = body.get("agentCards", [])
    if not agent_cards:
        raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agentCards must be a non-empty list")
    client_ip = request.client.host
    total_cards = len(agent_cards)

    owner = _get_owner_from_request(request) if OWNER_ISOLATION_ENABLED else None

    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    registered_results = []
    async with semaphore_guard(register_semaphore):
        for index, agent_card in enumerate(agent_cards, start=1):
            agent = Parse(json.dumps(agent_card), AgentCard())
            card_started = time.perf_counter()
            logger.info(
                f"Register agent request: card={index}/{total_cards}, name={agent.name}, org={agent.provider.organization}, client={client_ip}, owner={owner}")
            details = {
                "agentName": agent.name,
                "organization": agent.provider.organization,
                "url": agent.provider.url,
            }
            try:
                await _check_agent_limit(registry, client_ip, details)
                await _check_duplicate_agent(agent, registry, client_ip, details)
                try:
                    validate_agent_card(agent)
                except HTTPException as e:
                    details["message"] = e.detail
                    await _audit_failure(OperationName.REGISTER_AGENT, details, client_ip)
                    raise CustomHTTPException(
                        e.status_code, f"Card {index}/{total_cards} ({agent.name}): {e.detail}") from e

                signature_result = signature_validator.validate_agent_card(agent)
                if not signature_result.is_valid:
                    details["message"] = signature_result.error_message
                    await _audit_failure(OperationName.REGISTER_AGENT, details, client_ip)
                    raise CustomHTTPException(
                        status.HTTP_401_UNAUTHORIZED,
                        f"Card {index}/{total_cards} ({agent.name}): "
                        f"{signature_result.error_message or 'Signature verification failed'}"
                    )

                registry_signed = bool(registry_signer and registry_signer.is_enabled())
                if registry_signed:
                    agent = registry_signer.sign_agent_card(agent)
                    logger.info(f"Registry signature added for agent: card={index}/{total_cards}, name={agent.name}")

                approval_enabled = config.get('agent_approval_enabled', 'false')
                initial_status = 'registered' if approval_enabled == 'true' else 'published'

                result = await _perform_registration(agent, client_ip, details, initial_status=initial_status, owner=owner)
                if not result:
                    raise CustomHTTPException(
                        status.HTTP_409_CONFLICT,
                        f"Agent '{agent.name}' already exists in organization '{agent.provider.organization}'"
                    )
                await _audit_result(OperationName.REGISTER_AGENT, result, details, client_ip)

                duration_ms = int((time.perf_counter() - card_started) * 1000)
                logger.info(
                    f"Register agent success: card={index}/{total_cards}, name={agent.name}, org={agent.provider.organization}, status={initial_status}, registrySigned={registry_signed}, duration={duration_ms}ms")
                registered_results.append({
                    "name": agent.name,
                    "organization": agent.provider.organization,
                    "status": initial_status,
                    "registrySigned": registry_signed,
                })
            except CustomHTTPException as e:
                logger.error(
                    f"Register batch aborted at card {index}/{total_cards}: name={agent.name}, org={agent.provider.organization}, httpStatus={e.status_code}, detail={e.detail}")
                if e.extra is None:
                    e.extra = {"registeredAgents": registered_results}
                raise

        return JSONResponse(status_code=status.HTTP_201_CREATED, content={"results": registered_results})


@app.get(
    "/rest/v1/registry-center/agent-cards",
    response_model=None,
    summary="Query agent cards",
)
async def list_agents_exact(
        request: Request,
        name: Optional[str] = Query(None, description="Exact agent name"),
        organization: Optional[str] = Query(None, description="Exact organization"),
        registry: RegistryCore = Depends(get_registry),
        _: Any = Depends(RateLimiter('query')),
):
    """
    Search agents by exact fields (AND combination).
    All parameters are optional. If none provided, returns all agents.
    Only returns agents with published status, response does not include status field.
    """
    client_ip = request.client.host
    logger.info(f"Query agents request: name={name}, org={organization}, client={client_ip}")
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    async with semaphore_guard(query_semaphore):
        query_handle = HandlerRegistry.get_handler(InterfaceType.QUERY)
        agents = await query_handle.handle(name, organization)

        published_agents = []
        for agent in agents:
            agent_status = registry.get_status(agent.name, agent.provider.organization)
            if agent_status != 'published':
                continue
            if _is_hidden_unhealthy(agent.name, agent.provider.organization):
                continue
            agent_dict = MessageToDict(agent)
            published_agents.append(agent_dict)
        logger.info(f"Query agents result: {len(published_agents)} agents found")
        return {"agentCards": published_agents}


@app.put("/rest/v1/registry-center/agent-cards/{organization}/{name}", summary="Full update(replace) an agent")
async def update_agent(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Path(..., description="Agent organization"),
        registry: RegistryCore = Depends(get_registry),
        _: Any = Depends(RateLimiter('update')),
        signature_validator: AgentCardSignatureValidator = Depends(get_signature_validator),
        registry_signer: Optional[AgentCardSigner] = Depends(get_registry_signer),
):
    """
    Fully replace an existing agent. The name and organization in the body must match the path/query.
    On success returns 200 with {"results": [{"name", "organization", "registrySigned"}]}.
    Returns 404 if the agent does not exist.
    """
    body_json = await request.json()
    agent_cards = body_json.get("agentCards", [])
    if not agent_cards:
        raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agentCards must be a non-empty list")
    client_ip = request.client.host
    total_cards = len(agent_cards)

    owner = await _verify_owner_permission(request, name, organization, registry) if OWNER_ISOLATION_ENABLED else None

    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    updated_results = []
    async with semaphore_guard(update_semaphore):
        for index, agent_card in enumerate(agent_cards, start=1):
            agent_data = Parse(json.dumps(agent_card), AgentCard())
            card_started = time.perf_counter()
            logger.info(f"Update agent request: card={index}/{total_cards}, name={name}, org={organization}, client={client_ip}, owner={owner}")
            details = {
                "agentName": agent_data.name,
                "organization": agent_data.provider.organization,
                "url": agent_data.provider.url,
            }
            try:
                try:
                    validate_agent_card(agent_data)
                except HTTPException as e:
                    details["message"] = e.detail
                    await _audit_failure(OperationName.UPDATE_AGENT, details, client_ip)
                    raise CustomHTTPException(
                        e.status_code, f"Card {index}/{total_cards} ({agent_data.name}): {e.detail}") from e

                signature_result = signature_validator.validate_agent_card(agent_data)
                if not signature_result.is_valid:
                    details["message"] = signature_result.error_message
                    await _audit_failure(OperationName.UPDATE_AGENT, details, client_ip)
                    raise CustomHTTPException(
                        status.HTTP_401_UNAUTHORIZED,
                        f"Card {index}/{total_cards} ({agent_data.name}): "
                        f"{signature_result.error_message or 'Signature verification failed'}"
                    )

                registry_signed = bool(registry_signer and registry_signer.is_enabled())
                if registry_signed:
                    agent_data = registry_signer.sign_agent_card(agent_data)
                    logger.info(f"Registry signature added for agent: card={index}/{total_cards}, name={agent_data.name}")

                data = MessageToDict(agent_data, preserving_proto_field_name=True)
                success = await _perform_update(client_ip, name, organization, data, details, owner=owner)
                if not success:
                    raise CustomHTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

                duration_ms = int((time.perf_counter() - card_started) * 1000)
                logger.info(
                    f"Update agent success: card={index}/{total_cards}, name={name}, org={organization}, registrySigned={registry_signed}, duration={duration_ms}ms")
                updated_results.append({
                    "name": name,
                    "organization": organization,
                    "registrySigned": registry_signed,
                })
            except CustomHTTPException as e:
                logger.error(
                    f"Update batch aborted at card {index}/{total_cards}: name={name}, org={organization}, httpStatus={e.status_code}, detail={e.detail}")
                if e.extra is None:
                    e.extra = {"updatedAgents": updated_results}
                raise
        return JSONResponse(status_code=status.HTTP_200_OK, content={"results": updated_results})


@app.delete("/rest/v1/registry-center/agent-cards/{organization}/{name}", summary="Deregister an agent")
async def deregister_agent(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Path(..., description="Agent organization"),
        registry: RegistryCore = Depends(get_registry),
        _: Any = Depends(RateLimiter('deregister'))
):
    """
    Remove an agent from the registry.
    On success returns 200 with {"name", "organization", "deleted": true}.
    Returns 404 if the agent does not exist.
    """
    client_ip = request.client.host

    owner = await _verify_owner_permission(request, name, organization, registry) if OWNER_ISOLATION_ENABLED else None

    logger.info(f"Deregister agent request: name={name}, org={organization}, client={client_ip}, owner={owner}")
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    details = {"agentName": name, "organization": organization}

    async with semaphore_guard(deregister_semaphore):
        deregister_handle = HandlerRegistry.get_handler(InterfaceType.DEREGISTER)
        success = await deregister_handle.handle(name, organization, owner=owner)
        await _audit_result(OperationName.DEREGISTER_AGENT, success, details, client_ip)
        if not success:
            raise CustomHTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
        logger.info(f"Deregister agent success: name={name}, org={organization}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"name": name, "organization": organization, "deleted": True},
        )


@app.post("/rest/v1/registry-center/agent-cards/semantic-query", response_model=None, summary="Fuzzy retrieve by task")
async def retrieve_agents_by_task(
        request: Request,
        top_n: int = 10,
        _: Any = Depends(RateLimiter('retrieve'))
):
    """
    Find agents that are semantically relevant to the given task using LLM.
    """
    body_json = await request.json()
    task = body_json.get("task")
    client_ip = request.client.host
    logger.info(f"Retrieve agents request: task='{task}', top_n={top_n}, client={client_ip}")
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    async with semaphore_guard(retrieve_semaphore):
        retrieve_handle = HandlerRegistry.get_handler(InterfaceType.RETRIEVE)
        agents = await retrieve_handle.handle(task, top_n)
        agents = [agent for agent in agents
                  if not _is_hidden_unhealthy(agent.name, agent.provider.organization)]
        result = [MessageToDict(agent) for agent in agents]
        logger.info(f"Retrieve agents result: {len(result)} agents found for task='{task}'")
        return {"agentCards": result}


@app.get("/rest/v1/registry-center/agent-cards/{organization}/{name}", response_model=None, summary="Get agent by exact name and organization")
async def get_agent(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Path(..., description="Agent organization"),
        _: Any = Depends(RateLimiter('get')),
        registry: RegistryCore = Depends(get_registry),
):
    """
    Search a single agent by its unique key(name and organization).
    Only returns agents with published status, response does not include status field.
    """
    client_ip = request.client.host
    logger.info(f"Get agent request: name={name}, org={organization}, client={client_ip}")
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    async with semaphore_guard(get_semaphore):
        get_handle = HandlerRegistry.get_handler(InterfaceType.GET)
        record = await get_handle.handle(name, organization)

        if record is None:
            return {"agentCards": []}

        agent_status = registry.get_status(name, organization)
        if agent_status != 'published':
            return {"agentCards": []}

        if _is_hidden_unhealthy(name, organization):
            return {"agentCards": []}

        agent_dict = MessageToDict(record.agent_card)
        logger.info(f"Get agent result: {'found' if agent_dict else 'not found'} for name={name}, org={organization}")
        return {"agentCards": [agent_dict]}


def close_registry():
    registry = get_registry()
    registry.close()


# ---------- Heartbeat & Health Endpoints ----------
@app.post(
    "/rest/v1/registry-center/agent-cards/{organization}/{name}/heartbeat",
    summary="Report an agent heartbeat",
)
async def report_heartbeat(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Path(..., description="Agent organization"),
        registry: RegistryCore = Depends(get_registry),
        _: Any = Depends(RateLimiter('heartbeat')),
):
    """
    Agents periodically report liveness. The response carries the effective
    detection config so agents can align with the registry dynamically.
    """
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    async with semaphore_guard(heartbeat_semaphore):
        health_service = get_health_service()
        if not health_service.enabled:
            return JSONResponse(status_code=status.HTTP_200_OK, content={
                "heartbeat_enabled": False,
                "server_time": utc_now_iso(),
            })
        record = registry.get_by_key_with_owner(name, organization)
        if record is None:
            raise CustomHTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

        previous, state = health_service.record_heartbeat(name, organization)
        if previous is not None and previous != state.status:
            get_broadcast_service().event_bus.publish(EventType.AGENT_HEALTH_CHANGED, {
                "name": name,
                "organization": organization,
                "health_status": state.status.value,
                "previous_health_status": previous.value,
                "tags": registry.get_agent_tags(name, organization) or [],
            })
            logger.info(f"Agent recovered via heartbeat: {name}({organization}) "
                        f"{previous.value} -> {state.status.value}")

        return JSONResponse(status_code=status.HTTP_200_OK, content={
            "heartbeat_enabled": True,
            "interval": health_service.interval,
            "failure_threshold": health_service.failure_threshold,
            "grace_period": health_service.grace_period,
            "server_time": utc_now_iso(),
            "health_status": state.status.value,
        })


@app.get("/rest/v1/registry-center/agents/health", summary="List agent health states")
async def list_agents_health(
        request: Request,
        health_status: Optional[str] = Query(None, alias="status",
                                             description="Filter: healthy/suspect/offline"),
        _: Any = Depends(RateLimiter('query')),
):
    """Admin overview of heartbeat-monitored agents for observability dashboards."""
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    if health_status is not None and health_status not in (s.value for s in HealthStatus):
        raise CustomHTTPException(status.HTTP_400_BAD_REQUEST,
                                  f"Invalid status filter '{health_status}'")

    async with semaphore_guard(query_semaphore):
        health_service = get_health_service()
        agents = []
        for state in health_service.list_monitored():
            if health_status is not None and state.status.value != health_status:
                continue
            agents.append({
                "name": state.name,
                "organization": state.organization,
                "health_status": state.status.value,
                "last_heartbeat_at": state.last_heartbeat_at.isoformat(),
                "status_changed_at": state.status_changed_at.isoformat(),
            })
        # Detection config lets dashboards align with the actual thresholds
        # (e.g. countdown-to-offline bars) instead of hard-coded defaults.
        return {"agents": agents, "config": health_service.detection_config()}


@app.get("/rest/v1/registry-center/agents/health/history",
         summary="Query agent health transition history")
async def list_agents_health_history(
        request: Request,
        name: Optional[str] = Query(None, description="Filter by agent name"),
        organization: Optional[str] = Query(None, description="Filter by organization"),
        limit: int = Query(50, ge=1, le=500, description="Max entries"),
        _: Any = Depends(RateLimiter('query')),
):
    """Recent health status transitions (newest first) for audits and timelines."""
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    async with semaphore_guard(query_semaphore):
        health_service = get_health_service()
        if not health_service.enabled:
            raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                      "Heartbeat detection is disabled")
        return {"history": health_service.history(name, organization, limit)}


@app.get("/rest/v1/registry-center/agents/health/stream",
         summary="Stream agent health changes (Server-Sent Events)")
async def stream_agent_health(
        request: Request,
        _: Any = Depends(RateLimiter('query')),
):
    """
    Real-time AGENT_HEALTH_CHANGED push over SSE. Emits `event: health_changed`
    frames with the RegistryEvent payload; a `: ping` comment every 15s keeps
    intermediaries from closing the connection.
    """
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    health_service = get_health_service()
    if not health_service.enabled:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                  "Heartbeat detection is disabled")

    broadcast_service = get_broadcast_service()
    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    def listener(event):
        if event.event_type != EventType.AGENT_HEALTH_CHANGED:
            return
        try:
            loop.call_soon_threadsafe(event_queue.put_nowait, event)
        except RuntimeError:
            pass  # event loop already closed

    async def event_stream():
        broadcast_service.event_bus.add_listener(listener)
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                    payload = json.dumps(event.to_dict(), ensure_ascii=False)
                    yield f"event: health_changed\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broadcast_service.event_bus.remove_listener(listener)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Subscription & Change Broadcast Endpoints ----------
@app.post("/rest/v1/registry-center/subscriptions", status_code=status.HTTP_201_CREATED,
          summary="Create a change broadcast subscription")
async def create_subscription(
        request: Request,
        _: Any = Depends(RateLimiter('subscription')),
):
    body = await request.json()
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    broadcast_service = get_broadcast_service()
    if not broadcast_service.broadcast_enabled:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                  "Change broadcast is disabled")

    async with semaphore_guard(subscription_semaphore):
        callback_url = body.get("callback_url")
        if not callback_url or not isinstance(callback_url, str):
            raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                      "callback_url is required")
        _validate_callback_url(callback_url)

        event_types = body.get("event_types")
        if event_types is not None:
            if not isinstance(event_types, list) or \
                    any(t not in (e.value for e in EventType) for t in event_types):
                raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                          "event_types must be a list of valid event type names")
        filters = body.get("filters") or {}
        if not isinstance(filters, dict):
            raise CustomHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                                      "filters must be an object")

        subscription = Subscription(
            subscription_id="",
            callback_url=callback_url,
            event_types=event_types,
            organizations=filters.get("organizations"),
            tags=filters.get("tags"),
            secret=body.get("secret"),
        )
        created = broadcast_service.subscription_store.create(subscription)
        if broadcast_service.dispatcher is not None:
            broadcast_service.dispatcher.add_subscription(created)
        logger.info(f"Subscription created: {created.subscription_id} -> {created.callback_url}")
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=created.to_dict())


@app.get("/rest/v1/registry-center/subscriptions", summary="List subscriptions")
async def list_subscriptions(
        request: Request,
        _: Any = Depends(RateLimiter('subscription')),
):
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    broadcast_service = get_broadcast_service()
    if not broadcast_service.broadcast_enabled:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                  "Change broadcast is disabled")
    subs = broadcast_service.subscription_store.list_all()
    return {"subscriptions": [s.to_dict() for s in subs]}


@app.delete("/rest/v1/registry-center/subscriptions/{subscription_id}",
            summary="Delete a subscription")
async def delete_subscription(
        request: Request,
        subscription_id: str = Path(..., description="Subscription ID"),
        _: Any = Depends(RateLimiter('subscription')),
):
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    broadcast_service = get_broadcast_service()
    if not broadcast_service.broadcast_enabled:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                  "Change broadcast is disabled")
    if not broadcast_service.subscription_store.delete(subscription_id):
        raise CustomHTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    if broadcast_service.dispatcher is not None:
        broadcast_service.dispatcher.remove_subscription(subscription_id)
    logger.info(f"Subscription deleted: {subscription_id}")
    return JSONResponse(status_code=status.HTTP_200_OK,
                        content={"subscription_id": subscription_id, "deleted": True})


@app.get("/rest/v1/registry-center/changes", summary="Reconcile registry changes since a version")
async def list_changes(
        request: Request,
        since: int = Query(0, ge=0, description="Last known registry_version"),
        limit: int = Query(100, ge=1, le=1000, description="Max events per page"),
        _: Any = Depends(RateLimiter('query')),
):
    """Fallback/reconciliation API: events with registry_version > since, ascending."""
    client_ip = request.client.host
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)

    async with semaphore_guard(query_semaphore):
        broadcast_service = get_broadcast_service()
        events = broadcast_service.outbox.list_after(since, limit + 1)
        has_more = len(events) > limit
        events = events[:limit]
        next_since = events[-1].registry_version if events else since
        return {
            "changes": [e.to_dict() for e in events],
            "has_more": has_more,
            "next_since": next_since,
        }


# ---------- Service lifecycle for health & broadcast ----------
_health_sweeper = None


async def startup_services():
    """Initialize health/broadcast stores and start background tasks."""
    global _health_sweeper
    registry = get_registry()
    backend = registry.storage if registry else None
    if registry and registry.use_vectordb:
        persistence_mode = "vectordb"
    else:
        persistence_mode = registry.persistence_mode if registry else "file"
    initialize_health_service(backend, persistence_mode)
    initialize_broadcast_service(backend, persistence_mode)
    broadcast_service = get_broadcast_service()

    health_service = get_health_service()
    if health_service.enabled:
        from agent_registry.health.sweeper import HealthSweeper
        _health_sweeper = HealthSweeper(
            health_service, registry, broadcast_service.event_bus,
            interval=health_service.interval,
            failure_threshold=health_service.failure_threshold,
            grace_period=health_service.grace_period,
            sweep_interval=health_service.sweep_interval,
            offline_ttl=health_service.offline_ttl,
        )
        _health_sweeper.start()
    await broadcast_service.start()


async def shutdown_services():
    global _health_sweeper
    if _health_sweeper is not None:
        await _health_sweeper.stop()
        _health_sweeper = None
    await get_broadcast_service().stop()


def _initialize_registry_guarded():
    """Startup-event wrapper: render an actionable message if storage init fails.

    The synchronous pre-check in start.py normally catches this first; this
    guard covers runs that bypass start.py (e.g. uvicorn factory usage).
    """
    from agent_registry.config import PERSISTENCE_CONF, PERSISTENCE_MODE
    from agent_registry.persistence.precheck import format_storage_error
    try:
        initialize_registry()
    except Exception as exc:
        logger.error(format_storage_error(PERSISTENCE_MODE, PERSISTENCE_CONF, exc))
        raise


app.add_event_handler("startup", _initialize_registry_guarded)
app.add_event_handler("startup", startup_services)
app.add_event_handler("shutdown", close_registry)
app.add_event_handler("shutdown", shutdown_services)

# Include knowledge graph router
app.include_router(knowledge_graph_router)

# Add shutdown handler for Neo4j driver
@app.on_event("shutdown")
async def shutdown_neo4j():
    close_neo4j_driver()


# ---------- JWK Endpoint ----------
jwk_provider = JWKProvider(cert_path=config.get("jwk_cert_path", "cert.pem"))

jwk_rate_item = parse_rate_limit('jwk')


@app.get("/rest/v1/registry-center/keys")
async def get_jwks(request: Request):
    """
    Return public key in JWK Set format for JWT signature verification.
    This endpoint does not require authentication.
    """
    enable_https = config.get('enable_https', 'true').lower() == 'true'
    sign_enabled = config.get('registry.sign.enabled', 'false').lower() == 'true'

    if not enable_https or not sign_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWK endpoint is not available when HTTPS or registry signing is disabled"
        )

    if jwk_rate_item and not await async_hit(jwk_rate_item, request.client.host):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too Many Requests"
        )

    acquired = False
    try:
        jwk_semaphore.acquire_nowait()
        acquired = True
        jwk_set = jwk_provider.get_jwk_set()
        keys = [jwk._jwk_data for jwk in jwk_set]
        return JSONResponse(content={"keys": keys}, media_type="application/jwk-set+json")
    except CertLoadError as e:
        logger.error(f"Failed to load JWK: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to load JWK certificate"
        )
    except Exception as e:
        logger.error(f"Unexpected error in JWK endpoint: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
    finally:
        if acquired:
            jwk_semaphore.release()
