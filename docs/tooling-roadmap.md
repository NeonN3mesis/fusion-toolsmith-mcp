# Tooling Roadmap

This is the general CAD tooling backlog for Fusion Toolsmith MCP. Keep these tools domain-neutral: no product-specific dimensions, names, or workflows.

## Suggested But Not Yet Done

- [ ] Reload Fusion after the latest install and run live smoke coverage for the new profile-loop, insert-socket, cleanup, document, and 3MF export tools.
  - Stop/start the `FusionMCP` add-in from Fusion 360 Utilities > Add-Ins, or restart Fusion, so the live process loads the installed Python modules.
  - Run `python -m fusion_mcp_cli doctor`, `scripts/test_fusion_mcp_live.ps1`, `scripts/test_fusion_mcp_inspection_fixture.ps1`, and `scripts/test_fusion_mcp_3mf_fixture.ps1`.

- [ ] Add live fixture validation for `create_insert_socket`.
  - Build a throwaway source sketch and cabinet body, call `create_insert_socket`, then validate the resulting plate body, socket cut feature, cutter cleanup behavior, and timeline health.
  - Include failure-path validation for alignment blockers and partial-attempt cleanup through `delete_named_experiment`.

- [ ] Add exact BRep contact/alignment validation for insert workflows.
  - `verify_insert_alignment` is currently broad-phase bounding-box validation.
  - Add exact contact/interference checks only after a reliable Fusion TemporaryBRepManager/measure-manager path is proven against throwaway fixtures.

- [ ] Add stronger cleanup coverage for generated experiments.
  - Validate `delete_named_experiment` live against named temporary sketches, bodies, timeline features, combine features, and cutter bodies.
  - Keep dry-run as the default and keep short-prefix deletion guarded.

- [ ] Add selection-set to export-plan regression coverage for real Fusion selection sets.
  - Verify `inspect_selection_sets`, `plan_multibody_3mf_export`, `plan_multicolor_3mf_export`, and `export_asset(format="3mf")` on real named selection sets after add-in reload.
  - Confirm non-body members are reported and body counts match slicer-colorable archive structure.

- [ ] Add exact-analysis fixture coverage.
  - Validate `exact_interference_check` and `exact_clearance_check` against known two-body fixtures and compare them with broad-phase reports.
  - Keep exact tools returning structured unsupported results where Fusion does not expose stable APIs.

- [ ] Add live fixture coverage for currently guarded but runtime-dependent mutators.
  - Mesh conversion/repair/reduce/remesh.
  - Sheet-metal flange/bend/unfold/refold/flat-pattern export.
  - Surface patch/stitch/thicken/trim/extend/ruled-surface.
  - Drawing view/dimension/callout/parts-list/revision-table.
  - Motion joints and joint limits.
  - CAM setup/operation/toolpath/post-processing.

- [ ] Add future high-level mutators only behind existing planner contracts.
  - Simulation study creation, load/constraint creation, meshing, solving, and result export behind `plan_simulation_study`.
  - Electronics/PCB export or synchronization helpers behind `plan_pcb_enclosure_fit`.
  - Configuration row creation/activation and configuration-specific parameter overrides behind `plan_design_variant`.
  - Document save/save-as/version/open/relink helpers behind `plan_document_management_action`.
  - Photoreal render, turntable, or presentation export helpers behind `plan_render_output`.

- [ ] Expand mock payload examples as each new live-backed mutator is added.
  - Keep mock responses deterministic, schema-aligned, and explicit that no Fusion execution occurred.
  - Add checked-in examples for client docs and CI smoke tests when new tool families land.

## Next Tool Gaps

- [ ] Mesh and reverse-engineering workflows
  - Validate guarded mesh conversion/repair/reduction/remeshing adapters against live throwaway imported-mesh fixtures.
  - `convert_mesh_to_solid` now enforces `plan_mesh_conversion` semantics before mutation, including explicit target, quality-loss acknowledgement, reason, preflight result, and state comparison.
  - `repair_mesh_body`, `reduce_mesh_body`, and `remesh_body` now enforce `plan_mesh_conversion` semantics and return structured unsupported responses when Fusion lacks compatible writable mesh feature collections.
  - Tests: live imported-mesh fixture coverage, unsupported runtime handling, conversion preflight blockers, and state comparison for any mutating conversion.
  - Plan:
    1. Probe Fusion's mesh-to-BRep, repair, reduce, and remesh API paths with throwaway imported mesh fixtures.
    2. Validate `convert_mesh_to_solid` live against a throwaway imported-mesh fixture now that unit tests enforce `plan_mesh_conversion` gating.
    3. Validate `repair_mesh_body`, `reduce_mesh_body`, and `remesh_body` live against throwaway imported-mesh fixtures and refine runtime-specific adapters where Fusion exposes compatible feature paths.

- [ ] Simulation and study workflows
  - Validate guarded study creation, load/constraint creation, meshing, solving, and result export against live throwaway Simulation fixtures.
  - Keep load, constraint, material, contact, mesh, solve, and result-export operations separate so agents cannot accidentally run expensive or misleading analysis.
  - Tests: live Simulation fixture coverage, explicit solve approval, unsupported Simulation API handling, and no accidental solve/export in unit tests.
  - Plan:
    1. Probe Fusion's Simulation study, load, constraint, mesh, solve, and result export API paths against a throwaway study fixture.
    2. Use `plan_simulation_study` as the required preflight contract before adding any Simulation mutator or solve/export tool.
    3. Add guarded tools for study creation, load/constraint creation, meshing, solving, and result export only after live probes confirm stable Simulation API adapters.

- [ ] Electronics and PCB workflows
  - Validate guarded electronics export/synchronization helpers against live throwaway electronics documents.
  - Keep board-outline, component, net, enclosure-fit, and export workflows separate from mechanical modeling tools.
  - Tests: live electronics fixture coverage, explicit export paths, and unsupported API handling on mechanical-only installs.
  - Plan:
    1. Probe Fusion's electronics export, board synchronization, and linked mechanical-reference API paths against throwaway electronics documents.
    2. Use `plan_pcb_enclosure_fit` as the required preflight contract before adding any mechanical/electronics bridge action.
    3. Add guarded export or synchronization helpers only after API probes show reliable board/component access across supported Fusion versions.

- [ ] Configuration and design-variant workflows
  - Validate guarded configuration creation/activation and parameter-set mutation against live throwaway configuration fixtures.
  - `apply_design_variant_parameters` now applies existing user-parameter sets only after `plan_design_variant` approves explicit variant name, parameter changes, affected bodies/features, reason, and user approval.
  - Keep configuration-row creation/activation separate from ordinary parameter edits, and require explicit naming plus rollback expectations when those adapters are added.
  - Tests: live configuration fixture coverage, parameter-set diffing, unsupported configuration API handling, and state comparison after any mutation.
  - Plan:
    1. Probe Fusion's configuration creation, activation, row, and parameter override APIs against a throwaway configuration fixture.
    2. Validate `apply_design_variant_parameters` live against a throwaway parameter/configuration fixture now that unit tests enforce planner gating.
    3. Add guarded tools for creating/activating configuration rows or applying configuration-specific parameter overrides only after live probes confirm stable configuration APIs and state comparison can verify the result.

- [ ] Render, appearance, and presentation workflows
  - Validate guarded render, turntable, or presentation-export helpers against live throwaway render fixtures.
  - `render_viewport_output` now captures a local viewport still only after `plan_render_output` approves explicit camera/named view, absolute path, resolution, reason, and user approval; it verifies a non-empty output file.
  - Keep rendering/export operations path-explicit and avoid promising photorealism or cloud rendering unless Fusion exposes a reliable local surface.
  - Tests: live render fixture coverage, output-file existence checks, nonblank artifact checks, and unsupported Render API handling.
  - Plan:
    1. Probe Fusion's local render, turntable, and presentation export APIs against throwaway render fixtures.
    2. Validate `render_viewport_output` live against a throwaway render fixture now that unit tests enforce planner gating and nonblank output checks.
    3. Add guarded photoreal render, turntable, or presentation-export helpers only after live probes verify runtime API support, output creation, and nonblank artifact checks.

- [ ] Data-management, version, and collaboration workflows
  - Validate guarded save, upload, version promotion, reference relink, and cloud actions against throwaway data-management fixtures.
  - `export_document_copy` now exports the active document to an explicit local `.f3d`/`.f3z` archive path only after `plan_document_management_action` approves an `export_copy` plan.
  - Keep save, upload, version promotion, reference relink, and cloud actions approval-gated because they affect user data outside the active model.
  - Tests: live document-management fixture coverage, cloud API fallback, explicit approval requirements, and no accidental save/upload in unit tests.
  - Plan:
    1. Probe Fusion's save, save-as, version, open data-file, export-copy, and reference relink API paths against throwaway documents/projects.
    2. Validate `export_document_copy` live against a throwaway document fixture now that unit tests enforce planner gating, active-document scope, archive API fallback, and non-empty output checks.
    3. Add guarded save/version/reference tools only where Fusion exposes reliable APIs, with dry-run/preflight modes and live tests that avoid changing real cloud projects.

- [ ] Analysis and clearance workflows
  - Validate `exact_interference_check` and `exact_clearance_check` against live throwaway two-body fixtures and refine runtime-specific TemporaryBRepManager/measure-manager adapters where needed.
  - Keep broad-phase tools honest about bounding-box limits; exact tools must keep returning structured unsupported/error payloads when candidate APIs are unavailable.
  - Tests: live exact-analysis fixture coverage behind a throwaway two-body model once candidate APIs are verified.
  - Plan:
    1. Use `inspect_analysis_capabilities` to identify candidate exact interference/minimum-distance APIs, then probe them in a throwaway fixture and compare against the existing broad-phase reports.
    2. Keep exact interference/minimum-distance work behind a capability probe; if the API path is unreliable, expose a structured unsupported result instead of approximating beyond the current broad-phase tools.
    3. Add live smoke coverage only after the exact-analysis API shape is verified.

- [ ] Sheet metal workflows
  - Validate `create_flange`, `create_bend`, `unfold_sheet_metal`, and `refold_sheet_metal` against live throwaway sheet-metal fixtures and refine runtime-specific Fusion API adapters where needed.
  - Tests: live execution for each mutating tool, no guessed sheet-metal rule/material behavior, unsupported API handling across Fusion versions, and flat-pattern output validation after unfold/refold.
  - Plan:
    1. Probe the Fusion API for reliable flange, bend, unfold, refold, and flat-pattern export paths against a throwaway sheet-metal fixture.
    2. Keep `export_flat_pattern` guarded by `preflight_flat_pattern`; expand only after live API probes prove a broader flat-pattern surface is reliable.
    3. Use `plan_sheet_metal_workflow` as the required preflight contract before adding creation/unfold/refold tools.

- [ ] Richer assembly joint workflows
  - Add live fixture coverage that creates predictable construction references, then verifies each joint's before/after state and inspection output.
  - Use `plan_joint_limits` before `set_joint_limits`; keep broader limit tooling behind live fixture validation for every supported motion type.
  - Tests: live fixture creation for each joint type and unsupported runtime/API fallback behavior.
  - Plan:
    1. Extend the inspection fixture to create named construction references for all motion-joint variants.
    2. Run each joint creation tool against the fixture and validate `get_assembly_joints` output.
    3. Expand limit tooling only after `plan_joint_limits` passes and the live API shape is verified for every supported motion type.

- [ ] Surface modeling and repair workflows
  - Validate `patch_surface`, `stitch_surfaces`, `thicken_surface`, `trim_surface`, `extend_surface`, and `create_ruled_surface` against live throwaway surface fixtures and refine runtime-specific Fusion API adapters where needed.
  - Keep `plan_surface_repair` as the gate for repair with explicit target names/entity tokens and reason fields; keep surface-to-solid conversion separate from mesh conversion.
  - Tests: live fixture execution for each mutating tool, unsupported API handling across Fusion versions, and state comparison for each operation.
  - Plan:
    1. Probe Fusion's patch/stitch/thicken/trim/extend/ruled-surface API paths with throwaway surface fixtures.
    2. Keep unsupported results for runtimes that do not expose compatible surface feature collections instead of falling back to raw scripts.
    3. Keep repair tools separate from mesh conversion and verify each mutator with state comparison plus surface fixture tests.

- [ ] Drawing and documentation workflows
  - Validate `add_drawing_view`, `add_drawing_dimension`, `add_drawing_callout`, `add_parts_list`, and `add_revision_table` against live throwaway drawing fixtures and refine runtime-specific Drawing API adapters where needed.
  - Keep exports preflight-gated and require explicit output paths; do not infer standards beyond a documented default.
  - Tests: live view creation execution, PDF export path validation, callout/BOM/dimension helpers, revision table placement, and unsupported drawing API handling across Fusion versions.
  - Plan:
    1. Use `plan_drawing_views` to normalize explicit drawing view and sheet metadata with documented defaults for standard, sheet size, and orientation before mutation.
    2. Layer dimensions, callouts, BOM/parts list, revision tables, and PDF export as separate tools with path validation and unsupported-API fallbacks.
    3. Keep drawing creation/edit tools separate from read-only inspection and preflight tooling.

- [ ] CAM/manufacturing workflows
  - Validate `create_manufacturing_setup`, `create_manufacturing_operation`, `generate_toolpaths`, and `post_process` against live throwaway manufacturing fixtures and refine runtime-specific CAM API adapters where needed.
  - Keep setup/operation/toolpath/post-processing workflows behind `plan_manufacturing_operation`; never infer production parameters.
  - Tests: live setup/operation creation, explicit setup/operation input validation, gated toolpath/post-processing behavior, and no accidental production output.
  - Plan:
    1. Probe Fusion's setup, operation, toolpath, and post-processing APIs against a throwaway manufacturing fixture.
    2. Use `plan_manufacturing_operation` as the required preflight contract before adding setup and operation creation.
    3. Gate toolpath generation and post-processing behind preflight plus explicit approval fields, then add mock responses and live tests that never run real production output accidentally.

- [ ] Mock/simulation mode expansion
  - Extend `fusion-mcp mock-server` responses for future high-value mutating tools as new tool families are added.
  - Keep responses deterministic, schema-aligned, and honest that no Fusion execution occurred.
  - Tests: mock responses for newly added tools, schema parity, and stable example payloads for docs.
  - Plan:
    1. For every new tool family, add mock responses in the same change that registers schemas and profiles.
    2. Add parity tests that fail when a live tool is registered without a deterministic mock response or when mock payloads drift from expected schema fields.
    3. Maintain a small set of stable example payloads for client docs and CI smoke checks instead of making the mock server imitate Fusion internals.

## Implemented

- `create_offset_plane`
  - Create a named construction plane offset from a standard plane, named construction plane, or selected planar face.

- `create_hole_pattern`
  - General hole-pattern cuts for explicit, rectangular, and circular point layouts.
  - Supports through, blind, counterbore, and true conical countersink cuts with structured result metadata.

- `revolve_feature`
  - Create revolve features from named sketch profiles and explicit standard, named, or selected axes.
  - Requires an explicit operation and returns angle, result bodies, participants, inspection, and before/after design-state comparison.

- `loft_feature`
  - Create solid loft features from ordered named sketch profiles.
  - Requires an explicit operation and returns section order, result bodies, participants, warnings, inspection, and before/after design-state comparison.

- `sweep_feature`
  - Create solid sweep features from a named sketch profile and an explicit indexed curve in a named path sketch.
  - Requires an explicit operation and returns path targeting, result bodies, participants, warnings, inspection, and before/after design-state comparison.

- `get_assembly_references`
  - Read-only report of component origins, standard axes/planes, construction axes/planes/points, and occurrence transforms.
  - Complements component-targeted `create_construction_point`, `create_construction_axis`, and `create_offset_plane` for repeatable placement references.

- Assembly joints
  - `get_assembly_joints` reports existing joints and as-built joints without mutating the model.
  - `create_rigid_joint` creates a narrow point-to-point rigid joint from named construction/sketch points or point entity tokens.
  - Revolute, slider, cylindrical, pin-slot, planar, and ball joints are exposed as explicit motion-joint tools rather than inferred behavior on the rigid-joint path.

- Material and appearance workflows
  - `list_appearances` discovers active-design and material-library appearances with optional filtering.
  - `inspect_body_style` reports body appearance, material, and physical material assignments across components, including exact body entity token filters for duplicate-name workflows.
  - `apply_appearance` applies a named or partial-match appearance to exact body names or body entity tokens and returns structured before/after style plus design-state comparison.

- Stronger sketch constraint editing
  - `add_sketch_constraint` supports common geometric constraints including midpoint, coincident, parallel, perpendicular, tangent, equal, concentric, fixed, horizontal, and vertical variants.
  - `delete_sketch_constraint` removes an inspected geometric constraint by index with a required reason, deletability guard, and before/after design-state comparison.

- `mirror_features_or_bodies`
  - Mirror named bodies, named timeline features, or selected entities across standard planes, named construction planes, or selected planar faces.
  - Returns created names and before/after design-state comparison.

- `pattern_feature`
  - Rectangular and circular patterning for named bodies, named timeline features, or selected entities.
  - Supports counts, spacing/angle, axes, optional second rectangular direction, and before/after design-state comparison.

- `create_rounded_pocket`
  - Cut a shallow rounded-rectangle recess into a named target body.
  - Supports depth, corner radius, standard or selected plane/face placement, cut direction, and state comparison.

- `get_body_faces`
  - Return indexed face metadata for a named body so agents can target open faces safely.

- `shell_body`
  - Shell a named body with explicit wall thickness and optional open face indices.
  - Includes before/after state comparison and uses `get_body_faces` for safe targeting.

- `offset_face_or_press_pull`
  - Create a controlled Offset Face feature on explicit body face indices or selected BRep faces.
  - Includes before/after state comparison and warnings that it covers face-offset behavior only, not arbitrary Press Pull edge/profile routing.

- Entity-token targeting for mutating tools
  - `fillet_feature` and `chamfer_feature` accept `edge_entity_tokens` from `get_body_edges`.
  - `shell_body` accepts `body_entity_token` and `open_face_entity_tokens` from `get_body_faces`.
  - `offset_face_or_press_pull` accepts `body_entity_token` and `face_entity_tokens` for exact face targeting.
  - Existing name/index targeting remains supported for compatibility.

- `create_construction_point`
  - Create named construction points from coordinates, named point entities, or selected point-like geometry.

- `create_construction_axis`
  - Create named construction axes from two named/coordinate-backed points or selected line-like geometry.
  - Useful for mirrors, revolves, circular patterns, and repeatable feature placement.

- `inspect_printability`
  - General read-only FDM sanity report: bounding boxes, thin/tiny/narrow feature candidates, small rounded-hole candidates, risky downward-face/overhang candidates, and optional Fusion triangle-mesh analysis.
  - Mesh-aware checks report triangle counts, approximate mesh surface area, tiny mesh edge candidates, and overhang triangle candidates when Fusion exposes mesh data.
  - Reports warnings and limitations only; it does not mutate geometry or claim to replace slicer preview/simulation.

- `inspect_selection_sets`
  - Reads named Fusion selection sets and their contents so export workflows can target curated body groups without relying on the active UI selection.

- `plan_multibody_3mf_export`
  - Read-only export preflight for targeted multibody/color 3MF exports.
  - Resolves body names, body entity tokens, and named selection-set contents.
  - Reports missing/ambiguous targets, ignored non-body selection-set members, expected body-count mismatches, overwrite policy, and generic export preflight blockers.

- `plan_multicolor_3mf_export`
  - Read-only color-aware planner that maps body names/entity tokens to intended appearances before 3MF export.
  - Verifies appearance availability, duplicate/missing assignment targets, overwrite policy, target body count, and generic export preflight before any appearance or export mutation.
  - Returns exact `apply_appearance` arguments followed by the `export_asset(format="3mf")` path agents should use.

- `verify_insert_alignment`
  - Read-only pre-export guard for removable plates, matching socket/pocket/cutter bodies, and raised logo bodies.
  - Uses axis-aligned bounding boxes to report footprint overlap, plate/socket depth equality for flush inserts, expected plate thickness mismatch, logo separation from the plate, and likely mirrored/separated geometry.
  - It is intentionally broad-phase only; exact BRep contact validation remains separate future work.

- `inspect_3mf_archive`
  - Read-only inspection for an existing `.3mf` file independent of the active Fusion document.
  - Reports package/model validity, object/build/component counts, broken references, metadata, the conservative `slicerColorabilityLikely` signal, and a `printReadiness` verdict for multibody color workflows.

- Mesh and reverse-engineering read-only workflows
  - `inspect_mesh_bodies` reports mesh body names, component/occurrence context, entity tokens, visibility, bounding boxes, size estimates, and triangle/node counts when Fusion exposes mesh data.
  - `plan_mesh_conversion` validates explicit mesh target, conversion intent, operation, optional tolerance/detail settings, quality-loss acknowledgement, and reason before any conversion or repair mutation.
  - Live fixture validation covers read-only mesh discovery and missing-target conversion preflight without requiring a real imported mesh document.

- Mesh and reverse-engineering guarded mutation workflows
  - `convert_mesh_to_solid`, `repair_mesh_body`, `reduce_mesh_body`, and `remesh_body` run only after `plan_mesh_conversion` passes for the matching conversion intent.
  - Repair/reduce/remesh tools verify exact mesh targets and return structured unsupported responses when Fusion lacks compatible writable mesh feature collections or input builders.
  - Tests cover preflight blockers, unsupported runtime handling, writable fake collection execution, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Configuration and design-variant read-only workflows
  - `inspect_design_configurations` reports exposed configuration collections, active configuration metadata, row/item parameters, user parameters, and blockers when Fusion does not expose configuration APIs.
  - `plan_design_variant` validates explicit variant name, base configuration, parameter changes, expected affected bodies/features, reason, and user approval before any future configuration or parameter-set mutation.
  - Live fixture validation covers configuration inspection and variant planning without creating configurations or editing parameters.

- Configuration and design-variant guarded parameter workflows
  - `apply_design_variant_parameters` runs only after `plan_design_variant` passes and updates existing user parameters without creating or activating Fusion configuration rows.
  - It returns per-parameter before/after values, the accepted preflight plan, and before/after design-state comparison.
  - Tests cover preflight blockers, approved parameter-set application, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Render and presentation read-only workflows
  - `inspect_render_workspace` reports active viewport camera, named views, render product/settings when exposed, environments, and appearance counts without rendering or changing scene state.
  - `plan_render_output` validates camera or named view, absolute output path, resolution, visual style, environment/background choices, reason, and user approval before any future render/export action.
  - Live fixture validation covers render workspace inspection and render-output planning without writing image files.

- Render and presentation guarded output workflows
  - `render_viewport_output` runs only after `plan_render_output` passes and writes a local viewport still to an explicit output path.
  - It verifies the output file exists and is non-empty, returns the accepted preflight plan, and reports before/after design-state comparison.
  - Tests cover render preflight blockers, non-empty viewport output, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Data-management read-only workflows
  - `inspect_document_management_state` reports active/open document save state, dataFile metadata, version-ish fields, project/folder metadata, cloud availability, and exposed external references without saving or relinking data.
  - `plan_document_management_action` validates explicit save/save-as/export-copy/version/open/relink intent, target paths or data-file identifiers, dry-run mode, reason, and user approval before any future document-management mutation.
  - Live fixture validation covers document-management inspection and dry-run planning without saving, uploading, versioning, opening, promoting, or relinking files.

- Data-management guarded local-copy workflows
  - `export_document_copy` runs only after `plan_document_management_action` passes for `export_copy` and writes a local `.f3d`/`.f3z` archive of the active document.
  - It refuses to activate another document, returns structured unsupported responses when Fusion lacks archive export APIs, and verifies a non-empty output file.
  - Tests cover approval blockers, unsupported runtime handling, non-empty archive output, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Data-management guarded new-document workflows
  - `create_design_document` runs only after `plan_document_management_action` passes for `new_design`, requires explicit user approval and reason, and creates one new unsaved Fusion design document.
  - It does not save, upload, version, open a data file, promote, relink, or create geometry.
  - The 3MF live fixture uses it with structured `create_box` calls instead of a raw setup script.

- Data-management guarded close workflows
  - `close_active_document` runs only after `plan_document_management_action` passes for `close`, requires explicit user approval and reason, and closes only the active document with explicit save/discard intent.
  - It refuses to activate or close a different named document and is profiled as dangerous because `save_changes=false` discards unsaved edits.
  - The 3MF live fixture uses `close_active_document` for throwaway-document cleanup instead of a raw cleanup script.

- Simulation read-only workflows
  - `inspect_simulation_workspace` reports whether Fusion exposes an active Simulation product and study collection without creating, meshing, solving, or exporting studies.
  - `list_simulation_studies` reports exposed study metadata including study type, solve status, load/constraint/material/contact counts, mesh availability, and result counts.
  - `plan_simulation_study` validates explicit study type, target bodies, material assumptions, loads, constraints, mesh settings, result outputs, and user approval before any future Simulation mutation.
  - Live fixture validation covers Simulation workspace inspection, study listing, and preflight planning without solving or exporting results.

- Electronics and PCB read-only workflows
  - `inspect_electronics_workspace` reports whether Fusion exposes an Electronics/PCB product, boards, board outlines, components, nets, connector candidates, and linked metadata.
  - `plan_pcb_enclosure_fit` validates explicit board outline, keepouts, connectors, mounting holes, clearance rules, enclosure body targets, reason, and user approval before any future electronics/mechanical bridge action.
  - Live fixture validation covers electronics workspace inspection and PCB enclosure-fit planning without syncing boards or editing mechanical geometry.

- `capture_demo_sequence`
  - General presentation helper for named camera views, staged visibility, screenshots, and before/after capture steps.
  - Captures still PNG frames for external video assembly and remains independent of any one project or model category.

- `get_physical_properties`
  - Read-only body mass, volume, area, density, center-of-mass, bounding-box, material, and appearance report.
  - Supports single-body, entity-token, and all-body inspection without mutating the design.

- Analysis and clearance workflows
  - `inspect_analysis_capabilities` reports whether the runtime exposes candidate exact BRep interference and minimum-distance APIs, with explicit blockers and warnings that candidates are not validated exact solvers.
  - `interference_check` reports read-only broad-phase body intersections using axis-aligned bounding boxes, overlap dimensions, and overlap volume estimates.
  - `clearance_check` reports read-only broad-phase distances between explicit target/tool body sets with a required minimum clearance expression.
  - `exact_interference_check` attempts exact BRep Boolean intersection only when TemporaryBRepManager copy/intersection candidates are exposed, and otherwise returns structured unsupported results.
  - `exact_clearance_check` attempts exact minimum-distance measurement only when a measure-manager candidate is exposed, and otherwise returns structured unsupported results.
  - Both tools accept body names/component keys/entity tokens, avoid inferred tolerances, advertise read-only annotations, and are covered by mock/server/unit/live-smoke paths.
  - `create_section_analysis` creates a named section-analysis entity on an explicit standard or named construction plane when the Fusion runtime exposes a compatible section-analysis API.
  - `delete_section_analysis` deletes named section analyses with a required reason and before/after state comparison for cleanup.
  - Section-analysis tools return structured unsupported responses instead of guessing a raw API path when Fusion does not expose a compatible section-analysis collection.

- Existing sketch/profile reuse workflows
  - `copy_profile_loop` copies/projects only one profile loop from a source sketch into a destination sketch, including an `outer_loop` selector for workflows that need an exact footprint from a crowded sketch.
  - `offset_profile_loop` offsets only the selected profile loop instead of all curves in the sketch, avoiding broad offsets of projected logos or reference geometry.
  - `extrude_existing_profile` wraps existing-profile extrusion with explicit profile-count, failure-stage, participant-body, and recovery diagnostics so profile instability does not force blind fallback scripting.
  - `create_insert_socket` creates a removable plate and matching target-body socket cut from one selected source profile loop. It copies the loop into a work sketch, creates plate and cutter bodies, verifies broad-phase alignment, cuts the target with the cutter, consumes the cutter by default, and returns `delete_named_experiment` recovery guidance for partial attempts.
  - `delete_named_experiment` is a dangerous-profile cleanup tool for named failed attempts; it dry-runs by default, requires a reason, refuses short prefixes unless explicitly overridden, and deletes matched timeline items, bodies, and sketches only with `confirm_delete=true`.
  - Tests cover loop-only copy/offset behavior, profile-reuse failure diagnostics, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Existing feature edit workflows
  - `edit_extrude_feature` edits existing extrude distance and/or operation by exact feature name.
  - `edit_fillet_radius`, `edit_chamfer_distance`, and `edit_shell_thickness` edit common existing feature dimensions without exposing a generic feature editor.
  - `edit_pattern_parameter` and `edit_hole_parameter` edit inspected count/spacing or hole-dimension model parameters by exact parameter name/role.
  - All existing-feature edit tools validate supported feature kind, run dependency/impact checks, block downstream-risk edits by default, support reasoned overrides, and return before/after parameter data plus design-state comparison.
  - Unsupported feature kinds return a structured tool-gap message that routes agents to inspection or justified raw-script fallback.

- Sheet metal read-only workflows
  - `inspect_sheet_metal_rules` reports active sheet-metal rule metadata, exposed rule collections, detected sheet-metal bodies, and unavailable-API warnings without mutating the model.
  - `preflight_flat_pattern` reports flat-pattern readiness, blockers, target body metadata, active rule data, and flatPattern availability without exporting or unfolding.
  - `plan_sheet_metal_workflow` validates explicit sheet-metal operation intent, target body, rule name, edge/face tokens, parameters, and reason fields before any flange/bend/unfold/refold workflow.
  - Tests cover non-sheet-metal design handling, rule metadata extraction, flat-pattern blockers, available flatPattern reporting, sheet-metal workflow plan validation, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Sheet metal flat-pattern export
  - `export_flat_pattern` exports an existing Fusion flatPattern to DXF, DWG, or STEP only after `preflight_flat_pattern` passes, or after a reasoned blocked-export override.
  - `plan_multibody_3mf_export` validates absolute `.3mf` output paths, explicit body names/entity tokens, named selection-set contents, expected body count, ignored non-body selection members, overwrite policy, and generic export readiness before writing a file.
  - `verify_insert_alignment` catches common insert/socket/logo layout blockers before multibody 3MF export, including separated raised geometry and flush-depth mismatches.
  - `export_asset(format="3mf")` now supports explicit body names, body entity tokens, named selection-set contents, expected body-count checks, explicit overwrite approval, native Fusion `ObjectCollection` body targeting, visibility restoration after failures, and exported 3MF package inspection with validity/object/build/component counts, embedded material/color evidence counts, conservative `slicerColorabilityLikely`, validation-scope notes, and `printReadiness` verdicts; `inspect_3mf_archive` exposes the same validation for existing files, and live validation against a throwaway multicolor export fixture is still needed after the add-in reloads.
  - Requires an absolute output path, never infers material/rule/manufacturing allowances, and returns structured unsupported results when Fusion does not expose a compatible flat-pattern export API.
  - Tests cover path validation, preflight blockers, override reason enforcement, unsupported API handling, export-manager success, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Sheet metal guarded mutation workflows
  - `create_flange`, `create_bend`, `unfold_sheet_metal`, and `refold_sheet_metal` run only after `plan_sheet_metal_workflow` passes.
  - Each tool resolves exact sheet-metal body targets, verifies requested edge/face entity tokens, applies explicit runtime-supported input parameters, and returns before/after design-state comparison.
  - Tools return structured unsupported responses when Fusion does not expose compatible writable sheet-metal feature collections or input builders.
  - Tests cover preflight blockers, missing runtime feature collections, writable fake collection execution, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Richer assembly joint workflows
  - `get_assembly_joints` reports existing joints and as-built joints with motion type, references, suppression, health, and best-effort motion-limit metadata.
  - `create_revolute_joint`, `create_slider_joint`, `create_cylindrical_joint`, `create_pin_slot_joint`, `create_planar_joint`, and `create_ball_joint` extend beyond rigid point-to-point joints.
  - `plan_joint_limits` validates explicit joint target, rotation/slide limit kind, min/max/rest expressions, and reason fields before any future joint-limit mutation.
  - `set_joint_limits` applies explicit rotation/slide limit expressions only after `plan_joint_limits` passes, and returns structured unsupported results when Fusion does not expose writable limit APIs.
  - Motion-joint tools require explicit point references by name/entity token and explicit motion directions where the joint type needs them; they do not guess origins, axes, normals, or slide directions.
  - Unit tests cover each joint type's required inputs, no-guessed-axis behavior, joint limit plan/set validation, unsupported limit APIs, state comparison, profile/schema registration, mock responses, and live-smoke required-tool checks.

- Surface modeling read-only workflows
  - `inspect_surface_bodies` identifies solid vs surface bodies, face counts, edge counts, best-effort open-edge candidates, and candidate repair paths without mutating geometry.
  - Supports body names/component keys/entity tokens, invisible-body filtering, and truncated or full open-edge candidate output.
  - `plan_surface_repair` validates explicit repair operation, target body, edge/face tokens, parameters, solid-body allowance, and required reason fields before any surface mutation.
  - Tests cover surface-vs-solid classification, open-edge reporting, missing target reporting, surface repair plan blockers, read-only annotations, profiles, mock mode, and live-smoke required-tool checks.

- Surface modeling guarded mutation workflows
  - `patch_surface`, `stitch_surfaces`, `thicken_surface`, `trim_surface`, `extend_surface`, and `create_ruled_surface` run only after `plan_surface_repair` passes.
  - Each tool resolves exact body/entity-token targets, verifies requested edge/face entity tokens, applies explicit runtime-supported input parameters, and returns before/after design-state comparison.
  - Tools return structured unsupported responses when Fusion does not expose compatible writable surface feature collections or input builders.
  - Tests cover preflight blockers, missing runtime feature collections, writable fake collection execution, annotations, profiles, mock mode, and live-smoke required-tool checks.

- CAM/manufacturing read-only workflows
  - `inspect_manufacturing_workspace` reports whether Fusion exposes an active CAM/manufacturing product, setup availability, and blockers without creating setups or toolpaths.
  - `list_manufacturing_setups` reports exposed setup metadata and optional operation summaries without inferring stock, WCS, tools, feeds, speeds, or post processors.
  - `inspect_operation` reports exposed CAM operation metadata by exact operation name or index and refuses to generate toolpaths or post-process output.
  - `plan_manufacturing_operation` validates explicit setup/operation intent, machine, stock, WCS, tool, feeds, speeds, post-processor data, and approval before any future CAM mutator can run.
  - Tests cover workspace unavailable handling, setup and operation metadata reporting, missing target blockers, manufacturing-plan validation, read-only annotations, profiles, mock mode, and live-smoke required-tool checks.

- CAM/manufacturing guarded mutation workflows
  - `create_manufacturing_setup`, `create_manufacturing_operation`, `generate_toolpaths`, and `post_process` run only after `plan_manufacturing_operation` passes with explicit production inputs and user approval.
  - `post_process` requires an absolute output path and all tools return structured unsupported responses when Fusion does not expose compatible CAM setup, operation, toolpath, or post-processing APIs.
  - A dedicated `manufacturing` profile groups CAM inspection, planning, and guarded mutation tools for clients that want to expose manufacturing separately from modeling/export surfaces.
  - Tests cover failed production preflight, missing setup targets, writable fake setup collection execution, toolpath gating, absolute post path validation, annotations, profiles, mock mode, and live-smoke required-tool checks.

- Drawing/documentation read-only workflows
  - `inspect_drawing_documents` reports open drawing documents, sheets, views, title blocks, tables, parts-list counts, and dimension counts when Fusion exposes the Drawing API.
  - `preflight_drawing_creation` checks saved active-document state, DrawingManager availability, optional absolute PDF path validity, and unsaved-change warnings before mutating drawing/export tools run.
  - `plan_drawing_views` normalizes explicit standard, sheet size/orientation, units, title-block intent, and view orientation/style/scale with documented defaults before any drawing mutation.
  - Tests cover drawing document/sheet/view metadata, saved-document requirement, PDF path validation, drawing-plan metadata validation, unsupported Drawing API handling, read-only annotations, profiles, mock mode, and live-smoke required-tool checks.

- Drawing/documentation guarded mutation workflows
  - `add_drawing_view`, `add_drawing_dimension`, `add_drawing_callout`, `add_parts_list`, and `add_revision_table` operate on an explicit open drawing sheet and require reason fields.
  - `add_drawing_view` runs only after `plan_drawing_views` passes; dimension/callout/BOM/revision helpers require explicit geometry/view/text/placement metadata where applicable.
  - Tools return structured unsupported responses when the active document is not a drawing or Fusion does not expose compatible sheet collections.
  - Tests cover missing inputs, unsupported Drawing API handling, writable fake drawing collection execution, annotations, profiles, mock mode, and live-smoke required-tool checks.

- First-class MCP prompts
  - Adds workflow prompts for tool-first routing, export readiness, threaded fasteners, sheet-metal enclosure planning, printability review, and physical-property review.
  - Prompt text routes agents toward structured tools and explicitly calls out unsupported CAD-domain gaps instead of encouraging invented raw-script behavior.

- Safer undo workflow
  - `undo_last_action` captures design state before/after undo and automatically redoes risky undo results unless explicitly overridden with a reason.
  - Guardrails catch design-type changes, newly unhealthy timeline items, and broad component/body/sketch removals.

- Server capability/adoption metadata
  - `fusion://agent/server-capabilities` summarizes supported transports, discovery keys, initialize instructions, safety gates, profiles, prompts, and capability counts.
  - `/health` advertises both legacy SSE and Streamable HTTP compatibility while keeping credentials out of the health payload.

- Initialize-time agent instructions
  - MCP initialize responses now include concise Toolsmith instructions: call `doctor`, inspect first, use structured tools, preflight edits/exports, validate after changes, and reserve `run_fusion_script` for justified gaps.
  - This gives clients a standard protocol-level guidance surface before they inspect prompts or resources.

- MCP tool risk annotations
  - Every advertised tool includes MCP `annotations` hints for read-only, destructive, idempotent, and open-world behavior.
  - Clients can use these hints for approval prompts and tool filtering; they are advisory metadata, not a replacement for Toolsmith's runtime guardrails.

- MCP resource ranking annotations
  - Every advertised resource and resource template includes assistant audience and priority metadata.
  - Agent workflow resources rank highest, live design resources rank above runtime journals, and local docs remain available without crowding out model context.

- Offline MCP schema export
  - `fusion-mcp dump-schemas` emits initialize metadata, tools, resources, resource templates, prompts, profiles, and server capabilities without launching Fusion.
  - Useful for GitHub review, client integration tests, and docs generation.

- No-Fusion mock server
  - `fusion-mcp mock-server` runs a deterministic Streamable HTTP endpoint on port `9101` by default.
  - It reuses the offline MCP schema surface and returns stable mock responses for client handshake, tool listing, prompt/resource reads, `doctor`, inspection, validation, workflow, export-preflight, and capture calls.
  - Adds specialized mock payloads for high-value export, drawing, demo-capture, construction-reference, joint, sketch-constraint, rounded-feature, hole-pattern, mirror/pattern, feature creation, sketch-dimension editing, mesh/component conversion, document/timeline/camera, appearance/visibility, and parameter flows instead of relying only on a generic fallback.
  - `SPECIALIZED_MOCK_TOOLS` documents the covered client-flow surface, and tests assert representative payloads plus prefix-derived registered mutating tool parity stay stable for integration clients.
  - `docs/mock-payload-examples.md` keeps representative checked-in JSON payloads synchronized with the mock generator for client docs and CI smoke examples.

- Live fixture validation hooks
  - `scripts/test_fusion_mcp_inspection_fixture.ps1` now probes exact analysis, motion-joint creation, joint-limit planning, surface repair, sheet-metal planning/mutation preflight, drawing mutation unsupported handling, and CAM planning/toolpath/post-processing gates against the controlled fixture document.
  - `scripts/test_fusion_mcp_3mf_fixture.ps1` creates a throwaway two-body document through `create_design_document` and `create_box`, plans color assignments through `plan_multicolor_3mf_export`, applies appearances with token-safe `apply_appearance`, exports targeted 3MF, verifies archive inspection, and closes the fixture document through `close_active_document`.
  - The probes accept either successful runtime-backed execution or the intended structured preflight/unsupported responses, so the fixture can validate contracts across Fusion versions without requiring production CAM output or broad destructive edits.
  - `fusion-mcp test-fixture --report-path <json>` writes a machine-readable pass/unsupported/preflight-blocked probe report for archiving runtime-specific adapter evidence.
  - `fusion-mcp test-3mf-fixture` is the live validation path for multicolor 3MF export after the add-in has reloaded the latest Python modules.
  - `fusion-mcp doctor` compares the live add-in source fingerprint with the current checkout so stale loaded Python modules are reported separately from missing tool names.
  - `fusion-mcp validate-fixture-report <json>` verifies the report schema and complete emitted probe surface, with optional `--require-passed <probe>` gates for runtimes where a specific adapter must be fully supported.
  - `fusion-mcp fixture-report-matrix <reports...>` summarizes probe status across archived reports as JSON or Markdown so Fusion-version and machine-specific adapter gaps can be compared directly.
  - Unit tests assert the fixture script keeps these validation probes in place.
