# SACAS Usage Guide

## Recommended Workflow

```
1. /graphify <path>        # (optional) deep codebase analysis — one-time cost
2. /sacas <path>           # scaffold the folder structure
3. Customize AGENTS.md     # fill in TODOs, add constraints
4. Per task:
   a. Create tasks/current/TASK.md with task definition
   b. Create tasks/current/CONTEXT.md scoped to that task
   c. Do the work
   d. Update tasks/current/PROGRESS.md
5. At session end: update PICKUP.md
```

## Portability

This structure works with any AI coding tool:

| Tool | How to Adapt |
|:---|:---|
| **Claude Code** | Rename `AGENTS.md` → `CLAUDE.md` at root |
| **Cursor** | Copy AGENTS.md content into `.cursorrules` |
| **Codex** | `AGENTS.md` works as-is |
| **GitHub Copilot** | Copy key sections to `.github/copilot-instructions.md` |
| **Antigravity** | Works natively — skill auto-detected |
| **Any LLM** | Markdown files are universal — any model that reads files can use them |

## Slash Commands

| Command | Mode | What It Does |
|:---|:---|:---|
| `/sacas` | replace | Analyze codebase + generate fresh folder structure |
| `/sacas <path>` | replace | Target specific directory |
| `/sacas-merge` | merge | Preserve existing AI configs, append SACAS sections |
| `/sacas-merge <path>` | merge | Merge on specific directory |
| `/sacas-status` | check | Report structure health + staleness |
