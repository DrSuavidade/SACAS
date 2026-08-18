"""Behavioral contract for SACAS installation roots and initialization."""

from __future__ import annotations

from pathlib import Path


def test_init_creates_default_structure_root_and_canonical_manifest(tmp_path: Path) -> None:
    from sacas.init import initialize

    result = initialize(tmp_path)

    assert result.sacas_root == tmp_path / "Structure"
    assert (tmp_path / "Structure" / ".sacas" / "manifest.json").is_file()
    assert (tmp_path / "Structure" / "ROUTER.md").is_file()
    assert (tmp_path / "Structure" / "rules").is_dir()
    assert (tmp_path / "Structure" / "map").is_dir()
    assert (tmp_path / "Structure" / "tasks" / "current").is_dir()
    assert (tmp_path / "Structure" / "references").is_dir()
    assert "sacas validate" in (tmp_path / "Structure" / "ROUTER.md").read_text(encoding="utf-8")


def test_init_supports_a_custom_relative_root(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.paths import discover_manifest

    initialize(tmp_path, sacas_root=".project/sacas")
    discovered = discover_manifest(tmp_path)

    assert discovered is not None
    assert discovered.sacas_root == tmp_path / ".project" / "sacas"
    assert discovered.manifest.sacas_root == ".project/sacas"


def test_init_allows_intentional_repository_root_placement(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.paths import discover_manifest

    initialize(tmp_path, sacas_root=".")
    discovered = discover_manifest(tmp_path)

    assert (tmp_path / ".sacas" / "manifest.json").is_file()
    assert discovered is not None
    assert discovered.sacas_root == tmp_path
    assert discovered.manifest.sacas_root == "."


def test_init_preserves_existing_human_router_and_manual_content(tmp_path: Path) -> None:
    from sacas.init import initialize

    router = tmp_path / "Structure" / "ROUTER.md"
    router.parent.mkdir(parents=True)
    router.write_text("# Team router\n\nKeep this human note.\n", encoding="utf-8")

    initialize(tmp_path)
    rendered = router.read_text(encoding="utf-8")

    assert "Keep this human note." in rendered
    assert "<!-- SACAS:START router -->" in rendered
    assert "<!-- SACAS:END router -->" in rendered


def test_manifest_discovery_finds_canonical_root_from_nested_directory(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.paths import discover_manifest

    initialize(tmp_path)
    nested = tmp_path / "src" / "service" / "api"
    nested.mkdir(parents=True)

    discovered = discover_manifest(nested)

    assert discovered is not None
    assert discovered.repository_root == tmp_path
    assert discovered.sacas_root == tmp_path / "Structure"


def test_init_creates_manual_only_protected_boundary_rules_file(tmp_path: Path) -> None:
    from sacas.init import initialize

    initialize(tmp_path)
    rules = (tmp_path / "Structure" / "rules" / "boundaries.md").read_text(encoding="utf-8")

    assert "MANUAL" in rules
    assert "only MANUAL" in rules
    assert "Graphify" in rules


def test_second_unchanged_init_is_idempotent(tmp_path: Path) -> None:
    from sacas.init import initialize

    initialize(tmp_path)
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    result = initialize(tmp_path)
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert result.changed is False
    assert after == before


def test_cli_init_accepts_its_text_root_argument(tmp_path: Path) -> None:
    from sacas.cli import main

    assert main(("init", "--root", str(tmp_path))) == 0
    assert (tmp_path / "Structure" / ".sacas" / "manifest.json").is_file()
