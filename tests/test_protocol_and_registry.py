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
        "Sketch",
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

    def test_export_readiness_prompt_warns_against_raw_exports(self):
        response = self.mcp_server.handle_prompt_get(23, "export_readiness", {})
        self.assertEqual(response["id"], 23)
        text = response["result"]["messages"][0]["content"]["text"]
        self.assertIn("preflight_export", text)
        self.assertIn("create_2d_drawing", text)
        self.assertIn("Do not use raw Fusion export APIs", text)

    def test_create_parametric_feature_does_not_simulate_success(self):
        result = self.tools.execute_tool("create_parametric_feature", {"feature_type": "extrude", "parameters": {}})
        self.assertIn("error", result)
        self.assertIn("Unsupported", result["error"])

    def test_csv_tools_reject_relative_paths_before_fusion_access(self):
        export_result = self.tools.execute_tool("export_parameters_csv", {"csv_path": "params.csv"})
        import_result = self.tools.execute_tool("import_parameters_csv", {"csv_path": "params.csv"})
        self.assertEqual(export_result, {"error": "CSV path must be absolute."})
        self.assertEqual(import_result, {"error": "CSV path must be absolute."})

    def test_preflight_model_change_healthy_returns_low_risk(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=True: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}, "warnings": []}}
        }
        try:
            res = self.tools.execute_tool("preflight_model_change", {"change_type": "fillet"})
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["riskLevel"], "low")
        self.assertTrue(res["result"]["compute"]["succeeded"])

    def test_preflight_model_change_blocks_compute_failure(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: (_ for _ in ()).throw(RuntimeError("compute failed")),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=True: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}, "warnings": []}}
        }
        try:
            res = self.tools.execute_tool("preflight_model_change", {"change_type": "cut"})
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertFalse(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["riskLevel"], "high")
        self.assertIn("Fusion computeAll failed.", res["result"]["blockingReasons"])

    def test_preflight_model_change_blocks_downstream_dependencies(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        original_dependencies = utilities.get_feature_dependencies

        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=True: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}, "warnings": []}}
        }
        utilities.get_feature_dependencies = lambda feature_name: {
            "result": {
                "featureName": feature_name,
                "likelyDownstreamConsumers": [{"timelineName": "CutB"}],
            }
        }
        try:
            res = self.tools.execute_tool("preflight_model_change", {
                "change_type": "delete_feature",
                "target_features": ["ExtrudeA"],
            })
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare
            utilities.get_feature_dependencies = original_dependencies

        self.assertFalse(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["riskLevel"], "high")
        self.assertEqual(res["result"]["downstreamConsumers"][0]["targetFeature"], "ExtrudeA")

    def test_export_asset_blocks_compute_errors_before_writing_file(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        executed = []
        timeline = types.SimpleNamespace(count=0, item=lambda idx: None)
        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=timeline,
            computeAll=lambda: (_ for _ in ()).throw(RuntimeError("compute failed")),
            exportManager=types.SimpleNamespace(
                createSTEPExportOptions=lambda path, root: ("step", path, root),
                execute=lambda options: executed.append(options),
            ),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("export_asset", {
                "format": "step",
                "export_path": os.path.join(self.temp_dir.name, "blocked.step"),
            })
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("error", res)
        self.assertIn("Export blocked", res["error"])
        self.assertEqual(executed, [])
        self.assertFalse(res["preflight"]["compute"]["succeeded"])

    def test_export_asset_unhealthy_override_requires_reason(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        executed = []
        timeline = types.SimpleNamespace(count=0, item=lambda idx: None)
        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=timeline,
            computeAll=lambda: (_ for _ in ()).throw(RuntimeError("compute failed")),
            exportManager=types.SimpleNamespace(
                createSTEPExportOptions=lambda path, root: ("step", path, root),
                execute=lambda options: executed.append(options),
            ),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("export_asset", {
                "format": "step",
                "export_path": os.path.join(self.temp_dir.name, "override.step"),
                "allow_unhealthy_export": True,
            })
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("error", res)
        self.assertIn("override_reason is required", res["error"])
        self.assertEqual(executed, [])

    def test_export_asset_unhealthy_override_records_reason(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        executed = []
        timeline = types.SimpleNamespace(count=0, item=lambda idx: None)
        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=timeline,
            computeAll=lambda: (_ for _ in ()).throw(RuntimeError("compute failed")),
            exportManager=types.SimpleNamespace(
                createSTEPExportOptions=lambda path, root: ("step", path, root),
                execute=lambda options: executed.append(options),
            ),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            export_path = os.path.join(self.temp_dir.name, "override.step")
            res = self.tools.execute_tool("export_asset", {
                "format": "step",
                "export_path": export_path,
                "allow_unhealthy_export": True,
                "override_reason": "User requested a diagnostic export of known broken geometry.",
            })
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertTrue(res["result"]["exported"])
        self.assertEqual(executed, [("step", export_path, design.rootComponent)])
        self.assertEqual(res["result"]["overrideReason"], "User requested a diagnostic export of known broken geometry.")

    def test_export_asset_blocks_unhealthy_timeline_before_writing_file(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        executed = []
        unhealthy_item = types.SimpleNamespace(
            name="BrokenExtrude",
            healthState=2,
            entity=types.SimpleNamespace(
                name="BrokenExtrude",
                objectType="adsk::fusion::ExtrudeFeature",
                healthState=2,
                errorOrWarningMessage="Profile missing",
            ),
        )
        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=types.SimpleNamespace(count=1, item=lambda idx: unhealthy_item),
            computeAll=lambda: None,
            exportManager=types.SimpleNamespace(
                createSTEPExportOptions=lambda path, root: ("step", path, root),
                execute=lambda options: executed.append(options),
            ),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 1, "unhealthyTimelineItems": 1},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("export_asset", {
                "format": "step",
                "export_path": os.path.join(self.temp_dir.name, "blocked.step"),
            })
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("error", res)
        self.assertEqual(executed, [])
        self.assertIn("Timeline or feature health issues are present.", res["preflight"]["blockingReasons"])
        self.assertEqual(res["preflight"]["unhealthyFeatures"][0]["messages"], ["Profile missing"])

    def test_export_asset_healthy_export_returns_preflight_proof(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state

        executed = []
        timeline = types.SimpleNamespace(count=0, item=lambda idx: None)
        design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(name="Root"),
            timeline=timeline,
            computeAll=lambda: None,
            exportManager=types.SimpleNamespace(
                createSTEPExportOptions=lambda path, root: ("step", path, root),
                execute=lambda options: executed.append(options),
            ),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            export_path = os.path.join(self.temp_dir.name, "healthy.step")
            res = self.tools.execute_tool("export_asset", {"format": "step", "export_path": export_path})
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertTrue(res["result"]["exported"])
        self.assertEqual(executed, [("step", export_path, design.rootComponent)])
        self.assertTrue(res["result"]["preflight"]["okToExport"])
        self.assertTrue(res["result"]["preflight"]["compute"]["succeeded"])

    def test_create_2d_drawing_blocks_failed_preflight_before_export(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_model_change

        design = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        _fake_app.activeProduct = design
        _fake_app.activeDocument = types.SimpleNamespace(dataFile=types.SimpleNamespace(name="SourceData"))
        utilities.preflight_model_change = lambda **_kwargs: {
            "result": {
                "okToProceed": False,
                "blockingReasons": ["Fusion computeAll failed."],
                "compute": {"succeeded": False},
            }
        }
        try:
            res = self.tools.execute_tool("create_2d_drawing", {
                "export_pdf_path": os.path.join(self.temp_dir.name, "blocked.pdf"),
            })
        finally:
            utilities.preflight_model_change = original_preflight

        self.assertIn("error", res)
        self.assertIn("Drawing export blocked", res["error"])
        self.assertEqual(res["preflight"]["blockingReasons"], ["Fusion computeAll failed."])

    def test_create_2d_drawing_unhealthy_override_requires_reason(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_model_change

        design = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        _fake_app.activeProduct = design
        _fake_app.activeDocument = types.SimpleNamespace(dataFile=types.SimpleNamespace(name="SourceData"))
        utilities.preflight_model_change = lambda **_kwargs: {
            "result": {
                "okToProceed": False,
                "blockingReasons": ["Timeline or feature health issues are present."],
                "compute": {"succeeded": True},
            }
        }
        try:
            res = self.tools.execute_tool("create_2d_drawing", {
                "export_pdf_path": os.path.join(self.temp_dir.name, "override.pdf"),
                "allow_unhealthy_model": True,
            })
        finally:
            utilities.preflight_model_change = original_preflight

        self.assertIn("error", res)
        self.assertIn("override_reason is required", res["error"])

    def test_create_2d_drawing_exports_with_preflight_proof(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_model_change
        original_drawing_module = sys.modules.get("adsk.drawing")

        design = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        _fake_app.activeProduct = design
        _fake_app.activeDocument = types.SimpleNamespace(dataFile=types.SimpleNamespace(name="SourceData"))
        utilities.preflight_model_change = lambda **_kwargs: {
            "result": {
                "okToProceed": True,
                "riskLevel": "low",
                "blockingReasons": [],
                "compute": {"succeeded": True},
            }
        }

        drawing_module = types.ModuleType("adsk.drawing")
        create_input = types.SimpleNamespace(
            automationPreferences=types.SimpleNamespace(
                componentSheetViewPreferences=types.SimpleNamespace(),
                assemblySheetPreferences=types.SimpleNamespace(),
                drawingViewPreferences=types.SimpleNamespace(),
            )
        )
        drawing_module.DrawingCreationModes = types.SimpleNamespace(AutomaticDrawingCreationMode=1)
        drawing_module.DrawingStandardTypes = types.SimpleNamespace(ASMEDrawingStandardType=1)
        drawing_module.DrawingUnitTypes = types.SimpleNamespace(MillimeterDrawingUnitType=1)
        drawing_module.ASMESheetSizes = types.SimpleNamespace(BASMESheetSize=1)
        drawing_module.SheetOrientationTypes = types.SimpleNamespace(LandscapeSheetOrientationType=1)
        drawing_module.SheetCreationTypes = types.SimpleNamespace(FirstLevelOnlySheetCreationType=1)
        drawing_module.DrawingViewStyleTypes = types.SimpleNamespace(VisibleEdgesDrawingViewStyleType=1)
        drawing_data_file = types.SimpleNamespace(name="DrawingData")
        drawing_module.DrawingManager = types.SimpleNamespace(get=lambda: types.SimpleNamespace(
            createDrawingInput=lambda data_file, mode: create_input,
            createDrawing=lambda input_obj: drawing_data_file,
        ))

        export_path = os.path.join(self.temp_dir.name, "healthy.pdf")
        export_calls = []

        def execute_pdf(options):
            export_calls.append(options)
            with open(options.path, "wb") as handle:
                handle.write(b"%PDF-1.4\n")
            return True

        drawing_doc = types.SimpleNamespace(drawing=types.SimpleNamespace(
            exportManager=types.SimpleNamespace(
                createPDFExportOptions=lambda path: types.SimpleNamespace(path=path, openPDF=True),
                execute=execute_pdf,
            )
        ))
        drawing_module.DrawingDocument = types.SimpleNamespace(cast=lambda doc: drawing_doc)
        sys.modules["adsk.drawing"] = drawing_module

        closed = []
        _fake_app.documents = types.SimpleNamespace(
            open=lambda data_file: types.SimpleNamespace(close=lambda save: closed.append(save))
        )
        try:
            res = self.tools.execute_tool("create_2d_drawing", {"export_pdf_path": export_path})
        finally:
            utilities.preflight_model_change = original_preflight
            if original_drawing_module is None:
                sys.modules.pop("adsk.drawing", None)
            else:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertTrue(res["result"]["created"])
        self.assertEqual(res["result"]["exportPath"], export_path)
        self.assertTrue(res["result"]["preflight"]["okToProceed"])
        self.assertEqual(len(export_calls), 1)
        self.assertTrue(os.path.exists(export_path))
        self.assertEqual(closed, [False])

    def test_run_fusion_script_blocks_raw_export_api_by_default(self):
        script = """
def run(context):
    exportMgr = design.exportManager
    exportMgr.createSTEPExportOptions('C:/tmp/model.step', rootComp)
"""
        res = self.tools.execute_tool("run_fusion_script", {"script": script})
        self.assertIn("error", res)
        self.assertIn("Scripted Fusion exports are blocked", res["error"])

    def test_run_fusion_script_export_override_requires_reason(self):
        script = """
def run(context):
    exportMgr = design.exportManager
"""
        res = self.tools.execute_tool("run_fusion_script", {
            "script": script,
            "allow_export": True,
        })
        self.assertIn("error", res)
        self.assertIn("export_override_reason is required", res["error"])

    def test_run_fusion_script_blocks_raw_drawing_export_api_by_default(self):
        script = """
def run(context):
    import adsk.drawing
    drawing_mgr = adsk.drawing.DrawingManager.get()
    drawing_doc = adsk.drawing.DrawingDocument.cast(app.activeDocument)
    drawing_doc.drawing.exportManager.createPDFExportOptions('C:/tmp/drawing.pdf')
"""
        res = self.tools.execute_tool("run_fusion_script", {"script": script})
        self.assertIn("error", res)
        self.assertIn("Scripted Fusion exports are blocked", res["error"])

    def test_run_fusion_script_drawing_export_override_requires_reason(self):
        script = """
def run(context):
    import adsk.drawing
    drawing_mgr = adsk.drawing.DrawingManager.get()
    drawing_data_file = drawing_mgr.createDrawing(None)
"""
        res = self.tools.execute_tool("run_fusion_script", {
            "script": script,
            "allow_export": True,
        })
        self.assertIn("error", res)
        self.assertIn("export_override_reason is required", res["error"])

    def test_run_fusion_script_allows_export_marker_with_reason(self):
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        script = """
def run(context):
    # exportManager is mentioned for a diagnostic dry run only.
    print('acknowledged')
"""
        res = self.tools.execute_tool("run_fusion_script", {
            "script": script,
            "allow_export": True,
            "export_override_reason": "Diagnostic script that does not write an export.",
        })
        self.assertIn("result", res)
        self.assertIn("acknowledged", res["output"])

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

    def test_sse_requires_token(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/sse", timeout=2)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_sse_rejects_bad_token(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/sse?token=bad-token", timeout=2)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_sse_allows_authorized_token(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/sse?token={self.mcp_server.auth_token}",
                timeout=2,
            ) as response:
                first_line = response.readline().decode("utf-8").strip()
                second_line = response.readline().decode("utf-8").strip()
            self.assertEqual(response.status, 200)
            self.assertEqual(first_line, "event: endpoint")
            self.assertIn("/messages?session_id=", second_line)
            self.assertIn("&token=", second_line)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_sse_rejects_extra_active_clients(self):
        session_id = "existing-sse-session"
        self.mcp_server.sessions[session_id] = queue.Queue()
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/sse?token={self.mcp_server.auth_token}",
                    timeout=2,
                )
            self.assertEqual(ctx.exception.code, 503)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.mcp_server.sessions.pop(session_id, None)

    def test_streamable_http_initialize_creates_session(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                body = json.loads(response.read().decode("utf-8"))
                session_id = response.headers.get("Mcp-Session-Id")
            self.assertEqual(response.status, 200)
            self.assertTrue(session_id)
            self.assertEqual(body["result"]["serverInfo"]["name"], "fusion-mcp")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_streamable_http_reuses_session_for_tools_list(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            init_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                data=init_payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(init_request, timeout=2) as response:
                session_id = response.headers.get("Mcp-Session-Id")

            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            tools_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                data=tools_payload,
                method="POST",
                headers={"Content-Type": "application/json", "Mcp-Session-Id": session_id},
            )
            with urllib.request.urlopen(tools_request, timeout=2) as response:
                body = json.loads(response.read().decode("utf-8"))
            tool_names = {tool["name"] for tool in body["result"]["tools"]}
            self.assertIn("inspect_design", tool_names)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_streamable_http_delete_closes_session(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            init_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                data=init_payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(init_request, timeout=2) as response:
                session_id = response.headers.get("Mcp-Session-Id")

            delete_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                data=b"",
                method="DELETE",
                headers={"Mcp-Session-Id": session_id},
            )
            with urllib.request.urlopen(delete_request, timeout=2) as response:
                self.assertEqual(response.status, 200)

            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            tools_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                data=tools_payload,
                method="POST",
                headers={"Content-Type": "application/json", "Mcp-Session-Id": session_id},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(tools_request, timeout=2)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_streamable_http_tool_call_posts_to_task_manager(self):
        original_post = self.mcp_server.TaskManager.post
        original_execute = self.mcp_server.execute_mcp_request_main_thread
        posted = []

        def fake_execute(session_id, req_id, method, params):
            posted.append((session_id, req_id, method, params))
            self.mcp_server.queue_session_message(
                session_id,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": "queued"}], "isError": False},
                },
            )

        def fake_post(command, callback, data):
            posted.append(command)
            callback(data)
            return "task-id"

        self.mcp_server.TaskManager.post = fake_post
        self.mcp_server.execute_mcp_request_main_thread = fake_execute
        try:
            handler = object.__new__(self.mcp_server.MCPServerHandler)
            response = handler._handle_mcp_request_direct({
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "inspect_design", "arguments": {}},
            })
        finally:
            self.mcp_server.TaskManager.post = original_post
            self.mcp_server.execute_mcp_request_main_thread = original_execute

        self.assertIn("mcp_request", posted)
        self.assertEqual(posted[1][2], "tools/call")
        self.assertEqual(response["id"], 7)
        self.assertFalse(response["result"]["isError"])

    def test_get_sketch_dimensions_returns_details(self):
        mock_param = types.SimpleNamespace(name="d1", expression="10 cm", value=10.0)
        mock_dim = types.SimpleNamespace(parameter=mock_param, objectType="SketchLinearDimension")
        mock_sketch = types.SimpleNamespace(name="TestSketch", sketchDimensions=types.SimpleNamespace(
            count=1,
            item=lambda idx: mock_dim
        ))

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[]
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("get_sketch_dimensions", {"sketch_name": "TestSketch"})
        self.assertIn("result", res)
        dims = res["result"]["dimensions"]
        self.assertEqual(len(dims), 1)
        self.assertEqual(dims[0]["parameterName"], "d1")
        self.assertEqual(dims[0]["expression"], "10 cm")

    def test_structural_inspection_tools_are_advertised(self):
        tool_names = {tool["name"] for tool in self.tools.get_tool_schemas()}
        self.assertIn("capture_design_state", tool_names)
        self.assertIn("compare_design_state", tool_names)
        self.assertIn("inspect_sketch", tool_names)
        self.assertIn("inspect_feature", tool_names)
        self.assertIn("get_feature_dependencies", tool_names)
        self.assertIn("map_coordinates", tool_names)
        self.assertIn("create_sketch", tool_names)
        self.assertIn("draw_line", tool_names)
        self.assertIn("draw_rectangle", tool_names)
        self.assertIn("draw_circle", tool_names)
        self.assertIn("project_geometry", tool_names)
        self.assertIn("get_body_edges", tool_names)
        self.assertIn("extrude_feature", tool_names)
        self.assertIn("fillet_feature", tool_names)
        self.assertIn("chamfer_feature", tool_names)
        self.assertIn("preflight_model_change", tool_names)
        self.assertIn("revert_active_document", tool_names)

    def test_capture_design_state_returns_structural_snapshot(self):
        mock_param = types.SimpleNamespace(name="screenWidth", expression="100 mm", value=10.0, unit="mm")
        mock_body = types.SimpleNamespace(
            name="BodyA",
            isVisible=True,
            isSolid=True,
            entityToken="body-token",
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0, y=0, z=0),
                maxPoint=types.SimpleNamespace(x=1, y=2, z=3),
            ),
            physicalProperties=types.SimpleNamespace(volume=6.0, area=22.0),
        )
        mock_sketch = types.SimpleNamespace(
            name="SketchA",
            isVisible=True,
            isFullyConstrained=False,
            boundingBox=None,
            sketchDimensions=[types.SimpleNamespace()],
            geometricConstraints=[types.SimpleNamespace(), types.SimpleNamespace()],
            sketchPoints=[],
            sketchCurves=types.SimpleNamespace(
                sketchLines=[types.SimpleNamespace()],
                sketchCircles=[],
                sketchArcs=[],
                sketchEllipses=[],
                sketchFittedSplines=[],
                sketchFixedSplines=[],
                sketchConicCurves=[],
            ),
        )
        mock_feature = types.SimpleNamespace(objectType="adsk::fusion::ExtrudeFeature", name="ExtrudeA")
        mock_timeline_item = types.SimpleNamespace(
            name="ExtrudeA",
            entity=mock_feature,
            healthState=0,
            isSuppressed=False,
        )
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[mock_body],
            sketches=[mock_sketch],
            occurrences=[],
            allOccurrences=[],
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
            designType="parametric",
            userParameters=[mock_param],
            allParameters=[],
            timeline=types.SimpleNamespace(
                count=1,
                markerPosition=1,
                item=lambda idx: mock_timeline_item,
            ),
        )
        _fake_app.activeProduct = self.mock_design
        _fake_app.activeDocument = types.SimpleNamespace(name="FixtureDoc", isModified=False)
        _fake_app.documents = [_fake_app.activeDocument]

        res = self.tools.execute_tool("capture_design_state", {"include_selections": False})
        self.assertIn("result", res)
        snapshot = res["result"]
        self.assertEqual(snapshot["design"]["units"], "mm")
        self.assertEqual(snapshot["counts"]["bodies"], 1)
        self.assertEqual(snapshot["counts"]["sketches"], 1)
        self.assertEqual(snapshot["counts"]["timelineItems"], 1)
        self.assertEqual(snapshot["parameters"]["user"][0]["name"], "screenWidth")
        self.assertEqual(snapshot["bodies"][0]["key"], "Root/BodyA")
        self.assertEqual(snapshot["sketches"][0]["curveCounts"]["lines"], 1)
        self.assertNotIn("selection", snapshot)

    def test_compare_design_state_reports_unintended_changes(self):
        before = {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "design": {"units": "mm"},
            "counts": {"bodies": 1, "unhealthyTimelineItems": 0},
            "components": [],
            "bodies": [{"key": "Root/BodyA", "name": "BodyA", "componentName": "Root"}],
            "sketches": [],
            "parameters": {"user": [{"name": "width", "expression": "10 mm", "value": 1.0, "unit": "mm"}], "model": []},
            "timeline": {"items": [{"index": 0, "name": "ExtrudeA", "health": "Healthy"}]},
        }
        after = {
            "document": {"active": {"name": "DocA", "isModified": True}},
            "design": {"units": "mm"},
            "counts": {"bodies": 2, "unhealthyTimelineItems": 1},
            "components": [],
            "bodies": [
                {"key": "Root/BodyA", "name": "BodyA", "componentName": "Root"},
                {"key": "Root/BodyB", "name": "BodyB", "componentName": "Root"},
            ],
            "sketches": [],
            "parameters": {"user": [{"name": "width", "expression": "12 mm", "value": 1.2, "unit": "mm"}], "model": []},
            "timeline": {"items": [{"index": 0, "name": "ExtrudeA", "health": "Error"}]},
        }

        res = self.tools.execute_tool("compare_design_state", {"before": before, "after": after})
        result = res["result"]
        self.assertTrue(result["hasChanges"])
        self.assertEqual(result["riskLevel"], "high")
        self.assertIn("bodies", result["changedCategories"])
        self.assertIn("userParameters", result["changedCategories"])
        self.assertEqual(result["diff"]["bodies"]["added"], ["Root/BodyB"])
        self.assertEqual(result["diff"]["userParameters"]["changed"][0]["changes"]["expression"]["after"], "12 mm")
        self.assertIn("New unhealthy timeline items appeared.", result["diff"]["warnings"])

    def test_create_sketch_returns_coordinate_mapping(self):
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        component = types.SimpleNamespace(name="Root")
        plane = types.SimpleNamespace(
            name="XY",
            objectType="adsk::fusion::ConstructionPlane",
            geometry=types.SimpleNamespace(
                origin=point(0, 0, 0),
                uDirection=vector(1, 0, 0),
                vDirection=vector(0, 1, 0),
                normal=vector(0, 0, 1),
            ),
        )
        created = []

        def add_sketch(input_plane):
            sketch = types.SimpleNamespace(
                name="",
                parentComponent=component,
                referencePlane=input_plane,
                transform=None,
            )
            created.append(sketch)
            return sketch

        component.xYConstructionPlane = plane
        component.xZConstructionPlane = plane
        component.yZConstructionPlane = plane
        component.constructionPlanes = []
        component.sketches = types.SimpleNamespace(add=add_sketch)
        component.allOccurrences = []
        self.mock_design = types.SimpleNamespace(rootComponent=component)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("create_sketch", {"name": "SmartSketch", "plane": "xy"})
        self.assertEqual(res["result"]["sketchName"], "SmartSketch")
        self.assertEqual(res["result"]["coordinateSystem"]["localXAxisInModel"], [1, 0, 0])
        self.assertEqual(created[0].name, "SmartSketch")

    def test_draw_line_circle_and_rectangle_return_entities(self):
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)

        class MockLine:
            def __init__(self, start, end):
                self.name = ""
                self.objectType = "adsk::fusion::SketchLine"
                self.isConstruction = False
                self.isReference = False
                self.entityToken = "line-token"
                self.startSketchPoint = types.SimpleNamespace(geometry=start, worldGeometry=start)
                self.endSketchPoint = types.SimpleNamespace(geometry=end, worldGeometry=end)
                self.geometry = types.SimpleNamespace(startPoint=start, endPoint=end)
                self.worldGeometry = types.SimpleNamespace(startPoint=start, endPoint=end)
                self.length = 1.0

        class MockCircle:
            def __init__(self, center, radius):
                self.name = ""
                self.objectType = "adsk::fusion::SketchCircle"
                self.isConstruction = False
                self.isReference = False
                self.entityToken = "circle-token"
                self.centerSketchPoint = types.SimpleNamespace(geometry=center, worldGeometry=center)
                self.radius = radius

        lines = []
        circles = []

        def add_line(start, end):
            line = MockLine(start, end)
            lines.append(line)
            return line

        def add_rectangle(corner1, corner2):
            rectangle = [
                MockLine(corner1, point(corner2.x, corner1.y, 0)),
                MockLine(point(corner2.x, corner1.y, 0), corner2),
                MockLine(corner2, point(corner1.x, corner2.y, 0)),
                MockLine(point(corner1.x, corner2.y, 0), corner1),
            ]
            lines.extend(rectangle)
            return rectangle

        def add_circle(center, radius):
            circle = MockCircle(center, radius)
            circles.append(circle)
            return circle

        plane = types.SimpleNamespace(
            name="XY",
            objectType="adsk::fusion::ConstructionPlane",
            geometry=types.SimpleNamespace(
                origin=point(0, 0, 0),
                uDirection=vector(1, 0, 0),
                vDirection=vector(0, 1, 0),
                normal=vector(0, 0, 1),
            ),
        )
        sketch = types.SimpleNamespace(
            name="SmartSketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            referencePlane=plane,
            transform=None,
            sketchCurves=types.SimpleNamespace(
                sketchLines=types.SimpleNamespace(addByTwoPoints=add_line, addTwoPointRectangle=add_rectangle),
                sketchCircles=types.SimpleNamespace(addByCenterRadius=add_circle),
            ),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(sketches=[sketch], allOccurrences=[]),
            unitsManager=types.SimpleNamespace(evaluateExpression=lambda expression, units: 0.25),
        )
        _fake_app.activeProduct = self.mock_design

        line_res = self.tools.execute_tool("draw_line", {
            "sketch_name": "SmartSketch",
            "start": [0, 0],
            "end": [1, 0],
            "name": "EdgeA",
        })
        rect_res = self.tools.execute_tool("draw_rectangle", {
            "sketch_name": "SmartSketch",
            "corner1": [0, 0],
            "corner2": [1, 1],
            "name_prefix": "Box",
        })
        circle_res = self.tools.execute_tool("draw_circle", {
            "sketch_name": "SmartSketch",
            "center": [0.5, 0.5],
            "radius": "2.5 mm",
            "name": "HoleCircle",
        })

        self.assertEqual(line_res["result"]["line"]["name"], "EdgeA")
        self.assertEqual(len(rect_res["result"]["lines"]), 4)
        self.assertEqual(circle_res["result"]["circle"]["name"], "HoleCircle")
        self.assertEqual(circles[0].radius, 0.25)

    def test_project_geometry_projects_named_body(self):
        projected_entity = types.SimpleNamespace(
            objectType="adsk::fusion::SketchLine",
            name="ProjectedLine",
            entityToken="projected-token",
        )
        body = types.SimpleNamespace(name="SourceBody")
        projected = []
        sketch = types.SimpleNamespace(
            name="ProjectSketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            referencePlane=types.SimpleNamespace(
                name="XY",
                objectType="adsk::fusion::ConstructionPlane",
                geometry=types.SimpleNamespace(
                    origin=types.SimpleNamespace(x=0, y=0, z=0),
                    uDirection=types.SimpleNamespace(x=1, y=0, z=0),
                    vDirection=types.SimpleNamespace(x=0, y=1, z=0),
                    normal=types.SimpleNamespace(x=0, y=0, z=1),
                ),
            ),
            transform=None,
            project=lambda entity: projected.append(entity) or [projected_entity],
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[body],
                sketches=[sketch],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("project_geometry", {
            "sketch_name": "ProjectSketch",
            "entity_name": "SourceBody",
        })
        self.assertEqual(projected, [body])
        self.assertEqual(res["result"]["projectedCount"], 1)
        self.assertEqual(res["result"]["projected"][0]["entityToken"], "projected-token")

    def test_project_geometry_projects_source_sketch_curve(self):
        source_line = types.SimpleNamespace(name="SourceLine")
        projected_entity = types.SimpleNamespace(
            objectType="adsk::fusion::SketchLine",
            name="ProjectedSourceLine",
            entityToken="projected-source-token",
        )
        projected = []
        plane = types.SimpleNamespace(
            name="XY",
            objectType="adsk::fusion::ConstructionPlane",
            geometry=types.SimpleNamespace(
                origin=types.SimpleNamespace(x=0, y=0, z=0),
                uDirection=types.SimpleNamespace(x=1, y=0, z=0),
                vDirection=types.SimpleNamespace(x=0, y=1, z=0),
                normal=types.SimpleNamespace(x=0, y=0, z=1),
            ),
        )
        source_sketch = types.SimpleNamespace(
            name="SourceSketch",
            sketchCurves=types.SimpleNamespace(
                sketchLines=types.SimpleNamespace(count=1, item=lambda idx: source_line),
            ),
        )
        target_sketch = types.SimpleNamespace(
            name="TargetSketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            referencePlane=plane,
            transform=None,
            project=lambda entity: projected.append(entity) or [projected_entity],
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[],
                sketches=[source_sketch, target_sketch],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("project_geometry", {
            "sketch_name": "TargetSketch",
            "source_sketch_name": "SourceSketch",
            "curve_type": "lines",
            "curve_index": 0,
        })
        self.assertEqual(projected, [source_line])
        self.assertEqual(res["result"]["projectedCount"], 1)
        self.assertEqual(res["result"]["projected"][0]["entityToken"], "projected-source-token")

    def test_get_body_edges_returns_indexed_edge_metadata(self):
        class MockCollection:
            def __init__(self, items):
                self._items = items
                self.count = len(items)
            def item(self, index):
                return self._items[index]

        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        edge0 = types.SimpleNamespace(
            name="Edge0",
            entityToken="edge0",
            length=1.5,
            objectType="adsk::fusion::BRepEdge",
            geometry=types.SimpleNamespace(objectType="adsk::core::Line3D"),
            startVertex=types.SimpleNamespace(geometry=point(0, 0, 0)),
            endVertex=types.SimpleNamespace(geometry=point(1, 0, 0)),
        )
        edge1 = types.SimpleNamespace(
            name="Edge1",
            entityToken="edge1",
            length=2.5,
            objectType="adsk::fusion::BRepEdge",
            geometry=types.SimpleNamespace(objectType="adsk::core::Arc3D"),
            startVertex=types.SimpleNamespace(geometry=point(0, 1, 0)),
            endVertex=types.SimpleNamespace(geometry=point(1, 1, 0)),
        )
        body = types.SimpleNamespace(
            name="BodyA",
            parentComponent=types.SimpleNamespace(name="Root"),
            edges=MockCollection([edge0, edge1]),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(bRepBodies=[body], allOccurrences=[])
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("get_body_edges", {
            "body_name": "BodyA",
            "edge_indices": [1],
        })

        self.assertIn("result", res)
        self.assertEqual(res["result"]["bodyName"], "BodyA")
        self.assertEqual(res["result"]["edgeCount"], 2)
        self.assertEqual(res["result"]["edges"][0]["index"], 1)
        self.assertEqual(res["result"]["edges"][0]["entityToken"], "edge1")
        self.assertEqual(res["result"]["edges"][0]["geometryType"], "adsk::core::Arc3D")
        self.assertEqual(res["result"]["edges"][0]["startVertex"], [0, 1, 0])

    def test_extrude_feature_requires_explicit_operation(self):
        res = self.tools.execute_tool("extrude_feature", {
            "sketch_name": "SketchA",
            "distance": "5 mm",
            "operation": "",
        })
        self.assertIn("error", res)
        self.assertIn("operation is required", res["error"])

    def test_extrude_feature_creates_named_body_and_state_diff(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockCollection:
            def __init__(self, items):
                self._items = items
                self.count = len(items)
            def item(self, index):
                return self._items[index]

        profile = types.SimpleNamespace(name="Profile0")
        result_body = types.SimpleNamespace(name="Body0")
        participant_body = types.SimpleNamespace(name="ParticipantBody")
        created_inputs = []

        class MockParticipantBodies:
            def __init__(self):
                self.items = []
            def add(self, body):
                self.items.append(body)

        class MockExtrudeInput:
            def __init__(self, profile_arg, operation_arg):
                self.profile = profile_arg
                self.operation = operation_arg
                self.participantBodies = MockParticipantBodies()
                self.distance = None
            def setDistanceExtent(self, _is_symmetric, distance):
                self.distance = distance

        class MockExtrudes:
            def createInput(self, profile_arg, operation_arg):
                input_obj = MockExtrudeInput(profile_arg, operation_arg)
                created_inputs.append(input_obj)
                return input_obj
            def add(self, input_obj):
                self.last_input = input_obj
                return types.SimpleNamespace(
                    name="",
                    bodies=MockCollection([result_body]),
                    participantBodies=MockCollection(input_obj.participantBodies.items),
                )

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(extrudeFeatures=MockExtrudes()),
        )
        sketch = types.SimpleNamespace(
            name="SketchA",
            parentComponent=component,
            profiles=MockCollection([profile]),
        )
        root = types.SimpleNamespace(
            name="Root",
            sketches=[sketch],
            bRepBodies=[participant_body],
            allOccurrences=[],
        )
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1, "unhealthyTimelineItems": 0}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {
            "result": {"featureName": feature_name, "operation": "NewBody"}
        }
        try:
            res = self.tools.execute_tool("extrude_feature", {
                "sketch_name": "SketchA",
                "distance": "5 mm",
                "operation": "NewBody",
                "name": "ExtrudeA",
                "body_name": "BodyA",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect

        self.assertIn("result", res)
        self.assertEqual(res["result"]["featureName"], "ExtrudeA")
        self.assertEqual(res["result"]["operation"], "NewBody")
        self.assertEqual(res["result"]["resultBodies"], ["BodyA"])
        self.assertEqual(created_inputs[0].distance, "5 mm")
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_fillet_feature_requires_edge_indices(self):
        res = self.tools.execute_tool("fillet_feature", {
            "body_name": "BodyA",
            "edge_indices": [],
            "radius": "1 mm",
        })
        self.assertIn("error", res)
        self.assertIn("edge_indices is required", res["error"])

    def test_fillet_feature_creates_constant_radius_edge_set(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockCollection:
            def __init__(self, items):
                self._items = items
                self.count = len(items)
            def item(self, index):
                return self._items[index]

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        original_object_collection = sys.modules["adsk.core"].ObjectCollection
        sys.modules["adsk.core"].ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())

        edge0 = types.SimpleNamespace(name="Edge0", entityToken="edge0", length=1.0, objectType="BRepEdge")
        edge1 = types.SimpleNamespace(name="Edge1", entityToken="edge1", length=2.0, objectType="BRepEdge")
        created_inputs = []

        class MockFilletInput:
            def __init__(self):
                self.edge_sets = []
            def addConstantRadiusEdgeSet(self, edges, radius, tangent_chain):
                self.edge_sets.append((list(edges), radius, tangent_chain))

        class MockFillets:
            def createInput(self):
                input_obj = MockFilletInput()
                created_inputs.append(input_obj)
                return input_obj
            def add(self, input_obj):
                return types.SimpleNamespace(name="")

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(filletFeatures=MockFillets()),
        )
        body = types.SimpleNamespace(
            name="BodyA",
            parentComponent=component,
            edges=MockCollection([edge0, edge1]),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[body],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1, "unhealthyTimelineItems": 0}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {
            "result": {"featureName": feature_name, "featureType": "FilletFeature"}
        }
        try:
            res = self.tools.execute_tool("fillet_feature", {
                "body_name": "BodyA",
                "edge_indices": [1],
                "radius": "1 mm",
                "name": "FilletA",
                "tangent_chain": False,
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect
            sys.modules["adsk.core"].ObjectCollection = original_object_collection

        self.assertIn("result", res)
        self.assertEqual(res["result"]["featureName"], "FilletA")
        self.assertEqual(res["result"]["bodyName"], "BodyA")
        self.assertEqual(res["result"]["edgeIndices"], [1])
        self.assertEqual(res["result"]["edges"][0]["entityToken"], "edge1")
        self.assertEqual(created_inputs[0].edge_sets[0][0], [edge1])
        self.assertEqual(created_inputs[0].edge_sets[0][1], "1 mm")
        self.assertFalse(created_inputs[0].edge_sets[0][2])
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_chamfer_feature_requires_edge_indices(self):
        res = self.tools.execute_tool("chamfer_feature", {
            "body_name": "BodyA",
            "edge_indices": [],
            "distance": "1 mm",
        })
        self.assertIn("error", res)
        self.assertIn("edge_indices is required", res["error"])

    def test_chamfer_feature_creates_equal_distance_chamfer(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockCollection:
            def __init__(self, items):
                self._items = items
                self.count = len(items)
            def item(self, index):
                return self._items[index]

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        original_object_collection = sys.modules["adsk.core"].ObjectCollection
        sys.modules["adsk.core"].ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())

        edge0 = types.SimpleNamespace(name="Edge0", entityToken="edge0", length=1.0, objectType="BRepEdge")
        edge1 = types.SimpleNamespace(name="Edge1", entityToken="edge1", length=2.0, objectType="BRepEdge")
        created_inputs = []

        class MockChamferInput:
            def __init__(self, edges, tangent_chain):
                self.edges = list(edges)
                self.tangent_chain = tangent_chain
                self.distance = None
            def setToEqualDistance(self, distance):
                self.distance = distance

        class MockChamfers:
            def createInput(self, edges, tangent_chain):
                input_obj = MockChamferInput(edges, tangent_chain)
                created_inputs.append(input_obj)
                return input_obj
            def add(self, input_obj):
                return types.SimpleNamespace(name="")

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(chamferFeatures=MockChamfers()),
        )
        body = types.SimpleNamespace(
            name="BodyA",
            parentComponent=component,
            edges=MockCollection([edge0, edge1]),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[body],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1, "unhealthyTimelineItems": 0}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {
            "result": {"featureName": feature_name, "featureType": "ChamferFeature"}
        }
        try:
            res = self.tools.execute_tool("chamfer_feature", {
                "body_name": "BodyA",
                "edge_indices": [1],
                "distance": "1 mm",
                "name": "ChamferA",
                "tangent_chain": False,
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect
            sys.modules["adsk.core"].ObjectCollection = original_object_collection

        self.assertIn("result", res)
        self.assertEqual(res["result"]["featureName"], "ChamferA")
        self.assertEqual(res["result"]["bodyName"], "BodyA")
        self.assertEqual(res["result"]["edgeIndices"], [1])
        self.assertEqual(res["result"]["edges"][0]["entityToken"], "edge1")
        self.assertEqual(created_inputs[0].edges, [edge1])
        self.assertEqual(created_inputs[0].distance, "1 mm")
        self.assertFalse(created_inputs[0].tangent_chain)
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_inspect_sketch_returns_coordinate_mapping_and_curves(self):
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        user_param = types.SimpleNamespace(name="fixtureWidth", expression="10 cm", value=10.0, unit="cm", comment="Width control")
        mock_param = types.SimpleNamespace(name="d1", expression="fixtureWidth", value=10.0, unit="cm")
        mock_dim = types.SimpleNamespace(name="LengthDim", parameter=mock_param, objectType="SketchLinearDimension")
        source_edge = types.SimpleNamespace(
            name="SourceEdge",
            objectType="adsk::fusion::BRepEdge",
            entityToken="edge-token",
        )
        mock_line = types.SimpleNamespace(
            name="Line1",
            objectType="adsk::fusion::SketchLine",
            isConstruction=False,
            isReference=True,
            entityToken="line-token",
            referencedEntity=source_edge,
            startSketchPoint=types.SimpleNamespace(geometry=point(0, 0, 0)),
            endSketchPoint=types.SimpleNamespace(geometry=point(1, 0, 0)),
            geometry=types.SimpleNamespace(startPoint=point(0, 0, 0), endPoint=point(1, 0, 0)),
            worldGeometry=types.SimpleNamespace(startPoint=point(10, 20, 30), endPoint=point(11, 20, 30)),
            length=1.0,
        )
        mock_sketch = types.SimpleNamespace(
            name="TestSketch",
            objectType="adsk::fusion::Sketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            isVisible=True,
            isFullyConstrained=False,
            referencePlane=types.SimpleNamespace(
                name="XZ",
                objectType="adsk::fusion::ConstructionPlane",
                geometry=types.SimpleNamespace(
                    origin=point(0, 0, 0),
                    uDirection=vector(1, 0, 0),
                    vDirection=vector(0, 0, -1),
                    normal=vector(0, 1, 0),
                ),
            ),
            sketchPoints=types.SimpleNamespace(count=0, item=lambda idx: None),
            sketchDimensions=types.SimpleNamespace(count=1, item=lambda idx: mock_dim),
            geometricConstraints=types.SimpleNamespace(count=0, item=lambda idx: None),
            sketchCurves=types.SimpleNamespace(
                sketchLines=types.SimpleNamespace(count=1, item=lambda idx: mock_line),
                sketchCircles=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchArcs=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchEllipses=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchFittedSplines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchFixedSplines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchConicCurves=types.SimpleNamespace(count=0, item=lambda idx: None),
            ),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(sketches=[mock_sketch], allOccurrences=[]),
            userParameters=types.SimpleNamespace(itemByName=lambda name: user_param if name == "fixtureWidth" else None),
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("inspect_sketch", {"sketch_name": "TestSketch"})
        self.assertIn("result", res)
        result = res["result"]
        self.assertEqual(result["coordinateSystem"]["localYAxisInModel"], [0, 0, -1])
        self.assertEqual(result["curves"]["lines"][0]["worldEndPoint"], [11, 20, 30])
        self.assertEqual(result["dimensions"][0]["parameterName"], "d1")
        self.assertEqual(result["parameters"][0]["name"], "d1")
        self.assertEqual(result["parameters"][0]["userParameterReferences"][0]["name"], "fixtureWidth")
        self.assertEqual(result["curves"]["lines"][0]["source"]["entityToken"], "edge-token")

    def test_map_coordinates_returns_both_transform_directions(self):
        original_point3d = sys.modules["adsk.core"].Point3D
        class MockPoint:
            def __init__(self, x, y, z):
                self.x = x
                self.y = y
                self.z = z
            def copy(self):
                return MockPoint(self.x, self.y, self.z)
            def transformBy(self, matrix):
                self.x += matrix.dx
                self.y += matrix.dy
                self.z += matrix.dz

        class MockMatrix:
            def __init__(self, dx, dy, dz):
                self.dx = dx
                self.dy = dy
                self.dz = dz
            def copy(self):
                return MockMatrix(self.dx, self.dy, self.dz)
            def invert(self):
                self.dx = -self.dx
                self.dy = -self.dy
                self.dz = -self.dz
                return True
            def asArray(self):
                return [1, 0, 0, self.dx, 0, 1, 0, self.dy, 0, 0, 1, self.dz]

        point = lambda x, y, z: MockPoint(x, y, z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        sys.modules["adsk.core"].Point3D = types.SimpleNamespace(create=point)
        try:
            mock_sketch = types.SimpleNamespace(
                name="TestSketch",
                referencePlane=types.SimpleNamespace(
                    geometry=types.SimpleNamespace(
                        origin=point(0, 0, 0),
                        uDirection=vector(1, 0, 0),
                        vDirection=vector(0, 0, -1),
                        normal=vector(0, 1, 0),
                    )
                ),
                sketchToModelSpace=lambda p: point(p.x, 100 + p.y, p.z),
                modelToSketchSpace=lambda p: point(p.x, p.y - 100, p.z),
            )
            target_occ = types.SimpleNamespace(
                name="TargetOcc",
                component=types.SimpleNamespace(name="TargetComp"),
                transform=MockMatrix(10, 0, 0),
            )
            root = types.SimpleNamespace(name="Root", sketches=[mock_sketch], allOccurrences=[target_occ])
            self.mock_design = types.SimpleNamespace(rootComponent=root)
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("map_coordinates", {
                "point": [1, 2, 3],
                "from_sketch": "TestSketch",
                "to_component": "TargetOcc",
            })
        finally:
            sys.modules["adsk.core"].Point3D = original_point3d
        self.assertEqual(res["result"]["sketchToModel"], [1, 102, 3])
        self.assertEqual(res["result"]["sketchToTargetComponent"], [-9, 102, 3])
        self.assertEqual(res["result"]["targetComponentToModel"], [11, 2, 3])
        self.assertEqual(res["result"]["modelToSketch"], [11, -98, 3])

    def test_inspect_feature_returns_extrude_operation_and_bodies(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        mock_body = types.SimpleNamespace(name="Body1")
        user_param = types.SimpleNamespace(name="slotDepth", expression="5 mm", value=0.5, unit="cm", comment="Slot depth")
        mock_distance_param = types.SimpleNamespace(
            name="d228",
            expression="slotDepth",
            value=0.5,
            unit="cm",
            objectType="adsk::fusion::ModelParameter",
            entityToken="param-token",
        )
        mock_extent = types.SimpleNamespace(
            objectType="adsk::fusion::DistanceExtentDefinition",
            distance=mock_distance_param,
        )
        mock_extrude = types.SimpleNamespace(
            name="CutSlot",
            objectType="adsk::fusion::ExtrudeFeature",
            healthState=0,
            operation=3,
            extentOne=mock_extent,
            extentTwo=None,
            isSymmetric=False,
            isSolid=True,
            participantBodies=types.SimpleNamespace(count=1, item=lambda idx: mock_body),
            bodies=types.SimpleNamespace(count=1, item=lambda idx: mock_body),
            profiles=types.SimpleNamespace(count=0, item=lambda idx: None),
        )
        sys.modules["adsk.fusion"].ExtrudeFeature = types.SimpleNamespace(cast=lambda value: value if value is mock_extrude else None)
        try:
            mock_item = types.SimpleNamespace(
                name="CutSlot",
                index=4,
                healthState=0,
                isSuppressed=False,
                entity=mock_extrude,
            )
            self.mock_design = types.SimpleNamespace(
                timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
                rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
                userParameters=types.SimpleNamespace(itemByName=lambda name: user_param if name == "slotDepth" else None),
            )
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("inspect_feature", {"feature_name": "CutSlot"})
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude

        self.assertEqual(res["result"]["featureType"], "ExtrudeFeature")
        self.assertEqual(res["result"]["operation"], "Cut")
        self.assertEqual(res["result"]["extentOne"]["distanceExpression"], "slotDepth")
        self.assertEqual(res["result"]["participantBodies"], ["Body1"])
        self.assertEqual(res["result"]["parameters"][0]["name"], "d228")
        self.assertEqual(res["result"]["parameters"][0]["role"], "extentOne.distance")
        self.assertEqual(res["result"]["parameters"][0]["userParameterReferences"][0]["name"], "slotDepth")

    def test_get_feature_dependencies_reports_profile_sketch_and_downstream(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        original_sketch = sys.modules["adsk.fusion"].Sketch
        mock_body = types.SimpleNamespace(name="Body1")
        mock_sketch = types.SimpleNamespace(
            name="SketchA",
            objectType="adsk::fusion::Sketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            referencePlane=types.SimpleNamespace(name="XY", objectType="adsk::fusion::ConstructionPlane"),
            sketchCurves=types.SimpleNamespace(
                sketchLines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchCircles=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchArcs=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchEllipses=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchFittedSplines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchFixedSplines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchConicCurves=types.SimpleNamespace(count=0, item=lambda idx: None),
            ),
        )
        mock_profile = types.SimpleNamespace(
            profileLoops=types.SimpleNamespace(
                count=1,
                item=lambda idx: types.SimpleNamespace(
                    profileCurves=types.SimpleNamespace(
                        count=1,
                        item=lambda cidx: types.SimpleNamespace(
                            sketchEntity=types.SimpleNamespace(parentSketch=mock_sketch)
                        )
                    )
                )
            )
        )
        target_extrude = types.SimpleNamespace(
            name="ExtrudeA",
            objectType="adsk::fusion::ExtrudeFeature",
            bodies=types.SimpleNamespace(count=1, item=lambda idx: mock_body),
            profiles=types.SimpleNamespace(count=1, item=lambda idx: mock_profile),
        )
        downstream_extrude = types.SimpleNamespace(
            name="CutB",
            objectType="adsk::fusion::ExtrudeFeature",
            participantBodies=types.SimpleNamespace(count=1, item=lambda idx: mock_body),
            bodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            profiles=types.SimpleNamespace(count=0, item=lambda idx: None),
        )
        items = [
            types.SimpleNamespace(name="ExtrudeA", index=0, healthState=0, entity=target_extrude),
            types.SimpleNamespace(name="CutB", index=1, healthState=0, entity=downstream_extrude),
        ]
        sys.modules["adsk.fusion"].ExtrudeFeature = types.SimpleNamespace(
            cast=lambda value: value if value in (target_extrude, downstream_extrude) else None
        )
        sys.modules["adsk.fusion"].Sketch = types.SimpleNamespace(cast=lambda value: value if value is mock_sketch else None)
        try:
            self.mock_design = types.SimpleNamespace(
                timeline=types.SimpleNamespace(count=2, item=lambda idx: items[idx]),
                rootComponent=types.SimpleNamespace(sketches=[mock_sketch], allOccurrences=[]),
            )
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("get_feature_dependencies", {"feature_name": "ExtrudeA"})
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude
            sys.modules["adsk.fusion"].Sketch = original_sketch

        self.assertTrue(res["result"]["bestEffort"])
        self.assertEqual(res["result"]["directInputs"][0]["sketchName"], "SketchA")
        self.assertEqual(res["result"]["likelyDownstreamConsumers"][0]["timelineName"], "CutB")
        self.assertIn("usesResultBodyAsParticipant", res["result"]["likelyDownstreamConsumers"][0]["reasons"])

    def test_get_feature_dependencies_keeps_unresolved_profiles(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        mock_distance_param = types.SimpleNamespace(
            name="d1",
            expression="fixtureHeight",
            value=0.8,
            unit="mm",
            objectType="adsk::fusion::ModelParameter",
        )
        mock_extent = types.SimpleNamespace(distance=mock_distance_param)
        mock_profile = types.SimpleNamespace(objectType="adsk::fusion::Profile")
        mock_extrude = types.SimpleNamespace(
            name="ExtrudeA",
            objectType="adsk::fusion::ExtrudeFeature",
            extentOne=mock_extent,
            extentTwo=None,
            bodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            profiles=types.SimpleNamespace(count=1, item=lambda idx: mock_profile),
        )
        mock_item = types.SimpleNamespace(name="ExtrudeA", index=0, healthState=0, entity=mock_extrude)
        sys.modules["adsk.fusion"].ExtrudeFeature = types.SimpleNamespace(cast=lambda value: value if value is mock_extrude else None)
        try:
            self.mock_design = types.SimpleNamespace(
                timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
                rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
            )
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("get_feature_dependencies", {"feature_name": "ExtrudeA"})
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude

        kinds = [item["kind"] for item in res["result"]["directInputs"]]
        self.assertIn("featureParameter", kinds)
        self.assertIn("profile", kinds)
        profile_input = [item for item in res["result"]["directInputs"] if item["kind"] == "profile"][0]
        self.assertEqual(profile_input["confidence"], "unknown")

    def test_revert_active_document_closes_and_reopens_saved_document(self):
        opened = []
        data_file = types.SimpleNamespace(name="SavedData")
        reopened_doc = types.SimpleNamespace(name="SavedDoc", activate=lambda: opened.append("activated"))
        closed = []
        doc = types.SimpleNamespace(
            name="SavedDoc",
            dataFile=data_file,
            isModified=True,
            close=lambda save: closed.append(save),
        )
        _fake_app.activeDocument = doc
        _fake_app.documents = types.SimpleNamespace(open=lambda df: opened.append(df) or reopened_doc)

        res = self.tools.execute_tool("revert_active_document", {"save_changes": False})
        self.assertIn("result", res)
        self.assertEqual(closed, [False])
        self.assertEqual(opened[0], data_file)
        self.assertEqual(opened[1], "activated")

    def test_delete_timeline_feature_requires_reason(self):
        deleted = []
        mock_item = types.SimpleNamespace(name="FeatureA", deleteMe=lambda: deleted.append(True))
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("delete_timeline_feature", {"name": "FeatureA"})

        self.assertIn("error", res)
        self.assertIn("reason is required", res["error"])
        self.assertEqual(deleted, [])

    def test_delete_timeline_feature_blocks_downstream_consumers(self):
        parametric = importlib.import_module("tools.parametric")
        original_dependencies = parametric.get_feature_dependencies
        deleted = []
        mock_item = types.SimpleNamespace(name="FeatureA", deleteMe=lambda: deleted.append(True))
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design
        parametric.get_feature_dependencies = lambda feature_name: {
            "result": {
                "featureName": feature_name,
                "likelyDownstreamConsumers": [{"timelineName": "CutB", "reasons": ["usesResultBodyAsParticipant"]}],
            }
        }
        try:
            res = self.tools.execute_tool("delete_timeline_feature", {
                "name": "FeatureA",
                "reason": "Remove obsolete test feature.",
            })
        finally:
            parametric.get_feature_dependencies = original_dependencies

        self.assertIn("error", res)
        self.assertIn("downstream consumers", res["error"])
        self.assertEqual(deleted, [])
        self.assertEqual(res["dependencyReport"]["likelyDownstreamConsumers"][0]["timelineName"], "CutB")

    def test_delete_timeline_feature_allows_override_and_returns_state_comparison(self):
        parametric = importlib.import_module("tools.parametric")
        original_dependencies = parametric.get_feature_dependencies
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        deleted = []
        mock_item = types.SimpleNamespace(name="FeatureA", deleteMe=lambda: deleted.append(True))
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design
        parametric.get_feature_dependencies = lambda feature_name: {
            "result": {
                "featureName": feature_name,
                "likelyDownstreamConsumers": [{"timelineName": "CutB", "reasons": ["usesResultBodyAsParticipant"]}],
            }
        }
        parametric._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 1 - len(deleted)}
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "medium", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("delete_timeline_feature", {
                "name": "FeatureA",
                "reason": "User approved deleting this obsolete branch.",
                "allow_downstream_risk": True,
            })
        finally:
            parametric.get_feature_dependencies = original_dependencies
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(deleted, [True])
        self.assertTrue(res["result"]["allowedDownstreamRisk"])
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "medium")

    def test_suppress_timeline_feature_blocks_downstream_consumers(self):
        parametric = importlib.import_module("tools.parametric")
        original_dependencies = parametric.get_feature_dependencies
        mock_item = types.SimpleNamespace(name="FeatureA", isSuppressed=False)
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design
        parametric.get_feature_dependencies = lambda feature_name: {
            "result": {
                "featureName": feature_name,
                "likelyDownstreamConsumers": [{"timelineName": "CutB"}],
            }
        }
        try:
            res = self.tools.execute_tool("suppress_timeline_feature", {
                "name": "FeatureA",
                "reason": "Temporarily isolate feature.",
            })
        finally:
            parametric.get_feature_dependencies = original_dependencies

        self.assertIn("error", res)
        self.assertFalse(mock_item.isSuppressed)

    def test_suppress_timeline_feature_allows_override_and_returns_state_comparison(self):
        parametric = importlib.import_module("tools.parametric")
        original_dependencies = parametric.get_feature_dependencies
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        mock_item = types.SimpleNamespace(name="FeatureA", isSuppressed=False)
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design
        parametric.get_feature_dependencies = lambda feature_name: {
            "result": {"featureName": feature_name, "likelyDownstreamConsumers": [{"timelineName": "CutB"}]}
        }
        parametric._design_state_snapshot = lambda include_selections=False: {
            "timeline": {"items": [{"name": "FeatureA", "isSuppressed": mock_item.isSuppressed}]}
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "medium", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("suppress_timeline_feature", {
                "name": "FeatureA",
                "reason": "User approved temporary suppression.",
                "allow_downstream_risk": True,
            })
        finally:
            parametric.get_feature_dependencies = original_dependencies
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertTrue(mock_item.isSuppressed)
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "medium")

    def test_edit_sketch_dimension(self):
        mock_param = types.SimpleNamespace(name="d1", expression="10 cm", value=10.0)
        mock_dim = types.SimpleNamespace(parameter=mock_param)
        mock_sketch = types.SimpleNamespace(name="TestSketch", sketchDimensions=types.SimpleNamespace(
            count=1,
            item=lambda idx: mock_dim
        ))

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[]
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("edit_sketch_dimension", {
            "sketch_name": "TestSketch",
            "parameter_name": "d1",
            "expression": "15 cm"
        })
        self.assertIn("result", res)
        self.assertEqual(mock_param.expression, "15 cm")

    def test_delete_sketch_dimension_requires_reason(self):
        deleted = []
        mock_param = types.SimpleNamespace(name="d1", expression="10 cm", value=10.0)
        mock_dim = types.SimpleNamespace(parameter=mock_param, deleteMe=lambda: deleted.append(True))
        mock_sketch = types.SimpleNamespace(name="TestSketch", sketchDimensions=types.SimpleNamespace(
            count=1,
            item=lambda idx: mock_dim
        ))

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[]
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("delete_sketch_dimension", {
            "sketch_name": "TestSketch",
            "parameter_name": "d1"
        })
        self.assertIn("error", res)
        self.assertIn("reason is required", res["error"])
        self.assertEqual(deleted, [])

    def test_delete_sketch_dimension(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        deleted = []
        mock_param = types.SimpleNamespace(name="d1", expression="10 cm", value=10.0)
        mock_dim = types.SimpleNamespace(parameter=mock_param, deleteMe=lambda: deleted.append(True))
        mock_sketch = types.SimpleNamespace(name="TestSketch", sketchDimensions=types.SimpleNamespace(
            count=1,
            item=lambda idx: mock_dim
        ))

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[]
            )
        )
        _fake_app.activeProduct = self.mock_design

        parametric._design_state_snapshot = lambda include_selections=False: {
            "counts": {"sketchDimensions": 1 - len(deleted)}
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("delete_sketch_dimension", {
                "sketch_name": "TestSketch",
                "parameter_name": "d1",
                "reason": "Remove obsolete driving dimension.",
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare
        self.assertIn("result", res)
        self.assertTrue(deleted)
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_add_sketch_constraint_midpoint(self):
        added = []
        mock_constraints = types.SimpleNamespace(
            addMidPoint=lambda e1, e2: added.append(("midpoint", e1, e2))
        )
        mock_sketch = types.SimpleNamespace(
            name="TestSketch",
            sketchPoints=types.SimpleNamespace(count=1, item=lambda idx: "point1"),
            sketchCurves=types.SimpleNamespace(count=1, item=lambda idx: "line1"),
            geometricConstraints=mock_constraints
        )

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[]
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("add_sketch_constraint", {
            "sketch_name": "TestSketch",
            "constraint_type": "midpoint",
            "use_selection": False,
            "entity_indices": [0, 1]
        })
        self.assertIn("result", res)
        self.assertEqual(added, [("midpoint", "point1", "line1")])

    def test_combine_bodies(self):
        added_combines = []
        class MockCombineFeatures:
            def createInput(self, target, tools):
                self.target = target
                self.tools = tools
                return self
            def add(self, input_obj):
                added_combines.append(input_obj)
                return types.SimpleNamespace(name="Combine_Target")

        mock_target = types.SimpleNamespace(name="TargetBody")
        mock_tool = types.SimpleNamespace(name="ToolBody")

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[mock_target, mock_tool],
                allOccurrences=[],
                features=types.SimpleNamespace(combineFeatures=MockCombineFeatures())
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("combine_bodies", {
            "target_body_name": "TargetBody",
            "tool_body_names": ["ToolBody"],
            "operation": "join"
        })
        self.assertIn("result", res)
        self.assertEqual(len(added_combines), 1)
        self.assertEqual(added_combines[0].target, mock_target)

    def test_reorganize_body_to_component(self):
        moved = []
        mock_body = types.SimpleNamespace(
            name="Body1",
            moveToComponent=lambda occ: moved.append(occ)
        )
        mock_target_occ = types.SimpleNamespace(
            name="TargetOcc",
            component=types.SimpleNamespace(name="TargetComp")
        )

        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[mock_body],
                allOccurrences=[mock_target_occ]
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("reorganize_body_to_component", {
            "body_name": "Body1",
            "target_component_name": "TargetComp"
        })
        self.assertIn("result", res)
        self.assertEqual(moved, [mock_target_occ])


if __name__ == "__main__":
    unittest.main()
