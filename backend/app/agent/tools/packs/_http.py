"""Shared plumbing for tools that call a REST API with an OAuth token.

Every failure becomes a sentence the model can act on. A 401 means the
person must reconnect, which the model cannot fix, so it says so; a
404 means the id was wrong, which it can.
"""

from __future__ import annotations

import asyncio
import base64
import html
import io
import re
from abc import abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel

from app.agent.tools.base import Tool, ToolContext, ToolResult

HTTP_TIMEOUT_S = 20.0
MAX_TEXT_CHARS = 15_000
# A PDF bigger than this, or longer than this many pages, is read in part.
MAX_PDF_BYTES = 20_000_000
MAX_PDF_PAGES = 60


class ApiError(Exception):
    def __init__(self, error_class: str, message: str) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message


def _client() -> httpx.AsyncClient:
    """Built in one place so tests can swap in a fake transport."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True)


async def request(
    ctx: ToolContext,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
    raw: bool = False,
) -> Any:
    """Make one authenticated request. Returns parsed JSON, or bytes
    when `raw` is set. Raises ApiError with a readable message."""
    if not ctx.credential:
        raise ApiError("not_connected", "No connected account is available for this tool.")

    async with _client() as http:
        resp = await http.request(
            method,
            url,
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {ctx.credential}", **(headers or {})},
        )

    if resp.status_code == 401:
        raise ApiError(
            "auth_expired",
            "The connected account's access has expired or was revoked. "
            "Tell the user to reconnect it under Settings > Connections.",
        )
    if resp.status_code == 403:
        raise ApiError(
            "forbidden",
            "The connected account does not have permission for this. "
            "It may need reconnecting with the requested permissions.",
        )
    if resp.status_code == 404:
        raise ApiError("not_found", "Nothing was found with that id.")
    if resp.status_code == 429:
        raise ApiError("rate_limited", "The provider is rate limiting requests. Try again later.")
    if resp.status_code >= 400:
        detail = resp.text[:300]
        raise ApiError("api_error", f"The provider answered {resp.status_code}: {detail}")

    if raw:
        return resp.content
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


class ApiTool(Tool):
    """A tool whose work is one or more API calls.

    Subclasses implement `call`; this turns any ApiError or network
    failure into a ToolResult, so a flaky provider costs one step, not
    the run.
    """

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult:
        try:
            return await self.call(ctx, args)
        except ApiError as exc:
            return ToolResult.failure(exc.error_class, exc.message)
        except httpx.HTTPError as exc:
            return ToolResult.failure("network_error", f"Could not reach the provider: {exc}")

    @abstractmethod
    async def call(self, ctx: ToolContext, args: Any) -> ToolResult: ...


def b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def html_to_text(markup: str) -> str:
    """Good enough for an email body: drop tags, keep line breaks."""
    markup = re.sub(r"(?is)<(script|style).*?</\1>", "", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", markup)
    text = html.unescape(re.sub(r"<[^>]+>", "", markup))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clip(text: str, limit: int = MAX_TEXT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[... cut at {limit} characters]"


def is_pdf(content: bytes, mime: str = "", name: str = "") -> bool:
    return "pdf" in mime.lower() or name.lower().endswith(".pdf") or content[:5] == b"%PDF-"


def _pdf_text_sync(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("it is protected with a password")
        total = len(reader.pages)
        pages = [(page.extract_text() or "").strip() for page in list(reader.pages)[:MAX_PDF_PAGES]]
    except (PdfReadError, OSError, KeyError, TypeError) as exc:
        raise ValueError("it is damaged or not really a PDF") from exc
    text = "\n\n".join(f"[page {i}]\n{t}" for i, t in enumerate(pages, 1) if t)
    if not text:
        raise ValueError("it has no text layer (it may be a scanned image)")
    if total > MAX_PDF_PAGES:
        text += f"\n\n[... only the first {MAX_PDF_PAGES} of {total} pages were read]"
    return text


async def pdf_text(data: bytes) -> str:
    """The text of a PDF, page by page. Parsing is slow, so it runs off
    the event loop. Raises ValueError with the reason it cannot be read."""
    if len(data) > MAX_PDF_BYTES:
        raise ValueError(f"it is larger than {MAX_PDF_BYTES // 1_000_000} MB")
    return await asyncio.to_thread(_pdf_text_sync, data)
