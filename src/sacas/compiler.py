"""Context Compiler - compiles admitted context into ephemeral payload for agents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from sacas.active_context import ActiveContextManifest, ActiveFileContext
from sacas.budget import estimate_tokens
from sacas.io import read_repo_text, read_repo_bytes
from sacas.paths import Installation
from sacas.regions import normalize_selections, merge_ranges
from sacas.active_context import ActiveSymbolContext, SourceRange


PACK_SCHEMA_VERSION = 1


class ContextCompilationError(ValueError):
    """The canonical active context cannot be represented safely in a pack."""

    def __init__(self, code: str, path: str, detail: str = "") -> None:
        self.code = code
        self.path = path
        message = f"{code}: {path}"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


def _read_admitted_source(installation: Installation, path: str, *, kind: str = "source") -> str:
    """Read an admitted text artifact and expose a stable failure category."""
    try:
        return read_repo_text(installation.repository_root, path)
    except FileNotFoundError as error:
        raise ContextCompilationError(f"{kind}_unavailable", path, str(error)) from error
    except OSError as error:
        raise ContextCompilationError(f"{kind}_unavailable", path, str(error)) from error
    except ValueError as error:
        message = str(error).lower()
        if "binary" in message or "utf-8" in message:
            code = f"{kind}_binary"
        elif "exceeds size" in message:
            code = f"{kind}_oversized"
        elif any(marker in message for marker in ("secret", "ignored", "escapes", "absolute", ".sacasignore")):
            code = f"{kind}_unsafe"
        else:
            code = f"{kind}_invalid"
        raise ContextCompilationError(code, path, str(error)) from error


@dataclass(frozen=True)
class ContextPackHeader:
    """Header record for context pack - appears as first line in JSONL."""
    type: str = "pack"
    schema_version: int = PACK_SCHEMA_VERSION
    task_id: str = ""
    task_contract_hash: str = ""
    git_revision: str = ""
    graph_snapshot_hash: str = ""
    estimated_tokens: int = 0
    fragment_count: int = 0


@dataclass(frozen=True)
class ContextPackFragment:
    """A single compiled context fragment for agent consumption."""
    type: str = "fragment"
    id: str = ""                     # ctx-001
    source: str = ""                 # src/auth/service.ts
    selector: str = ""               # AuthService.validateToken or src/auth/service.ts (full)
    lines: tuple[int, int] | None = None  # (83, 127) or None for full file
    content: str = ""                # exact source fragment
    content_hash: str = ""           # sha256(content)[:16]
    reason: str = ""                 # admission rationale
    estimated_tokens: int = 0        # token count for this fragment
    admission_event_ids: tuple[str, ...] = ()  # links to AdmissionEvent(s)
    role: str = "source"             # source, test, reference, rule
    ranking_score: float = 0.0
    confidence: float = 0.0
    fallback_reason: str | None = None  # if full-file fallback, why


def _normalize_ranges_for_file(
    file_path: str,
    symbols: list[ActiveSymbolContext],
    content_lines: list[str]
) -> list[tuple[tuple[ActiveSymbolContext, ...], tuple[int, int]]]:
    """Normalize and merge overlapping/adjacent ranges for a single file."""
    # Extract ranges from symbols
    ranges = []
    for sym in symbols:
        rng = sym.range
        if rng and rng.start_line and rng.end_line:
            if 1 <= rng.start_line <= len(content_lines) and 1 <= rng.end_line <= len(content_lines):
                ranges.append((rng.start_line, rng.end_line))
    
    if not ranges:
        return []
    
    # Merge overlapping/adjacent ranges
    merged = merge_ranges(ranges)
    
    # Retain every constituent symbol in a merged range.  A range is an output
    # convenience; symbol identity remains provenance input.
    result = []
    for start, end in merged:
        members = tuple(
            sym for sym in symbols
            if sym.range and not (sym.range.end_line < start or sym.range.start_line > end)
        )
        if members:
            result.append((members, (start, end)))
    
    return result


def _build_file_selections(
    installation: Installation,
    manifest: ActiveContextManifest
) -> dict[str, list[tuple[ActiveSymbolContext, tuple[int, int], ActiveFileContext]]]:
    """Build normalized selections per file, with deduplication."""
    file_selections: dict[str, list] = {}
    
    for f in manifest.all_files:
        content = _read_admitted_source(installation, f.path)
        
        content_lines = content.splitlines()
        
        if f.selection.get("mode") == "symbols":
            raw_symbols = f.selection.get("symbols", [])
            sym_objects = []
            for s in raw_symbols:
                if isinstance(s, dict):
                    sym_objects.append(ActiveSymbolContext.from_dict(s))
                else:
                    sym_objects.append(s)
            
            if sym_objects:
                # Merge ranges for payload size, but do not normalize symbols:
                # normalization combines names and loses selector provenance.
                merged = _normalize_ranges_for_file(f.path, sym_objects, content_lines)
                if merged:
                    # Check each merged range for staleness
                    for symbols_for_range, rng in merged:
                        start, end = rng
                        # Check if range is still valid
                        is_stale = False
                        if start > len(content_lines) or end > len(content_lines):
                            is_stale = True
                        else:
                            # Check if content at range still matches expected symbol name
                            fragment = "\n".join(content_lines[start-1:end])
                            # Graph snapshots can name a file-level node while
                            # still supplying a valid source range.  Parser and
                            # explicit selectors, by contrast, are executable
                            # claims and must retain their named anchor.
                            if any(
                                sym.name
                                and sym.range is not None
                                and sym.range.source in {"parser", "explicit"}
                                and sym.name.rsplit(".", 1)[-1] not in fragment
                                for sym in symbols_for_range
                            ):
                                is_stale = True
                        
                        if is_stale:
                            # Stale selector - mark for re-resolution or fail
                            file_selections.setdefault(f.path, []).append(
                                (symbols_for_range, rng, f, "stale_selector")
                            )
                        else:
                            file_selections.setdefault(f.path, []).append(
                                (symbols_for_range, rng, f)
                            )
                else:
                    raise ContextCompilationError("stale_selector", f.path, "no valid selected ranges")
            else:
                file_selections.setdefault(f.path, []).append(
                    (None, None, f)
                )
        else:
            # Full file mode
            file_selections.setdefault(f.path, []).append(
                (None, None, f)
            )
    
    return file_selections


def _compile_fragments(
    installation: Installation,
    manifest: ActiveContextManifest,
    file_selections: dict[str, list[tuple[ActiveSymbolContext, tuple[int, int], ActiveFileContext]]]
) -> list[ContextPackFragment]:
    """Compile normalized selections into fragments with exact content."""
    fragments = []
    ctx_counter = 0
    
    # Deterministic ordering: sort by source path, then by start line
    sorted_files = sorted(file_selections.keys())
    
    for source_path in sorted_files:
        selections = file_selections[source_path]
        
        # Read file content once
        content = _read_admitted_source(installation, source_path)
        
        content_lines = content.splitlines()
        
        # Sort selections by start line for deterministic ordering
        selections.sort(key=lambda x: (x[1][0] if x[1] else 0))
        
        for item in selections:
            ctx_counter += 1
            fragment_id = f"ctx-{ctx_counter:03d}"
            
            # Unpack selection (supports both old and new format)
            if len(item) == 4:
                symbols_for_range, line_range, file_ctx, stale_reason = item
            else:
                symbols_for_range, line_range, file_ctx = item
                stale_reason = None
            
            # A file-target admission applies to every fragment; a selector
            # admission applies only when its constituent symbol is present.
            symbol_names = tuple(sorted(sym.name for sym in symbols_for_range)) if line_range is not None else ()
            admitted_targets = {source_path, *(f"{source_path}::{name}" for name in symbol_names)}
            admission_ids = tuple(sorted({event.id for event in manifest.events if event.target in admitted_targets}))
            
            if stale_reason:
                raise ContextCompilationError("stale_selector", source_path, stale_reason)

            if line_range is not None:
                # Symbol/range fragment
                start, end = line_range
                fragment = "\n".join(content_lines[start-1:end])
                selector = f"{source_path}::{','.join(symbol_names)}" if symbol_names else source_path
                fallback_reason = stale_reason
            else:
                # Full file fragment
                fragment = content
                selector = source_path
                fallback_reason = stale_reason if stale_reason else ("unresolved_symbol" if (symbols_for_range is not None) else "full_file_mode")
            
            content_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
            tok_count = estimate_tokens(fragment)
            
            # Determine ranking/confidence from file context
            ranking = file_ctx.ranking_score
            confidence = file_ctx.confidence
            
            # For full file fallback from unresolved symbol, use file's scores
            if fallback_reason == "unresolved_symbol":
                ranking = file_ctx.ranking_score
                confidence = file_ctx.confidence
            
            fragments.append(ContextPackFragment(
                id=fragment_id,
                source=source_path,
                selector=selector,
                lines=line_range,
                content=fragment,
                content_hash=content_hash,
                reason=file_ctx.reason,
                estimated_tokens=tok_count,
                admission_event_ids=admission_ids,
                role=file_ctx.role,
                ranking_score=ranking,
                confidence=confidence,
                fallback_reason=fallback_reason
            ))
    
    # Deduplicate full-file fragments (same source, same full-file range)
    # Use a dict to keep first occurrence
    seen = {}
    deduped = []
    for frag in fragments:
        # Key for deduplication: (source, lines) where full file = (source, None)
        if frag.lines is None:
            key = (frag.source, None)
        else:
            key = (frag.source, frag.lines)
        
        if key not in seen:
            seen[key] = frag
            deduped.append(frag)
        else:
            # Merge admission event IDs
            existing = seen[key]
            merged_ids = tuple(sorted(set(existing.admission_event_ids) | set(frag.admission_event_ids)))
            # Recreate with merged IDs
            merged = ContextPackFragment(
                id=existing.id,
                source=existing.source,
                selector=existing.selector,
                lines=existing.lines,
                content=existing.content,
                content_hash=existing.content_hash,
                reason=existing.reason,
                estimated_tokens=existing.estimated_tokens,
                admission_event_ids=merged_ids,
                role=existing.role,
                ranking_score=max(existing.ranking_score, frag.ranking_score),
                confidence=max(existing.confidence, frag.confidence),
                fallback_reason=existing.fallback_reason
            )
            seen[key] = merged
            # Replace in deduped list
            idx = deduped.index(existing)
            deduped[idx] = merged
    
    # Re-assign IDs based on final deterministic order
    final_fragments = []
    for i, frag in enumerate(deduped, 1):
        final_fragments.append(ContextPackFragment(
            id=f"ctx-{i:03d}",
            source=frag.source,
            selector=frag.selector,
            lines=frag.lines,
            content=frag.content,
            content_hash=frag.content_hash,
            reason=frag.reason,
            estimated_tokens=frag.estimated_tokens,
            admission_event_ids=frag.admission_event_ids,
            role=frag.role,
            ranking_score=frag.ranking_score,
            confidence=frag.confidence,
            fallback_reason=frag.fallback_reason
        ))
    
    return final_fragments


def _compile_rules_and_references(
    installation: Installation,
    manifest: ActiveContextManifest,
    start_counter: int
) -> tuple[list[ContextPackFragment], int]:
    """Compile rules and references as fragments."""
    fragments = []
    ctx_counter = start_counter
    
    # Rules
    for r in manifest.rules:
        try:
            content = _read_admitted_source(installation, r.path, kind="rule")
            fragment_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            tok_count = estimate_tokens(content)
            ctx_counter += 1
            fragments.append(ContextPackFragment(
                id=f"ctx-{ctx_counter:03d}",
                source=r.path,
                selector=r.path,
                lines=None,
                content=content,
                content_hash=fragment_hash,
                reason=r.reason,
                estimated_tokens=tok_count,
                admission_event_ids=(),
                role="rule",
                ranking_score=1.0,
                confidence=1.0,
                fallback_reason=None
            ))
        except ContextCompilationError:
            raise
    
    # References
    for ref in manifest.references:
        try:
            content = _read_admitted_source(installation, ref.path, kind="reference")
            if ref.selection.get("mode") == "sections":
                from sacas.regions import extract_markdown_section
                sections_content = []
                for sec in ref.selection.get("sections", []):
                    heading_path = sec.get("heading_path", []) if isinstance(sec, dict) else getattr(sec, "heading_path", [])
                    if heading_path:
                        try:
                            sections_content.append(
                                extract_markdown_section(content, heading_path, strict=True)
                            )
                        except LookupError as error:
                            raise ContextCompilationError(
                                "stale_selector", ref.path, str(error)
                            ) from error
                fragment = "\n".join(sections_content)
                sec_names = ", ".join(" > ".join(sec.get("heading_path", [])) for sec in ref.selection.get("sections", []))
                selector = f"{ref.path} (Sections: {sec_names})"
            else:
                fragment = content
                selector = ref.path
            fragment_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
            tok_count = estimate_tokens(fragment)
            ctx_counter += 1
            fragments.append(ContextPackFragment(
                id=f"ctx-{ctx_counter:03d}",
                source=ref.path,
                selector=selector,
                lines=None,
                content=fragment,
                content_hash=fragment_hash,
                reason=ref.reason,
                estimated_tokens=tok_count,
                admission_event_ids=(),
                role="reference",
                ranking_score=1.0,
                confidence=1.0,
                fallback_reason=None
            ))
        except ContextCompilationError:
            raise
    
    return fragments, ctx_counter


def compile_context_pack(
    installation: Installation,
    manifest: ActiveContextManifest
) -> tuple[ContextPackHeader, list[ContextPackFragment]]:
    """Compile active context manifest into ordered context pack with header and fragments."""
    admitted_test_paths = {file.path for file in manifest.all_files if file.role == "test"}
    missing_tests = sorted(set(manifest.tests).difference(admitted_test_paths))
    if missing_tests:
        raise ContextCompilationError("test_coverage_incomplete", missing_tests[0])

    # Build normalized, deduplicated file selections
    file_selections = _build_file_selections(installation, manifest)
    
    # Compile source file fragments
    fragments = _compile_fragments(installation, manifest, file_selections)
    
    # Compile rules and references
    more_fragments, _ = _compile_rules_and_references(installation, manifest, len(fragments))
    fragments.extend(more_fragments)
    
    # Calculate totals
    total_tokens = sum(f.estimated_tokens for f in fragments)
    
    # Build header
    header = ContextPackHeader(
        task_id=manifest.task_id,
        task_contract_hash=manifest.task_contract_hash,
        git_revision=manifest.git_revision,
        graph_snapshot_hash=getattr(manifest, 'graph_snapshot_hash', ''),
        estimated_tokens=total_tokens,
        fragment_count=len(fragments)
    )
    
    validate_context_pack_records(header, fragments)
    return header, fragments


def write_context_pack(
    installation: Installation,
    header: ContextPackHeader,
    fragments: list[ContextPackFragment]
) -> Path:
    """Write context pack to .sacas/runtime/context.pack.jsonl with header + fragments atomically."""
    from sacas.io import write_text_atomic
    runtime_dir = installation.sacas_root / ".sacas" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pack_path = runtime_dir / "context.pack.jsonl"

    # Build content first
    lines = [json.dumps(asdict(header), ensure_ascii=False, sort_keys=True, separators=(",", ":"))]
    for fragment in fragments:
        lines.append(json.dumps(asdict(fragment), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    content = "\n".join(lines) + "\n"
    
    # Atomic write
    write_text_atomic(pack_path, content)

    return pack_path


def validate_context_pack_records(
    header: ContextPackHeader,
    fragments: list[ContextPackFragment],
) -> None:
    """Validate an in-memory context-pack record set before it is persisted.

    ``read_context_pack`` validates the serialized representation, but a
    publisher must not rely on a round-trip through disk to reject a compiler
    result.  Keeping this check pure also makes the publication boundary
    independently testable.
    """
    if (
        header.type != "pack"
        or isinstance(header.schema_version, bool)
        or header.schema_version != PACK_SCHEMA_VERSION
    ):
        raise ValueError("invalid context pack header schema")
    for field_name in ("task_id", "task_contract_hash", "git_revision", "graph_snapshot_hash"):
        value = getattr(header, field_name)
        if not isinstance(value, str):
            raise ValueError(f"context pack header has invalid {field_name}")
    if not header.task_id:
        raise ValueError("context pack header has no task ID")
    if not header.task_contract_hash:
        raise ValueError("context pack header has no task contract hash")
    if (
        not isinstance(header.fragment_count, int)
        or isinstance(header.fragment_count, bool)
        or header.fragment_count < 0
    ):
        raise ValueError("context pack header has invalid fragment count")
    if header.fragment_count != len(fragments):
        raise ValueError(
            f"Fragment count mismatch: header says {header.fragment_count}, found {len(fragments)}"
        )
    if (
        not isinstance(header.estimated_tokens, int)
        or isinstance(header.estimated_tokens, bool)
        or header.estimated_tokens < 0
    ):
        raise ValueError("context pack header has invalid token estimate")

    seen_ids: set[str] = set()
    for fragment in fragments:
        if fragment.type != "fragment":
            raise ValueError("invalid context pack fragment schema")
        for field_name in ("id", "source", "selector", "content_hash", "role"):
            value = getattr(fragment, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"context pack fragment has invalid {field_name}")
        if not isinstance(fragment.content, str) or not isinstance(fragment.reason, str):
            raise ValueError(f"context pack fragment has invalid text content")
        if fragment.id in seen_ids:
            raise ValueError(f"Duplicate fragment ID: {fragment.id}")
        seen_ids.add(fragment.id)
        if (
            not isinstance(fragment.estimated_tokens, int)
            or isinstance(fragment.estimated_tokens, bool)
            or fragment.estimated_tokens < 0
        ):
            raise ValueError(f"Fragment {fragment.id} has invalid token estimate")
        if not all(
            isinstance(score, (int, float)) and not isinstance(score, bool)
            for score in (fragment.ranking_score, fragment.confidence)
        ):
            raise ValueError(f"Fragment {fragment.id} has invalid ranking metadata")
        if fragment.fallback_reason is not None and not isinstance(fragment.fallback_reason, str):
            raise ValueError(f"Fragment {fragment.id} has invalid fallback reason")
        if not isinstance(fragment.admission_event_ids, tuple) or not all(
            isinstance(event_id, str) for event_id in fragment.admission_event_ids
        ):
            raise ValueError(f"Fragment {fragment.id} has invalid admission event IDs")
        if fragment.lines is not None and (
            not isinstance(fragment.lines, tuple)
            or len(fragment.lines) != 2
            or not all(isinstance(line, int) and line > 0 for line in fragment.lines)
            or fragment.lines[0] > fragment.lines[1]
        ):
            raise ValueError(f"Fragment {fragment.id} has invalid line range")
        expected_hash = hashlib.sha256(fragment.content.encode("utf-8")).hexdigest()[:16]
        if fragment.content_hash != expected_hash:
            raise ValueError(
                f"Fragment {fragment.id} content hash mismatch: expected {expected_hash}, "
                f"got {fragment.content_hash}"
            )


def compile_and_write_context_pack(installation: Installation, manifest: ActiveContextManifest) -> Path:
    """Convenience function: compile and write in one call."""
    header, fragments = compile_context_pack(installation, manifest)
    return write_context_pack(installation, header, fragments)


def validate_context_pack_against_state(
    header: ContextPackHeader,
    fragments: list[ContextPackFragment],
    manifest: ActiveContextManifest,
    contract: Any,
) -> None:
    """Reject a pack that cannot be attributed to the current canonical state."""
    from sacas.task_contract import task_contract_hash

    if header.task_id != manifest.task_id or header.task_id != contract.task_id:
        raise ValueError("context pack task ID does not match canonical task state")
    expected_hash = task_contract_hash(contract)
    if header.task_contract_hash != expected_hash or manifest.task_contract_hash != expected_hash:
        raise ValueError("context pack contract hash does not match canonical task contract")
    if (
        header.git_revision != manifest.git_revision
        or header.graph_snapshot_hash != manifest.graph_snapshot_hash
    ):
        raise ValueError("context pack identity does not match canonical manifest")

    fragment_sources_by_role: dict[str, set[str]] = {}
    for fragment in fragments:
        fragment_sources_by_role.setdefault(fragment.role, set()).add(fragment.source)
    rule_fragment_sources = {
        fragment.source for fragment in fragments if fragment.role == "rule"
    }
    reference_fragment_sources = {
        fragment.source for fragment in fragments if fragment.role == "reference"
    }

    # Test coverage has priority over generic file coverage: a path named by
    # `manifest.tests` is an executable-test admission, not merely a source
    # file which happens to be present in the pack.
    expected_test_paths = set(manifest.tests)
    expected_test_paths.update(
        file_context.path
        for file_context in manifest.all_files
        if file_context.role == "test"
    )
    missing_test_paths = sorted(expected_test_paths.difference(fragment_sources_by_role.get("test", set())))
    if missing_test_paths:
        raise ValueError(
            f"context pack missing canonical test coverage: {missing_test_paths[0]}"
        )

    expected_file_paths_by_role: dict[str, set[str]] = {}
    for file_context in manifest.all_files:
        if file_context.role != "test" and file_context.path not in expected_test_paths:
            expected_file_paths_by_role.setdefault(file_context.role, set()).add(file_context.path)
    missing_file_paths = sorted(
        path
        for role, paths in expected_file_paths_by_role.items()
        for path in paths.difference(fragment_sources_by_role.get(role, set()))
    )
    if missing_file_paths:
        raise ValueError(
            f"context pack missing canonical file coverage: {missing_file_paths[0]}"
        )

    missing_rule_paths = sorted(
        {rule.path for rule in manifest.rules}.difference(fragment_sources_by_role.get("rule", set()))
    )
    if missing_rule_paths:
        raise ValueError(
            f"context pack missing canonical rule coverage: {missing_rule_paths[0]}"
        )

    missing_reference_paths = sorted(
        {reference.path for reference in manifest.references}.difference(fragment_sources_by_role.get("reference", set()))
    )
    if missing_reference_paths:
        raise ValueError(
            "context pack missing canonical reference coverage: "
            f"{missing_reference_paths[0]}"
        )


def load_validated_context_pack(installation: Installation) -> tuple[ContextPackHeader, list[ContextPackFragment]]:
    """Load the runtime pack only after binding it to current task.json/context state."""
    from sacas.active_context import load_task_state

    task_dir = installation.sacas_root / "tasks" / "current"
    manifest, contract = load_task_state(task_dir)
    if manifest is None or contract is None:
        raise ValueError("canonical task state is unavailable")
    pack_path = installation.sacas_root / ".sacas" / "runtime" / "context.pack.jsonl"
    header, fragments = read_context_pack(pack_path)
    validate_context_pack_against_state(header, fragments, manifest, contract)
    return header, fragments


def read_context_pack(pack_path: Path) -> tuple[ContextPackHeader, list[ContextPackFragment]]:
    """Read context pack from JSONL file with validation."""
    content = pack_path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError("Empty context pack")
    lines = content.splitlines()

    def parse_record(line: str, line_num: int) -> dict[str, Any]:
        try:
            record = json.loads(line)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"Invalid context pack JSON at line {line_num}") from error
        if not isinstance(record, Mapping):
            raise ValueError(f"Invalid context pack record at line {line_num}: expected object")
        return dict(record)

    header_data = parse_record(lines[0], 1)
    if header_data.get("type") != "pack":
        raise ValueError("Invalid context pack: missing header")
    
    # Validate schema version
    schema_version = header_data.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"Unsupported context pack schema version: {schema_version}")
    
    try:
        header = ContextPackHeader(**header_data)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid context pack header") from error
    fragments = []
    seen_ids = set()
    
    for line_num, line in enumerate(lines[1:], start=2):
        frag_data = parse_record(line, line_num)
        if frag_data.get("type") != "fragment":
            raise ValueError(f"Invalid context pack record at line {line_num}: expected fragment")
        
        # Validate required fields
        required_fields = ["id", "source", "selector", "lines", "content", "content_hash", "reason", "estimated_tokens", "admission_event_ids", "role", "ranking_score", "confidence", "fallback_reason"]
        for field in required_fields:
            if field not in frag_data:
                raise ValueError(f"Invalid fragment at line {line_num}: missing required field '{field}'")
        
        # Validate fragment ID uniqueness
        frag_id = frag_data["id"]
        if not isinstance(frag_id, str):
            raise ValueError(f"Invalid fragment at line {line_num}: id must be a string")
        if frag_id in seen_ids:
            raise ValueError(f"Duplicate fragment ID at line {line_num}: {frag_id}")
        seen_ids.add(frag_id)
        
        # Validate content hash matches content
        content = frag_data["content"]
        if not isinstance(content, str):
            raise ValueError(f"Invalid fragment at line {line_num}: content must be a string")
        import hashlib
        expected_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        if frag_data["content_hash"] != expected_hash:
            raise ValueError(f"Fragment {frag_id} content hash mismatch: expected {expected_hash}, got {frag_data['content_hash']}")
        
        # Validate fragment count matches header
        if len(fragments) >= header.fragment_count:
            raise ValueError(f"Fragment count exceeds header fragment_count at line {line_num}")
        
        # Convert admission_event_ids from list to tuple
        if "admission_event_ids" in frag_data and isinstance(frag_data["admission_event_ids"], list):
            frag_data["admission_event_ids"] = tuple(frag_data["admission_event_ids"])
        # Convert lines from list to tuple
        if "lines" in frag_data and isinstance(frag_data["lines"], list):
            frag_data["lines"] = tuple(frag_data["lines"])
        
        try:
            fragments.append(ContextPackFragment(**frag_data))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid fragment at line {line_num}") from error
    
    # Final validation: fragment count matches header
    if len(fragments) != header.fragment_count:
        raise ValueError(f"Fragment count mismatch: header says {header.fragment_count}, found {len(fragments)}")
    
    validate_context_pack_records(header, fragments)
    return header, fragments
