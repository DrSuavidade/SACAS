<#
.SYNOPSIS
    Finds existing AI configuration files in the codebase.
.OUTPUTS
    JSON: { found: [{ type, path, sizeBytes }], hasExisting: bool }
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$found = @()

$targets = @(
    @{ pattern = "CLAUDE.md";    type = "claude-md" }
    @{ pattern = "claude.md";    type = "claude-md" }
    @{ pattern = "AGENTS.md";    type = "agents-md" }
    @{ pattern = ".cursorrules"; type = "cursor-rules" }
    @{ pattern = ".cursorignore"; type = "cursor-ignore" }
    @{ pattern = "CONTEXT.md";   type = "context-md" }
)

# Check root-level files
foreach ($t in $targets) {
    $fp = Join-Path $Path $t.pattern
    if (Test-Path $fp) {
        $found += @{
            type      = $t.type
            path      = $fp.Replace($Path, "").TrimStart("\", "/")
            sizeBytes = (Get-Item $fp).Length
        }
    }
}

# Check for AGENTS.md in subdirs (max depth 3)
$agentsMds = Get-ChildItem -Path $Path -Filter "AGENTS.md" -Recurse -Depth 3 -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -ne $Path -and $_.FullName -notmatch "node_modules|\.git|vendor" }
foreach ($f in $agentsMds) {
    $found += @{
        type      = "agents-md-nested"
        path      = $f.FullName.Replace($Path, "").TrimStart("\", "/")
        sizeBytes = $f.Length
    }
}

# Check for CONTEXT.md in subdirs
$contextMds = Get-ChildItem -Path $Path -Filter "CONTEXT.md" -Recurse -Depth 3 -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -ne $Path -and $_.FullName -notmatch "node_modules|\.git|vendor" }
foreach ($f in $contextMds) {
    $found += @{
        type      = "context-md-nested"
        path      = $f.FullName.Replace($Path, "").TrimStart("\", "/")
        sizeBytes = $f.Length
    }
}

# Check for directories
$aiDirs = @(
    @{ name = ".claude"; type = "claude-dir" }
    @{ name = ".ai";     type = "ai-dir" }
    @{ name = ".gemini"; type = "gemini-dir" }
)
foreach ($d in $aiDirs) {
    $dp = Join-Path $Path $d.name
    if (Test-Path $dp -PathType Container) {
        $found += @{
            type      = $d.type
            path      = $d.name
            sizeBytes = 0
        }
    }
}

# GitHub Copilot instructions
$copilot = Join-Path $Path ".github\copilot-instructions.md"
if (Test-Path $copilot) {
    $found += @{
        type      = "copilot-instructions"
        path      = ".github\copilot-instructions.md"
        sizeBytes = (Get-Item $copilot).Length
    }
}

@{
    found       = $found
    hasExisting = ($found.Count -gt 0)
} | ConvertTo-Json -Depth 5
