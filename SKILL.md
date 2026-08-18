---
name: sacas
description: >
  Use when starting work on any codebase, when onboarding to a new project,
  or when asked to scaffold/generate a folder structure for AI agent navigation.
  Triggers on: /sacas, /sacas-merge, scaffold workspace, generate context structure,
  create AGENTS.md, setup AI workspace, organize codebase for AI.
---

# /sacas — Scaffold Analyzer Context Architect

Generate a task-aware folder structure that gives AI agents precisely scoped context per task. Filesystem = orchestration. Folders = memory. Markdown = interface.

## Usage

Use the Python package `sacas`:

```bash
# Initialize a repository
python -m sacas init

# Build a system map from Graphify
python -m sacas map

# Create a new task
python -m sacas task "Goal" --files src/app.py

# Refresh task context and expand scope
python -m sacas refresh

# Show task status
python -m sacas status

# Validate installation and state
python -m sacas validate
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
