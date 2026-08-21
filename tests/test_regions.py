"""Behavioral tests for SACAS schema and generated-file ownership."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_manifest_serializes_stably_and_round_trips() -> None:
    from sacas.io import stable_json
    from sacas.models import Manifest, SCHEMA_VERSION

    manifest = Manifest(
        repository_root=".",
        sacas_root="Structure",
        adapters=("codex", "cursor"),
        context_budget=9_000,
    )

    rendered = stable_json(manifest.to_dict())

    assert rendered == (
        "{\n"
        '  "adapters": [\n'
        '    "codex",\n'
        '    "cursor"\n'
        "  ],\n"
        '  "context_budget": 9000,\n'
        '  "current_task_id": null,\n'
        '  "graphify_mode": "off",\n'
        '  "graphify_output": "graphify-out",\n'
        '  "repository_root": ".",\n'
        '  "sacas_root": "Structure",\n'
        f'  "schema_version": {SCHEMA_VERSION}\n'
        "}\n"
    )
    assert Manifest.from_dict(json.loads(rendered)) == manifest


def test_manifest_rejects_unsupported_schema_version() -> None:
    from sacas.models import Manifest, SchemaVersionError

    with pytest.raises(SchemaVersionError, match="schema version"):
        Manifest.from_dict({"schema_version": 999})


def test_minimal_current_schema_manifest_uses_all_defaults() -> None:
    from sacas.models import Manifest, SCHEMA_VERSION

    manifest = Manifest.from_dict({"schema_version": SCHEMA_VERSION})

    assert manifest == Manifest()


@pytest.mark.parametrize("data", [[], "not a manifest", 42])
def test_manifest_rejects_non_object_json_roots_with_controlled_error(data: object) -> None:
    from sacas.models import Manifest

    with pytest.raises(ValueError, match="manifest"):
        Manifest.from_dict(data)  # type: ignore[arg-type]


def test_manifest_converts_directly_supplied_mutable_adapters_to_an_immutable_tuple() -> None:
    from sacas.models import Manifest

    supplied_adapters = ["codex"]
    manifest = Manifest(adapters=supplied_adapters)  # type: ignore[arg-type]
    supplied_adapters.append("cursor")

    assert manifest.adapters == ("codex",)
    assert isinstance(manifest.adapters, tuple)


def test_manifest_rejects_unknown_graphify_mode() -> None:
    from sacas.models import Manifest

    with pytest.raises(ValueError, match="graphify_mode"):
        Manifest(graphify_mode="automatic")


@pytest.mark.parametrize("mode", [[], ""])
def test_manifest_rejects_non_string_or_empty_graphify_mode(mode: object) -> None:
    from sacas.models import Manifest

    with pytest.raises(ValueError, match="graphify_mode"):
        Manifest(graphify_mode=mode)  # type: ignore[arg-type]


def test_manifest_rejects_empty_current_task_id() -> None:
    from sacas.models import Manifest

    with pytest.raises(ValueError, match="current_task_id"):
        Manifest(current_task_id="")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"adapters": "codex"},
        {"adapters": 42},
        {"repository_root": ""},
        {"sacas_root": ""},
        {"graphify_output": ""},
        {"current_task_id": 42},
    ],
)
def test_manifest_direct_constructor_validates_machine_fields(kwargs: dict[str, object]) -> None:
    from sacas.models import Manifest

    with pytest.raises((TypeError, ValueError)):
        Manifest(**kwargs)  # type: ignore[arg-type]


def test_write_json_atomic_is_deterministic(tmp_path: Path) -> None:
    from sacas.io import write_json_atomic

    target = tmp_path / "nested" / "manifest.json"

    write_json_atomic(target, {"z": 1, "a": ["é"]})
    first_write = target.read_text(encoding="utf-8")
    write_json_atomic(target, {"a": ["é"], "z": 1})

    assert first_write == target.read_text(encoding="utf-8")
    assert first_write == '{\n  "a": [\n    "é"\n  ],\n  "z": 1\n}\n'


def test_write_text_atomic_normalizes_all_carriage_return_variants(tmp_path: Path) -> None:
    from sacas.io import write_text_atomic

    target = tmp_path / "text.txt"
    write_text_atomic(target, "one\rtwo\r\nthree\n")

    assert target.read_text(encoding="utf-8") == "one\ntwo\nthree\n"


@pytest.mark.parametrize("failure_name", ["fsync", "replace"])
def test_write_text_atomic_removes_temp_file_after_persistence_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_name: str
) -> None:
    from sacas import io

    target = tmp_path / "nested" / "text.txt"

    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated persistence failure")

    monkeypatch.setattr(io.os, failure_name, fail)

    with pytest.raises(OSError, match="simulated persistence failure"):
        io.write_text_atomic(target, "content")

    assert list(target.parent.iterdir()) == []


def test_replace_region_changes_only_owned_region_and_preserves_manual_text() -> None:
    from sacas.regions import replace_region

    source = (
        "# Router\n"
        "This introduction is human-authored.\n\n"
        "<!-- SACAS:START router -->\n"
        "old generated content\n"
        "<!-- SACAS:END router -->\n\n"
        "This footer is human-authored.\n"
    )

    rendered = replace_region(source, "router", "new generated content\nwith a second line")

    assert rendered == (
        "# Router\n"
        "This introduction is human-authored.\n\n"
        "<!-- SACAS:START router -->\n"
        "new generated content\n"
        "with a second line\n"
        "<!-- SACAS:END router -->\n\n"
        "This footer is human-authored.\n"
    )


def test_generated_region_helpers_normalize_lone_carriage_returns() -> None:
    from sacas.regions import render_generated_region, replace_generated_region

    source = "<!-- SACAS:START router -->\nold\n<!-- SACAS:END router -->\n"
    generated = "first\rsecond\r\nthird\n"

    assert render_generated_region("router", generated) == (
        "<!-- SACAS:START router -->\nfirst\nsecond\nthird\n<!-- SACAS:END router -->\n"
    )
    assert replace_generated_region(source, "router", generated) == (
        "<!-- SACAS:START router -->\nfirst\nsecond\nthird\n<!-- SACAS:END router -->\n"
    )


@pytest.mark.parametrize(
    "document",
    [
        "no generated region\n",
        "<!-- SACAS:START router -->\nmissing end\n",
        (
            "<!-- SACAS:START router -->\nfirst\n<!-- SACAS:END router -->\n"
            "<!-- SACAS:START router -->\nsecond\n<!-- SACAS:END router -->\n"
        ),
    ],
)
def test_replace_region_rejects_missing_malformed_or_duplicate_ownership(document: str) -> None:
    from sacas.regions import RegionError, replace_region

    with pytest.raises(RegionError, match="complete SACAS region"):
        replace_region(document, "router", "replacement")


def test_extract_symbol_range_python() -> None:
    from sacas.regions import extract_symbol_range
    content = (
        "def outer():\n"
        "    x = 1\n"
        "    def inner():\n"
        "        pass\n"
        "    return inner\n"
        "\n"
        "def second():\n"
        "    pass\n"
    )
    # Start at def outer() (line 1)
    start, end = extract_symbol_range(content, 1, "test.py")
    assert (start, end) == (1, 6)

    # Start at def inner() (line 3)
    start, end = extract_symbol_range(content, 3, "test.py")
    assert (start, end) == (3, 4)


def test_extract_symbol_range_braces() -> None:
    from sacas.regions import extract_symbol_range
    content = (
        "function foo() {\n"
        "    const x = { a: 1 };\n"
        "    if (true) {\n"
        "        console.log(x);\n"
        "    }\n"
        "}\n"
        "function bar() {}\n"
    )
    start, end = extract_symbol_range(content, 1, "test.js")
    assert (start, end) == (1, 6)


def test_extract_markdown_section() -> None:
    from sacas.regions import extract_markdown_section
    content = (
        "# Main\n"
        "## Sub1\n"
        "Content of sub1\n"
        "## Sub2\n"
        "### Configuration\n"
        "Config details\n"
        "## Sub3\n"
        "### Configuration\n"
        "Sub3 config details\n"
    )
    # Extract Sub2 -> Configuration
    sec1 = extract_markdown_section(content, ["Sub2", "Configuration"])
    assert "Config details" in sec1
    assert "Sub3 config details" not in sec1

    # Extract Sub3 -> Configuration
    sec2 = extract_markdown_section(content, ["Sub3", "Configuration"])
    assert "Sub3 config details" in sec2
    assert "Config details" not in sec2


def test_markdown_section_range_rejects_cross_parent_hierarchy() -> None:
    """A child heading under a sibling parent must never complete a hierarchy."""
    from sacas.regions import extract_markdown_section, find_markdown_section_range

    content = (
        "# Authentication\n"
        "## Overview\n"
        "Auth overview\n"
        "# Payments\n"
        "## Configuration\n"
        "Payments config\n"
    )

    # Authentication > Configuration does not exist: Overview closes nothing,
    # but Payments (level 1) closes the Authentication ancestor before any
    # Configuration heading appears.
    assert find_markdown_section_range(content, ["Authentication", "Configuration"]) is None
    section = extract_markdown_section(content, ["Authentication", "Configuration"])
    assert section == content

    # The real sections still resolve with exact ranges
    assert find_markdown_section_range(content, ["Authentication", "Overview"]) == (2, 3)
    assert find_markdown_section_range(content, ["Payments", "Configuration"]) == (5, 6)

    # A later valid occurrence after an abandoned partial match still resolves
    resumed = (
        "# Auth\n"
        "# Payments\n"
        "## Config\n"
        "Payments config\n"
    )
    assert find_markdown_section_range(resumed, ["Auth", "Config"]) is None
    other = (
        "# Guide\n"
        "## Setup\n"
        "# Recipes\n"
        "## Configuration\n"
        "Recipes config\n"
    )
    assert find_markdown_section_range(other, ["Guide", "Configuration"]) is None
