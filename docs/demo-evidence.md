# Demo Evidence

This records the live Fusion Toolsmith MCP flow used to create the README demo asset.

## Setup

- Created a separate unsaved Fusion design for the demo.
- The user's existing active design was not modified.
- Demo body: `Toolsmith_DemoBody`
- Demo parameters:
  - `toolsmithWidth`
  - `toolsmithDepth`
  - `toolsmithHeight`
  - `toolsmithSlotDepth`

## Tool Flow

1. `doctor`
   - Tool execution ready.
   - FusionMCP server running on port `9100`.
   - TaskManager running.

2. `plan_parameterization`
   - Target sketch: `Toolsmith_BaseSketch`
   - Target feature: `Toolsmith_BaseExtrude`
   - User parameters found: 4
   - Already parameterized entries: 3
   - Risk level: medium
   - OK to proceed with parameter-only edits: true

3. `capture_view`
   - Before screenshot: `docs/assets/fusion-toolsmith-before.png`

4. `modify_parameters`
   - Parameter: `toolsmithWidth`
   - Before: `42 mm`
   - After: `56 mm`
   - State comparison risk level: low
   - Changed categories: bodies, sketches, userParameters, modelParameters
   - Timeline changes: none

5. `get_parameter_usage`
   - `toolsmithWidth` drives sketch dimension `d5` in `Toolsmith_BaseSketch`.

6. `capture_view`
   - After screenshot: `docs/assets/fusion-toolsmith-after.png`

7. `preflight_export`
   - OK to export: true
   - Compute succeeded: true
   - Unhealthy timeline items: 0
   - State comparison after compute: no changes

## Generated Assets

- `docs/assets/fusion-toolsmith-before.png`
- `docs/assets/fusion-toolsmith-after.png`
- `docs/assets/fusion-toolsmith-demo.png`
- `docs/assets/fusion-toolsmith-demo.gif`
