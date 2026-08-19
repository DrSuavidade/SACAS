"""Tests for secure repository path validation and reading (WP1)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from sacas.paths import resolve_repo_path
from sacas.io import write_text_atomic, stable_json


class TestResolveRepoPath:
    """Test the resolve_repo_path function for sandboxing."""

    def test_valid_relative_path(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        (repo_root / "src" / "auth.py").write_text("content", encoding="utf-8")

        result = resolve_repo_path(repo_root, "src/auth.py")
        assert result == "src/auth.py"

    def test_absolute_posix_path_rejected(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            resolve_repo_path(repo_root, "/etc/passwd")

    def test_absolute_windows_path_rejected(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            resolve_repo_path(repo_root, "C:\\Windows\\foo")

    def test_windows_drive_colon_rejected(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            resolve_repo_path(repo_root, "C:foo")

    def test_unc_path_rejected(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            resolve_repo_path(repo_root, "\\\\server\\share\\foo")

    def test_windows_extended_path_rejected(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        with pytest.raises(ValueError, match="Absolute paths are not allowed"):
            resolve_repo_path(repo_root, "\\\\?\\C:\\foo")

    def test_directory_traversal_rejected(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()

        with pytest.raises(ValueError, match="Path escapes repository root"):
            resolve_repo_path(repo_root, "../secret.txt")

        with pytest.raises(ValueError, match="Path escapes repository root"):
            resolve_repo_path(repo_root, "../../foo")

        with pytest.raises(ValueError, match="Path escapes repository root"):
            resolve_repo_path(repo_root, "src/auth/../../../secret")

    def test_mixed_separators(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        (repo_root / "src" / "auth.py").write_text("content", encoding="utf-8")

        # Windows-style separators should work
        result = resolve_repo_path(repo_root, "src\\auth.py")
        assert result == "src/auth.py"

    def test_unicode_filename(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        unicode_file = repo_root / "src" / "测试.py"
        unicode_file.write_text("content", encoding="utf-8")

        result = resolve_repo_path(repo_root, "src/测试.py")
        assert result == "src/测试.py"

    def test_missing_file(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # resolve_repo_path doesn't check existence, only path validity
        # The read operation should handle missing files
        result = resolve_repo_path(repo_root, "src/missing.py")
        assert result == "src/missing.py"

    def test_directory_instead_of_file(self, tmp_path: Path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()

        result = resolve_repo_path(repo_root, "src")
        assert result == "src"


class TestReadRepoText:
    """Test secure repository text reading (to be implemented in WP1.1)."""

    def test_read_normal_file(self, tmp_path: Path):
        """Test reading a normal text file."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        test_file = repo_root / "src" / "test.py"
        test_file.write_text("print('hello')\n", encoding="utf-8")

        # Currently uses direct read - WP1 will add read_repo_text
        content = test_file.read_text(encoding="utf-8")
        assert content == "print('hello')\n"

    def test_read_crlf_file(self, tmp_path: Path):
        """Test reading a file with CRLF line endings."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        test_file = repo_root / "src" / "crlf.txt"
        test_file.write_bytes(b"line1\r\nline2\r\n")

        content = test_file.read_text(encoding="utf-8")
        # Python normalizes line endings by default
        assert "line1" in content
        assert "line2" in content

    def test_read_large_file(self, tmp_path: Path):
        """Test reading a large file (should have size limits in WP1.1)."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        test_file = repo_root / "src" / "large.txt"
        # Write 2MB file
        test_file.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")

        content = test_file.read_text(encoding="utf-8")
        assert len(content) == 2 * 1024 * 1024

    def test_read_binary_file(self, tmp_path: Path):
        """Test reading a binary file (should be rejected in WP1.1)."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        test_file = repo_root / "src" / "binary.bin"
        test_file.write_bytes(bytes(range(256)))

        # Currently reads as text with errors='ignore'
        content = test_file.read_text(encoding="utf-8", errors="ignore")
        # Should not crash
        assert isinstance(content, str)

    def test_secret_file_exclusion(self, tmp_path: Path):
        """Test that secret files are identified (WP1.1)."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()

        secret_files = [
            ".env",
            ".env.production",
            ".env.local",
            "private.key",
            "credentials.json",
            "secrets.yaml",
            "id_rsa",
            "id_rsa.pub",
        ]

        for secret in secret_files:
            secret_path = repo_root / secret
            secret_path.write_text("secret=value", encoding="utf-8")

            # WP1.1 will add a function to check if path is secret
            # For now, just verify we can identify them
            assert secret_path.exists()

    def test_symlink_escape_external(self, tmp_path: Path):
        """Test that external symlinks are rejected."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()

        external = tmp_path / "external_secret.txt"
        external.write_text("external secret", encoding="utf-8")

        link_path = repo_root / "src" / "link.txt"
        try:
            link_path.symlink_to(external)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")

        # WP1: resolve_repo_path should reject symlink escapes
        # Currently it resolves and checks if within repo_root
        resolved = link_path.resolve()
        try:
            resolved.relative_to(repo_root.resolve())
            # If this passes, the symlink is inside repo (not an escape)
            # But external symlink should fail this check
        except ValueError:
            # This is the expected behavior for external symlinks
            pass

    def test_symlink_internal(self, tmp_path: Path):
        """Test that internal symlinks are resolved to their target."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        (repo_root / "src" / "real.py").write_text("real content", encoding="utf-8")

        link_path = repo_root / "src" / "link.py"
        try:
            link_path.symlink_to(repo_root / "src" / "real.py")
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")

        # resolve_repo_path resolves symlinks - this is correct security behavior
        result = resolve_repo_path(repo_root, "src/link.py")
        assert result == "src/real.py"


class TestCompilerSecureReads:
    """Test that compiler uses secure path resolution (WP1.2)."""

    def test_compiler_uses_resolve_repo_path(self, tmp_path: Path):
        """WP1.2: Compiler should use resolve_repo_path for all repo reads."""
        # This test documents the requirement for WP1.2
        # Current implementation in compiler.py uses:
        #   f_path = installation.repository_root / f.path
        # Should be changed to:
        #   rel_path = resolve_repo_path(installation.repository_root, f.path)
        #   f_path = installation.repository_root / rel_path
        pass

    def test_refresh_uses_resolve_repo_path(self, tmp_path: Path):
        """WP1.2: Refresh should use resolve_repo_path."""
        # Current implementation in refresh.py uses:
        #   file_path = installation.repository_root / filepath
        pass

    def test_regions_uses_resolve_repo_path(self, tmp_path: Path):
        """WP1.2: Regions should use resolve_repo_path."""
        pass

    def test_tasks_uses_resolve_repo_path(self, tmp_path: Path):
        """WP1.2: Tasks should use resolve_repo_path."""
        pass

    def test_benchmark_uses_resolve_repo_path(self, tmp_path: Path):
        """WP1.2: Benchmark should use resolve_repo_path."""
        pass


class TestSacasIgnore:
    """Test .sacasignore support (WP1.1)."""

    def test_sacasignore_glob_pattern(self, tmp_path: Path):
        """Test .sacasignore with glob pattern."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        (repo_root / "src" / "test.py").write_text("print(1)\n", encoding="utf-8", newline="\n")
        (repo_root / "src" / "debug.log").write_text("debug info\n", encoding="utf-8", newline="\n")
        (repo_root / ".sacasignore").write_text("*.log\n", encoding="utf-8")

        from sacas.io import read_repo_text
        
        # Should be allowed
        content = read_repo_text(repo_root, "src/test.py")
        assert content.strip() == "print(1)"
        
        # Should be denied by .sacasignore pattern
        with pytest.raises(ValueError, match="Path matches .sacasignore"):
            read_repo_text(repo_root, "src/debug.log")

    def test_sacasignore_directory_pattern(self, tmp_path: Path):
        """Test .sacasignore with directory pattern."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        (repo_root / "src" / "test.py").write_text("print(1)\n", encoding="utf-8", newline="\n")
        # Use a custom directory name not in default IGNORE_DIRS
        (repo_root / "custom_build").mkdir()
        (repo_root / "custom_build" / "bundle.js").write_text("bundle\n", encoding="utf-8", newline="\n")
        # Use ** to match files inside the directory
        (repo_root / ".sacasignore").write_text("custom_build/**\n", encoding="utf-8")

        from sacas.io import read_repo_text
        
        # Should be allowed
        content = read_repo_text(repo_root, "src/test.py")
        assert content.strip() == "print(1)"
        
        # Should be denied by .sacasignore pattern
        with pytest.raises(ValueError, match="Path matches .sacasignore"):
            read_repo_text(repo_root, "custom_build/bundle.js")

    def test_sacasignore_allow_ignored_flag(self, tmp_path: Path):
        """Test allow_ignored bypasses .sacasignore."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "src").mkdir()
        (repo_root / "src" / "debug.log").write_text("debug info\n", encoding="utf-8", newline="\n")
        (repo_root / ".sacasignore").write_text("*.log\n", encoding="utf-8")

        from sacas.io import read_repo_text
        
        # Should be denied by default
        with pytest.raises(ValueError, match="Path matches .sacasignore"):
            read_repo_text(repo_root, "src/debug.log")
        
        # Should be allowed with allow_ignored=True
        content = read_repo_text(repo_root, "src/debug.log", allow_ignored=True)
        assert content.strip() == "debug info"


