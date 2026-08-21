from __future__ import annotations

import json
from pathlib import Path

import pytest
from sacas.active_context import (
    ActiveContextManifest,
    ActiveFileContext,
    ActiveSymbolContext,
    SourceRange,
    load_active_context,
    load_task_state,
    save_active_context,
    load_legacy_active_context,
)

def test_active_context_manifest_serialization() -> None:
    manifest = ActiveContextManifest(
        task_id="abc12345",
        goal="Improve authentication",
        category="bugfix",
        git_revision="gitsha123",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "symbols", "symbols": [
                    ActiveSymbolContext(
                        name="login",
                        range=SourceRange(start_line=10, end_line=20, source="explicit", confidence=1.0),
                        reason="Primary auth logic"
                    )
                ]},
                source="explicit",
                confidence="high",
                relation=None,
                trigger="initial_route",
                git_revision="gitsha123",
                reason="Direct access",
                hash=""
            ),
        ),
        rules=(),
        references=(),
        events=()
    )
    d = manifest.to_dict()
    assert d["task_id"] == "abc12345"
    assert d["files"][0]["selection"]["mode"] == "symbols"
    assert d["files"][0]["selection"]["symbols"][0]["name"] == "login"
    
    loaded = ActiveContextManifest.from_dict(d)
    assert loaded.task_id == "abc12345"
    assert loaded.files[0].path == "src/auth.py"
    assert loaded.files[0].selection["symbols"][0].range.start_line == 10


def test_active_context_serialization_preserves_each_constituent_symbol() -> None:
    """Persistence must not coalesce overlapping selector identities."""
    file_context = ActiveFileContext(
        path="src/auth.py",
        selection={"mode": "symbols", "symbols": [
            ActiveSymbolContext("login", SourceRange(1, 3, "parser", 1.0)),
            ActiveSymbolContext("validate", SourceRange(3, 5, "parser", 1.0)),
        ]},
        source="explicit",
    )
    persisted = file_context.to_dict()
    assert [symbol["name"] for symbol in persisted["selection"]["symbols"]] == ["login", "validate"]


@pytest.mark.parametrize(
    ("legacy_label", "expected_confidence"),
    (("high", 1.0), ("medium", 0.7), ("low", 0.4)),
)
def test_active_file_context_normalizes_legacy_confidence_labels_at_model_boundary(
    legacy_label: str, expected_confidence: float,
) -> None:
    """Legacy/manual labels become canonical numeric values before compilation."""
    context = ActiveFileContext(
        path="src/example.py",
        selection={"mode": "full"},
        source="explicit",
        confidence=legacy_label,
    )

    assert context.confidence == expected_confidence
    assert context.to_dict()["confidence"] == expected_confidence

def test_legacy_expansions_are_loaded_without_persisting(tmp_path: Path) -> None:
    # Set up legacy expansions.json v2
    legacy_data = {
        "schema_version": 2,
        "task_id": "legacy_task",
        "goal": "Fix user session expiration",
        "initial_scope": [
            {
                "path": "src/user.py",
                "symbols": ["session_expire"],
                "source": "heuristic",
                "confidence": "high",
                "reason": "Matches keywords"
            }
        ],
        "expansions": [
            {
                "path": "src/session_store.py",
                "source": "graphify",
                "confidence": "high",
                "triggered_by": "src/user.py",
                "relation": "calls",
                "reason": "Graph traversal"
            }
        ]
    }
    
    legacy_file = tmp_path / "expansions.json"
    legacy_file.write_text(json.dumps(legacy_data), encoding="utf-8")
    
    manifest = load_legacy_active_context(tmp_path)
    assert manifest is not None
    assert manifest.task_id == "legacy_task"
    assert manifest.category == "bugfix"
    assert len(manifest.files) == 2
    
    # Check session_store file has full selection
    user_file = next(f for f in manifest.files if f.path == "src/user.py")
    assert user_file.selection["mode"] == "symbols"
    assert user_file.selection["symbols"][0].name == "session_expire"
    
    store_file = next(f for f in manifest.files if f.path == "src/session_store.py")
    assert store_file.selection["mode"] == "full"
    
    # Legacy inspection is read-only; only refresh may publish a conversion.
    assert legacy_file.is_file()
    assert not (tmp_path / "active_context.json").exists()
    loaded = load_active_context(tmp_path)
    assert loaded is not None
    assert loaded.task_id == "legacy_task"


@pytest.mark.parametrize("source_state", ("missing", "binary"))
@pytest.mark.parametrize("reader", ("state", "status", "validate", "provenance", "benchmark"))
def test_legacy_context_readers_do_not_migrate_before_refresh(
    tmp_path: Path, source_state: str, reader: str,
) -> None:
    """Inspection paths must never replace a legacy task before its inputs are safe."""
    from sacas.benchmark import run_benchmark
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.provenance import query_why_file
    from sacas.status import get_status_report
    from sacas.validate import run_diagnostics

    initialized = initialize(tmp_path, graphify_mode="off")
    task_dir = initialized.sacas_root / "tasks" / "current"
    source = tmp_path / "src" / "legacy.py"
    if source_state == "binary":
        source.parent.mkdir()
        source.write_bytes(b"\x00not utf-8")

    legacy_payload = {
        "schema_version": 2,
        "task_id": "legacy-read-only",
        "goal": "Inspect legacy state",
        "initial_scope": [{"path": "src/legacy.py", "source": "explicit"}],
        "expansions": [],
    }
    expansions_path = task_dir / "expansions.json"
    expansions_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    original_expansions = expansions_path.read_bytes()

    manifest_path = initialized.sacas_root / ".sacas" / "manifest.json"
    installation_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    installation_payload["current_task_id"] = "legacy-read-only"
    manifest_path.write_text(json.dumps(installation_payload), encoding="utf-8")
    installation = discover_manifest(tmp_path)
    assert installation is not None

    if reader == "state":
        load_task_state(task_dir)
    elif reader == "status":
        get_status_report(installation)
    elif reader == "validate":
        run_diagnostics(tmp_path)
    elif reader == "provenance":
        query_why_file(installation, "src/legacy.py")
    else:
        run_benchmark(installation)

    assert expansions_path.read_bytes() == original_expansions
    assert not (task_dir / "task.json").exists()
    assert not (task_dir / "active_context.json").exists()
