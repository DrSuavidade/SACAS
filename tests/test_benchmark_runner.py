from __future__ import annotations

import json
from pathlib import Path
import pytest
from sacas.active_context import ActiveContextManifest, ActiveFileContext, ActiveSymbolContext, SourceRange
from sacas.benchmark_runner import run_routing_benchmark_suite, load_and_run_all_benchmarks
from sacas.init import initialize
from sacas.paths import discover_manifest
from sacas.active_context import save_active_context
from sacas.cli import main

def test_benchmark_suite_metrics(tmp_path: Path) -> None:
    # 1. Initialize
    init_result = initialize(tmp_path)
    installation = discover_manifest(tmp_path)
    
    # Create mock repo source files
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "auth.py").write_text("def auth(): pass\n", encoding="utf-8")
    (tmp_path / "src" / "session.py").write_text("def session(): pass\n", encoding="utf-8")
    (tmp_path / "src" / "helper.py").write_text("print('help')\n", encoding="utf-8")
    
    # Gold standard
    gold_task = {
        "id": "t_gold_001",
        "goal": "Fix session restoration",
        "expected": {
            "files": ["src/auth.py", "src/session.py"],
            "symbols": ["src/auth.py::auth"],
            "tests": ["tests/test_auth.py"]
        }
    }
    
    # Manifest has auth.py and helper.py
    manifest = ActiveContextManifest(
        task_id="t_gold_001",
        goal="Fix session restoration",
        category="bugfix",
        git_revision="unknown",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={
                    "mode": "symbols",
                    "symbols": [
                        ActiveSymbolContext(
                            name="auth",
                            range=SourceRange(start_line=1, end_line=1, source="parser", confidence=1.0)
                        )
                    ]
                },
                source="explicit",
                confidence="high", relation=None, trigger="initial_route",
                git_revision="unknown", reason="Needed", hash=""
            ),
            ActiveFileContext(
                path="src/helper.py", selection={"mode": "full"}, source="explicit",
                confidence="high", relation=None, trigger="initial_route",
                git_revision="unknown", reason="Needed", hash=""
            ),
        ),
        rules=(),
        references=(),
        events=(),
        tests=("tests/test_auth.py",)
    )
    
    # Candidates list has session.py (score 90), auth.py (score 100)
    candidates_list = [
        {"path": "src/session.py", "score": 90.0},
        {"path": "src/auth.py", "score": 100.0}
    ]
    
    res = run_routing_benchmark_suite(installation, gold_task, manifest, candidates_list)
    assert res.precision == 0.5  # tp=1 (auth.py), fp=1 (helper.py)
    assert res.recall == 0.5  # tp=1, fn=1 (session.py is missing from manifest)
    assert res.symbol_recall == 1.0  # auth is matched
    assert res.test_recall == 1.0  # tests/test_auth.py matches
    
    assert res.precision_at_5 == 0.4
    assert res.mrr == 1.0

def test_load_and_run_all_benchmarks(tmp_path: Path) -> None:
    init_result = initialize(tmp_path)
    installation = discover_manifest(tmp_path)
    
    # Create gold suite file
    bench_dir = installation.sacas_root / "benchmarks"
    bench_dir.mkdir(parents=True, exist_ok=True)
    gold_file = bench_dir / "auth_gold.json"
    gold_file.write_text(json.dumps({
        "id": "t_gold_001",
        "goal": "Fix session restoration",
        "expected": {
            "files": ["src/auth.py"]
        }
    }), encoding="utf-8")
    
    # Set current task
    task_dir = installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    manifest = ActiveContextManifest(
        task_id="t_gold_001",
        goal="Fix session restoration",
        category="bugfix",
        git_revision="unknown",
        files=(),
        rules=(),
        references=(),
        events=()
    )
    save_active_context(task_dir, manifest)
    
    # Update manifest.json task ID
    (installation.manifest_path).write_text(json.dumps({
        "repository_root": ".",
        "sacas_root": "Structure",
        "graphify_mode": "existing",
        "graphify_output": "graphify-out",
        "adapters": [],
        "context_budget": 12000,
        "current_task_id": "t_gold_001",
        "schema_version": 1
    }), encoding="utf-8")
    
    # Run CLI command benchmark
    exit_code = main(["benchmark", "--root", str(tmp_path)])
    assert exit_code == 0
