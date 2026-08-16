<#
.SYNOPSIS
    Reads graphify output (graph.json, GRAPH_REPORT.md) and extracts actionable data for SACAS enrichment.
.OUTPUTS
    JSON: enriched module map with communities, god nodes, cross-module edges
#>
param(
    [string]$Path = ".",
    [string]$SubDir = "Structure"
)

$Path = Resolve-Path $Path
$graphPath = Join-Path $Path "graphify-out\graph.json"
$reportPath = Join-Path $Path "graphify-out\GRAPH_REPORT.md"
$labelsPath = Join-Path $Path "graphify-out\.graphify_labels.json"

if (-not (Test-Path $graphPath)) {
    Write-Error "No graphify data found at $graphPath. Run /graphify first."
    exit 1
}

Write-Host "SACAS: Reading graphify data..." -ForegroundColor Cyan

$graph = Get-Content $graphPath -Raw | ConvertFrom-Json

# Load labels if available (not required)
$labels = @{}
if (Test-Path $labelsPath) {
    try {
        $labelsRaw = Get-Content $labelsPath -Raw | ConvertFrom-Json
        $labelsRaw.PSObject.Properties | ForEach-Object { $labels[$_.Name] = $_.Value }
    } catch {}
}

# Extract communities → module map
$communityMap = @{}
foreach ($node in $graph.nodes) {
    $cid = "$($node.community)"
    if (-not $communityMap.ContainsKey($cid)) {
        $communityMap[$cid] = @{
            id    = $cid
            label = if ($labels.ContainsKey($cid)) { $labels[$cid] } else { "community-$cid" }
            nodes = @()
            files = @()
        }
    }
    $fileVal = $node.source_file
    if (-not $fileVal) { $fileVal = $node.source_location }
    
    $communityMap[$cid].nodes += @{
        id    = $node.id
        type  = $node.type
        file  = $fileVal
        line  = $node.source_location
    }
    # Skip adding if the value is just a line number reference (e.g. L12)
    if ($fileVal -and $fileVal -notmatch "^L\d+$" -and $communityMap[$cid].files -notcontains $fileVal) {
        $communityMap[$cid].files += $fileVal
    }
}

# Fallback: Graphify uses links in its JSON output format, but older versions might use edges
$edges = $graph.links
if (-not $edges) { $edges = $graph.edges }

# Find god nodes (high degree)
$degreeMap = @{}
foreach ($edge in $edges) {
    $src = $edge.source
    $tgt = $edge.target
    if (-not $degreeMap.ContainsKey($src)) { $degreeMap[$src] = 0 }
    if (-not $degreeMap.ContainsKey($tgt)) { $degreeMap[$tgt] = 0 }
    $degreeMap[$src]++
    $degreeMap[$tgt]++
}
$sortedNodes = $degreeMap.GetEnumerator() | ForEach-Object { [PSCustomObject]@{ id = $_.Key; degree = $_.Value } } | Sort-Object -Property degree -Descending | Select-Object -First 10
$godNodes = @($sortedNodes | ForEach-Object { @{ id = $_.id; degree = $_.degree } })

# Cross-community edges
$crossEdges = @()
$nodeCommunity = @{}
foreach ($node in $graph.nodes) {
    $nodeCommunity[$node.id] = "$($node.community)"
}
foreach ($edge in $edges) {
    $srcCom = $nodeCommunity[$edge.source]
    $tgtCom = $nodeCommunity[$edge.target]
    if ($srcCom -and $tgtCom -and $srcCom -ne $tgtCom) {
        $crossEdges += @{
            source          = $edge.source
            target          = $edge.target
            sourceCommunity = $srcCom
            targetCommunity = $tgtCom
            relation        = $edge.relation
        }
    }
}

$enrichment = @{
    communities  = $communityMap.Values
    godNodes     = $godNodes
    crossEdges   = $crossEdges
    totalNodes   = $graph.nodes.Count
    totalEdges   = if ($edges) { $edges.Count } else { 0 }
    communityCount = $communityMap.Count
}

# Save enrichment
$enrichPath = if ($SubDir) { Join-Path $Path "$SubDir\.sacas\graphify-enrichment.json" } else { Join-Path $Path ".sacas\graphify-enrichment.json" }
$enrichment | ConvertTo-Json -Depth 10 | Set-Content -Path $enrichPath -Encoding utf8

Write-Host "  Communities: $($communityMap.Count)" -ForegroundColor White
Write-Host "  God nodes:   $($godNodes.Count)" -ForegroundColor White
Write-Host "  Cross edges: $($crossEdges.Count)" -ForegroundColor White
Write-Host "  Saved to:    $enrichPath" -ForegroundColor DarkGray

$enrichment | ConvertTo-Json -Depth 10
