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
from . import register_tool
from .inspection import _design_state_snapshot, _health_to_string, _safe_value, compare_design_state, get_active_design, get_feature_dependencies

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
    "exportmgr.execute",
    "exportmanager.execute",
)


def _script_looks_like_export(script):
    normalized = script.lower()
    return any(marker in normalized for marker in _SCRIPT_EXPORT_MARKERS)


@register_tool("run_fusion_script")
def run_fusion_script(script, allow_export=False, export_override_reason=None):
    if not isinstance(script, str) or not script.strip():
        return {"error": "Script must be a non-empty string."}
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
    return {"result": "Script executed", "output": new_stdout.getvalue()}

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
        help_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "help_context.json")
        with open(help_path, "r", encoding="utf-8") as f:
            help_dict = json.load(f)
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
    url = f"https://help.autodesk.com/view/fusion360/ENU/?contextId=adsk_fusion_api_{clean_name}"
    
    common_classes = {
        "extrudefeature": "Creates, modifies, or deletes an extrusion feature. Inherits from Feature.",
        "sketch": "Represents a sketch in a component. Contains sketch curves, points, dimensions, and constraints.",
        "brepbody": "Represents a solid or sheet body in a component.",
        "brepface": "Represents a face of a BRepBody.",
        "brepedge": "Represents an edge of a BRepBody.",
        "occurrence": "Represents a component instance in an assembly.",
        "constructionplane": "Represents a construction plane used as a sketch or feature reference.",
        "userparameter": "Represents a user-defined parameter with expressions and unit conversions."
    }
    
    summary = common_classes.get(clean_name, "Class not in common offline index.")
    
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
def create_2d_drawing(export_pdf_path):
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
            
        return {"result": f"Successfully created 2D drawing sheet and saved PDF to '{export_pdf_path}'"}
    except Exception as e:
        return {"error": f"Failed to create 2D drawing sheet: {str(e)}"}
    finally:
        if doc:
            try:
                doc.close(False)
            except Exception:
                pass
