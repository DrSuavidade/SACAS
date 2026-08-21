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


@pytest.mark.parametrize(
    ("filename", "payload", "expected"),
    (
        ("task.json", "{not json", "task.json is malformed"),
        ("task.json", json.dumps({"schema_version": 99}), "task.json has unsupported schema version"),
        ("active_context.json", "{not json", "active_context.json is malformed"),
        (
            "active_context.json",
            json.dumps({"schema_version": 1, "task_id": "task", "files": {}}),
            "active_context.json has invalid field 'files'",
        ),
    ),
)
def test_canonical_state_loader_distinguishes_corruption_from_absence(
    tmp_path: Path, filename: str, payload: str, expected: str,
) -> None:
    """An existing canonical file is never silently treated as missing state."""
    from sacas.active_context import CanonicalStateError

    (tmp_path / filename).write_text(payload, encoding="utf-8")

    with pytest.raises(CanonicalStateError, match=expected):
        load_task_state(tmp_path)


@pytest.mark.parametrize("filename", ("task.json", "active_context.json"))
def test_public_state_consumers_refuse_corrupt_canonical_context(tmp_path: Path, filename: str) -> None:
    """Inspection consumers give deterministic errors without rewriting state."""
    from sacas.benchmark import run_benchmark
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.provenance import query_why_file
    from sacas.status import get_status_report

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    assert main(["task", "Corrupt state", "--root", str(tmp_path), "--files", "src/app.py"]) == 0
    task_dir = initialized.sacas_root / "tasks" / "current"
    corrupt = task_dir / filename
    corrupt.write_text("{not json", encoding="utf-8")
    installation = discover_manifest(tmp_path)
    assert installation is not None

    assert get_status_report(installation)["status"] == "invalid_canonical_state"
    expected_error = f"Canonical task state is corrupt: {filename} is malformed"
    assert query_why_file(installation, "src/app.py") == [expected_error]
    assert run_benchmark(installation) == {
        "active_task": False,
        "error": expected_error,
    }
    assert main(["expand", "--root", str(tmp_path), "--file", "src/app.py"]) == 1
    assert main(["status", "--root", str(tmp_path), "--format", "json"]) == 1
    assert main(["why", "src/app.py", "--root", str(tmp_path)]) == 1
    assert main(["refresh", "--root", str(tmp_path)]) == 1
    assert corrupt.read_text(encoding="utf-8") == "{not json"


@pytest.mark.parametrize(
    ("mutate", "expected"),
    (
        (lambda state: state["files"][0].__setitem__("path", 1), "files"),
        (lambda state: state["files"][0].__setitem__("ranking_score", True), "files"),
        (lambda state: state["files"][0].__setitem__("selection", {"mode": "sections"}), "selection"),
        (lambda state: state["rules"][0].__setitem__("hash", 1), "rules"),
        (lambda state: state["references"][0].__setitem__("selection", {"mode": "sections", "sections": "bad"}), "references"),
        (lambda state: state["events"][0].__setitem__("action", "remove"), "events"),
        (lambda state: state.__setitem__("budget", {"limit": True}), "budget"),
        (lambda state: state.__setitem__("policy", {"requested": 1}), "policy"),
    ),
)
def test_canonical_manifest_rejects_malformed_nested_state(
    tmp_path: Path, mutate: object, expected: str,
) -> None:
    """Every canonical nested record has a schema, not merely a JSON shape."""
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    from sacas.task_contract import CanonicalStateError

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    rule = initialized.sacas_root / "rules" / "task.md"
    reference = initialized.sacas_root / "references" / "task.md"
    rule.write_text("# Rule\n", encoding="utf-8")
    reference.write_text("# Reference\n", encoding="utf-8")
    assert main([
        "task", "Nested schema", "--root", str(tmp_path), "--files", "src/app.py",
        "--rules", "Structure/rules/task.md", "--references", "Structure/references/task.md",
    ]) == 0
    context_path = initialized.sacas_root / "tasks" / "current" / "active_context.json"
    state = json.loads(context_path.read_text(encoding="utf-8"))
    mutate(state)
    context_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(CanonicalStateError, match=expected):
        load_active_context(context_path.parent)
    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert get_status_report(installation)["status"] == "invalid_canonical_state"


def test_runtime_pack_loader_refuses_invalid_nested_selection_without_writing(tmp_path: Path) -> None:
    """The runtime entrypoint receives the typed canonical-state refusal too."""
    from sacas.cli import main
    from sacas.compiler import load_validated_context_pack
    from sacas.init import initialize
    from sacas.task_contract import CanonicalStateError

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    assert main(["task", "Invalid runtime state", "--root", str(tmp_path), "--files", "src/app.py"]) == 0
    task_dir = initialized.sacas_root / "tasks" / "current"
    context_path = task_dir / "active_context.json"
    state = json.loads(context_path.read_text(encoding="utf-8"))
    state["files"][0]["selection"] = {"mode": "symbols", "symbols": [{"name": 1}]}
    context_path.write_text(json.dumps(state), encoding="utf-8")
    before_context = context_path.read_bytes()
    pack_path = initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    before_pack = pack_path.read_bytes()

    with pytest.raises(CanonicalStateError, match="selection.symbols"):
        load_validated_context_pack(initialized.installation)

    assert context_path.read_bytes() == before_context
    assert pack_path.read_bytes() == before_pack


def test_canonical_loaders_accept_schema_v1_defaulted_fields(tmp_path: Path) -> None:
    """Strictness applies to supplied values, not valid schema-v1 omissions."""
    from sacas.task_contract import TaskContract, load_task_contract

    (tmp_path / "task.json").write_text(json.dumps({
        "task_id": "legacy-v1", "goal": "Compatibility", "category": "investigate",
    }), encoding="utf-8")
    (tmp_path / "active_context.json").write_text(json.dumps({
        "schema_version": 1, "task_id": "legacy-v1",
        "files": [{"path": "src/app.py", "selection": {"mode": "full"}, "source": "explicit"}],
    }), encoding="utf-8")

    assert load_task_contract(tmp_path) == TaskContract(1, "legacy-v1", "Compatibility", "investigate", (), (), ())
    manifest = load_active_context(tmp_path)
    assert manifest is not None
    assert manifest.files[0].git_revision == "unknown"


@pytest.mark.parametrize("filename", ("task.json", "active_context.json"))
def test_canonical_loader_rejects_directory_artifact_without_legacy_fallback(
    tmp_path: Path, filename: str,
) -> None:
    """Canonical paths must be regular files; directories are corruption, not absence."""
    from sacas.task_contract import CanonicalStateError, load_task_contract

    (tmp_path / filename).mkdir()
    legacy = tmp_path / "expansions.json"
    legacy.write_text(json.dumps({"schema_version": 2, "task_id": "legacy", "goal": "Legacy"}), encoding="utf-8")

    with pytest.raises(CanonicalStateError, match=filename):
        if filename == "task.json":
            load_task_contract(tmp_path)
        else:
            load_active_context(tmp_path)
    assert legacy.is_file()


def test_public_consumers_refuse_task_context_identity_mismatch_without_mutation(tmp_path: Path) -> None:
    """Canonical pair disagreement is an error, never an implicit missing contract."""
    from sacas.benchmark import run_benchmark
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.provenance import query_why_file
    from sacas.status import get_status_report

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    assert main(["task", "Mismatched state", "--root", str(tmp_path), "--files", "src/app.py"]) == 0
    task_dir = initialized.sacas_root / "tasks" / "current"
    contract_path = task_dir / "task.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["task_id"] = "different-task"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    before_contract = contract_path.read_bytes()
    before_context = (task_dir / "active_context.json").read_bytes()
    installation = discover_manifest(tmp_path)
    assert installation is not None
    expected = "Canonical task state is corrupt: task.json disagrees with active_context.json"

    assert get_status_report(installation)["error"] == expected
    assert run_benchmark(installation) == {"active_task": False, "error": expected}
    assert query_why_file(installation, "src/app.py") == [expected]
    assert main(["why", "src/app.py", "--root", str(tmp_path)]) == 1
    assert main(["expand", "--root", str(tmp_path), "--file", "src/app.py"]) == 1
    assert main(["status", "--root", str(tmp_path), "--format", "json"]) == 1
    assert contract_path.read_bytes() == before_contract
    assert (task_dir / "active_context.json").read_bytes() == before_context

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
