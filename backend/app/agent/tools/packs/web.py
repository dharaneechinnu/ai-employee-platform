"""Web tools. Phase 3's starter pack: read-only, so nothing can break.

`get_webpage` is restricted by an allowlist. Without one, a prompt
injection could point it at an internal address and use the agent as a
proxy into the private network — the classic SSRF shape.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.packs._http import html_to_text
from app.agent.tools.registry import register
from app.core.urls import is_private_address as _is_private_address

MAX_CHARS = 6_000


class GetWebpageArgs(BaseModel):
    url: str = Field(description="The full URL to read, including https://")


@register
class GetWebpage(Tool):
    name = "get_webpage"
    pack = "web"
    description = (
        "Fetch a web page and return its text. Use this to read documentation "
        "or any public page. Only addresses on the allowed list can be read."
    )
    args_model = GetWebpageArgs
    side_effect = SideEffect.READ
    timeout_s = 20.0

    async def run(self, ctx: ToolContext, args: GetWebpageArgs) -> ToolResult:  # type: ignore[override]
        parsed = urlparse(args.url)

        if parsed.scheme not in ("http", "https"):
            return ToolResult.failure("invalid_url", "Only http and https URLs can be read.")
        if not parsed.hostname:
            return ToolResult.failure("invalid_url", "That URL has no hostname.")

        allowed: list[str] = (ctx.config or {}).get("allowed_domains", [])
        if allowed and not any(
            parsed.hostname == d or parsed.hostname.endswith(f".{d}") for d in allowed
        ):
            return ToolResult.failure(
                "not_allowed",
                f"{parsed.hostname} is not on the allowed list. Ask an admin to add it.",
            )

        if _is_private_address(parsed.hostname):
            return ToolResult.failure(
                "not_allowed", "Internal and private addresses cannot be read."
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=True) as client:
                response = await client.get(args.url, headers={"User-Agent": "AgentPlatform/0.1"})
        except httpx.TimeoutException:
            return ToolResult.failure("timeout", f"{args.url} did not respond in time.")
        except httpx.HTTPError as exc:
            return ToolResult.failure("unreachable", f"Could not fetch that page: {exc}")

        if not response.is_success:
            return ToolResult.failure(
                "http_error", f"That page returned status {response.status_code}."
            )

        text = response.text
        if "html" in response.headers.get("content-type", "").lower():
            # Readable text, not markup: small models spend their whole
            # context on tags otherwise.
            text = html_to_text(text)
        text = text[:MAX_CHARS]
        return ToolResult.success(
            {"url": str(response.url), "status": response.status_code, "content": text}
        )
