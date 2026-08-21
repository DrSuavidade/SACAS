"""Regression coverage for the public SACAS command documentation."""

import argparse
import inspect
import re
from pathlib import Path

from sacas.benchmark_runner import run_routing_benchmark_suite
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

    assert "All commands support targeting specific directories" not in readme
    assert "Most commands accept `--root <path>`" in readme

    commands = subparsers(build_parser())
    headings = {
        "init": "### 1. `sacas init`",
        "map": "### 2. `sacas map`",
        "task": "### 3. `sacas task`",
        "refresh": "### 4. `sacas refresh`",
        "expand": "### 5. `sacas expand`",
        "why": "### 6. `sacas why`",
        "doctor": "### 7. `sacas doctor`",
        "status": "### 8. `sacas status`",
        "validate": "### 9. `sacas validate`",
        "migrate": "### 10. `sacas migrate`",
        "context-simulation": "### 11. `sacas context-simulation`",
        "benchmark": "### 12. `sacas benchmark`",
        "histbench": "### 13. `sacas histbench`",
    }
    for command, heading in headings.items():
        assert_parser_contract(command_section(heading), commands[command])

    pipeline_section = command_section("### 14. `sacas pipeline`")
    pipeline_children = subparsers(commands["pipeline"])
    for child, child_parser in pipeline_children.items():
        assert f"`sacas pipeline {child}`" in pipeline_section
        assert_parser_contract(pipeline_section, child_parser)

    # README claims these defaults explicitly; keep each claim tied to the parser default.
    claimed_defaults = (
        ("init", "### 1. `sacas init`", "root", ".", "default: current directory"),
        ("init", "### 1. `sacas init`", "sacas_root", "Structure", "default: `Structure`"),
        ("init", "### 1. `sacas init`", "graphify", "existing", "default: `existing`"),
        ("task", "### 3. `sacas task`", "context_policy", "advisory", "default: `advisory`"),
        ("histbench", "### 13. `sacas histbench`", "max_commits", 200, "default: 200"),
        ("pipeline", "### 14. `sacas pipeline`", "start", "01_analyze", "default: `01_analyze`"),
    )
    for command, heading, destination, expected, rendered in claimed_defaults:
        parser = pipeline_children["orchestrate"] if command == "pipeline" else commands[command]
        assert parser.get_default(destination) == expected
        assert rendered in command_section(heading)


def test_readme_uses_the_serialized_b2_benchmark_key() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    source = inspect.getsource(run_routing_benchmark_suite)
    match = re.search(r'baselines\["(B2_[^"]+)"\]', source)

    assert match, "run_routing_benchmark_suite must serialize a B2 baseline key"
    assert f"`{match.group(1)}`" in readme


def test_skill_documents_canonical_pair_and_routine_operations() -> None:
    skill = (REPOSITORY_ROOT / "SKILL.md").read_text(encoding="utf-8")

    for token in (
        "`task.json`",
        "`active_context.json`",
        "canonical pair",
        "sacas refresh",
        "sacas expand",
        "sacas why",
        "sacas doctor",
        "sacas status",
        "sacas validate",
        "sacas pipeline orchestrate",
        "sacas pipeline stage",
        "sacas pipeline review",
        "sacas pipeline list",
    ):
        assert token in skill, f"SKILL.md must document {token}"
