"""Regression coverage for the public SACAS command documentation."""

import argparse
import inspect
import re
from pathlib import Path

from sacas.lab.benchmark_runner import run_routing_benchmark_suite
from sacas.cli import build_parser


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_the_public_command_and_option_contract() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    def command_section(title: str) -> str:
        start = readme.index(title)
        end = readme.find("\n---", start)
        return readme[start:] if end == -1 else readme[start:end]

    def subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
        action = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        return action.choices

    def assert_parser_contract(section: str, parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            if action.dest == "help":
                continue
            if action.option_strings:
                for option in action.option_strings:
                    if option.startswith("--"):
                        assert option in section, f"section must document parser option {option}"
            else:
                assert (
                    action.dest in section or f"<{action.dest}>" in section
                ), f"section must document positional {action.dest}"

    assert "Most commands accept `--root <path>`" in readme

    commands = subparsers(build_parser())
    headings = {
        "init": "### 1. `sacas init`",
        "prepare": '### 2. `sacas prepare "<goal>"`',
        "add": "### 3. `sacas add`",
        "explain": "### 4. `sacas explain`",
        "doctor": "### 5. `sacas doctor`",
    }
    for command, heading in headings.items():
        assert_parser_contract(command_section(heading), commands[command])

    # The agent-facing surface stays tiny: everything else must not be a
    # documented headline command.
    public = set(headings)
    documented = set(re.findall(r"^### \d+\. `sacas ([a-z-]+)", readme, flags=re.M))
    assert documented == public

    # README claims these defaults explicitly; keep each claim tied to the parser default.
    claimed_defaults = (
        ("init", "### 1. `sacas init`", "root", ".", "default: current directory"),
        ("init", "### 1. `sacas init`", "sacas_root", "Structure", "default: `Structure`"),
        ("init", "### 1. `sacas init`", "graphify", "existing", "default: `existing`"),
        ("prepare", '### 2. `sacas prepare "<goal>"`', "context_policy", "advisory", "default: `advisory`"),
    )
    for command, heading, destination, expected, rendered in claimed_defaults:
        parser = commands[command]
        assert parser.get_default(destination) == expected
        assert rendered in command_section(heading)


def test_pipeline_and_context_simulation_are_removed_from_the_cli() -> None:
    commands = build_parser()
    action = next(
        action for action in commands._actions if isinstance(action, argparse._SubParsersAction)
    )
    for removed in ("pipeline", "context-simulation"):
        assert removed not in action.choices


def test_readme_uses_the_serialized_b2_benchmark_key() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    source = inspect.getsource(run_routing_benchmark_suite)
    match = re.search(r'baselines\["(B2_[^"]+)"\]', source)

    assert match, "run_routing_benchmark_suite must serialize a B2 baseline key"
    assert f"`{match.group(1)}`" in readme


def test_skill_documents_canonical_pair_and_minimal_operations() -> None:
    skill = (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for token in (
        "`task.json`",
        "`active_context.json`",
        "canonical pair",
        "sacas prepare",
        "sacas add",
        "sacas explain",
        "sacas doctor",
    ):
        assert token in skill, f"SKILL.md must document {token}"
