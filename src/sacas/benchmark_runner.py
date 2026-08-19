from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sacas.active_context import ActiveContextManifest
from sacas.paths import Installation
from sacas.budget import calculate_context_size

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
        context_efficiency: float,
        token_reduction: float
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
        self.context_efficiency = context_efficiency
        self.token_reduction = token_reduction

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "precision_at_5": self.precision_at_5,
            "precision_at_10": self.precision_at_10,
            "recall_at_5": self.recall_at_5,
            "recall_at_10": self.recall_at_10,
            "mrr": self.mrr,
            "context_efficiency": self.context_efficiency,
            "token_reduction": self.token_reduction
        }


def run_routing_benchmark_suite(
    installation: Installation,
    gold_task: dict[str, Any],
    manifest: ActiveContextManifest,
    candidates_list: list[dict[str, Any]]
) -> RoutingBenchmarkResult:
    """Evaluate context routing against a gold-standard task definition."""
    gold_expected = gold_task.get("expected", {})
    gold_files = set(gold_expected.get("files", []))
    
    # 1. Basic Precision/Recall on Admitted Files
    routed_files = {f.path for f in manifest.files}
    tp = len(routed_files.intersection(gold_files))
    fp = len(routed_files - gold_files)
    fn = len(gold_files - routed_files)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    # 2. Build Ranked Retrieve List
    # Admitted files first, followed by sorted candidates
    sorted_candidates = sorted(candidates_list, key=lambda x: -x.get("score", 0))
    ranked_list = list(routed_files) + [cand["path"] for cand in sorted_candidates if cand["path"] not in routed_files]

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

    # 5. Token Efficiency & Token Reduction vs Baseline
    # Get total repository token size
    ignored_parts = {".git", ".sacas", "__pycache__", "Structure", "graphify-out", ".worktrees"}
    repo_files = []
    for path in installation.repository_root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(installation.repository_root)
            if not any(part in ignored_parts for part in relative.parts):
                repo_files.append(relative.as_posix())
                
    baseline_tokens = calculate_context_size(installation.repository_root, tuple(repo_files))
    
    # Admitted tokens
    admitted_paths = tuple(f.path for f in manifest.files)
    admitted_tokens = calculate_context_size(installation.repository_root, admitted_paths)
    
    # Gold-relevant retrieved tokens
    gold_relevant_retrieved = tuple(f for f in admitted_paths if f in gold_files)
    gold_relevant_tokens = calculate_context_size(installation.repository_root, gold_relevant_retrieved)
    
    context_efficiency = gold_relevant_tokens / admitted_tokens if admitted_tokens > 0 else 0.0
    token_reduction = 1.0 - (admitted_tokens / baseline_tokens) if baseline_tokens > 0 else 0.0

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
        context_efficiency=context_efficiency,
        token_reduction=token_reduction
    )


def load_and_run_all_benchmarks(installation: Installation) -> list[RoutingBenchmarkResult]:
    """Load benchmark specifications and evaluate them."""
    results = []
    benchmark_dir = installation.sacas_root / "benchmarks"
    if not benchmark_dir.is_dir():
        return results

    from sacas.active_context import load_active_context
    task_dir = installation.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    if not manifest:
        return results

    # Load candidates
    candidates_list = []
    candidates_path = task_dir / "candidates.json"
    if candidates_path.is_file():
        try:
            candidates_list = json.loads(candidates_path.read_text(encoding="utf-8")).get("candidates", [])
        except Exception:
            pass

    for path in benchmark_dir.glob("*.json"):
        try:
            gold_task = json.loads(path.read_text(encoding="utf-8"))
            res = run_routing_benchmark_suite(installation, gold_task, manifest, candidates_list)
            results.append(res)
        except Exception:
            pass
    return results
