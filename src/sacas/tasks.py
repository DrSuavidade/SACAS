"""Generate task contracts, checklist state, and disposable context."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

from sacas.budget import calculate_context_size, calculate_manifest_tokens
from sacas.effects import calculate_task_effects
from sacas.graphify import read_graphify_manifest
from sacas.io import stable_json, write_text_atomic, read_repo_source_bytes, read_repo_text
from sacas.models import Manifest
from sacas.paths import (
    Installation,
    normalize_sacas_document_path,
    sacas_child_repo_path,
)


EXPLICIT_CONTEXT_REASON = "Explicitly specified by user"

# Admissions stop at the first ranked path scoring below this fraction of the
# best-ranked score, with an absolute floor of one strong token match (4).
# Real-repo sweeps showed pure relative cutoffs are no-ops because directory
# bonuses cluster scores; the floor removes directory-bonus-only admissions.
GOAL_RANK_CUTOFF_RATIO_NUM = 35
GOAL_RANK_CUTOFF_RATIO_DEN = 100
GOAL_RANK_CUTOFF_FLOOR = 4


def is_explicit_rule_or_reference(reason: str | None) -> bool:
    """Return whether a rule/reference originated from explicit user input."""
    return reason == EXPLICIT_CONTEXT_REASON
from sacas.regions import render_generated_region, replace_generated_region
from sacas.regions import resolve_section_ranges
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
)
from sacas.compiler import (
    compile_context_pack,
    validate_context_pack_records,
    validate_context_pack_against_state,
    write_context_pack,
)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """The result of generating a task."""

    task_id: str


def parse_protected_boundaries(
    repository_root: Path, boundaries_file: Path
) -> tuple[tuple[str, str], ...]:
    """Parse MANUAL entries from the boundaries.md file."""
    boundaries: list[tuple[str, str]] = []
    try:
        relative = boundaries_file.relative_to(repository_root).as_posix()
        content = read_repo_text(repository_root, relative, allow_ignored=True)
    except (ValueError, FileNotFoundError, OSError):
        return ()
    for line in content.splitlines():
        if line.strip().startswith("MANUAL "):
            parts = line.strip()[7:].split("|", 1)
            path_prefix = parts[0].strip()
            reason = parts[1].strip() if len(parts) > 1 else "Protected area"
            boundaries.append((path_prefix, reason))
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


def lexical_query_hash(goal: str) -> str:
    """Stable hash of the normalized lexical routing query."""
    normalized = " ".join(goal.lower().split())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()



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


def _source_hash(repository_root: Path, relative_path: str) -> str | None:
    """Return a source hash only when the repository boundary admits the file."""
    try:
        return hashlib.sha256(read_repo_source_bytes(repository_root, relative_path)).hexdigest()
    except (ValueError, FileNotFoundError, OSError):
        return None


def run_fallback_routing(root: Path, sacas_root: Path, goal: str, boundaries: tuple[tuple[str, str], ...], commit: str) -> list[dict]:
    keywords = extract_keywords(goal)
    if not keywords:
        return []

    query_hash = lexical_query_hash(goal)

    from sacas.search import FallbackIndex
    index = FallbackIndex(root, sacas_root)
    index.update()

    candidates = index.search(goal)

    results = []
    for score, filepath, matched in candidates[:5]:
        if is_file_protected(filepath, boundaries):
            continue
        f_hash = _source_hash(root, filepath)
        if f_hash is None:
            continue

        results.append({
            "path": filepath,
            "symbols": [],
            "reason": f"Matched heuristic scoring (score={score}) matching keywords: {', '.join(matched)}",
            "source": "heuristic",
            "confidence": "high" if score >= 8 else "medium",
            "relation": "keyword_match",
            "trigger": "task_goal",
            "git_revision": commit,
            "hash": f_hash,
            "query_hash": query_hash,
            "matched": list(matched),
            "score": score,
        })
    return results


def route_rules_and_references(
    repository_root: Path,
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
            r_rel = normalize_sacas_document_path(repository_root, sacas_root, r)
            rules_list.append(ActiveRuleContext(path=r_rel, hash="", reason=EXPLICIT_CONTEXT_REASON))
    else:
        # Heuristic rules routing
        rules_dir = sacas_root / "rules"
        if rules_dir.is_dir():
            for p in rules_dir.rglob("*.md"):
                rel_path = sacas_child_repo_path(repository_root, sacas_root, p.relative_to(sacas_root))
                filename = p.name.lower()
                # Default: always load boundaries.md if it exists, otherwise check keywords
                if filename == "boundaries.md" or any(kw in filename for kw in keywords):
                    try:
                        read_repo_text(repository_root, p.relative_to(repository_root).as_posix())
                    except (ValueError, FileNotFoundError, OSError):
                        continue
                    rules_list.append(ActiveRuleContext(path=rel_path, hash="", reason="Heuristic rule match"))
                    
    # 2. References
    if explicit_refs:
        for r in explicit_refs:
            path_part = r
            section_anchor = None
            if "#" in r:
                path_part, section_anchor = r.split("#", 1)
                
            path_part_clean = path_part.replace("\\", "/")
            r_rel = normalize_sacas_document_path(repository_root, sacas_root, path_part_clean)
                
            if section_anchor:
                heading_path = [section_anchor.replace("-", " ").title()]
                sel = resolve_section_ranges(
                    repository_root,
                    r_rel,
                    {"mode": "sections", "sections": [{"heading_path": heading_path}]},
                )
            else:
                sel = {"mode": "full"}
                
            refs_list.append(ActiveReferenceContext(path=r_rel, selection=sel, hash="", reason=EXPLICIT_CONTEXT_REASON))
    else:
        # Heuristic references routing
        refs_dir = sacas_root / "references"
        if refs_dir.is_dir():
            for p in refs_dir.rglob("*.md"):
                rel_path = sacas_child_repo_path(repository_root, sacas_root, p.relative_to(sacas_root))
                filename = p.name.lower()
                
                # Check keyword match in filename
                if any(kw in filename for kw in keywords):
                    try:
                        content = read_repo_text(repository_root, p.relative_to(repository_root).as_posix())
                        matched_headings = []
                        for line in content.splitlines():
                            if line.startswith("#"):
                                match = re.match(r"^(#+)\s+(.+)$", line)
                                if match:
                                    heading_text = match.group(2).strip()
                                    if any(kw in heading_text.lower() for kw in keywords):
                                        matched_headings.append(heading_text)
                        
                        if matched_headings and len(matched_headings) < 3:
                            sel = resolve_section_ranges(
                                repository_root,
                                p.relative_to(repository_root).as_posix(),
                                {"mode": "sections", "sections": [{"heading_path": [h]} for h in matched_headings]},
                                content=content,
                            )
                            reason = f"Heuristic reference section match for: {', '.join(matched_headings)}"
                        else:
                            sel = {"mode": "full"}
                            reason = "Heuristic reference file match"
                    except (ValueError, FileNotFoundError, OSError):
                        continue
                        
                    refs_list.append(ActiveReferenceContext(path=rel_path, selection=sel, hash="", reason=reason))
                    
    return rules_list, refs_list


def route_goal(
    installation: Installation,
    goal: str,
    category: str | None = None,
    files: tuple[str, ...] = (),
    symbols: tuple[str, ...] = (),
    tests: tuple[str, ...] = (),
    rules: tuple[str, ...] = (),
    references: tuple[str, ...] = (),
    context_policy: str = "advisory",
    task_contract_hash: str | None = None,
    *,
    seed_files: tuple[ActiveFileContext, ...] = (),
    seed_tests: tuple[str, ...] = (),
    seed_rules: tuple[ActiveRuleContext, ...] = (),
    seed_references: tuple[ActiveReferenceContext, ...] = (),
    seed_events: tuple[AdmissionEvent, ...] = (),
) -> ActiveContextManifest:
    """Collect initial context files, resolving Graphify structural seed hits or fallback lexical matches."""
    from sacas.graphify import get_graphify_provider, resolve_graph_routing_outcome
    from sacas.enforce import negotiate_policy
    task_id = hashlib.sha256(goal.strip().encode("utf-8")).hexdigest()[:8]
    old_manifest = installation.manifest
    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(installation.repository_root, boundaries_file)
    commit = get_git_commit(installation.repository_root)
    # Reroutes provide preserved explicit context as seeds.  It is admitted
    # before discovery so the skeleton budget sees the actual retained scope.
    active_files = list(seed_files)
    events = list(seed_events)
    graph_snapshot_hash = ""  # Will be set if Graphify succeeds

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
        elif any(kw in goal_lower for kw in ("document", "doc", "readme", "comment")):
            category = "documentation"
        elif any(kw in goal_lower for kw in ("architect", "design", "structure", "overview")):
            category = "architecture"
        else:
            category = "investigate"

    # 1. Process rules and references first
    rules_list, refs_list = route_rules_and_references(installation.repository_root, installation.sacas_root, goal, rules, references)

    # Hash rules
    hashed_rules = list(seed_rules)
    for r in rules_list:
        r_hash = _source_hash(installation.repository_root, r.path)
        if r_hash is None:
            continue
        hashed_rules.append(ActiveRuleContext(path=r.path, hash=r_hash, reason=r.reason))
        if rules:
            events.append(AdmissionEvent(
                id=f"evt-init-{len(events):03d}", target=r.path, action="admit",
                source="explicit", reason=r.reason, trigger="initial_route",
                ranking_score=1.0, confidence=1.0, evidence=("explicit_user_input", "rule"),
            ))

    # Hash references
    hashed_refs = list(seed_references)
    for ref in refs_list:
        ref_hash = _source_hash(installation.repository_root, ref.path)
        if ref_hash is None:
            continue
        hashed_refs.append(ActiveReferenceContext(path=ref.path, selection=ref.selection, hash=ref_hash, reason=ref.reason))
        if references:
            events.append(AdmissionEvent(
                id=f"evt-init-{len(events):03d}", target=ref.path, action="admit",
                source="explicit", reason=ref.reason, trigger="initial_route",
                ranking_score=1.0, confidence=1.0, evidence=("explicit_user_input", "reference"),
            ))

    # 2. Process explicit files (if provided)
    if files:
        for f in files:
            from sacas.paths import resolve_repo_path
            try:
                f_rel = resolve_repo_path(installation.repository_root, f)
            except ValueError:
                continue

            f_hash = _source_hash(installation.repository_root, f_rel)
            if f_hash is None:
                continue

            # Repeat symbols syntax helper
            file_symbols = []
            for sym in symbols:
                if "::" in sym:
                    sym_file, sym_name = sym.split("::", 1)
                    if sym_file == f or sym_file == f_rel:
                        from sacas.regions import SymbolRangeResolver
                        rng = SymbolRangeResolver.resolve(installation, f_rel, sym_name)
                        file_symbols.append(ActiveSymbolContext(name=sym_name, range=rng, reason="Explicitly specified by user"))
                else:
                    from sacas.regions import SymbolRangeResolver
                    rng = SymbolRangeResolver.resolve(installation, f_rel, sym)
                    file_symbols.append(ActiveSymbolContext(name=sym, range=rng, reason="Explicitly specified by user"))

            sel = {"mode": "symbols", "symbols": file_symbols} if file_symbols else {"mode": "full"}
            active_files.append(ActiveFileContext(
                path=f_rel,
                selection=sel,
                source="explicit",
                ranking_score=1.0,
                confidence=1.0,
                evidence=("explicit_user_input",),
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
                trigger="initial_route",
                ranking_score=1.0,
                confidence=1.0,
                evidence=("explicit_user_input",),
            ))

    # 3. Process tests as ordinary context with role="test"
    all_tests = tuple(dict.fromkeys((*seed_tests, *tests)))
    for t in all_tests:
        from sacas.paths import resolve_repo_path
        try:
            t_rel = resolve_repo_path(installation.repository_root, t)
        except ValueError:
            continue
        t_hash = _source_hash(installation.repository_root, t_rel)
        if t_hash is None:
            continue
        active_files.append(ActiveFileContext(
            path=t_rel,
            selection={"mode": "full"},
            source="explicit",
            ranking_score=1.0,
            confidence=1.0,
            evidence=("explicit_user_input", "test_file"),
            relation=None,
            trigger="initial_route",
            git_revision=commit,
            reason="Explicitly specified test context",
            hash=t_hash,
            role="test"
        ))
        events.append(AdmissionEvent(
            id=f"evt-init-{len(events):03d}", target=t_rel, action="admit",
            source="explicit", reason="Explicitly specified test context", trigger="initial_route",
            ranking_score=1.0, confidence=1.0, evidence=("explicit_user_input", "test_file"),
        ))

    # 4. If files were NOT explicitly provided, run Graphify/lexical routing with preventive budget
    if not files:
        skeleton_manifest = ActiveContextManifest(
            task_id=task_id,
            task_contract_hash=task_contract_hash,
            git_revision=commit,
            files=tuple(active_files),
            rules=tuple(hashed_rules),
            references=tuple(hashed_refs),
            events=tuple(events),
            budget=None,
            policy=None,
            tests=all_tests,
            goal=goal,
            category=category
        )
        from sacas.budget import compile_budget_report, estimate_tokens
        budget_plan = compile_budget_report(installation, skeleton_manifest)
        retrieval_budget = budget_plan.retrieval_budget
        remaining_space = budget_plan.remaining

        # Confidence string to float mapping
        conf_map = {"high": 1.0, "medium": 0.7, "low": 0.4}

        graphify_admissions = 0
        if old_manifest.graphify_mode != "off":
            provider = get_graphify_provider(installation, required={"query"})
            graph_relative = f"{old_manifest.graphify_output}/graph.json"
            outcome = resolve_graph_routing_outcome(
                installation.repository_root,
                graph_relative,
                goal,
                provider,
                token_budget=retrieval_budget,
            )
            graph_snapshot_hash = outcome.snapshot_hash
            query_res = outcome.query_result
            if not outcome.use_lexical_fallback and query_res is not None:
                    # Ranked results carry per-node goal relevance. Admissions
                    # below a relative cutoff of the best score are noise the
                    # budget alone would happily spend itself on, so stop at
                    # the first under-cutoff path (paths arrive ranked).
                    path_scores: dict[str, int] = {}
                    for scored_node in query_res.nodes:
                        if scored_node.path and scored_node.goal_rank_score > 0:
                            path_scores[scored_node.path] = max(
                                path_scores.get(scored_node.path, 0),
                                scored_node.goal_rank_score,
                            )
                    best_score = max(path_scores.values(), default=0)
                    if best_score:
                        ratio_cut = -(-best_score * GOAL_RANK_CUTOFF_RATIO_NUM // GOAL_RANK_CUTOFF_RATIO_DEN)
                        cutoff = max(ratio_cut, GOAL_RANK_CUTOFF_FLOOR)
                    else:
                        cutoff = 0
                    path_to_node = {n.path: n for n in query_res.nodes if n.path}
                    for path in query_res.paths:
                        if cutoff and path_scores.get(path, 0) < cutoff:
                            break
                        from sacas.paths import resolve_repo_path
                        try:
                            f_rel = resolve_repo_path(installation.repository_root, path)
                        except ValueError:
                            continue

                        if is_file_protected(f_rel, parsed_boundaries):
                            continue

                        f_hash = _source_hash(installation.repository_root, f_rel)
                        if f_hash is None:
                            continue
                        
                        node = path_to_node.get(path)
                        confidence = "high"
                        relation = "seed"
                        reason = f"Discovered via Graphify query matching goal: {goal}"
                        selection = {"mode": "full"}
                        if node:
                            from sacas.regions import SymbolRangeResolver
                            resolved_res = SymbolRangeResolver.resolve_node_range(installation, f_rel, node.label, node.line)
                            if resolved_res:
                                selection, reason = resolved_res
                            if node.node_type:
                                reason += f" (node type: {node.node_type})"
                            edge_conf = None
                            for edge in query_res.edges:
                                if edge.target == node.id and edge.confidence:
                                    edge_conf = edge.confidence
                                    relation = edge.relation
                                    break
                            if edge_conf:
                                confidence = edge_conf.lower()
                        
                        # Preventively compile/budget admissions:
                        cand_cost = 0
                        try:
                            content = read_repo_text(installation.repository_root, f_rel)
                            if selection.get("mode") == "symbols":
                                symbols_content = []
                                for sym in selection.get("symbols", []):
                                    rng = sym.range
                                    if rng:
                                        lines = content.splitlines()
                                        if 1 <= rng.start_line <= len(lines) and 1 <= rng.end_line <= len(lines):
                                            symbols_content.append("\n".join(lines[rng.start_line-1:rng.end_line]))
                                    cand_cost = estimate_tokens("\n".join(symbols_content))
                                else:
                                    cand_cost = estimate_tokens(content)
                        except (ValueError, FileNotFoundError, OSError):
                            pass

                        if cand_cost > remaining_space:
                            continue

                        remaining_space -= cand_cost

                        # Convert string confidence to float
                        conf_float = conf_map.get(confidence, 0.7)
                        
                        # Build evidence list
                        ev = ["graphify_query"]
                        if relation and relation != "seed":
                            ev.append(f"{relation}_relation")
                        if node and node.label:
                            ev.append("goal_symbol_match")
                        
                        # Extract graph IDs for provenance (WP3)
                        graph_query_id = getattr(query_res, 'query_id', '')
                        graph_snapshot_hash = getattr(query_res, 'graph_snapshot_hash', '')
                        graph_node_id = node.id if node else ''
                        graph_edge_source_id = ''
                        graph_edge_target_id = ''
                        graph_edge_kind = relation or ''
                        graph_confidence = edge_conf if 'edge_conf' in locals() and edge_conf else conf_float
                        
                        # Find edge info
                        for edge in query_res.edges:
                            if edge.target == node.id:
                                graph_edge_source_id = edge.source
                                graph_edge_target_id = edge.target
                                graph_edge_kind = edge.relation
                                if edge.confidence:
                                    graph_confidence = float(edge.confidence.lower() == 'high' and 1.0 or edge.confidence.lower() == 'medium' and 0.7 or 0.4)
                                break
                        
                        active_files.append(ActiveFileContext(
                            path=f_rel,
                            selection=selection,
                            source="graphify",
                            ranking_score=conf_float,
                            confidence=conf_float,
                            evidence=tuple(ev),
                            relation=relation,
                            trigger="task_goal",
                            git_revision=commit,
                            reason=reason,
                            hash=f_hash
                        ))
                        events.append(AdmissionEvent(
                            id=f"evt-init-{len(events):03d}",
                            target=f_rel,
                            action="admit",
                            source="graphify",
                            reason=reason,
                            trigger="initial_route",
                            ranking_score=conf_float,
                            confidence=conf_float,
                            evidence=tuple(ev),
                            relation=relation,
                            direction="forward",
                            graph_snapshot_hash=graph_snapshot_hash,
                            graph_query_id=graph_query_id,
                            graph_node_id=graph_node_id,
                            graph_edge_source_id=graph_edge_source_id,
                            graph_edge_target_id=graph_edge_target_id,
                            graph_edge_kind=graph_edge_kind,
                            graph_confidence=graph_confidence,
                        ))
                        graphify_admissions += 1

        if graphify_admissions == 0:
            # Fallback Lexical Search
            fallback_results = run_fallback_routing(installation.repository_root, installation.sacas_root, goal, parsed_boundaries, commit)
            for item in fallback_results:
                if not item["hash"]:
                    continue
                cand_cost = 0
                try:
                    cand_cost = estimate_tokens(read_repo_text(installation.repository_root, item["path"]))
                except (ValueError, FileNotFoundError, OSError):
                    pass

                if cand_cost > remaining_space:
                    continue

                remaining_space -= cand_cost

                active_files.append(ActiveFileContext(
                    path=item["path"],
                    selection={"mode": "full"},
                    source="heuristic",
                    ranking_score=conf_map.get(item["confidence"], 0.5),
                    confidence=conf_map.get(item["confidence"], 0.5),
                    evidence=("heuristic_keyword_match",),
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
                    trigger="initial_route",
                    ranking_score=conf_map.get(item["confidence"], 0.5),
                    confidence=conf_map.get(item["confidence"], 0.5),
                    evidence=("heuristic_keyword_match",),
                    relation=item["relation"],
                    direction="forward",
                    lexical_query_hash=item.get("query_hash", ""),
                    lexical_matched_terms=tuple(item.get("matched", [])),
                    lexical_score=float(item.get("score", 0.0)),
                ))

    # Construct final manifest without policy yet
    manifest = ActiveContextManifest(
        task_id=task_id,
        task_contract_hash=task_contract_hash,
        git_revision=commit,
        graph_snapshot_hash=graph_snapshot_hash,
        files=tuple(active_files),
        rules=tuple(hashed_rules),
        references=tuple(hashed_refs),
        events=tuple(events),
        budget=None,
        policy=None,
        tests=all_tests,
        goal=goal,
        category=category
    )

    negotiated = negotiate_policy(installation, context_policy)
    manifest = replace(
        manifest,
        policy=negotiated,
    )
    return negotiated_policy_or_manifest(negotiated, manifest)


def negotiated_policy_or_manifest(negotiated, manifest):
    return manifest


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
    category: str | None = None,
    context_policy: str = "advisory"
) -> TaskResult:
    """Create or update a SACAS task, generating its contract, context, and state."""
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

    # Infer/set category
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
        elif any(kw in goal_lower for kw in ("document", "doc", "readme", "comment")):
            category = "documentation"
        elif any(kw in goal_lower for kw in ("architect", "design", "structure", "overview")):
            category = "architecture"
        else:
            category = "investigate"

    # Save canonical TaskContract (task.json)
    from sacas.task_contract import TaskContract, save_task_contract, task_contract_hash
    contract = TaskContract(
        schema_version=1,
        task_id=task_id,
        goal=goal,
        category=category,
        criteria=criteria,
        constraints=constraints,
        verification=verification
    )
    save_task_contract(task_dir, contract)
    contract_hash = task_contract_hash(contract)

    manifest = route_goal(
        installation=installation,
        goal=goal,
        category=category,
        files=files,
        symbols=symbols,
        tests=tests,
        rules=rules,
        references=references,
        context_policy=context_policy,
        task_contract_hash=contract_hash
    )

    from sacas.enforce import get_enforcement_provider
    provider = get_enforcement_provider(installation, manifest)
    provider.enforce(installation, manifest)

    # Regenerate task markdown which will calculate budget and update manifest
    regenerate_task_markdown(
        installation=installation,
        task_dir=task_dir,
        manifest=manifest,
        contract=contract
    )

    return TaskResult(task_id=task_id)


def regenerate_task_markdown(
    installation: Installation,
    task_dir: Path,
    manifest: ActiveContextManifest,
    contract: TaskContract | None = None,
    candidates_data: dict[str, object] | None = None,
) -> None:
    """Regenerate TASK.md and CONTEXT.md deterministically."""
    if contract is None:
        from sacas.task_contract import load_task_contract
        contract = load_task_contract(task_dir)

    criteria = contract.criteria if contract else ()
    constraints = contract.constraints if contract else ()
    verification = contract.verification if contract else ()

    # 1. In-memory TASK.md
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

    # Gather Graphify evidence & boundaries for CONTEXT.md
    graphify_manifest_path = installation.sacas_root / ".sacas" / "graphify.json"
    evidence = None
    if graphify_manifest_path.is_file():
        try:
            evidence = read_graphify_manifest(graphify_manifest_path)
        except Exception:
            pass

    boundaries_file = installation.sacas_root / "rules" / "boundaries.md"
    parsed_boundaries = parse_protected_boundaries(installation.repository_root, boundaries_file)

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

    protected_files = []
    for f in manifest.files:
        reason = is_file_protected(f.path, parsed_boundaries)
        if reason:
            protected_files.append(f"- `{f.path}`: {reason}")

    protected_section = ""
    if protected_files:
        protected_section = "### Protected Boundaries\n" + "\n".join(protected_files) + "\n\n"

    def build_context_content(limit=0, used=0, src=0, rule=0, ref=0, ctrl=0) -> str:
        context_lines = ["## Files"]
        initial_files = [f for f in manifest.files if f.trigger == "initial_route"]
        expanded_files = [f for f in manifest.files if f.trigger != "initial_route"]
        goal_str = contract.goal if contract else (manifest.goal or "Fix")

        if initial_files:
            for f in initial_files:
                rsn = f.reason
                if not rsn or "Discovered" in rsn or "Explicit" in rsn:
                    rsn = f"{goal_str} (seed)"
                if not rsn.startswith("admitted because"):
                    rsn = f"admitted because {rsn}"
                context_lines.append(f"- `{f.path}`: {rsn}")
        if expanded_files:
            context_lines.append("")
            context_lines.append("### Expanded Files")
            for f in expanded_files:
                rsn = f.reason or "expanded context"
                if not rsn.startswith("admitted because"):
                    rsn = f"admitted because {rsn}"
                context_lines.append(f"- `{f.path}`: {rsn}")
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
            f"- Limit: {limit} tokens",
            f"- Estimated context size: {used} tokens",
            f"  - Payload: {src} source, {rule} rules, {ref} references",
            f"  - Control: {ctrl} task documents",
            "",
            "## Evidence & Freshness",
            f"- Graphify Status: {evidence.status if evidence else 'unavailable'}",
            f"- Graphify Hash: {evidence.content_hash if (evidence and evidence.content_hash) else 'N/A'}",
            "",
        ])
        context_lines.extend(effects_lines)
        context_text = "\n".join(context_lines) + "\n"

        context_md_path = task_dir / "CONTEXT.md"
        if context_md_path.exists():
            old_text = context_md_path.read_text(encoding="utf-8")
            return replace_generated_region(old_text, "task-context", context_text)
        else:
            return f"# Task Context\n\n" + render_generated_region("task-context", context_text)

    # First pass: render skeleton CONTEXT.md with placeholder values
    context_md_skeleton = build_context_content()

    router_path = installation.sacas_root / "ROUTER.md"
    router_content = router_path.read_text(encoding="utf-8") if router_path.is_file() else ""

    rendered_views = {
        "TASK.md": task_md_content,
        "CONTEXT.md": context_md_skeleton,
        "ROUTER.md": router_content,
    }
    
    breakdown = calculate_manifest_tokens(installation, manifest, rendered_views=rendered_views)
    budget_state = ContextBudgetState(
        limit=breakdown.limit,
        used=breakdown.used,
        tokenizer=breakdown.tokenizer,
        source_tokens=breakdown.source_tokens,
        rule_tokens=breakdown.rule_tokens,
        reference_tokens=breakdown.reference_tokens,
        control_tokens=breakdown.control_tokens
    )

    # Re-render final CONTEXT.md with actual values
    context_md_final = build_context_content(
        limit=breakdown.limit,
        used=breakdown.used,
        src=breakdown.source_tokens,
        rule=breakdown.rule_tokens,
        ref=breakdown.reference_tokens,
        ctrl=breakdown.control_tokens
    )

    from dataclasses import replace
    updated_manifest = replace(manifest, budget=budget_state)
    views = {
        task_md_path: task_md_content,
        task_dir / "CONTEXT.md": context_md_final,
    }
    if candidates_data is not None:
        views[task_dir / "candidates.json"] = stable_json(candidates_data)
    publish_task_artifacts(
        installation,
        task_dir,
        updated_manifest,
        views,
        contract=contract,
    )


def publish_task_artifacts(
    installation: Installation,
    task_dir: Path,
    manifest: ActiveContextManifest,
    views: dict[Path, str],
    *,
    contract: TaskContract | None = None,
) -> Path:
    """Publish one coherent task generation in dependency order.

    Everything is rendered before this boundary.  The runtime pack is written
    first, the canonical manifest second, and human views last; readers reject
    a crash-window pack whose header does not match canonical state.
    """
    from sacas.task_contract import load_task_contract, save_task_contract

    header, fragments = compile_context_pack(installation, manifest)
    validate_context_pack_records(header, fragments)
    canonical_contract = contract or load_task_contract(task_dir)
    if canonical_contract is None:
        raise ValueError("canonical task contract is unavailable")
    validate_context_pack_against_state(
        header, fragments, manifest, canonical_contract, installation,
    )
    pack_path = write_context_pack(installation, header, fragments)
    if contract is not None:
        save_task_contract(task_dir, contract)
    save_active_context(task_dir, manifest)
    for path, content in views.items():
        write_text_atomic(path, content)
    return pack_path


def invalidate_runtime_context_pack(installation: Installation) -> None:
    """Remove an obsolete runtime pack before changing canonical task identity."""
    pack_path = installation.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    try:
        pack_path.unlink()
    except FileNotFoundError:
        pass
