"""Team chat: post a message to a Slack or Microsoft Teams channel.

Each connection is one channel's incoming webhook, pasted in by the
person. The webhook URL is the secret: it is stored encrypted like any
other credential and only ever reaches the request that posts.

Posting is destructive: a webhook message cannot be edited or taken
back, and the whole channel sees it. So, like sending an email, it asks
the person first unless they say otherwise.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

HTTP_TIMEOUT_S = 15.0
SLACK_PREFIX = "https://hooks.slack.com/"
# Teams channel webhooks: the Workflows app (Power Automate) and the
# older Office 365 connectors.
TEAMS_HOSTS = (".logic.azure.com", ".powerplatform.com", ".webhook.office.com")


def webhook_problem(kind: str, url: str) -> str | None:
    """Why this is not a webhook for that app, or None when it is."""
    url = url.strip()
    if kind == "slack":
        if not url.startswith(SLACK_PREFIX):
            return f"A Slack incoming webhook URL starts with {SLACK_PREFIX}"
        return None
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host.endswith(TEAMS_HOSTS):
        return (
            "A Teams channel webhook URL comes from the Workflows app, and its address ends "
            "in logic.azure.com, powerplatform.com or webhook.office.com."
        )
    return None


def _client() -> httpx.AsyncClient:
    """Built in one place so tests can swap in a fake transport. Never
    follows redirects: the checked address is the only one called."""
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=False)


async def post(kind: str, url: str, payload: dict[str, Any]) -> ToolResult:
    if problem := webhook_problem(kind, url):
        return ToolResult.failure("not_connected", f"{problem}. Reconnect it under Connections.")
    name = "Slack" if kind == "slack" else "Teams"
    try:
        async with _client() as http:
            resp = await http.post(url.strip(), json=payload)
    except httpx.HTTPError as exc:
        return ToolResult.failure("network_error", f"Could not reach {name}: {exc}")
    if resp.status_code in (401, 403, 404, 410):
        return ToolResult.failure(
            "auth_expired",
            f"{name} no longer accepts this webhook (it may have been removed). "
            "Tell the user to reconnect the channel under Connections.",
        )
    if resp.status_code == 429:
        return ToolResult.failure("rate_limited", f"{name} is limiting posts. Try again later.")
    if resp.status_code >= 400:
        return ToolResult.failure(
            "api_error", f"{name} answered {resp.status_code}: {resp.text[:200]}"
        )
    return ToolResult.success({"posted": True, "channel": None})


class ChatPostArgs(BaseModel):
    text: str = Field(
        min_length=1,
        max_length=3000,
        description="The message. Short paragraphs; *bold* and bullet lines are fine.",
    )
    title: str = Field(default="", max_length=150, description="Optional heading above it")


def _teams_card(args: ChatPostArgs) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    if args.title:
        body.append({"type": "TextBlock", "text": args.title, "weight": "Bolder", "size": "Medium"})
    body.append({"type": "TextBlock", "text": args.text, "wrap": True})
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": body,
                },
            }
        ],
    }


class _ChatPost(Tool):
    pack = "chat"
    args_model = ChatPostArgs
    side_effect = SideEffect.DESTRUCTIVE
    supports_dry_run = True
    timeout_s = HTTP_TIMEOUT_S + 5

    def payload(self, args: ChatPostArgs) -> dict[str, Any]:
        raise NotImplementedError

    async def run(self, ctx: ToolContext, args: ChatPostArgs) -> ToolResult:  # type: ignore[override]
        kind = str(self.requires_connection)
        channel = (ctx.config or {}).get("channel") or None
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_post_to": channel or kind})
        result = await post(kind, ctx.credential or "", self.payload(args))
        if result.ok:
            result.data = {"posted": True, "channel": channel}
        return result


@register
class SlackPost(_ChatPost):
    name = "slack_post"
    description = (
        "Post a message to the connected Slack channel, e.g. a daily summary or an alert. "
        "Everyone in the channel sees it and it cannot be taken back."
    )
    requires_connection = "slack"

    def payload(self, args: ChatPostArgs) -> dict[str, Any]:
        text = f"*{args.title}*\n{args.text}" if args.title else args.text
        return {"text": text}


@register
class TeamsPost(_ChatPost):
    name = "teams_post"
    description = (
        "Post a message to the connected Microsoft Teams channel, e.g. a daily summary or an "
        "alert. Everyone in the channel sees it and it cannot be taken back."
    )
    requires_connection = "teams"

    def payload(self, args: ChatPostArgs) -> dict[str, Any]:
        return _teams_card(args)
