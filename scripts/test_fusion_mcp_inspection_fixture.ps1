param(
    [string]$DiscoveryPath = "$env:USERPROFILE\.fusion_mcp.json",
    [int]$ExpectedPort = 9100,
    [int]$TimeoutSec = 10,
    [string]$ReportPath = "",
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
        [int]$TimeoutSec,
        [hashtable]$ExtraHeaders
    )

    $headers = @{}
    if ($ExtraHeaders) {
        foreach ($key in $ExtraHeaders.Keys) {
            $headers[$key] = $ExtraHeaders[$key]
        }
    }
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
        [int]$TimeoutSec,
        [hashtable]$ExtraHeaders
    )

    if ($null -eq $Arguments) {
        $Arguments = @{}
    }

    $body = New-JsonRpcPayload -Id $Id -Method "tools/call" -Params @{
        name = $Name
        arguments = $Arguments
    }
    $response = Invoke-McpRequest -Uri $Uri -SessionId $SessionId -Body $body -TimeoutSec $TimeoutSec -ExtraHeaders $ExtraHeaders
    $json = $response.Content | ConvertFrom-Json
    return Convert-ToolText -ToolResponse $json
}

function Invoke-McpToolAllowError {
    param(
        [string]$Uri,
        [string]$SessionId,
        [int]$Id,
        [string]$Name,
        [hashtable]$Arguments,
        [int]$TimeoutSec,
        [hashtable]$ExtraHeaders
    )

    if ($null -eq $Arguments) {
        $Arguments = @{}
    }

    $body = New-JsonRpcPayload -Id $Id -Method "tools/call" -Params @{
        name = $Name
        arguments = $Arguments
    }
    $response = Invoke-McpRequest -Uri $Uri -SessionId $SessionId -Body $body -TimeoutSec $TimeoutSec -ExtraHeaders $ExtraHeaders
    $json = $response.Content | ConvertFrom-Json
    $rawText = $json.result.content[0].text
    if ($json.result.isError) {
        return @{
            isError = $true
            errorText = $rawText
        }
    }
    try {
        return @{
            isError = $false
            value = ($rawText | ConvertFrom-Json)
        }
    }
    catch {
        return @{
            isError = $false
            value = $rawText
        }
    }
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

$script:fixtureProbeResults = @()
$script:fixtureStartedAt = (Get-Date).ToUniversalTime().ToString("o")
$script:fixturePassed = $false
$script:fixtureFailure = $null

function Add-FixtureProbe {
    param(
        [string]$Name,
        [string]$Status,
        [hashtable]$Detail = @{}
    )

    $script:fixtureProbeResults += [ordered]@{
        name = $Name
        status = $Status
        detail = $Detail
    }
}

function Write-FixtureReport {
    param(
        [string]$Status
    )

    if ([string]::IsNullOrWhiteSpace($ReportPath)) {
        return
    }

    $report = [ordered]@{
        status = $Status
        startedAt = $script:fixtureStartedAt
        completedAt = (Get-Date).ToUniversalTime().ToString("o")
        healthUri = $healthUri
        mcpPath = if ($mcpUri) { ([Uri]$mcpUri).AbsolutePath } else { $null }
        expectedPort = $ExpectedPort
        skipFixtureCreation = [bool]$SkipFixtureCreation
        keepFixtureDocument = [bool]$KeepFixtureDocument
        fixtureDocumentOpen = [bool]$script:fixtureCreated
        failure = $script:fixtureFailure
        probes = $script:fixtureProbeResults
    }

    $target = [System.IO.Path]::GetFullPath($ReportPath)
    $parent = [System.IO.Path]::GetDirectoryName($target)
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $report | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $target -Encoding UTF8
}

function Invoke-MotionJointProbe {
    param(
        [string]$Uri,
        [string]$SessionId,
        [int]$Id,
        [string]$ToolName,
        [hashtable]$Arguments,
        [string]$ExpectedKind,
        [int]$TimeoutSec,
        [hashtable]$ExtraHeaders
    )

    $probe = Invoke-McpToolAllowError `
        -Uri $Uri `
        -SessionId $SessionId `
        -Id $Id `
        -Name $ToolName `
        -Arguments $Arguments `
        -TimeoutSec ([Math]::Max($TimeoutSec, 20)) `
        -ExtraHeaders $ExtraHeaders
    if ($probe.isError) {
        Assert-True -Condition (
            ($probe.errorText -like "*rootComponent.joints*") -or
            ($probe.errorText -like "*JointGeometry.createByPoint*") -or
            ($probe.errorText -like "*JointInput.*JointMotion*") -or
            ($probe.errorText -like "*Failed to create*joint*") -or
            ($probe.errorText -like "*point references*") -or
            ($probe.errorText -like "*motion direction*")
        ) -Message "$ToolName failed unexpectedly: $($probe.errorText)"
        Write-Warning "$ToolName returned expected runtime joint-API limitation: $($probe.errorText)"
        Add-FixtureProbe -Name $ToolName -Status "unsupported" -Detail @{ error = $probe.errorText }
        return $null
    }

    Assert-True -Condition ($probe.value.result.jointKind -eq $ExpectedKind) -Message "$ToolName did not report expected jointKind '$ExpectedKind'."
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$probe.value.result.jointName)) -Message "$ToolName did not return a created joint name."
    Assert-True -Condition ($null -ne $probe.value.result.stateComparison) -Message "$ToolName did not return stateComparison."
    Add-FixtureProbe -Name $ToolName -Status "passed" -Detail @{ jointName = $probe.value.result.jointName; jointKind = $probe.value.result.jointKind }
    return $probe.value.result.jointName
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
if ($health.PSObject.Properties.Name -contains "task_manager_running" -and -not $health.task_manager_running) {
    throw "Fusion MCP server is responding, but TaskManager is not running. Stop/start the FusionMCP add-in from Utilities > Add-Ins."
}
Add-FixtureProbe -Name "health" -Status "passed" -Detail @{
    server = $health.server
    transport = $health.transport
    taskManagerRunning = $health.task_manager_running
    pendingTasks = $health.pending_tasks
}

$authHeaders = @{}
if ($discovery.authorization_header) {
    $authHeaders["Authorization"] = $discovery.authorization_header
}
$mcpUri = "{0}://{1}:{2}/mcp" -f $baseUri.Scheme, $baseUri.Host, $baseUri.Port
$legacyStreamableUri = $null
if ($discovery.bearer_sse_url) {
    $legacyStreamableCandidateUri = [Uri]$discovery.bearer_sse_url
    if ($legacyStreamableCandidateUri.Port -ne $ExpectedPort) {
        throw "Fusion MCP bearer SSE endpoint is on port $($legacyStreamableCandidateUri.Port), expected $ExpectedPort. Refusing to accept port fallback/sprawl."
    }
    $legacyStreamableUri = $legacyStreamableCandidateUri.AbsoluteUri
}
if ($discovery.streamable_http_url) {
    $candidateUri = [Uri]$discovery.streamable_http_url
    if ($candidateUri.Port -ne $ExpectedPort) {
        throw "Fusion MCP Streamable HTTP endpoint is on port $($candidateUri.Port), expected $ExpectedPort. Refusing to accept port fallback/sprawl."
    }
    if ($candidateUri.AbsolutePath -eq "/mcp") {
        $mcpUri = $candidateUri.AbsoluteUri
    }
}
$initBody = New-JsonRpcPayload -Id 1 -Method "initialize" -Params @{}
$initResponse = $null
try {
    $initResponse = Invoke-McpRequest -Uri $mcpUri -SessionId "" -Body $initBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
}
catch {
    $statusCode = $null
    if ($_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    if ($statusCode -eq 404 -and $legacyStreamableUri -and $legacyStreamableUri -ne $mcpUri) {
        $mcpUri = $legacyStreamableUri
        $initResponse = Invoke-McpRequest -Uri $mcpUri -SessionId "" -Body $initBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    }
    else {
        throw
    }
}
$sessionId = @($initResponse.Headers["Mcp-Session-Id"])[0]
if (-not $sessionId) {
    throw "Streamable HTTP initialize did not return Mcp-Session-Id."
}
Add-FixtureProbe -Name "initialize" -Status "passed" -Detail @{
    mcpPath = ([Uri]$mcpUri).AbsolutePath
    sessionCreated = $true
}

$script:fixtureCreated = $false

function Invoke-FixtureDocumentCleanup {
    param(
        [string]$Label = "Fixture cleanup"
    )

    if ($KeepFixtureDocument -or $SkipFixtureCreation -or -not $script:fixtureCreated -or -not $sessionId) {
        return
    }

    $cleanupScript = @'
def run(context):
    import adsk.core
    app = adsk.core.Application.get()
    doc = app.activeDocument
    if doc:
        print("closing " + doc.name)
        doc.close(False)
'@
    try {
        $cleanupResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 50 -Name "run_fusion_script" -Arguments @{
            script = $cleanupScript
            script_intent = "Close the temporary inspection fixture document after smoke testing."
            mcp_tool_gap = "The fixture cleanup needs direct document close behavior; it is not a modeling operation."
        } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
        Write-Host "$Label output:"
        Write-Host $cleanupResult.output
        $script:fixtureCreated = $false
    }
    catch {
        Write-Warning "$Label failed: $($_.Exception.Message)"
    }
}

try {
    $toolsBody = New-JsonRpcPayload -Id 2 -Method "tools/list" -Params @{}
    $toolsResponse = Invoke-McpRequest -Uri $mcpUri -SessionId $sessionId -Body $toolsBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $toolsJson = $toolsResponse.Content | ConvertFrom-Json
    $toolNames = @($toolsJson.result.tools | ForEach-Object { $_.name })
    foreach ($requiredTool in @(
        "run_fusion_script",
        "inspect_sketch",
        "inspect_feature",
        "get_sketch_parameters",
        "get_feature_parameters",
        "copy_profile_loop",
        "offset_profile_loop",
        "create_insert_socket",
        "extrude_existing_profile",
        "edit_extrude_feature",
        "edit_fillet_radius",
        "edit_chamfer_distance",
        "edit_shell_thickness",
        "edit_pattern_parameter",
        "edit_hole_parameter",
        "get_parameter_usage",
        "get_projected_geometry_sources",
        "get_feature_dependencies",
        "get_dependency_graph",
        "assess_change_impact",
        "plan_parameterization",
        "get_physical_properties",
        "inspect_selection_sets",
        "inspect_3mf_archive",
        "plan_multibody_3mf_export",
        "plan_multicolor_3mf_export",
        "inspect_mesh_bodies",
        "plan_mesh_conversion",
        "repair_mesh_body",
        "reduce_mesh_body",
        "remesh_body",
        "inspect_design_configurations",
        "plan_design_variant",
        "apply_design_variant_parameters",
        "inspect_render_workspace",
        "plan_render_output",
        "render_viewport_output",
        "inspect_document_management_state",
        "plan_document_management_action",
        "export_document_copy",
        "inspect_analysis_capabilities",
        "interference_check",
        "clearance_check",
        "verify_insert_alignment",
        "exact_interference_check",
        "exact_clearance_check",
        "inspect_sheet_metal_rules",
        "preflight_flat_pattern",
        "plan_sheet_metal_workflow",
        "export_flat_pattern",
        "inspect_surface_bodies",
        "plan_surface_repair",
        "inspect_drawing_documents",
        "preflight_drawing_creation",
        "plan_drawing_views",
        "inspect_electronics_workspace",
        "plan_pcb_enclosure_fit",
        "inspect_simulation_workspace",
        "list_simulation_studies",
        "plan_simulation_study",
        "add_drawing_view",
        "add_drawing_dimension",
        "add_drawing_callout",
        "add_parts_list",
        "add_revision_table",
        "inspect_manufacturing_workspace",
        "list_manufacturing_setups",
        "inspect_operation",
        "plan_manufacturing_operation",
        "create_manufacturing_setup",
        "create_manufacturing_operation",
        "generate_toolpaths",
        "post_process",
        "get_assembly_references",
        "plan_joint_limits",
        "create_section_analysis",
        "delete_section_analysis",
        "delete_named_experiment",
        "create_revolute_joint",
        "create_slider_joint",
        "create_cylindrical_joint",
        "create_pin_slot_joint",
        "create_planar_joint",
        "create_ball_joint",
        "set_joint_limits",
        "create_flange",
        "create_bend",
        "unfold_sheet_metal",
        "refold_sheet_metal",
        "patch_surface",
        "stitch_surfaces",
        "thicken_surface",
        "trim_surface",
        "extend_surface",
        "create_ruled_surface",
        "doctor",
        "recommend_mcp_workflow",
        "get_runtime_diagnostics",
        "map_coordinates"
    )) {
        Assert-True -Condition ($toolNames -contains $requiredTool) -Message "Required tool '$requiredTool' was not advertised."
    }
    Add-FixtureProbe -Name "tools_list" -Status "passed" -Detail @{
        advertisedToolCount = $toolNames.Count
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

    revolve_sketch = root.sketches.add(root.xYConstructionPlane)
    revolve_sketch.name = "Fixture_RevolveSketch"
    revolve_sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        adsk.core.Point3D.create(0.8, -0.5, 0),
        adsk.core.Point3D.create(1.4, 0.5, 0)
    )

    loft_plane_input = root.constructionPlanes.createInput()
    loft_plane_input.setByOffset(root.xYConstructionPlane, adsk.core.ValueInput.createByString("12 mm"))
    loft_plane = root.constructionPlanes.add(loft_plane_input)
    loft_plane.name = "Fixture_LoftSectionPlane"
    loft_sketch_a = root.sketches.add(root.xYConstructionPlane)
    loft_sketch_a.name = "Fixture_LoftSectionA"
    loft_sketch_a.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(-1.0, 2.8, 0), 0.4)
    loft_sketch_b = root.sketches.add(loft_plane)
    loft_sketch_b.name = "Fixture_LoftSectionB"
    loft_sketch_b.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(-1.0, 2.8, 0), 0.8)

    sweep_profile_sketch = root.sketches.add(root.yZConstructionPlane)
    sweep_profile_sketch.name = "Fixture_SweepProfile"
    sweep_profile_sketch.sketchCurves.sketchCircles.addByCenterRadius(adsk.core.Point3D.create(0, 0, 0), 0.2)
    sweep_path_sketch = root.sketches.add(root.xYConstructionPlane)
    sweep_path_sketch.name = "Fixture_SweepPath"
    sweep_path_sketch.sketchCurves.sketchLines.addByTwoPoints(
        adsk.core.Point3D.create(0, 0, 0),
        adsk.core.Point3D.create(2.0, 0, 0)
    )

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
            script_intent = "Create a controlled inspection fixture document for FusionMCP smoke testing."
            mcp_tool_gap = "The smoke fixture intentionally builds many relationships in one setup script so the inspection tools can be verified against a known design."
        } -TimeoutSec ([Math]::Max($TimeoutSec, 30)) -ExtraHeaders $authHeaders
        Write-Host "Fixture creation output:"
        Write-Host $fixtureResult.output
        $script:fixtureCreated = $true
        Add-FixtureProbe -Name "fixture_creation" -Status "passed" -Detail @{
            output = $fixtureResult.output
        }
    }

    $baseSketch = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 4 -Name "inspect_sketch" -Arguments @{
        sketch_name = "Fixture_BaseSketch"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($baseSketch.result.name -eq "Fixture_BaseSketch") -Message "inspect_sketch did not return Fixture_BaseSketch."
    Assert-True -Condition (@($baseSketch.result.parameters).Count -ge 1) -Message "Fixture_BaseSketch did not expose dimension parameters."
    Assert-True -Condition (@($baseSketch.result.curves.lines).Count -ge 4) -Message "Fixture_BaseSketch did not expose rectangle lines."

    $baseExtrude = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 5 -Name "inspect_feature" -Arguments @{
        feature_name = "Fixture_BaseExtrude"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($baseExtrude.result.featureType -eq "ExtrudeFeature") -Message "inspect_feature did not identify Fixture_BaseExtrude as an ExtrudeFeature."
    Assert-True -Condition (@($baseExtrude.result.parameters).Count -ge 1) -Message "Fixture_BaseExtrude did not expose feature parameters."
    Assert-True -Condition (@($baseExtrude.result.resultBodies) -contains "Fixture_BaseBody") -Message "Fixture_BaseExtrude did not expose Fixture_BaseBody."

    $projectSketch = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 6 -Name "inspect_sketch" -Arguments @{
        sketch_name = "Fixture_ProjectSketch"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
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
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($null -ne $mapped.result.sketchToModel) -Message "map_coordinates did not return sketchToModel."
    Assert-True -Condition ($null -ne $mapped.result.sketchToTargetComponent) -Message "map_coordinates did not return sketchToTargetComponent."
    Assert-True -Condition ($mapped.result.componentName -eq "Fixture_TargetComponent") -Message "map_coordinates did not resolve Fixture_TargetComponent."

    $dependencies = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 8 -Name "get_feature_dependencies" -Arguments @{
        feature_name = "Fixture_BaseExtrude"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($dependencies.result.bestEffort -eq $true) -Message "get_feature_dependencies did not identify bestEffort output."
    Assert-True -Condition (@($dependencies.result.directInputs).Count -ge 1) -Message "get_feature_dependencies did not report direct inputs."

    $pointA = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 9 -Name "create_construction_point" -Arguments @{
        name = "Fixture_AxisPointA"
        mode = "coordinates"
        base_plane_name = "xy"
        x = "0 mm"
        y = "0 mm"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($pointA.result.pointName -eq "Fixture_AxisPointA") -Message "create_construction_point did not create Fixture_AxisPointA."

    $pointB = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 10 -Name "create_construction_point" -Arguments @{
        name = "Fixture_AxisPointB"
        mode = "coordinates"
        base_plane_name = "xy"
        x = "20 mm"
        y = "0 mm"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($pointB.result.pointName -eq "Fixture_AxisPointB") -Message "create_construction_point did not create Fixture_AxisPointB."

    $axis = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 11 -Name "create_construction_axis" -Arguments @{
        name = "Fixture_PatternAxis"
        mode = "two_points"
        point_name_one = "Fixture_AxisPointA"
        point_name_two = "Fixture_AxisPointB"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($axis.result.axisName -eq "Fixture_PatternAxis") -Message "create_construction_axis did not create Fixture_PatternAxis."

    $revolveResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 12 -Name "revolve_feature" -Arguments @{
        sketch_name = "Fixture_RevolveSketch"
        profile_index = 0
        axis_name = "y"
        angle = "180 deg"
        operation = "new_body"
        name = "Fixture_RevolveFeature"
        body_name = "Fixture_RevolveBody"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$revolveResult.result.featureName)) -Message "revolve_feature did not create Fixture_RevolveFeature."

    $loftResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 13 -Name "loft_feature" -Arguments @{
        sections = @(
            @{
                sketch_name = "Fixture_LoftSectionA"
                profile_index = 0
            },
            @{
                sketch_name = "Fixture_LoftSectionB"
                profile_index = 0
            }
        )
        operation = "new_body"
        name = "Fixture_LoftFeature"
        body_name = "Fixture_LoftBody"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$loftResult.result.featureName)) -Message "loft_feature did not create Fixture_LoftFeature."

    $sweepResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 14 -Name "sweep_feature" -Arguments @{
        profile_sketch_name = "Fixture_SweepProfile"
        profile_index = 0
        path_sketch_name = "Fixture_SweepPath"
        path_curve_index = 0
        operation = "new_body"
        name = "Fixture_SweepFeature"
        body_name = "Fixture_SweepBody"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$sweepResult.result.featureName)) -Message "sweep_feature did not create Fixture_SweepFeature."

    $shellSeed = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 15 -Name "create_rounded_rectangle_body" -Arguments @{
        name = "Fixture_ShellBody"
        base_plane = "xy"
        width = "18 mm"
        height = "12 mm"
        thickness = "6 mm"
        corner_radius = "1 mm"
        x_offset = "-35 mm"
        y_offset = "0 mm"
        operation = "new_body"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($shellSeed.result.bodyName -eq "Fixture_ShellBody") -Message "create_rounded_rectangle_body did not create Fixture_ShellBody."

    $shellResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 16 -Name "shell_body" -Arguments @{
        body_name = "Fixture_ShellBody"
        thickness = "1 mm"
        name = "Fixture_ShellFeature"
        thickness_side = "inside"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$shellResult.result.featureName)) -Message "shell_body did not create a shell feature."

    $offsetSeed = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 17 -Name "create_rounded_rectangle_body" -Arguments @{
        name = "Fixture_OffsetBody"
        base_plane = "xy"
        width = "16 mm"
        height = "10 mm"
        thickness = "4 mm"
        corner_radius = "1 mm"
        x_offset = "0 mm"
        y_offset = "28 mm"
        operation = "new_body"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($offsetSeed.result.bodyName -eq "Fixture_OffsetBody") -Message "create_rounded_rectangle_body did not create Fixture_OffsetBody."

    $offsetFaces = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 18 -Name "get_body_faces" -Arguments @{
        body_name = "Fixture_OffsetBody"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $offsetFace = @($offsetFaces.result.faces | Sort-Object -Property area -Descending | Select-Object -First 1)
    Assert-True -Condition ($null -ne $offsetFace.index) -Message "get_body_faces did not return a target face for Fixture_OffsetBody."

    $offsetResult = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 19 -Name "offset_face_or_press_pull" -Arguments @{
        body_name = "Fixture_OffsetBody"
        face_indices = @([int]$offsetFace.index)
        distance = "0.5 mm"
        name = "Fixture_OffsetFaceFeature"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    if ($offsetResult.isError) {
        Assert-True -Condition ($offsetResult.errorText -like "*offsetFacesFeatures*") -Message "offset_face_or_press_pull failed unexpectedly: $($offsetResult.errorText)"
        Write-Warning "offset_face_or_press_pull returned the expected runtime unsupported response: $($offsetResult.errorText)"
        Add-FixtureProbe -Name "offset_face_or_press_pull" -Status "unsupported" -Detail @{ error = $offsetResult.errorText }
    }
    else {
        Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$offsetResult.value.result.featureName)) -Message "offset_face_or_press_pull did not create an Offset Face feature."
        Add-FixtureProbe -Name "offset_face_or_press_pull" -Status "passed" -Detail @{ featureName = $offsetResult.value.result.featureName }
    }

    $patternSeed = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 20 -Name "create_rounded_rectangle_body" -Arguments @{
        name = "Fixture_PatternSeed"
        base_plane = "xy"
        width = "6 mm"
        height = "6 mm"
        thickness = "3 mm"
        corner_radius = "0.5 mm"
        x_offset = "35 mm"
        y_offset = "0 mm"
        operation = "new_body"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($patternSeed.result.bodyName -eq "Fixture_PatternSeed") -Message "create_rounded_rectangle_body did not create Fixture_PatternSeed."

    $patternResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 21 -Name "pattern_feature" -Arguments @{
        name = "Fixture_RectangularPattern"
        pattern_type = "rectangular"
        body_names = @("Fixture_PatternSeed")
        direction_one_axis = "x"
        quantity_one = 2
        distance_one = "12 mm"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$patternResult.result.featureName)) -Message "pattern_feature did not create Fixture_RectangularPattern."

    $mirrorResult = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 22 -Name "mirror_features_or_bodies" -Arguments @{
        name = "Fixture_MirrorFeature"
        body_names = @("Fixture_PatternSeed")
        mirror_plane_name = "yz"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition (-not [string]::IsNullOrWhiteSpace([string]$mirrorResult.result.featureName)) -Message "mirror_features_or_bodies did not create Fixture_MirrorFeature."

    $printability = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 23 -Name "inspect_printability" -Arguments @{
        body_names = @("Fixture_BaseBody", "Fixture_OffsetBody", "Fixture_ShellBody", "Fixture_RevolveBody", "Fixture_LoftBody", "Fixture_SweepBody")
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($printability.result.readOnly -eq $true) -Message "inspect_printability did not report readOnly=true."

    $meshInspection = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 231 -Name "inspect_mesh_bodies" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($meshInspection.result.readOnly -eq $true) -Message "inspect_mesh_bodies did not report readOnly=true."
    Assert-True -Condition ($null -ne $meshInspection.result.meshBodyCount) -Message "inspect_mesh_bodies did not report meshBodyCount."
    Add-FixtureProbe -Name "inspect_mesh_bodies" -Status "passed" -Detail @{ meshBodyCount = $meshInspection.result.meshBodyCount }

    $meshPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 232 -Name "plan_mesh_conversion" -Arguments @{
        body_name = "Fixture_Missing_Mesh_Body"
        conversion_intent = "convert_to_brep"
        operation = "new_body"
        acknowledge_quality_loss = $true
        reason = "Live fixture validates mesh conversion preflight without mutating a real mesh body."
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($meshPlan.result.readOnly -eq $true) -Message "plan_mesh_conversion did not report readOnly=true."
    Assert-True -Condition ($meshPlan.result.ready -eq $false) -Message "plan_mesh_conversion unexpectedly passed for a missing mesh target."
    Assert-True -Condition (@($meshPlan.result.blockers).Count -ge 1) -Message "plan_mesh_conversion did not report blockers for a missing mesh target."
    Add-FixtureProbe -Name "plan_mesh_conversion" -Status "preflight_blocked" -Detail @{ blockers = @($meshPlan.result.blockers) }

    foreach ($meshToolName in @("repair_mesh_body", "reduce_mesh_body", "remesh_body")) {
        $meshMutationBlocked = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 242 -Name $meshToolName -Arguments @{
            mesh_body_name = "FixtureMissingMesh"
            acknowledge_quality_loss = $false
            reason = "Live fixture validates mesh mutation preflight gating without mutating meshes."
        } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
        Assert-True -Condition ($meshMutationBlocked.isError -eq $true) -Message "$meshToolName unexpectedly succeeded for a missing mesh/preflight-blocked target."
        Assert-True -Condition ($meshMutationBlocked.errorText -like "*preflight failed*") -Message "$meshToolName failed unexpectedly: $($meshMutationBlocked.errorText)"
        Add-FixtureProbe -Name $meshToolName -Status "preflight_blocked" -Detail @{ error = $meshMutationBlocked.errorText }
    }

    $configurationInspection = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 233 -Name "inspect_design_configurations" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($configurationInspection.result.readOnly -eq $true) -Message "inspect_design_configurations did not report readOnly=true."
    Assert-True -Condition ($null -ne $configurationInspection.result.configurationCollectionAvailable) -Message "inspect_design_configurations did not report configurationCollectionAvailable."
    Add-FixtureProbe -Name "inspect_design_configurations" -Status "passed" -Detail @{ configurationCollectionAvailable = $configurationInspection.result.configurationCollectionAvailable }

    $variantPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 234 -Name "plan_design_variant" -Arguments @{
        variant_name = "Fixture Variant"
        parameter_changes = @{ FixtureMissingParameter = "42 mm" }
        expected_affected_bodies = @("Fixture_BaseBody")
        reason = "Live fixture validates design variant planning without editing parameters or configurations."
        requires_user_approval = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($variantPlan.result.readOnly -eq $true) -Message "plan_design_variant did not report readOnly=true."
    if ($variantPlan.result.okToProceed -ne $true) {
        Assert-True -Condition (@($variantPlan.result.blockingReasons).Count -ge 1) -Message "plan_design_variant failed without blockers."
    }
    Add-FixtureProbe -Name "plan_design_variant" -Status $(if ($variantPlan.result.okToProceed -eq $true) { "passed" } else { "preflight_blocked" }) -Detail @{ okToProceed = $variantPlan.result.okToProceed }

    $variantApply = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 235 -Name "apply_design_variant_parameters" -Arguments @{
        variant_name = "Fixture Variant"
        parameter_changes = @{ FixtureMissingParameter = "42 mm" }
        expected_affected_bodies = @("Fixture_BaseBody")
        reason = "Live fixture validates guarded variant parameter application without editing real parameters."
        requires_user_approval = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($variantApply.isError -eq $true) -Message "apply_design_variant_parameters unexpectedly succeeded for a missing fixture parameter."
    Assert-True -Condition ($variantApply.errorText -like "*Design variant parameter preflight failed*") -Message "apply_design_variant_parameters failed unexpectedly: $($variantApply.errorText)"
    Add-FixtureProbe -Name "apply_design_variant_parameters" -Status "preflight_blocked" -Detail @{ error = $variantApply.errorText }

    $renderInspection = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 236 -Name "inspect_render_workspace" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($renderInspection.result.readOnly -eq $true) -Message "inspect_render_workspace did not report readOnly=true."
    Assert-True -Condition ($null -ne $renderInspection.result.activeViewportAvailable) -Message "inspect_render_workspace did not report activeViewportAvailable."
    Add-FixtureProbe -Name "inspect_render_workspace" -Status "passed" -Detail @{ activeViewportAvailable = $renderInspection.result.activeViewportAvailable }

    $renderOutputPath = Join-Path $env:TEMP "fusion_mcp_fixture_render.png"
    $renderPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 237 -Name "plan_render_output" -Arguments @{
        camera_name = "activeViewport"
        output_path = $renderOutputPath
        width = 1280
        height = 720
        visual_style = "shaded"
        environment = "default"
        reason = "Live fixture validates render output planning without writing a render file."
        requires_user_approval = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($renderPlan.result.readOnly -eq $true) -Message "plan_render_output did not report readOnly=true."
    if ($renderPlan.result.okToProceed -ne $true) {
        Assert-True -Condition (@($renderPlan.result.blockingReasons).Count -ge 1) -Message "plan_render_output failed without blockers."
    }
    Add-FixtureProbe -Name "plan_render_output" -Status $(if ($renderPlan.result.okToProceed -eq $true) { "passed" } else { "preflight_blocked" }) -Detail @{ okToProceed = $renderPlan.result.okToProceed }

    $renderBlocked = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 238 -Name "render_viewport_output" -Arguments @{
        camera_name = "activeViewport"
        output_path = $renderOutputPath
        width = 1280
        height = 720
        visual_style = "shaded"
        reason = "Live fixture validates render output preflight gating without writing an image."
        requires_user_approval = $false
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($renderBlocked.isError -eq $true) -Message "render_viewport_output unexpectedly succeeded without required approval."
    Assert-True -Condition ($renderBlocked.errorText -like "*Render output preflight failed*") -Message "render_viewport_output failed unexpectedly: $($renderBlocked.errorText)"
    Add-FixtureProbe -Name "render_viewport_output" -Status "preflight_blocked" -Detail @{ error = $renderBlocked.errorText }

    $documentManagement = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 239 -Name "inspect_document_management_state" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($documentManagement.result.readOnly -eq $true) -Message "inspect_document_management_state did not report readOnly=true."
    Assert-True -Condition ($null -ne $documentManagement.result.openDocumentCount) -Message "inspect_document_management_state did not report openDocumentCount."
    Add-FixtureProbe -Name "inspect_document_management_state" -Status "passed" -Detail @{ cloudDataAvailable = $documentManagement.result.cloudDataAvailable }

    $documentPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 240 -Name "plan_document_management_action" -Arguments @{
        action = "export_copy"
        target_path = (Join-Path $env:TEMP "fusion_mcp_fixture_copy.f3d")
        dry_run = $true
        reason = "Live fixture validates document-management planning without saving or exporting files."
        requires_user_approval = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($documentPlan.result.readOnly -eq $true) -Message "plan_document_management_action did not report readOnly=true."
    if ($documentPlan.result.okToProceed -ne $true) {
        Assert-True -Condition (@($documentPlan.result.blockingReasons).Count -ge 1) -Message "plan_document_management_action failed without blockers."
    }
    Add-FixtureProbe -Name "plan_document_management_action" -Status $(if ($documentPlan.result.okToProceed -eq $true) { "passed" } else { "preflight_blocked" }) -Detail @{ okToProceed = $documentPlan.result.okToProceed }

    $documentCopyBlocked = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 241 -Name "export_document_copy" -Arguments @{
        target_path = (Join-Path $env:TEMP "fusion_mcp_fixture_copy.f3d")
        reason = "Live fixture validates export-copy preflight gating without writing a document archive."
        requires_user_approval = $false
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($documentCopyBlocked.isError -eq $true) -Message "export_document_copy unexpectedly succeeded without required approval."
    Assert-True -Condition ($documentCopyBlocked.errorText -like "*Document export-copy preflight failed*") -Message "export_document_copy failed unexpectedly: $($documentCopyBlocked.errorText)"
    Add-FixtureProbe -Name "export_document_copy" -Status "preflight_blocked" -Detail @{ error = $documentCopyBlocked.errorText }

    $physicalProperties = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 24 -Name "get_physical_properties" -Arguments @{
        body_name = "Fixture_BaseBody"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($physicalProperties.result.readOnly -eq $true) -Message "get_physical_properties did not report readOnly=true."
    Assert-True -Condition ($physicalProperties.result.bodyCount -ge 1) -Message "get_physical_properties did not report Fixture_BaseBody."
    Assert-True -Condition ($null -ne $physicalProperties.result.bodies[0].volumeMm3) -Message "get_physical_properties did not report converted volume."

    $interference = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 25 -Name "interference_check" -Arguments @{
        body_names = @("Fixture_BaseBody", "Fixture_OffsetBody")
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($interference.result.readOnly -eq $true) -Message "interference_check did not report readOnly=true."
    Assert-True -Condition ($interference.result.pairCount -ge 1) -Message "interference_check did not evaluate body pairs."

    $clearance = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 26 -Name "clearance_check" -Arguments @{
        target_body_names = @("Fixture_BaseBody")
        tool_body_names = @("Fixture_OffsetBody")
        minimum_clearance = "0.1 mm"
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($clearance.result.readOnly -eq $true) -Message "clearance_check did not report readOnly=true."
    Assert-True -Condition ($clearance.result.pairCount -ge 1) -Message "clearance_check did not evaluate body pairs."

    $analysisCapabilities = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 27 -Name "inspect_analysis_capabilities" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($analysisCapabilities.result.readOnly -eq $true) -Message "inspect_analysis_capabilities did not report readOnly=true."
    Add-FixtureProbe -Name "inspect_analysis_capabilities" -Status "passed" -Detail @{
        exactInterferenceStatus = $analysisCapabilities.result.exactInterference.status
        exactClearanceStatus = $analysisCapabilities.result.exactMinimumDistance.status
    }

    $exactInterference = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 28 -Name "exact_interference_check" -Arguments @{
        body_names = @("Fixture_BaseBody", "Fixture_OffsetBody")
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    if ($exactInterference.isError) {
        Assert-True -Condition (($exactInterference.errorText -like "*Exact interference APIs are not available*") -or ($exactInterference.errorText -like "*requires at least two*") -or ($exactInterference.errorText -like "*Failed to run exact interference check*")) -Message "exact_interference_check failed unexpectedly: $($exactInterference.errorText)"
        Write-Warning "exact_interference_check returned expected unsupported/error-path response: $($exactInterference.errorText)"
        Add-FixtureProbe -Name "exact_interference_check" -Status "unsupported" -Detail @{ error = $exactInterference.errorText }
    }
    else {
        Assert-True -Condition ($exactInterference.value.result.readOnly -eq $true) -Message "exact_interference_check did not report readOnly=true."
        Assert-True -Condition ($exactInterference.value.result.method -eq "temporary_brep_boolean_intersection") -Message "exact_interference_check did not report the expected method."
        Add-FixtureProbe -Name "exact_interference_check" -Status "passed" -Detail @{
            method = $exactInterference.value.result.method
            validatedExact = $exactInterference.value.result.validatedExact
            pairCount = $exactInterference.value.result.pairCount
        }
    }

    $exactClearance = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 29 -Name "exact_clearance_check" -Arguments @{
        target_body_names = @("Fixture_BaseBody")
        tool_body_names = @("Fixture_OffsetBody")
        minimum_clearance = "0.1 mm"
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    if ($exactClearance.isError) {
        Assert-True -Condition (($exactClearance.errorText -like "*Exact minimum-distance APIs are not available*") -or ($exactClearance.errorText -like "*requires at least one*") -or ($exactClearance.errorText -like "*Failed to run exact clearance check*")) -Message "exact_clearance_check failed unexpectedly: $($exactClearance.errorText)"
        Write-Warning "exact_clearance_check returned expected unsupported/error-path response: $($exactClearance.errorText)"
        Add-FixtureProbe -Name "exact_clearance_check" -Status "unsupported" -Detail @{ error = $exactClearance.errorText }
    }
    else {
        Assert-True -Condition ($exactClearance.value.result.readOnly -eq $true) -Message "exact_clearance_check did not report readOnly=true."
        Assert-True -Condition ($exactClearance.value.result.method -eq "measure_manager_minimum_distance") -Message "exact_clearance_check did not report the expected method."
        Add-FixtureProbe -Name "exact_clearance_check" -Status "passed" -Detail @{
            method = $exactClearance.value.result.method
            validatedExact = $exactClearance.value.result.validatedExact
            pairCount = $exactClearance.value.result.pairCount
        }
    }

    $assemblyRefs = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 30 -Name "get_assembly_references" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($assemblyRefs.result.readOnly -eq $true) -Message "get_assembly_references did not report readOnly=true."
    Add-FixtureProbe -Name "get_assembly_references" -Status "passed" -Detail @{ componentCount = $assemblyRefs.result.componentCount }

    $jointPlan = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 31 -Name "plan_joint_limits" -Arguments @{
        joint_name = "Fixture_MissingJoint"
        limit_type = "rotation"
        minimum = "0 deg"
        maximum = "90 deg"
        reason = "Live fixture validates joint-limit planning on a missing joint without mutating the model."
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition (-not $jointPlan.isError) -Message "plan_joint_limits should return a structured plan result, not a transport/tool error."
    Assert-True -Condition ($jointPlan.value.result.readOnly -eq $true) -Message "plan_joint_limits did not report readOnly=true."
    Assert-True -Condition ($jointPlan.value.result.okToProceed -eq $false) -Message "plan_joint_limits unexpectedly passed for a missing fixture joint."
    Add-FixtureProbe -Name "plan_joint_limits" -Status "passed" -Detail @{ okToProceed = $jointPlan.value.result.okToProceed }

    $createdMotionJointNames = @()
    $motionJointBaseArgs = @{
        point_one_name = "Fixture_AxisPointA"
        point_two_name = "Fixture_AxisPointB"
    }
    foreach ($probeSpec in @(
        @{
            id = 43
            tool = "create_revolute_joint"
            expected = "revolute"
            args = $motionJointBaseArgs + @{
                name = "Fixture_RevoluteJoint"
                motion_axis = "z"
            }
        },
        @{
            id = 44
            tool = "create_slider_joint"
            expected = "slider"
            args = $motionJointBaseArgs + @{
                name = "Fixture_SliderJoint"
                slide_direction = "x"
            }
        },
        @{
            id = 45
            tool = "create_cylindrical_joint"
            expected = "cylindrical"
            args = $motionJointBaseArgs + @{
                name = "Fixture_CylindricalJoint"
                motion_axis = "z"
            }
        },
        @{
            id = 46
            tool = "create_pin_slot_joint"
            expected = "pin_slot"
            args = $motionJointBaseArgs + @{
                name = "Fixture_PinSlotJoint"
                motion_axis = "z"
                slide_direction = "x"
            }
        },
        @{
            id = 47
            tool = "create_planar_joint"
            expected = "planar"
            args = $motionJointBaseArgs + @{
                name = "Fixture_PlanarJoint"
                normal_direction = "z"
            }
        },
        @{
            id = 48
            tool = "create_ball_joint"
            expected = "ball"
            args = $motionJointBaseArgs + @{
                name = "Fixture_BallJoint"
            }
        }
    )) {
        $createdName = Invoke-MotionJointProbe `
            -Uri $mcpUri `
            -SessionId $sessionId `
            -Id $probeSpec.id `
            -ToolName $probeSpec.tool `
            -Arguments $probeSpec.args `
            -ExpectedKind $probeSpec.expected `
            -TimeoutSec $TimeoutSec `
            -ExtraHeaders $authHeaders
        if ($createdName) {
            $createdMotionJointNames += $createdName
        }
    }

    if ($createdMotionJointNames.Count -gt 0) {
        $assemblyJointsAfterMotion = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 49 -Name "get_assembly_joints" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
        $reportedJointNames = @($assemblyJointsAfterMotion.result.joints | ForEach-Object { $_.name })
        foreach ($createdJointName in $createdMotionJointNames) {
            Assert-True -Condition ($reportedJointNames -contains $createdJointName) -Message "get_assembly_joints did not report created motion joint '$createdJointName'."
        }
    }

    $surfacePlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 32 -Name "plan_surface_repair" -Arguments @{
        operation = "thicken_surface"
        body_name = "Fixture_BaseBody"
        parameters = @{ thickness = "0.5 mm" }
        reason = "Live fixture validates guarded surface repair planning on an explicit solid body."
        allow_solid_body = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($surfacePlan.result.readOnly -eq $true) -Message "plan_surface_repair did not report readOnly=true."
    Assert-True -Condition ($surfacePlan.result.operation -eq "thicken_surface") -Message "plan_surface_repair did not echo thicken_surface operation."
    Add-FixtureProbe -Name "plan_surface_repair" -Status "passed" -Detail @{ operation = $surfacePlan.result.operation; okToProceed = $surfacePlan.result.okToProceed }

    $surfaceMutator = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 33 -Name "thicken_surface" -Arguments @{
        body_name = "Fixture_BaseBody"
        parameters = @{ thickness = "0.5 mm" }
        reason = "Live fixture validates guarded surface mutator unsupported handling."
        allow_solid_body = $true
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    if ($surfaceMutator.isError) {
        Assert-True -Condition (($surfaceMutator.errorText -like "*preflight failed*") -or ($surfaceMutator.errorText -like "*thickenFeatures*") -or ($surfaceMutator.errorText -like "*surface feature*")) -Message "thicken_surface failed unexpectedly: $($surfaceMutator.errorText)"
        Add-FixtureProbe -Name "thicken_surface" -Status "unsupported" -Detail @{ error = $surfaceMutator.errorText }
    }
    else {
        Assert-True -Condition (($surfaceMutator.value.result.operation -eq "thicken_surface") -or ($surfaceMutator.value.unsupported -eq $true)) -Message "thicken_surface did not return a mutator or unsupported result."
        Add-FixtureProbe -Name "thicken_surface" -Status $(if ($surfaceMutator.value.unsupported -eq $true) { "unsupported" } else { "passed" }) -Detail @{ operation = $surfaceMutator.value.result.operation }
    }

    $sheetRules = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 34 -Name "inspect_sheet_metal_rules" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($sheetRules.result.readOnly -eq $true) -Message "inspect_sheet_metal_rules did not report readOnly=true."
    Add-FixtureProbe -Name "inspect_sheet_metal_rules" -Status "passed" -Detail @{ bodyCount = @($sheetRules.result.bodies).Count }

    $sheetPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 35 -Name "plan_sheet_metal_workflow" -Arguments @{
        operation = "create_flange"
        body_name = "Fixture_BaseBody"
        edge_entity_tokens = @("fixture-missing-edge-token")
        rule_name = "Fixture Missing Rule"
        parameters = @{ height = "5 mm"; angle = "90 deg" }
        reason = "Live fixture validates sheet-metal planner blockers on a non-sheet-metal body."
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($sheetPlan.result.readOnly -eq $true) -Message "plan_sheet_metal_workflow did not report readOnly=true."
    Assert-True -Condition ($sheetPlan.result.okToProceed -eq $false) -Message "plan_sheet_metal_workflow unexpectedly passed for a non-sheet-metal fixture body."
    Add-FixtureProbe -Name "plan_sheet_metal_workflow" -Status "passed" -Detail @{ okToProceed = $sheetPlan.result.okToProceed }

    $sheetMutator = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 36 -Name "create_flange" -Arguments @{
        body_name = "Fixture_BaseBody"
        edge_entity_tokens = @("fixture-missing-edge-token")
        rule_name = "Fixture Missing Rule"
        parameters = @{ height = "5 mm"; angle = "90 deg" }
        reason = "Live fixture validates guarded sheet-metal mutator preflight."
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition ($sheetMutator.isError -eq $true) -Message "create_flange should fail preflight on the non-sheet-metal fixture body."
    Assert-True -Condition ($sheetMutator.errorText -like "*Sheet-metal operation preflight failed*") -Message "create_flange did not report the expected preflight failure: $($sheetMutator.errorText)"
    Add-FixtureProbe -Name "create_flange" -Status "preflight_blocked" -Detail @{ error = $sheetMutator.errorText }

    $drawingPreflight = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 37 -Name "preflight_drawing_creation" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($drawingPreflight.result.readOnly -eq $true) -Message "preflight_drawing_creation did not report readOnly=true."
    Add-FixtureProbe -Name "preflight_drawing_creation" -Status "passed" -Detail @{ okToProceed = $drawingPreflight.result.okToProceed }

    $drawingMutator = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 38 -Name "add_drawing_callout" -Arguments @{
        text = "CHECK FIT"
        reason = "Live fixture validates drawing mutator unsupported handling outside a drawing document."
    } -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    Assert-True -Condition ($drawingMutator.isError -eq $true) -Message "add_drawing_callout should fail outside an active drawing document."
    Assert-True -Condition (($drawingMutator.errorText -like "*not an open Fusion drawing document*") -or ($drawingMutator.errorText -like "*Drawing API is not available*")) -Message "add_drawing_callout did not return the expected unsupported drawing response: $($drawingMutator.errorText)"
    Add-FixtureProbe -Name "add_drawing_callout" -Status "unsupported" -Detail @{ error = $drawingMutator.errorText }

    $electronicsWorkspace = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 371 -Name "inspect_electronics_workspace" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($electronicsWorkspace.result.readOnly -eq $true) -Message "inspect_electronics_workspace did not report readOnly=true."
    Add-FixtureProbe -Name "inspect_electronics_workspace" -Status "passed" -Detail @{ workspaceAvailable = $electronicsWorkspace.result.workspaceAvailable }

    $pcbFitPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 372 -Name "plan_pcb_enclosure_fit" -Arguments @{
        board_outline = @{ width = "80 mm"; height = "50 mm"; thickness = "1.6 mm" }
        keepouts = @{ antenna = @{ x = "0 mm"; y = "0 mm"; width = "20 mm"; height = "8 mm" } }
        connectors = @{ J1 = @{ type = "usb-c"; envelope = "10 x 8 x 4 mm"; insertion_direction = "front" } }
        mounting_holes = @{ H1 = @{ x = "5 mm"; y = "5 mm"; diameter = "3.2 mm" } }
        clearance_rules = @{ board_to_wall = "1.5 mm"; connector_service = "6 mm" }
        enclosure_body_name = "Fixture_BaseBody"
        reason = "Live fixture validates PCB enclosure-fit planning without editing electronics or mechanical geometry."
        requires_user_approval = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($pcbFitPlan.result.readOnly -eq $true) -Message "plan_pcb_enclosure_fit did not report readOnly=true."
    if ($pcbFitPlan.result.okToProceed -ne $true) {
        Assert-True -Condition (@($pcbFitPlan.result.blockingReasons).Count -ge 1) -Message "plan_pcb_enclosure_fit failed without blockers."
    }
    Add-FixtureProbe -Name "plan_pcb_enclosure_fit" -Status $(if ($pcbFitPlan.result.okToProceed -eq $true) { "passed" } else { "preflight_blocked" }) -Detail @{ okToProceed = $pcbFitPlan.result.okToProceed }

    $simulationWorkspace = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 381 -Name "inspect_simulation_workspace" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($simulationWorkspace.result.readOnly -eq $true) -Message "inspect_simulation_workspace did not report readOnly=true."
    Add-FixtureProbe -Name "inspect_simulation_workspace" -Status "passed" -Detail @{ workspaceAvailable = $simulationWorkspace.result.workspaceAvailable }

    $simulationStudies = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 382 -Name "list_simulation_studies" -Arguments @{} -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($simulationStudies.result.readOnly -eq $true) -Message "list_simulation_studies did not report readOnly=true."
    Add-FixtureProbe -Name "list_simulation_studies" -Status "passed" -Detail @{ studyCount = $simulationStudies.result.studyCount }

    $simulationPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 383 -Name "plan_simulation_study" -Arguments @{
        study_name = "Fixture Static Stress"
        study_type = "static_stress"
        target_body_names = @("Fixture_BaseBody")
        materials = @{ Fixture_BaseBody = "fixture material" }
        loads = @{ load1 = @{ type = "force"; magnitude = "10 N"; direction = "z" } }
        constraints = @{ fixed1 = @{ type = "fixed"; target = "Fixture_BaseBody" } }
        mesh_settings = @{ size = "5 mm"; order = "linear" }
        result_outputs = @{ plots = @("stress", "displacement") }
        requires_user_approval = $true
    } -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($simulationPlan.result.readOnly -eq $true) -Message "plan_simulation_study did not report readOnly=true."
    if ($simulationPlan.result.okToProceed -ne $true) {
        Assert-True -Condition (@($simulationPlan.result.blockingReasons).Count -ge 1) -Message "plan_simulation_study failed without blockers."
    }
    Add-FixtureProbe -Name "plan_simulation_study" -Status $(if ($simulationPlan.result.okToProceed -eq $true) { "passed" } else { "preflight_blocked" }) -Detail @{ okToProceed = $simulationPlan.result.okToProceed }

    $manufacturingPlanArgs = @{
        setup_name = "Fixture Setup"
        operation_name = "Fixture Adaptive"
        operation_type = "adaptive"
        machine = @{ name = "Fixture Machine"; controller = "generic" }
        stock = @{ x_mm = 40; y_mm = 20; z_mm = 8; material = "fixture" }
        wcs = @{ origin = "stock_box_point"; axis = "model_z" }
        tool = @{ name = "Fixture Tool"; diameter_mm = 6; flutes = 2 }
        feeds = @{ cut_mm_per_min = 500; plunge_mm_per_min = 100 }
        speeds = @{ spindle_rpm = 10000 }
        post_processor = @{ name = "fixture-generic"; output_extension = "nc" }
        requires_user_approval = $true
    }
    $manufacturingPlan = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 39 -Name "plan_manufacturing_operation" -Arguments $manufacturingPlanArgs -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    Assert-True -Condition ($manufacturingPlan.result.readOnly -eq $true) -Message "plan_manufacturing_operation did not report readOnly=true."
    if ($manufacturingPlan.result.okToProceed -ne $true) {
        Assert-True -Condition (@($manufacturingPlan.result.blockingReasons).Count -ge 1) -Message "plan_manufacturing_operation failed without blockers."
    }
    Add-FixtureProbe -Name "plan_manufacturing_operation" -Status "passed" -Detail @{ okToProceed = $manufacturingPlan.result.okToProceed }

    $toolpathProbe = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 40 -Name "generate_toolpaths" -Arguments $manufacturingPlanArgs -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    if ($toolpathProbe.isError) {
        Assert-True -Condition (($toolpathProbe.errorText -like "*Manufacturing preflight failed*") -or ($toolpathProbe.errorText -like "*Target setup or operation was not found*") -or ($toolpathProbe.errorText -like "*toolpath generation method*")) -Message "generate_toolpaths failed unexpectedly: $($toolpathProbe.errorText)"
        Add-FixtureProbe -Name "generate_toolpaths" -Status "preflight_blocked" -Detail @{ error = $toolpathProbe.errorText }
    }
    else {
        Assert-True -Condition (($toolpathProbe.value.result.generated -eq $true) -or ($toolpathProbe.value.unsupported -eq $true)) -Message "generate_toolpaths did not return a generated or unsupported result."
        Add-FixtureProbe -Name "generate_toolpaths" -Status $(if ($toolpathProbe.value.unsupported -eq $true) { "unsupported" } else { "passed" }) -Detail @{ generated = $toolpathProbe.value.result.generated }
    }

    $postProbeArgs = $manufacturingPlanArgs.Clone()
    $postProbeArgs.output_path = Join-Path $env:TEMP "fusion_mcp_fixture.nc"
    $postProbe = Invoke-McpToolAllowError -Uri $mcpUri -SessionId $sessionId -Id 41 -Name "post_process" -Arguments $postProbeArgs -TimeoutSec ([Math]::Max($TimeoutSec, 20)) -ExtraHeaders $authHeaders
    if ($postProbe.isError) {
        Assert-True -Condition (($postProbe.errorText -like "*Manufacturing preflight failed*") -or ($postProbe.errorText -like "*Target setup or operation was not found*") -or ($postProbe.errorText -like "*post-processing method*")) -Message "post_process failed unexpectedly: $($postProbe.errorText)"
        Add-FixtureProbe -Name "post_process" -Status "preflight_blocked" -Detail @{ error = $postProbe.errorText }
    }
    else {
        Assert-True -Condition (($postProbe.value.result.posted -eq $true) -or ($postProbe.value.unsupported -eq $true)) -Message "post_process did not return a posted or unsupported result."
        Add-FixtureProbe -Name "post_process" -Status $(if ($postProbe.value.unsupported -eq $true) { "unsupported" } else { "passed" }) -Detail @{ posted = $postProbe.value.result.posted }
    }

    $demoOutput = Join-Path $env:TEMP "fusion_mcp_fixture_frames"
    $demoCapture = Invoke-McpTool -Uri $mcpUri -SessionId $sessionId -Id 42 -Name "capture_demo_sequence" -Arguments @{
        output_dir = $demoOutput
        image_width = 640
        image_height = 360
        view_names = @("iso", "front")
        hide_all_sketches = $true
        restore_visibility = $true
    } -TimeoutSec ([Math]::Max($TimeoutSec, 30)) -ExtraHeaders $authHeaders
    Assert-True -Condition ($demoCapture.result.frameCount -ge 2) -Message "capture_demo_sequence did not capture expected frames."
    Add-FixtureProbe -Name "capture_demo_sequence" -Status "passed" -Detail @{ frameCount = $demoCapture.result.frameCount }

    Invoke-FixtureDocumentCleanup
    Add-FixtureProbe -Name "fixture_cleanup" -Status "passed" -Detail @{ fixtureDocumentOpen = $script:fixtureCreated }

    $script:fixturePassed = $true
    Write-Host "Fusion MCP inspection fixture verification passed."
    Write-Host "Health: $healthUri"
    Write-Host "Session: $sessionId"
}
catch {
    $script:fixtureFailure = $_.Exception.Message
    throw
}
finally {
    Invoke-FixtureDocumentCleanup -Label "Fixture cleanup after failure"
    Write-FixtureReport -Status $(if ($script:fixturePassed) { "passed" } else { "failed" })

    if ($sessionId) {
        try {
            Invoke-WebRequest `
                -Uri $mcpUri `
                -Method Delete `
                -Headers ($authHeaders + @{ "Mcp-Session-Id" = $sessionId }) `
                -TimeoutSec $TimeoutSec `
                -UseBasicParsing | Out-Null
        }
        catch {
            Write-Warning "Failed to close MCP session '$sessionId': $($_.Exception.Message)"
        }
    }
}
