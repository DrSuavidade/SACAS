"""Behavioral tests for cold-agent validation diagnostic suite."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_validate_command_runs_diagnostics(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    init_result = initialize(tmp_path)
    
    # Run validate command
    exit_code = main(["validate", "--root", str(tmp_path), "--format", "json"])
    assert exit_code == 0
    
    # We should have no active task, but it should validate manifest successfully


def test_validate_detects_legacy_progress_file(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.validate import run_diagnostics

    init_result = initialize(tmp_path)
    
    # Create task
    main([
        "task",
        "Goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
    # Write legacy PROGRESS.md
    task_dir = init_result.sacas_root / "tasks" / "current"
    (task_dir / "PROGRESS.md").write_text("Legacy progress tracking", encoding="utf-8")
    
    report = run_diagnostics(tmp_path)
    assert report["status"] == "FAIL"
    assert any(item["check"] == "state_drift" for item in report["diagnostics"])


def test_validate_detects_malformed_regions(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.validate import run_diagnostics

    init_result = initialize(tmp_path)
    
    # Malform ROUTER.md by removing END tag
    router_file = init_result.sacas_root / "ROUTER.md"
    router_file.write_text("<!-- SACAS:START router -->\nContent", encoding="utf-8")
    
    report = run_diagnostics(tmp_path)
    assert report["status"] == "FAIL"
    assert any(item["check"] == "malformed_regions" for item in report["diagnostics"])


def test_validate_detects_budget_overrun(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.validate import run_diagnostics

    init_result = initialize(tmp_path)
    
    # Write app.py with a large content
    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("A" * 50000, encoding="utf-8") # ~12,500 tokens (limit is 12,000)
    
    # Create task
    main([
        "task",
        "Goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
    report = run_diagnostics(tmp_path)
    assert report["status"] == "WARNING"
    assert any(item["check"] == "budget_limit" for item in report["diagnostics"])

