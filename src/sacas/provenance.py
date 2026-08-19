"""Provenance tracking - traces context from files back to task goals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sacas.active_context import ActiveContextManifest, AdmissionEvent, ActiveFileContext
from sacas.paths import Installation


@dataclass(frozen=True)
class ProvenanceNode:
    """A node in the provenance chain."""
    type: str  # task, graphify_query, graph_node, graph_edge, admission_event, context_pack, file
    label: str
    details: dict[str, Any]
    children: tuple["ProvenanceNode", ...] = ()


def trace_file_to_goal(installation: Installation, target_path: str, manifest: ActiveContextManifest) -> ProvenanceNode:
    """Build provenance chain from a file back to the task goal."""
    # Start with the task goal
    root = ProvenanceNode(
        type="task",
        label=f"Task: {manifest.goal}",
        details={
            "task_id": manifest.task_id,
            "category": manifest.category,
            "git_revision": manifest.git_revision,
        },
        children=()
    )
    
    # Find admission event for this file
    admission_event = None
    for event in manifest.events:
        if event.target == target_path:
            admission_event = event
            break
    
    if not admission_event:
        return root
    
    # Build chain: task -> graphify_query -> graph_node -> graph_edge -> admission -> context_pack -> file
    children = []
    
    # Graphify query
    if admission_event.source == "graphify":
        query_node = ProvenanceNode(
            type="graphify_query",
            label=f"Graphify query: {admission_event.reason}",
            details={
                "source": admission_event.source,
                "trigger": admission_event.trigger,
            },
            children=()
        )
        
        # Find the graph node/edge that led to this
        # Look at evidence in admission event
        evidence = list(admission_event.evidence) if admission_event.evidence else []
        
        if "graphify_query" in evidence:
            # Graph node
            node_label = "Graphify node"
            for e in manifest.events:
                if e.triggered_by and e.target == target_path:
                    # This is complex - we'd need graph data
                    pass
            
            # Simplified: add graph edge info
            if admission_event.relation:
                edge_node = ProvenanceNode(
                    type="graph_edge",
                    label=f"Graph edge: {admission_event.relation}",
                    details={
                        "relation": admission_event.relation,
                        "direction": admission_event.direction,
                        "confidence": admission_event.confidence,
                    },
                    children=()
                )
                query_node = ProvenanceNode(
                    type="graphify_query",
                    label=f"Graphify query: {admission_event.reason}",
                    details={"source": admission_event.source, "trigger": admission_event.trigger},
                    children=(edge_node,)
                )
        
        children.append(query_node)
    
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
        },
        children=()
    )
    children.append(admit_node)
    
    # Context pack entry
    pack_node = ProvenanceNode(
        type="context_pack",
        label=f"Context pack entry",
        details={
            "file": target_path,
            "hash": _get_file_hash(installation, target_path),
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
        },
        children=tuple(children)
    )


def _get_file_hash(installation: Installation, path: str) -> str:
    """Get file hash from manifest."""
    import hashlib
    f_path = installation.repository_root / path
    if f_path.is_file():
        return hashlib.sha256(f_path.read_bytes()).hexdigest()[:16]
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
    
    # Build provenance chain
    root = trace_file_to_goal(installation, found_file.path, manifest)
    return render_provenance_chain(root)