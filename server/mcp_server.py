"""
MCP Server Module for FusionMCP
Handles HTTP server, SSE sessions, and JSON-RPC protocol dispatching.
"""

import adsk.core, adsk.fusion
import threading
import json
import uuid
import queue
import os
import secrets
import traceback
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from .task_manager import TaskManager
try:
    from ..tools.utilities import FusionScriptExecutionError
except ImportError:
    from tools.utilities import FusionScriptExecutionError

try:
    app = adsk.core.Application.get()
except Exception:
    app = None
server_instance = None
auth_token = secrets.token_urlsafe(32)
MAX_REQUEST_BYTES = 1024 * 1024
DEFAULT_PORT = 9100
server_stop_event = threading.Event()

# Thread-safe structures for SSE
sessions_lock = threading.Lock()
sessions = {}  # session_id -> queue.Queue
subscriptions_lock = threading.Lock()
subscriptions = {} # session_id -> set of URIs

def discovery_file_path():
    return os.path.join(os.path.expanduser("~"), ".fusion_mcp.json")

def remove_discovery_file(expected_token=None):
    path = discovery_file_path()
    if not os.path.exists(path):
        return
    if expected_token is not None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("token") != expected_token:
                log_message(
                    "Discovery file token does not belong to this server instance; "
                    "leaving it in place."
                )
                return
        except Exception as e:
            log_message(f"Discovery file ownership check failed: {e}")
            return
    os.remove(path)

PROMPTS = [
    {
        "name": "review_design",
        "description": "Analyze the active Fusion design for errors, warnings, and overall structure.",
        "arguments": []
    },
    {
        "name": "create_parametric_box",
        "description": "Guide the agent to create a parametric box with explicit dimensions.",
        "arguments": [
            {"name": "length", "description": "Length expression, for example 10 cm.", "required": True},
            {"name": "width", "description": "Width expression, for example 5 cm.", "required": True},
            {"name": "height", "description": "Height expression, for example 2 cm.", "required": True}
        ]
    }
]

def queue_session_message(session_id, payload):
    with sessions_lock:
        q = sessions.get(session_id)
        if q:
            q.put(json.dumps(payload))
            return True
    return False

def log_message(message):
    if app:
        app.log(message)
    else:
        print(message)

def make_jsonrpc_error(req_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": code,
            "message": message
        }
    }

def import_tools_module():
    try:
        from .. import tools as tools_module
    except ImportError:
        import tools as tools_module
    return tools_module

class MCPServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        globals()["log_message"](f"HTTP {self.address_string()} - {format % args}")

    def _parsed_url(self):
        return urlparse(self.path)

    def _query_params(self):
        return parse_qs(self._parsed_url().query)

    def _query_value(self, name):
        values = self._query_params().get(name)
        return values[0] if values else ""

    def _is_authorized(self):
        return secrets.compare_digest(self._query_value("token"), auth_token)

    def _session_exists(self, session_id):
        with sessions_lock:
            return session_id in sessions

    def _send_empty(self, status):
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()

    def _send_json(self, data, status=200):
        try:
            body = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            log_message(f"HTTP response send error: {e}")

    def do_GET(self):
        parsed = self._parsed_url()
        if parsed.path in ('/', '/health'):
            with sessions_lock:
                active_sessions = len(sessions)
            self._send_json({
                "status": "ok",
                "server": "fusion-mcp",
                "version": "1.0.0",
                "transport": "sse",
                "sse_url": f"/sse?token={auth_token}",
                "active_sessions": active_sessions
            })
            return

        if parsed.path == '/sse':
            if not self._is_authorized():
                self._send_empty(403)
                return

            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
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
                log_message(f"SSE Error: {e}")
            finally:
                with sessions_lock:
                    if session_id in sessions:
                        del sessions[session_id]
                with subscriptions_lock:
                    if session_id in subscriptions:
                        del subscriptions[session_id]
        else:
            self._send_empty(404)

    def do_OPTIONS(self):
        self._send_empty(204)

    def do_POST(self):
        parsed = self._parsed_url()
        if parsed.path == '/messages':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
            except ValueError:
                self._send_empty(400)
                return

            if content_length > MAX_REQUEST_BYTES:
                self._send_empty(413)
                return

            post_data = b""
            if content_length > 0:
                try:
                    post_data = self.rfile.read(content_length)
                except Exception as e:
                    log_message(f"Failed to read post data: {e}")
                    self._send_empty(400)
                    return

            if not self._is_authorized():
                self._send_empty(403)
                return

            session_id = self._query_value("session_id")
            if not session_id or not self._session_exists(session_id):
                self._send_empty(404)
                return

            if content_length <= 0:
                self._send_empty(400)
                return

            self.send_response(202)
            self.send_header('Content-Length', '0')
            self.send_header('Connection', 'close')
            self.end_headers()
            
            try:
                request_data = json.loads(post_data)
                if not isinstance(request_data, dict):
                    queue_session_message(session_id, make_jsonrpc_error(None, -32600, "Request must be a JSON object."))
                    return
                method = request_data.get("method")
                req_id = request_data.get("id")
                is_notification = "id" not in request_data
                params_obj = request_data.get("params", {})
                if not isinstance(method, str) or not method:
                    if not is_notification:
                        queue_session_message(session_id, make_jsonrpc_error(req_id, -32600, "Request method must be a non-empty string."))
                    return
                if params_obj is None:
                    params_obj = {}
                if not isinstance(params_obj, dict):
                    if not is_notification:
                        queue_session_message(session_id, make_jsonrpc_error(req_id, -32602, "Request params must be an object."))
                    return

                def respond(payload):
                    if not is_notification:
                        queue_session_message(session_id, payload)

                if is_notification and not method.startswith("notifications/"):
                    log_message(f"Ignoring unsupported JSON-RPC notification method: {method}")
                    return
                
                # Handle MCP base methods in this thread
                if method == "initialize":
                    if is_notification:
                        return
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {},
                                "resourceTemplates": {},
                                "resources": {"subscribe": True, "listChanged": False},
                                "prompts": {},
                                "logging": {}
                            },
                            "serverInfo": {"name": "fusion-mcp", "version": "1.0.0"}
                        }
                    }
                    respond(response)
                    return
                elif method == "notifications/initialized":
                    return
                elif method == "logging/setLevel":
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                    respond(response)
                    return
                elif method == "tools/list":
                    if is_notification:
                        return
                    tools_module = import_tools_module()
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "tools": tools_module.get_tool_schemas()
                        }
                    }
                    respond(response)
                    return
                elif method == "resources/list":
                    if is_notification:
                        return
                    tools_module = import_tools_module()
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "resources": tools_module.get_resources_schemas()
                        }
                    }
                    respond(response)
                    return
                elif method == "resources/templates/list":
                    if is_notification:
                        return
                    tools_module = import_tools_module()
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "resourceTemplates": tools_module.get_resource_templates()
                        }
                    }
                    respond(response)
                    return
                elif method == "resources/subscribe":
                    uri = params_obj.get("uri")
                    if not isinstance(uri, str) or not uri:
                        respond(make_jsonrpc_error(req_id, -32602, "Missing resource URI."))
                        return
                    with subscriptions_lock:
                        if session_id not in subscriptions:
                            subscriptions[session_id] = set()
                        subscriptions[session_id].add(uri)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                    respond(response)
                    return
                elif method == "resources/unsubscribe":
                    uri = params_obj.get("uri")
                    with subscriptions_lock:
                        if session_id in subscriptions and uri in subscriptions[session_id]:
                            subscriptions[session_id].remove(uri)
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                    respond(response)
                    return
                elif method == "prompts/list":
                    response = {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": PROMPTS}}
                    respond(response)
                    return
                elif method == "prompts/get":
                    prompt_name = params_obj.get("name")
                    prompt_args = params_obj.get("arguments", {}) or {}
                    response = handle_prompt_get(req_id, prompt_name, prompt_args)
                    respond(response)
                    return
                else:
                    # Queue to main thread via TaskManager
                    def main_thread_callback(task_data):
                        execute_mcp_request_main_thread(session_id, req_id, method, params_obj)

                    task_id = TaskManager.post(
                        command="mcp_request",
                        callback=main_thread_callback,
                        data={}
                    )
                    if not task_id:
                        respond(make_jsonrpc_error(req_id, -32000, "Fusion task manager is not running."))
                
            except json.JSONDecodeError as e:
                queue_session_message(session_id, make_jsonrpc_error(None, -32700, f"Parse error: {e}"))
            except Exception as e:
                log_message(f"POST Error: {e}")
                queue_session_message(session_id, make_jsonrpc_error(None, -32603, "Internal server error."))
            return

        self._send_empty(404)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def handle_prompt_get(req_id, prompt_name, prompt_args):
    if prompt_name == "review_design":
        text = "Inspect the active Fusion design, read the timeline and parameters, then report issues before editing."
    elif prompt_name == "create_parametric_box":
        length = prompt_args.get("length", "<length>")
        width = prompt_args.get("width", "<width>")
        height = prompt_args.get("height", "<height>")
        text = f"Create a parametric box with length {length}, width {width}, and height {height}. Name created sketches, features, and bodies."
    else:
        return make_jsonrpc_error(req_id, -32602, f"Unknown prompt: {prompt_name}")
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "description": next((p["description"] for p in PROMPTS if p["name"] == prompt_name), ""),
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": text}
                }
            ]
        }
    }


def execute_mcp_request_main_thread(session_id, req_id, method, params):
    try:
        # Check for active command
        if app and app.userInterface.activeCommand != "SelectCommand":
            raise Exception(f"Fusion is busy with command '{app.userInterface.activeCommand}'. Please cancel it first.")
        
        try:
            if method == "tools/call":
                tool = params.get("name")
                arguments = params.get("arguments", {})
                if not isinstance(tool, str) or not tool:
                    queue_session_message(session_id, make_jsonrpc_error(req_id, -32602, "Tool name must be a non-empty string."))
                    return
                if arguments is None:
                    arguments = {}
                if not isinstance(arguments, dict):
                    queue_session_message(session_id, make_jsonrpc_error(req_id, -32602, "Tool arguments must be an object."))
                    return
                
                tools_module = import_tools_module()
                res = tools_module.execute_tool(tool, arguments)
                
                if isinstance(res, dict) and "error" in res:
                    result_payload = {
                        "content": [{"type": "text", "text": str(res["error"])}],
                        "isError": True
                    }
                else:
                    result_payload = {
                        "content": [{"type": "text", "text": json.dumps(res, indent=2) if not isinstance(res, str) else res}],
                        "isError": False
                    }
                
            elif method == "resources/read":
                uri = params.get("uri")
                if not isinstance(uri, str):
                    queue_session_message(session_id, make_jsonrpc_error(req_id, -32602, "Resource URI must be a string."))
                    return
                
                tools_module = import_tools_module()
                res = tools_module.read_resource(uri)
                
                if isinstance(res, dict) and "error" in res:
                    queue_session_message(session_id, make_jsonrpc_error(req_id, -32602, str(res["error"])))
                    return
                else:
                    result_payload = {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": "application/json",
                                "text": json.dumps(res, indent=2) if not isinstance(res, str) else res
                            }
                        ]
                    }
            else:
                queue_session_message(session_id, make_jsonrpc_error(req_id, -32601, f"Method not found: {method}"))
                return

            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result_payload
            }
            
            queue_session_message(session_id, response)
            
        except Exception as e:
            log_message(f"Execution Error: {e}")
            if isinstance(e, FusionScriptExecutionError):
                parts = []
                if e.stdout_text:
                    parts.append("Stdout before exception:\n" + e.stdout_text)
                parts.append("Script traceback:\n" + e.traceback_text)
                error_text = "\n\n".join(parts)
            else:
                error_text = f"Execution Error: {str(e)}\n{traceback.format_exc()}"
            queue_session_message(session_id, {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": error_text}],
                    "isError": True
                }
            })
            
    except Exception as e:
        log_message(f"Event Notification Error: {e}")


def is_port_available(port=DEFAULT_PORT):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def start_server():
    global server_instance, app
    try:
        app = adsk.core.Application.get()
        server_stop_event.clear()
        port = DEFAULT_PORT
        wait_logged = False
        while not is_port_available(port):
            if not wait_logged:
                log_message(
                    f"Fusion MCP port {port} is already in use. "
                    "Waiting for it instead of starting on another port."
                )
                wait_logged = True
            try:
                remove_discovery_file()
            except Exception as e:
                log_message(f"Failed to remove stale discovery file: {e}")
            if server_stop_event.wait(2.0):
                return

        if wait_logged:
            log_message(f"Fusion MCP port {port} is available; starting server.")

        if server_stop_event.is_set():
            return

        if server_instance:
            log_message(
                "Fusion MCP server instance already exists. "
                "Skipping duplicate startup."
            )
            return

        server_instance = ThreadedHTTPServer(('127.0.0.1', port), MCPServerHandler)
        log_message(f"Starting Server on port {port}")
        
        # Write discovery file
        discovery_path = discovery_file_path()
        try:
            with open(discovery_path, "w", encoding="utf-8") as f:
                json.dump({
                    "sse_url": f"http://127.0.0.1:{port}/sse?token={auth_token}",
                    "port": port,
                    "token": auth_token
                }, f)
        except Exception as e:
            log_message(f"Failed to write discovery file: {e}")
            
        server_instance.serve_forever()
    except Exception as e:
        if app:
            log_message(f"Server crash: {e}\n{traceback.format_exc()}")


def stop_server():
    global server_instance
    try:
        server_stop_event.set()
        if server_instance:
            server_instance.shutdown()
            try:
                server_instance.server_close()
            except Exception as e:
                if app:
                    log_message(f"Failed to close server socket: {e}")
            server_instance = None
            
        # Clean up discovery file
        try:
            remove_discovery_file(expected_token=auth_token)
        except Exception as e:
            if app:
                log_message(f"Failed to remove discovery file: {e}")
                    
        # Send CLOSE signal to all sessions to unblock threads
        with sessions_lock:
            for session_id, q in sessions.items():
                q.put("CLOSE")
    except Exception as e:
        log_message(f"Error stopping server: {e}")
