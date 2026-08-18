"""Command-line interface for SACAS."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from sacas import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the public SACAS argument parser."""
    parser = argparse.ArgumentParser(
        prog="sacas",
        description="SACAS routes repository evidence into focused task context.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command", metavar="COMMAND")
    subcommands.add_parser("init", help="Initialize SACAS in a repository.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run SACAS and return its process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    return 0
