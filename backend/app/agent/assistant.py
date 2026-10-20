"""The personal assistant: one helper, four ways of working.

People use a chat assistant for different jobs, and the same answer is
wrong for each. A student wants to understand, not to be handed the
answer; a professional wants the draft, short; a researcher wants
sources and an honest line between what is known and what is guessed.
A mode is that difference written down, so the person picks it once
instead of re-explaining themselves every message.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agent.tools.base import Tool
from app.agent.tools.registry import registry
from app.db.models.conversation import ChatMode
from app.db.models.policy import PolicySetting

# A chat turn may take a few tool steps; it should not take fifteen.
CHAT_MAX_STEPS = 10
# Older messages are dropped first. Enough for a long working session,
# small enough to fit every provider's context with room to answer.
HISTORY_MESSAGES = 24
HISTORY_CHARS = 40_000


@dataclass(frozen=True, slots=True)
class Mode:
    key: ChatMode
    label: str
    for_whom: str
    instructions: str
    examples: tuple[str, ...]


MODES: dict[ChatMode, Mode] = {
    ChatMode.GENERAL: Mode(
        key=ChatMode.GENERAL,
        label="General",
        for_whom="Everyday questions and tasks",
        instructions=(
            "Answer clearly and directly. Lead with the answer, then the detail that "
            "matters. Ask one short question when the request is ambiguous rather than "
            "guessing."
        ),
        examples=(
            "Plan a three-day trip to Jaipur on a student budget",
            "Explain what a mutual fund SIP is in simple words",
        ),
    ),
    ChatMode.STUDY: Mode(
        key=ChatMode.STUDY,
        label="Study",
        for_whom="Students learning a subject",
        instructions=(
            "You are a patient tutor. Help the person understand, not just finish. "
            "Explain step by step with a small worked example, define new terms, and "
            "check understanding with one short question at the end. For homework or "
            "exam questions, guide them to the answer with hints before giving it in "
            "full, unless they ask for the full solution. Point out common mistakes."
        ),
        examples=(
            "Teach me recursion with one Python example",
            "Quiz me on the causes of the French Revolution",
        ),
    ),
    ChatMode.WORK: Mode(
        key=ChatMode.WORK,
        label="Work",
        for_whom="Professionals getting things done",
        instructions=(
            "You are a sharp professional assistant. Be concise and practical: give the "
            "draft, the decision or the next steps, ready to use. Use headings and bullet "
            "points for anything longer than a paragraph. Match the tone the person "
            "needs (formal for clients, plain for colleagues). Never send, delete or "
            "change anything without saying exactly what you are about to do."
        ),
        examples=(
            "Draft a polite follow-up email to a client who has not paid",
            "Turn these meeting notes into action items with owners",
        ),
    ),
    ChatMode.RESEARCH: Mode(
        key=ChatMode.RESEARCH,
        label="Research",
        for_whom="Researchers and deep dives",
        instructions=(
            "You are a careful research assistant. Structure the answer: a short summary, "
            "the findings, then open questions. Separate what is well established from "
            "what is uncertain or your inference, and say how confident you are. When "
            "you read a source with a tool, cite it by its address. Never invent "
            "citations, numbers or quotes: if you do not know, say so."
        ),
        examples=(
            "Compare RAG and fine-tuning for a small team, with trade-offs",
            "Summarise the main arguments for and against a four-day work week",
        ),
    ),
}

TEAM_INSTRUCTIONS = (
    "You lead a small team of specialists, reached with the `ask_specialist` tool: "
    "researcher (finds and reads sources), analyst (works through numbers, logic and "
    "options), writer (drafts clear text) and critic (checks a draft for errors and "
    "gaps). For a simple question, answer yourself. For a bigger one, plan first: split "
    "the work into independent parts and ask several specialists in the same step so "
    "they work at the same time, then combine what comes back into one answer. Give "
    "each specialist a task that stands alone, since they cannot see this "
    "conversation. Check their work before relying on it, and ask the critic to review "
    "anything important before you answer."
)


def system_prompt(mode: ChatMode, *, person: str | None, team: bool, tool_names: list[str]) -> str:
    chosen = MODES[mode]
    today = datetime.now(UTC).strftime("%A %d %B %Y")
    parts = [
        f"You are a personal AI assistant{f' for {person}' if person else ''}. Today is {today}.",
        f"Mode: {chosen.label}. {chosen.instructions}",
        "Write in Markdown. Use the person's language.",
    ]
    if tool_names:
        parts.append(
            "You can use tools. Use one only when it helps answer; say briefly what you "
            "found. If a tool needs the person's approval, the run pauses until they "
            "decide."
        )
    else:
        parts.append(
            "You have no tools right now. If the request needs live data or an action, say "
            "what you would need instead of pretending."
        )
    if team:
        parts.append(TEAM_INSTRUCTIONS)
    return "\n\n".join(parts)


# Handing work to the person's AI Employees belongs to AI Employees; a
# chat has its own team of specialists.
_NOT_IN_CHAT = {"delegate_to_specialist"}


def chat_tools(resolver: Any, connected: set[str]) -> list[type[Tool]]:
    """Every tool this person's assistant can use right now.

    Tools are the platform's side of the deal, so there is nothing to
    pick: built-in tools are always on, an app's tools are on once the
    person has connected that app, and every tool from their MCP
    servers is on. Their Permissions still decide each call (run, ask
    first, or blocked), and a blocked tool is not offered at all, so
    the model never wastes a step on it.
    """
    chosen: list[type[Tool]] = []
    for tool in [*registry.all(), *resolver.extra_tools.values()]:
        if tool.name in _NOT_IN_CHAT:
            continue
        if tool.requires_connection and tool.requires_connection not in connected:
            continue
        if resolver.evaluate(tool.name).setting is PolicySetting.BLOCKED:
            continue
        chosen.append(tool)
    return chosen
