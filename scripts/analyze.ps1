<#
.SYNOPSIS
    Orchestrator — runs all detect-*.ps1 scripts and merges results into analysis.json.
.OUTPUTS
    JSON: merged analysis object written to .sacas/analysis.json
#>
param(
    [string]$Path = ".",
    [string]$SubDir = "Structure"
)

$Path = Resolve-Path $Path
$scriptDir = $PSScriptRoot

Write-Host "SACAS: Analyzing $Path ..." -ForegroundColor Cyan

# Proactively run graphify if available
Write-Host "  Checking for Graphify..." -ForegroundColor DarkGray
$hasGraphifyInstalled = $false
$graphifyCmd = Get-Command graphify -ErrorAction SilentlyContinue

if ($graphifyCmd) { $hasGraphifyInstalled = $true }
else {
    # Check if python has graphifyy
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        python -c "import graphify" 2>$null
        if ($LASTEXITCODE -eq 0) { $hasGraphifyInstalled = $true }
    }
}

if ($hasGraphifyInstalled) {
    Write-Host "  Graphify found. Running extraction..." -ForegroundColor Cyan
    # Check if we have API keys
    $hasKey = ($env:GEMINI_API_KEY -or $env:GOOGLE_API_KEY -or $env:ANTHROPIC_API_KEY -or $env:OPENAI_API_KEY -or $env:DEEPSEEK_API_KEY)
    
    $runSuccess = $false
    try {
        if ($hasKey) {
            # Try full extraction
            if ($graphifyCmd) {
                $process = Start-Process -FilePath "graphify" -ArgumentList "extract", "`"$Path`"" -NoNewWindow -PassThru -Wait -ErrorAction SilentlyContinue
                $runSuccess = ($process.ExitCode -eq 0)
            } else {
                python -m graphify.cli extract $Path 2>$null
                $runSuccess = ($LASTEXITCODE -eq 0)
            }
        }
        
        # Fall back to code-only if no key or full run failed
        if (-not $runSuccess) {
            Write-Host "  No LLM key or full extraction failed. Running local code-only extraction..." -ForegroundColor DarkGray
            if ($graphifyCmd) {
                $process = Start-Process -FilePath "graphify" -ArgumentList "extract", "`"$Path`"", "--code-only" -NoNewWindow -PassThru -Wait -ErrorAction SilentlyContinue
                $process2 = Start-Process -FilePath "graphify" -ArgumentList "cluster-only", "`"$Path`"" -NoNewWindow -PassThru -Wait -ErrorAction SilentlyContinue
                $runSuccess = ($process.ExitCode -eq 0 -and $process2.ExitCode -eq 0)
            } else {
                python -m graphify.cli extract $Path --code-only 2>$null
                python -m graphify.cli cluster-only $Path 2>$null
                $runSuccess = ($LASTEXITCODE -eq 0)
            }
        }
        
        if ($runSuccess) {
            Write-Host "  Graphify extraction succeeded!" -ForegroundColor Green
        } else {
            Write-Host "  Graphify extraction returned failure. Continuing with shallow scan." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  Graphify execution encountered an error: $_. Continuing with shallow scan." -ForegroundColor Yellow
    }
} else {
    Write-Host "  Graphify not installed. Continuing with shallow scan." -ForegroundColor DarkGray
}

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

# Auto-detect project description from README.md
$projectDescription = "TODO: Add project description"
$readmePath = Join-Path $Path "README.md"
if (Test-Path $readmePath) {
    try {
        $readme = Get-Content $readmePath -Raw
        # Extract first non-empty line that doesn't start with # (usually the project description)
        $lines = $readme -split "`n" | Where-Object { $_.Trim() }
        foreach ($line in $lines) {
            if ($line -notmatch "^\s*#") {
                $projectDescription = $line.Trim()
                break
            }
        }
    } catch {}
}

# Merge
$analysis = @{
    projectPath        = $Path.ToString()
    projectName        = (Split-Path $Path -Leaf)
    projectDescription = $projectDescription
    analyzedAt         = (Get-Date -Format "o")
    stack              = $stack
    architecture       = $arch
    conventions        = $conv
    modules            = $mods.modules
    existingAI         = $existing
    hasGraphify        = $hasGraphify
}

# Write to .sacas/
$sacasDir = if ($SubDir) { Join-Path $Path "$SubDir\.sacas" } else { Join-Path $Path ".sacas" }
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
