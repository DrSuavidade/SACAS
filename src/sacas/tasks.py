"""Generate task contracts, checklist state, and disposable context."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from sacas.budget import calculate_context_size, calculate_manifest_tokens
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
from sacas.active_context import (
    ActiveContextManifest,
    ActiveFileContext,
    ActiveSymbolContext,
    SourceRange,
    ActiveRuleContext,
    ActiveReferenceContext,
    AdmissionEvent,
    ContextBudgetState,
    ContextPolicyState,
    save_active_context,
    load_active_context,
    enforce_cursor_negation_patterns,
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
    stop_words = {
        "fix", "add", "change", "update", "bug", "issue", "make", "implement",
        "test", "logic", "refactor", "code", "the", "and", "for"
    }
    filtered = [w for w in words if w not in stop_words]
    return list(dict.fromkeys(filtered))



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


def run_fallback_routing(root: Path, sacas_root: Path, goal: str, boundaries: tuple[tuple[str, str], ...], commit: str) -> list[dict]:
    keywords = extract_keywords(goal)
    if not keywords:
        return []

    from sacas.search import FallbackIndex
    index = FallbackIndex(root, sacas_root)
    index.update()
    
    candidates = index.search(goal)

    results = []
    for score, filepath, matched in candidates[:5]:
        if is_file_protected(filepath, boundaries):
            continue
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


def route_rules_and_references(
    sacas_root: Path,
    goal: str,
    explicit_rules: tuple[str, ...],
    explicit_refs: tuple[str, ...]
) -> tuple[list[ActiveRuleContext], list[ActiveReferenceContext]]:
    import re
    from sacas.tasks import extract_keywords
    keywords = extract_keywords(goal)
    
    rules_list = []
    refs_list = []
    
    # 1. Rules
    if explicit_rules:
        for r in explicit_rules:
            r_clean = r.replace("\\", "/")
            if not r_clean.startswith("Structure/"):
                r_rel = "Structure/" + r_clean
            else:
                r_rel = r_clean
            rules_list.append(ActiveRuleContext(path=r_rel, hash="", reason="Explicitly specified by user"))
    else:
        # Heuristic rules routing
        rules_dir = sacas_root / "rules"
        if rules_dir.is_dir():
            for p in rules_dir.rglob("*.md"):
                rel_path = "Structure/" + p.relative_to(sacas_root).as_posix()
                filename = p.name.lower()
                # Default: always load boundaries.md if it exists, otherwise check keywords
                if filename == "boundaries.md" or any(kw in filename for kw in keywords):
                    rules_list.append(ActiveRuleContext(path=rel_path, hash="", reason="Heuristic rule match"))
                    
    # 2. References
    if explicit_refs:
        for r in explicit_refs:
            path_part = r
            section_anchor = None
            if "#" in r:
                path_part, section_anchor = r.split("#", 1)
                
            path_part_clean = path_part.replace("\\", "/")
            if not path_part_clean.startswith("Structure/"):
                r_rel = "Structure/" + path_part_clean
            else:
                r_rel = path_part_clean
                
            if section_anchor:
                heading_path = [section_anchor.replace("-", " ").title()]
                sel = {"mode": "sections", "sections": [{"heading_path": heading_path}]}
            else:
                sel = {"mode": "full"}
                
            refs_list.append(ActiveReferenceContext(path=r_rel, selection=sel, hash="", reason="Explicitly specified by user"))
    else:
        # Heuristic references routing
        refs_dir = sacas_root / "references"
        if refs_dir.is_dir():
            for p in refs_dir.rglob("*.md"):
                rel_path = "Structure/" + p.relative_to(sacas_root).as_posix()
                filename = p.name.lower()
                
                # Check keyword match in filename
                if any(kw in filename for kw in keywords):
                    try:
                        content = p.read_text(encoding="utf-8")
                        matched_headings = []
                        for line in content.splitlines():
                            if line.startswith("#"):
                                match = re.match(r"^(#+)\s+(.+)$", line)
                                if match:
                                    heading_text = match.group(2).strip()
                                    if any(kw in heading_text.lower() for kw in keywords):
                                        matched_headings.append(heading_text)
                        
                        if matched_headings and len(matched_headings) < 3:
                            sel = {"mode": "sections", "sections": [{"heading_path": [h]} for h in matched_headings]}
                            reason = f"Heuristic reference section match for: {', '.join(matched_headings)}"
                        else:
                            sel = {"mode": "full"}
                            reason = "Heuristic reference file match"
                    except OSError:
                        sel = {"mode": "full"}
                        reason = "Heuristic reference file match"
                        
                    refs_list.append(ActiveReferenceContext(path=rel_path, selection=sel, hash="", reason=reason))
                    
    return rules_list, refs_list


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
    rules: tuple[str, ...] = (),
    references: tuple[str, ...] = (),
    category: str | None = None
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
    references = tuple(references)

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
    active_files = []
    events = []

    # Infer category
    if not category:
        goal_lower = goal.lower()
        if "test" in goal_lower:
            category = "test"
        elif "refactor" in goal_lower:
            category = "refactor"
        elif any(kw in goal_lower for kw in ("fix", "bug", "crash", "error", "issue")):
            category = "bugfix"
        elif any(kw in goal_lower for kw in ("add", "implement", "new", "feature")):
            category = "feature"
        else:
            category = "bugfix"

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

            # Repeat symbols syntax helper
            file_symbols = []
            for sym in symbols:
                if "::" in sym:
                    sym_file, sym_name = sym.split("::", 1)
                    if sym_file == f or sym_file == f_rel:
                        file_symbols.append(ActiveSymbolContext(name=sym_name, range=None, reason="Explicitly specified by user"))
                else:
                    file_symbols.append(ActiveSymbolContext(name=sym, range=None, reason="Explicitly specified by user"))

            sel = {"mode": "symbols", "symbols": file_symbols} if file_symbols else {"mode": "full"}
            active_files.append(ActiveFileContext(
                path=f_rel,
                selection=sel,
                source="explicit",
                confidence="high",
                relation=None,
                trigger="initial_route",
                git_revision=commit,
                reason="Explicitly specified by user",
                hash=f_hash
            ))
            events.append(AdmissionEvent(
                id=f"evt-init-{len(events):03d}",
                target=f_rel,
                action="admit",
                source="explicit",
                reason="Explicitly specified by user",
                trigger="initial_route"
            ))
    else:
        graphify_success = False
        initial_scope_paths = []
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
                        
                        active_files.append(ActiveFileContext(
                            path=f_rel,
                            selection={"mode": "full"},
                            source="graphify",
                            confidence="high",
                            relation="seed",
                            trigger="task_goal",
                            git_revision=commit,
                            reason=f"Discovered via Graphify query matching goal: {goal}",
                            hash=f_hash
                        ))
                        events.append(AdmissionEvent(
                            id=f"evt-init-{len(events):03d}",
                            target=f_rel,
                            action="admit",
                            source="graphify",
                            reason=f"Discovered via Graphify query matching goal: {goal}",
                            trigger="initial_route"
                        ))
                    graphify_success = len(active_files) > 0

        if not graphify_success:
            # Fallback Lexical Search
            fallback_results = run_fallback_routing(installation.repository_root, installation.sacas_root, goal, parsed_boundaries, commit)
            for item in fallback_results:
                active_files.append(ActiveFileContext(
                    path=item["path"],
                    selection={"mode": "full"},
                    source="heuristic",
                    confidence=item["confidence"],
                    relation=item["relation"],
                    trigger="task_goal",
                    git_revision=commit,
                    reason=item["reason"],
                    hash=item["hash"]
                ))
                events.append(AdmissionEvent(
                    id=f"evt-init-{len(events):03d}",
                    target=item["path"],
                    action="admit",
                    source="heuristic",
                    reason=item["reason"],
                    trigger="initial_route"
                ))

    if not active_files:
        import sys
        print(f"WARNING: Task contains zero source files/symbols and no routing evidence was discovered.", file=sys.stderr)

    rules_list, refs_list = route_rules_and_references(installation.sacas_root, goal, rules, references)

    # Hash rules
    hashed_rules = []
    for r in rules_list:
        r_path = installation.repository_root / r.path
        r_hash = ""
        if r_path.is_file():
            try:
                r_hash = hashlib.sha256(r_path.read_bytes()).hexdigest()
            except OSError:
                pass
        hashed_rules.append(ActiveRuleContext(path=r.path, hash=r_hash, reason=r.reason))

    # Hash references
    hashed_refs = []
    for ref in refs_list:
        ref_path = installation.repository_root / ref.path
        ref_hash = ""
        if ref_path.is_file():
            try:
                ref_hash = hashlib.sha256(ref_path.read_bytes()).hexdigest()
            except OSError:
                pass
        hashed_refs.append(ActiveReferenceContext(path=ref.path, selection=ref.selection, hash=ref_hash, reason=ref.reason))

    # Construct manifest without budget yet
    manifest = ActiveContextManifest(
        task_id=task_id,
        goal=goal,
        category=category,
        git_revision=commit,
        files=tuple(active_files),
        rules=tuple(hashed_rules),
        references=tuple(hashed_refs),
        events=tuple(events),
        budget=None,
        policy=ContextPolicyState(
            requested="advisory",
            effective="advisory",
            provider="advisory",
            file_reads="enforced" if len(active_files) > 0 else "advisory",
            terminal_reads="advisory",
            mcp_reads="advisory"
        ),
        tests=tests
    )

    # Save active_context.json
    save_active_context(task_dir, manifest)
    enforce_cursor_negation_patterns(installation, manifest)

    # Regenerate task markdown which will calculate budget and update manifest
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        manifest=manifest,
        criteria=criteria,
        constraints=constraints,
        verification=verification
    )

    return TaskResult(task_id=task_id)


def regenerate_task_markdown(
    installation: Installation,
    task_dir: Path,
    manifest: ActiveContextManifest,
    criteria: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    verification: tuple[str, ...] = (),
) -> None:
    """Regenerate TASK.md, STATE.md, PICKUP.md, and CONTEXT.md deterministically."""
    # 4. Generate TASK.md
    task_md_path = task_dir / "TASK.md"
    crit_lines = [f"- {item} (EXPLICIT)" for item in criteria] if criteria else ["UNKNOWN"]
    const_lines = [f"- {item} (EXPLICIT)" for item in constraints] if constraints else ["UNKNOWN"]
    ver_lines = [f"- {item} (EXPLICIT)" for item in verification] if verification else ["UNKNOWN"]
    
    contract_lines = [
        f"Goal: {manifest.goal}",
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
        task_md_content = f"# Task {manifest.task_id}\n\n" + render_generated_region("task-contract", contract_text)
    write_text_atomic(task_md_path, task_md_content)

    # 5. Generate STATE.md and PICKUP.md
    state_md_path = task_dir / "STATE.md"
    old_state_content = state_md_path.read_text(encoding="utf-8") if state_md_path.exists() else None
    state_text = render_state_markdown(manifest.task_id, manifest.goal, criteria, verification, old_content=old_state_content)
    
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

    # Calculate unified budget
    breakdown = calculate_manifest_tokens(installation, manifest)
    budget_state = ContextBudgetState(
        limit=breakdown.limit,
        used=breakdown.used,
        tokenizer=breakdown.tokenizer,
        source_tokens=breakdown.source_tokens,
        rule_tokens=breakdown.rule_tokens,
        reference_tokens=breakdown.reference_tokens,
        control_tokens=breakdown.control_tokens
    )

    # Save active_context.json with updated budget
    manifest = ActiveContextManifest(
        task_id=manifest.task_id,
        goal=manifest.goal,
        category=manifest.category,
        git_revision=manifest.git_revision,
        files=manifest.files,
        rules=manifest.rules,
        references=manifest.references,
        events=manifest.events,
        budget=budget_state,
        policy=manifest.policy,
        tests=manifest.tests,
        schema_version=manifest.schema_version
    )
    save_active_context(task_dir, manifest)

    # 6. Generate CONTEXT.md
    context_md_path = task_dir / "CONTEXT.md"
    
    graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
    evidence = None
    if graphify_manifest_path.is_file():
        try:
            evidence = read_graphify_manifest(graphify_manifest_path)
        except Exception:
            pass

    # Read boundaries
    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(boundaries_file)

    # Bounded Effects
    effects_lines = []
    all_files = tuple(f.path for f in manifest.files)
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
    for f in manifest.files:
        reason = is_file_protected(f.path, parsed_boundaries)
        if reason:
            protected_files.append(f"- `{f.path}`: {reason}")

    protected_section = ""
    if protected_files:
        protected_section = "### Protected Boundaries\n" + "\n".join(protected_files) + "\n\n"

    # Context.md lines
    context_lines = ["## Files"]
    initial_files = [f.path for f in manifest.files if f.trigger == "initial_route"]
    expanded_files = [f.path for f in manifest.files if f.trigger != "initial_route"]

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
    symbols_present = False
    for f in manifest.files:
        if f.selection.get("mode") == "symbols":
            for sym in f.selection.get("symbols", []):
                symbols_present = True
                rng_str = f" L{sym.range.start_line}-L{sym.range.end_line}" if sym.range else ""
                context_lines.append(f"- `{f.path}::{sym.name}`{rng_str}")
    if not symbols_present:
        context_lines.append("- None")
    context_lines.append("")
    
    context_lines.append("## Tests")
    if manifest.tests:
        context_lines.extend(f"- `{t}`" for t in manifest.tests)
    else:
        context_lines.append("- None")
    context_lines.append("")
    
    context_lines.append("## Rules")
    if manifest.rules:
        context_lines.extend(f"- `{r.path}`" for r in manifest.rules)
    else:
        context_lines.append("- None")
    context_lines.append("")

    context_lines.append("## References")
    if manifest.references:
        for ref in manifest.references:
            if ref.selection.get("mode") == "sections":
                sec_names = ", ".join(" > ".join(sec.get("heading_path", [])) for sec in ref.selection.get("sections", []))
                context_lines.append(f"- `{ref.path}` (Sections: {sec_names})")
            else:
                context_lines.append(f"- `{ref.path}`")
    else:
        context_lines.append("- None")
    context_lines.append("")
    
    if protected_section:
        context_lines.append(protected_section)
        
    context_lines.extend([
        "## Budget",
        f"- Limit: {breakdown.limit} tokens",
        f"- Estimated context size: {breakdown.used} tokens",
        f"  - Payload: {breakdown.source_tokens} source, {breakdown.rule_tokens} rules, {breakdown.reference_tokens} references",
        f"  - Control: {breakdown.control_tokens} task documents",
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
