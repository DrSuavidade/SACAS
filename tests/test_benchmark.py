"""Behavioral tests for SACAS lab benchmark command."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_benchmark_command(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    init_result = initialize(tmp_path)

    # Create task
    main([
        "task",
        "Benchmark goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])

    # Run benchmark command
    exit_code = main(["lab", "benchmark", "--root", str(tmp_path), "--format", "json"])
    assert exit_code == 0


def test_context_simulation_command_removed(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    initialize(tmp_path)
    with pytest.raises(SystemExit):
        main(["context-simulation", "--root", str(tmp_path), "--format", "json"])


def test_benchmark_json_returns_nonzero_for_corrupt_canonical_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    assert main(["task", "Corrupt benchmark", "--root", str(tmp_path), "--files", "src/app.py"]) == 0
    (initialized.sacas_root / "tasks" / "current" / "active_context.json").write_text("{bad", encoding="utf-8")

    assert main(["lab", "benchmark", "--root", str(tmp_path), "--format", "json"]) == 1
    assert json.loads(capsys.readouterr().out)["error"].startswith("Canonical task state is corrupt")
