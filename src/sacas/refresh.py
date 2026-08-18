"""Refresh task context, detect stale files, and progressively expand scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sacas.graphify import read_graphify_manifest
from sacas.io import stable_json, write_text_atomic
from sacas.map import impact_records
from sacas.paths import Installation
from sacas.tasks import (
    is_file_protected,
    parse_protected_boundaries,
    regenerate_task_markdown,
)


def refresh_context(
    installation: Installation,
    selective_files: tuple[str, ...] = ()
) -> bool:
    """Refresh active task file hashes and progressively expand context based on Graphify evidence."""
    task_id = installation.manifest.current_task_id
    if not task_id:
        raise ValueError("No active SACAS task to refresh.")

    task_dir = installation.sacas_root / "tasks" / "current"
    expansions_path = task_dir / "expansions.json"
    if not expansions_path.is_file():
        raise ValueError("Active task metadata (expansions.json) is missing.")

    try:
        expansions = json.loads(expansions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Active task metadata (expansions.json) is unreadable.") from error

    initial_files = expansions.get("initial_files", {})
    expanded_files = expansions.get("expanded_files", {})

    changed = False

    # 1. Update hashes for initial and expanded files
    for filepath in list(initial_files.keys()):
        if selective_files and filepath not in selective_files:
            continue
        file_path = installation.repository_root / filepath
        curr_hash = ""
        if file_path.is_file():
            try:
                curr_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except OSError:
                pass
        if initial_files.get(filepath) != curr_hash:
            initial_files[filepath] = curr_hash
            changed = True

    for filepath in list(expanded_files.keys()):
        if selective_files and filepath not in selective_files:
            continue
        file_path = installation.repository_root / filepath
        curr_hash = ""
        if file_path.is_file():
            try:
                curr_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except OSError:
                pass
        if expanded_files.get(filepath) != curr_hash:
            expanded_files[filepath] = curr_hash
            changed = True

    # 2. Scope expansion (only if NOT doing a selective files refresh)
    if not selective_files:
        graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
        evidence = None
        if graphify_manifest_path.is_file():
            try:
                evidence = read_graphify_manifest(graphify_manifest_path)
            except Exception:
                pass

        if evidence is not None:
            # Read boundaries
            boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
            parsed_boundaries = parse_protected_boundaries(boundaries_file)

            # Look up candidates to expand
            candidates: set[str] = set()
            for filepath in list(initial_files.keys()) + list(expanded_files.keys()):
                records = impact_records(evidence, filepath)
                for record in records:
                    candidates.add(record.path)

            for cand in sorted(candidates):
                if cand in initial_files or cand in expanded_files:
                    continue
                # Refuse if protected
                reason = is_file_protected(cand, parsed_boundaries)
                if reason:
                    # Protected-boundary refusal: skip adding this candidate
                    continue

                # Add to expanded files
                cand_path = installation.repository_root / cand
                cand_hash = ""
                if cand_path.is_file():
                    try:
                        cand_hash = hashlib.sha256(cand_path.read_bytes()).hexdigest()
                    except OSError:
                        pass
                expanded_files[cand] = cand_hash
                changed = True

    # Write expansions.json if updated
    if changed:
        expansions["initial_files"] = initial_files
        expansions["expanded_files"] = expanded_files
        write_text_atomic(expansions_path, stable_json(expansions))

    # Always regenerate markdown documents to ensure they are up to date and correct
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        task_id=task_id,
        goal=expansions.get("goal", ""),
        criteria=tuple(expansions.get("criteria", ())),
        constraints=tuple(expansions.get("constraints", ())),
        verification=tuple(expansions.get("verification", ())),
        initial_files=tuple(initial_files.keys()),
        expanded_files=tuple(expanded_files.keys()),
        symbols=tuple(expansions.get("symbols", ())),
        tests=tuple(expansions.get("tests", ())),
        rules=tuple(expansions.get("rules", ())),
    )

    return changed
