from __future__ import annotations

import json
from pathlib import Path
from sacas.active_context import ActiveContextManifest, ActiveFileContext
from sacas.refresh import refresh_context
from sacas.init import initialize
from sacas.paths import discover_manifest
from sacas.active_context import save_active_context
from sacas.models import Manifest
from sacas.io import write_json_atomic
from sacas.graphify import GraphifyEvidence, write_graphify_manifest

def test_directional_routing(tmp_path: Path) -> None:
    # 1. Initialize
    init_result = initialize(tmp_path)
    installation = discover_manifest(tmp_path)
    
    # 2. Write graphify-out/graph.json
    graphify_out = tmp_path / "graphify-out"
    graphify_out.mkdir()
    (graphify_out / "graph.json").write_text(json.dumps({
        "nodes": [
            {"id": "src/api.py", "path": "src/api.py"},
            {"id": "src/web.py", "path": "src/web.py"}
        ],
        "edges": [
            {"source": "src/web.py", "target": "src/api.py", "type": "calls"}
        ]
    }), encoding="utf-8")

    # 3. Write Structure/.sacas/graphify.json
    evidence = GraphifyEvidence(
        output="graphify-out",
        status="fresh",
        provenance="graphify_existing",
        freshness="fresh",
        content_hash="abc",
        nodes=(
            ("src/api.py", "src/api.py"),
            ("src/web.py", "src/web.py")
        ),
        edges=(
            ("src/web.py", "src/api.py", "calls"),
        )
    )
    (installation.sacas_root / ".sacas").mkdir(parents=True, exist_ok=True)
    write_graphify_manifest(installation.sacas_root / ".sacas" / "graphify.json", evidence)

    # Create dummy source files
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "api.py").write_text("print('api')", encoding="utf-8")
    (tmp_path / "src" / "web.py").write_text("print('web')", encoding="utf-8")

    # 4. Create active context manifest for "bugfix" category focusing on dest (api.py)
    task_dir = installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    # Update manifest.json with task ID
    write_json_atomic(installation.manifest_path, {
        "repository_root": ".",
        "sacas_root": "Structure",
        "graphify_mode": "existing",
        "graphify_output": "graphify-out",
        "adapters": [],
        "context_budget": 12000,
        "current_task_id": "t_bugfix",
        "schema_version": 1
    })
    
    # Re-discover to load new task ID
    installation = discover_manifest(tmp_path)
    
    manifest_bugfix = ActiveContextManifest(
        task_id="t_bugfix",
        goal="Fix api bug",
        category="bugfix",
        git_revision="unknown",
        files=(
            ActiveFileContext(
                path="src/api.py", selection={"mode": "full"}, source="explicit",
                confidence="high", relation=None, trigger="initial_route",
                git_revision="unknown", reason="focus", hash=""
            ),
        ),
        rules=(),
        references=(),
        events=()
    )
    save_active_context(task_dir, manifest_bugfix)

    # Refresh
    refresh_context(installation)
    
    candidates = json.loads((task_dir / "candidates.json").read_text(encoding="utf-8"))
    cand_map = {c["path"]: c for c in candidates["candidates"]}
    assert "src/web.py" in cand_map
    assert cand_map["src/web.py"]["score"] == 100
    assert cand_map["src/web.py"]["semantic_direction"] == "caller"

    # 5. Create active context manifest for "feature" category focusing on dest (api.py)
    write_json_atomic(installation.manifest_path, {
        "repository_root": ".",
        "sacas_root": "Structure",
        "graphify_mode": "existing",
        "graphify_output": "graphify-out",
        "adapters": [],
        "context_budget": 12000,
        "current_task_id": "t_feature",
        "schema_version": 1
    })
    installation = discover_manifest(tmp_path)
    
    manifest_feature = ActiveContextManifest(
        task_id="t_feature",
        goal="Add api feature",
        category="feature",
        git_revision="unknown",
        files=(
            ActiveFileContext(
                path="src/api.py", selection={"mode": "full"}, source="explicit",
                confidence="high", relation=None, trigger="initial_route",
                git_revision="unknown", reason="focus", hash=""
            ),
        ),
        rules=(),
        references=(),
        events=()
    )
    save_active_context(task_dir, manifest_feature)

    # Refresh
    refresh_context(installation)
    
    candidates = json.loads((task_dir / "candidates.json").read_text(encoding="utf-8"))
    cand_map = {c["path"]: c for c in candidates["candidates"]}
    assert "src/web.py" in cand_map
    assert cand_map["src/web.py"]["score"] == 70
