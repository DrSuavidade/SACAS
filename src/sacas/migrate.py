"""Migrate legacy PowerShell SACAS structures to Python CLI structures."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from sacas.init import initialize
from sacas.io import write_text_atomic
from sacas.paths import discover_manifest
from sacas.regions import render_generated_region
from sacas.state import generate_pickup_markdown, parse_state_checkboxes, render_state_markdown


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
    legacy_progress = sacas_root / "tasks" / "current" / "PROGRESS.md"
    new_state = sacas_root / "tasks" / "current" / "STATE.md"
    new_pickup = sacas_root / "tasks" / "current" / "PICKUP.md"
    new_active_context = sacas_root / "tasks" / "current" / "active_context.json"

    if legacy_progress.is_file():
        actions.append(f"Migrate legacy progress state from PROGRESS.md to STATE.md")
        actions.append(f"Delete legacy PROGRESS.md")
        
        if apply:
            content = legacy_progress.read_text(encoding="utf-8")
            
            # Parse checkboxes and comments
            criteria_items = []
            completed_items = set()
            comments_lines = []
            
            for line in content.splitlines():
                line_stripped = line.strip()
                if line_stripped.startswith("- [x]") or line_stripped.startswith("- [ ]"):
                    item_text = line_stripped[5:].strip()
                    criteria_items.append(item_text)
                    if line_stripped.startswith("- [x]"):
                        completed_items.add(item_text)
                elif not line_stripped.startswith("#") and not line_stripped.startswith("##") and line_stripped:
                    comments_lines.append(line)
                    
            comments = "\n".join(comments_lines) + "\n" if comments_lines else ""
            
            goal = "Migrated legacy task"
            task_id = hashlib.sha256(goal.encode("utf-8")).hexdigest()[:8]
            
            # Update manifest current_task_id
            if installation:
                manifest_path = installation.manifest_path
                manifest_data = installation.manifest.to_dict()
                manifest_data["current_task_id"] = task_id
                write_text_atomic(manifest_path, json.dumps(manifest_data, indent=2) + "\n")
            
            # Write STATE.md with completed items preserved
            state_lines = [
                f"Task: {task_id}",
                f"Goal: {goal}",
                "",
                "## Checklist",
            ]
            for item in criteria_items:
                status = "[x]" if item in completed_items else "[ ]"
                state_lines.append(f"- {status} {item} (Acceptance Criteria)")
                
            state_text = "\n".join(state_lines) + "\n"
            state_content = f"# Task State\n\n" + render_generated_region("task-state", state_text) + "\n" + comments
            
            new_state.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomic(new_state, state_content)
            
            # Generate active_context.json
            from sacas.active_context import ActiveContextManifest, save_active_context
            manifest = ActiveContextManifest(
                task_id=task_id,
                goal=goal,
                category="bugfix",
                git_revision="unknown",
                files=(),
                rules=(),
                references=(),
                events=(),
                budget=None,
                policy=None
            )
            save_active_context(sacas_root / "tasks" / "current", manifest)
            
            # Generate PICKUP.md
            completed, pending = parse_state_checkboxes(state_text)
            pickup_content = generate_pickup_markdown(completed, pending)
            write_text_atomic(new_pickup, pickup_content)
            
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
