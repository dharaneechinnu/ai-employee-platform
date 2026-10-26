"""What a run did to Google Sheets, kept by the tools and read at the end.

The AI is asked to finish with a report and the sheet's link, but a
small model may forget the link, or claim it saved rows it did not.
So the sheet tools write down what they really did, as it happens, and
the run adds a short closing block built from that record: the sheet's
link, how many rows were added, and any write that was refused. The
text comes from the tools, never from the AI.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KEY = "_sheet_log"

SHEET_WRITE_TOOLS = {"sheets_create", "sheets_append_rows", "sheets_update_cells"}


def address(sheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"


def note(config: Mapping[str, Any] | None, **entry: Any) -> None:
    """Record one thing a sheet tool did. A no-op when the run keeps no log.

    The list is shared by reference, so it is still the run's list when a
    tool works on its own copy of the context."""
    log = (config or {}).get(KEY)
    if isinstance(log, list):
        log.append(entry)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def closing(log: list[dict[str, Any]], blocked: list[tuple[str, str]] | None = None) -> str | None:
    """The block added under the AI's own report, or None if sheets were not used."""
    blocked = [(t, r) for t, r in (blocked or []) if t in SHEET_WRITE_TOOLS]
    if not log and not blocked:
        return None

    lines: list[str] = []
    order: list[str] = []
    for entry in log:
        if entry["sheet_id"] not in order:
            order.append(entry["sheet_id"])

    for sheet_id in order:
        mine = [e for e in log if e["sheet_id"] == sheet_id]
        created = next((e for e in mine if e["action"] == "created"), None)
        added = sum(e.get("rows", 0) for e in mine if e["action"] == "added")
        changed = sum(e.get("cells", 0) for e in mine if e["action"] == "updated")
        tabs = list(
            dict.fromkeys(e["tab"] for e in mine if e["action"] == "added" and e.get("tab"))
        )

        did: list[str] = []
        if created:
            did.append(f"created the sheet “{created['title']}”")
        if added:
            where = f" to {', '.join(tabs)}" if tabs else ""
            did.append(f"added {_plural(added, 'row')}{where}")
        if changed:
            did.append(f"changed {_plural(changed, 'cell')}")
        if not did:
            did.append("checked it; nothing new to add")
        lines.append("- It " + ", ".join(did) + ".")
        lines.append(f"- Open the sheet: {address(sheet_id)}")

    if blocked:
        names = ", ".join(sorted({t for t, _ in blocked}))
        lines.append(
            f"- **Not saved:** {names} was refused ({blocked[0][1]}). "
            "Set the sheet tools to run automatically under Permissions, then run it again."
        )

    return "---\n**Google Sheet**\n" + "\n".join(lines)
