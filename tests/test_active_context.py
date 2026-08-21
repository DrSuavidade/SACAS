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
    save_active_context,
    migrate_legacy_active_context,
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

def test_legacy_expansions_migration(tmp_path: Path) -> None:
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
    
    manifest = migrate_legacy_active_context(tmp_path)
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
    
    # Verify legacy file is deleted
    assert not legacy_file.exists()
    
    # Verify active_context.json exists and can be loaded
    assert (tmp_path / "active_context.json").is_file()
    loaded = load_active_context(tmp_path)
    assert loaded is not None
    assert loaded.task_id == "legacy_task"
