"""Command-line interface for SACAS."""

from __future__ import annotations

import argparse
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
    task_parser.add_argument("--tests", nargs="*", default=(), help="Focus tests.")
    task_parser.add_argument("--rules", nargs="*", default=(), help="Rules to follow.")

    refresh_parser = subcommands.add_parser("refresh", help="Refresh task context and detect stale files.")
    refresh_parser.add_argument("--root", default=".", help="Repository root (default: current directory).")
    refresh_parser.add_argument("--files", nargs="*", default=(), help="Selective focus files to refresh.")

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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run SACAS and return its process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        initialize(arguments.root, sacas_root=arguments.sacas_root)
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

        generate_task(
            installation,
            goal=arguments.goal,
            criteria=tuple(arguments.criteria),
            constraints=tuple(arguments.constraints),
            verification=tuple(arguments.verification),
            files=tuple(arguments.files),
            symbols=tuple(arguments.symbols),
            tests=tuple(arguments.tests),
            rules=tuple(arguments.rules),
        )
    elif arguments.command == "refresh":
        from sacas.paths import discover_manifest
        from sacas.refresh import refresh_context

        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")

        refresh_context(installation, selective_files=tuple(arguments.files))
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
        from sacas.benchmark import print_benchmark
        from sacas.paths import discover_manifest
        root = Path(arguments.root).resolve()
        installation = discover_manifest(root)
        if installation is None:
            raise ValueError("SACAS is not initialized. Run 'sacas init' first.")
        return print_benchmark(installation, format_type=arguments.format)
    return 0
