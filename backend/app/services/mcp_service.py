"""MCP tool servers: connect one, and its tools appear.

Adding a server is one form: a name, the server's MCP address, and an
access token if it needs one. We connect straight away and ask what it
can do (`tools/list`); a server that does not answer is not saved, so
the list never fills with broken entries.

The token is handled like every other secret: encrypted with the
company's key, never returned, and handed to a tool only at call time.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.mcp.client import McpClient, McpError
from app.agent.mcp.tools import build_tools, connection_kind, describe
from app.agent.tools.base import Grant, Tool
from app.core.crypto import decrypt, encrypt
from app.core.errors import NotFoundError, ValidationError
from app.core.observability import get_logger
from app.core.urls import check_service_url
from app.db.models.mcp import McpServer

log = get_logger(__name__)

MAX_SERVERS = 20
MAX_TOOLS_PER_SERVER = 100
STATUS_CONNECTED = "connected"
STATUS_FAILED = "failed"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24].strip("-")
    return slug or "server"


class McpService:
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        self.session = session
        self.owner_id = owner_id

    async def servers(self) -> list[McpServer]:
        result = await self.session.scalars(
            select(McpServer).where(McpServer.owner_id == self.owner_id).order_by(McpServer.name)
        )
        return list(result.all())

    async def get(self, server_id: uuid.UUID) -> McpServer:
        server = await self.session.scalar(
            select(McpServer).where(McpServer.id == server_id, McpServer.owner_id == self.owner_id)
        )
        if server is None:
            raise NotFoundError("That tool server is not connected.")
        return server

    async def add(self, *, name: str, url: str, token: str | None) -> McpServer:
        name = name.strip()
        if not name:
            raise ValidationError("Give the server a name, like CRM or Support desk.")
        url = check_service_url(url, what="tool server")
        token = (token or "").strip() or None

        existing = await self.servers()
        if len(existing) >= MAX_SERVERS:
            raise ValidationError(f"A company can connect up to {MAX_SERVERS} tool servers.")

        taken = {s.slug for s in existing}
        base = slugify(name)
        slug, n = base, 2
        while slug in taken:
            slug, n = f"{base[:21]}-{n}", n + 1

        # Connect before saving: an address that does not answer is
        # reported now, and nothing broken is stored.
        tools = await self._discover(url, token)

        server = McpServer(
            owner_id=self.owner_id,
            name=name[:100],
            slug=slug,
            url=url,
            token_enc=encrypt(token, scope=self.owner_id) if token else None,
            token_last4=token[-4:] if token and len(token) >= 4 else None,
            tools=tools,
            status=STATUS_CONNECTED,
            last_synced_at=datetime.now(UTC),
        )
        self.session.add(server)
        await self.session.flush()
        log.info("mcp_server_added", owner_id=str(self.owner_id), slug=slug, tools=len(tools))
        return server

    async def sync(self, server_id: uuid.UUID) -> McpServer:
        """Ask the server again what it offers. Tools it dropped stop
        appearing; new ones arrive switched off for every employee."""
        server = await self.get(server_id)
        try:
            server.tools = await self._discover(server.url, self._token(server))
        except ValidationError as exc:
            server.status = STATUS_FAILED
            server.last_error = str(exc)
        else:
            server.status = STATUS_CONNECTED
            server.last_error = None
        server.last_synced_at = datetime.now(UTC)
        return server

    async def remove(self, server_id: uuid.UUID) -> None:
        await self.session.delete(await self.get(server_id))

    async def _discover(self, url: str, token: str | None) -> list[dict[str, object]]:
        try:
            async with McpClient(url, token=token) as client:
                raw = await client.list_tools()
        except McpError as exc:
            raise ValidationError(exc.message) from exc
        tools = [t for t in (describe(r) for r in raw if isinstance(r, dict)) if t is not None]
        if not tools:
            raise ValidationError("This server works, but does not offer any tools.")
        return tools[:MAX_TOOLS_PER_SERVER]

    def _token(self, server: McpServer) -> str | None:
        return decrypt(server.token_enc, scope=self.owner_id) if server.token_enc else None

    # --- what a run sees ------------------------------------------

    async def tools(self) -> dict[str, type[Tool]]:
        """This company's MCP tools, by name. From the cached list, so no
        network call: a server that is down fails one tool call, not the
        whole run or the settings screens."""
        found: dict[str, type[Tool]] = {}
        for server in await self.servers():
            for tool in build_tools(server.slug, server.name, server.tools or []):
                found[tool.name] = tool
        return found

    async def grants(self) -> dict[str, Grant]:
        """Where each server lives and its token, for the worker only."""
        return {
            connection_kind(server.slug): Grant(
                credential=self._token(server) or "", config={"url": server.url}
            )
            for server in await self.servers()
        }
