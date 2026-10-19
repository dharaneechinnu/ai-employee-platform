"""A pretend MCP server, served through httpx's mock transport.

Speaks just enough Streamable HTTP for the client: initialize, the
initialized notification, tools/list, tools/call and session ids. Can
answer as plain JSON or as an event stream, and can demand a token.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_customer",
        "title": "Find a customer",
        "description": "Look up a customer by name or email.",
        "inputSchema": {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "update_deal_stage",
        "description": "Move a deal to another stage.",
        "inputSchema": {
            "type": "object",
            "properties": {"deal_id": {"type": "string"}, "stage": {"type": "string"}},
        },
    },
    {
        "name": "delete_contact",
        "description": "Delete a contact for good.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
        "annotations": {"destructiveHint": True},
    },
]


class FakeMcpServer:
    def __init__(self, *, sse: bool = False, token: str | None = None) -> None:
        self.sse = sse
        self.token = token
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.session_headers: list[str | None] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.token and request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        if request.method == "DELETE":
            return httpx.Response(200)

        body = json.loads(request.content)
        method = body.get("method")
        if "id" not in body:  # a notification
            return httpx.Response(202)

        self.session_headers.append(request.headers.get("mcp-session-id"))
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-crm", "version": "1"},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = body["params"]["name"]
            args = body["params"].get("arguments") or {}
            self.calls.append((name, args))
            if name == "find_customer":
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": f"Asha Rao, asha@example.com, matched '{args.get('query')}'",
                        }
                    ]
                }
            elif name == "delete_contact":
                result = {
                    "content": [{"type": "text", "text": "Contact is protected."}],
                    "isError": True,
                }
            else:
                result = {"content": [{"type": "text", "text": "Deal moved."}]}
        else:
            return self._reply(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": {"code": -32601, "message": "no such method"},
                }
            )

        return self._reply(
            {"jsonrpc": "2.0", "id": body["id"], "result": result}, init=method == "initialize"
        )

    def _reply(self, message: dict[str, Any], *, init: bool = False) -> httpx.Response:
        headers = {"mcp-session-id": "sess-123"} if init else {}
        if self.sse:
            # A progress notification first, as real servers send, then the reply.
            progress = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
            text = (
                f"event: message\ndata: {json.dumps(progress)}\n\n"
                f"event: message\ndata: {json.dumps(message)}\n\n"
            )
            return httpx.Response(
                200, text=text, headers={**headers, "content-type": "text/event-stream"}
            )
        return httpx.Response(200, json=message, headers=headers)
