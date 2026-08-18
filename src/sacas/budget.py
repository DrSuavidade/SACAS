"""Context and token budget calculations for SACAS task context."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sacas.active_context import ActiveContextManifest
    from sacas.paths import Installation

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
    """Legacy helper for backward compatibility."""
    total_tokens = 0
    total_tokens += calculate_context_size(installation.repository_root, files)

    def add_file_tokens(path: Path) -> int:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                return estimate_tokens(content)
            except OSError:
                pass
        return 0

    total_tokens += add_file_tokens(installation.sacas_root / "ROUTER.md")
    task_dir = installation.sacas_root / "tasks" / "current"
    total_tokens += add_file_tokens(task_dir / "TASK.md")
    total_tokens += add_file_tokens(task_dir / "CONTEXT.md")
    total_tokens += add_file_tokens(task_dir / "STATE.md")

    rules_dir = installation.sacas_root / "rules"
    if rules_dir.is_dir():
        for p in rules_dir.rglob("*"):
            if p.is_file():
                total_tokens += add_file_tokens(p)

    refs_dir = installation.sacas_root / "references"
    if refs_dir.is_dir():
        for p in refs_dir.rglob("*"):
            if p.is_file():
                total_tokens += add_file_tokens(p)

    return total_tokens

def get_detailed_context_breakdown(installation, files: tuple[str, ...]) -> dict[str, int]:
    """Legacy helper for backward compatibility."""
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

class ContextTokenBreakdown:
    def __init__(self, limit: int, tokenizer: str, source_tokens: int, rule_tokens: int, reference_tokens: int, control_tokens: int):
        self.limit = limit
        self.tokenizer = tokenizer
        self.source_tokens = source_tokens
        self.rule_tokens = rule_tokens
        self.reference_tokens = reference_tokens
        self.control_tokens = control_tokens
        self.used = source_tokens + rule_tokens + reference_tokens + control_tokens

    def to_dict(self) -> dict[str, int | str]:
        return {
            "limit": self.limit,
            "used": self.used,
            "tokenizer": self.tokenizer,
            "source_tokens": self.source_tokens,
            "rule_tokens": self.rule_tokens,
            "reference_tokens": self.reference_tokens,
            "control_tokens": self.control_tokens,
        }

def calculate_manifest_tokens(installation: Installation, manifest: ActiveContextManifest) -> ContextTokenBreakdown:
    """Calculate the unified context breakdown from the ActiveContextManifest."""
    from sacas.regions import extract_symbol_range, extract_markdown_section

    tokenizer = "char_heuristic"
    limit = installation.manifest.context_budget

    # 1. Payload: Source files
    source_tokens = 0
    for f in manifest.files:
        f_path = installation.repository_root / f.path
        if f_path.is_file():
            try:
                content = f_path.read_text(encoding="utf-8", errors="ignore")
                if f.selection.get("mode") == "symbols":
                    # Sum tokens of selected symbols/ranges
                    symbols_content = []
                    for sym in f.selection.get("symbols", []):
                        if sym.range:
                            start = sym.range.start_line
                            end = sym.range.end_line
                            lines = content.splitlines()
                            if 1 <= start <= len(lines) and 1 <= end <= len(lines):
                                symbols_content.append("\n".join(lines[start-1:end]))
                        else:
                            # Heuristic extraction starting from None end range
                            # Just load the whole file or try extraction (let's fallback to whole file for safety if no range)
                            symbols_content.append(content)
                    source_tokens += estimate_tokens("\n".join(symbols_content))
                else:
                    source_tokens += estimate_tokens(content)
            except OSError:
                pass

    # 2. Payload: Rules
    rule_tokens = 0
    for r in manifest.rules:
        r_path = installation.repository_root / r.path
        if r_path.is_file():
            try:
                rule_tokens += estimate_tokens(r_path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass

    # 3. Payload: References
    reference_tokens = 0
    for ref in manifest.references:
        ref_path = installation.repository_root / ref.path
        if ref_path.is_file():
            try:
                content = ref_path.read_text(encoding="utf-8", errors="ignore")
                if ref.selection.get("mode") == "sections":
                    sections_content = []
                    for sec in ref.selection.get("sections", []):
                        heading_path = sec.get("heading_path", [])
                        if heading_path:
                            sections_content.append(extract_markdown_section(content, heading_path))
                    reference_tokens += estimate_tokens("\n".join(sections_content))
                else:
                    reference_tokens += estimate_tokens(content)
            except OSError:
                pass

    # 4. Control tokens
    control_tokens = 0
    def add_file_tokens(path: Path) -> int:
        if path.is_file():
            try:
                return estimate_tokens(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
        return 0

    control_tokens += add_file_tokens(installation.sacas_root / "ROUTER.md")
    task_dir = installation.sacas_root / "tasks" / "current"
    control_tokens += add_file_tokens(task_dir / "TASK.md")
    control_tokens += add_file_tokens(task_dir / "CONTEXT.md")
    control_tokens += add_file_tokens(task_dir / "STATE.md")

    return ContextTokenBreakdown(
        limit=limit,
        tokenizer=tokenizer,
        source_tokens=source_tokens,
        rule_tokens=rule_tokens,
        reference_tokens=reference_tokens,
        control_tokens=control_tokens
    )
