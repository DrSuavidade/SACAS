"""Behavioral tests for deterministic repository evidence collection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


def copy_fixture(name: str, destination: Path) -> Path:
    root = destination / name
    shutil.copytree(FIXTURES / name, root)
    return root


@pytest.mark.parametrize(
    ("fixture", "expected_ecosystems"),
    [
        ("node-monorepo", {"npm", "pnpm", "nx", "turbo"}),
        ("python-service", {"python"}),
        ("dotnet-monolith", {"dotnet"}),
        ("nextjs-app", {"npm", "nextjs"}),
        ("rust-workspace", {"cargo"}),
        ("mixed-repo", {"go", "docker-compose", "maven", "gradle"}),
    ],
)
def test_metadata_detection_reports_supported_ecosystems(
    tmp_path: Path, fixture: str, expected_ecosystems: set[str]
) -> None:
    from sacas.repository import collect_repository_evidence

    report = collect_repository_evidence(copy_fixture(fixture, tmp_path))

    assert expected_ecosystems <= set(report.ecosystems)
    assert all(item.source == "workspace_metadata" for item in report.evidence)
    assert all(item.confidence == "high" for item in report.evidence)


def test_module_detection_uses_workspace_metadata_before_directory_heuristics(tmp_path: Path) -> None:
    from sacas.modules import detect_modules

    root = copy_fixture("node-monorepo", tmp_path)
    (root / "apps" / "web").mkdir(parents=True)
    (root / "apps" / "web" / "package.json").write_text(
        '{"name":"web"}', encoding="utf-8"
    )

    modules = detect_modules(root)

    web = next(module for module in modules if module.path == "apps/web")
    assert web.name == "web"
    assert web.source == "workspace_metadata"
    assert web.confidence == "high"


def test_module_detection_falls_back_to_deterministic_directory_heuristics(tmp_path: Path) -> None:
    from sacas.modules import detect_modules

    root = tmp_path / "repository with spaces"
    (root / "src" / "api").mkdir(parents=True)
    (root / "src" / "web").mkdir(parents=True)

    modules = detect_modules(root)

    assert [(module.name, module.path, module.source, module.confidence) for module in modules] == [
        ("api", "src/api", "directory_heuristic", "low"),
        ("web", "src/web", "directory_heuristic", "low"),
    ]


@pytest.mark.parametrize(
    ("fixture", "expected_name"),
    [
        ("python-service", "python-service"),
        ("dotnet-monolith", "App"),
        ("rust-workspace", "rust-workspace"),
        ("mixed-repo", "mixed-repo"),
    ],
)
def test_build_metadata_creates_high_confidence_module(tmp_path: Path, fixture: str, expected_name: str) -> None:
    from sacas.modules import detect_modules

    modules = detect_modules(copy_fixture(fixture, tmp_path))

    assert any(
        module.name == expected_name
        and module.source == "workspace_metadata"
        and module.confidence == "high"
        for module in modules
    )


def test_analysis_is_serializable_deterministic_and_tracks_freshness(tmp_path: Path) -> None:
    from sacas.analysis import analyze_repository, read_analysis, write_analysis

    root = copy_fixture("python-service", tmp_path / "space root")

    first = analyze_repository(root)
    output = root / "Structure" / ".sacas" / "analysis.json"
    write_analysis(output, first)
    first_bytes = output.read_bytes()
    second = analyze_repository(root)
    write_analysis(output, second)

    loaded = read_analysis(output)
    assert output.read_bytes() == first_bytes
    assert loaded.to_dict() == first.to_dict()
    assert first.freshness.status == "fresh"
    assert first.freshness.fingerprint == second.freshness.fingerprint


def test_analysis_detects_changed_metadata_as_stale(tmp_path: Path) -> None:
    from sacas.analysis import analyze_repository

    root = copy_fixture("python-service", tmp_path)
    first = analyze_repository(root)
    (root / "pyproject.toml").write_text("[project]\nname = 'changed'\n", encoding="utf-8")

    assert first.freshness.is_current(root) is False


def test_analysis_detects_changed_nested_module_metadata_as_stale(tmp_path: Path) -> None:
    from sacas.analysis import analyze_repository

    root = copy_fixture("node-monorepo", tmp_path)
    package = root / "apps" / "web" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"name":"web","version":"1"}', encoding="utf-8")
    analysis = analyze_repository(root)
    package.write_text('{"name":"web","version":"2"}', encoding="utf-8")

    assert "apps/web/package.json" in analysis.freshness.paths
    assert analysis.freshness.is_current(root) is False


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_analysis_detects_added_or_removed_module_descriptor_as_stale(
    tmp_path: Path, operation: str
) -> None:
    from sacas.analysis import analyze_repository

    root = copy_fixture("node-monorepo", tmp_path)
    package = root / "apps" / "web" / "package.json"
    package.parent.mkdir(parents=True)
    if operation == "remove":
        package.write_text('{"name":"web"}', encoding="utf-8")
    analysis = analyze_repository(root)
    if operation == "add":
        package.write_text('{"name":"web"}', encoding="utf-8")
    else:
        package.unlink()

    assert analysis.freshness.is_current(root) is False


def test_analysis_detects_later_creation_of_previously_absent_module_container(tmp_path: Path) -> None:
    from sacas.analysis import analyze_repository

    root = copy_fixture("python-service", tmp_path)
    analysis = analyze_repository(root)
    package = root / "apps" / "web" / "package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{"name":"web"}', encoding="utf-8")

    assert analysis.freshness.is_current(root) is False


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_analysis_detects_heuristic_module_topology_changes(tmp_path: Path, operation: str) -> None:
    from sacas.analysis import analyze_repository

    root = tmp_path / "heuristic-repository"
    child = root / "src" / "api"
    if operation == "remove":
        child.mkdir(parents=True)
    else:
        root.mkdir()
    analysis = analyze_repository(root)
    if operation == "add":
        child.mkdir(parents=True)
    else:
        child.rmdir()

    assert analysis.freshness.is_current(root) is False


@pytest.mark.parametrize("marker", ["package.json", "pyproject.toml", "App.csproj", "Workspace.sln"])
@pytest.mark.parametrize("operation", ["add", "remove"])
def test_analysis_detects_root_marker_creation_or_removal(
    tmp_path: Path, marker: str, operation: str
) -> None:
    from sacas.analysis import analyze_repository

    root = tmp_path / "empty-repository"
    root.mkdir()
    descriptor = root / marker
    if operation == "remove":
        descriptor.write_text("initial", encoding="utf-8")
    analysis = analyze_repository(root)
    if operation == "add":
        descriptor.write_text("created", encoding="utf-8")
    else:
        descriptor.unlink()

    assert analysis.freshness.is_current(root) is False
