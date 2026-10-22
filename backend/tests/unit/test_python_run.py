"""The Python tool: useful results, and the guards that hold on every platform."""

import os
import uuid

import pytest

from app.agent.tools.base import SideEffect, ToolContext
from app.agent.tools.packs.python_run import PythonRun
from app.agent.tools.registry import registry

CTX = ToolContext(owner_id=uuid.uuid4())


async def run(code: str, **extra: object):
    return await PythonRun().execute(CTX, {"code": code, **extra})


async def test_it_returns_what_the_program_prints() -> None:
    result = await run("import statistics\nprint(statistics.mean([2, 4, 9]))")
    assert result.ok
    assert result.data["output"].strip() == "5"


async def test_a_crash_comes_back_as_text_the_model_can_fix() -> None:
    result = await run("print(1/0)")
    assert result.error_class == "program_error"
    assert "ZeroDivisionError" in (result.message or "")


async def test_a_runaway_program_is_stopped() -> None:
    result = await run("while True:\n    pass", timeout_seconds=1)
    assert result.error_class == "timeout"


async def test_output_is_capped() -> None:
    result = await run("print('x' * 100000)")
    assert result.ok
    assert result.data["truncated"]
    assert len(result.data["output"]) <= 20_000


@pytest.mark.parametrize(
    "code",
    [
        "import socket",
        "import subprocess",
        "import urllib.request",
        "import ctypes",
        "import os\nos.system('echo hi')",
    ],
)
async def test_network_and_process_spawning_are_refused(code: str) -> None:
    result = await run(code)
    assert result.error_class == "program_error"


async def test_our_environment_is_not_visible() -> None:
    os.environ["SECRET_FOR_TEST"] = "hunter2"
    try:
        result = await run("import os\nprint(os.environ.get('SECRET_FOR_TEST'))")
    finally:
        del os.environ["SECRET_FOR_TEST"]
    assert result.ok
    assert "hunter2" not in result.data["output"]


async def test_a_dry_run_runs_nothing() -> None:
    ctx = ToolContext(owner_id=uuid.uuid4(), dry_run=True)
    result = await PythonRun().execute(ctx, {"code": "print('x')"})
    assert result.ok
    assert result.data["dry_run"]


def test_running_code_needs_a_persons_approval_by_default() -> None:
    tool = registry.get("python_run")
    assert tool is not None
    assert tool.side_effect is SideEffect.WRITE
