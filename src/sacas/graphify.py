"""Optional, read-mostly integration with Graphify output.

SACAS deliberately does not parse source code to fabricate a graph.  It either
consumes ``graphify-out/graph.json`` or asks Graphify itself to produce it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from pathlib import PureWindowsPath
import subprocess
from typing import Any

from .io import write_json_atomic


GraphifyRunner = Callable[[tuple[str, ...]], int | str | None]
_RUNNABLE_MODES = frozenset({"code-only", "semantic"})


@dataclass(frozen=True, slots=True)
class GraphifyEvidence:
    """A normalized snapshot of Graphify's externally-produced graph."""

    output: str
    status: str
    provenance: str
    freshness: str
    content_hash: str
    communities: tuple[tuple[str, tuple[str, ...]], ...] = ()
    nodes: tuple[tuple[str, str], ...] = ()
    edges: tuple[tuple[str, str, str], ...] = ()
    warning: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "output": self.output,
            "status": self.status,
            "provenance": self.provenance,
            "freshness": self.freshness,
            "content_hash": self.content_hash,
            "communities": [[name, list(paths)] for name, paths in self.communities],
            "nodes": [list(node) for node in self.nodes],
            "edges": [list(edge) for edge in self.edges],
            "warning": self.warning,
        }


def collect_graphify(
    root: Path | str,
    *,
    mode: str,
    output: str = "graphify-out",
    sacas_root: str = "Structure",
    runner: GraphifyRunner | None = None,
) -> GraphifyEvidence:
    """Collect optional Graphify evidence, never silently enabling semantics."""
    root_path = Path(root).resolve()
    output = repository_relative_path(root_path, output)
    sacas_root = repository_relative_path(root_path, sacas_root)
    if output == ".":
        raise ValueError("Graphify output must not be the repository root")
    if mode == "off":
        return _empty(root_path, output, status="disabled", provenance="disabled")
    if mode not in {"existing", *_RUNNABLE_MODES}:
        raise ValueError(f"Unsupported Graphify mode: {mode}")
    if mode in _RUNNABLE_MODES and output != "graphify-out":
        raise ValueError("Runnable Graphify modes do not support a custom Graphify output")
    if mode in _RUNNABLE_MODES:
        command = ("graphify", "extract", str(root_path), "--no-viz")
        if mode == "code-only":
            command += ("--code-only",)
        result = _run(command, runner)
        if result != 0:
            return _empty(
                root_path,
                output,
                status="unavailable",
                provenance=f"graphify_{mode}",
                warning=f"Graphify {mode} execution failed with exit code {result}",
            )
    graph_path = root_path / output / "graph.json"
    if not graph_path.is_file():
        return _empty(
            root_path,
            output,
            status="unavailable",
            provenance=f"graphify_{mode}",
            warning="Graphify graph.json is absent",
        )
    try:
        raw = graph_path.read_bytes()
        graph = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return _empty(
            root_path,
            output,
            status="unavailable",
            provenance=f"graphify_{mode}",
            warning="Graphify graph.json is unreadable",
        )
    if not isinstance(graph, dict):
        return _empty(
            root_path,
            output,
            status="unavailable",
            provenance=f"graphify_{mode}",
            warning="Graphify graph.json is not an object",
        )
    nodes = _nodes(graph.get("nodes"))
    edges = _edges(graph.get("edges"))
    status = "stale" if _has_newer_source(root_path, graph_path, output, sacas_root) else "fresh"
    return GraphifyEvidence(
        output=output,
        status=status,
        provenance=f"graphify_{mode}",
        freshness=status,
        content_hash=hashlib.sha256(raw).hexdigest(),
        communities=_communities(graph.get("nodes")),
        nodes=nodes,
        edges=edges,
        warning=_warning(mode, status),
    )


def safe_query(
    output: Path | str, query: str, *, runner: GraphifyRunner | None = None
) -> str | None:
    """Run Graphify's query command if available; failures remain non-fatal."""
    output_path = Path(output)
    if not (output_path / "graph.json").is_file():
        return None
    command = ("graphify", "query", query, "--graph", str(output_path / "graph.json"))
    result = _run(command, runner)
    return result if isinstance(result, str) else None


def repository_relative_path(root: Path | str, value: str) -> str:
    """Validate a user path is relative and remains within *root*."""
    if not isinstance(value, str) or not value:
        raise ValueError("Path must be a relative path inside the repository")
    candidate = Path(value)
    if candidate.is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("Path must be a relative path inside the repository")
    root_path = Path(root).resolve()
    resolved = (root_path / candidate).resolve()
    try:
        relative = resolved.relative_to(root_path)
    except ValueError as error:
        raise ValueError("Path must be a relative path inside the repository") from error
    return relative.as_posix()


def write_graphify_manifest(path: Path, evidence: GraphifyEvidence) -> None:
    """Persist the optional graph snapshot separately from human-authored maps."""
    write_json_atomic(path, evidence.to_dict())


def read_graphify_manifest(path: Path) -> GraphifyEvidence:
    """Load one graph snapshot, rejecting malformed machine state."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Graphify manifest must be an object")
    try:
        communities = tuple((name, tuple(paths)) for name, paths in data.get("communities", []))
        nodes = tuple(tuple(node) for node in data.get("nodes", []))
        edges = tuple(tuple(edge) for edge in data.get("edges", []))
        return GraphifyEvidence(
            output=data["output"], status=data["status"], provenance=data["provenance"],
            freshness=data["freshness"], content_hash=data["content_hash"],
            communities=communities, nodes=nodes, edges=edges, warning=data.get("warning", ""),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Invalid Graphify manifest") from error


def _run(command: tuple[str, ...], runner: GraphifyRunner | None) -> int | str:
    if runner is not None:
        try:
            result = runner(command)
        except (OSError, subprocess.SubprocessError):
            return 127
        return 0 if result is None else result
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError:
        return 127
    return completed.stdout.strip() if completed.returncode == 0 and completed.stdout else completed.returncode


def _empty(root: Path, output: str, *, status: str, provenance: str, warning: str = "") -> GraphifyEvidence:
    return GraphifyEvidence(str(root / output), status, provenance, status, "", warning=warning)


def _warning(mode: str, status: str) -> str:
    warnings: list[str] = []
    if mode == "semantic":
        warnings.append("Semantic Graphify extraction was explicitly selected")
    if status == "stale":
        warnings.append("Graphify graph.json is older than repository source")
    return "; ".join(warnings)


def _nodes(raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        return ()
    found: list[tuple[str, str]] = []
    for node in raw:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            path = node.get("path", node["id"])
            if isinstance(path, str):
                found.append((node["id"], path))
    return tuple(sorted(set(found)))


def _edges(raw: object) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(raw, list):
        return ()
    found: list[tuple[str, str, str]] = []
    for edge in raw:
        if not isinstance(edge, dict):
            continue
        source, target = edge.get("source"), edge.get("target")
        kind = edge.get("type", edge.get("relationship", "related"))
        if all(isinstance(item, str) for item in (source, target, kind)):
            found.append((source, target, kind))
    return tuple(sorted(set(found)))


def _communities(raw: object) -> tuple[tuple[str, tuple[str, ...]], ...]:
    grouped: dict[str, set[str]] = {}
    if isinstance(raw, list):
        for node in raw:
            if not isinstance(node, dict):
                continue
            community, path = node.get("community"), node.get("path", node.get("id"))
            if isinstance(community, str) and isinstance(path, str):
                grouped.setdefault(community, set()).add(path)
    return tuple((name, tuple(sorted(paths))) for name, paths in sorted(grouped.items()))


def _has_newer_source(root: Path, graph_path: Path, output: str, sacas_root: str) -> bool:
    graph_time = graph_path.stat().st_mtime_ns
    ignored = {".git", ".sacas", "__pycache__"}
    generated_roots = (Path(output),) if sacas_root == "." else (Path(output), Path(sacas_root))
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts) or any(
            relative.is_relative_to(generated_root) for generated_root in generated_roots
        ):
            continue
        try:
            if path.stat().st_mtime_ns > graph_time:
                return True
        except OSError:
            continue
    return False
