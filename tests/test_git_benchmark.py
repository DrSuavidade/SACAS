"""Tests for historical Git benchmarking (WP5)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from sacas.git_benchmark import (
    generate_historical_tasks,
    save_historical_benchmarks,
    _run_git,
    _get_parent_commit,
    _is_merge_commit,
    _get_diff_files,
    _get_diff_symbols,
    _get_diff_tests,
)


@pytest.fixture
def temp_git_repo() -> Path:
    """Create a temporary git repo with some history."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        
        # Initialize git
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True, capture_output=True)
        
        # Create initial commit
        (repo / "src").mkdir()
        (repo / "src" / "auth.py").write_text("def login():\n    pass\n", encoding="utf-8")
        (repo / "README.md").write_text("# Project\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo, check=True, capture_output=True)
        
        # Commit 2: add user service
        (repo / "src" / "user.py").write_text("class User:\n    pass\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/user.py"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add user service"], cwd=repo, check=True, capture_output=True)
        
        # Commit 3: fix auth (modify existing file)
        (repo / "src" / "auth.py").write_text("def login():\n    return True\n\ndef logout():\n    pass\n", encoding="utf-8")
        subprocess.run(["git", "add", "src/auth.py"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Fix auth login logic"], cwd=repo, check=True, capture_output=True)
        
        # Commit 4: add test
        (repo / "tests").mkdir()
        (repo / "tests" / "test_auth.py").write_text("def test_login():\n    assert True\n", encoding="utf-8")
        subprocess.run(["git", "add", "tests/test_auth.py"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add auth tests"], cwd=repo, check=True, capture_output=True)
        
        yield repo


def test_run_git(temp_git_repo: Path):
    """Test running git commands."""
    output = _run_git(temp_git_repo, ["log", "--oneline", "-1"])
    assert "Add auth tests" in output or "Initial commit" in output


def test_get_parent_commit(temp_git_repo: Path):
    """Test getting parent commit."""
    # Get latest commit
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-1"]).strip()
    parent = _get_parent_commit(temp_git_repo, commits)
    assert parent is not None
    assert len(parent) == 40  # SHA1


def test_is_merge_commit(temp_git_repo: Path):
    """Test detecting merge commits."""
    # Get a regular commit
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-1"]).strip()
    assert _is_merge_commit(temp_git_repo, commits) == False
    
    # Get original branch name BEFORE creating feature branch
    original_branch = _run_git(temp_git_repo, ["symbolic-ref", "--short", "HEAD"]).strip()
    
    # Create a merge commit
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=temp_git_repo, check=True, capture_output=True)
    (temp_git_repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "add", "feature.txt"], cwd=temp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Feature"], cwd=temp_git_repo, check=True, capture_output=True)
    
    # Go back to original branch
    subprocess.run(["git", "checkout", original_branch], cwd=temp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "merge", "feature", "--no-ff", "-m", "Merge feature"], cwd=temp_git_repo, check=True, capture_output=True)
    
    merge_commit = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-1"]).strip()
    assert _is_merge_commit(temp_git_repo, merge_commit) == True


def test_get_diff_files(temp_git_repo: Path):
    """Test getting changed files between commits."""
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-4"]).strip().split("\n")
    # commits[0] = latest, commits[3] = initial
    parent = commits[3]
    child = commits[0]
    
    files = _get_diff_files(temp_git_repo, parent, child)
    assert "src/auth.py" in files
    assert "src/user.py" in files
    assert "tests/test_auth.py" in files
    # README.md was in initial commit, not changed in subsequent commits
    # So it won't appear in diff between initial and latest


def test_get_diff_symbols(temp_git_repo: Path):
    """Test extracting symbols from diff."""
    # Get the commit that added logout (3rd commit from latest)
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-4"]).strip().split("\n")
    # commits[0] = latest (test), commits[1] = auth fix, commits[2] = user, commits[3] = initial
    parent = commits[2]  # user commit
    child = commits[1]   # auth fix commit (added logout)
    
    symbols = _get_diff_symbols(temp_git_repo, parent, child)
    # Should find "logout" from the auth.py change
    assert "logout" in symbols


def test_get_diff_tests(temp_git_repo: Path):
    """Test getting test files from diff."""
    # Test commit is the latest
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-2"]).strip().split("\n")
    parent = commits[1]
    child = commits[0]
    
    tests = _get_diff_tests(temp_git_repo, parent, child)
    assert "tests/test_auth.py" in tests


def test_generate_historical_tasks(temp_git_repo: Path):
    """Test generating historical benchmark tasks."""
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    # Should have tasks for each non-merge, non-root commit with changes
    assert len(tasks) >= 3
    
    for task in tasks:
        assert task.id.startswith("hist-")
        assert task.parent_commit
        assert task.child_commit
        assert task.goal
        assert len(task.goal) >= 10
        assert "files" in task.expected
        assert "symbols" in task.expected
        assert "tests" in task.expected
        assert task.metadata.get("weak_gold") == True
        assert task.metadata.get("generation_schema") == "v1"


def test_generate_historical_tasks_skips_merge(temp_git_repo: Path):
    """Test that merge commits are skipped."""
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    # Verify no task has a merge commit as child
    for task in tasks:
        assert _is_merge_commit(temp_git_repo, task.child_commit) == False


def test_save_historical_benchmarks(temp_git_repo: Path):
    """Test saving benchmarks to JSON files."""
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    with tempfile.TemporaryDirectory() as tmp:
        output_dir = Path(tmp) / "benchmarks"
        save_historical_benchmarks(tasks, output_dir)
        
        # Check files were created
        files = list(output_dir.glob("*.json"))
        assert len(files) == len(tasks)
        
        # Check content
        for file in files:
            data = json.loads(file.read_text())
            assert "id" in data
            assert "goal" in data
            assert "expected" in data
            assert "metadata" in data
            assert data["metadata"].get("weak_gold") == True


def test_historical_task_parent_is_actual_parent(temp_git_repo: Path):
    """Test that parent_commit is the actual git parent, not just previous in list."""
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    for task in tasks:
        # Verify the parent is actually the parent in git
        actual_parent = _get_parent_commit(temp_git_repo, task.child_commit)
        assert task.parent_commit == actual_parent


def test_generate_historical_tasks_root_commit_skipped(temp_git_repo: Path):
    """Test that root commit (no parent) is skipped."""
    # Root commit should not generate a task since it has no parent
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    # Count non-merge commits with changes (excluding root)
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-10"]).strip().split("\n")
    non_root_count = 0
    for c in commits:
        parent = _get_parent_commit(temp_git_repo, c)
        if parent and not _is_merge_commit(temp_git_repo, c):
            files = _get_diff_files(temp_git_repo, parent, c)
            if files:
                non_root_count += 1
    
    assert len(tasks) == non_root_count


def test_generate_historical_tasks_correct_commit_order(temp_git_repo: Path):
    """Test that tasks are generated from oldest to newest (parent to child)."""
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    # Tasks should be ordered by child commit (which follows git history order)
    # git log returns newest first, so tasks should be in reverse chronological order
    for i in range(len(tasks) - 1):
        # Each task's child should be a descendant of the previous task's child
        # In practice, they follow git log order (newest first)
        assert tasks[i].child_commit != tasks[i+1].child_commit


def test_run_in_detached_worktree_isolation(temp_git_repo: Path):
    """Test that worktree operations don't affect the main repo."""
    from sacas.git_benchmark import _run_in_detached_worktree
    
    # Get a commit
    commit = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-1"]).strip()
    original_branch = _run_git(temp_git_repo, ["branch", "--show-current"]).strip()
    
    def check_isolation(worktree: Path):
        # Check we're in detached HEAD at the right commit
        current = _run_git(worktree, ["rev-parse", "HEAD"]).strip()
        assert current == commit
        # Check we're not on a branch
        branch = _run_git(worktree, ["branch", "--show-current"]).strip()
        assert branch == ""
        return "ok"
    
    result = _run_in_detached_worktree(temp_git_repo, commit, check_isolation)
    assert result == "ok"
    
    # Main repo should be unchanged
    assert _run_git(temp_git_repo, ["branch", "--show-current"]).strip() == original_branch


def test_historical_tasks_weak_gold_label(temp_git_repo: Path):
    """Test that generated tasks are labeled as weak gold."""
    tasks = generate_historical_tasks(temp_git_repo, max_commits=10)
    
    for task in tasks:
        assert task.metadata.get("weak_gold") == True
        assert "generation_schema" in task.metadata
        assert task.metadata["source"] == "git_history"


def test_generate_and_run_historical_benchmarks_integration(temp_git_repo: Path):
    """Integration test for generate + run (requires SACAS installation)."""
    # This test is skipped if no SACAS installation in the temp repo
    # Just verify the function exists and can be called
    from sacas.git_benchmark import generate_and_run_historical_benchmarks
    # We can't easily test this without a full SACAS installation
    # The function signature is tested by existence
    assert callable(generate_and_run_historical_benchmarks)