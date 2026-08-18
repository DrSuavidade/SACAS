"""Behavioral tests for SACAS task routing, contracts, and state preservation."""

from __future__ import annotations

import os
from pathlib import Path
import pytest


def test_task_generation_creates_files_with_stable_id(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.tasks import generate_task

    init_result = initialize(tmp_path)
    goal = "Implement login authentication"
    
    # Run task generation
    result = generate_task(
        init_result.installation,
        goal=goal,
        criteria=("User can log in", "Invalid credentials rejected"),
        constraints=("Use JWT",),
        verification=("Run pytest tests/test_auth.py",),
        files=("src/auth.py",),
        symbols=("login",),
        tests=("tests/test_auth.py",),
        rules=("rules/boundaries.md",)
    )

    assert result.task_id is not None
    assert len(result.task_id) == 8

    # Verify files created in tasks/current/
    task_dir = init_result.sacas_root / "tasks" / "current"
    assert (task_dir / "TASK.md").is_file()
    assert (task_dir / "CONTEXT.md").is_file()
    assert (task_dir / "STATE.md").is_file()
    assert (task_dir / "PICKUP.md").is_file()

    # Read TASK.md and check contract contents
    task_content = (task_dir / "TASK.md").read_text(encoding="utf-8")
    assert goal in task_content
    assert "User can log in (EXPLICIT)" in task_content
    assert "Use JWT (EXPLICIT)" in task_content
    assert "Run pytest tests/test_auth.py (EXPLICIT)" in task_content

    # Read CONTEXT.md and check context contents
    context_content = (task_dir / "CONTEXT.md").read_text(encoding="utf-8")
    assert "src/auth.py" in context_content
    assert "login" in context_content
    assert "tests/test_auth.py" in context_content


def test_task_rerun_preserves_checked_checkboxes_and_human_content(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.tasks import generate_task

    init_result = initialize(tmp_path)
    goal = "Build authentication"

    # Initial run
    generate_task(
        init_result.installation,
        goal=goal,
        criteria=("Log in", "Log out"),
        verification=("Run test",)
    )

    task_dir = init_result.sacas_root / "tasks" / "current"
    state_file = task_dir / "STATE.md"
    task_file = task_dir / "TASK.md"

    # Human edits STATE.md to check "Log in" and add notes outside region
    old_state = state_file.read_text(encoding="utf-8")
    edited_state = old_state.replace("- [ ] Log in (Acceptance Criteria)", "- [x] Log in (Acceptance Criteria)")
    edited_state += "\nHuman notes here.\n"
    state_file.write_text(edited_state, encoding="utf-8")

    # Human edits TASK.md to add notes outside region
    old_task = task_file.read_text(encoding="utf-8")
    edited_task = old_task + "\nHuman contract notes.\n"
    task_file.write_text(edited_task, encoding="utf-8")

    # Rerun task generation with same criteria
    generate_task(
        init_result.installation,
        goal=goal,
        criteria=("Log in", "Log out"),
        verification=("Run test",)
    )

    # Verify notes and checkmarks preserved
    new_state = state_file.read_text(encoding="utf-8")
    assert "- [x] Log in (Acceptance Criteria)" in new_state
    assert "- [ ] Log out (Acceptance Criteria)" in new_state
    assert "Human notes here." in new_state

    new_task = task_file.read_text(encoding="utf-8")
    assert "Human contract notes." in new_task


def test_task_protected_boundaries(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.tasks import generate_task

    init_result = initialize(tmp_path)
    
    # Write a MANUAL boundary
    boundaries_file = init_result.sacas_root / "rules" / "boundaries.md"
    boundaries_file.write_text(
        "MANUAL src/sensitive/ | Sensitive logic\n", encoding="utf-8"
    )

    generate_task(
        init_result.installation,
        goal="Do not modify sensitive things",
        files=("src/sensitive/secret.py", "src/safe.py")
    )

    task_dir = init_result.sacas_root / "tasks" / "current"
    context_content = (task_dir / "CONTEXT.md").read_text(encoding="utf-8")
    assert "Sensitive logic" in context_content
    assert "src/sensitive/secret.py" in context_content


def test_task_cli_command(tmp_path: Path) -> None:
    from sacas.cli import main
    from sacas.init import initialize

    init_result = initialize(tmp_path)
    
    # Run CLI command 'task'
    exit_code = main([
        "task",
        "Implement main application loop",
        "--root", str(tmp_path),
        "--criteria", "Task done",
        "--files", "src/app.py",
    ])
    
    assert exit_code == 0
    task_dir = init_result.sacas_root / "tasks" / "current"
    assert (task_dir / "TASK.md").is_file()
    assert "Implement main application loop" in (task_dir / "TASK.md").read_text(encoding="utf-8")


def test_goal_driven_routing_and_fallbacks(tmp_path: Path) -> None:
    from sacas.init import initialize
    from sacas.tasks import generate_task
    import json

    init_result = initialize(tmp_path)
    
    # Create target files
    auth_py = tmp_path / "src" / "auth.py"
    auth_py.parent.mkdir(parents=True, exist_ok=True)
    auth_py.write_text("class SessionManager:\n    pass\n", encoding="utf-8")
    
    # Run task generation with no --files specified, target goal containing "auth" and "Session"
    generate_task(
        init_result.installation,
        goal="fix auth Session persistence"
    )
    
    task_dir = init_result.sacas_root / "tasks" / "current"
    expansions_path = task_dir / "expansions.json"
    assert expansions_path.is_file()
    
    data = json.loads(expansions_path.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 2
    
    # Check that src/auth.py was matched by heuristic fallback
    initial_scope = data.get("initial_scope", [])
    paths = [item["path"] for item in initial_scope]
    assert "src/auth.py" in paths
    
    auth_item = next(item for item in initial_scope if item["path"] == "src/auth.py")
    assert auth_item["source"] == "heuristic"
    assert "auth" in auth_item["reason"] or "Session" in auth_item["reason"]


