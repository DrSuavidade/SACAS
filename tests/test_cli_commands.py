from __future__ import annotations

import json
from pathlib import Path
import pytest
from sacas.cli import main
from sacas.init import initialize
from sacas.active_context import load_active_context


def test_pipeline_commands_are_removed() -> None:
    import argparse

    from sacas.cli import build_parser

    parser = build_parser()
    action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert "pipeline" not in action.choices


def test_prepare_requires_a_goal(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(SystemExit):
        main(["prepare", "--root", str(tmp_path)])


def test_public_cli_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Full agent loop using only the public command names."""
    init_result = initialize(tmp_path)
    source = tmp_path / "src" / "auth.py"
    helper = tmp_path / "src" / "helper.py"
    source.parent.mkdir(parents=True)
    source.write_text("def login():\n    pass\n", encoding="utf-8")

    # 1. prepare creates a task and its context pack
    assert main(["prepare", "Fix authentication session", "--root", str(tmp_path), "--files", "src/auth.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    assert (init_result.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl").is_file()

    # 2. prepare with the same goal refreshes the existing task
    assert main(["prepare", "Fix authentication session", "--root", str(tmp_path)]) == 0
    refreshed = load_active_context(task_dir)
    assert refreshed is not None
    assert refreshed.task_id == manifest.task_id

    # 3. add admits an explicit file with an audit reason
    helper.write_text("value = 1\n", encoding="utf-8")
    assert main(["add", "--file", "src/helper.py", "--reason", "manual check", "--root", str(tmp_path)]) == 0
    updated = load_active_context(task_dir)
    assert updated is not None
    assert "src/helper.py" in [f.path for f in updated.files]

    # 4. explain shows provenance for that file
    assert main(["explain", "src/helper.py", "--root", str(tmp_path)]) == 0
    assert "src/helper.py" in capsys.readouterr().out

    # 5. explain without a path prints the status report
    assert main(["explain", "--root", str(tmp_path)]) == 0
    status_out = capsys.readouterr().out
    assert updated.task_id in status_out

    # 6. doctor runs diagnostics plus validation on a clean install
    assert main(["doctor", "--root", str(tmp_path)]) == 0

def test_expand_why_doctor_cli_commands(tmp_path: Path) -> None:
    # 1. Initialize
    init_result = initialize(tmp_path)
    
    # 2. Generate task
    exit_code = main([
        "task",
        "Fix authentication session bug",
        "--root", str(tmp_path),
        "--files", "src/auth.py",
        "--symbol", "src/auth.py::login",
        "--rules", "rules/boundaries.md"
    ])
    assert exit_code == 0
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    
    # 3. Test why command on admitted file
    exit_code = main(["why", "src/auth.py", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # 4. Test expand command explicitly adding a file and rule
    candidates_data = {
        "task_id": manifest.task_id,
        "candidates": [{
            "path": "src/session.py", "score": 90.0, "reason": "Graph relation Calls",
            "source": "graphify", "confidence": "high", "estimated_tokens": 100,
        }],
    }
    (task_dir / "candidates.json").write_text(json.dumps(candidates_data), encoding="utf-8")
    (tmp_path / "src" / "session.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "session.py").write_text("print('session')", encoding="utf-8")
    (tmp_path / "src" / "auth.py").write_text("def login():\n    pass\n", encoding="utf-8")
    (tmp_path / "src" / "helper.py").write_text("print('helper')", encoding="utf-8")
    (tmp_path / "Structure" / "rules" / "new_rule.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Structure" / "rules" / "new_rule.md").write_text("# New Rule\n\nContent\n", encoding="utf-8")
    assert main([
        "expand", "--file", "src/helper.py", "--rule", "rules/new_rule.md",
        "--all-candidates", "--reason", "CLI expansion check", "--root", str(tmp_path),
    ]) == 0
    updated = load_active_context(task_dir)
    assert updated is not None
    assert "src/helper.py" in [f.path for f in updated.files]
    assert "src/session.py" in [f.path for f in updated.files]
    assert "Structure/rules/new_rule.md" in [r.path for r in updated.rules]
    assert main(["why", "src/helper.py", "--root", str(tmp_path)]) == 0
    assert main(["doctor", "--root", str(tmp_path)]) == 0


def test_expand_is_all_or_nothing_when_any_requested_file_is_rejected(tmp_path: Path) -> None:
    """A rejected admission must not publish a partially expanded manifest."""
    init_result = initialize(tmp_path)
    source = tmp_path / "src" / "seed.py"
    valid = tmp_path / "src" / "valid.py"
    binary = tmp_path / "src" / "binary.bin"
    source.parent.mkdir(parents=True)
    source.write_text("seed = 1\n", encoding="utf-8")
    valid.write_text("valid = 1\n", encoding="utf-8")
    binary.write_bytes(b"\x00not text")
    assert main(["task", "Expand safely", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0

    task_dir = init_result.sacas_root / "tasks" / "current"
    before = {
        name: (task_dir / name).read_bytes()
        for name in ("active_context.json", "task.json")
    }

    assert main([
        "expand", "--root", str(tmp_path),
        "--file", "src/valid.py", "--file", "src/binary.bin",
    ]) == 1

    assert {
        name: (task_dir / name).read_bytes()
        for name in ("active_context.json", "task.json")
    } == before


def test_expand_generated_graphify_candidate_preserves_resolved_selector(tmp_path: Path) -> None:
    """A generated Graphify candidate must lower node evidence to a source range."""
    init_result = initialize(tmp_path)
    seed = tmp_path / "src" / "seed.py"
    candidate = tmp_path / "src" / "candidate.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("def seed():\n    return 1\n", encoding="utf-8")
    candidate.write_text("def chosen():\n    return 2\n\ndef other():\n    return 3\n", encoding="utf-8")
    assert main(["task", "Expand candidate", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0

    graphify = init_result.sacas_root / ".sacas" / "graphify.json"
    graphify.parent.mkdir(parents=True, exist_ok=True)
    graphify.write_text(json.dumps({
        "output": "graphify-out", "status": "fresh", "provenance": "graphify_existing",
        "freshness": "fresh", "content_hash": "graph-hash",
        "nodes": [
            ["seed-node", "src/seed.py", "seed", 1],
            ["candidate-node", "src/candidate.py", "chosen", 1],
        ],
        "edges": [["seed-node", "candidate-node", "calls"]],
    }), encoding="utf-8")

    assert main(["refresh", "--root", str(tmp_path)]) == 0
    refreshed = load_active_context(init_result.sacas_root / "tasks" / "current")
    assert refreshed is not None
    generated = json.loads((init_result.sacas_root / "tasks" / "current" / "candidates.json").read_text(encoding="utf-8"))
    graph_candidate = next(item for item in generated["candidates"] if item["path"] == "src/candidate.py")
    assert graph_candidate["graph_snapshot_hash"] == refreshed.graph_snapshot_hash
    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 0

    manifest = load_active_context(init_result.sacas_root / "tasks" / "current")
    assert manifest is not None
    admitted = next(item for item in manifest.files if item.path == "src/candidate.py")
    assert admitted.selection["mode"] == "symbols"
    assert admitted.selection["symbols"][0].name == "chosen"
    assert admitted.selection["symbols"][0].range is not None
    assert admitted.selection["symbols"][0].range.start_line == 1
    event = next(item for item in manifest.events if item.target == "src/candidate.py")
    assert event.graph_snapshot_hash == refreshed.graph_snapshot_hash


def test_expand_lowers_line_only_graphify_evidence_with_node_resolver(tmp_path: Path) -> None:
    init_result = initialize(tmp_path)
    seed = tmp_path / "src" / "seed.py"
    candidate = tmp_path / "src" / "candidate.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("seed = 1\n", encoding="utf-8")
    candidate.write_text("def selected():\n    return 1\n", encoding="utf-8")
    assert main(["task", "Node range", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    (task_dir / "candidates.json").write_text(json.dumps({
        "task_id": manifest.task_id,
        "candidates": [{
            "path": "src/candidate.py", "source": "graphify",
            "node_label": "descriptive graph node", "node_line": 1,
        }],
    }), encoding="utf-8")

    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 0
    updated = load_active_context(task_dir)
    assert updated is not None
    admitted = next(item for item in updated.files if item.path == "src/candidate.py")
    assert admitted.selection["mode"] == "symbols"
    assert admitted.selection["symbols"][0].name == "selected"


def test_expand_rejects_candidate_graph_hash_when_active_hash_is_empty(tmp_path: Path) -> None:
    init_result = initialize(tmp_path)
    source = tmp_path / "src" / "seed.py"
    candidate = tmp_path / "src" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text("seed = 1\n", encoding="utf-8")
    candidate.write_text("candidate = 1\n", encoding="utf-8")
    assert main(["task", "Graph binding", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None and manifest.graph_snapshot_hash == ""
    before = {name: (task_dir / name).read_bytes() for name in ("active_context.json", "task.json")}
    (task_dir / "candidates.json").write_text(json.dumps({
        "task_id": manifest.task_id,
        "graph_snapshot_hash": "untrusted-graph",
        "candidates": [{"path": "src/candidate.py", "source": "graphify"}],
    }), encoding="utf-8")

    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 1
    assert {name: (task_dir / name).read_bytes() for name in before} == before


def test_expand_requires_and_records_candidate_graph_hash_for_active_graph(tmp_path: Path) -> None:
    from dataclasses import replace
    from sacas.active_context import save_active_context

    init_result = initialize(tmp_path)
    source = tmp_path / "src" / "seed.py"
    candidate = tmp_path / "src" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text("seed = 1\n", encoding="utf-8")
    candidate.write_text("candidate = 1\n", encoding="utf-8")
    assert main(["task", "Graph event", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    manifest = replace(manifest, graph_snapshot_hash="canonical-graph")
    save_active_context(task_dir, manifest)
    before = {name: (task_dir / name).read_bytes() for name in ("active_context.json", "task.json")}
    (task_dir / "candidates.json").write_text(json.dumps({
        "task_id": manifest.task_id, "graph_snapshot_hash": "canonical-graph",
        "candidates": [{"path": "src/candidate.py", "source": "graphify"}],
    }), encoding="utf-8")

    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 1
    assert {name: (task_dir / name).read_bytes() for name in before} == before

    (task_dir / "candidates.json").write_text(json.dumps({
        "task_id": manifest.task_id, "graph_snapshot_hash": "canonical-graph",
        "candidates": [{
            "path": "src/candidate.py", "source": "graphify",
            "graph_snapshot_hash": "canonical-graph",
        }],
    }), encoding="utf-8")
    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 0
    updated = load_active_context(task_dir)
    assert updated is not None
    event = next(item for item in updated.events if item.target == "src/candidate.py")
    assert event.graph_snapshot_hash == "canonical-graph"


@pytest.mark.parametrize(
    ("arguments", "prepare"),
    [
        (("--file", "../outside.py"), lambda root, task: None),
        (("--file", ".env"), lambda root, task: (root / ".env").write_text("token=x\n", encoding="utf-8")),
        (("--file", "ignored.py"), lambda root, task: ((root / ".sacasignore").write_text("ignored.py\n", encoding="utf-8"), (root / "ignored.py").write_text("x = 1\n", encoding="utf-8"))),
        (("--symbol", "src/seed.py::missing"), lambda root, task: None),
        (("--reference", "rules/boundaries.md#missing-heading"), lambda root, task: None),
    ],
    ids=("escaped", "secret", "ignored", "unresolved-symbol", "missing-reference-heading"),
)
def test_expand_rejects_unsafe_or_unresolved_input_without_mutation(
    tmp_path: Path, arguments: tuple[str, str], prepare: object,
) -> None:
    init_result = initialize(tmp_path)
    seed = tmp_path / "src" / "seed.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("def seed():\n    return 1\n", encoding="utf-8")
    assert main(["task", "Boundary inputs", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    before = {name: (task_dir / name).read_bytes() for name in ("active_context.json", "task.json")}
    prepare(tmp_path, task_dir)  # type: ignore[operator]

    assert main(["expand", "--root", str(tmp_path), *arguments]) == 1
    assert {name: (task_dir / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("candidate_payload", [
    {"task_id": "wrong", "candidates": []},
    {"task_id": "PLACEHOLDER", "candidates": {"not": "a list"}},
])
def test_expand_rejects_untrusted_candidates_without_mutation(tmp_path: Path, candidate_payload: dict[str, object]) -> None:
    init_result = initialize(tmp_path)
    seed = tmp_path / "src" / "seed.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("seed = 1\n", encoding="utf-8")
    assert main(["task", "Candidate boundary", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    if candidate_payload["task_id"] == "PLACEHOLDER":
        candidate_payload = {**candidate_payload, "task_id": manifest.task_id}
    before = {name: (task_dir / name).read_bytes() for name in ("active_context.json", "task.json")}
    (task_dir / "candidates.json").write_text(json.dumps(candidate_payload), encoding="utf-8")

    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 1
    assert {name: (task_dir / name).read_bytes() for name in before} == before


def test_expand_rejects_malformed_candidate_fields_without_mutation(tmp_path: Path) -> None:
    init_result = initialize(tmp_path)
    source = tmp_path / "src" / "seed.py"
    candidate = tmp_path / "src" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text("seed = 1\n", encoding="utf-8")
    candidate.write_text("candidate = 1\n", encoding="utf-8")
    assert main(["task", "Candidate shape", "--root", str(tmp_path), "--files", "src/seed.py"]) == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    before = {name: (task_dir / name).read_bytes() for name in ("active_context.json", "task.json")}
    (task_dir / "candidates.json").write_text(json.dumps({
        "task_id": manifest.task_id,
        "candidates": [{"path": "src/candidate.py", "source": ["not", "a", "string"]}],
    }), encoding="utf-8")

    assert main(["expand", "--root", str(tmp_path), "--all-candidates"]) == 1
    assert {name: (task_dir / name).read_bytes() for name in before} == before
