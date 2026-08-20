from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "relative, payload",
    [
        (".env", b"TOKEN=secret\n"),
        ("build/generated.py", b"x = 1\n"),
        ("src/binary.py", b"\x00"),
        ("src/invalid.py", b"\xff"),
        ("src/oversized.py", b"x" * 1_000_001),
    ],
    ids=("secret", "ignored", "binary", "invalid_utf8", "oversized"),
)
def test_route_goal_never_admits_unreadable_explicit_source_across_context_layers(
    tmp_path: Path, relative: str, payload: bytes
) -> None:
    """Failed source reads cannot create file, test, rule, or reference entries."""
    from sacas.init import initialize
    from sacas.tasks import route_goal

    root = tmp_path / "repo"
    root.mkdir()
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    installation = initialize(root).installation

    manifest = route_goal(
        installation,
        "secure routing",
        files=(relative,),
        tests=(relative,),
        rules=(relative,),
        references=(relative,),
    )

    assert manifest.files == ()
    assert manifest.rules == ()
    assert manifest.references == ()
    assert manifest.events == ()


def test_route_goal_never_admits_an_external_symlink(tmp_path: Path) -> None:
    """Every explicit context layer rejects a symlink that leaves the repo."""
    from sacas.init import initialize
    from sacas.tasks import route_goal

    root = tmp_path / "repo"
    root.mkdir()
    external = tmp_path / "outside.py"
    external.write_text("x = 1\n", encoding="utf-8")
    link = root / "src" / "outside.py"
    link.parent.mkdir()
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")
    installation = initialize(root).installation

    manifest = route_goal(
        installation,
        "secure routing",
        files=("src/outside.py",),
        tests=("src/outside.py",),
        rules=("src/outside.py",),
        references=("src/outside.py",),
    )

    assert manifest.files == ()
    assert manifest.rules == ()
    assert manifest.references == ()
    assert manifest.events == ()


def test_parse_protected_boundaries_rejects_external_symlink(tmp_path: Path) -> None:
    """Boundary policy is repository content and must not be read through an external link."""
    from sacas.tasks import parse_protected_boundaries

    root = tmp_path / "repo"
    boundaries = root / "Structure" / "rules" / "boundaries.md"
    boundaries.parent.mkdir(parents=True)
    external = tmp_path / "external-boundaries.md"
    external.write_text("MANUAL src/ | external policy\n", encoding="utf-8")
    try:
        boundaries.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")

    assert parse_protected_boundaries(root, boundaries) == ()


def test_fallback_routing_drops_candidates_rejected_by_the_source_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fallback candidate without an admissible source hash is not returned."""
    from sacas.tasks import run_fallback_routing

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

    class FakeIndex:
        def __init__(self, *_: object) -> None:
            pass

        def update(self) -> None:
            pass

        def search(self, _: str) -> list[tuple[int, str, list[str]]]:
            return [(10, ".env", ["secret"])]

    monkeypatch.setattr("sacas.search.FallbackIndex", FakeIndex)

    assert run_fallback_routing(root, root / "Structure", "secret", (), "head") == []


def test_graphify_routing_drops_candidates_rejected_by_the_source_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graphify paths cannot bypass the same source admission boundary."""
    from dataclasses import replace

    from sacas.graphify import GraphifyQueryResult
    from sacas.init import initialize
    from sacas.tasks import route_goal

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    initialized = initialize(root).installation
    installation = replace(initialized, manifest=replace(initialized.manifest, graphify_mode="existing"))

    class FakeProvider:
        def verify_capabilities(self, *, required: set[str]) -> bool:
            return required == {"query"}

        def query(self, *_: object, **__: object) -> GraphifyQueryResult:
            return GraphifyQueryResult("success", (), (), "", paths=(".env",))

        def validate_query_contract(self, result: GraphifyQueryResult) -> bool:
            return result.status == "success"

    monkeypatch.setattr("sacas.graphify.get_graphify_provider", lambda *_args, **_kwargs: FakeProvider())

    manifest = route_goal(installation, "secret")

    assert manifest.files == ()
    assert manifest.events == ()


def test_heuristic_reference_routing_skips_external_symlink(tmp_path: Path) -> None:
    """Heuristic Structure references must not read outside the repository."""
    from sacas.tasks import route_rules_and_references

    repository_root = tmp_path / "repo"
    references = repository_root / "Structure" / "references"
    references.mkdir(parents=True)
    external = tmp_path / "authentication.md"
    external.write_text("# Authentication\n", encoding="utf-8")
    link = references / "authentication.md"
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform")

    rules, routed_references = route_rules_and_references(
        repository_root,
        repository_root / "Structure",
        "improve authentication",
        (),
        (),
    )

    assert rules == []
    assert routed_references == []
