#!/usr/bin/env bash
# Runs the gates CI runs, inside the `api` container, and prints a summary.
# Usage: bash .claude/skills/self-review-pr/checks.sh [base-ref]   (default origin/main)
#
# It does not run `alembic`: a safety hook may hold it. If the PR adds a
# migration, run the upgrade/downgrade round trip yourself (see SKILL.md).
# The dev .env holds real OAuth credentials that the tests expect to be unset,
# so they are blanked here. ENVIRONMENT=test keeps the rate limiters in memory.

set -u
BASE="${1:-origin/main}"
cd "$(git rev-parse --show-toplevel)" || exit 2

results=()
failed=0

run() { # name, command...
  local name="$1"; shift
  echo; echo "=== $name"
  if "$@"; then results+=("PASS  $name"); else results+=("FAIL  $name"); failed=1; fi
}

api() { docker compose exec -T "$@"; }

run "ruff check"        api api ruff check .
run "ruff format check" api api ruff format --check .
run "mypy app (strict)" api api mypy app
run "pytest (all)"      api -e ENVIRONMENT=test \
                            -e GOOGLE_CLIENT_ID= -e GOOGLE_CLIENT_SECRET= \
                            -e MICROSOFT_CLIENT_ID= -e MICROSOFT_CLIENT_SECRET= \
                            api python -m pytest -q -p no:cacheprovider

if git diff --name-only "$BASE"...HEAD | grep -q '^frontend/'; then
  run "frontend build" bash -c 'cd frontend && npm run build'
else
  results+=("SKIP  frontend build (no frontend changes)")
fi

if git diff --name-only "$BASE"...HEAD | grep -q '^backend/alembic/versions/'; then
  results+=("TODO  migrations changed: run upgrade head, downgrade 0017, upgrade head yourself")
fi

echo; echo "=== summary vs $BASE"
printf '%s\n' "${results[@]}"
exit "$failed"
