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

$request = [System.Net.HttpWebRequest]::Create($discovery.sse_url)
$request.Method = "GET"
$request.Accept = "text/event-stream"
$request.Timeout = $TimeoutSec * 1000
$request.ReadWriteTimeout = $TimeoutSec * 1000

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
    Invoke-RestMethod -Uri $messagesUri -Method Post -Body $initializeBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

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
    Invoke-RestMethod -Uri $messagesUri -Method Post -Body $toolsBody -ContentType "application/json" -TimeoutSec $TimeoutSec | Out-Null

    $toolsEvent = Read-SseEvent -Reader $reader -DeadlineMs ($TimeoutSec * 1000)
    $toolsResponse = $toolsEvent.data | ConvertFrom-Json
    $toolNames = @($toolsResponse.result.tools | ForEach-Object { $_.name })
    if ($toolsResponse.id -ne 2 -or -not ($toolNames -contains "inspect_design")) {
        throw "tools/list did not return expected tools."
    }
}
finally {
    $response.Close()
}

Write-Host "Fusion MCP live smoke test passed."
Write-Host "Health: $healthUri"
