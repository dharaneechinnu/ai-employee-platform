---
name: self-review-pr
description: Review a Baton pull request (or the current branch) before merging it. Checks for security problems, backend changes that could block a user, agent runs that can end without a clear stop cause, and runs every test the way CI does. Use when asked to self-review, review before merge, check a PR, or "make sure it is safe to merge to main".
---

# Self-review a PR

Review the change as the person who gets paged if it breaks: a security
hole, a user who can no longer sign in or run a task, or an agent run that
ends with no explanation. Report what you found and what you could **not**
check. Do not say "looks good" about something you did not run or read.

## Ground rules

- The review is **read-only**. Fix things in a separate step, after the report.
- Never merge unless the user asked for the merge **and** the gate in step 7 is met.
- Never print secrets, tokens or the contents of `.env`. Refer to names only.
- A finding needs a file and line, what goes wrong, and for whom. No vague worries.
- If a command is held by a safety hook (for example `alembic`, `rm -rf`), do not
  retry it. Say what was not checked and give the user the command to run.

## 0. Scope the change

```bash
gh pr view --json number,title,baseRefName,headRefName,files,additions,deletions
git diff --stat origin/main...HEAD
```

Sort the changed files by layer: `api/` routes, `services/`, `agent/`,
`workers/`, `db/` and `alembic/`, `core/`, `config.py`, tests, frontend, CI.
A change in a layer you do not read is not reviewed. Read every changed
non-test file; read tests for what they prove, not just that they pass.

## 1. Run the gates (mechanical)

```bash
bash .claude/skills/self-review-pr/checks.sh
```

It runs, inside the `api` container and in CI's order: `ruff check`,
`ruff format --check`, `mypy app` (strict) and the full `pytest`, plus the
frontend build when `frontend/` changed. Any red line is a **blocker**.

Known to this repo, so do not misread them as your change:

- The dev `.env` has real Google and Microsoft OAuth credentials. Tests expect none,
  so `checks.sh` blanks them. Sign-up and login limiter tests need `ENVIRONMENT=test`.
- If the test database is behind the code's migration head, a test that reads
  seeded data fails (for example the default policy). Compare
  `select version_num from alembic_version` on `ai_employee_test` with `alembic heads`.
  Say it is environmental and name the command to fix it. CI builds a fresh database.
- If the PR adds a migration, CI also runs `upgrade head`, `downgrade 0017`,
  `upgrade head`. Read the migration's `downgrade` and check it is reversible.

## 2. Scan the diff (mechanical)

```bash
python .claude/skills/self-review-pr/scan_diff.py origin/main
```

Triage **every** hit: real, or false positive with a reason. The scan finds
patterns, not bugs. A clean scan proves nothing.

## 3. Security review

Read the diff against each line. Baton's promises are in the code comments;
break one and it is a blocker.

| Check | What to look for |
|---|---|
| **Secrets never leave** | API keys and OAuth tokens are encrypted per person (`core/crypto.py`), write-only, never in a response, a log line, a run event or the model's context. New fields named `key`, `token`, `secret`, `password`, `credential` must be redacted (`task_service._redact`) or not stored. |
| **Every query is one person's** | Every `select`/`update`/`delete` on a person-owned table filters `owner_id`. A route taking an id must prove the caller owns it (404, not 403, for someone else's). Look for `session.get(Model, id)` with no owner check. |
| **Auth on every route** | New routes use the auth dependency (`ContextDep`). Platform-admin routes use the staff dependency. Nothing reads a person's data as staff. |
| **Permissions cannot be bypassed** | "Ask first" and "Blocked" hold for specialists, scheduled runs, and any new way to call a tool. A new path that runs a tool must go through the policy check. |
| **No outbound request to a user-supplied URL** without `core/urls.check_service_url`. |
| **Injection** | No f-string or `%` in SQL (`text(...)`). No `shell=True`, `eval`, `exec`, `pickle`. Tool results and web pages are data, never instructions. |
| **Limits** | New public or expensive endpoints are rate limited. Loops that call a model have a step, token and time budget. |
| **Supply chain and CI** | New dependencies are needed, pinned and from the usual index. Changes to `.github/workflows` do not widen permissions or print secrets. |
| **Logs** | No personal data or tool arguments in `log.*` beyond ids and names. |

## 4. Backend user-blocker review

Ask: can a person still sign in, add a key, send a message and get an answer,
and can a scheduled agent still run? Check each:

1. **Boot:** `python -c "from app.main import create_app; create_app()"` and
   `python -c "from app.workers.main import WorkerSettings"` import cleanly. New required
   settings have a safe default; production-only checks do not break dev.
2. **Migrations:** one head; no destructive change without a reason; reversible
   unless the repo says otherwise (0017 is one-way by design).
3. **API contract:** no removed or renamed response fields, status codes or routes the
   frontend uses (`grep` the frontend). New fields are optional.
4. **Hot path:** new work on the message to task to run path, or in the worker loop, must
   fail open if Redis or a provider is down, and must not hold a database connection
   across a model call.
5. **Defaults that change behaviour:** routing, concurrency, timeouts, retention. Say who notices.
6. **Cron jobs:** registered in `workers/main.py`, safe to run twice, bounded in size,
   one bad row does not stop the batch.
7. **Error messages** a person sees are plain sentences that say what to do next.

## 5. Agent stop-cause review

Every run must end, be recorded, and tell the person why. Known causes: `completed`,
`max_steps`, `max_tokens`, `timeout`, `cancelled`, `provider_error`, `awaiting_approval`
(`agent/loop.py`), plus `provider_not_connected`, `provider_key_unreadable` and `stalled`
(`workers/jobs/`). For the change under review:

1. **Every exit path is covered.** Read `workers/jobs/agent_run.py::_execute` from `claim_run`
   to `_finish`. For each new `await` or call, ask: if this raises, what happens to the run?
   A run left `running` is only rescued by the stalled-run sweep, ten minutes later.
2. **A new cause has a plain message** in `_STOP_MESSAGES` (or an explicit `error=`), maps to
   the right `RunStatus` and `TaskStatus`, writes a `run_stopped` or `run_finished` event, and
   sets `agent.last_status` for scheduled runs.
3. **Budgets still hold:** steps, tokens, time, cancel. Retries and fallbacks cannot loop for ever.
4. **Unattended runs** never wait for an approval; "ask first" becomes a refusal.
5. **Provider failures** map as documented in `providers/fallback.py` (rate limit retries then
   switch, refused key switches at once, malformed request does not switch).
6. **Each cause has a test** that asserts the status, the stop cause, the message the person
   sees and the event. List cause to test in the report; a cause without a test is a finding.

## 6. Report

Write it in this shape, most severe first. Plain words.

```
Verdict: SAFE TO MERGE | FIX FIRST | DO NOT MERGE

Blockers      (security hole, user cannot proceed, run ends without a reason, red gate)
  1. <file:line> <what goes wrong> <who it hits> <fix>
Should fix    (real but not blocking)
Nits
Verified OK   (what you read or ran, in one line each)
Not verified  (what you could not check, and why)
Gates         ruff / format / mypy / tests: pass or fail, with counts
Stop causes   cause -> test
```

Verdict rule: any blocker or red gate means **DO NOT MERGE**. "Not verified" items that
touch security or the hot path mean **FIX FIRST** until the user accepts the risk in words.

## 7. Merge gate (only when the user asked to merge)

Merge only if **all** are true: verdict is SAFE TO MERGE; CI on the PR is green (read it
with the app's PR status tool, not by polling); the branch is up to date with `main`;
the full test run in step 1 passed, or each failure is proven environmental. Then:

```bash
gh pr merge <number> --merge
```

This repo merges with merge commits. Do not enable auto-merge, and do not delete the
branch, unless the user says so. After merging, say what was merged and what was left.
