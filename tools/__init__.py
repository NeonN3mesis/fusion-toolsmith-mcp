"""
Tools and Resources Registry Package
"""

import json
import os
import re
import traceback

tools_registry = {}
resources_registry = {}

_DESTRUCTIVE_TOOLS = {
    "clear_change_journal",
    "close_active_document",
    "delete_section_analysis",
    "delete_named_experiment",
    "delete_sketch_constraint",
    "delete_sketch_dimension",
    "delete_timeline_feature",
    "suppress_timeline_feature",
    "undo_last_action",
    "revert_active_document",
    "run_fusion_script",
    "set_active_document",
    "set_timeline_marker",
}

_NON_IDEMPOTENT_MUTATION_PREFIXES = (
    "add_",
    "clone_",
    "combine_",
    "convert_",
    "create_",
    "draw_",
    "extrude_",
    "fillet_",
    "generate_",
    "chamfer_",
    "loft_",
    "mirror_",
    "pattern_",
    "patch_",
    "post_",
    "project_",
    "refold_",
    "reorganize_",
    "revolve_",
    "shell_",
    "stitch_",
    "sweep_",
    "thicken_",
    "trim_",
    "unfold_",
    "extend_",
)

_READ_ONLY_TOOL_NAMES = {
    "assess_change_impact",
    "capture_design_state",
    "compare_design_state",
    "doctor",
    "extract_reference_dimensions",
    "get_assembly_joints",
    "get_assembly_references",
    "get_assembly_tree",
    "get_best_practices",
    "get_body_edges",
    "get_body_faces",
    "get_change_journal",
    "get_current_selection",
    "get_dependency_graph",
    "get_feature_dependencies",
    "get_feature_parameters",
    "get_fusion_api_help",
    "get_mcp_workflow_guide",
    "get_parameter",
    "get_parameter_usage",
    "get_physical_properties",
    "get_projected_geometry_sources",
    "get_runtime_diagnostics",
    "get_sketch_dimensions",
    "get_sketch_parameters",
    "get_timeline",
    "git_status",
    "inspect_analysis_capabilities",
    "inspect_body_style",
    "inspect_design",
    "inspect_design_configurations",
    "inspect_document_management_state",
    "inspect_drawing_documents",
    "inspect_electronics_workspace",
    "inspect_mesh_bodies",
    "inspect_feature",
    "inspect_manufacturing_workspace",
    "inspect_simulation_workspace",
    "inspect_operation",
    "inspect_render_workspace",
    "interference_check",
    "clearance_check",
    "exact_interference_check",
    "exact_clearance_check",
    "inspect_printability",
    "inspect_selection_sets",
    "inspect_sheet_metal_rules",
    "inspect_sketch",
    "inspect_surface_bodies",
    "inspect_3mf_archive",
    "list_appearances",
    "list_documents",
    "list_manufacturing_setups",
    "list_simulation_studies",
    "map_coordinates",
    "measure_entity",
    "plan_drawing_views",
    "plan_design_variant",
    "plan_document_management_action",
    "plan_joint_limits",
    "plan_manufacturing_operation",
    "plan_mesh_conversion",
    "plan_multibody_3mf_export",
    "plan_multicolor_3mf_export",
    "plan_parameterization",
    "plan_pcb_enclosure_fit",
    "plan_render_output",
    "plan_simulation_study",
    "plan_sheet_metal_workflow",
    "plan_surface_repair",
    "preflight_drawing_creation",
    "preflight_export",
    "preflight_flat_pattern",
    "preflight_model_change",
    "query_selection",
    "recommend_mcp_workflow",
    "search_fusion_api_documentation",
    "search_local_fusion_docs",
    "validate_model",
    "verify_insert_alignment",
}

_IDEMPOTENT_MUTATION_TOOLS = {
    "apply_appearance",
    "apply_design_variant_parameters",
    "edit_chamfer_distance",
    "edit_extrude_feature",
    "edit_fillet_radius",
    "edit_hole_parameter",
    "edit_pattern_parameter",
    "edit_shell_thickness",
    "edit_sketch_dimension",
    "export_asset",
    "export_document_copy",
    "export_flat_pattern",
    "export_parameters_csv",
    "import_parameters_csv",
    "modify_parameters",
    "offset_face_or_press_pull",
    "render_viewport_output",
    "set_camera",
    "set_joint_limits",
    "set_parameter",
    "set_visibility",
}

_USER_INTERACTION_TOOLS = {"prompt_user"}

def register_tool(name):
    def decorator(func):
        tools_registry[name] = func
        return func
    return decorator

def register_resource(pattern):
    def decorator(func):
        resources_registry[pattern] = func
        return func
    return decorator

def _tool_title(name):
    return str(name).replace("_", " ").title()

def _tool_annotations(name):
    read_only = name in _READ_ONLY_TOOL_NAMES
    destructive = name in _DESTRUCTIVE_TOOLS
    idempotent = read_only or name in _IDEMPOTENT_MUTATION_TOOLS
    if any(name.startswith(prefix) for prefix in _NON_IDEMPOTENT_MUTATION_PREFIXES):
        idempotent = False
    if name in _USER_INTERACTION_TOOLS:
        idempotent = False
    return {
        "title": _tool_title(name),
        "readOnlyHint": bool(read_only),
        "destructiveHint": bool(destructive),
        "idempotentHint": bool(idempotent),
        "openWorldHint": False,
    }

def _with_tool_annotations(schemas):
    annotated = []
    for schema in schemas:
        item = dict(schema)
        name = item.get("name")
        if name:
            existing = dict(item.get("annotations") or {})
            annotations = _tool_annotations(name)
            annotations.update(existing)
            item["annotations"] = annotations
        annotated.append(item)
    return annotated

def _resource_annotations(uri):
    if str(uri).startswith("fusion://agent/"):
        return {"audience": ["assistant"], "priority": 0.95}
    if str(uri).startswith("fusion://design/"):
        return {"audience": ["assistant"], "priority": 0.85}
    if str(uri).startswith("fusion://runtime/"):
        return {"audience": ["assistant"], "priority": 0.7}
    if str(uri).startswith("fusion://docs/"):
        return {"audience": ["assistant"], "priority": 0.55}
    return {"audience": ["assistant"], "priority": 0.5}

def _with_resource_annotations(schemas, key="uri"):
    annotated = []
    for schema in schemas:
        item = dict(schema)
        uri = item.get(key)
        if uri:
            existing = dict(item.get("annotations") or {})
            annotations = _resource_annotations(uri)
            annotations.update(existing)
            item["annotations"] = annotations
        annotated.append(item)
    return annotated

@register_resource("fusion://agent/tool-profiles")
def read_tool_profiles():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tool_profiles.json")
    with open(path, "r", encoding="utf-8") as f:
        profiles = json.load(f)
    advertised = {schema.get("name") for schema in get_tool_schemas() if schema.get("name")}
    registered = set(tools_registry.keys())
    for profile in profiles.get("profiles", {}).values():
        tools = profile.get("tools") or []
        profile["missingFromSchema"] = [name for name in tools if name not in advertised]
        profile["missingFromRegistry"] = [name for name in tools if name not in registered]
    return profiles

@register_resource("fusion://agent/server-capabilities")
def read_server_capabilities():
    tool_schemas = get_tool_schemas()
    resource_schemas = get_resources_schemas()
    profile_data = read_tool_profiles()
    try:
        from ..server import mcp_server
    except Exception:
        import server.mcp_server as mcp_server
    prompts = [
        prompt.get("name")
        for prompt in getattr(mcp_server, "PROMPTS", [])
        if prompt.get("name")
    ]
    return {
        "schemaVersion": 1,
        "server": {
            "name": "fusion-mcp",
            "productName": "Fusion Toolsmith MCP",
            "version": "1.1.0",
            "runsInside": "Autodesk Fusion 360 add-in",
            "port": getattr(mcp_server, "DEFAULT_PORT", 9100),
            "instructions": getattr(mcp_server, "SERVER_INSTRUCTIONS", ""),
        },
        "transports": [
            {
                "name": "streamable_http",
                "endpoint": "/mcp",
                "authentication": "bearer",
                "status": "preferred",
                "sessionHeader": "Mcp-Session-Id",
            },
            {
                "name": "http_sse",
                "endpoint": "/sse",
                "authentication": "bearer_or_query_token",
                "status": "legacy_compatible",
                "messageEndpoint": "/messages",
            },
        ],
        "discovery": {
            "file": "~/.fusion_mcp.json",
            "preferredKeys": ["streamable_http_url", "authorization_header"],
            "legacyKeys": ["sse_url", "bearer_sse_url"],
            "healthEndpoint": "/health",
            "healthIsTokenFree": True,
        },
        "safety": {
            "toolFirstWorkflowResource": "fusion://agent/tool-first-workflow",
            "toolProfilesResource": "fusion://agent/tool-profiles",
            "changeJournalResource": "fusion://runtime/change-journal",
            "rawScriptTool": "run_fusion_script",
            "rawScriptRequiredArguments": ["script_intent", "mcp_tool_gap"],
            "guardedUndoTool": "undo_last_action",
            "preflightTools": ["doctor", "preflight_model_change", "preflight_export", "validate_model"],
        },
        "counts": {
            "tools": len(tool_schemas),
            "resources": len(resource_schemas),
            "profiles": len(profile_data.get("profiles", {})),
            "prompts": len(prompts),
        },
        "toolAnnotations": {
            "coverage": sum(1 for tool in tool_schemas if tool.get("annotations")),
            "fields": ["title", "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"],
        },
        "resourceAnnotations": {
            "coverage": sum(1 for resource in resource_schemas if resource.get("annotations")),
            "fields": ["audience", "priority"],
        },
        "prompts": prompts,
        "profiles": sorted(profile_data.get("profiles", {}).keys()),
        "notableCapabilities": [
            "structured CAD tools before raw scripts",
            "machine-readable tool profiles",
            "MCP tool annotations for client approval and risk UI",
            "read-only inspection and physical-property reports",
            "preflighted model changes and exports",
            "local redacted change journal",
            "guarded undo with automatic redo on risky state changes",
        ],
    }

def get_tool_schemas():
    schemas = [
        {
            "name": "inspect_design",
            "description": "Summarize the current design state (components, bodies, sketches, timeline, parameters, units, warnings). Instructions: Always use this tool when starting a task or after losing context. Understand the current units (e.g., 'cm' vs 'mm') before making changes. Review the timeline for warnings and identify the root component.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "capture_design_state",
            "description": "Capture a compact structural snapshot of the active Fusion design for before/after safety checks. Includes open documents, active document, units, components, bodies, sketches, parameters, timeline health, and optional selection state.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_selections": {
                        "type": "boolean",
                        "default": True,
                        "description": "Include currently selected UI entities in the snapshot."
                    }
                }
            }
        },
        {
            "name": "compare_design_state",
            "description": "Compare two capture_design_state snapshots and report added, removed, and changed structures plus warnings. Use after mutating tools to detect unintended changes or new timeline health issues.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "before": {"type": "object", "description": "Snapshot object returned by capture_design_state before an operation."},
                    "after": {"type": "object", "description": "Snapshot object returned by capture_design_state after an operation."}
                },
                "required": ["before", "after"]
            }
        },
        {
            "name": "extract_reference_dimensions",
            "description": "Read body, sketch, user parameter, bounding-box, and rounded-slot-candidate dimensions from the active design for recreating reference geometry with structured tools.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional body name or names to include. Omit for all bodies."
                    },
                    "sketch_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional sketch name or names to include. Omit for all sketches."
                    },
                    "include_parameters": {"type": "boolean", "default": True},
                    "infer_slots": {"type": "boolean", "default": True, "description": "Infer rounded-slot candidates from two-line/two-arc sketches."}
                }
            }
        },
        {
            "name": "inspect_printability",
            "description": "Read-only FDM printability sanity report for bodies. Reports BRep heuristics plus optional Fusion triangle-mesh analysis for tiny facets and overhang candidates without mutating geometry.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional body name or names to inspect. Omit for all visible bodies."
                    },
                    "include_invisible": {"type": "boolean", "default": False},
                    "build_axis": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "default": "z"},
                    "nozzle_diameter": {"type": "string", "default": "0.4 mm"},
                    "layer_height": {"type": "string", "default": "0.2 mm"},
                    "minimum_wall_thickness": {"type": "string", "description": "Defaults to 3x nozzle diameter."},
                    "minimum_hole_diameter": {"type": "string", "default": "2.0 mm"},
                    "minimum_slot_width": {"type": "string", "default": "1.0 mm"},
                    "minimum_feature_size": {"type": "string", "description": "Defaults to max(nozzle diameter, 2x layer height)."},
                    "overhang_angle_degrees": {"type": "number", "default": 45},
                    "max_items_per_warning": {"type": "integer", "default": 25},
                    "include_mesh_analysis": {"type": "boolean", "default": True, "description": "When true, also analyze Fusion-exposed triangle mesh data if available. Read-only and still not a slicer simulation."},
                    "mesh_quality": {"type": "string", "default": "low", "description": "Requested mesh quality hint for Fusion's mesh calculator when that API is available."}
                }
            }
        },
        {
            "name": "inspect_mesh_bodies",
            "description": "Read-only mesh body discovery before conversion or repair. Reports mesh body names, entity tokens, bounding boxes, triangle/node counts when Fusion exposes mesh data, and conversion capability flags.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional mesh body name or names to inspect. Omit for all visible mesh bodies."
                    },
                    "include_invisible": {"type": "boolean", "default": False},
                    "mesh_quality": {"type": "string", "default": "low", "description": "Requested mesh quality hint for Fusion mesh calculators when that API is available."}
                }
            }
        },
        {
            "name": "inspect_design_configurations",
            "description": "Read-only design configuration and variant metadata report. Returns exposed configuration rows/items, active configuration, and user parameters when Fusion exposes them.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_parameters": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "plan_design_variant",
            "description": "Read-only design-variant plan validator. Requires explicit variant name, parameter changes, affected bodies/features or warnings, reason, and approval before any future configuration or parameter-set mutation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variant_name": {"type": "string", "description": "Explicit name for the planned design variant."},
                    "base_configuration": {"type": "string", "description": "Optional existing configuration name to use as the base."},
                    "parameter_changes": {"type": "object", "description": "Explicit parameter-name to expression/value map."},
                    "expected_affected_bodies": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Expected affected bodies for downstream impact checks."
                    },
                    "expected_affected_features": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Expected affected timeline features for downstream impact checks."
                    },
                    "reason": {"type": "string", "description": "Why this design variant is needed."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "inspect_document_management_state",
            "description": "Read-only document management report. Returns active/open document save state, dataFile/cloud metadata, version-ish fields, project/folder data, and exposed external references without saving or relinking.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_open_documents": {"type": "boolean", "default": True},
                    "include_external_references": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "plan_document_management_action",
            "description": "Read-only preflight for document save, save-as, export-copy, version snapshot/promotion, open-data-file, and reference relink actions. Requires explicit targets, dry_run, reason, and user approval.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["save", "save_as", "export_copy", "version_snapshot", "promote_version", "relink_reference", "open_data_file"]
                    },
                    "document_name": {"type": "string", "description": "Optional open document name. Defaults to active document for active-document actions."},
                    "data_file_id": {"type": "string", "description": "Explicit Fusion dataFile identifier for cloud/version/relink actions."},
                    "target_path": {"type": "string", "description": "Absolute local path for save_as/export_copy planning."},
                    "target_folder_id": {"type": "string", "description": "Explicit Fusion folder/project target for save_as/open actions."},
                    "reference_name": {"type": "string", "description": "Reference name to relink for relink_reference."},
                    "version_id": {"type": "string", "description": "Explicit version identifier for promote/open actions."},
                    "dry_run": {"type": "boolean", "default": True},
                    "reason": {"type": "string", "description": "Why this document-management action is needed."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["action"]
            }
        },
        {
            "name": "export_document_copy",
            "description": "Export the active Fusion document as a local .f3d/.f3z archive copy after plan_document_management_action approves export_copy. Does not save, upload, version, open, activate, promote, or relink cloud data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_name": {"type": "string", "description": "Optional active document name. The tool refuses to activate another document."},
                    "target_path": {"type": "string", "description": "Absolute local .f3d or .f3z archive path."},
                    "reason": {"type": "string", "description": "Why this local document copy is needed."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["target_path", "reason", "requires_user_approval"]
            }
        },
        {
            "name": "inspect_render_workspace",
            "description": "Read-only render, viewport, camera, named-view, environment, appearance-count, and render-settings metadata report. Does not render or change scene state.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "plan_render_output",
            "description": "Read-only render output planner. Requires explicit camera or named view, absolute output path, resolution, visual style/environment choices, reason, and approval before any future render/export action.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "camera_name": {"type": "string", "description": "Camera name from inspect_render_workspace, e.g. activeViewport."},
                    "named_view": {"type": "string", "description": "Named view from inspect_render_workspace."},
                    "output_path": {"type": "string", "description": "Absolute output path for the planned render image."},
                    "width": {"type": "integer", "default": 1920},
                    "height": {"type": "integer", "default": 1080},
                    "visual_style": {"type": "string", "default": "shaded"},
                    "environment": {"type": "string", "description": "Optional explicit render environment/scene name."},
                    "background": {"type": "string", "description": "Optional explicit background setting."},
                    "reason": {"type": "string", "description": "Why the render output is needed."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "render_viewport_output",
            "description": "Capture a local viewport still to an explicit output path after plan_render_output approves it. Verifies the output file exists and is non-empty; this is not photoreal/cloud rendering.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "camera_name": {"type": "string", "description": "Use activeViewport for the current viewport camera."},
                    "named_view": {"type": "string", "description": "Optional named view to apply before capture."},
                    "output_path": {"type": "string", "description": "Absolute output PNG/image path."},
                    "width": {"type": "integer", "default": 1920},
                    "height": {"type": "integer", "default": 1080},
                    "visual_style": {"type": "string", "default": "shaded"},
                    "environment": {"type": "string", "description": "Optional explicit environment label recorded in the plan."},
                    "background": {"type": "string", "description": "Optional explicit background label recorded in the plan."},
                    "reason": {"type": "string", "description": "Why this render/viewport output is needed."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["output_path", "reason", "requires_user_approval"]
            }
        },
        {
            "name": "plan_mesh_conversion",
            "description": "Read-only preflight for mesh conversion, repair, reduction, or remeshing. Requires explicit target, intent, quality-loss acknowledgement, and reason before any mesh mutation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Mesh body name from inspect_mesh_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact mesh body entity token from inspect_mesh_bodies."},
                    "conversion_intent": {
                        "type": "string",
                        "enum": ["convert_to_brep", "repair_mesh", "reduce_mesh", "remesh"],
                        "default": "convert_to_brep"
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["new_body", "join", "cut"],
                        "default": "new_body",
                        "description": "Requested downstream BRep operation where applicable."
                    },
                    "tolerance": {"type": "string", "description": "Optional explicit conversion tolerance expression."},
                    "detail_level": {"type": "string", "description": "Optional explicit detail/quality setting for the intended operation."},
                    "acknowledge_quality_loss": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to acknowledge mesh conversion can lose detail or create heavy BRep geometry."
                    },
                    "reason": {"type": "string", "description": "Why conversion, repair, reduction, or remeshing is needed."}
                }
            }
        },
        {
            "name": "get_physical_properties",
            "description": "Read-only physical-property report for one body, an entity token, or all bodies. Returns mass, volume, area, density, center of mass, bounding box, material, and appearance metadata with Fusion raw units and mm conversions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {
                        "type": "string",
                        "description": "Optional body name or component/body key to inspect. Omit with no entity token to report all bodies."
                    },
                    "body_entity_token": {
                        "type": "string",
                        "description": "Optional exact BRepBody entity token from inspection tools."
                    },
                    "include_all": {
                        "type": "boolean",
                        "default": False,
                        "description": "When true, report every body in the active design. No mutation is performed."
                    }
                }
            }
        },
        {
            "name": "interference_check",
            "description": "Read-only broad-phase interference report for bodies. Reports axis-aligned bounding-box intersections and overlap estimates; does not claim exact Boolean interference volume.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional body name, component/body key, or list. Omit with no entity tokens to check all visible bodies."
                    },
                    "body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens from inspection tools."
                    },
                    "include_invisible": {"type": "boolean", "default": False},
                    "max_pairs": {"type": "integer", "default": 200}
                }
            }
        },
        {
            "name": "inspect_analysis_capabilities",
            "description": "Read-only probe for exact BRep analysis API availability. Reports whether the runtime exposes candidate exact interference and minimum-distance APIs before exact tools are enabled.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "exact_interference_check",
            "description": "Read-only exact BRep interference attempt using Fusion TemporaryBRepManager candidate APIs. Returns unsupported when exact APIs are unavailable and reports validatedExact=false until live fixture validation is complete.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional body name, component/body key, or list. Omit with no entity tokens to check all visible bodies."
                    },
                    "body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens from inspection tools."
                    },
                    "include_invisible": {"type": "boolean", "default": False},
                    "max_pairs": {"type": "integer", "default": 200}
                }
            }
        },
        {
            "name": "clearance_check",
            "description": "Read-only broad-phase clearance report between explicit target and tool body sets using bounding-box distance. Requires explicit minimum clearance and does not infer tolerances.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Target body name, component/body key, or list."
                    },
                    "tool_body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Tool/neighbor body name, component/body key, or list."
                    },
                    "target_body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens for target bodies."
                    },
                    "tool_body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens for tool bodies."
                    },
                    "minimum_clearance": {"type": "string", "default": "0 mm", "description": "Explicit minimum clearance expression, e.g. '0.5 mm'."},
                    "include_invisible": {"type": "boolean", "default": False},
                    "max_pairs": {"type": "integer", "default": 200}
                }
            }
        },
        {
            "name": "exact_clearance_check",
            "description": "Read-only exact minimum-distance attempt using Fusion measure-manager candidate APIs. Returns unsupported when exact APIs are unavailable and reports validatedExact=false until live fixture validation is complete.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Target body name, component/body key, or list."
                    },
                    "tool_body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Tool/neighbor body name, component/body key, or list."
                    },
                    "target_body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens for target bodies."
                    },
                    "tool_body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens for tool bodies."
                    },
                    "minimum_clearance": {"type": "string", "default": "0 mm", "description": "Explicit minimum clearance expression, e.g. '0.5 mm'."},
                    "include_invisible": {"type": "boolean", "default": False},
                    "max_pairs": {"type": "integer", "default": 200}
                }
            }
        },
        {
            "name": "inspect_sheet_metal_rules",
            "description": "Read-only sheet-metal rule and body metadata report. Returns active rule, exposed rule collection, thickness/bend/K-factor metadata when available, and blockers/warnings for non-sheet-metal designs.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "plan_sheet_metal_workflow",
            "description": "Read-only sheet-metal workflow planner. Validates explicit operation, target body, rule name, edge/face tokens, parameters, and reason before future flange, bend, unfold, refold, or flat-pattern workflows.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["create_flange", "create_bend", "unfold_sheet_metal", "refold_sheet_metal", "export_flat_pattern"]},
                    "body_name": {"type": "string", "description": "Exact sheet-metal body name or component/body key from inspect_sheet_metal_rules."},
                    "body_entity_token": {"type": "string", "description": "Exact sheet-metal body entity token from inspect_sheet_metal_rules."},
                    "edge_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Explicit edge entity token or tokens for flange/bend operations."
                    },
                    "face_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Explicit face entity token or tokens for bend/refold/unfold planning."
                    },
                    "rule_name": {"type": "string", "description": "Explicit sheet-metal rule name. Required for creation operations."},
                    "parameters": {"type": "object", "description": "Explicit operation parameters such as height, angle, bend radius, relief, or unfold station."},
                    "reason": {"type": "string", "description": "Required for sheet-metal topology-changing operations."}
                },
                "required": ["operation"]
            }
        },
        {
            "name": "create_flange",
            "description": "Create an explicit sheet-metal flange after plan_sheet_metal_workflow passes. Requires target body, edge entity tokens, rule name, parameters, and reason; returns unsupported when Fusion lacks a compatible flange API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact sheet-metal body name or component/body key from inspect_sheet_metal_rules."},
                    "body_entity_token": {"type": "string", "description": "Exact sheet-metal body entity token from inspect_sheet_metal_rules."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit edge entity token or tokens for the flange base."},
                    "rule_name": {"type": "string", "description": "Explicit sheet-metal rule name; never inferred."},
                    "parameters": {"type": "object", "description": "Explicit flange parameters such as height, angle, bend radius, relief, or direction."},
                    "reason": {"type": "string", "description": "Required reason for creating the flange."}
                },
                "required": ["edge_entity_tokens", "rule_name", "reason"]
            }
        },
        {
            "name": "create_bend",
            "description": "Create an explicit sheet-metal bend after plan_sheet_metal_workflow passes. Requires target body, edge/face tokens, rule name, parameters, and reason; returns unsupported when Fusion lacks a compatible bend API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact sheet-metal body name or component/body key from inspect_sheet_metal_rules."},
                    "body_entity_token": {"type": "string", "description": "Exact sheet-metal body entity token from inspect_sheet_metal_rules."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit edge entity token or tokens for the bend."},
                    "face_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit face entity token or tokens for the bend."},
                    "rule_name": {"type": "string", "description": "Explicit sheet-metal rule name; never inferred."},
                    "parameters": {"type": "object", "description": "Explicit bend parameters such as angle, radius, position, relief, or direction."},
                    "reason": {"type": "string", "description": "Required reason for creating the bend."}
                },
                "required": ["rule_name", "reason"]
            }
        },
        {
            "name": "unfold_sheet_metal",
            "description": "Unfold an explicit sheet-metal body after plan_sheet_metal_workflow and flat-pattern preflight pass. Requires a reason and returns unsupported when Fusion lacks a compatible unfold API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact sheet-metal body name or component/body key from inspect_sheet_metal_rules."},
                    "body_entity_token": {"type": "string", "description": "Exact sheet-metal body entity token from inspect_sheet_metal_rules."},
                    "face_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Optional explicit stationary face token or tokens when required by the runtime."},
                    "parameters": {"type": "object", "description": "Explicit unfold parameters supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Required reason for unfolding the body."}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "refold_sheet_metal",
            "description": "Refold an explicit sheet-metal body after plan_sheet_metal_workflow passes. Requires a reason and returns unsupported when Fusion lacks a compatible refold API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact sheet-metal body name or component/body key from inspect_sheet_metal_rules."},
                    "body_entity_token": {"type": "string", "description": "Exact sheet-metal body entity token from inspect_sheet_metal_rules."},
                    "face_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Optional explicit face token or tokens when required by the runtime."},
                    "parameters": {"type": "object", "description": "Explicit refold parameters supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Required reason for refolding the body."}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "inspect_surface_bodies",
            "description": "Read-only surface/solid body classification report with face counts, edge counts, best-effort open-edge candidates, and candidate repair paths. Does not repair or convert geometry.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional body name, component/body key, or list. Omit with no entity tokens to inspect all bodies."
                    },
                    "body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Optional exact BRepBody entity token or tokens from inspection tools."
                    },
                    "include_invisible": {"type": "boolean", "default": False},
                    "include_edges": {"type": "boolean", "default": False, "description": "If true, include all open-edge candidates instead of truncating the list."}
                }
            }
        },
        {
            "name": "plan_surface_repair",
            "description": "Read-only surface repair/creation plan validator. Requires explicit operation, target body/entity token, required edge/face tokens, parameters, and reason fields before future surface repair mutations.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["patch_surface", "stitch_surfaces", "thicken_surface", "trim_surface", "extend_surface", "create_ruled_surface"]},
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "edge_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Explicit edge entity token or tokens for patch/stitch/extend-style operations."
                    },
                    "face_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Explicit face entity token or tokens for trim/ruled-surface-style operations."
                    },
                    "parameters": {"type": "object", "description": "Explicit operation parameters such as thickness, tolerance, direction, or boundary mode."},
                    "reason": {"type": "string", "description": "Required for destructive or topology-changing repairs."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                },
                "required": ["operation"]
            }
        },
        {
            "name": "patch_surface",
            "description": "Create a bounded patch surface from explicit open-edge entity tokens after plan_surface_repair passes. Returns unsupported when Fusion does not expose a compatible patch surface API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit open-edge entity token or tokens to bound the patch."},
                    "parameters": {"type": "object", "description": "Explicit patch parameters supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Reason for the surface creation."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                },
                "required": ["edge_entity_tokens"]
            }
        },
        {
            "name": "stitch_surfaces",
            "description": "Stitch explicit surface edge tokens after plan_surface_repair passes. Requires a reason and returns unsupported when Fusion does not expose a compatible stitch API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit edge entity token or tokens to stitch."},
                    "parameters": {"type": "object", "description": "Explicit stitch parameters such as tolerance when supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Required reason for topology-changing repair."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                },
                "required": ["edge_entity_tokens", "reason"]
            }
        },
        {
            "name": "thicken_surface",
            "description": "Thicken explicit surface faces after plan_surface_repair passes. Requires a reason and returns unsupported when Fusion does not expose a compatible thicken API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "face_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Optional explicit face entity token or tokens to thicken; omit only when the runtime can thicken the whole target body."},
                    "parameters": {"type": "object", "description": "Explicit thicken parameters such as thickness/direction when supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Required reason for topology-changing repair."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "trim_surface",
            "description": "Trim explicit surface faces or edges after plan_surface_repair passes. Requires a reason and returns unsupported when Fusion does not expose a compatible trim API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit edge entity token or tokens used by the trim."},
                    "face_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit face entity token or tokens used by the trim."},
                    "parameters": {"type": "object", "description": "Explicit trim parameters supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Required reason for topology-changing repair."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "extend_surface",
            "description": "Extend explicit surface edge tokens after plan_surface_repair passes. Requires a reason and returns unsupported when Fusion does not expose a compatible extend API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit edge entity token or tokens to extend."},
                    "parameters": {"type": "object", "description": "Explicit extend parameters such as distance when supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Required reason for topology-changing repair."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                },
                "required": ["edge_entity_tokens", "reason"]
            }
        },
        {
            "name": "create_ruled_surface",
            "description": "Create a ruled surface from explicit edge or face tokens after plan_surface_repair passes. Returns unsupported when Fusion does not expose a compatible ruled-surface API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name or component/body key from inspect_surface_bodies."},
                    "body_entity_token": {"type": "string", "description": "Exact BRepBody entity token from inspect_surface_bodies."},
                    "edge_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit edge entity token or tokens used for the ruled surface."},
                    "face_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}], "description": "Explicit face entity token or tokens used for the ruled surface."},
                    "parameters": {"type": "object", "description": "Explicit ruled-surface parameters supported by the active Fusion runtime."},
                    "reason": {"type": "string", "description": "Reason for the surface creation."},
                    "allow_solid_body": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "inspect_simulation_workspace",
            "description": "Read-only Simulation workspace discovery. Reports whether a Simulation product and study collection are exposed without creating, meshing, solving, or exporting studies.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "list_simulation_studies",
            "description": "Read-only Simulation study listing. Reports study metadata, solve status, load/constraint/material/contact counts, mesh availability, and result counts when Fusion exposes them.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_details": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "plan_simulation_study",
            "description": "Read-only Simulation study plan validator. Requires explicit study type, target bodies, materials, loads, constraints, mesh settings, result outputs, and approval before any future Simulation mutation or solve.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "study_name": {"type": "string", "description": "Explicit Simulation study name."},
                    "study_type": {
                        "type": "string",
                        "enum": ["static_stress", "modal_frequencies", "thermal", "thermal_stress", "buckling", "shape_optimization", "event_simulation"]
                    },
                    "target_body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Target body name, component/body key, or names from inspection tools."
                    },
                    "target_body_entity_tokens": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Exact BRepBody entity token or tokens for study targets."
                    },
                    "materials": {"type": "object", "description": "Explicit material assignments or assumptions for each target."},
                    "loads": {"type": "object", "description": "Explicit load definitions, directions, magnitudes, and units."},
                    "constraints": {"type": "object", "description": "Explicit constraint definitions and target references."},
                    "contacts": {"type": "object", "description": "Optional explicit contact definitions."},
                    "mesh_settings": {"type": "object", "description": "Explicit mesh size/order/refinement settings."},
                    "result_outputs": {"type": "object", "description": "Explicit requested result plots/exports and output paths when applicable."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "inspect_manufacturing_workspace",
            "description": "Read-only CAM/manufacturing workspace availability report. Returns exposed product/setup metadata and blockers without creating setups, generating toolpaths, or posting output.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "inspect_electronics_workspace",
            "description": "Read-only Fusion Electronics/PCB workspace discovery. Reports exposed board, outline, component, net, connector-candidate, and linked metadata without editing electronics or mechanical data.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "plan_pcb_enclosure_fit",
            "description": "Read-only PCB-to-enclosure fit planner. Requires explicit board outline, keepouts, connectors, mounting holes, clearance rules, reason, and approval before any future electronics/mechanical bridge action.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "board_outline": {"type": "object", "description": "Explicit board outline dimensions, entity token, or coordinate references."},
                    "keepouts": {"type": "object", "description": "Explicit keepout regions and clearance zones."},
                    "connectors": {"type": "object", "description": "Explicit connector positions, envelopes, insertion directions, and service clearances."},
                    "mounting_holes": {"type": "object", "description": "Explicit mounting hole locations, diameters, bosses, inserts, or screw data."},
                    "clearance_rules": {"type": "object", "description": "Explicit board-to-wall, component, connector, fastener, and service clearance rules."},
                    "enclosure_body_name": {"type": "string", "description": "Optional target enclosure body name or component/body key from inspection tools."},
                    "enclosure_body_entity_token": {"type": "string", "description": "Optional exact BRepBody entity token for target enclosure geometry."},
                    "linked_mechanical_reference": {"type": "string", "description": "Optional explicit linked mechanical/electronics reference identifier."},
                    "reason": {"type": "string", "description": "Why PCB enclosure-fit planning is needed."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "inspect_drawing_documents",
            "description": "Read-only inspection of open Fusion drawing documents, sheets, drawing views, title blocks, tables, parts lists, and dimension counts when the Drawing API exposes them.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_sheets": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "preflight_drawing_creation",
            "description": "Read-only readiness check before creating or exporting a drawing. Checks saved active document, DrawingManager availability, optional PDF path validity, and unsaved-change warnings.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_pdf_path": {"type": "string", "description": "Optional absolute PDF path to validate before create_2d_drawing."}
                }
            }
        },
        {
            "name": "plan_drawing_views",
            "description": "Read-only drawing sheet/view planner. Validates explicit standard, sheet size/orientation, units, view orientation/style/scale, and optional PDF path without creating drawings or exports.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "standard": {"type": "string", "enum": ["ASME", "ISO"], "default": "ASME"},
                    "sheet_size": {"type": "string", "enum": ["A", "B", "C", "D", "E", "A4", "A3", "A2", "A1", "A0"], "default": "A"},
                    "sheet_orientation": {"type": "string", "enum": ["landscape", "portrait"], "default": "landscape"},
                    "units": {"type": "string", "enum": ["mm", "in"], "default": "mm"},
                    "views": {
                        "oneOf": [
                            {"type": "object"},
                            {"type": "array", "items": {"type": "object"}}
                        ],
                        "description": "Optional view object or array. Each view may include name, orientation, style, scale, placement, and source."
                    },
                    "title_block": {"type": "string", "description": "Optional explicit title-block name or identifier to carry into the plan."},
                    "export_pdf_path": {"type": "string", "description": "Optional absolute PDF path to validate alongside drawing creation preflight."}
                }
            }
        },
        {
            "name": "add_drawing_view",
            "description": "Add an explicit drawing view to an open drawing sheet after plan_drawing_views passes. Returns unsupported when the active drawing sheet lacks compatible drawingViews APIs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sheet_name": {"type": "string", "description": "Optional exact sheet name; defaults to sheet_index."},
                    "sheet_index": {"type": "integer", "default": 0},
                    "view": {"type": "object", "description": "Explicit view plan object with name, orientation, style, scale, placement, and source."},
                    "standard": {"type": "string", "enum": ["ASME", "ISO"], "default": "ASME"},
                    "sheet_size": {"type": "string", "enum": ["A", "B", "C", "D", "E", "A4", "A3", "A2", "A1", "A0"], "default": "A"},
                    "sheet_orientation": {"type": "string", "enum": ["landscape", "portrait"], "default": "landscape"},
                    "units": {"type": "string", "enum": ["mm", "in"], "default": "mm"},
                    "title_block": {"type": "string"},
                    "reason": {"type": "string", "description": "Required reason for changing the drawing."}
                },
                "required": ["view", "reason"]
            }
        },
        {
            "name": "add_drawing_dimension",
            "description": "Add a drawing dimension to an open drawing sheet from explicit inspected geometry entity tokens. Returns unsupported when compatible drawing dimension APIs are unavailable.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sheet_name": {"type": "string"},
                    "sheet_index": {"type": "integer", "default": 0},
                    "view_name": {"type": "string", "description": "Optional exact drawing view name."},
                    "geometry_entity_tokens": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                    "dimension_type": {"type": "string", "enum": ["linear", "aligned", "angular", "radial", "diameter"], "default": "linear"},
                    "placement": {"type": "object", "description": "Explicit placement data for the dimension text/leader."},
                    "text": {"type": "string", "description": "Optional dimension text override."},
                    "reason": {"type": "string", "description": "Required reason for changing the drawing."}
                },
                "required": ["geometry_entity_tokens", "reason"]
            }
        },
        {
            "name": "add_drawing_callout",
            "description": "Add a callout/note to an open drawing sheet with explicit text, optional target view/entity token, and placement. Returns unsupported when compatible note APIs are unavailable.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sheet_name": {"type": "string"},
                    "sheet_index": {"type": "integer", "default": 0},
                    "text": {"type": "string"},
                    "target_view_name": {"type": "string"},
                    "target_entity_token": {"type": "string"},
                    "placement": {"type": "object"},
                    "reason": {"type": "string", "description": "Required reason for changing the drawing."}
                },
                "required": ["text", "reason"]
            }
        },
        {
            "name": "add_parts_list",
            "description": "Add a parts list/BOM table to an open drawing sheet from an explicit source view name. Returns unsupported when compatible parts-list APIs are unavailable.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sheet_name": {"type": "string"},
                    "sheet_index": {"type": "integer", "default": 0},
                    "source_view_name": {"type": "string"},
                    "placement": {"type": "object"},
                    "bom_level": {"type": "string", "enum": ["first_level", "all_levels", "parts_only"], "default": "first_level"},
                    "reason": {"type": "string", "description": "Required reason for changing the drawing."}
                },
                "required": ["source_view_name", "reason"]
            }
        },
        {
            "name": "add_revision_table",
            "description": "Add a revision table to an open drawing sheet with explicit placement and optional initial revision metadata. Returns unsupported when compatible revision-table APIs are unavailable.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sheet_name": {"type": "string"},
                    "sheet_index": {"type": "integer", "default": 0},
                    "placement": {"type": "object"},
                    "initial_revision": {"type": "object"},
                    "reason": {"type": "string", "description": "Required reason for changing the drawing."}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "list_manufacturing_setups",
            "description": "Read-only list of exposed CAM/manufacturing setups and optional operation summaries. Does not infer stock, WCS, tools, feeds, speeds, or production parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_operations": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "inspect_operation",
            "description": "Read-only inspection of an exposed CAM/manufacturing operation by name or index, optionally scoped to a setup name. Does not generate toolpaths or post-process.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "operation_name": {"type": "string", "description": "Exact operation name to inspect."},
                    "setup_name": {"type": "string", "description": "Optional exact setup name to scope the search."},
                    "operation_index": {"type": "integer", "description": "Optional 0-based operation index within the setup."}
                }
            }
        },
        {
            "name": "plan_manufacturing_operation",
            "description": "Read-only CAM setup/operation plan validator. Requires explicit machine, stock, WCS, tool, feeds, speeds, post-processor, operation type, and user approval before future manufacturing mutations.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "setup_name": {"type": "string"},
                    "operation_name": {"type": "string"},
                    "operation_type": {"type": "string", "enum": ["2d_contour", "2d_pocket", "adaptive", "drill", "face", "trace"]},
                    "machine": {"type": "object", "description": "Explicit machine metadata such as id/name/model/controller."},
                    "stock": {"type": "object", "description": "Explicit stock dimensions/material/origin information."},
                    "wcs": {"type": "object", "description": "Explicit work coordinate system and origin/axis information."},
                    "tool": {"type": "object", "description": "Explicit cutting tool metadata such as id/name/diameter/flutes/material."},
                    "feeds": {"type": "object", "description": "Explicit positive numeric feed values."},
                    "speeds": {"type": "object", "description": "Explicit positive numeric spindle/surface-speed values."},
                    "post_processor": {"type": "object", "description": "Explicit post-processor id/name/path and output intent."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["setup_name", "operation_name", "operation_type", "machine", "stock", "wcs", "tool", "feeds", "speeds", "post_processor", "requires_user_approval"]
            }
        },
        {
            "name": "create_manufacturing_setup",
            "description": "Create a CAM/manufacturing setup only after plan_manufacturing_operation passes with explicit machine, stock, WCS, tool, feeds, speeds, post-processor, and user approval. Returns unsupported when Fusion lacks a compatible setup API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "setup_name": {"type": "string"},
                    "operation_name": {"type": "string"},
                    "operation_type": {"type": "string", "enum": ["2d_contour", "2d_pocket", "adaptive", "drill", "face", "trace"]},
                    "machine": {"type": "object"},
                    "stock": {"type": "object"},
                    "wcs": {"type": "object"},
                    "tool": {"type": "object"},
                    "feeds": {"type": "object"},
                    "speeds": {"type": "object"},
                    "post_processor": {"type": "object"},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["setup_name", "operation_name", "operation_type", "machine", "stock", "wcs", "tool", "feeds", "speeds", "post_processor", "requires_user_approval"]
            }
        },
        {
            "name": "create_manufacturing_operation",
            "description": "Create a CAM/manufacturing operation in an explicit setup only after plan_manufacturing_operation passes. Returns unsupported when Fusion lacks a compatible operation API.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "setup_name": {"type": "string"},
                    "operation_name": {"type": "string"},
                    "operation_type": {"type": "string", "enum": ["2d_contour", "2d_pocket", "adaptive", "drill", "face", "trace"]},
                    "machine": {"type": "object"},
                    "stock": {"type": "object"},
                    "wcs": {"type": "object"},
                    "tool": {"type": "object"},
                    "feeds": {"type": "object"},
                    "speeds": {"type": "object"},
                    "post_processor": {"type": "object"},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["setup_name", "operation_name", "operation_type", "machine", "stock", "wcs", "tool", "feeds", "speeds", "post_processor", "requires_user_approval"]
            }
        },
        {
            "name": "generate_toolpaths",
            "description": "Generate CAM toolpaths only after plan_manufacturing_operation passes and explicit user approval is present. Does not infer production parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "setup_name": {"type": "string"},
                    "operation_name": {"type": "string"},
                    "operation_type": {"type": "string", "enum": ["2d_contour", "2d_pocket", "adaptive", "drill", "face", "trace"]},
                    "machine": {"type": "object"},
                    "stock": {"type": "object"},
                    "wcs": {"type": "object"},
                    "tool": {"type": "object"},
                    "feeds": {"type": "object"},
                    "speeds": {"type": "object"},
                    "post_processor": {"type": "object"},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["setup_name", "operation_name", "operation_type", "machine", "stock", "wcs", "tool", "feeds", "speeds", "post_processor", "requires_user_approval"]
            }
        },
        {
            "name": "post_process",
            "description": "Post-process CAM output to an explicit absolute output path only after plan_manufacturing_operation passes and explicit user approval is present.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "output_path": {"type": "string", "description": "Absolute NC/code output path."},
                    "setup_name": {"type": "string"},
                    "operation_name": {"type": "string"},
                    "operation_type": {"type": "string", "enum": ["2d_contour", "2d_pocket", "adaptive", "drill", "face", "trace"]},
                    "machine": {"type": "object"},
                    "stock": {"type": "object"},
                    "wcs": {"type": "object"},
                    "tool": {"type": "object"},
                    "feeds": {"type": "object"},
                    "speeds": {"type": "object"},
                    "post_processor": {"type": "object"},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["output_path", "setup_name", "operation_name", "operation_type", "machine", "stock", "wcs", "tool", "feeds", "speeds", "post_processor", "requires_user_approval"]
            }
        },
        {
            "name": "preflight_flat_pattern",
            "description": "Read-only flat-pattern readiness check for an explicit or detected sheet-metal body. Reports active rule, target body metadata, flatPattern availability, blockers, and warnings without exporting.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Optional exact body name or component/body key from inspection."},
                    "body_entity_token": {"type": "string", "description": "Optional exact BRepBody entity token from inspection tools."}
                }
            }
        },
        {
            "name": "query_selection",
            "description": "Describe currently selected entities in the Fusion UI in agent-friendly terms (e.g., coordinates, type, owning component). Instructions: Ask the user to select the target entity in the Fusion UI if it's too difficult to find programmatically. Use this tool to read their selection.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_current_selection",
            "description": "Return details about the currently selected Fusion UI entities, including objectType, tempId, entityToken where available, and useful geometry properties such as face area or edge length.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "inspect_selection_sets",
            "description": "Read named Fusion selection sets and their contents. Use this before targeted multibody export workflows when active UI selection is insufficient.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional selection set name or names to inspect. Omit to list all selection sets."
                    },
                    "include_entities": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "inspect_sketch",
            "description": "Return structured sketch details including local-to-model coordinate mapping, points, lines, arcs, circles, dimensions, geometric constraints, dimension parameters, and referenced user parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Exact sketch name to inspect."}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "get_projected_geometry_sources",
            "description": "Return projected/reference sketch curves and points with source entity, source body/component, and inferred owner feature metadata when Fusion exposes it.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Exact sketch name whose projected/reference geometry should be inspected."}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "inspect_feature",
            "description": "Return structured timeline feature details including operation, extent definitions, health state, participant bodies, result bodies, feature model parameters, and referenced user parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name to inspect."}
                },
                "required": ["feature_name"]
            }
        },
        {
            "name": "get_sketch_parameters",
            "description": "Return only the dimension/model parameters owned by a sketch, including roles, expressions, values, dimensions, and referenced user parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Exact sketch name whose parameters should be extracted."}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "get_feature_parameters",
            "description": "Return only the model parameters owned by a timeline feature, including roles, expressions, values, and referenced user parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name whose parameters should be extracted."}
                },
                "required": ["feature_name"]
            }
        },
        {
            "name": "get_parameter_usage",
            "description": "Find sketch dimensions and feature parameters that directly use a model parameter or reference a user parameter by name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "parameter_name": {"type": "string", "description": "User parameter or model parameter name to search for, e.g. screenWidth or d228."}
                },
                "required": ["parameter_name"]
            }
        },
        {
            "name": "get_feature_dependencies",
            "description": "Return a best-effort dependency report for a timeline feature, including direct inputs, nearby predecessors, and likely downstream consumers with confidence levels.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name to analyze."}
                },
                "required": ["feature_name"]
            }
        },
        {
            "name": "get_dependency_graph",
            "description": "Return a best-effort global dependency graph across timeline features, sketches, parameters, profile sketches, projected geometry, result bodies, and likely downstream consumers.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "assess_change_impact",
            "description": "Assess likely impact before editing, suppressing, deleting, or rebuilding timeline features. Summarizes direct inputs, downstream consumers, and a risk level without modifying the model.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_features": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Feature name or list of feature names to assess."
                    },
                    "change_type": {
                        "type": "string",
                        "default": "edit",
                        "description": "Planned operation label, e.g. edit, suppress, delete, rebuild, parameterize."
                    }
                },
                "required": ["target_features"]
            }
        },
        {
            "name": "plan_parameterization",
            "description": "Read-only planner for converting existing sketches/features to user-parameter-driven expressions without intentionally changing geometry. Classifies existing dimensions and feature parameters into already-parameterized, safe expression candidates, inspection-required, and rebuild-candidate buckets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_sketches": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional sketch name or list of sketch names to analyze. Omit to analyze all sketches."
                    },
                    "target_features": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional feature/timeline name or list of names to analyze. Omit to analyze all timeline features."
                    }
                }
            }
        },
        {
            "name": "map_coordinates",
            "description": "Map a 3D point between a sketch's local coordinate system, root model space, and an optional target component/occurrence using Fusion transforms.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "point": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                        "description": "Point as [x, y, z]."
                    },
                    "from_sketch": {"type": "string", "description": "Sketch whose local coordinate system should be used."},
                    "to_component": {"type": "string", "default": "root", "description": "Component or occurrence name for target component-space coordinates."},
                    "direction": {
                        "type": "string",
                        "enum": ["sketch_to_model", "model_to_sketch", "both"],
                        "default": "both",
                        "description": "Transform direction. 'both' returns both interpretations for verification."
                    }
                },
                "required": ["point", "from_sketch"]
            }
        },
        {
            "name": "create_sketch",
            "description": "Create a named sketch on a component construction plane and return coordinate-system mapping for safe local/model alignment.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the new sketch."},
                    "plane": {"type": "string", "default": "xy", "description": "Plane: xy, xz, yz, or a named construction plane in the target component."},
                    "component": {"type": "string", "default": "root", "description": "Component or occurrence name. Defaults to root."}
                },
                "required": ["name"]
            }
        },
        {
            "name": "draw_line",
            "description": "Draw a line in an existing sketch using local sketch coordinates. Returns structured line metadata including local/world endpoints when Fusion exposes them.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string"},
                    "start": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
                    "end": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
                    "name": {"type": "string"},
                    "construction": {"type": "boolean", "default": False}
                },
                "required": ["sketch_name", "start", "end"]
            }
        },
        {
            "name": "draw_rectangle",
            "description": "Draw a rectangle in an existing sketch using local sketch coordinates. Accepts either corner1/corner2 or center plus width/height.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string"},
                    "corner1": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
                    "corner2": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
                    "center": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
                    "width": {"description": "Width as model units expression or numeric internal units."},
                    "height": {"description": "Height as model units expression or numeric internal units."},
                    "name_prefix": {"type": "string"},
                    "construction": {"type": "boolean", "default": False}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "draw_circle",
            "description": "Draw a circle in an existing sketch using local sketch coordinates. Radius can be a Fusion unit expression such as '5 mm'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string"},
                    "center": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 3},
                    "radius": {"description": "Radius as a Fusion unit expression or numeric internal units."},
                    "name": {"type": "string"},
                    "construction": {"type": "boolean", "default": False}
                },
                "required": ["sketch_name", "center", "radius"]
            }
        },
        {
            "name": "project_geometry",
            "description": "Project a selected or named body/sketch/entity token into a sketch, returning projected entity metadata. Prefer entity_token or UI selection for exact edges/faces.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string"},
                    "entity_name": {"type": "string", "description": "Name of a body or sketch to project."},
                    "entity_token": {"type": "string", "description": "Fusion entity token to project when available."},
                    "source_sketch_name": {"type": "string", "description": "Project a curve from this source sketch by curve_type and curve_index."},
                    "curve_type": {
                        "type": "string",
                        "enum": ["lines", "circles", "arcs", "ellipses", "fittedSplines", "fixedSplines", "conics"],
                        "default": "lines"
                    },
                    "curve_index": {"type": "integer", "default": 0},
                    "use_selection": {"type": "boolean", "default": False},
                    "selection_indices": {"type": "array", "items": {"type": "integer"}}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "get_body_edges",
            "description": "Return indexed edge metadata for a named body, including entity tokens, lengths, geometry type, endpoints, and midpoint when available. Use before fillet_feature or chamfer_feature to choose explicit edge indices.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name to inspect."},
                    "edge_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional subset of 0-based edge indices. Omit to return all edges."
                    }
                },
                "required": ["body_name"]
            }
        },
        {
            "name": "get_body_faces",
            "description": "Return indexed face metadata for a named body, including entity tokens, area, geometry type, and centroid when available. Use before shell_body, offset_face_or_press_pull, or selected-face workflows to choose explicit face indices.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name to inspect."},
                    "face_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional subset of 0-based face indices. Omit to return all faces."
                    }
                },
                "required": ["body_name"]
            }
        },
        {
            "name": "offset_face_or_press_pull",
            "description": "Create a controlled Offset Face feature on explicit face indices of a named body or selected BRep faces. This covers the face-offset branch of Press Pull only; use extrude_feature or fillet_feature for other Press Pull outcomes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Name of the body whose faces should be offset. Required unless use_selection=true, body_entity_token is supplied, or face_entity_tokens infer the body."},
                    "body_entity_token": {"type": "string", "description": "Optional Fusion entity token for the target BRep body."},
                    "face_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Explicit 0-based face indices on the body. Use get_body_faces first."
                    },
                    "face_entity_tokens": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Fusion entity tokens for exact BRep face targeting, usually from get_body_faces."
                    },
                    "distance": {"type": "string", "description": "Fusion distance expression, e.g. '1 mm' or '-0.5 mm'. Positive follows the face normal."},
                    "name": {"type": "string", "description": "Optional name for the created Offset Face feature."},
                    "use_selection": {"type": "boolean", "default": False, "description": "If true, offset currently selected BRep faces instead of body_name/face_indices."}
                },
                "required": ["distance"]
            }
        },
        {
            "name": "extrude_feature",
            "description": "Create an extrusion from a named sketch profile with explicit NewBody/Join/Cut/Intersect operation and built-in before/after design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Sketch containing the profile to extrude."},
                    "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the sketch."},
                    "distance": {"type": "string", "description": "Fusion distance expression, e.g. '10 mm' or 'height / 2'."},
                    "operation": {
                        "type": "string",
                        "enum": ["NewBody", "Join", "Cut", "Intersect", "new_body", "join", "cut", "intersect"],
                        "description": "Required explicit feature operation. Do not guess."
                    },
                    "name": {"type": "string", "description": "Optional name for the created extrude feature."},
                    "body_name": {"type": "string", "description": "Optional name for the first result body."},
                    "participant_body_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit participant bodies for Join/Cut/Intersect operations."
                    }
                },
                "required": ["sketch_name", "distance", "operation"]
            }
        },
        {
            "name": "extrude_existing_profile",
            "description": "Hardened extrusion wrapper for an existing sketch profile. Reports profile counts, failure stage, participant-body resolution, and recovery actions when Fusion rejects profile reuse.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Sketch containing the existing profile to extrude."},
                    "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the sketch."},
                    "distance": {"type": "string", "description": "Fusion distance expression, e.g. '10 mm' or 'height / 2'."},
                    "operation": {
                        "type": "string",
                        "enum": ["NewBody", "Join", "Cut", "Intersect", "new_body", "join", "cut", "intersect"],
                        "description": "Required explicit feature operation. Do not guess."
                    },
                    "name": {"type": "string", "description": "Optional name for the created extrude feature."},
                    "body_name": {"type": "string", "description": "Optional name for the first result body."},
                    "participant_body_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit participant bodies for Join/Cut/Intersect operations."
                    }
                },
                "required": ["sketch_name", "distance", "operation"]
            }
        },
        {
            "name": "copy_profile_loop",
            "description": "Copy/project only one loop from an existing sketch profile into a destination sketch. Use this when a source sketch contains reference/logo curves but only the outer profile loop should be reused.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_sketch_name": {"type": "string", "description": "Sketch containing the source profile."},
                    "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the source sketch."},
                    "loop_index": {"type": "integer", "default": 0, "description": "0-based profile-loop index. Ignored when outer_loop=true."},
                    "outer_loop": {"type": "boolean", "default": False, "description": "Copy the profile loop Fusion marks as outer."},
                    "destination_sketch_name": {"type": "string", "description": "Existing destination sketch name or name for a new destination sketch."},
                    "destination_plane": {"type": "string", "description": "Optional destination plane: xy/xz/yz or a construction plane name."},
                    "construction": {"type": "boolean", "default": False, "description": "Mark copied/projected curves as construction geometry."}
                },
                "required": ["source_sketch_name"]
            }
        },
        {
            "name": "offset_profile_loop",
            "description": "Offset only one loop from an existing sketch profile, instead of all curves in the sketch. Use this when projected logo/reference curves make create_sketch_offset too broad.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Sketch containing the source profile loop."},
                    "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the sketch."},
                    "loop_index": {"type": "integer", "default": 0, "description": "0-based profile-loop index. Ignored when outer_loop=true."},
                    "outer_loop": {"type": "boolean", "default": False, "description": "Offset the profile loop Fusion marks as outer."},
                    "offset_distance": {"type": "string", "description": "Fusion distance expression, e.g. '0.2 mm' or '-0.15 mm'."},
                    "construction": {"type": "boolean", "default": False, "description": "Mark offset curves as construction geometry."}
                },
                "required": ["sketch_name", "offset_distance"]
            }
        },
        {
            "name": "create_insert_socket",
            "description": "Create a removable insert plate and matching socket cut from one existing sketch profile loop. Copies only the selected loop into a work sketch, creates plate and cutter bodies, verifies broad-phase alignment, cuts the target body, and reports cleanup/recovery details.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source_sketch_name": {"type": "string", "description": "Source sketch containing the profile loop to reuse."},
                    "target_body_name": {"type": "string", "description": "Body to cut the matching socket into."},
                    "insert_thickness": {"type": "string", "description": "Plate thickness, e.g. '2 mm'."},
                    "clearance": {"type": "string", "default": "0 mm", "description": "Optional lateral cutter clearance offset. Inspect the generated work sketch if this creates multiple profiles."},
                    "mode": {"type": "string", "enum": ["flush", "proud", "recessed"], "default": "flush"},
                    "profile_index": {"type": "integer", "default": 0},
                    "loop_index": {"type": "integer", "default": 0},
                    "outer_loop": {"type": "boolean", "default": True},
                    "work_sketch_name": {"type": "string"},
                    "destination_plane": {"type": "string", "description": "Optional xy/xz/yz or named construction plane for the generated work sketch."},
                    "plate_body_name": {"type": "string"},
                    "plate_feature_name": {"type": "string"},
                    "cutter_body_name": {"type": "string"},
                    "cutter_feature_name": {"type": "string"},
                    "socket_feature_name": {"type": "string"},
                    "socket_depth": {"type": "string", "description": "Socket cut depth. Defaults to insert_thickness."},
                    "cutter_profile_index": {"type": "integer", "default": 0, "description": "Profile index in the generated work sketch used for the cutter body."},
                    "keep_cutter_body": {"type": "boolean", "default": False},
                    "allow_alignment_blockers": {"type": "boolean", "default": False, "description": "Allow the cut even if broad-phase plate/cutter verification reports blockers."},
                    "reason": {"type": "string", "description": "Required reason for this topology-changing insert/socket workflow."}
                },
                "required": ["source_sketch_name", "target_body_name", "insert_thickness", "reason"]
            }
        },
        {
            "name": "revolve_feature",
            "description": "Create a revolve from a named sketch profile around a standard, named, or selected axis with explicit NewBody/Join/Cut/Intersect operation and built-in before/after design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Sketch containing the profile to revolve."},
                    "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the sketch."},
                    "axis_name": {"type": "string", "default": "z", "description": "Revolve axis: x, y, z, or a named construction axis."},
                    "use_selected_axis": {"type": "boolean", "default": False, "description": "If true, use the currently selected construction axis or linear BRep edge."},
                    "angle": {"type": "string", "default": "360 deg", "description": "Fusion angle expression, e.g. '360 deg' or '180 deg'."},
                    "operation": {
                        "type": "string",
                        "enum": ["NewBody", "Join", "Cut", "Intersect", "new_body", "join", "cut", "intersect"],
                        "description": "Required explicit feature operation. Do not guess."
                    },
                    "name": {"type": "string", "description": "Optional name for the created revolve feature."},
                    "body_name": {"type": "string", "description": "Optional name for the first result body."},
                    "participant_body_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit participant bodies for Join/Cut/Intersect operations."
                    }
                },
                "required": ["sketch_name", "operation"]
            }
        },
        {
            "name": "loft_feature",
            "description": "Create a solid loft from an ordered list of named sketch profiles with explicit NewBody/Join/Cut/Intersect operation and built-in before/after design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "properties": {
                                "sketch_name": {"type": "string", "description": "Sketch containing this loft section profile."},
                                "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the sketch."}
                            },
                            "required": ["sketch_name"]
                        },
                        "description": "Ordered loft sections. The first item is the first profile; order matters."
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["NewBody", "Join", "Cut", "Intersect", "new_body", "join", "cut", "intersect"],
                        "description": "Required explicit feature operation. Do not guess."
                    },
                    "name": {"type": "string", "description": "Optional name for the created loft feature."},
                    "body_name": {"type": "string", "description": "Optional name for the first result body."},
                    "participant_body_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit participant bodies for Join/Cut/Intersect operations."
                    }
                },
                "required": ["sections", "operation"]
            }
        },
        {
            "name": "sweep_feature",
            "description": "Create a solid sweep from a named sketch profile along an explicit indexed curve in a named path sketch, with required operation and before/after design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "profile_sketch_name": {"type": "string", "description": "Sketch containing the profile to sweep."},
                    "profile_index": {"type": "integer", "default": 0, "description": "0-based profile index in the profile sketch."},
                    "path_sketch_name": {"type": "string", "description": "Sketch containing the path curve."},
                    "path_curve_index": {"type": "integer", "default": 0, "description": "0-based curve index from the path sketch. Inspect the sketch first."},
                    "chain_path": {"type": "boolean", "default": False, "description": "If true, let Fusion chain connected path curves from the selected curve."},
                    "operation": {
                        "type": "string",
                        "enum": ["NewBody", "Join", "Cut", "Intersect", "new_body", "join", "cut", "intersect"],
                        "description": "Required explicit feature operation. Do not guess."
                    },
                    "name": {"type": "string", "description": "Optional name for the created sweep feature."},
                    "body_name": {"type": "string", "description": "Optional name for the first result body."},
                    "participant_body_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional explicit participant bodies for Join/Cut/Intersect operations."
                    }
                },
                "required": ["profile_sketch_name", "path_sketch_name", "operation"]
            }
        },
        {
            "name": "fillet_feature",
            "description": "Create a constant-radius fillet on explicit edge indices or edge entity tokens with built-in before/after design-state comparison. Inspect edges before choosing targets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Name of the body whose edges should be filleted."},
                    "body_entity_token": {"type": "string", "description": "Optional Fusion entity token for the target BRep body."},
                    "edge_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Explicit 0-based edge indices on the body. Required unless edge_entity_tokens are supplied."
                    },
                    "edge_entity_tokens": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Fusion entity tokens for exact BRep edge targeting, usually from get_body_edges."
                    },
                    "radius": {"type": "string", "description": "Fusion radius expression, e.g. '1 mm'."},
                    "name": {"type": "string", "description": "Optional name for the created fillet feature."},
                    "tangent_chain": {"type": "boolean", "default": True}
                },
                "required": ["radius"]
            }
        },
        {
            "name": "chamfer_feature",
            "description": "Create an equal-distance chamfer on explicit edge indices or edge entity tokens with built-in before/after design-state comparison. Inspect edges before choosing targets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Name of the body whose edges should be chamfered."},
                    "body_entity_token": {"type": "string", "description": "Optional Fusion entity token for the target BRep body."},
                    "edge_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Explicit 0-based edge indices on the body. Required unless edge_entity_tokens are supplied."
                    },
                    "edge_entity_tokens": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Fusion entity tokens for exact BRep edge targeting, usually from get_body_edges."
                    },
                    "distance": {"type": "string", "description": "Fusion chamfer distance expression, e.g. '1 mm'."},
                    "name": {"type": "string", "description": "Optional name for the created chamfer feature."},
                    "tangent_chain": {"type": "boolean", "default": True}
                },
                "required": ["distance"]
            }
        },
        {
            "name": "shell_body",
            "description": "Shell a named or entity-token-targeted body with explicit wall thickness and optional indexed or token-targeted open faces. Use get_body_faces first when opening specific faces.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Name of the body to shell."},
                    "body_entity_token": {"type": "string", "description": "Optional Fusion entity token for the BRep body to shell."},
                    "thickness": {"type": "string", "description": "Inside or default shell thickness, e.g. '2 mm'."},
                    "open_face_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Optional 0-based face indices to remove/open while shelling."
                    },
                    "open_face_entity_tokens": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional Fusion entity tokens for exact open-face targeting, usually from get_body_faces."
                    },
                    "name": {"type": "string", "description": "Optional name for the created shell feature."},
                    "thickness_side": {"type": "string", "enum": ["inside", "outside", "both"], "default": "inside"},
                    "outside_thickness": {"type": "string", "description": "Outside thickness for outside or both mode. Defaults to thickness."},
                    "tangent_chain": {"type": "boolean", "default": True}
                },
                "required": ["thickness"]
            }
        },

        {
            "name": "create_parametric_feature",
            "description": "Create a named sketch as a safe parametric starting point and return design-state comparison. Use specialized tools like create_box, create_cylinder, create_coil, create_sketch_offset, set_parameter, and modify_parameters for other operations.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "feature_type": {"type": "string", "enum": ["sketch"]},
                    "parameters": {"type": "object"}
                },
                "required": ["feature_type", "parameters"]
            }
        },
        {
            "name": "create_box",
            "description": "Create a parametric 3D box (rectangular prism) by sketching a rectangle on a plane and extruding it, returning design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Descriptive name for the created box body."},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "description": "The base construction plane. Default: xy"},
                    "length": {"type": "string", "description": "Length along X axis (e.g., '10 cm' or '100 mm')"},
                    "width": {"type": "string", "description": "Width along Z axis (e.g., '10 cm' or '100 mm')"},
                    "height": {"type": "string", "description": "Extrusion height along normal (e.g., '10 cm' or '100 mm')"},
                    "x_offset": {"type": "string", "description": "Center position offset on plane U axis (e.g., '0 cm')"},
                    "z_offset": {"type": "string", "description": "Center position offset on plane V axis (e.g., '0 cm')"},
                    "operation": {"type": "string", "enum": ["new_body", "join", "cut", "intersect"], "description": "Feature operation type."}
                },
                "required": ["length", "width", "height"]
            }
        },
        {
            "name": "create_cylinder",
            "description": "Create a parametric 3D cylinder by sketching a circle on a plane and extruding it, returning design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Descriptive name for the cylinder."},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "description": "The base construction plane. Default: xy"},
                    "radius": {"type": "string", "description": "Cylinder radius (e.g., '5 cm')"},
                    "height": {"type": "string", "description": "Extrusion height (e.g., '10 cm')"},
                    "x_offset": {"type": "string", "description": "Center position offset on plane U axis (e.g., '0 cm')"},
                    "z_offset": {"type": "string", "description": "Center position offset on plane V axis (e.g., '0 cm')"},
                    "operation": {"type": "string", "enum": ["new_body", "join", "cut", "intersect"], "description": "Feature operation type."}
                },
                "required": ["radius", "height"]
            }
        },
        {
            "name": "create_rounded_rectangle_body",
            "description": "Create an extruded rounded-rectangle body from length expressions. Useful for brackets, plates, trays, enclosures, and other rounded rectangular CAD geometry without raw scripts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "default": "xy"},
                    "width": {"type": "string", "description": "Overall width, e.g. '180 mm'."},
                    "height": {"type": "string", "description": "Overall height, e.g. '70 mm'."},
                    "thickness": {"type": "string", "description": "Extrude distance, e.g. '5 mm'."},
                    "corner_radius": {"type": "string", "description": "Corner radius, e.g. '4 mm'."},
                    "x_offset": {"type": "string", "default": "0 mm"},
                    "y_offset": {"type": "string", "default": "0 mm"},
                    "operation": {"type": "string", "enum": ["new_body", "join", "cut", "intersect"], "default": "new_body"},
                    "hide_sketch": {"type": "boolean", "default": True}
                },
                "required": ["width", "height", "thickness", "corner_radius"]
            }
        },
        {
            "name": "create_rounded_slot_cut",
            "description": "Cut a rounded slot into a named body from length expressions, with explicit target body and axis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_name": {"type": "string"},
                    "name": {"type": "string"},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "default": "xy"},
                    "length": {"type": "string", "description": "Overall slot length, e.g. '24 mm'."},
                    "width": {"type": "string", "description": "Slot width / end diameter, e.g. '9 mm'."},
                    "cut_depth": {"type": "string", "description": "Cut extrusion distance, e.g. '8 mm'."},
                    "x_offset": {"type": "string", "default": "0 mm"},
                    "y_offset": {"type": "string", "default": "0 mm"},
                    "axis": {"type": "string", "enum": ["x", "y"], "default": "x"},
                    "hide_sketch": {"type": "boolean", "default": True}
                },
                "required": ["target_body_name", "length", "width", "cut_depth"]
            }
        },
        {
            "name": "create_rounded_pocket",
            "description": "Cut a shallow rounded-rectangle pocket or recess into a named body from length expressions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_name": {"type": "string"},
                    "name": {"type": "string"},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "default": "xy"},
                    "width": {"type": "string", "description": "Overall pocket width, e.g. '40 mm'."},
                    "height": {"type": "string", "description": "Overall pocket height, e.g. '20 mm'."},
                    "depth": {"type": "string", "description": "Pocket cut depth, e.g. '2 mm'."},
                    "corner_radius": {"type": "string", "description": "Corner radius, e.g. '3 mm'."},
                    "x_offset": {"type": "string", "default": "0 mm"},
                    "y_offset": {"type": "string", "default": "0 mm"},
                    "cut_direction": {"type": "string", "enum": ["positive", "negative"], "default": "positive"},
                    "use_selected_plane": {"type": "boolean", "default": False, "description": "Use the selected construction plane or planar face for pocket placement."},
                    "hide_sketch": {"type": "boolean", "default": True}
                },
                "required": ["target_body_name", "width", "height", "depth", "corner_radius"]
            }
        },
        {
            "name": "create_counterbore_hole_pattern",
            "description": "Cut repeated counterbore holes into a named body from explicit point coordinates and hole dimensions.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_name": {"type": "string"},
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 2,
                            "maxItems": 2
                        },
                        "description": "List of [x, y] length-expression coordinates, e.g. [['10 mm', '5 mm']]."
                    },
                    "name": {"type": "string"},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "default": "xy"},
                    "hole_diameter": {"type": "string"},
                    "counterbore_diameter": {"type": "string"},
                    "counterbore_depth": {"type": "string"},
                    "through_depth": {"type": "string"},
                    "hide_sketch": {"type": "boolean", "default": True}
                },
                "required": ["target_body_name", "points", "hole_diameter", "counterbore_diameter", "counterbore_depth", "through_depth"]
            }
        },
        {
            "name": "create_hole_pattern",
            "description": "Cut a general hole pattern into a named body. Supports explicit, rectangular, and circular point generation plus through, blind, counterbore, and true conical countersink cuts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_name": {"type": "string"},
                    "name": {"type": "string"},
                    "hole_type": {"type": "string", "enum": ["through", "blind", "counterbore", "countersink"], "default": "through"},
                    "base_plane": {"type": "string", "enum": ["xy", "xz", "yz"], "default": "xy"},
                    "hole_diameter": {"type": "string"},
                    "cut_depth": {"type": "string"},
                    "points": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                        "description": "Explicit [x, y] length-expression points."
                    },
                    "pattern_type": {"type": "string", "enum": ["explicit", "rectangular", "circular"], "default": "explicit"},
                    "origin": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                    "spacing": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                    "count": {
                        "oneOf": [
                            {"type": "integer"},
                            {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}
                        ]
                    },
                    "center": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
                    "radius": {"type": "string"},
                    "start_angle_deg": {"type": "number", "default": 0},
                    "total_angle_deg": {"type": "number", "default": 360},
                    "counterbore_diameter": {"type": "string"},
                    "counterbore_depth": {"type": "string"},
                    "countersink_diameter": {"type": "string"},
                    "countersink_depth": {"type": "string"},
                    "cut_direction": {"type": "string", "enum": ["positive", "negative"], "default": "positive"},
                    "hide_sketch": {"type": "boolean", "default": True}
                },
                "required": ["target_body_name", "hole_diameter", "cut_depth"]
            }
        },
        {
            "name": "mirror_features_or_bodies",
            "description": "Mirror named bodies, named timeline features, or selected entities across a standard plane, named construction plane, or selected planar face.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the created mirror feature."},
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Body name or names to mirror."
                    },
                    "feature_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Timeline feature name or names to mirror."
                    },
                    "mirror_plane_name": {"type": "string", "default": "yz", "description": "Standard plane xy/xz/yz or named construction plane."},
                    "use_selected_plane": {"type": "boolean", "default": False, "description": "Use the selected construction plane or planar face as the mirror plane."},
                    "use_selected_entities": {"type": "boolean", "default": False, "description": "Mirror currently selected entities in addition to named bodies/features."}
                }
            }
        },
        {
            "name": "pattern_feature",
            "description": "Create a rectangular or circular pattern from named bodies, named timeline features, or selected entities.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the created pattern feature."},
                    "pattern_type": {"type": "string", "enum": ["rectangular", "circular"], "default": "rectangular"},
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Body name or names to pattern."
                    },
                    "feature_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Timeline feature name or names to pattern."
                    },
                    "use_selected_entities": {"type": "boolean", "default": False},
                    "direction_one_axis": {"type": "string", "default": "x", "description": "Rectangular pattern first direction: x, y, z, or named construction axis."},
                    "quantity_one": {"type": "integer", "default": 2},
                    "distance_one": {"type": "string", "default": "10 mm"},
                    "direction_two_axis": {"type": "string", "description": "Optional second rectangular direction: x, y, z, or named construction axis."},
                    "quantity_two": {"type": "integer"},
                    "distance_two": {"type": "string"},
                    "axis_name": {"type": "string", "default": "z", "description": "Circular pattern axis: x, y, z, or named construction axis."},
                    "use_selected_axis": {"type": "boolean", "default": False},
                    "quantity": {"type": "integer", "default": 2},
                    "total_angle": {"type": "string", "default": "360 deg"},
                    "distance_type": {"type": "string", "enum": ["spacing", "extent"], "default": "spacing"},
                    "compute_option": {"type": "string", "enum": ["optimized", "identical", "adjust"], "default": "optimized"}
                }
            }
        },
        {
            "name": "create_coil",
            "description": "Create a coil-like helical pipe feature in Fusion 360 and return design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the pipe body."},
                    "base_plane_name": {"type": "string", "description": "Construction plane name or xy/xz/yz."},
                    "center_point_name": {"type": "string", "description": "Construction or sketch point name to use as center."},
                    "diameter": {"type": "string", "description": "Coil centerline diameter, e.g., '2 cm'."},
                    "height": {"type": "string", "description": "Coil height, e.g., '4 cm'."},
                    "revolutions": {"type": "number", "description": "Number of revolutions."},
                    "section_size": {"type": "string", "description": "Pipe section size/diameter, e.g., '0.2 cm'."},
                    "section_type": {"type": "string", "enum": ["circular", "square", "triangular"]},
                    "operation": {"type": "string", "enum": ["new_body", "join", "cut", "intersect"]},
                    "clockwise": {"type": "boolean", "description": "True for clockwise rotation."},
                    "points_per_revolution": {"type": "integer"},
                    "create_path_sketch": {"type": "boolean"},
                    "hollow_thickness": {"type": "string"}
                },
                "required": ["diameter", "height", "revolutions", "section_size"]
            }
        },
        {
            "name": "modify_parameters",
            "description": "Safely edit user parameters with before/after validation. Instructions: Check existing parameters with `inspect_design` before modifying. Ensure units are explicitly stated if required.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "param_name": {"type": "string"},
                    "new_expression": {"type": "string"}
                },
                "required": ["param_name", "new_expression"]
            }
        },
        {
            "name": "list_documents",
            "description": "List all open documents in Fusion 360, indicating which one is active and if they have unsaved changes.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "set_active_document",
            "description": "Switch the active document/tab in Fusion 360 by specifying its name or index.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the target document tab (e.g., 'BoxModel v1')."},
                    "index": {"type": "integer", "description": "Index of the document tab (0-based)."}
                }
            }
        },
        {
            "name": "create_design_document",
            "description": "Create a new unsaved Fusion design document after document-management planning. Does not save, upload, version, open a data file, promote, or relink cloud data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_name": {"type": "string", "description": "Optional name for the new unsaved design document."},
                    "requires_user_approval": {"type": "boolean", "description": "Must be true to confirm creating a new document is intentional."},
                    "reason": {"type": "string", "description": "Required reason explaining why a new design document is needed."}
                },
                "required": ["requires_user_approval", "reason"]
            }
        },
        {
            "name": "close_active_document",
            "description": "Close the active Fusion document with explicit save/discard intent after document-management planning. Does not activate another document, save-as, upload, version, promote, or relink cloud data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "document_name": {"type": "string", "description": "Optional guard: the active document must have this exact name before it is closed."},
                    "save_changes": {"type": "boolean", "default": False, "description": "True saves current changes before closing; false discards unsaved changes."},
                    "requires_user_approval": {"type": "boolean", "description": "Must be true to confirm the close action is intentional."},
                    "reason": {"type": "string", "description": "Required reason explaining why closing this active document is intentional."}
                },
                "required": ["requires_user_approval", "reason"]
            }
        },
        {
            "name": "revert_active_document",
            "description": "Close and reopen the active saved Fusion document from its data file. Use save_changes=false to reset to the last saved state after a failed script.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "save_changes": {"type": "boolean", "default": False, "description": "True saves current changes before closing; false discards unsaved changes."}
                }
            }
        },
        {
            "name": "create_sketch_offset",
            "description": "Create a parametric offset copy of all sketch curves in a sketch. Useful for making insets/outsets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The sketch to offset curves in."},
                    "distance": {"type": "string", "description": "Offset distance, e.g., '1.5 mm' or '-1.0 mm'. Negative values move inward."}
                },
                "required": ["sketch_name", "distance"]
            }
        },
        {
            "name": "create_offset_plane",
            "description": "Create a named construction plane offset from a standard plane, named construction plane, or currently selected planar face. Use before sketching features that need controlled depth or placement.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the new construction plane."},
                    "base_plane_name": {"type": "string", "description": "Standard plane name xy/xz/yz or an existing construction plane name."},
                    "offset": {"type": "string", "description": "Offset distance expression, e.g. '5 mm' or '-2 mm'."},
                    "use_selected_plane": {"type": "boolean", "default": False, "description": "If true, offset from the currently selected construction plane or planar face."},
                    "target_component_name": {"type": "string", "description": "Optional component name to create the construction plane in."}
                },
                "required": ["offset"]
            }
        },
        {
            "name": "create_construction_point",
            "description": "Create a named construction point from coordinates, a named point, or the currently selected point-like entity.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the new construction point."},
                    "mode": {"type": "string", "enum": ["coordinates", "named", "selected"], "default": "coordinates"},
                    "base_plane_name": {"type": "string", "default": "xy", "description": "Sketch plane used when creating a coordinate-backed reference point."},
                    "x": {"type": "string", "default": "0 mm", "description": "First sketch-plane coordinate when mode=coordinates."},
                    "y": {"type": "string", "default": "0 mm", "description": "Second sketch-plane coordinate when mode=coordinates."},
                    "point_name": {"type": "string", "description": "Existing construction/sketch point name when mode=named."},
                    "use_selected_point": {"type": "boolean", "default": False},
                    "hide_reference_sketch": {"type": "boolean", "default": True},
                    "target_component_name": {"type": "string", "description": "Optional component name to create the construction point in."}
                }
            }
        },
        {
            "name": "create_rigid_joint",
            "description": "Create a basic point-to-point rigid assembly joint from two explicit construction/sketch point names or point entity tokens.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Rigid Joint", "description": "Name for the created joint."},
                    "point_one_name": {"type": "string", "description": "First construction point or sketch point name."},
                    "point_two_name": {"type": "string", "description": "Second construction point or sketch point name."},
                    "point_one_entity_token": {"type": "string", "description": "Optional Fusion entity token for the first point-like reference."},
                    "point_two_entity_token": {"type": "string", "description": "Optional Fusion entity token for the second point-like reference."},
                    "flip": {"type": "boolean", "default": False, "description": "Set Fusion joint input flip when supported."},
                    "offset_x": {"type": "string", "description": "Optional X offset expression, e.g. '1 mm'."},
                    "offset_y": {"type": "string", "description": "Optional Y offset expression, e.g. '1 mm'."},
                    "offset_z": {"type": "string", "description": "Optional Z offset expression, e.g. '1 mm'."}
                }
            }
        },
        {
            "name": "create_section_analysis",
            "description": "Create a named Fusion section-analysis entity on an explicit standard or named construction plane. Returns design-state comparison and requires cleanup with delete_section_analysis when finished.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Section Analysis", "description": "Explicit name for the analysis entity."},
                    "plane_name": {"type": "string", "default": "xy", "description": "Section plane: xy, xz, yz, or a named construction plane in the target component."},
                    "target_component_name": {"type": "string", "description": "Optional component containing the named plane."},
                    "activate": {"type": "boolean", "default": True, "description": "Turn on the analysis lightbulb when Fusion exposes that property."}
                }
            }
        },
        {
            "name": "delete_section_analysis",
            "description": "Delete named section-analysis entities created for inspection. Requires a reason and returns design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact section-analysis name to delete."},
                    "reason": {"type": "string", "description": "Required reason for deleting this analysis entity."}
                },
                "required": ["name", "reason"]
            }
        },
        {
            "name": "create_revolute_joint",
            "description": "Create a revolute assembly joint from two explicit point references and an explicit rotation axis from inspected assembly references. No origins or axes are guessed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Revolute Joint"},
                    "point_one_name": {"type": "string"},
                    "point_two_name": {"type": "string"},
                    "point_one_entity_token": {"type": "string"},
                    "point_two_entity_token": {"type": "string"},
                    "motion_axis": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "description": "Required explicit rotation axis."},
                    "flip": {"type": "boolean", "default": False},
                    "offset_x": {"type": "string"},
                    "offset_y": {"type": "string"},
                    "offset_z": {"type": "string"}
                },
                "required": ["motion_axis"]
            }
        },
        {
            "name": "create_slider_joint",
            "description": "Create a slider assembly joint from two explicit point references and an explicit slide direction from inspected assembly references. No origins or axes are guessed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Slider Joint"},
                    "point_one_name": {"type": "string"},
                    "point_two_name": {"type": "string"},
                    "point_one_entity_token": {"type": "string"},
                    "point_two_entity_token": {"type": "string"},
                    "slide_direction": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "description": "Required explicit slide direction."},
                    "flip": {"type": "boolean", "default": False},
                    "offset_x": {"type": "string"},
                    "offset_y": {"type": "string"},
                    "offset_z": {"type": "string"}
                },
                "required": ["slide_direction"]
            }
        },
        {
            "name": "create_cylindrical_joint",
            "description": "Create a cylindrical assembly joint from two explicit point references and an explicit rotation/slide axis from inspected assembly references. No origins or axes are guessed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Cylindrical Joint"},
                    "point_one_name": {"type": "string"},
                    "point_two_name": {"type": "string"},
                    "point_one_entity_token": {"type": "string"},
                    "point_two_entity_token": {"type": "string"},
                    "motion_axis": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "description": "Required explicit rotation/slide axis."},
                    "flip": {"type": "boolean", "default": False},
                    "offset_x": {"type": "string"},
                    "offset_y": {"type": "string"},
                    "offset_z": {"type": "string"}
                },
                "required": ["motion_axis"]
            }
        },
        {
            "name": "create_pin_slot_joint",
            "description": "Create a pin-slot assembly joint from two explicit point references plus explicit rotation axis and slide direction. No origins or axes are guessed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Pin Slot Joint"},
                    "point_one_name": {"type": "string"},
                    "point_two_name": {"type": "string"},
                    "point_one_entity_token": {"type": "string"},
                    "point_two_entity_token": {"type": "string"},
                    "motion_axis": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "description": "Required explicit rotation axis."},
                    "slide_direction": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "description": "Required explicit slot slide direction."},
                    "flip": {"type": "boolean", "default": False},
                    "offset_x": {"type": "string"},
                    "offset_y": {"type": "string"},
                    "offset_z": {"type": "string"}
                },
                "required": ["motion_axis", "slide_direction"]
            }
        },
        {
            "name": "create_planar_joint",
            "description": "Create a planar assembly joint from two explicit point references and an explicit plane normal direction from inspected assembly references. No origins or axes are guessed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Planar Joint"},
                    "point_one_name": {"type": "string"},
                    "point_two_name": {"type": "string"},
                    "point_one_entity_token": {"type": "string"},
                    "point_two_entity_token": {"type": "string"},
                    "normal_direction": {"type": "string", "enum": ["x", "y", "z", "-x", "-y", "-z"], "description": "Required explicit plane normal direction."},
                    "flip": {"type": "boolean", "default": False},
                    "offset_x": {"type": "string"},
                    "offset_y": {"type": "string"},
                    "offset_z": {"type": "string"}
                },
                "required": ["normal_direction"]
            }
        },
        {
            "name": "create_ball_joint",
            "description": "Create a ball assembly joint from two explicit point references. No origins are guessed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "default": "Ball Joint"},
                    "point_one_name": {"type": "string"},
                    "point_two_name": {"type": "string"},
                    "point_one_entity_token": {"type": "string"},
                    "point_two_entity_token": {"type": "string"},
                    "flip": {"type": "boolean", "default": False},
                    "offset_x": {"type": "string"},
                    "offset_y": {"type": "string"},
                    "offset_z": {"type": "string"}
                }
            }
        },
        {
            "name": "create_construction_axis",
            "description": "Create a named construction axis from two points or from the currently selected line-like entity.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the new construction axis."},
                    "mode": {"type": "string", "enum": ["two_points", "selected_line"], "default": "two_points"},
                    "point_name_one": {"type": "string", "description": "First existing construction/sketch point name."},
                    "point_name_two": {"type": "string", "description": "Second existing construction/sketch point name."},
                    "point_one": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "First [x, y] sketch-plane coordinate for a coordinate-backed reference point."
                    },
                    "point_two": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Second [x, y] sketch-plane coordinate for a coordinate-backed reference point."
                    },
                    "base_plane_name": {"type": "string", "default": "xy"},
                    "use_selected_line": {"type": "boolean", "default": False},
                    "hide_reference_sketch": {"type": "boolean", "default": True},
                    "target_component_name": {"type": "string", "description": "Optional component name to create the construction axis in."}
                }
            }
        },
        {
            "name": "clone_timeline_feature",
            "description": "Extract parameters and details of an existing timeline feature in the active design, creating a clean JSON recipe.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the feature in the timeline."},
                    "index": {"type": "integer", "description": "Timeline index of the feature (0-based)."}
                }
            }
        },
        {
            "name": "get_timeline",
            "description": "Retrieve the complete, ordered list of history features in the active model's timeline, detailing their index, type, name, health state, and suppression state.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "set_timeline_marker",
            "description": "Move the timeline playhead marker to roll back or roll forward the model history. Use index (0 to timeline.count) or target feature name.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer", "description": "0-based position index to roll back to."},
                    "name": {"type": "string", "description": "The name of the feature to roll the marker immediately after."}
                }
            }
        },
        {
            "name": "suppress_timeline_feature",
            "description": "Suppress or unsuppress a historical feature in the active design timeline. Requires a reason and blocks likely downstream dependency risk unless explicitly overridden.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the feature in the timeline."},
                    "index": {"type": "integer", "description": "The 0-based timeline index of the feature."},
                    "suppress": {"type": "boolean", "default": True, "description": "True to suppress, False to unsuppress."},
                    "reason": {"type": "string", "description": "Required. State why changing this feature's suppression state is intentional."},
                    "allow_downstream_risk": {"type": "boolean", "default": False, "description": "Explicitly allow the operation when dependency analysis finds likely downstream consumers."}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "delete_timeline_feature",
            "description": "Delete an existing feature from the design timeline. Requires a reason, captures before/after state, and blocks likely downstream dependency risk unless explicitly overridden.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the feature in the timeline."},
                    "index": {"type": "integer", "description": "The 0-based timeline index of the feature."},
                    "reason": {"type": "string", "description": "Required. State why deleting this timeline feature is intentional."},
                    "allow_downstream_risk": {"type": "boolean", "default": False, "description": "Explicitly allow the deletion when dependency analysis finds likely downstream consumers."}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "delete_named_experiment",
            "description": "Dangerous cleanup tool for named experimental artifacts. Matches exact names and/or prefixes across timeline items, bodies, and sketches, defaults to dry-run, and requires confirm_delete=true plus reason before deleting anything.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Exact timeline item, body, or sketch names to delete."
                    },
                    "prefixes": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Name prefixes to delete. Prefixes shorter than 3 characters require allow_short_prefix=true."
                    },
                    "reason": {"type": "string", "description": "Required. State why this experimental cleanup is intentional."},
                    "confirm_delete": {"type": "boolean", "default": False, "description": "When false, only reports matches. Set true to delete matched artifacts."},
                    "include_timeline": {"type": "boolean", "default": True},
                    "include_bodies": {"type": "boolean", "default": True},
                    "include_sketches": {"type": "boolean", "default": True},
                    "allow_short_prefix": {"type": "boolean", "default": False}
                },
                "required": ["reason"]
            }
        },
        {
            "name": "get_best_practices",
            "description": "Get Fusion 360 design best practices, coordinate rules (Y-up), body naming conventions, and script execution guidelines.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "list_appearances",
            "description": "List available active-design and material-library appearances for styling bodies. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Optional case-insensitive name filter, such as 'steel', 'glass', or 'black'."},
                    "include_libraries": {"type": "boolean", "default": True, "description": "Include appearances from installed Fusion material libraries, not only appearances already copied into the active design."},
                    "limit": {"type": "integer", "default": 50, "description": "Maximum number of appearances to return. Clamped from 1 to 500."}
                }
            }
        },
        {
            "name": "inspect_body_style",
            "description": "Report current appearance/material assignments for a named body, body entity token, or all bodies. Read-only.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Exact body name to inspect."},
                    "body_entity_tokens": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Exact BRep body entity token or tokens to inspect. Prefer this when names are ambiguous."
                    },
                    "include_all_bodies": {"type": "boolean", "default": False, "description": "When true, report style state for every body in all components."}
                }
            }
        },
        {
            "name": "apply_appearance",
            "description": "Style one or more exact body targets in the active design with a materials-library appearance. Supports body entity tokens for duplicate-name-safe multicolor export prep.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Backwards-compatible exact name of one body to style."},
                    "body_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Exact BRep body name or names to style."
                    },
                    "body_entity_tokens": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Exact BRep body entity token or tokens to style. Prefer this when names are ambiguous."
                    },
                    "appearance_name": {"type": "string", "description": "The name of the appearance (e.g. 'Gold - Polished', 'Steel - Satin', 'Glass - Clear'). Supports case-insensitive partial matching."},
                    "expected_body_count": {"type": "integer", "description": "Optional guard requiring the resolved body count to match before applying."}
                },
                "required": ["appearance_name"]
            }
        },
        {
            "name": "get_mcp_workflow_guide",
            "description": "Get the official step-by-step CAD workflow guide for Fusion 360 AI Agents.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "search_fusion_api_documentation",
            "description": "Get description and official documentation URLs for Autodesk Fusion 360 API classes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string", "description": "The exact class name to search for (e.g. 'ExtrudeFeature', 'BRepBody')."}
                },
                "required": ["class_name"]
            }
        },
        {
            "name": "git_status",
            "description": "Check current git status in the design workspace folder.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "export_parameters_csv",
            "description": "Export active user parameters to a CSV file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "csv_path": {"type": "string", "description": "Absolute target CSV file path."}
                },
                "required": ["csv_path"]
            }
        },
        {
            "name": "import_parameters_csv",
            "description": "Import user parameters from a CSV spreadsheet file, updating or creating parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "csv_path": {"type": "string", "description": "Absolute source CSV file path."}
                },
                "required": ["csv_path"]
            }
        },
        {
            "name": "convert_mesh_to_solid",
            "description": "Convert an imported STL/OBJ mesh body to a solid B-Rep body after plan_mesh_conversion preflight passes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mesh_body_name": {"type": "string", "description": "The mesh body name from inspect_mesh_bodies. Use mesh_body_entity_token instead when names are ambiguous."},
                    "mesh_body_entity_token": {"type": "string", "description": "Exact mesh body entity token from inspect_mesh_bodies."},
                    "operation": {"type": "string", "enum": ["new_body", "join", "cut"], "default": "new_body"},
                    "acknowledge_quality_loss": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to acknowledge that mesh-to-BRep conversion can lose detail or create heavy geometry."
                    },
                    "reason": {"type": "string", "description": "Required explanation for why this conversion is intentional."},
                    "tolerance": {"type": "string", "description": "Optional tolerance note or Fusion expression for the conversion plan."},
                    "detail_level": {"type": "string", "description": "Optional detail level note for the conversion plan."}
                }
            }
        },
        {
            "name": "repair_mesh_body",
            "description": "Repair a mesh body after plan_mesh_conversion approves repair_mesh. Returns unsupported instead of guessing when Fusion lacks compatible mesh repair APIs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mesh_body_name": {"type": "string", "description": "Mesh body name from inspect_mesh_bodies."},
                    "mesh_body_entity_token": {"type": "string", "description": "Exact mesh body entity token from inspect_mesh_bodies."},
                    "repair_type": {"type": "string", "description": "Optional explicit repair mode/type for runtimes that expose it."},
                    "acknowledge_quality_loss": {"type": "boolean", "default": False},
                    "reason": {"type": "string"},
                    "tolerance": {"type": "string"},
                    "detail_level": {"type": "string"}
                }
            }
        },
        {
            "name": "reduce_mesh_body",
            "description": "Reduce a mesh body after plan_mesh_conversion approves reduce_mesh. Returns unsupported instead of guessing when Fusion lacks compatible mesh reduction APIs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mesh_body_name": {"type": "string", "description": "Mesh body name from inspect_mesh_bodies."},
                    "mesh_body_entity_token": {"type": "string", "description": "Exact mesh body entity token from inspect_mesh_bodies."},
                    "reduction_target": {"type": "string", "description": "Optional explicit reduction target, ratio, or quality note for runtimes that expose it."},
                    "acknowledge_quality_loss": {"type": "boolean", "default": False},
                    "reason": {"type": "string"},
                    "tolerance": {"type": "string"},
                    "detail_level": {"type": "string"}
                }
            }
        },
        {
            "name": "remesh_body",
            "description": "Remesh a mesh body after plan_mesh_conversion approves remesh. Returns unsupported instead of guessing when Fusion lacks compatible remesh APIs.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mesh_body_name": {"type": "string", "description": "Mesh body name from inspect_mesh_bodies."},
                    "mesh_body_entity_token": {"type": "string", "description": "Exact mesh body entity token from inspect_mesh_bodies."},
                    "remesh_type": {"type": "string", "description": "Optional explicit remesh mode/type for runtimes that expose it."},
                    "acknowledge_quality_loss": {"type": "boolean", "default": False},
                    "reason": {"type": "string"},
                    "tolerance": {"type": "string"},
                    "detail_level": {"type": "string"}
                }
            }
        },
        {
            "name": "create_2d_drawing",
            "description": "Generate a 2D drafting sheet (blueprint) of the active model and export it to PDF after model-health preflight checks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_pdf_path": {"type": "string", "description": "Absolute path to save the generated PDF drawing blueprint."},
                    "allow_unhealthy_model": {
                        "type": "boolean",
                        "default": False,
                        "description": "Allow drawing export even when preflight detects compute or timeline health issues. Requires override_reason."
                    },
                    "require_compute": {
                        "type": "boolean",
                        "default": True,
                        "description": "Run Fusion computeAll during preflight and block on compute failure."
                    },
                    "override_reason": {
                        "type": "string",
                        "description": "Required explanation when allow_unhealthy_model is true and preflight fails."
                    }
                },
                "required": ["export_pdf_path"]
            }
        },
        {
            "name": "get_parameter",
            "description": "Read a Fusion user parameter by name. If name is omitted or empty, returns all user parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Optional user parameter name"}
                }
            }
        },
        {
            "name": "set_parameter",
            "description": "Set a Fusion user parameter expression and return before/after values.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "expression": {"type": "string"}
                },
                "required": ["name", "expression"]
            }
        },
        {
            "name": "apply_design_variant_parameters",
            "description": "Apply an explicit user-parameter set after plan_design_variant approves it. Does not create or activate Fusion configuration rows.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "variant_name": {"type": "string", "description": "Explicit name for the planned variant being applied."},
                    "base_configuration": {"type": "string", "description": "Optional inspected base configuration name."},
                    "parameter_changes": {"type": "object", "description": "Parameter-name to expression map for existing user parameters."},
                    "expected_affected_bodies": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Expected affected bodies for downstream review."
                    },
                    "expected_affected_features": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                        "description": "Expected affected timeline features for downstream review."
                    },
                    "reason": {"type": "string", "description": "Why this parameter-set variant should be applied."},
                    "requires_user_approval": {"type": "boolean", "default": False}
                },
                "required": ["variant_name", "parameter_changes", "reason", "requires_user_approval"]
            }
        },
        {
            "name": "capture_view",
            "description": "Take screenshots from standard isometric or orthographic views. Instructions: Take screenshots after complex changes to verify intent. State the desired view (e.g., 'front', 'iso').",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "view_name": {"type": "string", "default": "iso"}
                }
            }
        },
        {
            "name": "capture_demo_sequence",
            "description": "Capture a generic sequence of staged PNG frames using named camera views and optional per-step visibility changes. Restores visibility by default and reports before/after design-state comparisons.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Optional ordered capture steps. Omit to capture the view_names list or a single iso frame.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "view_name": {"type": "string", "enum": ["top", "bottom", "left", "right", "front", "back", "iso"]},
                                "orientation": {"type": "string", "enum": ["top", "bottom", "left", "right", "front", "back", "iso"]},
                                "capture": {"type": "boolean", "default": True},
                                "body_names": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                                "sketch_names": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                                "construction_plane_names": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                                "visible": {"type": "boolean", "default": True},
                                "hide_all_sketches": {"type": "boolean"},
                                "hide_all_construction_planes": {"type": "boolean"},
                                "clear_selection": {"type": "boolean", "default": True},
                                "image_width": {"type": "integer"},
                                "image_height": {"type": "integer"},
                                "note": {"type": "string"}
                            }
                        }
                    },
                    "view_names": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["top", "bottom", "left", "right", "front", "back", "iso"]},
                        "description": "Convenience list used when steps is omitted."
                    },
                    "output_dir": {"type": "string", "description": "Directory where PNG frames should be written. Defaults to a temp directory."},
                    "image_width": {"type": "integer", "default": 1920},
                    "image_height": {"type": "integer", "default": 1080},
                    "restore_visibility": {"type": "boolean", "default": True},
                    "hide_all_sketches": {"type": "boolean", "default": False},
                    "hide_all_construction_planes": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "validate_model",
            "description": "Check for constraints, broken references, timeline warnings, and naming conventions. Instructions: Run this before finishing a task to ensure the model remains in a healthy, parametric state.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "get_runtime_diagnostics",
            "description": "Report live FusionMCP runtime diagnostics including tool schema/registry counts, missing required tools, loaded module paths, redacted discovery data, manifest opt-in state, and whether an add-in restart is recommended.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "required_tools": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional tool name or list of tool names expected to be live. Omit for the default critical FusionMCP tool set."
                    }
                }
            }
        },
        {
            "name": "doctor",
            "description": "Run a read-only FusionMCP readiness check and return a clear ok/warning/error verdict for runtime health, TaskManager state, discovery token freshness, schema/registry alignment, active design availability, and timeline health.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "required_tools": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional tool name or list of critical tools expected to be live. Omit for the default FusionMCP readiness set."
                    },
                    "require_active_design": {
                        "type": "boolean",
                        "default": True,
                        "description": "If true, missing active Fusion design is a blocking readiness problem."
                    }
                }
            }
        },
        {
            "name": "get_change_journal",
            "description": "Read recent local FusionMCP tool-call journal entries from ~/.fusion_mcp/journal.jsonl. Entries redact tokens, authorization headers, and raw scripts.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "default": 200,
                        "description": "Maximum number of recent entries to return, capped at 1000."
                    }
                }
            }
        },
        {
            "name": "clear_change_journal",
            "description": "Clear the local FusionMCP tool-call journal. Requires a reason because this removes audit history.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Required reason for clearing the journal."
                    }
                },
                "required": ["reason"]
            }
        },
        {
            "name": "recommend_mcp_workflow",
            "description": "Return the structured FusionMCP workflow an agent should follow for a task before falling back to raw scripting. Use this when deciding whether to inspect, parameterize, modify geometry, troubleshoot runtime state, or export.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Short description of the user task, e.g. parameterize this model, export STEP, add a cut, troubleshoot MCP."
                    },
                    "intent": {
                        "type": "string",
                        "description": "Optional more specific intent or planned operation."
                    },
                    "allow_raw_script": {
                        "type": "boolean",
                        "default": False,
                        "description": "Set true only when raw scripting is being considered after checking structured tools."
                    }
                },
                "required": ["task"]
            }
        },
        {
            "name": "preflight_model_change",
            "description": "Run a read-only risk check before a model-changing operation. Checks compute health, timeline health, unsaved document state, optional target feature dependencies, and returns okToProceed/riskLevel.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "change_type": {"type": "string", "default": "generic", "description": "Short label for the planned change, e.g. fillet, cut, parameter_update, delete_feature."},
                    "target_features": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional feature name or list of feature names to dependency-check."
                    },
                    "target_bodies": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional body name or list of body names involved in the planned change."
                    },
                    "require_compute": {"type": "boolean", "default": True, "description": "Force Fusion computeAll during the preflight."}
                }
            }
        },
        {
            "name": "preflight_export",
            "description": "Run export readiness checks without writing a file. Forces compute by default, checks timeline/feature health, and compares design state before/after compute.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "require_compute": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "inspect_3mf_archive",
            "description": "Read-only inspection for an existing 3MF file. Reports package validity, model part, object/build/component counts, broken references, metadata, embedded material/color evidence, validation scope, slicer colorability likelihood, and a printReadiness verdict.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_path": {"type": "string", "description": "Absolute .3mf file path to inspect."},
                    "expected_body_count": {"type": "integer", "description": "Optional expected body/object count used to warn when the archive appears collapsed for multicolor workflows."}
                },
                "required": ["export_path"]
            }
        },
        {
            "name": "plan_multibody_3mf_export",
            "description": "Read-only planning tool for targeted multibody 3MF exports. Resolves body names, body entity tokens, and named selection-set contents, reports blockers/non-body selection members, and runs export readiness checks before export_asset writes a file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_path": {"type": "string", "description": "Absolute .3mf output path to validate."},
                    "body_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Exact BRep body name or names to include."
                    },
                    "body_entity_tokens": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Exact BRep body entity token or tokens to include. Prefer this when names are ambiguous."
                    },
                    "selection_set_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Named Fusion selection sets whose BRep body contents should be included."
                    },
                    "require_compute": {"type": "boolean", "default": True},
                    "expected_body_count": {"type": "integer", "description": "Optional guard requiring the resolved body count to match before export."},
                    "allow_overwrite": {"type": "boolean", "default": False, "description": "Allow replacing an existing .3mf export path. Defaults to false to avoid accidental overwrite."},
                    "requires_user_approval": {"type": "boolean", "default": False},
                    "reason": {"type": "string", "description": "Required when requires_user_approval=true."}
                }
            }
        },
        {
            "name": "verify_insert_alignment",
            "description": "Read-only pre-export guard for removable insert plates, socket/pocket/cutter bodies, and raised logo bodies. Uses axis-aligned bounding boxes to catch separated, non-overlapping, mirrored, or wrong-depth geometry before 3MF export.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "plate_body_name": {"type": "string", "description": "Exact BRep body name for the removable plate."},
                    "socket_body_name": {"type": "string", "description": "Exact BRep body name for the matching socket, pocket, or cutter body."},
                    "logo_body_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional logo/raised body names that should touch or intersect the plate footprint."
                    },
                    "plate_body_entity_token": {"type": "string", "description": "Plate body entity token. Prefer this when names are ambiguous."},
                    "socket_body_entity_token": {"type": "string", "description": "Socket body entity token. Prefer this when names are ambiguous."},
                    "logo_body_entity_tokens": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional logo/raised body entity tokens."
                    },
                    "thickness_axis": {"type": "string", "enum": ["x", "y", "z"], "default": "z", "description": "Axis used as plate thickness and socket depth."},
                    "expected_plate_thickness": {"type": "string", "description": "Optional expected plate thickness expression, e.g. '2 mm'."},
                    "flush_mode": {"type": "string", "enum": ["flush", "proud", "recessed"], "default": "flush"},
                    "tolerance": {"type": "string", "default": "0.05 mm", "description": "Allowed bbox depth/contact tolerance."},
                    "include_invisible": {"type": "boolean", "default": False}
                }
            }
        },
        {
            "name": "plan_multicolor_3mf_export",
            "description": "Read-only planner for multicolor 3MF exports. Verifies body/entity-token color assignments, appearance availability, export target count, overwrite policy, and generic export readiness before applying appearances or writing a file.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_path": {"type": "string", "description": "Absolute .3mf output path to validate."},
                    "color_assignments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "body_name": {"type": "string", "description": "Exact BRep body name to color."},
                                "body_entity_token": {"type": "string", "description": "Exact BRep body entity token to color. Prefer this when names are ambiguous."},
                                "appearance_name": {"type": "string", "description": "Appearance to apply before export."}
                            },
                            "required": ["appearance_name"]
                        },
                        "description": "Per-body color assignments. Each item needs body_name or body_entity_token plus appearance_name."
                    },
                    "selection_set_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "Optional named selection sets to include in the export body set."
                    },
                    "require_compute": {"type": "boolean", "default": True},
                    "expected_body_count": {"type": "integer", "description": "Optional guard requiring the resolved body count to match before export."},
                    "allow_overwrite": {"type": "boolean", "default": False, "description": "Allow replacing an existing .3mf export path. Defaults to false."},
                    "requires_user_approval": {"type": "boolean", "default": False},
                    "reason": {"type": "string", "description": "Required when requires_user_approval=true."}
                }
            }
        },
        {
            "name": "export_asset",
            "description": "Safely export the design to STL, STEP, or targeted multibody 3MF. Runs preflight_export first and blocks compute/timeline-health problems unless allow_unhealthy_export is explicitly true and override_reason explains the risk. For 3MF, call plan_multibody_3mf_export first, then provide body_names, body_entity_tokens, or selection_set_names to export a controlled visible-body set.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "format": {"type": "string", "enum": ["step", "stl", "3mf"]},
                    "export_path": {"type": "string"},
                    "body_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "For 3MF exports, exact BRep body name or names to include."
                    },
                    "body_entity_tokens": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "For 3MF exports, exact BRep body entity token or tokens to include. Prefer this when names are ambiguous."
                    },
                    "selection_set_names": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}}
                        ],
                        "description": "For 3MF exports, named Fusion selection sets whose BRep body contents should be included."
                    },
                    "restore_visibility": {
                        "type": "boolean",
                        "default": True,
                        "description": "For 3MF exports, restore body visibility after temporarily showing only target bodies."
                    },
                    "expected_body_count": {
                        "type": "integer",
                        "description": "For 3MF exports, require the resolved body count to match this value before writing."
                    },
                    "allow_overwrite": {
                        "type": "boolean",
                        "default": False,
                        "description": "For 3MF exports, allow replacing an existing output path. Defaults to false to avoid accidental overwrite."
                    },
                    "allow_unhealthy_export": {
                        "type": "boolean",
                        "default": False,
                        "description": "Explicit override to export even when preflight reports compute or health problems."
                    },
                    "require_compute": {
                        "type": "boolean",
                        "default": True,
                        "description": "Force Fusion computeAll before export."
                    },
                    "override_reason": {
                        "type": "string",
                        "description": "Required when allow_unhealthy_export=true and preflight checks fail. State why exporting a potentially incomplete model is intentional."
                    }
                },
                "required": ["format", "export_path"]
            }
        },
        {
            "name": "export_flat_pattern",
            "description": "Safely export an existing sheet-metal flat pattern to DXF, DWG, or STEP. Runs preflight_flat_pattern first and blocks when no flat pattern is available unless allow_blocked_export is explicitly true with an override reason.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_path": {"type": "string", "description": "Absolute output path for the exported flat pattern."},
                    "format": {"type": "string", "enum": ["dxf", "dwg", "step"], "default": "dxf"},
                    "allow_blocked_export": {
                        "type": "boolean",
                        "default": False,
                        "description": "Explicit override to attempt export even when preflight reports flat-pattern blockers."
                    },
                    "override_reason": {
                        "type": "string",
                        "description": "Required when allow_blocked_export=true and preflight checks fail. State why exporting despite blockers is intentional."
                    }
                },
                "required": ["export_path"]
            }
        },
        {
            "name": "get_fusion_api_help",
            "description": "Retrieve targeted Fusion API documentation, known gotchas, and local examples. Instructions: Consult this before writing complex arbitrary scripts with `run_fusion_script`.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "topic": {"type": "string"}
                }
            }
        },
        {
            "name": "search_local_fusion_docs",
            "description": "Search FusionMCP's local Fusion API and best-practices documentation index. Use before raw scripts or unfamiliar Fusion API classes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms such as ConstructionPlane, units, or timeline safety."},
                    "limit": {"type": "integer", "default": 10}
                }
            }
        },
        {
            "name": "set_camera",
            "description": "Manipulate the active viewport camera to view the model from standard angles. Automatically fits the view to the model.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "orientation": {"type": "string", "enum": ["top", "bottom", "left", "right", "front", "back", "iso"]}
                },
                "required": ["orientation"]
            }
        },
        {
            "name": "prompt_user",
            "description": "Display a non-blocking UI message box to the user in Fusion 360. Use this to ask for manual interaction.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "message": {"type": "string"}
                },
                "required": ["message"]
            }
        },
        {
            "name": "measure_entity",
            "description": "Measure the bounding box, volume, and area of a component or body. If entity_name is omitted, measures the current selection.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "entity_name": {"type": "string", "description": "Optional name of body/component to measure"}
                }
            }
        },
        {
            "name": "undo_last_action",
            "description": "Undo the last CAD operation with guardrails. Captures design state before/after and automatically redoes the undo if it changes design type, removes broad model structures, or increases unhealthy timeline items unless allow_risky is explicitly set with a reason.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "allow_risky": {"type": "boolean", "default": False, "description": "Allow a guarded undo even when risky state changes are detected. Requires reason."},
                    "reason": {"type": "string", "description": "Required when allow_risky=true. Explain why the risky undo is intentional."}
                }
            }
        },
        {
            "name": "get_assembly_tree",
            "description": "Return a nested JSON hierarchy of all components, occurrences, and their transforms. By default, only returns the top level (depth=1).",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "max_depth": {"type": "integer", "default": 1}
                }
            }
        },
        {
            "name": "get_assembly_references",
            "description": "Read-only report of component origins, standard axes/planes, construction axes/planes/points, and occurrence transforms for repeatable assembly placement.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_all_components": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "get_assembly_joints",
            "description": "Read-only report of assembly joints and as-built joints exposed by Fusion.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "include_as_built": {"type": "boolean", "default": True, "description": "Include as-built joints when Fusion exposes them on the root component."}
                }
            }
        },
        {
            "name": "plan_joint_limits",
            "description": "Read-only assembly joint limit planner. Validates explicit joint target, limit type, min/max/rest expressions, and reason before future motion-limit mutations.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "joint_name": {"type": "string", "description": "Exact joint name from get_assembly_joints."},
                    "joint_entity_token": {"type": "string", "description": "Exact joint entity token from get_assembly_joints."},
                    "limit_type": {"type": "string", "enum": ["rotation", "slide"]},
                    "minimum": {"type": "string", "description": "Minimum angle/distance expression when enable_minimum=true."},
                    "maximum": {"type": "string", "description": "Maximum angle/distance expression when enable_maximum=true."},
                    "rest": {"type": "string", "description": "Rest angle/distance expression when enable_rest=true."},
                    "enable_minimum": {"type": "boolean", "default": True},
                    "enable_maximum": {"type": "boolean", "default": True},
                    "enable_rest": {"type": "boolean", "default": False},
                    "reason": {"type": "string", "description": "Required reason for planning joint limit changes."}
                },
                "required": ["limit_type", "reason"]
            }
        },
        {
            "name": "set_joint_limits",
            "description": "Set explicit rotation or slide limits on an existing assembly joint after plan_joint_limits passes. Returns unsupported if Fusion does not expose writable limit APIs for the selected joint.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "joint_name": {"type": "string", "description": "Exact joint name from get_assembly_joints."},
                    "joint_entity_token": {"type": "string", "description": "Exact joint entity token from get_assembly_joints."},
                    "limit_type": {"type": "string", "enum": ["rotation", "slide"]},
                    "minimum": {"type": "string", "description": "Minimum angle/distance expression when enable_minimum=true."},
                    "maximum": {"type": "string", "description": "Maximum angle/distance expression when enable_maximum=true."},
                    "rest": {"type": "string", "description": "Rest angle/distance expression when enable_rest=true."},
                    "enable_minimum": {"type": "boolean", "default": True},
                    "enable_maximum": {"type": "boolean", "default": True},
                    "enable_rest": {"type": "boolean", "default": False},
                    "reason": {"type": "string", "description": "Required reason for changing joint limits."}
                },
                "required": ["limit_type", "reason"]
            }
        },
        {
            "name": "get_sketch_dimensions",
            "description": "Retrieve all parametric dimensions (index, parameter name, type, expression, and current value) in a specific sketch.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The exact name of the sketch to read."}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "edit_extrude_feature",
            "description": "Narrowly edit an existing extrude feature's distance and/or operation by exact feature name. Runs dependency/impact checks and returns before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name for the ExtrudeFeature to edit."},
                    "distance": {"type": "string", "description": "Optional new distance expression, e.g. '12 mm' or 'wallHeight / 2'."},
                    "operation": {"type": "string", "enum": ["NewBody", "Join", "Cut", "Intersect", "new_body", "join", "cut", "intersect"], "description": "Optional new explicit extrude operation."},
                    "parameter_name": {"type": "string", "description": "Optional exact model parameter name or role from inspect_feature/get_feature_parameters when multiple parameters exist."},
                    "reason": {"type": "string", "description": "Required only when allow_downstream_risk=true."},
                    "allow_downstream_risk": {"type": "boolean", "default": False}
                },
                "required": ["feature_name"]
            }
        },
        {
            "name": "edit_fillet_radius",
            "description": "Narrowly edit an existing fillet feature radius by exact feature name. Runs dependency/impact checks and returns before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name for the FilletFeature to edit."},
                    "radius": {"type": "string", "description": "New radius expression, e.g. '2 mm'."},
                    "parameter_name": {"type": "string", "description": "Optional exact model parameter name or role from inspect_feature/get_feature_parameters when multiple parameters exist."},
                    "reason": {"type": "string", "description": "Required only when allow_downstream_risk=true."},
                    "allow_downstream_risk": {"type": "boolean", "default": False}
                },
                "required": ["feature_name", "radius"]
            }
        },
        {
            "name": "edit_chamfer_distance",
            "description": "Narrowly edit an existing chamfer feature distance by exact feature name. Runs dependency/impact checks and returns before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name for the ChamferFeature to edit."},
                    "distance": {"type": "string", "description": "New chamfer distance expression, e.g. '1 mm'."},
                    "parameter_name": {"type": "string", "description": "Optional exact model parameter name or role from inspect_feature/get_feature_parameters when multiple parameters exist."},
                    "reason": {"type": "string", "description": "Required only when allow_downstream_risk=true."},
                    "allow_downstream_risk": {"type": "boolean", "default": False}
                },
                "required": ["feature_name", "distance"]
            }
        },
        {
            "name": "edit_shell_thickness",
            "description": "Narrowly edit an existing shell feature thickness by exact feature name. Runs dependency/impact checks and returns before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name for the ShellFeature to edit."},
                    "thickness": {"type": "string", "description": "New shell thickness expression, e.g. '1.6 mm'."},
                    "parameter_name": {"type": "string", "description": "Optional exact model parameter name or role from inspect_feature/get_feature_parameters when multiple parameters exist."},
                    "reason": {"type": "string", "description": "Required only when allow_downstream_risk=true."},
                    "allow_downstream_risk": {"type": "boolean", "default": False}
                },
                "required": ["feature_name", "thickness"]
            }
        },
        {
            "name": "edit_pattern_parameter",
            "description": "Narrowly edit an existing pattern feature count/spacing model parameter by exact feature and parameter name. Runs dependency/impact checks and returns before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name for the pattern feature to edit."},
                    "parameter_name": {"type": "string", "description": "Exact model parameter name or role from inspect_feature/get_feature_parameters, such as quantityOne or distanceOne."},
                    "expression": {"type": "string", "description": "New count or spacing expression."},
                    "reason": {"type": "string", "description": "Required only when allow_downstream_risk=true."},
                    "allow_downstream_risk": {"type": "boolean", "default": False}
                },
                "required": ["feature_name", "parameter_name", "expression"]
            }
        },
        {
            "name": "edit_hole_parameter",
            "description": "Narrowly edit an existing hole feature dimension model parameter by exact feature and parameter name. Runs dependency/impact checks and returns before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name for the HoleFeature to edit."},
                    "parameter_name": {"type": "string", "description": "Exact model parameter name or role from inspect_feature/get_feature_parameters, such as diameter, depth, or tipAngle."},
                    "expression": {"type": "string", "description": "New hole dimension expression."},
                    "reason": {"type": "string", "description": "Required only when allow_downstream_risk=true."},
                    "allow_downstream_risk": {"type": "boolean", "default": False}
                },
                "required": ["feature_name", "parameter_name", "expression"]
            }
        },
        {
            "name": "edit_sketch_dimension",
            "description": "Modify the value/expression of an existing parametric dimension in a sketch and return before/after parameter data plus design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The name of the sketch containing the dimension."},
                    "parameter_name": {"type": "string", "description": "The name of the dimension parameter (e.g. 'd5') or the index of the dimension (0-based)."},
                    "expression": {"type": "string", "description": "The new parametric expression or value (e.g., '15 mm', 'width / 2')."}
                },
                "required": ["sketch_name", "parameter_name", "expression"]
            }
        },
        {
            "name": "delete_sketch_dimension",
            "description": "Delete/remove a specific dimension constraint from a sketch. Requires a reason and returns before/after design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The name of the sketch containing the dimension."},
                    "parameter_name": {"type": "string", "description": "The name of the dimension parameter (e.g. 'd5') or the index of the dimension (0-based) to delete."},
                    "reason": {"type": "string", "description": "Required. State why removing this dimension is intentional."}
                },
                "required": ["sketch_name", "parameter_name", "reason"]
            }
        },
        {
            "name": "add_sketch_constraint",
            "description": "Apply geometric constraints (such as midpoint, horizontal/vertical points, tangent, parallel, concentric, fixed) between sketch curves or points and return design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The name of the sketch to apply constraints in."},
                    "constraint_type": {
                        "type": "string",
                        "enum": ["midpoint", "horizontal_points", "vertical_points", "coincident", "parallel", "perpendicular", "tangent", "equal", "concentric", "fixed", "horizontal", "vertical"],
                        "description": "The geometric relationship to apply."
                    },
                    "use_selection": {"type": "boolean", "default": True, "description": "If true, applies constraint to the currently selected entities in the Fusion 360 UI."},
                    "selection_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Specify which active selection indexes to use. Default uses the first two."
                    },
                    "entity_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "If use_selection is false, specify index of sketchPoints (0 to count-1) or sketchCurves (count to points+curves-1) to constrain."
                    }
                },
                "required": ["sketch_name", "constraint_type"]
            }
        },
        {
            "name": "delete_sketch_constraint",
            "description": "Delete a specific geometric constraint from a sketch using the constraint index from inspect_sketch. Requires a reason and returns before/after design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The name of the sketch containing the constraint."},
                    "constraint_index": {"type": "integer", "description": "0-based constraint index from inspect_sketch constraints[].index."},
                    "reason": {"type": "string", "description": "Required. State why deleting this constraint is intentional."}
                },
                "required": ["sketch_name", "constraint_index", "reason"]
            }
        },
        {
            "name": "combine_bodies",
            "description": "Perform an explicit Boolean Combine operation (Join, Cut, or Intersect) between a target body and one or more tool bodies, returning design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target_body_name": {"type": "string", "description": "The name of the main body that will be kept and modified."},
                    "tool_body_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of names of bodies to join, cut, or intersect with the target body."
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["join", "cut", "intersect"],
                        "description": "Required explicit Boolean operation. Do not guess."
                    },
                    "keep_tool_bodies": {"type": "boolean", "default": False, "description": "If true, tool bodies are preserved instead of being consumed/deleted."}
                },
                "required": ["target_body_name", "tool_body_names", "operation"]
            }
        },
        {
            "name": "reorganize_body_to_component",
            "description": "Move a solid body from its current component into a different sub-component, creating a new component if requested, and return design-state comparison.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "The name of the body to relocate."},
                    "target_component_name": {"type": "string", "description": "The name of the existing sub-component/occurrence to move the body to."},
                    "new_component_name": {"type": "string", "description": "Create a new sub-component with this name and move the body into it."}
                },
                "required": ["body_name"]
            }
        },
        {
            "name": "set_visibility",
            "description": "Show or hide named bodies, sketches, and construction planes, optionally hiding all sketches/planes and clearing the active selection for clean inspection or presentation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
                    },
                    "sketch_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
                    },
                    "construction_plane_names": {
                        "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]
                    },
                    "visible": {"type": "boolean", "default": True},
                    "hide_all_sketches": {"type": "boolean", "default": False},
                    "hide_all_construction_planes": {"type": "boolean", "default": False},
                    "clear_selection": {"type": "boolean", "default": True}
                }
            }
        },
        {
            "name": "run_fusion_script",
            "description": "FALLBACK TOOL OF LAST RESORT. Do not use this tool when structured MCP tools can inspect, plan, sketch, constrain, feature, parameterize, validate, or export. Requires script_intent and mcp_tool_gap to explain why structured tools are insufficient. Raw scripts that call Fusion export APIs are blocked by default; use export_asset for safe preflight-gated exports.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "The python script to execute"},
                    "script_intent": {
                        "type": "string",
                        "description": "Required. Specific operation this fallback script performs. Use structured MCP inspection/planning tools first."
                    },
                    "mcp_tool_gap": {
                        "type": "string",
                        "description": "Required. Why existing structured MCP tools cannot safely accomplish this operation."
                    },
                    "allow_export": {
                        "type": "boolean",
                        "default": False,
                        "description": "Explicitly allow a raw script that uses Fusion export APIs. Prefer export_asset instead."
                    },
                    "export_override_reason": {
                        "type": "string",
                        "description": "Required when allow_export=true for scripts that use Fusion export APIs."
                    }
                },
                "required": ["script", "script_intent", "mcp_tool_gap"]
            }
        }
    ]
    return _with_tool_annotations(schemas)

def get_resources_schemas():
    schemas = [
        {
            "uri": "fusion://design/parameters",
            "name": "Design Parameters",
            "description": "Live JSON document containing all user parameters and their expressions in the active design.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://design/tree",
            "name": "Assembly Tree",
            "description": "Live JSON document representing the nested component hierarchy and transformations.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://design/summary",
            "name": "Design Summary",
            "description": "High-level summary of the active design including units, root component, and timeline health.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://agent/tool-first-workflow",
            "name": "Tool-First Agent Workflow",
            "description": "Machine-readable policy for choosing structured FusionMCP tools before raw scripts.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://agent/tool-profiles",
            "name": "Tool Profiles",
            "description": "Machine-readable FusionMCP tool groups for client exposure and agent routing.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://agent/server-capabilities",
            "name": "Server Capabilities",
            "description": "Machine-readable summary of Fusion Toolsmith transports, discovery keys, safety gates, profiles, prompts, and capability counts.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://runtime/change-journal",
            "name": "Change Journal",
            "description": "Recent local JSONL journal entries for FusionMCP tool calls.",
            "mimeType": "application/json"
        },
        {
            "uri": "fusion://docs/fusion-api",
            "name": "Fusion API Local Docs",
            "description": "Local Fusion API and best-practices documentation index for script planning.",
            "mimeType": "application/json"
        }
    ]
    return _with_resource_annotations(schemas)

def get_resource_templates():
    templates = [
        {
            "uriTemplate": "fusion://design/tree/{depth}",
            "name": "Assembly Tree by Depth",
            "description": "Live JSON document representing the nested component hierarchy up to a specific depth.",
            "mimeType": "application/json"
        }
    ]
    return _with_resource_annotations(templates, key="uriTemplate")

def log_tool_exception(context, exc):
    message = f"{context}: {exc}\n{traceback.format_exc()}"
    try:
        import adsk.core
        app = adsk.core.Application.get()
        if app:
            app.log(message)
            return
    except Exception:
        pass
    print(message)

def execute_tool(name, arguments):
    if name not in tools_registry:
        return {"error": f"Tool '{name}' not found."}
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return {"error": "Tool arguments must be an object."}
    try:
        return tools_registry[name](**arguments)
    except Exception as e:
        log_tool_exception(f"Tool '{name}' failed", e)
        return {"error": str(e)}

def read_resource(uri):
    # Try exact match first
    if uri in resources_registry:
        try:
            return resources_registry[uri]()
        except Exception as e:
            log_tool_exception(f"Resource '{uri}' failed", e)
            return {"error": str(e)}
            
    # Try wildcard/template match for uri paths like fusion://design/tree/{depth}
    for pattern, handler in resources_registry.items():
        if '{' in pattern or '*' in pattern:
            regex_pattern = re.escape(pattern)
            regex_pattern = re.sub(r'\\\{\w+\\\}', r'([^/]+)', regex_pattern)
            regex_pattern = regex_pattern.replace(r'\*', r'([^/]+)')
            regex_pattern = f"^{regex_pattern}$"
            match = re.match(regex_pattern, uri)
            if match:
                try:
                    args = match.groups()
                    return handler(*args)
                except Exception as e:
                    log_tool_exception(f"Resource '{uri}' failed", e)
                    return {"error": str(e)}
                    
    return {"error": f"Resource '{uri}' not found."}

# Import submodules to register tools/resources
from . import inspection
from . import sketching
from . import features
from . import parametric
from . import utilities
