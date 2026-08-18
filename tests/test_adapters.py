"""Behavioral contract for platform-neutral agent adapters and ignores."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("platform", "relative_path"),
    [
        ("codex", "AGENTS.md"),
        ("claude", "CLAUDE.md"),
        ("cursor", ".cursor/rules/sacas.mdc"),
        ("copilot", ".github/copilot-instructions.md"),
        ("gemini", "GEMINI.md"),
    ],
)
def test_adapter_generation_is_idempotent_and_preserves_manual_content(
    tmp_path: Path, platform: str, relative_path: str
) -> None:
    from sacas.adapters import generate_adapter

    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Team instructions\n\nKeep this manual note.\n", encoding="utf-8")

    assert generate_adapter(tmp_path, "Structure", platform) is True
    first = target.read_text(encoding="utf-8")
    assert "Keep this manual note." in first
    assert f"<!-- SACAS:START adapter-{platform} -->" in first
    assert f"<!-- SACAS:END adapter-{platform} -->" in first
    assert "Structure/ROUTER.md" in first

    assert generate_adapter(tmp_path, "Structure", platform) is False
    assert target.read_text(encoding="utf-8") == first


@pytest.mark.parametrize(
    ("platform", "relative_path"),
    [
        ("codex", ".aiignore"),
        ("claude", ".claudeignore"),
        ("cursor", ".cursorignore"),
        ("copilot", ".github/copilot-ignore"),
        ("gemini", ".geminiignore"),
    ],
)
def test_platform_ignore_is_bounded_preserves_manual_content_and_ignores_root_graphify_output(
    tmp_path: Path, platform: str, relative_path: str
) -> None:
    from sacas.adapters import generate_adapter_ignore

    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Keep this manual ignore\nprivate/\n", encoding="utf-8")

    assert generate_adapter_ignore(tmp_path, platform) is True
    first = target.read_text(encoding="utf-8")
    assert "# Keep this manual ignore" in first
    assert "private/" in first
    assert f"<!-- SACAS:START ignore-{platform} -->" in first
    assert "graphify-out/" in first
    assert "Structure/graphify-out/" not in first

    assert generate_adapter_ignore(tmp_path, platform) is False
    assert target.read_text(encoding="utf-8") == first


def test_init_generates_all_default_adapters_and_platform_ignores(tmp_path: Path) -> None:
    from sacas.init import initialize

    initialize(tmp_path)

    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / ".cursor/rules/sacas.mdc").is_file()
    assert (tmp_path / ".github/copilot-instructions.md").is_file()
    assert (tmp_path / "GEMINI.md").is_file()
    assert (tmp_path / ".aiignore").read_text(encoding="utf-8").count("graphify-out/") == 1
