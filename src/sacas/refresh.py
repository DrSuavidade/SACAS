"""Refresh task context, detect stale files, and suggest candidate expansions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from sacas.graphify import read_graphify_manifest
from sacas.io import stable_json, write_text_atomic
from sacas.paths import Installation
from sacas.tasks import (
    is_file_protected,
    parse_protected_boundaries,
    regenerate_task_markdown,
)
from sacas.active_context import load_active_context, load_task_state, save_active_context, ActiveFileContext

def refresh_context(
    installation: Installation,
    selective_files: tuple[str, ...] = ()
) -> bool:
    """Refresh active task file hashes and generate disposable candidates.json suggestions."""
    task_id = installation.manifest.current_task_id
    if not task_id:
        raise ValueError("No active SACAS task to refresh.")

    task_dir = installation.sacas_root / "tasks" / "current"
    manifest, contract = load_task_state(task_dir)
    if manifest is None:
        raise ValueError("Active task metadata (active_context.json) is missing or unreadable.")

    changed = False
    updated_files = []
    changed_file_paths = set()

    # 1. Update hashes of existing files and detect changes
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
                ranking_score=f.ranking_score,
                confidence=f.confidence,
                evidence=f.evidence,
                relation=f.relation,
                trigger=f.trigger,
                git_revision=f.git_revision,
                reason=f.reason,
                hash=curr_hash,
                role=f.role
            ))
            changed = True
            changed_file_paths.add(f.path)
        else:
            updated_files.append(f)

    # Reconstruct manifest with updated file hashes
    from dataclasses import replace
    manifest = replace(manifest, files=tuple(updated_files))
    save_active_context(task_dir, manifest)

    # 2. If files changed, perform incremental invalidation and re-routing
    if changed_file_paths:
        manifest = _incremental_re_route(installation, manifest, changed_file_paths, task_dir)
        changed = True

    # 3. Scope expansion analysis to output candidates.json (only if NOT selective refresh)
    if not selective_files:
        candidates_list = generate_candidates_for_manifest(installation, manifest)
        candidates_data = {
            "task_id": manifest.task_id,
            "candidates": candidates_list
        }
        write_text_atomic(task_dir / "candidates.json", stable_json(candidates_data))

    # 4. Always regenerate markdown documents
    manifest, contract = load_task_state(task_dir)
    if manifest is None:
        raise ValueError("Active task metadata (active_context.json) is missing or unreadable.")
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        manifest=manifest,
        contract=contract,
    )

    return changed


def _incremental_re_route(
    installation: Installation,
    manifest: ActiveContextManifest,
    changed_file_paths: set[str],
    task_dir: Path
) -> ActiveContextManifest:
    """Re-route only selectors affected by changed files.
    
    Uses admission event triggered_by chains to find downstream dependencies.
    """
    from sacas.tasks import route_goal
    
    # Find admission events for changed files
    affected_event_ids = set()
    for event in manifest.events:
        if event.target in changed_file_paths:
            affected_event_ids.add(event.id)
    
    # Traverse triggered_by chain to find all downstream events
    all_affected = set(affected_event_ids)
    to_process = list(affected_event_ids)
    
    while to_process:
        current_id = to_process.pop()
        # Find events that were triggered by this event
        for event in manifest.events:
            if event.triggered_by == current_id and event.id not in all_affected:
                all_affected.add(event.id)
                to_process.append(event.id)
    
    # Find all files affected by these events
    affected_file_paths = set()
    for event in manifest.events:
        if event.id in all_affected:
            affected_file_paths.add(event.target)
    
    # Keep unaffected files as-is
    unaffected_files = [f for f in manifest.files if f.path not in affected_file_paths]
    
    # For affected files, we need to re-route them
    # Use the original task goal to re-route all affected files
    affected_files = [f for f in manifest.files if f.path in affected_file_paths]
    
    if not affected_files:
        return manifest
    
    # Extract ALL affected file paths and symbols for re-routing
    re_route_files = []
    re_route_symbols = []
    for f in affected_files:
        re_route_files.append(f.path)
        if f.selection.get("mode") == "symbols":
            for sym in f.selection.get("symbols", []):
                name = getattr(sym, "name", None) or (sym.get("name") if isinstance(sym, dict) else None)
                if name:
                    re_route_symbols.append(f"{f.path}::{name}")
    
    # Re-route with the same goal and affected files
    # This will re-run Graphify/heuristic routing for them
    new_manifest = route_goal(
        installation=installation,
        goal=manifest.goal,
        category=manifest.category,
        files=tuple(re_route_files),
        symbols=tuple(re_route_symbols),
        tests=tuple(manifest.tests),
        rules=tuple(r.path for r in manifest.rules),
        references=tuple(ref.path for ref in manifest.references),
        context_policy="advisory",
        task_contract_hash=manifest.task_contract_hash
    )
    
    # Merge: keep unaffected files, replace affected with newly routed
    final_files = list(unaffected_files) + list(new_manifest.files)
    
    # Deduplicate by path (keep highest ranking_score)
    file_map = {}
    for f in final_files:
        if f.path not in file_map or f.ranking_score > file_map[f.path].ranking_score:
            file_map[f.path] = f
    
    merged_files = list(file_map.values())
    
    # Merge events: keep unaffected events, add new ones
    unaffected_events = [e for e in manifest.events if e.target not in affected_file_paths]
    merged_events = unaffected_events + list(new_manifest.events)
    
    merged_manifest = replace(
        manifest,
        files=tuple(merged_files),
        events=tuple(merged_events),
        budget=None,  # will be recalculated
        policy=None   # will be recalculated
    )
    
    save_active_context(task_dir, merged_manifest)
    return merged_manifest


def generate_candidates_for_manifest(
    installation: Installation,
    manifest: ActiveContextManifest
) -> list[dict[str, Any]]:
    """Generate candidates from the active manifest.
    
    DESIGN BOUNDARY: External Graphify access goes through GraphifyProvider,
    while persisted SACAS-normalized graph evidence is read from the internal
    SACAS graphify.json manifest snapshot directly.
    """
    from sacas.budget import calculate_context_size, compile_budget_report
    from sacas.refresh import read_graphify_manifest, parse_protected_boundaries, is_file_protected
    
    budget_plan = compile_budget_report(installation, manifest)
    
    graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
    evidence = None
    if graphify_manifest_path.is_file():
        try:
            evidence = read_graphify_manifest(graphify_manifest_path)
        except Exception:
            pass

    active_paths = {f.path for f in manifest.files}
    candidates_list = []

    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(boundaries_file)

    RELATION_DIRECTION_WEIGHTS = {
        "bugfix": {
            "calls": {"incoming": 100, "outgoing": 85},
            "tests": {"incoming": 100, "outgoing": 90},
            "imports": {"incoming": 95, "outgoing": 80},
            "depends_on": {"incoming": 85, "outgoing": 85},
        },
        "feature": {
            "calls": {"incoming": 70, "outgoing": 100},
            "tests": {"incoming": 80, "outgoing": 95},
            "imports": {"incoming": 65, "outgoing": 95},
            "depends_on": {"incoming": 80, "outgoing": 85},
        },
        "test": {
            "calls": {"incoming": 80, "outgoing": 80},
            "tests": {"incoming": 100, "outgoing": 100},
            "imports": {"incoming": 80, "outgoing": 80},
            "depends_on": {"incoming": 70, "outgoing": 70},
        },
        "refactor": {
            "calls": {"incoming": 90, "outgoing": 90},
            "tests": {"incoming": 80, "outgoing": 80},
            "imports": {"incoming": 90, "outgoing": 90},
            "depends_on": {"incoming": 80, "outgoing": 80},
        },
        "docs": {
            "calls": {"incoming": 30, "outgoing": 30},
            "tests": {"incoming": 30, "outgoing": 30},
            "imports": {"incoming": 30, "outgoing": 30},
            "depends_on": {"incoming": 40, "outgoing": 40},
        },
        "documentation": {
            "calls": {"incoming": 30, "outgoing": 30},
            "tests": {"incoming": 30, "outgoing": 30},
            "imports": {"incoming": 30, "outgoing": 30},
            "depends_on": {"incoming": 40, "outgoing": 40},
        },
        "security": {
            "calls": {"incoming": 100, "outgoing": 90},
            "tests": {"incoming": 95, "outgoing": 95},
            "imports": {"incoming": 95, "outgoing": 95},
            "depends_on": {"incoming": 90, "outgoing": 90},
        },
        "architecture": {
            "calls": {"incoming": 85, "outgoing": 85},
            "tests": {"incoming": 70, "outgoing": 70},
            "imports": {"incoming": 90, "outgoing": 90},
            "depends_on": {"incoming": 85, "outgoing": 85},
        },
        "investigate": {
            "calls": {"incoming": 80, "outgoing": 80},
            "tests": {"incoming": 70, "outgoing": 70},
            "imports": {"incoming": 85, "outgoing": 85},
            "depends_on": {"incoming": 80, "outgoing": 80},
        },
    }

    if evidence is not None:
        node_paths = dict(evidence.nodes)
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
                direction = "incoming"
            elif is_source_active and dest_path not in active_paths:
                cand_path = dest_path
                trigger_path = source_path
                direction = "outgoing"
            else:
                continue

            if is_file_protected(cand_path, parsed_boundaries):
                continue

            cat = manifest.category or "investigate"
            cat_weights = RELATION_DIRECTION_WEIGHTS.get(cat, RELATION_DIRECTION_WEIGHTS["investigate"])
            rel_weights = cat_weights.get(edge_kind, {"incoming": 85, "outgoing": 85})
            score = rel_weights.get(direction, 85)

            semantic_direction = "related"
            if edge_kind == "calls":
                semantic_direction = "caller" if direction == "incoming" else "callee"
            elif edge_kind == "imports":
                semantic_direction = "importer" if direction == "incoming" else "imported"
            elif edge_kind == "tests":
                semantic_direction = "test" if direction == "incoming" else "test_target"

            confidence = 1.0
            final_score = score * confidence
            if cand_path not in candidate_details or final_score > candidate_details[cand_path]["score"]:
                candidate_details[cand_path] = {
                    "score": final_score,
                    "relation": edge_kind,
                    "direction": direction,
                    "semantic_direction": semantic_direction,
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
                                "direction": "outgoing",
                                "semantic_direction": "community_member",
                                "triggered_by": trigger_path,
                                "confidence": confidence,
                            }

        remaining_space = budget_plan.remaining
        sorted_cands = sorted(candidate_details.items(), key=lambda x: (-x[1]["score"], x[0]))
        for cand_path, details in sorted_cands:
            cand_cost = calculate_context_size(installation.repository_root, (cand_path,))
            if cand_cost > remaining_space:
                continue
            remaining_space -= cand_cost
            trigger_rel = "seed"
            for f in manifest.files:
                if f.path == details['triggered_by']:
                    trigger_rel = f.relation or "seed"
                    break
            reason_str = f"{details['triggered_by']} ({trigger_rel}) -> {details['relation']} ({details['semantic_direction']}) -> {cand_path}"
            candidates_list.append({
                "path": cand_path,
                "score": details["score"],
                "reason": reason_str,
                "source": "graphify",
                "confidence": "high" if details["confidence"] >= 0.9 else "medium",
                "relation": details["relation"],
                "direction": details["direction"],
                "semantic_direction": details["semantic_direction"],
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
        remaining_space = budget_plan.remaining
        for score, filepath, matched in raw_cands:
            if filepath in active_paths:
                continue
            if is_file_protected(filepath, parsed_boundaries):
                continue
            cand_cost = calculate_context_size(installation.repository_root, (filepath,))
            if cand_cost > remaining_space:
                continue
            remaining_space -= cand_cost
            candidates_list.append({
                "path": filepath,
                "score": float(score),
                "reason": f"Fallback lexical match (score={score}) matching: {', '.join(matched)}",
                "source": "heuristic",
                "confidence": "high" if score >= 8 else "medium",
                "relation": "keyword_match",
                "estimated_tokens": cand_cost
            })
            
    return candidates_list
