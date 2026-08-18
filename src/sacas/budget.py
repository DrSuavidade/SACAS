"""Context and token budget calculations for SACAS task context."""

from __future__ import annotations

from pathlib import Path


def estimate_tokens(text: str) -> int:
    """Estimate token count for a given text content."""
    # Standard heuristic: 1 token ~ 4 characters
    return len(text) // 4


def calculate_context_size(repository_root: Path, files: tuple[str, ...]) -> int:
    """Calculate the total estimated tokens for a list of files."""
    total_tokens = 0
    for file_rel in files:
        file_path = repository_root / file_rel
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                total_tokens += estimate_tokens(content)
            except OSError:
                pass
    return total_tokens


def calculate_total_context_size(installation, files: tuple[str, ...]) -> int:
    """Calculate the total estimated tokens for the entire active SACAS context."""
    total_tokens = 0

    # 1. Sum up all source files
    total_tokens += calculate_context_size(installation.repository_root, files)

    # Helper to count tokens of a file if it exists
    def add_file_tokens(path: Path) -> int:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                return estimate_tokens(content)
            except OSError:
                pass
        return 0

    # 2. Add ROUTER.md
    total_tokens += add_file_tokens(installation.sacas_root / "ROUTER.md")

    # 3. Add TASK.md, CONTEXT.md, STATE.md under tasks/current/
    task_dir = installation.sacas_root / "tasks" / "current"
    total_tokens += add_file_tokens(task_dir / "TASK.md")
    total_tokens += add_file_tokens(task_dir / "CONTEXT.md")
    total_tokens += add_file_tokens(task_dir / "STATE.md")

    # 4. Add rules/ recursively
    rules_dir = installation.sacas_root / "rules"
    if rules_dir.is_dir():
        for p in rules_dir.rglob("*"):
            if p.is_file():
                total_tokens += add_file_tokens(p)

    # 5. Add references/ recursively
    refs_dir = installation.sacas_root / "references"
    if refs_dir.is_dir():
        for p in refs_dir.rglob("*"):
            if p.is_file():
                total_tokens += add_file_tokens(p)

    return total_tokens


def get_detailed_context_breakdown(installation, files: tuple[str, ...]) -> dict[str, int]:
    """Return a token count breakdown for different parts of the active context."""
    def add_file_tokens(path: Path) -> int:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                return len(content) // 4
            except OSError:
                pass
        return 0

    source_tokens = calculate_context_size(installation.repository_root, files)
    router_tokens = add_file_tokens(installation.sacas_root / "ROUTER.md")

    task_dir = installation.sacas_root / "tasks" / "current"
    task_tokens = add_file_tokens(task_dir / "TASK.md")
    context_tokens = add_file_tokens(task_dir / "CONTEXT.md")
    state_tokens = add_file_tokens(task_dir / "STATE.md")

    rules_tokens = 0
    rules_dir = installation.sacas_root / "rules"
    if rules_dir.is_dir():
        for p in rules_dir.rglob("*"):
            if p.is_file():
                rules_tokens += add_file_tokens(p)

    refs_tokens = 0
    refs_dir = installation.sacas_root / "references"
    if refs_dir.is_dir():
        for p in refs_dir.rglob("*"):
            if p.is_file():
                refs_tokens += add_file_tokens(p)

    return {
        "source": source_tokens,
        "router": router_tokens,
        "task": task_tokens,
        "context": context_tokens,
        "state": state_tokens,
        "rules": rules_tokens,
        "references": refs_tokens,
        "total": source_tokens + router_tokens + task_tokens + context_tokens + state_tokens + rules_tokens + refs_tokens
    }


