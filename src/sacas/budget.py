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
