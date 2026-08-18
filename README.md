# SACAS — Scaffold Architect Context Analyzer Skill

SACAS routes repository evidence into focused task context for AI-assisted software development.

## Installation

Requires Python 3.11+. Install the package in editable development mode:

```bash
python -m pip install -e ".[test]"
```

## CLI Commands

All commands support `--root <path>` to target a specific repository directory.

### `sacas init`
Initialize SACAS in a repository. Creates the default `Structure/` directory with `ROUTER.md`, rules, and platform-specific adapters.

```bash
sacas init --sacas-root Structure
```

### `sacas map`
Build a system map from optional Graphify evidence.

```bash
sacas map --mode existing
```

### `sacas task`
Generate task contracts and context files under `Structure/tasks/current/` (`TASK.md`, `CONTEXT.md`, `STATE.md`, and `PICKUP.md`).

```bash
sacas task "Implement user authentication" --files src/auth.py --criteria "User can log in"
```

### `sacas refresh`
Refresh file hashes in the active task context and progressively expand context using Graphify evidence. Respects protected boundaries.

```bash
sacas refresh
```

### `sacas status`
Show the status, staleness, and budget consumption of the active task. Supports `--format text|json`.

```bash
sacas status --format json
```

### `sacas validate`
Run cold-agent validation diagnostics (manifest, regions, missing references, state drift, budget, etc.). Supports `--format text|json`.

```bash
sacas validate
```

### `sacas migrate`
Migrate legacy PowerShell SACAS structures (like `PROGRESS.md`) to the new Python CLI structures (`STATE.md`). Use `--apply` to execute changes.

```bash
sacas migrate --apply
```

### `sacas benchmark`
Run actual routing quality benchmarks for the active task (initial files count, expanded count, budget exclusions, etc.). Supports `--format text|json`.

```bash
sacas benchmark
```

### `sacas context-simulation`
Run simulated context size metrics across the entire repository comparing baseline, Graphify, and SACAS modes. Supports `--format text|json`.

```bash
sacas context-simulation
```

## Key Concept

`CONTEXT.md` is the token-saving secret. Each task gets a `CONTEXT.md` that lists exactly which files and symbols are relevant. The agent reads only those files — not the full codebase.

## Portability

SACAS automatically generates adapters and instructions for:
- **Antigravity**: natively uses the skill.
- **Claude Code**: copies rules into `CLAUDE.md`.
- **Cursor**: copies rules into `.cursorrules` / `.cursor/rules/`.
- **GitHub Copilot**: copies instructions into `.github/copilot-instructions.md`.

## License

MIT
