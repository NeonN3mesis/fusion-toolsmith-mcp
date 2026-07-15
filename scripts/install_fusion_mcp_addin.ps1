param(
    [string]$AddInsRoot = "$env:APPDATA\Autodesk\Autodesk Fusion 360\API\AddIns",
    [string]$AddInName = "FusionMCP",
    [string]$LegacyAddInName = "Fusion MCP Addin"
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

$legacyManifest = Join-Path (Join-Path $AddInsRoot $LegacyAddInName) "$LegacyAddInName.manifest"
if (Test-Path -LiteralPath $legacyManifest -PathType Leaf) {
    $legacyBackup = "$legacyManifest.bak"
    if (-not (Test-Path -LiteralPath $legacyBackup -PathType Leaf)) {
        Copy-Item -LiteralPath $legacyManifest -Destination $legacyBackup -Force
    }

    $legacyText = Get-Content -LiteralPath $legacyManifest -Raw
    if ($legacyText -match '"runOnStartup"\s*:\s*true') {
        $legacyText = [regex]::Replace($legacyText, '"runOnStartup"\s*:\s*true', '"runOnStartup": false', 1)
        Set-Content -LiteralPath $legacyManifest -Value $legacyText -Encoding UTF8
        Write-Host "Disabled runOnStartup for legacy add-in: $LegacyAddInName"
    }
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
