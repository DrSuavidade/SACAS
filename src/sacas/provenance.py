"""Provenance tracking - traces context from files back to task goals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sacas.active_context import ActiveContextManifest, AdmissionEvent, ActiveFileContext
from sacas.paths import Installation
from sacas.compiler import read_context_pack


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
    fragment = None
    try:
        pack_path = installation.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
        if pack_path.is_file():
            header, fragments = read_context_pack(pack_path)
            for frag in fragments:
                if frag.source == target_path:
                    fragment = frag
                    break
    except Exception:
        pass
    
    # Find admission event for this file from manifest (for backward compatibility)
    admission_event = None
    for event in manifest.events:
        if event.target == target_path:
            admission_event = event
            break
    
    # If we have a fragment with admission_event_ids, use those
    fragment_admission_ids = ()
    if fragment and fragment.admission_event_ids:
        fragment_admission_ids = fragment.admission_event_ids
    
    if not admission_event and not fragment_admission_ids:
        return root
    
    # Build chain: task -> graphify/lexical evidence -> admission -> context_pack -> file
    children = []
    
    # Use fragment admission IDs if available, otherwise fall back to manifest event
    if fragment_admission_ids:
        # Build chain from fragment admission IDs
        for adm_id in fragment_admission_ids:
            # Find the admission event in manifest
            adm_event = None
            for event in manifest.events:
                if event.id == adm_id:
                    adm_event = event
                    break
            if adm_event:
                # Add evidence chain for this admission
                children.extend(_build_evidence_chain(adm_event))
    elif admission_event:
        # Fall back to single admission event
        children.extend(_build_evidence_chain(admission_event))
    
    # Context pack entry - read from actual pack file
    pack_hash = _get_pack_fragment_hash(installation, target_path)
    pack_node = ProvenanceNode(
        type="context_pack",
        label=f"Context pack entry",
        details={
            "file": target_path,
            "content_hash": pack_hash,
            "fragment_id": fragment.id if fragment else None,
        },
        children=()
    )
    children.append(pack_node)
    
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


def _get_pack_fragment_hash(installation: Installation, target_path: str) -> str:
    """Get file hash from repository."""
    import hashlib
    from sacas.io import read_repo_bytes
    try:
        content_bytes = read_repo_bytes(installation.repository_root, path)
        return hashlib.sha256(content_bytes).hexdigest()[:16]
    except Exception:
        return ""


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
    
    task_dir = installation.sacas_root / "tasks" / "current"
    manifest, contract = load_task_state(task_dir)
    
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