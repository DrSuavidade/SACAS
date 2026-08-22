"""Historical Git Benchmark - generates gold tasks from commit history."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from sacas.paths import Installation


@dataclass(frozen=True)
class HistoricalTask:
    """A benchmark task derived from a historical commit."""
    id: str                    # hist-<parent_commit_short>
    parent_commit: str         # parent commit hash
    child_commit: str          # child commit hash
    goal: str                  # commit message (first line)
    expected: dict[str, list[str]]  # files, symbols, tests from diff
    metadata: dict[str, Any]  # generation info


def _run_git(repo: Path, args: list[str]) -> str:
    """Run git command and return stdout as UTF-8 text."""
    result = subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False
    )
    return (result.stdout or "").strip()


def _get_commit_history(repo: Path, max_commits: int = 1000) -> list[dict]:
    """Get commit history with hashes and messages."""
    output = _run_git(repo, ["log", f"-{max_commits}", "--pretty=format:%H|%s"])
    commits = []
    for line in output.splitlines():
        if "|" in line:
            hash_val, message = line.split("|", 1)
            commits.append({"hash": hash_val, "message": message})
    return commits


def _get_parent_commit(repo: Path, commit: str) -> str | None:
    """Get the first parent of a commit (skip merge commits)."""
    output = _run_git(repo, ["rev-parse", f"{commit}^"])
    if output:
        return output.strip()
    return None


def _is_merge_commit(repo: Path, commit: str) -> bool:
    """Check if a commit is a merge commit."""
    output = _run_git(repo, ["rev-parse", "--verify", f"{commit}^2"])
    return output != ""


def _get_diff_files(repo: Path, parent: str, child: str) -> list[str]:
    """Get list of files changed between two commits."""
    output = _run_git(repo, ["diff", "--name-only", parent, child])
    files = [f.strip() for f in output.splitlines() if f.strip()]
    return files


def _get_diff_symbols(repo: Path, parent: str, child: str) -> list[str]:
    """Get list of symbols (functions/classes) changed between two commits."""
    output = _run_git(repo, ["diff", parent, child])
    symbols = []
    
    import re
    for line in output.splitlines():
        if line.startswith("+") or line.startswith("-"):
            content = line[1:].strip()
            # Python
            for pattern in [
                r"^\s*def\s+(\w+)\s*\(",
                r"^\s*class\s+(\w+)\s*[\(:]",
                r"^\s*async\s+def\s+(\w+)\s*\(",
            ]:
                match = re.search(pattern, content)
                if match:
                    symbols.append(match.group(1))
            # JavaScript/TypeScript
            for pattern in [
                r"^\s*function\s+(\w+)\s*\(",
                r"^\s*const\s+(\w+)\s*=\s*(?:async\s*)?function",
                r"^\s*(\w+)\s*:\s*(?:async\s*)?function",
                r"^\s*class\s+(\w+)\s*\{",
                r"^\s*interface\s+(\w+)\s*\{",
            ]:
                match = re.search(pattern, content)
                if match:
                    symbols.append(match.group(1))
            # Go/Rust/Java/C#
            for pattern in [
                r"^\s*func\s+(\w+)\s*\(",
                r"^\s*fn\s+(\w+)\s*\(",
                r"^\s*public\s+\w+\s+(\w+)\s*\(",
                r"^\s*def\s+(\w+)\s*\(",
            ]:
                match = re.search(pattern, content)
                if match:
                    symbols.append(match.group(1))
    
    return list(dict.fromkeys(symbols))


def _get_diff_tests(repo: Path, parent: str, child: str) -> list[str]:
    """Get test files changed between two commits."""
    files = _get_diff_files(repo, parent, child)
    test_files = [f for f in files if any(
        t in f.lower() for t in ["test", "spec", "_test", "test_"]
    )]
    return test_files


def generate_historical_tasks(repo: Path, max_commits: int = 500) -> list[HistoricalTask]:
    """Generate historical benchmark tasks from git history.

    For each commit pair (parent, child), creates a task where:
    - Goal = commit message (child commit)
    - Expected = what changed in child vs parent
    - Uses explicit Git parent lookup (not list position)
    - Skips merge commits
    """
    commits = list(reversed(_get_commit_history(repo, max_commits)))
    tasks = []
    
    for i in range(len(commits)):
        child = commits[i]
        
        # Get actual parent (not list position)
        parent_hash = _get_parent_commit(repo, child["hash"])
        if not parent_hash:
            continue  # root commit
        
        # Skip merge commits
        if _is_merge_commit(repo, child["hash"]):
            continue
        
        changed_files = _get_diff_files(repo, parent_hash, child["hash"])
        if not changed_files:
            continue
            
        # Skip trivial commits
        if len(changed_files) > 50:
            continue
            
        goal = child["message"].split("\n")[0]
        if len(goal) < 10:
            continue
            
        changed_symbols = _get_diff_symbols(repo, parent_hash, child["hash"])
        changed_tests = _get_diff_tests(repo, parent_hash, child["hash"])
        
        task_id = f"hist-{child['hash'][:8]}"
        
        # Build file::symbol pairs only for symbols actually in the file
        # Read file content from child commit using git show to avoid contamination
        file_symbol_pairs = []
        for f in changed_files:
            try:
                # Read file content from child commit
                result = subprocess.run(
                    ["git", "show", f"{child['hash']}:{f}"],
                    cwd=repo,
                    capture_output=True,
                    text=True,
                    check=False,
                    encoding="utf-8",
                    errors="ignore"
                )
                if result.returncode == 0:
                    content = result.stdout
                    for s in changed_symbols:
                        if s in content:
                            file_symbol_pairs.append(f"{f}::{s}")
            except OSError:
                pass
        
        task = HistoricalTask(
            id=task_id,
            parent_commit=parent_hash,
            child_commit=child["hash"],
            goal=goal,
            expected={
                "files": changed_files,
                "symbols": file_symbol_pairs,
                "tests": changed_tests,
            },
            metadata={
                "parent_commit": parent_hash,
                "child_commit": child["hash"],
                "source": "git_history",
                "generation_schema": "v1",
                "weak_gold": True,
            }
        )
        tasks.append(task)
    
    return tasks


def save_historical_benchmarks(tasks: list[HistoricalTask], output_dir: Path) -> None:
    """Save historical tasks as JSON benchmark files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for task in tasks:
        benchmark = {
            "id": task.id,
            "goal": task.goal,
            "category": "investigate",
            "expected": task.expected,
            "metadata": task.metadata
        }
        file_path = output_dir / f"{task.id}.json"
        file_path.write_text(json.dumps(benchmark, indent=2))


def _run_in_detached_worktree(repo: Path, commit: str, callback) -> Any:
    """Run a callback in a detached git worktree at the given commit."""
    with tempfile.TemporaryDirectory() as tmp:
        worktree_path = Path(tmp) / "worktree"
        
        # Add worktree at specific commit
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree_path), commit],
            cwd=repo,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create worktree: {result.stderr}")
        
        try:
            return callback(worktree_path)
        finally:
            # Cleanup worktree
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=repo,
                capture_output=True,
                check=False
            )


def run_historical_benchmarks(installation: Installation, benchmark_dir: Path) -> list[dict[str, Any]]:
    """Run SACAS routing against historical benchmarks in isolated parent worktrees.

    Never mutates the user's active checkout.
    """
    from sacas.tasks import route_goal
    from sacas.init import initialize
    
    results = []
    repo_root = installation.repository_root
    
    for bench_file in sorted(benchmark_dir.glob("*.json")):
        try:
            gold_task = json.loads(bench_file.read_text(encoding="utf-8"))
            
            parent_commit = gold_task.get("metadata", {}).get("parent_commit")
            if not parent_commit:
                continue
                
            # Run routing in detached worktree at parent commit
            def do_routing(worktree: Path):
                # Need a new Installation for the worktree
                # Discover or create SACAS in the worktree
                from sacas.paths import discover_manifest
                worktree_install = discover_manifest(worktree)
                if not worktree_install:
                    # Initialize minimal SACAS in worktree if not present
                    try:
                        from sacas.paths import sacas_root_posix

                        initialize(
                            worktree,
                            sacas_root=sacas_root_posix(repo_root, installation.sacas_root),
                            graphify_mode="off",
                        )
                        worktree_install = discover_manifest(worktree)
                    except Exception:
                        raise RuntimeError("Failed to initialize SACAS in worktree")
                
                manifest = route_goal(
                    installation=worktree_install,
                    goal=gold_task.get("goal", ""),
                    category=gold_task.get("category", "investigate"),
                    files=(),
                    symbols=(),
                    tests=(),
                    rules=(),
                    references=(),
                    context_policy="advisory",
                )
                return manifest
            
            manifest = _run_in_detached_worktree(repo_root, parent_commit, do_routing)
            
            # Evaluate after routing. Child diff data is never passed to route_goal.
            expected_files = set(gold_task["expected"].get("files", ()))
            retrieved_files = {file.path for file in manifest.files}
            true_positives = len(expected_files & retrieved_files)
            precision = true_positives / len(retrieved_files) if retrieved_files else 0.0
            recall = true_positives / len(expected_files) if expected_files else 0.0
            eval_result = {"precision": precision, "recall": recall}
            
            results.append({
                "task_id": gold_task["id"],
                "goal": gold_task["goal"],
                "parent_commit": parent_commit,
                "child_commit": gold_task.get("metadata", {}).get("child_commit"),
                "expected_files": gold_task["expected"].get("files", []),
                "expected_symbols": gold_task["expected"].get("symbols", []),
                "expected_tests": gold_task["expected"].get("tests", []),
                "retrieved_files": [f.path for f in manifest.files],
                "eval": eval_result,
            })
        except Exception as e:
            results.append({
                "task_id": bench_file.stem,
                "error": str(e)
            })
    
    return results


def generate_and_run_historical_benchmarks(
    repo: Path,
    sacas_root: Path,
    max_commits: int = 200,
    output_dir: Path | None = None
) -> list[dict[str, Any]]:
    """Generate historical tasks from repo history and run benchmarks."""
    from sacas.paths import discover_manifest
    
    # Generate tasks
    tasks = generate_historical_tasks(repo, max_commits)
    
    if output_dir is None:
        output_dir = sacas_root / "benchmarks" / "historical"
    
    save_historical_benchmarks(tasks, output_dir)
    
    # Run benchmarks
    installation = discover_manifest(repo)
    if not installation:
        raise RuntimeError("No SACAS installation found")
    
    return run_historical_benchmarks(installation, output_dir)
