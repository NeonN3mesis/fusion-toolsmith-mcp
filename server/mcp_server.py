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
import socket
import time
import string
import hashlib
from datetime import datetime, timezone
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
SOURCE_FINGERPRINT_FILES = (
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
MAX_SSE_SESSIONS = 1
HTTP_SESSION_TTL_SECONDS = 60 * 60
STREAMABLE_HTTP_PATH = "/mcp"
server_stop_event = threading.Event()
ANTIGRAVITY_SERVER_NAME = "autodesk-fusion-mcp"
MAX_JOURNAL_ARGUMENT_TEXT = 300
MAX_JOURNAL_ENTRIES_READ = 200
SERVER_INSTRUCTIONS = (
    "Fusion Toolsmith MCP is a safety-first Autodesk Fusion 360 server. "
    "Start with doctor, then inspect_design and fusion://agent/tool-first-workflow before editing. "
    "Prefer structured inspection, sketch, feature, parameter, validation, presentation, and export tools. "
    "Use run_fusion_script only as a last resort with script_intent and mcp_tool_gap. "
    "Run preflight_model_change before risky model edits, preflight_export before exports, and validate_model after changes. "
    "Treat tools marked destructive or dangerous as requiring explicit user intent."
)

# Thread-safe structures for SSE
sessions_lock = threading.Lock()
sessions = {}  # session_id -> queue.Queue
subscriptions_lock = threading.Lock()
subscriptions = {} # session_id -> set of URIs
http_sessions_lock = threading.Lock()
http_sessions = {}
_SESSION_ID_HEXDIGITS = set(string.hexdigits)

def discovery_file_path():
    return os.path.join(os.path.expanduser("~"), ".fusion_mcp.json")

def runtime_dir_path():
    return os.path.join(os.path.expanduser("~"), ".fusion_mcp")

def journal_file_path():
    return os.path.join(runtime_dir_path(), "journal.jsonl")

def source_root_path():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def source_fingerprint(root_dir=None):
    root_dir = root_dir or source_root_path()
    digest = hashlib.sha256()
    files = []
    for rel_path in SOURCE_FINGERPRINT_FILES:
        normalized = rel_path.replace("\\", "/")
        path = os.path.join(root_dir, rel_path)
        item = {"path": normalized, "exists": os.path.exists(path)}
        digest.update(normalized.encode("utf-8"))
        if item["exists"]:
            try:
                with open(path, "rb") as handle:
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

def install_metadata():
    path = os.path.join(source_root_path(), ".fusion_mcp_install.json")
    result = {"path": path, "exists": os.path.exists(path)}
    if result["exists"]:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                result["payload"] = json.load(handle)
        except Exception as exc:
            result["error"] = str(exc)
    return result

def antigravity_config_path():
    return os.path.join(os.path.expanduser("~"), ".gemini", "config", "mcp_config.json")

def sync_antigravity_mcp_config(sse_url, server_name=ANTIGRAVITY_SERVER_NAME):
    path = antigravity_config_path()
    if not os.path.exists(path):
        return {"status": "skipped", "reason": "config_missing", "path": path}

    with open(path, "r", encoding="utf-8-sig") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        return {"status": "skipped", "reason": "config_not_object", "path": path}

    mcp_servers = config.setdefault("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return {"status": "skipped", "reason": "mcpServers_not_object", "path": path}

    server_config = mcp_servers.setdefault(server_name, {})
    if not isinstance(server_config, dict):
        return {"status": "skipped", "reason": "server_config_not_object", "path": path}

    if server_config.get("serverUrl") == sse_url and server_config.get("disabled") is False:
        return {"status": "unchanged", "path": path}

    server_config["serverUrl"] = sse_url
    server_config["disabled"] = False
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(temp_path, path)
    return {"status": "updated", "path": path}

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

def prune_http_sessions(now=None):
    now = time.time() if now is None else now
    expired = []
    with http_sessions_lock:
        for session_id, last_seen in list(http_sessions.items()):
            if now - last_seen > HTTP_SESSION_TTL_SECONDS:
                expired.append(session_id)
                http_sessions.pop(session_id, None)
    return expired

def create_http_session(now=None):
    session_id = uuid.uuid4().hex
    with http_sessions_lock:
        http_sessions[session_id] = time.time() if now is None else now
    return session_id

def touch_http_session(session_id, now=None):
    prune_http_sessions(now=now)
    if not session_id:
        return False
    with http_sessions_lock:
        if session_id not in http_sessions:
            return False
        http_sessions[session_id] = time.time() if now is None else now
        return True

def normalize_http_session_id(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    text = str(value).strip()
    if "," in text:
        text = text.split(",", 1)[0].strip()
    return text

def is_valid_http_session_id(session_id):
    return (
        isinstance(session_id, str)
        and len(session_id) == 32
        and all(ch in _SESSION_ID_HEXDIGITS for ch in session_id)
    )

def get_task_manager_stats():
    if hasattr(TaskManager, "get_pending_task_stats"):
        try:
            return TaskManager.get_pending_task_stats()
        except Exception as e:
            return {"error": str(e)}
    return {
        "pendingTasks": TaskManager.get_pending_task_count(),
        "oldestTaskAgeSeconds": 0.0,
        "taskTimeoutSeconds": None,
        "maxPendingTasks": None,
        "backpressureActive": False,
        "tasks": [],
    }

def remove_http_session(session_id):
    with http_sessions_lock:
        http_sessions.pop(session_id, None)

def remove_sse_session(session_id):
    with sessions_lock:
        q = sessions.pop(session_id, None)
    with subscriptions_lock:
        subscriptions.pop(session_id, None)
    if q:
        q.put("CLOSE")
        return True
    return False

def _redact_journal_value(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in ("token", "authorization", "authorization_header", "password", "secret"):
                redacted[key] = "<redacted>"
            elif key_text == "script" and isinstance(item, str):
                redacted[key] = f"<script redacted: {len(item)} chars>"
            else:
                redacted[key] = _redact_journal_value(item)
        return redacted
    if isinstance(value, list):
        return [_redact_journal_value(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > MAX_JOURNAL_ARGUMENT_TEXT:
        return value[:MAX_JOURNAL_ARGUMENT_TEXT] + f"...<truncated {len(value) - MAX_JOURNAL_ARGUMENT_TEXT} chars>"
    return value

def _result_changed_design(res):
    if not isinstance(res, dict):
        return False
    result = res.get("result") if isinstance(res.get("result"), dict) else res
    comparison = result.get("stateComparison") if isinstance(result, dict) else None
    if isinstance(comparison, dict):
        return bool(comparison.get("hasChanges") or comparison.get("diff", {}).get("countChanges"))
    return False

def append_change_journal(entry):
    os.makedirs(runtime_dir_path(), exist_ok=True)
    entry = dict(entry)
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    with open(journal_file_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")

def read_change_journal(limit=MAX_JOURNAL_ENTRIES_READ):
    path = journal_file_path()
    if not os.path.exists(path):
        return []
    try:
        limit = max(1, min(int(limit), 1000))
    except (TypeError, ValueError):
        limit = MAX_JOURNAL_ENTRIES_READ
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    entries = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"error": "invalid journal line", "raw": line[:MAX_JOURNAL_ARGUMENT_TEXT]})
    return entries

def clear_change_journal():
    path = journal_file_path()
    if os.path.exists(path):
        os.remove(path)
        return True
    return False

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
    },
    {
        "name": "export_readiness",
        "description": "Guide the agent to verify compute and timeline health before any STEP, STL, or drawing/PDF export.",
        "arguments": []
    },
    {
        "name": "tool_first_workflow",
        "description": "Guide the agent to call doctor and use structured FusionMCP tools before falling back to raw scripts.",
        "arguments": []
    },
    {
        "name": "threaded_fastener_workflow",
        "description": "Guide the agent through a safe threaded-fastener modeling workflow using inspection, parameters, and structured feature tools.",
        "arguments": [
            {"name": "diameter", "description": "Nominal fastener diameter expression, for example M4 or 4 mm.", "required": False},
            {"name": "length", "description": "Fastener length expression, for example 16 mm.", "required": False}
        ]
    },
    {
        "name": "sheet_metal_enclosure_workflow",
        "description": "Guide the agent through a sheet-metal enclosure planning workflow without inventing unsupported sheet-metal operations.",
        "arguments": []
    },
    {
        "name": "printability_review",
        "description": "Guide the agent through read-only printability, physical-property, and export-readiness checks.",
        "arguments": []
    },
    {
        "name": "physical_properties_review",
        "description": "Guide the agent to report mass, volume, area, center of mass, materials, and body-level physical-property gaps.",
        "arguments": []
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
    import threading
    if app and threading.current_thread() == threading.main_thread():
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

def make_initialize_result():
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
            "resourceTemplates": {},
            "resources": {"subscribe": True, "listChanged": False},
            "prompts": {},
            "logging": {}
        },
        "serverInfo": {"name": "fusion-mcp", "version": "1.1.0"},
        "instructions": SERVER_INSTRUCTIONS,
    }

def import_tools_module():
    try:
        from .. import tools as tools_module
    except ImportError:
        import tools as tools_module
    return tools_module

class MCPServerHandler(BaseHTTPRequestHandler):
    def _is_loopback(self):
        client_ip = self.client_address[0]
        return client_ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost")

    def log_message(self, format, *args):
        globals()["log_message"](f"HTTP {self.address_string()} - {format % args}")

    def _parsed_url(self):
        return urlparse(self.path)

    def _query_params(self):
        return parse_qs(self._parsed_url().query)

    def _query_value(self, name):
        values = self._query_params().get(name)
        return values[0] if values else ""

    def _bearer_token(self):
        header = self.headers.get("Authorization") or ""
        parts = header.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return ""

    def _provided_token(self):
        return self._bearer_token() or self._query_value("token")

    def _is_authorized(self):
        return secrets.compare_digest(self._provided_token(), auth_token)

    def _using_query_token(self):
        return bool(self._query_value("token"))

    def _session_exists(self, session_id):
        with sessions_lock:
            return session_id in sessions

    def _http_session_id(self):
        return normalize_http_session_id(
            self.headers.get("Mcp-Session-Id") or self.headers.get("mcp-session-id")
        )

    def _send_invalid_http_session(self, req_id=None):
        self._send_json(make_jsonrpc_error(
            req_id,
            -32600,
            "Invalid Mcp-Session-Id header. Send the scalar session id string returned by initialize; "
            "PowerShell users should use @($response.Headers['Mcp-Session-Id'])[0]."
        ), status=400)

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

    def _send_json_with_headers(self, data, headers, status=200):
        try:
            body = json.dumps(data).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            log_message(f"HTTP response send error: {e}")

    def _handle_mcp_request_direct(self, request_data):
        if not isinstance(request_data, dict):
            return make_jsonrpc_error(None, -32600, "Request must be a JSON object.")

        method = request_data.get("method")
        req_id = request_data.get("id")
        params_obj = request_data.get("params", {})
        is_notification = "id" not in request_data

        if not isinstance(method, str) or not method:
            if is_notification:
                return None
            return make_jsonrpc_error(req_id, -32600, "Request method must be a non-empty string.")

        if params_obj is None:
            params_obj = {}
        if not isinstance(params_obj, dict):
            if is_notification:
                return None
            return make_jsonrpc_error(req_id, -32602, "Request params must be an object.")

        if is_notification:
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": make_initialize_result()
            }
        if method == "logging/setLevel":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}
        if method == "tools/list":
            tools_module = import_tools_module()
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools_module.get_tool_schemas()}}
        if method == "resources/list":
            tools_module = import_tools_module()
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": tools_module.get_resources_schemas()}}
        if method == "resources/templates/list":
            tools_module = import_tools_module()
            return {"jsonrpc": "2.0", "id": req_id, "result": {"resourceTemplates": tools_module.get_resource_templates()}}
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": PROMPTS}}
        if method == "prompts/get":
            return handle_prompt_get(req_id, params_obj.get("name"), params_obj.get("arguments", {}) or {})

        if method in ("tools/call", "resources/read"):
            response_queue = queue.Queue()
            session_id = uuid.uuid4().hex
            with sessions_lock:
                sessions[session_id] = response_queue
            try:
                def main_thread_callback(task_data):
                    execute_mcp_request_main_thread(session_id, req_id, method, params_obj)

                task_id = TaskManager.post(
                    command="mcp_request",
                    callback=main_thread_callback,
                    data={}
                )
                if not task_id:
                    return make_jsonrpc_error(req_id, -32000, "Fusion task manager is not running.")

                return json.loads(response_queue.get(timeout=30))
            except queue.Empty:
                return make_jsonrpc_error(req_id, -32000, "Timed out waiting for Fusion response.")
            finally:
                with sessions_lock:
                    sessions.pop(session_id, None)

        return make_jsonrpc_error(req_id, -32601, f"Method not found: {method}")

    def do_GET(self):
        if not self._is_loopback():
            self._send_empty(403)
            return
        parsed = self._parsed_url()
        if parsed.path in ('/', '/health'):
            prune_http_sessions()
            with sessions_lock:
                active_sessions = len(sessions)
            with http_sessions_lock:
                active_http_sessions = len(http_sessions)
            task_stats = get_task_manager_stats()
            self._send_json({
                "status": "ok",
                "server": "fusion-mcp",
                "version": "1.1.0",
                "transport": "sse",
                "transports": ["sse", "streamable_http"],
                "discovery": discovery_file_path(),
                "source_root": source_root_path(),
                "source_fingerprint": source_fingerprint(),
                "install_metadata": install_metadata(),
                "active_sessions": active_sessions,
                "active_http_sessions": active_http_sessions,
                "task_manager_running": TaskManager.is_running(),
                "pending_tasks": task_stats.get("pendingTasks"),
                "task_manager": task_stats,
            })
            return

        if parsed.path == '/sse':
            if not self._is_authorized():
                self._send_empty(403)
                return
            with sessions_lock:
                if len(sessions) >= MAX_SSE_SESSIONS:
                    self._send_json(
                        {"error": "Fusion MCP already has an active SSE client."},
                        status=503
                    )
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
            
            # Send endpoint event. Keep token-in-query only for legacy clients
            # that authenticated this SSE stream that way.
            endpoint_path = f"/messages?session_id={session_id}"
            if self._using_query_token():
                endpoint_path += f"&token={auth_token}"
            endpoint_msg = f"event: endpoint\ndata: {endpoint_path}\n\n"
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
                remove_sse_session(session_id)
        elif parsed.path == '/shutdown':
            if not self._is_authorized():
                self._send_empty(403)
                return
            self._send_json({"status": "stopping", "server": "fusion-mcp"})
            threading.Thread(target=stop_server, daemon=True, name="FusionMCP-ShutdownThread").start()
        else:
            self._send_empty(404)

    def do_OPTIONS(self):
        if not self._is_loopback():
            self._send_empty(403)
            return
        self._send_empty(204)

    def do_DELETE(self):
        if not self._is_loopback():
            self._send_empty(403)
            return
        parsed = self._parsed_url()
        if parsed.path == '/messages':
            if not self._is_authorized():
                self._send_empty(403)
                return
            session_id = self._query_value("session_id")
            if not session_id:
                self._send_empty(400)
                return
            if not remove_sse_session(session_id):
                self._send_empty(404)
                return
            self._send_empty(200)
            return

        if parsed.path not in ('/', '/sse', STREAMABLE_HTTP_PATH):
            self._send_empty(404)
            return
        if not self._is_authorized():
            self._send_empty(403)
            return

        session_id = self._http_session_id()
        if not session_id:
            self._send_empty(400)
            return
        if not is_valid_http_session_id(session_id):
            self._send_empty(400)
            return

        remove_http_session(session_id)
        self._send_empty(200)

    def do_POST(self):
        if not self._is_loopback():
            self._send_empty(403)
            return
        parsed = self._parsed_url()
        if parsed.path in ('/', '/sse', STREAMABLE_HTTP_PATH):
            if not self._is_authorized():
                self._send_empty(403)
                return
            try:
                content_length = int(self.headers.get('Content-Length', 0))
            except ValueError:
                self._send_empty(400)
                return

            if content_length > MAX_REQUEST_BYTES:
                self._send_empty(413)
                return

            if content_length <= 0:
                self._send_empty(400)
                return

            try:
                post_data = self.rfile.read(content_length)
                request_data = json.loads(post_data)
            except json.JSONDecodeError as e:
                self._send_json(make_jsonrpc_error(None, -32700, f"Parse error: {e}"), status=400)
                return
            except Exception as e:
                log_message(f"Failed to read streamable HTTP request: {e}")
                self._send_empty(400)
                return

            method = request_data.get("method") if isinstance(request_data, dict) else None
            session_id = self._http_session_id()
            request_id = request_data.get("id") if isinstance(request_data, dict) else None
            if session_id and not is_valid_http_session_id(session_id):
                self._send_invalid_http_session(request_id)
                return

            prune_http_sessions()
            if method == "initialize" and not session_id:
                session_id = create_http_session()
            else:
                if not touch_http_session(session_id):
                    self._send_json(make_jsonrpc_error(
                        request_id,
                        -32001,
                        "Session not found."
                    ), status=404)
                    return

            response = self._handle_mcp_request_direct(request_data)
            headers = {
                "Mcp-Session-Id": session_id,
                "Mcp-Protocol-Version": "2024-11-05"
            }
            if response is None:
                self._send_empty(202)
            else:
                self._send_json_with_headers(response, headers)
            return

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
                        "result": make_initialize_result()
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

    def __init__(self, server_address, RequestHandlerClass, bind_and_activate=True):
        host, port = server_address
        if ":" in host or host == "":
            self.address_family = socket.AF_INET6
        else:
            self.address_family = socket.AF_INET
        super().__init__(server_address, RequestHandlerClass, bind_and_activate)

    def server_bind(self):
        if self.address_family == socket.AF_INET6:
            try:
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except (AttributeError, socket.error):
                pass
        super().server_bind()


def handle_prompt_get(req_id, prompt_name, prompt_args):
    if prompt_name == "review_design":
        text = "Inspect the active Fusion design, read the timeline and parameters, then report issues before editing."
    elif prompt_name == "create_parametric_box":
        length = prompt_args.get("length", "<length>")
        width = prompt_args.get("width", "<width>")
        height = prompt_args.get("height", "<height>")
        text = f"Create a parametric box with length {length}, width {width}, and height {height}. Name created sketches, features, and bodies."
    elif prompt_name == "export_readiness":
        text = (
            "Before exporting, run preflight_export for STEP/STL or create_2d_drawing for drawings/PDFs. "
            "Do not use raw Fusion export APIs through run_fusion_script. If preflight reports compute, timeline, "
            "or feature health problems, stop and report the blockingReasons unless the user explicitly asks for "
            "a diagnostic export of known-broken geometry and provides an override reason."
        )
    elif prompt_name == "tool_first_workflow":
        text = (
            "Use structured FusionMCP tools first. Start by calling doctor and, when task routing is unclear, "
            "recommend_mcp_workflow or read fusion://agent/tool-first-workflow. Then inspect the model with "
            "inspect_design/get_timeline and choose specific tools such as inspect_sketch, inspect_feature, "
            "plan_parameterization, map_coordinates, create_sketch, draw_line, draw_rectangle, draw_circle, "
            "extrude_feature, fillet_feature, chamfer_feature, preflight_model_change, validate_model, "
            "preflight_export, and export_asset. Only use run_fusion_script when no structured tool can safely "
            "perform the operation; provide script_intent and mcp_tool_gap."
        )
    elif prompt_name == "threaded_fastener_workflow":
        diameter = prompt_args.get("diameter", "<diameter>")
        length = prompt_args.get("length", "<length>")
        text = (
            f"Plan a threaded fastener with nominal diameter {diameter} and length {length}. Start with doctor, "
            "inspect_design, and get_physical_properties if existing bodies are involved. Use parameters for "
            "diameter, length, head size, pitch/thread representation, clearance, and tolerances. Prefer structured "
            "sketch, extrude_feature, revolve_feature, create_hole_pattern, chamfer_feature, fillet_feature, and "
            "inspect_printability tools. Do not fake real manufacturable threads unless the user explicitly accepts "
            "cosmetic/thread-representation limitations; report any missing thread or CAM capability as a tool gap."
        )
    elif prompt_name == "sheet_metal_enclosure_workflow":
        text = (
            "Plan a sheet-metal enclosure workflow. Start with doctor, inspect_design, get_physical_properties, "
            "get_timeline, and inspect_printability. Identify sheet thickness, bend radius, flange widths, reliefs, "
            "fastener clearances, and flat-pattern/export requirements. Use current structured sketch/modeling tools "
            "only for geometry they explicitly support, and do not invent flange, bend, unfold, or flat-pattern tools. "
            "If true sheet-metal APIs are needed, stop and report the missing sheet-metal tool gap before using raw scripts."
        )
    elif prompt_name == "printability_review":
        text = (
            "Run a read-only printability review. Start with doctor and inspect_design, then call get_physical_properties "
            "and inspect_printability with mesh analysis enabled. Report bounding boxes, mass/volume/area, material gaps, "
            "thin walls, small holes, narrow slots, risky overhangs, and any warnings that still require slicer preview. "
            "Do not mutate geometry or export until preflight_export is clean or the user accepts the remaining risk."
        )
    elif prompt_name == "physical_properties_review":
        text = (
            "Call get_physical_properties for all bodies. Summarize mass, volume, surface area, density, center of mass, "
            "bounding boxes, physical materials, appearances, invisible bodies, non-solid bodies, and any bodies where "
            "Fusion did not expose physicalProperties. Keep this review read-only."
        )
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
                started = time.time()
                res = tools_module.execute_tool(tool, arguments)
                duration_ms = int((time.time() - started) * 1000)
                
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
                try:
                    append_change_journal({
                        "kind": "tools/call",
                        "requestId": req_id,
                        "sessionId": session_id,
                        "tool": tool,
                        "arguments": _redact_journal_value(arguments),
                        "isError": result_payload["isError"],
                        "durationMs": duration_ms,
                        "changedDesign": _result_changed_design(res),
                    })
                except Exception as journal_error:
                    log_message(f"Failed to append change journal: {journal_error}")
                 
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
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            except (AttributeError, socket.error):
                pass
            s.bind(('::', port))
            return True
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def start_server():
    global server_instance, app
    try:
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

        server_instance = ThreadedHTTPServer(('::', port), MCPServerHandler)
        log_message(f"Starting Server on port {port}")
        
        # Write discovery file and keep Antigravity pointed at this live token.
        discovery_path = discovery_file_path()
        sse_url = f"http://127.0.0.1:{port}/sse?token={auth_token}"
        bearer_sse_url = f"http://127.0.0.1:{port}/sse"
        streamable_http_url = f"http://127.0.0.1:{port}{STREAMABLE_HTTP_PATH}"
        try:
            with open(discovery_path, "w", encoding="utf-8") as f:
                json.dump({
                    "sse_url": sse_url,
                    "bearer_sse_url": bearer_sse_url,
                    "streamable_http_url": streamable_http_url,
                    "authorization_header": f"Bearer {auth_token}",
                    "port": port,
                    "transports": ["sse", "streamable_http"],
                    "token": auth_token
                }, f)
        except Exception as e:
            log_message(f"Failed to write discovery file: {e}")
        try:
            sync_result = sync_antigravity_mcp_config(sse_url)
            if sync_result.get("status") == "updated":
                log_message("Updated Antigravity Fusion MCP serverUrl from live discovery.")
        except Exception as e:
            log_message(f"Failed to sync Antigravity MCP config: {e}")
            
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
