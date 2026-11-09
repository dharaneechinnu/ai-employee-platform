"""What each AI has done in a run, and the note that hands the job over.

When one AI stops part way and another takes over, the second one has to
know which steps are already finished, or it may repeat a change (a sheet
row added twice, a second draft email) or skip a part. The conversation
holds every tool call and result, but nothing says "these are done, carry
on with the rest". This does.

Two pieces:

- `WorkLog` is kept by the agent loop for one run. It tracks, per AI, how
  many model calls it made, the tokens it used and how many tool steps it
  asked for, and which AI made each step.
- `build_note` reads the conversation (the complete record of what
  happened, including steps from before a pause for approval) and the
  log (who did it) and writes a short note: done, looked up, failed.

The fallback layer calls `build_note` at the moment it switches AI and
puts the note in the instructions the new AI receives. The instructions
are the right place: every provider takes them in a slot of their own,
they are sent on every step, and shrinking a request never cuts them.
"""

from __future__ import annotations

import contextvars
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any

from app.agent.providers.base import (
    HandoffNote,
    LLMError,
    Message,
    ProviderAuthError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderTooLargeError,
    ProviderUnavailableError,
    Role,
    ToolCall,
    Usage,
)
from app.agent.tools.base import SideEffect
from app.agent.tools.registry import registry

# Marks the note inside the instructions, so a second switch replaces it
# instead of stacking a second one on top.
MARKER = "[Handoff note]"

# A small-limit AI must not be pushed over its size limit by the note.
MAX_LISTED = 20
ARG_CHARS = 120
REASON_CHARS = 100

_FAILED = re.compile(r"^Tool failed \(([^)]*)\):\s*(.*)$", re.DOTALL)
_BLOCKED = re.compile(r"^'[^']+' is not permitted")


@dataclass(slots=True)
class ModelUsage:
    """What one AI did in this run."""

    calls: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    # Tool steps this AI asked for (a step is one tool call).
    tool_calls: int = 0


@dataclass(slots=True)
class WorkLog:
    """Per-run record of which AI did what. One per agent loop."""

    usage: dict[str, ModelUsage] = field(default_factory=dict)
    # Tool call id -> the AI that asked for it.
    made_by: dict[str, str] = field(default_factory=dict)
    handoffs: list[HandoffNote] = field(default_factory=list)

    def record_reply(self, model: str, usage: Usage, calls: list[ToolCall]) -> None:
        entry = self.usage.setdefault(model, ModelUsage())
        entry.calls += 1
        entry.prompt_tokens += usage.prompt_tokens
        entry.output_tokens += usage.output_tokens
        entry.tool_calls += len(calls)
        for call in calls:
            self.made_by[call.id] = model

    def record_handoff(self, note: HandoffNote) -> None:
        self.handoffs.append(note)

    def usage_summary(self) -> dict[str, dict[str, int]]:
        """Plain numbers per AI, for the run's event log."""
        return {
            model: {
                "calls": u.calls,
                "prompt_tokens": u.prompt_tokens,
                "output_tokens": u.output_tokens,
                "tool_calls": u.tool_calls,
            }
            for model, u in self.usage.items()
        }


# The loop that is making a model call right now. A context variable, not
# an attribute of the provider: parallel helpers can share one fallback
# provider, and each must hand over using its own record of its own work.
CURRENT_LOG: contextvars.ContextVar[WorkLog | None] = contextvars.ContextVar(
    "baton_work_log", default=None
)


def reason_for(exc: LLMError) -> str:
    """Why the AI that stopped could not carry on, in plain words."""
    if isinstance(exc, ProviderRateLimitError):
        return "it reached its usage limit"
    if isinstance(exc, ProviderUnavailableError):
        return "its service was not answering"
    if isinstance(exc, ProviderAuthError):
        return "its key was refused"
    if isinstance(exc, ProviderModelNotFoundError):
        return "its model was not available"
    if isinstance(exc, ProviderTooLargeError):
        return "the request was too big for it"
    return "it hit an error"


def _shorten(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _args_text(arguments: dict[str, Any]) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(arguments)
    return _shorten(text, ARG_CHARS)


def _is_change(tool_name: str) -> bool:
    """A step that creates, changes or sends something. A tool we do not
    know is treated as a change: the strong warning is the safe default."""
    tool = registry.get(tool_name)
    return tool is None or tool.side_effect is not SideEffect.READ


@dataclass(slots=True)
class _Entry:
    kind: str  # "done" | "lookup" | "failed"
    text: str


def _entries(messages: list[Message], log: WorkLog) -> list[_Entry]:
    """Every tool step that has a result, in the order it happened."""
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    results: dict[str, str] = {}
    for m in messages:
        if m.role is Role.ASSISTANT:
            for call in m.tool_calls:
                calls[call.id] = call
                order.append(call.id)
        elif m.role is Role.TOOL and m.tool_call_id in calls:
            results[m.tool_call_id] = m.content or ""

    entries: list[_Entry] = []
    for call_id in order:
        if call_id not in results:
            continue  # asked for, never answered: not a finished step
        call = calls[call_id]
        content = results[call_id]
        who = log.made_by.get(call_id)
        head = f"[{who}] " if who else ""
        what = f"{head}{call.name} {_args_text(call.arguments)}".rstrip()

        if _BLOCKED.match(content):
            entries.append(_Entry("failed", f"{what}: blocked by the person's permissions"))
        elif failed := _FAILED.match(content):
            reason = _shorten(failed.group(2), REASON_CHARS)
            entries.append(_Entry("failed", f"{what}: {reason}"))
        elif _is_change(call.name):
            entries.append(_Entry("done", what))
        else:
            entries.append(_Entry("lookup", what))
    return entries


def build_note(
    messages: list[Message],
    log: WorkLog,
    *,
    from_model: str | None = None,
    to_model: str | None = None,
    reason: str | None = None,
) -> HandoffNote | None:
    """The note for the AI taking over, or None when no step has a result yet
    (a switch before any work was done has nothing to hand over)."""
    entries = _entries(messages, log)
    if not entries:
        return None

    omitted = max(0, len(entries) - MAX_LISTED)
    shown = entries[-MAX_LISTED:]
    done = [e.text for e in shown if e.kind == "done"]
    lookups = [e.text for e in shown if e.kind == "lookup"]
    failed = [e.text for e in shown if e.kind == "failed"]

    intro = "Another AI"
    if from_model:
        intro += f" ({from_model})"
    intro += " started this job and stopped part way"
    if reason:
        intro += f" because {reason}"
    intro += ". You are taking over. Everything it did is in the conversation above."

    lines = [MARKER, intro]
    if done:
        lines += ["", "Already done. Do NOT repeat these:", *(f"- {t}" for t in done)]
    if lookups:
        lines += ["", "Already looked up (no need to look again):", *(f"- {t}" for t in lookups)]
    if failed:
        lines += ["", "Tried and failed:", *(f"- {t}" for t in failed)]
    if omitted:
        lines += ["", f"({omitted} earlier steps are not listed. Check the conversation.)"]
    lines += [
        "",
        "Now finish whatever the person's request still needs. "
        "Before making any change, check it was not already made.",
    ]

    return HandoffNote(
        text="\n".join(lines),
        done=len(done),
        looked_up=len(lookups),
        failed=len(failed),
        omitted=omitted,
        from_model=from_model,
        to_model=to_model,
        reason=reason,
    )


def _with_text(system: Message, note: str) -> Message:
    base = system.content or ""
    at = base.find(MARKER)
    if at >= 0:
        base = base[:at].rstrip()  # a second switch replaces the first note
    return replace(system, content=f"{base}\n\n{note}".strip())


def with_note(messages: list[Message], note: str) -> list[Message]:
    """A copy of the conversation with the note added to its instructions."""
    out = list(messages)
    attach_note(out, note)
    return out


def attach_note(messages: list[Message], note: str) -> None:
    """Add the note to the instructions of this list, in place."""
    for i, m in enumerate(messages):
        if m.role is Role.SYSTEM:
            messages[i] = _with_text(m, note)
            return
    messages.insert(0, Message(role=Role.SYSTEM, content=note))
