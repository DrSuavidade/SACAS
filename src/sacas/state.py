"""Task state management and PICKUP.md generation."""

from __future__ import annotations

import re
from pathlib import Path


def parse_state_checkboxes(content: str) -> tuple[list[str], list[str]]:
    """Parse completed and pending items from a state markdown content."""
    completed: list[str] = []
    pending: list[str] = []
    for line in content.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("- [x]"):
            completed.append(line_stripped[5:].strip())
        elif line_stripped.startswith("- [ ]"):
            pending.append(line_stripped[5:].strip())
    return completed, pending


def generate_pickup_markdown(completed: list[str], pending: list[str]) -> str:
    """Generate PICKUP.md content from parsed state checklist items."""
    summary = "Completed: " + ", ".join(completed) if completed else "No tasks completed yet."
    in_progress = [f"- {item}" for item in pending] if pending else ["- None"]
    priority = [f"1. {pending[0]}"] if pending else ["1. All tasks completed."]
    
    lines = [
        "# PICKUP",
        "",
        "## Last Session Summary",
        summary,
        "",
        "## In-Progress Work",
        *in_progress,
        "",
        "## Open Decisions",
        "- None",
        "",
        "## Known Issues",
        "- None",
        "",
        "## Priority for Next Session",
        *priority,
        ""
    ]
    return "\n".join(lines)


def render_state_markdown(
    task_id: str,
    goal: str,
    criteria: tuple[str, ...],
    verification: tuple[str, ...],
    old_content: str | None = None
) -> str:
    """Render STATE.md checklist, preserving existing checked states if rerun."""
    completed_items: set[str] = set()
    if old_content:
        for line in old_content.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("- [x]"):
                item_text = line_stripped[5:].strip()
                completed_items.add(item_text)
                clean_text = re.sub(r"\s*\((Acceptance Criteria|Verification)\)$", "", item_text)
                completed_items.add(clean_text)

    lines = [
        f"Task: {task_id}",
        f"Goal: {goal}",
        "",
        "## Checklist",
    ]
    
    for item in criteria:
        status = "[x]" if (item in completed_items or f"{item} (Acceptance Criteria)" in completed_items) else "[ ]"
        lines.append(f"- {status} {item} (Acceptance Criteria)")
        
    for item in verification:
        status = "[x]" if (item in completed_items or f"{item} (Verification)" in completed_items) else "[ ]"
        lines.append(f"- {status} {item} (Verification)")
        
    return "\n".join(lines) + "\n"
