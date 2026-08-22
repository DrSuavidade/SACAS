---
name: sacas
description: >
  Use when a SACAS installation already exists in the workspace, when explicitly
  invoked via /sacas command, or when the user asks for context architecture/AI repo organization.
  Do NOT auto-initialize merely because coding work begins.
  Triggers on: /sacas, sacas init, explicit user request for context architecture.
---

# SACAS — task-aware context compiler

SACAS compiles `user task + repository` into a minimal, deterministic context pack for an AI coding agent. Routing, ranking, invalidation, mapping, validation, and refresh are internal compiler operations. The agent-facing surface is three operations.

## When to Use

- **Auto-activate** when a SACAS installation (`.sacas` / `Structure`) already exists in the workspace
- **Auto-activate** when user explicitly invokes `/sacas`
- **Do NOT auto-initialize** merely because coding work begins

## Workflow

1. **Before substantial coding work**, give SACAS the user's task:

   ```bash
   sacas prepare "<task goal>"
   ```

2. **Use the returned context pack** as the initial working context. It lists exactly which files, symbols, and line ranges are relevant, under a token budget. Do not independently load broad repository context unless needed.

3. **When additional context is genuinely required** and the router missed it, request expansion:

   ```bash
   sacas add --file src/helper.py --symbol src/auth.py::login --reason "why this is needed"
   ```

4. **After relevant source changes**, stale context is detected automatically; `sacas prepare "<same goal>"` republishes a fresh validated pack.

5. **Debugging only** — inspect why something is in context or overall freshness/budget:

   ```bash
   sacas explain src/auth.py    # provenance chain for one path/symbol
   sacas explain                # current status: freshness, budget, breakdown
   sacas doctor                 # diagnostics + validation
   ```

## Canonical State

`task.json` (TaskContract) and `active_context.json` (ActiveContextManifest) inside `$SACAS_ROOT/tasks/current/` are the canonical pair. `TASK.md` and `CONTEXT.md` are rendered views. The runtime payload is `.sacas/runtime/context.pack.jsonl`: exact fragments with hashes, line ranges, admission provenance, and token estimates.

## Key Principle

The agent should think **Task → SACAS → context** — nothing else. Whether that means Graphify retrieval, lexical fallback, SHA256 invalidation, range resolution, or budgeting underneath is SACAS's job, not the agent's. Benchmarks and diagnostics live in the developer lab (`sacas lab`), outside normal operation.
