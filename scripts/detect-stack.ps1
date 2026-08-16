<#
.SYNOPSIS
    Detects the tech stack of a project by reading config files.
.OUTPUTS
    JSON: { language, framework, packageManager, containerized, dependencies, devDependencies }
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$result = @{
    language       = $null
    framework      = $null
    packageManager = $null
    containerized  = $false
    dependencies   = @()
    devDependencies = @()
}

# Node/JS/TS
$pkgJson = Join-Path $Path "package.json"
if (Test-Path $pkgJson) {
    $pkg = Get-Content $pkgJson -Raw | ConvertFrom-Json
    $result.language = "javascript"

    # Check for TypeScript
    $tsConfig = Join-Path $Path "tsconfig.json"
    if (Test-Path $tsConfig) { $result.language = "typescript" }

    # Detect framework from dependencies
    $allDeps = @{}
    if ($pkg.dependencies) {
        $pkg.dependencies.PSObject.Properties | ForEach-Object { $allDeps[$_.Name] = $_.Value }
        $result.dependencies = @($pkg.dependencies.PSObject.Properties.Name)
    }
    if ($pkg.devDependencies) {
        $pkg.devDependencies.PSObject.Properties | ForEach-Object { $allDeps[$_.Name] = $_.Value }
        $result.devDependencies = @($pkg.devDependencies.PSObject.Properties.Name)
    }

    $frameworkMap = @{
        "next"    = "nextjs"
        "react"   = "react"
        "vue"     = "vue"
        "@angular/core" = "angular"
        "svelte"  = "svelte"
        "nuxt"    = "nuxt"
        "express" = "express"
        "fastify" = "fastify"
    }
    foreach ($key in $frameworkMap.Keys) {
        if ($allDeps.ContainsKey($key)) {
            $result.framework = $frameworkMap[$key]
            break
        }
    }

    # Package manager
    if ($pkg.packageManager) {
        $result.packageManager = ($pkg.packageManager -split "@")[0]
    } elseif (Test-Path (Join-Path $Path "pnpm-lock.yaml")) {
        $result.packageManager = "pnpm"
    } elseif (Test-Path (Join-Path $Path "yarn.lock")) {
        $result.packageManager = "yarn"
    } elseif (Test-Path (Join-Path $Path "bun.lockb")) {
        $result.packageManager = "bun"
    } else {
        $result.packageManager = "npm"
    }
}

# Rust
if (Test-Path (Join-Path $Path "Cargo.toml")) { $result.language = "rust" }

# Go
if (Test-Path (Join-Path $Path "go.mod")) { $result.language = "go" }

# Python
$pyFiles = @("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg")
foreach ($f in $pyFiles) {
    if (Test-Path (Join-Path $Path $f)) {
        $result.language = "python"
        # Detect framework
        $reqFile = Join-Path $Path "requirements.txt"
        $pyProj = Join-Path $Path "pyproject.toml"
        $content = ""
        if (Test-Path $reqFile) { $content = Get-Content $reqFile -Raw }
        elseif (Test-Path $pyProj) { $content = Get-Content $pyProj -Raw }
        if ($content -match "django") { $result.framework = "django" }
        elseif ($content -match "fastapi") { $result.framework = "fastapi" }
        elseif ($content -match "flask") { $result.framework = "flask" }
        break
    }
}

# Java/Kotlin
if (Test-Path (Join-Path $Path "pom.xml")) { $result.language = "java" }
if (Test-Path (Join-Path $Path "build.gradle")) {
    $gradle = Get-Content (Join-Path $Path "build.gradle") -Raw
    $result.language = if ($gradle -match "kotlin") { "kotlin" } else { "java" }
}
if (Test-Path (Join-Path $Path "build.gradle.kts")) { $result.language = "kotlin" }

# .NET
$csproj = Get-ChildItem -Path $Path -Filter "*.csproj" -Depth 0 -ErrorAction SilentlyContinue
$sln = Get-ChildItem -Path $Path -Filter "*.sln" -Depth 0 -ErrorAction SilentlyContinue
if ($csproj -or $sln) { $result.language = "dotnet" }

# Ruby
if (Test-Path (Join-Path $Path "Gemfile")) { $result.language = "ruby" }

# PHP
if (Test-Path (Join-Path $Path "composer.json")) { $result.language = "php" }

# Containerized
if ((Test-Path (Join-Path $Path "Dockerfile")) -or (Test-Path (Join-Path $Path "docker-compose.yml")) -or (Test-Path (Join-Path $Path "docker-compose.yaml"))) {
    $result.containerized = $true
}

$result | ConvertTo-Json -Depth 5
