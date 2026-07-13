param(
    [string]$ConfigPath = "$env:USERPROFILE\.gemini\config\mcp_config.json",
    [string]$DiscoveryPath = "$env:USERPROFILE\.fusion_mcp.json",
    [string]$ServerName = "autodesk-fusion-mcp",
    [switch]$NoBackup
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "MCP config not found: $ConfigPath"
}
if (-not (Test-Path -LiteralPath $DiscoveryPath)) {
    throw "Fusion MCP discovery file not found: $DiscoveryPath"
}

$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
$discovery = Get-Content -Raw -LiteralPath $DiscoveryPath | ConvertFrom-Json

if (-not $discovery.sse_url) {
    throw "Discovery file does not contain sse_url: $DiscoveryPath"
}
if (-not $config.mcpServers) {
    $config | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([pscustomobject]@{})
}
if (-not $config.mcpServers.$ServerName) {
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name $ServerName -Value ([pscustomobject]@{})
}

if (-not $NoBackup) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    Copy-Item -LiteralPath $ConfigPath -Destination "$ConfigPath.bak-$stamp"
}

$config.mcpServers.$ServerName | Add-Member -MemberType NoteProperty -Name "serverUrl" -Value $discovery.sse_url -Force
$config.mcpServers.$ServerName | Add-Member -MemberType NoteProperty -Name "disabled" -Value $false -Force
$config | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

Write-Host "Updated $ServerName serverUrl to $($discovery.sse_url)"
