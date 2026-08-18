"""Deterministic module discovery from metadata, then bounded heuristics."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


DEFAULT_MODULE_CONTAINERS = ("apps", "packages")


@dataclass(frozen=True, slots=True)
class Module:
    name: str
    path: str
    source: str
    confidence: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "path": self.path,
            "source": self.source,
            "confidence": self.confidence,
        }


def detect_modules(root: Path) -> tuple[Module, ...]:
    """Find package modules, otherwise first-level conventional directories."""
    root = root.resolve()
    metadata_modules = _package_modules(root)
    if metadata_modules:
        return tuple(sorted(metadata_modules, key=lambda item: (item.path, item.name)))
    return tuple(_directory_heuristics(root))


def module_metadata_paths(root: Path) -> tuple[str, ...]:
    """Return every module descriptor that contributes to metadata discovery."""
    root = root.resolve()
    paths: list[Path] = []
    for container in workspace_containers(root):
        paths.extend(sorted((root / container).glob("*/package.json")))
    for filename in ("pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts"):
        candidate = root / filename
        if candidate.is_file():
            paths.append(candidate)
    paths.extend(sorted(root.glob("*.csproj")))
    return tuple(sorted({path.relative_to(root).as_posix() for path in paths}))


def workspace_containers(root: Path) -> tuple[str, ...]:
    """Return bounded roots from simple declared workspace globs.

    Only ``container/*`` patterns are supported.  Complex or negated globs
    deliberately remain outside this lightweight detector.
    """
    root = root.resolve()
    containers = set(DEFAULT_MODULE_CONTAINERS)
    package = root / "package.json"
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        workspaces = data.get("workspaces", []) if isinstance(data, dict) else []
        if isinstance(workspaces, dict):
            workspaces = workspaces.get("packages", [])
        if isinstance(workspaces, list):
            containers.update(_simple_workspace_container(item) for item in workspaces if isinstance(item, str))
    for filename in ("pnpm-workspace.yaml", "pnpm-workspace.yml"):
        path = root / filename
        if path.is_file():
            for pattern in _pnpm_package_patterns(path):
                containers.add(_simple_workspace_container(pattern))
    return tuple(sorted(container for container in containers if container))


def _simple_workspace_container(pattern: str) -> str | None:
    candidate = pattern.strip().replace("\\", "/")
    parts = candidate.split("/")
    if len(parts) == 2 and parts[1] == "*" and parts[0] and not parts[0].startswith("!"):
        return parts[0]
    return None


def _pnpm_package_patterns(path: Path) -> tuple[str, ...]:
    """Parse only the top-level block-style ``packages:`` YAML sequence."""
    patterns: list[str] = []
    in_packages = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not in_packages:
            if re.match(r"^packages:\s*(?:#.*)?$", line):
                in_packages = True
            continue
        if line and not line[0].isspace():
            break
        match = re.match(r"^  -\s*['\"]?([^'\"\s]+)['\"]?\s*(?:#.*)?$", line)
        if match:
            patterns.append(match.group(1))
    return tuple(patterns)


def _package_modules(root: Path) -> list[Module]:
    modules: dict[str, Module] = {}

    def add(path: Path, name: str | None = None) -> None:
        relative = path.parent.relative_to(root).as_posix() or "."
        modules.setdefault(
            relative,
            Module(name or path.parent.name, relative, "workspace_metadata", "high"),
        )

    for container in workspace_containers(root):
        for package in sorted((root / container).glob("*/package.json")):
            add(package, _package_name(package))
    for filename in ("pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts"):
        path = root / filename
        if path.is_file():
            add(path, root.name)
    for project in sorted(root.glob("*.csproj")):
        add(project, project.stem)
    return list(modules.values())


def _package_name(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("name") if isinstance(data, dict) else None
    return value if isinstance(value, str) and value else None


def _directory_heuristics(root: Path) -> list[Module]:
    modules: list[Module] = []
    for container_name in ("apps", "packages", "services", "src"):
        container = root / container_name
        if not container.is_dir():
            continue
        for child in sorted(path for path in container.iterdir() if path.is_dir() and not path.name.startswith(".")):
            modules.append(Module(child.name, child.relative_to(root).as_posix(), "directory_heuristic", "low"))
    return modules
