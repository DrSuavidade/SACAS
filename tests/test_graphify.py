"""Graphify is optional evidence; SACAS never recreates its extraction."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def graph_fixture(destination: Path) -> Path:
    output = destination / "graphify-out"
    output.mkdir()
    shutil.copy2(FIXTURES / "graphify-out" / "graph.json", output / "graph.json")
    return output


def test_off_mode_does_not_read_or_invoke_graphify(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify

    output = graph_fixture(tmp_path)
    invoked: list[tuple[str, ...]] = []

    evidence = collect_graphify(tmp_path, mode="off", runner=lambda args: invoked.append(args))

    assert evidence.status == "disabled"
    assert evidence.communities == ()
    assert invoked == []
    assert output.exists()


def test_existing_mode_reads_compatible_graph_with_hash_and_provenance(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify

    graph_fixture(tmp_path)
    evidence = collect_graphify(tmp_path, mode="existing")

    assert evidence.status == "fresh"
    assert evidence.provenance == "graphify_existing"
    assert len(evidence.content_hash) == 64
    assert evidence.communities == (("core", ("src/api.py", "src/web.py")),)


def test_existing_mode_is_graceful_when_graph_is_absent_or_stale(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify

    missing = collect_graphify(tmp_path, mode="existing")
    assert (missing.status, missing.warning) == ("unavailable", "Graphify graph.json is absent")

    output = graph_fixture(tmp_path)
    graph = output / "graph.json"
    os.utime(graph, (1, 1))
    source = tmp_path / "src" / "api.py"
    source.parent.mkdir()
    source.write_text("changed", encoding="utf-8")
    stale = collect_graphify(tmp_path, mode="existing")
    assert stale.status == "stale"
    assert stale.freshness == "stale"


def test_code_only_uses_graphify_cli_local_extraction_without_semantic_flags(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify

    observed: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> int:
        observed.append(args)
        graph_fixture(tmp_path)
        return 0

    evidence = collect_graphify(tmp_path, mode="code-only", runner=runner)

    assert evidence.status == "fresh"
    assert observed == [("graphify", "extract", str(tmp_path.resolve()), "--no-viz", "--code-only")]
    assert "semantic" not in " ".join(observed[0])


def test_semantic_mode_requires_explicit_mode_and_is_the_only_mode_with_semantic_flag(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify

    observed: list[tuple[str, ...]] = []

    def runner(args: tuple[str, ...]) -> int:
        observed.append(args)
        graph_fixture(tmp_path)
        return 0

    evidence = collect_graphify(tmp_path, mode="semantic", runner=runner)

    assert evidence.status == "fresh"
    assert observed == [("graphify", "extract", str(tmp_path.resolve()), "--no-viz")]
    assert "explicitly selected" in evidence.warning


def test_failed_optional_graphify_execution_returns_evidence_warning(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify

    evidence = collect_graphify(tmp_path, mode="code-only", runner=lambda _args: 1)

    assert evidence.status == "unavailable"
    assert "exit code 1" in evidence.warning


def test_safe_query_returns_no_result_when_graphify_cli_is_unavailable(tmp_path: Path) -> None:
    from sacas.graphify import safe_query

    graph_fixture(tmp_path)
    assert safe_query(tmp_path / "graphify-out", "what calls api", runner=lambda _args: 127) is None


def test_safe_query_targets_the_supplied_custom_output_graph(tmp_path: Path) -> None:
    from sacas.graphify import safe_query

    output = tmp_path / "custom-output"
    output.mkdir()
    (output / "graph.json").write_text("{}", encoding="utf-8")
    observed: list[tuple[str, ...]] = []

    assert safe_query(output, "what calls api", runner=lambda args: observed.append(args) or "answer") == "answer"
    assert observed == [
        ("graphify", "query", "what calls api", "--graph", str(output / "graph.json"))
    ]


def test_system_map_uses_community_evidence_without_tasks_or_protected_boundaries(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify
    from sacas.map import build_system_map, render_system_map

    graph_fixture(tmp_path)
    system_map = build_system_map(collect_graphify(tmp_path, mode="existing"))
    rendered = render_system_map(system_map)

    assert system_map.communities[0].name == "core"
    assert system_map.protected_boundaries == ()
    assert "tasks/" not in rendered.lower()
    assert "protected" not in rendered.lower()
    assert "Community: core" in rendered


def test_impact_records_are_bounded_to_direct_relationship_types(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify
    from sacas.map import impact_records

    graph_fixture(tmp_path)
    records = impact_records(collect_graphify(tmp_path, mode="existing"), "src/api.py")

    assert [(record.kind, record.path) for record in records] == [
        ("direct_target", "src/api.py"),
        ("caller", "src/web.py"),
        ("importer", "src/worker.py"),
        ("dependent", "src/consumer.py"),
        ("test", "tests/test_api.py"),
    ]
    assert all(record.provenance == "graphify_existing" for record in records)


def test_graph_manifest_and_system_map_persist_deterministically(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify, read_graphify_manifest, write_graphify_manifest
    from sacas.map import build_system_map, render_system_map, write_system_map

    graph_fixture(tmp_path)
    evidence = collect_graphify(tmp_path, mode="existing")
    manifest = tmp_path / "Structure" / ".sacas" / "graphify.json"
    output = tmp_path / "Structure" / "map" / "SYSTEM.md"

    write_graphify_manifest(manifest, evidence)
    write_system_map(output, build_system_map(evidence))

    assert read_graphify_manifest(manifest) == evidence
    first = output.read_text(encoding="utf-8")
    write_system_map(output, build_system_map(evidence))
    assert output.read_text(encoding="utf-8") == first
    assert "<!-- SACAS:START system-map -->" in first
    assert render_system_map(build_system_map(evidence)) in first


def test_system_map_update_replaces_only_owned_region_and_preserves_manual_content(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify
    from sacas.map import build_system_map, write_system_map

    graph_fixture(tmp_path)
    output = tmp_path / "Structure" / "map" / "SYSTEM.md"
    output.parent.mkdir(parents=True)
    output.write_text(
        "# Human map\n\nManual introduction.\n\n<!-- SACAS:START system-map -->\nold\n"
        "<!-- SACAS:END system-map -->\n\nManual conclusion.\n",
        encoding="utf-8",
    )

    write_system_map(output, build_system_map(collect_graphify(tmp_path, mode="existing")))

    rendered = output.read_text(encoding="utf-8")
    assert "Manual introduction." in rendered
    assert "Manual conclusion." in rendered
    assert "old" not in rendered


def test_system_map_refuses_to_overwrite_an_unowned_human_document(tmp_path: Path) -> None:
    from sacas.graphify import collect_graphify
    from sacas.map import build_system_map, write_system_map
    from sacas.regions import RegionError

    graph_fixture(tmp_path)
    output = tmp_path / "Structure" / "map" / "SYSTEM.md"
    output.parent.mkdir(parents=True)
    output.write_text("# Human map\n\nDo not replace.\n", encoding="utf-8")

    with pytest.raises(RegionError, match="complete SACAS region"):
        write_system_map(output, build_system_map(collect_graphify(tmp_path, mode="existing")))

    assert output.read_text(encoding="utf-8") == "# Human map\n\nDo not replace.\n"


def test_cli_map_consumes_existing_graph_and_writes_only_map_artifacts(tmp_path: Path) -> None:
    from sacas.cli import main

    graph_fixture(tmp_path)
    assert main(["map", "--root", str(tmp_path), "--mode", "existing"]) == 0

    assert (tmp_path / "Structure" / "map" / "SYSTEM.md").is_file()
    assert (tmp_path / "Structure" / ".sacas" / "graphify.json").is_file()
    assert not (tmp_path / "Structure" / "tasks").exists()
