from __future__ import annotations

import json
from pathlib import Path
from sacas.graphify import CliGraphifyProvider, JsonGraphifyProvider
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

    result = provider.query("anything", graph_file)
    assert result is not None
    assert result.status == "success"
    assert "src/a.py" in result.paths
    assert "src/b.py" in result.paths

def test_fake_graphify_provider() -> None:
    provider = FakeGraphifyProvider(capable=True, mock_paths=("src/c.py",))
    assert provider.verify_capabilities([]) is True

    result = provider.query("anything", Path("dummy"))
    assert result is not None
    assert result.paths == ("src/c.py",)
    assert provider.queries_received == [("anything", Path("dummy"))]
