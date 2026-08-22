"""Benchmark SACAS routing quality metrics for the active task."""

from __future__ import annotations

import json
from typing import Any
from sacas import __version__
from sacas.graphify import GraphifyAdapter
from sacas.paths import Installation
from sacas.tasks import get_git_commit


def run_benchmark(installation: Installation) -> dict[str, Any]:
    """Calculate actual routing quality metrics for the active task."""
    task_id = installation.manifest.current_task_id
    if not task_id:
        return {"active_task": False}

    from sacas.active_context import load_task_state
    from sacas.task_contract import CanonicalStateError
    task_dir = installation.sacas_root / "tasks" / "current"
    try:
        manifest, _contract = load_task_state(task_dir)
    except CanonicalStateError as error:
        return {
            "active_task": False,
            "error": f"Canonical task state is corrupt: {error}",
        }
    if not manifest:
        return {"active_task": False}

    initial_scope = [f for f in manifest.files if f.trigger == "initial_route"]
    expansions = [f for f in manifest.files if f.trigger != "initial_route"]

    initial_count = len(initial_scope)
    expansion_count = len(expansions)
    total_count = len(manifest.files)
    
    # Read adjacent count from candidates.json
    adjacent_count = 0
    candidates_path = task_dir / "candidates.json"
    if candidates_path.is_file():
        try:
            candidates_data = json.loads(candidates_path.read_text(encoding="utf-8"))
            adjacent_count = len(candidates_data.get("candidates", []))
        except Exception:
            pass

    expansion_ratio = (expansion_count / initial_count) if initial_count > 0 else 0.0

    from sacas.budget import calculate_manifest_tokens
    breakdown = calculate_manifest_tokens(installation, manifest)
    total_size = breakdown.used

    return {
        "active_task": True,
        "task_id": task_id,
        "goal": manifest.goal,
        "metadata": {
            "sacas_version": __version__,
            "graphify_version": GraphifyAdapter.get_installed_version() or "N/A",
            "repository_commit": get_git_commit(installation.repository_root),
        },
        "metrics": {
            "initial_files_count": initial_count,
            "final_files_count": total_count,
            "expansion_events_count": expansion_count,
            "expansion_ratio": expansion_ratio,
            "budget_rejected_count": adjacent_count,
            "total_context_tokens": total_size,
            "context_budget": installation.manifest.context_budget,
        }
    }


def print_benchmark(installation: Installation, format_type: str = "text") -> int:
    """Print actual task benchmark metrics."""
    report = run_benchmark(installation)
    if format_type == "json":
        print(json.dumps(report, indent=2))
        return 1 if report.get("error") else 0

    if not report.get("active_task"):
        if report.get("error"):
            print(report["error"])
            return 1
        print("No active task found to benchmark routing quality.")
        return 0

    print("SACAS Routing Quality Benchmark")
    print("===============================")
    print(f"Task ID:          {report['task_id']}")
    print(f"Goal:             {report['goal']}")
    print(f"Commit:           {report['metadata']['repository_commit']}")
    print(f"SACAS Version:    {report['metadata']['sacas_version']}")
    print(f"Graphify Version: {report['metadata']['graphify_version']}")
    
    metrics = report["metrics"]
    print("\nMetrics:")
    print(f"  Initial Scope Files: {metrics['initial_files_count']}")
    print(f"  Expanded Files:      {metrics['final_files_count']}")
    print(f"  Expansion Events:    {metrics['expansion_events_count']}")
    print(f"  Expansion Ratio:     {metrics['expansion_ratio'] * 100:.1f}%")
    print(f"  Budget Excluded:     {metrics['budget_rejected_count']}")
    print(f"  Total Context Size:  {metrics['total_context_tokens']} / {metrics['context_budget']} tokens")
    return 0
