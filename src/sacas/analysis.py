"""Serializable repository analysis built entirely from local evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .io import write_json_atomic
from .modules import Module, detect_modules, module_metadata_paths, workspace_containers
from .repository import Evidence, collect_repository_evidence


MODULE_CONTAINERS = ("apps", "packages", "services", "src")
ROOT_MARKERS = (
    "package.json",
    "pnpm-workspace.yaml",
    "pnpm-workspace.yml",
    "nx.json",
    "turbo.json",
    "Cargo.toml",
    "go.mod",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "pyproject.toml",
)


@dataclass(frozen=True, slots=True)
class Freshness:
    fingerprint: str
    paths: tuple[str, ...]
    inventory_roots: tuple[str, ...] = ()
    status: str = "fresh"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "fingerprint": self.fingerprint,
            "paths": list(self.paths),
            "inventory_roots": list(self.inventory_roots),
        }

    def is_current(self, root: Path) -> bool:
        return self.fingerprint == _fingerprint(root.resolve(), self.paths, self.inventory_roots)


@dataclass(frozen=True, slots=True)
class Analysis:
    root: str
    ecosystems: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    modules: tuple[Module, ...]
    freshness: Freshness
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "ecosystems": list(self.ecosystems),
            "evidence": [item.to_dict() for item in self.evidence],
            "modules": [item.to_dict() for item in self.modules],
            "freshness": self.freshness.to_dict(),
        }


def analyze_repository(root: Path) -> Analysis:
    root = root.resolve()
    repository = collect_repository_evidence(root)
    paths = tuple(sorted({item.path for item in repository.evidence} | set(module_metadata_paths(root))))
    # Record every conventional container, even absent ones, so creating a
    # future module cannot leave a prior analysis falsely fresh.
    inventory_roots = tuple(
        dict.fromkeys((*MODULE_CONTAINERS, *workspace_containers(root)))
    )
    return Analysis(
        root=str(root),
        ecosystems=repository.ecosystems,
        evidence=repository.evidence,
        modules=detect_modules(root),
        freshness=Freshness(_fingerprint(root, paths, inventory_roots), paths, inventory_roots),
    )


def write_analysis(path: Path, analysis: Analysis) -> None:
    write_json_atomic(path, analysis.to_dict())


def read_analysis(path: Path) -> Analysis:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported analysis schema version")
    freshness = data["freshness"]
    return Analysis(
        root=data["root"],
        ecosystems=tuple(data["ecosystems"]),
        evidence=tuple(Evidence(**item) for item in data["evidence"]),
        modules=tuple(Module(**item) for item in data["modules"]),
        freshness=Freshness(
            fingerprint=freshness["fingerprint"],
            paths=tuple(freshness["paths"]),
            inventory_roots=tuple(freshness.get("inventory_roots", [])),
            status=freshness["status"],
        ),
        schema_version=data["schema_version"],
    )


def _fingerprint(root: Path, paths: tuple[str, ...], inventory_roots: tuple[str, ...] = ()) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update((root / relative).read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    for inventory_root in inventory_roots:
        container = root / inventory_root
        digest.update(f"@inventory:{inventory_root}".encode("utf-8"))
        digest.update(b"\0")
        if container.is_dir():
            for child in sorted(path for path in container.iterdir() if path.is_dir()):
                relative = child.relative_to(root).as_posix()
                digest.update(relative.encode("utf-8"))
                digest.update(b":package.json=")
                digest.update(b"1" if (child / "package.json").is_file() else b"0")
                digest.update(b"\0")
        else:
            digest.update(b"<missing-container>\0")
    digest.update(b"@root-markers\0")
    for filename in ROOT_MARKERS:
        _digest_marker(digest, root / filename, filename)
    for marker in sorted([*root.glob("*.csproj"), *root.glob("*.sln")]):
        _digest_marker(digest, marker, marker.name)
    return digest.hexdigest()


def _digest_marker(digest: "hashlib._Hash", path: Path, label: str) -> None:
    digest.update(label.encode("utf-8"))
    digest.update(b"=")
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(b"<missing>")
    digest.update(b"\0")
