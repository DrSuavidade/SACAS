"""Behavioral tests for SACAS context refresh, suggestions, and status."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


def test_status_command_requires_task_or_reports_none(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    init_result = initialize(tmp_path)
    
    # Run status before any task is created
    exit_code = main(["status", "--root", str(tmp_path), "--format", "json"])
    assert exit_code == 0


def test_refresh_and_status_behavior(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    
    init_result = initialize(tmp_path)

    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("print('hello')", encoding="utf-8")

    # Create a task
    main([
        "task",
        "Test goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
    # Write Graphify evidence with some edges for app.py
    # Let's say app.py is called by src/caller.py and has tests/test_app.py
    graphify_manifest_path = init_result.sacas_root / ".sacas" / "graphify.json"
    evidence_data = {
        "output": "graphify-out",
        "status": "fresh",
        "provenance": "graphify_existing",
        "freshness": "fresh",
        "content_hash": "dummyhash",
        "nodes": [
            ["node_app", "src/app.py"],
            ["node_caller", "src/caller.py"],
            ["node_test", "tests/test_app.py"]
        ],
        "edges": [
            ["node_caller", "node_app", "calls"],
            ["node_test", "node_app", "tests"]
        ]
    }
    graphify_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    graphify_manifest_path.write_text(json.dumps(evidence_data), encoding="utf-8")
    
    # Also write a boundary to verify protected boundary refusal
    boundaries_file = init_result.sacas_root / "rules" / "boundaries.md"
    boundaries_file.write_text(
        "MANUAL src/caller.py | Do not expand caller\n", encoding="utf-8"
    )
    
    # Now run refresh to trigger suggestion candidate search
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # Verify tests/test_app.py was suggested (not protected), but src/caller.py was refused (protected)
    task_dir = init_result.sacas_root / "tasks" / "current"
    candidates_path = task_dir / "candidates.json"
    assert candidates_path.is_file()
    
    candidates_data = json.loads(candidates_path.read_text(encoding="utf-8"))
    cand_paths = [item["path"] for item in candidates_data["candidates"]]
    assert "tests/test_app.py" in cand_paths
    assert "src/caller.py" not in cand_paths
    
    # Now modify src/app.py to make it stale
    app_py.write_text("print('hello changed')", encoding="utf-8")
    
    # Verify status reports stale state
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    fresh_inst = discover_manifest(tmp_path)
    report = get_status_report(fresh_inst)
    assert report["status"] == "stale"
    assert "src/app.py" in report["stale_files"]


def test_refresh_predictive_budgeting_and_ranking(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    
    init_result = initialize(tmp_path)

    app_py = tmp_path / "src" / "app.py"
    app_py.parent.mkdir(parents=True, exist_ok=True)
    app_py.write_text("print('hello')", encoding="utf-8")

    # Create a task
    main([
        "task",
        "Test budget goal",
        "--root", str(tmp_path),
        "--files", "src/app.py"
    ])
    
    # Write Graphify evidence
    graphify_manifest_path = init_result.sacas_root / ".sacas" / "graphify.json"
    evidence_data = {
        "output": "graphify-out",
        "status": "fresh",
        "provenance": "graphify_existing",
        "freshness": "fresh",
        "content_hash": "dummyhash",
        "nodes": [
            ["node_app", "src/app.py"],
            ["node_caller", "src/caller.py"],
            ["node_test", "tests/test_app.py"]
        ],
        "edges": [
            ["node_caller", "node_app", "calls"],
            ["node_test", "node_app", "tests"]
        ]
    }
    graphify_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    graphify_manifest_path.write_text(json.dumps(evidence_data), encoding="utf-8")
    
    # Write caller.py and test_app.py
    caller_py = tmp_path / "src" / "caller.py"
    caller_py.parent.mkdir(parents=True, exist_ok=True)
    caller_py.write_text("print('caller')", encoding="utf-8")
    
    test_app_py = tmp_path / "tests" / "test_app.py"
    test_app_py.parent.mkdir(parents=True, exist_ok=True)
    test_app_py.write_text("print('test')", encoding="utf-8")
    
    # Refresh context
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    candidates = json.loads((task_dir / "candidates.json").read_text(encoding="utf-8"))
    
    cand_paths = [item["path"] for item in candidates["candidates"]]
    assert "src/caller.py" in cand_paths
    assert "tests/test_app.py" in cand_paths


def test_schema_migration_v1_to_v2(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.refresh import refresh_context
    import json
    
    init_result = initialize(tmp_path)
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    expansions_path = task_dir / "expansions.json"
    v1_data = {
        "initial_files": {"src/app.py": "hash_val"},
        "expanded_files": {"src/helper.py": "hash_val2"},
        "goal": "V1 task upgrade"
    }
    expansions_path.write_text(json.dumps(v1_data), encoding="utf-8")
    
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "app.py").write_text("print()", encoding="utf-8")
    (tmp_path / "src" / "helper.py").write_text("print()", encoding="utf-8")
    
    manifest_path = init_result.sacas_root / ".sacas" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["current_task_id"] = "task_v1"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    
    from sacas.paths import discover_manifest
    changed = refresh_context(discover_manifest(tmp_path))
    
    # Verify legacy file is deleted
    assert not expansions_path.exists()
    
    # Verify active_context.json exists and contains correct schema
    active_path = task_dir / "active_context.json"
    assert active_path.is_file()
    
    active_data = json.loads(active_path.read_text(encoding="utf-8"))
    assert active_data.get("schema_version") == 1
    
    files_paths = [f["path"] for f in active_data["files"]]
    assert "src/app.py" in files_paths
    assert "src/helper.py" in files_paths


def test_refresh_preserves_contract_criteria_constraints_verification(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize
    from sacas.task_contract import load_task_contract
    
    init_result = initialize(tmp_path)
    
    # Create task with criteria, constraints, and verification
    main([
        "task",
        "Implement auth tokens",
        "--root", str(tmp_path),
        "--criteria", "Criteria-A", "Criteria-B",
        "--constraints", "Constraint-C",
        "--verification", "Verify-D"
    ])
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    contract = load_task_contract(task_dir)
    assert contract is not None
    assert contract.criteria == ("Criteria-A", "Criteria-B")
    assert contract.constraints == ("Constraint-C",)
    assert contract.verification == ("Verify-D",)
    
    # Run refresh
    exit_code = main(["refresh", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # Reload and verify they are preserved exactly
    contract_after = load_task_contract(task_dir)
    assert contract_after is not None
    assert contract_after.criteria == ("Criteria-A", "Criteria-B")
    assert contract_after.constraints == ("Constraint-C",)
    assert contract_after.verification == ("Verify-D",)


def test_refresh_converges_contract_fingerprint_and_context_pack_in_one_run(tmp_path: Path) -> None:
    """Editing task.json cannot leave the manifest and compiled pack on the old contract."""
    from sacas.compiler import read_context_pack
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import TaskContract, save_task_contract, task_contract_hash
    from sacas.active_context import load_active_context

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(): pass\n", encoding="utf-8")
    from sacas.tasks import generate_task
    generate_task(initialized.installation, "Update auth", files=("src/auth.py",))

    task_dir = initialized.sacas_root / "tasks" / "current"
    changed_contract = TaskContract(
        schema_version=1,
        task_id="task-contract-identifier",
        goal="Investigate payment ledger failures",
        category="bugfix",
        criteria=("new criterion",),
        constraints=(),
        verification=(),
    )
    save_task_contract(task_dir, changed_contract)

    refreshed_installation = discover_manifest(tmp_path)
    assert refreshed_installation is not None
    assert refresh_context(refreshed_installation) is True

    manifest = load_active_context(task_dir)
    assert manifest is not None
    expected = task_contract_hash(changed_contract)
    assert manifest.task_id == changed_contract.task_id
    assert manifest.goal == changed_contract.goal
    assert manifest.category == changed_contract.category
    assert manifest.task_contract_hash == expected
    header, _ = read_context_pack(initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl")
    assert header.task_id == changed_contract.task_id
    assert header.task_contract_hash == expected

    # A converged contract must not keep causing a rewrite on every refresh.
    manifest_identity = (task_dir / "active_context.json").read_bytes()
    pack_path = initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    pack_identity = pack_path.read_bytes()
    assert refresh_context(discover_manifest(tmp_path)) is False
    assert (task_dir / "active_context.json").read_bytes() == manifest_identity
    assert pack_path.read_bytes() == pack_identity


def _configure_custom_graph_output(repository: Path, output: str, mode: str = "existing") -> None:
    """Persist a normal installation configuration; routing reads graph bytes directly."""
    manifest_path = repository / "Structure" / ".sacas" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["graphify_mode"] = mode
    manifest["graphify_output"] = output
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _custom_graph_provider(monkeypatch: pytest.MonkeyPatch, repository: Path, output: str) -> None:
    from sacas.graphify import JsonGraphifyProvider

    graph_path = repository / output / "graph.json"

    class QueryableJsonProvider(JsonGraphifyProvider):
        # This is a test adapter for a configured graph file.  Production may
        # select a CLI provider; the scenario needs deterministic real JSON
        # query behavior without consulting SACAS graphify metadata.
        def verify_capabilities(self, required: set[str]) -> bool:
            return self._read_data() is not None

    monkeypatch.setattr(
        "sacas.graphify.get_graphify_provider",
        lambda *_args, **_kwargs: QueryableJsonProvider(graph_path, repository),
    )


def _write_graph(path: Path, target: str) -> bytes:
    raw = json.dumps({"nodes": [{"id": target, "path": target}], "edges": []}).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def test_custom_graph_bytes_drive_refresh_identity_reroute_and_convergence(tmp_path: Path) -> None:
    """A configured custom graph is canonical input, including raw-byte-only changes."""
    import hashlib
    from sacas.active_context import load_active_context
    from sacas.compiler import read_context_pack
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialize(tmp_path, graphify_mode="existing")
    _configure_custom_graph_output(tmp_path, "custom-graph")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(): pass\n", encoding="utf-8")
    graph_path = tmp_path / "custom-graph" / "graph.json"
    first_raw = _write_graph(graph_path, "src/auth.py")
    installation = discover_manifest(tmp_path)
    assert installation is not None
    generate_task(installation, "auth.py")
    task_dir = tmp_path / "Structure" / "tasks" / "current"
    first_manifest = load_active_context(task_dir)
    assert first_manifest is not None
    assert first_manifest.graph_snapshot_hash == hashlib.sha256(first_raw).hexdigest()
    assert any(item.source == "graphify" for item in first_manifest.files)

    # Semantically identical JSON with different raw bytes is a distinct evidence snapshot.
    second_raw = first_raw + b"\n"
    graph_path.write_bytes(second_raw)
    assert refresh_context(discover_manifest(tmp_path)) is True
    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert refreshed.graph_snapshot_hash == hashlib.sha256(second_raw).hexdigest()
    assert any(event.source == "graphify" for event in refreshed.events)
    header, _ = read_context_pack(tmp_path / "Structure" / ".sacas" / "runtime" / "context.pack.jsonl")
    assert header.graph_snapshot_hash == hashlib.sha256(second_raw).hexdigest()
    assert refresh_context(discover_manifest(tmp_path)) is False


def test_graph_mode_off_and_graph_deletion_clear_identity_then_converge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing configured graph evidence never preserves a stale snapshot identity."""
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialize(tmp_path, graphify_mode="existing")
    _configure_custom_graph_output(tmp_path, "custom-graph")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(): pass\n", encoding="utf-8")
    graph_path = tmp_path / "custom-graph" / "graph.json"
    _write_graph(graph_path, "src/auth.py")
    _custom_graph_provider(monkeypatch, tmp_path, "custom-graph")
    installation = discover_manifest(tmp_path)
    assert installation is not None
    generate_task(installation, "auth.py")
    task_dir = tmp_path / "Structure" / "tasks" / "current"

    _configure_custom_graph_output(tmp_path, "custom-graph", mode="off")
    assert refresh_context(discover_manifest(tmp_path)) is True
    off_manifest = load_active_context(task_dir)
    assert off_manifest is not None
    assert off_manifest.graph_snapshot_hash == ""
    assert any(item.source == "heuristic" for item in off_manifest.files)
    assert refresh_context(discover_manifest(tmp_path)) is False

    _configure_custom_graph_output(tmp_path, "custom-graph", mode="existing")
    graph_path.unlink()
    assert refresh_context(discover_manifest(tmp_path)) is False
    deleted_manifest = load_active_context(task_dir)
    assert deleted_manifest is not None
    assert deleted_manifest.graph_snapshot_hash == ""


def test_deleting_a_configured_graph_clears_identity_uses_fallback_and_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deletion is an invalidation event even when the graph had previously routed matches."""
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialize(tmp_path, graphify_mode="existing")
    _configure_custom_graph_output(tmp_path, "custom-graph")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(): pass\n", encoding="utf-8")
    graph_path = tmp_path / "custom-graph" / "graph.json"
    _write_graph(graph_path, "src/auth.py")
    _custom_graph_provider(monkeypatch, tmp_path, "custom-graph")
    installation = discover_manifest(tmp_path)
    assert installation is not None
    generate_task(installation, "auth.py")

    graph_path.unlink()
    assert refresh_context(discover_manifest(tmp_path)) is True
    task_dir = tmp_path / "Structure" / "tasks" / "current"
    deleted_manifest = load_active_context(task_dir)
    assert deleted_manifest is not None
    assert deleted_manifest.graph_snapshot_hash == ""
    assert any(item.source == "heuristic" for item in deleted_manifest.files)
    assert refresh_context(discover_manifest(tmp_path)) is False


@pytest.mark.parametrize("provider_result", ("failure", "no_matches"))
def test_graph_fallback_keeps_valid_raw_identity_and_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_result: str
) -> None:
    """Optional Graphify failures retain valid evidence identity while using lexical routing."""
    import hashlib
    from sacas.active_context import load_active_context
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialize(tmp_path, graphify_mode="existing")
    _configure_custom_graph_output(tmp_path, "custom-graph")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(): pass\n", encoding="utf-8")
    raw = _write_graph(tmp_path / "custom-graph" / "graph.json", "src/auth.py")

    class FallbackProvider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            if provider_result == "failure":
                return None
            return GraphifyQueryResult(
                status="success", nodes=(), edges=(), raw_output="no matches", paths=()
            )

    graph_path = tmp_path / "custom-graph" / "graph.json"
    monkeypatch.setattr(
        "sacas.graphify.get_graphify_provider",
        lambda *_args, **_kwargs: FallbackProvider(graph_path, tmp_path),
    )
    installation = discover_manifest(tmp_path)
    assert installation is not None
    generate_task(installation, "auth.py")

    task_dir = tmp_path / "Structure" / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    assert manifest.graph_snapshot_hash == hashlib.sha256(raw).hexdigest()
    assert any(item.source == "heuristic" for item in manifest.files)
    assert any(event.source == "heuristic" for event in manifest.events)
    assert refresh_context(discover_manifest(tmp_path)) is False


@pytest.mark.parametrize("provider_result", ("failure", "no_matches"))
def test_graph_refresh_fallback_replaces_stale_graph_provenance_and_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider_result: str
) -> None:
    """A changed valid graph that cannot route must replace, not retain, old graph admissions."""
    import hashlib
    from sacas.active_context import load_active_context
    from sacas.compiler import read_context_pack
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialize(tmp_path, graphify_mode="existing")
    _configure_custom_graph_output(tmp_path, "custom-graph")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def login(): pass\n", encoding="utf-8")
    graph_path = tmp_path / "custom-graph" / "graph.json"
    _write_graph(graph_path, "src/auth.py")

    phase = "matching"

    class LifecycleProvider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

        def query(self, goal: str, graph_file: Path, *, token_budget: int | None = None):
            if phase == "matching":
                return super().query(goal, graph_file, token_budget=token_budget)
            if provider_result == "failure":
                return None
            return GraphifyQueryResult("success", (), (), "no matches", paths=())

    monkeypatch.setattr(
        "sacas.graphify.get_graphify_provider",
        lambda *_args, **_kwargs: LifecycleProvider(graph_path, tmp_path),
    )
    installation = discover_manifest(tmp_path)
    assert installation is not None
    generate_task(installation, "auth.py")
    task_dir = tmp_path / "Structure" / "tasks" / "current"
    initial = load_active_context(task_dir)
    assert initial is not None
    assert any(item.source == "graphify" for item in initial.files)
    assert any(event.source == "graphify" for event in initial.events)

    phase = "fallback"
    new_raw = graph_path.read_bytes() + b"\n"
    graph_path.write_bytes(new_raw)
    assert refresh_context(discover_manifest(tmp_path)) is True

    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    expected_hash = hashlib.sha256(new_raw).hexdigest()
    assert refreshed.graph_snapshot_hash == expected_hash
    assert not any(item.source == "graphify" for item in refreshed.files)
    assert not any(event.source == "graphify" for event in refreshed.events)
    assert any(item.source == "heuristic" for item in refreshed.files)
    assert any(event.source == "heuristic" for event in refreshed.events)
    pack_path = tmp_path / "Structure" / ".sacas" / "runtime" / "context.pack.jsonl"
    header, _ = read_context_pack(pack_path)
    assert header.graph_snapshot_hash == expected_hash

    pack_bytes = pack_path.read_bytes()
    assert refresh_context(discover_manifest(tmp_path)) is False
    assert pack_path.read_bytes() == pack_bytes
