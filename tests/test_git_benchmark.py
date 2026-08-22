"""Tests for historical Git benchmarking (WP5)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from sacas.lab.git_benchmark import (
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

    task_children = {task.child_commit for task in tasks}
    expected_order = [
        commit
        for commit in reversed(_run_git(temp_git_repo, ["log", "--pretty=format:%H", "-10"]).splitlines())
        if commit in task_children
    ]
    assert [task.child_commit for task in tasks] == expected_order


def test_historical_routing_uses_actual_parent_worktree_without_child_file_hints(
    temp_git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sacas.lab.git_benchmark import run_historical_benchmarks
    from sacas.init import initialize
    from sacas.active_context import ActiveContextManifest
    import sacas.tasks

    parent = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-2"]).splitlines()[1]
    child = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-1"]).strip()
    benchmark_dir = tmp_path / "benchmarks"
    benchmark_dir.mkdir()
    (benchmark_dir / "historical.json").write_text(json.dumps({
        "id": "hist-parent-only",
        "goal": "Investigate child-only behavior",
        "category": "investigate",
        "expected": {"files": ["child_only.py"], "symbols": [], "tests": []},
        "metadata": {"parent_commit": parent, "child_commit": child, "weak_gold": True},
    }), encoding="utf-8")
    installation = initialize(temp_git_repo).installation
    captured: dict[str, object] = {}

    def fake_route_goal(*, installation, **kwargs):
        captured["root"] = installation.repository_root
        captured["head"] = _run_git(installation.repository_root, ["rev-parse", "HEAD"])
        captured["kwargs"] = kwargs
        return ActiveContextManifest(task_id="route", git_revision="unknown", files=(), rules=(), references=(), events=())

    monkeypatch.setattr(sacas.tasks, "route_goal", fake_route_goal)
    results = run_historical_benchmarks(installation, benchmark_dir)

    assert captured["root"] != temp_git_repo
    assert captured["head"] == parent
    assert captured["kwargs"] == {
        "goal": "Investigate child-only behavior",
        "category": "investigate",
        "files": (), "symbols": (), "tests": (), "rules": (), "references": (),
        "context_policy": "advisory",
    }
    assert results[0]["child_commit"] == child
    assert "error" not in results[0]


def test_run_in_detached_worktree_isolation(temp_git_repo: Path):
    """Test that worktree operations don't affect the main repo."""
    from sacas.lab.git_benchmark import _run_in_detached_worktree
    
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


def test_histbench_full_cli_workflow(temp_git_repo: Path, capsys: pytest.CaptureFixture[str]):
    """Public CLI workflow: init -> histbench -> non-empty metrics, no swallowed errors."""
    from sacas.cli import main

    # Real SACAS installation over real commit history
    assert main(["init", "--root", str(temp_git_repo), "--graphify", "off"]) == 0

    exit_code = main([
        "lab", "histbench",
        "--root", str(temp_git_repo),
        "--max-commits", "10",
        "--format", "json",
    ])
    assert exit_code == 0

    out = capsys.readouterr().out
    results = json.loads(out[out.index("["):])

    assert isinstance(results, list) and len(results) >= 3
    for result in results:
        assert "error" not in result, result
        assert result["task_id"].startswith("hist-")
        assert result["goal"]
        assert len(result["parent_commit"]) == 40
        assert isinstance(result["retrieved_files"], list)
        eval_result = result["eval"]
        assert set(eval_result) == {"precision", "recall"}
        assert 0.0 <= eval_result["precision"] <= 1.0
        assert 0.0 <= eval_result["recall"] <= 1.0

    # Weak-gold sanity: the auth fix task retrieves src/auth.py through real routing
    auth_tasks = [
        result for result in results
        if "src/auth.py" in result["expected_files"]
    ]
    assert auth_tasks, "expected at least one task touching src/auth.py"
    assert any("src/auth.py" in result["retrieved_files"] for result in auth_tasks)


def test_histbench_command_returns_nonzero_when_a_result_has_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Historical failures remain on disk and produce a failing CLI status."""
    from sacas.cli import histbench_command
    from sacas.init import initialize
    import sacas.lab.git_benchmark as git_benchmark_module

    installation = initialize(tmp_path).installation
    output_dir = tmp_path / "historical-output"
    monkeypatch.setattr(git_benchmark_module, "generate_historical_tasks", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(git_benchmark_module, "save_historical_benchmarks", lambda _tasks, directory: directory.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(
        git_benchmark_module,
        "run_historical_benchmarks",
        lambda _installation, _directory: [{"task_id": "hist-failed", "error": "routing failed"}],
    )

    assert histbench_command(installation, output_dir=str(output_dir), format_type="json") == 1
    assert output_dir.is_dir()
    assert "routing failed" in capsys.readouterr().out

def test_get_diff_symbols_handles_non_ascii_content(temp_git_repo: Path):
    """Diffs containing non-UTF8-hostile characters must not crash generation."""
    (temp_git_repo / "src" / "resumo.py").write_text(
        "# resumo\n\ndef resumo_dia():\n    return 1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "src/resumo.py"], cwd=temp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Add resumo — ação e coração"],
        cwd=temp_git_repo, check=True, capture_output=True,
    )
    commits = _run_git(temp_git_repo, ["log", "--pretty=format:%H", "-2"]).strip().split("\n")
    parent, child = commits[1], commits[0]

    symbols = _get_diff_symbols(temp_git_repo, parent, child)
    assert "resumo_dia" in symbols
