# SACAS Router Design

> **Archived historical design.** This document preserves the 18 Aug 2026 proposal and may describe superseded commands or state models; use the current README and `sacas --help` for supported behavior.

## Goal

Transform SACAS from a PowerShell scaffolder into a task-aware, Python-based context router for AI-assisted software development.

## Authority model

Source code and build metadata are the implementation truth. Human-authored SACAS rules and references express project intent. Graphify supplies derived structural evidence. SACAS maps and task context are disposable navigation aids; task state is temporary execution state.

## Core layout

`Structure/` is the default SACAS root. `Structure/.sacas/manifest.json` is the canonical marker and records schema version, repository/root locations, Graphify mode/output, adapters, context budget, and current task. Markdown agents read `ROUTER.md`, rules, map context, task `TASK.md`/`CONTEXT.md`, and canonical `STATE.md`. JSON holds generated analysis, cache, provenance, freshness, and module data.

## Commands

The distributable Python package exposes `sacas init`, `analyze`, `task`, `refresh`, `status`, `validate`, `install`, `migrate`, and `benchmark`. Generation is deterministic and replaces only bounded SACAS-owned regions. Human content is preserved. There is no duplicate PowerShell implementation; a thin launcher is permitted only when it delegates to the Python CLI.

## Context and Graphify

`task` assigns a stable task ID and compiles narrow, task-specific context: files/symbols, reasons, tests, rules, adjacent candidates, protected boundaries, provenance, confidence, freshness, and an estimated context budget. Contract fields are marked `EXPLICIT`, `INFERRED`, or `UNKNOWN`; missing acceptance criteria are never fabricated. Scope may expand when dependency evidence supports it, and each expansion is recorded separately from initial routing for later quality measurement. Graphify communities inform maps only; they never create tasks or edit prohibitions. Modes are explicit: `off`, `existing`, `code-only`, and `semantic`; semantic processing requires explicit selection.

## Reliability

The implementation is fixture-tested, including idempotency, custom roots, missing/stale Graphify data, generated/manual boundaries, migration, task context, refresh, validation, budgets, and ignores. Legacy artifacts are deleted only after parity and migration tests prove the replacement behavior. Validation is actionable and degrades gracefully when Git, Graphify, or symbol resolution is unavailable. Status, validation, and benchmark commands support machine-readable output. Benchmark records include model, agent/version, SACAS and Graphify versions, repository commit, and cache state alongside deterministic local and optional agent-run metrics.
