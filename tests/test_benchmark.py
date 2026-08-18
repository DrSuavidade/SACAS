"""Behavioral tests for SACAS benchmark command."""

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
    exit_code = main(["benchmark", "--root", str(tmp_path), "--format", "json"])
    assert exit_code == 0
