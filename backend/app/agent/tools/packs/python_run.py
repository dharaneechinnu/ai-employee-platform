"""Run a short Python program, for analysis the calculator cannot do.

LOCAL-USE SANDBOX. This is a restricted subprocess, not a container, and
it is not a security boundary against a determined attacker:

- a separate interpreter in isolated mode (no user site, no env path),
  in a throwaway directory, with an empty environment so no secret of
  ours is visible to it;
- a hard wall-clock limit and an output cap;
- on Linux and macOS, CPU and memory limits as well;
- before the program starts, networking and process-spawning modules are
  made unimportable and the ways to start another program are removed.

A program that works hard enough can still get round the in-process
guards, so the tool is labelled `write`: under the default permissions a
person approves each run, and an unattended agent cannot use it at all.
Move this behind a container before it runs for anyone but its owner.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

MAX_CODE_CHARS = 20_000
DEFAULT_SECONDS = 10
MAX_SECONDS = 30
MAX_OUTPUT_CHARS = 20_000
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024

# Runs inside the child before the program. Kept as text so it executes
# in the child's own interpreter, ahead of any code the model wrote.
_PRELUDE = f"""
import builtins, importlib.abc, os, runpy, sys

_BLOCKED = {{
    "socket", "ssl", "select", "selectors", "asyncio", "http", "urllib", "ftplib",
    "smtplib", "telnetlib", "xmlrpc", "requests", "httpx", "subprocess", "multiprocessing",
    "ctypes", "_ctypes", "pty", "webbrowser", "shutil", "signal", "_socket", "_posixsubprocess",
}}

class _Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split(".")[0] in _BLOCKED:
            raise ImportError(f"'{{name}}' is not available in this sandbox")

sys.meta_path.insert(0, _Deny())
for _m in list(sys.modules):
    if _m.split(".")[0] in _BLOCKED:
        del sys.modules[_m]

for _name in ("system", "popen", "execv", "execve", "execvp", "execl", "execlp", "execle",
              "spawnl", "spawnv", "spawnlp", "spawnvp", "fork", "forkpty", "kill", "startfile"):
    if hasattr(os, _name):
        setattr(os, _name, None)

try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, ({MEMORY_LIMIT_BYTES}, {MEMORY_LIMIT_BYTES}))
    resource.setrlimit(resource.RLIMIT_CPU, ({MAX_SECONDS}, {MAX_SECONDS}))
except ImportError:
    pass

runpy.run_path(sys.argv[1], run_name="__main__")
"""


class PythonRunArgs(BaseModel):
    code: str = Field(
        min_length=1,
        max_length=MAX_CODE_CHARS,
        description="A complete Python program. Print what you want back. Standard library "
        "only, no network, no files outside its scratch folder.",
    )
    timeout_seconds: int = Field(default=DEFAULT_SECONDS, ge=1, le=MAX_SECONDS)


def _clean_env() -> dict[str, str]:
    """Nothing from our environment: it holds keys and database passwords."""
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if sys.platform == "win32":
        # Python cannot start on Windows without these.
        for key in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def _cap(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS], True


@register
class PythonRun(Tool):
    name = "python_run"
    pack = "python"
    description = (
        "Run a short Python program and get what it prints. Use it for data analysis, "
        "statistics, parsing and anything the calculator cannot do. Standard library only; "
        "no internet, no installed packages, no files. Print your results."
    )
    args_model = PythonRunArgs
    # Runs model-written code, so a person approves each run.
    side_effect = SideEffect.WRITE
    timeout_s = MAX_SECONDS + 10.0

    async def run(self, ctx: ToolContext, args: PythonRunArgs) -> ToolResult:  # type: ignore[override]
        if ctx.dry_run:
            return ToolResult.success({"dry_run": True, "would_run_chars": len(args.code)})

        with tempfile.TemporaryDirectory(prefix="pyrun-") as scratch:
            program = Path(scratch) / "main.py"
            program.write_text(args.code, encoding="utf-8")
            try:
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-I",
                    "-c",
                    _PRELUDE,
                    str(program),
                    cwd=scratch,
                    env=_clean_env(),
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                return ToolResult.failure("cannot_start", f"Could not start Python: {exc}")

            try:
                out, err = await asyncio.wait_for(proc.communicate(), args.timeout_seconds)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult.failure(
                    "timeout",
                    f"The program ran longer than {args.timeout_seconds} seconds and was stopped.",
                )

        stdout, cut_out = _cap(out.decode("utf-8", "replace"))
        stderr, cut_err = _cap(err.decode("utf-8", "replace"))
        if proc.returncode != 0:
            # The last lines of a traceback hold the cause; the model can fix it from there.
            return ToolResult.failure(
                "program_error",
                f"Exit code {proc.returncode}.\n{stderr[-3000:]}\n{stdout[-2000:]}".strip(),
            )
        return ToolResult.success(
            {"output": stdout, "stderr": stderr, "truncated": cut_out or cut_err}
        )
