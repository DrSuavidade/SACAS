"""Behavioral provenance tests for compiled context fragments."""

from __future__ import annotations

from pathlib import Path


def test_provenance_reports_each_fragment_specific_content_hash(tmp_path: Path) -> None:
    """A file with two selected regions exposes each pack fragment, not file bytes."""
    from sacas.active_context import ActiveContextManifest, ActiveFileContext, ActiveSymbolContext, AdmissionEvent, SourceRange
    from sacas.compiler import compile_and_write_context_pack
    from sacas.init import initialize
    from sacas.provenance import trace_file_to_goal

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("def first():\n    return 1\n\ndef second():\n    return 2\n", encoding="utf-8")
    manifest = ActiveContextManifest(
        task_id="provenance", task_contract_hash="contract", git_revision="rev", goal="Trace service",
        files=(ActiveFileContext(
            path="src/service.py", source="explicit", selection={"mode": "symbols", "symbols": [
                ActiveSymbolContext("first", SourceRange(1, 2, "parser", 1.0)),
                ActiveSymbolContext("second", SourceRange(4, 5, "parser", 1.0)),
            ]},
        ),),
        events=(
            AdmissionEvent("evt-first", "src/service.py::first", "admit", "explicit", "first", "initial"),
            AdmissionEvent("evt-second", "src/service.py::second", "admit", "explicit", "second", "initial"),
        ),
    )
    from sacas.compiler import compile_context_pack
    _, fragments = compile_context_pack(initialized.installation, manifest)
    compile_and_write_context_pack(initialized.installation, manifest)

    chain = trace_file_to_goal(initialized.installation, "src/service.py", manifest)
    pack_nodes = [child for child in chain.children if child.type == "context_pack"]
    assert {node.details["content_hash"] for node in pack_nodes} == {fragment.content_hash for fragment in fragments}
    assert {node.details["fragment_id"] for node in pack_nodes} == {fragment.id for fragment in fragments}


def test_provenance_nests_only_each_fragment_own_admission_events(tmp_path: Path) -> None:
    """Sibling fragments cannot borrow each other's selector provenance."""
    from sacas.active_context import ActiveContextManifest, ActiveFileContext, ActiveSymbolContext, AdmissionEvent, SourceRange
    from sacas.compiler import compile_and_write_context_pack
    from sacas.init import initialize
    from sacas.provenance import trace_file_to_goal

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("def first():\n    return 1\n\ndef second():\n    return 2\n", encoding="utf-8")
    manifest = ActiveContextManifest(
        task_id="provenance", task_contract_hash="contract", git_revision="rev", goal="Trace service",
        files=(ActiveFileContext(
            path="src/service.py", source="explicit", selection={"mode": "symbols", "symbols": [
                ActiveSymbolContext("first", SourceRange(1, 2, "parser", 1.0)),
                ActiveSymbolContext("second", SourceRange(4, 5, "parser", 1.0)),
            ]},
        ),),
        events=(
            AdmissionEvent("evt-first", "src/service.py::first", "admit", "explicit", "first", "initial"),
            AdmissionEvent("evt-second", "src/service.py::second", "admit", "explicit", "second", "initial"),
        ),
    )
    compile_and_write_context_pack(initialized.installation, manifest)

    chain = trace_file_to_goal(initialized.installation, "src/service.py", manifest)
    pack_nodes = [child for child in chain.children if child.type == "context_pack"]
    event_ids_by_selector = {
        node.details["selector"]: {
            descendant.details["event_id"]
            for descendant in node.children if descendant.type == "admission_event"
        }
        for node in pack_nodes
    }
    assert event_ids_by_selector == {
        "src/service.py::first": {"evt-first"},
        "src/service.py::second": {"evt-second"},
    }
