# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
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
from functools import partial
from typing import Optional, Tuple, Any, Dict

import anyio
from a2a.types import AgentCard
from fastapi import FastAPI, HTTPException, Query, Request, Depends, status, Path
from fastapi.responses import JSONResponse
from google.protobuf.json_format import Parse, MessageToDict
from jwt import PyJWK
from loguru import logger
from limits import strategies, storage, parse_many

from starlette.responses import Response

from agent_registry.agent_registry.jwk_provider import JWKProvider, CertLoadError
from agent_registry.config import (
    MAX_REQUEST_BODY_SIZE,
    MAX_URL_LENGTH, CONN_TIMEOUT, CONN_MAX, FLOW_CTL_PARALLEL_REGISTER, FLOW_CTL_PARALLEL_QUERY, FLOW_CTL_REGISTER,
    FLOW_CTL_QUERY, AGENT_NUM_MAX, FLOW_CTL_PARALLEL_UPDATE, FLOW_CTL_PARALLEL_GET, FLOW_CTL_PARALLEL_RETRIEVE,
    FLOW_CTL_PARALLEL_DEREGISTER, FLOW_CTL_UPDATE, FLOW_CTL_GET, FLOW_CTL_RETRIEVE, FLOW_CTL_DEREGISTER,
    FLOW_CTL_JWK, FLOW_CTL_PARALLEL_JWK, OWNER_ISOLATION_ENABLED, OWNER_VALIDATION_MODE,
)
from agent_registry.core import RegistryCore
from agent_registry.model.validated_agentcard import validate_agent_card
from agent_registry.registry_instance import get_registry, initialize_registry
from agent_registry.middleware import ConnectionLimitMiddleware, TimeoutMiddleware

from common.custom.custom_handle import HandlerRegistry
from common.custom.interface_type import InterfaceType
from common.log.audit_logger import OperationResult, LogLevel, OperatorObject, OperationName
from common.util.config_util import get_conf
from common.cert.cert_cn_parser import validate_cn

# ---------- Rate Limiter Setup (In-Memory) ----------
# Use in-memory storage for single-node deployments. Counts reset on restart.
sync_storage = storage.MemoryStorage()
# Moving window strategy provides smoother rate limiting.
limiter = strategies.MovingWindowRateLimiter(sync_storage)

audit_handle = HandlerRegistry.get_handler(InterfaceType.AUDIT)


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
        # Check rate limit; if exceeded, raise 429.
        if not await async_hit(self.rate_item, identifier):
            raise  CustomHTTPException(status.HTTP_429_TOO_MANY_REQUESTS,"Too Many Requests")
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

config = get_conf()

app.add_middleware(
    ConnectionLimitMiddleware,
    max_connections=int(config.get(CONN_MAX, 11))
)

app.add_middleware(
    TimeoutMiddleware,
    timeout_seconds=int(config.get(CONN_TIMEOUT, 30))
)

register_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_REGISTER, 50)))
query_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_QUERY, 100)))
update_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_UPDATE, 100)))
get_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_GET, 100)))
retrieve_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_RETRIEVE, 100)))
deregister_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_DEREGISTER, 50)))
jwk_semaphore = anyio.Semaphore(int(config.get(FLOW_CTL_PARALLEL_JWK, 1)))

class CustomHTTPException(HTTPException):
    def __init__(self, status_code: int, error_message: str):
        super().__init__(status_code=status_code, detail=error_message)
        self.error_message = error_message

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "errors": {
                "error": [
                    {
                        "errorMessage": exc.detail
                    }
                ]
            }
        }
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
    if request.method in ("POST", "PUT"):
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
    if len(registry.get_agents()) >= int(config.get(AGENT_NUM_MAX, 40)):
        details["message"] = "Agent registration limit exceeded."
        await audit_handle.handle({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise CustomHTTPException(status.HTTP_409_CONFLICT,"Agent registration limit exceeded.",)


async def _check_duplicate_agent(agent: AgentCard, registry: RegistryCore, client_ip: str,
                                 details: dict) -> None:
    """Check if an agent with same (name, organization) already exists, log and raise if found."""
    key = _make_agent_key(agent.name, agent.provider.organization)
    if key in registry.get_agents():
        details["message"] = "Registration skipped: duplicate agent."
        await audit_handle.handle({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise CustomHTTPException(status.HTTP_409_CONFLICT,
                                  f"Registration skipped: duplicate agent ({agent.name}, {agent.provider.organization})",
                                  )


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
        await audit_handle.handle({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise CustomHTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except Exception as e:
        await audit_handle.handle({
            "operation_name": OperationName.REGISTER_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        logger.error(f"Unexpected error in register: {e}")
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
        await audit_handle.handle({
            "operation_name": OperationName.UPDATE_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.SUCCESS,
            "object_name": OperatorObject.AGENT,
            "details": data,
            "client_ip": client_ip
        })
        return success
    except ValueError as e:
        details["message"] = str(e)
        await audit_handle.handle({
            "operation_name": OperationName.UPDATE_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        raise CustomHTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except Exception as e:
        await audit_handle.handle({
            "operation_name": OperationName.UPDATE_AGENT,
            "level": LogLevel.MINOR,
            "result": OperationResult.FAILURE,
            "object_name": OperatorObject.AGENT,
            "details": details,
            "client_ip": client_ip
        })
        logger.error(f"Unexpected error in update: {e}")
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
):
    """
    Register a new agent.
    The combination (name, provider.organization) must be unique.
    Returns True if registered, False if duplicate.
    """
    body = await request.json()
    agent_cards = body.get("agentCards", [])
    client_ip = request.client.host

    owner = None
    if OWNER_ISOLATION_ENABLED:
        owner = _get_owner_from_request(request)

    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)
    acquired = False
    try:
        register_semaphore.acquire_nowait()
        acquired = True
        for agent_card in agent_cards:
            agent = Parse(json.dumps(agent_card), AgentCard())
            logger.info(
                f"Register agent request: name={agent.name}, org={agent.provider.organization}, client={client_ip}, owner={owner}")
            details = {
                "agentName": agent.name,
                "organization": agent.provider.organization,
                "url": agent.provider.url,
            }
            await _check_agent_limit(registry, client_ip, details)
            await _check_duplicate_agent(agent, registry, client_ip, details)
            try:
                validate_agent_card(agent)
            except HTTPException as e:
                logger.error(f"Agent card validation failed: {agent.name}, {agent.provider.organization}")
                raise CustomHTTPException(e.status_code, e.detail)
            logger.info(f"Register agent success: name={agent.name}, org={agent.provider.organization}")

            approval_enabled = config.get('agent_approval_enabled', 'false')
            if approval_enabled == 'true':
                initial_status = 'registered'
                status_message = "Agent registered, waiting for approval"
            else:
                initial_status = 'published'
                status_message = "Agent registered and published"

            result = await _perform_registration(agent, client_ip, details, initial_status=initial_status, owner=owner)
            await audit_handle.handle({
                "operation_name": OperationName.REGISTER_AGENT,
                "level": LogLevel.MINOR,
                "result": OperationResult.SUCCESS if result else OperationResult.FAILURE,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": client_ip
            })

        return Response(status_code=status.HTTP_201_CREATED)
    except anyio.WouldBlock as e:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy") from e
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in registry:{e}")
        raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error") from e
    finally:
        if acquired:
            register_semaphore.release()


@app.get(
    "/rest/v1/registry-center/agent-cards",
    response_model=None,
    summary="Exact search",
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
    acquired = False
    try:
        query_semaphore.acquire_nowait()
        acquired = True
        try:
            query_handle = HandlerRegistry.get_handler(InterfaceType.QUERY)
            agents = await query_handle.handle(name, organization)

            published_agents = []
            for agent in agents:
                agent_status = registry.get_status(agent.name, agent.provider.organization)
                if agent_status != 'published':
                    continue
                agent_dict = MessageToDict(agent)
                published_agents.append(agent_dict)
            logger.info(f"Query agents result: {len(published_agents)} agents found")
            return {"agentCards": published_agents}
        except Exception as e:
            logger.error(f"Error in exact search: {e}")
            raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,"Internal server error") from e
    except anyio.WouldBlock as e:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy") from e
    finally:
        if acquired:
            query_semaphore.release()


@app.put("/rest/v1/registry-center/agent-cards/{organization}/{name}", response_model=bool, summary="Full update(replace) an agent")
async def update_agent(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Path(..., description="Agent organization"),
        registry: RegistryCore = Depends(get_registry), _: Any = Depends(RateLimiter('update'))
):
    """
    Fully replace an existing agent. The name and organization in the body must match the path/query.
    Returns True if updated, False if not found.
    """
    body_json = await request.json()
    agent_cards = body_json.get("agentCards", [])
    client_ip = request.client.host

    owner = None
    if OWNER_ISOLATION_ENABLED:
        owner = await _verify_owner_permission(request, name, organization, registry)

    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)
    acquired = False
    try:
        # Convert to dict for update
        update_semaphore.acquire_nowait()
        acquired = True
        for agent_card in agent_cards:
            agent_data = Parse(json.dumps(agent_card), AgentCard())
            logger.info(f"Update agent request: name={name}, org={organization}, client={client_ip}, owner={owner}")
            details = {
                "agentName": agent_data.name,
                "organization": agent_data.provider.organization,
                "url": agent_data.provider.url,
            }
            try:
                validate_agent_card(agent_data)
            except HTTPException as e:
                logger.error(f"Agent card validation failed: {agent_data.name}, {agent_data.provider.organization}")
                raise CustomHTTPException(e.status_code, e.detail)
            await _check_agent_limit(registry, client_ip, details)

            data = MessageToDict(agent_data, preserving_proto_field_name=True)
            success = await _perform_update(client_ip, name, organization, data, details, owner=owner)
            if not success:
                raise CustomHTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
            logger.info(f"Update agent success: name={name}, org={organization}")
        return Response(status_code=status.HTTP_200_OK)
    except ValueError as e:
        raise CustomHTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in full update:{e}")
        raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal server error") from e
    finally:
        if acquired:
            update_semaphore.release()


@app.delete("/rest/v1/registry-center/agent-cards/{organization}/{name}", response_model=bool, summary="Deregister an agent")
async def deregister_agent(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Path(..., description="Agent organization"),
        registry: RegistryCore = Depends(get_registry),
        _: Any = Depends(RateLimiter('deregister'))
):
    """
    Remove an agent from the registry.
    Returns True if deleted, False if not found.
    """
    client_ip = request.client.host

    owner = None
    if OWNER_ISOLATION_ENABLED:
        owner = await _verify_owner_permission(request, name, organization, registry)

    logger.info(f"Deregister agent request: name={name}, org={organization}, client={client_ip}, owner={owner}")
    authenticate_handle = HandlerRegistry.get_handler(InterfaceType.AUTHENTICATE)
    await authenticate_handle.handle(client_ip, request)
    acquired = False
    details = {
        "agentName": name,
        "organization": organization,
    }
    try:
        deregister_semaphore.acquire_nowait()
        acquired = True
        try:
            deregister_handle = HandlerRegistry.get_handler(InterfaceType.DEREGISTER)
            success = await deregister_handle.handle(name, organization, owner=owner)
            if not success:
                await audit_handle.handle({
                    "operation_name": OperationName.DEREGISTER_AGENT,
                    "level": LogLevel.MINOR,
                    "result": OperationResult.FAILURE,
                    "object_name": OperatorObject.AGENT,
                    "details": details,
                    "client_ip": client_ip
                })
                raise CustomHTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
            await audit_handle.handle({
                "operation_name": OperationName.DEREGISTER_AGENT,
                "level": LogLevel.MINOR,
                "result": OperationResult.SUCCESS,
                "object_name": OperatorObject.AGENT,
                "details": details,
                "client_ip": client_ip
            })
            logger.info(f"Deregister agent success: name={name}, org={organization}")
            return Response(status_code=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error in deregister: {e}")
            raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,"Internal server error") from e

    except anyio.WouldBlock as e:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy") from e
    finally:
        if acquired:
            deregister_semaphore.release()


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
    acquired = False
    try:
        retrieve_semaphore.acquire_nowait()
        acquired = True
        try:
            retrieve_handle = HandlerRegistry.get_handler(InterfaceType.RETRIEVE)
            agents = await retrieve_handle.handle(task, top_n)
            result = [MessageToDict(agent) for agent in agents]
            logger.info(f"Retrieve agents result: {len(result)} agents found for task='{task}'")
            return {"agentCards": result}
        except Exception as e:
            logger.error(f"Error in retrieve: {e}")
            raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,"Internal server error") from e
    except anyio.WouldBlock as e:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy") from e
    finally:
        if acquired:
            retrieve_semaphore.release()


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
    acquired = False
    try:
        get_semaphore.acquire_nowait()
        acquired = True
        try:
            get_handle = HandlerRegistry.get_handler(InterfaceType.GET)
            record = await get_handle.handle(name, organization)

            if record is None:
                return {"agentCards": []}

            agent_status = registry.get_status(name, organization)
            if agent_status != 'published':
                return {"agentCards": []}

            agent_dict = MessageToDict(record.agent_card)
            logger.info(f"Get agent result: {'found' if agent_dict else 'not found'} for name={name}, org={organization}")
            return {"agentCards": [agent_dict]}
        except Exception as e:
            logger.error(f"Error in get agent: {e}")
            raise CustomHTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,"Internal server error") from e
    except anyio.WouldBlock as e:
        raise CustomHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Server is busy") from e
    finally:
        if acquired:
            get_semaphore.release()


def close_registry():
    registry = get_registry()
    registry.close()


app.add_event_handler("startup", initialize_registry)
app.add_event_handler("shutdown", close_registry)


def _make_agent_key(name: str, organization: str) -> Tuple[str, str]:
    """Create a normalized key for indexing."""
    return name.strip(), organization.strip()


# ---------- JWK Endpoint ----------
jwk_provider = JWKProvider(cert_path=config.get("JWK_CERT_PATH", "cert.pem"))
jwk_kid = config.get("JWK_KID", None)

jwk_rate_item = parse_rate_limit('jwk')


@app.get("/.well-known/jwks.json")
async def get_jwks(request: Request):
    """
    Download public key in PEM format for JWT signature verification.
    This endpoint does not require authentication.
    """
    if jwk_rate_item and not await async_hit(jwk_rate_item, request.client.host):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too Many Requests"
        )

    acquired = False
    try:
        jwk_semaphore.acquire_nowait()
        acquired = True
        public_key_pem = jwk_provider.get_public_key_pem()
        return Response(
            content=public_key_pem,
            media_type="application/x-pem-file",
            headers={
                "Content-Disposition": "attachment; filename=public_key.pem"
            }
        )
    except CertLoadError as e:
        logger.error(f"Failed to load JWK: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
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


def _enhance_jwk(jwk: PyJWK) -> Dict[str, Any]:
    """Enhance JWK with kid and key_ops fields."""
    jwk_dict = jwk._jwk_data.copy()
    if jwk_kid:
        jwk_dict["kid"] = jwk_kid
    jwk_dict["key_ops"] = ["verify"]
    return jwk_dict