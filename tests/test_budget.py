from __future__ import annotations

import json
from pathlib import Path
from sacas.active_context import (
    ActiveContextManifest,
    ActiveFileContext,
    ActiveSymbolContext,
    SourceRange,
    ActiveRuleContext,
    ActiveReferenceContext,
)
from sacas.budget import calculate_manifest_tokens
from sacas.paths import Installation
from sacas.models import Manifest

def test_calculate_manifest_tokens(tmp_path: Path) -> None:
    # 1. Setup repository structure
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    src_dir = repo_root / "src"
    src_dir.mkdir()
    
    file1 = src_dir / "auth.py"
    file1.write_text(
        "def login():\n"
        "    print('logging in')\n"
        "\n"
        "def logout():\n"
        "    print('logging out')\n",
        encoding="utf-8"
    ) # 5 lines, total ~70 characters
    
    # 2. Setup SACAS Structure
    sacas_root = repo_root / "Structure"
    sacas_root.mkdir()
    
    router_md = sacas_root / "ROUTER.md"
    router_md.write_text("# Router\nInstructions here.\n", encoding="utf-8")
    
    task_dir = sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True)
    (task_dir / "TASK.md").write_text("# Task\nGoal here.\n", encoding="utf-8")
    (task_dir / "CONTEXT.md").write_text("# Context\nFiles here.\n", encoding="utf-8")
    (task_dir / "STATE.md").write_text("# State\nChecklist here.\n", encoding="utf-8")
    
    rules_dir = sacas_root / "rules"
    rules_dir.mkdir()
    rule1 = rules_dir / "boundaries.md"
    rule1.write_text("MANUAL paths here", encoding="utf-8")
    
    references_dir = sacas_root / "references"
    references_dir.mkdir()
    ref1 = references_dir / "auth.md"
    ref1.write_text(
        "# Authentication\n"
        "## Password reset\n"
        "Password reset flow instructions\n"
        "## Session management\n"
        "Session details\n",
        encoding="utf-8"
    )
    
    # Define an Installation mock
    manifest_inst = Manifest(repository_root=".", sacas_root="Structure", context_budget=12000)
    installation = Installation(
        repository_root=repo_root,
        sacas_root=sacas_root,
        manifest_path=repo_root / ".sacas" / "manifest.json",
        manifest=manifest_inst
    )
    
    # Test case 1: Active symbol routing
    active_manifest = ActiveContextManifest(
        task_id="t1",
        goal="Fix login redirect",
        category="bugfix",
        git_revision="unknown",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={
                    "mode": "symbols",
                    "symbols": [
                        ActiveSymbolContext(
                            name="login",
                            range=SourceRange(start_line=1, end_line=2, source="explicit", confidence=1.0)
                        )
                    ]
                },
                source="explicit",
                confidence="high",
                relation=None,
                trigger="initial_route",
                git_revision="unknown",
                reason="Needed",
                hash=""
            ),
        ),
        rules=(
            ActiveRuleContext(path="Structure/rules/boundaries.md", hash="", reason="Rule check"),
        ),
        references=(
            ActiveReferenceContext(
                path="Structure/references/auth.md",
                selection={
                    "mode": "sections",
                    "sections": [{"heading_path": ["Password reset"]}]
                },
                hash="",
                reason="Reference doc"
            ),
        ),
        events=()
    )
    
    breakdown = calculate_manifest_tokens(installation, active_manifest)
    
    # Verification of payload vs control divide
    # src/auth.py: selected lines 1-2: "def login():\n    print('logging in')" -> 35 chars -> 8 tokens
    # rules/boundaries.md: "MANUAL paths here" -> 17 chars -> 4 tokens
    # references/auth.md section "Password reset" -> "## Password reset\nPassword reset flow instructions" -> ~50 chars -> 12 tokens
    # total payload ~ 24 tokens
    assert breakdown.source_tokens > 0
    assert breakdown.rule_tokens > 0
    assert breakdown.reference_tokens > 0
    assert breakdown.control_tokens > 0
    assert breakdown.used == (breakdown.source_tokens + breakdown.rule_tokens + breakdown.reference_tokens + breakdown.control_tokens)
