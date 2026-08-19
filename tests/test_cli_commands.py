from __future__ import annotations

import json
from pathlib import Path
from sacas.cli import main
from sacas.init import initialize
from sacas.active_context import load_active_context

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
    # Create candidate.json to simulate candidates
    candidates_data = {
        "task_id": manifest.task_id,
        "candidates": [
            {
                "path": "src/session.py",
                "score": 90.0,
                "reason": "Graph relation Calls",
                "source": "graphify",
                "confidence": "high",
                "estimated_tokens": 100
            }
        ]
    }
    (task_dir / "candidates.json").write_text(json.dumps(candidates_data), encoding="utf-8")
    
    # Create session.py, auth.py, and helper.py
    (tmp_path / "src" / "session.py").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "session.py").write_text("print('session')", encoding="utf-8")
    (tmp_path / "src" / "auth.py").write_text("def login():\n    pass\n", encoding="utf-8")
    (tmp_path / "src" / "helper.py").write_text("print('helper')", encoding="utf-8")
    # Create the rule file that will be added
    (tmp_path / "Structure" / "rules" / "new_rule.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Structure" / "rules" / "new_rule.md").write_text("# New Rule\n\nContent\n", encoding="utf-8")
    
    exit_code = main([
        "expand",
        "--file", "src/helper.py",
        "--rule", "rules/new_rule.md",
        "--all-candidates",
        "--reason", "CLI expansion check",
        "--root", str(tmp_path)
    ])
    assert exit_code == 0
    
    # Reload manifest
    updated = load_active_context(task_dir)
    assert updated is not None
    files_paths = [f.path for f in updated.files]
    assert "src/helper.py" in files_paths
    assert "src/session.py" in files_paths  # candidate was expanded because all-candidates was requested
    
    rules_paths = [r.path for r in updated.rules]
    assert "Structure/rules/new_rule.md" in rules_paths
    
    # Check why command on candidates
    exit_code = main(["why", "src/helper.py", "--root", str(tmp_path)])
    assert exit_code == 0
    
    # 5. Test doctor command
    exit_code = main(["doctor", "--root", str(tmp_path)])
    assert exit_code == 0
