"""Generate task contracts, checklist state, and disposable context."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from sacas.budget import calculate_context_size
from sacas.effects import calculate_task_effects
from sacas.graphify import read_graphify_manifest
from sacas.io import stable_json, write_text_atomic
from sacas.models import Manifest
from sacas.paths import Installation
from sacas.regions import render_generated_region, replace_generated_region
from sacas.state import (
    generate_pickup_markdown,
    parse_state_checkboxes,
    render_state_markdown,
)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """The result of generating a task."""

    task_id: str


def parse_protected_boundaries(boundaries_file: Path) -> tuple[tuple[str, str], ...]:
    """Parse MANUAL entries from the boundaries.md file."""
    boundaries: list[tuple[str, str]] = []
    if boundaries_file.is_file():
        try:
            content = boundaries_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.strip().startswith("MANUAL "):
                    parts = line.strip()[7:].split("|", 1)
                    path_prefix = parts[0].strip()
                    reason = parts[1].strip() if len(parts) > 1 else "Protected area"
                    boundaries.append((path_prefix, reason))
        except OSError:
            pass
    return tuple(boundaries)


def is_file_protected(file_path: str, boundaries: tuple[tuple[str, str], ...]) -> str | None:
    """Return the protection reason if the file path falls within a boundary, else None."""
    for path_prefix, reason in boundaries:
        if file_path.startswith(path_prefix):
            return reason
    return None


def generate_task(
    installation: Installation,
    goal: str,
    *,
    criteria: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    verification: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    symbols: tuple[str, ...] = (),
    tests: tuple[str, ...] = (),
    rules: tuple[str, ...] = ()
) -> TaskResult:
    """Create or update a SACAS task, generating its contract, context, and state."""
    criteria = tuple(criteria)
    constraints = tuple(constraints)
    verification = tuple(verification)
    files = tuple(files)
    symbols = tuple(symbols)
    tests = tuple(tests)
    rules = tuple(rules)

    # 1. Stable task ID
    task_id = hashlib.sha256(goal.strip().encode("utf-8")).hexdigest()[:8]

    # 2. Update manifest's current task
    manifest_path = installation.manifest_path
    old_manifest = installation.manifest
    new_manifest = Manifest(
        repository_root=old_manifest.repository_root,
        sacas_root=old_manifest.sacas_root,
        graphify_mode=old_manifest.graphify_mode,
        graphify_output=old_manifest.graphify_output,
        adapters=old_manifest.adapters,
        context_budget=old_manifest.context_budget,
        current_task_id=task_id,
        schema_version=old_manifest.schema_version,
    )
    write_text_atomic(manifest_path, stable_json(new_manifest.to_dict()))

    # Prepare current task directory
    task_dir = installation.sacas_root / "tasks" / "current"
    task_dir.mkdir(parents=True, exist_ok=True)

    # Write expansions.json
    expansions_path = task_dir / "expansions.json"
    initial_files = {}
    for f in files:
        f_path = installation.repository_root / f
        if f_path.is_file():
            try:
                content = f_path.read_bytes()
                initial_files[f] = hashlib.sha256(content).hexdigest()
            except OSError:
                initial_files[f] = ""
        else:
            initial_files[f] = ""

    expansions_data = {
        "initial_files": initial_files,
        "expanded_files": {},
        "goal": goal,
        "criteria": list(criteria),
        "constraints": list(constraints),
        "verification": list(verification),
        "symbols": list(symbols),
        "tests": list(tests),
        "rules": list(rules)
    }
    write_text_atomic(expansions_path, stable_json(expansions_data))

    # Regenerate all files
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        task_id=task_id,
        goal=goal,
        criteria=criteria,
        constraints=constraints,
        verification=verification,
        initial_files=files,
        expanded_files=(),
        symbols=symbols,
        tests=tests,
        rules=rules,
    )

    return TaskResult(task_id=task_id)


def regenerate_task_markdown(
    installation: Installation,
    task_dir: Path,
    task_id: str,
    goal: str,
    criteria: tuple[str, ...],
    constraints: tuple[str, ...],
    verification: tuple[str, ...],
    initial_files: tuple[str, ...],
    expanded_files: tuple[str, ...],
    symbols: tuple[str, ...],
    tests: tuple[str, ...],
    rules: tuple[str, ...],
) -> None:
    """Regenerate TASK.md, STATE.md, PICKUP.md, and CONTEXT.md deterministically."""
    # Read boundaries
    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(boundaries_file)

    # 4. Generate TASK.md
    task_md_path = task_dir / "TASK.md"
    crit_lines = [f"- {item} (EXPLICIT)" for item in criteria] if criteria else ["UNKNOWN"]
    const_lines = [f"- {item} (EXPLICIT)" for item in constraints] if constraints else ["UNKNOWN"]
    ver_lines = [f"- {item} (EXPLICIT)" for item in verification] if verification else ["UNKNOWN"]
    
    contract_lines = [
        f"Goal: {goal}",
        "",
        "### Acceptance Criteria",
        *crit_lines,
        "",
        "### Constraints",
        *const_lines,
        "",
        "### Verification",
        *ver_lines,
    ]
    contract_text = "\n".join(contract_lines) + "\n"
    
    if task_md_path.exists():
        old_text = task_md_path.read_text(encoding="utf-8")
        task_md_content = replace_generated_region(old_text, "task-contract", contract_text)
    else:
        task_md_content = f"# Task {task_id}\n\n" + render_generated_region("task-contract", contract_text)
    write_text_atomic(task_md_path, task_md_content)

    # 5. Generate STATE.md and PICKUP.md
    state_md_path = task_dir / "STATE.md"
    old_state_content = state_md_path.read_text(encoding="utf-8") if state_md_path.exists() else None
    state_text = render_state_markdown(task_id, goal, criteria, verification, old_content=old_state_content)
    
    if state_md_path.exists():
        state_md_content = replace_generated_region(old_state_content, "task-state", state_text)
    else:
        state_md_content = f"# Task State\n\n" + render_generated_region("task-state", state_text)
    write_text_atomic(state_md_path, state_md_content)

    # PICKUP.md
    pickup_md_path = task_dir / "PICKUP.md"
    completed, pending = parse_state_checkboxes(state_text)
    pickup_content = generate_pickup_markdown(completed, pending)
    write_text_atomic(pickup_md_path, pickup_content)

    # 6. Generate CONTEXT.md
    context_md_path = task_dir / "CONTEXT.md"
    graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
    evidence = None
    if graphify_manifest_path.is_file():
        try:
            evidence = read_graphify_manifest(graphify_manifest_path)
        except Exception:
            pass

    # Budget
    all_files = tuple(initial_files) + tuple(expanded_files)
    total_size = calculate_context_size(installation.repository_root, all_files)
    budget_limit = installation.manifest.context_budget

    # Effects
    effects_lines = []
    if evidence is not None:
        effects = calculate_task_effects(evidence, all_files)
        if effects:
            effects_lines.append("### Bounded Effects")
            for record in effects:
                effects_lines.append(f"- **{record.kind}**: `{record.path}` (Provenance: {record.provenance})")
        else:
            effects_lines.append("### Bounded Effects\nNone")
    else:
        effects_lines.append("### Bounded Effects\nGraphify evidence unavailable.")

    # Boundaries
    protected_files = []
    for file_path in all_files:
        reason = is_file_protected(file_path, parsed_boundaries)
        if reason:
            protected_files.append(f"- `{file_path}`: {reason}")

    protected_section = ""
    if protected_files:
        protected_section = "### Protected Boundaries\n" + "\n".join(protected_files) + "\n\n"

    # Context.md lines
    context_lines = ["## Files"]
    if initial_files:
        context_lines.extend(f"- `{f}`" for f in initial_files)
    if expanded_files:
        context_lines.append("")
        context_lines.append("### Expanded Files")
        context_lines.extend(f"- `{f}`" for f in expanded_files)
    if not initial_files and not expanded_files:
        context_lines.append("- None")
    context_lines.append("")
    
    context_lines.append("## Symbols")
    if symbols:
        context_lines.extend(f"- `{s}`" for s in symbols)
    else:
        context_lines.append("- None")
    context_lines.append("")
    
    context_lines.append("## Tests")
    if tests:
        context_lines.extend(f"- `{t}`" for t in tests)
    else:
        context_lines.append("- None")
    context_lines.append("")
    
    context_lines.append("## Rules")
    if rules:
        context_lines.extend(f"- `{r}`" for r in rules)
    else:
        context_lines.append("- None")
    context_lines.append("")
    
    if protected_section:
        context_lines.append(protected_section)
        
    context_lines.extend([
        "## Budget",
        f"- Limit: {budget_limit} tokens",
        f"- Estimated context size: {total_size} tokens",
        "",
        "## Evidence & Freshness",
        f"- Graphify Status: {evidence.status if evidence else 'unavailable'}",
        f"- Graphify Hash: {evidence.content_hash if (evidence and evidence.content_hash) else 'N/A'}",
        "",
    ])
    context_lines.extend(effects_lines)
    context_text = "\n".join(context_lines) + "\n"

    if context_md_path.exists():
        old_text = context_md_path.read_text(encoding="utf-8")
        context_md_content = replace_generated_region(old_text, "task-context", context_text)
    else:
        context_md_content = f"# Task Context\n\n" + render_generated_region("task-context", context_text)
    write_text_atomic(context_md_path, context_md_content)
