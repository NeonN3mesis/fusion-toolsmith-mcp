param(
    [string]$DiscoveryPath = "$env:USERPROFILE\.fusion_mcp.json",
    [int]$ExpectedPort = 9100,
    [int]$TimeoutSec = 20,
    [string]$ExportPath = "",
    [switch]$KeepFixtureDocument
)

$ErrorActionPreference = "Stop"

function New-JsonRpcPayload {
    param([int]$Id, [string]$Method, [hashtable]$Params)
    return @{ jsonrpc = "2.0"; id = $Id; method = $Method; params = $Params } | ConvertTo-Json -Depth 100 -Compress
}

function Invoke-McpRequest {
    param(
        [string]$Uri,
        [string]$SessionId,
        [string]$Body,
        [int]$TimeoutSec,
        [hashtable]$ExtraHeaders
    )
    $headers = @{}
    if ($ExtraHeaders) {
        foreach ($key in $ExtraHeaders.Keys) { $headers[$key] = $ExtraHeaders[$key] }
    }
    if ($SessionId) { $headers["Mcp-Session-Id"] = $SessionId }
    return Invoke-WebRequest -Uri $Uri -Method Post -Body $Body -ContentType "application/json" -Headers $headers -TimeoutSec $TimeoutSec -UseBasicParsing
}

function Convert-ToolText {
    param($ToolResponse)
    $rawText = $ToolResponse.result.content[0].text
    if ($ToolResponse.result.isError) {
        throw "MCP tool returned error: $rawText"
    }
    try { return $rawText | ConvertFrom-Json } catch { return $rawText }
}

function Invoke-McpTool {
    param(
        [string]$Uri,
        [string]$SessionId,
        [int]$Id,
        [string]$Name,
        [hashtable]$Arguments,
        [int]$TimeoutSec,
        [hashtable]$ExtraHeaders
    )
    if ($null -eq $Arguments) { $Arguments = @{} }
    $body = New-JsonRpcPayload -Id $Id -Method "tools/call" -Params @{ name = $Name; arguments = $Arguments }
    $response = Invoke-McpRequest -Uri $Uri -SessionId $SessionId -Body $body -TimeoutSec $TimeoutSec -ExtraHeaders $ExtraHeaders
    return Convert-ToolText -ToolResponse ($response.Content | ConvertFrom-Json)
}

if (-not (Test-Path -LiteralPath $DiscoveryPath -PathType Leaf)) {
    throw "Discovery file not found at $DiscoveryPath. Load or restart the FusionMCP add-in first."
}

$discovery = Get-Content -LiteralPath $DiscoveryPath -Raw | ConvertFrom-Json
$mcpUrl = $discovery.streamable_http_url
if (-not $mcpUrl) { $mcpUrl = "http://127.0.0.1:$($discovery.port)/" }
$mcpUri = [Uri]$mcpUrl
if ($mcpUri.Port -ne $ExpectedPort) {
    throw "Fusion MCP is listening on port $($mcpUri.Port), expected $ExpectedPort."
}

$authHeaders = @{}
if ($discovery.authorization_header) {
    $authHeaders["Authorization"] = [string]$discovery.authorization_header
}

$initialize = New-JsonRpcPayload -Id 1 -Method "initialize" -Params @{
    protocolVersion = "2024-11-05"
    capabilities = @{}
    clientInfo = @{ name = "fusion-mcp-3mf-fixture"; version = "1.0.0" }
}
$initResponse = Invoke-McpRequest -Uri $mcpUrl -SessionId "" -Body $initialize -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
$sessionId = [string]($initResponse.Headers["Mcp-Session-Id"] | Select-Object -First 1)
if (-not $sessionId) { throw "No Mcp-Session-Id returned by initialize." }

$toolsBody = New-JsonRpcPayload -Id 2 -Method "tools/list" -Params @{}
$toolsResponse = Invoke-McpRequest -Uri $mcpUrl -SessionId $sessionId -Body $toolsBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
$tools = @((($toolsResponse.Content | ConvertFrom-Json).result.tools | ForEach-Object { $_.name }))
$requiredTools = @("create_design_document", "create_box", "list_appearances", "inspect_body_style", "inspect_selection_sets", "inspect_3mf_archive", "plan_multicolor_3mf_export", "apply_appearance", "export_asset", "close_active_document")
$missing = @($requiredTools | Where-Object { $_ -notin $tools })
if ($missing.Count -gt 0) {
    throw "Live FusionMCP runtime is missing required 3MF fixture tools: $($missing -join ', '). Restart the add-in so Python modules reload."
}

if (-not $ExportPath) {
    $ExportPath = Join-Path $env:TEMP ("fusion_mcp_3mf_fixture_{0}.3mf" -f ([Guid]::NewGuid().ToString("N")))
}
if (Test-Path -LiteralPath $ExportPath) {
    Remove-Item -LiteralPath $ExportPath -Force
}

function Find-AppearanceName {
    param([string[]]$Queries, [int]$StartId)
    $id = $StartId
    foreach ($query in $Queries) {
        $appearanceResult = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id $id -Name "list_appearances" -Arguments @{
            query = $query
            include_libraries = $true
            limit = 10
        } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
        $id += 1
        $matches = @($appearanceResult.result.appearances)
        if ($matches.Count -gt 0 -and $matches[0].name) {
            return [string]$matches[0].name
        }
    }
    throw "Could not find an appearance matching any of: $($Queries -join ', ')"
}

$fixtureDocument = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id 3 -Name "create_design_document" -Arguments @{
    document_name = "FusionMCP_3MF_Fixture"
    requires_user_approval = $true
    reason = "Create a controlled throwaway two-body multicolor 3MF export fixture."
} -TimeoutSec ([Math]::Max($TimeoutSec, 45)) -ExtraHeaders $authHeaders

$null = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id 4 -Name "create_box" -Arguments @{
    name = "Fixture_ColorBody_A"
    base_plane = "xy"
    length = "20 mm"
    width = "20 mm"
    height = "4 mm"
    x_offset = "0 mm"
    z_offset = "0 mm"
    operation = "new_body"
} -TimeoutSec ([Math]::Max($TimeoutSec, 45)) -ExtraHeaders $authHeaders

$null = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id 5 -Name "create_box" -Arguments @{
    name = "Fixture_ColorBody_B"
    base_plane = "xy"
    length = "20 mm"
    width = "20 mm"
    height = "4 mm"
    x_offset = "26 mm"
    z_offset = "0 mm"
    operation = "new_body"
} -TimeoutSec ([Math]::Max($TimeoutSec, 45)) -ExtraHeaders $authHeaders

$style = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id 6 -Name "inspect_body_style" -Arguments @{
    include_all_bodies = $true
} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
$bodyA = @($style.result.bodies | Where-Object { $_.name -eq "Fixture_ColorBody_A" }) | Select-Object -First 1
$bodyB = @($style.result.bodies | Where-Object { $_.name -eq "Fixture_ColorBody_B" }) | Select-Object -First 1
if (-not $bodyA -or -not $bodyB) {
    throw "Structured fixture setup did not create both expected bodies. Body style report: $($style.result | ConvertTo-Json -Compress)"
}

$redAppearance = Find-AppearanceName -Queries @("red", "black") -StartId 7
$blueAppearance = Find-AppearanceName -Queries @("blue", "white") -StartId 9
$fixtureJson = [pscustomobject]@{
    documentName = [string]$fixtureDocument.result.documentName
    bodies = @(
        [pscustomobject]@{ name = [string]$bodyA.name; entityToken = [string]$bodyA.entityToken; appearanceName = $redAppearance },
        [pscustomobject]@{ name = [string]$bodyB.name; entityToken = [string]$bodyB.entityToken; appearanceName = $blueAppearance }
    )
}
$assignments = @(
    @{ appearance_name = [string]$fixtureJson.bodies[0].appearanceName },
    @{ appearance_name = [string]$fixtureJson.bodies[1].appearanceName }
)
if ($fixtureJson.bodies[0].entityToken) { $assignments[0].body_entity_token = [string]$fixtureJson.bodies[0].entityToken } else { $assignments[0].body_name = [string]$fixtureJson.bodies[0].name }
if ($fixtureJson.bodies[1].entityToken) { $assignments[1].body_entity_token = [string]$fixtureJson.bodies[1].entityToken } else { $assignments[1].body_name = [string]$fixtureJson.bodies[1].name }

$plan = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id 11 -Name "plan_multicolor_3mf_export" -Arguments @{
    export_path = $ExportPath
    color_assignments = $assignments
    expected_body_count = 2
    allow_overwrite = $false
} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
if (-not $plan.result.okToExport) {
    throw "plan_multicolor_3mf_export blocked fixture export: $($plan.result.blockingReasons -join '; ')"
}

$id = 12
foreach ($assignment in $plan.result.colorAssignments) {
    $args = @{}
    foreach ($prop in $assignment.applyAppearanceArguments.PSObject.Properties) {
        if ($null -ne $prop.Value) { $args[$prop.Name] = $prop.Value }
    }
    $null = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id $id -Name "apply_appearance" -Arguments $args -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $id += 1
}

$exportArgs = @{
    format = "3mf"
    export_path = $ExportPath
    expected_body_count = 2
    allow_overwrite = $false
}
$bodyTokens = @($fixtureJson.bodies | ForEach-Object { [string]$_.entityToken } | Where-Object { $_ })
if ($bodyTokens.Count -eq 2) {
    $exportArgs.body_entity_tokens = $bodyTokens
} else {
    $exportArgs.body_names = @([string]$fixtureJson.bodies[0].name, [string]$fixtureJson.bodies[1].name)
}

$export = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id $id -Name "export_asset" -Arguments $exportArgs -TimeoutSec ([Math]::Max($TimeoutSec, 45)) -ExtraHeaders $authHeaders
$id += 1

if (-not $export.result.exported) { throw "export_asset did not report exported=true." }
if (-not $export.result.archiveValidation.valid) {
    throw "3MF archive validation failed: $($export.result.archiveValidation | ConvertTo-Json -Compress)"
}
if ($export.result.archiveValidation.objectCount -lt 2) {
    throw "3MF archive exposed fewer than two objects: $($export.result.archiveValidation.objectCount)"
}
if (-not $export.result.archiveValidation.slicerColorabilityLikely) {
    throw "3MF archive did not expose enough separate object candidates for slicer color assignment: $($export.result.archiveValidation | ConvertTo-Json -Compress)"
}
if (-not $export.result.archiveValidation.printReadiness.readyForMulticolorAssignment) {
    throw "3MF archive print-readiness verdict did not approve multicolor assignment: $($export.result.archiveValidation.printReadiness | ConvertTo-Json -Compress)"
}

$standaloneInspection = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id $id -Name "inspect_3mf_archive" -Arguments @{
    export_path = $ExportPath
    expected_body_count = 2
} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
$id += 1
if (-not $standaloneInspection.result.valid -or -not $standaloneInspection.result.printReadiness.readyForMulticolorAssignment) {
    throw "Standalone inspect_3mf_archive did not confirm the exported fixture: $($standaloneInspection.result | ConvertTo-Json -Compress)"
}

if (-not $KeepFixtureDocument) {
    $null = Invoke-McpTool -Uri $mcpUrl -SessionId $sessionId -Id $id -Name "close_active_document" -Arguments @{
        document_name = "FusionMCP_3MF_Fixture"
        save_changes = $false
        requires_user_approval = $true
        reason = "Close the controlled throwaway FusionMCP 3MF fixture document without saving."
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
}

[pscustomobject]@{
    status = "passed"
    exportPath = $ExportPath
    documentName = $fixtureJson.documentName
    bodyCount = 2
    archiveValidation = $export.result.archiveValidation
    standaloneArchiveInspection = $standaloneInspection.result
} | ConvertTo-Json -Depth 20
