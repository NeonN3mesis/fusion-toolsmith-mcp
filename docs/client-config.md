# Client Configuration

Fusion Toolsmith MCP runs inside Fusion 360 and exposes local MCP transports on fixed port `9100`.

Use the generated config instead of hand-writing endpoints:

```powershell
fusion-mcp print-client-config
```

## Recommended Transport

Prefer Streamable HTTP with bearer auth when your MCP client supports headers.

The live discovery file is:

```text
C:\Users\<you>\.fusion_mcp.json
```

Important discovery keys:

- `streamable_http_url`: preferred Streamable HTTP endpoint, normally `http://127.0.0.1:9100/mcp`.
- `authorization_header`: bearer auth header for clients that support request headers.
- `bearer_sse_url`: bearer-auth SSE URL for legacy SSE clients.
- `sse_url`: legacy query-token SSE URL for clients that cannot send headers.
- `transports`: advertised transport modes.
- `port` and `token`: local runtime values.

Treat the token and authorization header as sensitive local credentials.

## Antigravity/Gemini Config

FusionMCP auto-syncs Antigravity/Gemini-style config on add-in startup:

```text
C:\Users\<you>\.gemini\config\mcp_config.json
```

Manual sync is available:

```powershell
fusion-mcp sync-config
```

## PowerShell Session Header Note

Some PowerShell clients return `Mcp-Session-Id` as an array-like header value. Scalarize it before reuse:

```powershell
$sessionId = @($initializeResponse.Headers["Mcp-Session-Id"])[0]
```

## Offline Schema And Mock Server

Export the offline MCP schema bundle without launching Fusion:

```powershell
fusion-mcp dump-schemas --output dist\mcp-schemas.json
```

Run a deterministic no-Fusion mock server for client integration tests:

```powershell
fusion-mcp mock-server --port 9101
```

The mock server exposes `/health` and Streamable HTTP MCP calls at `/sse`. It advertises the same offline tool/resource/prompt surface as `dump-schemas`, but tool calls return deterministic mock data instead of touching Fusion.
