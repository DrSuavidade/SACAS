"""Command-line interface for SACAS."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from sacas import __version__
from sacas.graphify import collect_graphify, write_graphify_manifest
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run SACAS and return its process exit code."""
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "init":
        initialize(arguments.root, sacas_root=arguments.sacas_root)
    elif arguments.command == "map":
        root = Path(arguments.root).resolve()
        sacas_root = root / arguments.sacas_root
        evidence = collect_graphify(root, mode=arguments.mode, output=arguments.output)
        write_graphify_manifest(sacas_root / ".sacas" / "graphify.json", evidence)
        write_system_map(sacas_root / "map" / "SYSTEM.md", build_system_map(evidence))
    return 0
