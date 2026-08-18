"""Real integration tests for GraphifyAdapter against the installed graphifyy package."""

from __future__ import annotations

import shutil
from pathlib import Path
import pytest


def test_graphify_adapter_real_flow(tmp_path: Path) -> None:
    from sacas.graphify import GraphifyAdapter
    
    # 1. Version and capabilities check
    adapter = GraphifyAdapter(tmp_path, tmp_path)
    version = adapter.get_installed_version()
    assert version is not None
    assert adapter.verify_capabilities(required=["extract", "query"]) is True
    
    # 2. Extract a tiny fixture repo
    repo = tmp_path / "tiny-repo"
    repo.mkdir()
    auth_py = repo / "auth.py"
    auth_py.write_text("class SessionManager:\n    def restore_session(self):\n        pass\n", encoding="utf-8")
    
    # Extract using adapter/real command
    success = adapter.extract_code_only(repo)
    assert success is True
    
    graph_json = repo / "graphify-out" / "graph.json"
    assert graph_json.is_file()
    
    # 3. Query the graph
    result = adapter.query("session", graph_path=graph_json)
    assert result is not None
    assert len(result.paths) > 0
    assert "auth.py" in result.paths


def test_graphify_adapter_incompatible_degradation() -> None:
    from sacas.graphify import GraphifyAdapter
    
    class MockAdapter(GraphifyAdapter):
        @classmethod
        def get_installed_version(cls) -> str | None:
            return "0.8.0" # too low
            
    adapter = MockAdapter(Path("."), Path("."))
    assert adapter.verify_capabilities(required=["extract", "query"]) is False
