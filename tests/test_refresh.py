"""Behavioral tests for SACAS context refresh, suggestions, and status."""

from __future__ import annotations

import json
import hashlib
from dataclasses import replace
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


def test_status_checks_reference_and_working_file_layers(tmp_path: Path) -> None:
    """Status must not call a pack fresh while any admitted file layer changed."""
    from sacas.active_context import ActiveFileContext, load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.status import get_status_report
    from sacas.tasks import generate_task, publish_task_artifacts

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "source.py"
    reference = tmp_path / "src" / "reference.py"
    working = tmp_path / "src" / "working.py"
    source.parent.mkdir()
    source.write_text("source = 1\n", encoding="utf-8")
    reference.write_text("reference = 1\n", encoding="utf-8")
    working.write_text("working = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Layer status", files=("src/source.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    updated = replace(
        manifest,
        reference_files=(
            ActiveFileContext(
                path="src/reference.py", selection={"mode": "full"}, source="explicit",
                hash=hashlib.sha256(reference.read_bytes()).hexdigest(),
            ),
        ),
        working_files=(
            ActiveFileContext(
                path="src/working.py", selection={"mode": "full"}, source="explicit",
                hash=hashlib.sha256(working.read_bytes()).hexdigest(),
            ),
        ),
    )
    publish_task_artifacts(initialized.installation, task_dir, updated, {})
    reference.write_text("reference = 2\n", encoding="utf-8")
    working.write_text("working = 2\n", encoding="utf-8")

    report = get_status_report(discover_manifest(tmp_path))
    assert report["status"] == "stale"
    assert {"src/reference.py", "src/working.py"}.issubset(report["stale_files"])


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


def test_refresh_removes_runtime_pack_before_rerouting_an_invalidated_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reroute never observes the pack that was built from stale identity."""
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import TaskContract, save_task_contract
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Original", files=("src/one.py",))
    pack_path = initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    assert pack_path.is_file()

    task_dir = initialized.sacas_root / "tasks" / "current"
    save_task_contract(task_dir, TaskContract(1, "new-task", "Replacement", "investigate", (), (), ()))

    import sacas.refresh as refresh_module
    original_reroute = refresh_module._re_route_files

    def observe_invalidated_pack(*args: object, **kwargs: object):
        assert not pack_path.exists()
        return original_reroute(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "_re_route_files", observe_invalidated_pack)
    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True


def test_refresh_compile_failure_keeps_canonical_manifest_and_removes_pack(tmp_path: Path) -> None:
    """Failed compilation publishes neither a source rehash nor a stale runtime pack."""
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task
    from sacas.active_context import ActiveRuleContext, load_active_context, save_active_context

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Keep canonical", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    rule = initialized.sacas_root / "rules" / "custom.md"
    rule.write_text("safe rule\n", encoding="utf-8")
    manifest = load_active_context(task_dir)
    assert manifest is not None
    save_active_context(
        task_dir,
        replace(
            manifest,
            rules=(ActiveRuleContext(
                path="Structure/rules/custom.md",
                hash=hashlib.sha256(rule.read_bytes()).hexdigest(),
                reason="required rule",
            ),),
        ),
    )
    manifest_path = task_dir / "active_context.json"
    before = manifest_path.read_bytes()
    rule.write_bytes(b"\x00unsafe")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="rule_binary"):
        refresh_context(installation)

    assert manifest_path.read_bytes() == before
    assert not (initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl").exists()


def test_refresh_refuses_missing_admitted_source_without_mutating_canonical_state(
    tmp_path: Path,
) -> None:
    """A deleted admission is an error, not permission to erase its history."""
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "one.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Keep admissions", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest_path = task_dir / "active_context.json"
    before = manifest_path.read_bytes()
    assert load_active_context(task_dir) is not None
    source.unlink()

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="canonical admission unavailable: src/one.py"):
        refresh_context(installation)

    assert manifest_path.read_bytes() == before
    assert not (initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl").exists()


def test_legacy_refresh_missing_source_does_not_materialize_contract_or_mutate_context(
    tmp_path: Path,
) -> None:
    """Rejected legacy refreshes must not persist their synthesized contract."""
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "legacy.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Legacy admission", files=("src/legacy.py",))

    task_dir = initialized.sacas_root / "tasks" / "current"
    context_path = task_dir / "active_context.json"
    contract_path = task_dir / "task.json"
    before_context = context_path.read_bytes()
    contract_path.unlink()
    source.unlink()

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="canonical admission unavailable: src/legacy.py"):
        refresh_context(installation)

    assert not contract_path.exists()
    assert context_path.read_bytes() == before_context
    assert not (initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl").exists()


def test_true_legacy_refresh_failure_keeps_expansions_and_creates_no_canonical_state(
    tmp_path: Path,
) -> None:
    """A legacy-only task must pass the secure gate before migration writes."""
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context

    initialized = initialize(tmp_path, graphify_mode="off")
    task_dir = initialized.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    expansions_path = task_dir / "expansions.json"
    expansions_path.write_text(
        json.dumps({
            "task_id": "legacy-only",
            "goal": "Repair a missing legacy source",
            "initial_files": {"src/missing.py": "legacy-hash"},
            "expanded_files": {},
        }),
        encoding="utf-8",
    )
    expansions_before = expansions_path.read_bytes()

    manifest_path = initialized.sacas_root / ".sacas" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["current_task_id"] = "legacy-only"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="canonical admission unavailable: src/missing.py"):
        refresh_context(installation)

    assert not (task_dir / "task.json").exists()
    assert not (task_dir / "active_context.json").exists()
    assert expansions_path.read_bytes() == expansions_before


def test_true_legacy_refresh_binary_source_keeps_expansions_and_creates_no_canonical_state(
    tmp_path: Path,
) -> None:
    """The non-mutating legacy path also protects rejected binary admissions."""
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "legacy.py"
    source.parent.mkdir()
    source.write_bytes(b"\x00binary")
    task_dir = initialized.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    expansions_path = task_dir / "expansions.json"
    expansions_path.write_text(
        json.dumps({
            "task_id": "legacy-binary",
            "goal": "Repair a binary legacy source",
            "initial_files": {"src/legacy.py": "legacy-hash"},
            "expanded_files": {},
        }),
        encoding="utf-8",
    )
    expansions_before = expansions_path.read_bytes()

    manifest_path = initialized.sacas_root / ".sacas" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["current_task_id"] = "legacy-binary"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="source_binary: src/legacy.py"):
        refresh_context(installation)

    assert not (task_dir / "task.json").exists()
    assert not (task_dir / "active_context.json").exists()
    assert expansions_path.read_bytes() == expansions_before


def test_selective_refresh_refuses_when_an_unselected_context_layer_is_stale(tmp_path: Path) -> None:
    """A selective refresh must not publish a partially-current manifest."""
    from dataclasses import replace
    from sacas.active_context import ActiveFileContext, load_active_context, save_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    extra = tmp_path / "docs" / "runbook.md"
    extra.write_text("first\n", encoding="utf-8")
    generate_task(initialized.installation, "Update main", files=("src/main.py",))

    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    reference = ActiveFileContext(
        path="docs/runbook.md", selection={"mode": "full"}, source="explicit",
        hash=hashlib.sha256(extra.read_bytes()).hexdigest(), role="reference",
        reason="explicit runbook",
    )
    save_active_context(task_dir, replace(manifest, reference_files=(reference,)))
    before = (task_dir / "active_context.json").read_bytes()
    extra.write_text("second\n", encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="unselected stale context"):
        refresh_context(installation, selective_files=("src/main.py",))
    assert (task_dir / "active_context.json").read_bytes() == before


def test_selective_refresh_refuses_stale_rule_or_reference_without_writing(tmp_path: Path) -> None:
    """Rules and references are canonical inputs, not exempt metadata."""
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("def main(): pass\n", encoding="utf-8")
    rule = initialized.sacas_root / "rules" / "custom.md"
    reference = initialized.sacas_root / "references" / "custom.md"
    rule.write_text("first rule\n", encoding="utf-8")
    reference.write_text("first reference\n", encoding="utf-8")
    generate_task(
        initialized.installation,
        "Update main",
        files=("src/main.py",),
        rules=("rules/custom.md",),
        references=("references/custom.md",),
    )

    task_dir = initialized.sacas_root / "tasks" / "current"
    before = (task_dir / "active_context.json").read_bytes()
    rule.write_text("second rule\n", encoding="utf-8")
    reference.write_text("second reference\n", encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    with pytest.raises(ValueError, match="unselected stale context"):
        refresh_context(installation, selective_files=("src/main.py",))
    assert (task_dir / "active_context.json").read_bytes() == before


def test_refresh_rehashes_rules_and_references(tmp_path: Path) -> None:
    """An ordinary refresh updates each non-source canonical input hash."""
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "main.py"
    source.parent.mkdir()
    source.write_text("def main(): pass\n", encoding="utf-8")
    rule = initialized.sacas_root / "rules" / "custom.md"
    reference = initialized.sacas_root / "references" / "custom.md"
    rule.write_text("first rule\n", encoding="utf-8")
    reference.write_text("first reference\n", encoding="utf-8")
    generate_task(
        initialized.installation,
        "Update main",
        files=("src/main.py",),
        rules=("rules/custom.md",),
        references=("references/custom.md",),
    )
    rule.write_text("second rule\n", encoding="utf-8")
    reference.write_text("second reference\n", encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    refreshed = load_active_context(initialized.sacas_root / "tasks" / "current")
    assert refreshed is not None
    assert refreshed.rules[0].hash == hashlib.sha256(rule.read_bytes()).hexdigest()
    assert refreshed.references[0].hash == hashlib.sha256(reference.read_bytes()).hexdigest()


def test_refresh_rehashes_every_context_file_layer(tmp_path: Path) -> None:
    """Source refresh updates hashes in files, reference_files, and working_files."""
    from dataclasses import replace
    from sacas.active_context import ActiveFileContext, load_active_context, save_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    extra = tmp_path / "docs" / "runbook.md"
    extra.write_text("first\n", encoding="utf-8")
    generate_task(initialized.installation, "Update main", files=("src/main.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    context = ActiveFileContext(path="docs/runbook.md", selection={"mode": "full"}, source="explicit", hash="old", role="reference")
    save_active_context(task_dir, replace(manifest, reference_files=(context,), working_files=(context,)))
    extra.write_text("second\n", encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    expected = hashlib.sha256(extra.read_bytes()).hexdigest()
    assert refreshed.reference_files[0].hash == expected
    assert refreshed.working_files[0].hash == expected


def test_task_reroute_keeps_explicit_admission_ids_for_all_explicit_context(tmp_path: Path) -> None:
    """Task invalidation preserves user context evidence while discovery is recomputed."""
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import TaskContract, load_task_contract, save_task_contract
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass\n", encoding="utf-8")
    (initialized.sacas_root / "rules" / "custom.md").write_text("rule\n", encoding="utf-8")
    (initialized.sacas_root / "references" / "custom.md").write_text("reference\n", encoding="utf-8")
    generate_task(
        initialized.installation, "Update main", files=("src/main.py",),
        tests=("tests/test_main.py",), rules=("rules/custom.md",), references=("references/custom.md",),
    )
    task_dir = initialized.sacas_root / "tasks" / "current"
    before = load_active_context(task_dir)
    assert before is not None
    explicit_before = {event.target: event.id for event in before.events if event.source == "explicit"}
    assert {"src/main.py", "tests/test_main.py", "Structure/rules/custom.md", "Structure/references/custom.md"} <= explicit_before.keys()

    contract = load_task_contract(task_dir)
    assert contract is not None
    save_task_contract(task_dir, TaskContract(
        schema_version=contract.schema_version, task_id=contract.task_id, goal=contract.goal,
        category=contract.category, criteria=("new criterion",), constraints=contract.constraints,
        verification=contract.verification,
    ))
    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    after = load_active_context(task_dir)
    assert after is not None
    explicit_after = {event.target: event.id for event in after.events if event.source == "explicit"}
    assert explicit_after == explicit_before


def test_task_reroute_preserves_explicit_layer_membership_and_discards_other_origins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A contract change retains explicit entries in their original layer only."""
    from dataclasses import replace
    from sacas.active_context import ActiveFileContext, load_active_context, save_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import load_task_contract, save_task_contract
    from sacas.tasks import generate_task
    import sacas.tasks

    initialized = initialize(tmp_path, graphify_mode="off")
    for name in ("main.py", "reference_explicit.py", "reference_heuristic.py", "reference_graph.py", "working_explicit.py", "working_heuristic.py", "working_graph.py"):
        path = tmp_path / "src" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"def {name[:-3]}(): pass\n", encoding="utf-8")
    generate_task(initialized.installation, "Update main", files=("src/main.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None

    def context(path: str, source: str) -> ActiveFileContext:
        return ActiveFileContext(
            path=path,
            selection={"mode": "full"},
            source=source,
            hash=hashlib.sha256((tmp_path / path).read_bytes()).hexdigest(),
            reason=f"{source} admission",
        )

    reference_items = (
        context("src/reference_explicit.py", "explicit"),
        context("src/reference_heuristic.py", "heuristic"),
        context("src/reference_graph.py", "graphify"),
    )
    working_items = (
        context("src/working_explicit.py", "explicit"),
        context("src/working_heuristic.py", "heuristic"),
        context("src/working_graph.py", "graphify"),
    )
    save_active_context(task_dir, replace(original, reference_files=reference_items, working_files=working_items))
    contract = load_task_contract(task_dir)
    assert contract is not None
    save_task_contract(task_dir, replace(contract, criteria=("a changed contract",)))

    observed: list[dict[str, object]] = []
    original_route_goal = sacas.tasks.route_goal

    def record_route_goal(*args, **kwargs):
        observed.append(kwargs)
        return original_route_goal(*args, **kwargs)

    monkeypatch.setattr(sacas.tasks, "route_goal", record_route_goal)
    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True

    assert {file.path for file in observed[0]["seed_files"]} >= {
        "src/main.py", "src/reference_explicit.py", "src/working_explicit.py",
    }
    assert {file.source for file in observed[0]["seed_files"]} == {"explicit"}
    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert [file.path for file in refreshed.reference_files] == ["src/reference_explicit.py"]
    assert [file.path for file in refreshed.working_files] == ["src/working_explicit.py"]
    assert not {
        "src/reference_heuristic.py", "src/reference_graph.py",
        "src/working_heuristic.py", "src/working_graph.py",
    } & {file.path for file in refreshed.all_files}


def test_source_refresh_reresolves_symbols_without_replacing_selector_events(tmp_path: Path) -> None:
    """A changed selector keeps its independently-addressable admission evidence."""
    from dataclasses import replace
    from sacas.active_context import ActiveSymbolContext, AdmissionEvent, SourceRange, load_active_context, save_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("\n\ndef work():\n    return 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Investigate service", files=("src/service.py",), symbols=("src/service.py::work",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    file = replace(original.files[0], source="heuristic", evidence=("lexical",), reason="matched goal")
    events = (
        AdmissionEvent("evt-file", "src/service.py", "admit", "heuristic", "matched", "initial"),
        AdmissionEvent("evt-symbol", "src/service.py::work", "admit", "heuristic", "selector", "initial"),
    )
    save_active_context(task_dir, replace(original, files=(file,), events=events))
    source.write_text("\n\n\n\ndef work():\n    return 1\n", encoding="utf-8")

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True

    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert refreshed.files[0].source == "heuristic"
    assert refreshed.files[0].evidence == ("lexical",)
    symbol = refreshed.files[0].selection["symbols"][0]
    assert symbol.name == "work"
    assert symbol.range is not None and symbol.range.start_line == 5
    assert [event.id for event in refreshed.events] == ["evt-file", "evt-symbol"]
    assert refreshed.events[1].target == "src/service.py::work"


def test_task_reroute_seeds_explicit_context_before_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract changes feed preserved user context to routing as budgeted seeds."""
    from dataclasses import replace
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import TaskContract, load_task_contract, save_task_contract
    from sacas.tasks import generate_task
    import sacas.tasks

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_main.py").write_text("def test_main(): pass\n", encoding="utf-8")
    (initialized.sacas_root / "rules" / "custom.md").write_text("rule\n", encoding="utf-8")
    (initialized.sacas_root / "references" / "custom.md").write_text("reference\n", encoding="utf-8")
    generate_task(
        initialized.installation, "Update main", files=("src/main.py",),
        tests=("tests/test_main.py",), rules=("rules/custom.md",), references=("references/custom.md",),
    )
    task_dir = initialized.sacas_root / "tasks" / "current"
    contract = load_task_contract(task_dir)
    assert contract is not None
    save_task_contract(task_dir, replace(contract, criteria=("new criterion",)))

    observed: list[dict[str, object]] = []
    original_route_goal = sacas.tasks.route_goal
    def record_route_goal(*args, **kwargs):
        observed.append(kwargs)
        return original_route_goal(*args, **kwargs)
    monkeypatch.setattr(sacas.tasks, "route_goal", record_route_goal)

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    assert len(observed) == 1
    assert [file.path for file in observed[0]["seed_files"]] == ["src/main.py"]
    assert observed[0]["seed_tests"] == ("tests/test_main.py",)
    assert [rule.path for rule in observed[0]["seed_rules"]] == ["Structure/rules/custom.md"]
    assert [reference.path for reference in observed[0]["seed_references"]] == ["Structure/references/custom.md"]
    assert {event.target for event in observed[0]["seed_events"]} >= {
        "src/main.py", "tests/test_main.py", "Structure/rules/custom.md", "Structure/references/custom.md",
    }


def test_full_reroute_discards_legacy_nonexplicit_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only still-admitted explicit test contexts seed a contract reroute."""
    from dataclasses import replace
    from sacas.active_context import ActiveFileContext, load_active_context, save_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import load_task_contract, save_task_contract
    from sacas.tasks import generate_task
    import sacas.tasks

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    explicit_test = tmp_path / "tests" / "test_explicit.py"
    legacy_test = tmp_path / "tests" / "test_legacy.py"
    explicit_test.write_text("def test_explicit(): pass\n", encoding="utf-8")
    legacy_test.write_text("def test_legacy(): pass\n", encoding="utf-8")
    generate_task(
        initialized.installation, "Update main",
        files=("src/main.py",), tests=("tests/test_explicit.py",),
    )
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    legacy_context = ActiveFileContext(
        path="tests/test_legacy.py", selection={"mode": "full"}, source="heuristic",
        hash=hashlib.sha256(legacy_test.read_bytes()).hexdigest(), role="test",
        reason="legacy heuristic test",
    )
    save_active_context(
        task_dir,
        replace(
            original,
            files=(*original.files, legacy_context),
            tests=("tests/test_explicit.py", "tests/test_legacy.py", "tests/not-admitted.py"),
        ),
    )
    contract = load_task_contract(task_dir)
    assert contract is not None
    save_task_contract(task_dir, replace(contract, criteria=("new criterion",)))

    observed: list[dict[str, object]] = []
    original_route_goal = sacas.tasks.route_goal
    def record_route_goal(*args, **kwargs):
        observed.append(kwargs)
        return original_route_goal(*args, **kwargs)
    monkeypatch.setattr(sacas.tasks, "route_goal", record_route_goal)

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    assert observed[0]["seed_tests"] == ("tests/test_explicit.py",)
    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert refreshed.tests == ("tests/test_explicit.py",)
    assert "tests/test_legacy.py" not in {file.path for file in refreshed.all_files}


def test_full_reroute_seeds_explicit_rules_and_references_by_reason_not_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit rule/reference retention is not coupled to optional event history."""
    from dataclasses import replace
    from sacas.active_context import load_active_context, save_active_context
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import load_task_contract, save_task_contract
    from sacas.tasks import generate_task
    import sacas.tasks

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (initialized.sacas_root / "rules" / "custom.md").write_text("rule\n", encoding="utf-8")
    (initialized.sacas_root / "references" / "custom.md").write_text("reference\n", encoding="utf-8")
    generate_task(
        initialized.installation, "Update main", files=("src/main.py",),
        rules=("rules/custom.md",), references=("references/custom.md",),
    )
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    save_active_context(
        task_dir,
        replace(original, events=tuple(event for event in original.events if event.target == "src/main.py")),
    )
    contract = load_task_contract(task_dir)
    assert contract is not None
    save_task_contract(task_dir, replace(contract, criteria=("new criterion",)))

    observed: list[dict[str, object]] = []
    original_route_goal = sacas.tasks.route_goal
    def record_route_goal(*args, **kwargs):
        observed.append(kwargs)
        return original_route_goal(*args, **kwargs)
    monkeypatch.setattr(sacas.tasks, "route_goal", record_route_goal)

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    assert [rule.path for rule in observed[0]["seed_rules"]] == ["Structure/rules/custom.md"]
    assert [reference.path for reference in observed[0]["seed_references"]] == ["Structure/references/custom.md"]


def test_task_contract_reroute_replaces_heuristic_rules_and_references_but_keeps_explicit(
    tmp_path: Path,
) -> None:
    """A task change keeps explicit context and recomputes, rather than retaining, heuristics."""
    from dataclasses import replace
    from sacas.active_context import (
        ActiveReferenceContext,
        ActiveRuleContext,
        load_active_context,
        save_active_context,
    )
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.task_contract import load_task_contract, save_task_contract
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    rules_dir = initialized.sacas_root / "rules"
    references_dir = initialized.sacas_root / "references"
    (rules_dir / "custom.md").write_text("explicit rule\n", encoding="utf-8")
    (rules_dir / "authentication.md").write_text("old heuristic rule\n", encoding="utf-8")
    (rules_dir / "payments.md").write_text("recomputed heuristic rule\n", encoding="utf-8")
    (references_dir / "custom.md").write_text("explicit reference\n", encoding="utf-8")
    (references_dir / "authentication.md").write_text("old heuristic reference\n", encoding="utf-8")
    (references_dir / "payments.md").write_text("recomputed heuristic reference\n", encoding="utf-8")
    generate_task(
        initialized.installation,
        "Update authentication",
        files=("src/main.py",),
        rules=("rules/custom.md",),
        references=("references/custom.md",),
    )
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    save_active_context(
        task_dir,
        replace(
            original,
            rules=(*original.rules, ActiveRuleContext(
                path="Structure/rules/authentication.md", hash="old-rule", reason="Heuristic rule match",
            )),
            references=(*original.references, ActiveReferenceContext(
                path="Structure/references/authentication.md", selection={"mode": "full"},
                hash="old-reference", reason="Heuristic reference file match",
            )),
        ),
    )
    contract = load_task_contract(task_dir)
    assert contract is not None
    save_task_contract(task_dir, replace(contract, goal="Update payments"))

    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True

    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert "Structure/rules/authentication.md" not in {rule.path for rule in refreshed.rules}
    assert {
        "Structure/rules/custom.md", "Structure/rules/payments.md",
    } <= {rule.path for rule in refreshed.rules}
    assert {reference.path for reference in refreshed.references} == {
        "Structure/references/custom.md", "Structure/references/payments.md",
    }
    assert next(rule for rule in refreshed.rules if rule.path.endswith("custom.md")).reason == "Explicitly specified by user"
    assert next(reference for reference in refreshed.references if reference.path.endswith("custom.md")).reason == "Explicitly specified by user"


def test_graph_rediscovery_seeds_non_graph_context_and_explicit_origin_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rediscovery budgets retained context and cannot replace an explicit file's origin."""
    from dataclasses import replace
    from sacas.active_context import AdmissionEvent, ActiveFileContext, load_active_context, save_active_context
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task
    import sacas.tasks

    initialized = initialize(tmp_path, graphify_mode="existing")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def auth(): pass\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("def other(): pass\n", encoding="utf-8")
    for name in ("reference.py", "reference_graph.py", "working.py", "working_graph.py"):
        (tmp_path / "src" / name).write_text(f"def {name[:-3]}(): pass\n", encoding="utf-8")
    graph = tmp_path / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    generate_task(initialized.installation, "Investigate auth", files=("src/auth.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    heuristic = ActiveFileContext(
        path="src/other.py", selection={"mode": "full"}, source="heuristic", hash="",
        ranking_score=0.2, confidence=0.2, reason="matched goal",
    )
    def context(path: str, source: str) -> ActiveFileContext:
        return ActiveFileContext(
            path=path, selection={"mode": "full"}, source=source,
            hash=hashlib.sha256((tmp_path / path).read_bytes()).hexdigest(),
            reason=f"{source} context",
        )
    save_active_context(
        task_dir,
        replace(
            original,
            files=(*original.files, heuristic),
            reference_files=(
                context("src/reference.py", "explicit"),
                context("src/reference_graph.py", "graphify"),
            ),
            working_files=(
                context("src/working.py", "heuristic"),
                context("src/working_graph.py", "graphify"),
            ),
            events=(*original.events,
                AdmissionEvent("evt-reference-graph", "src/reference_graph.py", "admit", "graphify", "old graph", "initial"),
                AdmissionEvent("evt-working-graph", "src/working_graph.py", "admit", "graphify", "old graph", "initial"),
            ),
        ),
    )
    graph.write_text('{"nodes": [], "edges": [], "changed": true}', encoding="utf-8")

    observed: list[dict[str, object]] = []
    original_route_goal = sacas.tasks.route_goal
    def record_route_goal(*args, **kwargs):
        observed.append(kwargs)
        return original_route_goal(*args, **kwargs)
    monkeypatch.setattr(sacas.tasks, "route_goal", record_route_goal)

    class AuthGraphProvider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            return GraphifyQueryResult("success", (), (), "auth", paths=("src/auth.py",))

    monkeypatch.setattr("sacas.graphify.get_graphify_provider", lambda *_args, **_kwargs: AuthGraphProvider(graph, tmp_path))
    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True
    assert {file.path for file in observed[0]["seed_files"]} == {
        "src/auth.py", "src/other.py", "src/reference.py", "src/working.py",
    }
    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert next(file for file in refreshed.files if file.path == "src/auth.py").source == "explicit"
    assert not any(
        event.source == "graphify" and event.target.split("::", 1)[0] == "src/auth.py"
        for event in refreshed.events
    )
    assert [file.path for file in refreshed.reference_files] == ["src/reference.py"]
    assert [file.path for file in refreshed.working_files] == ["src/working.py"]
    assert not {
        "src/reference_graph.py", "src/working_graph.py",
    } & {file.path for file in refreshed.all_files}
    assert not any(event.source == "graphify" and event.target in {
        "src/reference_graph.py", "src/working_graph.py",
    } for event in refreshed.events)


def test_graph_rediscovery_replaces_heuristic_context_with_fresh_graph_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh Graphify hit supersedes a retained heuristic admission for its path."""
    from dataclasses import replace
    from sacas.active_context import AdmissionEvent, ActiveFileContext, load_active_context, save_active_context
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.refresh import refresh_context
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="existing")
    source = tmp_path / "src" / "auth.py"
    source.parent.mkdir()
    source.write_text("def auth(): pass\n", encoding="utf-8")
    graph = tmp_path / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text('{"nodes": [], "edges": []}', encoding="utf-8")
    generate_task(initialized.installation, "Investigate auth")
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    heuristic = ActiveFileContext(
        path="src/auth.py", selection={"mode": "full"}, source="heuristic",
        hash=hashlib.sha256(source.read_bytes()).hexdigest(), ranking_score=1.0,
        confidence=0.5, evidence=("lexical",), reason="lexical auth match",
    )
    heuristic_event = AdmissionEvent(
        "evt-heuristic-auth", "src/auth.py", "admit", "heuristic",
        "lexical auth match", "initial_route", evidence=("lexical",),
    )
    save_active_context(
        task_dir,
        replace(original, files=(heuristic,), events=(heuristic_event,)),
    )
    graph.write_text('{"nodes": [], "edges": [], "revision": 2}', encoding="utf-8")

    class AuthGraphProvider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            return GraphifyQueryResult("success", (), (), "auth", paths=("src/auth.py",))

    monkeypatch.setattr(
        "sacas.graphify.get_graphify_provider",
        lambda *_args, **_kwargs: AuthGraphProvider(graph, tmp_path),
    )
    installation = discover_manifest(tmp_path)
    assert installation is not None
    assert refresh_context(installation) is True

    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    matching_files = [file for file in refreshed.files if file.path == "src/auth.py"]
    assert len(matching_files) == 1
    assert matching_files[0].source == "graphify"
    matching_events = [event for event in refreshed.events if event.target == "src/auth.py"]
    assert len(matching_events) == 1
    assert matching_events[0].source == "graphify"
    assert matching_events[0].id == "evt-refresh-000"


def test_merge_events_preserves_history_deduplicates_semantics_and_allocates_refresh_ids() -> None:
    """Refresh events never reuse init or digest IDs, even when those IDs collide."""
    from sacas.active_context import AdmissionEvent
    from sacas.refresh import _merge_events

    preserved = AdmissionEvent(
        "evt-init-000", "src/explicit.py", "admit", "explicit", "chosen", "initial_route",
    )
    existing_refresh = AdmissionEvent(
        "evt-refresh-000", "src/old.py", "admit", "heuristic", "old", "initial_route",
    )
    duplicate_of_preserved = AdmissionEvent(
        "evt-init-999", "src/explicit.py", "admit", "explicit", "chosen", "initial_route",
    )
    first_new = AdmissionEvent(
        "evt-init-001", "src/one.py", "admit", "graphify", "new one", "refresh",
    )
    second_new = AdmissionEvent(
        "evt-deadbeef", "src/two.py", "admit", "graphify", "new two", "refresh",
    )

    merged = _merge_events(
        (preserved, existing_refresh),
        (duplicate_of_preserved, first_new, second_new),
        retain_sources={"explicit", "heuristic"},
    )

    assert [event.id for event in merged] == [
        "evt-init-000", "evt-refresh-000", "evt-refresh-001", "evt-refresh-002",
    ]
    assert [event.target for event in merged] == [
        "src/explicit.py", "src/old.py", "src/one.py", "src/two.py",
    ]


def test_graph_no_match_uses_lexical_fallback_when_seeded_explicit_files_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graph fallback is based on new Graphify admissions, not retained file count."""
    from sacas.active_context import ActiveFileContext
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider
    from sacas.init import initialize
    from sacas.tasks import route_goal

    initialized = initialize(tmp_path, graphify_mode="existing")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def auth(): pass\n", encoding="utf-8")
    (tmp_path / "src" / "retained.py").write_text("def retained(): pass\n", encoding="utf-8")
    graph = tmp_path / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    class NoMatchProvider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            return GraphifyQueryResult("success", (), (), "none", paths=())

    monkeypatch.setattr("sacas.graphify.get_graphify_provider", lambda *_args, **_kwargs: NoMatchProvider(graph, tmp_path))
    manifest = route_goal(
        initialized.installation, "Investigate auth",
        seed_files=(ActiveFileContext(path="src/retained.py", selection={"mode": "full"}, source="explicit", hash=""),),
    )
    assert any(file.path == "src/auth.py" and file.source == "heuristic" for file in manifest.files)


def test_graph_no_match_uses_lexical_fallback_when_explicit_tests_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit test must not suppress lexical fallback after an empty graph query."""
    from sacas.active_context import load_active_context
    from sacas.graphify import GraphifyQueryResult, JsonGraphifyProvider
    from sacas.init import initialize
    from sacas.paths import discover_manifest
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="existing")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def auth(): pass\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_auth(): pass\n", encoding="utf-8")
    graph = tmp_path / "graphify-out" / "graph.json"
    graph.parent.mkdir()
    graph.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    class NoMatchProvider(JsonGraphifyProvider):
        def verify_capabilities(self, required: set[str]) -> bool:
            return True

        def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None):
            return GraphifyQueryResult("success", (), (), "none", paths=())

    monkeypatch.setattr(
        "sacas.graphify.get_graphify_provider",
        lambda *_args, **_kwargs: NoMatchProvider(graph, tmp_path),
    )
    installation = discover_manifest(tmp_path)
    assert installation is not None
    generate_task(installation, "Investigate auth", tests=("tests/test_auth.py",))
    manifest = load_active_context(initialized.sacas_root / "tasks" / "current")
    assert manifest is not None
    assert any(file.path == "src/auth.py" and file.source == "heuristic" for file in manifest.files)


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
