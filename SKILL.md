---
name: sacas
description: >
  Use when a SACAS installation already exists in the workspace, when explicitly
  invoked via /sacas command, or when the user asks for context architecture/AI repo organization.
  Do NOT auto-initialize merely because coding work begins.
  Triggers on: /sacas, sacas init, explicit user request for context architecture.
---

# /sacas — Scaffold Analyzer Context Architect

Generate a task-aware folder structure that gives AI agents precisely scoped context per task. Filesystem = orchestration. Folders = memory. Markdown = interface.

## When to Use

- **Auto-activate** when `.sacas` / `Structure` installation already exists in the workspace
- **Auto-activate** when user explicitly invokes `/sacas` or `sacas init`
- **Suggest** when onboarding to a large unfamiliar repository (>50 files) and user asks for context help
- **Do NOT auto-initialize** merely because coding work begins

## Usage

Use the Python package `sacas`:

```bash
# Initialize a repository (lean context router)
sacas init

# Initialize with ICM workflow (stages + _config)
sacas init --workflow

# Build a system map from Graphify
sacas map

# Create a new task
sacas task "Goal" --files src/app.py

# Refresh task context and expand scope
sacas refresh

# Admit an explicit file, symbol, rule, or reference with an audit reason
sacas expand --symbol src/app.py::main --reason "Task entry point"

# Show task status
sacas status

# Validate installation and state
sacas validate

# Diagnose ignore boundaries and configuration health
sacas doctor

# Run context size simulations
sacas context-simulation

# Run actual task routing quality benchmarks
sacas benchmark

# Generate historical Git benchmarks
sacas histbench --generate-only

# Explain why a file/symbol is in context
sacas why src/auth.py

# Use the optional ICM workflow: inspect stages, then orchestrate or run/review one
sacas pipeline list
sacas pipeline orchestrate --start 01_analyze
sacas pipeline stage 02_implement
sacas pipeline review 02_implement
```

## Structure

**Lean (default `sacas init`):**
```
your-project/
├── .aiignore                  # Root ignore config
├── .cursorignore              # Root ignore config
└── Structure/                 # Configurable sub-directory
    ├── ROUTER.md              # SACAS router guide
    ├── rules/
    │   └── boundaries.md      # Protected scope boundaries (MANUAL entries only)
    ├── map/
    │   └── SYSTEM.md          # Generated codebase map
    ├── references/
    ├── tasks/
    │   └── current/
    │       ├── task.json      # Canonical TaskContract (goal, criteria, constraints, verification)
    │       ├── active_context.json  # Canonical ActiveContextManifest (admitted files, symbols, budget)
    │       ├── TASK.md        # Current task goal and contract (rendered view)
    │       ├── CONTEXT.md     # Scoped files, symbols, budget (rendered view)
    │       ├── STATE.md       # Checklist of task items (rendered view)
    │       └── PICKUP.md      # Cross-session handoff (rendered view)
    └── .sacas/
        ├── manifest.json      # Canonical configuration marker
        └── graphify.json      # Cached Graphify evidence
```

**With `--workflow` (`sacas init --workflow`):**
```
your-project/
└── Structure/
    ├── CLAUDE.md              # Workspace identity
    ├── CONTEXT.md             # Workspace routing
    ├── _config/
    │   ├── conventions.md
    │   ├── voice.md
    │   └── design-system.md
    ├── stages/
    │   ├── 01_analyze/
    │   │   ├── CONTEXT.md     # Stage contract
    │   │   ├── references/
    │   │   └── output/
    │   ├── 02_implement/
    │   │   ├── CONTEXT.md
    │   │   ├── references/
    │   │   └── output/
    │   └── 03_verify/
    │       ├── CONTEXT.md
    │       ├── references/
    │       └── output/
    └── ... (lean structure)
```

## Key Principle

`task.json` and `active_context.json` are the canonical pair. `task.json` records task intent; `active_context.json` records admitted selectors, source hashes, provenance, and budget. Each task gets a compiled context that lists exactly which files and symbols are relevant, with line ranges and token budgets. The agent receives the minimal auditable context — not the full codebase.

For routine operation, create or update the task with `sacas task`, use `sacas refresh` to recompile canonical state, use `sacas expand` only for explicit audited admissions, inspect decisions with `sacas why`, check health with `sacas doctor`, inspect freshness with `sacas status`, and run `sacas validate` before handing context to an agent.

## New Capabilities

- **Symbol-range routing**: Graphify results are automatically reduced to exact symbol ranges (Python AST, heuristic for other languages)
- **Provenance tracking**: `sacas why <file>` shows Task → Graphify → edge → admission → context pack → file
- **Historical benchmarks**: `sacas histbench` generates gold tasks from git commit history
- **Context compiler**: `.sacas/runtime/context.pack.jsonl` ephemeral payload for agent consumption
- **Incremental invalidation**: File hash changes trigger selective re-routing of affected selectors only
