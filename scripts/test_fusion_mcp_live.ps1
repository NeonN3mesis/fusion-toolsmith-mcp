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

$effectiveSseUrl = $discovery.sse_url
$authHeaders = @{}
if ($discovery.bearer_sse_url -and $discovery.authorization_header) {
    $effectiveSseUrl = $discovery.bearer_sse_url
    $authHeaders["Authorization"] = $discovery.authorization_header
}

$request = [System.Net.HttpWebRequest]::Create($effectiveSseUrl)
$request.Method = "GET"
$request.Accept = "text/event-stream"
$request.Timeout = $TimeoutSec * 1000
$request.ReadWriteTimeout = $TimeoutSec * 1000
if ($authHeaders.ContainsKey("Authorization")) {
    $request.Headers["Authorization"] = $authHeaders["Authorization"]
}

$response = $request.GetResponse()
try {
    $reader = [System.IO.StreamReader]::new($response.GetResponseStream())
    $endpointEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    if ($endpointEvent.event -ne "endpoint" -or -not $endpointEvent.data.StartsWith("/messages?")) {
        throw "Unexpected endpoint event: $($endpointEvent | ConvertTo-Json -Compress)"
    }

    $messagesUri = "{0}://{1}:{2}{3}" -f $baseUri.Scheme, $baseUri.Host, $baseUri.Port, $endpointEvent.data
    $initializeBody = @{
        jsonrpc = "2.0"
        id = 1
        method = "initialize"
        params = @{}
    } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri $messagesUri -Method Post -Headers $authHeaders -Body $initializeBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

    $initializeEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    if ($initializeEvent.event -ne "message") {
        throw "Expected initialize message event, got: $($initializeEvent | ConvertTo-Json -Compress)"
    }
    $initializeResponse = $initializeEvent.data | ConvertFrom-Json
    if ($initializeResponse.id -ne 1 -or $initializeResponse.result.serverInfo.name -ne "fusion-mcp") {
        throw "Unexpected initialize response: $($initializeResponse | ConvertTo-Json -Compress)"
    }

    $toolsBody = @{
        jsonrpc = "2.0"
        id = 2
        method = "tools/list"
        params = @{}
    } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri $messagesUri -Method Post -Headers $authHeaders -Body $toolsBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

    $toolsEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    $toolsResponse = $toolsEvent.data | ConvertFrom-Json
    $toolNames = @($toolsResponse.result.tools | ForEach-Object { $_.name })
    $requiredTools = @(
        "inspect_design",
        "recommend_mcp_workflow",
        "extract_reference_dimensions",
        "create_rounded_rectangle_body",
        "create_rounded_slot_cut",
        "create_counterbore_hole_pattern",
        "set_visibility"
    )
    $missingTools = @($requiredTools | Where-Object { $toolNames -notcontains $_ })
    if ($toolsResponse.id -ne 2 -or $missingTools.Count -gt 0) {
        throw "tools/list did not return expected tools. Missing: $($missingTools -join ', ')"
    }

    $inspectBody = @{
        jsonrpc = "2.0"
        id = 3
        method = "tools/call"
        params = @{
            name = "inspect_design"
            arguments = @{}
        }
    } | ConvertTo-Json -Depth 20 -Compress
    Invoke-RestMethod -Uri $messagesUri -Method Post -Headers $authHeaders -Body $inspectBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

    $inspectEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    $inspectResponse = $inspectEvent.data | ConvertFrom-Json
    if ($inspectResponse.id -ne 3 -or $inspectResponse.error -or $inspectResponse.result.isError) {
        throw "inspect_design tool call failed: $($inspectResponse | ConvertTo-Json -Compress -Depth 20)"
    }

    $doctorBody = @{
        jsonrpc = "2.0"
        id = 4
        method = "tools/call"
        params = @{
            name = "doctor"
            arguments = @{
                require_active_design = $false
            }
        }
    } | ConvertTo-Json -Depth 20 -Compress
    Invoke-RestMethod -Uri $messagesUri -Method Post -Headers $authHeaders -Body $doctorBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

    $doctorEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    $doctorResponse = $doctorEvent.data | ConvertFrom-Json
    if ($doctorResponse.id -ne 4 -or $doctorResponse.error -or $doctorResponse.result.isError) {
        throw "doctor tool call failed: $($doctorResponse | ConvertTo-Json -Compress -Depth 20)"
    }

    $workflowBody = @{
        jsonrpc = "2.0"
        id = 5
        method = "tools/call"
        params = @{
            name = "recommend_mcp_workflow"
            arguments = @{
                task = "Export this model as STEP."
            }
        }
    } | ConvertTo-Json -Depth 20 -Compress
    Invoke-RestMethod -Uri $messagesUri -Method Post -Headers $authHeaders -Body $workflowBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

    $workflowEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    $workflowResponse = $workflowEvent.data | ConvertFrom-Json
    if ($workflowResponse.id -ne 5 -or $workflowResponse.error -or $workflowResponse.result.isError) {
        throw "recommend_mcp_workflow tool call failed: $($workflowResponse | ConvertTo-Json -Compress -Depth 20)"
    }
}
finally {
    $response.Close()
}

Write-Host "Fusion MCP live smoke test passed."
Write-Host "Health: $healthUri"
