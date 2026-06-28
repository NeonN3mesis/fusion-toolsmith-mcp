import adsk.core, adsk.fusion, traceback
import threading
import json
import uuid
import queue
import time
import os
import secrets
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

app = None
ui  = None
customEvent = "FusionMCPServerEvent"
eventHandler = None
backgroundThread = None
server = None
auth_token = secrets.token_urlsafe(32)
MAX_REQUEST_BYTES = 1024 * 1024

# Thread-safe structures for SSE
sessions_lock = threading.Lock()
sessions = {}  # session_id -> queue.Queue
subscriptions_lock = threading.Lock()
subscriptions = {} # session_id -> set of URIs

commandTerminatedHandler = None

def queue_session_message(session_id, payload):
    with sessions_lock:
        q = sessions.get(session_id)
        if q:
            q.put(json.dumps(payload))
            return True
    return False

def make_jsonrpc_error(req_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message
        }
    }

def get_tool_schemas():
    return [
        {
            "name": "inspect_design",
            "description": "Summarize the current design state (components, bodies, sketches, timeline, parameters, units, warnings). Instructions: Always use this tool when starting a task or after losing context. Understand the current units (e.g., 'cm' vs 'mm') before making changes. Review the timeline for warnings and identify the root component.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "query_selection",
            "description": "Describe currently selected entities in the Fusion UI in agent-friendly terms (e.g., coordinates, type, owning component). Instructions: Ask the user to select the target entity in the Fusion UI if it's too difficult to find programmatically. Use this tool to read their selection.",
            "inputSchema": {"type": "object", "properties": {}}
        },
        {
            "name": "run_fusion_script",
            "description": "Execute arbitrary Fusion API Python scripts. Instructions: Use this only when high-level tools are insufficient. Provide a robust `run(context)` function. Do not catch exceptions; let them surface. Ensure your script takes a screenshot before and after changes if modifying the design.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "script": {"type": "string", "description": "The python script to execute"}
                },
                "required": ["script"]
            }
        },
        {
            "name": "create_parametric_feature",
            "description": "Create higher-level parametric features like sketch, extrude, fillet, shell, pattern, joint, construction geometry. Instructions: Use this for safe, reversible modeling. Avoid direct modeling unless necessary. Name your features and sketches descriptively. Ensure parameter inputs match the document's units.",
            "inputSchema": {
                "type": "object", 
                "properties": {
                    "feature_type": {"type": "string", "enum": ["sketch", "extrude", "fillet", "shell"]},
                    "parameters": {"type": "object"}
                },
                "required": ["feature_type", "parameters"]
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
        }
    ]

def get_resource_schemas():
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

def get_prompt_schemas():
    return [
        {
            "name": "review_design",
            "description": "Analyze the active Fusion design for errors, warnings, and overall structure.",
            "arguments": []
        },
        {
            "name": "create_parametric_box",
            "description": "Instruct the agent to create a parametric box with specific dimensions.",
            "arguments": [
                {
                    "name": "length",
                    "description": "Length in cm (e.g., '10cm')",
                    "required": True
                },
                {
                    "name": "width",
                    "description": "Width in cm (e.g., '5cm')",
                    "required": True
                },
                {
                    "name": "height",
                    "description": "Height in cm (e.g., '2cm')",
                    "required": True
                }
            ]
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

def log_message(msg, level="info"):
    try:
        # Write to local file
        log_path = os.path.join(os.path.dirname(__file__), "fusion_mcp.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level.upper()}] {msg}\n")
            
        # Push over SSE to all connected clients
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "level": level,
                "data": msg
            }
        }
        with sessions_lock:
            for q in sessions.values():
                q.put(json.dumps(notification))
    except:
        pass

class MCPServerHandler(BaseHTTPRequestHandler):
    server_version = "FusionMCP/1.0"

    def _send_empty(self, status_code):
        self.send_response(status_code)
        self.end_headers()

    def _parsed_url(self):
        return urlparse(self.path)

    def _query_params(self):
        return parse_qs(self._parsed_url().query, keep_blank_values=True)

    def _query_value(self, name):
        values = self._query_params().get(name)
        return values[0] if values else ""

    def _is_authorized(self):
        return secrets.compare_digest(self._query_value("token"), auth_token)

    def _session_exists(self, session_id):
        with sessions_lock:
            return session_id in sessions

    def do_GET(self):
        parsed = self._parsed_url()
        if parsed.path == '/sse':
            if not self._is_authorized():
                self._send_empty(403)
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()
            
            session_id = uuid.uuid4().hex
            q = queue.Queue()
            with sessions_lock:
                sessions[session_id] = q
            
            # Send endpoint event
            endpoint_msg = f"event: endpoint\ndata: /messages?session_id={session_id}&token={auth_token}\n\n"
            self.wfile.write(endpoint_msg.encode('utf-8'))
            self.wfile.flush()
            
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        continue
                        
                    if msg == "CLOSE":
                        break
                    # msg should be a jsonrpc response string
                    sse_event = f"event: message\ndata: {msg}\n\n"
                    self.wfile.write(sse_event.encode('utf-8'))
                    self.wfile.flush()
            except Exception as e:
                log_message(f"SSE Error: {e}", "error")
            finally:
                with sessions_lock:
                    if session_id in sessions:
                        del sessions[session_id]
                with subscriptions_lock:
                    if session_id in subscriptions:
                        del subscriptions[session_id]
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self._send_empty(204)

    def do_POST(self):
        parsed = self._parsed_url()
        if parsed.path == '/messages':
            if not self._is_authorized():
                self._send_empty(403)
                return

            session_id = self._query_value("session_id")
            if not session_id or not self._session_exists(session_id):
                self._send_empty(404)
                return

            try:
                content_length = int(self.headers.get('Content-Length', 0))
            except ValueError:
                self._send_empty(400)
                return

            if content_length <= 0:
                self._send_empty(400)
                return
            if content_length > MAX_REQUEST_BYTES:
                self._send_empty(413)
                return

            post_data = self.rfile.read(content_length)

            self.send_response(202)
            self.end_headers()
            
            try:
                request_data = json.loads(post_data)
                method = request_data.get("method")
                req_id = request_data.get("id")
                params_obj = request_data.get("params", {})
                
                # Handle MCP base methods in this thread
                if method == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {},
                                "resources": {"subscribe": True, "listChanged": False},
                                "prompts": {},
                                "logging": {}
                            },
                            "serverInfo": {"name": "fusion-mcp", "version": "1.0.0"}
                        }
                    }
                    queue_session_message(session_id, response)
                    return
                elif method == "notifications/initialized":
                    return
                elif method == "logging/setLevel":
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                    queue_session_message(session_id, response)
                    return
                elif method == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "tools": get_tool_schemas()
                        }
                    }
                    queue_session_message(session_id, response)
                    return
                elif method == "resources/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "resources": get_resource_schemas()
                        }
                    }
                    queue_session_message(session_id, response)
                    return
                elif method == "resources/templates/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "resourceTemplates": get_resource_templates()
                        }
                    }
                    queue_session_message(session_id, response)
                    return
                elif method == "resources/subscribe":
                    uri = params_obj.get("uri")
                    if not isinstance(uri, str) or not uri:
                        queue_session_message(session_id, make_jsonrpc_error(req_id, -32602, "Missing resource URI."))
                        return
                    with subscriptions_lock:
                        if session_id not in subscriptions:
                            subscriptions[session_id] = set()
                        subscriptions[session_id].add(uri)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                    queue_session_message(session_id, response)
                    return
                elif method == "resources/unsubscribe":
                    uri = params_obj.get("uri")
                    with subscriptions_lock:
                        if session_id in subscriptions and uri in subscriptions[session_id]:
                            subscriptions[session_id].remove(uri)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                    queue_session_message(session_id, response)
                    return
                elif method == "prompts/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "prompts": get_prompt_schemas()
                        }
                    }
                    queue_session_message(session_id, response)
                    return
                elif method == "prompts/get":
                    # Prompts are static logic for now, no need to dispatch to Fusion UI thread
                    prompt_name = params_obj.get("name")
                    args = params_obj.get("arguments", {})
                    
                    if prompt_name == "review_design":
                        messages = [{"role": "user", "content": {"type": "text", "text": "Please read the fusion://design/summary and fusion://design/tree resources. Tell me if there are any timeline warnings, and describe the assembly structure briefly."}}]
                    elif prompt_name == "create_parametric_box":
                        messages = [{"role": "user", "content": {"type": "text", "text": f"Please use the run_fusion_script tool to create a box with length={args.get('length')}, width={args.get('width')}, height={args.get('height')}. Ensure it is fully parametric."}}]
                    else:
                        messages = []
                        
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "description": f"Prompt for {prompt_name}",
                            "messages": messages
                        }
                    }
                    queue_session_message(session_id, response)
                    return
                elif method in ["tools/call", "resources/read"]:
                    # Fire custom event to main thread for CAD operations
                    event_args = json.dumps({
                        "session_id": session_id,
                        "id": req_id,
                        "method": method,
                        "params": params_obj
                    })
                    
                    if method == "tools/call":
                        log_message(f"Calling tool: {params_obj.get('name')}", "info")
                    elif method == "resources/read":
                        log_message(f"Reading resource: {params_obj.get('uri')}", "info")
                        
                    try:
                        app.fireCustomEvent(customEvent, event_args)
                    except Exception as e:
                        queue_session_message(session_id, make_jsonrpc_error(req_id, -32603, f"Failed to dispatch request to Fusion: {e}"))
                    return
                elif method:
                    queue_session_message(session_id, make_jsonrpc_error(req_id, -32601, f"Method not found: {method}"))
                    return
                else:
                    queue_session_message(session_id, make_jsonrpc_error(req_id, -32600, "Invalid request: missing method."))
                    return
                
            except json.JSONDecodeError as e:
                queue_session_message(session_id, make_jsonrpc_error(None, -32700, f"Parse error: {e}"))
            except Exception as e:
                log_message(f"POST Error: {e}", "error")
                queue_session_message(session_id, make_jsonrpc_error(None, -32603, str(e)))
            return

        self._send_empty(404)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def find_free_port(start_port=9100):
    import socket
    for port in range(start_port, 9200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return None

def start_server():
    global server
    try:
        port = find_free_port()
        if not port:
            log_message("No free ports available.", "error")
            return
            
        server = ThreadedHTTPServer(('127.0.0.1', port), MCPServerHandler)
        log_message(f"Starting Server on port {port}", "info")
        
        # Write discovery file
        discovery_path = os.path.join(os.path.expanduser("~"), ".fusion_mcp.json")
        try:
            with open(discovery_path, "w", encoding="utf-8") as f:
                json.dump({
                    "sse_url": f"http://127.0.0.1:{port}/sse?token={auth_token}",
                    "port": port,
                    "token": auth_token
                }, f)
        except Exception as e:
            log_message(f"Failed to write discovery file: {e}", "error")
            
        server.serve_forever()
    except Exception as e:
        log_message(f"Server crash: {e}", "error")

class MCPEventHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            req = json.loads(args.additionalInfo)
            session_id = req.get("session_id")
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})
            
            # Check for active command
            if app.userInterface.activeCommand != "SelectCommand":
                raise Exception(f"Fusion is busy with command '{app.userInterface.activeCommand}'. Please cancel it first.")
            
            is_error = False
            result_payload = {}
            
            try:
                if method == "tools/call":
                    tool = params.get("name")
                    arguments = params.get("arguments", {})
                    content = []
                    
                    if tool == "inspect_design":
                        res = self.inspect_design()
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "query_selection":
                        res = self.query_selection()
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "run_fusion_script":
                        res = self.run_fusion_script(arguments.get("script", ""))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "create_parametric_feature":
                        res = self.create_parametric_feature(arguments.get("feature_type"), arguments.get("parameters"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "modify_parameters":
                        res = self.modify_parameters(arguments.get("param_name"), arguments.get("new_expression"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "capture_view":
                        res = self.capture_view(arguments.get("view_name", "iso"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "validate_model":
                        res = self.validate_model()
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "export_asset":
                        res = self.export_asset(arguments.get("format"), arguments.get("export_path"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "get_fusion_api_help":
                        res = self.get_fusion_api_help(arguments.get("topic"))
                        content.append({"type": "text", "text": res})
                    elif tool == "set_camera":
                        res = self.set_camera(arguments.get("orientation"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "prompt_user":
                        res = self.prompt_user(arguments.get("message"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "measure_entity":
                        res = self.measure_entity(arguments.get("entity_name"))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "undo_last_action":
                        res = self.undo_last_action()
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    elif tool == "get_assembly_tree":
                        res = self.get_assembly_tree(arguments.get("max_depth", 1))
                        content.append({"type": "text", "text": json.dumps(res, indent=2)})
                    else:
                        is_error = True
                        content.append({"type": "text", "text": f"Unknown tool: {tool}"})

                    if not is_error and isinstance(res, dict) and "error" in res:
                        is_error = True
                        
                    result_payload = {"content": content, "isError": is_error}
                    
                elif method == "resources/read":
                    uri = params.get("uri")
                    if not isinstance(uri, str):
                        raise Exception("Resource URI must be a string.")
                    contents = []
                    
                    if uri == "fusion://design/parameters":
                        res = self.read_parameters()
                        contents.append({"uri": uri, "mimeType": "application/json", "text": json.dumps(res, indent=2)})
                    elif uri == "fusion://design/tree":
                        res = self.get_assembly_tree(max_depth=999).get("result", {})
                        contents.append({"uri": uri, "mimeType": "application/json", "text": json.dumps(res, indent=2)})
                    elif uri.startswith("fusion://design/tree/"):
                        try:
                            depth = int(uri.split("/")[-1])
                        except:
                            depth = 1
                        res = self.get_assembly_tree(max_depth=depth).get("result", {})
                        contents.append({"uri": uri, "mimeType": "application/json", "text": json.dumps(res, indent=2)})
                    elif uri == "fusion://design/summary":
                        res = self.inspect_design().get("result", {})
                        contents.append({"uri": uri, "mimeType": "application/json", "text": json.dumps(res, indent=2)})
                    else:
                        raise Exception(f"Unknown resource URI: {uri}")
                        
                    result_payload = {"contents": contents}
                    
            except Exception as e:
                is_error = True
                if method == "tools/call":
                    result_payload = {"content": [{"type": "text", "text": f"Execution Error: {str(e)}\n{traceback.format_exc()}"}], "isError": True}
                else:
                    result_payload = str(e) # Captured for error block
                log_message(f"Execution Error: {e}", "error")
                
            if is_error and method != "tools/call":
                response = make_jsonrpc_error(req_id, -32603, str(result_payload))
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": result_payload
                }
                
            queue_session_message(session_id, response)
                
        except Exception as e:
            log_message(f"Event handler error: {e}", "error")

    # --- Tool & Resource Implementations ---

    def get_active_design(self):
        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            raise Exception("No active Fusion 360 Design found. Ensure you are in the Design workspace.")
        return design

    def inspect_design(self):
        design = self.get_active_design()
        summary = {
            "rootComponent": design.rootComponent.name,
            "components": [occ.component.name for occ in design.rootComponent.allOccurrences],
            "units": design.unitsManager.defaultLengthUnits
        }
        return {"result": summary}
        
    def read_parameters(self):
        design = self.get_active_design()
        params_dict = {}
        for param in design.userParameters:
            params_dict[param.name] = {
                "expression": param.expression,
                "value": param.value,
                "unit": param.unit
            }
        return {"userParameters": params_dict}

    def query_selection(self):
        selections = []
        for i in range(ui.activeSelections.count):
            entity = ui.activeSelections.item(i).entity
            selections.append({"type": str(type(entity)), "name": getattr(entity, 'name', 'Unknown')})
        return {"result": {"selected": selections}}

    def run_fusion_script(self, script):
        import io, sys
        if not isinstance(script, str) or not script.strip():
            return {"error": "Script must be a non-empty string."}

        script_globals = {
            "__name__": "__fusion_mcp_script__",
            "adsk": adsk,
            "app": app,
            "ui": ui
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
        finally:
            sys.stdout = old_stdout
        return {"result": "Script executed", "output": new_stdout.getvalue()}

    def create_parametric_feature(self, feature_type, params):
        if not isinstance(params, dict):
            params = {}
        design = self.get_active_design()
        root = design.rootComponent
        if feature_type == "sketch":
            sketch = root.sketches.add(root.xYConstructionPlane)
            sketch.name = params.get("name", "AutoSketch")
            return {"result": f"Created sketch {sketch.name}"}
        else:
            return {"result": f"Simulated creation of {feature_type} with parameters {params}"}

    def modify_parameters(self, param_name, new_expression):
        if not isinstance(param_name, str) or not param_name:
            return {"error": "Parameter name must be a non-empty string."}
        if not isinstance(new_expression, str) or not new_expression:
            return {"error": "New expression must be a non-empty string."}
        design = self.get_active_design()
        param = design.userParameters.itemByName(param_name)
        if not param:
            return {"error": f"Parameter '{param_name}' not found."}
        old_expr = param.expression
        param.expression = new_expression
        return {"result": f"Successfully updated '{param_name}' from '{old_expr}' to '{new_expression}'"}

    def capture_view(self, view_name):
        import tempfile, os
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"fusion_screenshot_{uuid.uuid4().hex[:6]}.png")
        viewport = app.activeViewport
        viewport.saveAsImageFile(file_path, 1920, 1080)
        return {"result": f"Screenshot saved to {file_path}"}

    def validate_model(self):
        design = self.get_active_design()
        issues = []
        timeline = design.timeline
        for i in range(timeline.count):
            obj = timeline.item(i)
            if obj.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
                issues.append(f"Timeline issue at '{obj.name}'")
        if not issues:
            return {"result": {"status": "Healthy", "issues": []}}
        else:
            return {"result": {"status": "Issues Found", "issues": issues}}

    def export_asset(self, export_format, export_path):
        import os
        if not isinstance(export_format, str):
            return {"error": "Export format must be a string."}
        if not isinstance(export_path, str) or not export_path:
            return {"error": "Export path must be a non-empty string."}
        if "\x00" in export_path:
            return {"error": "Export path contains an invalid null byte."}
        if not os.path.isabs(export_path):
            return {"error": "Export path must be absolute."}

        export_format = export_format.lower()
        design = self.get_active_design()
        export_dir = os.path.dirname(export_path)
        if export_dir and not os.path.exists(export_dir):
            os.makedirs(export_dir, exist_ok=True)
        exportMgr = design.exportManager
        if export_format == "step":
            options = exportMgr.createSTEPExportOptions(export_path, design.rootComponent)
        elif export_format == "stl":
            options = exportMgr.createSTLExportOptions(design.rootComponent, export_path)
        else:
            return {"error": f"Unsupported format: {export_format}"}
        exportMgr.execute(options)
        return {"result": f"Exported {export_format} to {export_path}"}

    def get_fusion_api_help(self, topic):
        try:
            help_path = os.path.join(os.path.dirname(__file__), "help_context.json")
            with open(help_path, "r", encoding="utf-8") as f:
                help_dict = json.load(f)
            return json.dumps(help_dict, indent=2)
        except Exception as e:
            return f"Failed to load help: {e}"

    def set_camera(self, orientation):
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

    def prompt_user(self, message):
        if not isinstance(message, str) or not message:
            return {"error": "Message must be a non-empty string."}
        if len(message) > 4000:
            return {"error": "Message is too long."}
        ui.messageBox(message, "Fusion MCP AI Agent")
        return {"result": "Message shown to user."}

    def measure_entity(self, entity_name):
        design = self.get_active_design()
            
        entity = None
        if entity_name:
            for occ in design.rootComponent.allOccurrences:
                if occ.component.name == entity_name or occ.name == entity_name:
                    entity = occ
                    break
                for body in occ.bRepBodies:
                    if body.name == entity_name:
                        entity = body
                        break
        else:
            if ui.activeSelections.count > 0:
                entity = ui.activeSelections.item(0).entity
                
        if not entity:
            return {"error": "Entity not found or nothing selected"}
            
        try:
            if not hasattr(entity, 'boundingBox'):
                return {"error": f"Entity of type {type(entity)} does not have a bounding box."}
                
            bbox = entity.boundingBox
            result = {
                "min": [bbox.minPoint.x, bbox.minPoint.y, bbox.minPoint.z],
                "max": [bbox.maxPoint.x, bbox.maxPoint.y, bbox.maxPoint.z]
            }
            
            # Use physicalProperties for volume/area if available
            if hasattr(entity, 'physicalProperties'):
                props = entity.physicalProperties
                result["volume"] = props.volume
                result["area"] = props.area
            elif hasattr(entity, 'volume'):
                result["volume"] = entity.volume
                result["area"] = getattr(entity, 'area', None)
                
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}

    def undo_last_action(self):
        try:
            # Native undo command
            app.executeTextCommand(u'NuIUndo')
            return {"result": "Undid last action"}
        except Exception as e:
            return {"error": f"Failed to undo: {e}"}

    def get_assembly_tree(self, max_depth=1):
        try:
            max_depth = int(max_depth)
        except (TypeError, ValueError):
            max_depth = 1
        max_depth = max(0, min(max_depth, 50))
        design = self.get_active_design()
            
        def traverse(comp, current_depth):
            node = {"name": comp.name, "occurrences": []}
            if current_depth > max_depth:
                return node
                
            for occ in comp.occurrences:
                transform = occ.transform
                data = transform.asArray() # 16 element matrix
                node["occurrences"].append({
                    "name": occ.name,
                    "transform": data,
                    "sub": traverse(occ.component, current_depth + 1) if occ.childOccurrences.count > 0 else None
                })
            return node
            
        return {"result": traverse(design.rootComponent, 1)}


class MyCommandTerminatedHandler(adsk.core.ApplicationCommandEventHandler):
    def __init__(self):
        super().__init__()
    def notify(self, args):
        try:
            with subscriptions_lock:
                subscription_items = [(sid, list(uris)) for sid, uris in subscriptions.items()]

            for sid, uris in subscription_items:
                for uri in uris:
                    notification = {
                        "jsonrpc": "2.0",
                        "method": "notifications/resources/updated",
                        "params": {"uri": uri}
                    }
                    queue_session_message(sid, notification)
        except Exception as e:
            log_message(f"Event Error: {e}", "error")

def run(context):
    global app, ui, eventHandler, backgroundThread, commandTerminatedHandler
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface
        
        log_message("Starting Fusion MCP Add-In", "info")
        
        eventHandler = MCPEventHandler()
        app.registerCustomEvent(customEvent)
        app.customEvent.add(eventHandler)
        
        commandTerminatedHandler = MyCommandTerminatedHandler()
        ui.commandTerminated.add(commandTerminatedHandler)
        
        backgroundThread = threading.Thread(target=start_server, daemon=True)
        backgroundThread.start()
        
    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))

def stop(context):
    global server, app, ui, commandTerminatedHandler
    try:
        log_message("Stopping Fusion MCP Add-In", "info")
        if server:
            server.shutdown()
        if app:
            app.unregisterCustomEvent(customEvent)
        if ui and commandTerminatedHandler:
            ui.commandTerminated.remove(commandTerminatedHandler)
            
        # Send CLOSE signal to all sessions to unblock threads
        with sessions_lock:
            for session_id, q in sessions.items():
                q.put("CLOSE")
            
    except:
        if ui:
            ui.messageBox('Failed:\n{}'.format(traceback.format_exc()))
