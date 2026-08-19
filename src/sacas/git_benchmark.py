"""Historical Git Benchmark - generates gold tasks from commit history."""

from __future__ import annotations

import json
import subprocess
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


def _run_git(repo: Path, args: list[str]) -> str:
    """Run git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        text=True,
        check=False
    )
    return result.stdout.strip()


def _get_commit_history(repo: Path, max_commits: int = 1000) -> list[dict]:
    """Get commit history with hashes and messages."""
    output = _run_git(repo, ["log", f"-{max_commits}", "--pretty=format:%H|%s"])
    commits = []
    for line in output.splitlines():
        if "|" in line:
            hash_val, message = line.split("|", 1)
            commits.append({"hash": hash_val, "message": message})
    return commits


def _get_diff_files(repo: Path, parent: str, child: str) -> list[str]:
    """Get list of files changed between two commits."""
    output = _run_git(repo, ["diff", "--name-only", parent, child])
    files = [f.strip() for f in output.splitlines() if f.strip()]
    return files


def _get_diff_symbols(repo: Path, parent: str, child: str) -> list[str]:
    """Get list of symbols (functions/classes) changed between two commits.
    
    Uses git diff with function context to extract symbol names.
    """
    output = _run_git(repo, ["diff", parent, child])
    symbols = []
    
    # Parse diff hunks for function/class definitions
    import re
    for line in output.splitlines():
        # Look for function/class definitions in diff context
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
    
    return list(dict.fromkeys(symbols))  # deduplicate, preserve order


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
    - Goal = commit message
    - Expected files/symbols/tests = what actually changed
    """
    commits = _get_commit_history(repo, max_commits)
    tasks = []
    
    for i in range(1, len(commits)):
        parent = commits[i-1]
        child = commits[i]
        
        changed_files = _get_diff_files(repo, parent["hash"], child["hash"])
        if not changed_files:
            continue
            
        # Skip trivial commits
        if len(changed_files) > 50:  # likely a large refactor or generated files
            continue
            
        goal = child["message"].split("\n")[0]
        if len(goal) < 10:  # too short to be meaningful
            continue
            
        changed_symbols = _get_diff_symbols(repo, parent["hash"], child["hash"])
        changed_tests = _get_diff_tests(repo, parent["hash"], child["hash"])
        
        task_id = f"hist-{parent['hash'][:8]}"
        
        task = HistoricalTask(
            id=task_id,
            parent_commit=parent["hash"],
            child_commit=child["hash"],
            goal=goal,
            expected={
                "files": changed_files,
                "symbols": [f"{f}::{s}" for f in changed_files for s in changed_symbols if s in open(repo / f, encoding="utf-8", errors="ignore").read()],
                "tests": changed_tests,
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
            "category": "investigate",  # historical tasks are investigation by nature
            "expected": task.expected,
            "metadata": {
                "parent_commit": task.parent_commit,
                "child_commit": task.child_commit,
                "source": "git_history"
            }
        }
        file_path = output_dir / f"{task.id}.json"
        file_path.write_text(json.dumps(benchmark, indent=2))


def run_historical_benchmarks(installation: Installation, benchmark_dir: Path) -> list[dict[str, Any]]:
    """Run SACAS routing against historical benchmarks and collect results."""
    from sacas.benchmark_runner import load_and_run_all_benchmarks
    from sacas.tasks import route_goal
    
    results = []
    
    for bench_file in benchmark_dir.glob("*.json"):
        try:
            gold_task = json.loads(bench_file.read_text(encoding="utf-8"))
            
            # Need to checkout parent commit temporarily
            parent_commit = gold_task.get("metadata", {}).get("parent_commit")
            if not parent_commit:
                continue
                
            # Run isolated routing
            manifest = route_goal(
                installation=installation,
                goal=gold_task.get("goal", ""),
                category=gold_task.get("category"),
                files=tuple(gold_task.get("files", ())),
                symbols=tuple(gold_task.get("symbols", ())),
                tests=tuple(gold_task.get("tests", ())),
                rules=tuple(gold_task.get("rules", ())),
                references=tuple(gold_task.get("references", ())),
            )
            
            # This would need the benchmark runner to evaluate
            # For now, return the task info
            results.append({
                "task_id": gold_task["id"],
                "goal": gold_task["goal"],
                "parent_commit": parent_commit,
                "expected_files": gold_task["expected"].get("files", []),
                "expected_symbols": gold_task["expected"].get("symbols", []),
                "expected_tests": gold_task["expected"].get("tests", []),
            })
        except Exception as e:
            results.append({
                "task_id": bench_file.stem,
                "error": str(e)
            })
    
    return results