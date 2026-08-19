from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal
from sacas.models import ACTIVE_CONTEXT_SCHEMA_VERSION

@dataclass(frozen=True)
class SourceRange:
    start_line: int
    end_line: int
    source: Literal["graphify", "parser", "heuristic", "explicit"]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source": self.source,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceRange:
        return cls(
            start_line=data["start_line"],
            end_line=data["end_line"],
            source=data["source"],
            confidence=data["confidence"],
        )

@dataclass(frozen=True)
class ActiveSymbolContext:
    name: str
    range: SourceRange | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "range": self.range.to_dict() if self.range else None,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveSymbolContext:
        rng = data.get("range")
        return cls(
            name=data["name"],
            range=SourceRange.from_dict(rng) if rng else None,
            reason=data.get("reason"),
        )

@dataclass(frozen=True)
class ActiveFileContext:
    path: str
    selection: dict[str, Any]  # {"mode": "full"} or {"mode": "symbols", "symbols": [ActiveSymbolContext]}
    source: str
    confidence: str
    relation: str | None
    trigger: str | None
    git_revision: str
    reason: str
    hash: str
    role: str = "source"

    def to_dict(self) -> dict[str, Any]:
        sel = self.selection.copy()
        if sel.get("mode") == "symbols":
            from sacas.regions import normalize_selections
            from sacas.active_context import ActiveSymbolContext
            symbols = []
            for s in sel.get("symbols", []):
                if isinstance(s, dict):
                    symbols.append(ActiveSymbolContext.from_dict(s))
                else:
                    symbols.append(s)
            normalized = normalize_selections(tuple(symbols))
            sel["symbols"] = [s.to_dict() for s in normalized]
        return {
            "path": self.path,
            "selection": sel,
            "source": self.source,
            "confidence": self.confidence,
            "relation": self.relation,
            "trigger": self.trigger,
            "git_revision": self.git_revision,
            "reason": self.reason,
            "hash": self.hash,
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveFileContext:
        sel = data["selection"].copy()
        if sel.get("mode") == "symbols":
            sel["symbols"] = [ActiveSymbolContext.from_dict(s) for s in sel.get("symbols", [])]
        return cls(
            path=data["path"],
            selection=sel,
            source=data["source"],
            confidence=data["confidence"],
            relation=data.get("relation"),
            trigger=data.get("trigger"),
            git_revision=data.get("git_revision", "unknown"),
            reason=data.get("reason", ""),
            hash=data.get("hash", ""),
            role=data.get("role", "source")
        )

@dataclass(frozen=True)
class ActiveRuleContext:
    path: str
    hash: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "hash": self.hash,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveRuleContext:
        return cls(
            path=data["path"],
            hash=data["hash"],
            reason=data.get("reason", ""),
        )

@dataclass(frozen=True)
class ActiveReferenceContext:
    path: str
    selection: dict[str, Any]  # {"mode": "full"} or {"mode": "sections", "sections": [{"heading_path": ["auth"], "start": 1, "end": 2}]}
    hash: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "selection": self.selection,
            "hash": self.hash,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveReferenceContext:
        return cls(
            path=data["path"],
            selection=data["selection"],
            hash=data["hash"],
            reason=data.get("reason", ""),
        )

@dataclass(frozen=True)
class AdmissionEvent:
    id: str
    target: str
    action: Literal["admit"]
    source: str
    reason: str
    trigger: str
    triggered_by: str | None = None
    relation: str | None = None
    direction: Literal["forward", "reverse"] | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target": self.target,
            "action": self.action,
            "source": self.source,
            "reason": self.reason,
            "trigger": self.trigger,
            "triggered_by": self.triggered_by,
            "relation": self.relation,
            "direction": self.direction,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdmissionEvent:
        return cls(
            id=data["id"],
            target=data["target"],
            action=data["action"],
            source=data["source"],
            reason=data["reason"],
            trigger=data["trigger"],
            triggered_by=data.get("triggered_by"),
            relation=data.get("relation"),
            direction=data.get("direction"),
            confidence=data.get("confidence"),
        )

@dataclass(frozen=True)
class ContextBudgetState:
    limit: int
    used: int
    tokenizer: str
    source_tokens: int
    rule_tokens: int
    reference_tokens: int
    control_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "used": self.used,
            "tokenizer": self.tokenizer,
            "source_tokens": self.source_tokens,
            "rule_tokens": self.rule_tokens,
            "reference_tokens": self.reference_tokens,
            "control_tokens": self.control_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextBudgetState:
        return cls(
            limit=data["limit"],
            used=data["used"],
            tokenizer=data["tokenizer"],
            source_tokens=data["source_tokens"],
            rule_tokens=data["rule_tokens"],
            reference_tokens=data["reference_tokens"],
            control_tokens=data["control_tokens"],
        )

@dataclass(frozen=True)
class ContextPolicyState:
    requested: str
    effective: str
    provider: str
    file_reads: str
    terminal_reads: str
    mcp_reads: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "effective": self.effective,
            "provider": self.provider,
            "file_reads": self.file_reads,
            "terminal_reads": self.terminal_reads,
            "mcp_reads": self.mcp_reads,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContextPolicyState:
        return cls(
            requested=data["requested"],
            effective=data["effective"],
            provider=data["provider"],
            file_reads=data["file_reads"],
            terminal_reads=data["terminal_reads"],
            mcp_reads=data["mcp_reads"],
        )

@dataclass(frozen=True)
class ActiveContextManifest:
    task_id: str
    task_contract_hash: str = ""
    git_revision: str = "unknown"
    files: tuple[ActiveFileContext, ...] = ()
    rules: tuple[ActiveRuleContext, ...] = ()
    references: tuple[ActiveReferenceContext, ...] = ()
    events: tuple[AdmissionEvent, ...] = ()
    budget: ContextBudgetState | None = None
    policy: ContextPolicyState | None = None
    tests: tuple[str, ...] = ()
    schema_version: int = ACTIVE_CONTEXT_SCHEMA_VERSION
    goal: str = ""
    category: str = "investigate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "task_contract_hash": self.task_contract_hash,
            "git_revision": self.git_revision,
            "files": [f.to_dict() for f in self.files],
            "rules": [r.to_dict() for r in self.rules],
            "references": [ref.to_dict() for ref in self.references],
            "events": [e.to_dict() for e in self.events],
            "budget": self.budget.to_dict() if self.budget else None,
            "policy": self.policy.to_dict() if self.policy else None,
            "tests": list(self.tests),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActiveContextManifest:
        if data.get("schema_version") != ACTIVE_CONTEXT_SCHEMA_VERSION:
            raise ValueError(f"Unsupported active context version {data.get('schema_version')}")
        files = tuple(ActiveFileContext.from_dict(f) for f in data.get("files", []))
        rules = tuple(ActiveRuleContext.from_dict(r) for r in data.get("rules", []))
        references = tuple(ActiveReferenceContext.from_dict(ref) for ref in data.get("references", []))
        events = tuple(AdmissionEvent.from_dict(e) for e in data.get("events", []))
        bg = data.get("budget")
        budget = ContextBudgetState.from_dict(bg) if bg else None
        pl = data.get("policy")
        policy = ContextPolicyState.from_dict(pl) if pl else None
        return cls(
            task_id=data["task_id"],
            task_contract_hash=data.get("task_contract_hash", ""),
            git_revision=data.get("git_revision", "unknown"),
            files=files,
            rules=rules,
            references=references,
            events=events,
            budget=budget,
            policy=policy,
            tests=tuple(data.get("tests", [])),
            schema_version=data.get("schema_version", ACTIVE_CONTEXT_SCHEMA_VERSION),
            goal=data.get("goal", ""),
            category=data.get("category", "investigate")
        )

def load_active_context(task_dir: Path) -> ActiveContextManifest | None:
    path = task_dir / "active_context.json"
    manifest = None
    if not path.is_file():
        manifest = migrate_legacy_active_context(task_dir)
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            manifest = ActiveContextManifest.from_dict(data)
        except Exception:
            pass
    if manifest:
        from sacas.task_contract import load_task_contract
        contract = load_task_contract(task_dir)
        if contract:
            from dataclasses import replace
            manifest = replace(manifest, goal=contract.goal, category=contract.category)
    return manifest

def save_active_context(task_dir: Path, manifest: ActiveContextManifest) -> None:
    from sacas.io import stable_json, write_text_atomic
    path = task_dir / "active_context.json"
    write_text_atomic(path, stable_json(manifest.to_dict()))
    
    from sacas.task_contract import load_task_contract, TaskContract, save_task_contract
    if manifest.goal or manifest.category:
        contract = load_task_contract(task_dir)
        if not contract or contract.task_id != manifest.task_id:
            contract = TaskContract(
                schema_version=1,
                task_id=manifest.task_id,
                goal=manifest.goal,
                category=manifest.category,
                criteria=(),
                constraints=(),
                verification=()
            )
            save_task_contract(task_dir, contract)

def migrate_legacy_active_context(task_dir: Path) -> ActiveContextManifest | None:
    legacy_path = task_dir / "expansions.json"
    if not legacy_path.is_file():
        return None
    try:
        from sacas.io import write_text_atomic, stable_json
        legacy_data = json.loads(legacy_path.read_text(encoding="utf-8"))
        
        goal = legacy_data.get("goal", "")
        task_id = legacy_data.get("task_id", "")
        
        # Categorize
        import re
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
            
        files_list = []
        events_list = []
        
        # Helper to map schemas
        from sacas.tasks import get_initial_files, get_expanded_files
        initial_files = get_initial_files(legacy_data)
        expanded_files = get_expanded_files(legacy_data)
        
        # Standard rules/refs mapping
        rules_list = []
        for r_path in legacy_data.get("rules", []):
            rules_list.append(ActiveRuleContext(path=r_path, hash="", reason="Legacy rule"))
            
        # Reconstruct initial files
        if legacy_data.get("schema_version") == 2:
            initials = legacy_data.get("initial_scope", [])
            for item in initials:
                path = item["path"]
                symbols = [ActiveSymbolContext(name=s) for s in item.get("symbols", [])]
                sel = {"mode": "symbols", "symbols": symbols} if symbols else {"mode": "full"}
                files_list.append(ActiveFileContext(
                    path=path,
                    selection=sel,
                    source=item.get("source", "explicit"),
                    confidence=item.get("confidence", "high"),
                    relation=item.get("relation"),
                    trigger=item.get("trigger", "initial_route"),
                    git_revision=item.get("git_revision", "unknown"),
                    reason=item.get("reason", "Discovered in initial route"),
                    hash=item.get("hash", "")
                ))
                # Add admission event
                events_list.append(AdmissionEvent(
                    id=f"evt-init-{len(events_list):03d}",
                    target=path,
                    action="admit",
                    source=item.get("source", "explicit"),
                    reason=item.get("reason", "Discovered in initial route"),
                    trigger="initial_route",
                ))
                
            exps = legacy_data.get("expansions", [])
            for item in exps:
                path = item["path"]
                files_list.append(ActiveFileContext(
                    path=path,
                    selection={"mode": "full"},
                    source=item.get("source", "graphify"),
                    confidence=item.get("confidence", "high"),
                    relation=item.get("relation"),
                    trigger="expansion",
                    git_revision=item.get("git_revision", "unknown"),
                    reason=item.get("reason", "Expanded via relationship"),
                    hash=item.get("hash", "")
                ))
                events_list.append(AdmissionEvent(
                    id=item.get("id", f"evt-exp-{len(events_list):03d}"),
                    target=path,
                    action="admit",
                    source=item.get("source", "graphify"),
                    reason=item.get("reason", "Expanded via relationship"),
                    trigger="expansion",
                    triggered_by=item.get("triggered_by"),
                    relation=item.get("relation"),
                    confidence=1.0 if item.get("confidence") == "high" else 0.5
                ))
        else:
            # V1 legacy structure
            for f_path, f_hash in initial_files.items():
                files_list.append(ActiveFileContext(
                    path=f_path,
                    selection={"mode": "full"},
                    source="explicit",
                    confidence="high",
                    relation=None,
                    trigger="initial_route",
                    git_revision="unknown",
                    reason="Legacy initial file",
                    hash=f_hash
                ))
                events_list.append(AdmissionEvent(
                    id=f"evt-init-{len(events_list):03d}",
                    target=f_path,
                    action="admit",
                    source="explicit",
                    reason="Legacy initial file",
                    trigger="initial_route",
                ))
            for f_path, f_hash in expanded_files.items():
                files_list.append(ActiveFileContext(
                    path=f_path,
                    selection={"mode": "full"},
                    source="graphify",
                    confidence="high",
                    relation=None,
                    trigger="expansion",
                    git_revision="unknown",
                    reason="Legacy expanded file",
                    hash=f_hash
                ))
                events_list.append(AdmissionEvent(
                    id=f"evt-exp-{len(events_list):03d}",
                    target=f_path,
                    action="admit",
                    source="graphify",
                    reason="Legacy expanded file",
                    trigger="expansion"
                ))
                
        from sacas.task_contract import TaskContract, save_task_contract, task_contract_hash
        contract = TaskContract(
            schema_version=1,
            task_id=task_id,
            goal=goal,
            category=category,
            criteria=(),
            constraints=(),
            verification=()
        )
        save_task_contract(task_dir, contract)
        h = task_contract_hash(contract)
                 
        manifest = ActiveContextManifest(
            task_id=task_id,
            task_contract_hash=h,
            git_revision=legacy_data.get("git_revision", "unknown"),
            files=tuple(files_list),
            rules=tuple(rules_list),
            references=(),
            events=tuple(events_list),
            budget=None,
            policy=None,
            goal=goal,
            category=category
        )
        
        # Save to active_context.json
        save_active_context(task_dir, manifest)
        
        # Clean up legacy expansions.json
        try:
            legacy_path.unlink()
        except OSError:
            pass
            
        return manifest
    except Exception:
        return None


def build_parent_negations(path: str) -> list[str]:
    parts = path.replace("\\", "/").split("/")
    negations = []
    if not path or path == ".":
        return []
    current = ""
    for part in parts[:-1]:
        if current:
            current = f"{current}/{part}"
        else:
            current = part
        negations.append(f"!{current}/")
    negations.append(f"!{path}")
    return negations


def enforce_cursor_negation_patterns(installation: Installation, manifest: ActiveContextManifest) -> None:
    """Write gitignore-style negation patterns in a SACAS-owned region of .cursorignore."""
    if "cursor" not in installation.manifest.adapters:
        return

    cursor_ignore_path = installation.repository_root / ".cursorignore"

    # Build negation lines
    lines = [
        "# SACAS Cursor Selective Context negation patterns",
        "# Ignore all files by default",
        "*",
        "",
        "# Negate SACAS control documents and folders",
        "!Structure/",
        "!Structure/tasks/",
        "!Structure/tasks/current/",
        "!Structure/tasks/current/**",
        "!Structure/ROUTER.md",
        "!Structure/map/",
        "!Structure/map/SYSTEM.md",
        "",
        "# Negate active context files, rules, and references",
    ]

    all_negations = []
    for f in manifest.files:
        all_negations.extend(build_parent_negations(f.path))

    for r in manifest.rules:
        all_negations.extend(build_parent_negations(r.path))

    for ref in manifest.references:
        all_negations.extend(build_parent_negations(ref.path))

    # Deduplicate while preserving order
    seen = set()
    deduped_negations = []
    for neg in all_negations:
        if neg not in seen:
            seen.add(neg)
            deduped_negations.append(neg)

    lines.extend(deduped_negations)

    negation_content = "\n".join(lines) + "\n"

    from sacas.regions import render_generated_region, replace_generated_region
    if cursor_ignore_path.is_file():
        old_text = cursor_ignore_path.read_text(encoding="utf-8")
        if "<!-- SACAS:START cursor-ignore -->" in old_text:
            try:
                new_text = replace_generated_region(old_text, "cursor-ignore", negation_content)
            except Exception:
                new_text = old_text + "\n" + render_generated_region("cursor-ignore", negation_content)
        else:
            new_text = old_text + "\n" + render_generated_region("cursor-ignore", negation_content)
    else:
        new_text = render_generated_region("cursor-ignore", negation_content)

    from sacas.io import write_text_atomic
    write_text_atomic(cursor_ignore_path, new_text)
