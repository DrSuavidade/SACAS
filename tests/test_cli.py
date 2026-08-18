"""Behavioral contract for the public ``sacas`` command."""

from __future__ import annotations

import subprocess
import sys


def run_sacas(*arguments: str) -> subprocess.CompletedProcess[str]:
    import os
    from pathlib import Path
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parent.parent / "src")
    return subprocess.run(
        [sys.executable, "-m", "sacas", *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_help_describes_sacas_command() -> None:
    result = run_sacas("--help")

    assert result.returncode == 0
    assert "SACAS" in result.stdout
    assert "init" in result.stdout


def test_unknown_command_returns_argument_error() -> None:
    result = run_sacas("not-a-command")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_published_version_is_available_from_cli_and_package() -> None:
    from sacas import __version__

    result = run_sacas("--version")

    assert __version__ == "0.1.0"
    assert result.returncode == 0
    assert result.stdout.strip() == __version__
