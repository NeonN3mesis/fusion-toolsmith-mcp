# Demo Script

Use this flow for a short README GIF or video. Keep the recording focused on the agent transcript and Fusion 360 changing state.

## Setup

1. Open an existing Fusion design with at least one sketch, one feature, and one user parameter.
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
Inspect the active design. Summarize components, sketches, features, user parameters, and likely risky edits.
```

Show:

- the agent uses inspection tools before mutation
- the result mentions actual model structure

Prompt:

```text
Plan a parameter-safe change to this model. Do not edit yet. Include downstream impact.
```

Show:

- parameter plan
- dependency or impact assessment

Prompt:

```text
Apply the safest parameter-only change, capture before and after state, and compare the result.
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
