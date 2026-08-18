"""End-to-end routing quality and loop verification test."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from sacas.cli import main
from sacas.paths import discover_manifest


def test_e2e_routing_loop(tmp_path: Path) -> None:
    # 1. Initialize tiny fixture repo with actual relations
    repo = tmp_path / "tiny-repo"
    repo.mkdir()
    
    # Create files
    src_dir = repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    
    auth_py = src_dir / "auth.py"
    auth_py.write_text("class SessionManager:\n    def restore_session(self):\n        pass\n", encoding="utf-8")
    
    session_py = src_dir / "session.py"
    session_py.write_text("from src.auth import SessionManager\n", encoding="utf-8")
    
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_auth_py = tests_dir / "test_auth.py"
    test_auth_py.write_text("def test_session():\n    pass\n", encoding="utf-8")

    # Initialize SACAS with Graphify code-only mode
    exit_code = main(["init", "--root", str(repo), "--graphify", "code-only"])
    assert exit_code == 0
    
    # Run map to extract Graphify graph
    exit_code = main(["map", "--root", str(repo), "--mode", "code-only"])
    assert exit_code == 0
    
    # Run task generation with no focus files, but goal containing "Session"
    exit_code = main(["task", "fix Session restoration", "--root", str(repo)])
    assert exit_code == 0
    
    # Verify TASK.md and expansions.json exist
    installation = discover_manifest(repo)
    assert installation is not None
    
    task_dir = installation.sacas_root / "tasks" / "current"
    expansions_path = task_dir / "expansions.json"
    assert expansions_path.is_file()
    
    expansions_data = json.loads(expansions_path.read_text(encoding="utf-8"))
    assert expansions_data.get("schema_version") == 2
    
    # Verify initial_scope has auth.py
    initial_scope = expansions_data.get("initial_scope", [])
    paths = [item["path"] for item in initial_scope]
    assert "src/auth.py" in paths
    
    # Check provenance
    auth_item = next(item for item in initial_scope if item["path"] == "src/auth.py")
    assert auth_item["source"] == "graphify"
    assert auth_item["relation"] == "seed"
    assert auth_item["trigger"] == "task_goal"
    assert auth_item["confidence"] == "high"
    
    # Run validate
    exit_code = main(["validate", "--root", str(repo)])
    assert exit_code == 0
    
    # Modify a file to make it stale and trigger refresh
    auth_py.write_text("class SessionManager:\n    def restore_session(self):\n        print('modified')\n", encoding="utf-8")
    
    # Run refresh
    exit_code = main(["refresh", "--root", str(repo)])
    assert exit_code == 0
    
    # Run status command
    exit_code = main(["status", "--root", str(repo), "--format", "json"])
    assert exit_code == 0


def test_e2e_routing_fallback_on_incompatible_graphify(tmp_path: Path) -> None:
    # Test fallback to heuristics when graphify is missing or incompatible
    repo = tmp_path / "tiny-repo-fallback"
    repo.mkdir()
    
    src_dir = repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    
    auth_py = src_dir / "auth.py"
    auth_py.write_text("class AuthProvider:\n    pass\n", encoding="utf-8")
    
    # Initialize with graphify off
    exit_code = main(["init", "--root", str(repo), "--graphify", "off"])
    assert exit_code == 0
    
    # Generate task without --files
    exit_code = main(["task", "fix Auth authentication logic", "--root", str(repo)])
    assert exit_code == 0
    
    installation = discover_manifest(repo)
    assert installation is not None
    task_dir = installation.sacas_root / "tasks" / "current"
    
    expansions_data = json.loads((task_dir / "expansions.json").read_text(encoding="utf-8"))
    initial_scope = expansions_data.get("initial_scope", [])
    paths = [item["path"] for item in initial_scope]
    
    # Heuristics should discover auth.py
    assert "src/auth.py" in paths
    auth_item = next(item for item in initial_scope if item["path"] == "src/auth.py")
    assert auth_item["source"] == "heuristic"
    assert auth_item["relation"] == "keyword_match"
