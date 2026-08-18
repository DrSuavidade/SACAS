"""Refresh task context, detect stale files, and suggest candidate expansions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from sacas.graphify import read_graphify_manifest
from sacas.io import stable_json, write_text_atomic
from sacas.paths import Installation
from sacas.tasks import (
    is_file_protected,
    parse_protected_boundaries,
    regenerate_task_markdown,
)
from sacas.active_context import load_active_context, save_active_context, ActiveFileContext

def refresh_context(
    installation: Installation,
    selective_files: tuple[str, ...] = ()
) -> bool:
    """Refresh active task file hashes and generate disposable candidates.json suggestions."""
    task_id = installation.manifest.current_task_id
    if not task_id:
        raise ValueError("No active SACAS task to refresh.")

    task_dir = installation.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    if manifest is None:
        raise ValueError("Active task metadata (active_context.json) is missing or unreadable.")

    changed = False
    updated_files = []

    # 1. Update hashes of existing files
    for f in manifest.files:
        filepath = f.path
        if selective_files and filepath not in selective_files:
            updated_files.append(f)
            continue
            
        file_path = installation.repository_root / filepath
        curr_hash = ""
        if file_path.is_file():
            try:
                curr_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
            except OSError:
                pass
                
        if f.hash != curr_hash:
            updated_files.append(ActiveFileContext(
                path=f.path,
                selection=f.selection,
                source=f.source,
                confidence=f.confidence,
                relation=f.relation,
                trigger=f.trigger,
                git_revision=f.git_revision,
                reason=f.reason,
                hash=curr_hash
            ))
            changed = True
        else:
            updated_files.append(f)

    # Reconstruct manifest with updated file hashes
    from sacas.active_context import ActiveContextManifest
    manifest = ActiveContextManifest(
        task_id=manifest.task_id,
        goal=manifest.goal,
        category=manifest.category,
        git_revision=manifest.git_revision,
        files=tuple(updated_files),
        rules=manifest.rules,
        references=manifest.references,
        events=manifest.events,
        budget=manifest.budget,
        policy=manifest.policy,
        tests=manifest.tests,
        schema_version=manifest.schema_version
    )
    save_active_context(task_dir, manifest)

    # 2. Scope expansion analysis to output candidates.json (only if NOT selective refresh)
    if not selective_files:
        from sacas.budget import calculate_context_size
        
        graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
        evidence = None
        if graphify_manifest_path.is_file():
            try:
                evidence = read_graphify_manifest(graphify_manifest_path)
            except Exception:
                pass

        active_paths = {f.path for f in manifest.files}
        candidates_list = []

        # Read boundaries
        boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
        parsed_boundaries = parse_protected_boundaries(boundaries_file)

        if evidence is not None:
            node_paths = dict(evidence.nodes)
            edge_kind_scores = {
                "calls": 100,
                "imports": 100,
                "tests": 90,
                "depends_on": 85,
            }

            candidate_details = {}
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
                    confidence = 1.0
                    relation = edge_kind
                elif is_source_active and dest_path not in active_paths:
                    cand_path = dest_path
                    trigger_path = source_path
                    score = edge_kind_scores.get(edge_kind, 25)
                    confidence = 1.0
                    relation = edge_kind
                else:
                    continue

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

            # Community check
            for comm_name, comm_paths in evidence.communities:
                active_in_comm = [p for p in comm_paths if p in active_paths]
                if active_in_comm:
                    trigger_path = active_in_comm[0]
                    for p in comm_paths:
                        if p not in active_paths:
                            if is_file_protected(p, parsed_boundaries):
                                continue
                            score = 40
                            confidence = 0.5
                            final_score = score * confidence
                            if p not in candidate_details or final_score > candidate_details[p]["score"]:
                                candidate_details[p] = {
                                    "score": final_score,
                                    "relation": "community",
                                    "triggered_by": trigger_path,
                                    "confidence": confidence,
                                }

            sorted_cands = sorted(candidate_details.items(), key=lambda x: (-x[1]["score"], x[0]))
            for cand_path, details in sorted_cands:
                cand_cost = calculate_context_size(installation.repository_root, (cand_path,))
                candidates_list.append({
                    "path": cand_path,
                    "score": details["score"],
                    "reason": f"Graph relation '{details['relation']}' triggered by {details['triggered_by']}",
                    "source": "graphify",
                    "confidence": "high" if details["confidence"] >= 0.9 else "medium",
                    "relation": details["relation"],
                    "triggered_by": details["triggered_by"],
                    "estimated_tokens": cand_cost
                })
        else:
            # Fallback search ranking
            from sacas.search import FallbackIndex
            index = FallbackIndex(installation.repository_root, installation.sacas_root)
            index.update()
            
            # search using keywords in goal
            raw_cands = index.search(manifest.goal)
            for score, filepath, matched in raw_cands:
                if filepath in active_paths:
                    continue
                if is_file_protected(filepath, parsed_boundaries):
                    continue
                cand_cost = calculate_context_size(installation.repository_root, (filepath,))
                candidates_list.append({
                    "path": filepath,
                    "score": float(score),
                    "reason": f"Fallback lexical match (score={score}) matching: {', '.join(matched)}",
                    "source": "heuristic",
                    "confidence": "high" if score >= 8 else "medium",
                    "relation": "keyword_match",
                    "estimated_tokens": cand_cost
                })

        # Save disposable candidates.json
        candidates_data = {
            "task_id": manifest.task_id,
            "candidates": candidates_list
        }
        write_text_atomic(task_dir / "candidates.json", stable_json(candidates_data))

    # 3. Always regenerate markdown documents
    # First reload manifest to ensure we get any budget/hash changes
    manifest = load_active_context(task_dir)
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        manifest=manifest,
        criteria=tuple(installation.manifest.to_dict().get("criteria", ())), # Wait, we don't have criteria stored in manifest, tasks can read checklist or STATE.md
    )

    return changed
