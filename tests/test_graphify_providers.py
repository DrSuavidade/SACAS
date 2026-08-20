from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import pytest
from sacas.graphify import MAX_GRAPH_SNAPSHOT_BYTES, GraphifyAdapter, JsonGraphifyProvider
from sacas.init import initialize
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


def test_get_graphify_provider_routes_a_configured_json_snapshot_without_monkeypatching(tmp_path: Path) -> None:
    """The production provider factory honours manifest.graphify_output."""
    initialized = initialize(tmp_path, graphify_mode="existing")
    graph_file = tmp_path / "custom-output" / "graph.json"
    graph_file.parent.mkdir()
    graph_file.write_text(
        json.dumps({"nodes": [{"id": "src/auth.py", "path": "src/auth.py"}], "edges": []}),
        encoding="utf-8",
    )
    installation = replace(
        initialized.installation,
        manifest=replace(initialized.installation.manifest, graphify_output="custom-output"),
    )

    from sacas.graphify import get_graphify_provider

    provider = get_graphify_provider(installation, required={"query"})
    result = provider.query("auth.py", graph_file)

    assert isinstance(provider, JsonGraphifyProvider)
    assert result is not None
    assert result.paths == ("src/auth.py",)


def test_graph_routing_outcome_uses_raw_custom_snapshot_identity(tmp_path: Path) -> None:
    """Routing identity is the secure graph.json bytes, never SACAS metadata."""
    from sacas.graphify import JsonGraphifyProvider, resolve_graph_routing_outcome

    graph_file = tmp_path / "custom-output" / "graph.json"
    graph_file.parent.mkdir()
    raw = b'{"nodes": [{"id": "src/auth.py", "path": "src/auth.py"}], "edges": []}'
    graph_file.write_bytes(raw)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def login(): pass\n", encoding="utf-8")

    class Provider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

    outcome = resolve_graph_routing_outcome(
        tmp_path, "custom-output/graph.json", "auth.py", Provider(graph_file, tmp_path)
    )

    import hashlib
    assert outcome.snapshot_hash == hashlib.sha256(raw).hexdigest()
    assert outcome.use_lexical_fallback is False
    assert outcome.query_result is not None
    assert outcome.query_result.graph_snapshot_hash == outcome.snapshot_hash


@pytest.mark.parametrize(
    ("content", "provider_failure", "expected_hash", "expected_warning"),
    [
        (None, False, "", "snapshot unavailable"),
        (b"\xffnot-json", False, "", "snapshot unavailable"),
        (b'{"nodes": [], "edges": []}', True, "raw", "retry"),
        (b'{"nodes": [], "edges": []}', False, "raw", "retry"),
    ],
)
def test_graph_routing_outcomes_fall_back_without_losing_valid_identity(
    tmp_path: Path,
    content: bytes | None,
    provider_failure: bool,
    expected_hash: str,
    expected_warning: str,
) -> None:
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider, resolve_graph_routing_outcome

    graph_file = tmp_path / "graphify-out" / "graph.json"
    graph_file.parent.mkdir()
    if content is not None:
        graph_file.write_bytes(content)

    class Provider(JsonGraphifyProvider):
        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            if provider_failure:
                return None
            return super().query(goal, graph_path, token_budget=token_budget)

    outcome = resolve_graph_routing_outcome(tmp_path, "graphify-out/graph.json", "unmatched", Provider(graph_file, tmp_path))

    assert outcome.use_lexical_fallback is True
    assert expected_warning in outcome.warning
    if expected_hash == "raw":
        import hashlib
        assert outcome.snapshot_hash == hashlib.sha256(content).hexdigest()
    else:
        assert outcome.snapshot_hash == ""


@pytest.mark.parametrize("failure_point", ("verify", "query", "validate"))
def test_graph_routing_outcome_degrades_when_an_optional_provider_raises(
    tmp_path: Path, failure_point: str
) -> None:
    """A valid snapshot identity survives every optional-provider runtime failure."""
    from sacas.graphify import GraphifyProvider, resolve_graph_routing_outcome

    graph_file = tmp_path / "custom-output" / "graph.json"
    graph_file.parent.mkdir()
    raw = b'{"nodes": [{"id": "src/auth.py"}], "edges": []}'
    graph_file.write_bytes(raw)

    class RaisingProvider(GraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            if failure_point == "verify":
                raise RuntimeError("optional provider failed")
            return True

        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            if failure_point == "query":
                raise RuntimeError("optional provider failed")
            from sacas.graphify import GraphifyQueryResult
            return GraphifyQueryResult("success", (), (), "", ("src/auth.py",))

        def validate_query_contract(self, result: object) -> bool:
            if failure_point == "validate":
                raise RuntimeError("optional provider failed")
            return True

        def neighbors(self, path: str):
            return []

        def communities(self):
            return ()

        def locate_symbol(self, file_path: str, symbol_name: str):
            return None

    outcome = resolve_graph_routing_outcome(
        tmp_path, "custom-output/graph.json", "auth", RaisingProvider()
    )

    import hashlib
    assert outcome.snapshot_hash == hashlib.sha256(raw).hexdigest()
    assert outcome.use_lexical_fallback is True
    assert outcome.query_result is None
    assert "sacas map" in outcome.warning
    assert "task reroute" in outcome.warning


def test_graph_routing_outcome_tells_user_how_to_retry_a_valid_no_match(tmp_path: Path) -> None:
    from sacas.graphify import resolve_graph_routing_outcome

    graph_file = tmp_path / "graphify-out" / "graph.json"
    graph_file.parent.mkdir()
    graph_file.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    outcome = resolve_graph_routing_outcome(
        tmp_path, "graphify-out/graph.json", "missing", JsonGraphifyProvider(graph_file, tmp_path)
    )

    assert "sacas map" in outcome.warning
    assert "task reroute" in outcome.warning
