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
from .inspection import get_active_design

class FusionScriptExecutionError(Exception):
    def __init__(self, message, stdout_text, traceback_text):
        super().__init__(message)
        self.stdout_text = stdout_text
        self.traceback_text = traceback_text

@register_tool("run_fusion_script")
def run_fusion_script(script):
    if not isinstance(script, str) or not script.strip():
        return {"error": "Script must be a non-empty string."}

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

@register_tool("export_asset")
def export_asset(format, export_path):
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
    return {"result": f"Exported {format} to {export_path}"}

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
            
        export_dir = os.path.dirname(export_pdf_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
            
        doc = app.documents.add(adsk.core.DocumentTypes.DrawingDocumentType)
        if not doc:
            return {"error": "Failed to create new drawing document."}
            
        try:
            import adsk.drawing
            drawing_doc = adsk.drawing.DrawingDocument.cast(doc)
            if not drawing_doc or drawing_doc.sheets.count <= 0:
                return {"error": "Drawing document did not contain any sheets to export."}
            sheet = drawing_doc.sheets.item(0)
            sheet.exportToPDF(export_pdf_path)
        except Exception as export_error:
            return {"error": f"Failed to export drawing PDF: {export_error}"}

        if not os.path.exists(export_pdf_path):
            return {"error": f"Drawing export completed but PDF was not found at '{export_pdf_path}'."}
            
        return {"result": f"Successfully created 2D drawing sheet and saved PDF to '{export_pdf_path}'"}
    except Exception as e:
        return {"error": f"Failed to create 2D drawing sheet: {str(e)}"}
