<#
.SYNOPSIS
    Identifies logical module boundaries in the codebase.
.OUTPUTS
    JSON: { modules: [{ name, path, entryPoint, fileCount, estimatedLines }] }
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$excludeDirs = @("node_modules", ".git", "vendor", "target", "build", "dist", "__pycache__", ".next", ".nuxt", "venv", ".venv", "env", ".sacas", "graphify-out")

function Get-ModuleInfo {
    param([string]$ModulePath, [string]$Name)

    $files = Get-ChildItem -Path $ModulePath -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object {
            $rel = $_.FullName.Substring($ModulePath.Length)
            $skip = $false
            foreach ($ex in $excludeDirs) {
                if ($rel -match [regex]::Escape("\$ex\") -or $rel -match [regex]::Escape("/$ex/")) { $skip = $true; break }
            }
            -not $skip
        }

    $fileCount = ($files | Measure-Object).Count
    $totalBytes = 0
    $codeExts = @(".js", ".ts", ".jsx", ".tsx", ".py", ".rs", ".go", ".java", ".kt", ".cs", ".rb", ".php", ".c", ".cpp", ".h", ".vue", ".svelte")
    foreach ($f in $files) {
        if ($codeExts -contains $f.Extension) { $totalBytes += $f.Length }
    }
    # Estimate: ~40 bytes per line of code on average
    $lineCount = [math]::Round($totalBytes / 40)

    # Find entry point
    $entryNames = @("index.ts", "index.js", "index.tsx", "main.ts", "main.js", "mod.rs", "lib.rs", "main.py", "__init__.py", "main.go", "README.md")
    $entryPoint = $null
    foreach ($e in $entryNames) {
        $ep = Join-Path $ModulePath $e
        if (Test-Path $ep) { $entryPoint = $e; break }
    }

    @{
        name           = $Name
        path           = $ModulePath.Replace($Path, "").TrimStart("\", "/")
        entryPoint     = $entryPoint
        fileCount      = $fileCount
        estimatedLines = $lineCount
    }
}

$modules = @()

# Check src/ subdirectories first
$srcDir = Join-Path $Path "src"
if (Test-Path $srcDir) {
    $srcSubs = Get-ChildItem -Path $srcDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $excludeDirs -notcontains $_.Name }
    foreach ($sub in $srcSubs) {
        $modules += Get-ModuleInfo -ModulePath $sub.FullName -Name $sub.Name
    }
}

# Check common monorepo dirs
$monorepoDirs = @("packages", "apps", "services", "libs", "modules")
foreach ($dir in $monorepoDirs) {
    $dirPath = Join-Path $Path $dir
    if (Test-Path $dirPath) {
        $subs = Get-ChildItem -Path $dirPath -Directory -ErrorAction SilentlyContinue |
            Where-Object { $excludeDirs -notcontains $_.Name }
        foreach ($sub in $subs) {
            $modules += Get-ModuleInfo -ModulePath $sub.FullName -Name $sub.Name
        }
    }
}

# If no modules found from src/ or monorepo dirs, use top-level dirs
if ($modules.Count -eq 0) {
    $topDirs = Get-ChildItem -Path $Path -Directory -ErrorAction SilentlyContinue |
        Where-Object { $excludeDirs -notcontains $_.Name -and $_.Name -notmatch "^\." }
    foreach ($sub in $topDirs) {
        $info = Get-ModuleInfo -ModulePath $sub.FullName -Name $sub.Name
        if ($info.fileCount -gt 0) {
            $modules += $info
        }
    }
}

@{ modules = $modules } | ConvertTo-Json -Depth 5
