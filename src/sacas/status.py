"""Concise task and context status reporting."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from sacas.budget import calculate_context_size
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

    for f in manifest.files:
        if f.trigger == "initial_route":
            initial_files.append(f.path)
        else:
            expanded_files.append(f.path)

        f_path = installation.repository_root / f.path
        if f_path.is_file():
            try:
                curr_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                if curr_hash != f.hash:
                    stale_files.append(f.path)
            except OSError:
                stale_files.append(f.path)
        else:
            stale_files.append(f.path)

    status = "stale" if stale_files else "fresh"
    from sacas.budget import calculate_manifest_tokens, estimate_tokens
    breakdown_obj = calculate_manifest_tokens(installation, manifest)
    
    def f_tokens(path: Path) -> int:
        if path.is_file():
            try:
                return estimate_tokens(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
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

    print(f"Task ID: {report['current_task_id']}")
    print(f"Status:  {report['status'].upper()}")
    bd = report["breakdown"]
    print(f"Router ~{bd['router']} Task ~{bd['task']} Context ~{bd['context']} Rules ~{bd['rules']} References ~{bd['references']} Source ~{bd['source']}")
    print("────────────────────────")
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
