"""Every tool's argument schema reads the same in every provider.

Gemini refused any request that offered a tool whose schema used shared
definitions (`$defs` / `$ref`), and `text_tools` is given to every agent,
so these checks run over the whole catalogue rather than one example.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.agent.tools.packs  # noqa: F401  (registers every tool)
from app.agent.tools.registry import registry
from app.agent.tools.schema import for_gemini, inline_refs

GEMINI_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "pattern",
    "anyOf",
}

TOOLS = registry.all()


def _keys(node: Any) -> set[str]:
    """Every schema keyword used, leaving out argument names."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                for sub in value.values():
                    found |= _keys(sub)
            else:
                found.add(key)
                found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_no_tool_schema_uses_shared_definitions(tool: Any) -> None:
    keys = _keys(tool.json_schema())
    assert "$defs" not in keys and "$ref" not in keys


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_gemini_gets_only_keywords_it_accepts(tool: Any) -> None:
    schema = for_gemini(tool.json_schema())
    assert _keys(schema) <= GEMINI_KEYS
    assert schema["type"] == "object"
    assert set(schema.get("required", [])) <= set(schema.get("properties", {}))


def test_an_enum_definition_is_written_out_in_place() -> None:
    schema = inline_refs(
        {
            "$defs": {"Mode": {"enum": ["a", "b"], "type": "string"}},
            "properties": {"mode": {"$ref": "#/$defs/Mode", "description": "Pick one"}},
            "type": "object",
        }
    )
    assert schema == {
        "properties": {"mode": {"enum": ["a", "b"], "type": "string", "description": "Pick one"}},
        "type": "object",
    }


def test_an_optional_field_becomes_nullable_for_gemini() -> None:
    schema = for_gemini(
        {
            "type": "object",
            "properties": {
                "note": {"anyOf": [{"type": "string", "maxLength": 9}, {"type": "null"}]},
                "title": {"type": "string", "format": "email", "title": "Title"},
            },
        }
    )
    assert schema["properties"]["note"] == {"type": "string", "maxLength": 9, "nullable": True}
    # "title" is an argument name here, so it stays; its unsupported format goes.
    assert schema["properties"]["title"] == {"type": "string"}


def test_a_model_that_contains_itself_does_not_loop() -> None:
    schema = inline_refs(
        {
            "$defs": {
                "Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}
            },
            "$ref": "#/$defs/Node",
        }
    )
    assert schema["properties"]["child"] == {"type": "object"}
