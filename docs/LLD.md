# Low Level Design — Baton (personal assistant)

**Last updated:** 2026-10-28
**Read [HLD.md](HLD.md) first.** This document assumes the architecture described there.

> **How to read the code samples.** Every table that holds data carries `owner_id` (the person). Where this document shows code, it is a short sketch of the real code; the source files named are the reference.

## Contents

| Part | Covers |
|---|---|
| 1 | Folder structure and layering rules |
| 2 | Database tables |
| 3 | API |
| 4 | The agent loop |
| 5 | Tool and provider contracts |
| 6 | Permissions |
| 7 | Event log and SSE |
| 8 | Worker and queue |
| 9 | Encryption |
| 10 | Errors and tests |

---

# Part 1 — Folder structure and layering

## 1.1 Repository layout

```
.
├── docker-compose.yml   Makefile   .env.example
├── backend/
│   ├── pyproject.toml
│   ├── alembic/versions/            # 0001 … 0032
│   ├── scripts/                     # bootstrap_admin.py, seed_demo.py
│   ├── tests/                       # unit/, integration/, isolation/
│   └── app/
│       ├── main.py                  # API entrypoint
│       ├── config.py                # pydantic-settings
│       ├── api/v1/
│       │   ├── deps.py              # current user, request context (owner_id)
│       │   └── routes/              # auth, platform, conversations, agents, tasks, history,
│       │                            # usage, setup, providers, connections, policies,
│       │                            # approval_links, memory, notifications, speech, health
│       ├── schemas/
│       ├── services/                # business logic, no FastAPI imports
│       ├── db/
│       │   ├── models/              # SQLAlchemy 2.0
│       │   └── repositories/        # ALL queries live here
│       ├── agent/
│       │   ├── loop.py              # the hand-written agent loop
│       │   ├── graph.py             # the loop as a one-node LangGraph graph
│       │   ├── graph_loop.py        # loop with LangGraph-saved pauses (off by default)
│       │   ├── supervisor.py        # team mode as a graph (off by default)
│       │   ├── assistant.py         # chat modes and the system prompt
│       │   ├── team.py              # lead + helpers, ask_specialist
│       │   ├── routing.py           # Automatic: which AI for which task
│       │   ├── schedule.py          # agent schedules
│       │   ├── services.py          # app parts (Gmail, Sheets …) and read/edit levels
│       │   ├── tool_infer.py        # pick an agent's tools from its instructions
│       │   ├── providers/           # anthropic, gemini, openai_compatible, fallback
│       │   └── tools/               # base, registry, packs/
│       ├── workers/
│       │   ├── main.py              # worker entrypoint
│       │   └── jobs/                # run_task, dispatch_due_agents, expire_approvals
│       └── core/                    # security, crypto, signed, errors, rate_limit, usernames, urls, observability
└── frontend/
    ├── src/
    │   ├── App.tsx                  # routes
    │   ├── components/              # Rail (the menu), CommandPalette, SetupBar, coach (tours), ui …
    │   ├── pages/                   # Chat, Agents, Approvals, Memory, Connections,
    │   │                            # Providers, Policies, Notifications, Login, Register,
    │   │                            # PlatformAdmin, ApproveLink, Product
    │   └── lib/                     # api.ts (typed client, base path /api/v1), commands.ts (shortcuts) …
    └── scripts/                     # video recorders (see README)
```

## 1.2 Layering rules

```
route  →  service  →  repository  →  database
                 ↘ agent (worker)
```

| Rule | Why |
|---|---|
| A route never writes a query | `owner_id` filtering must happen in exactly one place |
| A service never imports FastAPI | Business logic stays testable without HTTP |
| A repository holds no business rules | It fetches and saves; nothing else |
| The API never runs an agent | Long work belongs to the worker |

## 1.3 The repository base class

Every table that holds a person's data is read and written through `OwnerScopedRepository` in `app/db/repositories/base.py`:

```python
class OwnerScopedRepository[ModelT: Base](BaseRepository[ModelT]):
    def __init__(self, session: AsyncSession, owner_id: uuid.UUID) -> None: ...

    def _scoped(self) -> Select:            # the only way to start a query
        return select(self.model).where(self.model.owner_id == self.owner_id)

    def create(self, **data) -> ModelT:     # sets owner_id itself
        ...
```

Two properties matter. `create` sets `owner_id` itself, so a caller cannot pass someone else's. And a `get` that finds nothing becomes a **404**: the route cannot tell "missing" from "someone else's", so neither can a caller.

The `owner_id` comes from the signed-in token (`RequestContext.owner_id` in `deps.py`), never from the request body or path.

---

# Part 2 — Database tables

Conventions: `id` is a UUID primary key (event and call logs use `bigint`), timestamps are `timestamptz`, money is `numeric(12,6)`. Exact columns are in `app/db/models/`.

## 2.1 Identity

| Table | Holds | Scoped by |
|---|---|---|
| `users` | username (unique, case-insensitive), email, password hash (argon2id), name, `is_active`, last sign-in | its own id |
| `setup_tokens` | the one-time setup link: token **hash**, expiry (72 h by default), used-at | `user_id` |
| `refresh_tokens` | token hash, `family_id` for rotation, expiry, revoked-at | `user_id` |
| `platform_admins` | email, password hash, `is_active` | global — separate from `users` on purpose |
| `platform_admin_audit` | who did what, to which target, when | global; **append-only by database grants** |

## 2.2 Your setup

| Table | Holds |
|---|---|
| `agents` | name, `handle` (unique per person, for @mentions), description, instructions, `model` (`auto` or `provider:model`), `routing`, `tools` (list, or null for "everything I allow"), `tools_auto`, `archived`, `schedule` (JSON), `schedule_enabled`, `next_run_at`, `last_run_at`, `last_status`, `last_summary`, `run_conversation_id`, `max_steps` (default 40, max 80), `scope` (for example the sheet ids it may write) |
| `provider_configs` | your AI keys: provider, **encrypted key**, last 4 characters, status, chosen model, `plan` (free or paid). Web search keys (Tavily, Brave) are kept here too |
| `connections` | Google, Microsoft, mailbox (IMAP), GitHub, database, Slack and Teams webhooks: kind, label, **encrypted credential**, config, status, last error, enabled |
| `person_oauth_apps` | your own Google or Microsoft app (client id, **encrypted secret**) |
| `policies` | your permission rules: scope (tool or pack), value, side effect, setting |
| `notification_settings` | email and Slack switches, encrypted Slack webhook |
| `embedding_configs` | which embedding provider and model your memory uses |
| `setup_progress` | which first-time setup steps you have finished (for the setup bar and AI-key guides) |

All of these carry `owner_id`.

## 2.3 Platform rules

| Table | Holds | Scope |
|---|---|---|
| `supported_providers` | the AI provider catalog: key, name, base URL, API format, default model, `trains_on_data`, `enabled` | global |
| `policy_defaults` | starting permission values | global |
| `platform_oauth_apps` | the shared Google / Microsoft app behind one-click sign-in | global |
| `platform_service_access` | whether a part of an app (for example Sheets, edit) is allowed for everyone | global |
| `platform_connection_access` | whether a kind of app (GitHub, database, Slack ...) is open for everyone | global |
| `person_service_access` | the same as `platform_service_access`, for one person | `owner_id` |
| `person_connection_access` | whether a connection kind is open for one person | `owner_id` |

## 2.4 Conversation and execution

| Table | Holds |
|---|---|
| `conversations` | title, `mode` (general, study, work, research, code), `model`, `routing`, `team`, optional `agent_id` |
| `conversation_messages` | role, content, the `task_id` that produced a reply, the model and why it was chosen, tools used, an agent draft card if any |
| `tasks` | `conversation_id`, optional `agent_id`, input, status, `dry_run`, `created_by`, `cancel_requested` |
| `runs` | one attempt: status, steps, tokens, cost, output, stop cause, heartbeat |
| `run_events` | `(run_id, seq)` unique; type; redacted payload. **Insert only.** |
| `llm_calls` | provider, model, tokens, cost, latency |
| `tool_invocations` | tool, side effect, redacted args, status, duration |
| `approvals` | `run_id`, tool, side effect, the **full proposed action**, status, decided by and when, `expires_at` (24 h) |
| `run_checkpoints` | the saved conversation of a paused run, and the pending tool call |
| `graph_checkpoints`, `graph_checkpoint_writes` | LangGraph's saved state, used only when `AGENT_CHECKPOINTER` is on |

All carry `owner_id`.

## 2.5 Knowledge

| Table | Holds |
|---|---|
| `memories` | kind, content, a generated full-text column, `embedding_model` |
| `memory_vectors_384` / `_768` / `_1024` / `_1536` | one table per vector width, because a pgvector index needs a fixed width |
| `run_summaries` | goal, outcome, lesson of a finished run |

## 2.6 The isolation test

`backend/tests/isolation/test_owner_scoping.py` walks every mapped table. A table without `owner_id` fails the test unless it is in `GLOBAL_TABLES` with a written reason (accounts, tokens, the Platform Admin's tables, the provider catalog, platform defaults and platform rules). A second test fails if any reason is blank.

---

# Part 3 — API

## 3.1 Conventions

| Aspect | Decision |
|---|---|
| Base path | `/api/v1` |
| Auth | `Authorization: Bearer <access>` (15 minutes); refresh token in an httpOnly cookie (30 days), rotated on use |
| Scope | Everything for a signed-in person is under `/me`. There is no id in the path to tamper with. |
| Another person's item | **404**, never 403 |
| Validation | Pydantic; 422 with field errors |
| Platform Admin | Under `/platform`, with a separate token type (`platform_access`). A normal token is refused there. |

## 3.2 Endpoint catalogue

**Auth**

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/register` | Username, email and password; signs you in at once. 10 sign-ups an hour per address. |
| GET | `/auth/username-available` | Yes or no only |
| POST | `/auth/setup` | Set your password from a setup link made by a Platform Admin |
| POST | `/auth/login` | Email or username. 8 wrong passwords lock the account and address for 15 minutes. |
| POST | `/auth/refresh` | Rotates; reusing an old token revokes the whole family |
| POST | `/auth/logout` | |
| GET | `/auth/me` | id, username, email, name |

Both limits are counted in Redis (`app/core/rate_limit.py`), so every API instance shares them.

**Chat** (`/me`)

| Method | Path |
|---|---|
| GET | `/me/assistant` (modes and settings for the chat screen) |
| GET · POST | `/me/conversations` |
| GET · PATCH · DELETE | `/me/conversations/{id}` |
| POST | `/me/conversations/{id}/messages` (queues a task; returns at once) |

**Agents** (`/me/agents`)

| Method | Path | Notes |
|---|---|---|
| GET | `/me/agents/overview` | The whole AI Agents page in one call |
| GET | `/me/agents/tree` | What the live tree shows right now |
| POST | `/me/agents/readiness` | Check a draft before it exists |
| POST | `/me/agents` | Create (pressing Create on a draft card). Max 30. |
| GET · PATCH · DELETE | `/me/agents/{id}` | DELETE archives it; chats that used it still read |
| GET | `/me/agents/{id}/readiness` | |
| POST | `/me/agents/{id}/pause` · `/resume` | The schedule |
| POST | `/me/agents/{id}/run` | Run now |
| POST | `/me/agents/{id}/chat` | Open a chat with this agent |

**Tasks and runs** (`/me`)

| Method | Path | Notes |
|---|---|---|
| GET | `/me/tasks` · `/me/tasks/{id}` | |
| POST | `/me/tasks/{id}/cancel` | |
| GET | `/me/runs/{id}` · `/me/runs/{id}/trace` | |
| GET | `/me/runs/{id}/events` | **SSE**, resumes with `Last-Event-ID` |
| GET | `/me/live` | **SSE** of everything the account is doing |
| GET | `/me/history/runs` · `/me/history/runs/{id}` · `/me/history/models` | Past runs with filters, one run in full, models used |
| GET | `/me/usage` | Spend, and estimated savings against a reference model |
| GET · POST | `/me/setup` · `/me/setup/guide` | How far first-time setup has got |

**AI providers** (`/me`)

| Method | Path |
|---|---|
| GET | `/me/providers/available` · `/me/providers` · `/me/models` |
| POST | `/me/providers` · `/me/providers/{key}/test` · `/me/providers/{key}/auto-model` |
| PUT | `/me/providers/{key}/model` · `/me/providers/{key}/plan` (free or paid) |
| GET | `/me/providers/{key}/models` |
| DELETE | `/me/providers/{key}` |

No endpoint returns a key. The list shows provider, status and last 4 characters.

**Connections** (`/me`)

| Method | Path |
|---|---|
| GET | `/me/connections/available` · `/me/connections` · `/me/connections/services` |
| POST | `/me/connections/oauth/{kind}/start` (body: which parts and levels to share) |
| POST | `/me/connections` (by hand: IMAP, GitHub, database, Slack and Teams webhooks) · `/me/connections/{id}/test` |
| PATCH · DELETE | `/me/connections/{id}` |
| GET · PUT · DELETE | `/me/connections/oauth-apps` · `/me/connections/oauth-apps/{kind}` (your own Google/Microsoft app) |

The OAuth callback is public; it trusts only the signed `state`.

**Permissions and approvals** (`/me`)

| Method | Path |
|---|---|
| GET · PUT | `/me/policies` |
| POST | `/me/policies/reset` |
| GET | `/me/tools` |
| GET | `/me/approvals` · `/me/approvals/{id}` |
| POST | `/me/approvals/{id}/approve` · `/me/approvals/{id}/reject` |
| GET · POST | `/approval-links/{token}` · `/approval-links/{token}/decide` (public, signed link; showing never decides) |

**Memory, notifications, speech** (`/me`)

| Method | Path |
|---|---|
| GET · POST | `/me/memory` |
| DELETE | `/me/memory/{id}` |
| POST | `/me/memory/search` |
| GET | `/me/embedding-providers` |
| GET · PUT | `/me/embedding-config` |
| POST | `/me/embedding-config/reembed` |
| GET · PUT | `/me/notifications` |
| POST | `/me/notifications/test` |
| GET | `/me/speech` |
| POST | `/me/speech/transcribe` |

**Platform Admin** (`/platform`)

| Method | Path | Notes |
|---|---|---|
| POST | `/platform/auth/login` · `/platform/auth/logout` | Email and password. The sign-in lasts 8 hours (`PLATFORM_SESSION_HOURS`) in a session cookie, so a page refresh keeps it. |
| GET | `/platform/me` · `/platform/overview` | Who is signed in; the headline numbers |
| GET · POST | `/platform/people` | POST returns the setup token once |
| GET | `/platform/people/{id}` | Counts and health only: tasks run, providers connected (yes/no) |
| POST | `/platform/people/{id}/suspend` · `/restore` | Nothing is read or deleted |
| POST | `/platform/people/{id}/setup-link` | A new setup link for an invited account |
| GET · PUT | `/platform/people/{id}/connections` · `…/connections/{kind}` | Open or close a connection kind for one person |
| GET · PUT | `/platform/app-access` · `/platform/app-access/{kind}` | Open or close a kind of app for everyone |
| GET · PUT | `/platform/people/{id}/services` · `…/services/{service}/{level}` | Open or close one part of an app for one person |
| GET · PUT | `/platform/service-access` · `/platform/service-access/{service}/{level}` | The same, for everyone |
| GET · PUT · PATCH · DELETE | `/platform/oauth-apps` · `/platform/oauth-apps/{provider}` | The shared one-click apps |
| GET · PUT · PATCH | `/platform/providers` · `/platform/providers/{key}` | The AI provider catalog |
| GET | `/platform/audit` | Read-only |

**There is no `/platform` endpoint that returns anyone's chats, tasks, memory, credentials or keys.** Absence is the control.

---

# Part 4 — The agent loop

## 4.1 Sketch

The real code is `AgentLoop` in `app/agent/loop.py`, started by `run_task` in `app/workers/jobs/agent_run.py`.

```python
# run_task, simplified
task, conversation, agent = load(...)
tools    = allowed_tools(person, agent)        # Permissions, grants, platform rules, agent list
provider = choose_ai(conversation or agent)    # Automatic routing, with fallbacks
loop     = AgentLoop(provider=provider, tools=tools, budget=..., check_policy=...)
outcome  = await run_in_graph(loop, system_prompt=..., task=task.input, history=...)

# AgentLoop.run, simplified
while True:
    stop if budget spent or cancel requested
    reply = await provider.complete(messages, tool_schemas)
    record llm_call; add reply to messages
    if no tool calls: finish with reply text
    for each call (up to 3 at once when independent):
        decision = check_policy(call)
        Blocked -> tell the model it is blocked
        Ask     -> save state, create approval, pause (return)
        Auto    -> run the tool; errors come back as text
```

`run_in_graph` (in `graph.py`) runs the loop as the single node of a LangGraph graph. With `AGENT_CHECKPOINTER=true`, `GraphLoop` pauses with LangGraph's `interrupt()` and saves state in `graph_checkpoints`; otherwise the pause is saved in `run_checkpoints`. With `AGENT_SUPERVISOR=true`, team mode runs as the graph in `supervisor.py`. Both settings are off by default.

## 4.2 Budgets

| Run | Steps | Time |
|---|---|---|
| A chat turn | 10 (`CHAT_MAX_STEPS`) | worker job limit |
| A scheduled or "run now" agent run | the agent's `max_steps` (default 40, max 80) | 840 s |
| A team helper | 6 steps | 180 s |

At most 6 helper calls per message. Team mode is off for unattended runs.

## 4.3 Properties

| Property | Where |
|---|---|
| **Budget checked first, every step** | A runaway loop stops before it costs more |
| **Cancellation checked every step** | Stops within one step |
| **Tool errors become messages** | The model can recover |
| **Pausing returns** | The worker is freed; it does not wait for a person |
| **Permission checked per call** | One run can hit Always allow, Ask and Blocked in turn |

---

# Part 5 — Tool and provider contracts

## 5.1 The Tool interface (`app/agent/tools/base.py`)

```python
class Tool(ABC):
    name: ClassVar[str]
    pack: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]
    side_effect: ClassVar[SideEffect]          # read | write | destructive — no default
    supports_dry_run: ClassVar[bool] = False
    timeout_s: ClassVar[float] = 30.0
    requires_connection: ClassVar[str | None] = None

    async def run(self, ctx: ToolContext, args: BaseModel) -> ToolResult: ...
```

`ToolContext` carries `owner_id`, `run_id`, `dry_run` and the credentials the worker attached (`grants`). The model never sees them. `ToolResult` is `ok`, `data`, or an error class and message that `as_text()` turns into a sentence for the model.

**`side_effect` has no default.** A tool without it fails at import, so the server will not start.

## 5.2 Registry and the tool list

The registry (`app/agent/tools/registry.py`) holds every built-in tool and the catastrophic blocklist (`BLOCKED_ACTIONS`). For one run, the tools offered are the ones that pass every layer:

1. the platform allows that part of the app (for everyone, or for this person);
2. the person's connection was granted that permission (for example Gmail edit);
3. the agent lists the tool (if it is an agent run with a narrowed list);
4. the person's Permissions do not block it.

A tool that fails a layer is not described to the model at all. The agent-designing tool (`propose_agent`) is not in the registry: it is given only to a chat that is designing an agent.

## 5.3 Provider interface (`app/agent/providers/base.py`)

```python
class LLMProvider(ABC):
    async def complete(self, *, messages, tools, model, temperature, max_tokens) -> LLMReply: ...
    async def list_models(self) -> list[str]: ...
    async def check(self, model: str) -> None: ...
```

Three adapters: `AnthropicProvider` (keeps Claude's thinking blocks between tool calls), `GeminiProvider`, and `OpenAICompatibleProvider` (OpenAI, Groq, DeepSeek, Mistral, OpenRouter, Together, NVIDIA, Sarvam, and the person's own server). Which adapter a catalog entry uses is its `api_format`. A fallback wrapper moves to the next connected AI on a rate limit or outage. Errors are typed (`ProviderRateLimitError`, `ProviderAuthError`, `ProviderTooLargeError` …) so the caller can tell a bad key from a busy server.

## 5.4 Cost

Each model call is priced from a per-model table (`app/agent/pricing.py`) and stored in `llm_calls`. With your own key we cannot see your real invoice, so every figure is shown as an **estimated cost**.

---

# Part 6 — Permissions

## 6.1 Resolution order (`app/services/policy_service.py`)

1. **Catastrophic blocklist**: platform-wide, nobody can override.
2. Your rule for this tool.
3. Your rule for this pack and side effect.
4. Platform default for this tool.
5. Platform default for this pack and side effect.
6. **Safe fallback**: read → Always allow, write → Ask me first, destructive → Blocked.

Most specific wins, except the blocklist, which always wins. Rule 6 means a new tool with no rule is safe by default. An unknown tool is refused.

## 6.2 Platform defaults versus your rules

| | Platform Admin | You |
|---|---|---|
| Sets | The starting values (`policy_defaults`) | Your own value, looser or stricter |
| Can you go looser than the default? | — | ✅ Yes (switching an irreversible action to Always allow asks you once more) |
| Can you override the blocklist? | — | ❌ No; the backend refuses it |

Separately, the Platform Admin can close a part of an app (for example Sheets edit) for everyone or one person. That is a different layer (Part 5.2, layer 1): it removes the tool rather than changing its setting.

## 6.3 Where it is enforced

In the worker, before every tool call. The screens read the same rules only to show helpful text. A screen check is a convenience; the worker check is the control.

---

# Part 7 — Event log and SSE

## 7.1 Event types

| Type | When |
|---|---|
| `run_started`, `run_finished`, `run_stopped` | Start and end of a run |
| `thinking`, `llm_call`, `text` | Model steps and output |
| `model_chosen`, `model_fallback`, `model_retry`, `provider_error` | Which AI, and any handover |
| `tool_call`, `tool_result`, `tool_blocked`, `parallel_started` | Tools |
| `approval_requested`, `approval_decided` | Approvals |
| `specialist_started`, `specialist_step`, `specialist_finished`, `specialist_failed`, `specialist_escalated`, `team_summary` | Team mode |

## 7.2 Writing

Events are inserted into `run_events` with the next `seq`, with secret-looking keys (`api_key`, `token`, `password`, `secret` …) replaced by `[redacted]` **before** the insert, then published on Redis channel `run:{id}`. Persist first, publish second: a lost publish is recovered on reconnect; an event is never shown that is not in the permanent record.

## 7.3 SSE protocol

```
GET /api/v1/me/runs/{id}/events
Last-Event-ID: 12          ← optional, to resume

id: 13
event: tool_call
data: {"seq":13,"tool":"gmail_search", ...}
```

The server first replays events after `Last-Event-ID` from Postgres, then streams live ones from Redis. The client drops duplicates by `seq`.

---

# Part 8 — Worker and queue

## 8.1 Jobs (`app/workers/main.py`)

| Job | Trigger |
|---|---|
| `run_task` | A chat message, a "run now", a scheduled run, or an approval granted |
| `dispatch_due_agents` | Every minute: start agents whose `next_run_at` has come, after a readiness re-check |
| `expire_approvals` | Every 5 minutes: fail runs whose approval passed 24 h; also delete LangGraph state older than 3 days left by crashed runs |
| `ping` | Proves the API → Redis → worker path |

## 8.2 Concurrency

```python
max_jobs    = 1 if settings.slow_mode else settings.worker_max_jobs   # slow_mode defaults to on
job_timeout = 900
```

One run makes many model calls, so with free-tier keys, running two at once trips rate limits. In slow mode the queue gets longer instead of runs failing.

## 8.3 Retries

Provider errors are typed. A rate limit or outage moves the run to the next connected AI. A bad key fails at once with a message the person can act on. A team helper that could not finish is tried once more on the strongest connected AI.

---

# Part 9 — Encryption (`app/core/crypto.py`)

```
master key (ENCRYPTION_KEY)  →  SHA-256(master + scope)  →  AES-GCM key for that scope
```

```python
encrypt(plaintext, scope=owner_id)   # nonce + ciphertext; scope is also the AAD
decrypt(blob, scope=owner_id)        # wrong scope or key → SecretUnreadableError
```

| Property | Benefit |
|---|---|
| A different key per person | One person's secrets cannot be decrypted with another's key |
| The scope as authenticated data | A ciphertext moved to another person's row fails to decrypt |
| AES-GCM | Tampering is detected |
| `scope="platform"` | Used for the Platform Admin's shared app secrets |

A secret that cannot be decrypted (after a changed `ENCRYPTION_KEY`, say) raises `SecretUnreadableError`, which tells the person in plain words to enter it again.

No function returns a decrypted secret to an HTTP response. The worker decrypts only at call time, to add it to the outgoing request.

---

# Part 10 — Errors and tests

## 10.1 Errors (`app/core/errors.py`)

```
AppError                 → 500
├── AuthError            → 401   (InvalidCredentialsError, TokenReuseError)
├── PermissionDeniedError→ 403
├── NotFoundError        → 404   ← also another person's item
├── ConflictError        → 409
├── ValidationError      → 422   (SecretUnreadableError)
├── RateLimitError       → 429
└── UpstreamError        → 502
```

Tool failures never become HTTP errors: they are `ToolResult` failures, given to the model as text.

## 10.2 Tests (`backend/tests/`)

| Suite | What it checks |
|---|---|
| `unit/` | Services, permission resolution, routing, schedules, cost maths, budgets |
| `integration/` | Routes against real Postgres and Redis: auth, sign-up and setup links, chat, agents and schedules, approvals, memory, providers, connections, platform admin |
| `isolation/` | Every scoped table has `owner_id` (`test_owner_scoping.py`) |

Two integration tests guard the boundaries directly: `test_person_isolation.py` (another person's items return 404) and `test_platform_cannot_read_customer_data.py` (the Platform Admin cannot read content).

Tests use scripted and stub providers, so they run with no API key and no cost. `make test` runs them against a separate database (`ai_employee_test`).

---

*End of Low Level Design.*
