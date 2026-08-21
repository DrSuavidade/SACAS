# SACAS Fix6 Stabilization Design

## Purpose

Fix6 is a stabilization release that makes SACAS's existing context-compiler architecture trustworthy before empirical evaluation. It addresses all P0 and P1 findings from the Fix5 architecture review while explicitly deferring P2 model and architecture refinements.

## Scope

Fix6 must establish these invariants:

1. A task, graph, or source change converges after one successful refresh; an immediate second refresh performs no semantic work.
2. Refreshing source code preserves why and how each file was admitted.
3. Graph rediscovery removes obsolete Graphify-derived state without rewriting explicit history.
4. Invalid canonical context cannot reach an agent, and admitted canonical context cannot disappear silently from the compiled pack.
5. Every repository-controlled read passes through SACAS's repository trust boundary.
6. Benchmarks and tests describe and prove their actual behavior.

Fix6 does not introduce a new persisted schema, dependency DAG, workflow engine, retrieval service, ranking model, provenance database, Graphify replacement, daemon, or UI.

## Delivery Structure

Fix6 will be delivered as five dependency-ordered, independently reviewable commits:

1. Secure repository I/O and isolated test fixtures.
2. Canonical task and graph fingerprint convergence.
3. Origin-preserving refresh and correct provenance ledger.
4. Fail-closed compilation and pack/canonical validation.
5. Honest benchmarks, documentation, and the release acceptance gate.

Every commit begins with a failing behavioral test, implements the smallest compatible change, passes its targeted tests, and ends with a green full suite.

## Canonical and Derived State

`task.json` remains the canonical task contract. `active_context.json` remains the canonical admission manifest. They are not merged.

`graphify-out/graph.json` is external, rebuildable evidence. Its raw byte hash is the sole graph snapshot identity used by Graphify queries, refresh, active context, provenance, and pack headers. `Structure/.sacas/graphify.json` remains a derived normalized cache and stores that identity as `content_hash`; SACAS must not hash the cache serialization as a second identity.

`candidates.json`, Markdown views, and `context.pack.jsonl` remain derived. The context pack is the only exact agent payload and must be treated as unusable whenever it does not match canonical state.

`STATE.md` retains its existing generated-plus-checkbox behavior in Fix6. Redesigning its authority is deferred.

## Refresh State Machine

Refresh follows one compute-then-publish flow:

```text
load task contract + active context
→ calculate current task, graph, and source identities
→ classify invalidation
→ rediscover or re-resolve in memory
→ validate admissions and provenance
→ compile and validate the next pack in memory
→ publish canonical state and derived artifacts
→ immediate second refresh is clean
```

Task invalidation uses the current contract's task ID, goal, category, and hash. Graph invalidation compares the manifest's raw-graph identity to the current raw-graph identity. Source-only invalidation re-resolves the existing selection without calling the explicit-admission path.

Task rerouting preserves only admissions whose persisted source is `explicit`, explicit tests, and rules/references whose existing reason marks them as explicitly specified. It re-resolves and rehashes those preserved inputs. Old heuristic and Graphify admissions and events are discarded and recomputed from the current task. This deliberately avoids treating task-dependent discovery as durable user intent without adding a new schema field.

A named helper defines the legacy rule/reference explicitness predicate; production code must not duplicate comparisons against human-readable reason text.

Task or graph invalidation takes precedence over `selective_files` and performs the required full reroute. For source-only selective refresh, selected admitted files are re-resolved, but publication succeeds only when no non-selected admitted file is stale. If non-selected stale admissions exist, refresh fails with their paths and publishes no pack; a subsequent unfiltered refresh is required for global convergence.

Refresh must not publish intermediate manifests with updated hashes but stale selectors. Cross-file atomic replacement is not claimed. Publication uses this protocol:

1. Detect invalidation. If external state changed, remove the existing disposable runtime pack before further work so old content cannot be consumed as current.
2. Build and validate the next manifest, pack, and views in memory.
3. Atomically write the new pack.
4. Atomically write `active_context.json`.
5. Atomically write derived Markdown and candidates.

Pack readers validate the pack header and admission coverage against the currently loaded canonical task and manifest. A crash between steps 3 and 4 therefore leaves a new pack that is rejected against the old manifest. A crash before step 3 leaves no pack. A crash after step 4 leaves matching canonical state and pack even if human-readable views are stale. Failed compilation publishes neither the candidate manifest nor a usable pack.

## Origin and Provenance Semantics

Source-only selector refresh preserves the existing file's `source`, ranking score, confidence, evidence, relation, trigger, role, and admission events. A Graphify-derived file does not become explicit unless the user explicitly admits it.

Graph rediscovery preserves genuine explicit and non-Graphify history, removes obsolete Graphify-derived files and events, and adds only current Graphify evidence. Event IDs must be unique and deterministic after merging.

No schema change is required for fragment/event correlation. Existing file-targeted events apply to every fragment produced by that file-level admission. New symbol-specific events may use the existing `AdmissionEvent.target` string as `path::symbol`; those events apply only to the matching selector. A merged range receives the stable sorted union of events applicable to its constituent selections. `sacas why` must inspect all matching fragments, report each selector/range and its applicable events, and compute hashes from the actual compiled fragment content.

Preserved event IDs remain stable. Newly generated IDs must be deterministic and must not collide with preserved IDs; preserved history is never renumbered merely to make IDs contiguous.

## Compiler Failure Semantics

Compilation is fail-closed for canonical admissions:

- A missing, unreadable, ignored, secret, binary, oversized, or invalidly encoded admitted source is an error.
- A stale, moved, or deleted selector must be successfully re-resolved before compilation.
- A previously resolved selector cannot silently become an old-range fragment or automatic whole-file fallback.
- Every entry in `manifest.all_files` (`files`, `reference_files`, and `working_files`) must yield at least one expected fragment. Every `manifest.tests` path must correspond to an admitted `ActiveFileContext` with `role="test"`. Every admitted rule and reference must yield its required fragment.
- Pack schema, IDs, counts, content hashes, task hash, graph hash, and admitted-source coverage must validate before publication.

A failed refresh or compilation must leave the runtime pack absent or explicitly unusable; an old pack cannot masquerade as the current payload.

A legitimately empty manifest with no files in any layer, no tests, no rules, and no references may produce a valid header-only pack.

## Repository Trust Boundary

Repository enumeration may discover path names but must not directly read content. All repository-controlled content and hashes pass through secure repository I/O, including fallback indexing, symbol resolution, explicit CLI expansion, status, validation, budgeting, and benchmark baselines.

The boundary rejects traversal, absolute Windows/POSIX paths, UNC escapes, external symlinks, secrets, `.sacasignore` matches, ignored directories, binaries, oversized files, and invalid UTF-8.

Trusted SACAS internal state under `Structure/.sacas` uses dedicated internal-state reads and is not incorrectly subjected to repository ignore policy.

## Graphify Behavior

Graphify remains optional evidence. Outcomes are explicit:

- Graph absent: graph identity is empty; remove old Graphify admissions/events and use lexical fallback.
- Graph removed after prior use: treat as graph invalidation, remove old Graphify state, use lexical fallback, and persist an empty graph identity.
- Malformed graph: treat as unavailable evidence with an empty identity, remove old Graphify state, and use lexical fallback.
- Valid graph but provider/query failure: preserve the valid raw-graph identity for convergence, remove unverified old Graphify state, and use lexical fallback.
- Valid query with zero matches: preserve the raw-graph identity and use lexical fallback.
- Valid query with matches: admit only validated, budget-fitting results and preserve the raw-graph identity.

Graphify success is based on admitted Graphify source results, not the total number of already active files or tests. Custom configured Graphify output paths use the identity of the graph actually queried.

Graph evidence uses a dedicated secure snapshot reader rather than the ordinary 1 MB source-file limit. It validates the configured repository-relative path, rejects escapes and binary/invalid JSON, and enforces a documented 50 MB maximum. A provider/query failure emits a warning explaining that an intentional retry requires rebuilding/touching the graph with `sacas map` or rerouting the task; unchanged evidence otherwise remains clean by design.

## Benchmark and Test Credibility

The B1 baseline performs secure full-content filename and keyword search over eligible repository files. The serialized result and CLI label currently called `token_reduction` become `whole_repository_reduction`. A read-only Python property named `token_reduction` may temporarily alias the new field for callers, but newly written JSON and CLI output contain only the honest name. Tests and documentation use the new name.

Historical routing continues to run in a detached worktree at the actual parent commit. The child commit supplies the task goal and weak evaluation gold only; child filenames and blobs are never passed into routing.

Placeholder tests are replaced with behavioral assertions. Mutable fixtures use temporary repositories so a successful test run leaves `git status --short` empty.

## Error Reporting

Failures identify the artifact and invariant that failed: task fingerprint mismatch, graph identity mismatch, invalid selector, unavailable admitted source, incomplete pack, unsafe repository path, or malformed graph evidence. Errors must not be swallowed into an apparently successful empty result where canonical correctness is at stake.

## Acceptance Gate

Fix6 is releasable only when:

- Task, graph, and source changes each converge after one refresh.
- Source refresh preserves admission origin and evidence.
- Graph rediscovery does not retain obsolete events or create duplicate IDs.
- Stale selectors and missing admitted sources fail closed.
- Manifest, task contract, and pack identities agree.
- No repository-controlled read bypasses secure I/O.
- Graphify failure falls back correctly.
- Benchmark terminology and B1 behavior are accurate.
- Historical routing proves parent-only isolation.
- The complete suite passes and leaves the worktree clean.
- A regenerated local SACAS task state passes `sacas validate` with no `FAIL`
  diagnostics. `Structure/` is intentionally ignored and is not presented as a
  committed release artifact.

## Deferred P2 Work

Fix6 records but does not implement:

- A new ranking/confidence model.
- Multi-node-per-file Graphify aggregation.
- Deterministic Graphify query-ID redesign.
- A redesign of `STATE.md` authority.
- Any empirical retrieval-driven architecture expansion.

After Fix6, SACAS should move to empirical evaluation and allow measured retrieval outcomes to determine subsequent architecture work.
