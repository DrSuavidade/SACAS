"""Behavioral tests for legacy structure migration."""

from __future__ import annotations

import shutil
from pathlib import Path


def test_migrate_command_dry_run_and_apply(tmp_path: Path) -> None:
    from sacas.cli import main

    # Copy legacy fixture
    legacy_fixture = Path(__file__).parent / "fixtures" / "legacy-sacas"
    temp_repo = tmp_path / "legacy-repo"
    shutil.copytree(legacy_fixture, temp_repo)

    # Dry run
    exit_code = main(["migrate", "--root", str(temp_repo)])
    assert exit_code == 0
    # Files should not be modified
    assert (temp_repo / "Structure" / "tasks" / "current" / "PROGRESS.md").is_file()
    assert not (temp_repo / "Structure" / ".sacas" / "manifest.json").is_file()

    # Apply migration
    exit_code = main(["migrate", "--root", str(temp_repo), "--apply"])
    assert exit_code == 0

    # PROGRESS.md should be migrated into the canonical task contract and removed
    assert not (temp_repo / "Structure" / "tasks" / "current" / "PROGRESS.md").exists()
    assert (temp_repo / "Structure" / ".sacas" / "manifest.json").is_file()

    contract_content = (temp_repo / "Structure" / "tasks" / "current" / "task.json").read_text(encoding="utf-8")
    assert "Step 1: Initial setup" in contract_content
