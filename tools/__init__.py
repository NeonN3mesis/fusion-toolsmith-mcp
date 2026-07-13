"""
Tools and Resources Registry Package
"""

import re

tools_registry = {}
resources_registry = {}

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

def get_tool_schemas():
    return [
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
            "name": "inspect_sketch",
            "description": "Return structured sketch details including local-to-model coordinate mapping, points, lines, arcs, circles, dimensions, and geometric constraints.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "Exact sketch name to inspect."}
                },
                "required": ["sketch_name"]
            }
        },
        {
            "name": "inspect_feature",
            "description": "Return structured timeline feature details including operation, extent definitions, health state, participant bodies, result bodies, and feature-specific metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string", "description": "Exact timeline or feature name to inspect."}
                },
                "required": ["feature_name"]
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
            "name": "create_parametric_feature",
            "description": "Create a named sketch as a safe parametric starting point. Use specialized tools like create_box, create_cylinder, create_coil, create_sketch_offset, set_parameter, and modify_parameters for other operations.",
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
            "description": "Create a parametric 3D box (rectangular prism) by sketching a rectangle on a plane and extruding it.",
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
            "description": "Create a parametric 3D cylinder by sketching a circle on a plane and extruding it.",
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
            "name": "create_coil",
            "description": "Create a coil-like helical pipe feature in Fusion 360.",
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
            "description": "Suppress or unsuppress a historical feature in the active design timeline.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the feature in the timeline."},
                    "index": {"type": "integer", "description": "The 0-based timeline index of the feature."},
                    "suppress": {"type": "boolean", "default": True, "description": "True to suppress, False to unsuppress."}
                }
            }
        },
        {
            "name": "delete_timeline_feature",
            "description": "Delete an existing feature from the design timeline.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the feature in the timeline."},
                    "index": {"type": "integer", "description": "The 0-based timeline index of the feature."}
                }
            }
        },
        {
            "name": "get_best_practices",
            "description": "Get Fusion 360 design best practices, coordinate rules (Y-up), body naming conventions, and script execution guidelines.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "apply_appearance",
            "description": "Style a named body in the active design with a materials library appearance.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "The exact name of the body to style (e.g. 'LampBase')."},
                    "appearance_name": {"type": "string", "description": "The name of the appearance (e.g. 'Gold - Polished', 'Steel - Satin', 'Glass - Clear'). Supports case-insensitive partial matching."}
                },
                "required": ["body_name", "appearance_name"]
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
            "description": "Convert an imported STL/OBJ mesh body to a solid B-Rep body.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mesh_body_name": {"type": "string", "description": "The name of the mesh body in the design."},
                    "operation": {"type": "string", "enum": ["new_body", "join", "cut", "intersect"]}
                },
                "required": ["mesh_body_name"]
            }
        },
        {
            "name": "create_2d_drawing",
            "description": "Generate a 2D drafting sheet (blueprint) of the active model and export it to PDF.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "export_pdf_path": {"type": "string", "description": "Absolute path to save the generated PDF drawing blueprint."}
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
            "name": "validate_model",
            "description": "Check for constraints, broken references, timeline warnings, and naming conventions. Instructions: Run this before finishing a task to ensure the model remains in a healthy, parametric state.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "export_asset",
            "description": "Export the design to STL, STEP, or F3D. Instructions: Specify an explicit absolute path. Ensure the design is saved or validated before exporting.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "format": {"type": "string", "enum": ["step", "stl"]},
                    "export_path": {"type": "string"}
                },
                "required": ["format", "export_path"]
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
            "description": "Automatically undo the last CAD operation in the Fusion timeline. Use this if your previous script broke the model.",
            "inputSchema": {"type": "object", "properties": {}}
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
            "name": "edit_sketch_dimension",
            "description": "Modify the value/expression of an existing parametric dimension in a sketch.",
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
            "description": "Delete/remove a specific dimension constraint from a sketch.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The name of the sketch containing the dimension."},
                    "parameter_name": {"type": "string", "description": "The name of the dimension parameter (e.g. 'd5') or the index of the dimension (0-based) to delete."}
                },
                "required": ["sketch_name", "parameter_name"]
            }
        },
        {
            "name": "add_sketch_constraint",
            "description": "Apply geometric constraints (such as midpoint, horizontal/vertical points, tangent, parallel) between sketch curves or points.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sketch_name": {"type": "string", "description": "The name of the sketch to apply constraints in."},
                    "constraint_type": {
                        "type": "string",
                        "enum": ["midpoint", "horizontal_points", "vertical_points", "coincident", "parallel", "perpendicular", "tangent", "equal", "horizontal", "vertical"],
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
            "name": "combine_bodies",
            "description": "Perform a Boolean Combine operation (Join, Cut, or Intersect) between a target body and one or more tool bodies.",
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
                        "default": "join",
                        "description": "The Boolean operation to perform."
                    },
                    "keep_tool_bodies": {"type": "boolean", "default": False, "description": "If true, tool bodies are preserved instead of being consumed/deleted."}
                },
                "required": ["target_body_name", "tool_body_names"]
            }
        },
        {
            "name": "reorganize_body_to_component",
            "description": "Move a solid body from its current component into a different sub-component, creating a new component if requested.",
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
            "name": "run_fusion_script",
            "description": "⚠️ FALLBACK TOOL OF LAST RESORT. Do NOT use this tool if any high-level parametric, inspection, or constraint tools (e.g. modify_parameters, set_parameter, create_box, create_cylinder, etc.) can accomplish the task. Executing arbitrary scripts is dangerous, bypasses safety validation, and can crash Fusion. Use only when absolutely no other tool fits.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "script": {"type": "string", "description": "The python script to execute"}
                },
                "required": ["script"]
            }
        }
    ]

def get_resources_schemas():
    return [
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
        }
    ]

def get_resource_templates():
    return [
        {
            "uriTemplate": "fusion://design/tree/{depth}",
            "name": "Assembly Tree by Depth",
            "description": "Live JSON document representing the nested component hierarchy up to a specific depth.",
            "mimeType": "application/json"
        }
    ]

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
        return {"error": str(e)}

def read_resource(uri):
    # Try exact match first
    if uri in resources_registry:
        try:
            return resources_registry[uri]()
        except Exception as e:
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
                    return {"error": str(e)}
                    
    return {"error": f"Resource '{uri}' not found."}

# Import submodules to register tools/resources
from . import inspection
from . import parametric
from . import utilities
