"""Small deterministic documents written by ``sacas init``."""

from __future__ import annotations

from sacas.regions import render_generated_region


def router_document(existing: str | None = None) -> str:
    """Render or update the compact router without replacing human prose."""
    generated = (
        "# SACAS router\n\n"
        "- Rules: `rules/` (protected boundaries are only explicit `MANUAL` entries in "
        "`rules/boundaries.md`)\n"
        "- Current task: `tasks/current/`\n"
        "- References: `references/`\n\n"
        "Commands: `sacas prepare \"<goal>\"`, `sacas add --file <path>`, `sacas explain <path>`."
    )
    region = render_generated_region("router", generated)
    if existing is None:
        return "# Repository router\n\n" + region
    if "<!-- SACAS:START router -->" not in existing:
        separator = "" if not existing or existing.endswith("\n\n") else "\n"
        return existing + separator + region
    from sacas.regions import replace_generated_region

    return replace_generated_region(existing, "router", generated)


def boundaries_document() -> str:
    """Describe the sole user-controlled protected-boundary rule format."""
    return """# Protected boundaries

This file is human-authored: only MANUAL entries define protected scope boundaries.
SACAS never infers protected boundaries from Graphify communities,
module names, or repository layout.

Add one boundary per line:

```text
MANUAL path/to/protected-area/ | reason for the boundary
```
"""
