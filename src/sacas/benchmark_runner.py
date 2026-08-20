from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from sacas.active_context import ActiveContextManifest
from sacas.paths import Installation
from sacas.budget import calculate_context_size, calculate_manifest_tokens
from sacas.tasks import route_goal, run_fallback_routing, extract_keywords
from sacas.refresh import generate_candidates_for_manifest
from sacas.graphify import get_graphify_provider
from sacas.io import RepositoryTextFile, iter_repo_text_files


def _get_repo_entries(installation: Installation) -> list[RepositoryTextFile]:
    """Get all repository files excluding SACAS/Graphify directories."""
    return list(iter_repo_text_files(
        installation.repository_root,
        excluded_roots=("Structure", "graphify-out", ".worktrees"),
    ))


def _get_repo_files(installation: Installation) -> list[str]:
    return [entry.path for entry in _get_repo_entries(installation)]


def _baseline_b0_whole_repo(installation: Installation) -> tuple[int, list[str]]:
    """B0: Whole repository baseline."""
    repo_entries = _get_repo_entries(installation)
    repo_files = [entry.path for entry in repo_entries]
    tokens = calculate_context_size(installation.repository_root, tuple(repo_files))
    return tokens, repo_files


def _baseline_b1_basic_search(installation: Installation, goal: str) -> tuple[int, list[str]]:
    """B1: Basic search baseline - filename + content keyword matching.
    
    Simulates what a developer/agent can achieve with basic repository search.
    """
    from sacas.tasks import extract_keywords
    keywords = extract_keywords(goal)
    if not keywords:
        return 0, []
    
    repo_entries = _get_repo_entries(installation)
    scored_files = []
    for entry in repo_entries:
        f = entry.path
        score = 0
        fname = Path(f).name.lower()
        
        # Filename matching
        for kw in keywords:
            if kw in fname:
                score += 10
                if fname.startswith(kw):
                    score += 5
        
        # Content keyword matching searches the whole eligible source entry.
        content_sample = entry.content.lower()
        for kw in keywords:
            if kw in content_sample:
                score += 3
        
        if score > 0:
            scored_files.append((score, f))
    
    scored_files.sort(key=lambda x: -x[0])
    top_files = [f for _, f in scored_files[:10]]
    tokens = calculate_context_size(installation.repository_root, tuple(top_files))
    return tokens, top_files


def _baseline_b2_lexical_fallback(installation: Installation, goal: str) -> tuple[int, list[str]]:
    """B2: Lexical SACAS fallback routing."""
    from sacas.tasks import get_git_commit, parse_protected_boundaries
    commit = get_git_commit(installation.repository_root)
    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(installation.repository_root, boundaries_file)
    
    fallback_results = run_fallback_routing(installation.repository_root, installation.sacas_root, goal, parsed_boundaries, commit)
    files = [item["path"] for item in fallback_results]
    tokens = calculate_context_size(installation.repository_root, tuple(files))
    return tokens, files


def _baseline_b3_graphify_whole_files(installation: Installation, goal: str) -> tuple[int, list[str]]:
    """B3: Graphify only (whole files)."""
    try:
        provider = get_graphify_provider(installation, required={"query"})
        if not provider.verify_capabilities(required={"query"}):
            return 0, []
        
        graph_path = installation.repository_root / "graphify-out" / "graph.json"
        if not graph_path.is_file():
            return 0, []
        
        query_res = provider.query(goal, graph_path, token_budget=2000)
        if not query_res or not query_res.paths:
            return 0, []
        
        files = list(query_res.paths)
        tokens = calculate_context_size(installation.repository_root, tuple(files))
        return tokens, files
    except Exception:
        return 0, []


def _baseline_b5_hybrid_lexical_graph(installation: Installation, goal: str) -> tuple[int, list[str]]:
    """B5: Hybrid lexical + Graphify whole-file retrieval.
    
    Combines basic search (B1) with Graphify whole-file (B3).
    Does NOT approximate a full coding agent - just hybrid retrieval.
    """
    b1_tokens, b1_files = _baseline_b1_basic_search(installation, goal)
    b3_tokens, b3_files = _baseline_b3_graphify_whole_files(installation, goal)
    
    combined_files = list(dict.fromkeys(b1_files + b3_files))
    tokens = calculate_context_size(installation.repository_root, tuple(combined_files))
    return tokens, combined_files


def _compute_baseline_metrics(installation: Installation, goal: str, gold_files: set[str], 
                              baseline_files: list[str]) -> dict[str, float]:
    """Compute recall metrics for a baseline."""
    if not baseline_files:
        return {"recall": 0.0, "precision": 0.0, "f1": 0.0, "tokens": 0}
    
    baseline_set = set(baseline_files)
    tp = len(baseline_set.intersection(gold_files))
    fp = len(baseline_set - gold_files)
    fn = len(gold_files - baseline_set)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    tokens = calculate_context_size(installation.repository_root, tuple(baseline_files))
    
    return {"precision": precision, "recall": recall, "f1": f1, "tokens": tokens}


class RoutingBenchmarkResult:
    def __init__(
        self,
        task_id: str,
        precision: float,
        recall: float,
        f1: float,
        precision_at_5: float,
        precision_at_10: float,
        recall_at_5: float,
        recall_at_10: float,
        mrr: float,
        symbol_recall: float,
        test_recall: float,
        payload_context_efficiency: float,
        total_context_efficiency: float,
        token_reduction: float,
        baselines: dict[str, dict[str, float]] | None = None
    ):
        self.task_id = task_id
        self.precision = precision
        self.recall = recall
        self.f1 = f1
        self.precision_at_5 = precision_at_5
        self.precision_at_10 = precision_at_10
        self.recall_at_5 = recall_at_5
        self.recall_at_10 = recall_at_10
        self.mrr = mrr
        self.symbol_recall = symbol_recall
        self.test_recall = test_recall
        self.payload_context_efficiency = payload_context_efficiency
        self.total_context_efficiency = total_context_efficiency
        self.token_reduction = token_reduction
        self.baselines = baselines or {}

    def to_dict(self) -> dict[str, Any]:
        result = {
            "task_id": self.task_id,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "precision_at_5": self.precision_at_5,
            "precision_at_10": self.precision_at_10,
            "recall_at_5": self.recall_at_5,
            "recall_at_10": self.recall_at_10,
            "mrr": self.mrr,
            "symbol_recall": self.symbol_recall,
            "test_recall": self.test_recall,
            "payload_context_efficiency": self.payload_context_efficiency,
            "total_context_efficiency": self.total_context_efficiency,
            "token_reduction": self.token_reduction
        }
        if self.baselines:
            result["baselines"] = self.baselines
        return result


def run_routing_benchmark_suite(
    installation: Installation,
    gold_task: dict[str, Any],
    manifest: ActiveContextManifest,
    candidates_list: list[dict[str, Any]]
) -> RoutingBenchmarkResult:
    """Evaluate context routing against a gold-standard task definition."""
    gold_expected = gold_task.get("expected", {})
    gold_files = set(gold_expected.get("files", []))
    gold_symbols = set(gold_expected.get("symbols", []))
    gold_tests = set(gold_expected.get("tests", []))
    
    # 1. Deterministic file list (admitted files preserve manifest order)
    routed_files_ordered = [f.path for f in manifest.files]
    routed_files_set = set(routed_files_ordered)
    
    tp = len(routed_files_set.intersection(gold_files))
    fp = len(routed_files_set - gold_files)
    fn = len(gold_files - routed_files_set)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    # Routed symbols
    routed_symbols = set()
    for f in manifest.files:
        if f.selection.get("mode") == "symbols":
            for sym in f.selection.get("symbols", []):
                name = getattr(sym, "name", None) or (sym.get("name") if isinstance(sym, dict) else None)
                if name:
                    routed_symbols.add(f"{f.path}::{name}")
                
    symbol_recall = len(routed_symbols.intersection(gold_symbols)) / len(gold_symbols) if gold_symbols else 0.0
    
    # Routed tests
    routed_tests = {f.path for f in manifest.files if f.role == "test"} | set(manifest.tests or ())
    test_recall = len(routed_tests.intersection(gold_tests)) / len(gold_tests) if gold_tests else 0.0

    # 2. Build Ranked Retrieve List
    sorted_candidates = sorted(candidates_list, key=lambda x: -x.get("score", 0))
    ranked_list = routed_files_ordered + [cand["path"] for cand in sorted_candidates if cand["path"] not in routed_files_set]

    # 3. Precision@K and Recall@K
    def calc_metrics_at_k(k: int) -> tuple[float, float]:
        retrieved_at_k = set(ranked_list[:k])
        tp_k = len(retrieved_at_k.intersection(gold_files))
        prec_k = tp_k / k if k > 0 else 0.0
        rec_k = tp_k / len(gold_files) if len(gold_files) > 0 else 0.0
        return prec_k, rec_k

    precision_at_5, recall_at_5 = calc_metrics_at_k(5)
    precision_at_10, recall_at_10 = calc_metrics_at_k(10)

    # 4. Mean Reciprocal Rank (MRR)
    mrr = 0.0
    for idx, path in enumerate(ranked_list):
        if path in gold_files:
            mrr = 1.0 / (idx + 1)
            break

    # 5. Token Breakdown & Efficiencies
    breakdown = calculate_manifest_tokens(installation, manifest)
    payload_tokens = breakdown.source_tokens + breakdown.rule_tokens + breakdown.reference_tokens
    
    # Gold-relevant manifest definition
    gold_relevant_files = [f for f in manifest.files if f.path in gold_files]
    gold_relevant_rules = [r for r in manifest.rules if r.path in gold_files]
    gold_relevant_refs = [ref for ref in manifest.references if ref.path in gold_files]
    
    gold_manifest = ActiveContextManifest(
        task_id=manifest.task_id, task_contract_hash=manifest.task_contract_hash,
        git_revision=manifest.git_revision, files=tuple(gold_relevant_files),
        rules=tuple(gold_relevant_rules), references=tuple(gold_relevant_refs),
        events=(), budget=None, policy=manifest.policy,
        goal=manifest.goal, category=manifest.category
    )
    gold_breakdown = calculate_manifest_tokens(installation, gold_manifest)
    gold_relevant_payload = gold_breakdown.source_tokens + gold_breakdown.rule_tokens + gold_breakdown.reference_tokens
    
    payload_context_efficiency = gold_relevant_payload / payload_tokens if payload_tokens > 0 else 0.0
    total_context_efficiency = gold_relevant_payload / breakdown.used if breakdown.used > 0 else 0.0

    goal = gold_task.get("goal", manifest.goal)
    
    # Compute all baselines
    baselines = {}
    
    # B0: Whole repository
    b0_tokens, b0_files = _baseline_b0_whole_repo(installation)
    baselines["B0_whole_repo"] = _compute_baseline_metrics(installation, goal, gold_files, b0_files)
    
    # B1: Basic search (filename + content keywords)
    b1_tokens, b1_files = _baseline_b1_basic_search(installation, goal)
    baselines["B1_basic_search"] = _compute_baseline_metrics(installation, goal, gold_files, b1_files)
    
    # B2: Lexical SACAS fallback
    b2_tokens, b2_files = _baseline_b2_lexical_fallback(installation, goal)
    baselines["B2_lexical_fallback"] = _compute_baseline_metrics(installation, goal, gold_files, b2_files)
    
    # B3: Graphify whole files
    b3_tokens, b3_files = _baseline_b3_graphify_whole_files(installation, goal)
    baselines["B3_graphify_whole"] = _compute_baseline_metrics(installation, goal, gold_files, b3_files)
    
    # B4: SACAS Graphify routing (current) - this is the main result
    baselines["B4_sacas_graphify"] = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tokens": breakdown.used
    }
    
    # B5: Hybrid lexical + Graphify whole-file retrieval
    b5_tokens, b5_files = _baseline_b5_hybrid_lexical_graph(installation, goal)
    baselines["B5_hybrid_lexical_graph"] = _compute_baseline_metrics(installation, goal, gold_files, b5_files)
    
    # Token reduction vs B0 (whole repo)
    token_reduction = 1.0 - (breakdown.used / b0_tokens) if b0_tokens > 0 else 0.0

    return RoutingBenchmarkResult(
        task_id=gold_task.get("id", manifest.task_id),
        precision=precision,
        recall=recall,
        f1=f1,
        precision_at_5=precision_at_5,
        precision_at_10=precision_at_10,
        recall_at_5=recall_at_5,
        recall_at_10=recall_at_10,
        mrr=mrr,
        symbol_recall=symbol_recall,
        test_recall=test_recall,
        payload_context_efficiency=payload_context_efficiency,
        total_context_efficiency=total_context_efficiency,
        token_reduction=token_reduction,
        baselines=baselines
    )


def load_and_run_all_benchmarks(installation: Installation) -> list[RoutingBenchmarkResult]:
    """Load benchmark specifications, run isolated routing, and evaluate them."""
    results = []
    benchmark_dir = installation.sacas_root / "benchmarks"
    if not benchmark_dir.is_dir():
        return results

    for path in benchmark_dir.glob("*.json"):
        try:
            gold_task = json.loads(path.read_text(encoding="utf-8"))
            
            # Isolated routing engine execution
            manifest = route_goal(
                installation=installation,
                goal=gold_task.get("goal", ""),
                category=gold_task.get("category"),
                files=tuple(gold_task.get("files", ())),
                symbols=tuple(gold_task.get("symbols", ())),
                tests=tuple(gold_task.get("tests", ())),
                rules=tuple(gold_task.get("rules", ())),
                references=tuple(gold_task.get("references", ()))
            )
            
            # Isolated candidate generation
            candidates_list = generate_candidates_for_manifest(installation, manifest)
            
            res = run_routing_benchmark_suite(installation, gold_task, manifest, candidates_list)
            results.append(res)
        except Exception as exc:
            raise RuntimeError(f"Benchmark {path.name} failed: {exc}") from exc
    return results
