"""Locate the one canonical SACAS installation for a repository."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from sacas.models import Manifest


MANIFEST_RELATIVE_PATH = Path(".sacas") / "manifest.json"
LOCATOR_RELATIVE_PATH = Path(".sacas") / "root.json"
DEFAULT_SACAS_ROOT = "Structure"


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
    """Find an installation through ancestors and bounded canonical locations only."""
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for repository_root in (current, *current.parents):
        manifest_path = repository_root / MANIFEST_RELATIVE_PATH
        if manifest_path.is_file():
            found = _load_if_owned(repository_root, manifest_path)
            if found is not None:
                return found
        locator_path = repository_root / LOCATOR_RELATIVE_PATH
        if locator_path.is_file():
            found = _load_from_locator(repository_root, locator_path)
            if found is not None:
                return found
        default_manifest = repository_root / DEFAULT_SACAS_ROOT / MANIFEST_RELATIVE_PATH
        if default_manifest.is_file():
            found = _load_if_owned(repository_root, default_manifest)
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


def _load_from_locator(repository_root: Path, locator_path: Path) -> Installation | None:
    with locator_path.open(encoding="utf-8") as source:
        locator = json.load(source)
    if not isinstance(locator, dict) or not isinstance(locator.get("manifest"), str):
        raise ValueError(f"Invalid SACAS root locator: {locator_path}")
    manifest_path = (repository_root / locator["manifest"]).resolve()
    try:
        manifest_path.relative_to(repository_root)
    except ValueError as error:
        raise ValueError("SACAS root locator must point inside the repository") from error
    if not manifest_path.is_file():
        return None
    return _load_if_owned(repository_root, manifest_path)
