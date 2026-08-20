"""Deterministic and atomic persistence helpers + secure repository reads."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import fnmatch
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator

from sacas.paths import resolve_repo_path


DEFAULT_MAX_BYTES = 1_000_000


@dataclass(frozen=True, slots=True)
class RepositoryTextFile:
    """An immutable source entry returned by secure repository enumeration."""

    path: str
    content: str

SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials*",
    "secrets*",
    "*.secret",
    "*.token",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "*.pfx",
    "*.p12",
)

IGNORE_DIRS = (
    ".git",
    ".sacas",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    "target",
)


def _is_secret_path(rel_path: str) -> bool:
    """Check if a relative path matches secret patterns."""
    name = Path(rel_path).name
    for pattern in SECRET_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _is_ignored_dir(rel_path: str) -> bool:
    """Check if path is in an ignored directory."""
    parts = Path(rel_path).parts
    for part in parts:
        if part in IGNORE_DIRS:
            return True
    return False


def _load_sacasignore(repo_root: Path) -> list[str]:
    """Load patterns from .sacasignore file."""
    ignore_file = repo_root / ".sacasignore"
    if not ignore_file.is_file():
        return []
    try:
        lines = ignore_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    patterns = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def _matches_sacasignore(rel_path: str, patterns: list[str]) -> bool:
    """Check if path matches any .sacasignore pattern."""
    for pattern in patterns:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(Path(rel_path).name, pattern):
            return True
    return False


def _is_binary(content: bytes) -> bool:
    """Heuristic check for binary content."""
    if b"\x00" in content:
        return True
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def read_repo_text(
    repository_root: Path,
    user_path: str,
    *,
    allow_ignored: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> str:
    """Safely read a text file from the repository.

    Validates path, rejects secret/ignored files, enforces size limit,
    and detects binary content.
    
    Secrets are ALWAYS rejected regardless of allow_ignored.
    allow_ignored only bypasses .sacasignore and ignored directories.
    """
    if max_bytes is None:
        max_bytes = DEFAULT_MAX_BYTES

    rel_path = resolve_repo_path(repository_root, user_path)

    # SECRET CHECK - ALWAYS ENFORCED
    if _is_secret_path(rel_path):
        raise ValueError(f"Secret file access denied: {rel_path}")

    # Ignored directory / .sacasignore - optionally bypassable
    if not allow_ignored:
        if _is_ignored_dir(rel_path):
            raise ValueError(f"Ignored directory access denied: {rel_path}")
        sacasignore_patterns = _load_sacasignore(repository_root)
        if _matches_sacasignore(rel_path, sacasignore_patterns):
            raise ValueError(f"Path matches .sacasignore: {rel_path}")

    abs_path = repository_root / rel_path

    if not abs_path.is_file():
        raise FileNotFoundError(f"File not found: {rel_path}")

    try:
        content_bytes = abs_path.read_bytes()
    except OSError as e:
        raise OSError(f"Cannot read file: {rel_path}") from e

    if len(content_bytes) > max_bytes:
        raise ValueError(f"File exceeds size limit ({max_bytes} bytes): {rel_path}")

    if _is_binary(content_bytes):
        raise ValueError(f"Binary file not allowed as text: {rel_path}")

    return content_bytes.decode("utf-8")


def read_repo_bytes(
    repository_root: Path,
    user_path: str,
    *,
    allow_ignored: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> bytes:
    """Safely read raw bytes from the repository (for hashing).
    
    Secrets are ALWAYS rejected regardless of allow_ignored.
    allow_ignored only bypasses .sacasignore and ignored directories.
    """
    if max_bytes is None:
        max_bytes = DEFAULT_MAX_BYTES

    rel_path = resolve_repo_path(repository_root, user_path)

    # SECRET CHECK - ALWAYS ENFORCED
    if _is_secret_path(rel_path):
        raise ValueError(f"Secret file access denied: {rel_path}")

    # Ignored directory / .sacasignore - optionally bypassable
    if not allow_ignored:
        if _is_ignored_dir(rel_path):
            raise ValueError(f"Ignored directory access denied: {rel_path}")
        sacasignore_patterns = _load_sacasignore(repository_root)
        if _matches_sacasignore(rel_path, sacasignore_patterns):
            raise ValueError(f"Path matches .sacasignore: {rel_path}")

    abs_path = repository_root / rel_path

    if not abs_path.is_file():
        raise FileNotFoundError(f"File not found: {rel_path}")

    try:
        content_bytes = abs_path.read_bytes()
    except OSError as e:
        raise OSError(f"Cannot read file: {rel_path}") from e

    if len(content_bytes) > max_bytes:
        raise ValueError(f"File exceeds size limit ({max_bytes} bytes): {rel_path}")

    return content_bytes


def read_repo_source_bytes(
    repository_root: Path,
    user_path: str,
    *,
    allow_ignored: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
) -> bytes:
    """Read hashable source bytes through the text-only repository boundary.

    Callers that treat a file as source must not silently accept binary or
    invalid UTF-8 data.  Encoding the validated text keeps source hashing and
    source rendering on one policy boundary.
    """
    return read_repo_text(
        repository_root,
        user_path,
        allow_ignored=allow_ignored,
        max_bytes=max_bytes,
    ).encode("utf-8")


def iter_repo_text_files(
    repository_root: Path,
    *,
    allow_ignored: bool = False,
    max_bytes: int | None = DEFAULT_MAX_BYTES,
    excluded_roots: tuple[str, ...] = (),
) -> Iterator[RepositoryTextFile]:
    """Yield readable repository text files in stable repository-relative order."""
    root = repository_root.resolve()
    excluded = tuple(
        resolve_repo_path(root, excluded_root).rstrip("/")
        for excluded_root in excluded_roots
    )
    candidates = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix(),
    )
    seen_relative: set[str] = set()
    for candidate in candidates:
        try:
            relative = candidate.resolve().relative_to(root).as_posix()
            if relative in seen_relative:
                continue
            seen_relative.add(relative)
            if any(relative == item or relative.startswith(f"{item}/") for item in excluded):
                continue
            content = read_repo_text(
                root,
                relative,
                allow_ignored=allow_ignored,
                max_bytes=max_bytes,
            )
        except (FileNotFoundError, OSError, ValueError):
            continue
        yield RepositoryTextFile(relative, content)


def stable_json(data: Any) -> str:
    """Return canonical human-readable JSON suitable for generated state."""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_text_atomic(path: Path, content: str) -> None:
    """Atomically replace *path* with UTF-8, LF-normalized text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(normalized)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, data: Any) -> None:
    """Atomically persist JSON in SACAS's deterministic serialization."""
    write_text_atomic(path, stable_json(data))
