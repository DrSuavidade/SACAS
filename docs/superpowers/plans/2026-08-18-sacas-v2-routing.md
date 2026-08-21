# SACAS v2 Routing Implementation Plan

> **Archived historical plan.** This 18 Aug 2026 v2 proposal is retained unchanged apart from this notice and may describe superseded behavior; use the current README and `sacas --help` for supported behavior.

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement verified Graphify integration (>=0.9.46,<1.0), capability probing, goal-driven context routing (Graphify + Symbol/Module/Filename heuristics), strict path containment, predictive budgeting, and a full E2E routing verification loop.

**Architecture:** Create an isolated `GraphifyAdapter` with capability detection, robust query string parsing, and query contract validation. Design `expansions.json` (schema v2) to separate initial scope, expansions, and adjacent budget-excluded files with rich provenance. Standardize path resolution to enforce relative component containment.

**Tech Stack:** Python 3.11+, argparse, Graphify (0.9.46+), pytest.

---

## Chunk 1: Graphify compatibility, capability checking, and fallback

### Task 1: Create GraphifyAdapter with capability checks and parser isolation

**Files:**
- Create: `tests/test_graphify_integration.py`
- Modify: `src/sacas/graphify.py`
- Modify: `tests/test_graphify.py`

- [ ] Write integration test that extracts a tiny fixture repo using real `graphify extract --code-only` and queries it.
- [ ] Run test to verify failure.
- [ ] Implement `GraphifyAdapter` class containing:
  - `get_installed_version()` (returns package version via `importlib.metadata.version('graphifyy')`)
  - `verify_capabilities()` (checks version >=0.9.46,<1.0 and runs CLI check commands)
  - `query()` (runs CLI query command)
  - `parse_query_output()` (parses NODE paths using isolated regex matching)
  - `validate_query_contract()` (checks if output conforms to expected schema)
- [ ] Handle grace fallbacks: if Graphify is incompatible or fails, emit a warning and fall back to repository heuristics.
- [ ] Verify unit and integration tests pass.

---

## Chunk 2: Goal-driven routing and fallbacks

### Task 2: Implement initial retrieval heuristics and Graphify query routing

**Files:**
- Modify: `src/sacas/tasks.py`
- Modify: `src/sacas/validate.py`
- Modify: `tests/test_tasks.py`

- [ ] Write test validating that keyword queries (like "auth") search symbols, module names, directory names, and filenames to score candidates in SACAS-only mode.
- [ ] Verify test fails.
- [ ] Implement scoring logic:
  - Filename match: weight 4
  - Symbol declaration match (regex scan file for `class `, `def `, `fn `, `struct ` matching terms): weight 5
  - Directory name match: weight 3
  - Test file name match: weight 4
- [ ] Wire `generate_task` to query Graphify (using `GraphifyAdapter`) and/or fall back to the scoring heuristic to populate `initial_scope`.
- [ ] Design and implement the new `expansions.json` (schema v2) containing:
  - `schema_version`: 2
  - `initial_scope`: list of dictionaries (with path, symbols, reason, source, confidence, relation, trigger, git_revision)
  - `expansions`: list of dictionaries (dynamic expansions)
  - `adjacent`: list of dictionaries (adjacent/excluded files)
- [ ] Verify tests pass.

---

## Chunk 3: Path sandboxing and component-based boundaries

### Task 3: Implement strict path resolution and component-level boundary matching

**Files:**
- Modify: `src/sacas/paths.py`
- Modify: `src/sacas/tasks.py`
- Modify: `tests/test_tasks.py`

- [ ] Write tests verifying path resolution blocks absolute paths, `../` escapes, and matches boundaries component-wise (e.g. `src/auth/` does not prefix-match `src/authentication/`).
- [ ] Verify test fails.
- [ ] Implement `resolve_repo_path` inside `src/sacas/paths.py`. Refactor boundary matching to split paths into components and verify containment.
- [ ] Verify tests pass.

---

## Chunk 4: Ranked, budget-aware expansion

### Task 4: Implement scored candidates and predictive budgeting

**Files:**
- Modify: `src/sacas/budget.py`
- Modify: `src/sacas/refresh.py`
- Modify: `tests/test_refresh.py`

- [ ] Write test verifying candidate scoring:
  - direct calls/imports (100)
  - corresponding tests (90)
  - reverse dependencies (85)
  - same graph community (40)
  - confidence modifier (EXTRACTED: 1.0, INFERRED: 0.75, heuristic: 0.5)
- [ ] Write test checking predictive budgeting (reject candidate before adding if projected size of all SACAS documents + candidate > budget, and move to `adjacent`).
- [ ] Update `budget.py` to calculate whole context size (Source, ROUTER, TASK, CONTEXT, STATE, rules, references).
- [ ] Refactor `refresh_context` to score, sort, and predictively budget candidates.
- [ ] Verify tests pass.

---

## Chunk 5: Diagnostics, benchmarks, state, and E2E loop

### Task 5: Upgrade status, validate, benchmark, and add full E2E loop

**Files:**
- Modify: `src/sacas/status.py`
- Modify: `src/sacas/validate.py`
- Modify: `src/sacas/benchmark.py`
- Modify: `tests/test_validate.py`
- Modify: `tests/test_benchmark.py`
- Modify: `.gitignore`
- Create: `tests/test_e2e_routing.py`

- [ ] Write test verifying complete E2E routing loop: `sacas init` -> `graphify extract --code-only` -> `sacas task "<goal>"` -> `validate` -> modify -> `refresh` -> `status`.
- [ ] Verify test fails.
- [ ] Refactor status, validate, and benchmark. Clean up `.gitignore` to ignore python cache/egg-info, untrack `src/sacas.egg-info` from git.
- [ ] Implement `tests/test_e2e_routing.py`.
- [ ] Verify tests pass.
