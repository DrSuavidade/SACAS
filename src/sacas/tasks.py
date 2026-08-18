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
    p_parts = Path(file_path).parts
    for path_prefix, reason in boundaries:
        b_parts = Path(path_prefix).parts
        if len(p_parts) >= len(b_parts) and p_parts[:len(b_parts)] == b_parts:
            return reason
    return None


def get_initial_files(expansions: dict) -> dict[str, str]:
    if expansions.get("schema_version") == 2:
        return {item["path"]: item.get("hash", "") for item in expansions.get("initial_scope", [])}
    return expansions.get("initial_files", {})


def get_expanded_files(expansions: dict) -> dict[str, str]:
    if expansions.get("schema_version") == 2:
        return {item["path"]: item.get("hash", "") for item in expansions.get("expansions", [])}
    return expansions.get("expanded_files", {})


def get_git_commit(root: Path) -> str:
    import subprocess
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False
        )
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout.strip()
    except OSError:
        pass
    return "unknown"


def extract_keywords(goal: str) -> list[str]:
    import re
    words = re.findall(r"\b[a-zA-Z0-9]{3,}\b", goal.lower())
    return list(dict.fromkeys(words))


def score_file_against_goal(filepath: str, file_content: str, keywords: list[str]) -> tuple[int, list[str]]:
    import re
    score = 0
    filename = Path(filepath).name.lower()
    matched_keywords = []

    for kw in keywords:
        if kw in filename:
            score += 4
            matched_keywords.append(kw)
            if filename.startswith(kw):
                score += 2

    if "test" in filename:
        for kw in keywords:
            if kw != "test" and kw in filename:
                score += 4
                if kw not in matched_keywords:
                    matched_keywords.append(kw)

    components = [p.lower() for p in Path(filepath).parent.parts]
    for kw in keywords:
        for comp in components:
            if kw in comp:
                score += 3
                if kw not in matched_keywords:
                    matched_keywords.append(kw)

    for kw in keywords:
        pattern = rf"\b(class|def|fn|struct|interface|function)\b\s+\w*{re.escape(kw)}\w*"
        matches = re.findall(pattern, file_content, re.IGNORECASE)
        if matches:
            score += 5 * len(matches)
            if kw not in matched_keywords:
                matched_keywords.append(kw)

    return score, matched_keywords


def run_fallback_routing(root: Path, goal: str, boundaries: tuple[tuple[str, str], ...], commit: str) -> list[dict]:
    keywords = extract_keywords(goal)
    if not keywords:
        return []

    ignored = {".git", ".sacas", "__pycache__", "Structure", "graphify-out", ".worktrees"}
    candidates = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in ignored for part in relative.parts):
            continue

        rel_str = relative.as_posix()
        if is_file_protected(rel_str, boundaries):
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            content = ""

        score, matched = score_file_against_goal(rel_str, content, keywords)
        if score > 0:
            candidates.append((score, rel_str, matched))

    candidates.sort(key=lambda s: (-s[0], len(s[1]), s[1]))

    results = []
    for score, filepath, matched in candidates[:5]:
        try:
            f_hash = hashlib.sha256((root / filepath).read_bytes()).hexdigest()
        except OSError:
            f_hash = ""

        results.append({
            "path": filepath,
            "symbols": [],
            "reason": f"Matched heuristic scoring (score={score}) matching keywords: {', '.join(matched)}",
            "source": "heuristic",
            "confidence": "high" if score >= 8 else "medium",
            "relation": "keyword_match",
            "trigger": "task_goal",
            "git_revision": commit,
            "hash": f_hash
        })
    return results


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
    from sacas.graphify import GraphifyAdapter

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

    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(boundaries_file)

    commit = get_git_commit(installation.repository_root)
    initial_scope_list = []

    if files:
        for f in files:
            from sacas.paths import resolve_repo_path
            try:
                f_rel = resolve_repo_path(installation.repository_root, f)
            except ValueError:
                continue

            f_path = installation.repository_root / f_rel
            f_hash = ""
            if f_path.is_file():
                try:
                    f_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                except OSError:
                    pass
            initial_scope_list.append({
                "path": f_rel,
                "symbols": list(symbols),
                "reason": "Explicitly specified by user",
                "source": "explicit",
                "confidence": "high",
                "relation": None,
                "trigger": "cli_arg",
                "git_revision": commit,
                "hash": f_hash
            })
    else:
        graphify_success = False
        if old_manifest.graphify_mode != "off":
            adapter = GraphifyAdapter(installation.repository_root, installation.sacas_root)
            if adapter.verify_capabilities(required=["extract", "query"]):
                graph_path = installation.repository_root / old_manifest.graphify_output / "graph.json"
                query_res = adapter.query(goal, graph_path)
                if query_res and adapter.validate_query_contract(query_res):
                    for path in query_res.paths:
                        from sacas.paths import resolve_repo_path
                        try:
                            f_rel = resolve_repo_path(installation.repository_root, path)
                        except ValueError:
                            continue

                        if is_file_protected(f_rel, parsed_boundaries):
                            continue

                        f_path = installation.repository_root / f_rel
                        f_hash = ""
                        if f_path.is_file():
                            try:
                                f_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                            except OSError:
                                pass
                        initial_scope_list.append({
                            "path": f_rel,
                            "symbols": [],
                            "reason": f"Discovered via Graphify query matching goal: {goal}",
                            "source": "graphify",
                            "confidence": "high",
                            "relation": "seed",
                            "trigger": "task_goal",
                            "git_revision": commit,
                            "hash": f_hash
                        })
                    graphify_success = len(initial_scope_list) > 0

        if not graphify_success:
            initial_scope_list = run_fallback_routing(installation.repository_root, goal, parsed_boundaries, commit)

    if not initial_scope_list:
        import sys
        print(f"WARNING: Task contains zero source files/symbols and no routing evidence was discovered.", file=sys.stderr)

    expansions_path = task_dir / "expansions.json"
    expansions_data = {
        "schema_version": 2,
        "task_id": task_id,
        "goal": goal,
        "criteria": list(criteria),
        "constraints": list(constraints),
        "verification": list(verification),
        "symbols": list(symbols),
        "tests": list(tests),
        "rules": list(rules),
        "initial_scope": initial_scope_list,
        "expansions": [],
        "adjacent": []
    }
    write_text_atomic(expansions_path, stable_json(expansions_data))

    initial_files = tuple(item["path"] for item in initial_scope_list)
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        task_id=task_id,
        goal=goal,
        criteria=criteria,
        constraints=constraints,
        verification=verification,
        initial_files=initial_files,
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
