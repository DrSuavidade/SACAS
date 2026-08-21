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


def test_validate_reports_invalid_symbol_range_for_a_readable_file(tmp_path: Path) -> None:
    """Range validation must run after a successful source read too."""
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.validate import run_diagnostics

    initialization = initialize(tmp_path)
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("def app():\n    return 1\n", encoding="utf-8")
    assert main(["task", "Validate a range", "--root", str(tmp_path), "--files", "src/app.py"]) == 0

    context_path = initialization.sacas_root / "tasks" / "current" / "active_context.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    context["files"][0]["selection"] = {
        "mode": "symbols",
        "symbols": [{
            "name": "app",
            "range": {"start_line": 3, "end_line": 1, "source": "explicit", "confidence": 1.0},
            "reason": "test",
        }],
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")

    report = run_diagnostics(tmp_path)

    assert any(item["check"] == "invalid_range" for item in report["diagnostics"])


def test_validate_detects_empty_scope(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.validate import run_diagnostics

    init_result = initialize(tmp_path)
    
    # Create task with empty files
    main([
        "task",
        "Test goal with empty files",
        "--root", str(tmp_path)
    ])
    
    # Empty task on disk - expansions.json initial_scope will be empty if Graphify is off and no fallback matches
    # Let's ensure Graphify mode is off to force fallback (which also yields empty since there are no files in tmp_path!)
    report = run_diagnostics(tmp_path)
    assert any(item["check"] == "empty_scope" for item in report["diagnostics"])


def test_corrupt_context_pack_is_reported_by_status_and_validate(tmp_path: Path) -> None:
    """Runtime consumers report malformed JSONL rather than leaking parser exceptions."""
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    from sacas.validate import run_diagnostics

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    assert main(["task", "Corrupt pack", "--root", str(tmp_path), "--files", "src/app.py"]) == 0
    pack_path = initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    pack_path.write_text("[]\n", encoding="utf-8")

    report = get_status_report(discover_manifest(tmp_path))
    diagnostics = run_diagnostics(tmp_path)

    assert report["status"] == "invalid_context_pack"
    assert any(item["check"] == "invalid_context_pack" for item in diagnostics["diagnostics"])


def test_validate_marks_changed_canonical_rules_and_references_stale(tmp_path: Path) -> None:
    """Rules and references are canonical admissions, not optional display material."""
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    from sacas.tasks import generate_task
    from sacas.validate import run_diagnostics

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    rule = initialized.sacas_root / "rules" / "task.md"
    reference = initialized.sacas_root / "references" / "task.md"
    rule.write_text("# Rule\n", encoding="utf-8")
    reference.write_text("# Reference\n", encoding="utf-8")
    generate_task(
        initialized.installation,
        "Canonical support artifacts",
        files=("src/app.py",),
        rules=("Structure/rules/task.md",),
        references=("Structure/references/task.md",),
    )
    rule.write_text("# Changed rule\n", encoding="utf-8")
    reference.unlink()

    report = run_diagnostics(tmp_path)
    status = get_status_report(discover_manifest(tmp_path))

    messages = [item["message"] for item in report["diagnostics"]]
    assert any("Structure/rules/task.md" in message for message in messages)
    assert any("Structure/references/task.md" in message for message in messages)
    assert {"Structure/rules/task.md", "Structure/references/task.md"}.issubset(status["stale_files"])


