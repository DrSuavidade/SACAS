"""Initialize SACAS filesystem state without overwriting human content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sacas.io import stable_json, write_text_atomic
from sacas.models import Manifest
from sacas.paths import MANIFEST_RELATIVE_PATH, Installation, resolve_sacas_root
from sacas.templates import boundaries_document, router_document


@dataclass(frozen=True, slots=True)
class InitResult:
    """Resolved installation and whether initialization changed any file."""

    installation: Installation
    changed: bool

    @property
    def sacas_root(self) -> Path:
        return self.installation.sacas_root


def initialize(repository_root: Path | str, *, sacas_root: str = "Structure") -> InitResult:
    """Create the canonical SACAS layout, preserving human-authored documents."""
    repository_root = Path(repository_root).resolve()
    resolved_root = resolve_sacas_root(repository_root, sacas_root)
    manifest = Manifest(repository_root=".", sacas_root=sacas_root.replace("\\", "/"))
    manifest_path = resolved_root / MANIFEST_RELATIVE_PATH
    changed = False

    for directory in (
        resolved_root / ".sacas",
        resolved_root / "rules",
        resolved_root / "map",
        resolved_root / "tasks" / "current",
        resolved_root / "references",
    ):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            changed = True

    changed |= _write_if_changed(manifest_path, stable_json(manifest.to_dict()))
    router_path = resolved_root / "ROUTER.md"
    existing_router = router_path.read_text(encoding="utf-8") if router_path.exists() else None
    changed |= _write_if_changed(router_path, router_document(existing_router))
    boundaries_path = resolved_root / "rules" / "boundaries.md"
    if not boundaries_path.exists():
        write_text_atomic(boundaries_path, boundaries_document())
        changed = True

    installation = Installation(repository_root, resolved_root, manifest_path, manifest)
    return InitResult(installation=installation, changed=changed)


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    write_text_atomic(path, content)
    return True
