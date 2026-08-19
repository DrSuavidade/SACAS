"""Small deterministic documents written by ``sacas init``."""

from __future__ import annotations

from sacas.regions import render_generated_region


def router_document(existing: str | None = None) -> str:
    """Render or update the compact router without replacing human prose."""
    generated = (
        "# SACAS router\n\n"
        "- Rules: `rules/` (protected boundaries are only explicit `MANUAL` entries in "
        "`rules/boundaries.md`)\n"
        "- System map: `map/`\n"
        "- Current task: `tasks/current/`\n"
        "- References: `references/`\n\n"
        "Commands: `sacas status`, `sacas validate`, `sacas task \"<goal>\"`."
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


def claude_md_document() -> str:
    """Layer 0: Workspace identity and navigation (ICM CLAUDE.md)."""
    return """# Workspace Identity

This is a SACAS workspace using Interpretable Context Methodology (ICM).

## Structure

```
Structure/
├── CLAUDE.md              # Layer 0: This file — workspace identity & navigation
├── CONTEXT.md             # Layer 1: Workspace routing & shared resources
├── stages/                # Layer 2: Numbered stage folders (01_xxx, 02_xxx, ...)
│   ├── 01_analyze/
│   │   ├── CONTEXT.md     # Stage contract: inputs, process, outputs
│   │   ├── references/    # Layer 3: Stage-specific stable references
│   │   └── output/        # Layer 4: Working artifacts (handoff to next stage)
│   ├── 02_implement/
│   │   ├── CONTEXT.md
│   │   ├── references/
│   │   └── output/
│   └── 03_verify/
│       ├── CONTEXT.md
│       ├── references/
│       └── output/
├── _config/               # Layer 3: Global stable references (factory config)
│   ├── conventions.md
│   ├── voice.md
│   └── design-system.md
├── map/SYSTEM.md          # Generated codebase map (sacas map)
├── rules/boundaries.md    # Protected scope boundaries
├── .sacas/
│   ├── manifest.json      # Canonical configuration marker
│   └── graphify.json      # Cached Graphify evidence
└── tasks/                 # Legacy task tracking (optional, for non-pipeline work)
    ├── backlog/
    ├── current/
    └── completed/
```

## Navigation

- **Start here**: Read `CONTEXT.md` for workspace routing
- **Run a pipeline**: `sacas pipeline run` (executes stages sequentially with review gates)
- **Run a stage**: `sacas pipeline stage 01_analyze`
- **Review output**: `sacas pipeline review 01_analyze`
- **Ad-hoc task**: `sacas task \"<goal>\"` (uses `tasks/current/`)

## Key Principle

**Filesystem = orchestration. Folders = memory. Markdown = interface.**

Each stage receives focused context (2,000–8,000 tokens) via its `CONTEXT.md` contract.
The agent reads only the files listed in the stage's Inputs table — not the full codebase.
"""


def workspace_context_document() -> str:
    """Layer 1: Workspace routing and shared resources (ICM CONTEXT.md)."""
    return """# Workspace Context

## Purpose

This workspace structures AI-assisted development using staged context delivery.
Each stage loads only the context it needs — avoiding the "lost in the middle" problem.

## Shared Resources (Available to All Stages)

| Resource | Path | Layer | Purpose |
|----------|------|-------|---------|
| Codebase Map | `map/SYSTEM.md` | 1 | Generated dependency graph |
| Conventions | `_config/conventions.md` | 3 | Code style, patterns, naming |
| Voice Guide | `_config/voice.md` | 3 | Tone, terminology, formatting |
| Design System | `_config/design-system.md` | 3 | UI/UX patterns, components |
| Boundaries | `rules/boundaries.md` | 1 | Protected scope boundaries |

## Stage Overview

| Stage | Folder | Purpose |
|-------|--------|---------|
| 01 | `stages/01_analyze/` | Analyze codebase, understand requirements |
| 02 | `stages/02_implement/` | Implement changes based on analysis |
| 03 | `stages/03_verify/` | Test, validate, verify implementation |

## Commands

```bash
# Initialize workspace (run once)
sacas init

# Build system map
sacas map

# Run full pipeline with human review gates
sacas pipeline run

# Run specific stage
sacas pipeline stage 01_analyze

# Review stage output before next stage
sacas pipeline review 01_analyze

# Ad-hoc task (non-pipeline)
sacas task "fix authentication bug" --symbol src/auth.py::login
```

## Token Budgeting

- **Per stage**: 2,000–8,000 focused tokens (Layers 0–4)
- **Monolithic equivalent**: 30,000–50,000 tokens (most irrelevant)
- **Budget enforcement**: `advisory` | `warn` | `enforce` via `sacas task --context-policy`
"""


def stage_context_template(stage_num: int, stage_name: str, purpose: str) -> str:
    """Layer 2: Stage contract template (ICM CONTEXT.md per stage)."""
    stage_id = f"{stage_num:02d}_{stage_name}"
    prev_stage = f"{stage_num-1:02d}_*" if stage_num > 1 else "none"
    
    return f"""# Stage {stage_num}: {stage_name.replace('_', ' ').title()}

**Stage ID**: `{stage_id}`
**Purpose**: {purpose}

---

## Inputs

- Layer 4 (working): `../{prev_stage}/output/`  # Output from previous stage
- Layer 3 (reference): `../../_config/conventions.md`  # Code conventions
- Layer 3 (reference): `../../_config/voice.md`  # Voice & tone guide
- Layer 3 (reference): `references/`  # Stage-specific references (add as needed)

---

## Process

1. Read the inputs listed above
2. {purpose}
3. Write outputs to `output/` folder

**Constraints**:
- Follow conventions in `_config/conventions.md`
- Match tone in `_config/voice.md`
- Respect boundaries in `../../rules/boundaries.md`

---

## Outputs

- `output.md` -> `output/`  # Primary deliverable for next stage
- Additional files as needed -> `output/`

---

## Review Gate

**Human review required before next stage runs.**

Check `output/` for:
- [ ] Completeness
- [ ] Accuracy
- [ ] Alignment with stage purpose
- [ ] Adherence to conventions

Edit files in `output/` directly if changes needed. Next stage reads whatever is there.
"""


def config_conventions_document() -> str:
    """Layer 3: Global code conventions (factory config)."""
    return """# Code Conventions

Configure once. Stable across all runs. Internalize as constraints.

## Language & Framework

- Language: Python 3.11+
- Framework: None (pure Python CLI)
- Style: PEP 8, type hints required

## Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Files | snake_case | `active_context.py` |
| Classes | PascalCase | `ActiveContextManifest` |
| Functions | snake_case | `load_active_context` |
| Constants | UPPER_SNAKE_CASE | `MAX_TOKENS` |
| Private | _leading_underscore | `_internal_helper` |

## Code Patterns

- Use `dataclass(frozen=True, slots=True)` for data models
- Prefer `tuple` over `list` for immutable sequences
- Use `from __future__ import annotations` for forward references
- Explicit type hints on all public functions
- No `Any` unless absolutely necessary

## Error Handling

- Raise specific exceptions, not generic `Exception`
- Use `ValueError` for invalid arguments
- Use `FileNotFoundError` for missing files
- Log errors with context, don't swallow

## Testing

- Test file: `tests/test_<module>.py`
- Use `pytest` with fixtures
- Mock external dependencies
- Aim for >80% coverage on core logic
"""


def config_voice_document() -> str:
    """Layer 3: Voice and tone guide (factory config)."""
    return """# Voice & Tone Guide

Configure once. Stable across all runs. Internalize as constraints.

## Tone

- **Concise**: Prefer 1-3 sentences. Avoid preamble/postamble.
- **Direct**: Answer the question first, then elaborate if needed.
- **Technical**: Use precise terminology. No hand-waving.
- **Actionable**: Give commands, not suggestions.

## Formatting

- Code references: `file_path:line_number`
- Commands: `bash command --flag`
- File paths: `src/module.py`
- Symbols: `module::ClassName.method`

## Prohibited

- Emojis (unless explicitly requested)
- "Here is...", "Based on...", "The answer is..."
- Unnecessary introductions/conclusions
- Marketing language ("powerful", "seamless", "robust")

## Examples

| Instead of | Use |
|------------|-----|
| "Here is the implementation..." | `src/auth.py:42` |
| "You should run..." | `npm test` |
| "This powerful feature enables..." | "This feature enables..." |
"""


def config_design_system_document() -> str:
    """Layer 3: Design system (factory config)."""
    return """# Design System

Configure once. Stable across all runs. Internalize as constraints.

## Colors

| Role | Hex | Usage |
|------|-----|-------|
| Primary | `#0066CC` | Buttons, links, active states |
| Secondary | `#6C757D` | Muted text, borders |
| Success | `#28A745` | Success messages, passed tests |
| Warning | `#FFC107` | Warnings, deprecated |
| Danger | `#DC3545` | Errors, failed tests |
| Background | `#FFFFFF` | Page background |
| Surface | `#F8F9FA` | Cards, panels |

## Typography

- **Font**: System UI stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto`)
- **Monospace**: `ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas`
- **Base size**: 16px
- **Line height**: 1.5

## Spacing

- **Unit**: 4px
- **Scale**: 4, 8, 12, 16, 24, 32, 48, 64

## Components

| Component | Variants | States |
|-----------|----------|--------|
| Button | primary, secondary, ghost | default, hover, active, disabled |
| Input | text, textarea, select | default, focus, error, disabled |
| Card | default, elevated | default, hover |
| Badge | default, success, warning, danger | — |

## Icons

- Use Lucide icons (SVG)
- Size: 16px, 20px, 24px
- Stroke width: 2px
"""


def stage_output_readme(stage_num: int, stage_name: str) -> str:
    """Layer 4: Output folder README (working artifacts)."""
    stage_id = f"{stage_num:02d}_{stage_name}"
    return f"""# Stage {stage_num} Output: {stage_name.replace('_', ' ').title()}

**Stage ID**: `{stage_id}`
**Layer**: 4 (Working Artifacts — changes every run)

## Contents

This folder contains the working artifacts produced by stage {stage_num}.
These files are the **handoff** to the next stage.

## Files

| File | Description |
|------|-------------|
| `output.md` | Primary deliverable (edit before next stage) |
| `*.md` | Additional artifacts as needed |

## Human Review

**Before running the next stage**, review and edit files in this folder.
The next stage reads exactly what is here — your edits become its input.

```bash
# Review this stage's output
sacas pipeline review {stage_id}

# Then run next stage
sacas pipeline stage {{next_stage}}
```

## Token Note

These are **Layer 4 (working)** artifacts — processed as input by the next stage.
They are NOT internalized as constraints like Layer 3 references.
"""
