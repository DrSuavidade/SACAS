"""Generate small, platform-neutral pointers to the canonical SACAS router."""

from __future__ import annotations

from pathlib import Path

from sacas.io import write_text_atomic
from sacas.regions import render_generated_region, replace_generated_region


DEFAULT_ADAPTERS = ("codex", "claude", "cursor", "copilot", "gemini")

_ADAPTER_PATHS = {
    "codex": Path("AGENTS.md"),
    "claude": Path("CLAUDE.md"),
    "cursor": Path(".cursor") / "rules" / "sacas.mdc",
    "copilot": Path(".github") / "copilot-instructions.md",
    "gemini": Path("GEMINI.md"),
}

_IGNORE_PATHS = {
    "codex": Path(".aiignore"),
    "claude": Path(".claudeignore"),
    "cursor": Path(".cursorignore"),
    "gemini": Path(".geminiignore"),
}


def generate_adapter(repository_root: Path | str, sacas_root: str, platform: str) -> bool:
    """Write one platform entry point while retaining all non-SACAS prose."""
    root = Path(repository_root).resolve()
    target = root / _path_for(_ADAPTER_PATHS, platform)
    router = Path(sacas_root).as_posix().rstrip("/") + "/ROUTER.md"
    generated = (
        "## SACAS\n\n"
        f"Read `{router}` before acting. It is the canonical entry point for SACAS "
        "rules, task context, and generated navigation."
    )
    if platform == "copilot":
        generated += (
            "\n\nGitHub Copilot does not provide a repository-local ignore file. "
            "Configure exclusions through administrator settings; in agent mode, verify "
            "that the configured repository and organization policies apply."
        )
    return _replace_or_append(target, f"adapter-{platform}", generated)


def generate_adapter_ignore(
    repository_root: Path | str,
    sacas_root: str,
    platform: str,
    *,
    graphify_output: str = "graphify-out",
) -> bool:
    """Add bounded ignore rules for generated data to one agent platform."""
    if platform == "copilot":
        _path_for(_ADAPTER_PATHS, platform)
        return False
    root = Path(repository_root).resolve()
    target = root / _path_for(_IGNORE_PATHS, platform)
    output = _root_relative_directory(graphify_output)
    generated = "# SACAS generated data\n" + _sacas_metadata_ignore(sacas_root) + "\n" + output
    return _replace_or_append(target, f"ignore-{platform}", generated)


def generate_adapters(
    repository_root: Path | str,
    sacas_root: str,
    *,
    platforms: tuple[str, ...] = DEFAULT_ADAPTERS,
    graphify_output: str = "graphify-out",
) -> bool:
    """Generate the configured platform pointers and their matching ignore files."""
    changed = False
    for platform in platforms:
        changed |= generate_adapter(repository_root, sacas_root, platform)
        changed |= generate_adapter_ignore(
            repository_root, sacas_root, platform, graphify_output=graphify_output
        )
    return changed


def _replace_or_append(target: Path, region_name: str, generated: str) -> bool:
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    marker = f"<!-- SACAS:START {region_name} -->"
    if marker in existing:
        rendered = replace_generated_region(existing, region_name, generated)
    else:
        separator = "" if not existing or existing.endswith("\n\n") else "\n"
        rendered = existing + separator + render_generated_region(region_name, generated)
    if rendered == existing:
        return False
    write_text_atomic(target, rendered)
    return True


def _path_for(paths: dict[str, Path], platform: str) -> Path:
    try:
        return paths[platform]
    except KeyError as error:
        supported = ", ".join(DEFAULT_ADAPTERS)
        raise ValueError(f"Unsupported adapter {platform!r}; supported adapters: {supported}.") from error


def _root_relative_directory(value: str) -> str:
    normalized = value.replace("\\", "/").strip("/")
    if not normalized or "/" in normalized or normalized in {".", ".."}:
        raise ValueError("graphify_output must be a root-level directory name")
    return normalized + "/"


def _sacas_metadata_ignore(sacas_root: str) -> str:
    normalized = sacas_root.replace("\\", "/").strip("/")
    if normalized in {"", "."}:
        return ".sacas/"
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("sacas_root must be relative to the repository")
    return normalized + "/.sacas/"
