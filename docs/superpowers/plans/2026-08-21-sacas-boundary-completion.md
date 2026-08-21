# SACAS Boundary Completion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make expansion, canonical-state loading, and lean initialization obey SACAS's canonical trust and selector invariants.

**Architecture:** Validate every expansion request in memory before constructing a replacement manifest. Lower candidate graph evidence to source selectors through the existing resolver. Treat corruption as distinct from absence, and keep workflow artifacts opt-in.

**Tech Stack:** Python 3, pytest, existing SACAS IO/path/selector APIs.

---

## Chunk 1: Safe expansion and selector candidates

### Task 1: Fail-closed expansion admission

**Files:**
- Modify: `src/sacas/cli.py`
- Test: `tests/test_cli_commands.py`

- [ ] Write a failing test for rejected escaped, secret, ignored, binary, and invalid symbol expansion inputs.
- [ ] Run the focused test and confirm current expansion creates an empty-hash admission or otherwise fails the required contract.
- [ ] Normalize paths with `resolve_repo_path`; securely read every requested admission before mutating the in-memory manifest; reject failures with a nonzero command result.
- [ ] Re-run focused expansion tests.

### Task 2: Preserve candidate selectors

**Files:**
- Modify: `src/sacas/cli.py`
- Test: `tests/test_cli_commands.py`

- [ ] Write a failing candidate-expansion test with Graphify symbol/line metadata.
- [ ] Confirm `--all-candidates` currently produces a full-file selection.
- [ ] Resolve candidate evidence to `ActiveSymbolContext`; retain full-file selection only for candidates with no selector evidence.
- [ ] Re-run focused candidate tests.

## Chunk 2: Canonical state and lean initialization

### Task 3: Report canonical corruption

**Files:**
- Modify: `src/sacas/task_contract.py`
- Modify: `src/sacas/active_context.py`
- Modify: `src/sacas/status.py`
- Modify: `src/sacas/validate.py`
- Test: `tests/test_active_context.py`
- Test: `tests/test_validate.py`

- [ ] Write failing tests for malformed `task.json` and `active_context.json` through status and validate.
- [ ] Confirm they are currently treated as missing state.
- [ ] Introduce a typed canonical-state exception and convert it to clear diagnostics at user-facing consumers.
- [ ] Re-run focused state/validation tests.

### Task 4: Make default initialization lean

**Files:**
- Modify: `src/sacas/init.py`
- Test: `tests/test_init.py`
- [ ] Write a failing default-init test asserting no workflow-only artifacts, plus a workflow-mode counterpart.
- [ ] Confirm the default path creates the legacy artifacts.
- [ ] Gate those artifacts on `workflow` without changing core router setup.
- [ ] Re-run focused initialization tests.

## Chunk 3: Release gate

- [ ] Run focused changed-module tests.
- [ ] Run `python -m pytest -q -p no:cacheprovider`.
- [ ] Run `python -m sacas refresh --root .`, `python -m sacas validate --root .`, and `python -m sacas status --root . --format json`.
- [ ] Run `git diff --check`, review the complete diff, and commit the reviewed hardening change on `main`.
