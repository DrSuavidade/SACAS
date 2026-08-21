"""Tests for the context compiler (WP0 baseline + WP2 architecture)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from sacas.compiler import (
    compile_context_pack,
    write_context_pack,
    compile_and_write_context_pack,
    read_context_pack,
    ContextPackHeader,
    ContextPackFragment,
)
from sacas.active_context import (
    ActiveContextManifest,
    ActiveFileContext,
    ActiveSymbolContext,
    SourceRange,
    ActiveRuleContext,
    ActiveReferenceContext,
)
from sacas.paths import Installation


class FakeInstallation:
    def __init__(self, repo_root: Path, sacas_root: Path):
        self.repository_root = repo_root
        self.sacas_root = sacas_root


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Each compiler test receives a writable copy, never the checked-in fixture."""
    source = Path(__file__).parent / "fixtures" / "context_compiler"
    copied = tmp_path / "context_compiler"
    shutil.copytree(source, copied)
    assert copied != source
    return copied


@pytest.fixture
def installation(fixture_repo: Path) -> FakeInstallation:
    return FakeInstallation(fixture_repo, fixture_repo)


@pytest.fixture
def manifest_with_symbol(installation: FakeInstallation) -> ActiveContextManifest:
    return ActiveContextManifest(
        task_id="test-001",
        task_contract_hash="sha256:abc123",
        git_revision="abc123",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={
                    "mode": "symbols",
                    "symbols": [
                        ActiveSymbolContext(
                            name="AuthService.validate_token",
                            range=SourceRange(10, 20, "parser", 0.9),
                            reason="validate token method",
                        )
                    ],
                },
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="abc123",
                reason="Test symbol",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="test goal",
        category="investigate",
    )


@pytest.fixture
def manifest_full_file(installation: FakeInstallation) -> ActiveContextManifest:
    return ActiveContextManifest(
        task_id="test-002",
        task_contract_hash="sha256:def456",
        git_revision="def456",
        files=(
            ActiveFileContext(
                path="src/user.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.8,
                confidence=0.8,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="def456",
                reason="Full file test",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="full file test",
        category="feature",
    )


def test_compiler_symbol_output_contains_exact_content(
    installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest
):
    """WP2.2: Symbol output must contain exact source lines."""
    header, fragments = compile_context_pack(installation, manifest_with_symbol)
    assert len(fragments) == 1
    fragment = fragments[0]
    assert fragment.lines == (10, 20)
    assert fragment.source == "src/auth.py"
    assert "validate_token" in fragment.selector
    assert fragment.content != ""  # Exact content included

    # Read the actual source lines
    source_path = installation.repository_root / "src/auth.py"
    content = source_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    expected_fragment = "\n".join(lines[9:20])  # 0-indexed

    # Hash must match exact emitted content
    expected_hash = hashlib.sha256(expected_fragment.encode()).hexdigest()[:16]
    assert fragment.content_hash == expected_hash
    assert fragment.content == expected_fragment


def test_compiler_full_file_output_contains_content(
    installation: FakeInstallation, manifest_full_file: ActiveContextManifest
):
    """WP2.2: Full file output must contain exact content."""
    header, fragments = compile_context_pack(installation, manifest_full_file)
    assert len(fragments) == 1
    fragment = fragments[0]
    assert fragment.lines is None
    assert fragment.source == "src/user.py"
    assert fragment.content != ""

    source_path = installation.repository_root / "src/user.py"
    content = source_path.read_text(encoding="utf-8")
    expected_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    assert fragment.content_hash == expected_hash
    assert fragment.content == content


def test_compiler_hash_matches_exact_content(
    installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest
):
    """WP2.2: Invariant - hash must match serialized fragment content exactly."""
    header, fragments = compile_context_pack(installation, manifest_with_symbol)
    fragment = fragments[0]

    # The fragment should have content that matches its hash
    computed_hash = hashlib.sha256(fragment.content.encode()).hexdigest()[:16]
    assert fragment.content_hash == computed_hash


def test_compiler_deterministic_ordering(installation: FakeInstallation):
    """WP2.5: Compilation must produce deterministic ordering."""
    # Create manifest with multiple files in non-alphabetical order
    manifest = ActiveContextManifest(
        task_id="test-order",
        task_contract_hash="sha256:order",
        git_revision="order",
        files=(
            ActiveFileContext(
                path="src/user.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.5,
                confidence=0.5,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="order",
                reason="User service",
                hash="",
                role="source",
            ),
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="order",
                reason="Auth service",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="order test",
        category="investigate",
    )

    header1, fragments1 = compile_context_pack(installation, manifest)
    header2, fragments2 = compile_context_pack(installation, manifest)

    # Order should be deterministic (by source path)
    assert [f.source for f in fragments1] == [f.source for f in fragments2]
    assert [f.id for f in fragments1] == [f.id for f in fragments2]


def test_compiler_deterministic_ids(installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest):
    """WP2.5: IDs must derive from final deterministic ordering."""
    header1, fragments1 = compile_context_pack(installation, manifest_with_symbol)
    header2, fragments2 = compile_context_pack(installation, manifest_with_symbol)
    assert fragments1[0].id == fragments2[0].id


def test_compiler_rules_compile(installation: FakeInstallation):
    """WP2: Rules must compile correctly."""
    manifest = ActiveContextManifest(
        task_id="test-rules",
        task_contract_hash="sha256:rules",
        git_revision="rules",
        files=(),
        rules=(
            ActiveRuleContext(
                path="src/auth.py",
                hash=hashlib.sha256(
                    (installation.repository_root / "src" / "auth.py").read_bytes()
                ).hexdigest(),
                reason="Auth rule",
            ),
        ),
        references=(),
        events=(),
        goal="rules test",
        category="investigate",
    )

    header, fragments = compile_context_pack(installation, manifest)
    assert len(fragments) == 1
    assert fragments[0].role == "rule"
    assert fragments[0].source == "src/auth.py"
    assert fragments[0].content != ""


def test_compiler_references_compile(installation: FakeInstallation):
    """WP2: References/Markdown sections must compile correctly."""
    # Create a markdown file
    md_path = installation.repository_root / "README.md"
    md_path.write_text("# Title\n\n## Section 1\n\nContent 1\n\n## Section 2\n\nContent 2\n", encoding="utf-8")

    try:
        manifest = ActiveContextManifest(
            task_id="test-refs",
            task_contract_hash="sha256:refs",
            git_revision="refs",
            files=(),
            rules=(),
            references=(
                ActiveReferenceContext(
                    path="README.md",
                    selection={"mode": "sections", "sections": [{"heading_path": ["Section 1"]}]},
                    hash="",
                    reason="Reference section",
                ),
            ),
            events=(),
            goal="refs test",
            category="documentation",
        )

        header, fragments = compile_context_pack(installation, manifest)
        assert len(fragments) == 1
        assert fragments[0].role == "reference"
        assert "Section 1" in fragments[0].selector
        assert "Content 1" in fragments[0].content
    finally:
        md_path.unlink(missing_ok=True)


def test_compiler_rejects_missing_reference_section(installation: FakeInstallation):
    """A section selector is an executable claim, not a full-document fallback."""
    md_path = installation.repository_root / "README.md"
    md_path.write_text("# Title\n\n## Present\n\nContent\n", encoding="utf-8")
    manifest = ActiveContextManifest(
        task_id="test-missing-reference-section",
        task_contract_hash="sha256:refs",
        git_revision="refs",
        references=(
            ActiveReferenceContext(
                path="README.md",
                selection={"mode": "sections", "sections": [{"heading_path": ["Absent"]}]},
                hash="",
                reason="Reference section",
            ),
        ),
        goal="refs test",
        category="documentation",
    )

    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="stale_selector"):
        compile_context_pack(installation, manifest)


def test_compiler_empty_context_pack(installation: FakeInstallation):
    """WP2: Empty context pack should work."""
    manifest = ActiveContextManifest(
        task_id="test-empty",
        task_contract_hash="sha256:empty",
        git_revision="empty",
        files=(),
        rules=(),
        references=(),
        events=(),
        goal="empty test",
        category="investigate",
    )

    header, fragments = compile_context_pack(installation, manifest)
    assert fragments == []
    assert header.fragment_count == 0
    assert header.estimated_tokens == 0


def test_compiler_missing_source_file(installation: FakeInstallation):
    """A missing canonical source rejects compilation."""
    manifest = ActiveContextManifest(
        task_id="test-missing",
        task_contract_hash="sha256:missing",
        git_revision="missing",
        files=(
            ActiveFileContext(
                path="src/nonexistent.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.5,
                confidence=0.5,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="missing",
                reason="Missing file",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="missing test",
        category="investigate",
    )

    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="source_unavailable"):
        compile_context_pack(installation, manifest)


def test_compiler_deleted_source_file(installation: FakeInstallation):
    """WP2: Deleted source file should not produce stale fragment."""
    # Create a temp file, add to manifest, then delete
    temp_file = installation.repository_root / "src/temp.py"
    temp_file.write_text("print('hello')\n", encoding="utf-8")

    manifest = ActiveContextManifest(
        task_id="test-deleted",
        task_contract_hash="sha256:deleted",
        git_revision="deleted",
        files=(
            ActiveFileContext(
                path="src/temp.py",
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.5,
                confidence=0.5,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="deleted",
                reason="Temp file",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="deleted test",
        category="investigate",
    )

    # File exists - should compile
    header, fragments = compile_context_pack(installation, manifest)
    assert len(fragments) == 1

    # Delete file
    temp_file.unlink()

    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="source_unavailable"):
        compile_context_pack(installation, manifest)


def test_compiler_write_context_pack(installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest):
    """WP2.7: write_context_pack creates valid JSONL with header + fragments."""
    header, fragments = compile_context_pack(installation, manifest_with_symbol)
    pack_path = write_context_pack(installation, header, fragments)

    assert pack_path.exists()
    assert pack_path.name == "context.pack.jsonl"

    # Read and validate JSONL
    lines = pack_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2  # header + 1 fragment
    header_data = json.loads(lines[0])
    assert header_data["type"] == "pack"
    assert header_data["task_id"] == "test-001"
    assert header_data["fragment_count"] == 1
    
    fragment_data = json.loads(lines[1])
    assert fragment_data["type"] == "fragment"
    assert fragment_data["id"] == "ctx-001"
    assert fragment_data["source"] == "src/auth.py"
    assert "content" in fragment_data
    assert fragment_data["content_hash"] is not None


def test_compiler_secure_path_enforcement(installation: FakeInstallation):
    """WP1/WP2: Compiler must not read paths that escape repository."""
    manifest = ActiveContextManifest(
        task_id="test-security",
        task_contract_hash="sha256:security",
        git_revision="security",
        files=(
            ActiveFileContext(
                path="../secret.txt",  # Attempt escape
                selection={"mode": "full"},
                source="explicit",
                ranking_score=0.5,
                confidence=0.5,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="security",
                reason="Security test",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="security test",
        category="security",
    )

    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="source_unsafe"):
        compile_context_pack(installation, manifest)


def test_compiler_overlapping_ranges_merge(installation: FakeInstallation):
    """WP2.3: Overlapping ranges should merge."""
    manifest = ActiveContextManifest(
        task_id="test-overlap",
        task_contract_hash="sha256:overlap",
        git_revision="overlap",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={
                    "mode": "symbols",
                    "symbols": [
                        ActiveSymbolContext(name="AuthService.validate_token", range=SourceRange(10, 20, "parser", 0.9), reason="symbol 1"),
                        ActiveSymbolContext(name="AuthService.refresh_token", range=SourceRange(15, 30, "parser", 0.9), reason="symbol 2"),  # Overlaps
                    ],
                },
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="overlap",
                reason="Overlap test",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="overlap test",
        category="investigate",
    )

    header, fragments = compile_context_pack(installation, manifest)
    # Should produce 1 merged entry with lines (10, 30)
    assert len(fragments) == 1
    assert fragments[0].lines == (10, 30)


def test_compiler_adjacent_ranges_merge(installation: FakeInstallation):
    """WP2.3: Adjacent ranges should merge."""
    manifest = ActiveContextManifest(
        task_id="test-adjacent",
        task_contract_hash="sha256:adjacent",
        git_revision="adjacent",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={
                    "mode": "symbols",
                    "symbols": [
                        ActiveSymbolContext(name="AuthService.validate_token", range=SourceRange(10, 20, "parser", 0.9), reason="symbol 1"),
                        ActiveSymbolContext(name="AuthService.refresh_token", range=SourceRange(21, 30, "parser", 0.9), reason="symbol 2"),  # Adjacent
                    ],
                },
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="adjacent",
                reason="Adjacent test",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="adjacent test",
        category="investigate",
    )

    header, fragments = compile_context_pack(installation, manifest)
    # Should merge adjacent
    assert len(fragments) == 1
    assert fragments[0].lines == (10, 30)


def test_compiler_unresolved_selector_fails_closed(installation: FakeInstallation):
    """An unresolved symbol must not become a broad full-file fallback."""
    manifest = ActiveContextManifest(
        task_id="test-dup-full",
        task_contract_hash="sha256:dupfull",
        git_revision="dupfull",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "symbols", "symbols": [
                    ActiveSymbolContext(name="NonexistentSymbol1", range=None, reason="unresolved"),
                    ActiveSymbolContext(name="NonexistentSymbol2", range=None, reason="unresolved"),
                ]},
                source="explicit",
                ranking_score=0.9,
                confidence=0.9,
                evidence=("explicit",),
                relation=None,
                trigger="initial_route",
                git_revision="dupfull",
                reason="Unresolved symbols",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="dupe test",
        category="investigate",
    )

    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="stale_selector"):
        compile_context_pack(installation, manifest)


def test_compiler_stale_selector_detection(installation: FakeInstallation):
    """WP2.6: Stale selectors should trigger invalidation path (future test)."""
    # This test documents expected behavior for WP2.6
    # A selector that was valid but source has changed should be detected
    # The stale detection is now implemented in _build_file_selections
    # This test verifies the stale_reason is set correctly
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "test.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8")
        
        fake_inst = FakeInstallation(repo, repo)
        
        # Create manifest with a selector for "foo" at lines 1-1
        from sacas.active_context import ActiveContextManifest, ActiveFileContext, ActiveSymbolContext, SourceRange, AdmissionEvent, save_active_context
        
        task_dir = repo / "tasks" / "current"
        task_dir.mkdir(parents=True, exist_ok=True)
        
        manifest = ActiveContextManifest(
            task_id="test-stale",
            task_contract_hash="sha256:stale",
            git_revision="stale",
            files=(
                ActiveFileContext(
                    path="src/test.py",
                    selection={"mode": "symbols", "symbols": [
                        ActiveSymbolContext(name="foo", range=SourceRange(1, 1, "parser", 0.9), reason="test")
                    ]},
                    source="explicit",
                    ranking_score=0.9,
                    confidence=0.9,
                    evidence=("explicit",),
                    relation=None,
                    trigger="initial_route",
                    git_revision="stale",
                    reason="test",
                    hash="",
                    role="source",
                ),
            ),
            rules=(),
            references=(),
            events=(
                AdmissionEvent(
                    id="evt-001",
                    target="src/test.py",
                    action="admit",
                    source="explicit",
                    reason="test",
                    trigger="initial_route",
                    ranking_score=0.9,
                    confidence=0.9,
                    evidence=("explicit",),
                ),
            ),
            goal="test",
            category="investigate",
        )
        
        save_active_context(task_dir, manifest)
        
        # Compile - should work (foo exists at line 1)
        header, fragments = compile_context_pack(fake_inst, manifest)
        assert len(fragments) == 1
        assert fragments[0].fallback_reason is None
        
        # Now change the file so foo moves
        (repo / "src" / "test.py").write_text("# comment\n\ndef foo():\n    pass\n", encoding="utf-8")
        
        # Re-compile - stale selectors require refresh before publication.
        from sacas.compiler import ContextCompilationError
        with pytest.raises(ContextCompilationError, match="stale_selector"):
            compile_context_pack(fake_inst, manifest)


def test_compiler_identical_state_byte_identical(installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest):
    """WP2: Identical state must produce byte-identical pack."""
    pack_path1 = compile_and_write_context_pack(installation, manifest_with_symbol)
    content1 = pack_path1.read_bytes()

    pack_path2 = compile_and_write_context_pack(installation, manifest_with_symbol)
    content2 = pack_path2.read_bytes()

    assert content1 == content2


def test_compiler_pack_structure(installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest):
    """Baseline: Verify new pack structure with header + fragments."""
    header, fragments = compile_context_pack(installation, manifest_with_symbol)
    pack_path = write_context_pack(installation, header, fragments)

    lines = pack_path.read_text(encoding="utf-8").strip().split("\n")
    header_data = json.loads(lines[0])
    fragment_data = json.loads(lines[1])

    # Header schema
    assert header_data["type"] == "pack"
    assert header_data["schema_version"] == 1
    assert "task_id" in header_data
    assert "task_contract_hash" in header_data
    assert "git_revision" in header_data
    assert "graph_snapshot_hash" in header_data
    assert "estimated_tokens" in header_data
    assert "fragment_count" in header_data

    # Fragment schema
    assert fragment_data["type"] == "fragment"
    assert "id" in fragment_data
    assert "source" in fragment_data
    assert "selector" in fragment_data
    assert "lines" in fragment_data
    assert "content" in fragment_data
    assert "content_hash" in fragment_data
    assert "reason" in fragment_data
    assert "estimated_tokens" in fragment_data
    assert "admission_event_ids" in fragment_data
    assert "role" in fragment_data
    assert "ranking_score" in fragment_data
    assert "confidence" in fragment_data
    assert "fallback_reason" in fragment_data


def test_compiler_read_context_pack(installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest):
    """Test reading context pack back."""
    header, fragments = compile_context_pack(installation, manifest_with_symbol)
    pack_path = write_context_pack(installation, header, fragments)

    read_header, read_fragments = read_context_pack(pack_path)
    assert read_header.task_id == header.task_id
    assert read_header.fragment_count == header.fragment_count
    assert len(read_fragments) == len(fragments)
    assert read_fragments[0].id == fragments[0].id
    assert read_fragments[0].content == fragments[0].content
    assert read_fragments[0].content_hash == fragments[0].content_hash


@pytest.mark.parametrize("integer_field", ("schema_version", "fragment_count", "estimated_tokens"))
def test_validate_context_pack_records_rejects_boolean_header_integer_fields(integer_field: str) -> None:
    """Boolean values must not pass JSONL integer-field validation."""
    from dataclasses import replace
    from sacas.compiler import validate_context_pack_records

    header = ContextPackHeader(
        task_id="task",
        task_contract_hash="contract",
        git_revision="revision",
        graph_snapshot_hash="",
    )

    with pytest.raises(ValueError, match="invalid context pack header schema|invalid fragment count|invalid token estimate"):
        validate_context_pack_records(replace(header, **{integer_field: True}), [])


def test_validate_context_pack_records_rejects_boolean_fragment_token_count() -> None:
    """Boolean values must not pass fragment token-count validation either."""
    from sacas.compiler import validate_context_pack_records

    content = "value = 1\n"
    fragment = ContextPackFragment(
        id="ctx-001",
        source="src/example.py",
        selector="src/example.py",
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        role="source",
        estimated_tokens=True,
    )
    header = ContextPackHeader(
        task_id="task",
        task_contract_hash="contract",
        git_revision="revision",
        graph_snapshot_hash="",
        fragment_count=1,
    )

    with pytest.raises(ValueError, match="invalid token estimate"):
        validate_context_pack_records(header, [fragment])


@pytest.mark.parametrize(
    "payload",
    (
        "not json\n",
        "[]\n",
        '{"type":"pack","schema_version":1,"task_id":7}\n',
        '{"type":"pack","schema_version":1,"task_id":"task","task_contract_hash":"hash","git_revision":"rev","graph_snapshot_hash":"","estimated_tokens":0,"fragment_count":0}\n[]\n',
        '{"type":"pack","schema_version":1,"task_id":"task","task_contract_hash":"hash","git_revision":"rev","graph_snapshot_hash":"","estimated_tokens":0,"fragment_count":0}\n{"type":"note"}\n',
    ),
)
def test_read_context_pack_rejects_malformed_jsonl_records(tmp_path: Path, payload: str) -> None:
    """Every serialized record must be a schema-valid mapping of its declared type."""
    from sacas.compiler import read_context_pack

    pack_path = tmp_path / "context.pack.jsonl"
    pack_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError):
        read_context_pack(pack_path)


def test_regions_normalize_selections():
    """Test regions.py normalize_selections (used by compiler)."""
    from sacas.regions import normalize_selections, merge_ranges
    from sacas.active_context import ActiveSymbolContext, SourceRange

    symbols = [
        ActiveSymbolContext(name="foo", range=SourceRange(10, 20, "parser", 0.9)),
        ActiveSymbolContext(name="bar", range=SourceRange(15, 30, "parser", 0.9)),  # Overlaps
        ActiveSymbolContext(name="baz", range=SourceRange(31, 40, "parser", 0.9)),  # Adjacent to bar
    ]

    normalized = normalize_selections(tuple(symbols))
    # Should merge overlapping and adjacent
    assert len(normalized) <= len(symbols)


def test_regions_merge_ranges():
    """Test regions.py merge_ranges directly."""
    from sacas.regions import merge_ranges

    # Overlapping
    assert merge_ranges([(10, 20), (15, 30)]) == [(10, 30)]
    # Adjacent
    assert merge_ranges([(10, 20), (21, 30)]) == [(10, 30)]
    # Separate
    assert merge_ranges([(10, 20), (30, 40)]) == [(10, 20), (30, 40)]
    # Contained
    assert merge_ranges([(10, 30), (15, 20)]) == [(10, 30)]
    # Unsorted input
    assert merge_ranges([(30, 40), (10, 20)]) == [(10, 20), (30, 40)]


def test_compiler_admission_event_ids_collected(installation: FakeInstallation):
    """Test that admission event IDs are collected for fragments."""
    manifest = ActiveContextManifest(
        task_id="test-events",
        task_contract_hash="sha256:events",
        git_revision="events",
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
                git_revision="events",
                reason="Test",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(
            # Add an admission event for this file
            __import__('sacas.active_context', fromlist=['AdmissionEvent']).AdmissionEvent(
                id="evt-001",
                target="src/auth.py",
                action="admit",
                source="explicit",
                reason="Test",
                trigger="initial_route",
            ),
        ),
        goal="events test",
        category="investigate",
    )

    header, fragments = compile_context_pack(installation, manifest)
    assert len(fragments) == 1
    assert "evt-001" in fragments[0].admission_event_ids


def test_compiler_stale_merged_symbol_selector_fails_closed(installation: FakeInstallation):
    """One merged range must retain its constituent selectors' provenance."""
    from sacas.active_context import AdmissionEvent, ActiveSymbolContext, SourceRange
    manifest = ActiveContextManifest(
        task_id="merged-events", task_contract_hash="hash", git_revision="rev",
        files=(ActiveFileContext(
            path="src/auth.py", source="explicit", selection={"mode": "symbols", "symbols": [
                ActiveSymbolContext("login", SourceRange(1, 3, "parser", 1.0)),
                ActiveSymbolContext("validate", SourceRange(3, 5, "parser", 1.0)),
            ]},
        ),),
        events=(
            AdmissionEvent("evt-login", "src/auth.py::login", "admit", "explicit", "login", "initial"),
            AdmissionEvent("evt-validate", "src/auth.py::validate", "admit", "explicit", "validate", "initial"),
        ),
    )
    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="stale_selector"):
        compile_context_pack(installation, manifest)


def test_compiler_stale_merged_selector_is_detected_independent_of_order(installation: FakeInstallation):
    """The serialized selector remains canonical when persisted symbol order differs."""
    from sacas.active_context import AdmissionEvent, ActiveSymbolContext, SourceRange
    manifest = ActiveContextManifest(
        task_id="merged-events", task_contract_hash="hash", git_revision="rev",
        files=(ActiveFileContext(
            path="src/auth.py", source="explicit", selection={"mode": "symbols", "symbols": [
                ActiveSymbolContext("validate", SourceRange(3, 5, "parser", 1.0)),
                ActiveSymbolContext("login", SourceRange(1, 3, "parser", 1.0)),
            ]},
        ),),
        events=(
            AdmissionEvent("evt-login", "src/auth.py::login", "admit", "explicit", "login", "initial"),
            AdmissionEvent("evt-validate", "src/auth.py::validate", "admit", "explicit", "validate", "initial"),
        ),
    )
    from sacas.compiler import ContextCompilationError
    with pytest.raises(ContextCompilationError, match="stale_selector"):
        compile_context_pack(installation, manifest)


def test_compiler_ranking_confidence_separate(installation: FakeInstallation):
    """WP3.3: Ranking score and confidence are separate fields."""
    manifest = ActiveContextManifest(
        task_id="test-rank-conf",
        task_contract_hash="sha256:rc",
        git_revision="rc",
        files=(
            ActiveFileContext(
                path="src/auth.py",
                selection={"mode": "full"},
                source="graphify",
                ranking_score=0.42,
                confidence=0.95,
                evidence=("graphify",),
                relation="calls",
                trigger="expansion",
                git_revision="rc",
                reason="Graphify found this",
                hash="",
                role="source",
            ),
        ),
        rules=(),
        references=(),
        events=(),
        goal="ranking vs confidence",
        category="investigate",
    )

    header, fragments = compile_context_pack(installation, manifest)
    assert len(fragments) == 1
    frag = fragments[0]
    assert frag.ranking_score == 0.42
    assert frag.confidence == 0.95


# Baseline snapshot test - captures current compiler output for regression detection
def test_compiler_baseline_snapshot(installation: FakeInstallation, manifest_with_symbol: ActiveContextManifest):
    """WP0: Baseline snapshot of current compiler output."""
    header, fragments = compile_context_pack(installation, manifest_with_symbol)
    pack_path = write_context_pack(installation, header, fragments)
    content = pack_path.read_text(encoding="utf-8")

    # This captures the current behavior for regression testing
    assert "ctx-001" in content
    assert "src/auth.py" in content
    assert "content_hash" in content
    assert "type" in content
    assert "pack" in content


def test_compiler_fails_closed_when_an_admitted_source_is_unavailable(
    installation: FakeInstallation,
) -> None:
    """A canonical admission must never disappear from a compiled payload."""
    from sacas.compiler import ContextCompilationError

    manifest = ActiveContextManifest(
        task_id="missing-source", task_contract_hash="contract", git_revision="rev",
        files=(ActiveFileContext(
            path="src/does-not-exist.py", selection={"mode": "full"}, source="explicit",
        ),),
    )

    with pytest.raises(ContextCompilationError, match="source_unavailable"):
        compile_context_pack(installation, manifest)


def test_compiler_rejects_an_admitted_source_changed_after_its_hash_was_recorded(
    installation: FakeInstallation,
) -> None:
    """Compilation cannot turn a source edit into an unrecorded context pack."""
    from sacas.compiler import ContextCompilationError

    source = installation.repository_root / "src" / "auth.py"
    admitted_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = ActiveContextManifest(
        task_id="stale-source", task_contract_hash="contract", git_revision="rev",
        files=(ActiveFileContext(
            path="src/auth.py", selection={"mode": "full"}, source="explicit",
            hash=admitted_hash,
        ),),
    )
    source.write_text("def replacement():\n    return False\n", encoding="utf-8")

    with pytest.raises(ContextCompilationError, match="source_hash_mismatch"):
        compile_context_pack(installation, manifest)


def test_validated_pack_rejects_source_changed_after_publication(tmp_path: Path) -> None:
    """Runtime consumers bind pack bytes to the still-current admitted source."""
    from sacas.compiler import load_validated_context_pack
    from sacas.init import initialize
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "one.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Publish source", files=("src/one.py",))
    source.write_text("value = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="canonical source hash mismatch: src/one.py"):
        load_validated_context_pack(initialized.installation)


def test_publisher_rejects_source_changed_after_canonical_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publication stops before its runtime write when admitted source bytes changed."""
    from sacas.active_context import load_active_context
    from sacas.compiler import ContextCompilationError
    from sacas.init import initialize
    from sacas.tasks import generate_task, publish_task_artifacts
    import sacas.tasks as tasks_module

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "one.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Publish source", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    source.write_text("value = 2\n", encoding="utf-8")

    def must_not_write(*args: object, **kwargs: object) -> Path:
        raise AssertionError("publisher wrote a pack with stale source bytes")

    monkeypatch.setattr(tasks_module, "write_context_pack", must_not_write)
    with pytest.raises(ContextCompilationError, match="source_hash_mismatch"):
        publish_task_artifacts(initialized.installation, task_dir, manifest, {})


def test_compiler_fails_closed_for_a_stale_symbol_selector(
    installation: FakeInstallation,
) -> None:
    """An out-of-date selected range must be refreshed, never silently widened."""
    from sacas.compiler import ContextCompilationError

    manifest = ActiveContextManifest(
        task_id="stale-selector", task_contract_hash="contract", git_revision="rev",
        files=(ActiveFileContext(
            path="src/auth.py",
            selection={"mode": "symbols", "symbols": [
                ActiveSymbolContext("missing_symbol", SourceRange(1, 1, "parser", 1.0)),
            ]},
            source="explicit",
        ),),
    )

    with pytest.raises(ContextCompilationError, match="stale_selector"):
        compile_context_pack(installation, manifest)


@pytest.mark.parametrize(
    ("filename", "payload_size", "expected_code"),
    [
        ("binary.bin", 0, "source_binary"),
        ("too-large.py", 1_000_001, "source_oversized"),
    ],
)
def test_compiler_classifies_unsafe_source_content(
    installation: FakeInstallation, filename: str, payload_size: int, expected_code: str,
) -> None:
    """Unsafe admitted content is a typed compilation failure, never a skip."""
    from sacas.compiler import ContextCompilationError

    path = f"src/{filename}"
    payload = b"\x00not-source" if payload_size == 0 else b"x" * payload_size
    (installation.repository_root / path).write_bytes(payload)
    manifest = ActiveContextManifest(
        task_id="unsafe", task_contract_hash="contract", git_revision="rev",
        files=(ActiveFileContext(path=path, selection={"mode": "full"}, source="explicit"),),
    )

    with pytest.raises(ContextCompilationError, match=expected_code):
        compile_context_pack(installation, manifest)


def test_validated_pack_rejects_a_contract_hash_mismatch(tmp_path: Path) -> None:
    """Pack consumers require the pack and the current canonical contract to agree."""
    from sacas.compiler import compile_and_write_context_pack, load_validated_context_pack
    from sacas.init import initialize
    from sacas.task_contract import TaskContract, save_task_contract
    from sacas.active_context import save_active_context

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    task_dir = initialized.installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)
    manifest = ActiveContextManifest(
        task_id="task", task_contract_hash="wrong", git_revision="rev",
        files=(ActiveFileContext(path="src/one.py", selection={"mode": "full"}, source="explicit"),),
    )
    save_active_context(task_dir, manifest)
    save_task_contract(task_dir, TaskContract(1, "task", "goal", "investigate", (), (), ()))
    compile_and_write_context_pack(initialized.installation, manifest)

    with pytest.raises(ValueError, match="contract hash"):
        load_validated_context_pack(initialized.installation)


def test_publisher_leaves_pre_manifest_crash_pack_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If publication stops before canonical state, readers reject the new pack."""
    from dataclasses import replace
    from sacas.compiler import load_validated_context_pack
    from sacas.init import initialize
    from sacas.tasks import generate_task, publish_task_artifacts
    import sacas.tasks as tasks_module

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Original", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    from sacas.active_context import load_active_context
    original = load_active_context(task_dir)
    assert original is not None
    newer = replace(
        original,
        git_revision="source-refresh-revision",
        graph_snapshot_hash="graph-refresh-hash",
    )

    def fail_before_manifest(*args: object, **kwargs: object) -> None:
        raise OSError("simulated pre-manifest crash")

    monkeypatch.setattr(tasks_module, "save_active_context", fail_before_manifest)
    with pytest.raises(OSError, match="pre-manifest"):
        publish_task_artifacts(initialized.installation, task_dir, newer, {})

    with pytest.raises(ValueError, match="identity"):
        load_validated_context_pack(initialized.installation)


def test_validated_pack_rejects_header_source_or_graph_identity_mutation(tmp_path: Path) -> None:
    """A pack header cannot claim a source or graph state absent from its manifest."""
    from dataclasses import replace
    from sacas.compiler import (
        compile_and_write_context_pack,
        load_validated_context_pack,
        read_context_pack,
        write_context_pack,
    )
    from sacas.init import initialize
    from sacas.tasks import generate_task
    from sacas.active_context import load_active_context

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Original", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    compile_and_write_context_pack(initialized.installation, manifest)
    header, fragments = read_context_pack(
        initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    )
    write_context_pack(
        initialized.installation,
        replace(header, git_revision="mutated-revision", graph_snapshot_hash="mutated-graph"),
        fragments,
    )

    with pytest.raises(ValueError, match="identity"):
        load_validated_context_pack(initialized.installation)


@pytest.mark.parametrize(
    "omitted_source, expected_kind",
    [
        ("src/app.py", "file"),
        ("tests/test_app.py", "test"),
        ("Structure/rules/task.md", "rule"),
        ("Structure/references/task.md", "reference"),
    ],
)
def test_validated_pack_rejects_dropped_canonical_fragment_after_header_recount(
    tmp_path: Path, omitted_source: str, expected_kind: str,
) -> None:
    """Runtime consumers reject a self-consistent pack missing canonical coverage."""
    from dataclasses import replace
    from sacas.active_context import save_active_context
    from sacas.compiler import (
        compile_and_write_context_pack,
        load_validated_context_pack,
        read_context_pack,
        write_context_pack,
    )
    from sacas.init import initialize
    from sacas.task_contract import TaskContract, save_task_contract, task_contract_hash

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text("def test_value():\n    assert 1\n", encoding="utf-8")
    (initialized.sacas_root / "rules" / "task.md").write_text("# Rule\n", encoding="utf-8")
    (initialized.sacas_root / "references" / "task.md").write_text("# Reference\n", encoding="utf-8")
    task_dir = initialized.sacas_root / "tasks" / "current"
    contract = TaskContract(1, "coverage", "coverage", "investigate", (), (), ())
    save_task_contract(task_dir, contract)
    manifest = ActiveContextManifest(
        task_id="coverage",
        task_contract_hash=task_contract_hash(contract),
        git_revision="rev",
        files=(
            ActiveFileContext(path="src/app.py", selection={"mode": "full"}, source="explicit"),
            ActiveFileContext(
                path="tests/test_app.py", selection={"mode": "full"}, source="explicit", role="test",
            ),
        ),
        tests=("tests/test_app.py",),
        rules=(ActiveRuleContext("Structure/rules/task.md", "", "required rule"),),
        references=(ActiveReferenceContext("Structure/references/task.md", {"mode": "full"}, "", "required reference"),),
    )
    save_active_context(task_dir, manifest)
    compile_and_write_context_pack(initialized.installation, manifest)
    header, fragments = read_context_pack(
        initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    )
    tampered = [fragment for fragment in fragments if fragment.source != omitted_source]
    write_context_pack(initialized.installation, replace(header, fragment_count=len(tampered)), tampered)

    with pytest.raises(ValueError, match=rf"canonical {expected_kind} coverage"):
        load_validated_context_pack(initialized.installation)


def test_validated_pack_rejects_source_fragment_with_a_non_source_role(tmp_path: Path) -> None:
    """A matching path cannot satisfy source admission under the wrong pack role."""
    from dataclasses import replace
    from sacas.active_context import load_active_context
    from sacas.compiler import (
        compile_and_write_context_pack,
        load_validated_context_pack,
        read_context_pack,
        write_context_pack,
    )
    from sacas.init import initialize
    from sacas.tasks import generate_task

    initialized = initialize(tmp_path, graphify_mode="off")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Role coverage", files=("src/app.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    compile_and_write_context_pack(initialized.installation, manifest)
    pack_path = initialized.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    header, fragments = read_context_pack(pack_path)
    tampered = [
        replace(fragment, role="rule") if fragment.source == "src/app.py" else fragment
        for fragment in fragments
    ]
    write_context_pack(initialized.installation, header, tampered)

    with pytest.raises(ValueError, match="canonical file coverage"):
        load_validated_context_pack(initialized.installation)


def test_publisher_validates_in_memory_fragment_coverage_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publisher rejects an incomplete compiler result before it can replace the runtime pack."""
    from dataclasses import replace
    from sacas.active_context import load_active_context
    from sacas.compiler import ContextPackHeader
    from sacas.init import initialize
    from sacas.tasks import generate_task, publish_task_artifacts
    import sacas.tasks as tasks_module

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Original", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None

    def incomplete_pack(*args: object, **kwargs: object) -> tuple[ContextPackHeader, list[ContextPackFragment]]:
        return ContextPackHeader(
            task_id=manifest.task_id,
            task_contract_hash=manifest.task_contract_hash,
            git_revision=manifest.git_revision,
            graph_snapshot_hash=manifest.graph_snapshot_hash,
            fragment_count=0,
        ), []

    def must_not_write(*args: object, **kwargs: object) -> Path:
        raise AssertionError("publisher wrote an invalid in-memory pack")

    monkeypatch.setattr(tasks_module, "compile_context_pack", incomplete_pack)
    monkeypatch.setattr(tasks_module, "write_context_pack", must_not_write)
    with pytest.raises(ValueError, match="canonical file coverage"):
        publish_task_artifacts(initialized.installation, task_dir, manifest, {})


def test_publisher_rejects_tampered_in_memory_pack_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The publisher validates compiler records before any runtime write occurs."""
    from dataclasses import replace
    from sacas.active_context import load_active_context
    from sacas.init import initialize
    from sacas.tasks import generate_task, publish_task_artifacts
    import sacas.tasks as tasks_module

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Original", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    assert manifest is not None
    original_compile = tasks_module.compile_context_pack

    def tampered_pack(*args: object, **kwargs: object) -> tuple[ContextPackHeader, list[ContextPackFragment]]:
        header, fragments = original_compile(*args, **kwargs)
        return header, [replace(fragments[0], content_hash="not-a-valid-hash"), *fragments[1:]]

    def must_not_write(*args: object, **kwargs: object) -> Path:
        raise AssertionError("publisher wrote a tampered in-memory pack")

    monkeypatch.setattr(tasks_module, "compile_context_pack", tampered_pack)
    monkeypatch.setattr(tasks_module, "write_context_pack", must_not_write)
    with pytest.raises(ValueError, match="content hash mismatch"):
        publish_task_artifacts(initialized.installation, task_dir, manifest, {})


def test_publisher_keeps_pack_and_manifest_coherent_after_view_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A post-manifest crash may skip views but leaves a reader-valid canonical pack."""
    from dataclasses import replace
    from sacas.compiler import load_validated_context_pack
    from sacas.init import initialize
    from sacas.tasks import generate_task, publish_task_artifacts
    import sacas.tasks as tasks_module
    from sacas.active_context import load_active_context

    initialized = initialize(tmp_path, graphify_mode="off")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.py").write_text("value = 1\n", encoding="utf-8")
    generate_task(initialized.installation, "Original", files=("src/one.py",))
    task_dir = initialized.sacas_root / "tasks" / "current"
    original = load_active_context(task_dir)
    assert original is not None
    newer = replace(original, git_revision="post-manifest-revision")

    def fail_view_write(path: Path, content: str) -> None:
        if path.name == "TASK.md":
            raise OSError("simulated post-manifest crash")
        raise AssertionError(f"unexpected view write: {path}")

    monkeypatch.setattr(tasks_module, "write_text_atomic", fail_view_write)
    with pytest.raises(OSError, match="post-manifest"):
        publish_task_artifacts(
            initialized.installation, task_dir, newer, {task_dir / "TASK.md": "new view\n"},
        )

    header, _ = load_validated_context_pack(initialized.installation)
    assert header.git_revision == "post-manifest-revision"
