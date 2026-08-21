"""End-to-end routing quality and loop verification test."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from sacas.cli import main
from sacas.paths import discover_manifest
from sacas.active_context import load_active_context


def test_e2e_routing_loop(tmp_path: Path) -> None:
    # 1. Initialize tiny fixture repo with actual relations
    repo = tmp_path / "tiny-repo"
    repo.mkdir()
    
    # Create files
    src_dir = repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    
    auth_py = src_dir / "auth.py"
    auth_py.write_text("class SessionManager:\n    def restore_session(self):\n        pass\n", encoding="utf-8")
    
    session_py = src_dir / "session.py"
    session_py.write_text("from src.auth import SessionManager\n", encoding="utf-8")
    
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_auth_py = tests_dir / "test_auth.py"
    test_auth_py.write_text("def test_session():\n    pass\n", encoding="utf-8")

    # Initialize SACAS with Graphify code-only mode
    exit_code = main(["init", "--root", str(repo), "--graphify", "code-only"])
    assert exit_code == 0
    
    # Run map to extract Graphify graph
    exit_code = main(["map", "--root", str(repo), "--mode", "code-only"])
    assert exit_code == 0
    
    # Run task generation with no focus files, but goal containing "Session"
    exit_code = main(["task", "fix Session restoration", "--root", str(repo)])
    assert exit_code == 0
    
    # Verify TASK.md and active_context.json exist
    installation = discover_manifest(repo)
    assert installation is not None
    
    task_dir = installation.sacas_root / "tasks" / "current"
    active_path = task_dir / "active_context.json"
    assert active_path.is_file()
    
    manifest = load_active_context(task_dir)
    assert manifest is not None
    assert manifest.schema_version == 1
    
    # Verify files has auth.py
    paths = [item.path for item in manifest.files]
    assert "src/auth.py" in paths
    
    # Check provenance
    auth_item = next(item for item in manifest.files if item.path == "src/auth.py")
    assert auth_item.source == "graphify"
    assert auth_item.relation == "seed"
    assert auth_item.trigger == "task_goal"
    assert auth_item.confidence_label() == "high"
    
    # Run validate
    exit_code = main(["validate", "--root", str(repo)])
    assert exit_code == 0
    
    # Modify a file to make it stale and trigger refresh
    auth_py.write_text("class SessionManager:\n    def restore_session(self):\n        print('modified')\n", encoding="utf-8")
    
    # Run refresh
    exit_code = main(["refresh", "--root", str(repo)])
    assert exit_code == 0
    
    # Run status command
    exit_code = main(["status", "--root", str(repo), "--format", "json"])
    assert exit_code == 0

    # 8. Test candidates generation during E2E refresh
    # Set a budget of 2000 tokens
    manifest_path = installation.sacas_root / ".sacas" / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["context_budget"] = 2000
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Add caller relation to graphify cache
    graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
    g_data = json.loads(graphify_manifest_path.read_text(encoding="utf-8"))
    
    # We add a new node src/logger.py and a calls edge from node_auth to node_logger
    g_data["nodes"] = [
        ["node_auth", "src/auth.py"],
        ["node_session", "src/session.py"],
        ["node_logger", "src/logger.py"]
    ]
    g_data["edges"] = [
        ["node_auth", "node_logger", "calls"]
    ]
    graphify_manifest_path.write_text(json.dumps(g_data), encoding="utf-8")

    # Create logger.py as a file
    logger_py = repo / "src" / "logger.py"
    logger_py.write_text("print('logger')\n" * 150, encoding="utf-8")

    # Run refresh
    exit_code = main(["refresh", "--root", str(repo)])
    assert exit_code == 0

    # Check candidates.json
    candidates_path = task_dir / "candidates.json"
    assert candidates_path.is_file()
    candidates_data = json.loads(candidates_path.read_text(encoding="utf-8"))
    cand_paths = [item["path"] for item in candidates_data["candidates"]]
    assert "src/logger.py" in cand_paths


def test_e2e_routing_fallback_on_incompatible_graphify(tmp_path: Path) -> None:
    # Test fallback to heuristics when graphify is missing or incompatible
    repo = tmp_path / "tiny-repo-fallback"
    repo.mkdir()
    
    src_dir = repo / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    
    auth_py = src_dir / "auth.py"
    auth_py.write_text("class AuthProvider:\n    pass\n", encoding="utf-8")
    
    # Initialize with graphify off
    exit_code = main(["init", "--root", str(repo), "--graphify", "off"])
    assert exit_code == 0
    
    # Generate task without --files
    exit_code = main(["task", "fix Auth authentication logic", "--root", str(repo)])
    assert exit_code == 0
    
    installation = discover_manifest(repo)
    assert installation is not None
    task_dir = installation.sacas_root / "tasks" / "current"
    
    manifest = load_active_context(task_dir)
    assert manifest is not None
    
    paths = [item.path for item in manifest.files]
    
    # Heuristics should discover auth.py
    assert "src/auth.py" in paths
    auth_item = next(item for item in manifest.files if item.path == "src/auth.py")
    assert auth_item.source == "heuristic"
    assert auth_item.relation == "keyword_match"


def test_e2e_custom_sacas_root_lifecycle(tmp_path: Path) -> None:
    """Full lifecycle with a non-default SACAS root must never assume Structure/."""
    repo = tmp_path / "custom-root-repo"
    repo.mkdir()

    src_dir = repo / "src"
    src_dir.mkdir()
    (repo / "src" / "auth.py").write_text(
        "class AuthProvider:\n    def authenticate(self):\n        pass\n",
        encoding="utf-8",
    )

    exit_code = main(["init", "--root", str(repo), "--sacas-root", ".context", "--graphify", "off"])
    assert exit_code == 0

    installation = discover_manifest(repo)
    assert installation is not None
    assert installation.sacas_root == (repo / ".context").resolve()
    assert (repo / ".context" / "rules" / "boundaries.md").is_file()

    rules_dir = repo / ".context" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "auth_rules.md").write_text("# Auth rules\n\nAlways hash passwords.\n", encoding="utf-8")

    refs_dir = repo / ".context" / "references"
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / "auth_flow.md").write_text("# Auth flow\n\nAuthentication starts in the provider.\n", encoding="utf-8")

    # Task generation: heuristic fallback routing + heuristic rule/reference routing
    exit_code = main(["task", "fix auth session handling", "--root", str(repo)])
    assert exit_code == 0

    task_dir = installation.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None

    file_paths = [item.path for item in manifest.files]
    assert "src/auth.py" in file_paths

    # Rules and references must be expressed under .context/, not Structure/
    rule_paths = [item.path for item in manifest.rules]
    assert ".context/rules/boundaries.md" in rule_paths
    assert ".context/rules/auth_rules.md" in rule_paths

    ref_paths = [item.path for item in manifest.references]
    assert ref_paths, "expected at least one reference under .context/"
    for path in ref_paths:
        assert path.startswith(".context/"), path
    assert any("auth_flow.md" in path for path in ref_paths)

    # Expand with an explicit unprefixed rule path
    (repo / "src" / "session.py").write_text("from src.auth import AuthProvider\n", encoding="utf-8")
    exit_code = main([
        "expand", "--root", str(repo),
        "--file", "src/session.py",
        "--rule", "rules/auth_rules.md",
        "--reason", "test expansion",
    ])
    assert exit_code == 0

    manifest = load_active_context(task_dir)
    assert manifest is not None
    assert "src/session.py" in [item.path for item in manifest.files]
    assert any(item.path == ".context/rules/auth_rules.md" for item in manifest.rules)

    # Refresh must keep canonical state readable under the custom root
    exit_code = main(["refresh", "--root", str(repo)])
    assert exit_code == 0

    manifest = load_active_context(task_dir)
    assert manifest is not None
    refreshed_rule_paths = [item.path for item in manifest.rules]
    assert ".context/rules/auth_rules.md" in refreshed_rule_paths
    assert not any(path.startswith("Structure/") for path in (
        [item.path for item in manifest.files]
        + refreshed_rule_paths
        + [item.path for item in manifest.references]
    ))

    # Validation and provenance queries succeed against the custom root
    exit_code = main(["validate", "--root", str(repo)])
    assert exit_code == 0

    exit_code = main(["why", "src/auth.py", "--root", str(repo)])
    assert exit_code == 0


def test_e2e_lexical_provenance_chain(tmp_path: Path) -> None:
    """Fallback routing must preserve query evidence end-to-end under graphify_mode=off."""
    from sacas.provenance import query_why_file
    from sacas.tasks import lexical_query_hash

    repo = tmp_path / "lexical-prov-repo"
    repo.mkdir()

    src_dir = repo / "src"
    src_dir.mkdir()
    (repo / "src" / "auth.py").write_text(
        "class AuthProvider:\n    def authenticate(self):\n        pass\n",
        encoding="utf-8",
    )

    exit_code = main(["init", "--root", str(repo), "--graphify", "off"])
    assert exit_code == 0

    goal = "fix auth session handling"
    exit_code = main(["task", goal, "--root", str(repo)])
    assert exit_code == 0

    installation = discover_manifest(repo)
    assert installation is not None
    task_dir = installation.sacas_root / "tasks" / "current"

    manifest = load_active_context(task_dir)
    assert manifest is not None

    auth_item = next(item for item in manifest.files if item.path == "src/auth.py")
    assert auth_item.source == "heuristic"
    assert auth_item.relation == "keyword_match"

    # The admission event records the exact query evidence
    auth_events = [e for e in manifest.events if e.target == "src/auth.py" and e.source == "heuristic"]
    assert auth_events, "expected a heuristic admission event for src/auth.py"
    event = auth_events[0]
    assert event.lexical_query_hash == lexical_query_hash(goal)
    assert "auth" in event.lexical_matched_terms
    assert event.lexical_score > 0

    # The why chain exposes Task -> lexical query -> admission -> fragment -> file
    chain = query_why_file(installation, "src/auth.py")
    text = "\n".join(chain)
    assert "Lexical query:" in text
    assert event.lexical_query_hash[:16] in text
    assert "auth" in text
