# SACAS Documentation Accuracy Design

## Purpose

Make the current public SACAS contract discoverable and prevent the documented
CLI surface from silently drifting from the executable one.

## Decisions

1. `README.md` is the complete user-facing CLI reference. It documents every
   public command and supported option that materially changes behavior,
   including machine-readable formats and migration apply mode.
2. `SKILL.md` is the concise agent-facing operational guide. It includes the
   canonical state pair and all routine commands, including expansion,
   diagnostics, and workflow pipelines.
3. Historical specs and implementation plans remain versioned engineering
   records. They receive an explicit archival banner when their stated command
   surface predates current SACAS, rather than being rewritten as current
   documentation.
4. A documentation regression test asserts that the README contains every
   command, material option, and pipeline subcommand exposed by the CLI, and
   that the skill contains the canonical pair and routine operations. The test
   is not a Markdown parser; it guards stable public-contract anchors.

## Non-goals

Do not rewrite historical design rationale, alter command behavior, or claim
that Graphify is available when its optional local evidence is absent. Both
legacy router plans and the legacy v2-routing plan remain historical records.
