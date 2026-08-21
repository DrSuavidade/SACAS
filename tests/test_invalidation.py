"""Tests for invalidation logic (WP4)."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

import pytest

from sacas.refresh import (
    _compute_graph_snapshot_hash,
    _compute_source_hashes,
    _get_stale_files,
    _is_graph_changed,
    _is_task_changed,
    refresh_context,
)
from sacas.active_context import (
    ActiveContextManifest,
    ActiveFileContext,
    ActiveSymbolContext,
    SourceRange,
    AdmissionEvent,
    save_active_context,
)
from sacas.paths import Installation, Manifest, discover_manifest


class FakeInstallation:
    def __init__(self, repo_root: Path, sacas_root: Path):
        self.repository_root = repo_root
        self.sacas_root = sacas_root
        # Create a simple mutable object instead of Manifest (which is frozen)
        class SimpleManifest:
            def __init__(self):
                self.current_task_id = None
                self.sacas_root = "Structure"
                self.context_budget = 12000
                self.adapters = []
                self.graphify_mode = "off"
                self.graphify_output = ".sacas/graphify.json"
        self.manifest = SimpleManifest()


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Mutation-oriented refresh tests must never alter the source fixture."""
    source = Path(__file__).parent / "fixtures" / "context_compiler"
    copied = tmp_path / "context_compiler"
    shutil.copytree(source, copied)
    assert copied != source
    return copied


@pytest.fixture
def fake_installation(fixture_repo: Path) -> FakeInstallation:
    return FakeInstallation(fixture_repo, fixture_repo)


@pytest.fixture
def temp_repo_with_graph() -> Path:
    """Create a temporary repo with a graphify.json for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "auth.py").write_text("def foo():\n    pass\n", encoding="utf-8")
        (repo / "src" / "user.py").write_text("class User:\n    pass\n", encoding="utf-8")
        
        # Create SACAS structure
        sacas_root = repo / "Structure"
        sacas_root.mkdir()
        (sacas_root / ".sacas").mkdir()
        
        # Create a graphify.json
        graphify_data = {
            "nodes": [["n1", "src/auth.py"], ["n2", "src/user.py"]],
            "edges": [["n1", "n2", "calls"]],
            "communities": []
        }
        import json
        (sacas_root / ".sacas" / "graphify.json").write_text(json.dumps(graphify_data))
        
        # Create manifest.json
        manifest_data = {
            "schema_version": 1,
            "sacas_root": "Structure",
            "context_budget": 12000,
            "adapters": [],
            "graphify_mode": "off",
            "graphify_output": ".sacas/graphify.json"
        }
        (sacas_root / ".sacas" / "manifest.json").write_text(json.dumps(manifest_data))
        
        yield repo


def test_compute_graph_snapshot_hash(fake_installation: FakeInstallation):
    """The fingerprint belongs to configured raw graph.json, not SACAS metadata."""
    fake_installation.manifest.graphify_mode = "existing"
    fake_installation.manifest.graphify_output = "custom-output"
    graph_dir = fake_installation.repository_root / "custom-output"
    graph_file = graph_dir / "graph.json"
    
    hash_val = _compute_graph_snapshot_hash(fake_installation)
    assert hash_val == ""
    
    # With raw graph.json
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_file.write_text('{"nodes": [], "edges": []}')
    
    hash_val = _compute_graph_snapshot_hash(fake_installation)
    assert hash_val != ""
    assert len(hash_val) == 64  # Full SHA256


def test_compute_source_hashes(fake_installation: FakeInstallation):
    """Test computing source file hashes."""
    hashes = _compute_source_hashes(fake_installation, ("src/auth.py", "src/user.py"))
    assert "src/auth.py" in hashes
    assert "src/user.py" in hashes
    assert len(hashes["src/auth.py"]) == 64
    assert len(hashes["src/user.py"]) == 64
    
    # Missing file
    hashes = _compute_source_hashes(fake_installation, ("src/missing.py",))
    assert hashes["src/missing.py"] == ""


def test_is_graph_changed(fake_installation: FakeInstallation):
    """Test graph change detection."""
    manifest = ActiveContextManifest(
        task_id="test",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash="sha256:old",
        files=(),
        events=(),
        goal="test",
        category="investigate"
    )
    
    # Manifest has graph hash but no graphify.json exists - this IS a change (graph removed)
    assert _is_graph_changed(manifest, "") == True
    
    # Different hash - should be changed
    assert _is_graph_changed(manifest, "sha256:new") == True
    
    # Same hash - should not be changed
    assert _is_graph_changed(manifest, "sha256:old") == False
    
    # A newly available graph is an invalidation too: it changes routing inputs.
    manifest_no_graph = ActiveContextManifest(
        task_id="test",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash="",
        files=(),
        events=(),
        goal="test",
        category="investigate"
    )
    assert _is_graph_changed(manifest_no_graph, "") == False
    assert _is_graph_changed(manifest_no_graph, "sha256:new") == True


def test_is_task_changed(fake_installation: FakeInstallation):
    """Test task contract change detection."""
    import tempfile
    import json
    from sacas.task_contract import TaskContract, task_contract_hash
    
    # Create a temp task directory with task.json
    with tempfile.TemporaryDirectory() as tmp:
        task_dir = Path(tmp)
        task_file = task_dir / "task.json"
        
        # Write initial task
        old_task = {
            "schema_version": 1,
            "task_id": "test",
            "goal": "old goal",
            "category": "investigate",
            "criteria": [],
            "constraints": [],
            "verification": []
        }
        task_file.write_text(json.dumps(old_task))
        
        # Compute the correct hash
        contract = TaskContract.from_dict(old_task)
        old_hash = task_contract_hash(contract)
        
        manifest = ActiveContextManifest(
            task_id="test",
            task_contract_hash=old_hash,
            git_revision="rev",
            graph_snapshot_hash="",
            files=(),
            events=(),
            goal="test",
            category="investigate"
        )
        
        # Same task - should not be changed
        assert _is_task_changed(manifest, task_dir) == False
        
        # Modify task.json
        new_task = {
            "schema_version": 1,
            "task_id": "test",
            "goal": "new goal",
            "category": "investigate",
            "criteria": [],
            "constraints": [],
            "verification": []
        }
        task_file.write_text(json.dumps(new_task))
        
        # Different task - should be changed
        assert _is_task_changed(manifest, task_dir) == True


def test_get_stale_files(fake_installation: FakeInstallation):
    """Test detecting stale files based on three fingerprints."""
    # Create manifest with file hashes - use ACTUAL file hashes
    auth_content = (fake_installation.repository_root / "src/auth.py").read_bytes()
    auth_hash = hashlib.sha256(auth_content).hexdigest()
    user_content = (fake_installation.repository_root / "src/user.py").read_bytes()
    user_hash = hashlib.sha256(user_content).hexdigest()
    
    # Use WRONG hash for auth.py to simulate change
    wrong_auth_hash = hashlib.sha256(b"old content").hexdigest()
    
    manifest = ActiveContextManifest(
        task_id="test",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash="sha256:graph",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="rev",
                reason="test",
                hash=wrong_auth_hash,  # Different from actual file
                role="source",
            ),
            ActiveFileContext(
                path="src/user.py",
                selection={"mode": "full"},
                source="graphify",
                ranking_score=0.8,
                confidence=0.8,
                evidence=("graphify_query",),
                relation="calls",
                trigger="task_goal",
                git_revision="rev",
                reason="test",
                hash=user_hash,  # Matches actual file
                role="source",
            ),
        ),
        events=(),
        goal="test",
        category="investigate"
    )
    
    source_changed, graph_derived_stale, task_dependent = _get_stale_files(fake_installation, manifest)
    
    # auth.py hash differs - should be in source_changed
    assert "src/auth.py" in source_changed
    
    # user.py hash matches - should NOT be in source_changed
    assert "src/user.py" not in source_changed
    
    # user.py is graphify-derived and graph changed - should be in graph_derived_stale
    assert "src/user.py" in graph_derived_stale


def test_refresh_detects_source_change(fake_installation: FakeInstallation):
    """Test refresh detects source file changes."""
    # Setup task directory
    task_dir = fake_installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    # Get current hash of auth.py
    auth_content = (fake_installation.repository_root / "src/auth.py").read_bytes()
    auth_hash = hashlib.sha256(auth_content).hexdigest()
    
    # Create manifest with WRONG hash
    wrong_hash = hashlib.sha256(b"different content").hexdigest()
    
    manifest = ActiveContextManifest(
        task_id="test-refresh",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash="",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="rev",
                reason="test",
                hash=wrong_hash,
                role="source",
            ),
        ),
        events=(),
        goal="test",
        category="investigate"
    )
    
    save_active_context(task_dir, manifest)
    
    # Update installation manifest to have current_task_id
    fake_installation.manifest.current_task_id = "test-refresh"
    
    # Run refresh - should detect change and update hash
    changed = refresh_context(fake_installation)
    
    # Should detect change
    assert changed == True
    
    # Reload manifest and check hash was updated
    from sacas.active_context import load_active_context
    updated = load_active_context(task_dir)
    assert updated.files[0].hash == auth_hash


def test_refresh_preserves_unchanged_files(fake_installation: FakeInstallation):
    """Test refresh preserves files that haven't changed."""
    task_dir = fake_installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    auth_content = (fake_installation.repository_root / "src/auth.py").read_bytes()
    auth_hash = hashlib.sha256(auth_content).hexdigest()
    user_content = (fake_installation.repository_root / "src/user.py").read_bytes()
    user_hash = hashlib.sha256(user_content).hexdigest()
    
    manifest = ActiveContextManifest(
        task_id="test-preserve",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash="",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="rev",
                reason="test",
                hash=auth_hash,
                role="source",
            ),
            ActiveFileContext(
                path="src/user.py",
                selection={"mode": "full"},
                source="graphify",
                ranking_score=0.8,
                confidence=0.8,
                evidence=("graphify_query",),
                relation="calls",
                trigger="task_goal",
                git_revision="rev",
                reason="test",
                hash=user_hash,
                role="source",
            ),
        ),
        events=(),
        goal="test",
        category="investigate"
    )
    
    save_active_context(task_dir, manifest)
    fake_installation.manifest.current_task_id = "test-preserve"
    
    # Run refresh - no changes
    changed = refresh_context(fake_installation)
    
    # A legacy manifest is upgraded to a canonical task contract on its first
    # refresh, which is itself a durable state change.
    assert changed is True
    assert (task_dir / "task.json").is_file()
    
    # Reload and verify both files preserved with same hashes
    from sacas.active_context import load_active_context
    updated = load_active_context(task_dir)
    assert len(updated.files) == 2
    for f in updated.files:
        if f.path == "src/auth.py":
            assert f.hash == auth_hash
        elif f.path == "src/user.py":
            assert f.hash == user_hash


def test_refresh_graph_change_invalidates_graph_files(fake_installation: FakeInstallation):
    """Test that graph changes invalidate graph-derived files."""
    # Create graphify.json
    graph_dir = fake_installation.sacas_root / ".sacas"
    graph_dir.mkdir(parents=True, exist_ok=True)
    graph_file = graph_dir / "graphify.json"
    graph_file.write_text('{"nodes": [], "edges": []}')
    
    task_dir = fake_installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    user_content = (fake_installation.repository_root / "src/user.py").read_bytes()
    user_hash = hashlib.sha256(user_content).hexdigest()
    
    # Manifest with OLD graph hash
    old_graph_hash = "sha256:old_graph_hash"
    
    manifest = ActiveContextManifest(
        task_id="test-graph-change",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash=old_graph_hash,
        files=(
            ActiveFileContext(
                path="src/user.py",
                selection={"mode": "full"},
                source="graphify",
                ranking_score=0.8,
                confidence=0.8,
                evidence=("graphify_query",),
                relation="calls",
                trigger="task_goal",
                git_revision="rev",
                reason="test",
                hash=user_hash,
                role="source",
            ),
        ),
        events=(),
        goal="test",
        category="investigate"
    )
    
    save_active_context(task_dir, manifest)
    fake_installation.manifest.current_task_id = "test-graph-change"
    
    # Run refresh - graph hash differs, should re-route graphify files
    changed = refresh_context(fake_installation)
    
    # Should detect graph change
    assert changed == True
    
    # Reload - graph_snapshot_hash should be updated
    from sacas.active_context import load_active_context
    updated = load_active_context(task_dir)
    assert updated.graph_snapshot_hash != old_graph_hash


def test_refresh_deleted_file(fake_installation: FakeInstallation):
    """Test refresh handles deleted source files."""
    task_dir = fake_installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    
    # Create temp file
    temp_file = fake_installation.repository_root / "src/temp.py"
    temp_file.write_text("print('hello')\n", encoding="utf-8")
    temp_hash = hashlib.sha256(temp_file.read_bytes()).hexdigest()
    
    manifest = ActiveContextManifest(
        task_id="test-deleted",
        task_contract_hash="sha256:task",
        git_revision="rev",
        graph_snapshot_hash="",
        files=(
            ActiveFileContext(
                path="src/temp.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="rev",
                reason="test",
                hash=temp_hash,
                role="source",
            ),
        ),
        events=(),
        goal="test",
        category="investigate"
    )
    
    save_active_context(task_dir, manifest)
    fake_installation.manifest.current_task_id = "test-deleted"
    
    # Delete the file
    temp_file.unlink()
    
    # Run refresh
    changed = refresh_context(fake_installation)
    
    # Should detect deletion and remove the no-longer-admissible source.
    assert changed == True
    
    from sacas.active_context import load_active_context
    updated = load_active_context(task_dir)
    assert updated.files == ()
