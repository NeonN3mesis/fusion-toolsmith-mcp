"""
Utility tools for script execution, viewport capture, export, camera controls, and undoing.
"""

import adsk.core, adsk.fusion
import json
import uuid
import os
import sys
import io
import hashlib
import traceback
import zipfile
import xml.etree.ElementTree as ET
from . import register_resource, register_tool
from .inspection import _collection_items, _describe_selected_entity, _design_state_snapshot, _health_to_string, _safe_value, _selection_set_snapshots, compare_design_state, get_active_design, get_feature_dependencies, plan_document_management_action, plan_drawing_views, plan_render_output, preflight_flat_pattern

class FusionScriptExecutionError(Exception):
    def __init__(self, message, stdout_text, traceback_text):
        super().__init__(message)
        self.stdout_text = stdout_text
        self.traceback_text = traceback_text


_SCRIPT_EXPORT_MARKERS = (
    "exportmanager",
    "createstepexportoptions",
    "createstlexportoptions",
    "createigesexportoptions",
    "createsmtfileexportoptions",
    "createfusionarchiveexportoptions",
    "createusdexportoptions",
    "createpdfexportoptions",
    "drawingmanager",
    "createdrawing",
    "drawingdocument",
    "exportmgr.execute",
    "exportmanager.execute",
)

_DEFAULT_RUNTIME_REQUIRED_TOOLS = (
    "doctor",
    "run_fusion_script",
    "inspect_design",
    "extract_reference_dimensions",
    "inspect_printability",
    "inspect_analysis_capabilities",
    "interference_check",
    "clearance_check",
    "exact_interference_check",
    "exact_clearance_check",
    "inspect_sheet_metal_rules",
    "preflight_flat_pattern",
    "plan_sheet_metal_workflow",
    "inspect_surface_bodies",
    "plan_surface_repair",
    "inspect_drawing_documents",
    "preflight_drawing_creation",
    "plan_drawing_views",
    "inspect_manufacturing_workspace",
    "list_manufacturing_setups",
    "inspect_operation",
    "plan_manufacturing_operation",
    "create_manufacturing_setup",
    "create_manufacturing_operation",
    "generate_toolpaths",
    "post_process",
    "inspect_sketch",
    "inspect_feature",
    "inspect_selection_sets",
    "get_body_faces",
    "get_assembly_references",
    "get_assembly_joints",
    "plan_joint_limits",
    "list_appearances",
    "inspect_body_style",
    "offset_face_or_press_pull",
    "revolve_feature",
    "loft_feature",
    "sweep_feature",
    "get_sketch_parameters",
    "get_feature_parameters",
    "edit_extrude_feature",
    "edit_fillet_radius",
    "edit_chamfer_distance",
    "edit_shell_thickness",
    "edit_pattern_parameter",
    "edit_hole_parameter",
    "get_parameter_usage",
    "get_projected_geometry_sources",
    "get_feature_dependencies",
    "get_dependency_graph",
    "assess_change_impact",
    "plan_parameterization",
    "recommend_mcp_workflow",
    "get_change_journal",
    "clear_change_journal",
    "search_local_fusion_docs",
    "preflight_export",
    "inspect_3mf_archive",
    "plan_multibody_3mf_export",
    "plan_multicolor_3mf_export",
    "export_asset",
    "export_document_copy",
    "export_flat_pattern",
    "create_2d_drawing",
    "add_drawing_view",
    "add_drawing_dimension",
    "add_drawing_callout",
    "add_parts_list",
    "add_revision_table",
    "capture_view",
    "render_viewport_output",
    "capture_demo_sequence",
    "create_offset_plane",
    "create_construction_point",
    "create_construction_axis",
    "create_rigid_joint",
    "create_section_analysis",
    "create_revolute_joint",
    "create_slider_joint",
    "create_cylindrical_joint",
    "create_pin_slot_joint",
    "create_planar_joint",
    "create_ball_joint",
    "set_joint_limits",
    "create_flange",
    "create_bend",
    "unfold_sheet_metal",
    "refold_sheet_metal",
    "patch_surface",
    "stitch_surfaces",
    "thicken_surface",
    "trim_surface",
    "extend_surface",
    "create_ruled_surface",
    "add_sketch_constraint",
    "delete_sketch_constraint",
    "create_rounded_rectangle_body",
    "create_rounded_slot_cut",
    "create_rounded_pocket",
    "create_hole_pattern",
    "create_counterbore_hole_pattern",
    "mirror_features_or_bodies",
    "pattern_feature",
    "set_visibility",
)

_SOURCE_FINGERPRINT_FILES = (
    "FusionMCP.py",
    "FusionMCP.manifest",
    "tool_profiles.json",
    os.path.join("server", "mcp_server.py"),
    os.path.join("tools", "__init__.py"),
    os.path.join("tools", "features.py"),
    os.path.join("tools", "inspection.py"),
    os.path.join("tools", "utilities.py"),
    os.path.join("tools", "parametric.py"),
)

_TOOL_FIRST_POLICY = {
    "mandatoryFirstStep": "doctor",
    "resource": "fusion://agent/tool-first-workflow",
    "principles": [
        "Use structured FusionMCP tools before raw scripts.",
        "Inspect live model state before editing existing geometry.",
        "Run preflight checks before model changes and exports.",
        "Use run_fusion_script only when no structured tool can safely do the job.",
    ],
    "workflows": {
        "inspect_or_review": {
            "firstTools": ["doctor", "inspect_design", "get_assembly_tree"],
            "preferredTools": [
                "get_assembly_references",
                "get_assembly_joints",
                "extract_reference_dimensions",
                "inspect_analysis_capabilities",
                "inspect_sketch",
                "inspect_feature",
                "get_feature_dependencies",
                "get_dependency_graph",
                "capture_view",
                "validate_model",
            ],
        },
        "parameterize_existing_model": {
            "firstTools": ["doctor", "inspect_design", "plan_parameterization"],
            "preferredTools": [
                "inspect_sketch",
                "inspect_feature",
                "get_sketch_parameters",
                "get_feature_parameters",
                "get_parameter_usage",
                "assess_change_impact",
                "modify_parameters",
                "edit_extrude_feature",
                "edit_fillet_radius",
                "edit_chamfer_distance",
                "edit_shell_thickness",
                "edit_pattern_parameter",
                "edit_hole_parameter",
                "edit_sketch_dimension",
                "set_parameter",
                "validate_model",
            ],
        },
        "modify_geometry": {
            "firstTools": ["doctor", "inspect_design", "preflight_model_change"],
            "preferredTools": [
                "query_selection",
                "get_current_selection",
                "extract_reference_dimensions",
                "inspect_printability",
                "inspect_analysis_capabilities",
                "inspect_sheet_metal_rules",
                "preflight_flat_pattern",
                "plan_sheet_metal_workflow",
                "inspect_surface_bodies",
                "plan_surface_repair",
                "inspect_drawing_documents",
                "preflight_drawing_creation",
                "plan_drawing_views",
                "inspect_manufacturing_workspace",
                "list_manufacturing_setups",
                "inspect_operation",
                "plan_manufacturing_operation",
                "inspect_sketch",
                "inspect_feature",
                "get_assembly_references",
                "plan_joint_limits",
                "list_appearances",
                "inspect_body_style",
                "get_body_faces",
                "assess_change_impact",
                "map_coordinates",
                "create_sketch",
                "draw_line",
                "draw_rectangle",
                "draw_circle",
                "add_sketch_constraint",
                "delete_sketch_constraint",
                "project_geometry",
                "create_offset_plane",
                "create_construction_point",
                "create_construction_axis",
                "create_rigid_joint",
                "create_section_analysis",
                "create_revolute_joint",
                "create_slider_joint",
                "create_cylindrical_joint",
                "create_pin_slot_joint",
                "create_planar_joint",
                "create_ball_joint",
                "extrude_feature",
                "revolve_feature",
                "loft_feature",
                "sweep_feature",
                "fillet_feature",
                "chamfer_feature",
                "shell_body",
                "offset_face_or_press_pull",
                "edit_extrude_feature",
                "edit_fillet_radius",
                "edit_chamfer_distance",
                "edit_shell_thickness",
                "edit_pattern_parameter",
                "edit_hole_parameter",
                "combine_bodies",
                "create_rounded_rectangle_body",
                "create_rounded_slot_cut",
                "create_rounded_pocket",
                "create_hole_pattern",
                "create_counterbore_hole_pattern",
                "mirror_features_or_bodies",
                "pattern_feature",
                "list_appearances",
                "inspect_body_style",
                "apply_appearance",
                "set_visibility",
                "validate_model",
            ],
        },
        "export": {
            "firstTools": ["doctor", "inspect_design", "preflight_export"],
            "preferredTools": ["inspect_selection_sets", "plan_multibody_3mf_export", "plan_multicolor_3mf_export", "inspect_3mf_archive", "preflight_flat_pattern", "preflight_drawing_creation", "plan_drawing_views", "export_asset", "export_flat_pattern", "create_2d_drawing", "capture_view", "capture_demo_sequence"],
        },
        "mcp_runtime_troubleshooting": {
            "firstTools": ["doctor", "get_runtime_diagnostics"],
            "preferredTools": ["inspect_design"],
        },
    },
    "rawScriptPolicy": {
        "tool": "run_fusion_script",
        "status": "last_resort",
        "requiredArguments": ["script_intent", "mcp_tool_gap"],
        "exportPolicy": "Raw Fusion export APIs are blocked by default; use export_asset, export_flat_pattern, or create_2d_drawing.",
    },
}


def _normalize_names(names):
    if names is None:
        return []
    if isinstance(names, str):
        return [names]
    return [str(name) for name in names]


def _all_components(root):
    components = [root]
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        if component and component not in components:
            components.append(component)
    return components


def _entity_ref(entity):
    if not entity:
        return None
    return {
        "name": _safe_value(lambda: entity.name),
        "objectType": _safe_value(lambda: entity.objectType),
        "entityToken": _safe_value(lambda: entity.entityToken),
    }


def _find_body_by_name(root, body_name):
    for component in _all_components(root):
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            if _safe_value(lambda body=body: body.name) == body_name:
                return component, body
    return None, None


def _body_style_summary(body, component=None):
    component = component or _safe_value(lambda: body.parentComponent)
    return {
        "bodyName": _safe_value(lambda: body.name),
        "componentName": _safe_value(lambda: component.name),
        "entityToken": _safe_value(lambda: body.entityToken),
        "isVisible": _safe_value(lambda: body.isVisible),
        "appearance": _entity_ref(_safe_value(lambda: body.appearance)),
        "material": _entity_ref(_safe_value(lambda: body.material)),
        "physicalMaterial": _entity_ref(_safe_value(lambda: body.physicalMaterial)),
    }


def _find_appearance(app, design, appearance_name, copy_from_library=True):
    requested = str(appearance_name).strip() if appearance_name is not None else ""
    if not requested:
        return None, "appearance_name is required."
    local_appearances = _safe_value(lambda: design.appearances)
    item_by_name = _safe_value(lambda: local_appearances.itemByName)
    if callable(item_by_name):
        appearance = item_by_name(requested)
        if appearance:
            return appearance, None
    for appearance in _collection_items(local_appearances):
        name = _safe_value(lambda appearance=appearance: appearance.name)
        if name and requested.lower() in name.lower():
            return appearance, None
    for library in _collection_items(_safe_value(lambda: app.materialLibraries)):
        appearances = _safe_value(lambda library=library: library.appearances)
        item_by_name = _safe_value(lambda appearances=appearances: appearances.itemByName)
        library_appearance = item_by_name(requested) if callable(item_by_name) else None
        if not library_appearance:
            for candidate in _collection_items(appearances):
                name = _safe_value(lambda candidate=candidate: candidate.name)
                if name and requested.lower() in name.lower():
                    library_appearance = candidate
                    break
        if library_appearance:
            add_by_copy = _safe_value(lambda: local_appearances.addByCopy)
            if copy_from_library and callable(add_by_copy):
                try:
                    return add_by_copy(library_appearance), None
                except Exception:
                    return library_appearance, None
            return library_appearance, None
    return None, f"Appearance '{requested}' not found locally or in libraries."


def _set_named_visibility(collection, requested_names, visible):
    requested = set(_normalize_names(requested_names))
    changed = []
    missing = set(requested)
    if not requested:
        return changed, []
    for entity in _collection_items(collection):
        name = _safe_value(lambda entity=entity: entity.name)
        if name not in requested:
            continue
        try:
            entity.isLightBulbOn = bool(visible)
        except Exception:
            try:
                entity.isVisible = bool(visible)
            except Exception:
                pass
        changed.append(name)
        missing.discard(name)
    return changed, sorted(missing)


@register_tool("set_visibility")
def set_visibility(body_names=None, sketch_names=None, construction_plane_names=None, visible=True, hide_all_sketches=False, hide_all_construction_planes=False, clear_selection=True):
    design = get_active_design()
    root = design.rootComponent
    before = _design_state_snapshot(include_selections=True)
    changed = {"bodies": [], "sketches": [], "constructionPlanes": []}
    missing = {"bodies": [], "sketches": [], "constructionPlanes": []}

    for component in _all_components(root):
        body_changed, body_missing = _set_named_visibility(
            _safe_value(lambda component=component: component.bRepBodies),
            body_names,
            visible,
        )
        sketch_changed, sketch_missing = _set_named_visibility(
            _safe_value(lambda component=component: component.sketches),
            sketch_names,
            visible,
        )
        plane_changed, plane_missing = _set_named_visibility(
            _safe_value(lambda component=component: component.constructionPlanes),
            construction_plane_names,
            visible,
        )
        changed["bodies"].extend(body_changed)
        changed["sketches"].extend(sketch_changed)
        changed["constructionPlanes"].extend(plane_changed)
        missing["bodies"].extend(body_missing)
        missing["sketches"].extend(sketch_missing)
        missing["constructionPlanes"].extend(plane_missing)

        if hide_all_sketches:
            for sketch in _collection_items(_safe_value(lambda component=component: component.sketches)):
                sketch.isLightBulbOn = False
                changed["sketches"].append(_safe_value(lambda sketch=sketch: sketch.name))
        if hide_all_construction_planes:
            for plane in _collection_items(_safe_value(lambda component=component: component.constructionPlanes)):
                plane.isLightBulbOn = False
                changed["constructionPlanes"].append(_safe_value(lambda plane=plane: plane.name))

    if clear_selection:
        ui = _safe_value(lambda: adsk.core.Application.get().userInterface)
        selections = _safe_value(lambda: ui.activeSelections) if ui else None
        if selections:
            _safe_value(lambda: selections.clear())

    for key in missing:
        missing[key] = sorted(set(missing[key]) - set(changed[key]))
        changed[key] = sorted({name for name in changed[key] if name})

    return {
        "result": {
            "visible": bool(visible),
            "changed": changed,
            "missing": missing,
            "clearSelection": bool(clear_selection),
            "stateComparison": compare_design_state(before, _design_state_snapshot(include_selections=True)).get("result"),
        }
    }


def _tool_first_policy():
    return json.loads(json.dumps(_TOOL_FIRST_POLICY))


def _mcp_server_module():
    try:
        from ..server import mcp_server
    except Exception:
        import server.mcp_server as mcp_server
    return mcp_server


def _workspace_file_path(name):
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), name)


def _load_help_context():
    path = _workspace_file_path("help_context.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_best_practices_text():
    path = _workspace_file_path("best_practices.md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _fusion_docs_url(class_name):
    clean_name = "".join(c for c in str(class_name or "") if c.isalnum()).lower()
    return f"https://help.autodesk.com/view/fusion360/ENU/?contextId=adsk_fusion_api_{clean_name}" if clean_name else None


def _common_api_topics():
    return {
        "extrudefeature": "Creates, modifies, or deletes an extrusion feature. Inherits from Feature.",
        "sketch": "Represents a sketch in a component. Contains sketch curves, points, dimensions, and constraints.",
        "brepbody": "Represents a solid or sheet body in a component.",
        "brepface": "Represents a face of a BRepBody.",
        "brepedge": "Represents an edge of a BRepBody.",
        "occurrence": "Represents a component instance in an assembly.",
        "constructionplane": "Represents a construction plane used as a sketch or feature reference.",
        "userparameter": "Represents a user-defined parameter with expressions and unit conversions.",
    }


def _docs_search_index():
    entries = []
    try:
        help_context = _load_help_context()
        for key, text in help_context.items():
            entries.append({
                "id": f"help:{key}",
                "title": key,
                "source": "help_context.json",
                "text": str(text),
            })
    except Exception as e:
        entries.append({"id": "error:help_context", "title": "help_context error", "source": "help_context.json", "text": str(e)})

    try:
        best_practices = _load_best_practices_text()
        section_title = "Best Practices"
        section_lines = []
        section_index = 0
        for line in best_practices.splitlines():
            if line.startswith("#"):
                if section_lines:
                    entries.append({
                        "id": f"best_practices:{section_index}",
                        "title": section_title,
                        "source": "best_practices.md",
                        "text": "\n".join(section_lines).strip(),
                    })
                    section_index += 1
                    section_lines = []
                section_title = line.lstrip("#").strip() or "Best Practices"
            else:
                section_lines.append(line)
        if section_lines:
            entries.append({
                "id": f"best_practices:{section_index}",
                "title": section_title,
                "source": "best_practices.md",
                "text": "\n".join(section_lines).strip(),
            })
    except Exception as e:
        entries.append({"id": "error:best_practices", "title": "best_practices error", "source": "best_practices.md", "text": str(e)})

    for key, summary in _common_api_topics().items():
        entries.append({
            "id": f"api:{key}",
            "title": key,
            "source": "offline_api_index",
            "text": summary,
            "url": _fusion_docs_url(key),
        })
    return entries


def _search_docs(query=None, limit=10):
    entries = _docs_search_index()
    if not query:
        return entries[:limit]
    terms = [term for term in str(query).lower().split() if term]
    scored = []
    for entry in entries:
        haystack = f"{entry.get('title', '')} {entry.get('text', '')}".lower()
        score = sum(haystack.count(term) for term in terms)
        if score:
            scored.append((score, entry))
    scored.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    return [entry for _score, entry in scored[:limit]]


def _classify_workflow(task, intent=None):
    text = f"{task or ''} {intent or ''}".lower()
    if any(word in text for word in ("export", "step", "stl", "pdf", "drawing", "print file")):
        return "export"
    if any(word in text for word in ("parameter", "parametric", "parameterize", "dimension", "expression")):
        return "parameterize_existing_model"
    if any(word in text for word in ("mcp", "server", "connection", "doctor", "runtime", "stale", "token", "taskmanager")):
        return "mcp_runtime_troubleshooting"
    if any(word in text for word in ("edit", "modify", "cut", "join", "extrude", "fillet", "chamfer", "sketch", "delete", "suppress", "rebuild", "move")):
        return "modify_geometry"
    return "inspect_or_review"


@register_resource("fusion://agent/tool-first-workflow")
def read_tool_first_workflow():
    return _tool_first_policy()


@register_resource("fusion://runtime/change-journal")
def read_change_journal_resource():
    mcp_server = _mcp_server_module()
    return {
        "result": {
            "path": mcp_server.journal_file_path(),
            "entries": mcp_server.read_change_journal(),
        }
    }


@register_resource("fusion://docs/fusion-api")
def read_fusion_api_docs_index():
    return {
        "result": {
            "sources": ["help_context.json", "best_practices.md", "offline_api_index"],
            "entries": _docs_search_index(),
        }
    }


def _server_runtime_status():
    try:
        try:
            from ..server import mcp_server
            from ..server.task_manager import TaskManager
        except Exception:
            import server.mcp_server as mcp_server
            from server.task_manager import TaskManager
        return {
            "available": True,
            "authToken": _safe_value(lambda: mcp_server.auth_token),
            "defaultPort": _safe_value(lambda: mcp_server.DEFAULT_PORT),
            "serverRunning": _safe_value(lambda: mcp_server.server_instance is not None, False),
            "taskManagerRunning": _safe_value(lambda: TaskManager.is_running(), False),
            "pendingTasks": _safe_value(lambda: TaskManager.get_pending_task_count()),
            "taskManager": _safe_value(lambda: TaskManager.get_pending_task_stats(), {}),
        }
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
        }


def _read_discovery_payload():
    discovery_path = os.path.join(os.path.expanduser("~"), ".fusion_mcp.json")
    discovery = {"path": discovery_path, "exists": os.path.exists(discovery_path)}
    if discovery["exists"]:
        try:
            with open(discovery_path, "r", encoding="utf-8") as handle:
                discovery["payload"] = json.load(handle)
        except Exception as e:
            discovery["error"] = str(e)
    return discovery


def _source_fingerprint(root_dir):
    digest = hashlib.sha256()
    files = []
    for rel_path in _SOURCE_FINGERPRINT_FILES:
        abs_path = os.path.join(root_dir, rel_path)
        item = {
            "path": rel_path.replace("\\", "/"),
            "exists": os.path.exists(abs_path),
        }
        digest.update(rel_path.replace("\\", "/").encode("utf-8"))
        if item["exists"]:
            try:
                with open(abs_path, "rb") as handle:
                    data = handle.read()
                digest.update(data)
                item["sizeBytes"] = len(data)
                item["sha256"] = hashlib.sha256(data).hexdigest()
            except Exception as exc:
                item["error"] = str(exc)
                digest.update(str(exc).encode("utf-8"))
        else:
            digest.update(b"<missing>")
        files.append(item)
    return {
        "algorithm": "sha256",
        "fingerprint": digest.hexdigest(),
        "fileCount": len(files),
        "files": files,
    }


def _script_looks_like_export(script):
    normalized = script.lower()
    return any(marker in normalized for marker in _SCRIPT_EXPORT_MARKERS)


def _redact_discovery_payload(payload):
    if not isinstance(payload, dict):
        return None
    redacted = {}
    for key, value in payload.items():
        if key == "token":
            redacted[key] = "<redacted>"
        elif key == "authorization_header":
            redacted[key] = "<redacted>"
        elif key == "sse_url" and isinstance(value, str):
            redacted[key] = value.split("?token=", 1)[0] + "?token=<redacted>" if "?token=" in value else value
        else:
            redacted[key] = value
    return redacted


@register_tool("get_runtime_diagnostics")
def get_runtime_diagnostics(required_tools=None):
    if required_tools is None:
        required_tools = list(_DEFAULT_RUNTIME_REQUIRED_TOOLS)
    elif isinstance(required_tools, str):
        required_tools = [required_tools]
    elif not isinstance(required_tools, list):
        return {"error": "required_tools must be a string, list of strings, or omitted."}
    required_tools = [tool for tool in required_tools if isinstance(tool, str) and tool.strip()]

    from . import get_tool_schemas, tools_registry

    schema_names = sorted({schema.get("name") for schema in get_tool_schemas() if schema.get("name")})
    registry_names = sorted(tools_registry.keys())
    schema_set = set(schema_names)
    registry_set = set(registry_names)
    required_missing_from_schema = [tool for tool in required_tools if tool not in schema_set]
    required_missing_from_registry = [tool for tool in required_tools if tool not in registry_set]
    schema_not_registered = sorted(schema_set - registry_set)
    registered_not_in_schema = sorted(registry_set - schema_set)

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    manifest_path = os.path.join(root_dir, "FusionMCP.manifest")
    manifest = None
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except Exception as e:
            manifest = {"error": str(e)}

    discovery = _read_discovery_payload()
    if "payload" in discovery:
        discovery["payload"] = _redact_discovery_payload(discovery.get("payload"))

    module_names = [
        __package__,
        __name__,
        f"{__package__}.inspection" if __package__ else None,
        f"{__package__}.features" if __package__ else None,
        f"{__package__}.parametric" if __package__ else None,
        f"{__package__}.sketching" if __package__ else None,
    ]
    modules = []
    for module_name in module_names:
        module = sys.modules.get(module_name) if module_name else None
        if module:
            modules.append({
                "name": module_name,
                "file": _safe_value(lambda module=module: module.__file__),
            })

    restart_reasons = []
    if required_missing_from_schema or required_missing_from_registry:
        restart_reasons.append("One or more required tools are missing from the live schema or registry.")
    if schema_not_registered:
        restart_reasons.append("Some schema-advertised tools are not registered for execution.")
    if registered_not_in_schema:
        restart_reasons.append("Some registered tools are not advertised in the schema.")

    app = adsk.core.Application.get()
    active_doc = _safe_value(lambda: app.activeDocument)
    return {
        "result": {
            "toolCounts": {
                "schema": len(schema_names),
                "registry": len(registry_names),
            },
            "requiredTools": {
                "requested": required_tools,
                "missingFromSchema": required_missing_from_schema,
                "missingFromRegistry": required_missing_from_registry,
            },
            "registrySchemaMismatch": {
                "schemaNotRegistered": schema_not_registered,
                "registeredNotInSchema": registered_not_in_schema,
            },
            "runtime": {
                "rootDir": root_dir,
                "utilitiesFile": __file__,
                "sourceFingerprint": _source_fingerprint(root_dir),
                "modules": modules,
                "manifest": {
                    "path": manifest_path,
                    "exists": os.path.exists(manifest_path),
                    "runOnStartup": manifest.get("runOnStartup") if isinstance(manifest, dict) else None,
                    "name": manifest.get("name") if isinstance(manifest, dict) else None,
                    "type": manifest.get("type") if isinstance(manifest, dict) else None,
                    "error": manifest.get("error") if isinstance(manifest, dict) else None,
                },
                "discovery": discovery,
                "activeDocument": {
                    "name": _safe_value(lambda: active_doc.name),
                    "isModified": _safe_value(lambda: active_doc.isModified),
                } if active_doc else None,
            },
            "restartRecommended": bool(restart_reasons),
            "restartReasons": restart_reasons,
        }
}


@register_tool("doctor")
def doctor(required_tools=None, require_active_design=True):
    """
    Return a single read-only readiness report for FusionMCP.

    This is intentionally broader than get_runtime_diagnostics: it turns raw
    runtime facts into a verdict, blocking reasons, and concrete next actions.
    """
    if required_tools is None:
        required_tools = list(_DEFAULT_RUNTIME_REQUIRED_TOOLS)
    elif isinstance(required_tools, str):
        required_tools = [required_tools]
    elif not isinstance(required_tools, list):
        return {"error": "required_tools must be a string, list of strings, or omitted."}
    required_tools = [tool for tool in required_tools if isinstance(tool, str) and tool.strip()]

    diagnostics = get_runtime_diagnostics(required_tools=required_tools)
    if "error" in diagnostics:
        return diagnostics
    runtime_report = diagnostics.get("result") or {}
    server_status = _server_runtime_status()
    discovery = _read_discovery_payload()
    discovery_payload = discovery.get("payload") if isinstance(discovery.get("payload"), dict) else {}
    auth_token = server_status.get("authToken")
    discovery_token = discovery_payload.get("token")
    token_matches = bool(auth_token and discovery_token and auth_token == discovery_token)

    app = _safe_value(lambda: adsk.core.Application.get())
    active_doc = _safe_value(lambda: app.activeDocument) if app else None
    design = _safe_value(get_active_design)
    snapshot = _safe_value(lambda: _design_state_snapshot(include_selections=False)) if design else None
    unhealthy_count = _safe_value(lambda: snapshot["counts"]["unhealthyTimelineItems"], 0) if snapshot else None

    blocking_reasons = []
    warnings = []
    actions = []

    if runtime_report.get("requiredTools", {}).get("missingFromSchema"):
        blocking_reasons.append("One or more required tools are missing from the advertised schema.")
        actions.append("Restart/reload the FusionMCP add-in after reinstalling the current code.")
    if runtime_report.get("requiredTools", {}).get("missingFromRegistry"):
        blocking_reasons.append("One or more required tools are missing from the execution registry.")
        actions.append("Restart/reload the FusionMCP add-in and rerun doctor.")
    mismatch = runtime_report.get("registrySchemaMismatch") or {}
    if mismatch.get("schemaNotRegistered") or mismatch.get("registeredNotInSchema"):
        blocking_reasons.append("Tool schema and execution registry are out of sync.")
        actions.append("Run the unit suite and restart/reload the FusionMCP add-in.")

    if not server_status.get("available"):
        warnings.append("Server runtime status could not be inspected from this tool context.")
    else:
        if not server_status.get("serverRunning"):
            warnings.append("Server instance is not marked as running in-process.")
        if not server_status.get("taskManagerRunning"):
            blocking_reasons.append("TaskManager is not running; tools/call cannot execute Fusion API work.")
            actions.append("Stop/start the FusionMCP add-in from Utilities > Add-Ins.")
        if server_status.get("pendingTasks"):
            warnings.append(f"TaskManager has {server_status.get('pendingTasks')} pending task(s).")
        task_manager = server_status.get("taskManager") or {}
        oldest_age = task_manager.get("oldestTaskAgeSeconds") or 0
        timeout_seconds = task_manager.get("taskTimeoutSeconds") or 0
        if task_manager.get("backpressureActive"):
            blocking_reasons.append("TaskManager backpressure is active; too many tasks are pending.")
            actions.append("Wait for pending tasks to drain or stop/start the FusionMCP add-in.")
        elif timeout_seconds and oldest_age >= timeout_seconds:
            warnings.append("TaskManager has stale pending task metadata.")
            actions.append("Run doctor again or stop/start the FusionMCP add-in if pending tasks do not drain.")

    if not discovery.get("exists"):
        blocking_reasons.append("Discovery file is missing.")
        actions.append("Stop/start the FusionMCP add-in so it writes a fresh .fusion_mcp.json.")
    elif discovery.get("error"):
        blocking_reasons.append("Discovery file could not be read.")
        actions.append("Delete the stale discovery file and stop/start the FusionMCP add-in.")
    elif not token_matches:
        blocking_reasons.append("Discovery token does not match the live server token.")
        actions.append("Refresh discovery from /health or stop/start the FusionMCP add-in.")

    if require_active_design and not design:
        blocking_reasons.append("No active Fusion design is available.")
        actions.append("Open or activate a Fusion design document before running model tools.")
    elif not require_active_design and not design:
        warnings.append("No active Fusion design is available.")

    if unhealthy_count:
        warnings.append(f"Active design has {unhealthy_count} unhealthy timeline item(s).")
        actions.append("Run preflight_model_change or inspect timeline health before mutating/exporting.")

    status = "error" if blocking_reasons else ("warning" if warnings else "ok")
    if not actions and status == "ok":
        actions.append("FusionMCP is ready for structured tool use.")

    redacted_discovery = dict(discovery)
    if "payload" in redacted_discovery:
        redacted_discovery["payload"] = _redact_discovery_payload(redacted_discovery.get("payload"))
    redacted_server_status = dict(server_status)
    if redacted_server_status.get("authToken"):
        redacted_server_status["authToken"] = "<redacted>"

    return {
        "result": {
            "status": status,
            "ok": status == "ok",
            "toolExecutionReady": not blocking_reasons and bool(server_status.get("taskManagerRunning")),
            "blockingReasons": blocking_reasons,
            "warnings": warnings,
            "recommendedActions": actions,
            "checks": {
                "requiredTools": runtime_report.get("requiredTools"),
                "registrySchemaMismatch": runtime_report.get("registrySchemaMismatch"),
                "toolCounts": runtime_report.get("toolCounts"),
                "server": redacted_server_status,
                "discovery": redacted_discovery,
                "discoveryTokenMatchesLive": token_matches,
                "activeDocument": {
                    "name": _safe_value(lambda: active_doc.name),
                    "isModified": _safe_value(lambda: active_doc.isModified),
                } if active_doc else None,
                "activeDesign": {
                    "available": bool(design),
                    "units": _safe_value(lambda: design.unitsManager.defaultLengthUnits) if design else None,
                    "unhealthyTimelineItems": unhealthy_count,
                },
            },
        }
    }


@register_tool("get_change_journal")
def get_change_journal(limit=200):
    mcp_server = _mcp_server_module()
    return {
        "result": {
            "path": mcp_server.journal_file_path(),
            "entries": mcp_server.read_change_journal(limit=limit),
        }
    }


@register_tool("clear_change_journal")
def clear_change_journal(reason=None):
    if not isinstance(reason, str) or not reason.strip():
        return {"error": "reason is required before clearing the change journal."}
    mcp_server = _mcp_server_module()
    removed = mcp_server.clear_change_journal()
    return {
        "result": {
            "cleared": bool(removed),
            "path": mcp_server.journal_file_path(),
            "reason": reason.strip(),
        }
    }


@register_tool("search_local_fusion_docs")
def search_local_fusion_docs(query=None, limit=10):
    try:
        limit = max(1, min(int(limit), 25))
    except (TypeError, ValueError):
        limit = 10
    return {
        "result": {
            "query": query,
            "entries": _search_docs(query=query, limit=limit),
        }
    }


@register_tool("recommend_mcp_workflow")
def recommend_mcp_workflow(task, intent=None, allow_raw_script=False):
    """
    Return the structured FusionMCP workflow an agent should use for a task.

    This is deliberately read-only and policy-shaped: it gives agents a cheap
    MCP-native planning step before they reach for run_fusion_script.
    """
    if not isinstance(task, str) or not task.strip():
        return {"error": "task must be a non-empty string."}
    if intent is not None and not isinstance(intent, str):
        return {"error": "intent must be a string when provided."}

    workflow_name = _classify_workflow(task, intent)
    policy = _tool_first_policy()
    workflow = policy["workflows"][workflow_name]
    raw_policy = policy["rawScriptPolicy"]
    first_tools = list(workflow["firstTools"])
    preferred_tools = list(workflow["preferredTools"])

    next_actions = [f"Call {tool}." for tool in first_tools]
    if workflow_name == "export":
        next_actions.append("Use export_asset for STEP/STL/3MF or create_2d_drawing for drawing PDFs only after preflight passes.")
    elif workflow_name == "parameterize_existing_model":
        next_actions.append("Use the plan output to edit existing dimensions/parameters without intentionally changing geometry.")
    elif workflow_name == "modify_geometry":
        next_actions.append("Use structured sketch/feature tools and validate_model after the change.")

    return {
        "result": {
            "workflow": workflow_name,
            "task": task.strip(),
            "intent": intent.strip() if isinstance(intent, str) else None,
            "requiredFirstTools": first_tools,
            "preferredTools": preferred_tools,
            "resource": policy["resource"],
            "nextActions": next_actions,
            "rawScript": {
                "allowed": bool(allow_raw_script),
                "status": raw_policy["status"],
                "tool": raw_policy["tool"],
                "requiredArguments": raw_policy["requiredArguments"],
                "guidance": (
                    "Raw scripting is still a last resort. If used, the response must explain why the listed "
                    "structured tools cannot safely complete the operation."
                ),
                "exportPolicy": raw_policy["exportPolicy"],
            },
        }
    }


@register_tool("run_fusion_script")
def run_fusion_script(script, script_intent=None, mcp_tool_gap=None, allow_export=False, export_override_reason=None):
    if not isinstance(script, str) or not script.strip():
        return {"error": "Script must be a non-empty string."}
    if not isinstance(script_intent, str) or not script_intent.strip():
        return {
            "error": (
                "run_fusion_script is a fallback tool of last resort. Provide script_intent explaining the specific "
                "operation, after using structured MCP tools for inspection/planning first."
            ),
            "preferredTools": [
                "inspect_design",
                "get_timeline",
                "inspect_sketch",
                "inspect_feature",
                "plan_parameterization",
                "preflight_model_change",
                "create_sketch",
                "draw_line",
                "draw_rectangle",
                "draw_circle",
                "extrude_feature",
                "revolve_feature",
                "loft_feature",
                "sweep_feature",
                "fillet_feature",
                "chamfer_feature",
                "export_asset",
            ],
        }
    if not isinstance(mcp_tool_gap, str) or not mcp_tool_gap.strip():
        return {
            "error": (
                "mcp_tool_gap is required for run_fusion_script. State why the existing structured MCP tools cannot "
                "safely accomplish this operation."
            ),
            "guidance": "If a structured tool can do the job, call that tool instead of raw scripting.",
        }
    if _script_looks_like_export(script) and not allow_export:
        return {
            "error": (
                "Scripted Fusion exports are blocked by default. Use export_asset so compute and timeline health "
                "preflight checks run before writing files. If this raw export is intentional, call run_fusion_script "
                "with allow_export=true and export_override_reason."
            )
        }
    if _script_looks_like_export(script) and (not isinstance(export_override_reason, str) or not export_override_reason.strip()):
        return {"error": "export_override_reason is required when allow_export=true for a script that uses Fusion export APIs."}

    app = adsk.core.Application.get()
    ui = app.userInterface
    design = adsk.fusion.Design.cast(app.activeProduct)
    
    script_globals = {
        "__name__": "__fusion_mcp_script__",
        "adsk": adsk,
        "app": app,
        "ui": ui,
        "design": design,
        "rootComp": design.rootComponent if design else None
    }
    before = _safe_value(lambda: _design_state_snapshot(include_selections=False))
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout
    try:
        exec(script, script_globals)
        run_func = script_globals.get("run")
        if callable(run_func):
            run_func(None)
        else:
            return {"error": "Script must define a callable run(context) function."}
    except Exception as e:
        raise FusionScriptExecutionError(str(e), new_stdout.getvalue(), traceback.format_exc())
    finally:
        sys.stdout = old_stdout
    after = _safe_value(lambda: _design_state_snapshot(include_selections=False))
    state_comparison = None
    if before and after:
        state_comparison = _safe_value(lambda: compare_design_state(before, after).get("result"))
    return {
        "result": "Script executed",
        "output": new_stdout.getvalue(),
        "scriptIntent": script_intent.strip(),
        "mcpToolGap": mcp_tool_gap.strip(),
        "stateComparison": state_comparison,
    }

@register_tool("capture_view")
def capture_view(view_name="iso"):
    import tempfile
    app = adsk.core.Application.get()
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"fusion_screenshot_{uuid.uuid4().hex[:6]}.png")
    viewport = app.activeViewport
    
    # Map and set camera view orientation if requested
    set_camera(view_name)
    
    viewport.saveAsImageFile(file_path, 1920, 1080)
    return {"result": f"Screenshot saved to {file_path}"}


def _safe_filename(value):
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value or "step"))
    return cleaned.strip("_") or "step"


def _entity_visibility(entity):
    if hasattr(entity, "isLightBulbOn"):
        return "isLightBulbOn", _safe_value(lambda: entity.isLightBulbOn)
    if hasattr(entity, "isVisible"):
        return "isVisible", _safe_value(lambda: entity.isVisible)
    return None, None


def _visibility_snapshot(root):
    snapshot = []
    for component in _all_components(root):
        for collection_name, collection_getter in (
            ("body", lambda component=component: component.bRepBodies),
            ("sketch", lambda component=component: component.sketches),
            ("constructionPlane", lambda component=component: component.constructionPlanes),
        ):
            for entity in _collection_items(_safe_value(collection_getter)):
                attr, value = _entity_visibility(entity)
                if attr:
                    snapshot.append({
                        "entity": entity,
                        "attr": attr,
                        "value": value,
                        "kind": collection_name,
                        "name": _safe_value(lambda entity=entity: entity.name),
                    })
    return snapshot


def _restore_visibility(snapshot):
    restored = []
    for item in snapshot:
        entity = item.get("entity")
        attr = item.get("attr")
        if entity is None or not attr:
            continue
        try:
            setattr(entity, attr, item.get("value"))
            restored.append({"kind": item.get("kind"), "name": item.get("name")})
        except Exception:
            continue
    return restored


def _normalize_string_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    return []


def _body_key(body):
    token = _safe_value(lambda: body.entityToken)
    if token:
        return f"token:{token}"
    return f"id:{id(body)}"


def _all_brep_bodies(root):
    bodies = []
    for component in _all_components(root):
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            bodies.append(body)
    return bodies


def _is_brep_body(entity):
    return bool(adsk.fusion.BRepBody.cast(entity))


def _resolve_export_bodies(design, body_names=None, body_entity_tokens=None, selection_set_names=None):
    root = design.rootComponent
    requested_body_names = _normalize_string_list(body_names)
    requested_body_tokens = _normalize_string_list(body_entity_tokens)
    requested_selection_sets = _normalize_string_list(selection_set_names)
    all_bodies = _all_brep_bodies(root)
    bodies_by_name = {}
    bodies_by_token = {}
    for body in all_bodies:
        name = _safe_value(lambda body=body: body.name)
        if name:
            bodies_by_name.setdefault(name, []).append(body)
        token = _safe_value(lambda body=body: body.entityToken)
        if token:
            bodies_by_token.setdefault(token, []).append(body)

    resolved = []
    missing_bodies = []
    missing_tokens = []
    ambiguous_bodies = []
    ambiguous_tokens = []
    for name in requested_body_names:
        matches = bodies_by_name.get(name) or []
        if not matches:
            missing_bodies.append(name)
            continue
        if len(matches) > 1:
            ambiguous_bodies.append({"name": name, "count": len(matches)})
            continue
        resolved.append(matches[0])
    for token in requested_body_tokens:
        matches = bodies_by_token.get(token) or []
        if not matches:
            missing_tokens.append(token)
            continue
        if len(matches) > 1:
            ambiguous_tokens.append({"entityToken": token, "count": len(matches)})
            continue
        resolved.append(matches[0])

    missing_sets = []
    set_summaries = []
    if requested_selection_sets:
        snapshots = _selection_set_snapshots(names=requested_selection_sets, include_entities=True)
        found_names = {item.get("name") for item in snapshots}
        missing_sets = [name for name in requested_selection_sets if name not in found_names]
        token_to_body = {
            _safe_value(lambda body=body: body.entityToken): body
            for body in all_bodies
            if _safe_value(lambda body=body: body.entityToken)
        }
        name_to_single_body = {
            name: matches[0]
            for name, matches in bodies_by_name.items()
            if len(matches) == 1
        }
        for item in snapshots:
            body_count = 0
            non_body_entities = []
            for entity_info in item.get("entities") or []:
                body = None
                token = entity_info.get("entityToken")
                body_name = entity_info.get("bodyName") or entity_info.get("name")
                if token:
                    body = token_to_body.get(token)
                if body is None and body_name:
                    body = name_to_single_body.get(body_name)
                if body is not None:
                    resolved.append(body)
                    body_count += 1
                else:
                    non_body_entities.append(entity_info)
            set_summaries.append({
                "name": item.get("name"),
                "entityCount": item.get("entityCount"),
                "bodyCount": body_count,
                "nonBodyEntityCount": len(non_body_entities),
                "nonBodyEntities": non_body_entities[:10],
            })

    deduped = []
    seen = set()
    for body in resolved:
        key = _body_key(body)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(body)

    return {
        "bodies": deduped,
        "allBodies": all_bodies,
        "missingBodies": missing_bodies,
        "missingBodyEntityTokens": missing_tokens,
        "ambiguousBodies": ambiguous_bodies,
        "ambiguousBodyEntityTokens": ambiguous_tokens,
        "missingSelectionSets": missing_sets,
        "selectionSets": set_summaries,
        "requestedBodyNames": requested_body_names,
        "requestedBodyEntityTokens": requested_body_tokens,
        "requestedSelectionSetNames": requested_selection_sets,
    }


def _body_export_summary(body):
    info = _describe_selected_entity(body)
    return {
        "name": info.get("bodyName") or info.get("name"),
        "componentName": info.get("componentName"),
        "entityToken": info.get("entityToken"),
        "isVisible": _safe_value(lambda: body.isVisible),
    }


def _object_collection_from_entities(entities):
    object_collection_factory = _safe_value(lambda: adsk.core.ObjectCollection)
    create = _safe_value(lambda: object_collection_factory.create)
    if not callable(create):
        return None
    collection = create()
    add = _safe_value(lambda: collection.add)
    append = _safe_value(lambda: collection.append)
    for entity in entities:
        if callable(add):
            add(entity)
        elif callable(append):
            append(entity)
        else:
            return None
    return collection


def _create_3mf_export_options(export_manager, export_path, design, bodies):
    root = design.rootComponent
    body_collection = _object_collection_from_entities(bodies)
    candidate_args = [
        (bodies, export_path),
        (export_path, bodies),
        (root, export_path),
        (export_path, root),
        (export_path,),
    ]
    if body_collection is not None:
        candidate_args.insert(0, (export_path, body_collection))
        candidate_args.insert(0, (body_collection, export_path))
    method_names = ("createC3MFExportOptions", "create3MFExportOptions", "createThreeMFExportOptions")
    errors = []
    for method_name in method_names:
        method = _safe_value(lambda method_name=method_name: getattr(export_manager, method_name))
        if not callable(method):
            continue
        for args in candidate_args:
            try:
                return method(*args), f"{method_name}/{len(args)}"
            except TypeError as exc:
                errors.append(f"{method_name}/{len(args)}: {exc}")
                continue
    return None, "; ".join(errors) if errors else "Fusion runtime did not expose a compatible 3MF export options builder."


def _inspect_3mf_archive(export_path, expected_body_count=None):
    def build_print_readiness(result):
        blockers = []
        warnings = list(result.get("warnings") or [])
        if not result.get("exists") or result.get("sizeBytes", 0) <= 0:
            blockers.append("3MF file is missing or empty.")
        if not result.get("isZip"):
            blockers.append("3MF file is not a readable ZIP package.")
        if result.get("isZip") and not result.get("has3DModelPart"):
            blockers.append("3MF package does not contain a 3D model part.")
        if result.get("has3DModelPart") and result.get("objectCount", 0) <= 0:
            blockers.append("3MF model part does not contain object resources.")
        if result.get("has3DModelPart") and result.get("buildItemCount", 0) <= 0:
            blockers.append("3MF model part does not contain build items.")
        if result.get("missingBuildObjectIds"):
            blockers.append("3MF build contains object references that do not exist.")
        if result.get("missingComponentObjectIds"):
            blockers.append("3MF components contain object references that do not exist.")
        if expected_body_count is not None and not result.get("slicerColorabilityLikely"):
            warnings.append("3MF appears valid but may not expose enough separate objects for multicolor slicer assignment.")
        status = "ready" if not blockers and not warnings else "warning" if not blockers else "blocked"
        return {
            "status": status,
            "readyForSlicerImport": not blockers,
            "readyForMulticolorAssignment": not blockers and bool(result.get("slicerColorabilityLikely")),
            "blockingReasons": blockers,
            "warnings": warnings,
            "nextActions": [
                "Open the 3MF in the slicer and verify each intended body is separately colorable.",
            ] if not blockers and result.get("slicerColorabilityLikely") else [
                "Re-export as targeted multibody 3MF and verify separate object candidates match the intended body count.",
            ],
        }

    result = {
        "path": export_path,
        "exists": os.path.isfile(export_path),
        "sizeBytes": os.path.getsize(export_path) if os.path.isfile(export_path) else 0,
        "isZip": False,
        "has3DModelPart": False,
        "modelPart": None,
        "objectCount": 0,
        "meshObjectCount": 0,
        "componentObjectCount": 0,
        "componentReferenceCount": 0,
        "buildItemCount": 0,
        "objectIds": [],
        "buildObjectIds": [],
        "componentObjectIds": [],
        "missingBuildObjectIds": [],
        "missingComponentObjectIds": [],
        "separateObjectCandidateCount": 0,
        "baseMaterialGroupCount": 0,
        "colorGroupCount": 0,
        "colorPropertyCount": 0,
        "textureGroupCount": 0,
        "compositeMaterialGroupCount": 0,
        "multiPropertyGroupCount": 0,
        "propertyReferenceCount": 0,
        "embeddedColorEvidence": False,
        "slicerColorabilityLikely": False,
        "valid": False,
        "printReadiness": None,
        "validationScope": {
            "packageStructure": False,
            "objectSeparation": False,
            "embeddedMaterialOrColorProperties": False,
            "slicerAssignmentVerified": False,
            "notes": [
                "Archive inspection validates 3MF package structure and object separation only.",
                "It cannot prove that a specific slicer will preserve or expose every intended color assignment.",
            ],
        },
        "metadata": {},
        "warnings": [],
    }
    if not result["exists"] or result["sizeBytes"] <= 0:
        result["warnings"].append("3MF file does not exist or is empty.")
        result["printReadiness"] = build_print_readiness(result)
        return result
    try:
        with zipfile.ZipFile(export_path, "r") as archive:
            result["isZip"] = True
            names = archive.namelist()
            model_candidates = [name for name in names if name.lower().endswith(".model") and name.lower().startswith("3d/")]
            if not model_candidates:
                result["warnings"].append("3MF archive does not contain a 3D model part.")
                result["printReadiness"] = build_print_readiness(result)
                return result
            model_part = sorted(model_candidates)[0]
            result["has3DModelPart"] = True
            result["modelPart"] = model_part
            root = ET.fromstring(archive.read(model_part))

            def local_name(element):
                tag = str(element.tag)
                return tag.rsplit("}", 1)[-1] if "}" in tag else tag

            objects = [element for element in root.iter() if local_name(element) == "object"]
            build_items = [element for element in root.iter() if local_name(element) == "item"]
            component_refs = [element for element in root.iter() if local_name(element) == "component"]
            object_ids = [element.attrib.get("id") for element in objects if element.attrib.get("id")]
            object_id_set = set(object_ids)
            mesh_objects = [element for element in objects if any(local_name(child) == "mesh" for child in list(element))]
            component_objects = [element for element in objects if any(local_name(child) == "components" for child in list(element))]
            build_object_ids = [element.attrib.get("objectid") for element in build_items if element.attrib.get("objectid")]
            component_object_ids = [element.attrib.get("objectid") for element in component_refs if element.attrib.get("objectid")]
            base_material_groups = [element for element in root.iter() if local_name(element).lower() == "basematerials"]
            color_groups = [element for element in root.iter() if local_name(element).lower() == "colorgroup"]
            color_properties = [element for element in root.iter() if local_name(element).lower() == "color"]
            texture_groups = [element for element in root.iter() if local_name(element).lower() == "texture2dgroup"]
            composite_groups = [element for element in root.iter() if local_name(element).lower() == "compositematerials"]
            multi_property_groups = [element for element in root.iter() if local_name(element).lower() == "multiproperties"]
            property_reference_count = 0
            for element in root.iter():
                attrs = {str(key).lower(): value for key, value in element.attrib.items()}
                if "pid" in attrs or any(key.startswith("p") and key[1:].isdigit() for key in attrs):
                    property_reference_count += 1

            result["objectCount"] = len(objects)
            result["meshObjectCount"] = len(mesh_objects)
            result["componentObjectCount"] = len(component_objects)
            result["componentReferenceCount"] = len(component_refs)
            result["buildItemCount"] = len(build_items)
            result["objectIds"] = object_ids
            result["buildObjectIds"] = build_object_ids
            result["componentObjectIds"] = component_object_ids
            result["missingBuildObjectIds"] = [object_id for object_id in build_object_ids if object_id not in object_id_set]
            result["missingComponentObjectIds"] = [object_id for object_id in component_object_ids if object_id not in object_id_set]
            result["separateObjectCandidateCount"] = max(result["buildItemCount"], result["meshObjectCount"])
            result["baseMaterialGroupCount"] = len(base_material_groups)
            result["colorGroupCount"] = len(color_groups)
            result["colorPropertyCount"] = len(color_properties)
            result["textureGroupCount"] = len(texture_groups)
            result["compositeMaterialGroupCount"] = len(composite_groups)
            result["multiPropertyGroupCount"] = len(multi_property_groups)
            result["propertyReferenceCount"] = property_reference_count
            result["embeddedColorEvidence"] = bool(
                result["baseMaterialGroupCount"]
                or result["colorGroupCount"]
                or result["textureGroupCount"]
                or result["compositeMaterialGroupCount"]
                or result["multiPropertyGroupCount"]
                or result["propertyReferenceCount"]
            )
            metadata = {}
            for element in root.iter():
                if local_name(element) == "metadata":
                    name = element.attrib.get("name")
                    if name:
                        metadata[name] = element.text
            result["metadata"] = metadata
            if result["missingBuildObjectIds"]:
                result["warnings"].append("3MF build references missing object id(s): " + ", ".join(result["missingBuildObjectIds"]) + ".")
            if result["missingComponentObjectIds"]:
                result["warnings"].append("3MF component references missing object id(s): " + ", ".join(result["missingComponentObjectIds"]) + ".")
            if expected_body_count is not None:
                expected = int(expected_body_count)
                if result["objectCount"] < expected:
                    result["warnings"].append(f"3MF archive has {result['objectCount']} object(s), fewer than expected target body count {expected}.")
                if result["separateObjectCandidateCount"] < expected:
                    result["warnings"].append(f"3MF archive exposes {result['separateObjectCandidateCount']} separate object candidate(s), fewer than expected target body count {expected}.")
                result["slicerColorabilityLikely"] = result["separateObjectCandidateCount"] >= expected
                if expected > 1 and not result["embeddedColorEvidence"]:
                    result["warnings"].append("3MF archive exposes separate object candidates but no embedded material/color property groups; slicer color assignment may still work by object, but embedded colors were not verified.")
            else:
                result["slicerColorabilityLikely"] = result["separateObjectCandidateCount"] > 1
            result["valid"] = result["isZip"] and result["has3DModelPart"] and result["objectCount"] > 0 and result["buildItemCount"] > 0 and not result["missingBuildObjectIds"] and not result["missingComponentObjectIds"]
            result["validationScope"] = {
                "packageStructure": bool(result["valid"]),
                "objectSeparation": bool(result["slicerColorabilityLikely"]),
                "embeddedMaterialOrColorProperties": bool(result["embeddedColorEvidence"]),
                "slicerAssignmentVerified": False,
                "notes": [
                    "Archive inspection validates ZIP readability, 3D model resources, build references, object separation, and embedded material/color property evidence when present.",
                    "It cannot prove that a specific slicer will preserve or expose every intended color assignment; open the 3MF in the target slicer for final verification.",
                ],
            }
    except zipfile.BadZipFile:
        result["warnings"].append("3MF output is not a valid ZIP archive.")
    except Exception as exc:
        result["warnings"].append(f"Failed to inspect 3MF archive: {exc}")
    result["printReadiness"] = build_print_readiness(result)
    return result


@register_tool("inspect_3mf_archive")
def inspect_3mf_archive(export_path, expected_body_count=None):
    """
    Read-only inspection for an existing 3MF file.

    This is useful after any export path, including external or manually
    generated files, because it does not require an active Fusion design.
    """
    try:
        if not isinstance(export_path, str) or not export_path:
            return {"error": "export_path must be a non-empty string."}
        if "\x00" in export_path:
            return {"error": "export_path contains an invalid null byte."}
        if not os.path.isabs(export_path):
            return {"error": "export_path must be absolute."}
        if os.path.splitext(export_path)[1].lower() != ".3mf":
            return {"error": "export_path must end in .3mf."}
        return {"result": _inspect_3mf_archive(export_path, expected_body_count=expected_body_count)}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting 3MF archive: {e}\n{err}")
        return {"error": f"Failed to inspect 3MF archive: {str(e)}"}


def _multibody_3mf_plan(export_path=None, body_names=None, body_entity_tokens=None, selection_set_names=None, require_compute=True, expected_body_count=None, allow_overwrite=False, requires_user_approval=False, reason=None):
    blockers = []
    warnings = []
    if not isinstance(export_path, str) or not export_path.strip():
        blockers.append("export_path is required.")
    elif "\x00" in export_path:
        blockers.append("export_path contains an invalid null byte.")
    elif not os.path.isabs(export_path):
        blockers.append("export_path must be absolute.")
    elif os.path.splitext(export_path)[1].lower() != ".3mf":
        blockers.append("export_path must end in .3mf.")
    if requires_user_approval and (not isinstance(reason, str) or not reason.strip()):
        blockers.append("reason is required when requires_user_approval=true.")

    design = get_active_design()
    preflight = preflight_export(require_compute=require_compute)
    preflight_result = preflight.get("result") if isinstance(preflight, dict) else None
    if "error" in preflight:
        blockers.append(preflight["error"])
    elif preflight_result and not preflight_result.get("okToExport"):
        blockers.extend(preflight_result.get("blockingReasons") or ["Generic export preflight failed."])

    resolution = _resolve_export_bodies(
        design,
        body_names=body_names,
        body_entity_tokens=body_entity_tokens,
        selection_set_names=selection_set_names,
    )
    if resolution["missingBodies"]:
        blockers.append(f"Missing body target(s): {', '.join(resolution['missingBodies'])}.")
    if resolution["missingBodyEntityTokens"]:
        blockers.append(f"Missing body entity token target(s): {', '.join(resolution['missingBodyEntityTokens'])}.")
    if resolution["ambiguousBodies"]:
        blockers.append("Ambiguous body target(s): " + ", ".join(f"{item['name']} ({item['count']} matches)" for item in resolution["ambiguousBodies"]) + ".")
    if resolution["ambiguousBodyEntityTokens"]:
        blockers.append("Ambiguous body entity token target(s): " + ", ".join(f"{item['entityToken']} ({item['count']} matches)" for item in resolution["ambiguousBodyEntityTokens"]) + ".")
    if resolution["missingSelectionSets"]:
        blockers.append(f"Missing selection set(s): {', '.join(resolution['missingSelectionSets'])}.")
    if not resolution["bodies"]:
        blockers.append("No BRep bodies were resolved for 3MF export. Provide body_names, body_entity_tokens, or selection_set_names.")
    if expected_body_count is not None:
        try:
            expected = int(expected_body_count)
            if expected != len(resolution["bodies"]):
                blockers.append(f"Resolved {len(resolution['bodies'])} target bodies, expected {expected}.")
        except (TypeError, ValueError):
            blockers.append("expected_body_count must be an integer when provided.")
    for item in resolution["selectionSets"]:
        if item.get("nonBodyEntityCount"):
            warnings.append(f"Selection set '{item.get('name')}' contains {item.get('nonBodyEntityCount')} non-body entity/entities ignored for 3MF export.")
    if export_path and os.path.exists(export_path):
        if allow_overwrite:
            warnings.append("export_path already exists and allow_overwrite=true permits replacing it.")
        else:
            blockers.append("export_path already exists. Set allow_overwrite=true only when replacing it is intentional.")

    target_bodies = [_body_export_summary(body) for body in resolution["bodies"]]
    return {
        "okToExport": not blockers,
        "blockingReasons": blockers,
        "warnings": warnings,
        "exportPath": export_path,
        "format": "3mf",
        "targetBodies": target_bodies,
        "targetBodyCount": len(target_bodies),
        "allowOverwrite": bool(allow_overwrite),
        "targetResolution": {
            "requestedBodyNames": resolution["requestedBodyNames"],
            "requestedBodyEntityTokens": resolution["requestedBodyEntityTokens"],
            "requestedSelectionSetNames": resolution["requestedSelectionSetNames"],
            "selectionSets": resolution["selectionSets"],
        },
        "preflight": preflight_result or preflight,
        "requiresUserApproval": bool(requires_user_approval),
        "reason": reason.strip() if isinstance(reason, str) else None,
        "nextActions": [
            "Call export_asset with format='3mf' and the same explicit body_names/body_entity_tokens/selection_set_names after this plan is okToExport.",
            "Open the exported 3MF in the slicer and verify separate body/color objects before printing.",
        ],
    }


@register_tool("plan_multibody_3mf_export")
def plan_multibody_3mf_export(export_path=None, body_names=None, body_entity_tokens=None, selection_set_names=None, require_compute=True, expected_body_count=None, allow_overwrite=False, requires_user_approval=False, reason=None):
    """
    Read-only 3MF export plan for multibody/color workflows.

    This resolves exact body and selection-set targets, runs generic export
    preflight, reports ignored non-body selection-set members, and gives agents
    a structured path before writing a 3MF file.
    """
    try:
        return {"result": _multibody_3mf_plan(
            export_path=export_path,
            body_names=body_names,
            body_entity_tokens=body_entity_tokens,
            selection_set_names=selection_set_names,
            require_compute=require_compute,
            expected_body_count=expected_body_count,
            allow_overwrite=allow_overwrite,
            requires_user_approval=requires_user_approval,
            reason=reason,
        )}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error planning multibody 3MF export: {e}\n{err}")
        return {"error": f"Failed to plan multibody 3MF export: {str(e)}"}


@register_tool("plan_multicolor_3mf_export")
def plan_multicolor_3mf_export(export_path=None, color_assignments=None, selection_set_names=None, require_compute=True, expected_body_count=None, allow_overwrite=False, requires_user_approval=False, reason=None):
    """
    Read-only planner for color/material-aware multibody 3MF exports.

    color_assignments is a list of objects with appearance_name plus either
    body_name or body_entity_token. The tool resolves exact body targets,
    verifies appearances are discoverable, reports current style state, and
    returns the apply_appearance/export_asset sequence without writing files.
    """
    try:
        assignments = color_assignments or []
        if not isinstance(assignments, list):
            return {"error": "color_assignments must be an array of assignment objects."}
        blockers = []
        warnings = []
        body_names = []
        body_tokens = []
        assignment_reports = []
        seen_targets = set()
        app = adsk.core.Application.get()
        design = get_active_design()
        for index, assignment in enumerate(assignments):
            if not isinstance(assignment, dict):
                blockers.append(f"color_assignments[{index}] must be an object.")
                continue
            body_name = str(assignment.get("body_name") or "").strip()
            body_token = str(assignment.get("body_entity_token") or "").strip()
            appearance_name = str(assignment.get("appearance_name") or "").strip()
            if not body_name and not body_token:
                blockers.append(f"color_assignments[{index}] requires body_name or body_entity_token.")
            if not appearance_name:
                blockers.append(f"color_assignments[{index}] requires appearance_name.")
            if body_name:
                body_names.append(body_name)
            if body_token:
                body_tokens.append(body_token)
            target_key = body_token or f"name:{body_name}"
            if target_key in seen_targets:
                blockers.append(f"Duplicate color assignment target: {target_key}.")
            seen_targets.add(target_key)
            appearance, appearance_error = _find_appearance(app, design, appearance_name, copy_from_library=False) if appearance_name else (None, None)
            if appearance_name and not appearance:
                blockers.append(appearance_error or f"Appearance '{appearance_name}' not found locally or in libraries.")
            assignment_reports.append({
                "index": index,
                "bodyName": body_name or None,
                "bodyEntityToken": body_token or None,
                "appearanceName": appearance_name or None,
                "appearance": _entity_ref(appearance),
            })

        plan = _multibody_3mf_plan(
            export_path=export_path,
            body_names=body_names,
            body_entity_tokens=body_tokens,
            selection_set_names=selection_set_names,
            require_compute=require_compute,
            expected_body_count=expected_body_count if expected_body_count is not None else len(assignments),
            allow_overwrite=allow_overwrite,
            requires_user_approval=requires_user_approval,
            reason=reason,
        )
        blockers.extend(plan.get("blockingReasons") or [])
        warnings.extend(plan.get("warnings") or [])
        resolved_by_name = {}
        resolved_by_token = {}
        for body in _resolve_export_bodies(design, body_names=body_names, body_entity_tokens=body_tokens, selection_set_names=None)["bodies"]:
            name = _safe_value(lambda body=body: body.name)
            token = _safe_value(lambda body=body: body.entityToken)
            if name:
                resolved_by_name[name] = body
            if token:
                resolved_by_token[token] = body
        for report in assignment_reports:
            body = resolved_by_token.get(report.get("bodyEntityToken")) if report.get("bodyEntityToken") else resolved_by_name.get(report.get("bodyName"))
            report["currentStyle"] = _body_style_summary(body) if body else None
            report["applyAppearanceArguments"] = {
                "appearance_name": report.get("appearanceName"),
                "body_entity_tokens": [report.get("bodyEntityToken")] if report.get("bodyEntityToken") else None,
                "body_names": [report.get("bodyName")] if report.get("bodyName") else None,
                "expected_body_count": 1,
            }

        return {
            "result": {
                "okToExport": not blockers,
                "blockingReasons": blockers,
                "warnings": warnings,
                "exportPlan": plan,
                "colorAssignments": assignment_reports,
                "nextActions": [
                    "Call apply_appearance once for each colorAssignments[].applyAppearanceArguments entry.",
                    "Call plan_multibody_3mf_export again after appearances are applied if you need a final read-only check.",
                    "Call export_asset with format='3mf', allow_overwrite matching this plan, and the resolved body target arguments.",
                    "Open the exported 3MF in the slicer and verify each body is separately colorable before printing.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error planning multicolor 3MF export: {e}\n{err}")
        return {"error": f"Failed to plan multicolor 3MF export: {str(e)}"}


def _capture_view_to_file(view_name, output_dir, filename, width, height):
    os.makedirs(output_dir, exist_ok=True)
    app = adsk.core.Application.get()
    viewport = app.activeViewport
    camera_result = set_camera(view_name)
    if "error" in camera_result:
        return None, camera_result
    file_path = os.path.join(output_dir, filename)
    viewport.saveAsImageFile(file_path, int(width), int(height))
    return file_path, camera_result


def _find_named_view(design, name):
    if not name:
        return None
    for named_view in _collection_items(_safe_value(lambda: design.namedViews)):
        if _safe_value(lambda named_view=named_view: named_view.name) == name:
            return named_view
    return None


@register_tool("render_viewport_output")
def render_viewport_output(camera_name=None, named_view=None, output_path=None, width=1920, height=1080, visual_style="shaded", environment=None, background=None, reason=None, requires_user_approval=False):
    """
    Capture a local viewport still after plan_render_output approves the request.

    This intentionally does not claim photoreal or cloud rendering. It writes a
    Fusion viewport image to the explicit output path and verifies the file.
    """
    try:
        preflight = plan_render_output(
            camera_name=camera_name,
            named_view=named_view,
            output_path=output_path,
            width=width,
            height=height,
            visual_style=visual_style,
            environment=environment,
            background=background,
            reason=reason,
            requires_user_approval=requires_user_approval,
        )
        if "error" in preflight:
            return {"error": "Render output preflight failed.", "preflight": preflight}
        preflight_result = preflight.get("result") or {}
        if not preflight_result.get("okToProceed"):
            return {"error": "Render output preflight failed.", "preflight": preflight_result}

        plan = preflight_result.get("renderPlan") or {}
        path = plan.get("outputPath")
        if not path:
            return {"error": "Render output preflight did not return an output path.", "preflight": preflight_result}

        app = adsk.core.Application.get()
        viewport = app.activeViewport
        if not viewport:
            return {"error": "Fusion did not expose an active viewport for render output.", "preflight": preflight_result}

        design = get_active_design()
        before = _safe_value(lambda: _design_state_snapshot(include_selections=True))
        camera_applied = None
        named_view_name = plan.get("namedView")
        if named_view_name:
            target_view = _find_named_view(design, named_view_name)
            if not target_view:
                return {"error": f"Named view '{named_view_name}' was not found.", "preflight": preflight_result}
            target_camera = _safe_value(lambda: target_view.camera)
            if not target_camera:
                return {"error": f"Named view '{named_view_name}' did not expose a camera.", "preflight": preflight_result}
            viewport.camera = target_camera
            _safe_value(lambda: viewport.fit())
            camera_applied = {"namedView": named_view_name}
        elif plan.get("cameraName") and plan.get("cameraName") != "activeViewport":
            return {"error": "Only camera_name='activeViewport' or named_view capture is currently supported.", "preflight": preflight_result}

        output_dir = os.path.dirname(path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        viewport.saveAsImageFile(path, int(plan.get("width") or width), int(plan.get("height") or height))
        exists = os.path.isfile(path)
        size_bytes = os.path.getsize(path) if exists else 0
        if not exists or size_bytes <= 0:
            return {
                "error": "Fusion viewport capture did not create a non-empty output file.",
                "outputPath": path,
                "exists": exists,
                "sizeBytes": size_bytes,
                "preflight": preflight_result,
            }

        after = _safe_value(lambda: _design_state_snapshot(include_selections=True))
        return {
            "result": {
                "rendered": True,
                "method": "active_viewport_saveAsImageFile",
                "outputPath": path,
                "exists": exists,
                "sizeBytes": size_bytes,
                "width": int(plan.get("width") or width),
                "height": int(plan.get("height") or height),
                "visualStyle": plan.get("visualStyle"),
                "environment": plan.get("environment"),
                "background": plan.get("background"),
                "camera": camera_applied or {"cameraName": plan.get("cameraName") or "activeViewport"},
                "preflight": preflight_result,
                "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
                "notes": [
                    "This is a local viewport still capture, not a photoreal or cloud render.",
                    "The output file was verified to exist and be non-empty.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error rendering viewport output: {e}\n{err}")
        return {"error": f"Failed to render viewport output: {str(e)}"}


@register_tool("capture_demo_sequence")
def capture_demo_sequence(steps=None, output_dir=None, view_names=None, image_width=1920, image_height=1080, restore_visibility=True, hide_all_sketches=False, hide_all_construction_planes=False):
    """
    Generic demo capture helper for staged visibility and named camera views.

    This captures still frames for later video editing. It does not encode video
    and does not contain model-specific dimensions or project assumptions.
    """
    try:
        import tempfile
        design = get_active_design()
        root = design.rootComponent
        before = _design_state_snapshot(include_selections=True)
        visibility_before = _visibility_snapshot(root)
        capture_dir = output_dir or os.path.join(tempfile.gettempdir(), f"fusion_demo_sequence_{uuid.uuid4().hex[:8]}")

        if steps is None:
            names = view_names or ["iso"]
            steps = [{"name": str(name), "view_name": str(name), "capture": True} for name in names]
        if not isinstance(steps, list) or not steps:
            return {"error": "steps must be a non-empty array, or omit steps and provide optional view_names."}

        results = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                return {"error": f"step {index} must be an object."}
            step_name = step.get("name") or f"step_{index:02d}"
            step_visibility = None
            visibility_requested = any(
                key in step for key in (
                    "body_names",
                    "sketch_names",
                    "construction_plane_names",
                    "visible",
                    "hide_all_sketches",
                    "hide_all_construction_planes",
                )
            )
            if visibility_requested or hide_all_sketches or hide_all_construction_planes:
                step_visibility = set_visibility(
                    body_names=step.get("body_names"),
                    sketch_names=step.get("sketch_names"),
                    construction_plane_names=step.get("construction_plane_names"),
                    visible=step.get("visible", True),
                    hide_all_sketches=bool(step.get("hide_all_sketches", hide_all_sketches)),
                    hide_all_construction_planes=bool(step.get("hide_all_construction_planes", hide_all_construction_planes)),
                    clear_selection=bool(step.get("clear_selection", True)),
                )

            captured_path = None
            camera_result = None
            if step.get("capture", True):
                view_name = step.get("view_name") or step.get("orientation") or "iso"
                filename = f"{index:02d}_{_safe_filename(step_name)}_{_safe_filename(view_name)}.png"
                captured_path, camera_result = _capture_view_to_file(
                    view_name,
                    capture_dir,
                    filename,
                    step.get("image_width", image_width),
                    step.get("image_height", image_height),
                )
                if not captured_path:
                    restored = _restore_visibility(visibility_before) if restore_visibility else []
                    return {
                        "error": f"Failed to capture step '{step_name}': {camera_result.get('error') if camera_result else 'unknown camera error'}",
                        "restoredVisibility": restored,
                    }

            results.append({
                "index": index,
                "name": step_name,
                "viewName": step.get("view_name") or step.get("orientation") or "iso",
                "filePath": captured_path,
                "note": step.get("note"),
                "visibility": step_visibility,
                "camera": camera_result,
            })

        after_steps = _design_state_snapshot(include_selections=True)
        restored = []
        if restore_visibility:
            restored = _restore_visibility(visibility_before)
        after_restore = _design_state_snapshot(include_selections=True)

        return {
            "result": {
                "outputDir": capture_dir,
                "frames": results,
                "frameCount": len([frame for frame in results if frame.get("filePath")]),
                "restoreVisibility": bool(restore_visibility),
                "restoredVisibility": restored,
                "stateComparisonAfterSteps": compare_design_state(before, after_steps).get("result"),
                "stateComparisonAfterRestore": compare_design_state(before, after_restore).get("result"),
                "notes": [
                    "This tool captures still PNG frames only; use a video editor or ffmpeg to assemble video.",
                    "Steps are generic camera/visibility staging instructions and contain no project-specific assumptions.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error capturing demo sequence: {e}\n{err}")
        return {"error": f"Failed to capture demo sequence: {str(e)}"}


def _timeline_health_report(design):
    timeline = design.timeline
    unhealthy = []
    for i in range(timeline.count):
        item = timeline.item(i)
        entity = _safe_value(lambda item=item: item.entity)
        item_health = _health_to_string(_safe_value(lambda item=item: item.healthState))
        feature_health = _health_to_string(_safe_value(lambda entity=entity: entity.healthState)) if entity else None
        messages = [
            message for message in (
                _safe_value(lambda entity=entity: entity.errorOrWarningMessage) if entity else None,
                _safe_value(lambda item=item: item.errorOrWarningMessage),
            )
            if message
        ]
        if item_health not in ("Healthy", "0", "None") or (feature_health and feature_health not in ("Healthy", "0", "None")) or messages:
            unhealthy.append({
                "index": i,
                "timelineName": _safe_value(lambda item=item: item.name),
                "featureName": _safe_value(lambda entity=entity: entity.name) if entity else None,
                "objectType": _safe_value(lambda entity=entity: entity.objectType) if entity else "SystemEvent",
                "timelineHealth": item_health,
                "featureHealth": feature_health,
                "messages": messages,
            })
    return unhealthy


def _export_blocking_reasons(compute_error, unhealthy, comparison):
    reasons = []
    if compute_error:
        reasons.append("Fusion computeAll failed.")
    if unhealthy:
        reasons.append("Timeline or feature health issues are present.")
    diff = (comparison or {}).get("diff") or {}
    count_changes = diff.get("countChanges") or {}
    for key in ("bodies", "timelineItems", "unhealthyTimelineItems"):
        if key in count_changes:
            reasons.append(f"Compute changed {key}.")
    return reasons


def _model_change_risk_level(blocking_reasons, warnings):
    if blocking_reasons:
        return "high"
    if warnings:
        return "medium"
    return "low"


@register_tool("preflight_model_change")
def preflight_model_change(change_type="generic", target_features=None, target_bodies=None, require_compute=True):
    """
    Read-only readiness check before mutating the active model.

    It intentionally does not approve the operation. It reports the current
    health, compute behavior, and likely downstream dependency risk so an
    agent can decide whether to proceed, ask for confirmation, or inspect more.
    """
    try:
        design = get_active_design()
        target_features = target_features or []
        target_bodies = target_bodies or []
        if isinstance(target_features, str):
            target_features = [target_features]
        if isinstance(target_bodies, str):
            target_bodies = [target_bodies]

        before = _design_state_snapshot(include_selections=True)
        compute_error = None
        if require_compute:
            try:
                design.computeAll()
            except Exception as e:
                compute_error = str(e)
        after = _design_state_snapshot(include_selections=True)
        comparison = compare_design_state(before, after).get("result")
        unhealthy = _timeline_health_report(design)

        dependency_reports = []
        downstream_consumers = []
        for feature_name in target_features:
            report = get_feature_dependencies(feature_name)
            if "error" in report:
                dependency_reports.append({"featureName": feature_name, "error": report["error"]})
                continue
            result = report.get("result") or {}
            dependency_reports.append(result)
            for consumer in result.get("likelyDownstreamConsumers") or []:
                downstream_consumers.append({
                    "targetFeature": feature_name,
                    "consumer": consumer,
                })

        blocking_reasons = []
        warnings = []
        if compute_error:
            blocking_reasons.append("Fusion computeAll failed.")
        if unhealthy:
            blocking_reasons.append("Timeline or feature health issues are present.")
        if downstream_consumers:
            blocking_reasons.append("Target feature has likely downstream consumers.")

        active_doc = after.get("document", {}).get("active") or {}
        if active_doc.get("isModified"):
            warnings.append("Active document has unsaved changes.")

        diff = (comparison or {}).get("diff") or {}
        count_changes = diff.get("countChanges") or {}
        if count_changes:
            warnings.append("computeAll changed design-state counts.")
        for warning in diff.get("warnings") or []:
            warnings.append(warning)

        return {
            "result": {
                "okToProceed": not blocking_reasons,
                "riskLevel": _model_change_risk_level(blocking_reasons, warnings),
                "changeType": change_type,
                "targetFeatures": list(target_features),
                "targetBodies": list(target_bodies),
                "blockingReasons": blocking_reasons,
                "warnings": warnings,
                "compute": {
                    "required": bool(require_compute),
                    "succeeded": compute_error is None,
                    "error": compute_error,
                },
                "activeDocument": active_doc,
                "counts": after.get("counts"),
                "unhealthyFeatures": unhealthy,
                "dependencyReports": dependency_reports,
                "downstreamConsumers": downstream_consumers,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error during model-change preflight: {e}\n{err}")
        return {"error": f"Failed model-change preflight: {str(e)}"}


@register_tool("preflight_export")
def preflight_export(require_compute=True):
    import traceback
    try:
        design = get_active_design()
        before = _design_state_snapshot(include_selections=False)
        compute_error = None
        if require_compute:
            try:
                design.computeAll()
            except Exception as e:
                compute_error = str(e)
        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        unhealthy = _timeline_health_report(design)
        blocking_reasons = _export_blocking_reasons(compute_error, unhealthy, comparison)
        return {
            "result": {
                "okToExport": not blocking_reasons,
                "blockingReasons": blocking_reasons,
                "compute": {
                    "required": bool(require_compute),
                    "succeeded": compute_error is None,
                    "error": compute_error,
                },
                "activeDocument": after.get("document", {}).get("active"),
                "counts": after.get("counts"),
                "unhealthyFeatures": unhealthy,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error during export preflight: {e}\n{err}")
        return {"error": f"Failed export preflight: {str(e)}"}


@register_tool("export_asset")
def export_asset(format, export_path, allow_unhealthy_export=False, require_compute=True, override_reason=None, body_names=None, body_entity_tokens=None, selection_set_names=None, restore_visibility=True, expected_body_count=None, allow_overwrite=False):
    if not isinstance(format, str):
        return {"error": "Export format must be a string."}
    if not isinstance(export_path, str) or not export_path:
        return {"error": "Export path must be a non-empty string."}
    if "\x00" in export_path:
        return {"error": "Export path contains an invalid null byte."}
    if not os.path.isabs(export_path):
        return {"error": "Export path must be absolute."}

    format = format.lower()
    design = get_active_design()
    preflight = preflight_export(require_compute=require_compute)
    if "error" in preflight:
        return preflight
    preflight_result = preflight["result"]
    if not preflight_result["okToExport"] and not allow_unhealthy_export:
        return {
            "error": "Export blocked by preflight checks. Fix compute/timeline health issues or explicitly set allow_unhealthy_export=true.",
            "preflight": preflight_result,
        }
    if not preflight_result["okToExport"] and (not isinstance(override_reason, str) or not override_reason.strip()):
        return {
            "error": "override_reason is required when exporting despite failed preflight checks.",
            "preflight": preflight_result,
        }

    export_dir = os.path.dirname(export_path)
    if export_dir and not os.path.exists(export_dir):
        os.makedirs(export_dir, exist_ok=True)
    exportMgr = design.exportManager
    before = _safe_value(lambda: _design_state_snapshot(include_selections=False))
    if format == "step":
        options = exportMgr.createSTEPExportOptions(export_path, design.rootComponent)
    elif format == "stl":
        options = exportMgr.createSTLExportOptions(design.rootComponent, export_path)
    elif format == "3mf":
        plan = _multibody_3mf_plan(
            export_path=export_path,
            body_names=body_names,
            body_entity_tokens=body_entity_tokens,
            selection_set_names=selection_set_names,
            require_compute=False,
            expected_body_count=expected_body_count,
            allow_overwrite=allow_overwrite,
            reason=override_reason,
        )
        plan_blockers = [
            reason for reason in plan.get("blockingReasons") or []
            if reason not in (preflight_result.get("blockingReasons") or [])
        ]
        if plan_blockers:
            return {
                "error": "3MF export target preflight failed.",
                "blockingReasons": plan_blockers,
                "targetResolution": plan.get("targetResolution"),
                "preflight": preflight_result,
            }
        resolution = _resolve_export_bodies(
            design,
            body_names=body_names,
            body_entity_tokens=body_entity_tokens,
            selection_set_names=selection_set_names,
        )

        visibility_snapshot = _visibility_snapshot(design.rootComponent)
        target_keys = {_body_key(body) for body in resolution["bodies"]}
        for body in resolution["allBodies"]:
            attr, _value = _entity_visibility(body)
            if attr:
                setattr(body, attr, _body_key(body) in target_keys)
        options, method_or_error = _create_3mf_export_options(exportMgr, export_path, design, resolution["bodies"])
        if not options:
            if restore_visibility:
                _restore_visibility(visibility_snapshot)
            return {
                "unsupported": True,
                "error": "Fusion did not expose a compatible 3MF export API.",
                "details": method_or_error,
                "targetBodies": [_body_export_summary(body) for body in resolution["bodies"]],
                "plan": plan,
                "preflight": preflight_result,
            }
        try:
            exportMgr.execute(options)
        except Exception as exc:
            restored = _restore_visibility(visibility_snapshot) if restore_visibility else []
            return {
                "error": "Fusion 3MF export failed during export manager execution.",
                "details": str(exc),
                "method": method_or_error,
                "targetBodies": [_body_export_summary(body) for body in resolution["bodies"]],
                "visibilityRestored": bool(restore_visibility),
                "restoredVisibilityCount": len(restored),
                "plan": plan,
                "preflight": preflight_result,
            }
        else:
            restored = _restore_visibility(visibility_snapshot) if restore_visibility else []
        exists = os.path.isfile(export_path)
        size_bytes = os.path.getsize(export_path) if exists else 0
        if not exists or size_bytes <= 0:
            return {
                "error": "Fusion 3MF export did not create a non-empty file.",
                "exportPath": export_path,
                "exists": exists,
                "sizeBytes": size_bytes,
                "targetBodies": [_body_export_summary(body) for body in resolution["bodies"]],
                "visibilityRestored": bool(restore_visibility),
                "restoredVisibilityCount": len(restored),
                "plan": plan,
                "preflight": preflight_result,
            }
        archive_validation = _inspect_3mf_archive(export_path, expected_body_count=len(resolution["bodies"]))
        after = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        return {
            "result": {
                "exported": True,
                "format": format,
                "exportPath": export_path,
                "exists": exists,
                "sizeBytes": size_bytes,
                "method": method_or_error,
                "targetBodies": [_body_export_summary(body) for body in resolution["bodies"]],
                "targetResolution": {
                    "requestedBodyNames": resolution["requestedBodyNames"],
                    "requestedBodyEntityTokens": resolution["requestedBodyEntityTokens"],
                    "requestedSelectionSetNames": resolution["requestedSelectionSetNames"],
                    "selectionSets": resolution["selectionSets"],
                },
                "visibilityRestored": bool(restore_visibility),
                "restoredVisibilityCount": len(restored),
                "allowedUnhealthyExport": bool(allow_unhealthy_export),
                "overrideReason": override_reason if allow_unhealthy_export else None,
                "plan": plan,
                "preflight": preflight_result,
                "archiveValidation": archive_validation,
                "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
            }
        }
    else:
        return {"error": f"Unsupported format: {format}"}
    exportMgr.execute(options)
    after = _safe_value(lambda: _design_state_snapshot(include_selections=False))
    return {
        "result": {
            "exported": True,
            "format": format,
            "exportPath": export_path,
            "allowedUnhealthyExport": bool(allow_unhealthy_export),
            "overrideReason": override_reason if allow_unhealthy_export else None,
            "preflight": preflight_result,
            "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
        }
    }


def _create_document_archive_export_options(export_manager, export_path, design):
    creators = (
        ("createFusionArchiveExportOptions", (export_path, design)),
        ("createFusionArchiveExportOptions", (export_path,)),
        ("createArchiveExportOptions", (export_path, design)),
        ("createArchiveExportOptions", (export_path,)),
    )
    errors = []
    for method_name, args in creators:
        method = _safe_value(lambda method_name=method_name: getattr(export_manager, method_name))
        if not callable(method):
            continue
        try:
            return method(*args), method_name
        except TypeError as exc:
            errors.append(f"{method_name}{len(args)}: {exc}")
            continue
    return None, "; ".join(errors) if errors else "Fusion runtime did not expose a compatible Fusion archive export options builder."


@register_tool("export_document_copy")
def export_document_copy(document_name=None, target_path=None, reason=None, requires_user_approval=False):
    """
    Export the active document as a local Fusion archive copy after planning.

    This does not save, upload, version, open, activate, promote, or relink
    cloud data. It only writes a local archive file through Fusion exportManager.
    """
    try:
        preflight = plan_document_management_action(
            action="export_copy",
            document_name=document_name,
            target_path=target_path,
            dry_run=True,
            reason=reason,
            requires_user_approval=requires_user_approval,
        )
        if "error" in preflight:
            return {"error": "Document export-copy preflight failed.", "preflight": preflight}
        preflight_result = preflight.get("result") or {}
        if not preflight_result.get("okToProceed"):
            return {"error": "Document export-copy preflight failed.", "preflight": preflight_result}

        plan = preflight_result.get("actionPlan") or {}
        export_path = plan.get("targetPath")
        if not export_path:
            return {"error": "Document export-copy preflight did not return targetPath.", "preflight": preflight_result}
        if os.path.splitext(str(export_path))[1].lower() not in {".f3d", ".f3z"}:
            return {
                "error": "export_document_copy only supports Fusion archive paths ending in .f3d or .f3z.",
                "preflight": preflight_result,
            }

        app = adsk.core.Application.get()
        active_doc = _safe_value(lambda: app.activeDocument)
        active_name = _safe_value(lambda: active_doc.name)
        if document_name and active_name and document_name != active_name:
            return {
                "error": "export_document_copy only exports the active document; it will not activate another open document.",
                "activeDocument": active_name,
                "requestedDocument": document_name,
                "preflight": preflight_result,
            }

        design = get_active_design()
        export_manager = _safe_value(lambda: design.exportManager)
        if not export_manager:
            return {
                "unsupported": True,
                "error": "Fusion did not expose design.exportManager for document export-copy.",
                "preflight": preflight_result,
            }
        options, method_or_error = _create_document_archive_export_options(export_manager, export_path, design)
        if not options:
            return {
                "unsupported": True,
                "error": "Fusion did not expose a compatible Fusion archive export-copy API.",
                "details": method_or_error,
                "preflight": preflight_result,
            }

        before = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        export_dir = os.path.dirname(export_path)
        if export_dir:
            os.makedirs(export_dir, exist_ok=True)
        export_manager.execute(options)
        exists = os.path.isfile(export_path)
        size_bytes = os.path.getsize(export_path) if exists else 0
        if not exists or size_bytes <= 0:
            return {
                "error": "Fusion export-copy did not create a non-empty archive file.",
                "targetPath": export_path,
                "exists": exists,
                "sizeBytes": size_bytes,
                "preflight": preflight_result,
            }
        after = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        return {
            "result": {
                "exported": True,
                "action": "export_copy",
                "method": method_or_error,
                "targetPath": export_path,
                "exists": exists,
                "sizeBytes": size_bytes,
                "documentName": active_name,
                "preflight": preflight_result,
                "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
                "notes": [
                    "This tool exported a local Fusion archive copy only.",
                    "It did not save, upload, version, open, activate, promote, or relink cloud data.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error exporting document copy: {e}\n{err}")
        return {"error": f"Failed to export document copy: {str(e)}"}


def _active_flat_pattern():
    design = get_active_design()
    flat_pattern = _safe_value(lambda: design.flatPattern) or _safe_value(lambda: design.rootComponent.flatPattern)
    if flat_pattern:
        return flat_pattern
    for body in _collection_items(_safe_value(lambda: design.rootComponent.bRepBodies)):
        flat_pattern = _safe_value(lambda body=body: body.flatPattern)
        if flat_pattern:
            return flat_pattern
    for occ in _collection_items(_safe_value(lambda: design.rootComponent.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            flat_pattern = _safe_value(lambda body=body: body.flatPattern)
            if flat_pattern:
                return flat_pattern
    return None


def _export_flat_pattern_entity(flat_pattern, export_path, format_name):
    export_manager = _safe_value(lambda: flat_pattern.exportManager)
    if export_manager:
        creator_names = {
            "dxf": ("createDXFExportOptions", "createDxfExportOptions"),
            "dwg": ("createDWGExportOptions", "createDwgExportOptions"),
            "step": ("createSTEPExportOptions", "createStepExportOptions"),
        }.get(format_name, ())
        for creator_name in creator_names:
            creator = getattr(export_manager, creator_name, None)
            if callable(creator):
                try:
                    options = creator(export_path)
                except TypeError:
                    options = creator(flat_pattern, export_path)
                execute = getattr(export_manager, "execute", None)
                if callable(execute):
                    return bool(execute(options)), f"flatPattern.exportManager.{creator_name}"
    for method_name in ("saveAs", "export", "exportToFile"):
        method = getattr(flat_pattern, method_name, None)
        if callable(method):
            try:
                result = method(export_path)
            except TypeError:
                result = method(export_path, format_name)
            return bool(True if result is None else result), f"flatPattern.{method_name}"
    return None, None


@register_tool("export_flat_pattern")
def export_flat_pattern(export_path, format="dxf", allow_blocked_export=False, override_reason=None):
    if not isinstance(export_path, str) or not export_path:
        return {"error": "Export path must be a non-empty string."}
    if "\x00" in export_path:
        return {"error": "Export path contains an invalid null byte."}
    if not os.path.isabs(export_path):
        return {"error": "Export path must be absolute."}
    format_name = (format or "dxf").lower()
    if format_name not in ("dxf", "dwg", "step"):
        return {"error": "Flat pattern format must be one of dxf, dwg, or step."}

    preflight = preflight_flat_pattern()
    if "error" in preflight:
        return preflight
    preflight_result = preflight.get("result") or {}
    if not preflight_result.get("okToProceed") and not allow_blocked_export:
        return {
            "error": "Flat-pattern export blocked by preflight checks. Fix blockers or explicitly set allow_blocked_export=true with override_reason.",
            "preflight": preflight_result,
        }
    if not preflight_result.get("okToProceed") and (not isinstance(override_reason, str) or not override_reason.strip()):
        return {
            "error": "override_reason is required when exporting a flat pattern despite preflight blockers.",
            "preflight": preflight_result,
        }

    flat_pattern = _active_flat_pattern()
    if not flat_pattern:
        return {
            "error": "Fusion did not expose a flatPattern object to export.",
            "unsupported": True,
            "preflight": preflight_result,
        }
    export_dir = os.path.dirname(export_path)
    if export_dir and not os.path.exists(export_dir):
        os.makedirs(export_dir, exist_ok=True)
    exported, method = _export_flat_pattern_entity(flat_pattern, export_path, format_name)
    if exported is None:
        return {
            "error": "Fusion flatPattern object did not expose a supported export method.",
            "unsupported": True,
            "preflight": preflight_result,
        }
    if not exported:
        return {"error": f"Fusion failed to export flat pattern to '{export_path}'.", "preflight": preflight_result}
    return {
        "result": {
            "exported": True,
            "format": format_name,
            "exportPath": export_path,
            "method": method,
            "allowedBlockedExport": bool(allow_blocked_export),
            "overrideReason": override_reason if allow_blocked_export else None,
            "preflight": preflight_result,
        }
    }

@register_tool("get_fusion_api_help")
def get_fusion_api_help(topic=None):
    try:
        help_dict = _load_help_context()
        if topic and topic in help_dict:
            return json.dumps({topic: help_dict[topic]}, indent=2)
        return json.dumps(help_dict, indent=2)
    except Exception as e:
        return f"Failed to load help: {e}"

@register_tool("set_camera")
def set_camera(orientation):
    app = adsk.core.Application.get()
    viewport = app.activeViewport
    cam = viewport.camera
    mapping = {
        "top": adsk.core.ViewOrientations.TopViewOrientation,
        "bottom": adsk.core.ViewOrientations.BottomViewOrientation,
        "left": adsk.core.ViewOrientations.LeftViewOrientation,
        "right": adsk.core.ViewOrientations.RightViewOrientation,
        "front": adsk.core.ViewOrientations.FrontViewOrientation,
        "back": adsk.core.ViewOrientations.BackViewOrientation,
        "iso": adsk.core.ViewOrientations.IsoTopRightViewOrientation
    }
    if orientation in mapping:
        cam.viewOrientation = mapping[orientation]
        viewport.camera = cam
        viewport.fit()
        return {"result": f"Camera set to {orientation} and fit."}
    return {"error": f"Invalid orientation {orientation}"}

@register_tool("prompt_user")
def prompt_user(message):
    if not isinstance(message, str) or not message:
        return {"error": "Message must be a non-empty string."}
    if len(message) > 2000:
        return {"error": "Message is too long."}
    app = adsk.core.Application.get()
    ui = app.userInterface
    ui.messageBox(message, "Fusion MCP AI Agent")
    return {"result": "Message shown to user."}

@register_tool("undo_last_action")
def undo_last_action(allow_risky=False, reason=None):
    try:
        if allow_risky and not reason:
            return {"error": "reason is required when allow_risky=true."}
        app = adsk.core.Application.get()
        before = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        app.executeTextCommand(u'NuIUndo')
        after = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        comparison = compare_design_state(before, after).get("result") if before and after else None
        guard_reasons = _undo_guard_reasons(before, after, comparison)
        if guard_reasons and not allow_risky:
            redo_error = None
            try:
                app.executeTextCommand(u'NuIRedo')
            except Exception as redo_exc:
                redo_error = str(redo_exc)
            restored = _safe_value(lambda: _design_state_snapshot(include_selections=False))
            return {
                "error": "Undo was automatically redone because guardrails detected risky model state changes.",
                "guardReasons": guard_reasons,
                "redoAttempted": True,
                "redoError": redo_error,
                "stateComparison": comparison,
                "restoredStateComparison": compare_design_state(before, restored).get("result") if before and restored else None,
            }
        return {
            "result": {
                "message": "Undid last action",
                "guardReasons": guard_reasons,
                "allowRisky": bool(allow_risky),
                "reason": reason,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        return {"error": f"Failed to undo: {e}"}


def _undo_guard_reasons(before, after, comparison):
    reasons = []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return ["Unable to capture before/after design state for guarded undo."]
    before_design = before.get("design") or {}
    after_design = after.get("design") or {}
    if before_design.get("designType") != after_design.get("designType"):
        reasons.append("Undo changed the design type.")

    before_counts = before.get("counts") or {}
    after_counts = after.get("counts") or {}
    before_unhealthy = before_counts.get("unhealthyTimelineItems") or 0
    after_unhealthy = after_counts.get("unhealthyTimelineItems") or 0
    if after_unhealthy > before_unhealthy:
        reasons.append("Undo increased unhealthy timeline items.")

    for key in ("components", "bodies", "sketches"):
        before_count = before_counts.get(key)
        after_count = after_counts.get(key)
        if isinstance(before_count, int) and isinstance(after_count, int) and after_count < before_count:
            reasons.append(f"Undo removed {before_count - after_count} {key}.")

    if isinstance(comparison, dict):
        diff = comparison.get("diff") or {}
        removed = diff.get("removed") or {}
        for key in ("components", "bodies", "sketches"):
            removed_items = removed.get(key) if isinstance(removed, dict) else None
            if removed_items:
                reasons.append(f"Undo removed named {key}: {', '.join(str(item) for item in removed_items[:5])}.")
    return reasons

@register_tool("list_documents")
def list_documents():
    try:
        app = adsk.core.Application.get()
        docs = app.documents
        doc_list = []
        for i in range(docs.count):
            doc = docs.item(i)
            doc_list.append({
                "index": i,
                "name": doc.name,
                "isModified": doc.isModified,
                "isActive": doc == app.activeDocument
            })
        return {"result": {"documents": doc_list}}
    except Exception as e:
        return {"error": f"Failed to list documents: {e}"}

@register_tool("set_active_document")
def set_active_document(name=None, index=None):
    try:
        app = adsk.core.Application.get()
        docs = app.documents
        target_doc = None
        
        if index is not None:
            try:
                idx = int(index)
                if 0 <= idx < docs.count:
                    target_doc = docs.item(idx)
            except ValueError:
                pass
                
        if not target_doc and name:
            for i in range(docs.count):
                doc = docs.item(i)
                if doc.name == name:
                    target_doc = doc
                    break
                    
        if not target_doc:
            return {"error": f"Document not found (name='{name}', index={index})"}
            
        target_doc.activate()
        return {"result": f"Activated document '{target_doc.name}'"}
    except Exception as e:
        return {"error": f"Failed to activate document: {e}"}


@register_tool("create_design_document")
def create_design_document(document_name=None, requires_user_approval=False, reason=None):
    """
    Create a new unsaved Fusion design document with explicit approval.

    This replaces common raw-script fixture setup paths while staying narrow:
    it creates one Fusion design document, optionally names it, and does not
    save, upload, version, activate an existing document, or create geometry.
    """
    try:
        preflight = plan_document_management_action(
            action="new_design",
            document_name=document_name,
            dry_run=True,
            reason=reason,
            requires_user_approval=requires_user_approval,
        )
        if "error" in preflight:
            return {"error": "Design-document creation preflight failed.", "preflight": preflight}
        preflight_result = preflight.get("result") or {}
        if not preflight_result.get("okToProceed"):
            return {"error": "Design-document creation preflight failed.", "preflight": preflight_result}

        app = adsk.core.Application.get()
        docs = app.documents
        document_types = _safe_value(lambda: adsk.core.DocumentTypes)
        fusion_type = (
            _safe_value(lambda: document_types.FusionDesignDocumentType)
            or _safe_value(lambda: document_types.FusionDesignDocument)
        )
        if fusion_type is None:
            return {
                "unsupported": True,
                "error": "Fusion runtime did not expose DocumentTypes.FusionDesignDocumentType.",
                "preflight": preflight_result,
            }
        doc = docs.add(fusion_type)
        if document_name:
            _safe_value(lambda: setattr(doc, "name", str(document_name)))
        _safe_value(lambda: doc.activate())
        return {
            "result": {
                "created": True,
                "action": "new_design",
                "documentName": _safe_value(lambda: doc.name),
                "isModified": _safe_value(lambda: doc.isModified),
                "preflight": preflight_result,
                "notes": [
                    "This tool created a new unsaved Fusion design document only.",
                    "It did not save, upload, version, open a data file, promote, or relink cloud data.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to create design document: {e}"}


@register_tool("close_active_document")
def close_active_document(document_name=None, save_changes=False, requires_user_approval=False, reason=None):
    """
    Close the active Fusion document with explicit save/discard intent.

    This is intentionally narrow: it never activates another document, never
    saves under a new name, and always routes through document-management
    planning before calling Fusion's close API.
    """
    try:
        preflight = plan_document_management_action(
            action="close",
            document_name=document_name,
            dry_run=True,
            reason=reason,
            requires_user_approval=requires_user_approval,
        )
        if "error" in preflight:
            return {"error": "Document close preflight failed.", "preflight": preflight}
        preflight_result = preflight.get("result") or {}
        if not preflight_result.get("okToProceed"):
            return {"error": "Document close preflight failed.", "preflight": preflight_result}

        app = adsk.core.Application.get()
        doc = app.activeDocument
        if not doc:
            return {"error": "No active Fusion document is open.", "preflight": preflight_result}
        active_name = _safe_value(lambda: doc.name)
        if document_name and active_name and document_name != active_name:
            return {
                "error": "close_active_document only closes the active document; it will not activate another open document.",
                "activeDocument": active_name,
                "requestedDocument": document_name,
                "preflight": preflight_result,
            }
        was_modified = _safe_value(lambda: doc.isModified)
        close_result = doc.close(bool(save_changes))
        return {
            "result": {
                "closed": bool(True if close_result is None else close_result),
                "action": "close",
                "documentName": active_name,
                "saveChanges": bool(save_changes),
                "wasModifiedBeforeClose": was_modified,
                "preflight": preflight_result,
                "notes": [
                    "This tool only closed the active document.",
                    "It did not activate another document, save as a new file, upload, version, promote, or relink cloud data.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to close active document: {e}"}


@register_tool("revert_active_document")
def revert_active_document(save_changes=False):
    try:
        app = adsk.core.Application.get()
        doc = app.activeDocument
        if not doc:
            return {"error": "No active Fusion document is open."}
        data_file = doc.dataFile
        if not data_file:
            return {"error": "The active document must be saved to Fusion before it can be reopened from the data panel."}

        name = doc.name
        was_modified = doc.isModified
        doc.close(bool(save_changes))
        reopened = app.documents.open(data_file)
        if not reopened:
            return {"error": f"Closed '{name}' but Fusion did not reopen it from the saved data file."}
        reopened.activate()
        return {
            "result": {
                "documentName": reopened.name,
                "saveChanges": bool(save_changes),
                "wasModifiedBeforeClose": was_modified,
                "message": f"Reopened '{reopened.name}' from its saved Fusion data file."
            }
        }
    except Exception as e:
        return {"error": f"Failed to revert active document: {e}"}

@register_tool("get_best_practices")
def get_best_practices():
    try:
        workspace_dir = os.path.dirname(os.path.dirname(__file__))
        text_file = os.path.join(workspace_dir, "best_practices.md")
        
        if not os.path.exists(text_file):
            return {"error": f"Best practices file not found at {text_file}"}
            
        with open(text_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        text = "🎯 **FUSION 360 DESIGN BEST PRACTICES**\n\n"
        text += f"📄 **Length**: {len(content.splitlines())} lines\n\n"
        text += "---\n\n"
        text += content
        
        return {"result": text}
    except Exception as e:
        return {"error": f"Failed to load best practices: {e}"}


@register_tool("list_appearances")
def list_appearances(query=None, include_libraries=True, limit=50):
    try:
        app = adsk.core.Application.get()
        design = get_active_design()
        query_text = str(query).strip().lower() if query is not None else ""
        try:
            max_results = int(limit)
        except Exception:
            max_results = 50
        max_results = max(1, min(max_results, 500))

        results = []
        seen = set()

        def add_appearance(appearance, source, library_name=None):
            if len(results) >= max_results or not appearance:
                return
            name = _safe_value(lambda: appearance.name)
            if not name:
                return
            if query_text and query_text not in name.lower():
                return
            key = (source, library_name, name)
            if key in seen:
                return
            seen.add(key)
            item = _entity_ref(appearance)
            item.update({
                "source": source,
                "libraryName": library_name,
            })
            results.append(item)

        for appearance in _collection_items(_safe_value(lambda: design.appearances)):
            add_appearance(appearance, "design")

        library_count = 0
        if include_libraries:
            for library in _collection_items(_safe_value(lambda: app.materialLibraries)):
                library_count += 1
                library_name = _safe_value(lambda library=library: library.name)
                for appearance in _collection_items(_safe_value(lambda library=library: library.appearances)):
                    add_appearance(appearance, "library", library_name)
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break

        return {
            "result": {
                "query": query,
                "includeLibraries": bool(include_libraries),
                "limit": max_results,
                "count": len(results),
                "libraryCountScanned": library_count,
                "appearances": results,
            }
        }
    except Exception as e:
        return {"error": f"Failed to list appearances: {e}"}


@register_tool("inspect_body_style")
def inspect_body_style(body_name=None, body_entity_tokens=None, include_all_bodies=False):
    try:
        design = get_active_design()
        root = design.rootComponent
        requested_name = str(body_name).strip() if body_name is not None else ""
        requested_tokens = set(_normalize_string_list(body_entity_tokens))
        include_all = bool(include_all_bodies)
        if not requested_name and not requested_tokens and not include_all:
            return {"error": "body_name or body_entity_tokens is required unless include_all_bodies is true."}

        body_reports = []
        matched_tokens = set()
        for component in _all_components(root):
            for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
                name = _safe_value(lambda body=body: body.name)
                token = _safe_value(lambda body=body: body.entityToken)
                name_matches = requested_name and name == requested_name
                token_matches = token in requested_tokens if token else False
                if not include_all and not name_matches and not token_matches:
                    continue
                if token_matches:
                    matched_tokens.add(token)
                body_reports.append(_body_style_summary(body, component))

        if requested_name and not body_reports:
            return {"error": f"Body '{requested_name}' not found."}
        missing_tokens = sorted(requested_tokens - matched_tokens)
        if missing_tokens and not body_reports:
            return {"error": f"Body entity token(s) not found: {', '.join(missing_tokens)}."}

        return {
            "result": {
                "bodyName": requested_name or None,
                "bodyEntityTokens": sorted(requested_tokens),
                "missingBodyEntityTokens": missing_tokens,
                "includeAllBodies": include_all,
                "count": len(body_reports),
                "bodies": body_reports,
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect body style: {e}"}


@register_tool("apply_appearance")
def apply_appearance(appearance_name, body_name=None, body_names=None, body_entity_tokens=None, expected_body_count=None):
    try:
        app = adsk.core.Application.get()
        design = get_active_design()
        body_targets = []
        if body_name is not None:
            body_targets.extend(_normalize_string_list(body_name))
        body_targets.extend(_normalize_string_list(body_names))
        token_targets = _normalize_string_list(body_entity_tokens)
        if not body_targets and not token_targets:
            return {"error": "body_name, body_names, or body_entity_tokens is required."}

        resolution = _resolve_export_bodies(
            design,
            body_names=body_targets,
            body_entity_tokens=token_targets,
            selection_set_names=None,
        )
        blockers = []
        if resolution["missingBodies"]:
            blockers.append(f"Missing body target(s): {', '.join(resolution['missingBodies'])}.")
        if resolution["missingBodyEntityTokens"]:
            blockers.append(f"Missing body entity token target(s): {', '.join(resolution['missingBodyEntityTokens'])}.")
        if resolution["ambiguousBodies"]:
            blockers.append("Ambiguous body target(s): " + ", ".join(f"{item['name']} ({item['count']} matches)" for item in resolution["ambiguousBodies"]) + ".")
        if resolution["ambiguousBodyEntityTokens"]:
            blockers.append("Ambiguous body entity token target(s): " + ", ".join(f"{item['entityToken']} ({item['count']} matches)" for item in resolution["ambiguousBodyEntityTokens"]) + ".")
        if not resolution["bodies"]:
            blockers.append("No BRep bodies were resolved for appearance application.")
        if expected_body_count is not None:
            try:
                expected = int(expected_body_count)
                if expected != len(resolution["bodies"]):
                    blockers.append(f"Resolved {len(resolution['bodies'])} target bodies, expected {expected}.")
            except (TypeError, ValueError):
                blockers.append("expected_body_count must be an integer when provided.")
        if blockers:
            return {
                "error": "Appearance target resolution failed.",
                "blockingReasons": blockers,
                "targetResolution": {
                    "requestedBodyNames": resolution["requestedBodyNames"],
                    "requestedBodyEntityTokens": resolution["requestedBodyEntityTokens"],
                },
            }

        appearance, appearance_error = _find_appearance(app, design, appearance_name)
        if not appearance:
            return {"error": appearance_error or f"Appearance '{appearance_name}' not found locally or in libraries."}

        before = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        before_styles = [_body_style_summary(body) for body in resolution["bodies"]]
        for body in resolution["bodies"]:
            body.appearance = appearance
        after = _safe_value(lambda: _design_state_snapshot(include_selections=False))
        after_styles = [_body_style_summary(body) for body in resolution["bodies"]]
        return {
            "result": {
                "applied": True,
                "appearance": _entity_ref(appearance),
                "targetBodies": after_styles,
                "beforeStyles": before_styles,
                "targetResolution": {
                    "requestedBodyNames": resolution["requestedBodyNames"],
                    "requestedBodyEntityTokens": resolution["requestedBodyEntityTokens"],
                },
                "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error applying appearance: {e}\n{err}")
        return {"error": f"Failed to apply appearance: {str(e)}"}

@register_tool("get_mcp_workflow_guide")
def get_mcp_workflow_guide():
    try:
        workspace_dir = os.path.dirname(os.path.dirname(__file__))
        text_file = os.path.join(workspace_dir, "workflow_guide.md")
        
        if not os.path.exists(text_file):
            return {"error": f"Workflow guide file not found at {text_file}"}
            
        with open(text_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        return {"result": content}
    except Exception as e:
        return {"error": f"Failed to load workflow guide: {e}"}

@register_tool("search_fusion_api_documentation")
def search_fusion_api_documentation(class_name):
    clean_name = "".join(c for c in class_name if c.isalnum()).lower()
    url = _fusion_docs_url(clean_name)
    summary = _common_api_topics().get(clean_name, "Class not in common offline index.")
    
    text = f"📖 **Autodesk Fusion 360 API Reference**\n\n"
    text += f"**Class**: `{class_name}`\n"
    text += f"**Description**: {summary}\n"
    text += f"**Official Documentation Link**: [{class_name} API Page]({url})\n\n"
    text += f"💡 *Instructions for AI Agent*: Use your browser_subagent or read_url_content tool to load the official link above for a complete reference of all properties, methods, and code examples for the `{class_name}` class."
    
    return {"result": text}

@register_tool("git_status")
def git_status():
    import subprocess
    try:
        workspace_dir = os.path.dirname(os.path.dirname(__file__))
        res = subprocess.run(
            ["git", "status", "--short"],
            cwd=workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        return {"result": f"STDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"}
    except subprocess.TimeoutExpired:
        return {"error": "Git status timed out."}
    except Exception as e:
        return {"error": f"Git command failed: {e}"}

@register_tool("create_2d_drawing")
def create_2d_drawing(export_pdf_path, allow_unhealthy_model=False, require_compute=True, override_reason=None):
    doc = None
    drawing_doc = None
    try:
        if not isinstance(export_pdf_path, str) or not export_pdf_path:
            return {"error": "Export PDF path must be a non-empty string."}
        if "\x00" in export_pdf_path:
            return {"error": "Export PDF path contains an invalid null byte."}
        if not os.path.isabs(export_pdf_path):
            return {"error": "Export PDF path must be absolute."}

        app = adsk.core.Application.get()
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            return {"error": "No active design found."}
        source_doc = app.activeDocument
        if not source_doc or not source_doc.dataFile:
            return {"error": "The active design must be saved to Fusion before a drawing can be created."}

        preflight = preflight_model_change(change_type="create_2d_drawing", require_compute=require_compute)
        if "error" in preflight:
            return preflight
        preflight_result = preflight.get("result", {})
        if not preflight_result.get("okToProceed", False):
            if not allow_unhealthy_model:
                return {
                    "error": (
                        "Drawing export blocked by preflight checks. Fix compute/timeline health issues "
                        "or explicitly set allow_unhealthy_model=true with override_reason."
                    ),
                    "preflight": preflight_result,
                }
            if not isinstance(override_reason, str) or not override_reason.strip():
                return {
                    "error": "override_reason is required when creating a drawing despite failed model preflight checks.",
                    "preflight": preflight_result,
                }
            
        export_dir = os.path.dirname(export_pdf_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)

        try:
            import importlib
            adsk_drawing = importlib.import_module("adsk.drawing")
            drawing_mgr = adsk_drawing.DrawingManager.get()
            if not drawing_mgr:
                return {"error": "Fusion DrawingManager is not available."}

            create_input = drawing_mgr.createDrawingInput(
                source_doc.dataFile,
                adsk_drawing.DrawingCreationModes.AutomaticDrawingCreationMode
            )
            if not create_input:
                return {"error": "Failed to create drawing input."}
            create_input.standard = adsk_drawing.DrawingStandardTypes.ASMEDrawingStandardType
            create_input.units = adsk_drawing.DrawingUnitTypes.MillimeterDrawingUnitType
            create_input.asmeSheetSize = adsk_drawing.ASMESheetSizes.BASMESheetSize
            create_input.orientationType = adsk_drawing.SheetOrientationTypes.LandscapeSheetOrientationType
            create_input.sheetCreationType = adsk_drawing.SheetCreationTypes.FirstLevelOnlySheetCreationType

            prefs = create_input.automationPreferences
            if prefs:
                try:
                    prefs.componentSheetViewPreferences.isOrthogonalViewAdded = True
                    prefs.componentSheetViewPreferences.isIsometricViewAdded = True
                    prefs.assemblySheetPreferences.isSheetCreated = True
                    prefs.assemblySheetPreferences.isPartsListIncluded = False
                    prefs.drawingViewPreferences.style = adsk_drawing.DrawingViewStyleTypes.VisibleEdgesDrawingViewStyleType
                except Exception:
                    pass

            drawing_data_file = drawing_mgr.createDrawing(create_input)
            if not drawing_data_file:
                return {"error": "Fusion failed to create a drawing from the active design."}

            doc = app.documents.open(drawing_data_file)
            drawing_doc = adsk_drawing.DrawingDocument.cast(doc)
            if not drawing_doc:
                return {"error": "Created document was not a drawing document."}

            drawing = drawing_doc.drawing
            export_mgr = drawing.exportManager
            pdf_options = export_mgr.createPDFExportOptions(export_pdf_path)
            pdf_options.openPDF = False
            if not export_mgr.execute(pdf_options):
                return {"error": f"Fusion failed to export drawing PDF to '{export_pdf_path}'."}
        except Exception as drawing_error:
            return {"error": f"Failed to create or export drawing PDF: {drawing_error}"}

        if not os.path.exists(export_pdf_path):
            return {"error": f"Drawing export completed but PDF was not found at '{export_pdf_path}'."}
            
        return {
            "result": {
                "created": True,
                "exportPath": export_pdf_path,
                "allowedUnhealthyModel": bool(allow_unhealthy_model),
                "overrideReason": override_reason if allow_unhealthy_model else None,
                "preflight": preflight_result,
                "message": f"Successfully created 2D drawing sheet and saved PDF to '{export_pdf_path}'",
            }
        }
    except Exception as e:
        return {"error": f"Failed to create 2D drawing sheet: {str(e)}"}
    finally:
        if doc:
            try:
                doc.close(False)
            except Exception:
                pass


def _active_drawing_context(sheet_name=None, sheet_index=0):
    try:
        import importlib
        adsk_drawing = importlib.import_module("adsk.drawing")
    except Exception as exc:
        return None, None, None, None, f"Fusion Drawing API is not available: {exc}"
    app = adsk.core.Application.get()
    drawing_doc = _safe_value(lambda: adsk_drawing.DrawingDocument.cast(app.activeDocument))
    if not drawing_doc:
        return adsk_drawing, None, None, None, "The active document is not an open Fusion drawing document."
    drawing = _safe_value(lambda: drawing_doc.drawing)
    sheets = _collection_items(_safe_value(lambda: drawing.sheets))
    if not sheets:
        return adsk_drawing, drawing_doc, drawing, None, "The active drawing document does not expose any sheets."
    target = None
    if sheet_name:
        for sheet in sheets:
            if _safe_value(lambda sheet=sheet: sheet.name) == sheet_name:
                target = sheet
                break
    else:
        try:
            idx = int(sheet_index or 0)
        except Exception:
            idx = 0
        if 0 <= idx < len(sheets):
            target = sheets[idx]
    if not target:
        return adsk_drawing, drawing_doc, drawing, None, "Requested drawing sheet was not found."
    return adsk_drawing, drawing_doc, drawing, target, None


def _drawing_collection_add(collection, payload):
    if not collection or not hasattr(collection, "add"):
        return None, "Drawing collection did not expose add()."
    if hasattr(collection, "createInput"):
        variants = [(payload,), tuple()]
        last_error = None
        for args in variants:
            try:
                input_obj = collection.createInput(*args)
                if input_obj is not None:
                    for key, value in payload.items():
                        if hasattr(input_obj, key):
                            setattr(input_obj, key, value)
                    return collection.add(input_obj), None
            except TypeError as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)
                break
        if last_error:
            return None, f"Drawing collection createInput failed: {last_error}"
    variants = [(payload,), tuple(payload.values()), tuple()]
    last_error = None
    for args in variants:
        try:
            return collection.add(*args), None
        except TypeError as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
            break
    return None, f"Drawing collection did not accept a compatible add() signature: {last_error}"


def _run_drawing_collection_tool(operation, collection_attr, payload, sheet_name=None, sheet_index=0, reason=None):
    if not isinstance(reason, str) or not reason.strip():
        return {"error": f"reason is required before {operation}. State why this drawing change is intentional."}
    adsk_drawing, drawing_doc, drawing, sheet, context_error = _active_drawing_context(sheet_name=sheet_name, sheet_index=sheet_index)
    if context_error:
        return {
            "error": context_error,
            "unsupported": "Drawing API is not available" in context_error or "not an open Fusion drawing" in context_error,
        }
    collection = _safe_value(lambda: getattr(sheet, collection_attr))
    if not collection:
        return {
            "error": f"Active drawing sheet did not expose {collection_attr}.",
            "unsupported": True,
            "operation": operation,
        }
    full_payload = {
        "operation": operation,
        "sheet": sheet,
        "drawing": drawing,
        "drawingDocument": drawing_doc,
        **dict(payload or {}),
    }
    before = _design_state_snapshot(include_selections=False)
    created, add_error = _drawing_collection_add(collection, full_payload)
    if add_error:
        return {
            "error": add_error,
            "unsupported": True,
            "operation": operation,
        }
    after = _design_state_snapshot(include_selections=False)
    return {
        "result": {
            "message": f"Executed {operation} on drawing sheet.",
            "operation": operation,
            "sheetName": _safe_value(lambda: sheet.name),
            "createdName": _safe_value(lambda: created.name),
            "createdObjectType": _safe_value(lambda: created.objectType),
            "payload": {key: value for key, value in full_payload.items() if key not in {"sheet", "drawing", "drawingDocument"}},
            "reason": reason,
            "stateComparison": compare_design_state(before, after).get("result"),
            "warnings": [
                "Drawing API support varies by Fusion runtime. Inspect the drawing document after this operation.",
            ],
        }
    }


@register_tool("add_drawing_view")
def add_drawing_view(sheet_name=None, sheet_index=0, view=None, standard="ASME", sheet_size="A", sheet_orientation="landscape", units="mm", title_block=None, reason=None):
    plan = plan_drawing_views(
        standard=standard,
        sheet_size=sheet_size,
        sheet_orientation=sheet_orientation,
        units=units,
        views=view,
        title_block=title_block,
    )
    if "error" in plan:
        return plan
    plan_result = plan.get("result") or {}
    if not plan_result.get("okToProceed"):
        return {"error": "Drawing view creation preflight failed.", "preflight": plan_result}
    return _run_drawing_collection_tool(
        "add_drawing_view",
        "drawingViews",
        {"view": (plan_result.get("views") or [None])[0], "sheetPlan": plan_result.get("sheet")},
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        reason=reason,
    )


@register_tool("add_drawing_dimension")
def add_drawing_dimension(sheet_name=None, sheet_index=0, view_name=None, geometry_entity_tokens=None, dimension_type="linear", placement=None, text=None, reason=None):
    tokens = geometry_entity_tokens if isinstance(geometry_entity_tokens, list) else ([geometry_entity_tokens] if geometry_entity_tokens else [])
    if not tokens:
        return {"error": "geometry_entity_tokens are required for drawing dimensions."}
    return _run_drawing_collection_tool(
        "add_drawing_dimension",
        "dimensions",
        {
            "viewName": view_name,
            "geometryEntityTokens": tokens,
            "dimensionType": dimension_type,
            "placement": placement,
            "text": text,
        },
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        reason=reason,
    )


@register_tool("add_drawing_callout")
def add_drawing_callout(sheet_name=None, sheet_index=0, text=None, target_view_name=None, target_entity_token=None, placement=None, reason=None):
    if not isinstance(text, str) or not text.strip():
        return {"error": "text is required for drawing callouts."}
    return _run_drawing_collection_tool(
        "add_drawing_callout",
        "notes",
        {
            "text": text,
            "targetViewName": target_view_name,
            "targetEntityToken": target_entity_token,
            "placement": placement,
        },
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        reason=reason,
    )


@register_tool("add_parts_list")
def add_parts_list(sheet_name=None, sheet_index=0, source_view_name=None, placement=None, bom_level="first_level", reason=None):
    if not isinstance(source_view_name, str) or not source_view_name.strip():
        return {"error": "source_view_name is required for a parts list."}
    return _run_drawing_collection_tool(
        "add_parts_list",
        "partsLists",
        {
            "sourceViewName": source_view_name,
            "placement": placement,
            "bomLevel": bom_level,
        },
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        reason=reason,
    )


@register_tool("add_revision_table")
def add_revision_table(sheet_name=None, sheet_index=0, placement=None, initial_revision=None, reason=None):
    return _run_drawing_collection_tool(
        "add_revision_table",
        "revisionTables",
        {
            "placement": placement,
            "initialRevision": dict(initial_revision or {}),
        },
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        reason=reason,
    )
