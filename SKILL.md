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
# Initialize a repository
sacas init

# Build a system map from Graphify
sacas map

# Create a new task
sacas task "Goal" --files src/app.py

# Refresh task context and expand scope
sacas refresh

# Show task status
sacas status

# Validate installation and state
sacas validate

# Run context size simulations
sacas context-simulation

# Run actual task routing quality benchmarks
sacas benchmark
```

## Structure

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
    ├── tasks/
    │   └── current/
    │       ├── TASK.md        # Current task goal and contract
    │       ├── CONTEXT.md     # Scoped files, symbols, budget
    │       ├── STATE.md       # Checklist of task items
    │       └── PICKUP.md      # Cross-session handoff
    └── .sacas/
        ├── manifest.json      # Canonical configuration marker
        └── graphify.json      # Cached Graphify evidence
```

## Key Principle

`CONTEXT.md` is the token-saving secret. Each task gets a `CONTEXT.md` that lists exactly which files and symbols are relevant. The agent reads only those files — not the full codebase.
