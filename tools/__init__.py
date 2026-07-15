"""
Tools and Resources Registry Package
"""

import json
import os
import re
import traceback

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
            "name": "fillet_feature",
            "description": "Create a constant-radius fillet on explicit edge indices of a named body with built-in before/after design-state comparison. Inspect or select edges before choosing indices.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Name of the body whose edges should be filleted."},
                    "edge_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Required explicit 0-based edge indices on the body."
                    },
                    "radius": {"type": "string", "description": "Fusion radius expression, e.g. '1 mm'."},
                    "name": {"type": "string", "description": "Optional name for the created fillet feature."},
                    "tangent_chain": {"type": "boolean", "default": True}
                },
                "required": ["body_name", "edge_indices", "radius"]
            }
        },
        {
            "name": "chamfer_feature",
            "description": "Create an equal-distance chamfer on explicit edge indices of a named body with built-in before/after design-state comparison. Inspect or select edges before choosing indices.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "body_name": {"type": "string", "description": "Name of the body whose edges should be chamfered."},
                    "edge_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Required explicit 0-based edge indices on the body."
                    },
                    "distance": {"type": "string", "description": "Fusion chamfer distance expression, e.g. '1 mm'."},
                    "name": {"type": "string", "description": "Optional name for the created chamfer feature."},
                    "tangent_chain": {"type": "boolean", "default": True}
                },
                "required": ["body_name", "edge_indices", "distance"]
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
            "description": "Cut a general hole pattern into a named body. Supports explicit, rectangular, and circular point generation plus through, blind, counterbore, and countersink-intent cuts.",
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
                    "use_selected_plane": {"type": "boolean", "default": False, "description": "If true, offset from the currently selected construction plane or planar face."}
                },
                "required": ["offset"]
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
            "name": "export_asset",
            "description": "Safely export the design to STL or STEP. Runs preflight_export first and blocks compute/timeline-health problems unless allow_unhealthy_export is explicitly true and override_reason explains the risk.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "format": {"type": "string", "enum": ["step", "stl"]},
                    "export_path": {"type": "string"},
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
            "description": "Apply geometric constraints (such as midpoint, horizontal/vertical points, tangent, parallel) between sketch curves or points and return design-state comparison.",
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

def get_resource_templates():
    return [
        {
            "uriTemplate": "fusion://design/tree/{depth}",
            "name": "Assembly Tree by Depth",
            "description": "Live JSON document representing the nested component hierarchy up to a specific depth.",
            "mimeType": "application/json"
        }
    ]

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
