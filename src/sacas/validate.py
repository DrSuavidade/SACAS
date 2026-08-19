"""Cold-agent validation diagnostics for SACAS installation and task state."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from sacas.budget import calculate_context_size, calculate_total_context_size
from sacas.graphify import read_graphify_manifest
from sacas.paths import discover_manifest, Installation
from sacas.tasks import is_file_protected, parse_protected_boundaries


def check_regions_in_file(path: Path) -> list[str]:
    """Check for mismatched, duplicate, or malformed generated regions in a markdown file."""
    errors = []
    if not path.is_file():
        return errors
    try:
        content = path.read_text(encoding="utf-8")
        starts = re.findall(r"<!-- SACAS:START\s+(\S+)\s+-->", content)
        ends = re.findall(r"<!-- SACAS:END\s+(\S+)\s+-->", content)
        
        if len(starts) != len(ends):
            errors.append(f"Mismatched region tags in {path.name}: found {len(starts)} START tags and {len(ends)} END tags")
        else:
            for s, e in zip(sorted(starts), sorted(ends)):
                if s != e:
                    errors.append(f"Mismatched region names in {path.name}: START {s} does not match END {e}")
                    
        for name in set(starts):
            start_re = re.compile(rf"<!-- SACAS:START\s+{re.escape(name)}\s+-->")
            end_re = re.compile(rf"<!-- SACAS:END\s+{re.escape(name)}\s+-->")
            s_matches = list(start_re.finditer(content))
            e_matches = list(end_re.finditer(content))
            if len(s_matches) == 1 and len(e_matches) == 1:
                if s_matches[0].start() >= e_matches[0].start():
                    errors.append(f"Region {name} in {path.name} has START tag after END tag")
            elif len(s_matches) > 1 or len(e_matches) > 1:
                errors.append(f"Region {name} in {path.name} is duplicated")
    except Exception as err:
        errors.append(f"Failed to read {path.name} for region validation: {err}")
    return errors


def run_diagnostics(root: Path) -> dict[str, Any]:
    """Run all SACAS diagnostics and return a structured report."""
    diagnostics = []

    # 1. Manifest discovery and load
    installation = discover_manifest(root)
    if installation is None:
        diagnostics.append({
            "severity": "FAIL",
            "check": "manifest_check",
            "message": "SACAS manifest (manifest.json) not found. Run 'sacas init' first."
        })
        return {"status": "FAIL", "diagnostics": diagnostics}

    manifest = installation.manifest
    sacas_root = installation.sacas_root

    # Validate regions in ROUTER.md and map/SYSTEM.md
    for f in (sacas_root / "ROUTER.md", sacas_root / "map" / "SYSTEM.md"):
        for err in check_regions_in_file(f):
            diagnostics.append({
                "severity": "FAIL",
                "check": "malformed_regions",
                "message": err
            })

    # 2. Graphify availability check
    if manifest.graphify_mode != "off":
        graphify_manifest_path = sacas_root / ".sacas" / "graphify.json"
        if not graphify_manifest_path.is_file():
            diagnostics.append({
                "severity": "WARNING",
                "check": "graphify_availability",
                "message": f"Graphify manifest is missing at {graphify_manifest_path}."
            })
        else:
            try:
                evidence = read_graphify_manifest(graphify_manifest_path)
                if evidence.status == "stale":
                    diagnostics.append({
                        "severity": "WARNING",
                        "check": "graphify_availability",
                        "message": "Graphify graph is stale compared to repository source files."
                    })
            except Exception as err:
                diagnostics.append({
                    "severity": "WARNING",
                    "check": "graphify_availability",
                    "message": f"Graphify manifest is unreadable: {err}"
                })

    # 3. Build/test-command discoverability
    build_discovered = False
    for filename in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle"):
        if (installation.repository_root / filename).is_file():
            build_discovered = True
            break
    if not build_discovered:
        diagnostics.append({
            "severity": "WARNING",
            "check": "command_discoverability",
            "message": "Could not locate standard repository build/test configuration markers."
        })

    # 4. Active task validation
    task_id = manifest.current_task_id
    if task_id:
        task_dir = sacas_root / "tasks" / "current"
        
        # Check task.json
        task_json_path = task_dir / "task.json"
        if not task_json_path.is_file():
            diagnostics.append({
                "severity": "FAIL",
                "check": "missing_references",
                "message": "Required task contract task.json is missing."
            })
            
        # Check active_context.json
        active_json_path = task_dir / "active_context.json"
        if not active_json_path.is_file():
            diagnostics.append({
                "severity": "FAIL",
                "check": "missing_references",
                "message": "Required active context active_context.json is missing."
            })

        # Check views exist
        for filename in ("TASK.md", "CONTEXT.md"):
            path = task_dir / filename
            if not path.is_file():
                diagnostics.append({
                    "severity": "FAIL",
                    "check": "missing_references",
                    "message": f"Required task document {filename} is missing."
                })
            else:
                for err in check_regions_in_file(path):
                    diagnostics.append({
                        "severity": "FAIL",
                        "check": "malformed_regions",
                        "message": err
                    })

        # Check for legacy PROGRESS.md state drift
        if (task_dir / "PROGRESS.md").is_file():
            diagnostics.append({
                "severity": "FAIL",
                "check": "state_drift",
                "message": "Legacy PROGRESS.md file found. State should be tracked exclusively in STATE.md."
            })

        # Read active_context.json and check task files
        from sacas.active_context import load_active_context
        active_manifest = load_active_context(task_dir)
        
        from sacas.task_contract import load_task_contract, task_contract_hash
        contract = load_task_contract(task_dir)

        if active_manifest is not None:
            try:
                # Validate task/context IDs agree
                if contract and active_manifest.task_id != contract.task_id:
                    diagnostics.append({
                        "severity": "FAIL",
                        "check": "id_mismatch",
                        "message": f"Task contract ID ({contract.task_id}) does not match context ID ({active_manifest.task_id})."
                    })
                
                # Validate contract hash agrees
                if contract and active_manifest.task_contract_hash:
                    expected_hash = task_contract_hash(contract)
                    if active_manifest.task_contract_hash != expected_hash:
                        diagnostics.append({
                            "severity": "FAIL",
                            "check": "contract_hash_mismatch",
                            "message": "TaskContract hash in active_context.json does not match task.json."
                        })

                if not active_manifest.files:
                    diagnostics.append({
                        "severity": "WARNING",
                        "check": "empty_scope",
                        "message": "Task contains zero source files/symbols and no routing evidence was discovered."
                    })
                
                all_files = []
                stale_files = []
                missing_files = []
                
                # Overlap and duplicate selection check across all file types
                seen_paths = set()
                # Check legacy files + reference_files + working_files
                for f in active_manifest.all_files:
                    if f.path in seen_paths:
                        diagnostics.append({
                            "severity": "FAIL",
                            "check": "duplicate_files",
                            "message": f"Duplicate file context path found: {f.path}"
                        })
                    seen_paths.add(f.path)

                    all_files.append(f.path)
                    f_path = installation.repository_root / f.path
                    if not f_path.is_file():
                        missing_files.append(f.path)
                    else:
                        curr_hash = hashlib.sha256(f_path.read_bytes()).hexdigest()
                        if curr_hash != f.hash:
                            stale_files.append(f.path)
                        
                        # Verify symbols/ranges validity
                        if f.selection.get("mode") == "symbols":
                            for sym in f.selection.get("symbols", []):
                                name = getattr(sym, "name", None) or (sym.get("name") if isinstance(sym, dict) else None)
                                rng = getattr(sym, "range", None) or (sym.get("range") if isinstance(sym, dict) else None)
                                if rng:
                                    start = getattr(rng, "start_line", None) or (rng.get("start_line") if isinstance(rng, dict) else None)
                                    end = getattr(rng, "end_line", None) or (rng.get("end_line") if isinstance(rng, dict) else None)
                                    if start is not None and end is not None:
                                        if start > end or start < 1:
                                            diagnostics.append({
                                                "severity": "FAIL",
                                                "check": "invalid_range",
                                                "message": f"Invalid line range {start}-{end} for symbol {name} in {f.path}"
                                            })

                if missing_files:
                    diagnostics.append({
                        "severity": "FAIL",
                        "check": "missing_references",
                        "message": f"Referenced task files are missing: {', '.join(missing_files)}"
                    })
                if stale_files:
                    diagnostics.append({
                        "severity": "WARNING",
                        "check": "stale_context",
                        "message": f"Task files have been modified since routing: {', '.join(stale_files)}"
                    })

                # Budget check
                from sacas.budget import calculate_manifest_tokens
                breakdown = calculate_manifest_tokens(installation, active_manifest)
                total_size = breakdown.used
                if total_size > manifest.context_budget:
                    diagnostics.append({
                        "severity": "WARNING",
                        "check": "budget_limit",
                        "message": f"Estimated context size ({total_size} tokens) exceeds budget limit ({manifest.context_budget} tokens)."
                    })

                # Protected boundaries warning
                boundaries_file = sacas_root / "rules" / "boundaries.md"
                parsed_boundaries = parse_protected_boundaries(boundaries_file)
                protected_hits = []
                for f in all_files:
                    reason = is_file_protected(f, parsed_boundaries)
                    if reason:
                        protected_hits.append(f)
                if protected_hits:
                    diagnostics.append({
                        "severity": "WARNING",
                        "check": "protected_boundary_clarity",
                        "message": f"Focus files fall inside protected boundaries: {', '.join(protected_hits)}"
                    })
            except Exception as err:
                diagnostics.append({
                    "severity": "FAIL",
                    "check": "missing_references",
                    "message": f"active_context.json is malformed or unreadable: {err}"
                })
        else:
            diagnostics.append({
                "severity": "FAIL",
                "check": "missing_references",
                "message": "active_context.json is missing in current task directory."
            })

    # Calculate status
    has_fail = any(item["severity"] == "FAIL" for item in diagnostics)
    has_warning = any(item["severity"] == "WARNING" for item in diagnostics)
    
    status = "FAIL" if has_fail else ("WARNING" if has_warning else "PASS")
    return {"status": status, "diagnostics": diagnostics}


def perform_validation(root: Path, format_type: str = "text") -> int:
    """Run diagnostics and output report. Returns exit code (0 for PASS/WARNING, 1 for FAIL)."""
    report = run_diagnostics(root)
    if format_type == "json":
        print(json.dumps(report, indent=2))
    else:
        print(f"Validation Status: {report['status']}")
        if report["diagnostics"]:
            print("\nDiagnostics:")
            for item in report["diagnostics"]:
                print(f"  [{item['severity']}] {item['check']}: {item['message']}")
        else:
            print("All checks passed successfully.")
            
    return 1 if report["status"] == "FAIL" else 0
