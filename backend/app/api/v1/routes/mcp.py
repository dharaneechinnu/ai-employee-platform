"""MCP tool server routes.

Like every other secret, a server's access token can be written and
replaced but never read back: the list shows its last four characters.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.agent.mcp.tools import tool_name
from app.api.v1.deps import ContextDep, SessionDep
from app.db.models.mcp import McpServer
from app.services.mcp_service import McpService

router = APIRouter(prefix="/me", tags=["mcp"])



class AddServerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=500)
    token: str | None = Field(default=None, max_length=2000)


class ServerTool(BaseModel):
    name: str  # what an employee's tool list stores
    remote_name: str  # what the server calls it
    title: str | None
    description: str
    side_effect: str


class ServerResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    url: str
    token_last4: str | None
    status: str
    last_error: str | None
    last_synced_at: datetime | None
    tools: list[ServerTool]


def _response(server: McpServer) -> ServerResponse:
    tools: list[dict[str, Any]] = server.tools or []
    return ServerResponse(
        id=server.id,
        name=server.name,
        slug=server.slug,
        url=server.url,
        token_last4=server.token_last4,
        status=server.status,
        last_error=server.last_error,
        last_synced_at=server.last_synced_at,
        tools=[
            ServerTool(
                name=tool_name(server.slug, t["name"]),
                remote_name=t["name"],
                title=t.get("title"),
                description=t.get("description") or "",
                side_effect=t.get("effect", "write"),
            )
            for t in tools
        ],
    )


@router.get("/mcp-servers", response_model=list[ServerResponse], summary="Connected tool servers")
async def list_servers(ctx: ContextDep, session: SessionDep) -> list[ServerResponse]:
    return [_response(s) for s in await McpService(session, ctx.owner_id).servers()]


@router.post(
    "/mcp-servers",
    response_model=ServerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect an MCP tool server",
)
async def add_server(
    body: AddServerRequest,
    ctx: ContextDep,
    session: SessionDep,
) -> ServerResponse:
    server = await McpService(session, ctx.owner_id).add(
        name=body.name, url=body.url, token=body.token
    )
    return _response(server)


@router.post(
    "/mcp-servers/{server_id}/sync",
    response_model=ServerResponse,
    summary="Ask the server again which tools it offers",
)
async def sync_server(server_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> ServerResponse:
    return _response(await McpService(session, ctx.owner_id).sync(server_id))


@router.delete(
    "/mcp-servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Disconnect"
)
async def remove_server(server_id: uuid.UUID, ctx: ContextDep, session: SessionDep) -> None:
    await McpService(session, ctx.owner_id).remove(server_id)
