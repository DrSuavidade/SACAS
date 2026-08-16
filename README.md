# SACAS — Scaffold Analyzer Context Architect

Generate AI-optimized folder structures for any codebase. Filesystem = orchestration. Folders = memory. Markdown = interface.

SACAS analyzes a project's tech stack, architecture, conventions, and module boundaries, then scaffolds a structured workspace that gives AI agents precisely scoped context per task — reducing token usage by ~85%.

## Quick Start

```bash
# Copy to your AI tool's skills directory
# Antigravity
cp -r . ~/.gemini/config/skills/sacas/

# Claude Code
cp -r . ~/.claude/skills/sacas/

# Then in any project:
/sacas                    # analyze + scaffold
/sacas-merge              # preserve existing AI configs
/sacas-status             # check structure health
```

## What It Does

1. **Analyzes** your codebase — detects language, framework, architecture pattern, linter/formatter, module boundaries, and existing AI configs
2. **Scaffolds** a folder structure with scoped context files:

```
your-project/
├── AGENTS.md                  # Root agent instructions
├── PICKUP.md                  # Session handoff
├── .ai/rules/                 # Coding standards
├── context/
│   └── architecture.md        # System architecture
├── tasks/
│   ├── current/               # Active work (TASK.md + CONTEXT.md + PROGRESS.md)
│   ├── backlog/               # Queued tasks
│   └── completed/             # Done tasks
├── references/                # Per-module deep docs (loaded on demand)
└── .sacas/
    └── analysis.json          # Cached analysis
```

3. **Enriches** with [graphify](https://github.com/your-org/graphify) data (optional) — communities become module boundaries, god nodes get flagged, cross-module edges pre-populate CONTEXT.md files

## Key Concept

**CONTEXT.md is the token-saving secret.** Each task gets a CONTEXT.md that lists exactly which files are relevant. The agent reads ONLY those files — not the full codebase.

## Supported Stacks

| Language | Frameworks | Config Detection |
|:---|:---|:---|
| TypeScript/JavaScript | React, Next.js, Vue, Angular, Svelte, Express, Fastify | package.json, tsconfig.json |
| Python | Django, Flask, FastAPI | pyproject.toml, requirements.txt |
| Rust | — | Cargo.toml |
| Go | — | go.mod |
| Java/Kotlin | — | pom.xml, build.gradle |
| .NET | — | .csproj, .sln |
| Ruby | — | Gemfile |
| PHP | — | composer.json |

Architecture detection: monolith, monorepo (npm/pnpm/cargo/lerna/turbo/nx workspaces), microservices (docker-compose).

## File Structure

```
sacas/
├── SKILL.md                    # Skill definition (read by AI tools)
├── scripts/
│   ├── analyze.ps1             # Orchestrator
│   ├── detect-stack.ps1        # Tech stack detection
│   ├── detect-architecture.ps1 # Architecture pattern
│   ├── detect-conventions.ps1  # Linter/formatter detection
│   ├── detect-modules.ps1      # Module boundary detection
│   ├── detect-existing-ai.ps1  # Existing AI config detection
│   ├── scaffold.ps1            # Main scaffolder
│   ├── read-graphify.ps1       # Graphify data reader
│   └── generate-context-md.ps1 # Auto-generates CONTEXT.md from graphify
├── templates/                  # Markdown templates stamped out by scaffold
├── hooks/                      # Session lifecycle instructions
└── references/                 # Format guides and usage docs
```

## Portability

Works with any AI coding tool:

| Tool | How to Use |
|:---|:---|
| **Antigravity** | Copy to `~/.gemini/config/skills/sacas/` |
| **Claude Code** | Copy to `~/.claude/skills/sacas/`, rename AGENTS.md → CLAUDE.md |
| **Cursor** | Copy AGENTS.md content into `.cursorrules` |
| **GitHub Copilot** | Copy key sections to `.github/copilot-instructions.md` |
| **Any LLM** | Markdown files are universal |

## Requirements

- PowerShell 7+ (pwsh)
- Works on Windows, macOS (with pwsh), Linux (with pwsh)

## License

MIT
