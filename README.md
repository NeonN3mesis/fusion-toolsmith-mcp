# Fusion Toolsmith MCP

Safety-first Autodesk Fusion 360 MCP add-in for agents that need to inspect, plan, validate, and package CAD changes without blindly running raw scripts.

Fusion Toolsmith MCP runs inside Fusion 360, exposes MCP over local HTTP/SSE on port `9100`, and writes live discovery data to `~/.fusion_mcp.json`. The add-in is opt-in by default and does not start automatically with Fusion.

The installed Fusion add-in folder is still named `FusionMCP` for compatibility with existing local installs.

## Why Toolsmith

Generic Fusion MCP servers often expose a raw script bridge. Toolsmith adds a disciplined CAD workflow around that bridge:

- Inspect the live model before editing.
- Map sketches, features, parameters, projected geometry, and downstream dependencies.
- Route agents through structured tools before raw Fusion API scripts.
- Preflight exports and model mutations.
- Keep dangerous tools separated from normal inspection/modeling workflows.
- Record a local redacted tool-call journal.

Use Toolsmith when you want an agent to behave like a careful CAD assistant, not just a Python executor.

See [docs/tooling-roadmap.md](docs/tooling-roadmap.md) for the general CAD tooling backlog.

## What It Is Good At

- Inspecting existing designs before editing: sketches, features, parameters, projected geometry, selections, dependency reports, and coordinate mapping.
- Safer model mutation: explicit operations, preflight checks, downstream-consumer warnings, before/after design-state comparisons, and validation tools.
- Export safety: preflight-gated STEP/STL/PDF workflows.
- Local runtime hardening: fixed port, bearer-token support, token-free `/health`, session TTL cleanup, single active SSE client, and automatic Antigravity config sync.

## Runtime Shape

```text
MCP client
  -> http://127.0.0.1:9100/sse
  -> FusionMCP add-in running inside Fusion 360
  -> Fusion API on Fusion's main thread
```

Discovery file:

```text
C:\Users\<you>\.fusion_mcp.json
```

The discovery file includes:

- `sse_url`: legacy query-token URL for clients that only support URL auth.
- `bearer_sse_url`: preferred token-free URL.
- `authorization_header`: preferred bearer auth header.
- `port` and `token`.

## Install From This Checkout

Detailed installation and troubleshooting notes are in [docs/installation.md](docs/installation.md).

Install the management CLI in editable mode:

```powershell
python -m pip install -e .
```

Install or refresh the Fusion add-in files:

```powershell
fusion-mcp install-addin
```

If the old prototype add-in folder `Fusion MCP Addin` is present, the installer moves it to `AddInsDisabled` so it cannot keep claiming port `9100` or serve stale tools. Use `--keep-legacy-addin` only if you are intentionally testing that older add-in.

Build a distributable add-in ZIP:

```powershell
fusion-mcp package-addin
```

The package is written to:

```text
dist\FusionMCP-addin.zip
```

Then start or restart the `FusionMCP` add-in from Fusion 360:

```text
Utilities > Add-Ins > Scripts and Add-Ins > Add-Ins > FusionMCP > Run
```

The manifest keeps `runOnStartup` set to `false`. Start the add-in only when you need it.

## Verify

Run the live smoke test:

```powershell
fusion-mcp test-live
```

Or use the PowerShell script directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_fusion_mcp_live.ps1
```

Check runtime health:

```powershell
Invoke-RestMethod http://127.0.0.1:9100/health | ConvertTo-Json
```

Expected health output includes `discovery`, `active_sessions`, `active_http_sessions`, `task_manager_running`, and `pending_tasks`. It should not include a token or `sse_url`.

## Client Config

Print both legacy and bearer-style client snippets:

```powershell
fusion-mcp print-client-config
```

For Antigravity/Gemini-style config, FusionMCP auto-syncs this file on add-in startup:

```text
C:\Users\<you>\.gemini\config\mcp_config.json
```

Manual sync is still available:

```powershell
fusion-mcp sync-config
```

## Tool Profiles

Machine-readable profiles are available through both the CLI and MCP resource layer:

```powershell
fusion-mcp list-profiles
```

```text
fusion://agent/tool-profiles
```

Use these mental profiles when exposing tools to agents or documenting workflows:

- `core`: readiness, runtime diagnostics, workflow routing, and change-journal tools.
- `inspection`: design snapshots, printability checks, sketch/feature/parameter/dependency inspection, selection queries, body face/edge targeting, assembly reference/joint inspection, material/appearance reporting, timeline/tree inspection, and mutation preflight.
- `modeling`: structured sketches, constraints, projection, extrude/revolve/loft/sweep/fillet/chamfer/shell, offset face, combine, primitives, component-targeted construction geometry, rigid point-to-point joints, rounded cuts/pockets, hole patterns, mirror/pattern, appearance discovery/application, mesh conversion, and component organization.
- `parameters`: user/model parameter reads and edits, parameterization planning, sketch dimension editing, and parameter CSV import/export.
- `export`: preflight-gated STEP/STL/PDF export plus still-frame capture helpers.
- `presentation`: viewport camera, visibility staging, user prompts, screenshots, and `capture_demo_sequence` still-frame sequences.
- `document`: document listing, assembly tree/reference reads, timeline reads, timeline marker movement, and feature recipe cloning.
- `docs`: local Fusion API, workflow, and best-practices lookup.
- `dangerous`: raw scripting, clear journal, document activation/revert, undo, delete, and suppress tools. Use only after structured tools are insufficient.

## Feature Matrix

| Area | What Toolsmith exposes |
| --- | --- |
| Runtime safety | `doctor`, runtime diagnostics, fixed-port health, bearer auth, change journal, structured-tool routing |
| Inspection | design snapshots, sketch/feature/dependency inspection, body face/edge targeting, assembly origin/reference/joint reports, material/appearance reports, mesh-aware `inspect_printability` warnings |
| Safe modeling | typed sketching, guarded sketch constraint creation/deletion, extrudes, revolves, lofts, sweeps, token-targeted fillets/chamfers/shells, `offset_face_or_press_pull`, holes, pockets, mirrors, patterns, construction geometry, rigid point-to-point joints |
| Parameters | user/model parameter reads, safe edits, parameterization planning, dimension editing, CSV import/export |
| Export and presentation | preflighted STL/STEP/PDF export, screenshots, staged visibility, still-frame demo sequences |
| Dangerous tools | raw scripts, undo/revert, timeline deletion/suppression, and document activation are isolated from normal workflows |

## Development

Run the unit suite:

```powershell
python -m unittest discover -s tests
```

Run the structural live fixture when FusionMCP is loaded and you want deeper end-to-end coverage:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_fusion_mcp_inspection_fixture.ps1
```

Useful starter prompts are in [examples/prompts.md](examples/prompts.md).

Use [docs/demo-script.md](docs/demo-script.md) to record the short demo GIF/video for the README.

## CI And Releases

GitHub Actions runs the unit suite and builds the add-in ZIP on pushes and pull requests.

To publish a GitHub release with the packaged add-in attached:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

## License

MIT. See [LICENSE](LICENSE).

## Change Journal

FusionMCP writes local JSONL tool-call audit entries to:

```text
C:\Users\<you>\.fusion_mcp\journal.jsonl
```

Read it through MCP:

```text
fusion://runtime/change-journal
```

Or call:

```text
get_change_journal
clear_change_journal
```

The journal redacts tokens, authorization headers, raw scripts, and long string arguments.

## Local Docs

FusionMCP exposes a local Fusion API and best-practices index:

```text
fusion://docs/fusion-api
```

Search it with:

```text
search_local_fusion_docs
```

This is an offline companion to official Autodesk docs and is meant for quick planning before writing raw Fusion API scripts.

## Safety Notes

- Fusion API calls must execute on Fusion's main thread through `TaskManager`.
- `run_fusion_script` is intentionally a last-resort tool and requires intent/gap fields.
- Query-token auth remains for legacy clients, but bearer auth is preferred.
- If behavior does not change after editing files, reload the add-in or restart Fusion; Fusion may still hold the old Python modules in memory.
