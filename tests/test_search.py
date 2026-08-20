from __future__ import annotations

import json
from pathlib import Path
import pytest
from sacas.search import FallbackIndex

def test_fallback_index_lifecycle(tmp_path: Path) -> None:
    # 1. Setup paths
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    src_dir = repo_root / "src"
    src_dir.mkdir()
    
    auth_file = src_dir / "auth.py"
    auth_file.write_text("class SessionManager:\n    def login(self):\n        pass\n", encoding="utf-8")
    
    sacas_root = repo_root / "Structure"
    sacas_root.mkdir()
    
    index = FallbackIndex(repo_root, sacas_root)
    index.update()
    
    # Verify index was saved
    assert index.index_path.is_file()
    
    # Check entries parsed correctly
    assert "src/auth.py" in index.entries
    entry = index.entries["src/auth.py"]
    assert "SessionManager" in entry["symbols"]
    assert "login" in entry["symbols"]
    assert entry["language"] == "python"
    
    # Search check
    results = index.search("fix session login authentication")
    assert len(results) > 0
    score, path, matched = results[0]
    assert path == "src/auth.py"
    assert "session" in matched or "login" in matched


def test_fallback_index_only_indexes_validated_repository_text(tmp_path: Path) -> None:
    """Indexing must share the source-read admission boundary."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sacas_root = repo_root / "Structure"
    sacas_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "included.py").write_text("class Included: pass\n", encoding="utf-8")
    (repo_root / ".env").write_text("class Secret: pass\n", encoding="utf-8")
    (repo_root / ".sacasignore").write_text("ignored.py\n", encoding="utf-8")
    (repo_root / "src" / "ignored.py").write_text("class Ignored: pass\n", encoding="utf-8")
    (repo_root / "src" / "binary.py").write_bytes(b"\x00class Binary: pass")
    (repo_root / "src" / "invalid.py").write_bytes(b"\xffclass Invalid: pass")
    (repo_root / "src" / "large.py").write_bytes(b"x" * 1_000_001)

    external = tmp_path / "external.py"
    external.write_text("class External: pass\n", encoding="utf-8")
    try:
        (repo_root / "src" / "external.py").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")

    index = FallbackIndex(repo_root, sacas_root)
    index.update()

    assert "src/included.py" in index.entries
    assert not {
        ".env",
        "src/ignored.py",
        "src/binary.py",
        "src/invalid.py",
        "src/large.py",
        "src/external.py",
    } & set(index.entries)
