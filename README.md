# Fusion Toolsmith MCP

Safety-first, diagnostic, tool-first Autodesk Fusion 360 MCP server for serious agent-assisted CAD work. Choose Toolsmith when you want guarded workflows, runtime diagnostics, and structured Fusion tools before raw scripts; choose a simpler server when you only need a minimal bridge into Fusion.

Fusion Toolsmith MCP runs inside Fusion 360, exposes MCP over local HTTP on port `9100` with Streamable HTTP and legacy HTTP/SSE compatibility, and writes live discovery data to `~/.fusion_mcp.json`. The add-in is opt-in by default and does not start automatically with Fusion.

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

See [docs/external-fusion-mcp-sweep.md](docs/external-fusion-mcp-sweep.md) for the public Fusion MCP comparison notes that informed Toolsmith's adoption layer.

## What It Is Good At

- Inspecting existing designs before editing: sketches, features, parameters, projected geometry, selections, dependency reports, and coordinate mapping.
- Safer model mutation: explicit operations, preflight checks, downstream-consumer warnings, before/after design-state comparisons, and validation tools.
- Export safety: preflight-gated STEP/STL/3MF/PDF workflows.
- Local runtime hardening: fixed port, bearer-token support, token-free `/health`, session TTL cleanup, single active SSE client, and automatic Antigravity config sync.
- Machine-readable adoption metadata: initialize instructions, MCP tool/resource annotations, `fusion://agent/server-capabilities`, `fusion://agent/tool-profiles`, and `fusion://agent/tool-first-workflow`.

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
- `bearer_sse_url`: bearer-auth SSE URL for legacy SSE clients.
- `streamable_http_url`: preferred bearer-auth Streamable HTTP endpoint (`/mcp`).
- `authorization_header`: preferred bearer auth header.
- `transports`: advertised transport modes.
- `port` and `token`.

PowerShell clients should scalarize the returned `Mcp-Session-Id` before reusing it:

```powershell
$sessionId = @($initializeResponse.Headers["Mcp-Session-Id"])[0]
```

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

`fusion-mcp doctor` also checks the advertised tool registry and compares the live add-in source fingerprint with the current checkout. If required tools are missing or Fusion is still running older loaded modules after an install, it returns nonzero and recommends reloading the Fusion add-in.

Or use the PowerShell script directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_fusion_mcp_live.ps1
```

Check runtime health:

```powershell
Invoke-RestMethod http://127.0.0.1:9100/health | ConvertTo-Json
```

Expected health output includes `discovery`, `transports`, `active_sessions`, `active_http_sessions`, `task_manager_running`, and `pending_tasks`. It should not include a token or `sse_url`.

## Client Config

Print both legacy and bearer-style client snippets:

```powershell
fusion-mcp print-client-config
```

Export the offline MCP schema bundle without launching Fusion:

```powershell
fusion-mcp dump-schemas --output dist\mcp-schemas.json
```

Run a deterministic no-Fusion mock server for client integration tests:

```powershell
fusion-mcp mock-server --port 9101
```

The mock server exposes `/health` and Streamable HTTP MCP calls at `/sse`. It advertises the same offline tool/resource/prompt surface as `dump-schemas`, but tool calls return deterministic mock data instead of touching Fusion.

Stable representative mock payloads are documented in [docs/mock-payload-examples.md](docs/mock-payload-examples.md).

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

Server adoption metadata is available as JSON:

```text
fusion://agent/server-capabilities
```

That resource summarizes supported transports, discovery keys, initialize instructions, safety gates, tool/resource annotation coverage, profiles, prompts, and capability counts so clients can route without scraping README text.

Use these mental profiles when exposing tools to agents or documenting workflows:

- `core`: readiness, runtime diagnostics, workflow routing, and change-journal tools.
- `inspection`: design snapshots, physical-property, printability, `inspect_selection_sets`, `inspect_mesh_bodies`, `plan_mesh_conversion`, `inspect_design_configurations`, `plan_design_variant`, `inspect_render_workspace`, `plan_render_output`, `inspect_document_management_state`, `plan_document_management_action`, `inspect_electronics_workspace`, `plan_pcb_enclosure_fit`, `inspect_simulation_workspace`, `list_simulation_studies`, and `plan_simulation_study` checks, sketch/feature/parameter/dependency inspection, selection queries, body face/edge targeting, assembly reference/joint inspection, material/appearance reporting, timeline/tree inspection, and mutation preflight.
- `modeling`: structured sketches, constraints, projection, profile-loop copy/offset, insert plate/socket creation, hardened existing-profile extrusion, extrude/revolve/loft/sweep/fillet/chamfer/shell, offset face, combine, primitives, component-targeted construction geometry, rigid point-to-point joints, rounded cuts/pockets, hole patterns, mirror/pattern, appearance discovery/application, `convert_mesh_to_solid`, `repair_mesh_body`, `reduce_mesh_body`, `remesh_body`, and component organization.
- `parameters`: user/model parameter reads and edits, variant-planned parameter-set application, parameterization planning, sketch dimension editing, and parameter CSV import/export.
- `export`: preflight-gated STEP/STL/3MF/PDF export plus still-frame capture helpers.
- `presentation`: viewport camera, visibility staging, user prompts, screenshots, `render_viewport_output`, and `capture_demo_sequence` still-frame sequences.
- `document`: document listing, guarded new unsaved design-document creation, `export_document_copy` local archive export-copy, assembly tree/reference reads, timeline reads, timeline marker movement, and feature recipe cloning.
- `docs`: local Fusion API, workflow, and best-practices lookup.
- `dangerous`: raw scripting, clear journal, document activation/close/revert, undo, named-experiment cleanup, delete, and suppress tools. Use only after structured tools are insufficient.

## Feature Matrix

| Area | What Toolsmith exposes |
| --- | --- |
| Runtime safety | `doctor`, initialize instructions, offline schema export, runtime diagnostics, fixed-port health, Streamable HTTP/SSE metadata, bearer auth, MCP read-only/destructive/idempotent tool annotations, resource ranking annotations, change journal, structured-tool routing |
| Inspection | design snapshots, sketch/feature/dependency inspection, named selection-set contents via `inspect_selection_sets`, body face/edge targeting, insert/socket alignment checks via `verify_insert_alignment`, assembly origin/reference/joint reports, physical-property reports, material/appearance reports, mesh-body discovery and conversion preflight, configuration/variant planning, render output planning, document-management inspection/planning, electronics/PCB enclosure-fit planning, simulation workspace/study planning, mesh-aware `inspect_printability` warnings |
| Safe modeling | typed sketching, guarded sketch constraint creation/deletion, selected profile-loop copy/offset, insert plate/socket workflow, existing-profile extrusion diagnostics, extrudes, revolves, lofts, sweeps, token-targeted fillets/chamfers/shells, `offset_face_or_press_pull`, holes, pockets, mirrors, patterns, construction geometry, rigid point-to-point joints, guarded mesh conversion/repair/reduction/remeshing |
| Parameters | user/model parameter reads, safe edits, variant-planned parameter-set application, parameterization planning, dimension editing, CSV import/export |
| Export and presentation | preflighted STL/STEP/3MF/PDF/Fusion archive export with `export_document_copy`, targeted multibody 3MF exports through `plan_multibody_3mf_export`, color-aware planning through `plan_multicolor_3mf_export`, insert/socket/body-contact validation through `verify_insert_alignment`, standalone `inspect_3mf_archive` validation, and `export_asset`, screenshots, `render_viewport_output`, staged visibility, still-frame demo sequences |
| MCP prompts | workflow prompts for tool-first routing, export readiness, threaded fasteners, sheet-metal planning, printability review, and physical-property review |
| Dangerous tools | raw scripts, guarded undo/revert, named experimental cleanup, timeline deletion/suppression, and document activation/close are isolated from normal workflows |

## Development

Run the unit suite:

```powershell
python -m unittest discover -s tests
```

Run the structural live fixture when FusionMCP is loaded and you want deeper end-to-end coverage:

```powershell
fusion-mcp test-fixture
```

Run the guarded multicolor 3MF fixture after reloading the add-in when validating slicer/export workflows:

```powershell
fusion-mcp test-3mf-fixture
```

To keep a machine-readable validation artifact:

```powershell
fusion-mcp test-fixture --report-path dist\fusion-live-fixture-report.json
fusion-mcp validate-fixture-report dist\fusion-live-fixture-report.json
```

Compare archived reports from multiple Fusion versions or machines:

```powershell
fusion-mcp fixture-report-matrix reports\fusion-*.json --output dist\fusion-fixture-matrix.json
fusion-mcp fixture-report-matrix reports\fusion-*.json --format markdown --output dist\fusion-fixture-matrix.md
```

Or use the PowerShell script directly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_fusion_mcp_inspection_fixture.ps1
```

Useful starter prompts are in [examples/prompts.md](examples/prompts.md).

Use [docs/demo-script.md](docs/demo-script.md) to record the short demo GIF/video for the README.

## CI And Releases

GitHub Actions runs the unit suite, checks the no-Fusion mock/schema surfaces, and builds the add-in ZIP on pushes and pull requests.

To publish a GitHub release with the packaged add-in attached:

```powershell
git tag v1.1.0
git push origin v1.1.0
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
- Query-token auth remains for legacy SSE clients, but bearer auth is required for Streamable HTTP.
- If behavior does not change after editing files, reload the add-in or restart Fusion; Fusion may still hold the old Python modules in memory.
