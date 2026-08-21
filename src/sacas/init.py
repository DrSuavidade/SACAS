"""Initialize SACAS filesystem state without overwriting human content."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from sacas.adapters import DEFAULT_ADAPTERS, generate_adapters
from sacas.io import stable_json, write_text_atomic
from sacas.models import Manifest
from sacas.paths import (
    DEFAULT_SACAS_ROOT,
    LOCATOR_RELATIVE_PATH,
    MANIFEST_RELATIVE_PATH,
    Installation,
    discover_manifest,
    resolve_sacas_root,
)
from sacas.templates import (
    boundaries_document,
    router_document,
    claude_md_document,
    workspace_context_document,
    stage_context_template,
    config_conventions_document,
    config_voice_document,
    config_design_system_document,
    stage_output_readme,
)


@dataclass(frozen=True, slots=True)
class InitResult:
    """Resolved installation and whether initialization changed any file."""

    installation: Installation
    changed: bool

    @property
    def sacas_root(self) -> Path:
        return self.installation.sacas_root


def initialize(repository_root: Path | str, *, sacas_root: str = "Structure", graphify_mode: str = "off", workflow: bool = False) -> InitResult:
    """Create the canonical SACAS layout, preserving human-authored documents.
    
    By default creates a lean context-router structure.
    With workflow=True, also creates the ICM 5-layer pipeline structure.
    """
    repository_root = Path(repository_root).resolve()
    resolved_root = resolve_sacas_root(repository_root, sacas_root)
    configured_root = sacas_root.replace("\\", "/")
    if workflow and resolved_root == repository_root:
        raise ValueError(
            "workflow initialization cannot use the repository root because its "
            "workspace CLAUDE.md collides with the repository-root Claude adapter."
        )
    existing_installation = discover_manifest(repository_root)
    if existing_installation is not None and existing_installation.sacas_root != resolved_root:
        raise ValueError(
            "SACAS is already configured at "
            f"{existing_installation.sacas_root}; refusing to create a second install at "
            f"{resolved_root}."
        )
    manifest_path = resolved_root / MANIFEST_RELATIVE_PATH
    manifest = _load_manifest(manifest_path) if manifest_path.is_file() else Manifest(
        repository_root=".", sacas_root=configured_root, graphify_mode=graphify_mode
    )
    if manifest.sacas_root != configured_root:
        raise ValueError(
            f"Existing manifest configures sacas_root={manifest.sacas_root!r}; "
            f"requested {configured_root!r}."
        )
    changed = False

    # Core directory structure (always created)
    for directory in (
        resolved_root / ".sacas",
        resolved_root / "rules",
        resolved_root / "map",
        resolved_root / "references",
        resolved_root / "tasks" / "backlog",
        resolved_root / "tasks" / "current",
        resolved_root / "tasks" / "completed",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            changed = True

    # Optional ICM workflow directories
    if workflow:
        for directory in (
            resolved_root / "_config",
            resolved_root / "stages" / "01_analyze" / "references",
            resolved_root / "stages" / "01_analyze" / "output",
            resolved_root / "stages" / "02_implement" / "references",
            resolved_root / "stages" / "02_implement" / "output",
            resolved_root / "stages" / "03_verify" / "references",
            resolved_root / "stages" / "03_verify" / "output",
        ):
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                changed = True

    # Manifest
    if not manifest_path.exists():
        changed |= _write_if_changed(manifest_path, stable_json(manifest.to_dict()))
    if configured_root not in (".", DEFAULT_SACAS_ROOT):
        locator = {"manifest": manifest_path.relative_to(repository_root).as_posix()}
        changed |= _write_if_changed(repository_root / LOCATOR_RELATIVE_PATH, stable_json(locator))

    # Optional ICM workflow files
    if workflow:
        # Layer 0/1: Workflow workspace contracts. These are intentionally
        # opt-in; repository-root adapters remain core artifacts below.
        claude_path = resolved_root / "CLAUDE.md"
        if not claude_path.exists():
            write_text_atomic(claude_path, claude_md_document())
            changed = True

        context_path = resolved_root / "CONTEXT.md"
        if not context_path.exists():
            write_text_atomic(context_path, workspace_context_document())
            changed = True

        # Layer 2: Stage CONTEXT.md contracts
        stage_configs = [
            (1, "analyze", "Analyze codebase, understand requirements, produce structured analysis"),
            (2, "implement", "Implement changes based on analysis output, follow conventions"),
            (3, "verify", "Test, validate, and verify implementation against requirements"),
        ]
        for stage_num, stage_name, purpose in stage_configs:
            stage_context_path = resolved_root / "stages" / f"{stage_num:02d}_{stage_name}" / "CONTEXT.md"
            if not stage_context_path.exists():
                write_text_atomic(stage_context_path, stage_context_template(stage_num, stage_name, purpose))
                changed = True
            
            # Stage output README
            output_readme_path = resolved_root / "stages" / f"{stage_num:02d}_{stage_name}" / "output" / "README.md"
            if not output_readme_path.exists():
                write_text_atomic(output_readme_path, stage_output_readme(stage_num, stage_name))
                changed = True

        # Layer 3: Global stable references (_config/)
        config_files = [
            ("conventions.md", config_conventions_document()),
            ("voice.md", config_voice_document()),
            ("design-system.md", config_design_system_document()),
        ]
        for filename, content in config_files:
            config_path = resolved_root / "_config" / filename
            if not config_path.exists():
                write_text_atomic(config_path, content)
                changed = True

    # Router and boundaries (always)
    router_path = resolved_root / "ROUTER.md"
    existing_router = router_path.read_text(encoding="utf-8") if router_path.exists() else None
    changed |= _write_if_changed(router_path, router_document(existing_router))
    boundaries_path = resolved_root / "rules" / "boundaries.md"
    if not boundaries_path.exists():
        write_text_atomic(boundaries_path, boundaries_document())
        changed = True

    # Adapters
    adapters = manifest.adapters or DEFAULT_ADAPTERS
    changed |= generate_adapters(
        repository_root,
        configured_root,
        platforms=adapters,
        graphify_output=manifest.graphify_output,
    )

    installation = Installation(repository_root, resolved_root, manifest_path, manifest)
    return InitResult(installation=installation, changed=changed)


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    write_text_atomic(path, content)
    return True


def _load_manifest(path: Path) -> Manifest:
    with path.open(encoding="utf-8") as source:
        return Manifest.from_dict(json.load(source))
