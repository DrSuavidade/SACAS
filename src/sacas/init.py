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
from sacas.templates import boundaries_document, router_document


@dataclass(frozen=True, slots=True)
class InitResult:
    """Resolved installation and whether initialization changed any file."""

    installation: Installation
    changed: bool

    @property
    def sacas_root(self) -> Path:
        return self.installation.sacas_root


def initialize(repository_root: Path | str, *, sacas_root: str = "Structure", graphify_mode: str = "off") -> InitResult:
    """Create the canonical SACAS layout, preserving human-authored documents."""
    repository_root = Path(repository_root).resolve()
    resolved_root = resolve_sacas_root(repository_root, sacas_root)
    configured_root = sacas_root.replace("\\", "/")
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

    # Manifest
    if not manifest_path.exists():
        changed |= _write_if_changed(manifest_path, stable_json(manifest.to_dict()))
    if configured_root != DEFAULT_SACAS_ROOT:
        locator = {"manifest": manifest_path.relative_to(repository_root).as_posix()}
        changed |= _write_if_changed(repository_root / LOCATOR_RELATIVE_PATH, stable_json(locator))

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
