# SACAS Fix6 Stabilization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SACAS's existing context compiler secure, convergent, provenance-correct, fail-closed, and empirically credible without adding a new architecture or persisted schema.

**Architecture:** Keep `task.json` and `active_context.json` as the canonical pair, use one raw-graph identity end to end, preserve admission semantics during refresh, and validate the ephemeral pack against canonical state before it can be consumed. Deliver five dependency-ordered commits, each introduced by failing behavioral tests and closed by the full suite.

**Tech Stack:** Python 3.11+, frozen dataclasses, pathlib, JSON/JSONL, pytest, Git worktrees, Graphify provider abstraction.

---

## Preconditions and working agreement

- Execute in an isolated worktree created with `@using-git-worktrees`.
- Use `@test-driven-development` for every behavioral change.
- Use `@systematic-debugging` if a planned failing test fails for an unexpected reason.
- Use `@requesting-code-review` after each commit-sized task.
- Use `@verification-before-completion` before each commit and before the Fix6 acceptance gate.
- Do not change the active-context schema version.
- Do not implement the deferred P2 items listed in the design spec.
- Design reference: `docs/superpowers/specs/2026-08-20-sacas-fix6-stabilization-design.md`.

## File responsibility map

| File | Fix6 responsibility |
|---|---|
| `src/sacas/io.py` | Secure repository enumeration and reads |
| `src/sacas/analysis.py` | Secure repository metadata hashing |
| `src/sacas/modules.py` | Secure workspace/package descriptor reads |
| `src/sacas/repository.py` | Secure repository descriptor inspection |
| `src/sacas/graphify.py` | Validated graph snapshot loading and sole graph identity |
| `src/sacas/regions.py` | Selector resolution through secure repository reads |
| `src/sacas/search.py` | Secure fallback indexing |
| `src/sacas/tasks.py` | Initial routing, Graphify outcome semantics, explicit rule/reference predicate |
| `src/sacas/refresh.py` | Invalidation classification, origin-preserving refresh, event merge, publication orchestration |
| `src/sacas/compiler.py` | Fail-closed compilation, pack serialization/invalidation, canonical consistency validation |
| `src/sacas/provenance.py` | Fragment-specific event tracing and fragment hashes |
| `src/sacas/status.py` | Secure source freshness reporting |
| `src/sacas/validate.py` | Secure diagnostics and task/manifest/pack cross-validation |
| `src/sacas/cli.py` | Secure expansion reads and renamed benchmark output |
| `src/sacas/benchmark_runner.py` | Secure full-content B1 and honest reduction metric |
| `src/sacas/budget.py` | Secure source/rule/reference token counting; trusted control-file counting |
| `src/sacas/git_benchmark.py` | Historical isolation assertions and deterministic ordering |
| `tests/` | Lifecycle, security, compiler, provenance, benchmark, and release regression coverage |
| `README.md` | Correct state, metric, refresh, and failure semantics |

## Chunk 1: Secure repository boundary and isolated tests

### Task 1: Secure every repository-controlled read

**Commit:** `fix(security): enforce repository read boundary`

**Files:**
- Modify: `src/sacas/io.py:16`
- Modify: `src/sacas/analysis.py:90`
- Modify: `src/sacas/modules.py:56`
- Modify: `src/sacas/repository.py:52`
- Modify: `src/sacas/graphify.py:53`
- Modify: `src/sacas/search.py:29`
- Modify: `src/sacas/regions.py:196`
- Modify: `src/sacas/tasks.py:152`
- Modify: `src/sacas/cli.py:300`
- Modify: `src/sacas/status.py:12`
- Modify: `src/sacas/validate.py:49`
- Modify: `src/sacas/benchmark_runner.py:15`
- Modify: `src/sacas/budget.py:77`
- Test: `tests/test_compiler.py`
- Test: `tests/test_analysis.py`
- Test: `tests/test_budget.py`
- Test: `tests/test_repository_reads.py`
- Test: `tests/test_search.py`
- Test: `tests/test_symbol_resolver.py`
- Test: `tests/test_cli_commands.py`
- Test: `tests/test_validate.py`
- Test: `tests/test_benchmark_runner.py`
- Test: `tests/test_graphify.py`
- Test: `tests/test_invalidation.py`

- [ ] **Step 1: Write a failing fixture-isolation assertion**

Add `test_context_compiler_fixture_is_copied_before_mutation` to both compiler and invalidation tests. Assert the installation repository is below pytest's temporary root and is not the tracked fixture:

```python
tracked = (Path(__file__).parent / "fixtures" / "context_compiler").resolve()
assert installation.repository_root.resolve() != tracked
assert tmp_path.resolve() in installation.repository_root.resolve().parents
```

Run:

```powershell
python -m pytest tests/test_compiler.py::test_context_compiler_fixture_is_copied_before_mutation tests/test_invalidation.py::test_context_compiler_fixture_is_copied_before_mutation -q
```

Expected: both fail because the current fixtures point at the tracked directory.

- [ ] **Step 2: Move mutable compiler/invalidation fixtures to temporary repositories**

Replace fixtures that return `tests/fixtures/context_compiler` directly with copies under `tmp_path`:

```python
@pytest.fixture
def compiler_repo(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "context_compiler"
    destination = tmp_path / "context_compiler"
    shutil.copytree(source, destination)
    return destination
```

Update `tests/test_compiler.py` and `tests/test_invalidation.py` to use the copied repository. Snapshot the tracked `active_context.json` bytes in the isolation test and assert they are unchanged after invoking the mutating refresh/compiler helper against the copy.

- [ ] **Step 3: Verify fixture isolation is green**

Run:

```powershell
python -m pytest tests/test_compiler.py tests/test_invalidation.py -q
git status --short
```

Expected: targeted tests pass, tracked fixture bytes are unchanged, and status contains only intentional plan/test edits.

- [ ] **Step 4: Add failing core repository-boundary tests**

Delete the five bare-`pass` tests in `TestCompilerSecureReads`. Add parameterized tests that drive real consumers with:

```python
UNSAFE_PATHS = (
    "../outside.py",
    "/absolute/outside.py",
    r"C:\Windows\outside.py",
    r"\\server\share\outside.py",
    ".env",
    "private.key",
    "src/binary.bin",
    "src/too-large.txt",
)
```

Construct each fixture explicitly:

- create `.env` and `.sacasignore`-matched text containing a unique marker;
- create a NUL-containing binary and a 1,000,001-byte text file;
- create invalid UTF-8 with `write_bytes(b"\xff\xfe")`;
- create an external file and a repository symlink to it where supported;
- persist traversal/absolute/UNC paths in an `ActiveFileContext`.

For `read_repo_text()` and `read_repo_source_bytes()`, assert `ValueError` with the relevant denial reason. For enumeration, assert rejected relative paths are absent. These tests replace the direct-read “documentation” tests rather than supplementing them.

- [ ] **Step 5: Run core boundary tests and verify the missing source-byte API fails**

Run:

```powershell
python -m pytest tests/test_repository_reads.py -q
```

Expected: failures show `read_repo_source_bytes`/secure enumeration are absent and placeholder tests do not exercise production behavior.

- [ ] **Step 6: Add text-validating source bytes and secure enumeration to `io.py`**

Add:

```python
def read_repo_source_bytes(
    repository_root: Path,
    user_path: str,
    *,
    allow_ignored: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> bytes:
    content = read_repo_text(
        repository_root,
        user_path,
        allow_ignored=allow_ignored,
        max_bytes=max_bytes,
    )
    return content.encode("utf-8")
```

Use this helper for source hashes so binary or invalid UTF-8 content cannot become an apparently valid admission hash. Keep `read_repo_bytes()` as the bounded raw-byte primitive needed by the graph reader.

Add an immutable entry type and a deterministic iterator:

```python
@dataclass(frozen=True, slots=True)
class RepositoryTextFile:
    path: str
    content: str


def iter_repo_text_files(
    repository_root: Path,
    *,
    excluded_roots: tuple[str, ...] = (),
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Iterator[RepositoryTextFile]:
    """Yield eligible repository text files in repository-relative order."""
```

Implementation requirements:

- Enumerate names with `rglob("*")` but never read through the enumerated `Path`.
- Convert each name to a repository-relative POSIX path.
- Exclude configured generated roots by path component.
- Call `read_repo_text()` for content.
- Skip paths rejected as ignored, secret, binary, large, invalid UTF-8, missing, or escaped.
- Sort relative names before reading for deterministic output.

- [ ] **Step 7: Add a dedicated secure graph snapshot reader**

In `graphify.py`, add:

```python
MAX_GRAPH_SNAPSHOT_BYTES = 50_000_000


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    relative_path: str
    raw: bytes
    data: dict[str, Any]
    content_hash: str


def read_graph_snapshot(
    repository_root: Path,
    output: str,
) -> GraphSnapshot | None:
    """Read one valid repository-contained graph.json snapshot."""
```

Use `repository_relative_path()` for the configured output directory. Read its bytes
with `read_repo_bytes()` using `allow_ignored=True` and
`max_bytes=MAX_GRAPH_SNAPSHOT_BYTES`, reject NUL bytes, perform strict UTF-8
decoding, call `json.loads`, and require an object root. Return `None` only when the
graph is absent; raise a controlled `GraphSnapshotError` with `code` equal to
`unsafe`, `binary`, `invalid_encoding`, `oversized`, or `malformed` otherwise.

- [ ] **Step 8: Add failing routing/resolver/benchmark consumer tests**

Add these exact behavioral tests:

- `test_fallback_index_excludes_secret_ignored_binary_large_invalid_and_external_symlink`;
- `test_symbol_resolver_rejects_unsafe_or_secret_persisted_path`;
- `test_cli_expand_refuses_secret_file_rule_and_reference`;
- `test_status_and_validate_report_unavailable_unsafe_admission_without_reading_it`;
- `test_b0_b1_exclude_ineligible_files`;
- `test_budget_excludes_unreadable_admission_instead_of_direct_reading`;
- `test_analysis_module_and_repository_metadata_reads_reject_external_symlink`;
- `test_graph_snapshot_errors_become_unavailable_evidence_not_exceptions`.

Use unique marker strings and assert they never appear in indexes, candidates, diagnostics payload content, or benchmark file sets.

- [ ] **Step 9: Run consumer tests and verify direct-read failures**

```powershell
python -m pytest tests/test_search.py tests/test_symbol_resolver.py tests/test_cli_commands.py tests/test_validate.py tests/test_benchmark_runner.py tests/test_budget.py tests/test_analysis.py tests/test_graphify.py tests/test_compiler.py -q
```

Expected: failures identify the remaining direct-read consumers; optional Graphify tests may raise instead of returning unavailable evidence.

- [ ] **Step 10: Migrate fallback indexing and symbol resolution**

- `FallbackIndex.update()` consumes `iter_repo_text_files()` and hashes/indexes only returned entries.
- `SymbolRangeResolver.resolve()` and `resolve_node_range()` call `read_repo_text()`.
- `run_fallback_routing()` hashes with `read_repo_source_bytes()`.

Run `tests/test_search.py`, `tests/test_symbol_resolver.py`, and `tests/test_node_resolution.py`; expect all pass.

- [ ] **Step 11: Migrate CLI, status, validation, budgeting, and benchmark consumers**

- CLI expansion hashes rules, references, files, and symbols with `read_repo_source_bytes()`.
- Status and validation hash admitted source paths with `read_repo_source_bytes()` and report rejection as invalid context.
- `calculate_context_size()` and manifest rule/reference counting use secure repository reads. Legacy control-document counting may directly read trusted `Structure` control files, but repository rules/references are converted to repository-relative paths and use `read_repo_text()`.
- B0/B1 enumerate with `iter_repo_text_files()`; B1 scores complete content.

Run `tests/test_cli_commands.py`, `tests/test_validate.py`, `tests/test_budget.py`, and `tests/test_benchmark_runner.py`; expect all pass.

- [ ] **Step 12: Migrate analysis and repository metadata consumers**

Replace content reads/hashes in `analysis.py`, `modules.py`, and `repository.py` with secure reads using repository-relative paths. Preserve trusted internal-state reads. Run `tests/test_analysis.py`; expect all pass.

- [ ] **Step 13: Convert Graphify reader failures at the optional-evidence boundary**

`collect_graphify()` catches `GraphSnapshotError` and returns its existing empty
evidence value with `status="unavailable"` and warning
`f"Graphify graph rejected: {error.code}"`. Providers return `None` or an
unavailable result according to their existing interface; no `GraphSnapshotError`
escapes into routing. Task 2 distinguishes each unavailable outcome for identity
and fallback.

Graphify collection, adapter querying, and JSON provider loading obtain graph data
only through `read_graph_snapshot()`.

Run `tests/test_graphify.py` and `tests/test_graphify_providers.py`; expect all pass.

- [ ] **Step 14: Audit remaining production reads**

Run:

```powershell
rg -n "\.read_text\(|\.read_bytes\(|\bopen\(" src/sacas -g "*.py"
```

Classify every result in the implementation review notes as either repository-controlled and migrated, or trusted SACAS/internal/config state. No unclassified repository-controlled content read may remain.

- [ ] **Step 15: Make explicit rule/reference detection a named predicate**

In `tasks.py`, add and use:

```python
EXPLICIT_CONTEXT_REASON = "Explicitly specified by user"


def is_explicit_rule_or_reference(item: ActiveRuleContext | ActiveReferenceContext) -> bool:
    return item.reason == EXPLICIT_CONTEXT_REASON
```

Use the constant wherever explicit file/rule/reference reasons are constructed. This supports later task-reroute preservation without scattered text comparisons.

- [ ] **Step 16: Run targeted security and routing tests**

Run:

```powershell
python -m pytest tests/test_repository_reads.py tests/test_search.py tests/test_symbol_resolver.py tests/test_node_resolution.py tests/test_cli_commands.py tests/test_validate.py tests/test_budget.py tests/test_analysis.py tests/test_benchmark_runner.py tests/test_graphify.py tests/test_graphify_providers.py tests/test_compiler.py -q
```

Expected: all pass; secrets, ignored files, binaries, large files, invalid UTF-8, traversal, absolute paths, UNC paths, and external symlinks are excluded or rejected through real production consumers.

- [ ] **Step 17: Run the full suite and worktree-cleanliness check**

Run:

```powershell
python -m pytest -q -p no:cacheprovider
git diff --check
git status --short
```

Expected: full suite passes; status lists only intentional Task 1 changes and never a tracked fixture changed by tests.

- [ ] **Step 18: Commit Task 1**

```powershell
git add src/sacas/io.py src/sacas/analysis.py src/sacas/modules.py src/sacas/repository.py src/sacas/graphify.py src/sacas/search.py src/sacas/regions.py src/sacas/tasks.py src/sacas/cli.py src/sacas/status.py src/sacas/validate.py src/sacas/budget.py src/sacas/benchmark_runner.py tests/test_repository_reads.py tests/test_search.py tests/test_symbol_resolver.py tests/test_node_resolution.py tests/test_cli_commands.py tests/test_validate.py tests/test_budget.py tests/test_analysis.py tests/test_benchmark_runner.py tests/test_graphify.py tests/test_graphify_providers.py tests/test_compiler.py tests/test_invalidation.py
git commit -m "fix(security): enforce repository read boundary"
git status --short
```

Expected after commit: `git status --short` reports no output.

## Chunk 2: Fingerprint convergence and provenance-safe refresh

### Task 2: Use canonical task and graph identities end to end

**Commit:** `fix(refresh): converge task and graph identities`

**Files:**
- Modify: `src/sacas/graphify.py:26`
- Modify: `src/sacas/tasks.py:276`
- Modify: `src/sacas/refresh.py:20`
- Modify: `src/sacas/compiler.py:381`
- Test: `tests/test_graphify.py`
- Test: `tests/test_graphify_providers.py`
- Test: `tests/test_invalidation.py`
- Test: `tests/test_refresh.py`

- [ ] **Step 1: Write a task-change convergence lifecycle test**

Create `test_task_change_refresh_converges_and_updates_pack_header` using `tmp_path`:

```python
generate_task(installation, "old goal", files=("src/app.py",))
old_manifest = load_active_context(task_dir)
save_task_contract(task_dir, replace(load_task_contract(task_dir), goal="new goal"))

assert refresh_context(installation) is True
current_contract = load_task_contract(task_dir)
current_manifest = load_active_context(task_dir)
header, _ = read_context_pack(pack_path)

assert current_manifest.task_contract_hash == task_contract_hash(current_contract)
assert current_manifest.goal == "new goal"
assert header.task_contract_hash == current_manifest.task_contract_hash
assert refresh_context(installation) is False
```

Also assert the manifest task ID/category match the current contract.

- [ ] **Step 2: Complete the graph identity/outcome test set**

Implement these independently runnable test groups:

- [ ] **Step 2a: Raw identity.** Assert raw `graph.json` bytes and
  `GraphifyEvidence.content_hash` use the same SHA-256; the manifest and pack use
  it; reserializing `graphify.json` alone does not trigger rediscovery.
- [ ] **Step 2b: Change/removal.** Assert raw-byte changes trigger one rediscovery,
  removal stores empty identity and then converges, and custom `graphify_output`
  hashes the queried graph.
- [ ] **Step 2c: Rejection/provider failure.** Assert malformed evidence cleans old
  graph state and falls back, while provider failure retains valid raw identity,
  warns, and falls back.
- [ ] **Step 2d: Query result.** Assert zero matches retain raw identity and fall
  back; matches retain raw identity and admit only validated paths.

The individual assertions are:

- raw `graph.json` bytes and `GraphifyEvidence.content_hash` use the same SHA-256;
- `active_context.graph_snapshot_hash` and pack header use that value;
- changing raw graph bytes triggers exactly one rediscovery;
- serializing `Structure/.sacas/graphify.json` differently does not trigger rediscovery;
- custom `graphify_output` hashes the graph actually queried;
- graph removal stores an empty identity and the second refresh is clean;
- malformed graph is unavailable, cleans old graph state, and falls back lexically.
- provider failure retains the valid raw graph identity, warns with retry guidance,
  and falls back lexically;
- a valid zero-match query retains the raw graph identity and falls back lexically;
- a valid matching query retains the raw graph identity and admits only validated
  Graphify paths.

- [ ] **Step 3: Run the new convergence tests and verify failures**

Run:

```powershell
python -m pytest tests/test_invalidation.py tests/test_refresh.py tests/test_graphify.py tests/test_graphify_providers.py -q
```

Expected: task test fails because refresh retains the old contract hash; graph tests fail because refresh hashes normalized `graphify.json` while routing hashes raw `graph.json`.

- [ ] **Step 4: Define one typed Graphify routing outcome**

Add `GraphRoutingOutcome` in `graphify.py` with `snapshot_hash`,
`evidence_available`, `query_result`, `warning`, and `fallback_required` fields.
Implement `resolve_graph_routing_outcome(installation, query)` as the only place
that combines secure graph loading with provider/query behavior:

- absent or rejected snapshots return an empty hash, unavailable evidence, a
  controlled warning, and lexical fallback;
- valid snapshots with provider failure or zero matches retain the raw snapshot
  hash and request lexical fallback;
- valid snapshots with matches retain the raw hash and return the validated query
  result without fallback.

Catch `GraphSnapshotError` here; routing and refresh must not receive raw graph
reader exceptions.

- [ ] **Step 5: Replace `_compute_graph_snapshot_hash()` with the sole graph identity**

Implement:

```python
def current_graph_snapshot(installation: Installation) -> GraphSnapshot | None:
    return read_graph_snapshot(
        installation.repository_root,
        installation.manifest.graphify_output,
    )


```

Only `resolve_graph_routing_outcome()` invokes `current_graph_snapshot()`, inside
the `try` block that catches `GraphSnapshotError`. Every collection, routing,
refresh, provenance, and pack-header caller consumes the resulting
`GraphRoutingOutcome`; none reads a snapshot or computes a graph hash separately.
Thus absent and rejected graphs cannot escape through a separate hash-only path.
`Structure/.sacas/graphify.json` stores the same `content_hash`; never hash its
serialized bytes.

- [ ] **Step 6: Make graph-change comparison symmetric**

Replace the special-case “manifest has no hash means unchanged” logic with semantic equality:

```python
def _is_graph_changed(manifest: ActiveContextManifest, current_graph_hash: str) -> bool:
    return manifest.graph_snapshot_hash != current_graph_hash
```

Call it only when Graphify mode/evidence participates in routing, so `graphify_mode="off"` remains clean.

- [ ] **Step 7: Route with the current task contract during task invalidation**

In `refresh_context()`, load `contract` once, compute `current_task_hash`, and pass `contract.goal`, `contract.category`, and `current_task_hash` into full rerouting. Replace the final manifest's task ID, goal, category, and task hash from the contract before compilation.

Do not pass `manifest.task_contract_hash` into a task-change reroute.

- [ ] **Step 8: Persist the typed Graphify outcome identities**

Apply the design outcome table:

- absent/removed/malformed graph: empty identity and lexical fallback;
- valid graph with provider failure or zero matches: current raw identity plus lexical fallback;
- valid graph with matches: current raw identity plus validated graph admissions.

Provider failure must emit a warning that retry requires `sacas map` or task rerouting when raw evidence remains unchanged.

- [ ] **Step 9: Run convergence tests twice**

Run:

```powershell
python -m pytest tests/test_graphify.py tests/test_graphify_providers.py tests/test_invalidation.py tests/test_refresh.py -q
python -m pytest tests/test_graphify.py tests/test_graphify_providers.py tests/test_invalidation.py tests/test_refresh.py -q
```

Expected: both runs pass, proving no test-order or persisted-state dependency.

- [ ] **Step 10: Run full verification and commit Task 2**

```powershell
python -m pytest -q -p no:cacheprovider
git diff --check
git status --short
git add src/sacas/graphify.py src/sacas/tasks.py src/sacas/refresh.py src/sacas/compiler.py tests/test_graphify.py tests/test_graphify_providers.py tests/test_invalidation.py tests/test_refresh.py
git commit -m "fix(refresh): converge task and graph identities"
git status --short
```

Expected after commit: `git status --short` reports no output.

### Task 3: Preserve origin and maintain a correct provenance ledger

**Commit:** `fix(refresh): preserve admission provenance`

**Files:**
- Modify: `src/sacas/refresh.py:104`
- Modify: `src/sacas/tasks.py:423`
- Modify: `src/sacas/compiler.py:61`
- Modify: `src/sacas/provenance.py:23`
- Test: `tests/test_invalidation.py`
- Test: `tests/test_refresh.py`
- Test: `tests/test_compiler.py`
- Test: `tests/test_cli_commands.py`
- Test: `tests/test_e2e_routing.py`

- [ ] **Step 1: Write source-origin convergence tests**

Add a lifecycle test with a Graphify-derived symbol admission:

```python
before = load_active_context(task_dir)
before_file = file_by_path(before, "src/service.py")
before_events = events_for(before, "src/service.py")

move_symbol_in_source(repo / "src/service.py", "service")

assert refresh_context(installation) is True
after = load_active_context(task_dir)
after_file = file_by_path(after, "src/service.py")

assert after_file.source == before_file.source == "graphify"
assert after_file.evidence == before_file.evidence
assert after_file.ranking_score == before_file.ranking_score
assert after_file.confidence == before_file.confidence
assert symbol_range(after_file, "service") != symbol_range(before_file, "service")
assert refresh_context(installation) is False
```

Repeat for a heuristic-derived admission and an explicit admission.

- [ ] **Step 2: Write graph rediscovery event-ledger tests**

Implement these independently runnable groups across two sequential graph changes:

- [ ] **Step 2a: Removal and retention.** Removed Graphify paths/events disappear;
  retained explicit admissions/events keep their IDs.
- [ ] **Step 2b: Evidence and IDs.** Current Graphify admissions use current
  hash/query evidence; IDs remain unique; obsolete query IDs disappear; an
  unchanged refresh adds nothing.
- [ ] **Step 2c: Heuristic history.** Graph rediscovery preserves heuristic
  admissions/events when still relevant, replaces them only when the same path is
  newly admitted by Graphify, and creates no duplicate admission or event.

Assert in the combined lifecycle:

- removed Graphify paths and their events disappear;
- retained explicit admissions/events keep their IDs;
- current Graphify admissions point to the current graph hash/query evidence;
- all event IDs are unique;
- event count does not grow on an unchanged second refresh;
- obsolete query IDs are absent.

- [ ] **Step 3: Write task-reroute preservation tests**

Implement two independently runnable groups after changing the task contract:

- [ ] **Step 3a: File/test preservation.** Explicit files/tests survive with stable
  event IDs and refreshed hashes/selectors; heuristic/Graphify context is removed
  and recomputed.
- [ ] **Step 3b: Rule/reference budget preservation.** Explicit rules/references
  survive through `is_explicit_rule_or_reference()` and every preserved category
  is budgeted before new discoveries.

Construct explicit files/tests/rules/references plus heuristic and Graphify admissions and assert:

- explicit files and events survive with stable IDs but refreshed hashes/selectors;
- explicit tests survive;
- explicit rules/references survive through `is_explicit_rule_or_reference()`;
- old heuristic/Graphify admissions and events are removed and recomputed;
- preserved explicit files are included in budget calculation;
- preserved explicit tests, rules, and references are charged to their respective
  budget categories before new heuristic or Graphify admissions;
- immediate second refresh is clean.

- [ ] **Step 4: Write selective-refresh precedence tests**

Implement three independently runnable cases:

- [ ] **Step 4a: Invalidation precedence.** Task or graph invalidation ignores
  `selective_files` and performs the required full reroute.
- [ ] **Step 4b: Selective success.** Source-only selective refresh succeeds when
  only selected admissions are stale.
- [ ] **Step 4c: Selective rejection.** A non-selected stale admission raises a
  controlled incomplete-refresh error and leaves the canonical manifest unchanged.

Scan `manifest.all_files`, rules, and references before honoring the selective
filter. Task/graph invalidation always takes precedence. Task 4 adds the explicit
runtime-pack invalidation assertion; this task asserts only the controlled error
and unchanged canonical manifest.

- [ ] **Step 5: Write Graphify no-match fallback test with explicit tests present**

Create an active explicit test file, return a valid Graphify query with zero paths, and assert lexical source results are still admitted. This must fail against `graphify_success = len(active_files) > 0`.

- [ ] **Step 5a: Write layered source-refresh preservation tests**

Change one entry in each of `files`, `reference_files`, and `working_files`. Assert
refresh updates the appropriate hash/selector while preserving tuple membership,
source, evidence, ranking, confidence, relation, trigger, and role. Assert an
unchanged second refresh creates no new event.

- [ ] **Step 5b: Write fragment/event provenance tests**

Add compiler/provenance tests for two overlapping symbols with distinct events, a
file-target event that applies to every fragment, exact `path::symbol` matching,
stable sorted ID unions, and hashes computed from each fragment's content.

- [ ] **Step 6: Run the new tests and confirm root-cause failures**

Run:

```powershell
python -m pytest tests/test_invalidation.py tests/test_refresh.py tests/test_compiler.py tests/test_cli_commands.py tests/test_e2e_routing.py -q
```

Expected: origin becomes explicit, graph events accumulate, event IDs collide,
preserved context is not budgeted, and explicit tests suppress lexical fallback.

- [ ] **Step 7: Add an origin-preserving selector refresh helper**

In `refresh.py`, implement:

```python
def _refresh_file_selection(
    installation: Installation,
    file_context: ActiveFileContext,
) -> ActiveFileContext:
    """Rehash and re-resolve one admitted file without changing admission semantics."""
```

For full mode, only refresh the secure content hash. For symbol mode, resolve every
symbol through `SymbolRangeResolver.resolve()` and fail if any previously resolved
symbol cannot be resolved. Return `dataclasses.replace()` with only `selection` and
`hash` changed so origin, evidence, ranking, confidence, relation, trigger, and role
remain unchanged.

Apply the helper independently to `files`, `reference_files`, and `working_files`,
then reconstruct those same tuple memberships. Never flatten the three layers and
reclassify them during refresh.

- [ ] **Step 8: Separate reroute policies by invalidation type**

Replace the overloaded partial `route_goal()` explicit-files path with three explicitly
named branches: `_reroute_for_task_change`, `_rediscover_graph_context`, and
`_refresh_changed_sources`. Each accepts the installation, current contract,
current manifest, and invalidation details it needs, and returns one complete
in-memory manifest.

Extend the internal router with optional `seed_files`, `seed_events`, `seed_rules`,
and `seed_references` tuples. Public/new-task callers pass empty tuples. A task
reroute passes only refreshed admissions whose `source == "explicit"`, plus rules
and references accepted by the named `is_explicit_rule_or_reference()` predicate.
Initialize the budget ledger from those seeds before skeleton or discovered
admissions are considered. A graph rediscovery removes old Graphify admissions and
events, reruns Graphify, and preserves heuristic history unless the same path is
replaced by a new Graphify admission. Source refresh changes no admission source.

- [ ] **Step 9: Implement deterministic collision-free event merging**

Add `_event_identity(event)` and `_merge_events(preserved, generated)` helpers.
The identity tuple contains every persisted field except `id`: `target`, `action`,
`source`, `reason`, `trigger`, `triggered_by`, `relation`, `direction`,
`ranking_score`, `confidence`, `evidence`, all Graphify fields, and all lexical
fields.

Requirements:

- Preserve IDs of preserved events.
- Deduplicate semantically identical events with `_event_identity` excluding `id`.
- Allocate new `evt-refresh-NNN` IDs from the first unused number in deterministic event order.
- Never renumber preserved history.
- Graph rediscovery filters prior events by `source == "graphify"`, not
  `reroute_files`, while retaining heuristic event history for admissions that
  remain active.

- [ ] **Step 10: Implement fragment-aware provenance mapping without schema migration**

In `compiler.py`, introduce an internal `CompiledSelection` carrying the merged
line range, all constituent `ActiveSymbolContext` values, and the owning
`ActiveFileContext`. `_normalize_ranges_for_file()` groups every symbol overlapping
the merged range instead of keeping only the first. Build the canonical selector
as `source::` followed by sorted, comma-separated symbol names.

In `compiler.py`/`provenance.py`, add:

```python
def event_applies_to_selector(event: AdmissionEvent, source: str, selector: str) -> bool:
    if event.target == source:
        return True
    return event.target == selector
```

For merged ranges, call `event_applies_to_selector()` once for every constituent
selector retained by `CompiledSelection`, then union applicable IDs in sorted stable
order. Never match an event against the comma-joined display selector. Update
`trace_file_to_goal()` to collect every fragment whose `source` matches, render
selector/range/hash for each, and attach only its event IDs. Fix
`_get_pack_fragment_hash()` by hashing `fragment.content`, not an undefined
repository path.

- [ ] **Step 11: Make Graphify success depend on Graphify admissions**

Replace total-active-file counting with a local `graphify_admitted` counter. Zero admitted Graphify source files invokes lexical fallback even when explicit test files already exist.

- [ ] **Step 12: Run targeted refresh/provenance tests**

```powershell
python -m pytest tests/test_invalidation.py tests/test_refresh.py tests/test_compiler.py tests/test_cli_commands.py tests/test_e2e_routing.py -q
```

Expected: all origin, event, selective refresh, provenance, and fallback assertions pass.

- [ ] **Step 13: Run full verification and commit Task 3**

```powershell
python -m pytest -q -p no:cacheprovider
git diff --check
git status --short
git add src/sacas/refresh.py src/sacas/tasks.py src/sacas/compiler.py src/sacas/provenance.py tests/test_invalidation.py tests/test_refresh.py tests/test_compiler.py tests/test_cli_commands.py tests/test_e2e_routing.py
git commit -m "fix(refresh): preserve admission provenance"
git status --short
```

Expected after commit: `git status --short` reports no output.

## Chunk 3: Fail-closed compiler, benchmarks, and release gate

### Task 4: Make compilation and pack publication fail closed

**Commit:** `fix(compiler): reject invalid canonical context`

**Files:**
- Modify: `src/sacas/compiler.py:19`
- Modify: `src/sacas/tasks.py:764`
- Modify: `src/sacas/refresh.py:104`
- Modify: `src/sacas/validate.py:113`
- Modify: `src/sacas/cli.py:124`
- Test: `tests/test_compiler.py`
- Test: `tests/test_refresh.py`
- Test: `tests/test_invalidation.py`
- Test: `tests/test_validate.py`
- Test: `tests/test_cli_commands.py`

- [ ] **Step 1: Replace graceful-skip tests with fail-closed compiler tests**

Change `test_compiler_missing_source_file` and `test_compiler_deleted_source_file` to expect:

```python
with pytest.raises(ContextCompilationError) as exc:
    compile_context_pack(installation, manifest)
assert exc.value.code == "admitted_source_unavailable"
assert exc.value.path == "src/nonexistent.py"
```

Add corresponding tests for secret, ignored, binary, oversized, invalid UTF-8, unsafe persisted path, missing rule, and missing reference.

- [ ] **Step 2: Complete the stale-selector test**

Replace the non-asserting tail with:

```python
with pytest.raises(ContextCompilationError) as exc:
    compile_context_pack(fake_inst, manifest)
assert exc.value.code == "stale_selector"
assert exc.value.path == "src/test.py"
assert exc.value.selector == "src/test.py::foo"
```

Add deleted-symbol and out-of-bounds range cases. Assert no whole-file fallback is emitted.

- [ ] **Step 3: Add complete-admission coverage tests**

Test that compilation fails when:

- any `files`, `reference_files`, or `working_files` entry yields no fragment;
- a `manifest.tests` path has no admitted `role="test"` context;
- a mandatory rule/reference yields no fragment.

Retain and rename the header-only pack test to prove a genuinely empty manifest remains valid.

- [ ] **Step 4: Add pack/canonical cross-validation tests**

Create tests that mutate each of these after pack creation and expect validation failure:

- task ID/hash;
- graph hash;
- admitted source set;
- fragment content hash;
- fragment count;
- duplicate fragment ID;
- missing expected test/rule/reference fragment.

Exercise the runtime consumer, not only a validator helper: each mutation must make
`load_validated_context_pack(installation)` reject the pack.

- [ ] **Step 5: Add publication crash-window tests**

Monkeypatch each atomic write boundary to raise and assert:

1. Detected invalidation removes the old pack before rerouting.
2. Compilation failure leaves canonical manifest unchanged and pack absent.
3. Failure after pack write but before manifest write leaves a pack rejected against the old manifest.
4. Failure after manifest write but during Markdown writes leaves matching canonical manifest and pack.

- [ ] **Step 6: Run compiler lifecycle tests and verify current failures**

```powershell
python -m pytest tests/test_compiler.py tests/test_invalidation.py tests/test_refresh.py tests/test_validate.py -q
```

Expected: current compiler skips missing sources, emits stale ranges, accepts incomplete coverage, and has no cross-artifact validation/publication protocol.

- [ ] **Step 7: Add a typed compilation error**

In `compiler.py`:

```python
class ContextCompilationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str | None = None,
        selector: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.selector = selector
```

Raise it at the first invalid canonical admission. Never `continue` on a canonical file read failure.

- [ ] **Step 8: Make selector compilation reject known invalid state**

`_build_file_selections()` must:

- require every symbol to have a valid current range;
- reject ranges outside the file;
- reject a range that no longer resolves to the selector;
- never convert `no_valid_ranges` or `stale_selector` into a fragment;
- retain full-file mode only when it was the canonical admitted selection.

Selector re-resolution remains refresh's responsibility; compiler validates and emits only.

- [ ] **Step 9: Validate expected canonical coverage**

Add:

```python
def validate_context_pack_against_state(
    header: ContextPackHeader,
    fragments: Sequence[ContextPackFragment],
    contract: TaskContract,
    manifest: ActiveContextManifest,
) -> None:
    """Reject a self-consistent pack that does not represent canonical state."""
```

Check `header.task_id == contract.task_id`,
`header.task_contract_hash == task_contract_hash(contract)`, the matching manifest
task/graph identities, unique IDs, content hashes/counts, every
`manifest.all_files` source, every admitted test role, every rule, and every
reference. Permit header-only output only for a genuinely empty canonical
manifest.

Add `load_validated_context_pack(installation)`: load the current task contract and
manifest with `load_task_state()`, require both, read the pack, call
`validate_context_pack_against_state()`, and return the validated header/fragments.
Make provenance, `sacas validate`, and any CLI/status pack reader use this function
so no runtime consumer trusts a header against the manifest alone.

- [ ] **Step 10: Add explicit pack invalidation and in-memory serialization**

Implement `context_pack_path(installation)`, `invalidate_context_pack(installation)`,
and `serialize_context_pack(header, fragments)`. The invalidator resolves the one
known runtime-pack path and calls `unlink(missing_ok=True)`; serialization returns
deterministic JSONL with a final newline. `write_context_pack()` atomically writes
only the returned serialized value.

Serialization remains deterministic JSONL with a final newline. `write_context_pack()` writes the serialized value atomically.

- [ ] **Step 11: Reorder regeneration/publication**

Refactor `regenerate_task_markdown()` and add a single
`publish_task_artifacts(installation, task_dir, candidate_manifest,
candidates_data)` boundary. It computes views, budget, candidates JSON, candidate
manifest, header, fragments, and serialized pack before any publication. Validate
the candidate contract/manifest/pack in memory, then write in this order:

```python
write_context_pack(installation, header, fragments)
save_active_context(task_dir, updated_manifest)
write_text_atomic(task_md_path, task_md_content)
write_text_atomic(state_md_path, state_md_content)
write_text_atomic(task_dir / "PICKUP.md", pickup_content)
write_text_atomic(task_dir / "CONTEXT.md", context_md_final)
write_text_atomic(task_dir / "candidates.json", candidates_content)
```

Task creation, full refresh, selective refresh, CLI scope expansion, and
`_re_route_files()` all call this publisher; remove their direct
`save_active_context()` and generated-view writes. `refresh_context()` calls
`invalidate_context_pack()` immediately after detecting task, graph, or source
invalidation and before rerouting. It does not save intermediate updated hashes or
write `candidates.json` before the canonical commit point.

- [ ] **Step 12: Extend `sacas validate` to validate the pack against canonical state**

When a current task exists:

- require the runtime pack;
- call `load_validated_context_pack()`;
- report failures as `context_pack_mismatch` with a concrete reason;
- retain existing task ID/hash, stale source, missing source, and budget diagnostics using secure reads.

- [ ] **Step 13: Run targeted compiler and validation tests**

```powershell
python -m pytest tests/test_compiler.py tests/test_refresh.py tests/test_invalidation.py tests/test_validate.py tests/test_cli_commands.py -q
```

Expected: all fail-closed, coverage, crash-window, and cross-validation tests pass.

- [ ] **Step 14: Run full verification and commit Task 4**

```powershell
python -m pytest -q -p no:cacheprovider
git diff --check
git status --short
git add src/sacas/compiler.py src/sacas/tasks.py src/sacas/refresh.py src/sacas/validate.py src/sacas/cli.py tests/test_compiler.py tests/test_refresh.py tests/test_invalidation.py tests/test_validate.py tests/test_cli_commands.py
git commit -m "fix(compiler): reject invalid canonical context"
git status --short
```

Expected after commit: `git status --short` reports no output.

### Task 5: Make benchmarks, documentation, and release state credible

**Commit:** `fix(benchmark): make Fix6 claims reproducible`

**Files:**
- Modify: `src/sacas/benchmark_runner.py:146`
- Modify: `src/sacas/cli.py:590`
- Modify: `src/sacas/git_benchmark.py:124`
- Modify: `tests/test_benchmark_runner.py`
- Modify: `tests/test_git_benchmark.py`
- Modify: `tests/test_repository_reads.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-20-sacas-fix6-stabilization-design.md`
- Modify: `docs/superpowers/plans/2026-08-20-sacas-fix6-stabilization.md`
- Test: full suite and CLI acceptance commands

- [ ] **Step 1: Write metric compatibility tests**

Assert new results serialize only:

```python
assert "whole_repository_reduction" in result.to_dict()
assert "token_reduction" not in result.to_dict()
assert result.token_reduction == result.whole_repository_reduction
```

Assert CLI output says `Whole-repository reduction` or `vs B0`, never presents generic `Token Reduction`.

- [ ] **Step 2: Write a full-content B1 test**

Place the only matching keyword after line 50 in an eligible text file and assert B1 retrieves it. Add secret, ignored, binary, large, and invalid UTF-8 files containing the keyword and assert B1 excludes them.

- [ ] **Step 3: Replace historical ordering and isolation placeholders**

Replace SHA inequality with actual order assertions derived from `git log`. Add a
monkeypatched routing recorder proving each historical task calls `route_goal()`
without child-derived hints:

```python
files == ()
symbols == ()
tests == ()
goal == child_commit_subject
```

The recorder also captures `installation.repository_root`. Run
`git -C <captured-root> rev-parse HEAD` and assert it equals the expected parent
commit. Assert expected child filenames/blobs appear only in evaluation after
routing returns.

- [ ] **Step 4: Run benchmark tests and verify failures**

```powershell
python -m pytest tests/test_benchmark_runner.py tests/test_git_benchmark.py -q
```

Expected: generic metric name, 50-line B1 sampling, and weak historical order assertion fail the new tests.

- [ ] **Step 5: Rename the benchmark field with a read-only compatibility alias**

Change `RoutingBenchmarkResult` to store `whole_repository_reduction`. Add:

```python
@property
def token_reduction(self) -> float:
    """Deprecated compatibility alias; do not serialize."""
    return self.whole_repository_reduction
```

Update `to_dict()`, CLI output, tests, and README. Do not write both JSON fields.

- [ ] **Step 6: Remove B1's first-50-line sample**

Score the complete secure content returned by `iter_repo_text_files()`. Preserve deterministic top-10 ordering with a complete tie-break key:

```python
scored_files.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
```

- [ ] **Step 7: Make historical ordering explicit and deterministic**

Document that `_get_commit_history()` returns newest first and `generate_historical_tasks()` preserves that order, or intentionally reverse both implementation and tests to oldest first. Choose one convention, name it in the docstring, and assert exact child commit order. Do not use adjacency inequality as evidence.

- [ ] **Step 8: Update README and Fix6 non-goals**

Document:

- one-pass task/graph/source convergence;
- fail-closed compiler behavior;
- pack/canonical validation;
- secure read boundary;
- exact Graphify failure outcomes and retry instruction;
- `whole_repository_reduction` meaning;
- B1 full-content eligible-file behavior;
- historical weak-gold parent isolation;
- deferred P2 items.

- [ ] **Step 9: Regenerate and validate ignored local SACAS state**

`Structure/` is intentionally ignored by `.gitignore`; it is workspace state, not a
release artifact. After all production changes are complete, replace the leftover
test/demo task locally with this repository-grounded Fix6 verification task:

```powershell
python -m sacas task "Verify Fix6 secure convergence, provenance, compilation, and benchmarks" --root . --category investigate --criteria "All Fix6 acceptance checks pass" "A second refresh is clean" --constraints "Do not admit secrets, ignored files, binary files, or oversized files" --verification "python -m pytest -q -p no:cacheprovider" "python -m sacas validate --root ." --files src/sacas/io.py src/sacas/graphify.py src/sacas/refresh.py src/sacas/compiler.py src/sacas/benchmark_runner.py --tests tests/test_repository_reads.py tests/test_invalidation.py tests/test_compiler.py tests/test_benchmark_runner.py
python -m sacas refresh --root .
python -m sacas validate --root .
```

Expected: validation exits zero, emits no `FAIL`, and reports no missing, stale, or
hash-mismatch diagnostics. Graphify may report a controlled warning when external
evidence is unavailable. Confirm `git status --short --ignored Structure` marks the
generated state ignored; do not stage it.

- [ ] **Step 10: Run the complete release gate**

```powershell
python -m pytest -q -p no:cacheprovider
python -m sacas validate --root .
python -m sacas status --root . --format json
git diff --check
git status --short
```

Expected:

- 100% tests pass.
- Validation exits zero with no `FAIL` diagnostics.
- Status reports no stale files.
- No tracked fixture is modified by tests.
- `git diff --check` reports no whitespace errors.
- `git status --short` contains only intentional Task 5 code and documentation
  changes; ignored `Structure/` state is absent.

- [ ] **Step 11: Run historical benchmark smoke verification**

Use a verified temporary output directory so the smoke run cannot dirty the
repository:

```powershell
$fix6Bench = Join-Path ([System.IO.Path]::GetTempPath()) "sacas-fix6-histbench-$PID"
New-Item -ItemType Directory -Path $fix6Bench -ErrorAction Stop | Out-Null
python -m sacas histbench --root . --max-commits 5 --format json --output-dir $fix6Bench
$histbenchExit = $LASTEXITCODE
$resolvedBench = (Resolve-Path -LiteralPath $fix6Bench).Path
$resolvedTemp = (Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath())).Path
$relativeBench = [System.IO.Path]::GetRelativePath($resolvedTemp, $resolvedBench)
if ([System.IO.Path]::IsPathRooted($relativeBench) -or $relativeBench -eq "." -or $relativeBench -eq ".." -or $relativeBench.StartsWith("..$([System.IO.Path]::DirectorySeparatorChar)")) { throw "Unsafe benchmark cleanup path" }
Remove-Item -LiteralPath $resolvedBench -Recurse -Force
if ($histbenchExit -ne 0) { throw "Historical benchmark failed with exit code $histbenchExit" }
git status --short
```

Expected: every successful result identifies the actual parent and child, has no routing error, and reports retrieval from parent code. Treat insufficient/non-actionable commit samples as skipped weak gold, not false success.

- [ ] **Step 12: Commit Task 5**

```powershell
git add src/sacas/benchmark_runner.py src/sacas/cli.py src/sacas/git_benchmark.py tests/test_benchmark_runner.py tests/test_git_benchmark.py tests/test_repository_reads.py README.md docs/superpowers/specs/2026-08-20-sacas-fix6-stabilization-design.md docs/superpowers/plans/2026-08-20-sacas-fix6-stabilization.md
git commit -m "fix(benchmark): make Fix6 claims reproducible"
git status --short
```

Expected after commit: `git status --short` reports no output. Ignored local SACAS
state may remain and is deliberately outside the commit.

## Final Fix6 acceptance checklist

- [ ] `task.json`, `active_context.json`, and pack task hashes agree.
- [ ] Raw Graphify identity is identical in cache, manifest, provenance, and pack.
- [ ] Task change converges after one refresh.
- [ ] Graph change/removal converges after one refresh.
- [ ] Source change converges after one refresh and preserves origin.
- [ ] Selective refresh cannot publish a globally incomplete pack.
- [ ] Graph rediscovery removes obsolete events and produces no duplicate IDs.
- [ ] Graphify failure/no-match reaches lexical fallback even with explicit tests.
- [ ] Missing or unsafe admitted sources fail compilation.
- [ ] Stale/deleted selectors fail compilation unless refresh re-resolves them.
- [ ] Every canonical admission is represented in the pack.
- [ ] A crash or failed rebuild cannot leave an apparently current stale pack.
- [ ] `sacas why` reports every fragment and its applicable persisted events.
- [ ] No production repository-controlled read bypasses secure I/O.
- [ ] B1 searches full eligible content.
- [ ] New benchmark output uses `whole_repository_reduction` only.
- [ ] Historical routing uses the actual detached parent and no child file hints.
- [ ] Placeholder architecture tests are gone.
- [ ] Tests never modify tracked fixtures.
- [ ] Full suite passes.
- [ ] Regenerated local `sacas validate --root .` exits zero with no `FAIL`.
- [ ] `git diff --check` passes.
- [ ] Worktree contains only intentional uncommitted changes, or is clean after the fifth commit.

## Deferred after Fix6

Do not pull these into implementation unless empirical evaluation later demonstrates need:

- ranking/confidence model redesign;
- multi-node-per-file Graphify aggregation;
- deterministic query-ID redesign;
- `STATE.md` authority redesign;
- dependency graph/build engine;
- vector or embedding retrieval;
- new provenance storage;
- agent-success benchmarking framework.
