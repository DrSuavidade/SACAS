"""Migrate legacy PowerShell SACAS structures to Python CLI structures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from sacas.init import initialize
from sacas.io import write_text_atomic
from sacas.paths import discover_manifest


def migrate_repository(root: Path, apply: bool = False) -> dict[str, Any]:
    """Preview or apply migration from legacy PowerShell structure to Python structure."""
    root = root.resolve()
    actions = []

    # 1. Manifest / Init check
    installation = discover_manifest(root)
    if installation is None:
        actions.append("Initialize SACAS structure and manifest.json")
        if apply:
            initialize(root)
            installation = discover_manifest(root)

    sacas_root = installation.sacas_root if installation else root / "Structure"
    task_dir = sacas_root / "tasks" / "current"
    legacy_progress = task_dir / "PROGRESS.md"

    if legacy_progress.is_file():
        actions.append("Migrate legacy progress state from PROGRESS.md to the canonical task contract")
        actions.append("Delete legacy PROGRESS.md")

        if apply:
            content = legacy_progress.read_text(encoding="utf-8")

            # Parse checkboxes and comments
            criteria_items: list[str] = []
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith("- [x]") or line_stripped.startswith("- [ ]"):
                    criteria_items.append(line_stripped[5:].strip())

            goal = "Migrated legacy task"
            task_id = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:8]

            # Update manifest current_task_id
            if installation:
                manifest_path = installation.manifest_path
                manifest_data = installation.manifest.to_dict()
                manifest_data["current_task_id"] = task_id
                write_text_atomic(manifest_path, json.dumps(manifest_data, indent=2) + "\n")

            from sacas.task_contract import TaskContract, save_task_contract, task_contract_hash
            from sacas.active_context import ActiveContextManifest, save_active_context
            contract = TaskContract(
                schema_version=1,
                task_id=task_id,
                goal=goal,
                category="bugfix",
                criteria=tuple(criteria_items),
                constraints=(),
                verification=()
            )
            save_task_contract(task_dir, contract)
            h = task_contract_hash(contract)

            manifest = ActiveContextManifest(
                task_id=task_id,
                task_contract_hash=h,
                git_revision="unknown",
                files=(),
                rules=(),
                references=(),
                events=(),
                budget=None,
                policy=None,
                goal=goal,
                category="bugfix"
            )
            save_active_context(task_dir, manifest)

            # Remove legacy progress
            legacy_progress.unlink()

    return {
        "apply": apply,
        "actions": actions
    }


def perform_migration(root: Path, apply: bool = False, format_type: str = "text") -> int:
    """Execute migration preview or apply, outputting results in text or JSON."""
    result = migrate_repository(root, apply=apply)
    if format_type == "json":
        print(json.dumps(result, indent=2))
    else:
        if apply:
            print("Migration completed successfully.")
            for act in result["actions"]:
                print(f"  - Applied: {act}")
        else:
            print("Migration Preview (Dry-run):")
            if result["actions"]:
                for act in result["actions"]:
                    print(f"  - Would do: {act}")
                print("\nRun with --apply to execute these changes.")
            else:
                print("No migration actions required.")
    return 0
