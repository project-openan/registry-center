# agent_registry/server.py
from typing import List

from a2a.types import AgentCard
from fastapi import FastAPI, HTTPException, Query, Path, Body, Request
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import Response

from agent_registry.config import DEFAULT_LLM_TYPE, PERSISTENCE_FILE
from agent_registry.core import RegistryCore

_REQUEST_BODY_SIZE_LIMIT = 1024 * 1024  # 10MB default limit
_QUERY_URL_LENGTH_LIMIT = 1024  # 1KB default limit
_REQUEST_RATE_LIMIT = "10/minute"  # 默认的速率限制

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="Agent Registry Service",
    description="RESTful API for managing AI Agent cards with persistence and semantic search.",
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Global registry instance (singleton)
registry = RegistryCore(llm_type=DEFAULT_LLM_TYPE, persistence_file=PERSISTENCE_FILE)


@app.middleware("http")
async def limit_content_length(request: Request, call_next):
    if request.method in ("POST", "PUT"):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _REQUEST_BODY_SIZE_LIMIT:
            return Response(
                content="Request body exceeds size limit",
                status_code=413
            )
    response = await call_next(request)
    return response


@app.middleware("http")
async def limit_url_length(request: Request, call_next):
    # 获取完整 URL 字符串（包含 scheme、host、path、query 等）
    url_str = str(request.url)
    if len(url_str.encode('utf-8')) > _QUERY_URL_LENGTH_LIMIT:
        return Response(
            content="URL too long",
            status_code=414  # HTTP 414 URI Too Long
        )
    response = await call_next(request)
    return response


@app.post("/rest/a2a-t/v1/agent-register", response_model=bool, summary="Register a new agent")
@limiter.limit(_REQUEST_RATE_LIMIT)
async def register_agent(request: Request, agent: AgentCard):
    """
    Register a new agent. The combination (name, provider.organization) must be unique.
    Returns True if registered, False if duplicate.
    """
    try:
        success = registry.register(agent)
        return success
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Unexpected error in register: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.put("/rest/a2a-t/v1/update_agent/{name}", response_model=bool, summary="Full update (replace) an agent")
@limiter.limit(_REQUEST_RATE_LIMIT)
async def update_agent_full(
        request: Request,
        name: str = Path(..., description="Agent name"),
        organization: str = Query(..., description="Agent organization"),
        agent_data: AgentCard = Body(..., description="Full agent data")
):
    """
    Fully replace an existing agent. The name and organization in the body must match the path/query.
    Returns True if updated, False if agent not found.
    """
    try:
        # Convert to dict for update
        data = agent_data.model_dump()
        success = registry.update(name, organization, data, partial=False)
        if not success:
            raise HTTPException(status_code=404, detail="Agent not found")
        return success
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException as e:
        # 捕获已经定义的 HTTPException，避免被 except Exception 捕获
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in full update: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.delete("/rest/a2a-t/v1/deregister_agent/{name}", response_model=bool, summary="Deregister an agent")
async def deregister_agent(
        name: str = Path(..., description="Agent name"),
        organization: str = Query(..., description="Agent organization")
):
    """
    Remove an agent from the registry.
    Returns True if deleted, False if not found.
    """
    try:
        success = registry.deregister(name, organization)
        if not success:
            raise HTTPException(status_code=404, detail="Agent not found")
        return success
    except Exception as e:
        logger.error(f"Unexpected error in deregister: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.get("/rest/a2a-t/v1/agents/search", response_model=List[AgentCard], summary="Fuzzy search by task")
async def search_agents_by_task(
        task: str = Query(..., description="Natural language task description")
):
    """
    Find agents that are semantically relevant to the given task using LLM.
    """
    try:
        agents = registry.find_by_task(task)
        return agents
    except Exception as e:
        logger.error(f"Error in fuzzy search: {e}")
        raise HTTPException(status_code=500, detail="Internal server error") from e


@app.get("/rest/a2a-t/v1/health", summary="Health check")
async def health_check():
    return {"status": "ok"}
