"""Context Compiler - compiles admitted context into ephemeral payload for agents."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from sacas.active_context import ActiveContextManifest, ActiveFileContext
from sacas.budget import estimate_tokens
from sacas.paths import Installation


@dataclass(frozen=True)
class ContextPackEntry:
    """A single compiled context fragment for agent consumption."""
    id: str                    # ctx-001
    source: str                # src/auth/service.ts
    selector: str              # AuthService.validateToken or src/auth/service.ts (full)
    lines: tuple[int, int] | None  # (83, 127) or None for full file
    hash: str                  # content hash (first 16 chars)
    reason: str                # admission rationale
    estimated_tokens: int      # token count for this fragment
    admission_event_id: str    # link to AdmissionEvent
    role: str = "source"       # source, test, reference, rule


def compile_context_pack(
    installation: Installation,
    manifest: ActiveContextManifest
) -> list[ContextPackEntry]:
    """Compile active context manifest into ordered context pack entries."""
    entries = []
    ctx_counter = 0

    # Process all admitted files (legacy + reference_files + working_files)
    for f in manifest.all_files:
        f_path = installation.repository_root / f.path
        if not f_path.is_file():
            continue

        try:
            content = f_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        lines = content.splitlines()

        if f.selection.get("mode") == "symbols":
            symbols = f.selection.get("symbols", [])
            for sym in symbols:
                name = getattr(sym, "name", None) or (sym.get("name") if isinstance(sym, dict) else None)
                rng = getattr(sym, "range", None) or (sym.get("range") if isinstance(sym, dict) else None)
                sym_reason = getattr(sym, "reason", None) or (sym.get("reason") if isinstance(sym, dict) else None)

                if rng:
                    start = getattr(rng, "start_line", None) or (rng.get("start_line") if isinstance(rng, dict) else None)
                    end = getattr(rng, "end_line", None) or (rng.get("end_line") if isinstance(rng, dict) else None)
                    if start is not None and end is not None and 1 <= start <= len(lines) and 1 <= end <= len(lines):
                        fragment = "\n".join(lines[start-1:end])
                        fragment_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
                        tok_count = estimate_tokens(fragment)
                        ctx_counter += 1
                        entries.append(ContextPackEntry(
                            id=f"ctx-{ctx_counter:03d}",
                            source=f.path,
                            selector=f"{f.path}::{name}",
                            lines=(start, end),
                            hash=fragment_hash,
                            reason=sym_reason or f.reason,
                            estimated_tokens=tok_count,
                            admission_event_id=_find_admission_event_id(manifest, f.path),
                            role=f.role
                        ))
                    else:
                        # Fallback: full file
                        fragment = content
                        fragment_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
                        tok_count = estimate_tokens(fragment)
                        ctx_counter += 1
                        entries.append(ContextPackEntry(
                            id=f"ctx-{ctx_counter:03d}",
                            source=f.path,
                            selector=f.path,
                            lines=None,
                            hash=fragment_hash,
                            reason=f.reason,
                            estimated_tokens=tok_count,
                            admission_event_id=_find_admission_event_id(manifest, f.path),
                            role=f.role
                        ))
                else:
                    # No range - full file
                    fragment = content
                    fragment_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
                    tok_count = estimate_tokens(fragment)
                    ctx_counter += 1
                    entries.append(ContextPackEntry(
                        id=f"ctx-{ctx_counter:03d}",
                        source=f.path,
                        selector=f.path,
                        lines=None,
                        hash=fragment_hash,
                        reason=f.reason,
                        estimated_tokens=tok_count,
                        admission_event_id=_find_admission_event_id(manifest, f.path),
                        role=f.role
                    ))
        else:
            # Full file mode
            fragment = content
            fragment_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
            tok_count = estimate_tokens(fragment)
            ctx_counter += 1
            entries.append(ContextPackEntry(
                id=f"ctx-{ctx_counter:03d}",
                source=f.path,
                selector=f.path,
                lines=None,
                hash=fragment_hash,
                reason=f.reason,
                estimated_tokens=tok_count,
                admission_event_id=_find_admission_event_id(manifest, f.path),
                role=f.role
            ))

    # Process rules
    for r in manifest.rules:
        r_path = installation.repository_root / r.path
        if r_path.is_file():
            try:
                content = r_path.read_text(encoding="utf-8", errors="ignore")
                fragment_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                tok_count = estimate_tokens(content)
                ctx_counter += 1
                entries.append(ContextPackEntry(
                    id=f"ctx-{ctx_counter:03d}",
                    source=r.path,
                    selector=r.path,
                    lines=None,
                    hash=fragment_hash,
                    reason=r.reason,
                    estimated_tokens=tok_count,
                    admission_event_id="",
                    role="rule"
                ))
            except OSError:
                pass

    # Process references
    for ref in manifest.references:
        ref_path = installation.repository_root / ref.path
        if ref_path.is_file():
            try:
                content = ref_path.read_text(encoding="utf-8", errors="ignore")
                if ref.selection.get("mode") == "sections":
                    from sacas.regions import extract_markdown_section
                    sections_content = []
                    for sec in ref.selection.get("sections", []):
                        heading_path = sec.get("heading_path", []) if isinstance(sec, dict) else getattr(sec, "heading_path", [])
                        if heading_path:
                            sections_content.append(extract_markdown_section(content, heading_path))
                    fragment = "\n".join(sections_content)
                    sec_names = ", ".join(" > ".join(sec.get("heading_path", [])) for sec in ref.selection.get("sections", []))
                    selector = f"{ref.path} (Sections: {sec_names})"
                else:
                    fragment = content
                    selector = ref.path
                fragment_hash = hashlib.sha256(fragment.encode()).hexdigest()[:16]
                tok_count = estimate_tokens(fragment)
                ctx_counter += 1
                entries.append(ContextPackEntry(
                    id=f"ctx-{ctx_counter:03d}",
                    source=ref.path,
                    selector=selector,
                    lines=None,
                    hash=fragment_hash,
                    reason=ref.reason,
                    estimated_tokens=tok_count,
                    admission_event_id="",
                    role="reference"
                ))
            except OSError:
                pass

    return entries


def _find_admission_event_id(manifest: ActiveContextManifest, target_path: str) -> str:
    """Find the admission event ID for a given file path."""
    for event in manifest.events:
        if event.target == target_path:
            return event.id
    return ""


def write_context_pack(installation: Installation, entries: list[ContextPackEntry]) -> Path:
    """Write context pack to .sacas/runtime/context.pack.jsonl"""
    runtime_dir = installation.sacas_root / ".sacas" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    pack_path = runtime_dir / "context.pack.jsonl"

    with pack_path.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(asdict(entry)) + "\n")

    return pack_path


def compile_and_write_context_pack(installation: Installation, manifest: ActiveContextManifest) -> Path:
    """Convenience function: compile and write in one call."""
    entries = compile_context_pack(installation, manifest)
    return write_context_pack(installation, entries)