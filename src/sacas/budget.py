"""Context and token budget calculations for SACAS task context."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from sacas.io import read_repo_text

if TYPE_CHECKING:
    from sacas.active_context import ActiveContextManifest
    from sacas.paths import Installation


class Tokenizer(ABC):
    """Abstract base class for tokenizers."""
    
    name: str
    
    @abstractmethod
    def count(self, text: str) -> int:
        """Count tokens in text."""
        pass


class CharHeuristicTokenizer(Tokenizer):
    """Character-based heuristic: 1 token ≈ 4 characters."""
    
    name = "char_heuristic"
    
    def count(self, text: str) -> int:
        return len(text) // 4


class TiktokenTokenizer(Tokenizer):
    """tiktoken-based tokenizer for OpenAI-compatible models."""
    
    name = "tiktoken"
    
    def __init__(self, encoding: str = "cl100k_base"):
        try:
            import tiktoken
            self.enc = tiktoken.get_encoding(encoding)
        except ImportError:
            raise RuntimeError("tiktoken not installed. Install with: pip install tiktoken")
    
    def count(self, text: str) -> int:
        return len(self.enc.encode(text))


# Tokenizer registry
_TOKENIZERS: dict[str, Tokenizer] = {
    "char_heuristic": CharHeuristicTokenizer(),
}


def register_tokenizer(tokenizer: Tokenizer) -> None:
    """Register a tokenizer in the global registry."""
    _TOKENIZERS[tokenizer.name] = tokenizer


def get_tokenizer(name: str) -> Tokenizer:
    """Get a tokenizer by name."""
    if name not in _TOKENIZERS:
        if name == "tiktoken":
            _TOKENIZERS[name] = TiktokenTokenizer()
        else:
            raise ValueError(f"Unknown tokenizer: {name}. Available: {list(_TOKENIZERS.keys())}")
    return _TOKENIZERS[name]


def estimate_tokens(text: str, tokenizer: str = "char_heuristic") -> int:
    """Estimate token count for a given text content using specified tokenizer."""
    return get_tokenizer(tokenizer).count(text)

def calculate_context_size(repository_root: Path, files: tuple[str, ...], tokenizer: str = "char_heuristic") -> int:
    """Calculate the total estimated tokens for a list of files."""
    total_tokens = 0
    tok = get_tokenizer(tokenizer)
    for file_rel in files:
        try:
            content = read_repo_text(repository_root, file_rel)
            total_tokens += tok.count(content)
        except (ValueError, FileNotFoundError, OSError):
            pass
    return total_tokens

def calculate_total_context_size(installation, files: tuple[str, ...], tokenizer: str = "char_heuristic") -> int:
    """Legacy helper for backward compatibility."""
    total_tokens = 0
    total_tokens += calculate_context_size(installation.repository_root, files, tokenizer)

    def add_file_tokens(path: Path) -> int:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                return estimate_tokens(content, tokenizer)
            except OSError:
                pass
        return 0

    def add_repository_file_tokens(path: Path) -> int:
        """Count repository-owned docs only through the secure text boundary."""
        try:
            relative = path.relative_to(installation.repository_root).as_posix()
            return estimate_tokens(read_repo_text(installation.repository_root, relative), tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            return 0

    total_tokens += add_file_tokens(installation.sacas_root / "ROUTER.md")
    task_dir = installation.sacas_root / "tasks" / "current"
    total_tokens += add_file_tokens(task_dir / "TASK.md")
    total_tokens += add_file_tokens(task_dir / "CONTEXT.md")

    rules_dir = installation.sacas_root / "rules"
    if rules_dir.is_dir():
        for p in rules_dir.rglob("*"):
            if p.is_file():
                total_tokens += add_repository_file_tokens(p)

    refs_dir = installation.sacas_root / "references"
    if refs_dir.is_dir():
        for p in refs_dir.rglob("*"):
            if p.is_file():
                total_tokens += add_repository_file_tokens(p)

    return total_tokens

def get_detailed_context_breakdown(installation, files: tuple[str, ...], tokenizer: str = "char_heuristic") -> dict[str, int]:
    """Legacy helper for backward compatibility."""
    def add_file_tokens(path: Path) -> int:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                return estimate_tokens(content, tokenizer)
            except OSError:
                pass
        return 0

    def add_repository_file_tokens(path: Path) -> int:
        """Count repository-owned docs only through the secure text boundary."""
        try:
            relative = path.relative_to(installation.repository_root).as_posix()
            return estimate_tokens(read_repo_text(installation.repository_root, relative), tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            return 0

    source_tokens = calculate_context_size(installation.repository_root, files, tokenizer)
    router_tokens = add_file_tokens(installation.sacas_root / "ROUTER.md")

    task_dir = installation.sacas_root / "tasks" / "current"
    task_tokens = add_file_tokens(task_dir / "TASK.md")
    context_tokens = add_file_tokens(task_dir / "CONTEXT.md")

    rules_tokens = 0
    rules_dir = installation.sacas_root / "rules"
    if rules_dir.is_dir():
        for p in rules_dir.rglob("*"):
            if p.is_file():
                rules_tokens += add_repository_file_tokens(p)

    refs_tokens = 0
    refs_dir = installation.sacas_root / "references"
    if refs_dir.is_dir():
        for p in refs_dir.rglob("*"):
            if p.is_file():
                refs_tokens += add_repository_file_tokens(p)

    return {
        "source": source_tokens,
        "router": router_tokens,
        "task": task_tokens,
        "context": context_tokens,
        "rules": rules_tokens,
        "references": refs_tokens,
        "total": source_tokens + router_tokens + task_tokens + context_tokens + rules_tokens + refs_tokens
    }

from dataclasses import dataclass

@dataclass(frozen=True)
class BudgetPlan:
    limit: int
    control_reserved: int
    explicit_payload: int
    retrieval_budget: int
    automatic_payload_budget: int
    payload_used: int
    remaining: int

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

def compile_budget_report(
    installation: Installation,
    manifest: ActiveContextManifest,
    rendered_views: dict[str, str] | None = None,
    tokenizer: str = "char_heuristic"
) -> BudgetPlan:
    """Calculate the unified context budget plan."""
    from sacas.regions import extract_markdown_section

    limit = installation.manifest.context_budget

    # 1. Payload: Source files (legacy + reference_files + working_files)
    source_tokens = 0
    explicit_source_tokens = 0
    # Use all_files property which combines legacy files + reference_files + working_files
    for f in manifest.all_files:
        f_tokens = 0
        try:
            content = read_repo_text(installation.repository_root, f.path)
            if f.selection.get("mode") == "symbols":
                symbols_content = []
                from sacas.regions import normalize_selections
                from sacas.active_context import ActiveSymbolContext
                raw_symbols = f.selection.get("symbols", [])
                sym_objects = []
                for s in raw_symbols:
                    if isinstance(s, dict):
                        sym_objects.append(ActiveSymbolContext.from_dict(s))
                    else:
                        sym_objects.append(s)
                normalized = normalize_selections(tuple(sym_objects))
                for sym in normalized:
                    name = getattr(sym, "name", None) or (sym.get("name") if isinstance(sym, dict) else None)
                    rng = getattr(sym, "range", None) or (sym.get("range") if isinstance(sym, dict) else None)
                    if rng:
                        start = getattr(rng, "start_line", None) or (rng.get("start_line") if isinstance(rng, dict) else None)
                        end = getattr(rng, "end_line", None) or (rng.get("end_line") if isinstance(rng, dict) else None)
                        lines = content.splitlines()
                        if start is not None and end is not None and 1 <= start <= len(lines) and 1 <= end <= len(lines):
                            symbols_content.append("\n".join(lines[start-1:end]))
                        else:
                            symbols_content.append(content)
                    else:
                        symbols_content.append(content)
                f_tokens = estimate_tokens("\n".join(symbols_content), tokenizer)
            else:
                f_tokens = estimate_tokens(content, tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            pass
        source_tokens += f_tokens
        if f.source == "explicit":
            explicit_source_tokens += f_tokens

    # 2. Payload: Rules
    rule_tokens = 0
    for r in manifest.rules:
        try:
            rule_tokens += estimate_tokens(read_repo_text(installation.repository_root, r.path), tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            pass

    # 3. Payload: References
    reference_tokens = 0
    for ref in manifest.references:
        try:
            content = read_repo_text(installation.repository_root, ref.path)
            if ref.selection.get("mode") == "sections":
                sections_content = []
                for sec in ref.selection.get("sections", []):
                    heading_path = sec.get("heading_path", []) if isinstance(sec, dict) else getattr(sec, "heading_path", [])
                    if heading_path:
                        sections_content.append(extract_markdown_section(content, heading_path))
                reference_tokens += estimate_tokens("\n".join(sections_content), tokenizer)
            else:
                reference_tokens += estimate_tokens(content, tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            pass

    # 4. Control tokens
    control_tokens = 0
    views_to_check = ["ROUTER.md", "TASK.md", "CONTEXT.md"]
    for view_name in views_to_check:
        if rendered_views and view_name in rendered_views:
            control_tokens += estimate_tokens(rendered_views[view_name], tokenizer)
        else:
            if view_name == "ROUTER.md":
                p = installation.sacas_root / "ROUTER.md"
            else:
                p = installation.sacas_root / "tasks" / "current" / view_name
            if p.is_file():
                try:
                    rel_path = p.relative_to(installation.sacas_root).as_posix()
                    control_tokens += estimate_tokens(read_repo_text(installation.sacas_root, rel_path), tokenizer)
                except (ValueError, FileNotFoundError, OSError):
                    pass

    explicit_payload = explicit_source_tokens + rule_tokens + reference_tokens
    payload_used = source_tokens + rule_tokens + reference_tokens
    remaining = max(0, limit - control_tokens - payload_used)
    automatic_payload_budget = max(0, limit - control_tokens - explicit_payload)

    # Graphify structural retrieval budget
    retrieval_budget = 1000

    return BudgetPlan(
        limit=limit,
        control_reserved=control_tokens,
        explicit_payload=explicit_payload,
        retrieval_budget=retrieval_budget,
        automatic_payload_budget=automatic_payload_budget,
        payload_used=payload_used,
        remaining=remaining
    )

def calculate_manifest_tokens(installation: Installation, manifest: ActiveContextManifest, rendered_views: dict[str, str] | None = None, tokenizer: str = "char_heuristic") -> ContextTokenBreakdown:
    """Calculate the unified context breakdown from the ActiveContextManifest using compile_budget_report."""
    plan = compile_budget_report(installation, manifest, rendered_views=rendered_views, tokenizer=tokenizer)
    
    # Calculate rule, reference, source components for ContextTokenBreakdown compat
    # We do a quick count of rules & refs as before
    rule_tokens = 0
    for r in manifest.rules:
        try:
            rule_tokens += estimate_tokens(read_repo_text(installation.repository_root, r.path), tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            pass
            
    reference_tokens = 0
    from sacas.regions import extract_markdown_section
    for ref in manifest.references:
        try:
            content = read_repo_text(installation.repository_root, ref.path)
            if ref.selection.get("mode") == "sections":
                sections_content = []
                for sec in ref.selection.get("sections", []):
                    heading_path = sec.get("heading_path", []) if isinstance(sec, dict) else getattr(sec, "heading_path", [])
                    if heading_path:
                        sections_content.append(extract_markdown_section(content, heading_path))
                reference_tokens += estimate_tokens("\n".join(sections_content), tokenizer)
            else:
                reference_tokens += estimate_tokens(content, tokenizer)
        except (ValueError, FileNotFoundError, OSError):
            pass
            
    # Source tokens include legacy files + reference_files + working_files
    # Use all_files property which combines all three
    source_tokens = max(0, plan.payload_used - rule_tokens - reference_tokens)
    
    return ContextTokenBreakdown(
        limit=plan.limit,
        tokenizer=tokenizer,
        source_tokens=source_tokens,
        rule_tokens=rule_tokens,
        reference_tokens=reference_tokens,
        control_tokens=plan.control_reserved
    )
