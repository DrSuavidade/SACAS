"""Benchmark SACAS routing context sizes and quality metrics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from sacas import __version__
from sacas.budget import calculate_context_size
from sacas.graphify import read_graphify_manifest
from sacas.map import impact_records
from sacas.paths import Installation
from sacas.tasks import is_file_protected, parse_protected_boundaries


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


def get_git_commit(root: Path) -> str:
    """Get the current repository git commit hash."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False
        )
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout.strip()
    except OSError:
        pass
    return "unknown"


def run_benchmark(installation: Installation) -> dict[str, Any]:
    """Execute benchmark across all files in the repository comparing context size modes."""
    root = installation.repository_root
    sacas_root = installation.sacas_root

    # Get git commit
    commit = get_git_commit(root)

    # List all files in repo (excluding .git, etc.)
    ignored_parts = {".git", ".sacas", "__pycache__", "Structure", "graphify-out", ".worktrees"}
    repo_files = []
    for path in root.rglob("*"):
        if path.is_file():
            relative = path.relative_to(root)
            if not any(part in ignored_parts for part in relative.parts):
                repo_files.append(relative.as_posix())

    # Sort and cap for speed
    repo_files = sorted(repo_files)[:50]

    # Load Graphify evidence
    graphify_manifest_path = sacas_root / ".sacas" / "graphify.json"
    evidence = None
    if graphify_manifest_path.is_file():
        try:
            evidence = read_graphify_manifest(graphify_manifest_path)
        except Exception:
            pass

    # Read boundaries
    boundaries_file = sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(boundaries_file)

    baseline_sizes = []
    graphify_sizes = []
    sacas_sizes = []
    combined_sizes = []

    # Total repo size
    total_repo_size = calculate_context_size(root, tuple(repo_files))

    # Graphify community mappings
    community_files_map = {}
    if evidence:
        for name, paths in evidence.communities:
            for p in paths:
                community_files_map[p] = paths

    for f in repo_files:
        # Baseline: everything
        baseline_sizes.append(total_repo_size)

        # Graphify-only: community size
        if evidence and f in community_files_map:
            comm_paths = community_files_map[f]
            graphify_sizes.append(calculate_context_size(root, tuple(comm_paths)))
        else:
            graphify_sizes.append(0)

        # SACAS-only: just target file
        sacas_sizes.append(calculate_context_size(root, (f,)))

        # SACAS+Graphify: target file + expanded dependencies (respecting boundaries)
        expanded = [f]
        if evidence:
            records = impact_records(evidence, f)
            for record in records:
                if record.path != f and not is_file_protected(record.path, parsed_boundaries):
                    expanded.append(record.path)
        combined_sizes.append(calculate_context_size(root, tuple(expanded)))

    report = {
        "metadata": {
            "model": "Gemini 3.5 Flash",
            "agent_version": "Antigravity 2.0",
            "sacas_version": __version__,
            "graphify_version": "1.0.0" if evidence else "N/A",
            "repository_commit": commit,
            "cache_state": "cold"
        },
        "metrics": {
            "Baseline": {
                "median": percentile(baseline_sizes, 0.5),
                "p75": percentile(baseline_sizes, 0.75),
                "p95": percentile(baseline_sizes, 0.95)
            },
            "Graphify-only": {
                "median": percentile(graphify_sizes, 0.5),
                "p75": percentile(graphify_sizes, 0.75),
                "p95": percentile(graphify_sizes, 0.95)
            },
            "SACAS-only": {
                "median": percentile(sacas_sizes, 0.5),
                "p75": percentile(sacas_sizes, 0.75),
                "p95": percentile(sacas_sizes, 0.95)
            },
            "SACAS+Graphify": {
                "median": percentile(combined_sizes, 0.5),
                "p75": percentile(combined_sizes, 0.75),
                "p95": percentile(combined_sizes, 0.95)
            }
        }
    }
    return report


def print_benchmark(installation: Installation, format_type: str = "text") -> int:
    """Run benchmark and output the report."""
    report = run_benchmark(installation)
    if format_type == "json":
        print(json.dumps(report, indent=2))
    else:
        print("SACAS Benchmark Report")
        print("======================")
        print(f"Model:            {report['metadata']['model']}")
        print(f"Commit:           {report['metadata']['repository_commit']}")
        print(f"SACAS Version:    {report['metadata']['sacas_version']}")
        print("\nContext Sizes (tokens) by Mode:")
        for mode, metrics in report["metrics"].items():
            print(f"  {mode}:")
            print(f"    Median: {metrics['median']:.1f}")
            print(f"    p75:    {metrics['p75']:.1f}")
            print(f"    p95:    {metrics['p95']:.1f}")
    return 0
