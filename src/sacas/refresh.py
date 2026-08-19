"""Refresh task context, detect stale files, and suggest candidate expansions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from sacas.graphify import read_graphify_manifest
from sacas.io import stable_json, write_text_atomic, read_repo_bytes
from sacas.paths import Installation
from sacas.tasks import (
    is_file_protected,
    parse_protected_boundaries,
    regenerate_task_markdown,
)
from sacas.active_context import load_active_context, load_task_state, save_active_context, ActiveFileContext


def _compute_graph_snapshot_hash(installation: Installation) -> str:
    """Compute hash of graphify.json snapshot."""
    graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
    if not graphify_manifest_path.is_file():
        return ""
    try:
        content = graphify_manifest_path.read_bytes()
        return hashlib.sha256(content).hexdigest()
    except OSError:
        return ""


def _compute_source_hashes(installation: Installation, file_paths: tuple[str, ...]) -> dict[str, str]:
    """Compute content hashes for a set of source files."""
    hashes = {}
    for path in file_paths:
        try:
            content_bytes = read_repo_bytes(installation.repository_root, path)
            hashes[path] = hashlib.sha256(content_bytes).hexdigest()
        except (ValueError, FileNotFoundError, OSError):
            hashes[path] = ""
    return hashes


def _is_task_changed(manifest: ActiveContextManifest, task_dir: Path) -> bool:
    """Check if task contract has changed by comparing with current task.json on disk."""
    from sacas.task_contract import load_task_contract, task_contract_hash
    current_contract = load_task_contract(task_dir)
    if current_contract is None:
        return False
    current_hash = task_contract_hash(current_contract)
    return manifest.task_contract_hash != current_hash


def _is_graph_changed(manifest: ActiveContextManifest, current_graph_hash: str) -> bool:
    """Check if graph snapshot has changed."""
    # If manifest has no graph hash, it wasn't using graphify
    if not manifest.graph_snapshot_hash:
        return False
    # If current graph hash is empty, graphify.json was removed
    if not current_graph_hash:
        return True
    return manifest.graph_snapshot_hash != current_graph_hash


def _get_stale_files(
    installation: Installation,
    manifest: ActiveContextManifest
) -> tuple[set[str], set[str], set[str]]:
    """
    Determine which files are stale based on three fingerprints.
    
    Returns:
        (source_changed, graph_derived_stale, task_dependent)
    """
    source_changed = set()
    graph_derived_stale = set()
    task_dependent = set()
    
    current_graph_hash = _compute_graph_snapshot_hash(installation)
    
    # Check each file in manifest
    for f in manifest.all_files:
        # Compute current source hash
        try:
            content_bytes = read_repo_bytes(installation.repository_root, f.path)
            curr_hash = hashlib.sha256(content_bytes).hexdigest()
        except (ValueError, FileNotFoundError, OSError):
            curr_hash = ""
        
        if f.hash != curr_hash:
            source_changed.add(f.path)
        
        # Check if graph-derived and graph changed
        if f.source == "graphify" and _is_graph_changed(manifest, current_graph_hash):
            graph_derived_stale.add(f.path)
        
        # Check if task-dependent (ranking/admission may change if task changed)
        # We'll handle task change at the manifest level
        pass
    
    return source_changed, graph_derived_stale, task_dependent


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
    source_changed = set()

    # 1. Update hashes of existing files and detect changes
    for f in manifest.files:
        filepath = f.path
        if selective_files and filepath not in selective_files:
            updated_files.append(f)
            continue
            
        try:
            content_bytes = read_repo_bytes(installation.repository_root, filepath)
            curr_hash = hashlib.sha256(content_bytes).hexdigest()
        except (ValueError, FileNotFoundError, OSError):
            curr_hash = ""
            
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
            source_changed.add(f.path)
        else:
            updated_files.append(f)

    # Reconstruct manifest with updated file hashes
    manifest = replace(manifest, files=tuple(updated_files))
    save_active_context(task_dir, manifest)

    # 2. Check for invalidation triggers
    current_graph_hash = _compute_graph_snapshot_hash(installation)
    graph_changed = _is_graph_changed(manifest, current_graph_hash)
    task_changed = _is_task_changed(manifest, task_dir)

    # Determine what needs re-routing
    needs_reroute = False
    reroute_files = set()
    reroute_symbols = set()
    
    if source_changed or graph_changed:
        needs_reroute = True
        
        # Files with source changes need re-resolution
        for f in manifest.files:
            if f.path in source_changed:
                reroute_files.add(f.path)
                if f.selection.get("mode") == "symbols":
                    for sym in f.selection.get("symbols", []):
                        name = getattr(sym, "name", None) or (sym.get("name") if isinstance(sym, dict) else None)
                        if name:
                            reroute_symbols.add(f"{f.path}::{name}")
        
        # Graph-derived files need re-discovery if graph changed
        if graph_changed:
            # Clear graph-derived files so they get re-discovered by Graphify
            # We don't add them to reroute_files - instead we let the full re-route logic handle it
            # But since it's not a task change, we need special handling
            # Mark that we need graph rediscovery
            pass
    
    # 3. If task contract changed, full re-route needed
    if task_changed:
        needs_reroute = True
        # Full re-route: re-run discovery from task goal
        reroute_files = set()
        reroute_symbols = set()
        # Clear graph-derived files so they get re-discovered
        # Explicit files will be re-routed with the new goal
    
    # 4. If graph changed, need graph rediscovery
    if graph_changed:
        needs_reroute = True
        # Graph rediscovery: re-run Graphify discovery from task goal
        # Preserve explicit files, re-discover graph-derived ones
        reroute_files = set()
        reroute_symbols = set()
    
    # 5. Perform re-routing if needed
    if needs_reroute:
        # Determine if this is full re-route (task) or graph rediscovery
        full_reroute = task_changed
        graph_rediscovery = graph_changed and not task_changed
        manifest = _re_route_files(
            installation, manifest, reroute_files, reroute_symbols, task_dir,
            full_reroute=full_reroute,
            graph_rediscovery=graph_rediscovery
        )
        changed = True
        # Update graph snapshot hash after re-routing
        manifest = replace(manifest, graph_snapshot_hash=current_graph_hash)
        save_active_context(task_dir, manifest)

    # 5. Scope expansion analysis to output candidates.json (only if NOT selective refresh)
    if not selective_files:
        candidates_list = generate_candidates_for_manifest(installation, manifest)
        candidates_data = {
            "task_id": manifest.task_id,
            "candidates": candidates_list
        }
        write_text_atomic(task_dir / "candidates.json", stable_json(candidates_data))

    # 6. Always regenerate markdown documents
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


def _re_route_files(
    installation: Installation,
    manifest: ActiveContextManifest,
    reroute_files: set[str],
    reroute_symbols: set[str],
    task_dir: Path,
    full_reroute: bool = False,
    graph_rediscovery: bool = False
) -> ActiveContextManifest:
    """Re-route specified files/symbols or do full re-route if full_reroute=True."""
    from sacas.tasks import route_goal
    
    if full_reroute:
        # Full re-route: run discovery from scratch with the task goal
        # Preserve explicit rules/references/tests but re-discover source files
        explicit_rules = tuple(r.path for r in manifest.rules)
        explicit_refs = tuple(ref.path for ref in manifest.references)
        explicit_tests = tuple(manifest.tests)
        
        new_manifest = route_goal(
            installation=installation,
            goal=manifest.goal,
            category=manifest.category,
            files=(),
            symbols=(),
            tests=explicit_tests,
            rules=explicit_rules,
            references=explicit_refs,
            context_policy="advisory",
            task_contract_hash=manifest.task_contract_hash
        )
        
        # Preserve explicit files (they were manually admitted)
        explicit_files = [f for f in manifest.files if f.source == "explicit"]
        
        final_files = list(explicit_files) + list(new_manifest.files)
        
    elif graph_rediscovery:
        # Graph rediscovery: re-run Graphify discovery from task goal
        # Preserve explicit files and rules/references/tests
        # Clear graph-derived source files so they get re-discovered
        explicit_files = [f for f in manifest.files if f.source == "explicit"]
        explicit_rules = tuple(r.path for r in manifest.rules)
        explicit_refs = tuple(ref.path for ref in manifest.references)
        explicit_tests = tuple(manifest.tests)
        
        new_manifest = route_goal(
            installation=installation,
            goal=manifest.goal,
            category=manifest.category,
            files=(),
            symbols=(),
            tests=explicit_tests,
            rules=explicit_rules,
            references=explicit_refs,
            context_policy="advisory",
            task_contract_hash=manifest.task_contract_hash
        )
        
        final_files = list(explicit_files) + list(new_manifest.files)
        
    else:
        if not reroute_files:
            return manifest
        
        # Partial re-route: re-route only specified files/symbols
        new_manifest = route_goal(
            installation=installation,
            goal=manifest.goal,
            category=manifest.category,
            files=tuple(reroute_files),
            symbols=tuple(reroute_symbols),
            tests=tuple(manifest.tests),
            rules=tuple(r.path for r in manifest.rules),
            references=tuple(ref.path for ref in manifest.references),
            context_policy="advisory",
            task_contract_hash=manifest.task_contract_hash
        )
        
        # Keep unaffected files as-is
        unaffected_files = [f for f in manifest.files if f.path not in reroute_files]
        
        # Merge: keep unaffected files, replace affected with newly routed
        final_files = list(unaffected_files) + list(new_manifest.files)
    
    # Deduplicate by path (keep highest ranking_score)
    file_map = {}
    for f in final_files:
        if f.path not in file_map or f.ranking_score > file_map[f.path].ranking_score:
            file_map[f.path] = f
    
    merged_files = list(file_map.values())
    
    # Merge events: keep unaffected events, add new ones
    if full_reroute:
        # For full re-route, preserve explicit admission events, add new ones
        explicit_events = [e for e in manifest.events if e.source == "explicit"]
        merged_events = explicit_events + list(new_manifest.events)
    else:
        unaffected_events = [e for e in manifest.events if e.target not in reroute_files]
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