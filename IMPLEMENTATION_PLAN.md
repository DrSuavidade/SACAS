# SACAS Implementation Plan

Based on code review at commit `629894c` (19 Aug 2026). Prioritized roadmap with specific code changes.

---

## Phase 1: P0 — Critical State/Architecture Fixes

### 1.1 Persist Task Contract Canonically

**Problem:** `ActiveContextManifest` lacks `criteria`, `constraints`, `verification`, `tests` fields. Refresh reconstructs manifest but loses task contract (comment: "we don't have criteria stored in manifest").

**Files to change:**
- `src/sacas/task_contract.py` — already has `TaskContract` with all fields
- `src/sacas/active_context.py` — `ActiveContextManifest` needs `task_contract_hash` (exists) but not the contract itself
- `src/sacas/tasks.py` — `generate_task()` saves `task.json` but `load_active_context()` only recovers `goal`/`category`

**Changes:**

```python
# active_context.py: ActiveContextManifest
@dataclass(frozen=True)
class ActiveContextManifest:
    task_id: str
    task_contract_hash: str = ""
    # NEW: store minimal contract reference for round-trip
    # criteria/constraints/verification stay in task.json (canonical)
    # active_context.json stays focused on ADMISSION DECISIONS
```

**Action:** Ensure `load_active_context()` loads `task.json` alongside `active_context.json` and exposes both. The canonical split:
- `tasks/current/task.json` — WHAT (goal, criteria, constraints, verification, category)
- `tasks/current/active_context.json` — WHICH (admitted files, symbols, ranges, reasons, events, budget)

No schema merge needed. Just ensure both load/save atomically in `generate_task()` and `regenerate_task_markdown()`.

---

### 1.2 Graphify → Symbol/Range Routing (Not Whole Files)

**Problem:** Graphify discovers precise nodes (`validateToken` at line 84 in `auth.ts`), but SACAS admits entire file with `selection={"mode": "full"}`.

**Files to change:**
- `src/sacas/tasks.py` — `route_goal()` lines 440-530 (Graphify admission loop)
- `src/sacas/regions.py` — `SymbolRangeResolver.resolve_node_range()` already exists and returns `(selection_dict, reason)`
- `src/sacas/graphify.py` — `GraphifyQueryResult` has `nodes` with `label`, `path`, `line`, `node_type`

**Current flow (lines 466-521):**
```python
for path in query_res.paths:
    node = path_to_node.get(path)
    selection = {"mode": "full"}
    if node:
        resolved_res = SymbolRangeResolver.resolve_node_range(installation, f_rel, node.label, node.line)
        if resolved_res:
            selection, reason = resolved_res  # <-- THIS WORKS but reason not used properly
```

**Fix:** Use the resolved selection. The `resolved_res` already returns `{"mode": "symbols", "symbols": [ActiveSymbolContext]}`. Just adopt it.

**Additional:** When `node` exists but `resolve_node_range` returns `None`, fall back to line-range extraction (Tier 3 in resolver) rather than full file.

**Result:** Graphify admissions become symbol-scoped by default. Full file = fallback only.

---

## Phase 2: P1 — Semantic Corrections

### 2.1 Category Inference: Stop Defaulting to "bugfix"

**File:** `src/sacas/tasks.py` lines 298-310 and 648-659 (two locations)

**Current:**
```python
else:
    category = "bugfix"  # DANGEROUS DEFAULT
```

**Change:**
```python
else:
    category = "investigate"  # or "general", "unknown"
```

Add explicit categories: `investigate`, `documentation`, `architecture`, `general`, `unknown`. Only infer `bugfix`/`feature`/`test`/`refactor` when keywords strongly present.

---

### 2.2 Separate `ranking_score` from `confidence` with Evidence

**Files:** `src/sacas/active_context.py` (AdmissionEvent, ActiveFileContext), `src/sacas/tasks.py` (admission logic)

**Current:** `confidence: str` = "high"/"medium"/"low" assigned heuristically.

**New model:**
```python
@dataclass(frozen=True)
class AdmissionEvent:
    id: str
    target: str
    action: Literal["admit"]
    source: str
    reason: str
    trigger: str
    triggered_by: str | None = None
    relation: str | None = None
    direction: Literal["forward", "reverse"] | None = None
    # REPLACE confidence: float with:
    ranking_score: float = 0.0      # retrieval priority
    confidence: float = 0.0         # calibrated certainty [0,1]
    evidence: tuple[str, ...] = ()  # ["graphify_query", "calls_relation", "goal_symbol_match"]
```

**ActiveFileContext:** Add `ranking_score: float`, `confidence: float`, `evidence: tuple[str, ...]`.

**Rendering:** Keep `high/medium/low` labels in `CONTEXT.md` for humans (`>=0.7 high`, `>=0.4 medium`, else `low`).

---

### 2.3 Fix Benchmark Baselines (Add B1-B5)

**File:** `src/sacas/benchmark_runner.py` lines 147-157 (token_reduction calculation)

**Current baseline:** First 50 repo files → `calculate_context_size()` = "whole repo"

**New baselines to implement:**

| Baseline | Description | Implementation |
|----------|-------------|----------------|
| B0 | Whole repository (current) | Keep for reference |
| B1 | Filename + ripgrep retrieval | Simulate: `rg -l <keywords>` → top 10 files |
| B2 | Lexical SACAS fallback | `run_fallback_routing()` result |
| B3 | Graphify only (whole files) | Graphify paths with `mode: full` |
| B4 | SACAS Graphify routing (current) | Current `route_goal()` result |
| B5 | Coding agent native search | Approximate: B1 + B3 combined |

**Metrics per baseline:**
- `context_tokens` — tokens provided
- `file_recall` — % of gold files retrieved
- `symbol_recall` — % of gold symbols retrieved
- `test_recall` — % of gold tests retrieved
- `task_success` — proxy: did retrieval include files that actually changed in ground truth?

**Output:** Table comparing all baselines on same gold tasks.

---

### 2.4 Tokenizer Abstraction

**File:** `src/sacas/budget.py` line 12-15 (`estimate_tokens`)

**Current:** `len(text) // 4` hardcoded.

**New:** Pluggable tokenizer registry.

```python
# budget.py
from abc import ABC, abstractmethod

class Tokenizer(ABC):
    name: str
    @abstractmethod
    def count(self, text: str) -> int: ...

class CharHeuristicTokenizer(Tokenizer):
    name = "char_heuristic"
    def count(self, text: str) -> int:
        return len(text) // 4

class TiktokenTokenizer(Tokenizer):
    name = "tiktoken"
    def __init__(self, encoding="cl100k_base"):
        import tiktoken
        self.enc = tiktoken.get_encoding(encoding)
    def count(self, text: str) -> int:
        return len(self.enc.encode(text))

# Registry
TOKENIZERS = {
    "char_heuristic": CharHeuristicTokenizer(),
    "tiktoken": TiktokenTokenizer(),
    # anthropic, gemini adapters later
}

def estimate_tokens(text: str, tokenizer: str = "char_heuristic") -> int:
    return TOKENIZERS[tokenizer].count(text)
```

**Manifest:** Store `tokenizer: str` in `ContextBudgetState` (already has field). Render in `CONTEXT.md`: `tokenizer: char_heuristic`.

---

## Phase 3: Major Features

### 3.1 Context Compiler → `.sacas/runtime/context.pack.jsonl`

**New file:** `src/sacas/compiler.py`

**Concept:** After admission decisions finalize, compile an ephemeral payload the agent actually receives.

```python
# compiler.py
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ContextPackEntry:
    id: str                    # ctx-001
    source: str                # src/auth/service.ts
    selector: str              # AuthService.validateToken
    lines: tuple[int, int]     # (83, 127)
    hash: str                  # file content hash
    reason: str                # Called by LoginController.authenticate
    estimated_tokens: int      # 486
    admission_event_id: str    # evt-init-003

def compile_context_pack(
    installation: Installation,
    manifest: ActiveContextManifest
) -> list[ContextPackEntry]:
    entries = []
    for idx, f in enumerate(manifest.all_files):
        f_path = installation.repository_root / f.path
        if not f_path.is_file():
            continue
        content = f_path.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        
        if f.selection.get("mode") == "symbols":
            for sym in f.selection.get("symbols", []):
                rng = sym.range
                if rng and 1 <= rng.start_line <= len(lines) and 1 <= rng.end_line <= len(lines):
                    fragment = "\n".join(lines[rng.start_line-1:rng.end_line])
                    entries.append(ContextPackEntry(
                        id=f"ctx-{idx:03d}",
                        source=f.path,
                        selector=f"{f.path}::{sym.name}",
                        lines=(rng.start_line, rng.end_line),
                        hash=hashlib.sha256(fragment.encode()).hexdigest()[:16],
                        reason=sym.reason or f.reason,
                        estimated_tokens=estimate_tokens(fragment),
                        admission_event_id=f.ev  # link to event
                    ))
        else:
            # Full file fallback
            entries.append(ContextPackEntry(...))
    
    return entries

def write_context_pack(installation: Installation, entries: list[ContextPackEntry]) -> Path:
    runtime_dir = installation.sacas_root / ".sacas" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pack_path = runtime_dir / "context.pack.jsonl"
    with pack_path.open("w") as f:
        for e in entries:
            f.write(json.dumps(asdict(e)) + "\n")
    return pack_path
```

**Integration:** Call from `regenerate_task_markdown()` after manifest finalized. Agent reads `.sacas/runtime/context.pack.jsonl` instead of opening 5 files.

**Critical:** Pack is **generated artifact**, never canonical. Rebuild on every refresh.

---

### 3.2 Historical Git Benchmark Infrastructure

**New files:**
- `src/sacas/git_benchmark.py` — core logic
- `benchmarks/historical/` — generated gold tasks (gitignored)
- `scripts/gen_historical_benchmarks.py` — CLI to generate

**Algorithm:**
```python
def generate_historical_tasks(repo_root: Path, max_commits: int = 1000) -> list[dict]:
    # 1. Get commit history with messages
    commits = git_log(repo_root, max_commits)
    
    tasks = []
    for i in range(1, len(commits)):
        parent = commits[i-1]
        child = commits[i]
        
        # Ground truth from diff
        changed_files = git_diff_files(repo_root, parent.hash, child.hash)
        changed_symbols = git_diff_symbols(repo_root, parent.hash, child.hash)  # AST diff
        changed_tests = [f for f in changed_files if "test" in f]
        
        # Task goal from commit message
        goal = child.message.split("\n")[0]
        
        # Skip trivial commits
        if len(changed_files) == 0 or len(goal) < 10:
            continue
            
        tasks.append({
            "id": f"hist-{parent.hash[:8]}",
            "parent_commit": parent.hash,
            "child_commit": child.hash,
            "goal": goal,
            "expected": {
                "files": changed_files,
                "symbols": changed_symbols,
                "tests": changed_tests
            }
        })
    return tasks
```

**Evaluation:** For each historical task:
1. Checkout parent commit
2. Run `route_goal()` with commit message as goal
3. Measure recall@K, symbol_recall, token_reduction vs baselines
4. Aggregate across N tasks

**Output:** `benchmark_results/historical_<timestamp>.json` with per-task + aggregate metrics.

---

### 3.3 Provenance Tracking → `sacas why <file>`

**Files:** `src/sacas/cli.py` (new command), `src/sacas/provenance.py` (new)

**Data model:** Link `AdmissionEvent` → `ContextPackEntry` → modified file.

```python
# provenance.py
def trace_file_to_context(
    installation: Installation,
    target_file: str,
    manifest: ActiveContextManifest
) -> list[str]:
    """Return chain: task → graphify query → node → admission event → context pack → file"""
    # 1. Find admission event for target_file
    # 2. Follow triggered_by chain backwards
    # 3. Find corresponding context pack entries
    # 4. Render as tree
```

**CLI:**
```bash
sacas why src/auth/service.ts
```

**Output:**
```
Task: "Fix token validation expiry"
 ↓ Graphify query: "token validation expiry"
 ↓ Node: AuthService.validateToken (src/auth/service.ts:84)
 ↓ Edge: calls → LoginController.authenticate (confidence=0.91)
 ↓ Admission: evt-init-003 (ranking=0.84, confidence=0.91, evidence=["graphify_query","calls_relation"])
 ↓ Context Pack: ctx-008 (lines 83-127, 486 tokens)
 ↓ Modified: src/auth/service.ts
```

---

### 3.4 Incremental Invalidation

**Files:** `src/sacas/refresh.py`, `src/sacas/active_context.py` (hash fields exist)

**Mechanism:**
1. On `sacas refresh`, compute hash of each admitted file
2. Compare with `ActiveFileContext.hash`
3. If changed → mark stale, find dependent selectors
4. Only re-route affected selectors (not whole manifest)

**Implementation:**
```python
# refresh.py
def incremental_refresh(installation: Installation, manifest: ActiveContextManifest) -> ActiveContextManifest:
    stale_files = []
    for f in manifest.all_files:
        current_hash = file_hash(installation.repository_root / f.path)
        if current_hash != f.hash:
            stale_files.append(f.path)
    
    if not stale_files:
        return manifest  # nothing changed
    
    # Find which selectors depend on stale files
    affected_selectors = find_dependent_selectors(manifest, stale_files)
    
    # Re-route only affected selectors
    new_manifest = re_route_selectors(installation, manifest, affected_selectors)
    
    return new_manifest
```

**Dependency tracking:** Use Graphify edges (`calls`, `imports`, `references`) + admission event `triggered_by` chains.

---

## Phase 4: Hardening & Polish

### 4.1 Graphify Version Compatibility Matrix in CI

**File:** `.github/workflows/ci.yml` (or equivalent)

**Matrix:**
```yaml
strategy:
  matrix:
    graphify_version:
      - "0.9.44"   # minimum supported (API_VERSION_FLOOR)
      - "latest"   # latest release
```

**Test steps:**
1. Install specific graphifyy version
2. Run `graphify --help` verification
3. Run `graphify extract` on test fixture
4. Run `graphify query` contract validation
5. Run SACAS benchmark suite

**Fail fast:** If `graphify query` output contract changes, CI fails with clear message.

---

### 4.2 Narrow SKILL Trigger

**File:** `SKILL.md` and `src/sacas/cli.py` (init command)

**Current:** "when starting work on any codebase"

**New semantics:**
```markdown
Use SACAS automatically when:
- .sacas / Structure installation already exists
- user explicitly invokes /sacas or `sacas init`
- user asks for context architecture / AI repo organization

Suggest SACAS when:
- onboarding to a large unfamiliar repository (>50 files)

Do NOT initialize SACAS automatically merely because coding work began.
```

**Implementation:** `sacas init` requires explicit flag or existing installation detection.

---

### 4.3 Consolidate Legacy/Fallback Routing

**Files:** `src/sacas/tasks.py` — `run_fallback_routing()`, `route_goal()` has duplicate logic paths

**Action:** Single `RetrievalInterface` with implementations:
- `GraphifyRetrieval`
- `LexicalFallbackRetrieval` 
- `ExplicitRetrieval` (user-provided files/symbols)

All return `list[Candidate]` with unified fields: `path`, `symbols`, `score`, `evidence`, `source`.

`route_goal()` becomes: collect candidates from all enabled retrievers → merge → rank → budget filter → admit.

---

## Execution Order

| Week | Focus | Deliverable |
|------|-------|-------------|
| 1 | P0: Task contract persistence + Graphify symbol routing | `task.json` + `active_context.json` round-trip; Graphify admits symbols |
| 2 | P1: Category fix, confidence split, benchmark baselines | No more false bugfix; calibrated scores; B1-B5 baseline table |
| 3 | P1: Tokenizer abstraction + Context Compiler | Pluggable tokenizers; `.sacas/runtime/context.pack.jsonl` |
| 4 | Feature: Historical Git benchmarks + Provenance | `sacas bench-history`, `sacas why <file>` |
| 5 | Feature: Incremental invalidation + CI matrix | Fast refresh; Graphify version matrix in CI |
| 6 | Polish: SKILL trigger, legacy consolidation, docs | Cleaner init; single retrieval pipeline |

---

## Success Criteria

1. **Token reduction claims defensible:** Benchmark shows SACAS (B4) vs realistic baselines (B1, B2, B3, B5) with task quality metrics
2. **Symbol-level routing default:** >80% of Graphify admissions are symbol-scoped, not full files
3. **Provenance query works:** `sacas why <file>` shows complete chain for any modified file
4. **Historical validation:** >100 historical tasks evaluated, aggregate recall@5 > 0.7
5. **Refresh is incremental:** Changing 1 file re-routes <5 selectors, not full manifest