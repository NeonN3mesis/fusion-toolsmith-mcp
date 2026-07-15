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
