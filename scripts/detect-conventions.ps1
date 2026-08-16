<#
.SYNOPSIS
    Extracts coding conventions from linter/formatter config files.
.OUTPUTS
    JSON: { linter, formatter, editorConfig, typescriptStrict, rules }
#>
param(
    [string]$Path = "."
)

$Path = Resolve-Path $Path
$result = @{
    linter           = $null
    formatter        = $null
    editorConfig     = @{}
    typescriptStrict = $false
    rules            = @{}
}

# ESLint
$eslintFiles = @(".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml", "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs", "eslint.config.ts")
foreach ($f in $eslintFiles) {
    if (Test-Path (Join-Path $Path $f)) {
        $result.linter = "eslint"
        $result.rules["eslintConfig"] = $f
        break
    }
}

# Prettier
$prettierFiles = @(".prettierrc", ".prettierrc.js", ".prettierrc.cjs", ".prettierrc.json", ".prettierrc.yml", "prettier.config.js", "prettier.config.cjs")
foreach ($f in $prettierFiles) {
    if (Test-Path (Join-Path $Path $f)) {
        $result.formatter = "prettier"
        $result.rules["prettierConfig"] = $f
        break
    }
}

# Biome
if ((Test-Path (Join-Path $Path "biome.json")) -or (Test-Path (Join-Path $Path "biome.jsonc"))) {
    $result.linter = "biome"
    $result.formatter = "biome"
}

# Rust
if (Test-Path (Join-Path $Path "rustfmt.toml")) { $result.formatter = "rustfmt" }
if (Test-Path (Join-Path $Path "clippy.toml")) { $result.linter = "clippy" }

# Python
if (Test-Path (Join-Path $Path "ruff.toml")) { $result.linter = "ruff"; $result.formatter = "ruff" }
if (Test-Path (Join-Path $Path ".pylintrc")) { $result.linter = "pylint" }
$pyProj = Join-Path $Path "pyproject.toml"
if (Test-Path $pyProj) {
    $content = Get-Content $pyProj -Raw
    if ($content -match "\[tool\.ruff\]") { $result.linter = "ruff" }
    if ($content -match "\[tool\.black\]") { $result.formatter = "black" }
    if ($content -match "\[tool\.isort\]") { $result.rules["isort"] = $true }
}

# EditorConfig
$editorConfig = Join-Path $Path ".editorconfig"
if (Test-Path $editorConfig) {
    $result.editorConfig["present"] = $true
}

# TypeScript strictness
$tsConfig = Join-Path $Path "tsconfig.json"
if (Test-Path $tsConfig) {
    try {
        $ts = Get-Content $tsConfig -Raw | ConvertFrom-Json
        if ($ts.compilerOptions.strict -eq $true) { $result.typescriptStrict = $true }
    } catch {}
}

$result | ConvertTo-Json -Depth 5
