from __future__ import annotations

import json
from pathlib import Path
import pytest
from sacas.graphify import MAX_GRAPH_SNAPSHOT_BYTES, GraphifyAdapter, JsonGraphifyProvider
from tests.fakes import FakeGraphifyProvider

def test_json_graphify_provider(tmp_path: Path) -> None:
    graph_file = tmp_path / "graph.json"
    graph_file.write_text(json.dumps({
        "nodes": [
            {"id": "node_a", "path": "src/a.py"},
            {"id": "node_b", "path": "src/b.py"}
        ]
    }), encoding="utf-8")

    provider = JsonGraphifyProvider(graph_file)
    assert provider.verify_capabilities([]) is True

    result = provider.query("src", graph_file)
    assert result is not None
    assert result.status == "success"
    assert "src/a.py" in result.paths
    assert "src/b.py" in result.paths


def test_json_graphify_provider_omits_invalid_optional_fields(tmp_path: Path) -> None:
    graph_file = tmp_path / "graph.json"
    graph_file.write_text(json.dumps({
        "nodes": [{
            "id": "node_a",
            "path": 3,
            "label": 3,
            "line": None,
            "type": 3,
            "community": 3,
        }],
        "edges": [{
            "source": "node_a",
            "target": "node_b",
            "relation": 3,
            "confidence": 3,
            "provenance": 3,
        }],
    }), encoding="utf-8")

    provider = JsonGraphifyProvider(graph_file)

    result = provider.query("node_a", graph_file)

    assert result is not None
    assert result.paths == ("node_a",)
    assert result.nodes[0].path == "node_a"
    assert result.nodes[0].label is None
    assert result.nodes[0].line is None
    assert result.nodes[0].node_type is None
    assert result.nodes[0].community is None
    assert result.edges[0].relation == "calls"
    assert result.edges[0].confidence is None
    assert result.edges[0].provenance is None
    assert provider.neighbors("node_a") == [("node_a", "node_b", "related")]
    assert provider.communities() == ()


def test_json_graphify_provider_treats_an_external_graph_symlink_as_unavailable(tmp_path: Path) -> None:
    external = tmp_path.parent / f"{tmp_path.name}-outside.json"
    external.write_text('{"nodes": [{"id": "outside.py"}]}', encoding="utf-8")
    graph_dir = tmp_path / "graphify-out"
    graph_dir.mkdir()
    graph_file = graph_dir / "graph.json"
    try:
        graph_file.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")

    provider = JsonGraphifyProvider(graph_file, tmp_path)

    assert provider.verify_capabilities({"neighbors"}) is False
    assert provider.query("outside", graph_file) is None
    assert provider.neighbors("outside.py") == []
    assert provider.communities() == ()


def test_configured_json_provider_treats_invalid_snapshot_as_unavailable(tmp_path: Path) -> None:
    graph_file = tmp_path / "graphify-out" / "graph.json"
    graph_file.parent.mkdir()
    graph_file.write_bytes(b"\xffnot json")
    provider = JsonGraphifyProvider(graph_file, repository_root=tmp_path)

    assert provider.verify_capabilities({"neighbors"}) is False
    assert provider.query("src", graph_file) is None
    assert provider.neighbors("src/a.py") == []
    assert provider.communities() == ()


def test_json_graphify_provider_treats_oversized_snapshot_as_unavailable(tmp_path: Path) -> None:
    graph_file = tmp_path / "graphify-out" / "graph.json"
    graph_file.parent.mkdir()
    graph_file.write_bytes(b"{" + (b" " * MAX_GRAPH_SNAPSHOT_BYTES) + b"}")
    provider = JsonGraphifyProvider(graph_file, repository_root=tmp_path)

    assert provider.verify_capabilities({"neighbors"}) is False


def test_configured_adapter_omits_hash_for_rejected_snapshot(tmp_path: Path) -> None:
    graph_file = tmp_path / "graphify-out" / "graph.json"
    graph_file.parent.mkdir()
    graph_file.write_bytes(b"\x00{}")
    adapter = GraphifyAdapter(tmp_path, tmp_path / "Structure")

    result = adapter._parse_query_output("NODE node_a path=src/a.py")

    assert result.graph_snapshot_hash == ""


def test_configured_adapter_does_not_query_a_rejected_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    graph_file = tmp_path / "graphify-out" / "graph.json"
    graph_file.parent.mkdir()
    graph_file.write_bytes(b"\xffnot json")
    adapter = GraphifyAdapter(tmp_path, tmp_path / "Structure")

    def queried_graphify(*args: object, **kwargs: object) -> None:
        raise AssertionError("Graphify must not receive an invalid configured snapshot")

    monkeypatch.setattr("sacas.graphify.subprocess.run", queried_graphify)

    assert adapter.query("src", graph_file) is None

def test_fake_graphify_provider() -> None:
    provider = FakeGraphifyProvider(capable=True, mock_paths=("src/c.py",))
    assert provider.verify_capabilities([]) is True

    result = provider.query("anything", Path("dummy"))
    assert result is not None
    assert result.paths == ("src/c.py",)
    assert provider.queries_received == [("anything", Path("dummy"))]
