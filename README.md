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
- `--workflow`: Also create ICM workflow stages (`stages/`) and `_config/` directories (optional).

**Example:**
```bash
sacas init --sacas-root Structure --graphify code-only

# With ICM workflow
sacas init --sacas-root Structure --graphify code-only --workflow
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
- `--files [path ...]`: Optional. Explicit focus files.
- `--symbol [sym ...]`: Optional. Repeatable target code symbols (format: `file::SymbolName`).
- `--tests [test ...]`: Optional. Target tests.
- `--rules [rule ...]`: Optional. Rules to copy/link.
- `--references [ref ...]`: Optional. Reference files/documentation.
- `--category <bugfix|feature|test|refactor|docs|security|investigate>`: Optional task category (default: inferred from goal).
- `--context-policy <advisory|warn|enforce>`: Context isolation policy (default: `advisory`).

**Example:**
```bash
sacas task "fix Session restoration" --symbol src/auth.py::login --context-policy enforce
```

---

### 4. `sacas refresh`
Recalculate file hashes and verify active context integrity. **Note: refresh never automatically admits new context into the task.** Instead, it generates a list of suggested adjacent routing candidates in `Structure/tasks/current/candidates.json`.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--files [path ...]`: Optional. Re-evaluate only specified focus files.

**Example:**
```bash
sacas refresh
```

---

### 5. `sacas expand`
Explicitly expand the active context with new files, symbols, rules, or references.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--file [path ...]`: Repeatable. Explicit file path to admit.
- `--symbol [sym ...]`: Repeatable. Symbol path (format: `file::SymbolName`) to admit.
- `--rule [rule ...]`: Repeatable. Rule path to admit.
- `--reference [ref ...]`: Repeatable. Reference path (or section `file.md#heading`) to admit.
- `--reason <text>`: Audit rationale for this expansion.
- `--all-candidates`: Expand all candidates in `candidates.json` that fit the remaining context budget.

**Example:**
```bash
sacas expand --file src/helper.py --reason "Utility import"
```

---

### 6. `sacas why`
Explain the routing path and metadata for a given file or symbol.

**Arguments:**
- `path`: (Positional, Required) File path or symbol name to query.
- `--root <path>`: Repository root directory.

**Example:**
```bash
sacas why src/auth.py
```

---

### 7. `sacas doctor`
Run diagnostic health checks on workspace context and platform ignore boundaries.

**Arguments:**
- `--root <path>`: Repository root directory.

**Example:**
```bash
sacas doctor
```

---

### 8. `sacas status`
Show details of the current task, including task ID, context budget utilization, a breakdown of context components, and modified/stale files.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--format <text|json>`: Output presentation (default: `text`).

---

### 9. `sacas validate`
Run cold-agent validation checks (generated regions, legacy tracker files, stale file states, budget overruns, protected boundaries, etc.).

---

### 10. `sacas migrate`
Migrate legacy structures (e.g., PowerShell `PROGRESS.md` or v2 `expansions.json`) to the unified Python CLI structures (`active_context.json` and `STATE.md`).

---

### 11. `sacas context-simulation`
Simulate context sizes across all repository files using Baseline, Graphify-only, SACAS-only, and combined modes.

---

### 12. `sacas benchmark`
Evaluate routing quality metrics (Precision@K, Recall@K, MRR, Context Efficiency, and Token Reduction) for the active task or gold-standard benchmarks.

---

### 13. `sacas histbench`
Generate and run historical Git benchmarks from commit history.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--max-commits <n>`: Maximum commits to analyze (default: 200).
- `--generate-only`: Only generate benchmark files, don't run.
- `--output-dir <dir>`: Output directory for generated benchmarks.
- `--format <text|json>`: Output presentation (default: `text`).

**Example:**
```bash
sacas histbench --generate-only --max-commits 100
```

---

### 14. `sacas pipeline`
Manage ICM multi-stage pipelines.

**Subcommands:**
- `sacas pipeline orchestrate` — Walk through pipeline sequentially with review gates.
- `sacas pipeline stage <stage_id>` — Run a specific pipeline stage.
- `sacas pipeline review <stage_id>` — Open stage output for human review.
- `sacas pipeline list` — List available pipeline stages.

**Arguments:**
- `--root <path>`: Repository root directory.
- `--start <stage>`: Stage to start from (default: `01_analyze`).
- `--skip-review`: Skip human review gates (non-interactive).

---

## Architecture & Principles

### Context Budgeting
SACAS tracks the **whole working context size** against a configured `context_budget` inside `active_context.json` (canonical `ActiveContextManifest`).
- **Payload tokens:** Source files, rules, and references.
- **Control tokens:** Router/task metadata files (`ROUTER.md`, `TASK.md`, `CONTEXT.md`, `STATE.md`).

### Enforcement Policies
1. **Advisory:** Renders `CONTEXT.md` token report only; does not mutate ignore files.
2. **Warn:** Logs out-of-context access warnings where supported.
3. **Enforce:** Uses platform enforcement providers (e.g., writing precise nested negation patterns into `.cursorignore`) to block out-of-context access.

### Directory Structure

**Lean (default):**
```
your-project/
├── .aiignore
├── .cursorignore
└── Structure/
    ├── ROUTER.md              # SACAS router guide
    ├── rules/
    │   └── boundaries.md      # Protected scope boundaries (MANUAL entries only)
    ├── map/
    │   └── SYSTEM.md          # Generated codebase map
    ├── references/
    ├── tasks/
    │   └── current/
    │       ├── task.json      # Canonical TaskContract
    │       ├── active_context.json  # Canonical ActiveContextManifest
    │       ├── TASK.md        # Current task goal and contract (view)
    │       ├── CONTEXT.md     # Scoped files, symbols, budget (view)
    │       ├── STATE.md       # Checklist of task items (view)
    │       └── PICKUP.md      # Cross-session handoff (view)
    └── .sacas/
        ├── manifest.json      # Canonical configuration marker
        └── graphify.json      # Cached Graphify evidence
```

**With `--workflow`:**
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

## License

MIT