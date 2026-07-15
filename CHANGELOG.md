# Changelog

## v1.0.0

Initial public release of Fusion Toolsmith MCP.

### Highlights

- Safety-first Fusion 360 MCP add-in with opt-in startup behavior.
- Fixed local SSE endpoint on port `9100`.
- Bearer-token support with token-free `/health`.
- Structured inspection, modeling, parameter, export, documentation, and runtime tools.
- Tool profiles for safer agent routing.
- Redacted local tool-call journal.
- Local Fusion API documentation search companion.
- CLI helpers for install, config sync, live testing, profile listing, offline schema export, no-Fusion mock serving, and package builds.
- GitHub Actions CI and release ZIP packaging.

### Install

```powershell
git clone https://github.com/NeonN3mesis/fusion-toolsmith-mcp.git
cd fusion-toolsmith-mcp
python -m pip install -e .
fusion-mcp install-addin
fusion-mcp test-live
```

Or download `FusionMCP-addin.zip` from the GitHub release and extract the `FusionMCP` folder into Fusion 360's AddIns directory.
