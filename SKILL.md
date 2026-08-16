---
name: sacas
description: >
  Use when starting work on any codebase, when onboarding to a new project,
  or when asked to scaffold/generate a folder structure for AI agent navigation.
  Triggers on: /sacas, /sacas-merge, scaffold workspace, generate context structure,
  create AGENTS.md, setup AI workspace, organize codebase for AI.
---

# /sacas — Scaffold Analyzer Context Architect

Generate an MWP-style folder structure that gives AI agents precisely scoped context per task. Filesystem = orchestration. Folders = memory. Markdown = interface.

## Usage

```
/sacas                    # analyze + scaffold (replace mode)
/sacas <path>             # target specific directory
/sacas-merge              # merge with existing AI configs
/sacas-merge <path>       # merge on specific directory
/sacas-status             # check existing SACAS structure health
```

## What You Must Do When Invoked

### /sacas (default — replace mode)

1. **Detect target path.** Use argument if provided, else current working directory.

2. **Check for graphify data.** If `graphify-out/graph.json` exists in the target, note it — Step 5 will use it for enrichment.

3. **Run analysis.** Execute the analyzer scripts to scan the codebase:

```powershell
# Resolve scripts dir dynamically — works regardless of install location
$sacasSkill = (Get-ChildItem -Path ($env:USERPROFILE + '\.gemini\config\skills', $env:USERPROFILE + '\.gemini\antigravity\builtin\skills') -Filter 'sacas' -Directory -Recurse -Depth 0 -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
if (-not $sacasSkill) { $sacasSkill = (Get-ChildItem -Path ($env:USERPROFILE + '\.claude\skills') -Filter 'sacas' -Directory -ErrorAction SilentlyContinue | Select-Object -First 1).FullName }
$sacasScripts = Join-Path $sacasSkill 'scripts'
& "$sacasScripts\analyze.ps1" -Path "<TARGET_PATH>"
```

This produces `.sacas/analysis.json` with: tech stack, architecture pattern, coding conventions, module boundaries, existing AI configs.

4. **Run scaffold.** Generate the folder structure:

```powershell
& "$sacasScripts\scaffold.ps1" -Path "<TARGET_PATH>" -Mode "replace"
```

This creates:
```
<TARGET_PATH>/
├── AGENTS.md                  # Root agent instructions
├── PICKUP.md                  # Session handoff
├── .ai/rules/                 # Coding standards
├── .ai/prompts/               # Reusable prompts
├── context/
│   └── architecture.md        # System architecture
├── tasks/
│   ├── current/               # Active work
│   │   ├── TASK.md
│   │   ├── CONTEXT.md
│   │   └── PROGRESS.md
│   ├── backlog/               # Queued tasks
│   └── completed/             # Done tasks
├── references/                # Per-module deep docs (JIT loaded)
│   ├── {module-1}.md
│   └── {module-N}.md
└── .sacas/
    └── analysis.json          # Cached analysis
```

5. **Graphify enrichment (if available).** If `graphify-out/graph.json` exists:

```powershell
& "$sacasScripts\read-graphify.ps1" -Path "<TARGET_PATH>"
& "$sacasScripts\generate-context-md.ps1" -Path "<TARGET_PATH>"
```

This enriches:
- `references/` stubs with real dependency data from graph communities
- `context/architecture.md` with component relationships from graph edges
- Generates per-module `CONTEXT.md` files in `tasks/backlog/` with pre-populated file lists

6. **Print summary.** Show files created, modules detected, next steps.

### /sacas-merge

Same as `/sacas` but with `-Mode "merge"`:
- Reads existing CLAUDE.md, AGENTS.md, .cursorrules
- Preserves existing content
- Appends SACAS-generated sections marked with `<!-- SACAS-GENERATED -->`
- Does NOT overwrite user content

```powershell
& "$sacasScripts\scaffold.ps1" -Path "<TARGET_PATH>" -Mode "merge"
```

### /sacas-status

Quick health check of existing SACAS structure:

1. Check which SACAS files exist in the target
2. Compare `.sacas/analysis.json` timestamp vs source file mtimes
3. Report:
   - Which files are present/missing
   - Whether analysis is stale (source files changed since last scan)
   - Suggest re-run if structure is outdated

No scripts needed — just check filesystem directly.

## Auto-PICKUP.md

When SACAS structure exists in a project (AGENTS.md + tasks/ + PICKUP.md), write/update PICKUP.md at session end.

### Without graphify data:
Write a generic session summary:
- What files were modified
- Decisions made
- Open items
- Next steps

### With graphify data:
Enrich PICKUP.md with module-specific context:
- Which communities/modules were touched
- Which cross-module edges were affected
- Related god nodes that might need attention

Read `hooks/on-session-end.md` for the exact procedure.

## Key Principle

**CONTEXT.md is the token-saving secret.** Each task gets a CONTEXT.md that lists exactly which files are relevant. The agent reads ONLY those files — not the full codebase. This is what saves ~85% of tokens.

For recommended workflow and portability to other AI tools, see `references/usage-guide.md`.
