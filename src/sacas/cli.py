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
from sacas.paths import Installation, resolve_repo_path


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
        description="SACAS routes repository evidence into focused task context.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")

    init_parser = subcommands.add_parser("init", help="Initialize SACAS in a repository.")
    init_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    init_parser.add_argument("--sacas-root", default="Structure", help="SACAS root relative to repository.")
    init_parser.add_argument("--graphify", choices=("off", "existing", "code-only", "semantic"), default="existing", help="Graphify integration mode.")
    init_parser.add_argument("--workflow", action="store_true", help="Also create ICM workflow stages and _config directories.")

    map_parser = subcommands.add_parser("map", help="Build a system map from optional Graphify evidence.")
    map_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    map_parser.add_argument("--sacas-root", default="Structure", help="SACAS root relative to repository.")
    map_parser.add_argument("--output", default="graphify-out", help="Graphify output relative to repository.")
    map_parser.add_argument("--mode", choices=("off", "existing", "code-only", "semantic"), default="existing")

    task_parser = subcommands.add_parser("task", help="Generate task contracts and context.")
    task_parser.add_argument("goal", help="The goal of the task.")
    task_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    task_parser.add_argument("--criteria", nargs="*", default=(), help="Acceptance criteria.")
    task_parser.add_argument("--constraints", nargs="*", default=(), help="Constraints.")
    task_parser.add_argument("--verification", nargs="*", default=(), help="Verification instructions.")
    task_parser.add_argument("--files", nargs="*", default=(), help="Focus files.")
    task_parser.add_argument("--symbols", nargs="*", default=(), help="Focus symbols.")
    task_parser.add_argument("--symbol", action="append", default=[], help="Repeatable focus symbol path (file::name).")
    task_parser.add_argument("--tests", nargs="*", default=(), help="Focus tests.")
    task_parser.add_argument("--rules", nargs="*", default=(), help="Rules to follow.")
    task_parser.add_argument("--references", nargs="*", default=(), help="References to follow.")
    task_parser.add_argument("--category", choices=("bugfix", "feature", "test", "refactor", "docs", "security", "investigate"), default=None, help="Task type/category.")
    task_parser.add_argument("--context-policy", choices=("advisory", "warn", "enforce"), default="advisory", help="Context boundaries policy.")

    refresh_parser = subcommands.add_parser("refresh", help="Refresh task context and detect stale files.")
    refresh_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    refresh_parser.add_argument("--files", nargs="*", default=(), help="Selective focus files to refresh.")

    expand_parser = subcommands.add_parser("expand", help="Explicitly expand active context.")
    expand_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    expand_parser.add_argument("--file", action="append", default=[], help="File path to expand.")
    expand_parser.add_argument("--symbol", action="append", default=[], help="Symbol path (file::name) to expand.")
    expand_parser.add_argument("--rule", action="append", default=[], help="Rule path to expand.")
    expand_parser.add_argument("--reference", action="append", default=[], help="Reference path (or section references/doc.md#heading) to expand.")
    expand_parser.add_argument("--reason", default="", help="Audit rationale for this expansion.")
    expand_parser.add_argument("--all-candidates", action="store_true", help="Expand all candidates in candidates.json that fit context budget.")

    why_parser = subcommands.add_parser("why", help="Explain routing path and metadata for a given file or symbol.")
    why_parser.add_argument("path", help="File path or symbol name to query.")
    why_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")

    doctor_parser = subcommands.add_parser("doctor", help="Run diagnostic health checks on workspace context.")
    doctor_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")

    status_parser = subcommands.add_parser("status", help="Show the status of the active task.")
    status_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    status_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    validate_parser = subcommands.add_parser("validate", help="Run cold-agent validation diagnostics.")
    validate_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    validate_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    migrate_parser = subcommands.add_parser("migrate", help="Migrate legacy PowerShell SACAS to Python CLI.")
    migrate_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    migrate_parser.add_argument("--apply", action="store_true", help="Execute the migration changes.")
    migrate_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    benchmark_parser = subcommands.add_parser("benchmark", help="Run SACAS routing and quality benchmarks.")
    benchmark_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    benchmark_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    sim_parser = subcommands.add_parser("context-simulation", help="Run SACAS context comparison size simulations.")
    sim_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    sim_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    histbench_parser = subcommands.add_parser("histbench", help="Generate and run historical Git benchmarks.")
    histbench_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    histbench_parser.add_argument("--max-commits", type=int, default=200, help="Maximum commits to analyze (default: 200).")
    histbench_parser.add_argument("--generate-only", action="store_true", help="Only generate benchmark files, don't run.")
    histbench_parser.add_argument("--output-dir", help="Output directory for generated benchmarks (default: Structure/benchmarks/historical).")
    histbench_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    # Pipeline commands (ICM multi-stage workflows)
    pipeline_parser = subcommands.add_parser("pipeline", help="Manage ICM multi-stage pipelines.")
    pipeline_subcommands = pipeline_parser.add_subparsers(dest="pipeline_command", metavar="SUBCOMMAND")

    pipeline_orchestrate_parser = pipeline_subcommands.add_parser("orchestrate", help="Walk through pipeline sequentially with review gates.")
    pipeline_orchestrate_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    pipeline_orchestrate_parser.add_argument("--start", default="01_analyze", help="Stage to start from (default: 01_analyze).")
    pipeline_orchestrate_parser.add_argument("--skip-review", action="store_true", help="Skip human review gates (non-interactive).")

    pipeline_stage_parser = pipeline_subcommands.add_parser("stage", help="Run a specific pipeline stage.")
    pipeline_stage_parser.add_argument("stage_id", help="Stage ID (e.g., 01_analyze, 02_implement, 03_verify).")
    pipeline_stage_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")

    pipeline_review_parser = pipeline_subcommands.add_parser("review", help="Open stage output for human review.")
    pipeline_review_parser.add_argument("stage_id", help="Stage ID to review.")
    pipeline_review_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")

    pipeline_list_parser = pipeline_subcommands.add_parser("list", help="List available pipeline stages.")
    pipeline_list_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run SACAS and return its process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        initialize(arguments.root, sacas_root=arguments.sacas_root, graphify_mode=arguments.graphify, workflow=arguments.workflow)
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
    elif arguments.command == "task":
        from sacas.paths import discover_manifest
        from sacas.tasks import generate_task

        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")

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
    elif arguments.command == "refresh":
        from sacas.paths import discover_manifest
        from sacas.refresh import refresh_context

        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")

        refresh_context(installation, selective_files=tuple(arguments.files))
    elif arguments.command == "expand":
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
            
        return expand_context_command(
            installation,
            files=list(arguments.file),
            symbols=list(arguments.symbol),
            rules=list(arguments.rule),
            references=list(arguments.reference),
            reason=arguments.reason,
            all_candidates=arguments.all_candidates
        )
    elif arguments.command == "why":
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
            
        return query_why_command(installation, arguments.path)
    elif arguments.command == "doctor":
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
            
        return doctor_command(installation)
    elif arguments.command == "status":
        from sacas.paths import discover_manifest
        from sacas.status import print_status_report

        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")

        print_status_report(installation, format_type=arguments.format)
    elif arguments.command == "validate":
        from sacas.validate import perform_validation
        root = Path(arguments.root).resolve()
        return perform_validation(root, format_type=arguments.format)
    elif arguments.command == "migrate":
        from sacas.migrate import perform_migration
        root = Path(arguments.root).resolve()
        return perform_migration(root, apply=arguments.apply, format_type=arguments.format)
    elif arguments.command == "benchmark":
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
        return benchmark_command_dispatch(installation, format_type=arguments.format)
    elif arguments.command == "context-simulation":
        from sacas.benchmark import print_context_simulation
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
        return print_context_simulation(installation, format_type=arguments.format)
    elif arguments.command == "histbench":
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
        return histbench_command(
            installation,
            max_commits=arguments.max_commits,
            generate_only=arguments.generate_only,
            output_dir=arguments.output_dir,
            format_type=arguments.format
        )
    elif arguments.command == "pipeline":
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
        
        if arguments.pipeline_command == "orchestrate":
            return pipeline_orchestrate_command(installation, arguments.start, arguments.skip_review)
        elif arguments.pipeline_command == "stage":
            return pipeline_stage_command(installation, arguments.stage_id)
        elif arguments.pipeline_command == "review":
            return pipeline_review_command(installation, arguments.stage_id)
        elif arguments.pipeline_command == "list":
            return pipeline_list_command(installation)
        else:
            print("Usage: sacas pipeline {orchestrate|stage|review|list}")
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
    from sacas.regions import SymbolRangeResolver, extract_markdown_section
    import hashlib
    
    task_dir = installation.sacas_root / "tasks" / "current"
    manifest, contract = load_task_state(task_dir)
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
                extract_markdown_section(
                    read_repo_text(installation.repository_root, normalized), heading_path, strict=True,
                )
                selection: dict[str, object] = {
                    "mode": "sections", "sections": [{"heading_path": heading_path}],
                }
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


def query_why_command(installation: Installation, path: str) -> int:
    from sacas.provenance import query_why_file
    lines = query_why_file(installation, path)
    for line in lines:
        print(line)
    return 0


def doctor_command(installation: Installation) -> int:
    from sacas.validate import run_diagnostics
    report = run_diagnostics(installation.repository_root)
    diagnostics_list = report.get("diagnostics", [])
    
    cursor_ignore = installation.repository_root / ".cursorignore"
    cursor_ok = True
    if cursor_ignore.is_file():
        text = cursor_ignore.read_text(encoding="utf-8")
        if "<!-- SACAS:START cursor-ignore -->" not in text:
            cursor_ok = False
            
    print("SACAS Doctor Diagnostics:")
    fail_count = 0
    warning_count = 0
    
    for d in diagnostics_list:
        sev = d["severity"]
        check = d["check"]
        msg = d["message"]
        print(f"[{sev}] check={check}: {msg}")
        if sev == "FAIL":
            fail_count += 1
        elif sev == "WARNING":
            warning_count += 1
            
    if not cursor_ok:
        print("[WARNING] check=cursorignore_negation: .cursorignore exists but does not contain a SACAS-owned negation region.")
        warning_count += 1
        
    print(f"\nSummary: {fail_count} failures, {warning_count} warnings.")
    return 1 if fail_count > 0 else 0


def benchmark_command_dispatch(installation: Installation, format_type: str = "text") -> int:
    from sacas.benchmark_runner import load_and_run_all_benchmarks
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
        from sacas.benchmark import print_benchmark
        return print_benchmark(installation, format_type=format_type)


def histbench_command(
    installation: Installation,
    max_commits: int = 200,
    generate_only: bool = False,
    output_dir: str | None = None,
    format_type: str = "text"
) -> int:
    """Generate and optionally run historical Git benchmarks."""
    from sacas.git_benchmark import generate_historical_tasks, run_historical_benchmarks, save_historical_benchmarks
    import json
    
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


def pipeline_list_command(installation: Installation) -> int:
    """List available pipeline stages."""
    stages_dir = installation.sacas_root / "stages"
    if not stages_dir.exists():
        print("No pipeline stages found. Run 'sacas init' to create default stages.")
        return 1
    
    stages = sorted([d.name for d in stages_dir.iterdir() if d.is_dir()])
    if not stages:
        print("No pipeline stages configured.")
        return 0
    
    print("Available Pipeline Stages:")
    print("==========================")
    for stage in stages:
        stage_path = stages_dir / stage
        context_path = stage_path / "CONTEXT.md"
        purpose = "No description"
        if context_path.exists():
            content = context_path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("**Purpose**:"):
                    purpose = line.replace("**Purpose**:", "").strip()
                    break
        print(f"  {stage}: {purpose}")
    return 0


def pipeline_stage_command(installation: Installation, stage_id: str) -> int:
    """Run a specific pipeline stage."""
    stage_dir = installation.sacas_root / "stages" / stage_id
    if not stage_dir.exists():
        print(f"Stage not found: {stage_id}")
        print("Run 'sacas pipeline list' to see available stages.")
        return 1
    
    context_path = stage_dir / "CONTEXT.md"
    if not context_path.exists():
        print(f"Stage contract not found: {context_path}")
        return 1
    
    output_dir = stage_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Running stage: {stage_id}")
    print(f"Contract: {context_path}")
    print(f"Output: {output_dir}")
    print()
    print("Stage contract (CONTEXT.md):")
    print("=" * 50)
    print(context_path.read_text(encoding="utf-8"))
    print("=" * 50)
    print()
    print("NEXT STEPS:")
    print(f"  1. Review the contract above")
    print(f"  2. Execute the stage manually (AI agent reads CONTEXT.md and writes to {output_dir})")
    print(f"  3. Run 'sacas pipeline review {stage_id}' to review output before next stage")
    return 0


def pipeline_review_command(installation: Installation, stage_id: str) -> int:
    """Open stage output for human review."""
    stage_dir = installation.sacas_root / "stages" / stage_id
    if not stage_dir.exists():
        print(f"Stage not found: {stage_id}")
        return 1
    
    output_dir = stage_dir / "output"
    if not output_dir.exists():
        print(f"No output directory for stage: {stage_id}")
        return 1
    
    output_files = list(output_dir.glob("*"))
    if not output_files:
        print(f"No output files in {output_dir}")
        print("Run the stage first, then review.")
        return 0
    
    print(f"Reviewing output for stage: {stage_id}")
    print("=" * 50)
    for f in output_files:
        if f.is_file():
            print(f"\n--- {f.name} ---")
            content = f.read_text(encoding="utf-8")
            # Show first 100 lines
            lines = content.split("\n")
            for line in lines[:100]:
                print(line)
            if len(lines) > 100:
                print(f"... ({len(lines) - 100} more lines)")
    print("=" * 50)
    print()
    print("EDIT FILES IN THIS FOLDER BEFORE RUNNING NEXT STAGE:")
    print(f"  {output_dir}")
    print()
    print("When done editing, run next stage:")
    # Find next stage
    stages = sorted([d.name for d in (installation.sacas_root / "stages").iterdir() if d.is_dir()])
    try:
        idx = stages.index(stage_id)
        if idx + 1 < len(stages):
            print(f"  sacas pipeline stage {stages[idx + 1]}")
        else:
            print("  (This is the last stage)")
    except ValueError:
        pass
    return 0


def pipeline_orchestrate_command(installation: Installation, start_stage: str, skip_review: bool) -> int:
    """Walk through pipeline sequentially with review gates."""
    stages_dir = installation.sacas_root / "stages"
    if not stages_dir.exists():
        print("No pipeline stages found. Run 'sacas init' to create default stages.")
        return 1
    
    stages = sorted([d.name for d in stages_dir.iterdir() if d.is_dir()])
    if not stages:
        print("No pipeline stages configured.")
        return 1
    
    # Find start index
    try:
        start_idx = stages.index(start_stage)
    except ValueError:
        print(f"Start stage not found: {start_stage}")
        print(f"Available stages: {', '.join(stages)}")
        return 1
    
    print("SACAS Pipeline Execution")
    print("========================")
    print(f"Stages: {' -> '.join(stages[start_idx:])}")
    print(f"Review gates: {'DISABLED' if skip_review else 'ENABLED'}")
    print()
    
    for i, stage_id in enumerate(stages[start_idx:], start=start_idx):
        print(f"\n{'='*60}")
        print(f"STAGE {i+1}/{len(stages)}: {stage_id}")
        print(f"{'='*60}")
        
        # Run stage
        ret = pipeline_stage_command(installation, stage_id)
        if ret != 0:
            return ret
        
        # Review gate (unless last stage or skipped)
        if not skip_review and i < len(stages) - 1:
            print(f"\n--- REVIEW GATE ---")
            print(f"Stage {stage_id} complete. Review output before continuing.")
            pipeline_review_command(installation, stage_id)
            
            # Wait for user confirmation
            try:
                response = input("\nContinue to next stage? [y/N]: ").strip().lower()
                if response not in ("y", "yes"):
                    print("Pipeline paused. Run 'sacas pipeline stage <next>' to continue.")
                    return 0
            except (EOFError, KeyboardInterrupt):
                print("\nPipeline paused.")
                return 0
    
    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)
    return 0
