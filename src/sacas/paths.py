"""Locate the one canonical SACAS installation for a repository."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from sacas.models import Manifest


MANIFEST_RELATIVE_PATH = Path(".sacas") / "manifest.json"


@dataclass(frozen=True, slots=True)
class Installation:
    """Resolved filesystem locations and parsed manifest for an installation."""

    repository_root: Path
    sacas_root: Path
    manifest_path: Path
    manifest: Manifest


def resolve_sacas_root(repository_root: Path, configured_root: str) -> Path:
    """Resolve a SACAS root while rejecting paths that escape the repository."""
    root = repository_root.resolve()
    candidate = (root / configured_root).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("sacas_root must be inside the repository") from error
    return candidate


def discover_manifest(start: Path) -> Installation | None:
    """Find the nearest ancestor repository whose configured root owns a manifest."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for repository_root in (current, *current.parents):
        manifest_path = repository_root / MANIFEST_RELATIVE_PATH
        if manifest_path.is_file():
            found = _load_if_owned(repository_root, manifest_path)
            if found is not None:
                return found
        # The manifest itself remains canonical, including for intentionally nested
        # custom roots. Validate each candidate's configured root before accepting it.
        for child_manifest in sorted(repository_root.rglob(MANIFEST_RELATIVE_PATH.name)):
            if child_manifest.parent.name != ".sacas":
                continue
            found = _load_if_owned(repository_root, child_manifest)
            if found is not None:
                return found
    return None


def _load_if_owned(repository_root: Path, manifest_path: Path) -> Installation | None:
    with manifest_path.open(encoding="utf-8") as source:
        manifest = Manifest.from_dict(json.load(source))
    sacas_root = resolve_sacas_root(repository_root, manifest.sacas_root)
    if sacas_root / MANIFEST_RELATIVE_PATH != manifest_path.resolve():
        return None
    return Installation(
        repository_root=repository_root,
        sacas_root=sacas_root,
        manifest_path=manifest_path.resolve(),
        manifest=manifest,
    )
