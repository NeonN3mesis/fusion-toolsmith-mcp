param(
    [string]$DiscoveryPath = "$env:USERPROFILE\.fusion_mcp.json",
    [int]$ExpectedPort = 9100,
    [int]$TimeoutSec = 5
)

$ErrorActionPreference = "Stop"

function Read-SseEvent {
    param(
        [System.IO.StreamReader]$Reader,
        [int]$DeadlineMs
    )

    $eventName = ""
    $dataLines = New-Object System.Collections.Generic.List[string]
    $started = Get-Date

    while (((Get-Date) - $started).TotalMilliseconds -lt $DeadlineMs) {
        $lineTask = $Reader.ReadLineAsync()
        if (-not $lineTask.Wait(250)) {
            continue
        }

        $line = $lineTask.Result
        if ($null -eq $line) {
            throw "SSE stream closed before expected event."
        }

        if ($line.Length -eq 0) {
            if ($eventName -or $dataLines.Count -gt 0) {
                return @{
                    event = $eventName
                    data = ($dataLines -join "`n")
                }
            }
            continue
        }

        if ($line.StartsWith(":")) {
            continue
        }

        if ($line.StartsWith("event:")) {
            $eventName = $line.Substring(6).Trim()
            continue
        }

        if ($line.StartsWith("data:")) {
            $dataLines.Add($line.Substring(5).TrimStart())
        }
    }

    throw "Timed out waiting for SSE event."
}

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

$sessionId = $null
try {
    $initializeBody = New-JsonRpcPayload -Id 1 -Method "initialize" -Params @{}
    try {
        $initializeHttpResponse = Invoke-McpRequest -Uri $mcpUri -SessionId "" -Body $initializeBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    }
    catch {
        $statusCode = $null
        if ($_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        if ($statusCode -eq 404 -and $legacyStreamableUri -and $legacyStreamableUri -ne $mcpUri) {
            $mcpUri = $legacyStreamableUri
            $initializeHttpResponse = Invoke-McpRequest -Uri $mcpUri -SessionId "" -Body $initializeBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
        }
        else {
            throw
        }
    }
    $sessionId = @($initializeHttpResponse.Headers["Mcp-Session-Id"])[0]
    if (-not $sessionId) {
        throw "Streamable HTTP initialize did not return Mcp-Session-Id."
    }
    $initializeResponse = $initializeHttpResponse.Content | ConvertFrom-Json
    if ($initializeResponse.id -ne 1 -or $initializeResponse.result.serverInfo.name -ne "fusion-mcp") {
        throw "Unexpected initialize response: $($initializeResponse | ConvertTo-Json -Compress)"
    }

    $toolsBody = New-JsonRpcPayload -Id 2 -Method "tools/list" -Params @{}
    $toolsHttpResponse = Invoke-McpRequest -Uri $mcpUri -SessionId $sessionId -Body $toolsBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $toolsResponse = $toolsHttpResponse.Content | ConvertFrom-Json
    $toolNames = @($toolsResponse.result.tools | ForEach-Object { $_.name })
    $requiredTools = @(
        "inspect_design",
        "recommend_mcp_workflow",
        "extract_reference_dimensions",
        "inspect_printability",
        "inspect_selection_sets",
        "inspect_3mf_archive",
        "plan_multibody_3mf_export",
        "plan_multicolor_3mf_export",
        "inspect_mesh_bodies",
        "plan_mesh_conversion",
        "inspect_design_configurations",
        "plan_design_variant",
        "apply_design_variant_parameters",
        "inspect_render_workspace",
        "plan_render_output",
        "render_viewport_output",
        "inspect_document_management_state",
        "plan_document_management_action",
        "export_document_copy",
        "get_physical_properties",
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
        "inspect_manufacturing_workspace",
        "list_manufacturing_setups",
        "inspect_operation",
        "plan_manufacturing_operation",
        "create_manufacturing_setup",
        "create_manufacturing_operation",
        "generate_toolpaths",
        "post_process",
        "get_body_faces",
        "get_body_edges",
        "get_assembly_tree",
        "get_assembly_references",
        "get_assembly_joints",
        "plan_joint_limits",
        "list_appearances",
        "inspect_body_style",
        "get_timeline",
        "measure_entity",
        "validate_model",
        "assess_change_impact",
        "preflight_model_change",
        "edit_extrude_feature",
        "edit_fillet_radius",
        "edit_chamfer_distance",
        "edit_shell_thickness",
        "edit_pattern_parameter",
        "edit_hole_parameter",
        "offset_face_or_press_pull",
        "create_offset_plane",
        "create_construction_point",
        "create_construction_axis",
        "create_rigid_joint",
        "create_section_analysis",
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
        "add_sketch_constraint",
        "delete_sketch_constraint",
        "create_sketch_offset",
        "copy_profile_loop",
        "offset_profile_loop",
        "create_insert_socket",
        "create_parametric_feature",
        "extrude_existing_profile",
        "revolve_feature",
        "loft_feature",
        "sweep_feature",
        "create_rounded_rectangle_body",
        "create_rounded_slot_cut",
        "create_rounded_pocket",
        "create_hole_pattern",
        "create_counterbore_hole_pattern",
        "mirror_features_or_bodies",
        "pattern_feature",
        "apply_appearance",
        "convert_mesh_to_solid",
        "repair_mesh_body",
        "reduce_mesh_body",
        "remesh_body",
        "reorganize_body_to_component",
        "import_parameters_csv",
        "export_parameters_csv",
        "capture_view",
        "add_drawing_view",
        "add_drawing_dimension",
        "add_drawing_callout",
        "add_parts_list",
        "add_revision_table",
        "set_camera",
        "shell_body",
        "set_visibility",
        "capture_demo_sequence",
        "prompt_user",
        "list_documents",
        "create_design_document",
        "close_active_document",
        "delete_named_experiment",
        "set_timeline_marker",
        "clone_timeline_feature"
    )
    $missingTools = @($requiredTools | Where-Object { $toolNames -notcontains $_ })
    if ($toolsResponse.id -ne 2 -or $missingTools.Count -gt 0) {
        $installedAddIn = Join-Path $env:APPDATA "Autodesk\Autodesk Fusion 360\API\AddIns\FusionMCP"
        $installedHint = ""
        if (Test-Path -LiteralPath $installedAddIn -PathType Container) {
            $installedHint = " Installed add-in path exists at $installedAddIn."
        }
        throw "tools/list did not return expected tools. Missing: $($missingTools -join ', ').$installedHint If you just installed or updated FusionMCP, stop and run the FusionMCP add-in again from Fusion 360 Utilities > Add-Ins, or restart Fusion so it reloads Python modules."
    }

    $inspectBody = New-JsonRpcPayload -Id 3 -Method "tools/call" -Params @{
        name = "inspect_design"
        arguments = @{}
    }
    $inspectHttpResponse = Invoke-McpRequest -Uri $mcpUri -SessionId $sessionId -Body $inspectBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $inspectResponse = $inspectHttpResponse.Content | ConvertFrom-Json
    if ($inspectResponse.id -ne 3 -or $inspectResponse.error -or $inspectResponse.result.isError) {
        throw "inspect_design tool call failed: $($inspectResponse | ConvertTo-Json -Compress -Depth 20)"
    }

    $doctorBody = New-JsonRpcPayload -Id 4 -Method "tools/call" -Params @{
        name = "doctor"
        arguments = @{
            require_active_design = $false
        }
    }
    $doctorHttpResponse = Invoke-McpRequest -Uri $mcpUri -SessionId $sessionId -Body $doctorBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $doctorResponse = $doctorHttpResponse.Content | ConvertFrom-Json
    if ($doctorResponse.id -ne 4 -or $doctorResponse.error -or $doctorResponse.result.isError) {
        throw "doctor tool call failed: $($doctorResponse | ConvertTo-Json -Compress -Depth 20)"
    }

    $workflowBody = New-JsonRpcPayload -Id 5 -Method "tools/call" -Params @{
        name = "recommend_mcp_workflow"
        arguments = @{
            task = "Export this model as STEP."
        }
    }
    $workflowHttpResponse = Invoke-McpRequest -Uri $mcpUri -SessionId $sessionId -Body $workflowBody -TimeoutSec $TimeoutSec -ExtraHeaders $authHeaders
    $workflowResponse = $workflowHttpResponse.Content | ConvertFrom-Json
    if ($workflowResponse.id -ne 5 -or $workflowResponse.error -or $workflowResponse.result.isError) {
        throw "recommend_mcp_workflow tool call failed: $($workflowResponse | ConvertTo-Json -Compress -Depth 20)"
    }
}
finally {
    if ($sessionId) {
        try {
            $deleteRequest = [System.Net.HttpWebRequest]::Create($mcpUri)
            $deleteRequest.Method = "DELETE"
            $deleteRequest.Timeout = $TimeoutSec * 1000
            $deleteRequest.ReadWriteTimeout = $TimeoutSec * 1000
            $deleteRequest.Headers["Mcp-Session-Id"] = $sessionId
            if ($authHeaders.ContainsKey("Authorization")) {
                $deleteRequest.Headers["Authorization"] = $authHeaders["Authorization"]
            }
            $deleteResponse = $deleteRequest.GetResponse()
            $deleteResponse.Close()
        }
        catch {
            Write-Warning "Failed to explicitly close MCP Streamable HTTP session: $($_.Exception.Message)"
        }
    }
}

Write-Host "Fusion MCP live smoke test passed."
Write-Host "Health: $healthUri"
