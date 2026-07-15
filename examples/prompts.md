# Example Prompts

Use these prompts with an MCP-capable agent after Fusion Toolsmith MCP is loaded in Fusion 360.

## Runtime Readiness

```text
Call doctor and tell me whether Fusion Toolsmith MCP is ready. If it is not ready, give me the shortest fix path.
```

```text
Inspect the available Fusion Toolsmith tool profiles and tell me which profile you need for this task before using any mutating tools.
```

## Inspection First

```text
Inspect the active Fusion design. Summarize components, bodies, sketches, timeline features, user parameters, and anything that looks risky to edit.
```

```text
Inspect this selected feature and map its dependencies before proposing any changes.
```

```text
Find projected geometry in the selected sketch and report where it came from.
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
Before editing this sketch, inspect constraints, dimensions, projected geometry, and feature consumers. Then propose the smallest safe edit.
```

## Export

```text
Preflight this model for a 3D-printable STL export. Do not export until the preflight report is clean or you explain the remaining risk.
```

```text
Export STEP and STL files for the active design after running preflight checks. Put the result paths in the final answer.
```

## Last-Resort Raw Script

```text
If structured Fusion Toolsmith tools cannot do this task, explain the tool gap first. Only then use run_fusion_script with a clear intent and a minimal script.
```
