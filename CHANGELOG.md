# Changelog

## v1.1.0

FusionMCP hardening and tool-first CAD workflow release.

### Highlights

- Streamable HTTP authentication hardening for initialize and session reuse.
- Runtime diagnostics for TaskManager pending-task age, stale cleanup, and backpressure.
- Safer tool profile separation for destructive document, timeline, cleanup, and raw-script actions.
- Tool-first profile/sketch reuse workflow: `copy_profile_loop`, `offset_profile_loop`, `extrude_existing_profile`, and `create_insert_socket`.
- Insert/export validation helpers: `verify_insert_alignment`, `delete_named_experiment`, `plan_multibody_3mf_export`, `plan_multicolor_3mf_export`, and `inspect_3mf_archive`.
- Targeted 3MF export support through `export_asset(format="3mf")` with body/selection-set targeting and archive validation.
- Guarded document lifecycle helpers for throwaway fixture creation and cleanup.
- Expanded no-Fusion mock server payloads and checked-in mock examples for client integration.
- Live fixture scripts for structural tool coverage and multicolor 3MF export validation.
- CLI doctor now reports stale installed-vs-live source fingerprints and missing required live tools.

### Validation

```powershell
python -m unittest discover -s tests
fusion-mcp dump-schemas --output dist\mcp-schemas.json
fusion-mcp package-addin
```

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
