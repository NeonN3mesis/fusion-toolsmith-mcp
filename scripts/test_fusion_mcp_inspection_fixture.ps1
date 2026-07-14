param(
    [string]$DiscoveryPath = "$env:USERPROFILE\.fusion_mcp.json",
    [int]$ExpectedPort = 9100,
    [int]$TimeoutSec = 10,
    [switch]$SkipFixtureCreation,
    [switch]$KeepFixtureDocument
)

$ErrorActionPreference = "Stop"

function New-JsonRpcPayload {
    param(
        [int]$Id,
        [string]$Method,
        [hashtable]$Params
    )

    return @{
        jsonrpc = "2.0"
        id = $Id
        method = $Method
        params = $Params
    } | ConvertTo-Json -Depth 100 -Compress
}

function Invoke-McpRequest {
    param(
        [string]$Uri,
        [string]$SessionId,
        [string]$Body,
        [int]$TimeoutSec
    )

    $headers = @{}
    if ($SessionId) {
        $headers["Mcp-Session-Id"] = $SessionId
    }

    return Invoke-WebRequest `
        -Uri $Uri `
        -Method Post `
        -Body $Body `
        -ContentType "application/json" `
        -Headers $headers `
        -TimeoutSec $TimeoutSec `
        -UseBasicParsing
}

function Convert-ToolText {
    param($ToolResponse)

    if ($ToolResponse.result.isError) {
        $text = $ToolResponse.result.content[0].text
        throw "MCP tool returned error: $text"
    }

    $rawText = $ToolResponse.result.content[0].text
    try {
        return $rawText | ConvertFrom-Json
    }
    catch {
        return $rawText
    }
}

function Invoke-McpTool {
    param(
        [string]$Uri,
        [string]$SessionId,
        [int]$Id,
        [string]$Name,
        [hashtable]$Arguments,
        [int]$TimeoutSec
    )

    if ($null -eq $Arguments) {
        $Arguments = @{}
    }

    $body = New-JsonRpcPayload -Id $Id -Method "tools/call" -Params @{
        name = $Name
        arguments = $Arguments
    }
    $response = Invoke-McpRequest -Uri $Uri -SessionId $SessionId -Body $body -TimeoutSec $TimeoutSec
    $json = $response.Content | ConvertFrom-Json
    return Convert-ToolText -ToolResponse $json
}

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

if (-not (Test-Path -LiteralPath $DiscoveryPath -PathType Leaf)) {
    throw "Discovery file not found at $DiscoveryPath. Load or restart the FusionMCP add-in first."
}

$discovery = Get-Content -LiteralPath $DiscoveryPath -Raw | ConvertFrom-Json
if (-not $discovery.sse_url) {
    throw "Discovery file does not contain sse_url."
}

$baseUri = [Uri]$discovery.sse_url
if ($baseUri.Port -ne $ExpectedPort) {
    throw "Fusion MCP is listening on port $($baseUri.Port), expected $ExpectedPort. Refusing to accept port fallback/sprawl."
}

$healthUri = "{0}://{1}:{2}/health" -f $baseUri.Scheme, $baseUri.Host, $baseUri.Port
$health = Invoke-RestMethod -Uri $healthUri -TimeoutSec $TimeoutSec
if ($health.status -ne "ok" -or $health.server -ne "fusion-mcp") {
    throw "Unexpected health response: $($health | ConvertTo-Json -Compress)"
}

$mcpUri = "{0}://{1}:{2}/sse" -f $baseUri.Scheme, $baseUri.Host, $baseUri.Port
$initBody = New-JsonRpcPayload -Id 1 -Method "initialize" -Params @{}
$initResponse = Invoke-McpRequest -Uri $mcpUri -SessionId "" -Body $initBody -TimeoutSec $TimeoutSec
$sessionId = $initResponse.Headers["Mcp-Session-Id"]
if (-not $sessionId) {
    throw "Streamable HTTP initialize did not return Mcp-Session-Id."
}

try {
    $toolsBody = New-JsonRpcPayload -Id 2 -Method "tools/list" -Params @{}
    $toolsResponse = Invoke-McpRequest -Uri $mcpUri -SessionId $sessionId -Body $toolsBody -TimeoutSec $TimeoutSec
    $toolsJson = $toolsResponse.Content | ConvertFrom-Json
    $toolNames = @($toolsJson.result.tools | ForEach-Object { $_.name })
    foreach ($requiredTool in @(
        "run_fusion_script",
        "inspect_sketch",
        "inspect_feature",
        "get_sketch_parameters",
        "get_feature_parameters",
        "get_parameter_usage",
        "get_projected_geometry_sources",
        "get_feature_dependencies",
        "get_dependency_graph",
        "assess_change_impact",
        "get_runtime_diagnostics",
        "map_coordinates"
    )) {
        Assert-True -Condition ($toolNames -contains $requiredTool) -Message "Required tool '$requiredTool' was not advertised."
    }

    if (-not $SkipFixtureCreation) {
        $fixtureScript = @'
import adsk.core, adsk.fusion

def _user_param(design, name, expression, unit, comment):
    existing = design.userParameters.itemByName(name)
    if existing:
        existing.expression = expression
        existing.comment = comment
        return existing
    return design.userParameters.add(
        name,
        adsk.core.ValueInput.createByString(expression),
        unit,
        comment
    )

def _collection_count(collection):
    return collection.count if collection else 0

def run(context):
    app = adsk.core.Application.get()
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent

    _user_param(design, "fixtureWidth", "40 mm", "mm", "MCP inspection fixture width")
    _user_param(design, "fixtureDepth", "20 mm", "mm", "MCP inspection fixture depth")
    _user_param(design, "fixtureHeight", "8 mm", "mm", "MCP inspection fixture height")
    _user_param(design, "fixtureCutDepth", "10 mm", "mm", "MCP inspection fixture cut depth")

    base_sketch = root.sketches.add(root.xYConstructionPlane)
    base_sketch.name = "Fixture_BaseSketch"
    lines = base_sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(-2.0, -1.0, 0),
        adsk.core.Point3D.create(2.0, 1.0, 0)
    )

    horizontal = None
    vertical = None
    for i in range(lines.count):
        line = lines.item(i)
        start = line.startSketchPoint.geometry
        end = line.endSketchPoint.geometry
        if abs(start.y - end.y) < 1e-6:
            horizontal = line
        if abs(start.x - end.x) < 1e-6:
            vertical = line

    if horizontal:
        width_dim = base_sketch.sketchDimensions.addDistanceDimension(
            horizontal.startSketchPoint,
            horizontal.endSketchPoint,
            adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation,
            adsk.core.Point3D.create(0, -1.5, 0)
        )
        width_dim.parameter.expression = "fixtureWidth"

    if vertical:
        depth_dim = base_sketch.sketchDimensions.addDistanceDimension(
            vertical.startSketchPoint,
            vertical.endSketchPoint,
            adsk.fusion.DimensionOrientations.VerticalDimensionOrientation,
            adsk.core.Point3D.create(2.5, 0, 0)
        )
        depth_dim.parameter.expression = "fixtureDepth"

    extrudes = root.features.extrudeFeatures
    base_input = extrudes.createInput(base_sketch.profiles.item(0), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    base_input.setDistanceExtent(False, adsk.core.ValueInput.createByString("fixtureHeight"))
    base_extrude = extrudes.add(base_input)
    base_extrude.name = "Fixture_BaseExtrude"
    body = base_extrude.bodies.item(0)
    body.name = "Fixture_BaseBody"

    project_sketch = root.sketches.add(root.xYConstructionPlane)
    project_sketch.name = "Fixture_ProjectSketch"
    projected = project_sketch.project(body.edges.item(0))
    project_count = _collection_count(projected)

    cut_sketch = root.sketches.add(root.xYConstructionPlane)
    cut_sketch.name = "Fixture_CutSketch"
    cut_sketch.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), 0.35)
    cut_input = extrudes.createInput(cut_sketch.profiles.item(0), adsk.fusion.FeatureOperations.CutFeatureOperation)
    cut_input.setDistanceExtent(False, adsk.core.ValueInput.createByString("fixtureCutDepth"))
    cut_extrude = extrudes.add(cut_input)
    cut_extrude.name = "Fixture_CutExtrude"

    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(5.0, 0, 0)
    occ = root.occurrences.addNewComponent(transform)
    occ.component.name = "Fixture_TargetComponent"

    design.computeAll()
    print("fixture_created")
    print("projected_count=%s" % project_count)
    print("base_extrude=%s" % base_extrude.name)
    print("cut_extrude=%s" % cut_extrude.name)
'@

        $fixtureResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 3 -Name "run_fusion_script" -Arguments @{
            script = $fixtureScript
        } -TimeoutSec ([Math]::Max($TimeoutSec, 30))
        Write-Host "Fixture creation output:"
        Write-Host $fixtureResult.output
    }

    $baseSketch = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 4 -Name "inspect_sketch" -Arguments @{
        sketch_name = "Fixture_BaseSketch"
    } -TimeoutSec $TimeoutSec
    Assert-True -Condition ($baseSketch.result.name -eq "Fixture_BaseSketch") -Message "inspect_sketch did not return Fixture_BaseSketch."
    Assert-True -Condition (@($baseSketch.result.parameters).Count -ge 1) -Message "Fixture_BaseSketch did not expose dimension parameters."
    Assert-True -Condition (@($baseSketch.result.curves.lines).Count -ge 4) -Message "Fixture_BaseSketch did not expose rectangle lines."

    $baseExtrude = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 5 -Name "inspect_feature" -Arguments @{
        feature_name = "Fixture_BaseExtrude"
    } -TimeoutSec $TimeoutSec
    Assert-True -Condition ($baseExtrude.result.featureType -eq "ExtrudeFeature") -Message "inspect_feature did not identify Fixture_BaseExtrude as an ExtrudeFeature."
    Assert-True -Condition (@($baseExtrude.result.parameters).Count -ge 1) -Message "Fixture_BaseExtrude did not expose feature parameters."
    Assert-True -Condition (@($baseExtrude.result.resultBodies) -contains "Fixture_BaseBody") -Message "Fixture_BaseExtrude did not expose Fixture_BaseBody."

    $projectSketch = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 6 -Name "inspect_sketch" -Arguments @{
        sketch_name = "Fixture_ProjectSketch"
    } -TimeoutSec $TimeoutSec
    $projectCurves = @()
    foreach ($group in @("lines", "circles", "arcs", "ellipses", "fittedSplines", "fixedSplines", "conics")) {
        $projectCurves += @($projectSketch.result.curves.$group)
    }
    Assert-True -Condition ($projectCurves.Count -ge 1) -Message "Fixture_ProjectSketch did not expose projected curves."
    $referenceCurves = @($projectCurves | Where-Object { $_.isReference -eq $true })
    if ($referenceCurves.Count -lt 1) {
        Write-Warning "Projected curves were found, but Fusion did not report isReference=true for this fixture."
    }
    $sourceCurves = @($projectCurves | Where-Object { $null -ne $_.source })
    if ($sourceCurves.Count -lt 1) {
        Write-Warning "Projected curves did not expose source entity metadata through the current Fusion API object shape."
    }

    $mapped = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 7 -Name "map_coordinates" -Arguments @{
        point = @(1, 2, 0)
        from_sketch = "Fixture_BaseSketch"
        to_component = "Fixture_TargetComponent"
    } -TimeoutSec $TimeoutSec
    Assert-True -Condition ($null -ne $mapped.result.sketchToModel) -Message "map_coordinates did not return sketchToModel."
    Assert-True -Condition ($null -ne $mapped.result.sketchToTargetComponent) -Message "map_coordinates did not return sketchToTargetComponent."
    Assert-True -Condition ($mapped.result.componentName -eq "Fixture_TargetComponent") -Message "map_coordinates did not resolve Fixture_TargetComponent."

    $dependencies = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 8 -Name "get_feature_dependencies" -Arguments @{
        feature_name = "Fixture_BaseExtrude"
    } -TimeoutSec $TimeoutSec
    Assert-True -Condition ($dependencies.result.bestEffort -eq $true) -Message "get_feature_dependencies did not identify bestEffort output."
    Assert-True -Condition (@($dependencies.result.directInputs).Count -ge 1) -Message "get_feature_dependencies did not report direct inputs."

    if (-not $KeepFixtureDocument -and -not $SkipFixtureCreation) {
        $cleanupScript = @'
def run(context):
    import adsk.core
    app = adsk.core.Application.get()
    doc = app.activeDocument
    if doc:
        print("closing " + doc.name)
        doc.close(False)
'@
        $cleanupResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 9 -Name "run_fusion_script" -Arguments @{
            script = $cleanupScript
        } -TimeoutSec $TimeoutSec
        Write-Host "Fixture cleanup output:"
        Write-Host $cleanupResult.output
    }

    Write-Host "Fusion MCP inspection fixture verification passed."
    Write-Host "Health: $healthUri"
    Write-Host "Session: $sessionId"
}
finally {
    if ($sessionId) {
        try {
            Invoke-WebRequest `
                -Uri $mcpUri `
                -Method Delete `
                -Headers @{ "Mcp-Session-Id" = $sessionId } `
                -TimeoutSec $TimeoutSec `
                -UseBasicParsing | Out-Null
        }
        catch {
            Write-Warning "Failed to close MCP session '$sessionId': $($_.Exception.Message)"
        }
    }
}
