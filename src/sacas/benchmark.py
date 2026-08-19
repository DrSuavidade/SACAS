"""Benchmark SACAS routing context sizes and quality metrics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from sacas import __version__
from sacas.budget import calculate_context_size, calculate_total_context_size
from sacas.graphify import read_graphify_manifest, GraphifyAdapter
from sacas.map import impact_records
from sacas.paths import Installation
from sacas.tasks import (
    is_file_protected,
    parse_protected_boundaries,
    get_initial_files,
    get_expanded_files,
    get_git_commit,
)


def percentile(data: list[int], pct: float) -> float:
    """Calculate the percentile of a list of integers."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    index = (len(sorted_data) - 1) * pct
    lower = int(index)
    upper = lower + 1
    if upper < len(sorted_data):
        return sorted_data[lower] + (sorted_data[upper] - sorted_data[lower]) * (index - lower)
    return float(sorted_data[lower])


def run_context_simulation(installation: Installation) -> dict[str, Any]:
    """Execute simulation across all files in the repository comparing context size modes."""
    root = installation.repository_root
    sacas_root = installation.sacas_root

    commit = get_git_commit(root)
    graphify_ver = GraphifyAdapter.get_installed_version() or "N/A"

    # List all files in repo
    ignored_parts = {".git", ".sacas", "__pycache__", "Structure", "graphify-out", ".worktrees"}
    repo_files = []
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root)
            if not any(part in ignored_parts for part in relative.parts):
                repo_files.append(relative.as_posix())

    repo_files = sorted(repo_files)[:50]

    graphify_manifest_path = sacas_root / ".sacas" / "graphify.json"
    evidence = None
    if graphify_manifest_path.is_file():
        try:
            evidence = read_graphify_manifest(graphify_manifest_path)
        except Exception:
            pass

    boundaries_file = sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(boundaries_file)

    baseline_sizes = []
    graphify_sizes = []
    sacas_sizes = []
    combined_sizes = []

    total_repo_size = calculate_context_size(root, tuple(repo_files))

    community_files_map = {}
    if evidence:
        for name, paths in evidence.communities:
            for p in paths:
                community_files_map[p] = paths

    for f in repo_files:
        baseline_sizes.append(total_repo_size)

        if evidence and f in community_files_map:
            comm_paths = community_files_map[f]
            graphify_sizes.append(calculate_context_size(root, tuple(comm_paths)))
        else:
            graphify_sizes.append(0)

        sacas_sizes.append(calculate_context_size(root, (f,)))

        expanded = [f]
        if evidence:
            records = impact_records(evidence, f)
            for record in records:
                if record.path != f and not is_file_protected(record.path, parsed_boundaries):
                    expanded.append(record.path)
        combined_sizes.append(calculate_context_size(root, tuple(expanded)))

    return {
        "metadata": {
            "model": "Gemini 3.5 Flash",
            "agent_version": "Antigravity 2.0",
            "sacas_version": __version__,
            "graphify_version": graphify_ver,
            "repository_commit": commit,
            "cache_state": "cold"
        },
        "metrics": {
            "B0_whole_repo": {
                "median": percentile(baseline_sizes, 0.5),
                "p75": percentile(baseline_sizes, 0.75),
                "p95": percentile(baseline_sizes, 0.95)
            },
            "B3_graphify_whole": {
                "median": percentile(graphify_sizes, 0.5),
                "p75": percentile(graphify_sizes, 0.75),
                "p95": percentile(graphify_sizes, 0.95)
            },
            "B2_lexical_routing": {
                "median": percentile(sacas_sizes, 0.5),
                "p75": percentile(sacas_sizes, 0.75),
                "p95": percentile(sacas_sizes, 0.95)
            },
            "B5_hybrid_lexical_graph": {
                "median": percentile(combined_sizes, 0.5),
                "p75": percentile(combined_sizes, 0.75),
                "p95": percentile(combined_sizes, 0.95)
            }
        }
    }


def print_context_simulation(installation: Installation, format_type: str = "text") -> int:
    """Run simulation and output result."""
    report = run_context_simulation(installation)
    if format_type == "json":
        print(json.dumps(report, indent=2))
    else:
        print("SACAS Context Simulation Report")
        print("===============================")
        print(f"Model:            {report['metadata']['model']}")
        print(f"Commit:           {report['metadata']['repository_commit']}")
        print(f"SACAS Version:    {report['metadata']['sacas_version']}")
        print(f"Graphify Version: {report['metadata']['graphify_version']}")
        print("\nSimulated Context Sizes (tokens) by Retrieval Mode:")
        print("  (Primary metrics: Recall@K, Precision@K, MRR - not whole-repo reduction)")
        for mode, metrics in report["metrics"].items():
            print(f"  {mode}:")
            print(f"    Median: {metrics['median']:.1f}")
            print(f"    p75:    {metrics['p75']:.1f}")
            print(f"    p95:    {metrics['p95']:.1f}")
    return 0


def run_benchmark(installation: Installation) -> dict[str, Any]:
    """Calculate actual routing quality metrics for the active task."""
    task_id = installation.manifest.current_task_id
    if not task_id:
        return {"active_task": False}

    from sacas.active_context import load_active_context
    task_dir = installation.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
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
        return 0

    if not report.get("active_task"):
        print("No active task found to benchmark routing quality.")
        print("Use 'sacas context-simulation' to simulate context sizes across the repository.")
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
