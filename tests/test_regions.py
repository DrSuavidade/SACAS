"""Behavioral tests for SACAS schema and generated-file ownership."""

from __future__ import annotations

import json

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
