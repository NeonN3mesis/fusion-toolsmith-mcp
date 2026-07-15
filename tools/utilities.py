"""
Utility tools for script execution, viewport capture, export, camera controls, and undoing.
"""

import adsk.core, adsk.fusion
import json
import uuid
import os
import sys
import io
import traceback
from . import register_resource, register_tool
from .inspection import _collection_items, _design_state_snapshot, _health_to_string, _safe_value, compare_design_state, get_active_design, get_feature_dependencies

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
    "inspect_sketch",
    "inspect_feature",
    "get_body_faces",
    "offset_face_or_press_pull",
    "revolve_feature",
    "loft_feature",
    "sweep_feature",
    "get_sketch_parameters",
    "get_feature_parameters",
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
    "export_asset",
    "create_2d_drawing",
    "capture_view",
    "capture_demo_sequence",
    "create_offset_plane",
    "create_construction_point",
    "create_construction_axis",
    "create_rounded_rectangle_body",
    "create_rounded_slot_cut",
    "create_rounded_pocket",
    "create_hole_pattern",
    "create_counterbore_hole_pattern",
    "mirror_features_or_bodies",
    "pattern_feature",
    "set_visibility",
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
                "extract_reference_dimensions",
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
                "inspect_sketch",
                "inspect_feature",
                "get_body_faces",
                "assess_change_impact",
                "map_coordinates",
                "create_sketch",
                "draw_line",
                "draw_rectangle",
                "draw_circle",
                "project_geometry",
                "create_offset_plane",
                "create_construction_point",
                "create_construction_axis",
                "extrude_feature",
                "revolve_feature",
                "loft_feature",
                "sweep_feature",
                "fillet_feature",
                "chamfer_feature",
                "shell_body",
                "offset_face_or_press_pull",
                "combine_bodies",
                "create_rounded_rectangle_body",
                "create_rounded_slot_cut",
                "create_rounded_pocket",
                "create_hole_pattern",
                "create_counterbore_hole_pattern",
                "mirror_features_or_bodies",
                "pattern_feature",
                "set_visibility",
                "validate_model",
            ],
        },
        "export": {
            "firstTools": ["doctor", "inspect_design", "preflight_export"],
            "preferredTools": ["export_asset", "create_2d_drawing", "capture_view", "capture_demo_sequence"],
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
        "exportPolicy": "Raw Fusion export APIs are blocked by default; use export_asset or create_2d_drawing.",
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
        next_actions.append("Use export_asset for STEP/STL or create_2d_drawing for drawing PDFs only after preflight passes.")
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
    return {
        "result": "Script executed",
        "output": new_stdout.getvalue(),
        "scriptIntent": script_intent.strip(),
        "mcpToolGap": mcp_tool_gap.strip(),
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
def export_asset(format, export_path, allow_unhealthy_export=False, require_compute=True, override_reason=None):
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
    if format == "step":
        options = exportMgr.createSTEPExportOptions(export_path, design.rootComponent)
    elif format == "stl":
        options = exportMgr.createSTLExportOptions(design.rootComponent, export_path)
    else:
        return {"error": f"Unsupported format: {format}"}
    exportMgr.execute(options)
    return {
        "result": {
            "exported": True,
            "format": format,
            "exportPath": export_path,
            "allowedUnhealthyExport": bool(allow_unhealthy_export),
            "overrideReason": override_reason if allow_unhealthy_export else None,
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
def undo_last_action():
    try:
        app = adsk.core.Application.get()
        app.executeTextCommand(u'NuIUndo')
        return {"result": "Undid last action"}
    except Exception as e:
        return {"error": f"Failed to undo: {e}"}

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

@register_tool("apply_appearance")
def apply_appearance(body_name, appearance_name):
    try:
        app = adsk.core.Application.get()
        design = get_active_design()
        root = design.rootComponent
        
        # 1. Find the target body
        target_body = None
        for body in root.bRepBodies:
            if body.name == body_name:
                target_body = body
                break
                
        if not target_body:
            for occ in root.allOccurrences:
                for body in occ.bRepBodies:
                    if body.name == body_name:
                        target_body = body
                        break
                if target_body:
                    break
                    
        if not target_body:
            return {"error": f"Body '{body_name}' not found."}
            
        # 2. Check if local appearance exists
        appearance = design.appearances.itemByName(appearance_name)
        
        # 3. Search libraries if not local
        if not appearance:
            for lib in app.materialLibraries:
                try:
                    lib_appearance = lib.appearances.itemByName(appearance_name)
                    if lib_appearance:
                        appearance = design.appearances.addByCopy(lib_appearance)
                        break
                except Exception:
                    continue
                    
        if not appearance:
            for lib in app.materialLibraries:
                try:
                    for la in lib.appearances:
                        if appearance_name.lower() in la.name.lower():
                            appearance = design.appearances.addByCopy(la)
                            break
                    if appearance:
                        break
                except Exception:
                    continue
                    
        if not appearance:
            return {"error": f"Appearance '{appearance_name}' not found locally or in libraries."}
            
        # 4. Apply
        target_body.appearance = appearance
        return {"result": f"Successfully applied appearance '{appearance.name}' to body '{body_name}'"}
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
