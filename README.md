# AI Employee Platform

A platform where business teams — developers, operations, sales, HR — create and manage their own **AI Employees**: persistent AI workers with a role, instructions, scoped tool access and permission boundaries.

> **Status:** backend built through Phase 7. 102 tests passing, 59 endpoints live.

## What problem this solves

Every team has repetitive work that needs real tool access to be useful: triaging bug reports, updating records, drafting replies, pulling reports. A normal AI chatbot cannot do it, because it:

- forgets everything when the chat closes
- cannot reach your real apps
- cannot be trusted with actions that have consequences

This platform fixes all three.

## How it works

```
Company Admin  →  creates an AI Employee (name, role, instructions, tools)
Member         →  gives it a task: "Look at bug #42 and fix it"
The platform   →  runs it async, streams progress live, logs every step
Result         →  a real pull request, with full audit trail and cost per task
```

## Planned stack

| Layer | Technology |
|---|---|
| Frontend | React · TypeScript · Tailwind CSS |
| Backend | Python · FastAPI · SQLAlchemy 2.0 (async) |
| Database | PostgreSQL + pgvector |
| Queue | Redis + arq workers |
| AI | Gemini / OpenAI / Groq (pluggable, BYOK) · LangGraph (Phase 7) |
| Deployment | Docker Compose |

## Key design decisions

| Decision | Why |
|---|---|
| **Multi-tenant with `org_id` on every table** | Enforced in one repository layer, plus a test that fails if any table omits it |
| **BYOK** (each company brings their own AI API key) | Zero platform cost per customer; no customer can inflate someone else's bill |
| **Tools declare a side-effect label** (read / write / destructive) | Permission policy and human approval gates are enforceable, not advisory |
| **Append-only event log per run** | Live streaming, reconnect-safe, replayable, auditable — all from one property |
| **Credentials never enter the model context** | Prompt injection cannot leak a key that was never there |
| **Platform Admin cannot read customer data or keys** | The API endpoint does not exist, so it cannot be misused |
| **Eval harness with a pass-rate gate** | An agent at 70% is unusable, because the user cannot tell which 70% |

## Documentation

| Document | What it covers | Size |
|---|---|---|
| 🏗️ **[High Level Design](docs/HLD.md)** | System context, containers, domain model, core flows, security architecture, scalability, risks. 14 diagrams. | ~970 lines |
| 🔧 **[Low Level Design](docs/LLD.md)** | Folder layout, full database schema, API specification, agent loop, tool and provider contracts, policy engine, SSE protocol, encryption, testing strategy. | ~1,070 lines |
| 📋 **[Implementation Plan](docs/IMPLEMENTATION_PLAN.md)** | Phase-by-phase roadmap in plain English, with decisions, risks and a completion checklist per phase. | ~2,930 lines |

Read them in that order: **HLD → LLD → Plan**. The HLD fixes the big decisions, the LLD details them, and the plan sequences the work.

## Roadmap

| Phase | Name | Status |
|---|---|---|
| 0 | Foundation and walking skeleton | ✅ Built |
| 1 | Auth, companies, Platform Admin with 2FA | ✅ Built |
| 2 | AI Employee configuration and versioning | ✅ Built |
| 3 | LLM providers, tool registry, agent loop | ✅ Built |
| 4 | 🎯 **MVP** — async tasks, worker, live streaming | ✅ Built |
| 5 | Permission policy, approvals, email and SQL tools | ✅ Built |
| 6 | Memory, pluggable embeddings, hybrid search | ✅ Built |
| 7 | Parallel execution, bounded delegation | ✅ Built |
| 8–10 | Reliability · security and cost · production readiness | 🗒️ Outlined, not built |

**Not built, and deliberately so:** the LangGraph migration from Phase 7.
Its dependency footprint was measured at 25 transitive packages — including
a second HTTP client and a telemetry SDK — to replace a working loop with
102 tests behind it. What it would add here is durable checkpointing for
pausing inside a branch; the single-path pause already works and is tested.

## Running it

```bash
docker compose up --build        # all five services
make test                        # 102 tests
make lint                        # ruff + mypy strict
```

Host ports are **5433** (Postgres) and **6380** (Redis), not the defaults, so
the containers do not clash with a database already installed on your machine.

Create the first platform admin:

```bash
cd backend && python -m scripts.bootstrap_admin --email you@example.com
```

## What is verified

| Check | Result |
|---|---|
| Tests | 102 passing — unit, tenant isolation, and integration against real Postgres |
| Types | mypy **strict**, 72 files, zero errors |
| Lint | ruff with bugbear, bandit, async and blind-except rules, zero suppressions |
| Migrations | 6, each verified forward *and* backward |
| Live stack | `docker compose up` → 4 healthy services, 59 endpoints |
