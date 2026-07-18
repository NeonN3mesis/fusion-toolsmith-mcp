# Fusion Toolsmith MCP

Safety-first, diagnostic, tool-first Autodesk Fusion 360 MCP server for serious agent-assisted CAD work.

Choose Toolsmith when you want guarded workflows, runtime diagnostics, and structured Fusion tools before raw scripts. Choose a simpler Fusion MCP server when you only need a minimal bridge into Fusion and are comfortable managing safety yourself.

## Quick Start

Requirements: Windows, Autodesk Fusion 360, Python 3.9 or newer, and an MCP-capable client.

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

Verify it:

```powershell
fusion-mcp doctor
fusion-mcp test-live
```

The installed Fusion add-in folder is named `FusionMCP` for compatibility with existing local installs. The add-in is opt-in by default and does not start automatically with Fusion.

## Client Config

After the add-in is running, print client snippets:

```powershell
fusion-mcp print-client-config
```

Prefer the Streamable HTTP endpoint with bearer auth when your client supports headers. Legacy SSE/query-token support remains for older clients.

FusionMCP writes live discovery data to:

```text
C:\Users\<you>\.fusion_mcp.json
```

For Antigravity/Gemini-style config, the add-in auto-syncs:

```text
C:\Users\<you>\.gemini\config\mcp_config.json
```

## Why Toolsmith

Generic Fusion MCP servers often expose a raw script bridge. Toolsmith adds a careful CAD workflow around that bridge:

- inspect the live model before editing
- prefer structured tools before raw Fusion API scripts
- preflight model changes and exports
- isolate dangerous tools from normal profiles
- record a redacted local change journal
- diagnose stale installs, missing tools, task backlog, and auth/config issues

## What It Is Good At

- Existing-design inspection: sketches, features, parameters, projected geometry, dependencies, selection sets, assemblies, and physical properties.
- Safer model mutation: explicit modeling tools, profile-loop operations, insert/socket workflows, validation, and before/after design-state comparisons.
- Export and presentation: preflighted STL/STEP/3MF/PDF/Fusion archive exports, multibody 3MF planning, screenshots, viewport staging, and demo capture.
- Local runtime hardening: fixed port `9100`, bearer-token support, token-free `/health`, session cleanup, backpressure diagnostics, and stale-source fingerprint checks.

## Common Fix

If the server is reachable but tools are missing or old behavior remains after an update, stop and run the `FusionMCP` add-in again from Fusion 360, or restart Fusion. Fusion can keep old Python modules loaded after files are replaced.

## Documentation

- [Installation and troubleshooting](docs/installation.md)
- [Client configuration](docs/client-config.md)
- [Features and tool profiles](docs/features.md)
- [Safety model](docs/safety-model.md)
- [Development and releases](docs/development.md)
- [Mock payload examples](docs/mock-payload-examples.md)
- [Tooling roadmap](docs/tooling-roadmap.md)
- [External Fusion MCP comparison notes](docs/external-fusion-mcp-sweep.md)
- [Starter prompts](examples/prompts.md)

## Development

```powershell
python -m unittest discover -s tests
fusion-mcp dump-schemas --output dist\mcp-schemas.json
fusion-mcp package-addin
```

GitHub Actions runs the unit suite, checks the no-Fusion mock/schema surfaces, and builds the add-in ZIP on pushes and pull requests.

## License

MIT. See [LICENSE](LICENSE).
