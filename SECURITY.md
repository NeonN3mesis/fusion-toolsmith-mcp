# Security Policy

Fusion Toolsmith MCP is a local Fusion 360 add-in. It exposes a local HTTP/SSE MCP endpoint for clients running on the same machine.

## Supported Use

- Run the server only on trusted local machines.
- Keep the add-in opt-in. The manifest should keep `runOnStartup` set to `false`.
- Prefer bearer auth from `~/.fusion_mcp.json` over query-token URLs when the client supports custom headers.
- Treat `run_fusion_script` as a last-resort tool.

## Reporting Issues

Please open a private security advisory on GitHub if the issue could expose credentials, bypass local auth, trigger unintended model mutation, or run arbitrary code without explicit user intent.

For normal bugs, open a standard GitHub issue with:

- Fusion 360 version
- Windows version
- MCP client
- `fusion-mcp test-live` result
- relevant redacted logs or health output
