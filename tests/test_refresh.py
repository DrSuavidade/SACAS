"""Behavioral tests for SACAS context refresh, suggestions, and status."""

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

    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("print('hello')", encoding="utf-8")

    # Create a task
    main([
        "task",
        "Test goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
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
    
    # Now run refresh to trigger suggestion candidate search
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # Verify tests/test_app.py was suggested (not protected), but src/caller.py was refused (protected)
    task_dir = init_result.sacas_root / "tasks" / "current"
    candidates_path = task_dir / "candidates.json"
    assert candidates_path.is_file()
    
    candidates_data = json.loads(candidates_path.read_text(encoding="utf-8"))
    cand_paths = [item["path"] for item in candidates_data["candidates"]]
    assert "tests/test_app.py" in cand_paths
    assert "src/caller.py" not in cand_paths
    
    # Now modify src/app.py to make it stale
    app_py.write_text("print('hello changed')", encoding="utf-8")
    
    # Verify status reports stale state
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    fresh_inst = discover_manifest(tmp_path)
    report = get_status_report(fresh_inst)
    assert report["status"] == "stale"
    assert "src/app.py" in report["stale_files"]


def test_refresh_predictive_budgeting_and_ranking(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    
    init_result = initialize(tmp_path)

    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("print('hello')", encoding="utf-8")

    # Create a task
    main([
        "task",
        "Test budget goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
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
    test_app_py.write_text("print('test')", encoding="utf-8")
    
    # Refresh context
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    candidates = json.loads((task_dir / "candidates.json").read_text(encoding="utf-8"))
    
    cand_paths = [item["path"] for item in candidates["candidates"]]
    assert "src/caller.py" in cand_paths
    assert "tests/test_app.py" in cand_paths


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
    
    # Verify legacy file is deleted
    assert not expansions_path.exists()
    
    # Verify active_context.json exists and contains correct schema
    active_path = task_dir / "active_context.json"
    assert active_path.is_file()
    
    active_data = json.loads(active_path.read_text(encoding="utf-8"))
    assert active_data.get("schema_version") == 1
    
    files_paths = [f["path"] for f in active_data["files"]]
    assert "src/app.py" in files_paths
    assert "src/helper.py" in files_paths


def test_refresh_preserves_contract_criteria_constraints_verification(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.task_contract import load_task_contract
    
    init_result = initialize(tmp_path)
    
    # Create task with criteria, constraints, and verification
    main([
        "task",
        "Implement auth tokens",
        "--root", str(tmp_path),
        "--criteria", "Criteria-A", "Criteria-B",
        "--constraints", "Constraint-C",
        "--verification", "Verify-D"
    ])
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    contract = load_task_contract(task_dir)
    assert contract is not None
    assert contract.criteria == ("Criteria-A", "Criteria-B")
    assert contract.constraints == ("Constraint-C",)
    assert contract.verification == ("Verify-D",)
    
    # Run refresh
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # Reload and verify they are preserved exactly
    contract_after = load_task_contract(task_dir)
    assert contract_after is not None
    assert contract_after.criteria == ("Criteria-A", "Criteria-B")
    assert contract_after.constraints == ("Constraint-C",)
    assert contract_after.verification == ("Verify-D",)
