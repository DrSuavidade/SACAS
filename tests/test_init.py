"""Behavioral contract for SACAS installation roots and initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


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


def test_default_init_omits_workflow_only_workspace_artifacts(tmp_path: Path) -> None:
    from sacas.init import initialize

    initialize(tmp_path)

    assert (tmp_path / "CLAUDE.md").is_file()  # The repository-root Claude adapter is core.
    assert not (tmp_path / "Structure" / "CLAUDE.md").exists()
    assert not (tmp_path / "Structure" / "CONTEXT.md").exists()
    assert not (tmp_path / "Structure" / "_config").exists()
    assert not (tmp_path / "Structure" / "stages").exists()


def test_workflow_init_creates_workspace_artifacts(tmp_path: Path) -> None:
    from sacas.init import initialize

    initialize(tmp_path, workflow=True)

    assert (tmp_path / "Structure" / "CLAUDE.md").is_file()
    assert (tmp_path / "Structure" / "CONTEXT.md").is_file()
    assert (tmp_path / "Structure" / "_config" / "conventions.md").is_file()
    assert (tmp_path / "Structure" / "stages" / "01_analyze" / "CONTEXT.md").is_file()


def test_workflow_init_refuses_repository_root_placement_before_writing(tmp_path: Path) -> None:
    from sacas.init import initialize

    with pytest.raises(ValueError, match="workflow.*repository root"):
        initialize(tmp_path, sacas_root=".", workflow=True)

    assert not any(tmp_path.iterdir())


def test_lean_reinit_preserves_existing_workflow_artifacts_and_human_content(tmp_path: Path) -> None:
    from sacas.init import initialize

    initialize(tmp_path, workflow=True)
    workflow_context = tmp_path / "Structure" / "CONTEXT.md"
    workflow_context.write_text("# Human workflow note\n", encoding="utf-8")

    initialize(tmp_path)

    assert workflow_context.read_text(encoding="utf-8") == "# Human workflow note\n"
    assert (tmp_path / "Structure" / "_config" / "conventions.md").is_file()
    assert (tmp_path / "Structure" / "stages" / "03_verify" / "CONTEXT.md").is_file()


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


def test_repeat_init_preserves_existing_valid_manifest_configuration(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.models import Manifest

    initialize(tmp_path)
    manifest_path = tmp_path / "Structure" / ".sacas" / "manifest.json"
    configured = Manifest(
        graphify_mode="semantic",
        adapters=("codex",),
        context_budget=5_000,
        current_task_id="task-123",
    )
    manifest_path.write_text(json.dumps(configured.to_dict()), encoding="utf-8")

    result = initialize(tmp_path)

    assert result.changed is False
    assert result.installation.manifest == configured
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == configured.to_dict()


def test_manifest_discovery_does_not_select_a_sibling_installation(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.paths import discover_manifest

    sibling = tmp_path / "sibling"
    target = tmp_path / "target"
    initialize(sibling)
    target.mkdir()

    assert discover_manifest(target) is None


def test_manifest_discovery_does_not_select_a_descendant_installation(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.paths import discover_manifest

    initialize(tmp_path / "nested")

    assert discover_manifest(tmp_path) is None


@pytest.mark.parametrize("requested_root", ["Structure", "other-sacas"])
def test_init_refuses_to_create_a_second_install_from_a_custom_install(
    tmp_path: Path, requested_root: str
) -> None:
    from sacas.init import initialize

    initialize(tmp_path, sacas_root="custom-sacas")
    locator_path = tmp_path / ".sacas" / "root.json"
    before_locator = locator_path.read_bytes()

    with pytest.raises(ValueError, match="already configured"):
        initialize(tmp_path, sacas_root=requested_root)

    assert locator_path.read_bytes() == before_locator
    assert not (tmp_path / requested_root / ".sacas" / "manifest.json").exists()


def test_cli_init_accepts_its_text_root_argument(tmp_path: Path) -> None:
    from sacas.cli import main

    assert main(("init", "--root", str(tmp_path))) == 0
    assert (tmp_path / "Structure" / ".sacas" / "manifest.json").is_file()
