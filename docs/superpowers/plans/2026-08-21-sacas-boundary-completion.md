# SACAS Boundary Completion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make expansion, canonical-state loading, and lean initialization obey SACAS's canonical trust and selector invariants.

**Architecture:** Validate every expansion request in memory before constructing a replacement manifest. Persist Graphify node metadata in candidates, then lower it through the existing resolver. Treat corruption as distinct from absence for every consumer, and keep only `Structure` workflow artifacts opt-in.

**Tech Stack:** Python 3, pytest, existing SACAS IO/path/selector APIs.

---

## Chunk 1: Safe expansion and selector candidates

### Task 1: Fail-closed expansion admission

**Files:**
- Modify: `src/sacas/cli.py`
- Test: `tests/test_cli_commands.py`

- [ ] Write failing mixed-input transaction tests for escaped, secret, ignored, binary, invalid-symbol, invalid-reference-heading, malformed-candidates, and stale-task candidates inputs.
- [ ] Run the focused tests and confirm current expansion partially admits entries or creates an empty-hash admission.
- [ ] Normalize paths with `resolve_repo_path`; securely read and resolve every requested admission before mutating the in-memory manifest; reject failures with a nonzero command result and byte-identical canonical state/views.
- [ ] Re-run focused expansion tests.

### Task 2: Preserve candidate selectors

**Files:**
- Modify: `src/sacas/cli.py`
- Modify: `src/sacas/refresh.py`
- Modify: `src/sacas/graphify.py`
- Test: `tests/test_cli_commands.py`
- Test: `tests/test_refresh.py`
- Test: `tests/test_graphify.py`

- [ ] Write a failing test where generated Graphify evidence yields a candidate with node label/line metadata and expansion preserves its range.
- [ ] Confirm generation currently discards selector metadata and `--all-candidates` produces a full-file selection.
- [ ] Serialize stable node label/line metadata, then resolve it to `ActiveSymbolContext`; retain full-file selection only for candidates with no selector evidence.
- [ ] Re-run focused candidate tests.

## Chunk 2: Canonical state and lean initialization

### Task 3: Report canonical corruption

**Files:**
- Modify: `src/sacas/task_contract.py`
- Modify: `src/sacas/active_context.py`
- Modify: `src/sacas/status.py`
- Modify: `src/sacas/validate.py`
- Modify: `src/sacas/refresh.py`
- Modify: `src/sacas/cli.py`
- Modify: `src/sacas/compiler.py`
- Modify: `src/sacas/provenance.py`
- Modify: `src/sacas/benchmark.py`
- Test: `tests/test_active_context.py`
- Test: `tests/test_validate.py`
- Test: `tests/test_refresh.py`
- Test: `tests/test_cli_commands.py`
- Test: `tests/test_compiler.py`
- Test: `tests/test_provenance.py`
- Test: `tests/test_benchmark.py`

- [ ] Write failing tests for malformed `task.json` and `active_context.json` through status and validate.
- [ ] Add valid-JSON tests for unsupported schema versions and invalid types/selections, and consumer tests for refresh, expand, compiler, provenance, and benchmark refusal.
- [ ] Confirm they are currently treated as missing state or raise uncontrolled exceptions.
- [ ] Introduce a typed canonical-state exception and convert it to clear, nonzero diagnostics at every user-facing consumer without legacy fallback.
- [ ] Re-run focused state/validation tests.

### Task 4: Make default initialization lean

**Files:**
- Modify: `src/sacas/init.py`
- Test: `tests/test_init.py`
- [ ] Write a failing default-init test asserting no `Structure/CLAUDE.md` or `Structure/CONTEXT.md`, plus a workflow-mode counterpart and a non-destructive re-init case.
- [ ] Confirm the default path creates the legacy artifacts.
- [ ] Gate only `Structure` workflow artifacts on `workflow`, preserve the repository-root Claude adapter, and update the relevant README/help text.
- [ ] Re-run focused initialization tests.

## Chunk 3: Release gate

- [ ] Run focused changed-module tests.
- [ ] Run `python -m pytest -q -p no:cacheprovider`.
- [ ] Run `python -m sacas refresh --root .`, `python -m sacas validate --root .`, and `python -m sacas status --root . --format json`.
- [ ] Run `git diff --check`, review the complete diff, and commit the reviewed hardening change on `main`.
