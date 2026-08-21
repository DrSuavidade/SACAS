"""Provenance tracking - traces context from files back to task goals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sacas.active_context import ActiveContextManifest, AdmissionEvent, ActiveFileContext
from sacas.paths import Installation
from sacas.compiler import load_validated_context_pack


@dataclass(frozen=True)
class ProvenanceNode:
    """A node in the provenance chain."""
    type: str  # task, graphify_query, graph_node, graph_edge, admission_event, context_pack, file
    label: str
    details: dict[str, Any]
    children: tuple["ProvenanceNode", ...] = ()


def trace_file_to_goal(installation: Installation, target_path: str, manifest: ActiveContextManifest) -> ProvenanceNode:
    """Build provenance chain from a file back to the task goal using persisted evidence."""
    # Start with the task goal
    root = ProvenanceNode(
        type="task",
        label=f"Task: {manifest.goal}",
        details={
            "task_id": manifest.task_id,
            "category": manifest.category,
            "git_revision": manifest.git_revision,
            "task_contract_hash": manifest.task_contract_hash,
        },
        children=()
    )
    
    # Find the fragment in the context pack to get admission_event_ids
    fragments = []
    try:
        pack_path = installation.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
        if pack_path.is_file():
            _header, pack_fragments = load_validated_context_pack(installation)
            for frag in pack_fragments:
                if frag.source == target_path:
                    fragments.append(frag)
    except Exception:
        pass
    
    # Find admission event for this file from manifest (for backward compatibility)
    admission_event = None
    for event in manifest.events:
        if event.target == target_path:
            admission_event = event
            break
    
    if not admission_event and not fragments:
        return root

    # Build a fragment-local chain.  Do not flatten IDs from sibling fragments:
    # callers must be able to see exactly which admission produced each payload.
    children = []
    for fragment in fragments:
        fragment_children: list[ProvenanceNode] = []
        for admission_id in fragment.admission_event_ids:
            event = next((candidate for candidate in manifest.events if candidate.id == admission_id), None)
            if event is not None:
                fragment_children.extend(_build_evidence_chain(event))
        children.append(ProvenanceNode(
            type="context_pack",
            label="Context pack entry",
            details={
                "file": target_path,
                "content_hash": fragment.content_hash,
                "fragment_id": fragment.id,
                "selector": fragment.selector,
            },
            children=tuple(fragment_children),
        ))

    # Older packs did not carry event IDs; retain the legacy file admission.
    if not fragments and admission_event:
        children.extend(_build_evidence_chain(admission_event))
    
    # File
    file_node = ProvenanceNode(
        type="file",
        label=f"File: {target_path}",
        details={
            "path": target_path,
        },
        children=()
    )
    children.append(file_node)
    
    return ProvenanceNode(
        type="task",
        label=f"Task: {manifest.goal}",
        details={
            "task_id": manifest.task_id,
            "category": manifest.category,
            "git_revision": manifest.git_revision,
            "task_contract_hash": manifest.task_contract_hash,
        },
        children=tuple(children)
    )


def _build_evidence_chain(admission_event: AdmissionEvent) -> list[ProvenanceNode]:
    """Build provenance nodes for a single admission event."""
    children = []
    
    # Graphify evidence chain (if applicable)
    if admission_event.source == "graphify" and admission_event.graph_snapshot_hash:
        # Graphify query node
        query_node = ProvenanceNode(
            type="graphify_query",
            label=f"Graphify query: {admission_event.graph_query_id or 'unknown'}",
            details={
                "graph_snapshot_hash": admission_event.graph_snapshot_hash,
                "graph_query_id": admission_event.graph_query_id or "unknown",
                "trigger": admission_event.trigger,
            },
            children=()
        )
        
        # Graph node
        if admission_event.graph_node_id:
            node_node = ProvenanceNode(
                type="graph_node",
                label=f"Graph node: {admission_event.graph_node_id}",
                details={
                    "node_id": admission_event.graph_node_id,
                    "graph_snapshot_hash": admission_event.graph_snapshot_hash,
                },
                children=()
            )
            query_node = ProvenanceNode(
                type="graphify_query",
                label=f"Graphify query: {admission_event.graph_query_id or 'unknown'}",
                details={
                    "graph_snapshot_hash": admission_event.graph_snapshot_hash,
                    "graph_query_id": admission_event.graph_query_id or "unknown",
                    "trigger": admission_event.trigger,
                },
                children=(node_node,)
            )
        
        # Graph edge
        if admission_event.graph_edge_source_id and admission_event.graph_edge_target_id:
            edge_node = ProvenanceNode(
                type="graph_edge",
                label=f"Graph edge: {admission_event.graph_edge_kind}",
                details={
                    "source_id": admission_event.graph_edge_source_id,
                    "target_id": admission_event.graph_edge_target_id,
                    "relation": admission_event.graph_edge_kind,
                    "direction": admission_event.direction,
                    "confidence": admission_event.graph_confidence,
                },
                children=()
            )
            # Add edge as child of query or node
            if query_node.children:
                query_node = ProvenanceNode(
                    type="graphify_query",
                    label=f"Graphify query: {admission_event.graph_query_id or 'unknown'}",
                    details={
                        "graph_snapshot_hash": admission_event.graph_snapshot_hash,
                        "graph_query_id": admission_event.graph_query_id or "unknown",
                        "trigger": admission_event.trigger,
                    },
                    children=(query_node.children[0], edge_node)
                )
            else:
                query_node = ProvenanceNode(
                    type="graphify_query",
                    label=f"Graphify query: {admission_event.graph_query_id or 'unknown'}",
                    details={
                        "graph_snapshot_hash": admission_event.graph_snapshot_hash,
                        "graph_query_id": admission_event.graph_query_id or "unknown",
                        "trigger": admission_event.trigger,
                    },
                    children=(edge_node,)
                )
        
        children.append(query_node)
    
    # Lexical evidence chain (if applicable)
    elif admission_event.source == "heuristic" and admission_event.lexical_query_hash:
        lexical_node = ProvenanceNode(
            type="lexical_query",
            label=f"Lexical query: {admission_event.lexical_query_hash[:16]}",
            details={
                "query_hash": admission_event.lexical_query_hash,
                "matched_terms": list(admission_event.lexical_matched_terms),
                "score": admission_event.lexical_score,
            },
            children=()
        )
        children.append(lexical_node)
    
    # Explicit user context
    elif admission_event.source == "explicit":
        explicit_node = ProvenanceNode(
            type="explicit_context",
            label=f"Explicit user context",
            details={
                "source": "explicit",
                "trigger": admission_event.trigger,
            },
            children=()
        )
        children.append(explicit_node)
    
    # Admission event
    admit_node = ProvenanceNode(
        type="admission_event",
        label=f"Admission: {admission_event.id}",
        details={
            "event_id": admission_event.id,
            "source": admission_event.source,
            "reason": admission_event.reason,
            "trigger": admission_event.trigger,
            "ranking_score": admission_event.ranking_score,
            "confidence": admission_event.confidence,
            "evidence": list(admission_event.evidence),
            "relation": admission_event.relation,
            "direction": admission_event.direction,
            "graph_snapshot_hash": admission_event.graph_snapshot_hash,
            "graph_node_id": admission_event.graph_node_id,
            "graph_edge_source_id": admission_event.graph_edge_source_id,
            "graph_edge_target_id": admission_event.graph_edge_target_id,
            "graph_edge_kind": admission_event.graph_edge_kind,
            "graph_confidence": admission_event.graph_confidence,
            "lexical_query_hash": admission_event.lexical_query_hash,
            "lexical_matched_terms": list(admission_event.lexical_matched_terms),
            "lexical_score": admission_event.lexical_score,
        },
        children=()
    )
    children.append(admit_node)
    
    return children


def render_provenance_chain(node: ProvenanceNode, indent: int = 0) -> list[str]:
    """Render provenance chain as text lines."""
    lines = []
    prefix = "  " * indent
    lines.append(f"{prefix}{node.label}")
    if node.details:
        for key, value in node.details.items():
            if value:
                lines.append(f"{prefix}  {key}: {value}")
    for child in node.children:
        lines.extend(render_provenance_chain(child, indent + 1))
    return lines


def query_why_file(installation: Installation, target_path: str) -> list[str]:
    """Query why a file is in context and return formatted output."""
    from sacas.active_context import load_task_state
    from sacas.task_contract import CanonicalStateError
    
    task_dir = installation.sacas_root / "tasks" / "current"
    try:
        manifest, contract = load_task_state(task_dir)
    except CanonicalStateError as error:
        return [f"Canonical task state is corrupt: {error}"]
    
    if not manifest:
        return ["No active SACAS task found."]
    
    # Find the file in manifest
    found_file = None
    for f in manifest.all_files:
        if f.path == target_path or target_path in f.path:
            found_file = f
            break
    
    if not found_file:
        # Check rules
        for r in manifest.rules:
            if r.path == target_path or target_path in r.path:
                return [f"Rule: {r.path}", f"  Rationale: {r.reason}"]
        # Check references
        for ref in manifest.references:
            if ref.path == target_path or target_path in ref.path:
                return [f"Reference: {ref.path}", f"  Selection: {ref.selection}", f"  Rationale: {ref.reason}"]
        return [f"File '{target_path}' not found in active context."]
    
    # Build provenance chain from persisted evidence
    root = trace_file_to_goal(installation, found_file.path, manifest)
    return render_provenance_chain(root)
