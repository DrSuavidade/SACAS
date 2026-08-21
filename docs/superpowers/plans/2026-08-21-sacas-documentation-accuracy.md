# SACAS Documentation Accuracy Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align published SACAS documentation with the executable CLI and clearly separate historical records from current guidance.

**Architecture:** Keep README as the complete user contract and SKILL as concise operational guidance. Preserve old plans/specs as immutable history with prominent archival labeling. Test stable command/flag anchors directly.

**Tech Stack:** Markdown, Python 3, pytest.

---

### Task 1: Add documentation contract regression coverage

**Files:**
- Create: `tests/test_documentation.py`

- [ ] Write a failing test that checks every public README command name: init, map, task, refresh, expand, why, doctor, status, validate, migrate, benchmark, context-simulation, histbench, pipeline and its orchestrate/stage/review/list children. Assert the shared `--root` contract, init `--sacas-root/--graphify/--workflow`, map `--output/--mode`, task criteria/constraints/verification/files/`--symbol` and `--symbols`/tests/rules/references/category/context-policy, refresh `--files`, all expand flags, status/validate/migrate/benchmark/context-simulation formats, migrate apply, histbench flags, and pipeline child `--start/--skip-review` options. Global `--version` remains deliberately out of scope because it is self-documenting in root help rather than a per-command contract.
- [ ] Run it and confirm the current docs omit the selected flags/commands.
- [ ] Add a companion assertion that `SKILL.md` identifies `task.json` and `active_context.json` as the canonical pair and exposes routine operations.
- [ ] Re-run focused test; expect PASS only after documentation is corrected.

### Task 2: Update public documentation and label archives

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `IMPLEMENTATION_PLAN.md`
- Modify: `docs/superpowers/specs/2026-08-18-sacas-router-design.md`
- Modify: `docs/superpowers/plans/2026-08-18-sacas-router.md`
- Modify: `docs/superpowers/plans/2026-08-18-sacas-v2-routing.md`

- [ ] Add missing CLI options and examples to README, including both supported task-symbol aliases and pipeline child-specific flags.
- [ ] Add omitted routine commands and canonical-pair wording to SKILL.
- [ ] Add short archival banners to superseded implementation/design records without changing their historical content.
- [ ] Run documentation regression tests and `python -m sacas --help`.

### Task 3: Release verification

- [ ] Run `python -m pytest -q -p no:cacheprovider` and `git diff --check`.
- [ ] Review every Markdown change for current-vs-historical clarity.
- [ ] Commit the documentation accuracy change on `main`.
