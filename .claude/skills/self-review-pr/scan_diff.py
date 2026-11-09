"""Scan the lines a PR adds for patterns that need a human look.

Usage: python .claude/skills/self-review-pr/scan_diff.py [base-ref]   (default origin/main)

This finds patterns, not bugs. Every hit must be triaged as real or a false
positive. A clean scan proves nothing. Exit code 1 when there is a HIGH hit.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

BASE = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
SELF = ".claude/skills/self-review-pr/"


@dataclass(frozen=True)
class Rule:
    level: str  # HIGH, MED, INFO
    pattern: re.Pattern[str]
    message: str
    paths: tuple[str, ...] = ("",)  # the file path must contain one of these
    skip_tests: bool = True


SECRET_NAME = r"(api[_-]?key|secret|token|password|credential|authorization)"

RULES = [
    Rule("HIGH", re.compile(r"verify\s*=\s*False"), "TLS verification turned off"),
    Rule("HIGH", re.compile(r"shell\s*=\s*True"), "shell=True: command injection risk"),
    Rule("HIGH", re.compile(r"(?<![\w.])(eval|exec)\("), "eval/exec on a string"),
    Rule("HIGH", re.compile(r"pickle\.loads?\("), "pickle on untrusted data"),
    Rule("HIGH", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key in the diff"),
    Rule("HIGH", re.compile(r"\b(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{24,}|ghp_[A-Za-z0-9]{30,})"), "looks like a real key"),
    Rule(
        "HIGH",
        re.compile(rf"{SECRET_NAME}\w*\s*=\s*[\"'][^\"'\s]{{12,}}[\"']", re.I),
        "a literal that looks like a secret",
    ),
    Rule("HIGH", re.compile(r"\btext\(\s*f[\"']"), "f-string inside SQL text(): injection risk"),
    Rule(
        "MED",
        re.compile(rf"\blog(?:ger)?\.\w+\(.*{SECRET_NAME}", re.I),
        "a log line that mentions a secret-like name: check the value is not logged",
        ("backend/app",),
    ),
    Rule("MED", re.compile(r"^\s*print\("), "print() in app code", ("backend/app",)),
    Rule("MED", re.compile(r"except\s+(Exception|BaseException)\s*:\s*$"), "broad except: check it is not hiding a failure", ("backend/app",)),
    Rule("MED", re.compile(r"\b(httpx|requests|aiohttp)\.[\w.]*(get|post|put|delete|request|AsyncClient)\b"), "outbound HTTP: is the URL user-supplied? use check_service_url", ("backend/app",)),
    Rule("MED", re.compile(r"allow_private_urls|ALLOW_PRIVATE_URLS"), "private URL guard touched", ("backend/app",)),
    Rule("MED", re.compile(r"\bdisable\w*\b.*\b(auth|csrf|cors|rate)", re.I), "something security-related is being switched off", ("backend/app",)),
    Rule("INFO", re.compile(r"stop_cause\s*=\s*[\"'](\w+)[\"']"), "stop cause literal: needs a plain message and a test", ("backend/app",)),
    Rule("INFO", re.compile(r"cron\("), "cron job: bounded, safe to run twice, registered?", ("backend/app/workers",)),
]

ROUTE = re.compile(r"^\s*@router\.(get|post|put|patch|delete)\(")
AUTH_DEP = re.compile(r"ContextDep|StaffDep|PlatformDep|Depends\(|SessionDep|Security\(")
SELECT_OWNED = re.compile(r"\b(select|delete|update)\(\s*(?!func\b)([A-Z]\w+)")


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    if out.returncode:
        sys.exit(out.stderr.strip() or "git failed")
    return out.stdout


def added_lines() -> list[tuple[str, int, str]]:
    """(path, line number in the new file, text) for every added line."""
    rows: list[tuple[str, int, str]] = []
    path, line = "", 0
    for raw in git("diff", "--unified=0", "--no-color", f"{BASE}...HEAD").splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            rows.append((path, line, raw[1:]))
            line += 1
    return rows


def is_test(path: str) -> bool:
    return "/tests/" in path or path.startswith("tests/") or ".test." in path


def main() -> int:
    hits: list[tuple[str, str, int, str, str]] = []
    rows = added_lines()
    by_file: dict[str, list[tuple[int, str]]] = {}
    for path, n, text in rows:
        by_file.setdefault(path, []).append((n, text))
        if path.startswith(SELF):
            continue  # this file's own rules quote the patterns it looks for
        if not path.endswith((".py", ".ts", ".tsx", ".yml", ".yaml", ".sh", ".toml", ".json")):
            continue
        for rule in RULES:
            if rule.skip_tests and is_test(path):
                continue
            if not any(p in path for p in rule.paths):
                continue
            if rule.pattern.search(text):
                hits.append((rule.level, path, n, rule.message, text.strip()[:110]))

    # Routes with no auth dependency within the next few added lines.
    for path, lines in by_file.items():
        if not path.endswith(".py") or "/routes/" not in path:
            continue
        for i, (n, text) in enumerate(lines):
            if ROUTE.search(text):
                window = " ".join(t for _, t in lines[i : i + 8])
                if not AUTH_DEP.search(window):
                    hits.append(("MED", path, n, "new route with no auth dependency in view: confirm it is meant to be public", text.strip()[:110]))

    # Queries on a model with no owner_id nearby.
    for path, lines in by_file.items():
        if not path.endswith(".py") or "/backend/app/" not in "/" + path or is_test(path):
            continue
        for i, (n, text) in enumerate(lines):
            if SELECT_OWNED.search(text):
                window = " ".join(t for _, t in lines[i : i + 6])
                if "owner_id" not in window and "id ==" not in window:
                    hits.append(("INFO", path, n, "query with no owner_id nearby: confirm it is scoped to one person", text.strip()[:110]))

    # Files that need a deeper human look.
    for path in git("diff", "--name-only", f"{BASE}...HEAD").splitlines():
        if path.startswith("backend/alembic/versions/"):
            hits.append(("INFO", path, 0, "new migration: check downgrade, one head, no data loss", ""))
        if path in ("backend/pyproject.toml", "frontend/package.json"):
            hits.append(("INFO", path, 0, "dependencies changed: needed, pinned, from the usual index?", ""))
        if path.startswith(".github/workflows/"):
            hits.append(("MED", path, 0, "CI workflow changed: permissions, secrets, triggers", ""))

    order = {"HIGH": 0, "MED": 1, "INFO": 2}
    hits.sort(key=lambda h: (order[h[0]], h[1], h[2]))
    for level, path, n, message, text in hits:
        where = f"{path}:{n}" if n else path
        print(f"{level:<4} {where}  {message}")
        if text:
            print(f"       {text}")
    counts = {k: sum(1 for h in hits if h[0] == k) for k in order}
    print(f"\n{len(rows)} added lines scanned vs {BASE}: {counts['HIGH']} high, {counts['MED']} medium, {counts['INFO']} info")
    return 1 if counts["HIGH"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
