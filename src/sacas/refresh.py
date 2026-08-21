"""Refresh task context, detect stale files, and suggest candidate expansions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from sacas.graphify import GraphSnapshotError, raw_graph_snapshot_hash, read_graphify_manifest
from sacas.io import read_repo_source_bytes
from sacas.paths import Installation
from sacas.tasks import (
    is_file_protected,
    invalidate_runtime_context_pack,
    lexical_query_hash,
    parse_protected_boundaries,
    regenerate_task_markdown,
)
from sacas.active_context import (
    AdmissionEvent,
    ActiveSymbolContext,
    load_legacy_active_context,
    load_task_state,
    ActiveFileContext,
)
from sacas.task_contract import TaskContract, load_task_contract, task_contract_hash


def _compute_graph_snapshot_hash(installation: Installation) -> str:
    """Compute the raw configured graph.json identity through its secure reader."""
    if installation.manifest.graphify_mode == "off":
        return ""
    try:
        return raw_graph_snapshot_hash(
            installation.repository_root,
            f"{installation.manifest.graphify_output}/graph.json",
        )
    except GraphSnapshotError:
        return ""


def _compute_source_hashes(installation: Installation, file_paths: tuple[str, ...]) -> dict[str, str]:
    """Compute content hashes for a set of source files."""
    hashes = {}
    for path in file_paths:
        try:
            content_bytes = read_repo_source_bytes(installation.repository_root, path)
            hashes[path] = hashlib.sha256(content_bytes).hexdigest()
        except (ValueError, FileNotFoundError, OSError):
            hashes[path] = ""
    return hashes


def _reresolve_changed_source_selections(
    installation: Installation,
    manifest: ActiveContextManifest,
    changed_paths: set[str],
) -> ActiveContextManifest:
    """Refresh selector ranges in place without changing their admission origin."""
    from sacas.regions import SymbolRangeResolver

    def resolve_layer(items: tuple[ActiveFileContext, ...]) -> tuple[ActiveFileContext, ...]:
        refreshed: list[ActiveFileContext] = []
        for item in items:
            if item.path not in changed_paths or item.selection.get("mode") != "symbols":
                refreshed.append(item)
                continue
            symbols: list[ActiveSymbolContext] = []
            for raw_symbol in item.selection.get("symbols", []):
                symbol = ActiveSymbolContext.from_dict(raw_symbol) if isinstance(raw_symbol, dict) else raw_symbol
                resolved = SymbolRangeResolver.resolve(installation, item.path, symbol.name)
                if resolved is None:
                    raise ValueError(
                        f"Refresh refused: selector '{item.path}::{symbol.name}' no longer resolves"
                    )
                symbols.append(replace(symbol, range=resolved))
            refreshed.append(replace(item, selection={"mode": "symbols", "symbols": symbols}))
        return tuple(refreshed)

    refreshed = replace(
        manifest,
        files=resolve_layer(manifest.files),
        reference_files=resolve_layer(manifest.reference_files),
        working_files=resolve_layer(manifest.working_files),
    )
    # Admission targets identify the selected symbol, not its resolved range.
    # Retain the complete event so provenance and its stable ID survive a
    # source-only re-resolution.
    return refreshed


def _is_task_changed(manifest: ActiveContextManifest, task_dir: Path) -> bool:
    """Check if task contract has changed by comparing with current task.json on disk."""
    from sacas.task_contract import load_task_contract, task_contract_hash
    current_contract = load_task_contract(task_dir)
    if current_contract is None:
        return False
    current_hash = task_contract_hash(current_contract)
    return manifest.task_contract_hash != current_hash


def task_contract_hash_for_refresh(task_dir: Path, fallback_hash: str) -> str:
    """Use the current canonical task contract when a refresh rebuilds context."""
    from sacas.task_contract import load_task_contract, task_contract_hash

    contract = load_task_contract(task_dir)
    return task_contract_hash(contract) if contract is not None else fallback_hash


def _is_graph_changed(manifest: ActiveContextManifest, current_graph_hash: str) -> bool:
    """Check if graph snapshot has changed."""
    return manifest.graph_snapshot_hash != current_graph_hash


def _event_key(event: AdmissionEvent) -> tuple[object, ...]:
    """Identity independent of generated event IDs, used across reroutes."""
    return (
        event.target, event.action, event.source, event.reason, event.trigger,
        event.triggered_by, event.relation, event.direction, event.ranking_score,
        event.confidence, event.evidence, event.graph_snapshot_hash,
        event.graph_query_id, event.graph_node_id, event.graph_edge_source_id,
        event.graph_edge_target_id, event.graph_edge_kind, event.graph_confidence,
        event.lexical_query_hash, event.lexical_matched_terms, event.lexical_score,
    )


def _merge_events(
    existing: tuple[AdmissionEvent, ...], incoming: tuple[AdmissionEvent, ...], *,
    retain_sources: set[str], drop_targets: set[str] | None = None,
) -> tuple[AdmissionEvent, ...]:
    """Keep stable IDs for equivalent history and allocate collision-free new IDs."""
    drop_targets = drop_targets or set()
    retained = [event for event in existing if event.source in retain_sources or event.target not in drop_targets]
    by_key = {_event_key(event): event for event in retained}
    used_ids = {event.id for event in retained}
    result = list(retained)
    for event in incoming:
        prior = by_key.get(_event_key(event))
        if prior is not None:
            continue
        # New refresh history always receives a fresh namespace.  The ID
        # produced by route_goal belongs to its temporary reroute manifest;
        # preserving it could collide with an existing init event or change
        # shape across equivalent refreshes.
        sequence = 0
        while f"evt-refresh-{sequence:03d}" in used_ids:
            sequence += 1
        event_id = f"evt-refresh-{sequence:03d}"
        merged = replace(event, id=event_id)
        used_ids.add(event_id)
        by_key[_event_key(merged)] = merged
        result.append(merged)
    return tuple(result)


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
            content_bytes = read_repo_source_bytes(installation.repository_root, f.path)
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
    # Legacy-only task directories must not use the compatibility migration
    # loader here: it writes task.json/active_context.json before the secure
    # admission gate can refuse a missing or binary source.
    legacy_path = task_dir / "expansions.json"
    is_legacy_only = not (task_dir / "active_context.json").is_file() and legacy_path.is_file()
    if is_legacy_only:
        manifest = load_legacy_active_context(task_dir)
        contract = load_task_contract(task_dir)
    else:
        manifest, contract = load_task_state(task_dir, allow_task_id_mismatch=True)
    if manifest is None:
        raise ValueError("Active task metadata (active_context.json) is missing or unreadable.")
    # task.json is canonical when a refresh reroutes; load_task_state deliberately
    # withholds it on an ID mismatch, so read it directly for convergence.
    canonical_contract = contract or load_task_contract(task_dir)
    migrated_legacy_contract = False
    if canonical_contract is None or not canonical_contract.task_id:
        # Pre-contract task directories are still refreshable.  Build their
        # canonical contract in memory and let the normal publication boundary
        # persist it only after all admitted inputs have passed secure reads.
        # A refused refresh must leave both task.json and active_context.json
        # exactly as it found them.
        canonical_contract = TaskContract(
            schema_version=1,
            task_id=manifest.task_id or task_id,
            goal=manifest.goal,
            category=manifest.category,
            criteria=(),
            constraints=(),
            verification=(),
        )
        manifest = replace(
            manifest,
            task_id=canonical_contract.task_id,
            task_contract_hash=task_contract_hash(canonical_contract),
        )
        migrated_legacy_contract = True

    changed = migrated_legacy_contract
    # Read every admitted layer before writing anything.  A selective refresh
    # cannot safely publish if a non-selected admission is stale.
    # File admissions, rules, and references are all canonical inputs to the
    # compiled context.  Read their current bytes before mutating any durable
    # state so selective refresh remains an all-or-nothing operation.
    tracked_paths = tuple(dict.fromkeys(
        [file.path for file in manifest.all_files]
        + [rule.path for rule in manifest.rules]
        + [reference.path for reference in manifest.references]
    ))
    current_hashes: dict[str, str] = {}
    unreadable_paths: dict[str, tuple[str, Exception]] = {}
    kinds_by_path = {
        **{file.path: "source" for file in manifest.all_files},
        **{rule.path: "rule" for rule in manifest.rules},
        **{reference.path: "reference" for reference in manifest.references},
    }
    for path in tracked_paths:
        try:
            current_hashes[path] = hashlib.sha256(
                read_repo_source_bytes(installation.repository_root, path)
            ).hexdigest()
        except (ValueError, FileNotFoundError, OSError) as error:
            current_hashes[path] = ""
            unreadable_paths[path] = (kinds_by_path[path], error)
    stale_file_paths = {
        file.path for file in manifest.all_files
        if file.hash != current_hashes[file.path]
    }
    stale_rule_paths = {
        rule.path for rule in manifest.rules
        if rule.hash != current_hashes[rule.path]
    }
    stale_reference_paths = {
        reference.path for reference in manifest.references
        if reference.hash != current_hashes[reference.path]
    }
    stale_paths = stale_file_paths | stale_rule_paths | stale_reference_paths

    # The runtime pack is a cached projection of canonical state.  Once any
    # input used to produce it is stale, remove it before rerouting or before
    # reporting a selective-refresh refusal.
    current_graph_hash = _compute_graph_snapshot_hash(installation)
    graph_changed = _is_graph_changed(manifest, current_graph_hash)
    task_changed = (
        canonical_contract is not None
        and manifest.task_contract_hash != task_contract_hash(canonical_contract)
    )
    if stale_paths or graph_changed or task_changed:
        invalidate_runtime_context_pack(installation)

    # Canonical admissions are historical facts.  A failed secure read cannot
    # be repaired by dropping the admission (or its events) from a refresh;
    # doing so would silently publish a smaller context.  The cache may be
    # invalidated, but canonical state remains byte-for-byte untouched.
    if unreadable_paths:
        path = sorted(unreadable_paths)[0]
        kind, error = unreadable_paths[path]
        detail = str(error).lower()
        if "binary" in detail or "utf-8" in detail:
            raise ValueError(f"{kind}_binary: {path}: {error}") from error
        if "exceeds size" in detail:
            raise ValueError(f"{kind}_oversized: {path}: {error}") from error
        raise ValueError(f"Refresh refused: canonical admission unavailable: {path}") from error

    unselected_stale = stale_paths.difference(selective_files)
    if selective_files and unselected_stale:
        stale = ", ".join(sorted(unselected_stale))
        raise ValueError(f"Selective refresh refused: unselected stale context: {stale}")

    def refreshed_layer(items: tuple[ActiveFileContext, ...]) -> tuple[ActiveFileContext, ...]:
        refreshed: list[ActiveFileContext] = []
        for item in items:
            if item.path not in stale_paths:
                refreshed.append(item)
                continue
            refreshed.append(replace(item, hash=current_hashes[item.path]))
        return tuple(refreshed)

    if stale_paths:
        changed = True
        manifest = replace(
            manifest,
            files=refreshed_layer(manifest.files),
            reference_files=refreshed_layer(manifest.reference_files),
            working_files=refreshed_layer(manifest.working_files),
            rules=tuple(
                replace(rule, hash=current_hashes[rule.path])
                if rule.path in stale_rule_paths else rule
                for rule in manifest.rules
            ),
            references=tuple(
                replace(reference, hash=current_hashes[reference.path])
                if reference.path in stale_reference_paths else reference
                for reference in manifest.references
            ),
        )
        manifest = _reresolve_changed_source_selections(
            installation, manifest, stale_paths
        )

    # 2. Determine what needs re-routing
    needs_reroute = False
    reroute_files = set()
    reroute_symbols = set()
    
    if graph_changed:
        needs_reroute = True
    
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
            graph_rediscovery=graph_rediscovery,
            contract=canonical_contract,
        )
        changed = True
        # Update graph snapshot hash after re-routing
        manifest = replace(
            manifest,
            task_id=canonical_contract.task_id if canonical_contract else manifest.task_id,
            goal=canonical_contract.goal if canonical_contract else manifest.goal,
            category=canonical_contract.category if canonical_contract else manifest.category,
            task_contract_hash=(
                task_contract_hash(canonical_contract)
                if canonical_contract
                else manifest.task_contract_hash
            ),
            graph_snapshot_hash=current_graph_hash,
        )
    # 5. Scope expansion analysis stays in memory until the publication boundary.
    candidates_data: dict[str, object] | None = None
    if not selective_files:
        candidates_list = generate_candidates_for_manifest(installation, manifest)
        candidates_data = {
            "task_id": manifest.task_id,
            "graph_snapshot_hash": manifest.graph_snapshot_hash,
            "candidates": candidates_list
        }

    # 6. Always regenerate markdown documents
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        manifest=manifest,
        contract=canonical_contract,
        candidates_data=candidates_data,
    )
    if is_legacy_only:
        # The publisher has successfully made the canonical replacement
        # durable, so it is now safe to retire the legacy input.
        try:
            legacy_path.unlink()
        except OSError:
            pass

    return changed


def _re_route_files(
    installation: Installation,
    manifest: ActiveContextManifest,
    reroute_files: set[str],
    reroute_symbols: set[str],
    task_dir: Path,
    full_reroute: bool = False,
    graph_rediscovery: bool = False,
    contract: TaskContract | None = None,
) -> ActiveContextManifest:
    """Re-route specified files/symbols or do full re-route if full_reroute=True."""
    from sacas.tasks import route_goal
    routing_goal = contract.goal if contract else manifest.goal
    routing_category = contract.category if contract else manifest.category
    merged_reference_files = manifest.reference_files
    merged_working_files = manifest.working_files
    graph_replaced_heuristic_event_targets: set[str] = set()
    
    if full_reroute:
        # Full re-route: re-discover task-dependent context while retaining
        # only user admissions.  The three file layers are semantically
        # distinct, so keep their explicit members separate and restore them
        # to the same layer after routing.  Heuristic and Graphify admissions
        # are intentionally discarded across every layer.
        explicit_files_by_layer = tuple(
            file for file in manifest.files
            if file.source == "explicit" and file.role != "test"
        )
        explicit_reference_files = tuple(
            file for file in manifest.reference_files
            if file.source == "explicit" and file.role != "test"
        )
        explicit_working_files = tuple(
            file for file in manifest.working_files
            if file.source == "explicit" and file.role != "test"
        )
        explicit_files = (
            explicit_files_by_layer
            + explicit_reference_files
            + explicit_working_files
        )
        explicit_events = tuple(event for event in manifest.events if event.source == "explicit")
        from sacas.tasks import is_explicit_rule_or_reference
        explicit_rules = tuple(
            rule for rule in manifest.rules if is_explicit_rule_or_reference(rule.reason)
        )
        explicit_references = tuple(
            reference for reference in manifest.references
            if is_explicit_rule_or_reference(reference.reason)
        )
        # The legacy ``manifest.tests`` list is not evidence of an explicit
        # admission: it can contain paths from older routing runs after their
        # corresponding contexts have been removed.  Re-resolve only the
        # explicit test contexts that are still admitted, across every layer.
        # ``route_goal`` will hash those paths again before publishing them.
        explicit_tests = tuple(dict.fromkeys(
            file.path
            for file in manifest.all_files
            if file.source == "explicit" and file.role == "test"
        ))
        new_manifest = route_goal(
            installation=installation,
            goal=routing_goal,
            category=routing_category,
            files=(),
            symbols=(),
            tests=(), rules=(), references=(),
            context_policy="advisory",
            task_contract_hash=task_contract_hash_for_refresh(task_dir, manifest.task_contract_hash),
            seed_files=explicit_files,
            seed_tests=explicit_tests,
            seed_rules=explicit_rules,
            seed_references=explicit_references,
            seed_events=explicit_events,
        )

        # `route_goal` represents every admission in `files`.  Restore the
        # original layer placement for explicit context and leave only newly
        # discovered admissions in the legacy source layer.
        explicit_layer_paths = {
            file.path
            for file in (
                explicit_files_by_layer
                + explicit_reference_files
                + explicit_working_files
            )
        }
        explicit_test_paths = {
            file.path for file in manifest.all_files
            if file.source == "explicit" and file.role == "test"
        }
        final_files = [
            file for file in new_manifest.files
            if file.path not in explicit_layer_paths | explicit_test_paths
        ] + list(explicit_files_by_layer) + [
            file for file in manifest.files
            if file.source == "explicit" and file.role == "test"
        ]
        merged_reference_files = explicit_reference_files + tuple(
            file for file in manifest.reference_files
            if file.source == "explicit" and file.role == "test"
        )
        merged_working_files = explicit_working_files + tuple(
            file for file in manifest.working_files
            if file.source == "explicit" and file.role == "test"
        )
        
    elif graph_rediscovery:
        # Graph rediscovery is discovery over a retained non-Graphify
        # skeleton.  Seed it before budget calculation so stable explicit and
        # heuristic scope neither disappears nor gets displaced by a graph hit.
        retained_files_by_layer = tuple(
            file for file in manifest.files
            if file.source != "graphify" and file.role != "test"
        )
        retained_reference_files = tuple(
            file for file in manifest.reference_files
            if file.source != "graphify" and file.role != "test"
        )
        retained_working_files = tuple(
            file for file in manifest.working_files
            if file.source != "graphify" and file.role != "test"
        )
        retained_files = (
            retained_files_by_layer
            + retained_reference_files
            + retained_working_files
        )
        retained_tests = tuple(dict.fromkeys(
            file.path
            for file in manifest.all_files
            if file.source != "graphify" and file.role == "test"
        ))
        retained_events = tuple(event for event in manifest.events if event.source != "graphify")
        new_manifest = route_goal(
            installation=installation,
            goal=routing_goal,
            category=routing_category,
            files=(),
            symbols=(),
            tests=(), rules=(), references=(),
            context_policy="advisory",
            task_contract_hash=task_contract_hash_for_refresh(task_dir, manifest.task_contract_hash),
            seed_files=retained_files,
            seed_tests=retained_tests,
            seed_rules=manifest.rules,
            seed_references=manifest.references,
            seed_events=retained_events,
        )
        # Explicit context is user intent and cannot be displaced.  Heuristic
        # context remains a budget seed, but a new Graphify admission for the
        # same path replaces it so the current evidence is visible.
        explicit_context_paths = {
            file.path
            for file in (
                tuple(file for file in retained_files_by_layer if file.source == "explicit")
                + tuple(file for file in retained_reference_files if file.source == "explicit")
                + tuple(file for file in retained_working_files if file.source == "explicit")
                + tuple(
                    file for file in manifest.all_files
                    if file.source == "explicit" and file.role == "test"
                )
            )
        }
        retained_secondary_paths = {
            file.path for file in retained_reference_files + retained_working_files
        }
        fresh_graph_paths = {
            file.path for file in new_manifest.files if file.source == "graphify"
        }
        graph_replaced_heuristic_event_targets = {
            event.target for event in manifest.events
            if event.source == "heuristic"
            and event.target.split("::", 1)[0] in fresh_graph_paths
        }
        new_manifest = replace(
            new_manifest,
            events=tuple(
                event for event in new_manifest.events
                if event.target.split("::", 1)[0] not in explicit_context_paths
                and not (
                    event.source == "heuristic"
                    and event.target.split("::", 1)[0] in fresh_graph_paths
                )
            ),
        )
        final_files = [
            file for file in new_manifest.files
            if file.path not in explicit_context_paths
            and (file.path not in retained_secondary_paths or file.source == "graphify")
        ] + [
            file for file in retained_files_by_layer if file.source == "explicit"
        ] + [
            file for file in manifest.files
            if file.source == "explicit" and file.role == "test"
        ]
        merged_reference_files = tuple(
            file for file in retained_reference_files
            if not (file.source == "heuristic" and file.path in fresh_graph_paths)
        ) + tuple(
            file for file in manifest.reference_files
            if file.source == "explicit" and file.role == "test"
        )
        merged_working_files = tuple(
            file for file in retained_working_files
            if not (file.source == "heuristic" and file.path in fresh_graph_paths)
        ) + tuple(
            file for file in manifest.working_files
            if file.source == "explicit" and file.role == "test"
        )
        
    else:
        if not reroute_files:
            return manifest
        
        # Partial re-route: re-route only specified files/symbols
        new_manifest = route_goal(
            installation=installation,
            goal=routing_goal,
            category=routing_category,
            files=tuple(reroute_files),
            symbols=tuple(reroute_symbols),
            tests=(), rules=(), references=(),
            context_policy="advisory",
            task_contract_hash=task_contract_hash_for_refresh(task_dir, manifest.task_contract_hash)
        )
        
        # Keep unaffected files as-is
        unaffected_files = [f for f in manifest.files if f.path not in reroute_files]
        
        # Merge: keep unaffected files, replace affected with newly routed
        final_files = list(unaffected_files) + list(new_manifest.files)
    
    # Deduplicate by path.  A retained explicit admission is authoritative
    # regardless of a Graphify result's numerical confidence.
    file_map: dict[str, ActiveFileContext] = {}
    for f in final_files:
        existing = file_map.get(f.path)
        if existing is None:
            file_map[f.path] = f
        elif existing.source != "explicit" and (
            f.source == "explicit"
            or (existing.source == "heuristic" and f.source == "graphify")
            or f.ranking_score > existing.ranking_score
        ):
            file_map[f.path] = f
    
    merged_files = list(file_map.values())
    
    # Merge events: keep unaffected events, add new ones
    if full_reroute:
        merged_events = _merge_events(
            manifest.events, new_manifest.events, retain_sources={"explicit"},
            drop_targets={event.target for event in manifest.events if event.source != "explicit"},
        )
    elif graph_rediscovery:
        merged_events = _merge_events(
            manifest.events, new_manifest.events, retain_sources={"explicit"},
            drop_targets=(
                {event.target for event in manifest.events if event.source == "graphify"}
                | graph_replaced_heuristic_event_targets
            ),
        )
    else:
        merged_events = _merge_events(
            manifest.events, new_manifest.events, retain_sources={"explicit"}, drop_targets=reroute_files,
        )
    
    merged_manifest = replace(
        manifest,
        files=tuple(merged_files),
        reference_files=merged_reference_files,
        working_files=merged_working_files,
        rules=new_manifest.rules if full_reroute else manifest.rules,
        references=new_manifest.references if full_reroute else manifest.references,
        tests=new_manifest.tests if full_reroute else manifest.tests,
        events=merged_events,
        budget=None,  # will be recalculated
        policy=None   # will be recalculated
    )
    
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
    parsed_boundaries = parse_protected_boundaries(installation.repository_root, boundaries_file)

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
        node_details = {node_id: (path, label, line) for node_id, path, label, line in evidence.nodes}
        candidate_details = {}
        for source_id, destination_id, edge_kind in evidence.edges:
            source_detail = node_details.get(source_id)
            dest_detail = node_details.get(destination_id)
            if source_detail is None or dest_detail is None:
                continue
            source_path, _source_label, _source_line = source_detail
            dest_path, _dest_label, _dest_line = dest_detail

            is_dest_active = dest_path in active_paths
            is_source_active = source_path in active_paths

            if is_dest_active and source_path not in active_paths:
                cand_path = source_path
                trigger_path = dest_path
                candidate_node_id = source_id
                candidate_label, candidate_line = _source_label, _source_line
                direction = "incoming"
            elif is_source_active and dest_path not in active_paths:
                cand_path = dest_path
                trigger_path = source_path
                candidate_node_id = destination_id
                candidate_label, candidate_line = _dest_label, _dest_line
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
                    "graph_node_id": candidate_node_id,
                    "node_label": candidate_label,
                    "node_line": candidate_line,
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
                "estimated_tokens": cand_cost,
                "graph_node_id": details.get("graph_node_id", ""),
                "node_label": details.get("node_label"),
                "node_line": details.get("node_line"),
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
                "estimated_tokens": cand_cost,
                "query_hash": lexical_query_hash(manifest.goal),
                "matched": list(matched),
            })
            
    # candidates.json is derived task-bound state. Copy the canonical graph
    # identity onto every Graphify suggestion so expand can reject spliced or
    # stale records even when the surrounding payload looks valid.
    for candidate in candidates_list:
        candidate["graph_snapshot_hash"] = manifest.graph_snapshot_hash
    return candidates_list
