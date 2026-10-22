> **Superseded (Oct 2026).** This document describes the earlier company / AI Employees design. The product is now a personal multi-agent assistant. See `docs/AGENTS_PLAN.md` and the multi-agent build plan for the current design.

# Low Level Design — AI Employee Platform

**Version:** 0.1
**Last updated:** 2026-10-11
**Read [HLD.md](HLD.md) first** — this document assumes the architecture decided there.

## Contents

| Part | Covers |
|---|---|
| 1 | Folder structure and layering rules |
| 2 | Database schema |
| 3 | API specification |
| 4 | The agent loop |
| 5 | Tool and provider contracts |
| 6 | Policy engine |
| 7 | Event log and SSE protocol |
| 8 | Worker and queue |
| 9 | Encryption |
| 10 | Error taxonomy and testing |

---
---

# Part 1 — Folder structure and layering

## 1.1 Repository layout

```
ai-employee-platform/
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
├── .env.example
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic/versions/
│   └── app/
│       ├── main.py                    # API entrypoint
│       ├── config.py                  # pydantic-settings
│       │
│       ├── api/v1/
│       │   ├── deps.py                # current_user, current_org, require_permission
│       │   └── routes/
│       │       ├── auth.py  orgs.py  ai_employees.py  templates.py
│       │       ├── tasks.py  runs.py  tools.py  providers.py
│       │       ├── connections.py  policies.py  approvals.py
│       │       ├── memory.py  documents.py  workflows.py
│       │       └── platform/          # platform-admin only
│       │           ├── companies.py  providers.py  policies.py  audit.py
│       │
│       ├── schemas/                   # pydantic request/response — the contract
│       ├── services/                  # business logic, framework-free
│       │   ├── auth_service.py  employee_service.py  task_service.py
│       │   ├── policy_service.py  approval_service.py  memory_service.py
│       │   └── cost_service.py
│       │
│       ├── db/
│       │   ├── session.py
│       │   ├── models/                # SQLAlchemy 2.0 declarative
│       │   └── repositories/          # ← ALL queries live here
│       │       ├── base.py            # OrgScopedRepository
│       │       └── *_repo.py
│       │
│       ├── agent/                     # LangChain/LangGraph confined here
│       │   ├── runner.py              # AgentRunner port
│       │   ├── loop.py                # phase 3 hand-written loop
│       │   ├── graphs/                # phase 7 LangGraph
│       │   ├── providers/
│       │   │   ├── base.py            # LLMProvider ABC
│       │   │   ├── gemini.py  openai_compatible.py
│       │   │   ├── embeddings/        # local.py, api.py
│       │   │   └── pricing.py         # per-model cost table
│       │   ├── memory/                # compaction, recall, summarise
│       │   └── tools/
│       │       ├── base.py            # Tool ABC
│       │       ├── registry.py
│       │       └── packs/             # github.py, email.py, sql.py, http.py, docs.py
│       │
│       ├── workers/
│       │   ├── main.py                # worker entrypoint
│       │   ├── jobs/                  # run_task, reembed, expire_approvals, reap
│       │   └── queue.py
│       │
│       ├── core/
│       │   ├── security.py  crypto.py  events.py
│       │   ├── errors.py  observability.py  ratelimit.py
│       │
│       └── tests/
│           ├── unit/  integration/  e2e/
│           ├── isolation/             # tenant-isolation suite
│           ├── security/              # injection red-team suite
│           ├── evals/                 # golden tasks
│           └── cassettes/             # committed — CI runs offline
│
├── frontend/
│   └── src/
│       ├── api/                       # generated types + typed client
│       ├── mocks/                     # MSW handlers
│       ├── features/{auth,employees,tasks,runs,providers,policies,approvals,memory,platform}/
│       ├── components/ui/
│       └── hooks/
│
└── docs/
    ├── IMPLEMENTATION_PLAN.md  HLD.md  LLD.md
    └── adr/
```

## 1.2 Layering rules

```
route  →  service  →  repository  →  database
         ↘ agent (worker only)
```

| Rule | Why |
|---|---|
| A route never writes a query | `org_id` scoping must have exactly one chokepoint |
| A service never imports FastAPI | Business logic stays testable without HTTP |
| A repository never contains business rules | It fetches and persists; nothing else |
| `agent/` is imported only from `workers/` | Enforces "the API never runs an agent" |
| No LangChain/LangGraph type crosses out of `agent/` | Library churn stays contained |

**Enforcement:** an import-linter rule in CI, not a convention in a wiki.

## 1.3 The repository base class

Every tenant-owned repository inherits this. It is the single place tenant filtering happens.

```python
class OrgScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession, org_id: UUID):
        self.session = session
        self.org_id = org_id

    def _scoped(self) -> Select:
        return select(self.model).where(self.model.org_id == self.org_id)

    async def get(self, id: UUID) -> ModelT | None:
        return await self.session.scalar(self._scoped().where(self.model.id == id))

    async def list(self, **filters) -> Sequence[ModelT]: ...
    async def create(self, **data) -> ModelT:
        return self.model(org_id=self.org_id, **data)   # org_id never from caller
```

Two properties worth noting: `create` sets `org_id` itself, so a caller cannot pass someone else's. And `get` returning `None` becomes a **404**, never a 403 — the route layer does not distinguish "missing" from "someone else's".

---
---

# Part 2 — Database schema

Conventions: `id` is `uuid` primary key, timestamps are `timestamptz`, money is `numeric(12,6)`, soft delete via `archived_at` where needed.

## 2.1 Identity (Phase 1)

```sql
CREATE TABLE organizations (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    slug            citext UNIQUE NOT NULL,
    status          text NOT NULL DEFAULT 'active',      -- active|suspended|closed
    max_employees   int  NOT NULL DEFAULT 3,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           citext UNIQUE NOT NULL,
    password_hash   text NOT NULL,                        -- argon2id
    full_name       text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id  uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    org_id   uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role     text NOT NULL,                               -- admin|member
    UNIQUE (user_id, org_id)
);

CREATE TABLE invitations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email       citext NOT NULL,
    role        text NOT NULL,
    token_hash  text UNIQUE NOT NULL,                     -- store the hash, not the token
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz
);

CREATE TABLE refresh_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id   uuid NOT NULL,                            -- rotation family
    token_hash  text UNIQUE NOT NULL,
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz
);
CREATE INDEX ON refresh_tokens (family_id);

-- Platform admins live in their own table, NOT as a role on users
CREATE TABLE platform_admins (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           citext UNIQUE NOT NULL,
    password_hash   text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE platform_admin_audit (
    id          bigserial PRIMARY KEY,
    admin_id    uuid NOT NULL REFERENCES platform_admins(id),
    action      text NOT NULL,
    target      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
REVOKE UPDATE, DELETE ON platform_admin_audit FROM app_user;   -- append-only, enforced by grants
```

> The last line matters. Making the audit table append-only through **database grants** means application code cannot tamper with it even if compromised. A convention would not survive a bug.

## 2.2 Configuration (Phases 2, 3, 5)

```sql
CREATE TABLE ai_employees (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            text NOT NULL,
    job_title       text,
    department      text,
    status          text NOT NULL DEFAULT 'draft',        -- draft|active|paused|archived
    current_version_id uuid,
    created_by      uuid REFERENCES users(id),
    archived_at     timestamptz
);
CREATE INDEX ON ai_employees (org_id, status);

CREATE TABLE ai_employee_versions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id   uuid NOT NULL REFERENCES ai_employees(id) ON DELETE CASCADE,
    org_id        uuid NOT NULL,
    version_no    int NOT NULL,
    config        jsonb NOT NULL,     -- whole snapshot: instructions, model, limits, tools
    created_by    uuid REFERENCES users(id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (employee_id, version_no)
);

CREATE TABLE templates (
    id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id   uuid REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = platform template
    name     text NOT NULL,
    config   jsonb NOT NULL
);

CREATE TABLE supported_providers (                        -- the menu, platform-controlled
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key             text UNIQUE NOT NULL,                 -- gemini|openai|anthropic|groq
    display_name    text NOT NULL,
    kind            text NOT NULL,                        -- llm|embedding
    enabled         boolean NOT NULL DEFAULT true,
    trains_on_data  boolean NOT NULL DEFAULT false
);

CREATE TABLE provider_configs (                           -- the keys, BYOK
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          uuid REFERENCES organizations(id) ON DELETE CASCADE,  -- NULL = platform trial key
    provider_key    text NOT NULL REFERENCES supported_providers(key),
    api_key_enc     bytea NOT NULL,
    key_last4       text NOT NULL,                        -- for display only
    status          text NOT NULL DEFAULT 'untested',
    last_tested_at  timestamptz,
    UNIQUE (org_id, provider_key)
);

CREATE TABLE connections (                                -- GitHub, email, SQL, REST
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind            text NOT NULL,
    credential_enc  bytea NOT NULL,
    config          jsonb NOT NULL DEFAULT '{}',          -- repo list, allowed URLs, etc.
    status          text NOT NULL DEFAULT 'untested',
    last_tested_at  timestamptz
);
```

## 2.3 Execution (Phases 4, 5)

```sql
CREATE TABLE tasks (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id               uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    employee_id          uuid NOT NULL REFERENCES ai_employees(id),
    employee_version_id  uuid NOT NULL REFERENCES ai_employee_versions(id),   -- pinned
    title                text,
    input                text NOT NULL,
    status               text NOT NULL DEFAULT 'queued',
    dry_run              boolean NOT NULL DEFAULT false,
    created_by           uuid NOT NULL REFERENCES users(id),
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON tasks (org_id, status, created_at DESC);

CREATE TABLE runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    org_id        uuid NOT NULL,
    attempt       int NOT NULL DEFAULT 1,
    status        text NOT NULL DEFAULT 'running',
    step_count    int NOT NULL DEFAULT 0,
    total_tokens  int NOT NULL DEFAULT 0,
    cost_usd      numeric(12,6) NOT NULL DEFAULT 0,
    error_class   text,
    error_message text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    ended_at      timestamptz
);

CREATE TABLE run_events (
    id          bigserial PRIMARY KEY,
    run_id      uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq         int  NOT NULL,
    type        text NOT NULL,
    payload     jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);
CREATE INDEX ON run_events (run_id, seq);

CREATE TABLE llm_calls (
    id             bigserial PRIMARY KEY,
    run_id         uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    org_id         uuid NOT NULL,
    provider_key   text NOT NULL,
    model          text NOT NULL,
    prompt_tokens  int NOT NULL,
    output_tokens  int NOT NULL,
    cost_usd       numeric(12,6) NOT NULL,
    latency_ms     int NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE tool_invocations (
    id           bigserial PRIMARY KEY,
    run_id       uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    org_id       uuid NOT NULL,
    tool_name    text NOT NULL,
    side_effect  text NOT NULL,                           -- read|write|destructive
    args         jsonb NOT NULL,                          -- redacted
    status       text NOT NULL,
    duration_ms  int,
    idempotency_key text
);

CREATE TABLE policy_defaults (                            -- platform-set starting values
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_kind   text NOT NULL,                           -- pack|tool
    scope_value  text NOT NULL,                           -- 'github' or 'github.open_pull_request'
    side_effect  text,
    setting      text NOT NULL,                           -- auto|ask|blocked
    UNIQUE (scope_kind, scope_value, side_effect)
);

CREATE TABLE policies (                                   -- company overrides
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scope_kind   text NOT NULL,
    scope_value  text NOT NULL,
    side_effect  text,
    setting      text NOT NULL,
    UNIQUE (org_id, scope_kind, scope_value, side_effect)
);

CREATE TABLE blocked_actions (                            -- catastrophic list, platform-wide
    tool_name  text PRIMARY KEY,
    reason     text NOT NULL
);

CREATE TABLE approvals (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id       uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    org_id       uuid NOT NULL,
    tool_name    text NOT NULL,
    proposed     jsonb NOT NULL,                          -- the FULL payload the reviewer sees
    status       text NOT NULL DEFAULT 'pending',
    decided_by   uuid REFERENCES users(id),
    decided_at   timestamptz,
    expires_at   timestamptz NOT NULL
);
CREATE INDEX ON approvals (org_id, status, expires_at);

CREATE TABLE run_checkpoints (
    run_id      uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    state       jsonb NOT NULL,                           -- phase 5 handmade; phase 7 LangGraph
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run_heartbeats (
    run_id      uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    worker_id   text NOT NULL,
    beat_at     timestamptz NOT NULL DEFAULT now()
);
```

## 2.4 Knowledge (Phase 6)

```sql
CREATE TABLE embedding_configs (
    org_id          uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    provider_key    text NOT NULL,
    model           text NOT NULL,
    dim             int  NOT NULL,                        -- 768 | 1024 | 1536
    api_key_enc     bytea
);

CREATE TABLE memories (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    employee_id      uuid REFERENCES ai_employees(id) ON DELETE CASCADE,  -- NULL = org-wide
    kind             text NOT NULL,                       -- fact|correction|summary|document
    content          text NOT NULL,
    content_tsv      tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    embedding_model  text NOT NULL,                       -- mismatch detection
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON memories USING gin (content_tsv);         -- keyword half of hybrid search

-- One table per dimension: pgvector indexes require a fixed dimension
CREATE TABLE memory_vectors_768  (memory_id uuid PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE, embedding vector(768));
CREATE TABLE memory_vectors_1024 (memory_id uuid PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE, embedding vector(1024));
CREATE TABLE memory_vectors_1536 (memory_id uuid PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE, embedding vector(1536));
CREATE INDEX ON memory_vectors_1024 USING hnsw (embedding vector_cosine_ops);

CREATE TABLE run_summaries (
    run_id   uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    org_id   uuid NOT NULL,
    goal     text, outcome text, lesson text
);

CREATE TABLE reembed_jobs (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id    uuid NOT NULL,
    from_model text, to_model text,
    total int, done int, status text
);
```

## 2.5 The tenant-isolation test

```python
GLOBAL_TABLES = {"users", "platform_admins", "platform_admin_audit",
                 "supported_providers", "policy_defaults", "blocked_actions"}

def test_every_table_is_org_scoped():
    for model in Base.registry.mappers:
        table = model.class_.__tablename__
        if table in GLOBAL_TABLES:
            continue
        assert "org_id" in model.class_.__table__.columns, f"{table} is missing org_id"
```

Adding a table without `org_id` fails CI. The whitelist is deliberately short and requires a reviewer to justify an addition.

---
---

# Part 3 — API specification

## 3.1 Conventions

| Aspect | Decision |
|---|---|
| Base path | `/api/v1` |
| Auth | `Authorization: Bearer <access>` (15 min); refresh in an httpOnly cookie |
| Errors | RFC 7807 problem+json: `{type, title, status, detail, errors[]}` |
| Cross-tenant | **404**, never 403 |
| Pagination | Cursor: `?cursor=&limit=` → `{items, next_cursor}` |
| Idempotency | `Idempotency-Key` header on POSTs that cause side effects |
| Validation | Pydantic; 422 with field-level errors |

## 3.2 Endpoint catalogue

**Auth** (Phase 1)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/auth/accept-invite` | public | The only way an account is created |
| POST | `/auth/login` | public | Rate-limited per IP and per email |
| POST | `/auth/refresh` | cookie | Rotates; reuse revokes the whole family |
| POST | `/auth/logout` | any | |
| GET | `/auth/me` | any | |

**Organizations** (Phase 1)

| Method | Path | Role |
|---|---|---|
| GET | `/orgs` | any |
| GET · PATCH | `/orgs/{id}` | member · admin |
| GET | `/orgs/{id}/members` | member |
| POST | `/orgs/{id}/invites` | admin |
| PATCH · DELETE | `/orgs/{id}/members/{uid}` | admin |

**AI Employees** (Phase 2)

| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/ai-employees` | member | |
| POST | `/ai-employees` | admin | **Enforces `max_employees`** |
| GET | `/ai-employees/{id}` | member | |
| PATCH | `/ai-employees/{id}` | admin | Inserts a new version |
| DELETE | `/ai-employees/{id}` | admin | Archive |
| POST | `/ai-employees/{id}/activate` · `/pause` | admin | |
| GET | `/ai-employees/{id}/versions` | member | |
| POST | `/ai-employees/{id}/preview-prompt` | admin | Exact text sent to the model |
| GET · POST · DELETE | `/templates` · `/templates/{id}` | member · admin | |

**Providers and connections** (Phases 3, 5)

| Method | Path | Role |
|---|---|---|
| GET | `/providers/available` | admin |
| GET · POST | `/providers` · `/providers/{id}` | admin |
| POST | `/providers/{id}/test` | admin |
| GET | `/models` | member |
| GET · POST · DELETE | `/connections` · `/connections/{id}` | admin |
| POST | `/connections/{id}/test` | admin |

> No endpoint anywhere returns a plaintext key. `GET /providers` returns `{provider_key, status, key_last4}`.

**Tasks and runs** (Phase 4)

| Method | Path | Role | Notes |
|---|---|---|---|
| POST | `/tasks` | member | Returns 202 in <500 ms |
| GET | `/tasks` · `/tasks/{id}` | member | |
| POST | `/tasks/{id}/cancel` | member (own) · admin | |
| GET | `/runs/{id}` | member | |
| GET | `/runs/{id}/events` | member | **SSE**, supports `Last-Event-ID` |
| GET | `/runs/{id}/trace` | member | Full history as JSON |

**Policies and approvals** (Phase 5)

| Method | Path | Role |
|---|---|---|
| GET · PUT | `/policies` | admin |
| POST | `/policies/reset` | admin |
| GET | `/approvals` · `/approvals/{id}` | admin |
| POST | `/approvals/{id}/approve` · `/reject` | admin |

**Memory** (Phase 6)

| Method | Path | Role |
|---|---|---|
| GET · POST · PATCH · DELETE | `/memory` · `/memory/{id}` | admin |
| POST | `/memory/search` | member |
| POST | `/documents` | admin |
| GET · PUT | `/embedding-config` | admin |
| GET | `/reembed-jobs/{id}` | admin |

**Platform admin** (Phase 1, 3)

| Method | Path | Notes |
|---|---|---|
| POST | `/platform/auth/login` | Password only |
| GET · POST | `/platform/companies` | |
| PATCH | `/platform/companies/{id}/limits` | |
| POST | `/platform/companies/{id}/suspend` · `/reactivate` · `/close` | |
| GET | `/platform/companies/{id}/provider-status` | **Boolean only. No key data.** |
| GET · POST · PATCH | `/platform/supported-providers` | |
| GET · PUT | `/platform/policy-defaults` | |
| GET | `/platform/audit` | Read-only |

**There is deliberately no `/platform/*` endpoint that returns customer content, credentials, task text or memory.** Absence is the control.

## 3.3 Permission dependency

```python
def require_permission(perm: Permission):
    async def dep(ctx: RequestContext = Depends(get_context)) -> RequestContext:
        if perm not in ROLE_PERMISSIONS[ctx.role]:
            raise Forbidden()
        return ctx
    return dep

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN:  {EMPLOYEE_WRITE, TASK_WRITE, CONNECTION_WRITE,
                  POLICY_WRITE, APPROVAL_DECIDE, MEMBER_MANAGE, MEMORY_WRITE},
    Role.MEMBER: {TASK_WRITE, TASK_READ, EMPLOYEE_READ},
}
```

A test walks the OpenAPI schema and asserts every route carries either `require_permission` or an explicit `@public` marker. A forgotten guard fails CI rather than shipping.

---
---

# Part 4 — The agent loop

## 4.1 Pseudocode

```python
async def run_task(run_id: UUID) -> RunResult:
    ctx     = await load_run_context(run_id)      # version config, tools, policy, connections
    events  = EventWriter(run_id)                 # appends + publishes
    msgs    = ctx.checkpoint.messages if ctx.checkpoint else [
                  system(ctx.config.instructions), user(ctx.task.input)]
    budget  = Budget(ctx.config.max_steps, ctx.config.max_tokens, WALL_CLOCK)

    while True:
        if violation := budget.check():
            return await finish(run_id, FAILED, violation)
        if await cancel_requested(run_id):
            return await finish(run_id, CANCELLED)
        await heartbeat(run_id)

        await events.append("thinking")
        reply = await ctx.provider.complete(
            messages=msgs, tools=ctx.tool_schemas,
            model=ctx.config.model, temperature=ctx.config.temperature)

        await record_llm_call(run_id, reply.usage)
        budget.consume(reply.usage.total_tokens)
        msgs.append(reply.message)

        if not reply.tool_calls:
            return await finish(run_id, COMPLETED, output=reply.text)

        for call in reply.tool_calls:
            decision = ctx.policy.evaluate(call.name)          # see Part 6

            if decision is BLOCKED:
                msgs.append(tool_result(call, "Blocked by this company's policy."))
                await events.append("tool_blocked", call.name)
                continue

            if decision is ASK:
                await create_approval(run_id, call)
                await save_checkpoint(run_id, msgs)
                return await pause(run_id, AWAITING_APPROVAL)   # worker is freed

            result = await execute_tool(ctx, call, dry_run=ctx.task.dry_run)
            msgs.append(tool_result(call, result.as_text()))    # errors included as text
            await events.append("tool_result", result.summary())

        budget.step()
```

## 4.2 Five properties this encodes

| Property | Where |
|---|---|
| **Budget checked first, every iteration** | A runaway loop is stopped before it costs anything further |
| **Cancellation checked every iteration** | Stops within one step, typically under 5 s |
| **Tool errors become messages, not exceptions** | `result.as_text()` on failure lets the model recover |
| **Pausing returns from the function** | The worker is released; it does not sleep waiting for a human |
| **Policy is evaluated per call** | One run can legitimately hit Auto, Ask and Blocked in sequence |

## 4.3 Context compaction (Phase 6)

```python
if estimated_tokens(msgs) > ctx.config.context_threshold:
    head, tail = msgs[:-KEEP_RECENT], msgs[-KEEP_RECENT:]
    summary = await ctx.routine_provider.summarise(head)   # cheap model
    msgs = [msgs[0], assistant(f"[earlier steps] {summary}"), *tail]
```

The system message is always kept. Recent steps stay verbatim because the model needs their detail; older steps compress well because only their conclusions matter.

---
---

# Part 5 — Tool and provider contracts

## 5.1 The Tool interface

```python
class SideEffect(StrEnum):
    READ = "read"; WRITE = "write"; DESTRUCTIVE = "destructive"

class Tool(ABC):
    name: ClassVar[str]
    pack: ClassVar[str]
    description: ClassVar[str]
    args_schema: ClassVar[type[BaseModel]]
    side_effect: ClassVar[SideEffect]        # required — no default
    supports_dry_run: ClassVar[bool] = False
    timeout_s: ClassVar[int] = 30

    @abstractmethod
    async def execute(self, ctx: ToolContext, args: BaseModel) -> ToolResult: ...
```

```python
@dataclass
class ToolContext:
    org_id: UUID
    run_id: UUID
    connection: Connection | None     # credential handle, not the value
    dry_run: bool

@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error_class: str | None = None
    def as_text(self) -> str:
        return json.dumps(self.data) if self.ok else f"Tool failed: {self.error_class}. {self.message}"
```

**`side_effect` has no default.** A tool class without it raises at import time, so the process will not start. That is deliberate — a forgotten label is the one that emails four hundred customers.

## 5.2 Registry

```python
class ToolRegistry:
    def register(self, tool: type[Tool]) -> None:
        if not hasattr(tool, "side_effect"):
            raise ConfigError(f"{tool.__name__} must declare side_effect")
        if tool.name in BLOCKED_ACTIONS:
            raise ConfigError(f"{tool.name} is on the catastrophic blocklist")
        self._tools[tool.name] = tool

    def for_employee(self, cfg: EmployeeConfig) -> list[type[Tool]]:
        return [self._tools[n] for n in cfg.enabled_tools if n in self._tools]

    def schemas(self, tools) -> list[dict]:
        return [{"name": t.name, "description": t.description,
                 "parameters": t.args_schema.model_json_schema()} for t in tools]
```

The model only ever sees schemas for tools on **that employee's** allowlist. A tool that is not in the list does not exist as far as the model is concerned — which is the primary injection defence.

## 5.3 Provider interface

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, *, messages, tools, model, temperature, max_tokens) -> LLMReply: ...
    @abstractmethod
    def stream(self, **kw) -> AsyncIterator[LLMChunk]: ...
    @abstractmethod
    def count_tokens(self, messages) -> int: ...

@dataclass
class LLMReply:
    message: Message
    text: str | None
    tool_calls: list[ToolCall]
    usage: Usage              # prompt_tokens, output_tokens
    stop_reason: StopReason   # normalised across providers
```

Two implementations: `GeminiProvider` (native SDK) and `OpenAICompatibleProvider` (Groq, NVIDIA, Ollama, DeepSeek, OpenRouter, Together — one adapter, same wire format).

The interface normalises the four things that genuinely differ: tool-call shape, system-prompt placement, streaming event types, and stop reasons. Everything above `agent/providers/` is provider-agnostic.

## 5.4 Cost

```python
PRICING = {  # USD per 1M tokens — verify at build time, these move
    ("gemini", "gemini-flash"):  Price(input=0.30, output=2.50),
    ("groq",   "llama-70b"):     Price(input=0.59, output=0.79),
}

def cost_usd(provider, model, usage) -> Decimal:
    p = PRICING[(provider, model)]
    return (usage.prompt_tokens * p.input + usage.output_tokens * p.output) / Decimal(1_000_000)
```

With BYOK we cannot see the customer's actual invoice, so every figure is surfaced as **"estimated cost"**. Presenting an estimate as a bill would be dishonest.

---
---

# Part 6 — Policy engine

## 6.1 Resolution order

```python
def evaluate(self, tool_name: str) -> Decision:
    tool = registry.get(tool_name)

    # 1. Catastrophic blocklist — platform-wide, nobody can override
    if tool_name in self.blocked_actions:
        return Decision.BLOCKED

    # 2. Company override, specific tool
    if s := self.org_policies.get(("tool", tool_name)):
        return Decision(s)

    # 3. Company override, whole pack + side effect
    if s := self.org_policies.get(("pack", tool.pack, tool.side_effect)):
        return Decision(s)

    # 4. Platform default, specific tool
    if s := self.defaults.get(("tool", tool_name)):
        return Decision(s)

    # 5. Platform default, pack + side effect
    if s := self.defaults.get(("pack", tool.pack, tool.side_effect)):
        return Decision(s)

    # 6. Safe fallback
    return {READ: Decision.AUTO,
            WRITE: Decision.ASK,
            DESTRUCTIVE: Decision.BLOCKED}[tool.side_effect]
```

**Most specific wins, except the blocklist, which wins absolutely.** Rule 6 means a brand-new tool with no policy configured is safe by default — a new destructive tool is blocked until someone deliberately enables it.

## 6.2 Platform default versus company override

| | Platform Admin | Company Admin |
|---|---|---|
| Sets | The **starting value** for new companies | Their own value, **looser or stricter** |
| Can a company go looser than the default? | — | ✅ Yes |
| Can a company override the blocklist? | — | ❌ No |

The blocklist is intentionally tiny — three entries — and each carries a written reason, so it never looks arbitrary.

## 6.3 Where it is enforced

```python
# worker, before every tool execution — not in the API, not in the UI
decision = ctx.policy.evaluate(call.name)
```

The UI also reads policy, but only to render helpful text. **A screen-level check is a convenience; the worker-level check is the control.** A test calls the API directly, bypassing the UI, to prove the gate holds.

---
---

# Part 7 — Event log and SSE

## 7.1 Event types

| Type | Payload |
|---|---|
| `run_started` | `{employee_version_id, model}` |
| `thinking` | `{step}` |
| `llm_call` | `{model, prompt_tokens, output_tokens, cost_usd}` |
| `tool_call` | `{tool, args_redacted}` |
| `tool_result` | `{tool, ok, summary}` |
| `tool_blocked` | `{tool, reason}` |
| `approval_requested` | `{approval_id, tool}` |
| `approval_decided` | `{approval_id, decision, by}` |
| `branch_taken` *(P7)* | `{from, to, condition}` |
| `delegated_to` *(P7)* | `{specialist_employee_id}` |
| `run_finished` | `{status, cost_usd, step_count}` |

## 7.2 Writing

```python
class EventWriter:
    async def append(self, type: str, payload: dict) -> None:
        self._seq += 1
        await self.repo.insert(run_id=self.run_id, seq=self._seq,
                               type=type, payload=redact(payload))   # Postgres first
        await self.redis.publish(f"run:{self.run_id}",
                                 json.dumps({"seq": self._seq, ...}))  # Redis second
```

**Order matters.** Persist then publish. If Redis publish fails, the event still exists and the client recovers it on reconnect. If we published first and the insert failed, a client would see an event that is not in the permanent record.

## 7.3 SSE protocol

```
GET /api/v1/runs/{id}/events
Last-Event-ID: 12          ← optional, for resume

id: 13
event: tool_call
data: {"seq":13,"tool":"get_issue","args":{"number":42}}

: keepalive               ← comment frame every 15 s
```

```python
async def stream(run_id: UUID, last_id: int | None):
    for e in await repo.events_after(run_id, last_id or 0):   # 1. replay the gap
        yield sse(e)
    async for msg in redis.subscribe(f"run:{run_id}"):        # 2. then live
        yield sse(msg)
        if msg["type"] == "run_finished":
            break
```

Replay-then-subscribe closes the gap. A brief overlap is possible, so the client de-duplicates on `seq`, which is cheap and idempotent.

## 7.4 Redaction

```python
REDACT_KEYS = {"api_key", "token", "password", "secret", "authorization", "credential"}
```

Applied on write, so a secret never enters the table in the first place. Redacting on read would leave the plaintext permanently in the database.

---
---

# Part 8 — Worker and queue

## 8.1 Job types

| Job | Trigger | Schedule |
|---|---|---|
| `run_task` | Task created, or approval granted | On demand |
| `expire_approvals` | — | Every 5 min |
| `reap_dead_runs` | — | Every 1 min |
| `summarise_run` | Run completed | On demand |
| `reembed_memories` | Embedding provider changed | On demand |
| `cleanup_retention` | — | Daily |

## 8.2 Concurrency

```python
class WorkerSettings:
    max_jobs = 1 if settings.SLOW_MODE else 10    # SLOW_MODE on free tiers
    job_timeout = 900
    keep_result = 3600
```

**Why `max_jobs = 1` by default:** one task makes 10–15 model calls. Two concurrent tasks will exceed a free-tier per-minute limit. The queue lengthens instead of tasks failing, which is the better failure mode.

## 8.3 Retry classification

```python
TRANSIENT = {RateLimited, Timeout, ServerError, ConnectionError}   # retry with backoff
PERMANENT = {Unauthorized, NotFound, ValidationError, PolicyBlocked}  # fail immediately

delay = min(2 ** attempt + random.uniform(0, 1), 60)   # jitter avoids a thundering herd
```

Retrying a 401 is pointless — the key will still be wrong in four seconds. Failing fast on a 429 is equally pointless. Classification is what makes retries useful rather than noisy.

## 8.4 Dead-worker recovery

```python
async def reap_dead_runs():
    stale = await repo.runs_with_heartbeat_older_than(seconds=120)
    for run in stale:
        if run.has_checkpoint and run.attempt < MAX_ATTEMPTS:
            await queue.enqueue("run_task", run.id)        # resume from checkpoint
        else:
            await repo.fail(run.id, "worker_lost")
```

Without this, a `docker kill` leaves a run marked `running` forever. The heartbeat makes it detectable and the checkpoint makes it recoverable.

## 8.5 Idempotency

```python
key = sha256(f"{run_id}:{step}:{tool}:{canonical(args)}")
if existing := await repo.find_invocation(key):
    return existing.result          # retry must not create a second pull request
```

---
---

# Part 9 — Encryption

## 9.1 Envelope scheme

```
master key (env var, or KMS in production)
   └── wraps → per-company data key (DEK), stored wrapped
                  └── encrypts → credentials, API keys, OAuth secrets
```

```python
def encrypt_for_org(org_id: UUID, plaintext: str) -> bytes:
    dek = unwrap(load_wrapped_dek(org_id), master_key())
    return AESGCM(dek).encrypt(os.urandom(12), plaintext.encode(), aad=str(org_id).encode())
```

| Property | Benefit |
|---|---|
| Per-company DEK | Compromising one company does not expose the others |
| `aad = org_id` | Ciphertext cannot be moved between companies — decryption fails |
| AES-GCM | Authenticated: tampering is detected, not silently decrypted |
| Master key rotatable | Rewrap DEKs without touching a single credential row |

## 9.2 The access rules, as code

```python
# There is no function that returns a decrypted credential to an HTTP response.
# The only consumer is the worker, at call time:

async def call_with_credential(conn_id: UUID, request: Request) -> Response:
    secret = decrypt_for_org(org_id, load_ciphertext(conn_id))
    request.headers["Authorization"] = f"Bearer {secret}"
    try:
        return await http.send(request)
    finally:
        del secret
```

A test asserts that no response model anywhere in the OpenAPI schema contains a field whose name matches the secret-key pattern. This catches the mistake at the contract level rather than hoping reviewers notice.

---
---

# Part 10 — Error taxonomy and testing

## 10.1 Error hierarchy

```
AppError
├── AuthError            → 401
├── PermissionError      → 403
├── NotFoundError        → 404      ← also used for cross-tenant access
├── ValidationError      → 422
├── ConflictError        → 409      (e.g. employee limit reached)
├── RateLimitError       → 429
└── ToolError                       ← never reaches HTTP; returned to the model
    ├── ToolTimeout
    ├── ToolUnauthorized
    ├── ToolNotFound
    └── ToolUpstreamError
```

`ToolError` is deliberately outside the HTTP branch. Tool failures are **information for the model**, not responses to a user.

## 10.2 Test suites

| Suite | Scope | Runs | Gate |
|---|---|---|---|
| Unit | Services, policy resolution, cost maths, budget | Every commit | ≥80% on `services/`, `agent/`, `core/` |
| Integration | Routes against real Postgres + Redis (testcontainers) | Every commit | All pass |
| **Isolation** | Every route, cross-tenant → 404; every model has `org_id` | Every commit | **100%** |
| **Permissions** | Every route has a guard; role matrix enforced | Every commit | **100%** |
| **Secrets** | Grep every response and log line for key material | Every commit | **Zero hits** |
| Evals (replay) | 10 golden tasks from cassettes | Every commit | ≥8/10 |
| Evals (live) | Same tasks, real providers | Nightly | Tracked over time |
| **Red team** | 15 injection payloads in tool output | Pre-release | **Zero unauthorised calls** |
| E2E (Playwright) | Invite → employee → task → PR | Pre-merge | All pass |
| Chaos | 30% random tool failure | Nightly | Correct, or clean failure |

## 10.3 Cassettes

```python
@pytest.fixture
def llm(request):
    path = CASSETTES / f"{request.node.name}.json"
    return ReplayProvider(path) if path.exists() else RecordingProvider(path, RealProvider())
```

Committed to the repository, so CI runs with **no API key, no cost and no rate limit**, and the same input always produces the same result. This is what makes testing a non-deterministic system possible at all.

## 10.4 Eval assertions

Each golden task asserts a **fact**, never text:

```python
GOLDEN = [
    Task("Fix issue #1", lambda r: pr_exists(r) and "LoginButton.tsx" in pr_files(r)),
    Task("Comment on #2", lambda r: comment_exists(2)),
    Task("Find the login bug", lambda r: "LoginButton.tsx" in r.output),
    Task("Fix issue #7 (impossible)", lambda r: r.admitted_failure and not pr_exists(r)),
]
```

The last one is the most valuable test in the suite. **An agent that admits it cannot do something is worth far more than one that fabricates a plausible answer** — and it is the behaviour most likely to regress silently when prompts change.

---

*End of Low Level Design.*
