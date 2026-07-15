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

```text
Use the physical_properties_review MCP prompt, then execute the read-only checks it recommends.
```

## Inspection First

```text
Inspect the active Fusion design. Summarize components, bodies, sketches, timeline features, user parameters, and anything that looks risky to edit.
```

```text
Run a heuristic FDM printability inspection on the visible bodies. Report thin walls, small holes, narrow gaps, unsupported lips, and anything that needs slicer verification.
```

```text
Run inspect_printability with mesh analysis enabled. Treat mesh warnings as review candidates only, and call out which risks still require slicer preview verification.
```

```text
Get physical properties for all bodies. Report mass, volume, area, center of mass, material assignments, and any bodies where Fusion did not expose properties.
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
Use the threaded_fastener_workflow MCP prompt for an M4 x 16 mm fastener. Follow the structured-tool plan and report any thread-modeling limitations before creating geometry.
```

```text
Use the sheet_metal_enclosure_workflow MCP prompt. Plan the enclosure and stop at the missing-tool gap if true flange, bend, unfold, or flat-pattern APIs are required.
```

```text
Inspect the target body's faces and edges, then shell it with an explicit wall thickness. Use face indices for any open faces and compare design state before and after.
```

```text
Inspect the target body's edges and faces, then use entity tokens rather than names or indices for any fillet, chamfer, shell open-face, or offset-face operation where tokens are available.
```

```text
Create named construction points and an axis for a repeatable pattern setup, then use the structured pattern tools instead of raw scripting.
```

```text
Inspect assembly references and existing joints first, then create a rigid point-to-point joint only from explicit named points or entity tokens.
```

```text
Offset the selected face by a small explicit distance using the controlled face-offset tool. Explain why this is the face-offset branch of Press Pull and not an arbitrary Press Pull operation.
```

```text
Before editing this sketch, inspect constraints, dimensions, projected geometry, and feature consumers. Then propose the smallest safe edit.
```

```text
Inspect this sketch's constraints. If one constraint needs removal, use its inspected constraint index, require an explicit reason, and compare design state before and after deletion.
```

## Export

```text
Preflight this model for a 3D-printable STL export. Do not export until the preflight report is clean or you explain the remaining risk.
```

```text
Use the printability_review MCP prompt, run the read-only checks, and separate Toolsmith warnings from slicer-preview risks.
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
