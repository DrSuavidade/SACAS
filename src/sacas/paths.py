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
    """Resolve a SACAS root while rejecting paths that escape or claim the repository.

    A SACAS installation must live in a proper child directory of the
    repository so generic names like ``rules/`` or ``tasks/`` never collide
    with pre-existing project folders at the repository root.
    """
    root = repository_root.resolve()
    candidate = (root / configured_root).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("sacas_root must be inside the repository") from error
    if relative == Path("."):
        raise ValueError(
            "sacas_root must be a proper child of the repository; "
            "installing at the repository root is not supported"
        )
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
        raise ValueError(f"SACAS root locator points to a missing manifest: {manifest_path}")
    return _load_if_owned(repository_root, manifest_path)


def sacas_root_posix(repository_root: Path, sacas_root: Path) -> str:
    """Return the repository-relative POSIX name of a SACAS installation root."""
    root_resolved = Path(repository_root).resolve()
    candidate = Path(sacas_root)
    try:
        return candidate.resolve().relative_to(root_resolved).as_posix()
    except ValueError as error:
        raise ValueError("sacas_root must be inside the repository") from error


def sacas_child_repo_path(repository_root: Path, sacas_root: Path, child: str | Path = "") -> str:
    """Convert ``sacas_root + child`` into a repository-relative POSIX path."""
    prefix = sacas_root_posix(repository_root, sacas_root)
    child_text = str(child).replace("\\", "/").strip("/")
    if child_text in ("", "."):
        return prefix
    return f"{prefix}/{child_text}" if prefix != "." else child_text


def sacas_generated_exclusions(repository_root: Path, sacas_root: Path) -> tuple[str, ...]:
    """Repository-relative roots SACAS generates and must never route against."""
    return (sacas_root_posix(repository_root, sacas_root), "graphify-out", ".worktrees")


def normalize_sacas_document_path(repository_root: Path, sacas_root: Path, path: str) -> str:
    """Normalize a user-supplied SACAS document path beneath the installation root.

    Paths already expressed under the installation's root are preserved;
    everything else is treated as a child of that root. The resolved path
    must remain inside the SACAS installation, so ``..`` components cannot
    move a rule or reference into ordinary repository sources.
    """
    prefix = sacas_root_posix(repository_root, sacas_root)
    cleaned = path.replace("\\", "/").strip("/")
    from pathlib import PureWindowsPath

    if (
        not cleaned
        or path.startswith("/") 
        or Path(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or (len(path) > 1 and path[1] == ":")
    ):
        raise ValueError(f"Invalid SACAS document path: {path}")
    if cleaned == prefix or cleaned.startswith(f"{prefix}/"):
        candidate = cleaned
    else:
        candidate = f"{prefix}/{cleaned}"

    repo_resolved = Path(repository_root).resolve()
    try:
        relative = (repo_resolved / candidate).resolve().relative_to(repo_resolved)
        relative.relative_to(Path(prefix))
    except ValueError as error:
        raise ValueError(
            f"SACAS document path must remain inside the SACAS root: {path}"
        ) from error
    return relative.as_posix()


def resolve_repo_path(repository_root: Path, user_path: str | Path) -> str:
    """Resolve and normalize a user path inside the repository.

    Rejects absolute paths, escaping paths (e.g. via ../), and symlink escapes.
    Returns the relative path with forward slashes.
    """
    repo_resolved = repository_root.resolve()

    from pathlib import PureWindowsPath
    path_str = str(user_path).replace("\\", "/")
    if (path_str.startswith("/") or 
            Path(path_str).is_absolute() or 
            PureWindowsPath(path_str).is_absolute() or
            (len(path_str) > 1 and path_str[1] == ":")):
        raise ValueError("Absolute paths are not allowed")

    candidate = (repo_resolved / path_str).resolve()

    try:
        relative = candidate.relative_to(repo_resolved)
    except ValueError as error:
        raise ValueError("Path escapes repository root") from error

    return relative.as_posix()

