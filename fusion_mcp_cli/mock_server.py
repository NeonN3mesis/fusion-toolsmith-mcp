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
    if name == "capture_view":
        return {
            "result": {
                **common,
                "path": "mock://capture/view.png",
                "format": arguments.get("format", "png"),
                "note": "No file is written in mock mode.",
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
                "version": "1.0.0",
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
