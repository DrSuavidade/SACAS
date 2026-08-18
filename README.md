# SACAS — Scaffold Analyzer Context Architect Skill

SACAS routes repository evidence into focused task context for AI-assisted software development. It automates context discovery, boundaries enforcement, and predictive token budgeting.

## Installation

Requires Python 3.11+. Install the package in editable development mode:

```bash
python -m pip install -e ".[test]"
```

## CLI Commands Reference

All commands support targeting specific directories using `--root <path>` (default: current directory).

---

### 1. `sacas init`
Initialize a SACAS structure inside a repository directory.

**Arguments:**
- `--root <path>`: Repository root directory (default: current directory).
- `--sacas-root <name>`: Directory name for storing SACAS structures (default: `Structure`).
- `--graphify <off|existing|code-only|semantic>`: Graphify integration mode (default: `existing`).

**Example:**
```bash
sacas init --sacas-root Structure --graphify code-only
```

---

### 2. `sacas map`
Extract AST graph dependency nodes using Graphify to map the repository.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--sacas-root <name>`: SACAS structures directory.
- `--output <dir>`: Target output folder relative to repository for graph assets (default: `graphify-out`).
- `--mode <off|existing|code-only|semantic>`: Dependency extraction strategy.

**Example:**
```bash
sacas map --mode code-only
```

---

### 3. `sacas task`
Generate a new task contract, setting initial focus files via goal-driven routing and fallbacks.

**Arguments:**
- `goal`: (Positional, Required) Goal/description of the task.
- `--root <path>`: Repository root directory.
- `--criteria [item ...]`: Acceptance criteria for the task.
- `--constraints [item ...]`: Execution constraints.
- `--verification [item ...]`: Verification steps/commands.
- `--files [path ...]`: Optional. Explicit focus files (if omitted, automatic Graphify or heuristic fallback routing is performed!).
- `--symbols [sym ...]`: Optional. Target code symbols.
- `--tests [test ...]`: Optional. Target tests.
- `--rules [rule ...]`: Optional. Rules to copy/link.

**Example (Goal-Only Context Routing):**
```bash
sacas task "fix Session restoration and auth persistence"
```

---

### 4. `sacas refresh`
Recalculate file hashes, verify active context integrity, and dynamically expand task context by matching relations.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--files [path ...]`: Optional. Re-evaluate only specified focus files.

**Example:**
```bash
sacas refresh
```

---

### 5. `sacas status`
Show details of the current task, including task ID, context budget utilization, a breakdown of context components, and modified/stale files.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--format <text|json>`: Output presentation (default: `text`).

**Example:**
```bash
sacas status --format json
```

---

### 6. `sacas validate`
Run cold-agent validation checks (generated regions, legacy tracker files, stale file states, budget overruns, protected boundaries, etc.).

**Arguments:**
- `--root <path>`: Repository root directory.
- `--format <text|json>`: Output presentation (default: `text`).

**Example:**
```bash
sacas validate
```

---

### 7. `sacas migrate`
Migrate legacy structures (e.g., PowerShell `PROGRESS.md`) to the unified Python CLI structures (`STATE.md`).

**Arguments:**
- `--root <path>`: Repository root directory.
- `--apply`: Actually execute migration updates.
- `--format <text|json>`: Output presentation.

**Example:**
```bash
sacas migrate --apply
```

---

### 8. `sacas context-simulation`
Simulate context sizes across all repository files using Baseline, Graphify-only, SACAS-only, and combined modes.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--format <text|json>`: Output presentation.

**Example:**
```bash
sacas context-simulation --format json
```

---

### 9. `sacas benchmark`
Report actual task routing quality metrics (initial files count, expansion count, budget exclusions, ratio, and total context tokens) for the active task.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--format <text|json>`: Output presentation.

**Example:**
```bash
sacas benchmark
```

---

## Architecture & Principles

### Context Budgeting
SACAS tracks the **whole working context size** (inclusive of `ROUTER.md`, `TASK.md`, `CONTEXT.md`, `STATE.md`, rules, references, and matched source files) against a configured `context_budget`. During context expansion:
- Candidates are scored by relationship type (imports/calls: 100, tests: 90, depends_on: 85).
- They are checked against the budget with a metadata buffer cushion.
- Exceeded candidates are written to `expansions.json` under `adjacent` with `excluded_reason: "budget"`.

### Path Sandboxing
All file paths are sandboxed inside the repository using `resolve_repo_path`, which throws errors on absolute paths, Windows UNC prefixes, drive colons, and `../` repository escapes.

### Protected Boundaries
Boundaries configured in `Structure/rules/boundaries.md` are evaluated using component-based path containment matching (e.g., preventing prefix match bugs such as matching `src/auth/` against `src/authentication/`).

## Portability

SACAS automatically generates configuration rules for:
- **Antigravity**: natively uses the skill.
- **Claude Code**: copies rules into `CLAUDE.md`.
- **Cursor**: copies rules into `.cursorrules` / `.cursor/rules/`.
- **GitHub Copilot**: copies instructions into `.github/copilot-instructions.md`.

## License

MIT
