# Demo Script

Use this flow for a short README GIF or video. Keep the recording focused on the agent transcript and Fusion 360 changing state.

## Setup

1. Open a real Fusion design that can act as a reference model. The current README demo uses `slate wall mount v13`.
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
Inspect the active Pixel Slate wall-mount design. Summarize components, bodies, sketches, timeline health, and user parameters.
```

Show:

- the agent uses inspection tools before mutation
- the result mentions actual model structure and real dimensions such as tablet size, clearance, wall thickness, and lip width

Prompt:

```text
Create a separate new demo document that recreates the wall-mount workflow from scratch using the inspected reference dimensions. Do not modify the source design.
```

Show:

- the source design remains open and unmodified
- the new document contains a tablet reference, frame rails, retaining lips, screw details, and cable opening

Prompt:

```text
Plan a parameter-safe change to the new demo mount. Do not edit yet. Include downstream impact.
```

Show:

- parameter plan
- dependency or impact assessment

Prompt:

```text
Change LipHeight from 12 mm to 18 mm, capture before and after state, and compare the result.
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
docs/assets/pixel-slate-demo/pixel-slate-wall-mount-demo.gif
```

Then add it near the top of `README.md`.
