# Autodesk Fusion 360 MCP AI Agent Workflow Guide

Follow this systematic workflow to interact with Autodesk Fusion 360 reliably and prevent geometry/timeline errors.

---

## 1. Plan & Understand (Before Changing Anything)
1. **Understand Units**: Always call `inspect_design` to check default units (e.g. `'cm'`, `'mm'`). Design coordinates and parameter values must match this unit context.
2. **Analyze Assembly Tree**: Run `get_assembly_tree` to understand component occurrences and parent-child relationships.
3. **Timeline Inspection**: Use `get_timeline` to see if there are existing warning/error states. Never build on top of a broken timeline.

---

## 2. Modeling Execution (Clean & Parametric)
1. **Rollback Marker**: If adding a feature that logically belongs earlier in the design history, use `set_timeline_marker` to roll back, execute the feature, and roll forward.
2. **Prefer Primitives**: Use `create_box`, `create_cylinder`, and `create_coil` instead of writing custom Python scripts whenever possible.
3. **Name Everything**: Always assign descriptive names to sketches, bodies, and components immediately upon creation.
4. **Destructive Timeline Changes**: Before suppressing or deleting timeline features or deleting sketch dimensions, inspect dependencies and provide a concrete reason. Do not override downstream-risk blocks unless the user explicitly accepts the risk.

---

## 3. Visual & Model Validation (Post-Execution)
1. **Timeline Health Check**: Run `validate_model` to ensure your operations did not introduce timeline warnings.
2. **Visual Verification**: Take screenshots with `capture_view` from multiple standard angles (e.g. Front, Iso, Top) using `set_camera` to verify the geometries look correct.
3. **Check Suppression**: If debugging references, temporarily use `suppress_timeline_feature` to verify the reference chain.

---

## 4. Finalizing & Exporting
1. **Check Parameters**: Verify final parameter expressions with `get_parameter`.
2. **Preflight Export**: Run `preflight_export` or use `export_asset`, which runs preflight automatically. Do not export when compute or timeline health checks fail.
3. **Asset Export**: Run `export_asset` to save step or stl files to their target paths.
4. **No Raw Export Scripts**: Do not call Fusion `exportManager` from `run_fusion_script`. Raw scripted exports bypass model-health proof and are blocked by default.
