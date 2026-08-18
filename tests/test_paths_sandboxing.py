"""Tests for path containment sandboxing and component-based boundary matching."""

from __future__ import annotations

import pytest
from pathlib import Path
from sacas.paths import resolve_repo_path
from sacas.tasks import is_file_protected


def test_resolve_repo_path_sandbox(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    # Create some files
    (repo_root / "src").mkdir()
    (repo_root / "src" / "auth").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "auth" / "provider.py").write_text("content", encoding="utf-8")
    
    # Valid relative path resolution
    res = resolve_repo_path(repo_root, "src/auth/provider.py")
    assert res == "src/auth/provider.py"
    
    # Escape attempts
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        resolve_repo_path(repo_root, "/var/foo")
        
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        resolve_repo_path(repo_root, "C:\\Windows\\foo")
        
    with pytest.raises(ValueError, match="Path escapes repository root"):
        resolve_repo_path(repo_root, "../secret.txt")
        
    with pytest.raises(ValueError, match="Path escapes repository root"):
        resolve_repo_path(repo_root, "../../foo")

    with pytest.raises(ValueError, match="Path escapes repository root"):
        resolve_repo_path(repo_root, "src/auth/../../../secret")

    # Extra Windows UNC, drive colon, and escape checks
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        resolve_repo_path(repo_root, "C:foo")
        
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        resolve_repo_path(repo_root, "\\\\server\\share\\foo")
        
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        resolve_repo_path(repo_root, "\\\\?\\C:\\foo")

    with pytest.raises(ValueError, match="Path escapes repository root"):
        resolve_repo_path(repo_root, "src/../../foo")



def test_component_based_boundaries() -> None:
    # boundaries: prefix_path, reason
    boundaries = (
        ("src/auth/", "Auth logic"),
    )
    
    # Component matches
    assert is_file_protected("src/auth/provider.py", boundaries) == "Auth logic"
    assert is_file_protected("src/auth/session/store.py", boundaries) == "Auth logic"
    
    # Prefix but not component match
    assert is_file_protected("src/authentication/provider.py", boundaries) is None
    assert is_file_protected("src/author/book.py", boundaries) is None
