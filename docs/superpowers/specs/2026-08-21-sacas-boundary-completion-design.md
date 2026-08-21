# SACAS Boundary Completion Design

## Purpose

Complete the remaining outer-path hardening so every admission into canonical
context follows the same trust and selector rules as initial routing.

## Decisions

1. `expand` is an all-or-nothing admission boundary. It normalizes every
   supplied and candidate path with `resolve_repo_path`, validates bytes
   through the text-source reader, resolves requested symbols and reference
   headings, and refuses the whole command before publication when any input
   is rejected. It must never represent a rejected file with an empty hash.
2. The normalized Graphify evidence schema persists and validates stable node
   label/line metadata. Candidate generation carries that metadata
   (`node_label` and `node_line`, or a resolved selector) alongside each
   Graphify candidate.
   `expand --all-candidates` lowers that evidence through
   `SymbolRangeResolver` before admission. Full-file expansion is only the
   explicit no-selector case.
3. Canonical state has two distinct read outcomes: absent and corrupt.
   Missing canonical files are normal; malformed JSON, unsupported schema, or
   invalid field/selection types raise a typed canonical-state error. Every
   canonical-state consumer reports this deterministically; no legacy fallback
   may mask a corrupt canonical file.
4. `candidates.json` is task-bound derived input. Expansion requires its task
   ID to match the active manifest (and its graph hash when present), before
   considering any candidate admissions.
5. Lean initialization creates only SACAS core artifacts. `Structure` workflow
   scaffolding is emitted only with `--workflow`; the repository-root Claude
   adapter remains a core artifact. Re-running lean initialization never
   removes existing workflow files or human content.

## Non-goals

No new retrieval backends, graph store, orchestration layer, benchmark type,
or workflow mode is introduced. Existing `task.json -> active_context.json ->
context.pack.jsonl` ownership remains unchanged.

## Validation

Tests cover mixed valid/rejected expansion transactions, malformed candidate
payloads, generated Graphify candidate selector preservation, canonical
corruption through all public consumers, and non-destructive lean-vs-workflow
initialization. The full test suite and `sacas validate` remain release gates.
