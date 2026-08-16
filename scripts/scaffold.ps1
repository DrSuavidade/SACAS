<#
.SYNOPSIS
    Main scaffolder — reads analysis.json + templates, generates folder structure.
.PARAMETER Path
    Project root directory.
.PARAMETER AnalysisPath
    Path to analysis.json. Defaults to .sacas/analysis.json in project root.
.PARAMETER Mode
    'replace' (default) or 'merge'.
.PARAMETER TemplatePath
    Path to templates directory. Defaults to sibling templates/ dir.
#>
param(
    [string]$Path = ".",
    [string]$AnalysisPath,
    [ValidateSet("replace", "merge")]
    [string]$Mode = "replace",
    [string]$TemplatePath,
    [string]$SubDir = "Structure",
    [switch]$NonInteractive
)

$Path = Resolve-Path $Path
if (-not $AnalysisPath) { 
    $AnalysisPath = if ($SubDir) { Join-Path $Path "$SubDir\.sacas\analysis.json" } else { Join-Path $Path ".sacas\analysis.json" }
}
if (-not $TemplatePath) { $TemplatePath = Join-Path $PSScriptRoot "..\templates" }

if (-not (Test-Path $AnalysisPath)) {
    Write-Error "No analysis.json found at $AnalysisPath. Run analyze.ps1 first."
    exit 1
}

$analysis = Get-Content $AnalysisPath -Raw | ConvertFrom-Json
$created = @()

function Read-Template {
    param([string]$Name)
    $tp = Join-Path $TemplatePath $Name
    if (Test-Path $tp) { return Get-Content $tp -Raw }
    Write-Warning "Template not found: $Name"
    return ""
}

function Write-Scaffold {
    param([string]$FilePath, [string]$Content, [bool]$IsMerge = $false)
    # Prepend SubDir for files that do not live at the root (.gitignore, .cursorignore, .aiignore)
    $targetPath = $FilePath
    if ($SubDir -and $FilePath -notmatch "^\.gitignore|^\.cursorignore|^\.aiignore") {
        $targetPath = Join-Path $SubDir $FilePath
    }
    $fullPath = Join-Path $Path $targetPath
    $dir = Split-Path $fullPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }

    if ($IsMerge -and (Test-Path $fullPath)) {
        $existing = Get-Content $fullPath -Raw
        $Content = "$existing`n`n<!-- SACAS-GENERATED -->`n`n$Content"
    }
    Set-Content -Path $fullPath -Value $Content -Encoding utf8
    $script:created += $targetPath
}

# Build substitution values
$techStack = (@($analysis.stack.language, $analysis.stack.framework, $analysis.stack.packageManager) | Where-Object { $_ }) -join ", "
$conventions = @()
if ($analysis.conventions.linter) { $conventions += "Linter: $($analysis.conventions.linter)" }
if ($analysis.conventions.formatter) { $conventions += "Formatter: $($analysis.conventions.formatter)" }
if ($analysis.conventions.typescriptStrict) { $conventions += "TypeScript: strict mode" }
$conventionsStr = if ($conventions.Count -gt 0) { $conventions -join "`n- " } else { "No linter/formatter configs detected. Add conventions here." }

# Build file org map
$fileOrg = @()
foreach ($mod in $analysis.modules) {
    $entry = if ($mod.entryPoint) { " (entry: $($mod.entryPoint))" } else { "" }
    $fileOrg += "$($mod.path)/ — $($mod.name)$entry [$($mod.fileCount) files]"
}
$fileOrgStr = if ($fileOrg.Count -gt 0) { $fileOrg -join "`n" } else { "No modules detected. Document your file organization here." }

$isMerge = ($Mode -eq "merge")

Write-Host "SACAS: Scaffolding $Path (mode=$Mode) ..." -ForegroundColor Cyan

$projectDescription = if ($analysis.projectDescription) { $analysis.projectDescription } else { "TODO: Add project description" }
$projectConstraints = "TODO: Add project constraints and anti-patterns"
$verificationCommand = "<!-- TODO: Verification command (e.g. npm test) -->"
$verificationPurpose = "<!-- TODO: Describe purpose -->"

if (-not $NonInteractive) {
    Write-Host ""
    Write-Host "=== SACAS Interactive Setup ===" -ForegroundColor Cyan
    Write-Host "Auto-detected project description: $projectDescription" -ForegroundColor DarkGray
    $userDesc = Read-Host "Enter project description (press Enter to accept auto)"
    if ($userDesc -and $userDesc.Trim()) { $projectDescription = $userDesc.Trim() }

    $userConstraints = Read-Host "Enter project constraints / anti-patterns (press Enter to skip)"
    if ($userConstraints -and $userConstraints.Trim()) { $projectConstraints = $userConstraints.Trim() }

    $userCommand = Read-Host "Enter default verification / test command (e.g. npm test, press Enter to skip)"
    if ($userCommand -and $userCommand.Trim()) {
        $verificationCommand = $userCommand.Trim()
        $verificationPurpose = "Project test/validation execution"
    }
    Write-Host "=== Configuration Complete ===`n" -ForegroundColor Cyan
}

# 1. Create directories
$dirs = @(".ai/rules", ".ai/prompts", "context", "tasks/current", "tasks/backlog", "tasks/completed", "references")
foreach ($d in $dirs) {
    $targetDir = if ($SubDir) { Join-Path $SubDir $d } else { $d }
    $dp = Join-Path $Path $targetDir
    if (-not (Test-Path $dp)) { New-Item -ItemType Directory -Force -Path $dp | Out-Null }
}
# Only create scripts/ if not exists
$scriptsDir = if ($SubDir) { Join-Path $Path "$SubDir\scripts" } else { Join-Path $Path "scripts" }
if (-not (Test-Path $scriptsDir)) { New-Item -ItemType Directory -Force -Path $scriptsDir | Out-Null }

# 2. Root AGENTS.md
$agentsMd = Read-Template "AGENTS.md.template"
$agentsMd = $agentsMd -replace "{{PROJECT_NAME}}", $analysis.projectName
$agentsMd = $agentsMd -replace "{{PROJECT_DESCRIPTION}}", $projectDescription
$agentsMd = $agentsMd -replace "{{TECH_STACK}}", $techStack
$agentsMd = $agentsMd -replace "{{PACKAGE_MANAGER}}", ($analysis.stack.packageManager ?? "N/A")
$agentsMd = $agentsMd -replace "{{ARCHITECTURE_PATTERN}}", $analysis.architecture.pattern
$agentsMd = $agentsMd -replace "{{ARCHITECTURE_DESCRIPTION}}", "Services: $(if ($analysis.architecture.services) { $analysis.architecture.services -join ', ' } else { 'N/A' })"
$agentsMd = $agentsMd -replace "{{CONVENTIONS}}", "- $conventionsStr"
$agentsMd = $agentsMd -replace "{{FILE_ORGANIZATION_MAP}}", $fileOrgStr
$agentsMd = $agentsMd -replace "{{CONSTRAINTS}}", $projectConstraints
Write-Scaffold "AGENTS.md" $agentsMd -IsMerge $isMerge

# 2b. .gitignore for .sacas/
$gitignorePath = Join-Path $Path ".gitignore"
$sacasIgnore = if ($SubDir) { "$SubDir/.sacas/" } else { ".sacas/" }
if (Test-Path $gitignorePath) {
    $existing = Get-Content $gitignorePath -Raw
    if ($existing -notmatch [regex]::Escape($sacasIgnore)) {
        Add-Content -Path $gitignorePath -Value "`n# SACAS generated data`n$sacasIgnore"
    }
} else {
    Set-Content -Path $gitignorePath -Value "# SACAS generated data`n$sacasIgnore" -Encoding utf8
}

# 2c. Starter .ai/rules file from detected conventions
$rulesMd = Read-Template "conventions.md.template"
$rulesMd = $rulesMd -replace "{{LANGUAGE}}", ($analysis.stack.language ?? "Not detected")
$rulesMd = $rulesMd -replace "{{LINTER}}", ($analysis.conventions.linter ?? "Not detected")
$rulesMd = $rulesMd -replace "{{FORMATTER}}", ($analysis.conventions.formatter ?? "Not detected")
$rulesMd = $rulesMd -replace "{{STRICT_CHECKS}}", $(if ($analysis.conventions.typescriptStrict) { "TypeScript strict mode enabled" } else { "None" })
Write-Scaffold ".ai/rules/conventions.md" $rulesMd -IsMerge $isMerge

# 2d. .aiignore / .cursorignore
$aiignore = Read-Template "aiignore.template"
if ($SubDir) {
    # Replace relative patterns with SubDir prefixed patterns
    $aiignore = $aiignore -replace "(?m)^(\.sacas/|tasks/completed/|graphify-out/)", "$SubDir/`$1"
}
Write-Scaffold ".aiignore" $aiignore -IsMerge $isMerge
Write-Scaffold ".cursorignore" $aiignore -IsMerge $isMerge

# 2e. Task Runner instructions in prompts
$runnerMd = Read-Template "task-runner.md.template"
Write-Scaffold ".ai/prompts/task-runner.md" $runnerMd -IsMerge $isMerge

# 3. Architecture
$archMd = Read-Template "architecture.md.template"
$archMd = $archMd -replace "{{SYSTEM_OVERVIEW}}", "$($analysis.projectName) — $($analysis.architecture.pattern) ($techStack)"
$components = ($analysis.modules | ForEach-Object { "- **$($_.name)** ($($_.path)) — $($_.fileCount) files, ~$($_.estimatedLines) lines" }) -join "`n"
$archMd = $archMd -replace "{{MERMAID_COMPONENTS}}", ($analysis.modules | ForEach-Object { "    $($_.name)[$($_.name)]" }) -join "`n"
$archMd = $archMd -replace "{{COMPONENTS}}", ($components ?? "No modules detected.")
$archMd = $archMd -replace "{{DATA_FLOW}}", "TODO: Document data flow between components"
$archMd = $archMd -replace "{{DEP_NAME}}", "TODO"
$archMd = $archMd -replace "{{DEP_VERSION}}", "TODO"
$archMd = $archMd -replace "{{DEP_PURPOSE}}", "TODO"
$archMd = $archMd -replace "{{DEPLOYMENT}}", "TODO: Document deployment topology"
Write-Scaffold "context/architecture.md" $archMd -IsMerge $isMerge

# 4. PICKUP.md
$pickupMd = Read-Template "PICKUP.md.template"
$pickupMd = $pickupMd -replace "{{LAST_UPDATED}}", (Get-Date -Format "yyyy-MM-dd HH:mm")
$pickupMd = $pickupMd -replace "{{SESSION_SUMMARY}}", "Initial SACAS scaffold generated."
$pickupMd = $pickupMd -replace "{{IN_PROGRESS_ITEM}}", "Review and customize generated AGENTS.md"
$pickupMd = $pickupMd -replace "{{OPEN_DECISION}}", "Customize constraints and conventions in AGENTS.md"
$pickupMd = $pickupMd -replace "{{KNOWN_ISSUE}}", "None"
$pickupMd = $pickupMd -replace "{{PRIORITY_ITEM}}", "Fill in TODO sections in generated files"
Write-Scaffold "PICKUP.md" $pickupMd -IsMerge $isMerge

# 5. Task templates in tasks/
$taskMd = Read-Template "TASK.md.template"
$taskMd = $taskMd -replace "{{TASK_TITLE}}", "<!-- TODO: Task title -->"
$taskMd = $taskMd -replace "{{STATUS}}", "todo"
$taskMd = $taskMd -replace "{{PRIORITY}}", "<!-- TODO: Set priority -->"
$taskMd = $taskMd -replace "{{CREATED_DATE}}", (Get-Date -Format "yyyy-MM-dd")
$taskMd = $taskMd -replace "{{TASK_DESCRIPTION}}", "<!-- TODO: Describe the task -->"
$taskMd = $taskMd -replace "{{CRITERION}}", "<!-- TODO: Define acceptance criteria -->"
$taskMd = $taskMd -replace "{{RELATED_TASK}}", "None"
$taskMd = $taskMd -replace "{{NOTES}}", ""
Write-Scaffold "tasks/current/TASK.md" $taskMd -IsMerge $isMerge

$contextMd = Read-Template "CONTEXT.md.template"
$contextMd = $contextMd -replace "{{TASK_NAME}}", "<!-- TODO: Task name -->"
$contextMd = $contextMd -replace "{{FILE_PATH}}", "<!-- TODO: Add relevant file path -->"
$contextMd = $contextMd -replace "{{FILE_NOTES}}", "<!-- TODO: Describe role of this file -->"
$contextMd = $contextMd -replace "{{FUNCTION_NAME}}", "<!-- TODO -->"
$contextMd = $contextMd -replace "{{FILE}}", "<!-- TODO -->"
$contextMd = $contextMd -replace "{{START}}", "0"
$contextMd = $contextMd -replace "{{END}}", "0"
$contextMd = $contextMd -replace "{{DESCRIPTION}}", "<!-- TODO -->"
$contextMd = $contextMd -replace "{{DEPENDENCY}}", "<!-- TODO -->"
$contextMd = $contextMd -replace "{{VERSION}}", "<!-- TODO -->"
$contextMd = $contextMd -replace "{{WHY_RELEVANT}}", "<!-- TODO -->"
$contextMd = $contextMd -replace "{{CONSTRAINT}}", "<!-- TODO: Add constraints -->"
$contextMd = $contextMd -replace "{{VERIFICATION_COMMAND}}", $verificationCommand
$contextMd = $contextMd -replace "{{VERIFICATION_PURPOSE}}", $verificationPurpose
$contextMd = $contextMd -replace "{{EXCLUDED_PATH}}", "<!-- TODO: Add exclusions -->"
$contextMd = $contextMd -replace "{{REASON}}", "<!-- TODO -->"
Write-Scaffold "tasks/current/CONTEXT.md" $contextMd -IsMerge $isMerge

$progressMd = Read-Template "PROGRESS.md.template"
$progressMd = $progressMd -replace "{{SESSION_DATE}}", (Get-Date -Format "yyyy-MM-dd")
$progressMd = $progressMd -replace "{{CURRENT_STATUS}}", "Not started"
$progressMd = $progressMd -replace "{{DECISION}}", "None yet"
$progressMd = $progressMd -replace "{{BLOCKER}}", "None"
$progressMd = $progressMd -replace "{{FILE_PATH}}", "N/A"
$progressMd = $progressMd -replace "{{CHANGE_DESCRIPTION}}", "N/A"
$progressMd = $progressMd -replace "{{NEXT_STEP}}", "Begin task"
Write-Scaffold "tasks/current/PROGRESS.md" $progressMd -IsMerge $isMerge

# 6. Reference stubs for each module
foreach ($mod in $analysis.modules) {
    $refContent = @"
# $($mod.name)

> Reference documentation for the **$($mod.name)** module.
> Load this file only when working on this module.

## Overview

- **Path:** ``$($mod.path)``
- **Files:** $($mod.fileCount)
- **Lines:** ~$($mod.estimatedLines)
$(if ($mod.entryPoint) { "- **Entry:** ``$($mod.entryPoint)``" })

## Key Concepts

TODO: Document key concepts, patterns, and domain knowledge for this module.

## Common Operations

TODO: Document common tasks performed in this module.
"@
    $safeName = $mod.name -replace "[^a-zA-Z0-9_-]", "-"
    Write-Scaffold "references/$safeName.md" $refContent -IsMerge $isMerge
}

# Summary
Write-Host ""
Write-Host "SACAS Scaffold Complete:" -ForegroundColor Green
Write-Host "  Files created: $($created.Count)" -ForegroundColor White
foreach ($f in $created) {
    Write-Host "    + $f" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Review and customize AGENTS.md (fill in TODOs)" -ForegroundColor White
Write-Host "  2. Update context/architecture.md with real architecture" -ForegroundColor White
Write-Host "  3. Fill in references/ stubs with domain knowledge" -ForegroundColor White
Write-Host "  4. For each task: create tasks/current/CONTEXT.md scoped to that task" -ForegroundColor White
