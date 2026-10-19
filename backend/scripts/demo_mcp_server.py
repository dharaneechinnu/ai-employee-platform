"""A tiny MCP tool server for trying the MCP feature locally.

It pretends to be a CRM with three tools, one of each kind:

- find_customer       read-only            runs on its own
- update_deal_stage   changes something    waits for approval
- delete_contact      cannot be undone     blocked unless allowed

Run it, then add it under Connections > Tool servers (MCP) with the
address http://localhost:8765/mcp and the token demo-token-1234:

    uvicorn scripts.demo_mcp_server:app --port 8765

Local addresses need ALLOW_PRIVATE_URLS=true in .env (development only).
Speaks Streamable HTTP, answering every request with plain JSON.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

TOKEN = "demo-token-1234"  # noqa: S105 - a public demo value, not a secret

CUSTOMERS = {
    "asha": {"name": "Asha Rao", "email": "asha@brightmart.in", "plan": "Pro", "deal": "D-104"},
    "vikram": {
        "name": "Vikram Shah",
        "email": "vikram@zenfoods.in",
        "plan": "Starter",
        "deal": "D-221",
    },
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "find_customer",
        "title": "Find a customer",
        "description": "Look up a customer by name or email. Returns their plan and open deal.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A name or email"}},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "update_deal_stage",
        "title": "Move a deal",
        "description": "Move a deal to a new stage: lead, proposal, won or lost.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "deal_id": {"type": "string"},
                "stage": {"type": "string", "enum": ["lead", "proposal", "won", "lost"]},
            },
            "required": ["deal_id", "stage"],
        },
    },
    {
        "name": "delete_contact",
        "title": "Delete a contact",
        "description": "Delete a contact and their history for good.",
        "inputSchema": {
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
        "annotations": {"destructiveHint": True},
    },
]

app = FastAPI(title="Demo CRM (MCP)")


def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "find_customer":
        query = str(args.get("query", "")).lower()
        found = [c for key, c in CUSTOMERS.items() if key in query or c["email"] in query]
        text = (
            "\n".join(
                f"{c['name']} <{c['email']}>, {c['plan']} plan, open deal {c['deal']}"
                for c in found
            )
            or "No customer matches that."
        )
        return {"content": [{"type": "text", "text": text}]}
    if name == "update_deal_stage":
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Deal {args.get('deal_id')} moved to {args.get('stage')}.",
                }
            ]
        }
    if name == "delete_contact":
        return {"content": [{"type": "text", "text": f"Deleted {args.get('email')}."}]}
    return {"content": [{"type": "text", "text": f"Unknown tool {name}."}], "isError": True}


@app.post("/mcp")
async def mcp(request: Request) -> Response:
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    if "id" not in body:  # a notification needs no answer
        return Response(status_code=202)

    method, params = body.get("method"), body.get("params") or {}
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "demo-crm", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = _call(params.get("name", ""), params.get("arguments") or {})
    else:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32601, "message": "Method not found"},
            }
        )
    return JSONResponse({"jsonrpc": "2.0", "id": body["id"], "result": result})


@app.delete("/mcp")
async def end_session() -> Response:
    return Response(status_code=200)
