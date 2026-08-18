"""Deterministic and atomic persistence helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any


def stable_json(data: Any) -> str:
    """Return canonical human-readable JSON suitable for generated state."""
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_text_atomic(path: Path, content: str) -> None:
    """Atomically replace *path* with UTF-8, LF-normalized text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = content.replace("\r\n", "\n")
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(normalized)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def write_json_atomic(path: Path, data: Any) -> None:
    """Atomically persist JSON in SACAS's deterministic serialization."""
    write_text_atomic(path, stable_json(data))
