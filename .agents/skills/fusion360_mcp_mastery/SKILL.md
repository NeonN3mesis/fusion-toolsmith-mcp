---
name: fusion360-mcp-mastery
description: Comprehensive guide and workflow for interacting with Fusion 360 via the MCP servers (autodesk-fusion-mcp and fusion-mcp).
---

# Fusion 360 MCP Server Mastery

When assisting a user with Fusion 360 design tasks, follow these guidelines and workflows using the available MCP servers.

## Available Servers and Tools

### 1. High-Level Server (`fusion-mcp`)
*Provides structured, parametric operations and design state inspection.*
- **Inspection & Resources**: `inspect_design`, `get_assembly_tree`, `fusion://design/summary`, `fusion://design/parameters`
- **Parametric Operations**: `create_parametric_feature`, `modify_parameters`, `set_parameter`, `get_parameter`
- **Utilities**: `capture_view`, `validate_model`, `measure_entity`, `undo_last_action`, `export_asset`, `prompt_user`
- **Selection**: `query_selection`, `get_current_selection`

### 2. Low-Level Server (`autodesk-fusion-mcp`)
*Provides raw API access and documentation.*
- **Scripting**: `execute_api_script` (Use only when high-level tools are insufficient)
- **Docs & Guidelines**: `get_api_documentation`, `get_best_practices`
- **Visualization**: `get_screenshot`

## Standard Operating Procedure

1. **Understand the Context**:
   - Call `inspect_design` or read `fusion://design/summary` to understand the current units, root component, and timeline health.
   - Call `get_assembly_tree` to see the structure.
   - If the request is complex, call `get_best_practices` or `get_api_documentation` to ensure your approach is correct.

2. **Visual Verification (Before)**:
   - Call `capture_view` (from `fusion-mcp`) or `get_screenshot` (from `autodesk-fusion-mcp`) to visually understand the model state.

3. **Execution**:
   - **Prefer High-Level Tools**: Use `create_parametric_feature`, `modify_parameters`, etc. for robust, parametric design.
   - **Fallback to Scripting**: If you must use `execute_api_script` or `run_fusion_script`, ensure your script defines a `run(context)` function, does NOT use UI message boxes, and prints results to stdout. DO NOT catch exceptions unless explicitly ignoring them.
   - **Coordinate System**: Remember Y is UP (Height), X is Width, Z is Depth.
   - **Naming**: ALWAYS name bodies immediately after creation.

4. **Visual Verification (After)**:
   - Take another screenshot to verify changes.
   - Run `validate_model` to ensure constraints and timeline are intact.
   - Use `undo_last_action` if the change broke the model.

## Critical Design Best Practices
- **Construction Planes**: They are 2D surfaces. Use `Point3D.create(x, z, 0)` for XZ planes.
- **Lofting vs Extruding**: Use loft features for tapered circular profiles (like legs).
- **Materials**: Apply both material AND appearance properties. Create separate bodies for each material.
- **Heights**: Calculate all Y coordinates before geometry creation. Use `startExtent` for precise Y positioning rather than moving bodies after creation.
