from __future__ import annotations

import json
from pathlib import Path
from sacas.active_context import ActiveContextManifest, ActiveFileContext
from sacas.enforce import CursorEnforcementProvider, AdvisoryEnforcementProvider
from sacas.paths import Installation
from sacas.models import Manifest

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
    
    # Check .cursorignore contents
    cursor_ignore = repo_root / ".cursorignore"
    assert cursor_ignore.is_file()
    text = cursor_ignore.read_text(encoding="utf-8")
    assert "<!-- SACAS:START cursor-ignore -->" in text
    assert "!src/login.py" in text
