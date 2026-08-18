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
