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
    expansions_path = task_dir / "expansions.json"
    
    stale_files: list[str] = []
    initial_files: list[str] = []
    expanded_files: list[str] = []
    
    if expansions_path.is_file():
        try:
            data = json.loads(expansions_path.read_text(encoding="utf-8"))
            initials = data.get("initial_files", {})
            expanded = data.get("expanded_files", {})
            
            if isinstance(initials, dict):
                for f, recorded_hash in initials.items():
                    initial_files.append(f)
                    f_path = installation.repository_root / f
                    if f_path.is_file():
                        try:
                            curr_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                            if curr_hash != recorded_hash:
                                stale_files.append(f)
                        except OSError:
                            stale_files.append(f)
                    else:
                        stale_files.append(f)
            elif isinstance(initials, (list, tuple)):
                initial_files = list(initials)
                
            if isinstance(expanded, dict):
                for f, recorded_hash in expanded.items():
                    expanded_files.append(f)
                    f_path = installation.repository_root / f
                    if f_path.is_file():
                        try:
                            curr_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                            if curr_hash != recorded_hash:
                                stale_files.append(f)
                        except OSError:
                            stale_files.append(f)
                    else:
                        stale_files.append(f)
            elif isinstance(expanded, (list, tuple)):
                expanded_files = list(expanded)
        except Exception:
            pass

    status = "stale" if stale_files else "fresh"
    all_files = tuple(initial_files + expanded_files)
    estimated_size = calculate_context_size(installation.repository_root, all_files)
    
    return {
        "current_task_id": task_id,
        "status": status,
        "stale_files": stale_files,
        "initial_files": initial_files,
        "expanded_files": expanded_files,
        "context_budget": installation.manifest.context_budget,
        "estimated_size": estimated_size
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
    print(f"Budget:  {report['estimated_size']} / {report['context_budget']} tokens")
    
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
