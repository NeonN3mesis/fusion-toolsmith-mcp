# Example Prompts

Use these prompts with an MCP-capable agent after Fusion Toolsmith MCP is loaded in Fusion 360.

## Runtime Readiness

```text
Call doctor and tell me whether Fusion Toolsmith MCP is ready. If it is not ready, give me the shortest fix path.
```

```text
Inspect the available Fusion Toolsmith tool profiles and tell me which profile you need for this task before using any mutating tools.
```

```text
List the tool profiles and choose the smallest profile set needed for a read-only review of this model.
```

## Inspection First

```text
Inspect the active Fusion design. Summarize components, bodies, sketches, timeline features, user parameters, and anything that looks risky to edit.
```

```text
Run a heuristic FDM printability inspection on the visible bodies. Report thin walls, small holes, narrow gaps, unsupported lips, and anything that needs slicer verification.
```

```text
Inspect this selected feature and map its dependencies before proposing any changes.
```

```text
Find projected geometry in the selected sketch and report where it came from.
```

```text
List available black and metal appearances, inspect the current style assignments on all visible bodies, then suggest a body-by-body styling pass before applying anything.
```

## Parameter Workflows

```text
Find the model parameters that look safe to expose for customization. Do not modify geometry yet.
```

```text
Plan a parameterization strategy for this model. Include which dimensions should become user parameters and which downstream features could break.
```

```text
Change this model using existing parameters only. Capture design state before and after, then compare the result.
```

## Safer Modeling

```text
Create a new feature only after inspecting the active component and checking likely downstream impact.
```

```text
Inspect the target body's faces and edges, then shell it with an explicit wall thickness. Use face indices for any open faces and compare design state before and after.
```

```text
Create named construction points and an axis for a repeatable pattern setup, then use the structured pattern tools instead of raw scripting.
```

```text
Offset the selected face by a small explicit distance using the controlled face-offset tool. Explain why this is the face-offset branch of Press Pull and not an arbitrary Press Pull operation.
```

```text
Before editing this sketch, inspect constraints, dimensions, projected geometry, and feature consumers. Then propose the smallest safe edit.
```

## Export

```text
Preflight this model for a 3D-printable STL export. Do not export until the preflight report is clean or you explain the remaining risk.
```

```text
Export STEP and STL files for the active design after running preflight checks. Put the result paths in the final answer.
```

## Presentation

```text
Capture a still-frame demo sequence with iso, front, and top views. Hide construction sketches during capture and restore visibility after the sequence.
```

```text
Stage the model for review: hide construction planes, fit the camera to an isometric view, and capture a screenshot.
```

## Last-Resort Raw Script

```text
If structured Fusion Toolsmith tools cannot do this task, explain the tool gap first. Only then use run_fusion_script with a clear intent and a minimal script.
```
