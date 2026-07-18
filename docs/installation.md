# Installation

Fusion Toolsmith MCP installs as a local Fusion 360 add-in named `FusionMCP`.

## Requirements

- Windows
- Autodesk Fusion 360
- Python 3.9 or newer
- An MCP-capable client that supports local HTTP/SSE

## Install From GitHub

```powershell
git clone https://github.com/NeonN3mesis/fusion-toolsmith-mcp.git
cd fusion-toolsmith-mcp
python -m pip install -e .
fusion-mcp install-addin
```

`fusion-mcp install-addin` also moves the old prototype folder named `Fusion MCP Addin` to `AddInsDisabled` when it exists. That prevents the legacy add-in from starting instead of `FusionMCP` or serving an old tool list on port `9100`.

Start the add-in in Fusion 360:

```text
Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins > FusionMCP > Run
```

## Install From Release ZIP

Download `FusionMCP-addin.zip` from the latest GitHub release.

Extract the `FusionMCP` folder into:

```text
%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns
```

Start the add-in from Fusion 360:

```text
Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins > FusionMCP > Run
```

## Verify

```powershell
fusion-mcp test-live
```

For a faster readiness check:

```powershell
fusion-mcp doctor
```

`doctor` returns nonzero when the live server is reachable but the advertised tool registry is stale or missing required tools.

For deeper throwaway-fixture coverage after the live smoke test passes:

```powershell
fusion-mcp test-fixture
```

This wraps `scripts/test_fusion_mcp_inspection_fixture.ps1`, creates a controlled temporary model by default, and probes the guarded analysis, mesh, configuration, render, document-management, joint, surface, sheet-metal, drawing, electronics, simulation, CAM, and presentation contracts. Use `--keep-fixture-document` only when you intentionally want to inspect the generated Fusion document afterward.

Add `--report-path dist\fusion-live-fixture-report.json` when you want a JSON record of which live probes passed, were preflight-blocked, or returned expected unsupported API responses.

Validate a saved report without launching Fusion:

```powershell
fusion-mcp validate-fixture-report dist\fusion-live-fixture-report.json
```

The validator requires the complete probe surface emitted by the fixture, including exact analysis, motion joints, surface, sheet-metal, drawing, CAM, demo capture, and cleanup probes. Use repeated `--require-passed <probe_name>` arguments only for adapters that must be runtime-backed in the environment you are testing.

Compare multiple archived reports:

```powershell
fusion-mcp fixture-report-matrix reports\fusion-*.json --output dist\fusion-fixture-matrix.json
fusion-mcp fixture-report-matrix reports\fusion-*.json --format markdown --output dist\fusion-fixture-matrix.md
```

Or check health directly:

```powershell
Invoke-RestMethod http://127.0.0.1:9100/health | ConvertTo-Json
```

Expected health includes:

- `status: ok`
- `server: fusion-mcp`
- `task_manager_running: true`
- no exposed token

## MCP Client Config

Print client snippets:

```powershell
fusion-mcp print-client-config
```

Prefer `bearer_sse_url` plus `authorization_header` when your client supports request headers.

## Troubleshooting

### Live Smoke Still Shows Missing New Tools

Stop and run the `FusionMCP` add-in again, or restart Fusion 360. Fusion can keep Python modules loaded in memory after files are replaced, so a file refresh alone does not prove the running server is current.

### `fusion-mcp` Is Not Recognized

Use the module form:

```powershell
python -m fusion_mcp_cli --help
```

Or refresh PATH in the current shell:

```powershell
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
```

### Health Works But Tools Fail

Reload the add-in from Fusion 360. Fusion can keep old Python modules in memory after files are updated.

### Port 9100 Is Busy

Fusion Toolsmith MCP intentionally uses a fixed local port and refuses port sprawl. Stop the stale add-in/server using Fusion's Add-Ins dialog, then start `FusionMCP` again.

### TaskManager Is Not Running

Stop/start the add-in from Fusion 360. Fusion API calls must run on Fusion's main thread through the TaskManager.
