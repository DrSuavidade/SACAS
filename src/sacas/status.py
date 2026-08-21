"""Concise task and context status reporting."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from sacas.budget import calculate_context_size
from sacas.io import read_repo_source_bytes, read_repo_text
from sacas.paths import Installation


def get_status_report(installation: Installation) -> dict[str, Any]:
    """Calculate the status, staleness, and budget consumption for the active task."""
    task_id = installation.manifest.current_task_id
    if not task_id:
        return {
            "current_task_id": None,
            "status": "no_active_task",
            "stale_files": [],
            "initial_files": [],
            "expanded_files": [],
            "context_budget": installation.manifest.context_budget,
            "estimated_size": 0
        }

    task_dir = installation.sacas_root / "tasks" / "current"
    from sacas.active_context import load_active_context
    manifest = load_active_context(task_dir)
    if not manifest:
        return {
            "current_task_id": task_id,
            "status": "no_active_task",
            "stale_files": [],
            "initial_files": [],
            "expanded_files": [],
            "context_budget": installation.manifest.context_budget,
            "estimated_size": 0
        }

    stale_files: list[str] = []
    initial_files: list[str] = []
    expanded_files: list[str] = []

    canonical_artifacts = [
        (f.path, f.hash, f.trigger == "initial_route")
        for f in manifest.all_files
    ]
    canonical_artifacts.extend((rule.path, rule.hash, False) for rule in manifest.rules)
    canonical_artifacts.extend((reference.path, reference.hash, False) for reference in manifest.references)

    for path, expected_hash, is_initial in canonical_artifacts:
        if is_initial:
            initial_files.append(path)
        else:
            expanded_files.append(path)

        try:
                curr_hash = hashlib.sha256(read_repo_source_bytes(installation.repository_root, path)).hexdigest()
                if curr_hash != expected_hash:
                    stale_files.append(path)
        except (ValueError, FileNotFoundError, OSError):
            stale_files.append(path)

    # A changed canonical input is useful, actionable status.  Only validate
    # the cached projection when the canonical state itself is current.
    if not stale_files:
        try:
            from sacas.compiler import load_validated_context_pack
            load_validated_context_pack(installation)
        except (OSError, ValueError):
            return {
                "current_task_id": task_id,
                "status": "invalid_context_pack",
                "stale_files": [],
                "initial_files": [],
                "expanded_files": [],
                "context_budget": installation.manifest.context_budget,
                "estimated_size": 0,
            }

    status = "stale" if stale_files else "fresh"
    from sacas.budget import calculate_manifest_tokens, estimate_tokens
    breakdown_obj = calculate_manifest_tokens(installation, manifest)
    
    def f_tokens(path: Path) -> int:
        try:
            return estimate_tokens(read_repo_text(path.parent, path.name, allow_ignored=True))
        except (ValueError, FileNotFoundError, OSError):
            pass
        return 0

    breakdown = {
        "router": f_tokens(installation.sacas_root / "ROUTER.md"),
        "task": f_tokens(task_dir / "TASK.md"),
        "context": f_tokens(task_dir / "CONTEXT.md"),
        "state": f_tokens(task_dir / "STATE.md"),
        "rules": breakdown_obj.rule_tokens,
        "references": breakdown_obj.reference_tokens,
        "source": breakdown_obj.source_tokens,
        "total": breakdown_obj.used
    }
    estimated_size = breakdown_obj.used

    return {
        "current_task_id": task_id,
        "status": status,
        "stale_files": stale_files,
        "initial_files": initial_files,
        "expanded_files": expanded_files,
        "context_budget": installation.manifest.context_budget,
        "estimated_size": estimated_size,
        "breakdown": breakdown
    }


def print_status_report(installation: Installation, format_type: str = "text") -> None:
    """Print the task and context status report in text or JSON format."""
    report = get_status_report(installation)
    if format_type == "json":
        print(json.dumps(report, indent=2))
        return

    if report["status"] == "no_active_task":
        print("No active SACAS task.")
        return

    if report["status"] == "invalid_context_pack":
        print("Task context pack is invalid or stale; run `sacas refresh`.")
        return

    print(f"Task ID: {report['current_task_id']}")
    print(f"Status:  {report['status'].upper()}")
    bd = report["breakdown"]
    print(f"Router ~{bd['router']} Task ~{bd['task']} Context ~{bd['context']} Rules ~{bd['rules']} References ~{bd['references']} Source ~{bd['source']}")
    print("------------------------")
    print(f"Estimated total ~{bd['total']}")
    print(f"Budget {report['context_budget']}")
    
    if report["stale_files"]:
        print("\nStale files:")
        for f in report["stale_files"]:
            print(f"  - {f}")
            
    if report["initial_files"]:
        print("\nInitial focus files:")
        for f in report["initial_files"]:
            print(f"  - {f}")
            
    if report["expanded_files"]:
        print("\nExpanded files:")
        for f in report["expanded_files"]:
            print(f"  - {f}")
