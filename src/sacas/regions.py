"""Safe replacement of explicitly SACAS-owned generated regions."""

from __future__ import annotations

import re


class RegionError(ValueError):
    """Raised when a generated region is absent, duplicated, or malformed."""


def replace_region(document: str, name: str, generated: str) -> str:
    """Replace exactly one named SACAS region without touching manual content."""
    _validate_name(name)
    start = re.compile(rf"<!-- SACAS:START {re.escape(name)} -->\r?\n?")
    end = re.compile(rf"<!-- SACAS:END {re.escape(name)} -->")
    starts = list(start.finditer(document))
    ends = list(end.finditer(document))
    if len(starts) != 1 or len(ends) != 1 or starts[0].start() >= ends[0].start():
        raise RegionError(f"Expected one complete SACAS region named {name!r}.")

    content = generated.replace("\r\n", "\n").strip("\n")
    replacement = f"{content}\n" if content else ""
    return document[: starts[0].end()] + replacement + document[ends[0].start() :]


def render_region(name: str, generated: str) -> str:
    """Render a deterministic, standalone generated region."""
    _validate_name(name)
    content = generated.replace("\r\n", "\n").strip("\n")
    body = f"{content}\n" if content else ""
    return f"<!-- SACAS:START {name} -->\n{body}<!-- SACAS:END {name} -->\n"


def _validate_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise RegionError("Region names may contain only letters, digits, '.', '_', and '-'.")
