"""The tools that need no connection: calculator, text_tools, report_write.

A user's own model has nothing built in, so these are what every agent
can rely on. They must be exact, and must refuse bad input in words the
model can act on rather than crash.
"""

import uuid

import pytest

from app.agent.tools.base import ToolContext
from app.agent.tools.packs.calculator import CalculationError, Calculator, evaluate
from app.agent.tools.packs.report import ReportWrite
from app.agent.tools.packs.text import TextTools
from app.agent.tools.registry import registry

CTX = ToolContext(owner_id=uuid.uuid4())


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(1200 * 0.18) + 45", 261.0),
        ("2^10", 1024),
        ("sqrt(144) / 3", 4.0),
        ("round(10 / 3, 2)", 3.33),
        ("max(3, 9, 4) - min(3, 9, 4)", 6),
        ("-5 % 3", 1),
        ("pi * 2", 6.283185307179586),
    ],
)
def test_calculator_gets_exact_answers(expression: str, expected: float) -> None:
    assert evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",  # a call that is not a known function
        "open('x')",
        "(1).__class__",
        "[1, 2][0]",
        "'a' * 3",
        "x + 1",
        "True + 1",
        "1 / 0",
        "9 ** 9999",
        "sqrt(-1)",
        "",
        "1 +",
    ],
)
def test_calculator_refuses_anything_that_is_not_arithmetic(expression: str) -> None:
    with pytest.raises(CalculationError):
        evaluate(expression)


async def test_calculator_failure_is_a_sentence_for_the_model() -> None:
    result = await Calculator().execute(CTX, {"expression": "1 / 0"})
    assert not result.ok
    assert result.error_class == "invalid_expression"
    assert "zero" in (result.message or "").lower()


async def test_text_stats_count_exactly() -> None:
    result = await TextTools().execute(
        CTX, {"operation": "stats", "text": "One two three. Four five!\n\nSix."}
    )
    assert result.ok
    assert result.data["words"] == 6
    assert result.data["sentences"] == 3
    assert result.data["paragraphs"] == 2


async def test_text_extract_finds_each_item_once() -> None:
    text = "Mail a@b.com or a@b.com, see https://x.dev/page. Total 1,200 and 15%."
    emails = await TextTools().execute(
        CTX, {"operation": "extract", "text": text, "kind": "emails"}
    )
    urls = await TextTools().execute(CTX, {"operation": "extract", "text": text, "kind": "urls"})
    numbers = await TextTools().execute(
        CTX, {"operation": "extract", "text": text, "kind": "numbers"}
    )
    assert emails.data["items"] == ["a@b.com"]
    assert urls.data["items"] == ["https://x.dev/page"]
    assert numbers.data["items"] == ["1,200", "15%"]


async def test_text_compare_shows_the_change() -> None:
    result = await TextTools().execute(
        CTX, {"operation": "compare", "text": "a\nb\nc", "other_text": "a\nB\nc"}
    )
    assert result.ok
    assert not result.data["identical"]
    assert "-b" in result.data["diff"]
    assert "+B" in result.data["diff"]


async def test_text_tools_say_what_is_missing() -> None:
    compare = await TextTools().execute(CTX, {"operation": "compare", "text": "a"})
    extract = await TextTools().execute(CTX, {"operation": "extract", "text": "a"})
    assert compare.error_class == "invalid_arguments"
    assert "other_text" in (compare.message or "")
    assert extract.error_class == "invalid_arguments"
    assert "kind" in (extract.message or "")


async def test_report_is_one_document_with_one_title() -> None:
    result = await ReportWrite().execute(
        CTX,
        {
            "title": "Q3 Review",
            "summary": "Sales rose.",
            "sections": [{"heading": "Findings", "body": "# Sneaky title\nDetail."}],
            "sources": ["https://example.com/q3"],
        },
    )
    assert result.ok
    markdown = result.data["markdown"]
    assert markdown.startswith("# Q3 Review")
    assert markdown.count("\n# ") == 0  # the section's own title was pushed down
    assert "### Sneaky title" in markdown
    assert "## Sources" in markdown
    assert result.data["missing"] == []


async def test_report_without_sources_says_so() -> None:
    result = await ReportWrite().execute(
        CTX,
        {"title": "T", "summary": "S", "sections": [{"heading": "H", "body": "B"}]},
    )
    assert result.ok
    assert result.data["missing"]
    assert "## Sources" not in result.data["markdown"]


async def test_report_refuses_an_empty_one() -> None:
    result = await ReportWrite().execute(CTX, {"title": "T", "summary": "S", "sections": []})
    assert result.error_class == "invalid_arguments"


def test_the_common_tools_are_registered_and_read_only() -> None:
    for name in ("calculator", "text_tools", "report_write"):
        tool = registry.get(name)
        assert tool is not None
        assert tool.requires_connection is None
        assert tool.side_effect.value == "read"
