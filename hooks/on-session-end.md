# Session End: Auto-Generate PICKUP.md

Before ending any session where SACAS structure exists in the project, follow this procedure:

## Detection

Check if the project root has ALL of these:
- `AGENTS.md`
- `tasks/` directory
- `PICKUP.md`

If all three exist → this is a SACAS-managed project → update PICKUP.md.

## Procedure

### 1. Gather session data

- Current date/time
- Files modified this session (use `git diff --name-only` if git available, else track manually)
- Decisions made during the session
- Any open blockers or unresolved questions
- What was accomplished

### 2. Check for graphify enrichment

If `.sacas/graphify-enrichment.json` exists:
- Identify which communities/modules were touched (cross-reference modified files with community file lists)
- Note any cross-module edges that were affected
- Flag god nodes that were modified (high-risk changes)

### 3. Write PICKUP.md

Overwrite the existing PICKUP.md with:

```markdown
# Session Handoff

> Last updated: YYYY-MM-DD HH:MM

## Last Session Summary

[2-3 sentences: what was done, what was the goal]

## In-Progress Work

- [item with file paths]

## Open Decisions

- [decision needed + context]

## Known Issues

- [issue + severity]

## Priority for Next Session

1. [highest priority item]
2. [next item]
```

### 4. Update PROGRESS.md (if exists)

If `tasks/current/PROGRESS.md` exists, also update it with:
- Files modified
- Current status
- Next steps

## Rules

- Keep PICKUP.md under 500 words (token budget)
- Use structured sections, not prose
- Include file paths as relative paths
- Timestamp every update
- Distinguish facts from suggestions (use "Suggestion:" prefix)
- If graphify data available, mention which modules were touched
