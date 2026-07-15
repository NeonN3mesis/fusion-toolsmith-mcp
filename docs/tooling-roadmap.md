# Tooling Roadmap

This is the general CAD tooling backlog for Fusion Toolsmith MCP. Keep these tools domain-neutral: no product-specific dimensions, names, or workflows.

## Next Tool Gaps

- Loft tool
  - Create lofted solid/surface features from named profiles or selected profiles with clear section ordering and continuity warnings.

- Sweep/path tool
  - Create sweep features from a named profile and path, including basic path validation and result-body reporting.

- Assembly joints and origin helpers
  - Inspect and create basic joint/origin/construction references for repeatable component placement.

- Material and appearance workflows
  - Expand appearance assignment into reusable material/appearance inspection, assignment, and reporting workflows.

- Stronger sketch constraint editing
  - Add more complete constraint creation/editing and safer constraint conflict reporting.

- Entity-token targeting for more mutating tools
  - Let mutating tools target stable entity tokens when Fusion exposes them, not only names, indices, or current selection.

- Deeper slicer-grade printability
  - Move beyond heuristic warnings toward mesh/slicer-aware checks while keeping the tool read-only.

## Implemented

- `create_offset_plane`
  - Create a named construction plane offset from a standard plane, named construction plane, or selected planar face.

- `create_hole_pattern`
  - General hole-pattern cuts for explicit, rectangular, and circular point layouts.
  - Supports through, blind, counterbore, and true conical countersink cuts with structured result metadata.

- `revolve_feature`
  - Create revolve features from named sketch profiles and explicit standard, named, or selected axes.
  - Requires an explicit operation and returns angle, result bodies, participants, inspection, and before/after design-state comparison.

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

- `create_construction_point`
  - Create named construction points from coordinates, named point entities, or selected point-like geometry.

- `create_construction_axis`
  - Create named construction axes from two named/coordinate-backed points or selected line-like geometry.
  - Useful for mirrors, revolves, circular patterns, and repeatable feature placement.

- `inspect_printability`
  - General read-only FDM sanity report: bounding boxes, thin/tiny/narrow feature candidates, small rounded-hole candidates, and risky downward-face/overhang candidates.
  - Reports warnings and limitations only; does not mutate geometry or claim slicer-level validation.

- `capture_demo_sequence`
  - General presentation helper for named camera views, staged visibility, screenshots, and before/after capture steps.
  - Captures still PNG frames for external video assembly and remains independent of any one project or model category.
