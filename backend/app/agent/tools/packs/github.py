"""GitHub: the developer's pack.

Reading is most of the job: find a repository, search its code, read a
file, look at issues and pull requests, review a pull request's diff,
see what changed, and find out why CI is red.

Changing things follows one rule: **never touch the default branch**.
A code change is proposed as a new branch and a pull request, which a
person reviews and merges. There is deliberately no merge tool, and
deleting a repository or force-pushing are on the platform-wide
blocklist, so no permission setting can turn them on.

Connected with a fine-grained personal access token, so the person
chooses exactly which repositories and permissions the AI gets; a
read-only token makes every write tool fail harmlessly.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.agent.tools.base import SideEffect, ToolContext, ToolResult
from app.agent.tools.packs._http import ApiError, ApiTool, clip, request
from app.agent.tools.registry import register

API = "https://api.github.com"
HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
# A diff is read by a model; past this it is noise that crowds out the rest.
PATCH_CHARS = 4_000
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")


async def gh(ctx: ToolContext, method: str, path: str, **kwargs: Any) -> Any:
    headers = {**HEADERS, **kwargs.pop("headers", {})}
    return await request(ctx, method, f"{API}{path}", headers=headers, **kwargs)


class RepoArgs(BaseModel):
    repo: str = Field(description="owner/name, e.g. octocat/hello-world")

    @field_validator("repo")
    @classmethod
    def _repo_shape(cls, value: str) -> str:
        value = value.strip().removeprefix("https://github.com/").strip("/")
        if not _REPO.match(value):
            raise ValueError("use the form owner/name, e.g. octocat/hello-world")
        return value


# ------------------------------------------------------------------ read


class ListReposArgs(BaseModel):
    max_results: int = Field(default=20, ge=1, le=50)


@register
class GithubListRepos(ApiTool):
    name = "github_list_repos"
    pack = "github"
    description = (
        "List the GitHub repositories this connection can see, most recently updated first."
    )
    args_model = ListReposArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: ListReposArgs) -> ToolResult:
        data = await gh(
            ctx, "GET", "/user/repos", params={"sort": "updated", "per_page": args.max_results}
        )
        return ToolResult.success(
            [
                {
                    "repo": r.get("full_name"),
                    "description": r.get("description"),
                    "language": r.get("language"),
                    "private": r.get("private"),
                    "default_branch": r.get("default_branch"),
                    "open_issues": r.get("open_issues_count"),
                    "updated": r.get("pushed_at"),
                }
                for r in data
            ]
        )


class SearchCodeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Words or a symbol to find")
    repo: str | None = Field(default=None, description="Limit to one repository, owner/name")
    max_results: int = Field(default=10, ge=1, le=30)


@register
class GithubSearchCode(ApiTool):
    name = "github_search_code"
    pack = "github"
    description = (
        "Search code on GitHub, usually inside one repository. Returns matching files "
        "and the lines around each match."
    )
    args_model = SearchCodeArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: SearchCodeArgs) -> ToolResult:
        query = args.query + (f" repo:{RepoArgs(repo=args.repo).repo}" if args.repo else "")
        data = await gh(
            ctx,
            "GET",
            "/search/code",
            params={"q": query, "per_page": args.max_results},
            # Ask for the matching fragments, not just file names.
            headers={"Accept": "application/vnd.github.text-match+json"},
        )
        return ToolResult.success(
            {
                "total": data.get("total_count", 0),
                "matches": [
                    {
                        "repo": item.get("repository", {}).get("full_name"),
                        "path": item.get("path"),
                        "fragments": [m.get("fragment") for m in item.get("text_matches", [])][:3],
                    }
                    for item in data.get("items", [])
                ],
            }
        )


class ReadFileArgs(RepoArgs):
    path: str = Field(default="", max_length=500, description="File or folder; empty for the root")
    ref: str | None = Field(
        default=None, description="Branch, tag or commit; default branch if empty"
    )


@register
class GithubReadFile(ApiTool):
    name = "github_read_file"
    pack = "github"
    description = (
        "Read a file from a GitHub repository, or list a folder. Use it to understand "
        "code before suggesting a change."
    )
    args_model = ReadFileArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: ReadFileArgs) -> ToolResult:
        params = {"ref": args.ref} if args.ref else None
        data = await gh(
            ctx, "GET", f"/repos/{args.repo}/contents/{args.path.strip('/')}", params=params
        )
        if isinstance(data, list):  # a folder
            return ToolResult.success(
                {
                    "folder": args.path or "/",
                    "entries": [{"name": e.get("name"), "type": e.get("type")} for e in data],
                }
            )
        if data.get("encoding") != "base64" or data.get("content") is None:
            return ToolResult.failure("unreadable", "That file is too large or not text.")
        text = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return ToolResult.success(
            {"path": data.get("path"), "size": data.get("size"), "content": clip(text)}
        )


class ListIssuesArgs(RepoArgs):
    kind: str = Field(default="all", pattern="^(issues|pulls|all)$")
    state: str = Field(default="open", pattern="^(open|closed|all)$")
    max_results: int = Field(default=20, ge=1, le=50)


@register
class GithubListIssues(ApiTool):
    name = "github_list_issues"
    pack = "github"
    description = "List issues and pull requests in a repository, newest first."
    args_model = ListIssuesArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: ListIssuesArgs) -> ToolResult:
        data = await gh(
            ctx,
            "GET",
            f"/repos/{args.repo}/issues",
            params={"state": args.state, "per_page": args.max_results},
        )
        items = []
        for i in data:
            is_pr = "pull_request" in i
            if (args.kind == "issues" and is_pr) or (args.kind == "pulls" and not is_pr):
                continue
            items.append(
                {
                    "number": i.get("number"),
                    "kind": "pull request" if is_pr else "issue",
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "author": (i.get("user") or {}).get("login"),
                    "labels": [label.get("name") for label in i.get("labels", [])],
                    "comments": i.get("comments"),
                    "updated": i.get("updated_at"),
                }
            )
        return ToolResult.success(items)


class NumberArgs(RepoArgs):
    number: int = Field(ge=1, description="The issue or pull request number")


@register
class GithubReadIssue(ApiTool):
    name = "github_read_issue"
    pack = "github"
    description = "Read one issue or pull request in full, with its latest comments."
    args_model = NumberArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: NumberArgs) -> ToolResult:
        issue = await gh(ctx, "GET", f"/repos/{args.repo}/issues/{args.number}")
        comments = await gh(
            ctx,
            "GET",
            f"/repos/{args.repo}/issues/{args.number}/comments",
            params={"per_page": 20},
        )
        return ToolResult.success(
            {
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "author": (issue.get("user") or {}).get("login"),
                "body": clip(issue.get("body") or "", 8_000),
                "comments": [
                    {
                        "author": (c.get("user") or {}).get("login"),
                        "body": clip(c.get("body") or "", 1_500),
                    }
                    for c in comments
                ],
                "url": issue.get("html_url"),
            }
        )


@register
class GithubPullRequestDiff(ApiTool):
    name = "github_pr_diff"
    pack = "github"
    description = (
        "Read what a pull request changes: each file with its added and removed lines. "
        "Use it to review a pull request."
    )
    args_model = NumberArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: NumberArgs) -> ToolResult:
        pr = await gh(ctx, "GET", f"/repos/{args.repo}/pulls/{args.number}")
        files = await gh(
            ctx, "GET", f"/repos/{args.repo}/pulls/{args.number}/files", params={"per_page": 50}
        )
        return ToolResult.success(
            {
                "title": pr.get("title"),
                "author": (pr.get("user") or {}).get("login"),
                "base": (pr.get("base") or {}).get("ref"),
                "head": (pr.get("head") or {}).get("ref"),
                "description": clip(pr.get("body") or "", 3_000),
                "files": [
                    {
                        "path": f.get("filename"),
                        "status": f.get("status"),
                        "added": f.get("additions"),
                        "removed": f.get("deletions"),
                        "patch": clip(f.get("patch") or "", PATCH_CHARS),
                    }
                    for f in files
                ],
            }
        )


class CommitsArgs(RepoArgs):
    branch: str | None = Field(default=None, description="Default branch if empty")
    max_results: int = Field(default=15, ge=1, le=50)


@register
class GithubListCommits(ApiTool):
    name = "github_list_commits"
    pack = "github"
    description = "List recent commits on a branch: what changed, by whom, when."
    args_model = CommitsArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: CommitsArgs) -> ToolResult:
        params: dict[str, Any] = {"per_page": args.max_results}
        if args.branch:
            params["sha"] = args.branch
        data = await gh(ctx, "GET", f"/repos/{args.repo}/commits", params=params)
        return ToolResult.success(
            [
                {
                    "sha": (c.get("sha") or "")[:10],
                    "message": (c.get("commit", {}).get("message") or "").split("\n")[0],
                    "author": c.get("commit", {}).get("author", {}).get("name"),
                    "date": c.get("commit", {}).get("author", {}).get("date"),
                }
                for c in data
            ]
        )


@register
class GithubCiStatus(ApiTool):
    name = "github_ci_status"
    pack = "github"
    description = (
        "Check CI (GitHub Actions) for a branch: the latest runs, and for a failed run "
        "which jobs and steps failed. Use it to answer 'why is the build red?'."
    )
    args_model = CommitsArgs
    side_effect = SideEffect.READ
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: CommitsArgs) -> ToolResult:
        params: dict[str, Any] = {"per_page": min(args.max_results, 10)}
        if args.branch:
            params["branch"] = args.branch
        data = await gh(ctx, "GET", f"/repos/{args.repo}/actions/runs", params=params)
        runs: list[dict[str, Any]] = []
        for run in data.get("workflow_runs", []):
            entry: dict[str, Any] = {
                "workflow": run.get("name"),
                "branch": run.get("head_branch"),
                "commit": (run.get("head_sha") or "")[:10],
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "url": run.get("html_url"),
            }
            if run.get("conclusion") == "failure" and not any(r.get("failed_jobs") for r in runs):
                # The first failure gets detail: which job, which step.
                jobs = await gh(ctx, "GET", f"/repos/{args.repo}/actions/runs/{run['id']}/jobs")
                entry["failed_jobs"] = [
                    {
                        "job": job.get("name"),
                        "failed_steps": [
                            s.get("name")
                            for s in job.get("steps", [])
                            if s.get("conclusion") == "failure"
                        ],
                    }
                    for job in jobs.get("jobs", [])
                    if job.get("conclusion") == "failure"
                ]
            runs.append(entry)
        return ToolResult.success({"runs": runs})


# ------------------------------------------------------------------ write


class CommentArgs(NumberArgs):
    body: str = Field(min_length=1, max_length=20_000, description="Markdown")


@register
class GithubComment(ApiTool):
    name = "github_comment"
    pack = "github"
    description = "Comment on an issue or pull request. Others are notified."
    args_model = CommentArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: CommentArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_comment_on": args.number})
        comment = await gh(
            ctx,
            "POST",
            f"/repos/{args.repo}/issues/{args.number}/comments",
            json={"body": args.body},
        )
        return ToolResult.success({"commented": True, "url": comment.get("html_url")})


class CreateIssueArgs(RepoArgs):
    title: str = Field(min_length=1, max_length=250)
    body: str = Field(default="", max_length=20_000, description="Markdown")
    labels: list[str] = Field(default_factory=list, max_length=10)


@register
class GithubCreateIssue(ApiTool):
    name = "github_create_issue"
    pack = "github"
    description = "Open a new issue in a repository, e.g. a bug report or a task."
    args_model = CreateIssueArgs
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: CreateIssueArgs) -> ToolResult:
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_open": args.title})
        issue = await gh(
            ctx,
            "POST",
            f"/repos/{args.repo}/issues",
            json={"title": args.title, "body": args.body, "labels": args.labels},
        )
        return ToolResult.success({"number": issue.get("number"), "url": issue.get("html_url")})


class FileChange(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=200_000, description="The whole new file")


class ProposeChangeArgs(RepoArgs):
    title: str = Field(min_length=1, max_length=250, description="Pull request title")
    description: str = Field(default="", max_length=20_000, description="Why, and what changed")
    branch: str = Field(description="New branch name, e.g. fix/login-timeout")
    base: str | None = Field(
        default=None, description="Branch to merge into; default branch if empty"
    )
    files: list[FileChange] = Field(min_length=1, max_length=20)

    @field_validator("branch")
    @classmethod
    def _branch_shape(cls, value: str) -> str:
        if not _BRANCH.match(value) or ".." in value:
            raise ValueError("letters, digits, '.', '_', '-' and '/' only")
        return value


@register
class GithubProposeChange(ApiTool):
    name = "github_propose_change"
    pack = "github"
    description = (
        "Propose a code change: create a new branch, write the files on it, and open a "
        "pull request for a person to review and merge. Never changes the default branch. "
        "Give each file's complete new content."
    )
    args_model = ProposeChangeArgs
    # A write, not destructive: nothing lands until a person merges it,
    # and closing the pull request undoes it.
    side_effect = SideEffect.WRITE
    supports_dry_run = True
    timeout_s = 60.0
    requires_connection = "github"

    async def call(self, ctx: ToolContext, args: ProposeChangeArgs) -> ToolResult:
        repo = await gh(ctx, "GET", f"/repos/{args.repo}")
        base = args.base or repo.get("default_branch") or "main"
        if args.branch == base:
            return ToolResult.failure(
                "not_allowed", "Use a new branch: changes never go straight onto the base branch."
            )
        if ctx.dry_run:
            return ToolResult.success(
                {
                    "dry_run": True,
                    "would_open_pull_request": args.title,
                    "from": args.branch,
                    "into": base,
                    "files": [f.path for f in args.files],
                }
            )

        head = await gh(ctx, "GET", f"/repos/{args.repo}/git/ref/heads/{base}")
        try:
            await gh(
                ctx,
                "POST",
                f"/repos/{args.repo}/git/refs",
                json={"ref": f"refs/heads/{args.branch}", "sha": head["object"]["sha"]},
            )
        except ApiError as exc:
            if "already exists" in exc.message:
                return ToolResult.failure(
                    "branch_exists", f"A branch called {args.branch} exists. Pick another name."
                )
            raise

        for change in args.files:
            path = change.path.strip("/")
            existing_sha = None
            try:
                current = await gh(
                    ctx, "GET", f"/repos/{args.repo}/contents/{path}", params={"ref": args.branch}
                )
                existing_sha = current.get("sha") if isinstance(current, dict) else None
            except ApiError as exc:
                if exc.error_class != "not_found":
                    raise
            body: dict[str, Any] = {
                "message": f"{args.title}\n\nProposed by an AI assistant for review.",
                "content": base64.b64encode(change.content.encode()).decode(),
                "branch": args.branch,
            }
            if existing_sha:
                body["sha"] = existing_sha
            await gh(ctx, "PUT", f"/repos/{args.repo}/contents/{path}", json=body)

        pr = await gh(
            ctx,
            "POST",
            f"/repos/{args.repo}/pulls",
            json={
                "title": args.title,
                "head": args.branch,
                "base": base,
                "body": (
                    args.description + "\n\n---\n_Proposed by an AI assistant. "
                    "Review before merging._"
                ).strip(),
            },
        )
        return ToolResult.success(
            {
                "pull_request": pr.get("number"),
                "url": pr.get("html_url"),
                "branch": args.branch,
                "into": base,
                "files": [f.path for f in args.files],
            }
        )
