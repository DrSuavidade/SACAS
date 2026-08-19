"""Command-line interface for SACAS."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sacas import __version__
from sacas.graphify import collect_graphify, repository_relative_path, write_graphify_manifest
from sacas.init import initialize
from sacas.map import build_system_map, write_system_map


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
    task_parser.add_argument("--category", choices=("bugfix", "feature", "test", "refactor", "docs", "security"), default=None, help="Task type/category.")
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run SACAS and return its process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        initialize(arguments.root, sacas_root=arguments.sacas_root, graphify_mode=arguments.graphify)
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
        save_active_context,
        ActiveFileContext,
        ActiveSymbolContext,
        ActiveRuleContext,
        ActiveReferenceContext,
        AdmissionEvent,
        ActiveContextManifest,
    )
    from sacas.tasks import regenerate_task_markdown
    import hashlib
    
    task_dir = installation.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    if not manifest:
        print("No active SACAS task found.")
        return 1
        
    new_files = list(manifest.files)
    new_rules = list(manifest.rules)
    new_refs = list(manifest.references)
    new_events = list(manifest.events)
    
    # 1. Expand from candidates if requested
    if all_candidates:
        candidates_path = task_dir / "candidates.json"
        if candidates_path.is_file():
            try:
                candidates_data = json.loads(candidates_path.read_text(encoding="utf-8"))
                for cand in candidates_data.get("candidates", []):
                    path = cand["path"]
                    if path in [f.path for f in new_files]:
                        continue
                    
                    f_path = installation.repository_root / path
                    f_hash = ""
                    if f_path.is_file():
                        f_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                        
                    new_file_ctx = ActiveFileContext(
                        path=path,
                        selection={"mode": "full"},
                        source=cand.get("source", "graphify"),
                        confidence=cand.get("confidence", "high"),
                        relation=cand.get("relation"),
                        trigger="expansion",
                        git_revision=manifest.git_revision,
                        reason=cand.get("reason", "Expanded candidate"),
                        hash=f_hash
                    )
                    
                    # Dry-run check budget
                    from sacas.budget import calculate_manifest_tokens
                    temp_manifest = ActiveContextManifest(
                        task_id=manifest.task_id, goal=manifest.goal, category=manifest.category,
                        git_revision=manifest.git_revision, files=tuple(new_files + [new_file_ctx]),
                        rules=tuple(new_rules), references=tuple(new_refs), events=tuple(new_events),
                        tests=manifest.tests, schema_version=manifest.schema_version
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
                            trigger="expansion"
                        ))
                    else:
                        print(f"Skipping candidate {path} due to token budget constraint ({breakdown.used} > {manifest.budget.limit})")
            except Exception as e:
                print(f"Error loading candidates: {e}")
                
    # 2. Expand explicit files/symbols/rules/refs
    for f in files:
        if f in [item.path for item in new_files]:
            continue
        f_path = installation.repository_root / f
        f_hash = ""
        if f_path.is_file():
            f_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
            
        new_files.append(ActiveFileContext(
            path=f,
            selection={"mode": "full"},
            source="explicit",
            confidence="high",
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
            trigger="expansion"
        ))
        
    for sym in symbols:
        if "::" in sym:
            sym_file, sym_name = sym.split("::", 1)
        else:
            print(f"WARNING: Symbol '{sym}' is not in file::name format. Skipping.")
            continue
            
        found = False
        from sacas.regions import SymbolRangeResolver
        rng = SymbolRangeResolver.resolve(installation, sym_file, sym_name)
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
                    path=file_ctx.path, selection=sel, source=file_ctx.source, confidence=file_ctx.confidence,
                    relation=file_ctx.relation, trigger=file_ctx.trigger, git_revision=file_ctx.git_revision,
                    reason=file_ctx.reason, hash=file_ctx.hash
                )
                break
        if not found:
            f_path = installation.repository_root / sym_file
            f_hash = ""
            if f_path.is_file():
                f_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
            new_files.append(ActiveFileContext(
                path=sym_file,
                selection={"mode": "symbols", "symbols": [ActiveSymbolContext(name=sym_name, range=rng, reason=reason or "Explicit CLI expand")]},
                source="explicit", confidence="high", relation=None, trigger="expansion", git_revision=manifest.git_revision,
                reason=reason or "Explicit CLI expand", hash=f_hash
            ))
            
        new_events.append(AdmissionEvent(
            id=f"evt-exp-{len(new_events):03d}",
            target=sym,
            action="admit",
            source="explicit",
            reason=reason or "Explicit CLI expand",
            trigger="expansion"
        ))

    # Apply Rules/Refs
    for r in rules:
        r_clean = r.replace("\\", "/")
        if not r_clean.startswith("Structure/"):
            r_rel = "Structure/" + r_clean
        else:
            r_rel = r_clean
        if not any(rule.path == r_rel for rule in new_rules):
            r_path = installation.repository_root / r_rel
            r_hash = ""
            if r_path.is_file():
                r_hash = hashlib.sha256(r_path.read_bytes()).hexdigest()
            new_rules.append(ActiveRuleContext(path=r_rel, hash=r_hash, reason=reason or "Explicit CLI expand"))

    for ref in references:
        path_part = ref
        section_anchor = None
        if "#" in ref:
            path_part, section_anchor = ref.split("#", 1)
            
        path_part_clean = path_part.replace("\\", "/")
        if not path_part_clean.startswith("Structure/"):
            r_rel = "Structure/" + path_part_clean
        else:
            r_rel = path_part_clean
            
        if section_anchor:
            heading_path = [section_anchor.replace("-", " ").title()]
            sel = {"mode": "sections", "sections": [{"heading_path": heading_path}]}
        else:
            sel = {"mode": "full"}
            
        if not any(reference.path == r_rel for reference in new_refs):
            ref_path = installation.repository_root / r_rel
            ref_hash = ""
            if ref_path.is_file():
                ref_hash = hashlib.sha256(ref_path.read_bytes()).hexdigest()
            new_refs.append(ActiveReferenceContext(path=r_rel, selection=sel, hash=ref_hash, reason=reason or "Explicit CLI expand"))

    updated_manifest = ActiveContextManifest(
        task_id=manifest.task_id, goal=manifest.goal, category=manifest.category,
        git_revision=manifest.git_revision, files=tuple(new_files),
        rules=tuple(new_rules), references=tuple(new_refs), events=tuple(new_events),
        budget=manifest.budget, policy=manifest.policy, tests=manifest.tests, schema_version=manifest.schema_version
    )
    save_active_context(task_dir, updated_manifest)
    
    from sacas.enforce import get_enforcement_provider
    provider = get_enforcement_provider(installation, updated_manifest)
    provider.enforce(installation, updated_manifest)
    
    regenerate_task_markdown(installation, task_dir, updated_manifest)
    print("Expansion completed successfully.")
    return 0


def query_why_command(installation: Installation, path: str) -> int:
    from sacas.active_context import load_active_context
    task_dir = installation.sacas_root / "tasks" / "current"
    manifest = load_active_context(task_dir)
    if not manifest:
        print("No active SACAS task found.")
        return 1
        
    found = False
    for f in manifest.files:
        if f.path == path or path in f.path:
            print(f"File: {f.path}")
            print(f"  Admitted: yes")
            print(f"  Source: {f.source}")
            print(f"  Trigger: {f.trigger}")
            print(f"  Relation: {f.relation}")
            print(f"  Git Revision: {f.git_revision}")
            print(f"  Rationale: {f.reason}")
            # Show events
            events = [e for e in manifest.events if e.target == f.path]
            if events:
                print("  Admission History:")
                for e in events:
                    print(f"    - [{e.action.upper()}] source={e.source} reason={e.reason}")
            found = True
            
    for r in manifest.rules:
        if r.path == path or path in r.path:
            print(f"Rule: {r.path}")
            print(f"  Admitted: yes")
            print(f"  Rationale: {r.reason}")
            found = True
            
    for ref in manifest.references:
        if ref.path == path or path in ref.path:
            print(f"Reference: {ref.path}")
            print(f"  Admitted: yes")
            print(f"  Selection: {json.dumps(ref.selection)}")
            print(f"  Rationale: {ref.reason}")
            found = True
            
    if not found:
        candidates_path = task_dir / "candidates.json"
        if candidates_path.is_file():
            try:
                candidates_data = json.loads(candidates_path.read_text(encoding="utf-8"))
                for cand in candidates_data.get("candidates", []):
                    if cand["path"] == path or path in cand["path"]:
                        print(f"File (Candidate): {cand['path']}")
                        print(f"  Admitted: no (Recommended candidate)")
                        print(f"  Recommendation Score: {cand['score']}")
                        print(f"  Source: {cand['source']}")
                        print(f"  Relation: {cand.get('relation')}")
                        print(f"  Triggered By: {cand.get('triggered_by')}")
                        print(f"  Estimated Cost: {cand.get('estimated_tokens')} tokens")
                        print(f"  Rationale: {cand['reason']}")
                        found = True
            except Exception:
                pass
                
    if not found:
        print(f"No active context or candidate information found for path: {path}")
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
                print(f"Task ID:              {r.task_id}")
                print(f"  Precision:          {r.precision * 100:.1f}%")
                print(f"  Recall:             {r.recall * 100:.1f}%")
                print(f"  F1-Score:           {r.f1 * 100:.1f}%")
                print(f"  Precision@5:        {r.precision_at_5 * 100:.1f}%")
                print(f"  Precision@10:       {r.precision_at_10 * 100:.1f}%")
                print(f"  Recall@5:           {r.recall_at_5 * 100:.1f}%")
                print(f"  Recall@10:          {r.recall_at_10 * 100:.1f}%")
                print(f"  MRR:                {r.mrr:.3f}")
                print(f"  Context Efficiency: {r.context_efficiency * 100:.1f}%")
                print(f"  Token Reduction:    {r.token_reduction * 100:.1f}%")
                print("-" * 40)
        return 0
    else:
        from sacas.benchmark import print_benchmark
        return print_benchmark(installation, format_type=format_type)
