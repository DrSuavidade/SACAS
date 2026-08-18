from __future__ import annotations

import pytest
from sacas.active_context import ActiveContextManifest, ActiveFileContext
from sacas.benchmark_runner import run_routing_benchmark

def test_run_routing_benchmark() -> None:
    # Gold standard requires auth.py and session.py
    gold = {"src/auth.py", "src/session.py"}
    
    # Manifest has auth.py and helper.py
    manifest = ActiveContextManifest(
        task_id="t1",
        goal="Verify benchmark",
        category="bugfix",
        git_revision="unknown",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "full"},
                source="explicit",
                confidence="high",
                relation=None,
                trigger="initial_route",
                git_revision="unknown",
                reason="Needed",
                hash=""
            ),
            ActiveFileContext(
                path="src/helper.py",
                selection={"mode": "full"},
                source="explicit",
                confidence="high",
                relation=None,
                trigger="initial_route",
                git_revision="unknown",
                reason="Needed",
                hash=""
            ),
        ),
        rules=(),
        references=(),
        events=()
    )
    
    result = run_routing_benchmark(gold, manifest, token_usage=150)
    
    # Routed: auth.py (TP), helper.py (FP). Missing: session.py (FN).
    # tp = 1, fp = 1, fn = 1
    # precision = 1/2 = 0.5
    # recall = 1/2 = 0.5
    # f1 = 0.5
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5
    assert result.token_usage == 150
