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
        ) or (sacas_root == "." and _is_root_sacas_generated(relative)):
            continue
        try:
            if path.stat().st_mtime_ns > graph_time:
                return True
        except OSError:
            continue
    return False


def _is_root_sacas_generated(relative: Path) -> bool:
    """Recognize generated root-level SACAS state without hiding source files."""
    generated_files = {
        "ROUTER.md",
        "map/SYSTEM.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        ".aiignore",
        ".claudeignore",
        ".cursorignore",
        ".geminiignore",
        ".cursor/rules/sacas.mdc",
        ".github/copilot-instructions.md",
    }
    return relative.as_posix() in generated_files or relative.is_relative_to(Path("tasks/current"))


@dataclass(frozen=True)
class GraphQueryNode:
    id: str
    label: str | None
    path: str | None
    line: int | None
    node_type: str | None
    community: str | None

@dataclass(frozen=True)
class GraphQueryEdge:
    source: str
    target: str
    relation: str
    confidence: str | None = None
    provenance: str | None = None

@dataclass(frozen=True)
class GraphifyQueryResult:
    status: str
    nodes: tuple[GraphQueryNode, ...]
    edges: tuple[GraphQueryEdge, ...]
    raw_output: str
    paths: tuple[str, ...] = ()
    graph_snapshot_hash: str = ""
    query_id: str = ""



class GraphifyAdapter:
    """A verified interface to the external Graphify package."""

    API_VERSION_FLOOR = "0.9.44"

    def __init__(self, repository_root: Path, sacas_root: Path):
        self.repository_root = repository_root
        self.sacas_root = sacas_root

    @classmethod
    def get_installed_version(cls) -> str | None:
        """Get the installed graphifyy package version."""
        try:
            import importlib.metadata
            return importlib.metadata.version("graphifyy")
        except Exception:
            return None

    def verify_capabilities(self, required: list[str]) -> bool:
        """Verify version is >= floor and required commands exist in help text."""
        version_str = self.get_installed_version()
        if not version_str:
            return False

        def parse_ver(v_str: str) -> tuple[int, ...]:
            try:
                parts = []
                for x in v_str.split("."):
                    digits = "".join(ch for ch in x if ch.isdigit())
                    if digits:
                        parts.append(int(digits))
                return tuple(parts)
            except Exception:
                return (0, 0, 0)

        v_parsed = parse_ver(version_str)
        floor_parsed = parse_ver(self.API_VERSION_FLOOR)
        if v_parsed < floor_parsed:
            return False

        try:
            completed = subprocess.run(["graphify", "--help"], capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                return False
            help_text = completed.stdout
            for cmd in required:
                if cmd not in help_text:
                    return False
        except OSError:
            return False

        return True

    def extract_code_only(self, target_path: Path) -> bool:
        """Execute headless code-only extraction locally."""
        cmd = ("graphify", "extract", str(target_path.resolve()), "--code-only", "--no-viz")
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return completed.returncode == 0
        except OSError:
            return False

    def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None) -> GraphifyQueryResult | None:
        """Query Graphify and return isolated parsed paths."""
        if not graph_path.is_file():
            return None
        cmd = ["graphify", "query", goal, "--graph", str(graph_path.resolve())]
        if token_budget is not None:
            cmd += ["--budget", str(token_budget)]
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                return None
            return self._parse_query_output(completed.stdout)
        except OSError:
            return None

    def _parse_query_output(self, raw_output: str) -> GraphifyQueryResult:
        """Parse CLI query output into structured nodes and edges."""
        import re
        nodes = []
        edges = []
        paths = []
        has_nodes = False

        for line in raw_output.splitlines():
            line = line.strip()
            if line.startswith("NODE "):
                has_nodes = True
                parts = line.split(" ", 2)
                if len(parts) >= 2:
                    node_id = parts[1]
                    attrs_str = parts[2] if len(parts) > 2 else ""
                    
                    attrs = {}
                    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|(\S+))', attrs_str):
                        k = m.group(1)
                        v = m.group(2) or m.group(3)
                        if v == "None":
                            v = None
                        attrs[k] = v
                    
                    path = attrs.get("path") or attrs.get("src")
                    if path and path != "None":
                        paths.append(path)
                    
                    # Parse line from 'loc' attribute (e.g., 'L1' -> 1)
                    line_val = None
                    loc_attr = attrs.get("loc")
                    if loc_attr and loc_attr.startswith("L"):
                        try:
                            line_val = int(loc_attr[1:])
                        except ValueError:
                            pass
                    # Fallback to 'line' attribute
                    if line_val is None and attrs.get("line"):
                        try:
                            line_val = int(attrs["line"])
                        except ValueError:
                            pass
                    
                    # Use node_id as label if no explicit label attribute
                    label = attrs.get("label") or node_id
                    
                    nodes.append(GraphQueryNode(
                        id=node_id,
                        label=label,
                        path=path,
                        line=line_val,
                        node_type=attrs.get("node_type") or attrs.get("type"),
                        community=attrs.get("community")
                    ))
            elif line.startswith("EDGE "):
                parts = line.split(" ", 3)
                if len(parts) >= 3:
                    source = parts[1]
                    target = parts[2]
                    attrs_str = parts[3] if len(parts) > 3 else ""
                    
                    attrs = {}
                    for m in re.finditer(r'(\w+)\s*=\s*(?:"([^"]*)"|(\S+))', attrs_str):
                        k = m.group(1)
                        v = m.group(2) or m.group(3)
                        if v == "None":
                            v = None
                        attrs[k] = v
                        
                    edges.append(GraphQueryEdge(
                        source=source,
                        target=target,
                        relation=attrs.get("relation") or attrs.get("type") or "calls",
                        confidence=attrs.get("confidence"),
                        provenance=attrs.get("provenance")
                    ))

        if not has_nodes:
            if "No matching nodes found" in raw_output or not raw_output.strip():
                status = "no_matches"
            else:
                status = "parse_failure"
        else:
            status = "success"

        # Compute graph snapshot hash from the graph.json file
        graph_path = Path(self.repository_root) / "graphify-out" / "graph.json"
        graph_snapshot_hash = ""
        if graph_path.is_file():
            try:
                raw = graph_path.read_bytes()
                graph_snapshot_hash = hashlib.sha256(raw).hexdigest()
            except OSError:
                pass
        
        # Generate a query ID
        import uuid
        query_id = str(uuid.uuid4())[:8]
        
        return GraphifyQueryResult(
            status=status,
            nodes=tuple(nodes),
            edges=tuple(edges),
            raw_output=raw_output,
            paths=tuple(dict.fromkeys(paths)),
            graph_snapshot_hash=graph_snapshot_hash,
            query_id=query_id
        )

    def validate_query_contract(self, result: GraphifyQueryResult) -> bool:
        """Validate parsed query output conforms to basic expectations."""
        if result.status == "parse_failure":
            import sys
            print("WARNING: Graphify output parsing failed. Check if CLI output contract changed.", file=sys.stderr)
            return False
        return True


class GraphCapabilities:
    def __init__(self, query: bool, neighbors: bool, communities: bool, symbol_locations: bool):
        self.query = query
        self.neighbors = neighbors
        self.communities = communities
        self.symbol_locations = symbol_locations


class GraphifyProvider:
    capabilities: GraphCapabilities

    def verify_capabilities(self, required: set[str]) -> bool:
        raise NotImplementedError

    def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None) -> GraphifyQueryResult | None:
        raise NotImplementedError

    def validate_query_contract(self, result: GraphifyQueryResult) -> bool:
        raise NotImplementedError

    def neighbors(self, path: str) -> list[tuple[str, str, str]]:
        raise NotImplementedError

    def communities(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        raise NotImplementedError

    def locate_symbol(self, file_path: str, symbol_name: str) -> tuple[int, int] | None:
        raise NotImplementedError


class CliGraphifyProvider(GraphifyProvider):
    def __init__(self, repository_root: Path, sacas_root: Path):
        self.repository_root = repository_root
        self.sacas_root = sacas_root
        self.adapter = GraphifyAdapter(repository_root, sacas_root)
        self.capabilities = GraphCapabilities(
            query=True,
            neighbors=True,
            communities=True,
            symbol_locations=False
        )

    def verify_capabilities(self, required: set[str]) -> bool:
        cli_cmds = []
        for req in required:
            if req == "query":
                cli_cmds.append("query")
            elif req == "symbol_locations":
                return False
        if cli_cmds and not self.adapter.verify_capabilities(cli_cmds):
            return False
        for req in required:
            if not getattr(self.capabilities, req, False):
                return False
        return True

    def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None) -> GraphifyQueryResult | None:
        return self.adapter.query(goal, graph_path, token_budget=token_budget)

    def validate_query_contract(self, result: GraphifyQueryResult) -> bool:
        return self.adapter.validate_query_contract(result)

    def neighbors(self, path: str) -> list[tuple[str, str, str]]:
        manifest_path = self.sacas_root / ".sacas" / "graphify.json"
        if manifest_path.is_file():
            try:
                evidence = read_graphify_manifest(manifest_path)
                return [edge for edge in evidence.edges if edge[0] == path or edge[1] == path]
            except Exception:
                pass
        return []

    def communities(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        manifest_path = self.sacas_root / ".sacas" / "graphify.json"
        if manifest_path.is_file():
            try:
                evidence = read_graphify_manifest(manifest_path)
                return evidence.communities
            except Exception:
                pass
        return ()

    def locate_symbol(self, file_path: str, symbol_name: str) -> tuple[int, int] | None:
        return None


class JsonGraphifyProvider(GraphifyProvider):
    def __init__(self, graph_path: Path):
        self.graph_path = graph_path
        self.capabilities = GraphCapabilities(
            query=False,
            neighbors=True,
            communities=True,
            symbol_locations=False
        )

    def verify_capabilities(self, required: set[str]) -> bool:
        if not self.graph_path.is_file():
            return False
        for req in required:
            if not getattr(self.capabilities, req, False):
                return False
        return True

    def query(self, goal: str, graph_path: Path, *, token_budget: int | None = None) -> GraphifyQueryResult | None:
        if not self.graph_path.is_file():
            return None
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            paths = []
            nodes_list = []
            for node in data.get("nodes", []):
                p = node.get("path") or node.get("id")
                if p and any(part.lower() in goal.lower() for part in p.split("/")):
                    paths.append(p)
                line_val = None
                if node.get("line"):
                    try:
                        line_val = int(node["line"])
                    except ValueError:
                        pass
                nodes_list.append(GraphQueryNode(
                    id=node.get("id", ""),
                    label=node.get("label"),
                    path=p,
                    line=line_val,
                    node_type=node.get("type") or node.get("node_type"),
                    community=node.get("community")
                ))
            edges_list = []
            for edge in data.get("edges", []):
                edges_list.append(GraphQueryEdge(
                    source=edge.get("source", ""),
                    target=edge.get("target", ""),
                    relation=edge.get("relation") or edge.get("type") or "calls",
                    confidence=edge.get("confidence") or edge.get("provenance")
                ))
            return GraphifyQueryResult(
                status="success",
                nodes=tuple(nodes_list),
                edges=tuple(edges_list),
                raw_output=json.dumps(data),
                paths=tuple(dict.fromkeys(paths))
            )
        except Exception:
            return None

    def validate_query_contract(self, result: GraphifyQueryResult) -> bool:
        return result.status != "parse_failure"

    def neighbors(self, path: str) -> list[tuple[str, str, str]]:
        if not self.graph_path.is_file():
            return []
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            result = []
            for edge in data.get("edges", []):
                source = edge.get("source")
                target = edge.get("target")
                kind = edge.get("type") or edge.get("relationship") or "related"
                if source == path or target == path:
                    result.append((source, target, kind))
            return result
        except Exception:
            return []

    def communities(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        if not self.graph_path.is_file():
            return ()
        try:
            data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            grouped = {}
            for node in data.get("nodes", []):
                comm = node.get("community")
                path = node.get("path") or node.get("id")
                if comm and path:
                    grouped.setdefault(comm, set()).add(path)
            return tuple((name, tuple(sorted(paths))) for name, paths in sorted(grouped.items()))
        except Exception:
            return ()

    def locate_symbol(self, file_path: str, symbol_name: str) -> tuple[int, int] | None:
        return None


def get_graphify_provider(installation: Installation, required: set[str] | None = None, preferred: str = "auto") -> GraphifyProvider:
    if required is None:
        required = set()
    cli_provider = CliGraphifyProvider(installation.repository_root, installation.sacas_root)
    json_path = installation.repository_root / "graphify-out" / "graph.json"
    json_provider = JsonGraphifyProvider(json_path)

    if preferred == "cli":
        if cli_provider.verify_capabilities(required):
            return cli_provider
        if json_provider.verify_capabilities(required):
            return json_provider
    elif preferred == "json":
        if json_provider.verify_capabilities(required):
            return json_provider
        if cli_provider.verify_capabilities(required):
            return cli_provider
    else:  # auto
        if not required or required.issubset({"neighbors", "communities"}):
            if json_provider.verify_capabilities(required):
                return json_provider
        if cli_provider.verify_capabilities(required):
            return cli_provider
        if json_provider.verify_capabilities(required):
            return json_provider
    return json_provider if json_path.is_file() else cli_provider


