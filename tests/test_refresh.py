"""Behavioral tests for SACAS context refresh, progressive expansion, and status."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_status_command_requires_task_or_reports_none(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    init_result = initialize(tmp_path)
    
    # Run status before any task is created
    exit_code = main(["status", "--root", str(tmp_path), "--format", "json"])
    assert exit_code == 0


def test_refresh_and_status_behavior(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    
    init_result = initialize(tmp_path)
    
    # Create a task
    main([
        "task",
        "Test goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
    # Write src/app.py
    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("print('hello')", encoding="utf-8")
    
    # Write Graphify evidence with some edges for app.py
    # Let's say app.py is called by src/caller.py and has tests/test_app.py
    graphify_manifest_path = init_result.sacas_root / ".sacas" / "graphify.json"
    evidence_data = {
        "output": "graphify-out",
        "status": "fresh",
        "provenance": "graphify_existing",
        "freshness": "fresh",
        "content_hash": "dummyhash",
        "nodes": [
            ["node_app", "src/app.py"],
            ["node_caller", "src/caller.py"],
            ["node_test", "tests/test_app.py"]
        ],
        "edges": [
            ["node_caller", "node_app", "calls"],
            ["node_test", "node_app", "tests"]
        ]
    }
    graphify_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    graphify_manifest_path.write_text(json.dumps(evidence_data), encoding="utf-8")
    
    # Also write a boundary to verify protected boundary refusal
    boundaries_file = init_result.sacas_root / "rules" / "boundaries.md"
    boundaries_file.write_text(
        "MANUAL src/caller.py | Do not expand caller\n", encoding="utf-8"
    )
    
    # Now run refresh to trigger expansion
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # Verify tests/test_app.py was expanded (not protected), but src/caller.py was refused (protected)
    task_dir = init_result.sacas_root / "tasks" / "current"
    expansions_path = task_dir / "expansions.json"
    assert expansions_path.is_file()
    
    expansions = json.loads(expansions_path.read_text(encoding="utf-8"))
    initial_paths = [item["path"] for item in expansions.get("initial_scope", [])]
    expanded_paths = [item["path"] for item in expansions.get("expansions", [])]
    assert "src/app.py" in initial_paths
    assert "tests/test_app.py" in expanded_paths
    assert "src/caller.py" not in expanded_paths
    
    # Verify CONTEXT.md has the expanded test file
    context_content = (task_dir / "CONTEXT.md").read_text(encoding="utf-8")
    assert "tests/test_app.py" in context_content
    
    # Now modify src/app.py to make it stale
    app_py.write_text("print('hello changed')", encoding="utf-8")
    
    # Verify status reports stale state
    # We capture output or call status logic directly
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    fresh_inst = discover_manifest(tmp_path)
    report = get_status_report(fresh_inst)
    assert report["status"] == "stale"
    assert "src/app.py" in report["stale_files"]


def test_refresh_predictive_budgeting_and_ranking(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    
    init_result = initialize(tmp_path)
    
    manifest_path = init_result.sacas_root / ".sacas" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["context_budget"] = 500
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    
    # Create a task
    main([
        "task",
        "Test budget goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
    # Write src/app.py
    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("print('hello')", encoding="utf-8")
    
    # Write Graphify evidence
    graphify_manifest_path = init_result.sacas_root / ".sacas" / "graphify.json"
    evidence_data = {
        "output": "graphify-out",
        "status": "fresh",
        "provenance": "graphify_existing",
        "freshness": "fresh",
        "content_hash": "dummyhash",
        "nodes": [
            ["node_app", "src/app.py"],
            ["node_caller", "src/caller.py"],
            ["node_test", "tests/test_app.py"]
        ],
        "edges": [
            ["node_caller", "node_app", "calls"],
            ["node_test", "node_app", "tests"]
        ]
    }
    graphify_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    graphify_manifest_path.write_text(json.dumps(evidence_data), encoding="utf-8")
    
    # Write caller.py and test_app.py
    caller_py = tmp_path / "src" / "caller.py"
    caller_py.parent.mkdir(parents=True, exist_ok=True)
    caller_py.write_text("print('caller')", encoding="utf-8")
    
    test_app_py = tmp_path / "tests" / "test_app.py"
    test_app_py.parent.mkdir(parents=True, exist_ok=True)
    test_app_py.write_text("print('test')\n" * 200, encoding="utf-8")

    
    # Refresh context
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    expansions = json.loads((task_dir / "expansions.json").read_text(encoding="utf-8"))
    
    # caller.py fits (4 + 3 = 7 <= 10)
    expanded_paths = [item["path"] for item in expansions.get("expansions", [])]
    assert "src/caller.py" in expanded_paths, f"expansions: {json.dumps(expansions, indent=2)}"
    
    # test_app.py is budget excluded (7 + 20 > 10)
    adjacent_paths = [item["path"] for item in expansions.get("adjacent", [])]
    assert "tests/test_app.py" in adjacent_paths
    
    adjacent_item = next(item for item in expansions.get("adjacent", []) if item["path"] == "tests/test_app.py")
    assert adjacent_item["excluded_reason"] == "budget"


def test_schema_migration_v1_to_v2(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.refresh import refresh_context
    import json
    
    init_result = initialize(tmp_path)
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    expansions_path = task_dir / "expansions.json"
    v1_data = {
        "initial_files": {"src/app.py": "hash_val"},
        "expanded_files": {"src/helper.py": "hash_val2"},
        "goal": "V1 task upgrade"
    }
    expansions_path.write_text(json.dumps(v1_data), encoding="utf-8")
    
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "app.py").write_text("print()", encoding="utf-8")
    (tmp_path / "src" / "helper.py").write_text("print()", encoding="utf-8")
    
    manifest_path = init_result.sacas_root / ".sacas" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["current_task_id"] = "task_v1"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    
    from sacas.paths import discover_manifest
    changed = refresh_context(discover_manifest(tmp_path))
    
    v2_data = json.loads(expansions_path.read_text(encoding="utf-8"))
    assert v2_data.get("schema_version") == 2
    assert "initial_scope" in v2_data
    assert "expansions" in v2_data
    
    initial_paths = [item["path"] for item in v2_data["initial_scope"]]
    assert "src/app.py" in initial_paths
    
    expanded_paths = [item["path"] for item in v2_data["expansions"]]
    assert "src/helper.py" in expanded_paths


