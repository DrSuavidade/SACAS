# PICKUP.md Format Reference

## Purpose

PICKUP.md is the cross-session handoff file. It tells the next agent (or the same agent in a new session) exactly where you left off. Think of it as a shift change briefing.

## Token Budget

**Max 500 words.** The agent reads this at session start — every token counts. Be terse.

## Required Sections

| Section | Purpose | Max Length |
|:---|:---|:---|
| Last Session Summary | What happened | 2-3 sentences |
| In-Progress Work | What's actively being worked on | Bullet list |
| Open Decisions | Decisions that need to be made | Bullet list with context |
| Known Issues | Bugs, blockers, risks | Bullet list with severity |
| Priority for Next Session | What to do first | Numbered list |

## Rules

1. **Structured sections, not prose.** Bullets and tables, not paragraphs.
2. **Include file paths.** Use relative paths: `src/auth/middleware.ts`, not descriptions.
3. **Timestamp every update.** ISO format or YYYY-MM-DD HH:MM.
4. **Facts vs suggestions.** Prefix opinions with "Suggestion:" so the next agent knows what's proven vs proposed.
5. **No redundancy with PROGRESS.md.** PICKUP.md is the bird's-eye view. PROGRESS.md has session details. Don't duplicate.

## With Graphify Data

When `.sacas/graphify-enrichment.json` exists, add:

```markdown
## Modules Touched

- **Auth System** (community 3) — modified `src/auth/middleware.ts`
- Cross-module edge affected: Auth → Session Management

## God Nodes Modified

- `authenticateUser` (degree: 15) — high-impact change, verify downstream
```

This helps the next session understand blast radius of changes.

## Anti-Patterns

- ❌ Vague summaries: "Worked on auth stuff"
- ❌ No file references: "Fixed a bug in the middleware"
- ❌ Prose paragraphs: Long explanations of what happened
- ❌ Stale data: Leaving old session info without updating
- ✅ Precise: "Fixed JWT expiry check in `src/auth/middleware.ts:L45`. Changed `<` to `<=`."
