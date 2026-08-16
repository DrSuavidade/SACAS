<#
.SYNOPSIS
    Auto-generates per-module CONTEXT.md files using graphify enrichment data.
    Creates task folders in tasks/backlog/ with pre-populated CONTEXT.md for each community.
.PARAMETER Path
    Project root directory.
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$enrichPath = Join-Path $Path ".sacas\graphify-enrichment.json"
$analysisPath = Join-Path $Path ".sacas\analysis.json"

if (-not (Test-Path $enrichPath)) {
    Write-Error "No graphify enrichment found. Run read-graphify.ps1 first."
    exit 1
}

$enrichment = Get-Content $enrichPath -Raw | ConvertFrom-Json
$analysis = if (Test-Path $analysisPath) { Get-Content $analysisPath -Raw | ConvertFrom-Json } else { $null }

Write-Host "SACAS: Generating enriched CONTEXT.md files..." -ForegroundColor Cyan
$created = @()

foreach ($community in $enrichment.communities) {
    $name = $community.label -replace "[^a-zA-Z0-9_-]", "-"
    $taskDir = Join-Path $Path "tasks\backlog\$name"
    New-Item -ItemType Directory -Force -Path $taskDir | Out-Null

    # Build relevant files list
    $filesTable = @()
    foreach ($f in $community.files) {
        if ($f) { $filesTable += "| ``$f`` | read-only | Part of $($community.label) |" }
    }
    $filesSection = if ($filesTable.Count -gt 0) {
        "| File | Action | Notes |`n|:---|:---|:---|`n" + ($filesTable -join "`n")
    } else {
        "No files detected for this module."
    }

    # Build key functions from nodes
    $funcSection = @()
    foreach ($node in $community.nodes) {
        if ($node.type -eq "function" -or $node.type -eq "class" -or $node.type -eq "method") {
            $loc = if ($node.file) { " in ``$($node.file)``" } else { "" }
            $funcSection += "- ``$($node.id)``$loc"
        }
    }
    $funcStr = if ($funcSection.Count -gt 0) { $funcSection -join "`n" } else { "No key functions detected." }

    # Build cross-module dependencies
    $deps = @()
    foreach ($edge in $enrichment.crossEdges) {
        if ($edge.sourceCommunity -eq $community.id) {
            $targetLabel = ($enrichment.communities | Where-Object { $_.id -eq $edge.targetCommunity } | Select-Object -First 1).label
            $deps += "- ``$($edge.target)`` in **$targetLabel** ($($edge.relation))"
        }
    }
    $depsStr = if ($deps.Count -gt 0) { $deps | Select-Object -Unique | Select-Object -First 15 | Join-String -Separator "`n" } else { "No cross-module dependencies detected." }

    # Build DO NOT Touch list (other communities)
    $excludes = @()
    foreach ($otherCom in $enrichment.communities) {
        if ($otherCom.id -ne $community.id -and $otherCom.files.Count -gt 0) {
            $excludes += "- Files in **$($otherCom.label)** — different module"
        }
    }
    $excludeStr = if ($excludes.Count -gt 0) { $excludes | Select-Object -First 10 | Join-String -Separator "`n" } else { "N/A" }

    $contextContent = @"
# Context for: $($community.label)

> Auto-generated from graphify community analysis. Review and customize before use.

## Relevant Files

$filesSection

## Key Functions

$funcStr

## Dependencies (Cross-Module)

$depsStr

## Constraints

- Review cross-module edges before modifying shared interfaces

## DO NOT Touch

$excludeStr
"@

    $contextPath = Join-Path $taskDir "CONTEXT.md"
    Set-Content -Path $contextPath -Value $contextContent -Encoding utf8
    $created += "tasks/backlog/$name/CONTEXT.md"
}

# Enrich references/ stubs with graphify data
foreach ($community in $enrichment.communities) {
    $name = $community.label -replace "[^a-zA-Z0-9_-]", "-"
    $refPath = Join-Path $Path "references\$name.md"

    # Find god nodes in this community
    $communityGods = @()
    foreach ($god in $enrichment.godNodes) {
        $godNode = $community.nodes | Where-Object { $_.id -eq $god.id }
        if ($godNode) {
            $communityGods += "- **$($god.id)** (degree: $($god.degree)) — high connectivity, modify with care"
        }
    }

    $refContent = @"
# $($community.label)

> Reference documentation enriched by graphify analysis.
> Load this file only when working on this module.

## Overview

- **Community ID:** $($community.id)
- **Files:** $($community.files.Count)
- **Nodes:** $($community.nodes.Count) (functions, classes, concepts)

## Critical Nodes (God Nodes)

$(if ($communityGods.Count -gt 0) { $communityGods -join "`n" } else { "No god nodes in this community." })

## Files in This Module

$(($community.files | ForEach-Object { "- ``$_``" }) -join "`n")

## Key Concepts

TODO: Document key concepts, patterns, and domain knowledge for this module.
"@
    Set-Content -Path $refPath -Value $refContent -Encoding utf8
    $created += "references/$name.md"
}

# Enrich context/architecture.md with cross-module relationships
$archPath = Join-Path $Path "context\architecture.md"
if (Test-Path $archPath) {
    $archContent = Get-Content $archPath -Raw

    $mermaidLines = @("graph TD")
    foreach ($com in $enrichment.communities) {
        $mermaidLines += "    $($com.label -replace ' ','_')[$($com.label)]"
    }
    # Add edges between communities
    $edgePairs = @{}
    foreach ($edge in $enrichment.crossEdges) {
        $srcLabel = ($enrichment.communities | Where-Object { $_.id -eq $edge.sourceCommunity } | Select-Object -First 1).label -replace ' ','_'
        $tgtLabel = ($enrichment.communities | Where-Object { $_.id -eq $edge.targetCommunity } | Select-Object -First 1).label -replace ' ','_'
        $pair = "$srcLabel-->$tgtLabel"
        if (-not $edgePairs.ContainsKey($pair)) {
            $edgePairs[$pair] = $true
            $mermaidLines += "    $pair"
        }
    }
    $mermaidBlock = $mermaidLines -join "`n"

    # Use SACAS markers to only replace our own mermaid block, not user's
    $sacasMermaid = "<!-- SACAS-MERMAID-START -->`n``````mermaid`n$mermaidBlock`n```````n<!-- SACAS-MERMAID-END -->"

    if ($archContent -match "<!-- SACAS-MERMAID-START -->") {
        # Replace existing SACAS mermaid block
        $archContent = $archContent -replace "(?s)<!-- SACAS-MERMAID-START -->.*?<!-- SACAS-MERMAID-END -->", $sacasMermaid
    } elseif ($archContent -match "(?ms)``````mermaid.*?``````") {
        # First run — replace the template mermaid placeholder, wrap with markers
        $archContent = $archContent -replace "(?ms)``````mermaid.*?``````", $sacasMermaid
    } else {
        # No mermaid block at all — append after ## Component Diagram
        $archContent = $archContent -replace "(## Component Diagram)", "`$1`n`n$sacasMermaid"
    }
    Set-Content -Path $archPath -Value $archContent -Encoding utf8
}

Write-Host ""
Write-Host "Graphify Enrichment Complete:" -ForegroundColor Green
Write-Host "  Files created/updated: $($created.Count)" -ForegroundColor White
foreach ($f in $created) {
    Write-Host "    + $f" -ForegroundColor DarkGray
}
