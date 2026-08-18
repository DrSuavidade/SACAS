from __future__ import annotations

import json
from pathlib import Path
from sacas.search import FallbackIndex

def test_fallback_index_lifecycle(tmp_path: Path) -> None:
    # 1. Setup paths
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    
    src_dir = repo_root / "src"
    src_dir.mkdir()
    
    auth_file = src_dir / "auth.py"
    auth_file.write_text("class SessionManager:\n    def login(self):\n        pass\n", encoding="utf-8")
    
    sacas_root = repo_root / "Structure"
    sacas_root.mkdir()
    
    index = FallbackIndex(repo_root, sacas_root)
    index.update()
    
    # Verify index was saved
    assert index.index_path.is_file()
    
    # Check entries parsed correctly
    assert "src/auth.py" in index.entries
    entry = index.entries["src/auth.py"]
    assert "SessionManager" in entry["symbols"]
    assert "login" in entry["symbols"]
    assert entry["language"] == "python"
    
    # Search check
    results = index.search("fix session login authentication")
    assert len(results) > 0
    score, path, matched = results[0]
    assert path == "src/auth.py"
    assert "session" in matched or "login" in matched
