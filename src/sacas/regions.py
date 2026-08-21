"""Safe replacement of explicitly SACAS-owned generated regions."""

from __future__ import annotations

import re
from pathlib import Path

from sacas.io import read_repo_text


class RegionError(ValueError):
    """Raised when a generated region is absent, duplicated, or malformed."""


def replace_generated_region(document: str, name: str, generated: str) -> str:
    """Replace exactly one named SACAS region without touching manual content."""
    _validate_name(name)
    start = re.compile(rf"<!-- SACAS:START {re.escape(name)} -->\r?\n?")
    end = re.compile(rf"<!-- SACAS:END {re.escape(name)} -->")
    starts = list(start.finditer(document))
    ends = list(end.finditer(document))
    if len(starts) != 1 or len(ends) != 1 or starts[0].start() >= ends[0].start():
        raise RegionError(f"Expected one complete SACAS region named {name!r}.")

    content = _normalize_generated(generated)
    replacement = f"{content}\n" if content else ""
    return document[: starts[0].end()] + replacement + document[ends[0].start() :]


def render_generated_region(name: str, generated: str) -> str:
    """Render a deterministic, standalone generated region."""
    _validate_name(name)
    content = _normalize_generated(generated)
    body = f"{content}\n" if content else ""
    return f"<!-- SACAS:START {name} -->\n{body}<!-- SACAS:END {name} -->\n"


def replace_region(document: str, name: str, generated: str) -> str:
    """Backward-compatible name for :func:`replace_generated_region`."""
    return replace_generated_region(document, name, generated)


def render_region(name: str, generated: str) -> str:
    """Backward-compatible name for :func:`render_generated_region`."""
    return render_generated_region(name, generated)


def _normalize_generated(generated: str) -> str:
    return generated.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _validate_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise RegionError("Region names may contain only letters, digits, '.', '_', and '-'.")


def extract_symbol_range(content: str, start_line: int, file_path: str) -> tuple[int, int]:
    """Fallback logic to find the line range of a symbol starting at start_line."""
    lines = content.splitlines()
    if start_line < 1 or start_line > len(lines):
        return (start_line, start_line)

    ext = Path(file_path).suffix.lower()
    is_python = ext in (".py", ".pyw")

    if is_python:
        # Indentation-based block parsing
        start_idx = start_line - 1
        start_line_content = lines[start_idx]
        start_indent = len(start_line_content) - len(start_line_content.lstrip())
        
        # If line is empty or starts with comment, just return single line
        if not start_line_content.strip() or start_line_content.strip().startswith("#"):
            return (start_line, start_line)
            
        end_idx = start_idx
        for i in range(start_idx + 1, len(lines)):
            line = lines[i]
            # Ignore empty/comment-only lines for indentation drops
            if not line.strip() or line.strip().startswith("#"):
                end_idx = i
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= start_indent:
                break
            end_idx = i
        return (start_line, end_idx + 1)
    else:
        # Brace-based block parsing (JS, TS, C, Go, Java, Rust, etc.)
        start_idx = start_line - 1
        brace_count = 0
        has_braces = False
        end_idx = start_idx
        
        for i in range(start_idx, len(lines)):
            line = lines[i]
            # Remove comments/strings to avoid false brace counts
            cleaned = re.sub(r"//.*|/\*.*?\*/|#.*", "", line)
            cleaned = re.sub(r'".*?"|\'.*?\'|`.*?`', "", cleaned)
            
            for ch in cleaned:
                if ch == "{":
                    brace_count += 1
                    has_braces = True
                elif ch == "}":
                    brace_count -= 1
                    
            end_idx = i
            if has_braces and brace_count <= 0:
                break
        return (start_line, end_idx + 1)


def _normalize_heading(h: str) -> str:
    # Strip Markdown heading chars and normalize
    h_clean = h.lstrip("#").strip().lower()
    # Convert spaces/specials to slugs
    h_clean = re.sub(r"[^a-z0-9\s-]", "", h_clean)
    return re.sub(r"[\s-]+", "-", h_clean).strip("-")


def find_markdown_section_range(content: str, heading_path: list[str]) -> tuple[int, int] | None:
    """Locate the 1-based inclusive line range of a hierarchical markdown section.

    Returns ``None`` when the heading path cannot be fully matched.
    """
    if not heading_path:
        return None

    lines = content.splitlines()
    target_slugs = [_normalize_heading(h) for h in heading_path]
    matched_indices: list[int] = []

    start_line_idx = -1
    matched_level = -1

    for idx, line in enumerate(lines):
        if line.startswith("#"):
            match = re.match(r"^(#+)\s+(.+)$", line)
            if not match:
                continue
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            heading_slug = _normalize_heading(heading_text)

            next_idx_to_match = len(matched_indices)
            if next_idx_to_match < len(target_slugs):
                if heading_slug == target_slugs[next_idx_to_match]:
                    if not matched_indices or level > matched_level:
                        matched_indices.append(idx)
                        matched_level = level
                        if len(matched_indices) == len(target_slugs):
                            start_line_idx = idx
                        # A matched heading never closes or resets its own hierarchy.
                        continue

            # A fully matched section ends at the first same-or-higher heading.
            if start_line_idx != -1 and level <= matched_level:
                return (start_line_idx + 1, idx)

            # An incomplete hierarchy whose ancestor closed before the child
            # appeared must reset; otherwise a sibling branch's deeper heading
            # is wrongly accepted as a cross-parent match.
            if start_line_idx == -1 and matched_indices and level <= matched_level:
                matched_indices = []
                matched_level = -1

    if start_line_idx != -1:
        return (start_line_idx + 1, len(lines))

    return None


def extract_markdown_section(
    content: str,
    heading_path: list[str],
    *,
    strict: bool = False,
) -> str:
    """Extract a specific markdown section defined by a hierarchical heading path.

    Legacy callers retain the whole-document fallback. Compilers can request
    ``strict`` selection so a stale heading never silently broadens context.
    """
    found = find_markdown_section_range(content, heading_path)
    if found is None:
        if strict and heading_path:
            raise LookupError(f"markdown heading path not found: {' > '.join(heading_path)}")
        return content

    start, end = found
    return "\n".join(content.splitlines()[start - 1:end])


def resolve_section_ranges(
    repository_root: Path,
    path: str,
    selection: dict,
    *,
    content: str | None = None,
) -> dict:
    """Fill missing 1-based ``start``/``end`` lines into a sections-mode selection.

    Sections whose heading path cannot be located raise ``LookupError`` so a
    broken reference fails loudly instead of silently shrinking context.
    """
    if selection.get("mode") != "sections":
        return selection

    if content is None:
        content = read_repo_text(repository_root, path)

    resolved_sections = []
    for sec in selection.get("sections", []):
        heading_path = sec.get("heading_path", [])
        resolved = dict(sec)
        if "start" not in resolved or "end" not in resolved:
            found = find_markdown_section_range(content, list(heading_path))
            if found is None:
                raise LookupError(
                    f"markdown heading path not found in {path}: {' > '.join(map(str, heading_path))}"
                )
            resolved["start"], resolved["end"] = found
        resolved_sections.append(resolved)

    return {"mode": "sections", "sections": resolved_sections}


import ast
from sacas.active_context import SourceRange

def find_python_ast_symbol_range(content: str, symbol_name: str) -> tuple[int, int] | None:
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == symbol_name:
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    return (start, end)
    except Exception:
        pass
    return None


def find_heuristic_symbol_line(content: str, symbol_name: str, file_path: str) -> int | None:
    lines = content.splitlines()
    patterns = [
        re.compile(rf"\b(def|class|function|func|interface|struct)\s+{re.escape(symbol_name)}\b"),
        re.compile(rf"\bconst\s+{re.escape(symbol_name)}\b\s*="),
        re.compile(rf"\b{re.escape(symbol_name)}\s*:=\s*func"),
        re.compile(rf"\b{re.escape(symbol_name)}\b")
    ]
    for pattern in patterns:
        for idx, line in enumerate(lines):
            if pattern.search(line):
                return idx + 1
    return None


class SymbolRangeResolver:
    @staticmethod
    def resolve(installation, file_path: str, symbol_name: str) -> SourceRange | None:
        from sacas.graphify import get_graphify_provider
        
        try:
            content = read_repo_text(installation.repository_root, file_path)
        except (ValueError, FileNotFoundError, OSError):
            return None

        # Tier 1: Graphify provider locate_symbol
        provider = get_graphify_provider(installation, required={"symbol_locations"})
        if provider.verify_capabilities({"symbol_locations"}):
            loc = provider.locate_symbol(file_path, symbol_name)
            if loc:
                return SourceRange(start_line=loc[0], end_line=loc[1], source="graphify", confidence=1.0)

        # Tier 2: Python AST parser
        if file_path.endswith((".py", ".pyw")):
            ast_range = find_python_ast_symbol_range(content, symbol_name)
            if ast_range:
                return SourceRange(start_line=ast_range[0], end_line=ast_range[1], source="parser", confidence=1.0)

        # Tier 3: Language heuristic
        line_num = find_heuristic_symbol_line(content, symbol_name, file_path)
        if line_num:
            r = extract_symbol_range(content, line_num, file_path)
            return SourceRange(start_line=r[0], end_line=r[1], source="heuristic", confidence=0.72)

        return None

    @staticmethod
    def resolve_node_range(installation, file_path: str, node_label: str | None, node_line: int | None) -> tuple[dict[str, Any], str] | None:
        """Resolve a node to the best symbol range selection.
        Returns (selection_dict, reason) or None.
        """
        try:
            content = read_repo_text(installation.repository_root, file_path)
        except (ValueError, FileNotFoundError, OSError):
            return None

        # 1. Try resolving enclosing symbol at line (Python AST)
        if file_path.endswith((".py", ".pyw")) and node_line is not None:
            res = find_python_ast_symbol_at_line(content, node_line)
            if res:
                name, start, end = res
                from sacas.active_context import ActiveSymbolContext, SourceRange
                sym_ctx = ActiveSymbolContext(
                    name=name,
                    range=SourceRange(start_line=start, end_line=end, source="parser", confidence=1.0),
                    reason=f"Enclosing symbol for line {node_line}"
                )
                return {"mode": "symbols", "symbols": [sym_ctx]}, f"Resolved enclosing symbol '{name}' (lines {start}-{end})"

        # 2. Try resolving exact symbol by label/name
        if node_label:
            sym_name = node_label.split(".")[-1]
            rng = SymbolRangeResolver.resolve(installation, file_path, sym_name)
            if rng:
                from sacas.active_context import ActiveSymbolContext
                sym_ctx = ActiveSymbolContext(
                    name=node_label,
                    range=rng,
                    reason=f"Resolved symbol by name: {node_label}"
                )
                return {"mode": "symbols", "symbols": [sym_ctx]}, f"Resolved symbol '{node_label}' (lines {rng.start_line}-{rng.end_line})"

        # 3. Try line-range extraction starting from line
        if node_line is not None:
            r = extract_symbol_range(content, node_line, file_path)
            from sacas.active_context import ActiveSymbolContext, SourceRange
            name = node_label or f"line_{node_line}"
            sym_ctx = ActiveSymbolContext(
                name=name,
                range=SourceRange(start_line=r[0], end_line=r[1], source="heuristic", confidence=0.72),
                reason=f"Extracted block around line {node_line}"
            )
            return {"mode": "symbols", "symbols": [sym_ctx]}, f"Extracted block around line {node_line} (lines {r[0]}-{r[1]})"

        return None


def find_python_ast_symbol_at_line(content: str, line_num: int) -> tuple[str, int, int] | None:
    import ast
    try:
        tree = ast.parse(content)
        best_match = None
        for ast_node in ast.walk(tree):
            if isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if hasattr(ast_node, "lineno") and hasattr(ast_node, "end_lineno"):
                    if ast_node.lineno <= line_num <= ast_node.end_lineno:
                        if best_match is None or (ast_node.end_lineno - ast_node.lineno < best_match[2] - best_match[1]):
                            best_match = (ast_node.name, ast_node.lineno, ast_node.end_lineno)
        return best_match
    except Exception:
        pass
    return None


def merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping and adjacent line ranges.
    
    Args:
        ranges: List of (start_line, end_line) tuples
        
    Returns:
        List of merged (start_line, end_line) tuples, sorted by start_line
    """
    if not ranges:
        return []
    
    # Sort by start line
    sorted_ranges = sorted(ranges, key=lambda x: x[0])
    
    merged = []
    current_start, current_end = sorted_ranges[0]
    
    for start, end in sorted_ranges[1:]:
        # If overlapping or adjacent (current_end + 1 >= start)
        if start <= current_end + 1:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end
    
    merged.append((current_start, current_end))
    return merged


def normalize_selections(symbols: tuple[ActiveSymbolContext, ...]) -> tuple[ActiveSymbolContext, ...]:
    """Merge overlapping and adjacent line ranges and deduplicate symbols."""
    if not symbols:
        return ()

    from sacas.active_context import ActiveSymbolContext, SourceRange

    with_range = [s for s in symbols if s.range is not None]
    without_range = [s for s in symbols if s.range is None]

    if not with_range:
        # Deduplicate without_range by name
        seen_names = set()
        dedup_without = []
        for s in without_range:
            if s.name not in seen_names:
                seen_names.add(s.name)
                dedup_without.append(s)
        return tuple(dedup_without)

    with_range.sort(key=lambda s: s.range.start_line)

    merged = []
    current = with_range[0]

    for next_sym in with_range[1:]:
        if next_sym.range.start_line <= current.range.end_line + 1:
            new_end = max(current.range.end_line, next_sym.range.end_line)
            names = []
            for n in (current.name, next_sym.name):
                if n not in names:
                    names.append(n)
            combined_name = ", ".join(names)

            reasons = []
            for r in (current.reason, next_sym.reason):
                if r and r not in reasons:
                    reasons.append(r)
            combined_reason = "; ".join(reasons) if reasons else None

            current = ActiveSymbolContext(
                name=combined_name,
                range=SourceRange(
                    start_line=current.range.start_line,
                    end_line=new_end,
                    source=current.range.source,
                    confidence=max(current.range.confidence, next_sym.range.confidence)
                ),
                reason=combined_reason
            )
        else:
            merged.append(current)
            current = next_sym
    merged.append(current)

    seen_names = set()
    dedup_without = []
    for s in without_range:
        if s.name not in seen_names:
            seen_names.add(s.name)
            dedup_without.append(s)

    return tuple(merged + dedup_without)
