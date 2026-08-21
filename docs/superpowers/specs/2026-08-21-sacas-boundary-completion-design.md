# SACAS Boundary Completion Design

## Purpose

Complete the remaining outer-path hardening so every admission into canonical
context follows the same trust and selector rules as initial routing.

## Decisions

1. `expand` is an admission boundary. It normalizes every supplied and
   candidate path with `resolve_repo_path`, validates bytes through the
   text-source reader, and refuses the whole command before publication when
   any requested admission is rejected. It must never represent a rejected
   file with an empty hash.
2. Candidate records preserve a validated selector when one is available.
   Graph/node/symbol/line evidence is lowered through `SymbolRangeResolver`
   before admission. Full-file expansion is only the explicit no-selector
   case.
3. Canonical state has two distinct read outcomes: absent and corrupt.
   Missing canonical files are normal; malformed JSON or invalid schema is a
   typed canonical-state error surfaced by status and validation.
4. Lean initialization creates only SACAS core artifacts. Legacy workflow
   scaffolding is emitted only with `--workflow`.

## Non-goals

No new retrieval backends, graph store, orchestration layer, benchmark type,
or workflow mode is introduced. Existing `task.json -> active_context.json ->
context.pack.jsonl` ownership remains unchanged.

## Validation

Tests cover escaped/secret/ignored/binary expansion inputs, candidate selector
preservation, canonical corruption diagnostics, and lean-vs-workflow artifact
creation. The full test suite and `sacas validate` remain release gates.
