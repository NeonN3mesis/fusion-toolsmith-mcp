# Features And Tool Profiles

This page is the detailed tool inventory. The README keeps only the user-facing summary.

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

## Profiles

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
