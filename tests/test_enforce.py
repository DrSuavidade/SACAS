from __future__ import annotations

import json
from pathlib import Path
from sacas.active_context import ActiveContextManifest, ActiveFileContext, build_parent_negations
from sacas.enforce import CursorEnforcementProvider, AdvisoryEnforcementProvider, negotiate_policy, get_enforcement_provider
from sacas.paths import Installation
from sacas.models import Manifest
from sacas.cli import main

def test_build_parent_negations() -> None:
    res = build_parent_negations("src/services/auth/session.py")
    assert res == [
        "!src/",
        "!src/services/",
        "!src/services/auth/",
        "!src/services/auth/session.py"
    ]
    
    res_simple = build_parent_negations("src/main.py")
    assert res_simple == [
        "!src/",
        "!src/main.py"
    ]

def test_policy_negotiation(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    # 1. No adapters -> Requested enforce becomes effective advisory
    manifest_inst = Manifest(
        repository_root=".",
        sacas_root="Structure",
        adapters=(),
        context_budget=12000
    )
    installation = Installation(
        repository_root=repo_root,
        sacas_root=repo_root / "Structure",
        manifest_path=repo_root / ".sacas" / "manifest.json",
        manifest=manifest_inst
    )
    
    policy = negotiate_policy(installation, "enforce")
    assert policy.requested == "enforce"
    assert policy.effective == "advisory"
    assert policy.provider == "advisory"

    # 2. Cursor adapter configured -> Requested enforce becomes effective partial
    manifest_cursor = Manifest(
        repository_root=".",
        sacas_root="Structure",
        adapters=("cursor",),
        context_budget=12000
    )
    installation_cursor = Installation(
        repository_root=repo_root,
        sacas_root=repo_root / "Structure",
        manifest_path=repo_root / ".sacas" / "manifest.json",
        manifest=manifest_cursor
    )
    
    policy_cursor = negotiate_policy(installation_cursor, "enforce")
    assert policy_cursor.requested == "enforce"
    assert policy_cursor.effective == "partial"
    assert policy_cursor.provider == "cursor"

def test_enforce_cursor_patterns(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    sacas_root = repo_root / "Structure"
    sacas_root.mkdir()
    
    manifest_inst = Manifest(
        repository_root=".",
        sacas_root="Structure",
        adapters=("cursor",),
        context_budget=12000
    )
    
    installation = Installation(
        repository_root=repo_root,
        sacas_root=sacas_root,
        manifest_path=repo_root / ".sacas" / "manifest.json",
        manifest=manifest_inst
    )
    
    active_manifest = ActiveContextManifest(
        task_id="t1",
        goal="Enforce boundary check",
        category="bugfix",
        git_revision="unknown",
        files=(
            ActiveFileContext(
                path="src/login.py",
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
    
    provider = CursorEnforcementProvider()
    provider.enforce(installation, active_manifest)
    
    cursor_ignore = repo_root / ".cursorignore"
    assert cursor_ignore.is_file()
    text = cursor_ignore.read_text(encoding="utf-8")
    assert "<!-- SACAS:START cursor-ignore -->" in text
    assert "!src/" in text
    assert "!src/login.py" in text
