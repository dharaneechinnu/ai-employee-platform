"""Tool argument schemas, in the shape each AI provider accepts.

Pydantic writes a schema for every tool's arguments. Two things in it
trip providers up:

1. Shared definitions. An enum or a nested model becomes `$defs` plus a
   `$ref` to it. OpenAI and Anthropic follow the reference; Gemini does
   not, and refuses the whole request ("Unknown name $defs"), so every
   run that offered such a tool failed. `inline_refs` replaces each
   reference with the definition itself, which every provider reads.

2. Gemini reads only a subset of JSON Schema (an OpenAPI 3.0 "Schema").
   `for_gemini` keeps that subset: an optional field (`anyOf` with
   null) becomes `nullable`, and keywords Gemini rejects, such as
   `additionalProperties` or a string format other than `date-time`,
   are dropped. Dropping one only loosens the hint to the model; the
   tool still checks its arguments itself before it runs.
"""

from __future__ import annotations

import copy
from typing import Any

Schema = dict[str, Any]

# Keys Gemini's function declarations accept on a schema node.
_GEMINI_KEYS = {
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
_GEMINI_STRING_FORMATS = {"date-time", "enum"}


def inline_refs(schema: Schema) -> Schema:
    """The same schema with every `$ref` to `$defs` replaced by its target."""
    defs: dict[str, Schema] = schema.get("$defs", {})

    def resolve(node: Any, seen: tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(item, seen) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.removeprefix("#/$defs/")
            if name in seen or name not in defs:
                # A model that contains itself cannot be inlined; an object
                # with no detail is still a valid, if loose, description.
                return {"type": "object", **_siblings(node)}
            target = resolve(copy.deepcopy(defs[name]), (*seen, name))
            return {**target, **_siblings(node)}
        return {key: resolve(value, seen) for key, value in node.items() if key != "$defs"}

    return resolve(schema, ())  # type: ignore[no-any-return]


def _siblings(node: Schema) -> Schema:
    """What sits next to a `$ref`, such as its own description."""
    return {key: value for key, value in node.items() if key != "$ref"}


def for_gemini(schema: Schema) -> Schema:
    """The schema as Gemini's function declarations accept it."""
    return _gemini_node(inline_refs(schema))


def _gemini_node(node: Schema) -> Schema:
    # `X | None` arrives as anyOf [X, null]: Gemini spells that `nullable`.
    options = node.get("anyOf")
    if isinstance(options, list):
        real = [o for o in options if not (isinstance(o, dict) and o.get("type") == "null")]
        if len(real) < len(options) and len(real) == 1 and isinstance(real[0], dict):
            merged = {**{k: v for k, v in node.items() if k != "anyOf"}, **real[0]}
            return {**_gemini_node(merged), "nullable": True}

    out: Schema = {}
    for key, value in node.items():
        if key not in _GEMINI_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            # The keys here are argument names, not schema keywords.
            out[key] = {name: _gemini_node(sub) for name, sub in value.items()}
        elif key == "items" and isinstance(value, dict):
            out[key] = _gemini_node(value)
        elif key == "anyOf" and isinstance(value, list):
            out[key] = [_gemini_node(o) for o in value if isinstance(o, dict)]
        elif (
            key == "format" and value not in _GEMINI_STRING_FORMATS and node.get("type") == "string"
        ):
            continue
        else:
            out[key] = value
    # Gemini needs a type on every node; an enum alone is a string enum.
    if "type" not in out and "anyOf" not in out:
        out["type"] = "string" if "enum" in out else "object"
    return out
