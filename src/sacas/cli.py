"""Command-line interface for SACAS."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sacas import __version__
from sacas.graphify import collect_graphify, repository_relative_path, write_graphify_manifest
from sacas.init import initialize
from sacas.io import read_repo_source_bytes
from sacas.map import build_system_map, write_system_map
from sacas.paths import Installation, discover_manifest, resolve_repo_path


def _hash_repo_source(repository_root: Path, path: str) -> str:
    """Hash only a file admitted by the repository source-read boundary."""
    import hashlib
    try:
        return hashlib.sha256(read_repo_source_bytes(repository_root, path)).hexdigest()
    except (ValueError, FileNotFoundError, OSError):
        return ""


def build_parser() -> argparse.ArgumentParser:
    """Build the public SACAS argument parser."""
    parser = argparse.ArgumentParser(
        prog="sacas",
        description="SACAS compiles a coding task and repository into a minimal context pack.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    def add_command(name: str, *, hidden: bool = False, **kwargs) -> argparse.ArgumentParser:
        help_text = kwargs.pop("help", None)
        if hidden:
            help_text = argparse.SUPPRESS
        return subcommands.add_parser(name, help=help_text, **kwargs)

    # --- Agent-facing surface -------------------------------------------------
    init_parser = add_command("init", help="Initialize SACAS in a repository.")
    init_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    init_parser.add_argument("--sacas-root", default="Structure", help="SACAS root relative to repository.")
    init_parser.add_argument("--graphify", choices=("off", "existing", "code-only", "semantic"), default="existing", help="Graphify integration mode.")

    prepare_parser = add_command("prepare", help="Prepare the context pack for a task goal.")
    prepare_parser.add_argument("goal", help="The goal of the task.")
    prepare_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    prepare_parser.add_argument("--criteria", nargs="*", default=(), help="Acceptance criteria.")
    prepare_parser.add_argument("--constraints", nargs="*", default=(), help="Constraints.")
    prepare_parser.add_argument("--verification", nargs="*", default=(), help="Verification instructions.")
    prepare_parser.add_argument("--files", nargs="*", default=(), help="Focus files.")
    prepare_parser.add_argument("--symbols", nargs="*", default=(), help="Focus symbols.")
    prepare_parser.add_argument("--symbol", action="append", default=[], help="Repeatable focus symbol path (file::name).")
    prepare_parser.add_argument("--tests", nargs="*", default=(), help="Focus tests.")
    prepare_parser.add_argument("--rules", nargs="*", default=(), help="Rules to follow.")
    prepare_parser.add_argument("--references", nargs="*", default=(), help="References to follow.")
    prepare_parser.add_argument("--category", choices=("bugfix", "feature", "test", "refactor", "docs", "security", "investigate"), default=None, help="Task type/category.")
    prepare_parser.add_argument("--context-policy", choices=("advisory", "warn", "enforce"), default="advisory", help="Context boundaries policy.")

    add_parser = add_command("add", help="Admit an explicit file, symbol, rule, or reference into context.")
    add_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    add_parser.add_argument("--file", action="append", default=[], help="File path to expand.")
    add_parser.add_argument("--symbol", action="append", default=[], help="Symbol path (file::name) to expand.")
    add_parser.add_argument("--rule", action="append", default=[], help="Rule path to expand.")
    add_parser.add_argument("--reference", action="append", default=[], help="Reference path (or section references/doc.md#heading) to expand.")
    add_parser.add_argument("--reason", default="", help="Audit rationale for this expansion.")
    add_parser.add_argument("--all-candidates", action="store_true", help="Expand all candidates that fit the context budget.")

    explain_parser = add_command("explain", help="Explain context decisions (provenance or current status).")
    explain_parser.add_argument("path", nargs="?", default=None, help="File path or symbol name to query; omit for status.")
    explain_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    explain_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    doctor_parser = add_command("doctor", help="Run diagnostics and validation on the installation.")
    doctor_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    doctor_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    # --- Developer laboratory --------------------------------------------------
    lab_parser = add_command("lab", help="SACAS development laboratory (benchmarks).")
    lab_subcommands = lab_parser.add_subparsers(dest="lab_command", metavar="SUBCOMMAND")

    lab_bench_parser = lab_subcommands.add_parser("benchmark", help="Run SACAS routing and quality benchmarks.")
    lab_bench_parser.add_argument("--root", default=".")
    lab_bench_parser.add_argument("--format", choices=("text", "json"), default="text")

    lab_hist_parser = lab_subcommands.add_parser("histbench", help="Generate and run historical Git benchmarks.")
    lab_hist_parser.add_argument("--root", default=".")
    lab_hist_parser.add_argument("--max-commits", type=int, default=200)
    lab_hist_parser.add_argument("--generate-only", action="store_true")
    lab_hist_parser.add_argument("--output-dir")
    lab_hist_parser.add_argument("--format", choices=("text", "json"), default="text")

    return parser


LEGACY_COMMANDS = (
    "task", "expand", "why", "status", "validate",
    "refresh", "map", "migrate", "benchmark", "histbench",
)


def build_legacy_parser() -> argparse.ArgumentParser:
    """Build the hidden compatibility/internal-command parser."""
    parser = argparse.ArgumentParser(prog="sacas")
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    task_parser = subcommands.add_parser("task")
    task_parser.add_argument("goal", help="The goal of the task.")
    for arg in ("--criteria", "--constraints", "--verification", "--files", "--symbols", "--tests", "--rules", "--references"):
        task_parser.add_argument(arg, nargs="*", default=())
    task_parser.add_argument("--symbol", action="append", default=[])
    task_parser.add_argument("--category", choices=("bugfix", "feature", "test", "refactor", "docs", "security", "investigate"), default=None)
    task_parser.add_argument("--context-policy", choices=("advisory", "warn", "enforce"), default="advisory")
    task_parser.add_argument("--root", default=".")

    expand_parser = subcommands.add_parser("expand")
    expand_parser.add_argument("--root", default=".")
    expand_parser.add_argument("--file", action="append", default=[])
    expand_parser.add_argument("--symbol", action="append", default=[])
    expand_parser.add_argument("--rule", action="append", default=[])
    expand_parser.add_argument("--reference", action="append", default=[])
    expand_parser.add_argument("--reason", default="")
    expand_parser.add_argument("--all-candidates", action="store_true")

    why_parser = subcommands.add_parser("why")
    why_parser.add_argument("path")
    why_parser.add_argument("--root", default=".")

    status_parser = subcommands.add_parser("status")
    status_parser.add_argument("--root", default=".")
    status_parser.add_argument("--format", choices=("text", "json"), default="text")

    validate_parser = subcommands.add_parser("validate")
    validate_parser.add_argument("--root", default=".")
    validate_parser.add_argument("--format", choices=("text", "json"), default="text")

    refresh_parser = subcommands.add_parser("refresh")
    refresh_parser.add_argument("--root", default=".")
    refresh_parser.add_argument("--files", nargs="*", default=())

    map_parser = subcommands.add_parser("map")
    map_parser.add_argument("--root", default=".")
    map_parser.add_argument("--sacas-root", default="Structure")
    map_parser.add_argument("--output", default="graphify-out")
    map_parser.add_argument("--mode", choices=("off", "existing", "code-only", "semantic"), default="existing")

    migrate_parser = subcommands.add_parser("migrate")
    migrate_parser.add_argument("--root", default=".")
    migrate_parser.add_argument("--apply", action="store_true")
    migrate_parser.add_argument("--format", choices=("text", "json"), default="text")

    benchmark_parser = subcommands.add_parser("benchmark")
    benchmark_parser.add_argument("--root", default=".")
    benchmark_parser.add_argument("--format", choices=("text", "json"), default="text")

    histbench_parser = subcommands.add_parser("histbench")
    histbench_parser.add_argument("--root", default=".")
    histbench_parser.add_argument("--max-commits", type=int, default=200)
    histbench_parser.add_argument("--generate-only", action="store_true")
    histbench_parser.add_argument("--output-dir")
    histbench_parser.add_argument("--format", choices=("text", "json"), default="text")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run SACAS and return its process exit code."""
    import sys
    tokens = list(argv) if argv is not None else sys.argv[1:]
    if tokens and tokens[0] in LEGACY_COMMANDS:
        parser = build_legacy_parser()
    else:
        parser = build_parser()
    arguments = parser.parse_args(tokens)
    if arguments.command == "init":
        initialize(arguments.root, sacas_root=arguments.sacas_root, graphify_mode=arguments.graphify)
    elif arguments.command in ("prepare", "task"):
        from sacas.tasks import generate_task

        root = Path(arguments.root).resolve()
        installation = _require_installation(root)

        if arguments.command == "prepare":
            refreshed = _prepare_existing_task(installation, arguments.goal)
            if refreshed is not None:
                return refreshed

        # Merge symbols
        merged_symbols = list(arguments.symbols) + list(arguments.symbol)

        generate_task(
            installation,
            goal=arguments.goal,
            criteria=tuple(arguments.criteria),
            constraints=tuple(arguments.constraints),
            verification=tuple(arguments.verification),
            files=tuple(arguments.files),
            symbols=tuple(merged_symbols),
            tests=tuple(arguments.tests),
            rules=tuple(arguments.rules),
            references=tuple(getattr(arguments, "references", ())),
            category=getattr(arguments, "category", None),
            context_policy=getattr(arguments, "context_policy", "advisory")
        )
    elif arguments.command == "add":
        root = Path(arguments.root).resolve()
        installation = _require_installation(root)
        return expand_context_command(
            installation,
            files=list(arguments.file),
            symbols=list(arguments.symbol),
            rules=list(arguments.rule),
            references=list(arguments.reference),
            reason=arguments.reason,
            all_candidates=arguments.all_candidates
        )
    elif arguments.command == "expand":
        root = Path(arguments.root).resolve()
        installation = _require_installation(root)
        return expand_context_command(
            installation,
            files=list(arguments.file),
            symbols=list(arguments.symbol),
            rules=list(arguments.rule),
            references=list(arguments.reference),
            reason=arguments.reason,
            all_candidates=arguments.all_candidates
        )
    elif arguments.command in ("explain", "why", "status"):
        from sacas.status import print_status_report
        from sacas.provenance import query_why_file

        root = Path(arguments.root).resolve()
        installation = _require_installation(root)
        path = getattr(arguments, "path", None)
        if path:
            lines = query_why_file(installation, path)
            for line in lines:
                print(line)
            return 1 if lines and lines[0].startswith("Canonical task state is corrupt:") else 0
        format_type = getattr(arguments, "format", "text") or "text"
        return print_status_report(installation, format_type=format_type)
    elif arguments.command in ("doctor",):
        root = Path(arguments.root).resolve()
        return doctor_command(root, format_type=getattr(arguments, "format", "text"))
    elif arguments.command == "validate":
        root = Path(arguments.root).resolve()
        from sacas.validate import perform_validation
        return perform_validation(root, format_type=arguments.format)
    elif arguments.command == "refresh":
        from sacas.refresh import refresh_context
        from sacas.task_contract import CanonicalStateError

        root = Path(arguments.root).resolve()
        installation = _require_installation(root)
        try:
            refresh_context(installation, selective_files=tuple(arguments.files))
        except CanonicalStateError as error:
            print(f"Refresh refused: canonical task state is corrupt: {error}")
            return 1
    elif arguments.command == "map":
        root = Path(arguments.root).resolve()
        sacas_root_relative = repository_relative_path(root, arguments.sacas_root)
        output = repository_relative_path(root, arguments.output)
        sacas_root = root / sacas_root_relative
        evidence = collect_graphify(
            root, mode=arguments.mode, output=output, sacas_root=sacas_root_relative
        )
        write_graphify_manifest(sacas_root / ".sacas" / "graphify.json", evidence)
        write_system_map(sacas_root / "map" / "SYSTEM.md", build_system_map(evidence))
    elif arguments.command == "migrate":
        from sacas.migrate import perform_migration
        root = Path(arguments.root).resolve()
        return perform_migration(root, apply=arguments.apply, format_type=arguments.format)
    elif arguments.command == "lab":
        root = Path(arguments.root).resolve()
        installation = _require_installation(root)
        if arguments.lab_command == "benchmark":
            return benchmark_command_dispatch(installation, format_type=arguments.format)
        if arguments.lab_command == "histbench":
            return histbench_command(
                installation,
                max_commits=arguments.max_commits,
                generate_only=arguments.generate_only,
                output_dir=arguments.output_dir,
                format_type=arguments.format
            )
        lab_parser.print_help()
        return 1
    elif arguments.command in ("benchmark", "histbench"):
        root = Path(arguments.root).resolve()
        installation = _require_installation(root)
        if arguments.command == "benchmark":
            return benchmark_command_dispatch(installation, format_type=arguments.format)
        return histbench_command(
            installation,
            max_commits=arguments.max_commits,
            generate_only=arguments.generate_only,
            output_dir=arguments.output_dir,
            format_type=arguments.format
        )
    return 0


def _require_installation(root: Path) -> Installation:
    installation = discover_manifest(root)
    if installation is None:
        raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
    return installation


def _prepare_existing_task(installation: Installation, goal: str | None) -> int | None:
    """Refresh an existing identical task instead of regenerating from scratch."""
    if not goal:
        return None
    from sacas.refresh import refresh_context
    from sacas.active_context import load_active_context
    from sacas.task_contract import CanonicalStateError

    task_dir = installation.sacas_root / "tasks" / "current"
    try:
        manifest = load_active_context(task_dir)
    except CanonicalStateError:
        return None
    if not manifest or manifest.goal != goal:
        return None
    try:
        refresh_context(installation, selective_files=())
    except CanonicalStateError as error:
        print(f"Prepare refused: canonical task state is corrupt: {error}")
        return 1
    return 0


def expand_context_command(
    installation: Installation,
    files: list[str],
    symbols: list[str],
    rules: list[str],
    references: list[str],
    reason: str,
    all_candidates: bool
) -> int:
    from sacas.active_context import (
        load_active_context,
        load_task_state,
        ActiveFileContext,
        ActiveSymbolContext,
        ActiveRuleContext,
        ActiveReferenceContext,
        AdmissionEvent,
        ActiveContextManifest,
    )
    from sacas.tasks import regenerate_task_markdown
    from sacas.io import read_repo_source_bytes, read_repo_text
    from sacas.regions import SymbolRangeResolver, extract_markdown_section, resolve_section_ranges
    import hashlib

    task_dir = installation.sacas_root / "tasks" / "current"
    from sacas.task_contract import CanonicalStateError
    try:
        manifest, contract = load_task_state(task_dir)
    except CanonicalStateError as error:
        print(f"Expansion refused: canonical task state is corrupt: {error}")
        return 1
    if not manifest:
        print("No active SACAS task found.")
        return 1

    # Expansion is an admission boundary.  Do all filesystem and selector
    # checks before constructing anything that can be published or enforced.
    def admitted_source(path: str) -> tuple[str, str]:
        normalized = resolve_repo_path(installation.repository_root, path)
        raw = read_repo_source_bytes(installation.repository_root, normalized)
        return normalized, hashlib.sha256(raw).hexdigest()

    def structure_source(path: str) -> tuple[str, str, str]:
        requested = path.replace("\\", "/")
        root_relative = installation.sacas_root.relative_to(installation.repository_root).as_posix()
        if requested != root_relative and not requested.startswith(f"{root_relative}/"):
            requested = f"{root_relative}/{requested}"
        normalized, digest = admitted_source(requested)
        if normalized != root_relative and not normalized.startswith(f"{root_relative}/"):
            raise ValueError("Rule/reference must remain inside the SACAS root")
        return requested, normalized, digest

    try:
        explicit_files = [admitted_source(path) for path in files]
        explicit_symbols: list[tuple[str, str, str, object, str]] = []
        for requested in symbols:
            if "::" not in requested:
                raise ValueError(f"Symbol '{requested}' must use file::name format")
            path, symbol = requested.split("::", 1)
            if not path or not symbol:
                raise ValueError(f"Symbol '{requested}' must use file::name format")
            normalized, digest = admitted_source(path)
            resolved = SymbolRangeResolver.resolve(installation, normalized, symbol)
            if resolved is None:
                raise ValueError(f"Symbol '{normalized}::{symbol}' does not resolve")
            explicit_symbols.append((requested, normalized, symbol, resolved, digest))

        explicit_rules = [structure_source(path) for path in rules]
        explicit_refs: list[tuple[str, dict[str, object], str]] = []
        for requested in references:
            path, separator, anchor = requested.partition("#")
            _requested, normalized, digest = structure_source(path)
            if separator:
                if not anchor:
                    raise ValueError(f"Reference '{requested}' has an empty heading")
                heading_path = [anchor.replace("-", " ")]
                content = read_repo_text(installation.repository_root, normalized)
                extract_markdown_section(content, heading_path, strict=True)
                selection: dict[str, object] = resolve_section_ranges(
                    installation.repository_root,
                    normalized,
                    {"mode": "sections", "sections": [{"heading_path": heading_path}]},
                    content=content,
                )
            else:
                selection = {"mode": "full"}
            explicit_refs.append((normalized, selection, digest))

        candidates: list[tuple[dict[str, object], str, str, dict[str, object] | None]] = []
        if all_candidates:
            candidates_path = task_dir / "candidates.json"
            if candidates_path.is_file():
                raw_candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
                if not isinstance(raw_candidates, dict) or raw_candidates.get("task_id") != manifest.task_id:
                    raise ValueError("Candidates do not belong to the active task")
                candidate_graph_hash = raw_candidates.get("graph_snapshot_hash")
                if candidate_graph_hash is not None:
                    if not isinstance(candidate_graph_hash, str):
                        raise ValueError("Candidates graph hash is invalid")
                    if candidate_graph_hash != manifest.graph_snapshot_hash:
                        raise ValueError("Candidates are stale for the active graph snapshot")
                raw_list = raw_candidates.get("candidates")
                if not isinstance(raw_list, list):
                    raise ValueError("Candidates payload is malformed")
                for candidate in raw_list:
                    if not isinstance(candidate, dict) or not isinstance(candidate.get("path"), str):
                        raise ValueError("Candidate entry is malformed")
                    for field in (
                        "source", "reason", "relation", "graph_snapshot_hash", "graph_query_id",
                        "graph_node_id", "graph_edge_source_id", "graph_edge_target_id", "graph_edge_kind",
                    ):
                        if field in candidate and not isinstance(candidate[field], str):
                            raise ValueError(f"Candidate field '{field}' is malformed")
                    if "confidence" in candidate and not isinstance(candidate["confidence"], str):
                        raise ValueError("Candidate field 'confidence' is malformed")
                    if (
                        manifest.graph_snapshot_hash
                        and "graph_snapshot_hash" not in candidate
                    ):
                        raise ValueError("Candidate is missing its graph snapshot hash")
                    if (
                        "graph_snapshot_hash" in candidate
                        and candidate["graph_snapshot_hash"] != manifest.graph_snapshot_hash
                    ):
                        raise ValueError("Candidate is stale for the active graph snapshot")
                    path, digest = admitted_source(candidate["path"])
                    label = candidate.get("node_label")
                    line = candidate.get("node_line")
                    if label is not None and (not isinstance(label, str) or not label):
                        raise ValueError(f"Candidate selector is invalid for {path}")
                    if line is not None and (not isinstance(line, int) or line < 1):
                        raise ValueError(f"Candidate selector is invalid for {path}")
                    selector = None
                    if label is not None or line is not None:
                        resolved_node = SymbolRangeResolver.resolve_node_range(
                            installation, path, label, line,
                        )
                        if resolved_node is None:
                            raise ValueError(f"Candidate selector is unresolved for {path}")
                        selector, _selector_reason = resolved_node
                    candidates.append((candidate, path, digest, selector))
    except (ValueError, LookupError, FileNotFoundError, OSError, json.JSONDecodeError) as error:
        print(f"Expansion refused: {error}")
        return 1

    new_files = list(manifest.files)
    new_rules = list(manifest.rules)
    new_refs = list(manifest.references)
    new_events = list(manifest.events)

    # 1. Expand validated candidates.
    for cand, path, f_hash, selector in candidates:
                    if path in [f.path for f in new_files]:
                        continue
                    conf_map = {"high": 1.0, "medium": 0.7, "low": 0.4}
                    cand_conf = cand.get("confidence", "high")
                    conf_float = conf_map.get(cand_conf, 0.7)
                    ev = [f"candidate_{cand.get('source', 'graphify')}"]
                    if cand.get("relation"):
                        ev.append(f"{cand['relation']}_relation")
                    is_heuristic = cand.get("source") == "heuristic"

                    new_file_ctx = ActiveFileContext(
                        path=path,
                        selection=selector if selector is not None else {"mode": "full"},
                        source=cand.get("source", "graphify"),
                        ranking_score=conf_float,
                        confidence=conf_float,
                        evidence=tuple(ev),
                        relation=cand.get("relation"),
                        trigger="expansion",
                        git_revision=manifest.git_revision,
                        reason=cand.get("reason", "Expanded candidate"),
                        hash=f_hash
                    )

                    # Dry-run check budget
                    from sacas.budget import calculate_manifest_tokens
                    temp_manifest = ActiveContextManifest(
                        task_id=manifest.task_id, task_contract_hash=manifest.task_contract_hash,
                        git_revision=manifest.git_revision, files=tuple(new_files + [new_file_ctx]),
                        rules=tuple(new_rules), references=tuple(new_refs), events=tuple(new_events),
                        tests=manifest.tests, schema_version=manifest.schema_version,
                        goal=manifest.goal, category=manifest.category
                    )
                    breakdown = calculate_manifest_tokens(installation, temp_manifest)
                    if manifest.budget is None or breakdown.used <= manifest.budget.limit:
                        new_files.append(new_file_ctx)
                        new_events.append(AdmissionEvent(
                            id=f"evt-exp-{len(new_events):03d}",
                            target=path,
                            action="admit",
                            source=cand.get("source", "graphify"),
                            reason=cand.get("reason", "Expanded candidate"),
                            trigger="expansion",
                            ranking_score=conf_float,
                            confidence=conf_float,
                            evidence=tuple(ev),
                            relation=cand.get("relation"),
                            direction="forward",
                            graph_snapshot_hash=cand.get("graph_snapshot_hash", ""),
                            graph_query_id=cand.get("graph_query_id", ""),
                            graph_node_id=cand.get("graph_node_id", ""),
                            graph_edge_source_id=cand.get("graph_edge_source_id", ""),
                            graph_edge_target_id=cand.get("graph_edge_target_id", ""),
                            graph_edge_kind=cand.get("graph_edge_kind", ""),
                            graph_confidence=conf_float,
                            lexical_query_hash=cand.get("query_hash", "") if is_heuristic else "",
                            lexical_matched_terms=tuple(cand.get("matched", ())) if is_heuristic else (),
                            lexical_score=float(cand["score"]) if is_heuristic and isinstance(cand.get("score"), (int, float)) else 0.0,
                        ))
                    else:
                        print(f"Skipping candidate {path} due to token budget constraint ({breakdown.used} > {manifest.budget.limit})")

    # 2. Expand explicit files/symbols/rules/refs
    for f, f_hash in explicit_files:
        if f in [item.path for item in new_files]:
            continue

        new_files.append(ActiveFileContext(
            path=f,
            selection={"mode": "full"},
            source="explicit",
            ranking_score=1.0,
            confidence=1.0,
            evidence=("explicit_user_input",),
            relation=None,
            trigger="expansion",
            git_revision=manifest.git_revision,
            reason=reason or "Explicit CLI expand",
            hash=f_hash
        ))
        new_events.append(AdmissionEvent(
            id=f"evt-exp-{len(new_events):03d}",
            target=f,
            action="admit",
            source="explicit",
            reason=reason or "Explicit CLI expand",
            trigger="expansion",
            ranking_score=1.0,
            confidence=1.0,
            evidence=("explicit_user_input",),
            direction="forward"
        ))

    for sym, sym_file, sym_name, rng, f_hash in explicit_symbols:
        found = False
        for idx, file_ctx in enumerate(new_files):
            if file_ctx.path == sym_file:
                found = True
                sel = file_ctx.selection.copy()
                if sel.get("mode") == "symbols":
                    syms = list(sel["symbols"])
                    if not any(s.name == sym_name for s in syms):
                        syms.append(ActiveSymbolContext(name=sym_name, range=rng, reason=reason or "Explicit CLI expand"))
                    sel["symbols"] = syms
                else:
                    sel = {"mode": "symbols", "symbols": [ActiveSymbolContext(name=sym_name, range=rng, reason=reason or "Explicit CLI expand")]}

                new_files[idx] = ActiveFileContext(
                    path=file_ctx.path, selection=sel, source=file_ctx.source,
                    ranking_score=file_ctx.ranking_score, confidence=file_ctx.confidence,
                    evidence=file_ctx.evidence,
                    relation=file_ctx.relation, trigger=file_ctx.trigger, git_revision=file_ctx.git_revision,
                    reason=file_ctx.reason, hash=file_ctx.hash
                )
                break
        if not found:
            new_files.append(ActiveFileContext(
                path=sym_file,
                selection={"mode": "symbols", "symbols": [ActiveSymbolContext(name=sym_name, range=rng, reason=reason or "Explicit CLI expand")]},
                source="explicit", ranking_score=1.0, confidence=1.0, evidence=("explicit_user_input", "symbol"),
                relation=None, trigger="expansion", git_revision=manifest.git_revision,
                reason=reason or "Explicit CLI expand", hash=f_hash
            ))

        new_events.append(AdmissionEvent(
            id=f"evt-exp-{len(new_events):03d}",
            target=sym,
            action="admit",
            source="explicit",
            reason=reason or "Explicit CLI expand",
            trigger="expansion",
            ranking_score=1.0,
            confidence=1.0,
            evidence=("explicit_user_input", "symbol"),
            direction="forward"
        ))

    # Apply Rules/Refs
    for _requested, r_rel, r_hash in explicit_rules:
        if not any(rule.path == r_rel for rule in new_rules):
            new_rules.append(ActiveRuleContext(path=r_rel, hash=r_hash, reason=reason or "Explicit CLI expand"))

    for r_rel, sel, ref_hash in explicit_refs:
        if not any(reference.path == r_rel for reference in new_refs):
            new_refs.append(ActiveReferenceContext(path=r_rel, selection=sel, hash=ref_hash, reason=reason or "Explicit CLI expand"))

    from dataclasses import replace
    updated_manifest = replace(
        manifest,
        files=tuple(new_files),
        rules=tuple(new_rules),
        references=tuple(new_refs),
        events=tuple(new_events),
    )
    from sacas.enforce import get_enforcement_provider
    provider = get_enforcement_provider(installation, updated_manifest)
    provider.enforce(installation, updated_manifest)

    regenerate_task_markdown(installation, task_dir, updated_manifest, contract)
    print("Expansion completed successfully.")
    return 0


def doctor_command(root: Path, format_type: str = "text") -> int:
    from sacas.validate import perform_validation, run_diagnostics

    combined_failures = 0
    if format_type == "json":
        import json as _json
        installation = discover_manifest(root)
        diagnostics_report = (
            run_diagnostics(installation.repository_root)
            if installation is not None
            else {"diagnostics": []}
        )
        validation_payload = perform_validation(root, format_type="json")
        try:
            parsed = _json.loads(validation_payload)
        except json.JSONDecodeError:
            parsed = {"raw": validation_payload}
        payload = {
            "diagnostics": diagnostics_report.get("diagnostics", []),
            "validation": parsed,
        }
        print(_json.dumps(payload, indent=2))
        combined_failures = sum(
            1 for d in payload["diagnostics"] if d.get("severity") == "FAIL"
        )
        return 1 if combined_failures else 0

    installation = discover_manifest(root)
    if installation is None:
        print("SACAS is not initialized. Run 'sacas init' first.")
        return 1

    print("SACAS Doctor Diagnostics:")
    report = run_diagnostics(installation.repository_root)
    fail_count = 0
    warning_count = 0
    for d in report.get("diagnostics", []):
        sev = d["severity"]
        check = d["check"]
        msg = d["message"]
        print(f"[{sev}] check={check}: {msg}")
        if sev == "FAIL":
            fail_count += 1
        elif sev == "WARNING":
            warning_count += 1

    cursor_ignore = installation.repository_root / ".cursorignore"
    if cursor_ignore.is_file():
        text = cursor_ignore.read_text(encoding="utf-8")
        if "<!-- SACAS:START cursor-ignore -->" not in text:
            print("[WARNING] check=cursorignore_negation: .cursorignore exists but does not contain a SACAS-owned negation region.")
            warning_count += 1

    print(f"\nSummary: {fail_count} failures, {warning_count} warnings.")

    print("\nSACAS Validation:")
    validation_code = perform_validation(installation.repository_root, format_type="text")
    return 1 if fail_count > 0 else int(validation_code)


def benchmark_command_dispatch(installation: Installation, format_type: str = "text") -> int:
    from sacas.lab.benchmark_runner import load_and_run_all_benchmarks

    results = load_and_run_all_benchmarks(installation)

    if results:
        if format_type == "json":
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print("SACAS Gold-Standard Benchmark Suite Results")
            print("==========================================")
            for r in results:
                print(f"Task ID:                      {r.task_id}")
                print(f"  Precision:                  {r.precision * 100:.1f}%")
                print(f"  Recall:                     {r.recall * 100:.1f}%")
                print(f"  F1-Score:                   {r.f1 * 100:.1f}%")
                print(f"  Precision@5:                {r.precision_at_5 * 100:.1f}%")
                print(f"  Precision@10:               {r.precision_at_10 * 100:.1f}%")
                print(f"  Recall@5:                   {r.recall_at_5 * 100:.1f}%")
                print(f"  Recall@10:                  {r.recall_at_10 * 100:.1f}%")
                print(f"  MRR:                        {r.mrr:.3f}")
                print(f"  Symbol Recall:              {r.symbol_recall * 100:.1f}%")
                print(f"  Test-File Recall:           {r.test_recall * 100:.1f}%")
                print(f"  Payload Context Efficiency: {r.payload_context_efficiency * 100:.1f}%")
                print(f"  Total Context Efficiency:   {r.total_context_efficiency * 100:.1f}%")
                print(f"  Whole-repository reduction: {r.whole_repository_reduction * 100:.1f}%")
                print("-" * 40)
        return 0
    else:
        from sacas.lab.benchmark import print_benchmark
        return print_benchmark(installation, format_type=format_type)


def histbench_command(
    installation: Installation,
    max_commits: int = 200,
    generate_only: bool = False,
    output_dir: str | None = None,
    format_type: str = "text"
) -> int:
    """Generate and optionally run historical Git benchmarks."""
    from sacas.lab.git_benchmark import generate_historical_tasks, run_historical_benchmarks, save_historical_benchmarks

    repo_root = installation.repository_root

    # Determine output directory
    if output_dir:
        bench_dir = Path(output_dir)
    else:
        bench_dir = installation.sacas_root / "benchmarks" / "historical"

    print(f"Generating historical benchmarks from {repo_root}...")
    tasks = generate_historical_tasks(repo_root, max_commits=max_commits)

    if not tasks:
        print("No suitable historical tasks found.")
        return 0

    print(f"Generated {len(tasks)} historical benchmark tasks.")
    save_historical_benchmarks(tasks, bench_dir)
    print(f"Saved to {bench_dir}")

    if generate_only:
        return 0

    # Run benchmarks
    print("\nRunning benchmarks...")
    results = run_historical_benchmarks(installation, bench_dir)

    if not results:
        print("No benchmarks to run.")
        return 0

    if format_type == "json":
        print(json.dumps(results, indent=2))
    else:
        print("\nHistorical Benchmark Results")
        print("============================")
        for r in results:
            if "error" in r:
                print(f"Task ID:     {r['task_id']}")
                print(f"  Error:     {r['error']}")
                print("-" * 40)
                continue
            print(f"Task ID:     {r['task_id']}")
            print(f"  Precision: {r['eval']['precision'] * 100:.1f}%")
            print(f"  Recall:    {r['eval']['recall'] * 100:.1f}%")
            print(f"  Parent:    {r['parent_commit']}")
            print(f"  Child:     {r['child_commit']}")
            print("-" * 40)

    return 1 if any("error" in result for result in results) else 0
