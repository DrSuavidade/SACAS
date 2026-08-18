"""Calculate bounded impact effects for task files from Graphify evidence."""

from __future__ import annotations

from typing import Any
from sacas.graphify import GraphifyEvidence
from sacas.map import ImpactRecord, impact_records


def calculate_task_effects(
    evidence: GraphifyEvidence, files: tuple[str, ...]
) -> tuple[ImpactRecord, ...]:
    """Retrieve direct impact records for all task files, preserving order without duplicates."""
    seen: set[tuple[str, str]] = set()
    results: list[ImpactRecord] = []
    
    for file_path in files:
        records = impact_records(evidence, file_path)
        for record in records:
            key = (record.kind, record.path)
            if key not in seen:
                seen.add(key)
                results.append(record)
                
    order = {"direct_target": 0, "caller": 1, "importer": 2, "dependent": 3, "test": 4}
    return tuple(sorted(results, key=lambda item: (order.get(item.kind, 5), item.path)))
