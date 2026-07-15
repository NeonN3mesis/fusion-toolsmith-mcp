# Demo Evidence

This records the live Fusion Toolsmith MCP flow used to create the README demo asset.

## Source Reference

- Active reference document inspected: `slate wall mount v13`
- Reference body: `WallMount`
- Units: `mm`
- Timeline health: 0 unhealthy items
- User parameters found in the reference design: 17

Key reference parameters used for the demo:

- `TabletWidth = 202.04 mm`
- `TabletHeight = 290.85 mm`
- `TabletThickness = 7.00 mm`
- `Clearance = 1.00 mm`
- `WallThickness = 3.00 mm`
- `LipWidth = 12.00 mm`
- `ScrewHoleDiameter = 4.00 mm`
- `ScrewHeadDiameter = 9.00 mm`
- `BottomOpeningWidth = 60.00 mm`

## Demo Setup

- Created a separate unsaved Fusion design for the demo.
- The original `slate wall mount v13` design was not modified.
- Demo body count: 19
- Demo user parameter count: 10
- Demo timeline items: 40
- Demo unhealthy timeline items: 0

Primary demo bodies:

- `Toolsmith_PixelSlateReferenceBody`
- `Toolsmith_LeftFrameRailBody`
- `Toolsmith_RightFrameRailBody`
- `Toolsmith_TopFrameRailBody`
- `Toolsmith_BottomFrameRailBody`
- `Toolsmith_LeftRetainingLipBody`
- `Toolsmith_RightRetainingLipBody`
- `Toolsmith_BottomRetainingLipBody`
- `Toolsmith_TopRetentionTabLeftBody`
- `Toolsmith_TopRetentionTabRightBody`

## Tool Flow

1. `doctor`
   - Tool execution ready.
   - FusionMCP server running on port `9100`.
   - TaskManager running.

2. `capture_design_state`
   - Inspected the live `slate wall mount v13` reference model.
   - Extracted tablet, wall, clearance, lip, screw, and opening parameters.

3. `run_fusion_script`
   - Created a new from-scratch demo document.
   - Built the tablet reference, frame rails, retaining lips, screw details, and cable opening.
   - The script was limited to isolated demo setup.

4. `plan_parameterization`
   - Target features:
     - `Toolsmith_LeftRetainingLipFeature`
     - `Toolsmith_RightRetainingLipFeature`
     - `Toolsmith_BottomRetainingLipFeature`
   - User parameters found: 10
   - Already parameterized entries: 3
   - OK to proceed with parameter-only edits: true

5. `modify_parameters`
   - Parameter: `LipHeight`
   - Before: `12.00 mm`
   - After: `18.00 mm`
   - State comparison risk level: low
   - Changed categories: bodies, userParameters, modelParameters
   - Timeline changes: none

6. `get_parameter_usage`
   - `LipHeight` drives 5 feature parameters:
     - `Toolsmith_LeftRetainingLipFeature`
     - `Toolsmith_RightRetainingLipFeature`
     - `Toolsmith_BottomRetainingLipFeature`
     - `Toolsmith_TopRetentionTabLeftFeature`
     - `Toolsmith_TopRetentionTabRightFeature`

7. `preflight_export`
   - OK to export: true
   - Compute succeeded: true
   - Unhealthy timeline items: 0
   - State comparison after compute: no changes

## Generated Assets

- `docs/assets/pixel-slate-demo/01-tablet-reference.png`
- `docs/assets/pixel-slate-demo/02-frame-rails.png`
- `docs/assets/pixel-slate-demo/03-retaining-lips.png`
- `docs/assets/pixel-slate-demo/04-complete-mount.png`
- `docs/assets/pixel-slate-demo/05-lip-height-edit.png`
- `docs/assets/pixel-slate-demo/pixel-slate-wall-mount-demo.gif`
- `docs/assets/pixel-slate-demo/pixel-slate-wall-mount-demo.mp4`
- `docs/assets/pixel-slate-demo/pixel-slate-wall-mount-demo.png`
