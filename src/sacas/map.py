"""Compact system-map rendering from evidence, never task generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .graphify import GraphifyEvidence
from .io import write_text_atomic


@dataclass(frozen=True, slots=True)
class Community:
    name: str
    paths: tuple[str, ...]
    provenance: str
    freshness: str


@dataclass(frozen=True, slots=True)
class SystemMap:
    communities: tuple[Community, ...]
    provenance: str
    content_hash: str
    freshness: str
    protected_boundaries: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImpactRecord:
    kind: str
    path: str
    provenance: str
    freshness: str


def build_system_map(evidence: GraphifyEvidence) -> SystemMap:
    """Convert only Graphify community evidence into a system-map view."""
    return SystemMap(
        communities=tuple(
            Community(name, paths, evidence.provenance, evidence.freshness)
            for name, paths in evidence.communities
        ),
        provenance=evidence.provenance,
        content_hash=evidence.content_hash,
        freshness=evidence.freshness,
    )


def render_system_map(system_map: SystemMap) -> str:
    """Render deterministic human-facing map text with evidence metadata."""
    lines = ["# System map", "", f"Freshness: {system_map.freshness}", f"Provenance: {system_map.provenance}"]
    if system_map.content_hash:
        lines.append(f"Graph hash: {system_map.content_hash}")
    for community in system_map.communities:
        lines.extend(["", f"## Community: {community.name}"])
        lines.extend(f"- {path}" for path in community.paths)
    return "\n".join(lines) + "\n"


def write_system_map(path: Path, system_map: SystemMap) -> None:
    """Persist a generated map while keeping Graphify state in its own manifest."""
    write_text_atomic(path, render_system_map(system_map))


def impact_records(evidence: GraphifyEvidence, target: str) -> tuple[ImpactRecord, ...]:
    """Return direct, typed impact evidence only; no transitive expansion."""
    node_paths = dict(evidence.nodes)
    target_id = next((node_id for node_id, path in evidence.nodes if path == target or node_id == target), None)
    if target_id is None:
        return ()
    records = [ImpactRecord("direct_target", node_paths.get(target_id, target_id), evidence.provenance, evidence.freshness)]
    kinds = {"calls": "caller", "imports": "importer", "depends_on": "dependent", "tests": "test"}
    for source, destination, edge_kind in evidence.edges:
        if edge_kind in {"calls", "imports", "tests"} and destination == target_id:
            records.append(ImpactRecord(kinds[edge_kind], node_paths.get(source, source), evidence.provenance, evidence.freshness))
        elif edge_kind == "depends_on" and source == target_id:
            records.append(ImpactRecord("dependent", node_paths.get(destination, destination), evidence.provenance, evidence.freshness))
    order = {"direct_target": 0, "caller": 1, "importer": 2, "dependent": 3, "test": 4}
    return tuple(sorted(set(records), key=lambda item: (order[item.kind], item.path)))
