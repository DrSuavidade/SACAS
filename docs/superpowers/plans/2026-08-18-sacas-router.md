# SACAS Router Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a tested Python SACAS CLI that compiles narrow task context from repository evidence and optional Graphify data.

**Architecture:** A standard-library-first Python package owns manifest/configuration, deterministic generated regions, repository and Graphify evidence, task context, state, validation, migration, adapters, and benchmarks. Markdown is the human/agent interface; JSON is versioned machine state. Graphify remains external and optional.

**Tech Stack:** Python 3.11+, argparse, dataclasses, `tomllib`, pytest, GitHub Actions.

---

## Chunk 1: Package and deterministic foundation

### Task 1: Create the package contract

**Files:**
- Create: `pyproject.toml`
- Create: `src/sacas/__init__.py`
- Create: `src/sacas/__main__.py`
- Create: `src/sacas/cli.py`
- Create: `tests/test_cli.py`
- Create: `.github/workflows/test.yml`

- [x] Write behavioral tests for `sacas --help`, unknown-command exit codes, and the published package version.
- [x] Run `$env:PYTHONPATH='src'; python -m pytest tests/test_cli.py -q; Remove-Item Env:PYTHONPATH` and confirm assertions fail because the CLI contract is absent.
- [x] Add package metadata, a `sacas` console entry point, argparse command registration, and CI.
- [x] Re-run the focused test, then the full suite.

### Task 2: Define schemas and safe generated ownership

**Files:**
- Create: `src/sacas/models.py`
- Create: `src/sacas/regions.py`
- Create: `src/sacas/io.py`
- Create: `tests/test_regions.py`

- [x] Test manifest serialization/version validation and replace-only `SACAS:START/END` regions.
- [x] Verify tests fail because helpers do not exist.
- [x] Implement immutable models, atomic deterministic writes, and region replacement that leaves manual text unchanged.
- [x] Re-run focused and full tests.

## Chunk 2: Initialization, manifest, and adapter generation

### Task 3: Implement canonical root discovery and `init`

**Files:**
- Create: `src/sacas/paths.py`
- Create: `src/sacas/init.py`
- Create: `src/sacas/templates.py`
- Create: `tests/test_init.py`
- Create: `tests/conftest.py`

- [x] Test default/custom/root-level manifests, existing human router preservation, and a second unchanged init producing no diff.
- [x] Verify each test fails before implementation.
- [x] Implement manifest discovery, creation, compact routers, rules/map/task/references directories, and ownership headers.
- [x] Create a human-authored `rules/boundaries.md` format; only its `MANUAL` entries may be protected, never Graphify communities.
- [x] Run the focused tests and full suite.

### Task 4: Implement platform-neutral adapters and ignores

**Files:**
- Create: `src/sacas/adapters.py`
- Create: `tests/test_adapters.py`
- Modify: `src/sacas/init.py`

- [x] Test idempotent Codex/Claude/Cursor/Copilot/Gemini adapters and root-level `graphify-out/` ignores, including preservation of manual regions in every generated adapter.
- [x] Verify red state.
- [x] Generate bounded adapter sections and platform-specific ignores without redirecting Graphify output under `Structure/`.
- [x] Run focused tests and full suite.

## Chunk 3: Evidence collection and system map

### Task 5: Implement evidence-backed repository/module analysis

**Files:**
- Create: `src/sacas/repository.py`
- Create: `src/sacas/modules.py`
- Create: `src/sacas/analysis.py`
- Create: `tests/test_analysis.py`
- Create: `tests/fixtures/node-monorepo/package.json`
- Create: `tests/fixtures/python-service/pyproject.toml`
- Create: `tests/fixtures/dotnet-monolith/App.csproj`
- Create: `tests/fixtures/nextjs-app/package.json`
- Create: `tests/fixtures/node-monorepo/pnpm-workspace.yaml`
- Create: `tests/fixtures/node-monorepo/nx.json`
- Create: `tests/fixtures/node-monorepo/turbo.json`
- Create: `tests/fixtures/rust-workspace/Cargo.toml`
- Create: `tests/fixtures/mixed-repo/go.mod`
- Create: `tests/fixtures/mixed-repo/docker-compose.yml`
- Create: `tests/fixtures/mixed-repo/pom.xml`
- Create: `tests/fixtures/mixed-repo/build.gradle`

- [x] Test package workspaces (npm/pnpm/Nx/Turbo), Cargo, Go, .NET, Maven/Gradle, Python, Docker Compose, deterministic heuristic fallback, module source/confidence, spaces in paths, and analysis idempotency.
- [x] Verify red state.
- [x] Implement lightweight detectors for the tested metadata and bounded directory heuristics; serialize evidence and freshness. Document unsupported formats as fallbacks, not full support.
- [x] Run focused tests and full suite.

### Task 6: Consume Graphify without recreating it

**Files:**
- Create: `src/sacas/graphify.py`
- Create: `src/sacas/map.py`
- Create: `tests/test_graphify.py`
- Create: `tests/fixtures/graphify-out/graph.json`

- [x] Test `off`, `existing`, local-only `code-only`, and explicit `semantic` mode selection; absent/stale data; maps that use community evidence without task creation or protected boundaries.
- [x] Verify red state.
- [x] Implement graph manifest/hash freshness checks, safe optional query invocation, provenance levels, compact system map rendering, and bounded impact/effect records (direct target, callers/importers/dependents/tests). `code-only` invokes Graphify's supported local extraction rather than duplicating graph extraction; `semantic` requires explicit user selection before any external processing.
- [x] Run focused tests and full suite.

## Chunk 4: Task routing, state, refresh, and status

### Task 7: Generate task contracts and disposable context

**Files:**
- Create: `src/sacas/tasks.py`
- Create: `src/sacas/budget.py`
- Create: `src/sacas/state.py`
- Create: `src/sacas/effects.py`
- Create: `tests/test_tasks.py`

- [ ] Test task generation from goal plus evidence, a stable task ID, flags for acceptance criteria/constraints/verification, `EXPLICIT`/`INFERRED`/`UNKNOWN` contract fields, files/symbols/tests/rules, explicit-only protection, provenance/freshness, budget reporting, bounded effect routing, and deterministic rerun that preserves manual content.
- [ ] Verify red state.
- [ ] Implement a stable internal task ID with the v1 canonical `tasks/current/` view, compact `TASK.md`, `CONTEXT.md`, and canonical `STATE.md`; generate `PICKUP.md` from state only. Resolve each contract field as `EXPLICIT`, `INFERRED`, or `UNKNOWN`; never fabricate absent acceptance criteria.
- [ ] Run focused tests and full suite.

### Task 8: Implement progressive expansion, refresh, and status

**Files:**
- Create: `src/sacas/refresh.py`
- Create: `src/sacas/status.py`
- Create: `tests/test_refresh.py`
- Modify: `src/sacas/cli.py`

- [ ] Test stale referenced file detection, permitted evidence-backed scope expansion, protected-boundary refusal, no-op refresh, manual-content preservation, concise status output, and a separate immutable expansion record that distinguishes initial routing from later additions.
- [ ] Verify red state.
- [ ] Implement dependency-evidence expansion, a separately persisted expansion history for routing-quality measurement, selective refresh, and status reporting with `--format text|json`.
- [ ] Run focused tests and full suite.

## Chunk 5: Validation, migration, and benchmark harness

### Task 9: Implement cold-agent validation

**Files:**
- Create: `src/sacas/validate.py`
- Create: `tests/test_validate.py`

- [ ] Test PASS/WARNING/FAIL checks for manifests, missing references, stale context, Graphify availability, budgets, malformed generated regions, build/test-command discoverability, one canonical state/no `PROGRESS` drift, protected-boundary clarity, generated/manual ownership, and router hop budget.
- [ ] Verify red state.
- [ ] Implement structured actionable diagnostics, scriptable exit codes, and `--format text|json`.
- [ ] Run focused tests and full suite.

### Task 10: Implement safe migration and benchmark records

**Files:**
- Create: `src/sacas/migrate.py`
- Create: `src/sacas/benchmark.py`
- Create: `tests/test_migrate.py`
- Create: `tests/test_benchmark.py`
- Create: `tests/fixtures/legacy-sacas/Structure/tasks/current/PROGRESS.md`

- [ ] Test dry-run migration, preservation of references/history/manual regions, state consolidation, no deletion of unknown files, and benchmark schema validation for model, agent/version, SACAS version, Graphify version, repository commit, and cache state plus median/p75/p95 aggregation across Baseline, Graphify-only, SACAS-only, and SACAS+Graphify modes.
- [ ] Verify red state.
- [ ] Implement preview/apply migration and a JSONL benchmark schema/report that captures task type, mode, model, agent/version, SACAS/Graphify versions, repository commit, cache state, deterministic local metrics, optional agent metrics, and documented limitations. Add `--format text|json`.
- [ ] Run focused tests and full suite.

## Chunk 6: Documentation, validation, and repository retirement

### Task 11: Replace legacy documentation and scripts

**Files:**
- Modify: `README.md`
- Modify: `SKILL.md`
- Modify: `hooks/on-session-end.md`
- Delete: `scripts/analyze.ps1`
- Delete: `scripts/detect-architecture.ps1`
- Delete: `scripts/detect-conventions.ps1`
- Delete: `scripts/detect-existing-ai.ps1`
- Delete: `scripts/detect-modules.ps1`
- Delete: `scripts/detect-stack.ps1`
- Delete: `scripts/generate-context-md.ps1`
- Delete: `scripts/read-graphify.ps1`
- Delete: `scripts/scaffold.ps1`
- Delete: `templates/AGENTS-subfolder.md.template`
- Delete: `templates/AGENTS.md.template`
- Delete: `templates/aiignore.template`
- Delete: `templates/architecture.md.template`
- Delete: `templates/CONTEXT.md.template`
- Delete: `templates/conventions.md.template`
- Delete: `templates/PICKUP.md.template`
- Delete: `templates/PROGRESS.md.template`
- Delete: `templates/task-runner.md.template`
- Delete: `templates/TASK.md.template`
- Delete: `references/usage-guide.md`
- Delete: `references/pickup-format.md`
- Modify: `.aiignore`
- Modify: `.cursorignore`

- [ ] Write documentation tests/smoke tests for examples and search tests ensuring no unsupported token-saving percentage remains or obsolete `/sacas`, `/sacas-merge`, `PROGRESS.md`, and community-backlog workflow survives.
- [ ] Verify red state.
- [ ] Document authority, commands, modes, costs, ownership, migration, validation, budgets, benchmarks, and limitations. Retire obsolete PowerShell scaffold artifacts only after parity and migration tests have passed; a documented thin launcher may remain if it delegates exclusively to the Python CLI.
- [ ] Run `python -m pytest -q`, `python -m sacas --help`, representative fixture CLI flows, and repeated-operation diff checks. CI installs the package with `python -m pip install -e .[test]` before running `python -m pytest -q`.

### Task 12: Final verification and review

**Files:**
- Modify: `README.md` only if verification exposes an inaccurate example.

- [ ] Run all tests, CI-equivalent command, CLI smoke tests, fixture idempotency checks, Graphify-absent/stale flows, custom root flow, migration dry-run, and human-reference preservation test.
- [ ] Inspect `git diff --check` and final status.
- [ ] Record only verified outcomes in the engineering report.
