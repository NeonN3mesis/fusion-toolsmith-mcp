param(
    [string]$AddInsRoot = "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns",
    [string]$AddInName = "FusionMCP",
    [string]$LegacyAddInName = "Fusion MCP Addin",
    [switch]$KeepLegacyAddIn
)

$ErrorActionPreference = "Stop"

$sourceRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$targetRoot = Join-Path $AddInsRoot $AddInName
$requiredFiles = @(
    "__init__.py",
    "FusionMCP.py",
    "FusionMCP.manifest",
    "best_practices.md",
    "workflow_guide.md",
    "help_context.json",
    "tool_profiles.json"
)
$requiredDirs = @(
    "server",
    "tools",
    "mcp_primitives"
)

foreach ($file in $requiredFiles) {
    $path = Join-Path $sourceRoot $file
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file missing: $path"
    }
}

foreach ($dir in $requiredDirs) {
    $path = Join-Path $sourceRoot $dir
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Required directory missing: $path"
    }
}

New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null

$legacyRoot = Join-Path $AddInsRoot $LegacyAddInName
if (-not $KeepLegacyAddIn -and (Test-Path -LiteralPath $legacyRoot -PathType Container)) {
    $resolvedAddInsRoot = (Resolve-Path -LiteralPath $AddInsRoot).Path
    $resolvedLegacyRoot = (Resolve-Path -LiteralPath $legacyRoot).Path
    if (-not $resolvedLegacyRoot.StartsWith($resolvedAddInsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to move legacy add-in outside AddIns root: $resolvedLegacyRoot"
    }

    $disabledRoot = Join-Path (Split-Path -Parent $AddInsRoot) "AddInsDisabled"
    New-Item -ItemType Directory -Force -Path $disabledRoot | Out-Null
    $legacyTargetBase = Join-Path $disabledRoot "$LegacyAddInName.disabled-legacy"
    $legacyTarget = $legacyTargetBase
    $suffix = 1
    while (Test-Path -LiteralPath $legacyTarget) {
        $suffix++
        $legacyTarget = "$legacyTargetBase-$suffix"
    }
    Move-Item -LiteralPath $legacyRoot -Destination $legacyTarget
    Write-Host "Moved legacy Fusion MCP add-in outside Fusion scan path: $legacyTarget"
}

foreach ($file in $requiredFiles) {
    Copy-Item -LiteralPath (Join-Path $sourceRoot $file) -Destination (Join-Path $targetRoot $file) -Force
}

foreach ($dir in $requiredDirs) {
    $targetDir = Join-Path $targetRoot $dir
    if (Test-Path -LiteralPath $targetDir) {
        Remove-Item -LiteralPath $targetDir -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $sourceRoot $dir) -Destination $targetDir -Recurse -Force
}

Get-ChildItem -LiteralPath $targetRoot -Directory -Recurse -Force |
    Where-Object { $_.Name -eq "__pycache__" } |
    Remove-Item -Recurse -Force

Write-Host "Installed Fusion MCP add-in to: $targetRoot"
Write-Host "FusionMCP is installed in opt-in mode. It will not start automatically with Fusion 360."
