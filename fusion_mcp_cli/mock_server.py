import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .offline_schema import load_offline_mcp_surface


MOCK_DESIGN_SUMMARY = {
    "mock": True,
    "documentName": "Mock Fusion Toolsmith Design",
    "units": "mm",
    "rootComponent": "Root",
    "bodyCount": 2,
    "componentCount": 1,
    "timelineHealth": {"healthy": True, "warningCount": 0, "errorCount": 0},
}

SPECIALIZED_MOCK_TOOLS = {
    "doctor",
    "inspect_design",
    "get_assembly_tree",
    "validate_model",
    "inspect_mesh_bodies",
    "plan_mesh_conversion",
    "inspect_design_configurations",
    "plan_design_variant",
    "apply_design_variant_parameters",
    "inspect_render_workspace",
    "plan_render_output",
    "render_viewport_output",
    "inspect_document_management_state",
    "plan_document_management_action",
    "create_design_document",
    "export_document_copy",
    "inspect_analysis_capabilities",
    "interference_check",
    "clearance_check",
    "verify_insert_alignment",
    "exact_interference_check",
    "exact_clearance_check",
    "inspect_sheet_metal_rules",
    "preflight_flat_pattern",
    "plan_sheet_metal_workflow",
    "create_flange",
    "create_bend",
    "unfold_sheet_metal",
    "refold_sheet_metal",
    "export_flat_pattern",
    "inspect_surface_bodies",
    "plan_surface_repair",
    "patch_surface",
    "stitch_surfaces",
    "thicken_surface",
    "trim_surface",
    "extend_surface",
    "create_ruled_surface",
    "inspect_simulation_workspace",
    "list_simulation_studies",
    "plan_simulation_study",
    "inspect_manufacturing_workspace",
    "inspect_drawing_documents",
    "preflight_drawing_creation",
    "plan_drawing_views",
    "inspect_electronics_workspace",
    "plan_pcb_enclosure_fit",
    "add_drawing_view",
    "add_drawing_dimension",
    "add_drawing_callout",
    "add_parts_list",
    "add_revision_table",
    "list_manufacturing_setups",
    "inspect_operation",
    "plan_manufacturing_operation",
    "create_manufacturing_setup",
    "create_manufacturing_operation",
    "generate_toolpaths",
    "post_process",
    "edit_extrude_feature",
    "edit_fillet_radius",
    "edit_chamfer_distance",
    "edit_shell_thickness",
    "edit_pattern_parameter",
    "edit_hole_parameter",
    "create_revolute_joint",
    "create_slider_joint",
    "create_cylindrical_joint",
    "create_pin_slot_joint",
    "create_planar_joint",
    "create_ball_joint",
    "plan_joint_limits",
    "set_joint_limits",
    "create_section_analysis",
    "delete_section_analysis",
    "recommend_mcp_workflow",
    "inspect_selection_sets",
    "inspect_3mf_archive",
    "plan_multibody_3mf_export",
    "plan_multicolor_3mf_export",
    "preflight_export",
    "export_asset",
    "create_2d_drawing",
    "capture_view",
    "capture_demo_sequence",
    "create_offset_plane",
    "create_construction_point",
    "create_construction_axis",
    "create_rigid_joint",
    "add_sketch_constraint",
    "delete_sketch_constraint",
    "delete_named_experiment",
    "create_rounded_rectangle_body",
    "create_rounded_slot_cut",
    "create_rounded_pocket",
    "create_box",
    "create_cylinder",
    "create_coil",
    "create_parametric_feature",
    "create_sketch",
    "create_sketch_offset",
    "copy_profile_loop",
    "offset_profile_loop",
    "create_insert_socket",
    "extrude_existing_profile",
    "create_hole_pattern",
    "create_counterbore_hole_pattern",
    "revolve_feature",
    "loft_feature",
    "sweep_feature",
    "shell_body",
    "offset_face_or_press_pull",
    "mirror_features_or_bodies",
    "pattern_feature",
    "convert_mesh_to_solid",
    "repair_mesh_body",
    "reduce_mesh_body",
    "remesh_body",
    "reorganize_body_to_component",
    "set_visibility",
    "close_active_document",
    "set_active_document",
    "set_camera",
    "set_timeline_marker",
    "suppress_timeline_feature",
    "delete_timeline_feature",
    "apply_appearance",
    "modify_parameters",
    "set_parameter",
    "edit_sketch_dimension",
    "delete_sketch_dimension",
    "export_parameters_csv",
    "import_parameters_csv",
}


def _mcp_result(payload):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
        "isError": False,
    }


def _mock_tool_result(name, arguments):
    arguments = arguments or {}
    common = {"mock": True, "tool": name, "arguments": arguments}
    if name == "doctor":
        return {
            "result": {
                **common,
                "status": "ok",
                "toolExecutionReady": True,
                "activeDesignAvailable": True,
                "missingRequiredTools": [],
                "restartRecommended": False,
                "runtime": {
                    "server": "fusion-mcp-mock",
                    "transport": "streamable_http",
                    "taskManagerRunning": True,
                    "pendingTasks": 0,
                },
            }
        }
    if name == "inspect_design":
        return {"result": {**MOCK_DESIGN_SUMMARY, "requestedDetailLevel": arguments.get("detail_level", "summary")}}
    if name == "get_assembly_tree":
        return {
            "result": {
                **common,
                "name": "Root",
                "type": "component",
                "children": [
                    {"name": "Demo Body", "type": "body", "visible": True},
                    {"name": "Reference Body", "type": "body", "visible": False},
                ],
            }
        }
    if name == "validate_model":
        return {"result": {**common, "valid": True, "errors": [], "warnings": []}}
    if name == "inspect_mesh_bodies":
        return {
            "result": {
                **common,
                "readOnly": True,
                "units": "mm",
                "meshBodyCount": 1,
                "meshBodies": [
                    {
                        "name": arguments.get("body_name") or "Mock Mesh Body",
                        "componentName": "Root",
                        "entityToken": "mock-mesh-token",
                        "isVisible": True,
                        "boundingBox": {"min": [0, 0, 0], "max": [4, 3, 2]},
                        "sizeMm": [40, 30, 20],
                        "meshAnalysis": {
                            "status": "available",
                            "quality": arguments.get("mesh_quality", "low"),
                            "nodeCount": 8,
                            "triangleCount": 12,
                            "indexCount": 36,
                        },
                        "conversionBlockers": [
                            "Run plan_mesh_conversion with explicit target, intent, operation, quality-loss acknowledgement, and reason before conversion."
                        ],
                    }
                ],
                "skippedBodies": [],
                "conversionCapabilities": {
                    "meshToBrepAvailable": False,
                    "repairAvailable": False,
                    "reduceAvailable": False,
                    "remeshAvailable": False,
                },
                "notes": ["Mock mode does not inspect real Fusion mesh bodies."],
            }
        }
    if name == "plan_mesh_conversion":
        acknowledged = bool(arguments.get("acknowledge_quality_loss"))
        has_reason = bool(arguments.get("reason"))
        has_target = bool(arguments.get("body_name") or arguments.get("body_entity_token"))
        blockers = []
        if not has_target:
            blockers.append("Provide body_name or body_entity_token from inspect_mesh_bodies.")
        if not has_reason:
            blockers.append("Provide a reason explaining why mesh conversion or repair is needed.")
        if not acknowledged:
            blockers.append("Set acknowledge_quality_loss=true after accepting that mesh conversion can lose detail or create heavy BRep geometry.")
        blockers.append("Mock mode has no real Fusion mesh conversion API.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "ready": False,
                "blockers": blockers,
                "warnings": ["Mesh-to-BRep conversion may create very large timeline features; inspect triangle count before proceeding."],
                "target": {"name": arguments.get("body_name", "Mock Mesh Body"), "entityToken": arguments.get("body_entity_token", "mock-mesh-token")} if has_target else None,
                "conversionCapabilities": {
                    "meshToBrepAvailable": False,
                    "repairAvailable": False,
                    "reduceAvailable": False,
                    "remeshAvailable": False,
                },
                "normalizedRequest": {
                    "conversionIntent": arguments.get("conversion_intent", "convert_to_brep"),
                    "operation": arguments.get("operation", "new_body"),
                    "tolerance": arguments.get("tolerance"),
                    "detailLevel": arguments.get("detail_level"),
                    "acknowledgeQualityLoss": acknowledged,
                    "reason": arguments.get("reason"),
                },
            }
        }
    if name == "inspect_design_configurations":
        return {
            "result": {
                **common,
                "readOnly": True,
                "configurationCollectionAvailable": True,
                "collectionSource": "mock.configurations",
                "activeConfiguration": {"index": 0, "name": "Default", "isActive": True},
                "configurationCount": 2,
                "configurations": [
                    {"index": 0, "name": "Default", "isActive": True, "parameterCount": 1, "parameters": [{"name": "width", "expression": "80 mm"}]},
                    {"index": 1, "name": "Wide", "isActive": False, "parameterCount": 1, "parameters": [{"name": "width", "expression": "100 mm"}]},
                ],
                "userParameters": [
                    {"name": "width", "parameterType": "user", "expression": "80 mm", "unit": "mm"},
                    {"name": "height", "parameterType": "user", "expression": "50 mm", "unit": "mm"},
                ],
                "blockingReasons": [],
                "warnings": ["Mock mode does not inspect real Fusion design configurations."],
            }
        }
    if name == "plan_design_variant":
        approved = bool(arguments.get("requires_user_approval"))
        parameter_changes = arguments.get("parameter_changes") or {}
        blockers = []
        if not arguments.get("variant_name"):
            blockers.append("variant_name is required.")
        if not parameter_changes:
            blockers.append("parameter_changes must be a non-empty object mapping parameter names to explicit expressions.")
        if not arguments.get("reason"):
            blockers.append("reason is required for design-variant planning.")
        if not approved:
            blockers.append("requires_user_approval must be true before any configuration or parameter-set mutation.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": not blockers,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "variant": {
                    "name": arguments.get("variant_name"),
                    "baseConfiguration": arguments.get("base_configuration"),
                    "parameterChanges": parameter_changes,
                    "expectedAffectedBodies": arguments.get("expected_affected_bodies") or [],
                    "expectedAffectedFeatures": arguments.get("expected_affected_features") or [],
                },
                "requiresUserApproval": approved,
                "warnings": ["Mock mode plans design variants but does not create configurations or edit parameters."],
            }
        }
    if name == "apply_design_variant_parameters":
        parameter_changes = arguments.get("parameter_changes") or {}
        return {
            "result": {
                **common,
                "applied": True,
                "variantName": arguments.get("variant_name"),
                "baseConfiguration": arguments.get("base_configuration"),
                "parameterCount": len(parameter_changes),
                "parameters": [
                    {
                        "name": key,
                        "before": {"name": key, "expression": "mock-before"},
                        "after": {"name": key, "expression": value},
                    }
                    for key, value in sorted(parameter_changes.items())
                ],
                "preflight": {
                    "readOnly": True,
                    "okToProceed": True,
                    "blockingReasons": [],
                    "variant": {
                        "name": arguments.get("variant_name"),
                        "baseConfiguration": arguments.get("base_configuration"),
                        "parameterChanges": parameter_changes,
                    },
                    "requiresUserApproval": bool(arguments.get("requires_user_approval")),
                },
                "stateComparison": {"hasChanges": bool(parameter_changes), "riskLevel": "medium"},
                "note": "Mock mode does not edit Fusion parameters or create configuration rows.",
            }
        }
    if name == "inspect_analysis_capabilities":
        return {
            "result": {
                **common,
                "readOnly": True,
                "broadPhaseAvailable": True,
                "visibleBodyCount": 2,
                "exactInterference": {
                    "supported": False,
                    "status": "unsupported",
                    "temporaryBRepManagerAvailable": False,
                    "copyCandidate": {"available": False, "method": None},
                    "booleanCandidate": {"available": False, "method": None},
                },
                "exactMinimumDistance": {
                    "supported": False,
                    "status": "unsupported",
                    "measureManagerAvailable": False,
                    "distanceCandidate": {"available": False, "method": None},
                },
                "blockingReasons": ["Mock mode has no real Fusion BRep or measure-manager APIs."],
                "warnings": ["Mock mode does not run exact analysis."],
            }
        }
    if name == "interference_check":
        return {
            "result": {
                **common,
                "readOnly": True,
                "method": "axis_aligned_bounding_box",
                "bodyCount": 2,
                "pairCount": 1,
                "interferenceCount": 0,
                "interferences": [],
                "checkedPairs": [
                    {
                        "bodyA": {"bodyName": "Demo Body", "componentName": "Root"},
                        "bodyB": {"bodyName": "Reference Body", "componentName": "Root"},
                        "bboxIntersects": False,
                        "bboxDistanceMm": 12.5,
                        "method": "axis_aligned_bounding_box",
                    }
                ],
                "warnings": ["Mock mode does not inspect real geometry."],
            }
        }
    if name == "clearance_check":
        return {
            "result": {
                **common,
                "readOnly": True,
                "method": "axis_aligned_bounding_box",
                "minimumClearanceMm": arguments.get("minimum_clearance", "0 mm"),
                "targetCount": 1,
                "toolCount": 1,
                "pairCount": 1,
                "violationCount": 0,
                "violations": [],
                "warnings": ["Mock mode does not inspect real geometry."],
            }
        }
    if name == "exact_interference_check":
        return {
            "result": {
                **common,
                "readOnly": True,
                "method": "temporary_brep_boolean_intersection",
                "validatedExact": False,
                "bodyCount": 2,
                "pairCount": 1,
                "interferenceCount": 0,
                "interferences": [],
                "checkedPairs": [],
                "errors": [],
                "warnings": ["Mock mode does not run exact BRep Boolean analysis."],
            }
        }
    if name == "exact_clearance_check":
        return {
            "result": {
                **common,
                "readOnly": True,
                "method": "measure_manager_minimum_distance",
                "validatedExact": False,
                "minimumClearanceMm": arguments.get("minimum_clearance", "0 mm"),
                "targetCount": 1,
                "toolCount": 1,
                "pairCount": 1,
                "violationCount": 0,
                "violations": [],
                "checkedPairs": [],
                "errors": [],
                "warnings": ["Mock mode does not run exact minimum-distance analysis."],
            }
        }
    if name == "inspect_sheet_metal_rules":
        return {
            "result": {
                **common,
                "readOnly": True,
                "activeRule": {
                    "name": "Mock Sheet Metal Rule",
                    "thicknessExpression": "1 mm",
                    "bendRadiusExpression": "1 mm",
                    "kFactorValue": 0.44,
                },
                "ruleCount": 1,
                "sheetMetalBodyCount": 1,
                "warnings": ["Mock mode does not inspect real sheet-metal rules."],
            }
        }
    if name == "preflight_flat_pattern":
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": False,
                "riskLevel": "high",
                "blockingReasons": ["Mock mode has no real flatPattern object."],
                "flatPatternAvailable": False,
                "warnings": ["Mock mode does not export or unfold sheet metal."],
            }
        }
    if name == "plan_sheet_metal_workflow":
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": bool(arguments.get("operation")),
                "riskLevel": "medium" if arguments.get("operation") else "high",
                "blockingReasons": [] if arguments.get("operation") else ["operation must be supplied."],
                "operation": arguments.get("operation"),
                "targetBody": {"bodyName": arguments.get("body_name", "Mock Sheet Metal Body"), "entityToken": arguments.get("body_entity_token"), "isSheetMetal": True},
                "ruleName": arguments.get("rule_name", "Mock Sheet Metal Rule"),
                "edgeEntityTokens": arguments.get("edge_entity_tokens", []),
                "faceEntityTokens": arguments.get("face_entity_tokens", []),
                "parameters": arguments.get("parameters", {}),
                "reason": arguments.get("reason"),
                "inspection": {"sheetMetalBodyCount": 1, "activeRule": {"name": "Mock Sheet Metal Rule"}},
                "flatPatternPreflight": {"okToProceed": False, "flatPatternAvailable": False},
                "warnings": ["Mock mode plans sheet-metal workflows but does not create, unfold, refold, or export sheet metal."],
            }
        }
    if name in {"create_flange", "create_bend", "unfold_sheet_metal", "refold_sheet_metal"}:
        return {
            "result": {
                **common,
                "message": f"Mock executed {name} on sheet-metal body.",
                "operation": name,
                "featureName": f"Mock {name.replace('_', ' ').title()}",
                "bodyName": arguments.get("body_name", "Mock Sheet Metal Body"),
                "bodyEntityToken": arguments.get("body_entity_token", "mock-sheet-body-token"),
                "ruleName": arguments.get("rule_name"),
                "edgeEntityTokens": arguments.get("edge_entity_tokens", []),
                "faceEntityTokens": arguments.get("face_entity_tokens", []),
                "parameters": arguments.get("parameters", {}),
                "appliedParameters": {},
                "reason": arguments.get("reason"),
                "preflight": {
                    "okToProceed": True,
                    "operation": name,
                    "targetBody": {"bodyName": arguments.get("body_name", "Mock Sheet Metal Body"), "isSheetMetal": True},
                    "warnings": ["Mock mode does not inspect real sheet-metal geometry."],
                },
                "stateComparison": {"changed": True, "changes": ["mock sheet-metal feature added"]},
                "warnings": ["Mock mode does not modify Fusion sheet-metal geometry."],
            }
        }
    if name == "export_flat_pattern":
        return {
            "result": {
                **common,
                "exported": True,
                "format": arguments.get("format", "dxf"),
                "exportPath": arguments.get("export_path"),
                "allowedBlockedExport": bool(arguments.get("allow_blocked_export", False)),
                "overrideReason": arguments.get("override_reason") if arguments.get("allow_blocked_export", False) else None,
                "preflight": {"okToProceed": True, "riskLevel": "none", "blockingReasons": []},
                "note": "Mock mode does not write flat-pattern files.",
            }
        }
    if name == "inspect_surface_bodies":
        return {
            "result": {
                **common,
                "readOnly": True,
                "bodyCount": 2,
                "surfaceBodyCount": 1,
                "solidBodyCount": 1,
                "bodies": [
                    {"bodyName": "Mock Solid", "classification": "solid", "isSolid": True, "faceCount": 6, "openEdgeCount": 0},
                    {"bodyName": "Mock Surface", "classification": "surface", "isSolid": False, "faceCount": 1, "openEdgeCount": 4, "candidateRepairTools": ["patch_surface", "stitch_surfaces", "thicken_surface"]},
                ],
                "warnings": ["Mock mode does not inspect real surface topology."],
            }
        }
    if name == "plan_surface_repair":
        operation = arguments.get("operation", "patch_surface")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": bool(arguments.get("body_name") or arguments.get("body_entity_token")),
                "riskLevel": "medium" if (arguments.get("body_name") or arguments.get("body_entity_token")) else "high",
                "blockingReasons": [] if (arguments.get("body_name") or arguments.get("body_entity_token")) else ["body_name or body_entity_token is required."],
                "operation": operation,
                "target": {"bodyName": arguments.get("body_name", "Mock Surface"), "classification": "surface", "entityToken": arguments.get("body_entity_token")},
                "edgeEntityTokens": arguments.get("edge_entity_tokens", []),
                "faceEntityTokens": arguments.get("face_entity_tokens", []),
                "parameters": arguments.get("parameters", {}),
                "reason": arguments.get("reason"),
                "inspection": {"surfaceBodyCount": 1, "warnings": ["Mock mode does not inspect real surface topology."]},
                "warnings": ["Mock mode plans surface repair but does not modify Fusion geometry."],
            }
        }
    if name in {"patch_surface", "stitch_surfaces", "thicken_surface", "trim_surface", "extend_surface", "create_ruled_surface"}:
        return {
            "result": {
                **common,
                "message": f"Mock executed {name} on target body.",
                "operation": name,
                "featureName": f"Mock {name.replace('_', ' ').title()}",
                "bodyName": arguments.get("body_name", "Mock Surface"),
                "bodyEntityToken": arguments.get("body_entity_token", "mock-surface-token"),
                "edgeEntityTokens": arguments.get("edge_entity_tokens", []),
                "faceEntityTokens": arguments.get("face_entity_tokens", []),
                "parameters": arguments.get("parameters", {}),
                "appliedParameters": {},
                "reason": arguments.get("reason"),
                "preflight": {
                    "okToProceed": True,
                    "operation": name,
                    "target": {"bodyName": arguments.get("body_name", "Mock Surface"), "classification": "surface"},
                    "warnings": ["Mock mode does not inspect real surface topology."],
                },
                "stateComparison": {"changed": True, "changes": ["mock surface feature added"]},
                "warnings": ["Mock mode does not modify Fusion geometry."],
            }
        }
    if name == "inspect_manufacturing_workspace":
        return {
            "result": {
                **common,
                "readOnly": True,
                "workspaceAvailable": True,
                "okToInspectSetups": True,
                "blockingReasons": [],
                "manufacturingProduct": {
                    "objectType": "adsk::cam::CAM",
                    "productName": "Mock Manufacture",
                    "setupCount": 1,
                    "setupsAvailable": True,
                },
                "warnings": ["Mock mode does not inspect real CAM data."],
            }
        }
    if name == "inspect_drawing_documents":
        return {
            "result": {
                **common,
                "readOnly": True,
                "openDocumentCount": 1,
                "drawingDocumentCount": 1,
                "activeDocument": "Mock Drawing",
                "documents": [
                    {
                        "index": 0,
                        "name": "Mock Drawing",
                        "isDrawingDocument": True,
                        "sheetCount": 1,
                        "sheets": [{"index": 0, "name": "Sheet 1", "viewCount": 1, "views": [{"index": 0, "name": "Base View"}]}],
                    }
                ],
                "warnings": ["Mock mode does not inspect real drawing documents."],
            }
        }
    if name == "preflight_drawing_creation":
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": True,
                "riskLevel": "low",
                "blockingReasons": [],
                "activeDocument": {"name": "Mock Fusion Toolsmith Design", "isSaved": True},
                "exportPdfPath": arguments.get("export_pdf_path"),
                "drawingManagerAvailable": True,
                "warnings": ["Mock mode does not create or export drawings."],
            }
        }
    if name == "plan_drawing_views":
        views = arguments.get("views") or [{"name": "Base View", "orientation": "front", "scale": 1.0, "style": "visible", "placement": "center"}]
        if isinstance(views, dict):
            views = [views]
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": True,
                "riskLevel": "low",
                "blockingReasons": [],
                "sheet": {
                    "standard": arguments.get("standard", "ASME"),
                    "sheetSize": arguments.get("sheet_size", "A"),
                    "orientation": arguments.get("sheet_orientation", "landscape"),
                    "units": arguments.get("units", "mm"),
                    "titleBlock": arguments.get("title_block"),
                },
                "views": views,
                "exportPdfPath": arguments.get("export_pdf_path"),
                "preflight": {"okToProceed": True, "blockingReasons": []},
                "warnings": ["Mock mode plans drawing views but does not create drawing documents."],
            }
        }
    if name == "inspect_electronics_workspace":
        return {
            "result": {
                **common,
                "readOnly": True,
                "workspaceAvailable": True,
                "okToInspectBoards": True,
                "blockingReasons": [],
                "electronicsProduct": {
                    "objectType": "adsk::electronics::ElectronicsProduct",
                    "productName": "ElectronicsProductType",
                    "boardCount": 1,
                    "boardOutlineCount": 1,
                    "componentCount": 2,
                    "netCount": 3,
                    "connectorCandidateCount": 1,
                    "boards": [{"index": 0, "name": "Mock Board"}],
                    "boardOutlines": [{"index": 0, "name": "Mock Board Outline", "sizeMm": [80, 50, 1.6]}],
                    "components": [{"index": 0, "name": "J1 USB-C", "designator": "J1"}, {"index": 1, "name": "U1 MCU", "designator": "U1"}],
                    "nets": [{"index": 0, "name": "GND"}, {"index": 1, "name": "VBUS"}, {"index": 2, "name": "D+"}],
                    "connectorCandidates": [{"index": 0, "name": "J1 USB-C", "designator": "J1"}],
                },
                "warnings": ["Mock mode does not inspect real Fusion Electronics data."],
                "notes": ["Mock mode does not edit boards, components, nets, or mechanical links."],
            }
        }
    if name == "plan_pcb_enclosure_fit":
        approved = bool(arguments.get("requires_user_approval"))
        blockers = []
        for key in ("board_outline", "keepouts", "connectors", "mounting_holes", "clearance_rules", "reason"):
            if not arguments.get(key):
                blockers.append(f"{key} is required.")
        if not approved:
            blockers.append("requires_user_approval must be true before any electronics/mechanical bridge action.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": not blockers,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "boardOutline": arguments.get("board_outline") or {},
                "keepouts": arguments.get("keepouts") or {},
                "connectors": arguments.get("connectors") or {},
                "mountingHoles": arguments.get("mounting_holes") or {},
                "clearanceRules": arguments.get("clearance_rules") or {},
                "targetEnclosureBodies": [],
                "linkedMechanicalReference": arguments.get("linked_mechanical_reference"),
                "reason": arguments.get("reason"),
                "requiresUserApproval": approved,
                "warnings": ["Mock mode plans PCB enclosure fit but does not sync boards or edit mechanical geometry."],
            }
        }
    if name in {"add_drawing_view", "add_drawing_dimension", "add_drawing_callout", "add_parts_list", "add_revision_table"}:
        return {
            "result": {
                **common,
                "message": f"Mock executed {name} on drawing sheet.",
                "operation": name,
                "sheetName": arguments.get("sheet_name", "Mock Sheet 1"),
                "createdName": f"Mock {name.replace('_', ' ').title()}",
                "createdObjectType": "MockDrawingObject",
                "payload": {key: value for key, value in arguments.items() if key != "reason"},
                "reason": arguments.get("reason"),
                "stateComparison": {"changed": True, "changes": ["mock drawing object added"]},
                "warnings": ["Mock mode does not modify Fusion drawing documents."],
            }
        }
    if name == "inspect_simulation_workspace":
        return {
            "result": {
                **common,
                "readOnly": True,
                "workspaceAvailable": True,
                "okToInspectStudies": True,
                "blockingReasons": [],
                "simulationProduct": {
                    "objectType": "adsk::fusion::SimulationProduct",
                    "productName": "SimulationProductType",
                    "studyCount": 1,
                    "studiesAvailable": True,
                },
                "warnings": ["Mock mode does not inspect real Simulation products."],
            }
        }
    if name == "list_simulation_studies":
        return {
            "result": {
                **common,
                "readOnly": True,
                "studyCount": 1,
                "includeDetails": arguments.get("include_details", True),
                "studies": [
                    {
                        "index": 0,
                        "name": "Mock Static Stress",
                        "studyType": "static_stress",
                        "solveStatus": "not_solved",
                        "isSolved": False,
                        "loadCount": 1,
                        "constraintCount": 1,
                        "materialCount": 1,
                        "contactCount": 0,
                        "resultCount": 0,
                        "meshAvailable": False,
                    }
                ],
                "blockingReasons": [],
                "warnings": ["Mock mode does not mesh, solve, or export Simulation studies."],
            }
        }
    if name == "plan_simulation_study":
        approved = bool(arguments.get("requires_user_approval"))
        blockers = []
        for key in ("study_name", "study_type", "materials", "loads", "constraints", "mesh_settings", "result_outputs"):
            if not arguments.get(key):
                blockers.append(f"{key} is required.")
        if not (arguments.get("target_body_names") or arguments.get("target_body_entity_tokens")):
            blockers.append("target_body_names or target_body_entity_tokens are required.")
        if not approved:
            blockers.append("requires_user_approval must be true before any simulation study creation, meshing, solving, or result export.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": not blockers,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "study": {
                    "name": arguments.get("study_name"),
                    "type": arguments.get("study_type"),
                    "targetBodies": [],
                    "materials": arguments.get("materials") or {},
                    "loads": arguments.get("loads") or {},
                    "constraints": arguments.get("constraints") or {},
                    "contacts": arguments.get("contacts") or {},
                    "meshSettings": arguments.get("mesh_settings") or {},
                    "resultOutputs": arguments.get("result_outputs") or {},
                },
                "requiresUserApproval": approved,
                "warnings": ["Mock mode plans Simulation studies but does not create, mesh, solve, or export them."],
            }
        }
    if name == "list_manufacturing_setups":
        return {
            "result": {
                **common,
                "readOnly": True,
                "setupCount": 1,
                "includeOperations": arguments.get("include_operations", True),
                "setups": [
                    {
                        "index": 0,
                        "name": "Mock Setup",
                        "operationCount": 1,
                        "operations": [{"index": 0, "setupName": "Mock Setup", "name": "Mock Adaptive", "hasToolpath": False}],
                    }
                ],
                "blockingReasons": [],
                "warnings": ["Mock mode does not inspect real CAM setups."],
            }
        }
    if name == "inspect_operation":
        return {
            "result": {
                **common,
                "readOnly": True,
                "matchCount": 1,
                "operations": [
                    {
                        "index": arguments.get("operation_index", 0),
                        "setupName": arguments.get("setup_name", "Mock Setup"),
                        "name": arguments.get("operation_name", "Mock Adaptive"),
                        "hasToolpath": False,
                    }
                ],
                "blockingReasons": [],
                "warnings": ["Mock mode does not generate toolpaths or post-process output."],
            }
        }
    if name == "plan_manufacturing_operation":
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": bool(arguments.get("requires_user_approval", False)),
                "riskLevel": "medium" if arguments.get("requires_user_approval", False) else "high",
                "blockingReasons": [] if arguments.get("requires_user_approval", False) else ["requires_user_approval must be true before any future toolpath generation or post-processing step."],
                "setup": {
                    "name": arguments.get("setup_name", "Mock Setup"),
                    "machine": arguments.get("machine", {}),
                    "stock": arguments.get("stock", {}),
                    "wcs": arguments.get("wcs", {}),
                },
                "operation": {
                    "name": arguments.get("operation_name", "Mock Operation"),
                    "type": arguments.get("operation_type", "adaptive"),
                    "tool": arguments.get("tool", {}),
                    "feeds": arguments.get("feeds", {}),
                    "speeds": arguments.get("speeds", {}),
                },
                "postProcessor": arguments.get("post_processor", {}),
                "requiresUserApproval": bool(arguments.get("requires_user_approval", False)),
                "workspace": {"workspaceAvailable": True, "okToInspectSetups": True},
                "warnings": ["Mock mode plans manufacturing data but does not create setups, generate toolpaths, or post-process output."],
            }
        }
    if name in {"create_manufacturing_setup", "create_manufacturing_operation", "generate_toolpaths", "post_process"}:
        result = {
            **common,
            "operation": name,
            "setupName": arguments.get("setup_name", "Mock Setup"),
            "operationName": arguments.get("operation_name", "Mock Operation"),
            "preflight": {
                "okToProceed": bool(arguments.get("requires_user_approval", False)),
                "requiresUserApproval": bool(arguments.get("requires_user_approval", False)),
                "warnings": ["Mock mode does not execute real CAM actions."],
            },
            "stateComparison": {"changed": True, "changes": ["mock CAM state changed"]},
            "warnings": ["Mock mode does not create setups, generate toolpaths, or post-process output."],
        }
        if name == "create_manufacturing_setup":
            result.update({"message": "Mock created manufacturing setup.", "setupObjectType": "MockSetup"})
        elif name == "create_manufacturing_operation":
            result.update({"message": "Mock created manufacturing operation.", "operationObjectType": "MockOperation"})
        elif name == "generate_toolpaths":
            result.update({"message": "Mock generated toolpaths.", "generated": True})
        elif name == "post_process":
            result.update({"message": "Mock post-processed output.", "posted": True, "outputPath": arguments.get("output_path")})
        return {"result": result}
    if name in {
        "edit_extrude_feature",
        "edit_fillet_radius",
        "edit_chamfer_distance",
        "edit_shell_thickness",
        "edit_pattern_parameter",
        "edit_hole_parameter",
    }:
        expression = (
            arguments.get("distance")
            or arguments.get("radius")
            or arguments.get("thickness")
            or arguments.get("expression")
        )
        return {
            "result": {
                **common,
                "featureName": arguments.get("feature_name", "MockFeature"),
                "parameterName": arguments.get("parameter_name", "mockParameter"),
                "before": {"name": arguments.get("parameter_name", "mockParameter"), "expression": "1 mm"},
                "after": {"name": arguments.get("parameter_name", "mockParameter"), "expression": expression},
                "operationChange": {
                    "requested": arguments.get("operation"),
                    "before": "NewBody",
                    "after": arguments.get("operation"),
                } if arguments.get("operation") else None,
                "impactReport": {"okToProceed": True, "riskLevel": "low"},
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not edit Fusion geometry.",
            }
        }
    if name in {
        "create_revolute_joint",
        "create_slider_joint",
        "create_cylindrical_joint",
        "create_pin_slot_joint",
        "create_planar_joint",
        "create_ball_joint",
    }:
        return {
            "result": {
                **common,
                "jointName": arguments.get("name", "Mock Joint"),
                "jointKind": name.replace("create_", "").replace("_joint", ""),
                "pointOneName": arguments.get("point_one_name"),
                "pointTwoName": arguments.get("point_two_name"),
                "motionAxis": arguments.get("motion_axis"),
                "slideDirection": arguments.get("slide_direction"),
                "normalDirection": arguments.get("normal_direction"),
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not create Fusion assembly joints.",
            }
        }
    if name == "plan_joint_limits":
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": bool(arguments.get("joint_name") or arguments.get("joint_entity_token")),
                "riskLevel": "medium" if (arguments.get("joint_name") or arguments.get("joint_entity_token")) else "high",
                "blockingReasons": [] if (arguments.get("joint_name") or arguments.get("joint_entity_token")) else ["joint_name or joint_entity_token is required."],
                "joint": {
                    "name": arguments.get("joint_name", "Mock Joint"),
                    "entityToken": arguments.get("joint_entity_token"),
                    "jointMotion": {"jointType": "revolute", "rotationLimits": {}},
                },
                "limitType": arguments.get("limit_type", "rotation"),
                "requestedLimits": {
                    "enableMinimum": arguments.get("enable_minimum", True),
                    "minimum": arguments.get("minimum"),
                    "enableMaximum": arguments.get("enable_maximum", True),
                    "maximum": arguments.get("maximum"),
                    "enableRest": arguments.get("enable_rest", False),
                    "rest": arguments.get("rest"),
                },
                "reason": arguments.get("reason"),
                "warnings": ["Mock mode plans joint limits but does not edit Fusion assembly joints."],
            }
        }
    if name == "set_joint_limits":
        return {
            "result": {
                **common,
                "jointName": arguments.get("joint_name", "Mock Joint"),
                "jointEntityToken": arguments.get("joint_entity_token"),
                "limitType": arguments.get("limit_type", "rotation"),
                "requestedLimits": {
                    "enableMinimum": arguments.get("enable_minimum", True),
                    "minimum": arguments.get("minimum"),
                    "enableMaximum": arguments.get("enable_maximum", True),
                    "maximum": arguments.get("maximum"),
                    "enableRest": arguments.get("enable_rest", False),
                    "rest": arguments.get("rest"),
                },
                "preflight": {"okToProceed": True, "riskLevel": "medium"},
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not edit Fusion assembly joint limits.",
            }
        }
    if name == "create_section_analysis":
        return {
            "result": {
                **common,
                "sectionAnalysisName": arguments.get("name", "Mock Section Analysis"),
                "planeName": arguments.get("plane_name", "xy"),
                "activated": arguments.get("activate", True),
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not create Fusion section-analysis entities.",
            }
        }
    if name == "delete_section_analysis":
        return {
            "result": {
                **common,
                "sectionAnalysisName": arguments.get("name", "Mock Section Analysis"),
                "deletedCount": 1,
                "reason": arguments.get("reason"),
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not delete Fusion section-analysis entities.",
            }
        }
    if name == "delete_named_experiment":
        requested_names = arguments.get("names") or ["MockExperimentFeature"]
        if isinstance(requested_names, str):
            requested_names = [requested_names]
        dry_run = not bool(arguments.get("confirm_delete"))
        matches = [
            {"kind": "timeline", "name": item, "componentName": None, "identifier": index}
            for index, item in enumerate(requested_names)
        ]
        return {
            "result": {
                **common,
                "dryRun": dry_run,
                "deleted": not dry_run,
                "matchCount": len(matches),
                "matches": matches if dry_run else None,
                "deletedCount": 0 if dry_run else len(matches),
                "deletedItems": [] if dry_run else matches,
                "errorCount": 0,
                "errors": [],
                "reason": arguments.get("reason"),
                "stateComparison": None if dry_run else {"hasChanges": True, "riskLevel": "high"},
                "note": "Mock mode does not delete Fusion experimental artifacts.",
            }
        }
    if name == "recommend_mcp_workflow":
        return {
            "result": {
                **common,
                "recommendedFirstTools": ["doctor", "inspect_design", "validate_model"],
                "rawScriptAllowed": bool(arguments.get("allow_raw_script")),
                "notes": ["Mock mode returns deterministic planning data without Fusion."],
            }
        }
    if name == "preflight_export":
        return {
            "result": {
                **common,
                "okToExport": True,
                "blockingReasons": [],
                "warnings": ["Mock mode does not inspect real geometry."],
            }
        }
    if name == "inspect_selection_sets":
        requested = arguments.get("names")
        if isinstance(requested, str):
            requested_names = [requested]
        elif isinstance(requested, list):
            requested_names = requested
        else:
            requested_names = ["Selection Set2", "Selection Set3"]
        return {
            "result": {
                **common,
                "count": len(requested_names),
                "selectionSets": [
                    {
                        "name": set_name,
                        "entityCount": 1,
                        "entities": [
                            {
                                "kind": "BRepBody",
                                "bodyName": f"MockBody{index + 1}",
                                "componentName": "Root",
                                "entityToken": f"mock-body-token-{index + 1}",
                            }
                        ],
                    }
                    for index, set_name in enumerate(requested_names)
                ],
                "missingSelectionSets": [],
            }
        }
    if name == "plan_multibody_3mf_export":
        requested_bodies = arguments.get("body_names") or []
        if isinstance(requested_bodies, str):
            requested_bodies = [requested_bodies]
        requested_tokens = arguments.get("body_entity_tokens") or []
        if isinstance(requested_tokens, str):
            requested_tokens = [requested_tokens]
        requested_sets = arguments.get("selection_set_names") or []
        if isinstance(requested_sets, str):
            requested_sets = [requested_sets]
        target_count = len(requested_bodies) + len(requested_tokens) + len(requested_sets)
        blockers = []
        if not arguments.get("export_path"):
            blockers.append("export_path is required.")
        if target_count == 0:
            blockers.append("No BRep bodies were resolved for 3MF export. Provide body_names, body_entity_tokens, or selection_set_names.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToExport": not blockers,
                "blockingReasons": blockers,
                "warnings": ["Mock mode does not inspect real Fusion selection sets."],
                "format": "3mf",
                "exportPath": arguments.get("export_path"),
                "targetBodyCount": target_count,
                "targetBodies": [
                    {"name": name, "componentName": "Root", "entityToken": f"mock-token-{index + 1}"}
                    for index, name in enumerate(requested_bodies or ["MockBody"])
                ][:target_count or 0],
                "targetResolution": {
                    "requestedBodyNames": requested_bodies,
                    "requestedBodyEntityTokens": requested_tokens,
                    "requestedSelectionSetNames": requested_sets,
                    "selectionSets": [
                        {"name": set_name, "entityCount": 1, "bodyCount": 1, "nonBodyEntityCount": 0, "nonBodyEntities": []}
                        for set_name in requested_sets
                    ],
                },
                "preflight": {"okToExport": True, "blockingReasons": []},
            }
        }
    if name == "verify_insert_alignment":
        separated = bool(arguments.get("mock_separated_logo"))
        blockers = ["Logo bodies appear separated above the plate: MockLogo."] if separated else []
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToExport": not blockers,
                "method": "axis_aligned_bounding_box",
                "blockingReasons": blockers,
                "warnings": ["Mock mode does not inspect real Fusion BRep geometry."],
                "checks": {
                    "plateSocketFootprintOverlap": True,
                    "socketDepthMatchesPlateThickness": True,
                    "expectedPlateThicknessMatches": True,
                    "flushMode": arguments.get("flush_mode", "flush"),
                    "centerOffsetMm": [0.0, 0.0],
                    "depthDeltaMm": 0.0,
                    "expectedThicknessDeltaMm": None,
                    "toleranceMm": 0.05,
                    "thicknessAxis": arguments.get("thickness_axis", "z"),
                    "logoBodiesOnOrIntersectPlate": not separated,
                    "logoBodyCount": 1 if arguments.get("logo_body_names") else 0,
                    "mirroredOrSeparatedGeometrySuspect": separated,
                },
                "plate": {
                    "bodyName": arguments.get("plate_body_name", "MockPlate"),
                    "componentName": "Root",
                    "entityToken": "mock-plate-token",
                    "boundingBox": {"min": [0, 0, 0], "max": [4, 3, 0.2]},
                    "sizeMm": [40.0, 30.0, 2.0],
                },
                "socket": {
                    "bodyName": arguments.get("socket_body_name", "MockSocket"),
                    "componentName": "Root",
                    "entityToken": "mock-socket-token",
                    "boundingBox": {"min": [0, 0, 0], "max": [4, 3, 0.2]},
                    "sizeMm": [40.0, 30.0, 2.0],
                    "footprintOverlapWithPlate": {"overlaps": True, "overlapMm": [40.0, 30.0], "overlapAreaMm2": 1200.0},
                },
                "logoBodies": [
                    {
                        "bodyName": "MockLogo",
                        "componentName": "Root",
                        "entityToken": "mock-logo-token",
                        "separatedFromPlate": separated,
                        "footprintOverlapWithPlate": {"overlaps": True, "overlapMm": [10.0, 8.0], "overlapAreaMm2": 80.0},
                        "minAbovePlateTopMm": 1.0 if separated else -0.01,
                    }
                ] if arguments.get("logo_body_names") else [],
                "nextActions": [
                    "Fix blocking alignment issues before calling plan_multibody_3mf_export or export_asset.",
                    "Use exact Fusion inspection or section analysis if bounding boxes are too coarse for the geometry.",
                ],
            }
        }
    if name == "inspect_3mf_archive":
        expected_count = arguments.get("expected_body_count") or 2
        return {
            "result": {
                **common,
                "path": arguments.get("export_path"),
                "exists": True,
                "sizeBytes": 1024,
                "isZip": True,
                "has3DModelPart": True,
                "modelPart": "3D/3dmodel.model",
                "objectCount": int(expected_count),
                "meshObjectCount": int(expected_count),
                "componentObjectCount": 0,
                "componentReferenceCount": 0,
                "buildItemCount": int(expected_count),
                "objectIds": [str(index + 1) for index in range(int(expected_count))],
                "buildObjectIds": [str(index + 1) for index in range(int(expected_count))],
                "componentObjectIds": [],
                "missingBuildObjectIds": [],
                "missingComponentObjectIds": [],
                "separateObjectCandidateCount": int(expected_count),
                "slicerColorabilityLikely": int(expected_count) > 1,
                "valid": True,
                "printReadiness": {
                    "status": "warning",
                    "readyForSlicerImport": True,
                    "readyForMulticolorAssignment": int(expected_count) > 1,
                    "blockingReasons": [],
                    "warnings": ["Mock mode does not read real 3MF files."],
                    "nextActions": ["Open the 3MF in the slicer and verify each intended body is separately colorable."],
                },
                "metadata": {},
                "warnings": ["Mock mode does not read real 3MF files."],
            }
        }
    if name == "plan_multicolor_3mf_export":
        assignments = arguments.get("color_assignments") or []
        blockers = []
        if not arguments.get("export_path"):
            blockers.append("export_path is required.")
        if not assignments:
            blockers.append("No BRep bodies were resolved for 3MF export. Provide body_names, body_entity_tokens, or selection_set_names.")
        return {
            "result": {
                **common,
                "okToExport": not blockers,
                "blockingReasons": blockers,
                "warnings": ["Mock mode does not inspect real Fusion appearances or selection sets."],
                "exportPlan": {
                    "okToExport": not blockers,
                    "blockingReasons": blockers,
                    "exportPath": arguments.get("export_path"),
                    "format": "3mf",
                    "targetBodyCount": len(assignments),
                    "allowOverwrite": bool(arguments.get("allow_overwrite")),
                    "preflight": {"okToExport": True, "blockingReasons": []},
                },
                "colorAssignments": [
                    {
                        "index": index,
                        "bodyName": item.get("body_name") or f"MockBody{index + 1}",
                        "bodyEntityToken": item.get("body_entity_token") or f"mock-body-token-{index + 1}",
                        "appearanceName": item.get("appearance_name"),
                        "appearance": {"name": item.get("appearance_name"), "entityToken": f"mock-appearance-token-{index + 1}"},
                        "currentStyle": {"bodyName": item.get("body_name") or f"MockBody{index + 1}", "appearance": None},
                        "applyAppearanceArguments": {
                            "appearance_name": item.get("appearance_name"),
                            "body_entity_tokens": [item.get("body_entity_token")] if item.get("body_entity_token") else None,
                            "body_names": [item.get("body_name")] if item.get("body_name") else None,
                            "expected_body_count": 1,
                        },
                    }
                    for index, item in enumerate(assignments if isinstance(assignments, list) else [])
                    if isinstance(item, dict)
                ],
                "nextActions": [
                    "Call apply_appearance once for each color assignment.",
                    "Call export_asset with format='3mf'.",
                ],
            }
        }
    if name == "export_asset":
        return {
            "result": {
                **common,
                "exported": True,
                "format": arguments.get("format", "step"),
                "exportPath": arguments.get("export_path"),
                "targetResolution": {
                    "requestedBodyNames": arguments.get("body_names"),
                    "requestedBodyEntityTokens": arguments.get("body_entity_tokens"),
                    "requestedSelectionSetNames": arguments.get("selection_set_names"),
                } if arguments.get("format") == "3mf" else None,
                "archiveValidation": {
                    "isZip": True,
                    "has3DModelPart": True,
                    "objectCount": 1,
                    "buildItemCount": 1,
                    "warnings": [],
                } if arguments.get("format") == "3mf" else None,
                "allowedUnhealthyExport": bool(arguments.get("allow_unhealthy_export", False)),
                "overrideReason": arguments.get("override_reason") if arguments.get("allow_unhealthy_export", False) else None,
                "preflight": {"okToExport": True, "blockingReasons": []},
                "note": "Mock mode does not write export files.",
            }
        }
    if name == "create_2d_drawing":
        return {
            "result": {
                **common,
                "created": True,
                "drawingDocumentName": arguments.get("drawing_name", "Mock Drawing"),
                "standard": arguments.get("standard", "ASME"),
                "sheetSize": arguments.get("sheet_size", "A"),
                "exportPdfPath": arguments.get("export_pdf_path"),
                "preflight": {"okToProceed": True, "blockingReasons": []},
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not create or export drawings.",
            }
        }
    if name == "inspect_render_workspace":
        return {
            "result": {
                **common,
                "readOnly": True,
                "renderWorkspaceAvailable": False,
                "activeViewportAvailable": True,
                "activeCamera": {"name": "activeViewport", "viewOrientation": "iso"},
                "cameraCount": 1,
                "cameras": [{"name": "activeViewport", "viewOrientation": "iso"}],
                "namedViewCount": 1,
                "namedViews": [{"index": 0, "name": "Mock Iso"}],
                "appearanceCount": 2,
                "environmentCount": 1,
                "environments": [{"name": "Mock Studio"}],
                "renderProduct": None,
                "renderSettings": None,
                "warnings": ["Mock mode does not inspect real Fusion render products."],
            }
        }
    if name == "plan_render_output":
        approved = bool(arguments.get("requires_user_approval"))
        output_path = arguments.get("output_path")
        blockers = []
        if not (arguments.get("camera_name") or arguments.get("named_view")):
            blockers.append("camera_name or named_view is required.")
        if not output_path:
            blockers.append("output_path is required and must be absolute.")
        if not arguments.get("reason"):
            blockers.append("reason is required for render output planning.")
        if not approved:
            blockers.append("requires_user_approval must be true before any render/export action.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": not blockers,
                "riskLevel": "low" if not blockers else "high",
                "blockingReasons": blockers,
                "renderPlan": {
                    "cameraName": arguments.get("camera_name"),
                    "namedView": arguments.get("named_view"),
                    "outputPath": output_path,
                    "width": arguments.get("width", 1920),
                    "height": arguments.get("height", 1080),
                    "visualStyle": arguments.get("visual_style", "shaded"),
                    "environment": arguments.get("environment"),
                    "background": arguments.get("background"),
                    "reason": arguments.get("reason"),
                },
                "requiresUserApproval": approved,
                "warnings": ["Mock mode plans render output but does not write files or change render settings."],
            }
        }
    if name == "render_viewport_output":
        output_path = arguments.get("output_path") or "C:/Temp/mock-render.png"
        return {
            "result": {
                **common,
                "rendered": True,
                "method": "active_viewport_saveAsImageFile",
                "outputPath": output_path,
                "exists": True,
                "sizeBytes": 1024,
                "width": int(arguments.get("width") or 1920),
                "height": int(arguments.get("height") or 1080),
                "visualStyle": arguments.get("visual_style") or "shaded",
                "environment": arguments.get("environment"),
                "background": arguments.get("background"),
                "camera": {"namedView": arguments.get("named_view")} if arguments.get("named_view") else {"cameraName": arguments.get("camera_name") or "activeViewport"},
                "preflight": {
                    "readOnly": True,
                    "okToProceed": True,
                    "blockingReasons": [],
                    "renderPlan": {
                        "cameraName": arguments.get("camera_name"),
                        "namedView": arguments.get("named_view"),
                        "outputPath": output_path,
                        "width": int(arguments.get("width") or 1920),
                        "height": int(arguments.get("height") or 1080),
                        "visualStyle": arguments.get("visual_style") or "shaded",
                    },
                    "requiresUserApproval": bool(arguments.get("requires_user_approval")),
                },
                "stateComparison": {"hasChanges": False, "riskLevel": "low"},
                "note": "Mock mode does not render or write image files.",
            }
        }
    if name == "inspect_document_management_state":
        return {
            "result": {
                **common,
                "readOnly": True,
                "activeDocument": {
                    "name": "Mock Fusion Toolsmith Design",
                    "isActive": True,
                    "isModified": False,
                    "isSaved": True,
                    "dataFile": {
                        "name": "Mock Fusion Toolsmith Design",
                        "id": "mock-data-file-id",
                        "versionNumber": 3,
                        "parentProject": {"name": "Mock Project", "id": "mock-project-id"},
                        "parentFolder": {"name": "Mock Folder", "id": "mock-folder-id"},
                    },
                    "externalReferenceCount": 0,
                    "externalReferences": [],
                },
                "openDocumentCount": 1,
                "openDocuments": [],
                "cloudDataAvailable": True,
                "blockingReasons": [],
                "warnings": ["Mock mode does not inspect real Fusion cloud data."],
            }
        }
    if name == "plan_document_management_action":
        approved = bool(arguments.get("requires_user_approval"))
        dry_run = arguments.get("dry_run", True) is True
        action = arguments.get("action")
        blockers = []
        if not action:
            blockers.append("action must be supplied.")
        if not arguments.get("reason"):
            blockers.append("reason is required for document-management planning.")
        if not approved:
            blockers.append("requires_user_approval must be true before any close, save, upload, version, relink, or cloud document action.")
        if not dry_run:
            blockers.append("dry_run must remain true for planning; mutation tools must perform a separate explicit action.")
        return {
            "result": {
                **common,
                "readOnly": True,
                "okToProceed": not blockers,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "actionPlan": {
                    "action": action,
                    "documentName": arguments.get("document_name"),
                    "dataFileId": arguments.get("data_file_id"),
                    "targetPath": arguments.get("target_path"),
                    "targetFolderId": arguments.get("target_folder_id"),
                    "referenceName": arguments.get("reference_name"),
                    "versionId": arguments.get("version_id"),
                    "dryRun": dry_run,
                    "reason": arguments.get("reason"),
                },
                "requiresUserApproval": approved,
                "warnings": ["Mock mode plans document actions but does not save, version, open, or relink data."],
            }
        }
    if name == "create_design_document":
        document_name = arguments.get("document_name") or "Mock Unsaved Design"
        return {
            "result": {
                **common,
                "created": True,
                "action": "new_design",
                "documentName": document_name,
                "isModified": False,
                "preflight": {
                    "readOnly": True,
                    "okToProceed": True,
                    "blockingReasons": [],
                    "actionPlan": {
                        "action": "new_design",
                        "documentName": document_name,
                        "dryRun": True,
                        "reason": arguments.get("reason"),
                    },
                },
                "notes": ["Mock mode did not create a real Fusion document."],
            }
        }
    if name == "export_document_copy":
        target_path = arguments.get("target_path") or "C:/Temp/mock-copy.f3d"
        return {
            "result": {
                **common,
                "exported": True,
                "action": "export_copy",
                "method": "createFusionArchiveExportOptions",
                "targetPath": target_path,
                "exists": True,
                "sizeBytes": 2048,
                "documentName": arguments.get("document_name") or "Mock Fusion Toolsmith Design",
                "preflight": {
                    "readOnly": True,
                    "okToProceed": True,
                    "blockingReasons": [],
                    "actionPlan": {
                        "action": "export_copy",
                        "documentName": arguments.get("document_name"),
                        "targetPath": target_path,
                        "dryRun": True,
                        "reason": arguments.get("reason"),
                    },
                    "requiresUserApproval": bool(arguments.get("requires_user_approval")),
                },
                "stateComparison": {"hasChanges": False, "riskLevel": "low"},
                "note": "Mock mode does not write Fusion archive files.",
            }
        }
    if name == "close_active_document":
        return {
            "result": {
                **common,
                "closed": True,
                "action": "close",
                "documentName": arguments.get("document_name") or "Mock Fusion Toolsmith Design",
                "saveChanges": bool(arguments.get("save_changes")),
                "wasModifiedBeforeClose": False,
                "preflight": {
                    "readOnly": True,
                    "okToProceed": True,
                    "blockingReasons": [],
                    "actionPlan": {
                        "action": "close",
                        "documentName": arguments.get("document_name"),
                        "dryRun": True,
                        "reason": arguments.get("reason"),
                    },
                },
                "notes": ["Mock mode did not close a real Fusion document."],
            }
        }
    if name == "capture_view":
        return {
            "result": {
                **common,
                "path": "mock://capture/view.png",
                "format": arguments.get("format", "png"),
                "note": "No file is written in mock mode.",
            }
        }
    if name == "capture_demo_sequence":
        return {
            "result": {
                **common,
                "frameCount": len(arguments.get("steps") or []),
                "frames": [
                    {"index": index, "path": f"mock://capture/demo-frame-{index + 1}.png"}
                    for index, _step in enumerate(arguments.get("steps") or [])
                ],
                "note": "No files are written in mock mode.",
            }
        }
    if name in {"create_offset_plane", "create_construction_point", "create_construction_axis", "create_rigid_joint"}:
        return {
            "result": {
                **common,
                "created": True,
                "name": arguments.get("name", f"Mock {name.replace('_', ' ').title()}"),
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not create Fusion construction geometry or joints.",
            }
        }
    if name in {"add_sketch_constraint", "delete_sketch_constraint"}:
        return {
            "result": {
                **common,
                "sketchName": arguments.get("sketch_name", "Mock Sketch"),
                "constraintType": arguments.get("constraint_type"),
                "constraintIndex": arguments.get("constraint_index"),
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not edit sketch constraints.",
            }
        }
    if name == "create_insert_socket":
        prefix = arguments.get("work_sketch_name") or f"{arguments.get('source_sketch_name', 'MockSketch')}_InsertSocket"
        plate_name = arguments.get("plate_body_name") or f"{prefix}_Plate"
        cutter_name = arguments.get("cutter_body_name") or f"{prefix}_Cutter"
        return {
            "result": {
                **common,
                "created": True,
                "sourceSketchName": arguments.get("source_sketch_name", "MockSketch"),
                "workSketchName": arguments.get("work_sketch_name") or f"{prefix}_Sketch",
                "targetBodyName": arguments.get("target_body_name", "MockTarget"),
                "plateBodyName": plate_name,
                "cutterBodyName": cutter_name,
                "plateFeatureName": arguments.get("plate_feature_name") or f"{prefix}_PlateExtrude",
                "cutterFeatureName": arguments.get("cutter_feature_name") or f"{prefix}_CutterExtrude",
                "socketFeatureName": arguments.get("socket_feature_name") or f"{prefix}_SocketCut",
                "insertThickness": arguments.get("insert_thickness", "2 mm"),
                "socketDepth": arguments.get("socket_depth") or arguments.get("insert_thickness", "2 mm"),
                "clearance": arguments.get("clearance", "0 mm"),
                "mode": arguments.get("mode", "flush"),
                "keepCutterBody": bool(arguments.get("keep_cutter_body")),
                "alignmentVerification": {
                    "readOnly": True,
                    "okToExport": True,
                    "method": "axis_aligned_bounding_box",
                    "blockingReasons": [],
                    "checks": {
                        "plateSocketFootprintOverlap": True,
                        "socketDepthMatchesPlateThickness": True,
                        "logoBodiesOnOrIntersectPlate": True,
                    },
                },
                "diagnostics": {
                    "stage": "complete",
                    "createdArtifacts": [
                        {"kind": "sketch", "name": f"{prefix}_Sketch"},
                        {"kind": "body", "name": plate_name},
                        {"kind": "body", "name": cutter_name},
                    ],
                    "cutterCleanup": "combine_cut_consumed_tool_body" if not arguments.get("keep_cutter_body") else None,
                    "warnings": [],
                },
                "stateComparison": {"hasChanges": True, "riskLevel": "medium"},
                "note": "Mock mode does not create Fusion insert/socket geometry.",
            }
        }
    if name in {
        "create_box",
        "create_cylinder",
        "create_coil",
        "create_parametric_feature",
        "create_sketch",
        "create_sketch_offset",
        "copy_profile_loop",
        "offset_profile_loop",
        "extrude_existing_profile",
        "create_rounded_rectangle_body",
        "create_rounded_slot_cut",
        "create_rounded_pocket",
        "create_hole_pattern",
        "create_counterbore_hole_pattern",
        "revolve_feature",
        "loft_feature",
        "sweep_feature",
        "shell_body",
        "offset_face_or_press_pull",
        "mirror_features_or_bodies",
        "pattern_feature",
    }:
        result_name = arguments.get("name", f"Mock {name.replace('_', ' ').title()}")
        return {
            "result": {
                **common,
                "created": True,
                "name": result_name,
                "featureName": result_name,
                "bodyName": arguments.get("body_name") or arguments.get("target_body_name") or result_name,
                "targetBody": arguments.get("target_body_name") or arguments.get("body_name"),
                "createdBodies": [arguments.get("body_name") or arguments.get("name", "Mock Result")],
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not edit Fusion geometry.",
            }
        }
    if name in {"convert_mesh_to_solid", "reorganize_body_to_component"}:
        preflight = {
            "readOnly": True,
            "ready": True,
            "blockers": [],
            "warnings": ["Mock mode does not inspect real mesh quality."],
            "target": {
                "name": arguments.get("mesh_body_name") or arguments.get("body_name") or "Mock Mesh Body",
                "entityToken": arguments.get("mesh_body_entity_token") or "mock-mesh-token",
            },
            "normalizedRequest": {
                "conversionIntent": "convert_to_brep",
                "operation": arguments.get("operation") or "new_body",
                "acknowledgeQualityLoss": bool(arguments.get("acknowledge_quality_loss", True)),
                "reason": arguments.get("reason") or "Mock conversion fixture.",
            },
        } if name == "convert_mesh_to_solid" else None
        return {
            "result": {
                **common,
                "converted": name == "convert_mesh_to_solid",
                "reorganized": name == "reorganize_body_to_component",
                "bodyName": arguments.get("body_name") or arguments.get("mesh_body_name") or "Mock Body",
                "meshBodyName": arguments.get("mesh_body_name") or "Mock Mesh Body",
                "meshBodyEntityToken": arguments.get("mesh_body_entity_token") or "mock-mesh-token",
                "componentName": arguments.get("target_component_name") or arguments.get("new_component_name") or "Mock Component",
                "preflight": preflight,
                "stateComparison": {"hasChanges": True, "riskLevel": "medium"},
                "note": "Mock mode does not convert meshes or reorganize Fusion components.",
            }
        }
    if name in {"repair_mesh_body", "reduce_mesh_body", "remesh_body"}:
        flag = {
            "repair_mesh_body": "repaired",
            "reduce_mesh_body": "reduced",
            "remesh_body": "remeshed",
        }[name]
        intent = {
            "repair_mesh_body": "repair_mesh",
            "reduce_mesh_body": "reduce_mesh",
            "remesh_body": "remesh",
        }[name]
        return {
            "result": {
                **common,
                flag: True,
                "operation": intent,
                "meshBodyName": arguments.get("mesh_body_name") or "Mock Mesh Body",
                "meshBodyEntityToken": arguments.get("mesh_body_entity_token") or "mock-mesh-token",
                "featureName": f"Mock {name.replace('_', ' ').title()}",
                "parameters": {
                    "tolerance": arguments.get("tolerance"),
                    "detailLevel": arguments.get("detail_level"),
                    "repairType": arguments.get("repair_type"),
                    "reductionTarget": arguments.get("reduction_target"),
                    "remeshType": arguments.get("remesh_type"),
                },
                "preflight": {
                    "readOnly": True,
                    "ready": True,
                    "blockers": [],
                    "normalizedRequest": {
                        "conversionIntent": intent,
                        "acknowledgeQualityLoss": bool(arguments.get("acknowledge_quality_loss", True)),
                        "reason": arguments.get("reason") or "Mock mesh mutation fixture.",
                    },
                },
                "stateComparison": {"hasChanges": True, "riskLevel": "medium"},
                "note": "Mock mode does not repair, reduce, or remesh Fusion mesh bodies.",
            }
        }
    if name in {"set_visibility", "apply_appearance"}:
        return {
            "result": {
                **common,
                "applied": True,
                "bodyName": arguments.get("body_name"),
                "bodyNames": arguments.get("body_names"),
                "bodyEntityTokens": arguments.get("body_entity_tokens"),
                "visible": arguments.get("visible"),
                "appearance": {"name": arguments.get("appearance_name"), "entityToken": "mock-appearance-token"} if name == "apply_appearance" else None,
                "targetBodies": [
                    {
                        "bodyName": arguments.get("body_name") or "MockBody",
                        "entityToken": (arguments.get("body_entity_tokens") or ["mock-body-token"])[0] if isinstance(arguments.get("body_entity_tokens"), list) else arguments.get("body_entity_tokens") or "mock-body-token",
                        "appearance": {"name": arguments.get("appearance_name"), "entityToken": "mock-appearance-token"} if name == "apply_appearance" else None,
                    }
                ],
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not change Fusion visual state.",
            }
        }
    if name in {"set_active_document", "set_camera", "set_timeline_marker", "suppress_timeline_feature", "delete_timeline_feature"}:
        return {
            "result": {
                **common,
                "applied": True,
                "documentName": arguments.get("document_name") or arguments.get("name"),
                "camera": arguments.get("camera") or arguments.get("view_name"),
                "featureName": arguments.get("feature_name") or arguments.get("name"),
                "timelineIndex": arguments.get("index"),
                "suppressed": arguments.get("suppress") if name == "suppress_timeline_feature" else None,
                "reason": arguments.get("reason"),
                "stateComparison": {"hasChanges": name != "set_camera", "riskLevel": "medium"},
                "note": "Mock mode does not change Fusion documents, camera, or timeline state.",
            }
        }
    if name in {"modify_parameters", "set_parameter", "export_parameters_csv", "import_parameters_csv"}:
        return {
            "result": {
                **common,
                "parameterCount": len(arguments.get("parameters") or []) if isinstance(arguments.get("parameters"), list) else 1,
                "parameterName": arguments.get("name") or arguments.get("parameter_name"),
                "path": arguments.get("path") or arguments.get("csv_path"),
                "stateComparison": {"hasChanges": name in {"modify_parameters", "set_parameter", "import_parameters_csv"}, "riskLevel": "low"},
                "note": "Mock mode does not read or write Fusion parameters or CSV files.",
            }
        }
    if name in {"edit_sketch_dimension", "delete_sketch_dimension"}:
        return {
            "result": {
                **common,
                "sketchName": arguments.get("sketch_name", "Mock Sketch"),
                "parameterName": arguments.get("parameter_name", "mockSketchDimension"),
                "before": {"expression": "10 mm"},
                "after": None if name == "delete_sketch_dimension" else {"expression": arguments.get("expression")},
                "deleted": name == "delete_sketch_dimension",
                "reason": arguments.get("reason"),
                "stateComparison": {"hasChanges": True, "riskLevel": "low"},
                "note": "Mock mode does not edit Fusion sketch dimensions.",
            }
        }
    return {"result": {**common, "note": "No Fusion execution occurred."}}


def _mock_resource(uri, surface):
    if uri == "fusion://design/summary":
        return {"result": MOCK_DESIGN_SUMMARY}
    if uri == "fusion://design/parameters":
        return {
            "userParameters": {
                "mock_width": {"expression": "100 mm", "value": 10.0, "unit": "cm"},
                "mock_height": {"expression": "50 mm", "value": 5.0, "unit": "cm"},
            }
        }
    if uri.startswith("fusion://design/tree"):
        return {
            "name": "Root",
            "mock": True,
            "children": [{"name": "Demo Body", "type": "body"}, {"name": "Reference Body", "type": "body"}],
        }
    if uri == "fusion://runtime/change-journal":
        return {"result": {"path": "mock://change-journal.jsonl", "entries": []}}
    if uri == "fusion://agent/tool-profiles":
        return surface["profiles"]
    if uri == "fusion://agent/server-capabilities":
        return surface["serverCapabilities"]
    try:
        import tools

        return tools.read_resource(uri)
    except Exception as exc:
        return {"error": f"Mock resource '{uri}' is unavailable: {exc}"}


class MockMcpState:
    def __init__(self):
        self.surface = load_offline_mcp_surface()
        self.sessions = set()

    def new_session(self):
        session_id = f"mock-{uuid.uuid4()}"
        self.sessions.add(session_id)
        return session_id


class MockMcpHandler(BaseHTTPRequestHandler):
    server_version = "FusionMCPMock/1.0"

    def log_message(self, fmt, *args):
        print(f"[mock-server] {self.address_string()} - {fmt % args}", file=sys.stderr)

    @property
    def state(self):
        return self.server.state

    def _send_json(self, status, payload, extra_headers=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(
            200,
            {
                "status": "ok",
                "server": "fusion-mcp-mock",
                "version": "1.1.0",
                "transport": "streamable_http",
                "transports": ["streamable_http"],
                "mock": True,
                "active_http_sessions": len(self.state.sessions),
                "task_manager_running": True,
                "pending_tasks": 0,
            },
        )

    def do_DELETE(self):
        if self.path != "/sse":
            self._send_json(404, {"error": "not found"})
            return
        session_id = self.headers.get("Mcp-Session-Id")
        if session_id:
            self.state.sessions.discard(session_id)
        self._send_json(200, {"ok": True, "mock": True})

    def do_POST(self):
        if self.path != "/sse":
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return

        method = request.get("method")
        response_headers = {}
        if method == "initialize":
            session_id = self.state.new_session()
            response_headers["Mcp-Session-Id"] = session_id
        else:
            session_id = self.headers.get("Mcp-Session-Id")
            if session_id not in self.state.sessions:
                self._send_json(404, {"error": "unknown MCP session"})
                return

        self._send_json(200, self._jsonrpc_response(request), response_headers)

    def _jsonrpc_response(self, request):
        method = request.get("method")
        params = request.get("params") or {}
        request_id = request.get("id")
        surface = self.state.surface
        if method == "initialize":
            result = surface["server"]
        elif method == "tools/list":
            result = {"tools": surface["tools"]}
        elif method == "resources/list":
            result = {"resources": surface["resources"]}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": surface["resourceTemplates"]}
        elif method == "prompts/list":
            result = {"prompts": surface["prompts"]}
        elif method == "prompts/get":
            prompt_name = params.get("name")
            prompt = next((item for item in surface["prompts"] if item.get("name") == prompt_name), None)
            if not prompt:
                return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": f"Prompt not found: {prompt_name}"}}
            result = {"description": prompt.get("description", ""), "messages": prompt.get("messages", [])}
        elif method == "resources/read":
            uri = params.get("uri")
            resource = _mock_resource(uri, surface)
            result = {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(resource, indent=2)}]}
        elif method == "tools/call":
            result = _mcp_result(_mock_tool_result(params.get("name"), params.get("arguments") or {}))
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


class MockMcpHttpServer(ThreadingHTTPServer):
    def __init__(self, server_address):
        super().__init__(server_address, MockMcpHandler)
        self.state = MockMcpState()


def create_mock_http_server(host="127.0.0.1", port=9101):
    return MockMcpHttpServer((host, port))


def serve_mock_server(host="127.0.0.1", port=9101):
    server = create_mock_http_server(host, port)
    actual_host, actual_port = server.server_address[:2]
    print(f"FusionMCP mock server listening on http://{actual_host}:{actual_port}/sse")
    print(f"Health: http://{actual_host}:{actual_port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping FusionMCP mock server.")
    finally:
        server.server_close()
