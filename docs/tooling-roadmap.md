# Tooling Roadmap

This is the general CAD tooling backlog for Fusion Toolsmith MCP. Keep these tools domain-neutral: no product-specific dimensions, names, or workflows.

## Near-Term Tools

- `create_hole_pattern`
  - Replace narrow hole helpers with a general hole feature tool.
  - Support through, blind, counterbore, countersink, rectangular patterns, circular patterns, named target bodies, cut direction, and structured result metadata.

- `mirror_features_or_bodies`
  - Mirror selected or named bodies/features/sketch entities across standard origin planes, named construction planes, or selected planar faces.
  - Return created names and before/after design-state comparison.

- `pattern_feature`
  - Rectangular and circular patterning for bodies or features.
  - Support count, spacing/angle, axes, direction, and participant bodies where applicable.

- `create_rounded_pocket`
  - Cut a shallow rounded-rectangle recess into a named target body.
  - Support depth, corner radius, plane/face placement, optional cleanup fillets/chamfers, and state comparison.

## Medium-Term Tools

- `shell_body`
  - Shell a named body with explicit wall thickness and optional open faces.
  - Include timeline impact checks because shell operations can be fragile.

- `create_construction_axis_or_point`
  - Create named construction axes and points from standard origins, selected geometry, explicit coordinates, or intersections.
  - Useful for mirrors, revolves, circular patterns, and repeatable hole placement.

- `offset_face_or_press_pull`
  - Controlled direct-modeling face offset with strong preflight warnings and dependency reporting.
  - Require explicit target face selection or stable entity reference.

## Validation And Presentation

- `inspect_printability`
  - General FDM sanity report: bounding box, thin walls, small holes, narrow slots, unsupported lips, tiny features, and risky overhang-like faces.
  - Report warnings only; do not mutate geometry.

- `capture_demo_sequence`
  - General presentation helper for named camera views, staged visibility, screenshots, and before/after capture steps.
  - Must remain generic and independent of any one project or model category.
