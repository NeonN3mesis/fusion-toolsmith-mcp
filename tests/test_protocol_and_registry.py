import importlib
import json
import os
import queue
import sys
import tempfile
import threading
import types
import unittest
import urllib.request
import urllib.error
import time


class _FakeEvent:
    eventId = "FusionMCP.TaskManagerEvent"

    def __init__(self):
        self.handlers = []

    def add(self, handler):
        self.handlers.append(handler)

    def remove(self, handler):
        self.handlers.remove(handler)


class _FakeUI:
    activeCommand = "SelectCommand"

    def messageBox(self, *_args, **_kwargs):
        return None


class _FakeApp:
    def __init__(self):
        self.userInterface = _FakeUI()
        self.logs = []
        self.events = {}

    def log(self, message):
        self.logs.append(message)

    def registerCustomEvent(self, event_id):
        event = _FakeEvent()
        event.eventId = event_id
        self.events[event_id] = event
        return event

    def unregisterCustomEvent(self, event_id):
        self.events.pop(event_id, None)

    def fireCustomEvent(self, event_id, additional_info):
        event = self.events[event_id]
        args = types.SimpleNamespace(additionalInfo=additional_info)
        for handler in list(event.handlers):
            handler.notify(args)


_fake_app = _FakeApp()


def _install_adsk_stub():
    adsk = types.ModuleType("adsk")
    core = types.ModuleType("adsk.core")
    fusion = types.ModuleType("adsk.fusion")

    class _Application:
        @staticmethod
        def get():
            return _fake_app

    class _CustomEventHandler:
        def __init__(self):
            pass

    class _CustomEventArgs:
        pass

    core.Application = _Application
    core.CustomEventHandler = _CustomEventHandler
    core.CustomEventArgs = _CustomEventArgs
    core.ViewOrientations = types.SimpleNamespace(
        TopViewOrientation=1,
        BottomViewOrientation=2,
        LeftViewOrientation=3,
        RightViewOrientation=4,
        FrontViewOrientation=5,
        BackViewOrientation=6,
        IsoTopRightViewOrientation=7,
    )
    core.DocumentTypes = types.SimpleNamespace(DrawingDocumentType=1)
    core.ObjectCollection = types.SimpleNamespace(create=lambda: [])
    core.ValueInput = types.SimpleNamespace(
        createByString=lambda value: value,
        createByReal=lambda value: value,
    )
    core.Point3D = types.SimpleNamespace(create=lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z))
    core.Plane = types.SimpleNamespace(cast=lambda value: value)

    fusion.Design = types.SimpleNamespace(cast=lambda product: product)
    fusion.FeatureOperations = types.SimpleNamespace(
        NewBodyFeatureOperation=1,
        JoinFeatureOperation=2,
        CutFeatureOperation=3,
        IntersectFeatureOperation=4,
    )
    fusion.FeatureHealthStates = types.SimpleNamespace(
        HealthyFeatureHealthState=0,
        WarningFeatureHealthState=1,
        ErrorFeatureHealthState=2,
    )
    fusion.PipeSectionTypes = types.SimpleNamespace(
        CircularPipeSectionType=1,
        SquarePipeSectionType=2,
        TriangularPipeSectionType=3,
    )
    for name in [
        "BRepFace",
        "BRepEdge",
        "BRepVertex",
        "BRepBody",
        "Occurrence",
        "SketchEntity",
        "ConstructionPlane",
        "ExtrudeFeature",
        "FilletFeature",
        "ChamferFeature",
        "EmbossFeature",
    ]:
        setattr(fusion, name, types.SimpleNamespace(cast=lambda _value: None))

    adsk.core = core
    adsk.fusion = fusion
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = core
    sys.modules["adsk.fusion"] = fusion


_install_adsk_stub()


class ProtocolAndRegistryTests(unittest.TestCase):
    def setUp(self):
        self.mcp_server = importlib.import_module("server.mcp_server")
        self.task_manager = importlib.import_module("server.task_manager")
        self.tools = importlib.import_module("tools")
        self.mcp_server.app = _fake_app
        self.task_manager.app = _fake_app
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.mcp_server.discovery_file_path = lambda: os.path.join(self.temp_dir.name, ".fusion_mcp.json")

    def test_addin_entrypoint_imports_with_fallback(self):
        addin = importlib.import_module("FusionMCP")
        self.assertTrue(callable(addin.start_task_manager))
        self.assertTrue(callable(addin.stop_task_manager))

    def test_server_tools_import_shim_resolves_registry(self):
        tools_module = self.mcp_server.import_tools_module()
        self.assertTrue(callable(tools_module.get_tool_schemas))
        self.assertIn("inspect_design", {tool["name"] for tool in tools_module.get_tool_schemas()})

    def test_server_uses_fixed_default_port(self):
        self.assertEqual(self.mcp_server.DEFAULT_PORT, 9100)
        self.assertTrue(callable(self.mcp_server.is_port_available))

    def test_server_waits_on_fixed_port_and_stop_cancels_wait(self):
        original_is_port_available = self.mcp_server.is_port_available
        self.mcp_server.is_port_available = lambda _port: False
        self.mcp_server.server_instance = None
        self.mcp_server.server_stop_event.clear()
        try:
            thread = threading.Thread(target=self.mcp_server.start_server, daemon=True)
            thread.start()
            time.sleep(0.1)
            self.assertTrue(thread.is_alive())
            self.mcp_server.stop_server()
            thread.join(timeout=1.0)
            self.assertFalse(thread.is_alive())
            self.assertIsNone(self.mcp_server.server_instance)
        finally:
            self.mcp_server.is_port_available = original_is_port_available
            self.mcp_server.server_stop_event.clear()

    def test_task_manager_wrappers_post_and_execute(self):
        self.assertTrue(self.task_manager.start_task_manager())
        called = []
        task_id = self.task_manager.TaskManager.post("test", lambda data: called.append(data["ok"]), {"ok": True})
        self.assertIsNotNone(task_id)
        self.assertEqual(called, [True])
        self.assertTrue(self.task_manager.stop_task_manager())

    def test_destructive_git_tools_are_not_advertised_or_registered(self):
        tool_names = {tool["name"] for tool in self.tools.get_tool_schemas()}
        self.assertNotIn("git_commit", tool_names)
        self.assertNotIn("git_revert", tool_names)
        self.assertNotIn("git_commit", self.tools.tools_registry)
        self.assertNotIn("git_revert", self.tools.tools_registry)

    def test_wildcard_resource_matching_passes_capture_to_handler(self):
        self.tools.resources_registry["test://tree/*"] = lambda depth: {"depth": depth}
        try:
            self.assertEqual(self.tools.read_resource("test://tree/7"), {"depth": "7"})
        finally:
            self.tools.resources_registry.pop("test://tree/*", None)

    def test_unknown_method_returns_json_rpc_method_not_found(self):
        session_id = "session-test"
        self.mcp_server.sessions[session_id] = queue.Queue()
        try:
            self.mcp_server.execute_mcp_request_main_thread(session_id, 10, "missing/method", {})
            message = json.loads(self.mcp_server.sessions[session_id].get_nowait())
        finally:
            self.mcp_server.sessions.pop(session_id, None)
        self.assertEqual(message["error"]["code"], -32601)

    def test_prompt_get_returns_mcp_prompt_message(self):
        response = self.mcp_server.handle_prompt_get(
            22,
            "create_parametric_box",
            {"length": "10 cm", "width": "5 cm", "height": "2 cm"},
        )
        self.assertEqual(response["id"], 22)
        self.assertIn("messages", response["result"])
        text = response["result"]["messages"][0]["content"]["text"]
        self.assertIn("10 cm", text)

    def test_create_parametric_feature_does_not_simulate_success(self):
        result = self.tools.execute_tool("create_parametric_feature", {"feature_type": "extrude", "parameters": {}})
        self.assertIn("error", result)
        self.assertIn("Unsupported", result["error"])

    def test_csv_tools_reject_relative_paths_before_fusion_access(self):
        export_result = self.tools.execute_tool("export_parameters_csv", {"csv_path": "params.csv"})
        import_result = self.tools.execute_tool("import_parameters_csv", {"csv_path": "params.csv"})
        self.assertEqual(export_result, {"error": "CSV path must be absolute."})
        self.assertEqual(import_result, {"error": "CSV path must be absolute."})

    def test_health_endpoint_returns_json(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["server"], "fusion-mcp")

    def test_http_messages_initialize_enqueues_response(self):
        session_id = "http-init-session"
        self.mcp_server.sessions[session_id] = queue.Queue()
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            url = (
                f"http://127.0.0.1:{server.server_port}/messages"
                f"?session_id={session_id}&token={self.mcp_server.auth_token}"
            )
            request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 202)
            message = json.loads(self.mcp_server.sessions[session_id].get(timeout=1))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.mcp_server.sessions.pop(session_id, None)
        self.assertEqual(message["id"], 1)
        self.assertEqual(message["result"]["serverInfo"]["name"], "fusion-mcp")

    def test_http_initialized_notification_does_not_enqueue_response(self):
        session_id = "http-notification-session"
        self.mcp_server.sessions[session_id] = queue.Queue()
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}).encode("utf-8")
            url = (
                f"http://127.0.0.1:{server.server_port}/messages"
                f"?session_id={session_id}&token={self.mcp_server.auth_token}"
            )
            request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 202)
            self.assertTrue(self.mcp_server.sessions[session_id].empty())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.mcp_server.sessions.pop(session_id, None)

    def test_http_messages_requires_token(self):
        session_id = "http-auth-session"
        self.mcp_server.sessions[session_id] = queue.Queue()
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            url = f"http://127.0.0.1:{server.server_port}/messages?session_id={session_id}&token=bad-token"
            request = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.mcp_server.sessions.pop(session_id, None)


if __name__ == "__main__":
    unittest.main()
