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
    import datetime
    from sacas.tasks import get_initial_files, get_expanded_files, get_git_commit
    from sacas.budget import calculate_context_size, calculate_total_context_size

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

    # Dynamic schema migration to v2
    if expansions.get("schema_version") != 2:
        initial_scope = []
        for k, v in expansions.get("initial_files", {}).items():
            initial_scope.append({
                "path": k,
                "hash": v,
                "symbols": [],
                "reason": "Legacy task migration",
                "source": "legacy",
                "confidence": "high",
                "relation": None,
                "trigger": "migration",
                "git_revision": "unknown"
            })
        expansions_list = []
        for i, (k, v) in enumerate(expansions.get("expanded_files", {}).items()):
            expansions_list.append({
                "id": f"exp-{i:03d}",
                "path": k,
                "hash": v,
                "reason": "Legacy task migration",
                "source": "legacy",
                "confidence": "high",
                "relation": None,
                "triggered_by": "migration",
                "git_revision": "unknown",
                "added_at": "unknown"
            })
        expansions["schema_version"] = 2
        expansions["initial_scope"] = initial_scope
        expansions["expansions"] = expansions_list
        expansions["adjacent"] = []
        if "initial_files" in expansions:
            del expansions["initial_files"]
        if "expanded_files" in expansions:
            del expansions["expanded_files"]

    changed = False

    # 1. Update hashes for initial and expanded files
    for item in expansions.get("initial_scope", []):
        filepath = item["path"]
        if selective_files and filepath not in selective_files:
            continue
        file_path = installation.repository_root / filepath
        curr_hash = ""
        if file_path.is_file():
            try:
                curr_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except OSError:
                pass
        if item.get("hash") != curr_hash:
            item["hash"] = curr_hash
            changed = True

    for item in expansions.get("expansions", []):
        filepath = item["path"]
        if selective_files and filepath not in selective_files:
            continue
        file_path = installation.repository_root / filepath
        curr_hash = ""
        if file_path.is_file():
            try:
                curr_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except OSError:
                pass
        if item.get("hash") != curr_hash:
            item["hash"] = curr_hash
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

            active_initial = get_initial_files(expansions)
            active_expanded = get_expanded_files(expansions)
            active_paths = set(active_initial.keys()) | set(active_expanded.keys())

            # Identify candidates from graph edges
            candidate_details: dict[str, dict] = {}
            node_paths = dict(evidence.nodes)

            # Map edge kind to score
            edge_kind_scores = {
                "calls": 100,
                "imports": 100,
                "tests": 90,
                "depends_on": 85,
            }

            # Direct graph edges checking
            for source_id, destination_id, edge_kind in evidence.edges:
                source_path = node_paths.get(source_id)
                dest_path = node_paths.get(destination_id)
                if not source_path or not dest_path:
                    continue

                is_dest_active = dest_path in active_paths
                is_source_active = source_path in active_paths

                if is_dest_active and source_path not in active_paths:
                    cand_path = source_path
                    trigger_path = dest_path
                    score = edge_kind_scores.get(edge_kind, 25)
                    confidence = 1.0  # EXTRACTED
                    relation = edge_kind
                elif is_source_active and dest_path not in active_paths:
                    cand_path = dest_path
                    trigger_path = source_path
                    score = edge_kind_scores.get(edge_kind, 25)
                    confidence = 1.0  # EXTRACTED
                    relation = edge_kind
                else:
                    continue

                # Check protected
                if is_file_protected(cand_path, parsed_boundaries):
                    continue

                final_score = score * confidence
                if cand_path not in candidate_details or final_score > candidate_details[cand_path]["score"]:
                    candidate_details[cand_path] = {
                        "score": final_score,
                        "relation": relation,
                        "triggered_by": trigger_path,
                        "confidence": confidence,
                    }

            # Check community sharing for remaining files
            for comm_name, comm_paths in evidence.communities:
                active_in_comm = [p for p in comm_paths if p in active_paths]
                if active_in_comm:
                    trigger_path = active_in_comm[0]
                    for p in comm_paths:
                        if p not in active_paths:
                            if is_file_protected(p, parsed_boundaries):
                                continue
                            score = 40
                            confidence = 0.5  # heuristic
                            final_score = score * confidence
                            if p not in candidate_details or final_score > candidate_details[p]["score"]:
                                candidate_details[p] = {
                                    "score": final_score,
                                    "relation": "community",
                                    "triggered_by": trigger_path,
                                    "confidence": confidence,
                                }

            # Sort candidate paths by score desc, then path alphabetically
            sorted_cands = sorted(candidate_details.items(), key=lambda x: (-x[1]["score"], x[0]))

            # Predictive budgeting
            budget = installation.manifest.context_budget
            current_cost = calculate_total_context_size(installation, tuple(active_paths))
            commit = get_git_commit(installation.repository_root)
            timestamp = datetime.datetime.now().isoformat() + "Z"

            new_expansions = list(expansions.get("expansions", []))
            new_adjacent = []

            for rank, (cand_path, details) in enumerate(sorted_cands, 1):
                cand_cost = calculate_context_size(installation.repository_root, (cand_path,))

                # Resolve hash
                try:
                    cand_hash = hashlib.sha256((installation.repository_root / cand_path).read_bytes()).hexdigest()
                except OSError:
                    cand_hash = ""

                if current_cost + cand_cost <= budget:
                    new_expansions.append({
                        "id": f"exp-{len(new_expansions) + 1:03d}",
                        "path": cand_path,
                        "reason": f"Graph relation '{details['relation']}' triggered by {details['triggered_by']}",
                        "source": "graphify",
                        "confidence": "high" if details["confidence"] >= 0.9 else "medium",
                        "relation": details["relation"],
                        "triggered_by": details["triggered_by"],
                        "git_revision": commit,
                        "added_at": timestamp,
                        "hash": cand_hash
                    })
                    current_cost += cand_cost
                    changed = True
                else:
                    new_adjacent.append({
                        "path": cand_path,
                        "reason": f"Graph relation '{details['relation']}' triggered by {details['triggered_by']}",
                        "source": "graphify",
                        "confidence": "high" if details["confidence"] >= 0.9 else "medium",
                        "relation": details["relation"],
                        "rank": rank,
                        "estimated_tokens": cand_cost,
                        "excluded_reason": "budget"
                    })

            expansions["expansions"] = new_expansions
            expansions["adjacent"] = new_adjacent

    # Write expansions.json if updated
    if changed or expansions.get("schema_version") != 2:
        write_text_atomic(expansions_path, stable_json(expansions))

    # Always regenerate markdown documents to ensure they are up to date and correct
    initial_files = tuple(item["path"] for item in expansions.get("initial_scope", []))
    expanded_files = tuple(item["path"] for item in expansions.get("expansions", []))

    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        task_id=task_id,
        goal=expansions.get("goal", ""),
        criteria=tuple(expansions.get("criteria", ())),
        constraints=tuple(expansions.get("constraints", ())),
        verification=tuple(expansions.get("verification", ())),
        initial_files=initial_files,
        expanded_files=expanded_files,
        symbols=tuple(expansions.get("symbols", ())),
        tests=tuple(expansions.get("tests", ())),
        rules=tuple(expansions.get("rules", ())),
    )

    return changed
