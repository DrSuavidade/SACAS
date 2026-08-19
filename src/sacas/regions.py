"""Safe replacement of explicitly SACAS-owned generated regions."""

from __future__ import annotations

import re
from pathlib import Path


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


def extract_markdown_section(content: str, heading_path: list[str]) -> str:
    """Extract a specific markdown section defined by a hierarchical heading path."""
    if not heading_path:
        return content

    lines = content.splitlines()
    
    def normalize_heading(h: str) -> str:
        # Strip Markdown heading chars and normalize
        h_clean = h.lstrip("#").strip().lower()
        # Convert spaces/specials to slugs
        h_clean = re.sub(r"[^a-z0-9\s-]", "", h_clean)
        return re.sub(r"[\s-]+", "-", h_clean).strip("-")

    target_slugs = [normalize_heading(h) for h in heading_path]
    current_level = 0
    matched_indices = [] # Indices in target_slugs we have matched
    
    start_line_idx = -1
    matched_level = -1

    for idx, line in enumerate(lines):
        if line.startswith("#"):
            match = re.match(r"^(#+)\s+(.+)$", line)
            if not match:
                continue
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            heading_slug = normalize_heading(heading_text)
            
            # Check if this heading matches the next target slug in the path
            next_idx_to_match = len(matched_indices)
            if next_idx_to_match < len(target_slugs):
                if heading_slug == target_slugs[next_idx_to_match]:
                    # Must be a child (larger level) of the previously matched heading
                    if not matched_indices or level > matched_level:
                        matched_indices.append(idx)
                        matched_level = level
                        if len(matched_indices) == len(target_slugs):
                            start_line_idx = idx
                            continue

            # If we are already fully matched, any heading of same or higher level ends our section
            if start_line_idx != -1 and level <= matched_level:
                return "\n".join(lines[start_line_idx:idx])

    if start_line_idx != -1:
        return "\n".join(lines[start_line_idx:])
        
    return content


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
        
        full_path = installation.repository_root / file_path
        if not full_path.is_file():
            return None
            
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception:
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
