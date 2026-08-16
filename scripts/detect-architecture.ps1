<#
.SYNOPSIS
    Detects architectural pattern: monolith, monorepo, or microservices.
.OUTPUTS
    JSON: { pattern, workspaceManager, services[] }
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$result = @{
    pattern          = "monolith"
    workspaceManager = $null
    services         = @()
}

# Check for workspace managers
$pkgJson = Join-Path $Path "package.json"
if (Test-Path $pkgJson) {
    $pkg = Get-Content $pkgJson -Raw | ConvertFrom-Json
    if ($pkg.workspaces) {
        $result.pattern = "monorepo"
        $result.workspaceManager = "npm-workspaces"
    }
}

$workspaceFiles = @{
    "lerna.json"          = "lerna"
    "turbo.json"          = "turborepo"
    "nx.json"             = "nx"
    "pnpm-workspace.yaml" = "pnpm"
}
foreach ($file in $workspaceFiles.Keys) {
    if (Test-Path (Join-Path $Path $file)) {
        $result.pattern = "monorepo"
        $result.workspaceManager = $workspaceFiles[$file]
        break
    }
}

# Cargo workspaces
$cargoToml = Join-Path $Path "Cargo.toml"
if (Test-Path $cargoToml) {
    $cargo = Get-Content $cargoToml -Raw
    if ($cargo -match "\[workspace\]") {
        $result.pattern = "monorepo"
        $result.workspaceManager = "cargo-workspace"
    }
}

# Multiple config files at different levels → monorepo signal
$nestedConfigs = Get-ChildItem -Path $Path -Include "package.json","go.mod","Cargo.toml" -Recurse -Depth 3 -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -ne $Path -and $_.FullName -notmatch "node_modules|vendor|target|\.git" }
if ($nestedConfigs.Count -ge 2 -and $result.pattern -eq "monolith") {
    $result.pattern = "monorepo"
}

# Docker compose → microservices signal
$composeFiles = @("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
foreach ($cf in $composeFiles) {
    $composePath = Join-Path $Path $cf
    if (Test-Path $composePath) {
        $compose = Get-Content $composePath -Raw
        # Count service definitions
        $serviceMatches = [regex]::Matches($compose, "(?m)^  \w+:") 
        if ($serviceMatches.Count -ge 3) {
            $result.pattern = "microservices"
            $result.services = @($serviceMatches | ForEach-Object { $_.Value.Trim().TrimEnd(':') })
        }
        break
    }
}

# List services for monorepo (workspace packages)
if ($result.pattern -eq "monorepo" -and $result.services.Count -eq 0) {
    $packageDirs = @("packages", "apps", "services", "libs", "modules")
    foreach ($dir in $packageDirs) {
        $dirPath = Join-Path $Path $dir
        if (Test-Path $dirPath) {
            $result.services += @(Get-ChildItem -Path $dirPath -Directory | Select-Object -ExpandProperty Name)
        }
    }
}

$result | ConvertTo-Json -Depth 5
