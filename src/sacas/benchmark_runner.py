from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sacas.active_context import ActiveContextManifest

class RoutingBenchmarkResult:
    def __init__(self, task_id: str, precision: float, recall: float, f1: float, token_usage: int):
        self.task_id = task_id
        self.precision = precision
        self.recall = recall
        self.f1 = f1
        self.token_usage = token_usage

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "token_usage": self.token_usage
        }

def run_routing_benchmark(gold_standard_files: set[str], manifest: ActiveContextManifest, token_usage: int) -> RoutingBenchmarkResult:
    """Calculate precision, recall, F1, and token metrics against a gold standard set of files."""
    routed_files = {f.path for f in manifest.files}
    
    tp = len(routed_files.intersection(gold_standard_files))
    fp = len(routed_files - gold_standard_files)
    fn = len(gold_standard_files - routed_files)
    
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return RoutingBenchmarkResult(
        task_id=manifest.task_id,
        precision=precision,
        recall=recall,
        f1=f1,
        token_usage=token_usage
    )
