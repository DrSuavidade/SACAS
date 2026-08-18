"""Lightweight, deterministic repository metadata detection.

Only well-known local metadata is interpreted here.  Unknown formats deliberately
fall through to directory heuristics in :mod:`sacas.modules`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Evidence:
    ecosystem: str
    path: str
    source: str = "workspace_metadata"
    confidence: str = "high"

    def to_dict(self) -> dict[str, str]:
        return {
            "ecosystem": self.ecosystem,
            "path": self.path,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class RepositoryEvidence:
    root: Path
    evidence: tuple[Evidence, ...]

    @property
    def ecosystems(self) -> tuple[str, ...]:
        return tuple(sorted({item.ecosystem for item in self.evidence}))

    @property
    def metadata_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / item.path for item in self.evidence)


def collect_repository_evidence(root: Path) -> RepositoryEvidence:
    """Return local workspace/build evidence with stable ordering.

    The detector is intentionally shallow: it records metadata files, rather
    than attempting to resolve dependencies or invoke build tools.
    """
    root = root.resolve()
    found: list[Evidence] = []

    def add(ecosystem: str, relative: Path) -> None:
        found.append(Evidence(ecosystem, relative.as_posix()))

    package = root / "package.json"
    if package.is_file():
        add("npm", Path("package.json"))
        if _package_has_next(package):
            add("nextjs", Path("package.json"))
    for filename, ecosystem in (
        ("pnpm-workspace.yaml", "pnpm"),
        ("pnpm-workspace.yml", "pnpm"),
        ("nx.json", "nx"),
        ("turbo.json", "turbo"),
        ("Cargo.toml", "cargo"),
        ("go.mod", "go"),
        ("docker-compose.yml", "docker-compose"),
        ("docker-compose.yaml", "docker-compose"),
        ("compose.yml", "docker-compose"),
        ("compose.yaml", "docker-compose"),
        ("pom.xml", "maven"),
        ("build.gradle", "gradle"),
        ("build.gradle.kts", "gradle"),
        ("pyproject.toml", "python"),
    ):
        if (root / filename).is_file():
            add(ecosystem, Path(filename))
    for project in sorted(root.glob("*.csproj")):
        add("dotnet", project.relative_to(root))
    for solution in sorted(root.glob("*.sln")):
        add("dotnet", solution.relative_to(root))

    unique = {(item.ecosystem, item.path): item for item in found}
    return RepositoryEvidence(root, tuple(unique[key] for key in sorted(unique)))


def _package_has_next(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    sections = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
    return any(isinstance(data.get(section), dict) and "next" in data[section] for section in sections)
