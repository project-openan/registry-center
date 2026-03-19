# agent_registry/server.py
from typing import List, Optional

from a2a.types import AgentCard
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette import status
from starlette.responses import Response

from agent_registry.config import (PERSISTENCE_FILE,
                                   MAX_REQUEST_BODY_SIZE,
                                   MAX_URL_LENGTH,
                                   MAX_REQUEST_RATE)
from agent_registry.core import RegistryCore
from agent_registry.model.validated_agentcard import ValidatedAgentCard

# --- Configuration & Setup ---
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Agent Registry Service",
    description="RESTful API for managing AI Agent cards with persistence and semantic search.",
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# --- Dependency Injection ---
def get_registry() -> RegistryCore:
    return RegistryCore(persistence_file=PERSISTENCE_FILE)


# --- Middleware ---
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Content Length Check
    if request.method in ("POST", "PUT"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
            return Response(content="Payload Too Large", status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    # URL Length Check (Optimized)
    if len(str(request.url.path) + str(request.query_params)) > MAX_URL_LENGTH:
        return Response(content="URI Too Long", status_code=status.HTTP_414_URI_TOO_LONG)

    return await call_next(request)


# --- Routes ---
@app.post("/rest/a2a-t/v1/agents/register", response_model=bool, summary="Register a new agent")
@limiter.limit(MAX_REQUEST_RATE)
async def register_agent(
        request: Request,
        agent: ValidatedAgentCard,
        registry: RegistryCore = Depends(get_registry)
):
    """
    Register a new agent. The combination (name, provider.organization) must be unique.
    Returns True if registered, False if duplicate.
    """
    try:
        success = await registry.register(agent)
        return success
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Unexpected error in register: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error") from e


@app.get("/rest/a2a-t/v1/agents/query", response_model=List[AgentCard], summary="Exact search")
async def list_agents_exact(
        name: Optional[str] = Query(None, description="Exact agent name"),
        organization: Optional[str] = Query(None, description="Exact organization"),
        registry: RegistryCore = Depends(get_registry)
):
    """
    Search agents by exact fields (AND combination). All parameters optional.
    If no parameters provided, returns all agents.
    """
    try:
        agents = registry.find_exact(name=name, organization=organization)
        return agents
    except Exception as e:
        logger.error(f"Error in exact search: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e
