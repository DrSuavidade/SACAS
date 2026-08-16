<#
.SYNOPSIS
    Orchestrator — runs all detect-*.ps1 scripts and merges results into analysis.json.
.OUTPUTS
    JSON: merged analysis object written to .sacas/analysis.json
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$scriptDir = $PSScriptRoot

Write-Host "SACAS: Analyzing $Path ..." -ForegroundColor Cyan

# Run all detectors
Write-Host "  Detecting tech stack..." -ForegroundColor DarkGray
$stack = & "$scriptDir\detect-stack.ps1" -Path $Path | ConvertFrom-Json

Write-Host "  Detecting architecture..." -ForegroundColor DarkGray
$arch = & "$scriptDir\detect-architecture.ps1" -Path $Path | ConvertFrom-Json

Write-Host "  Detecting conventions..." -ForegroundColor DarkGray
$conv = & "$scriptDir\detect-conventions.ps1" -Path $Path | ConvertFrom-Json

Write-Host "  Detecting modules..." -ForegroundColor DarkGray
$mods = & "$scriptDir\detect-modules.ps1" -Path $Path | ConvertFrom-Json

Write-Host "  Detecting existing AI configs..." -ForegroundColor DarkGray
$existing = & "$scriptDir\detect-existing-ai.ps1" -Path $Path | ConvertFrom-Json

# Check for graphify
$hasGraphify = Test-Path (Join-Path $Path "graphify-out\graph.json")

# Merge
$analysis = @{
    projectPath   = $Path.ToString()
    projectName   = (Split-Path $Path -Leaf)
    analyzedAt    = (Get-Date -Format "o")
    stack         = $stack
    architecture  = $arch
    conventions   = $conv
    modules       = $mods.modules
    existingAI    = $existing
    hasGraphify   = $hasGraphify
}

# Write to .sacas/
$sacasDir = Join-Path $Path ".sacas"
New-Item -ItemType Directory -Force -Path $sacasDir | Out-Null
$analysisPath = Join-Path $sacasDir "analysis.json"
$analysis | ConvertTo-Json -Depth 10 | Set-Content -Path $analysisPath -Encoding utf8

Write-Host ""
Write-Host "SACAS Analysis Complete:" -ForegroundColor Green
Write-Host "  Language:     $($stack.language)" -ForegroundColor White
Write-Host "  Framework:    $($stack.framework ?? 'none')" -ForegroundColor White
Write-Host "  Architecture: $($arch.pattern)" -ForegroundColor White
Write-Host "  Modules:      $($mods.modules.Count)" -ForegroundColor White
Write-Host "  Linter:       $($conv.linter ?? 'none')" -ForegroundColor White
Write-Host "  Formatter:    $($conv.formatter ?? 'none')" -ForegroundColor White
Write-Host "  Existing AI:  $($existing.found.Count) configs found" -ForegroundColor White
Write-Host "  Graphify:     $(if ($hasGraphify) { 'available' } else { 'not found' })" -ForegroundColor White
Write-Host "  Saved to:     $analysisPath" -ForegroundColor DarkGray

# Output JSON to stdout
$analysis | ConvertTo-Json -Depth 10
