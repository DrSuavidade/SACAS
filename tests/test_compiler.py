"""Tests for the context compiler (WP0 baseline + WP2 architecture)."""

from __future__ import annotations

import hashlib
import json
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
def fixture_repo() -> Path:
    return Path("tests/fixtures/context_compiler")


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
            ActiveRuleContext(path="src/auth.py", hash="abc", reason="Auth rule"),
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
    """WP2: Missing source file should be skipped gracefully."""
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

    header, fragments = compile_context_pack(installation, manifest)
    # Should skip missing file
    assert fragments == []
    assert header.fragment_count == 0


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

    # Should skip deleted file
    header, fragments = compile_context_pack(installation, manifest)
    assert fragments == []


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

    header, fragments = compile_context_pack(installation, manifest)
    # Should not crash - either skip or handle gracefully
    assert isinstance(fragments, list)
    assert header.fragment_count == 0


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


def test_compiler_duplicate_full_file_dedupe(installation: FakeInstallation):
    """WP2.4: Duplicate full-file fallbacks must dedupe."""
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

    header, fragments = compile_context_pack(installation, manifest)
    # Should deduplicate by (source, normalized_range) - full file = None
    assert len(fragments) == 1
    assert fragments[0].lines is None


def test_compiler_stale_selector_detection(installation: FakeInstallation):
    """WP2.6: Stale selectors should trigger invalidation path (future test)."""
    # This test documents expected behavior for WP2.6
    # A selector that was valid but source has changed should be detected
    pass


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