"""The GitHub pack against a pretend GitHub API."""

from __future__ import annotations

import base64
import json
import uuid
from typing import Any

import httpx
import pytest

import app.agent.tools.packs._http as http_helper
from app.agent.tools.base import Grant, SideEffect, ToolContext
from app.agent.tools.registry import BLOCKED_ACTIONS, registry

REPO = "acme/api"


class FakeGitHub:
    def __init__(self) -> None:
        self.files: dict[str, str] = {"README.md": "# API\n", "app/main.py": "print('hi')\n"}
        self.branches = {"main": "sha-main"}
        self.calls: list[tuple[str, str, Any]] = []
        self.token_ok = True

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if not self.token_ok:
            return httpx.Response(401, json={"message": "Bad credentials"})
        assert request.headers["accept"].startswith("application/vnd.github")

        if path == "/user/repos":
            return httpx.Response(
                200, json=[{"full_name": REPO, "default_branch": "main", "private": True}]
            )
        if path == f"/repos/{REPO}":
            return httpx.Response(200, json={"full_name": REPO, "default_branch": "main"})
        if path.startswith(f"/repos/{REPO}/contents/"):
            file = path.split("/contents/", 1)[1]
            if request.method == "PUT":
                self.files[file] = base64.b64decode(body["content"]).decode()
                return httpx.Response(201, json={})
            if file == "app":
                return httpx.Response(200, json=[{"name": "main.py", "type": "file"}])
            if file not in self.files:
                return httpx.Response(404, json={"message": "Not Found"})
            content = base64.b64encode(self.files[file].encode()).decode()
            return httpx.Response(
                200,
                json={
                    "path": file,
                    "size": 10,
                    "encoding": "base64",
                    "content": content,
                    "sha": "f1",
                },
            )
        if path == f"/repos/{REPO}/pulls/7":
            return httpx.Response(
                200,
                json={
                    "title": "Fix login",
                    "user": {"login": "asha"},
                    "base": {"ref": "main"},
                    "head": {"ref": "fix/login"},
                    "body": "Fixes #3",
                },
            )
        if path == f"/repos/{REPO}/pulls/7/files":
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "app/auth.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                        "patch": "@@ -1 +1 @@\n-old\n+new",
                    }
                ],
            )
        if path == f"/repos/{REPO}/actions/runs":
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        {
                            "id": 11,
                            "name": "CI",
                            "head_branch": "main",
                            "head_sha": "abc1234567",
                            "status": "completed",
                            "conclusion": "failure",
                            "html_url": "u",
                        },
                        {
                            "id": 10,
                            "name": "CI",
                            "head_branch": "main",
                            "head_sha": "abc0000000",
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "u",
                        },
                    ]
                },
            )
        if path == f"/repos/{REPO}/actions/runs/11/jobs":
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "name": "test",
                            "conclusion": "failure",
                            "steps": [
                                {"name": "pytest", "conclusion": "failure"},
                                {"name": "setup", "conclusion": "success"},
                            ],
                        }
                    ]
                },
            )
        if path == f"/repos/{REPO}/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.branches["main"]}})
        if path == f"/repos/{REPO}/git/refs":
            name = body["ref"].removeprefix("refs/heads/")
            if name in self.branches:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.branches[name] = body["sha"]
            return httpx.Response(201, json={})
        if path == f"/repos/{REPO}/pulls" and request.method == "POST":
            return httpx.Response(
                201, json={"number": 8, "html_url": "https://github.com/acme/api/pull/8"}
            )
        if path == f"/repos/{REPO}/issues/3/comments":
            return httpx.Response(201, json={"html_url": "https://github.com/acme/api/issues/3#c"})
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    fake = FakeGitHub()
    monkeypatch.setattr(
        http_helper,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)),
    )
    return fake


def ctx(dry_run: bool = False) -> ToolContext:
    return ToolContext(
        owner_id=uuid.uuid4(), dry_run=dry_run, grants={"github": Grant("ghp_test_token")}
    )


async def run(name: str, args: dict[str, Any], dry_run: bool = False) -> Any:
    tool = registry.get(name)
    assert tool is not None, name
    return await tool().execute(ctx(dry_run), args)


def test_reading_is_free_and_changing_asks_and_nothing_merges_or_deletes() -> None:
    pack = {t.name: t for t in registry.all() if t.pack == "github"}
    reads = {n for n, t in pack.items() if t.side_effect is SideEffect.READ}
    writes = {n for n, t in pack.items() if t.side_effect is SideEffect.WRITE}
    assert reads == {
        "github_list_repos",
        "github_search_code",
        "github_read_file",
        "github_list_issues",
        "github_read_issue",
        "github_pr_diff",
        "github_list_commits",
        "github_ci_status",
    }
    assert writes == {"github_comment", "github_create_issue", "github_propose_change"}
    assert not any("merge" in n or "delete" in n for n in pack)
    assert {"delete_repository", "force_push"} <= set(BLOCKED_ACTIONS)


async def test_reads_a_file_and_lists_a_folder(github: FakeGitHub) -> None:
    file = await run("github_read_file", {"repo": REPO, "path": "app/main.py"})
    assert file.ok and file.data["content"] == "print('hi')\n"
    folder = await run("github_read_file", {"repo": "https://github.com/acme/api", "path": "app"})
    assert folder.data["entries"] == [{"name": "main.py", "type": "file"}]


async def test_a_bad_repo_name_is_explained(github: FakeGitHub) -> None:
    result = await run("github_read_file", {"repo": "not a repo"})
    assert result.error_class == "invalid_arguments"
    assert "owner/name" in (result.message or "")


async def test_reviews_a_pull_request_diff(github: FakeGitHub) -> None:
    diff = await run("github_pr_diff", {"repo": REPO, "number": 7})
    assert diff.data["head"] == "fix/login"
    assert diff.data["files"][0]["patch"].endswith("+new")


async def test_ci_status_names_the_failing_step(github: FakeGitHub) -> None:
    ci = await run("github_ci_status", {"repo": REPO, "branch": "main"})
    failed = ci.data["runs"][0]
    assert failed["conclusion"] == "failure"
    assert failed["failed_jobs"] == [{"job": "test", "failed_steps": ["pytest"]}]
    assert "failed_jobs" not in ci.data["runs"][1]


async def test_a_change_is_proposed_as_a_pull_request_on_a_new_branch(github: FakeGitHub) -> None:
    result = await run(
        "github_propose_change",
        {
            "repo": REPO,
            "title": "Greet properly",
            "branch": "fix/greeting",
            "files": [
                {"path": "app/main.py", "content": "print('hello')\n"},
                {"path": "docs/notes.md", "content": "new\n"},
            ],
        },
    )
    assert result.ok, result.message
    assert result.data["pull_request"] == 8 and result.data["into"] == "main"
    assert github.branches["fix/greeting"] == "sha-main"
    assert github.files["app/main.py"] == "print('hello')\n"
    puts = [c for c in github.calls if c[0] == "PUT"]
    assert puts[0][2]["branch"] == "fix/greeting"
    assert puts[0][2]["sha"] == "f1"  # an existing file is updated, not duplicated
    assert "sha" not in puts[1][2]  # a new file is created
    assert not any(c[0] == "PUT" and c[2].get("branch") == "main" for c in github.calls)


async def test_the_default_branch_is_never_written(github: FakeGitHub) -> None:
    result = await run(
        "github_propose_change",
        {"repo": REPO, "title": "x", "branch": "main", "files": [{"path": "a", "content": "b"}]},
    )
    assert result.error_class == "not_allowed"
    assert not any(c[0] in ("PUT", "POST") for c in github.calls)


async def test_an_existing_branch_name_is_reported(github: FakeGitHub) -> None:
    github.branches["fix/greeting"] = "old"
    result = await run(
        "github_propose_change",
        {
            "repo": REPO,
            "title": "x",
            "branch": "fix/greeting",
            "files": [{"path": "a", "content": "b"}],
        },
    )
    assert result.error_class == "branch_exists"


async def test_dry_run_changes_nothing(github: FakeGitHub) -> None:
    result = await run(
        "github_propose_change",
        {"repo": REPO, "title": "x", "branch": "fix/y", "files": [{"path": "a", "content": "b"}]},
        dry_run=True,
    )
    assert result.data["dry_run"] is True
    assert not any(c[0] in ("PUT", "POST") for c in github.calls)
    comment = await run("github_comment", {"repo": REPO, "number": 3, "body": "hi"}, dry_run=True)
    assert comment.data["dry_run"] is True


async def test_an_expired_token_says_to_reconnect(github: FakeGitHub) -> None:
    github.token_ok = False
    result = await run("github_list_repos", {})
    assert result.error_class == "auth_expired"
