"""A small MCP client over Streamable HTTP.

MCP is JSON-RPC 2.0. Over HTTP each message is a POST to one URL; the
server answers with plain JSON, or with a short event stream (SSE)
whose `data:` lines carry the same JSON. A session starts with
`initialize`, the server may hand back an `Mcp-Session-Id` header that
every later request repeats, and then the client sends
`notifications/initialized`.

Only the two methods this platform needs are implemented:
`tools/list` (what can you do?) and `tools/call` (do it).

Written against httpx rather than an SDK for the same reasons as the
LLM adapters: one error surface, no extra dependency, easy to fake in
tests. Redirects are not followed, so a server cannot bounce a request
to an internal address after its URL passed the safety check.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "ai-employee-platform", "version": "1.0"}
TIMEOUT_S = 30.0
# A tool result is read by a model, not a person. Anything bigger is
# almost certainly a mistake on the server and would blow the context.
MAX_RESPONSE_BYTES = 2_000_000


class McpError(Exception):
    """A failure worth saying out loud. `error_class` is stable for code;
    the message is a sentence a person, or a model, can act on."""

    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def transport() -> httpx.AsyncBaseTransport | None:
    """The HTTP transport. None means the real network; tests swap in a fake."""
    return None


class McpClient:
    def __init__(self, url: str, *, token: str | None = None) -> None:
        self.url = url
        self.token = token
        self._ids = itertools.count(1)
        self._session_id: str | None = None
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> McpClient:
        self._http = httpx.AsyncClient(
            timeout=TIMEOUT_S, follow_redirects=False, transport=transport()
        )
        await self._initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._http is not None:
            if self._session_id:
                # Polite, not required: tell the server it can forget us.
                try:
                    await self._http.delete(self.url, headers=self._headers())
                except httpx.HTTPError:
                    pass
            await self._http.aclose()

    # --- the two things we ask for ---------------------------------

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(20):  # a sane cap on pages
            result = await self._request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._request("tools/call", {"name": name, "arguments": arguments})

    # --- protocol plumbing ----------------------------------------

    async def _initialize(self) -> None:
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        if "tools" not in (result.get("capabilities") or {}):
            raise McpError("no_tools", "This server works, but does not offer any tools.")
        await self._notify("notifications/initialized")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _notify(self, method: str) -> None:
        assert self._http is not None
        try:
            await self._http.post(
                self.url, json={"jsonrpc": "2.0", "method": method}, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise McpError("unreachable", f"Could not reach the tool server: {exc}") from exc

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self._http is not None
        request_id = next(self._ids)
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}

        try:
            response = await self._http.post(self.url, json=body, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise McpError(
                "timeout", f"The tool server did not answer within {TIMEOUT_S:.0f}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise McpError("unreachable", f"Could not reach the tool server: {exc}") from exc

        _raise_for_status(response)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise McpError("too_large", "The tool server sent back far too much data.")

        if session_id := response.headers.get("mcp-session-id"):
            self._session_id = session_id

        message = _find_reply(response, request_id)
        if "error" in message:
            error = message["error"] or {}
            raise McpError(
                "server_error", f"The tool server said: {error.get('message', 'unknown error')}"
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise McpError("bad_reply", "The tool server's answer was not in the expected format.")
        return result


def _raise_for_status(response: httpx.Response) -> None:
    code = response.status_code
    if code < 300:
        return
    if 300 <= code < 400:
        raise McpError("redirected", "The tool server tried to redirect us. Use its final address.")
    if code in (401, 403):
        raise McpError(
            "auth_failed",
            "The tool server refused the access token. Update it under Connections.",
        )
    if code == 404:
        raise McpError("not_found", "Nothing answered at that address. Check the server's MCP URL.")
    if code == 429:
        raise McpError(
            "rate_limited", "The tool server is rate limiting requests. Try again later."
        )
    raise McpError("server_error", f"The tool server answered {code}: {response.text[:200]}")


def _find_reply(response: httpx.Response, request_id: int) -> dict[str, Any]:
    """The JSON-RPC reply to our request, from JSON or an event stream."""
    content_type = response.headers.get("content-type", "")
    try:
        if "text/event-stream" in content_type:
            # Each event's data lines join into one JSON message. The
            # server may send notifications first; we want our reply.
            for event in response.text.replace("\r\n", "\n").split("\n\n"):
                data = "\n".join(
                    line[5:].lstrip() for line in event.split("\n") if line.startswith("data:")
                )
                if not data:
                    continue
                message = json.loads(data)
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
            raise McpError(
                "bad_reply", "The tool server's event stream had no answer to our request."
            )

        message = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise McpError("bad_reply", "The tool server's answer was not valid JSON.") from exc

    if isinstance(message, list):  # a batch: pick ours
        message = next(
            (m for m in message if isinstance(m, dict) and m.get("id") == request_id), {}
        )
    if not isinstance(message, dict):
        raise McpError("bad_reply", "The tool server's answer was not in the expected format.")
    return message
