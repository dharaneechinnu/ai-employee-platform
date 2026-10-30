"""Arithmetic that is exact.

Models are unreliable at multi-digit arithmetic, and an analyst agent
that guesses a total is worse than one that says nothing. This tool
evaluates an expression by walking its syntax tree and allowing only
numbers, a few operators and a few named functions, so it never runs
model-written code. Needs nothing connected.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from app.agent.tools.base import SideEffect, Tool, ToolContext, ToolResult
from app.agent.tools.registry import register

MAX_EXPRESSION_CHARS = 500
# A huge power would hang the worker; far beyond any real calculation.
MAX_EXPONENT = 1000
MAX_ABS_RESULT = 1e300

_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": lambda *xs: sum(xs),
    "sqrt": math.sqrt,
    "ln": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "floor": math.floor,
    "ceil": math.ceil,
}
_CONSTANTS = {"pi": math.pi, "e": math.e}


class CalculationError(ValueError):
    pass


def evaluate(expression: str) -> float | int:
    """Evaluate `expression`, or raise `CalculationError` saying why not."""
    # Models write "2^3" meaning a power; Python reads ^ as something else.
    cleaned = expression.strip().replace("^", "**")
    if not cleaned:
        raise CalculationError("The expression is empty.")
    if len(cleaned) > MAX_EXPRESSION_CHARS:
        raise CalculationError(f"The expression is longer than {MAX_EXPRESSION_CHARS} characters.")
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"Could not read the expression: {exc.msg}.") from exc
    result: float | int = _eval(tree.body)
    if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
        raise CalculationError("The result is not a finite number.")
    if abs(result) > MAX_ABS_RESULT:
        raise CalculationError("The result is too large.")
    return result


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, int | float):
            raise CalculationError("Only numbers are allowed.")
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalculationError(f"'{node.id}' is not a number or a known constant (pi, e).")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculationError(f"Exponents above {MAX_EXPONENT} are not allowed.")
        try:
            return _BINARY[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise CalculationError("Division by zero.") from exc
        except OverflowError as exc:
            raise CalculationError("The result is too large.") from exc
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        fn = _FUNCTIONS.get(node.func.id)
        if fn is None:
            raise CalculationError(
                f"'{node.func.id}' is not a known function. Known: {', '.join(sorted(_FUNCTIONS))}."
            )
        try:
            return fn(*[_eval(a) for a in node.args])
        except (ValueError, TypeError, OverflowError) as exc:
            raise CalculationError(f"{node.func.id}: {exc}") from exc
    raise CalculationError("That kind of expression is not allowed. Use numbers and operators.")


class CalculatorArgs(BaseModel):
    expression: str = Field(
        min_length=1,
        description="Arithmetic such as '(1200 * 0.18) + 45' or 'sqrt(144) / 3'. "
        "Operators: + - * / // % ** and parentheses. Functions: "
        + ", ".join(sorted(_FUNCTIONS))
        + ". Constants: pi, e.",
    )


@register
class Calculator(Tool):
    name = "calculator"
    pack = "calculator"
    description = (
        "Calculate an arithmetic expression exactly. Use it for any sum, percentage, "
        "average or conversion instead of working it out yourself."
    )
    args_model = CalculatorArgs
    side_effect = SideEffect.READ
    timeout_s = 5.0

    async def run(self, ctx: ToolContext, args: CalculatorArgs) -> ToolResult:  # type: ignore[override]
        try:
            value = evaluate(args.expression)
        except CalculationError as exc:
            return ToolResult.failure("invalid_expression", str(exc))
        return ToolResult.success({"expression": args.expression.strip(), "result": value})
