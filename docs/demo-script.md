# Demo Script

Use this flow for a short README GIF or video. Keep the recording focused on the agent transcript and Fusion 360 changing state. Choose any non-sensitive Fusion design with enough sketches, bodies, parameters, and features to show inspection, safe mutation, and export preflight.

## Setup

1. Open a real Fusion design that can act as a reference model.
2. Start `FusionMCP` from Fusion 360.
3. Run:

```powershell
fusion-mcp test-live
```

## Recording Flow

Prompt:

```text
Call doctor and confirm Fusion Toolsmith MCP is ready.
```

Show:

- health is OK
- `task_manager_running` is true
- structured tools are available

Prompt:

```text
Inspect the active design. Summarize components, bodies, sketches, timeline health, and user parameters.
```

Show:

- the agent uses inspection tools before mutation
- the agent calls `extract_reference_dimensions` after `inspect_design`
- the result mentions actual model structure and real dimensions from the open design

Prompt:

```text
Create a separate new demo document that recreates a small representative part using the inspected reference dimensions. Do not modify the source design.
```

Show:

- the source design remains open and unmodified
- the new document contains a few clearly named bodies, cuts, and fastener features derived from the reference dimensions
- the agent uses structured tools such as `create_rounded_rectangle_body`, `create_rounded_slot_cut`, and `create_counterbore_hole_pattern`
- the agent uses `set_visibility` to hide construction sketches and stage the finished view

Prompt:

```text
Plan a parameter-safe change to the new demo model. Do not edit yet. Include downstream impact.
```

Show:

- parameter plan
- dependency or impact assessment

Prompt:

```text
Change one named user parameter, capture before and after state, and compare the result.
```

Show:

- model update in Fusion
- before/after comparison

Prompt:

```text
Preflight this model for STL export and explain any remaining risk.
```

Show:

- preflight report
- export readiness

## README Asset

Save the final GIF or MP4 under:

```text
docs/assets/fusion-toolsmith-demo.gif
```

Then add it near the top of `README.md`.
