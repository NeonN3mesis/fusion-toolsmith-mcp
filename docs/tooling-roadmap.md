# Tooling Roadmap

This is the general CAD tooling backlog for Fusion Toolsmith MCP. Keep these tools domain-neutral: no product-specific dimensions, names, or workflows.

## Next Tool Gaps

- CAM/manufacturing workflows
  - Setup creation, operation creation, toolpath generation, operation inspection, and post-processing.
  - Keep this gated and explicit; manufacturing tools should not infer stock, machines, tools, feeds, speeds, or post processors.

- Surface modeling workflows
  - Patch, stitch, thicken, ruled surface, trim/extend, and surface-to-solid repair helpers.
  - Start with inspection/preflight and narrow feature creation before destructive repair tools.

- Sheet metal workflows
  - Flange, bend, unfold/refold, flat pattern, and sheet-metal rule inspection.
  - Treat flat pattern export as a preflight-gated export workflow.

- Analysis workflows
  - Dedicated physical properties, section analysis, and interference checks.
  - Prefer read-only reporting first; mutating analysis entities should be separate tools with explicit names and cleanup behavior.

- Mock/simulation mode
  - Provide a deterministic no-Fusion mode for client integration tests, docs screenshots, and CI smoke coverage.

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
  - Revolute, slider, cylindrical, pin-slot, planar, and ball joints remain intentionally separate future expansions rather than inferred behavior.

- Material and appearance workflows
  - `list_appearances` discovers active-design and material-library appearances with optional filtering.
  - `inspect_body_style` reports body appearance, material, and physical material assignments across components.
  - `apply_appearance` applies a named or partial-match appearance to a named body.

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

- `capture_demo_sequence`
  - General presentation helper for named camera views, staged visibility, screenshots, and before/after capture steps.
  - Captures still PNG frames for external video assembly and remains independent of any one project or model category.

- `get_physical_properties`
  - Read-only body mass, volume, area, density, center-of-mass, bounding-box, material, and appearance report.
  - Supports single-body, entity-token, and all-body inspection without mutating the design.

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
