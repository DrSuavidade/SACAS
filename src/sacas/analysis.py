"""Serializable repository analysis built entirely from local evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from .io import write_json_atomic
from .modules import Module, detect_modules, module_metadata_paths
from .repository import Evidence, collect_repository_evidence


@dataclass(frozen=True, slots=True)
class Freshness:
    fingerprint: str
    paths: tuple[str, ...]
    status: str = "fresh"

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "fingerprint": self.fingerprint, "paths": list(self.paths)}

    def is_current(self, root: Path) -> bool:
        return self.fingerprint == _fingerprint(root.resolve(), self.paths)


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
    return Analysis(
        root=str(root),
        ecosystems=repository.ecosystems,
        evidence=repository.evidence,
        modules=detect_modules(root),
        freshness=Freshness(_fingerprint(root, paths), paths),
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
            fingerprint=freshness["fingerprint"], paths=tuple(freshness["paths"]), status=freshness["status"]
        ),
        schema_version=data["schema_version"],
    )


def _fingerprint(root: Path, paths: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in paths:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update((root / relative).read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()
