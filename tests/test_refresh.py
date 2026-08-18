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
    assert "src/app.py" in expansions["initial_files"]
    assert "tests/test_app.py" in expansions["expanded_files"]
    assert "src/caller.py" not in expansions["expanded_files"]
    
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
