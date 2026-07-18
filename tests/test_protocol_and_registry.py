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
        "ConstructionAxis",
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
        self.mcp_server.sessions.clear()
        self.mcp_server.http_sessions.clear()
        self.mcp_server.subscriptions.clear()
        self.task_manager.TaskManager._pending_tasks.clear()
        self.task_manager.TaskManager._is_running = False
        self.task_manager.TaskManager.TASK_TIMEOUT_SECONDS = 60.0
        self.task_manager.TaskManager.MAX_PENDING_TASKS = 8
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.mcp_server.discovery_file_path = lambda: os.path.join(self.temp_dir.name, ".fusion_mcp.json")
        self.mcp_server.runtime_dir_path = lambda: self.temp_dir.name

    def test_addin_entrypoint_imports_with_fallback(self):
        addin = importlib.import_module("FusionMCP")
        self.assertTrue(callable(addin.start_task_manager))
        self.assertTrue(callable(addin.stop_task_manager))

    def test_server_tools_import_shim_resolves_registry(self):
        tools_module = self.mcp_server.import_tools_module()
        self.assertTrue(callable(tools_module.get_tool_schemas))
        self.assertIn("inspect_design", {tool["name"] for tool in tools_module.get_tool_schemas()})

    def test_get_assembly_references_reports_origins_and_occurrences(self):
        def ref(name):
            return types.SimpleNamespace(name=name, entityToken=f"{name}-token", objectType="Ref")

        def plane(name):
            geometry = types.SimpleNamespace(
                origin=types.SimpleNamespace(x=1, y=2, z=3),
                normal=types.SimpleNamespace(x=0, y=0, z=1),
                uDirection=types.SimpleNamespace(x=1, y=0, z=0),
                vDirection=types.SimpleNamespace(x=0, y=1, z=0),
            )
            return types.SimpleNamespace(
                name=name,
                entityToken=f"{name}-token",
                objectType="ConstructionPlane",
                geometry=geometry,
                isLightBulbOn=True,
                isVisible=True,
            )

        child_component = types.SimpleNamespace(
            name="Child",
            xConstructionAxis=ref("Child X"),
            yConstructionAxis=ref("Child Y"),
            zConstructionAxis=ref("Child Z"),
            xYConstructionPlane=ref("Child XY"),
            xZConstructionPlane=ref("Child XZ"),
            yZConstructionPlane=ref("Child YZ"),
            originConstructionPoint=ref("Child Origin"),
            constructionAxes=[ref("Child Axis")],
            constructionPlanes=[plane("Child Plane")],
            constructionPoints=[ref("Child Point")],
        )
        transform = types.SimpleNamespace(asArray=lambda: [1, 0, 0, 0])
        occurrence = types.SimpleNamespace(name="Child:1", component=child_component, transform=transform)
        root = types.SimpleNamespace(
            name="Root",
            xConstructionAxis=ref("Root X"),
            yConstructionAxis=ref("Root Y"),
            zConstructionAxis=ref("Root Z"),
            xYConstructionPlane=ref("Root XY"),
            xZConstructionPlane=ref("Root XZ"),
            yZConstructionPlane=ref("Root YZ"),
            originConstructionPoint=ref("Root Origin"),
            constructionAxes=[],
            constructionPlanes=[],
            constructionPoints=[],
            allOccurrences=[occurrence],
        )
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("get_assembly_references", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["componentCount"], 2)
        self.assertEqual(res["result"]["components"][0]["origin"]["xAxis"]["name"], "Root X")
        self.assertEqual(res["result"]["components"][1]["constructionPoints"][0]["name"], "Child Point")
        self.assertEqual(res["result"]["components"][1]["constructionPlanes"][0]["name"], "Child Plane")
        self.assertEqual(res["result"]["components"][1]["constructionPlanes"][0]["normal"], [0, 0, 1])
        self.assertEqual(res["result"]["occurrences"][0]["componentName"], "Child")

    def test_get_assembly_joints_reports_joints_and_as_built_joints(self):
        joint = types.SimpleNamespace(
            name="RigidA",
            objectType="Joint",
            entityToken="joint-token",
            isLightBulbOn=True,
            isSuppressed=False,
            healthState=0,
            jointMotion=types.SimpleNamespace(
                objectType="RigidJointMotion",
                jointType="rigid",
                rotationLimits=types.SimpleNamespace(
                    isMinimumValueEnabled=True,
                    minimumValue=0.0,
                    isMaximumValueEnabled=True,
                    maximumValue=1.57,
                ),
            ),
            occurrenceOne=types.SimpleNamespace(name="OccA", entityToken="occ-a-token", objectType="Occurrence"),
            occurrenceTwo=types.SimpleNamespace(name="OccB", entityToken="occ-b-token", objectType="Occurrence"),
            geometryOrOriginOne=types.SimpleNamespace(name="PointA", entityToken="point-a-token", objectType="ConstructionPoint"),
            geometryOrOriginTwo=types.SimpleNamespace(name="PointB", entityToken="point-b-token", objectType="ConstructionPoint"),
        )
        as_built = types.SimpleNamespace(
            name="AsBuiltA",
            objectType="AsBuiltJoint",
            entityToken="as-built-token",
            jointMotion=types.SimpleNamespace(objectType="RigidJointMotion", jointType="rigid"),
        )
        root = types.SimpleNamespace(
            name="Root",
            joints=[joint],
            asBuiltJoints=[as_built],
        )
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("get_assembly_joints", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["jointCount"], 1)
        self.assertEqual(res["result"]["asBuiltJointCount"], 1)
        self.assertEqual(res["result"]["joints"][0]["name"], "RigidA")
        self.assertEqual(res["result"]["joints"][0]["occurrenceOne"]["name"], "OccA")
        self.assertEqual(res["result"]["joints"][0]["jointMotion"]["rotationLimits"]["maximumValue"], 1.57)
        self.assertEqual(res["result"]["asBuiltJoints"][0]["name"], "AsBuiltA")

    def test_plan_joint_limits_requires_target_expressions_and_reason(self):
        root = types.SimpleNamespace(name="Root", joints=[], asBuiltJoints=[])
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("plan_joint_limits", {"limit_type": "rotation"})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("joint_name or joint_entity_token is required", joined)
        self.assertIn("reason is required", joined)
        self.assertIn("minimum expression is required", joined)
        self.assertIn("maximum expression is required", joined)

    def test_plan_joint_limits_accepts_revolute_rotation_plan(self):
        joint = types.SimpleNamespace(
            name="DoorHinge",
            objectType="Joint",
            entityToken="joint-token",
            isLightBulbOn=True,
            isSuppressed=False,
            healthState=0,
            jointMotion=types.SimpleNamespace(
                objectType="RevoluteJointMotion",
                jointType="revolute",
                rotationLimits=types.SimpleNamespace(
                    isMinimumValueEnabled=False,
                    minimumValue=0.0,
                    isMaximumValueEnabled=False,
                    maximumValue=0.0,
                ),
            ),
        )
        root = types.SimpleNamespace(name="Root", joints=[joint], asBuiltJoints=[])
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("plan_joint_limits", {
            "joint_name": "DoorHinge",
            "limit_type": "rotation",
            "minimum": "0 deg",
            "maximum": "110 deg",
            "reason": "Limit hinge travel to avoid component collision.",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["joint"]["name"], "DoorHinge")
        self.assertEqual(res["result"]["limitType"], "rotation")
        self.assertEqual(res["result"]["requestedLimits"]["maximum"], "110 deg")
        self.assertIn("does not edit assembly joints", " ".join(res["result"]["warnings"]))

    def test_set_joint_limits_reports_unsupported_missing_limit_object(self):
        joint = types.SimpleNamespace(
            name="DoorHinge",
            objectType="Joint",
            entityToken="joint-token",
            jointMotion=types.SimpleNamespace(objectType="RevoluteJointMotion", jointType="revolute"),
        )
        root = types.SimpleNamespace(name="Root", joints=[joint], asBuiltJoints=[])
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("set_joint_limits", {
            "joint_name": "DoorHinge",
            "limit_type": "rotation",
            "minimum": "0 deg",
            "maximum": "90 deg",
            "reason": "Unit test unsupported path.",
        })

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])
        self.assertIn("did not expose rotationLimits", res["error"])

    def test_set_joint_limits_updates_writable_limit_expressions(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state

        minimum_value = types.SimpleNamespace(expression="0 deg")
        maximum_value = types.SimpleNamespace(expression="180 deg")
        limits = types.SimpleNamespace(
            isMinimumValueEnabled=False,
            minimumValue=minimum_value,
            isMaximumValueEnabled=False,
            maximumValue=maximum_value,
            isRestValueEnabled=False,
            restValue=types.SimpleNamespace(expression="45 deg"),
        )
        joint = types.SimpleNamespace(
            name="DoorHinge",
            objectType="Joint",
            entityToken="joint-token",
            isLightBulbOn=True,
            isSuppressed=False,
            healthState=0,
            jointMotion=types.SimpleNamespace(
                objectType="RevoluteJointMotion",
                jointType="revolute",
                rotationLimits=limits,
            ),
        )
        root = types.SimpleNamespace(name="Root", joints=[joint], asBuiltJoints=[])
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design
        parametric._design_state_snapshot = lambda include_selections=False: {
            "counts": {"joints": 1},
            "components": [],
            "bodies": [],
            "sketches": [],
            "parameters": {"user": [], "model": []},
            "timeline": {"items": [], "unhealthyItems": []},
            "document": {"active": {"isModified": False}},
            "design": {"designType": "ParametricDesignType"},
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("set_joint_limits", {
                "joint_name": "DoorHinge",
                "limit_type": "rotation",
                "minimum": "0 deg",
                "maximum": "110 deg",
                "reason": "Limit hinge travel to avoid collision.",
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(minimum_value.expression, "0 deg")
        self.assertEqual(maximum_value.expression, "110 deg")
        self.assertTrue(limits.isMinimumValueEnabled)
        self.assertTrue(limits.isMaximumValueEnabled)
        self.assertEqual(res["result"]["applied"]["maximum"], "maximumValue.expression")
        self.assertTrue(res["result"]["stateComparison"]["hasChanges"])

    def test_create_rigid_joint_from_named_points(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        original_joint_geometry = getattr(sys.modules["adsk.fusion"], "JointGeometry", None)
        original_rigid_motion = getattr(sys.modules["adsk.fusion"], "RigidJointMotion", None)

        class MockJointInput:
            def __init__(self, geometry_one, geometry_two):
                self.geometry_one = geometry_one
                self.geometry_two = geometry_two
                self.isFlipped = False
                self.offsetX = None
                self.offsetY = None
                self.offsetZ = None
                self.motion_set = False
            def setAsRigidJointMotion(self):
                self.motion_set = True

        created_inputs = []
        class MockJoints:
            def createInput(self, geometry_one, geometry_two):
                joint_input = MockJointInput(geometry_one, geometry_two)
                created_inputs.append(joint_input)
                return joint_input
            def add(self, joint_input):
                return types.SimpleNamespace(name="", input=joint_input)

        point_a = types.SimpleNamespace(name="PointA", objectType="ConstructionPoint")
        point_b = types.SimpleNamespace(name="PointB", objectType="ConstructionPoint")
        root = types.SimpleNamespace(
            name="Root",
            joints=MockJoints(),
            constructionPoints=[point_a, point_b],
            sketches=[],
            allOccurrences=[],
        )
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design
        sys.modules["adsk.fusion"].JointGeometry = types.SimpleNamespace(
            createByPoint=lambda point: types.SimpleNamespace(point=point)
        )
        sys.modules["adsk.fusion"].RigidJointMotion = types.SimpleNamespace(create=lambda: types.SimpleNamespace())
        parametric._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": len(created_inputs)}
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("create_rigid_joint", {
                "name": "RigidA",
                "point_one_name": "PointA",
                "point_two_name": "PointB",
                "flip": True,
                "offset_z": "2 mm",
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare
            if original_joint_geometry is None:
                delattr(sys.modules["adsk.fusion"], "JointGeometry")
            else:
                sys.modules["adsk.fusion"].JointGeometry = original_joint_geometry
            if original_rigid_motion is None:
                delattr(sys.modules["adsk.fusion"], "RigidJointMotion")
            else:
                sys.modules["adsk.fusion"].RigidJointMotion = original_rigid_motion

        self.assertIn("result", res)
        self.assertEqual(res["result"]["jointName"], "RigidA")
        self.assertEqual(created_inputs[0].geometry_one.point, point_a)
        self.assertEqual(created_inputs[0].geometry_two.point, point_b)
        self.assertTrue(created_inputs[0].motion_set)
        self.assertTrue(created_inputs[0].isFlipped)
        self.assertEqual(created_inputs[0].offsetZ, "2 mm")
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_create_section_analysis_from_standard_plane(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state

        created_inputs = []
        analyses = []
        class MockSectionInput:
            def __init__(self):
                self.plane = None
            def setByPlane(self, plane):
                self.plane = plane

        class MockSectionAnalyses:
            def __init__(self):
                self.count = 0
            def createInput(self):
                return MockSectionInput()
            def add(self, section_input):
                created_inputs.append(section_input)
                analysis = types.SimpleNamespace(name="", isLightBulbOn=False, objectType="SectionAnalysis", entityToken="section-token")
                analyses.append(analysis)
                self.count = len(analyses)
                return analysis
            def item(self, idx):
                return analyses[idx]

        plane = types.SimpleNamespace(name="XY")
        root = types.SimpleNamespace(
            name="Root",
            xYConstructionPlane=plane,
            xZConstructionPlane=types.SimpleNamespace(name="XZ"),
            yZConstructionPlane=types.SimpleNamespace(name="YZ"),
            constructionPlanes=[],
            allOccurrences=[],
            sectionAnalyses=MockSectionAnalyses(),
        )
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        parametric._design_state_snapshot = lambda include_selections=False: {"analysisCount": len(analyses)}
        parametric.compare_design_state = lambda before, after: {"result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}}
        try:
            res = self.tools.execute_tool("create_section_analysis", {
                "name": "Cutaway A",
                "plane_name": "xy",
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(created_inputs[0].plane, plane)
        self.assertEqual(analyses[0].name, "Cutaway A")
        self.assertTrue(analyses[0].isLightBulbOn)
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_create_section_analysis_reports_unsupported_runtime(self):
        root = types.SimpleNamespace(
            name="Root",
            xYConstructionPlane=types.SimpleNamespace(name="XY"),
            xZConstructionPlane=types.SimpleNamespace(name="XZ"),
            yZConstructionPlane=types.SimpleNamespace(name="YZ"),
            constructionPlanes=[],
            allOccurrences=[],
        )
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("create_section_analysis", {"name": "Cutaway A"})

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])

    def test_delete_section_analysis_requires_reason_and_deletes_named_items(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state

        deleted = []
        analysis = types.SimpleNamespace(name="Cutaway A", deleteMe=lambda: deleted.append("Cutaway A"))
        class MockSectionAnalyses:
            count = 1
            def item(self, idx):
                return analysis

        root = types.SimpleNamespace(name="Root", sectionAnalyses=MockSectionAnalyses())
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        missing_reason = self.tools.execute_tool("delete_section_analysis", {"name": "Cutaway A"})
        self.assertIn("reason is required", missing_reason["error"])

        parametric._design_state_snapshot = lambda include_selections=False: {"deleted": list(deleted)}
        parametric.compare_design_state = lambda before, after: {"result": {"hasChanges": True, "riskLevel": "low"}}
        try:
            res = self.tools.execute_tool("delete_section_analysis", {
                "name": "Cutaway A",
                "reason": "Cleanup temporary inspection section.",
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(deleted, ["Cutaway A"])
        self.assertEqual(res["result"]["deletedCount"], 1)

    def _install_motion_joint_fixture(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        original_joint_geometry = getattr(sys.modules["adsk.fusion"], "JointGeometry", None)

        class MockJointInput:
            def __init__(self, geometry_one, geometry_two):
                self.geometry_one = geometry_one
                self.geometry_two = geometry_two
                self.isFlipped = False
                self.motion_calls = []
                self.offsetX = None
                self.offsetY = None
                self.offsetZ = None
            def setAsRevoluteJointMotion(self, axis):
                self.motion_calls.append(("revolute", axis))
            def setAsSliderJointMotion(self, direction):
                self.motion_calls.append(("slider", direction))
            def setAsCylindricalJointMotion(self, axis):
                self.motion_calls.append(("cylindrical", axis))
            def setAsPinSlotJointMotion(self, axis, direction):
                self.motion_calls.append(("pin_slot", axis, direction))
            def setAsPlanarJointMotion(self, normal):
                self.motion_calls.append(("planar", normal))
            def setAsBallJointMotion(self):
                self.motion_calls.append(("ball",))

        created_inputs = []
        class MockJoints:
            def createInput(self, geometry_one, geometry_two):
                joint_input = MockJointInput(geometry_one, geometry_two)
                created_inputs.append(joint_input)
                return joint_input
            def add(self, joint_input):
                return types.SimpleNamespace(name="", input=joint_input)

        point_a = types.SimpleNamespace(name="PointA", objectType="ConstructionPoint")
        point_b = types.SimpleNamespace(name="PointB", objectType="ConstructionPoint")
        root = types.SimpleNamespace(
            name="Root",
            joints=MockJoints(),
            constructionPoints=[point_a, point_b],
            sketches=[],
            allOccurrences=[],
        )
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design
        sys.modules["adsk.fusion"].JointGeometry = types.SimpleNamespace(
            createByPoint=lambda point: types.SimpleNamespace(point=point)
        )
        parametric._design_state_snapshot = lambda include_selections=False: {
            "counts": {"createdJointInputs": len(created_inputs)}
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }

        def cleanup():
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare
            if original_joint_geometry is None:
                delattr(sys.modules["adsk.fusion"], "JointGeometry")
            else:
                sys.modules["adsk.fusion"].JointGeometry = original_joint_geometry

        return created_inputs, cleanup

    def test_create_motion_joint_tools_set_expected_motion(self):
        cases = [
            ("create_revolute_joint", {"motion_axis": "z"}, ("revolute", "z")),
            ("create_slider_joint", {"slide_direction": "x"}, ("slider", "x")),
            ("create_cylindrical_joint", {"motion_axis": "y"}, ("cylindrical", "y")),
            ("create_pin_slot_joint", {"motion_axis": "z", "slide_direction": "x"}, ("pin_slot", "z", "x")),
            ("create_planar_joint", {"normal_direction": "z"}, ("planar", "z")),
            ("create_ball_joint", {}, ("ball",)),
        ]
        for tool_name, args, expected_motion in cases:
            with self.subTest(tool=tool_name):
                created_inputs, cleanup = self._install_motion_joint_fixture()
                try:
                    res = self.tools.execute_tool(tool_name, {
                        "name": f"{tool_name}_A",
                        "point_one_name": "PointA",
                        "point_two_name": "PointB",
                        "offset_z": "1 mm",
                        **args,
                    })
                finally:
                    cleanup()

                self.assertIn("result", res)
                self.assertEqual(created_inputs[0].motion_calls[0], expected_motion)
                self.assertEqual(created_inputs[0].offsetZ, "1 mm")
                self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_create_revolute_joint_requires_explicit_axis(self):
        created_inputs, cleanup = self._install_motion_joint_fixture()
        try:
            res = self.tools.execute_tool("create_revolute_joint", {
                "name": "RevoluteA",
                "point_one_name": "PointA",
                "point_two_name": "PointB",
            })
        finally:
            cleanup()

        self.assertIn("error", res)
        self.assertIn("Explicit joint direction is required", res["error"])
        self.assertEqual(len(created_inputs), 1)

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

    def test_antigravity_config_sync_updates_stale_server_url(self):
        config_path = os.path.join(self.temp_dir.name, "mcp_config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({
                "mcpServers": {
                    "autodesk-fusion-mcp": {
                        "serverUrl": "http://127.0.0.1:9100/sse?token=stale-token",
                        "disabled": True,
                    },
                    "other-server": {
                        "serverUrl": "http://127.0.0.1:9999/sse?token=leave-alone",
                    },
                }
            }, f)

        original_config_path = self.mcp_server.antigravity_config_path
        self.mcp_server.antigravity_config_path = lambda: config_path
        try:
            result = self.mcp_server.sync_antigravity_mcp_config(
                "http://127.0.0.1:9100/sse?token=live-token"
            )
        finally:
            self.mcp_server.antigravity_config_path = original_config_path

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        fusion_config = config["mcpServers"]["autodesk-fusion-mcp"]
        self.assertEqual(result["status"], "updated")
        self.assertEqual(fusion_config["serverUrl"], "http://127.0.0.1:9100/sse?token=live-token")
        self.assertFalse(fusion_config["disabled"])
        self.assertEqual(
            config["mcpServers"]["other-server"]["serverUrl"],
            "http://127.0.0.1:9999/sse?token=leave-alone",
        )

    def test_antigravity_config_sync_skips_missing_config(self):
        missing_path = os.path.join(self.temp_dir.name, "missing.json")
        original_config_path = self.mcp_server.antigravity_config_path
        self.mcp_server.antigravity_config_path = lambda: missing_path
        try:
            result = self.mcp_server.sync_antigravity_mcp_config(
                "http://127.0.0.1:9100/sse?token=live-token"
            )
        finally:
            self.mcp_server.antigravity_config_path = original_config_path

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "config_missing")

    def test_antigravity_config_sync_accepts_utf8_bom_config(self):
        config_path = os.path.join(self.temp_dir.name, "mcp_config_bom.json")
        with open(config_path, "w", encoding="utf-8-sig") as f:
            json.dump({
                "mcpServers": {
                    "autodesk-fusion-mcp": {
                        "serverUrl": "http://127.0.0.1:9100/sse?token=stale-token",
                        "disabled": False,
                    }
                }
            }, f)

        original_config_path = self.mcp_server.antigravity_config_path
        self.mcp_server.antigravity_config_path = lambda: config_path
        try:
            result = self.mcp_server.sync_antigravity_mcp_config(
                "http://127.0.0.1:9100/sse?token=live-token"
            )
        finally:
            self.mcp_server.antigravity_config_path = original_config_path

        self.assertEqual(result["status"], "updated")
        with open(config_path, "r", encoding="utf-8-sig") as f:
            config = json.load(f)
        self.assertEqual(
            config["mcpServers"]["autodesk-fusion-mcp"]["serverUrl"],
            "http://127.0.0.1:9100/sse?token=live-token",
        )

    def test_change_journal_redacts_sensitive_and_long_arguments(self):
        redacted = self.mcp_server._redact_journal_value({
            "token": "secret",
            "authorization_header": "Bearer secret",
            "script": "print('x')",
            "note": "x" * 400,
        })

        self.assertEqual(redacted["token"], "<redacted>")
        self.assertEqual(redacted["authorization_header"], "<redacted>")
        self.assertIn("<script redacted:", redacted["script"])
        self.assertIn("<truncated", redacted["note"])

    def test_change_journal_append_read_and_clear(self):
        self.mcp_server.append_change_journal({
            "kind": "tools/call",
            "tool": "doctor",
            "arguments": {},
            "isError": False,
            "durationMs": 5,
            "changedDesign": False,
        })

        entries = self.mcp_server.read_change_journal()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["tool"], "doctor")
        self.assertFalse(entries[0]["isError"])

        self.assertTrue(self.mcp_server.clear_change_journal())
        self.assertEqual(self.mcp_server.read_change_journal(), [])

    def test_tool_call_journal_records_raw_script_state_changes(self):
        original_import_tools = self.mcp_server.import_tools_module
        session_id = "journal-session"
        self.mcp_server.sessions[session_id] = queue.Queue()

        class FakeTools:
            @staticmethod
            def execute_tool(name, arguments):
                return {
                    "result": "Script executed",
                    "output": "changed",
                    "stateComparison": {"hasChanges": True},
                }

        self.mcp_server.import_tools_module = lambda: FakeTools
        try:
            self.mcp_server.execute_mcp_request_main_thread(
                session_id,
                42,
                "tools/call",
                {"name": "run_fusion_script", "arguments": {"script": "redacted"}},
            )
            response = self.mcp_server.sessions[session_id].get(timeout=1)
        finally:
            self.mcp_server.import_tools_module = original_import_tools
            self.mcp_server.sessions.pop(session_id, None)

        self.assertIn("Script executed", json.loads(response)["result"]["content"][0]["text"])
        entries = self.mcp_server.read_change_journal()
        self.assertEqual(entries[-1]["tool"], "run_fusion_script")
        self.assertTrue(entries[-1]["changedDesign"])

    def test_task_manager_wrappers_post_and_execute(self):
        self.assertTrue(self.task_manager.start_task_manager())
        called = []
        task_id = self.task_manager.TaskManager.post("test", lambda data: called.append(data["ok"]), {"ok": True})
        self.assertIsNotNone(task_id)
        self.assertEqual(called, [True])
        self.assertTrue(self.task_manager.stop_task_manager())

    def test_task_manager_prunes_stale_pending_tasks(self):
        manager = self.task_manager.TaskManager
        manager._pending_tasks["stale"] = {
            "command": "mcp_request",
            "callback": lambda _data: None,
            "data": {},
            "created_at": 1000.0,
        }
        manager._pending_tasks["fresh"] = {
            "command": "mcp_request",
            "callback": lambda _data: None,
            "data": {},
            "created_at": 1059.5,
        }

        removed = manager.prune_stale_tasks(now=1061.0)

        self.assertEqual(removed, 1)
        self.assertNotIn("stale", manager._pending_tasks)
        self.assertIn("fresh", manager._pending_tasks)

    def test_task_manager_pending_stats_reports_backpressure(self):
        manager = self.task_manager.TaskManager
        manager.MAX_PENDING_TASKS = 1
        manager._pending_tasks["pending"] = {
            "command": "mcp_request",
            "callback": lambda _data: None,
            "data": {},
            "created_at": 1000.0,
        }

        stats = manager.get_pending_task_stats(now=1005.0)

        self.assertEqual(stats["pendingTasks"], 1)
        self.assertEqual(stats["oldestTaskAgeSeconds"], 5.0)
        self.assertTrue(stats["backpressureActive"])

    def test_task_manager_rejects_new_task_under_backpressure(self):
        manager = self.task_manager.TaskManager
        manager._is_running = True
        manager._custom_event = types.SimpleNamespace(eventId="FusionMCP.TaskManagerEvent")
        manager.MAX_PENDING_TASKS = 1
        manager._pending_tasks["pending"] = {
            "command": "mcp_request",
            "callback": lambda _data: None,
            "data": {},
            "created_at": time.time(),
        }

        task_id = manager.post("mcp_request", lambda _data: None, {})

        self.assertIsNone(task_id)
        self.assertEqual(len(manager._pending_tasks), 1)

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

    def test_tool_first_prompt_warns_against_script_shortcuts(self):
        response = self.mcp_server.handle_prompt_get(24, "tool_first_workflow", {})
        self.assertEqual(response["id"], 24)
        text = response["result"]["messages"][0]["content"]["text"]
        self.assertIn("Use structured FusionMCP tools first", text)
        self.assertIn("doctor", text)
        self.assertIn("recommend_mcp_workflow", text)
        self.assertIn("fusion://agent/tool-first-workflow", text)
        self.assertIn("plan_parameterization", text)
        self.assertIn("script_intent", text)
        self.assertIn("mcp_tool_gap", text)

    def test_domain_workflow_prompts_are_registered_and_tool_first(self):
        prompt_names = {prompt["name"] for prompt in self.mcp_server.PROMPTS}
        for prompt_name in [
            "threaded_fastener_workflow",
            "sheet_metal_enclosure_workflow",
            "printability_review",
            "physical_properties_review",
        ]:
            self.assertIn(prompt_name, prompt_names)

        fastener = self.mcp_server.handle_prompt_get(
            25,
            "threaded_fastener_workflow",
            {"diameter": "M4", "length": "16 mm"},
        )
        fastener_text = fastener["result"]["messages"][0]["content"]["text"]
        self.assertIn("M4", fastener_text)
        self.assertIn("16 mm", fastener_text)
        self.assertIn("create_hole_pattern", fastener_text)
        self.assertIn("inspect_printability", fastener_text)
        self.assertIn("tool gap", fastener_text)

        sheet_metal = self.mcp_server.handle_prompt_get(26, "sheet_metal_enclosure_workflow", {})
        sheet_text = sheet_metal["result"]["messages"][0]["content"]["text"]
        self.assertIn("get_physical_properties", sheet_text)
        self.assertIn("do not invent flange, bend, unfold, or flat-pattern tools", sheet_text)

        printability = self.mcp_server.handle_prompt_get(27, "printability_review", {})
        printability_text = printability["result"]["messages"][0]["content"]["text"]
        self.assertIn("get_physical_properties", printability_text)
        self.assertIn("inspect_printability", printability_text)
        self.assertIn("preflight_export", printability_text)

        physical = self.mcp_server.handle_prompt_get(28, "physical_properties_review", {})
        physical_text = physical["result"]["messages"][0]["content"]["text"]
        self.assertIn("Call get_physical_properties", physical_text)
        self.assertIn("read-only", physical_text)

    def test_tool_first_resource_returns_agent_policy(self):
        resource = self.tools.read_resource("fusion://agent/tool-first-workflow")
        self.assertEqual(resource["mandatoryFirstStep"], "doctor")
        self.assertIn("parameterize_existing_model", resource["workflows"])
        self.assertIn("preflight_export", resource["workflows"]["export"]["firstTools"])
        self.assertEqual(resource["rawScriptPolicy"]["tool"], "run_fusion_script")

    def test_tool_profiles_resource_groups_registered_tools(self):
        resource = self.tools.read_resource("fusion://agent/tool-profiles")
        self.assertEqual(resource["schemaVersion"], 1)
        self.assertIn("core", resource["profiles"])
        self.assertIn("dangerous", resource["profiles"])
        self.assertIn("docs", resource["profiles"])
        self.assertIn("presentation", resource["profiles"])
        self.assertIn("document", resource["profiles"])
        self.assertIn("doctor", resource["profiles"]["core"]["tools"])
        self.assertIn("get_change_journal", resource["profiles"]["core"]["tools"])
        self.assertIn("search_local_fusion_docs", resource["profiles"]["docs"]["tools"])
        self.assertIn("run_fusion_script", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("clear_change_journal", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("get_assembly_references", resource["profiles"]["inspection"]["tools"])
        self.assertIn("get_assembly_joints", resource["profiles"]["inspection"]["tools"])
        self.assertIn("plan_joint_limits", resource["profiles"]["inspection"]["tools"])
        self.assertIn("get_physical_properties", resource["profiles"]["inspection"]["tools"])
        self.assertIn("inspect_analysis_capabilities", resource["profiles"]["inspection"]["tools"])
        self.assertIn("interference_check", resource["profiles"]["inspection"]["tools"])
        self.assertIn("clearance_check", resource["profiles"]["inspection"]["tools"])
        self.assertIn("verify_insert_alignment", resource["profiles"]["inspection"]["tools"])
        self.assertIn("verify_insert_alignment", resource["profiles"]["export"]["tools"])
        self.assertIn("exact_interference_check", resource["profiles"]["inspection"]["tools"])
        self.assertIn("exact_clearance_check", resource["profiles"]["inspection"]["tools"])
        self.assertIn("inspect_sheet_metal_rules", resource["profiles"]["inspection"]["tools"])
        self.assertIn("preflight_flat_pattern", resource["profiles"]["inspection"]["tools"])
        self.assertIn("plan_sheet_metal_workflow", resource["profiles"]["inspection"]["tools"])
        self.assertIn("export_flat_pattern", resource["profiles"]["export"]["tools"])
        self.assertIn("inspect_surface_bodies", resource["profiles"]["inspection"]["tools"])
        self.assertIn("plan_surface_repair", resource["profiles"]["inspection"]["tools"])
        self.assertIn("inspect_drawing_documents", resource["profiles"]["inspection"]["tools"])
        self.assertIn("preflight_drawing_creation", resource["profiles"]["inspection"]["tools"])
        self.assertIn("plan_drawing_views", resource["profiles"]["inspection"]["tools"])
        self.assertIn("plan_drawing_views", resource["profiles"]["export"]["tools"])
        self.assertIn("add_drawing_view", resource["profiles"]["export"]["tools"])
        self.assertIn("add_drawing_dimension", resource["profiles"]["export"]["tools"])
        self.assertIn("add_drawing_callout", resource["profiles"]["export"]["tools"])
        self.assertIn("add_parts_list", resource["profiles"]["export"]["tools"])
        self.assertIn("add_revision_table", resource["profiles"]["export"]["tools"])
        self.assertIn("plan_multicolor_3mf_export", resource["profiles"]["export"]["tools"])
        self.assertIn("inspect_manufacturing_workspace", resource["profiles"]["inspection"]["tools"])
        self.assertIn("list_manufacturing_setups", resource["profiles"]["inspection"]["tools"])
        self.assertIn("inspect_operation", resource["profiles"]["inspection"]["tools"])
        self.assertIn("plan_manufacturing_operation", resource["profiles"]["inspection"]["tools"])
        self.assertIn("create_manufacturing_setup", resource["profiles"]["manufacturing"]["tools"])
        self.assertIn("create_manufacturing_operation", resource["profiles"]["manufacturing"]["tools"])
        self.assertIn("generate_toolpaths", resource["profiles"]["manufacturing"]["tools"])
        self.assertIn("post_process", resource["profiles"]["manufacturing"]["tools"])
        self.assertIn("list_appearances", resource["profiles"]["inspection"]["tools"])
        self.assertIn("inspect_body_style", resource["profiles"]["inspection"]["tools"])
        self.assertIn("revolve_feature", resource["profiles"]["modeling"]["tools"])
        self.assertIn("loft_feature", resource["profiles"]["modeling"]["tools"])
        self.assertIn("sweep_feature", resource["profiles"]["modeling"]["tools"])
        self.assertIn("list_appearances", resource["profiles"]["modeling"]["tools"])
        self.assertIn("inspect_body_style", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_rigid_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_section_analysis", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_revolute_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_slider_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_cylindrical_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_pin_slot_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_planar_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_ball_joint", resource["profiles"]["modeling"]["tools"])
        self.assertIn("set_joint_limits", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_flange", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_bend", resource["profiles"]["modeling"]["tools"])
        self.assertIn("unfold_sheet_metal", resource["profiles"]["modeling"]["tools"])
        self.assertIn("refold_sheet_metal", resource["profiles"]["modeling"]["tools"])
        self.assertIn("copy_profile_loop", resource["profiles"]["modeling"]["tools"])
        self.assertIn("offset_profile_loop", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_insert_socket", resource["profiles"]["modeling"]["tools"])
        self.assertIn("extrude_existing_profile", resource["profiles"]["modeling"]["tools"])
        self.assertIn("patch_surface", resource["profiles"]["modeling"]["tools"])
        self.assertIn("stitch_surfaces", resource["profiles"]["modeling"]["tools"])
        self.assertIn("thicken_surface", resource["profiles"]["modeling"]["tools"])
        self.assertIn("trim_surface", resource["profiles"]["modeling"]["tools"])
        self.assertIn("extend_surface", resource["profiles"]["modeling"]["tools"])
        self.assertIn("create_ruled_surface", resource["profiles"]["modeling"]["tools"])
        self.assertIn("edit_extrude_feature", resource["profiles"]["parameters"]["tools"])
        self.assertIn("edit_fillet_radius", resource["profiles"]["parameters"]["tools"])
        self.assertIn("edit_chamfer_distance", resource["profiles"]["parameters"]["tools"])
        self.assertIn("edit_shell_thickness", resource["profiles"]["parameters"]["tools"])
        self.assertIn("edit_pattern_parameter", resource["profiles"]["parameters"]["tools"])
        self.assertIn("edit_hole_parameter", resource["profiles"]["parameters"]["tools"])
        self.assertIn("delete_sketch_constraint", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("delete_section_analysis", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("delete_named_experiment", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("set_active_document", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("close_active_document", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("set_timeline_marker", resource["profiles"]["dangerous"]["tools"])
        self.assertIn("capture_demo_sequence", resource["profiles"]["presentation"]["tools"])
        self.assertIn("list_documents", resource["profiles"]["document"]["tools"])
        self.assertIn("create_design_document", resource["profiles"]["document"]["tools"])
        advertised = {schema["name"] for schema in self.tools.get_tool_schemas()}
        profiled = set()
        for profile in resource["profiles"].values():
            profiled.update(profile["tools"])
        self.assertEqual(sorted(advertised - profiled), [])
        destructive = {
            name
            for name, schema in ((schema["name"], schema) for schema in self.tools.get_tool_schemas())
            if schema["annotations"]["destructiveHint"]
        }
        dangerous = set(resource["profiles"]["dangerous"]["tools"])
        for profile_name, profile in resource["profiles"].items():
            if profile_name == "dangerous":
                continue
            self.assertFalse(set(profile["tools"]) & destructive)
        self.assertTrue(destructive <= dangerous)
        for profile in resource["profiles"].values():
            self.assertEqual(profile["missingFromSchema"], [])
            self.assertEqual(profile["missingFromRegistry"], [])

    def test_server_capabilities_resource_describes_transports_and_safety(self):
        resource = self.tools.read_resource("fusion://agent/server-capabilities")
        self.assertEqual(resource["schemaVersion"], 1)
        self.assertEqual(resource["server"]["name"], "fusion-mcp")
        self.assertIn("doctor", resource["server"]["instructions"])
        self.assertIn("run_fusion_script only as a last resort", resource["server"]["instructions"])
        transport_names = {transport["name"] for transport in resource["transports"]}
        self.assertIn("streamable_http", transport_names)
        self.assertIn("http_sse", transport_names)
        streamable = next(transport for transport in resource["transports"] if transport["name"] == "streamable_http")
        self.assertEqual(streamable["endpoint"], "/mcp")
        self.assertEqual(resource["discovery"]["healthEndpoint"], "/health")
        self.assertTrue(resource["discovery"]["healthIsTokenFree"])
        self.assertEqual(resource["safety"]["rawScriptTool"], "run_fusion_script")
        self.assertIn("script_intent", resource["safety"]["rawScriptRequiredArguments"])
        self.assertEqual(resource["safety"]["guardedUndoTool"], "undo_last_action")
        self.assertIn("modeling", resource["profiles"])
        self.assertIn("tool_first_workflow", resource["prompts"])
        self.assertGreater(resource["counts"]["tools"], 0)
        self.assertEqual(resource["toolAnnotations"]["coverage"], resource["counts"]["tools"])
        self.assertIn("readOnlyHint", resource["toolAnnotations"]["fields"])
        self.assertEqual(resource["resourceAnnotations"]["coverage"], resource["counts"]["resources"])
        self.assertIn("priority", resource["resourceAnnotations"]["fields"])

    def test_tool_schemas_include_mcp_risk_annotations(self):
        schemas = {schema["name"]: schema for schema in self.tools.get_tool_schemas()}

        for name, schema in schemas.items():
            annotations = schema.get("annotations")
            self.assertIsInstance(annotations, dict, name)
            for key in ("title", "readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                self.assertIn(key, annotations, name)

        self.assertTrue(schemas["inspect_design"]["annotations"]["readOnlyHint"])
        self.assertFalse(schemas["inspect_design"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["plan_joint_limits"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["inspect_analysis_capabilities"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["interference_check"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["clearance_check"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["verify_insert_alignment"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["exact_interference_check"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["exact_clearance_check"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["inspect_sheet_metal_rules"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["preflight_flat_pattern"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["plan_sheet_metal_workflow"]["annotations"]["readOnlyHint"])
        for name in ("create_flange", "create_bend", "unfold_sheet_metal", "refold_sheet_metal"):
            self.assertFalse(schemas[name]["annotations"]["readOnlyHint"], name)
            self.assertFalse(schemas[name]["annotations"]["destructiveHint"], name)
            self.assertFalse(schemas[name]["annotations"]["idempotentHint"], name)
        self.assertFalse(schemas["export_flat_pattern"]["annotations"]["readOnlyHint"])
        self.assertFalse(schemas["export_flat_pattern"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["export_flat_pattern"]["annotations"]["idempotentHint"])
        self.assertTrue(schemas["inspect_surface_bodies"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["plan_surface_repair"]["annotations"]["readOnlyHint"])
        for name in ("patch_surface", "stitch_surfaces", "thicken_surface", "trim_surface", "extend_surface", "create_ruled_surface"):
            self.assertFalse(schemas[name]["annotations"]["readOnlyHint"], name)
            self.assertFalse(schemas[name]["annotations"]["destructiveHint"], name)
            self.assertFalse(schemas[name]["annotations"]["idempotentHint"], name)
        self.assertTrue(schemas["inspect_drawing_documents"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["preflight_drawing_creation"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["plan_drawing_views"]["annotations"]["readOnlyHint"])
        for name in ("add_drawing_view", "add_drawing_dimension", "add_drawing_callout", "add_parts_list", "add_revision_table"):
            self.assertFalse(schemas[name]["annotations"]["readOnlyHint"], name)
            self.assertFalse(schemas[name]["annotations"]["destructiveHint"], name)
            self.assertFalse(schemas[name]["annotations"]["idempotentHint"], name)
        self.assertTrue(schemas["inspect_manufacturing_workspace"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["list_manufacturing_setups"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["inspect_operation"]["annotations"]["readOnlyHint"])
        self.assertTrue(schemas["plan_manufacturing_operation"]["annotations"]["readOnlyHint"])
        for name in ("create_manufacturing_setup", "create_manufacturing_operation", "generate_toolpaths", "post_process"):
            self.assertFalse(schemas[name]["annotations"]["readOnlyHint"], name)
            self.assertFalse(schemas[name]["annotations"]["destructiveHint"], name)
            self.assertFalse(schemas[name]["annotations"]["idempotentHint"], name)
        self.assertTrue(schemas["set_parameter"]["annotations"]["idempotentHint"])
        self.assertTrue(schemas["set_joint_limits"]["annotations"]["idempotentHint"])
        self.assertFalse(schemas["set_joint_limits"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["edit_extrude_feature"]["annotations"]["idempotentHint"])
        self.assertFalse(schemas["edit_extrude_feature"]["annotations"]["destructiveHint"])
        self.assertFalse(schemas["create_box"]["annotations"]["idempotentHint"])
        self.assertFalse(schemas["create_box"]["annotations"]["readOnlyHint"])
        for name in ("copy_profile_loop", "offset_profile_loop", "create_insert_socket", "extrude_existing_profile"):
            self.assertFalse(schemas[name]["annotations"]["readOnlyHint"], name)
            self.assertFalse(schemas[name]["annotations"]["destructiveHint"], name)
            self.assertFalse(schemas[name]["annotations"]["idempotentHint"], name)
        self.assertFalse(schemas["create_design_document"]["annotations"]["readOnlyHint"])
        self.assertFalse(schemas["create_design_document"]["annotations"]["destructiveHint"])
        self.assertFalse(schemas["create_design_document"]["annotations"]["idempotentHint"])
        self.assertTrue(schemas["run_fusion_script"]["annotations"]["destructiveHint"])
        self.assertFalse(schemas["create_section_analysis"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["delete_section_analysis"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["delete_named_experiment"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["clear_change_journal"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["set_active_document"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["close_active_document"]["annotations"]["destructiveHint"])
        self.assertTrue(schemas["set_timeline_marker"]["annotations"]["destructiveHint"])
        self.assertFalse(schemas["search_local_fusion_docs"]["annotations"]["openWorldHint"])

    def test_resource_schemas_include_client_ranking_annotations(self):
        resources = {schema["uri"]: schema for schema in self.tools.get_resources_schemas()}
        templates = {schema["uriTemplate"]: schema for schema in self.tools.get_resource_templates()}

        for name, schema in {**resources, **templates}.items():
            annotations = schema.get("annotations")
            self.assertIsInstance(annotations, dict, name)
            self.assertEqual(annotations["audience"], ["assistant"])
            self.assertIsInstance(annotations["priority"], float, name)

        self.assertGreater(
            resources["fusion://agent/server-capabilities"]["annotations"]["priority"],
            resources["fusion://docs/fusion-api"]["annotations"]["priority"],
        )
        self.assertGreater(
            resources["fusion://design/summary"]["annotations"]["priority"],
            resources["fusion://runtime/change-journal"]["annotations"]["priority"],
        )
        self.assertEqual(templates["fusion://design/tree/{depth}"]["annotations"]["priority"], 0.85)

    def test_list_appearances_reports_design_and_library_matches(self):
        design_appearance = types.SimpleNamespace(
            name="Matte Black",
            objectType="Appearance",
            entityToken="design-black-token",
        )
        library_appearance = types.SimpleNamespace(
            name="Black Oxide",
            objectType="Appearance",
            entityToken="library-black-token",
        )
        library = types.SimpleNamespace(
            name="Fusion Library",
            appearances=[library_appearance],
        )
        self.mock_design = types.SimpleNamespace(
            appearances=[design_appearance],
            rootComponent=types.SimpleNamespace(),
        )
        _fake_app.activeProduct = self.mock_design
        _fake_app.materialLibraries = [library]

        res = self.tools.execute_tool("list_appearances", {
            "query": "black",
            "include_libraries": True,
            "limit": 10,
        })

        self.assertIn("result", res)
        self.assertEqual(res["result"]["count"], 2)
        names = [item["name"] for item in res["result"]["appearances"]]
        self.assertEqual(names, ["Matte Black", "Black Oxide"])
        self.assertEqual(res["result"]["appearances"][1]["libraryName"], "Fusion Library")

    def test_inspect_body_style_reports_appearance_and_material(self):
        appearance = types.SimpleNamespace(
            name="Satin Steel",
            objectType="Appearance",
            entityToken="appearance-token",
        )
        material = types.SimpleNamespace(
            name="Steel",
            objectType="PhysicalMaterial",
            entityToken="material-token",
        )
        body = types.SimpleNamespace(
            name="Bracket",
            isVisible=True,
            appearance=appearance,
            material=material,
            physicalMaterial=material,
        )
        component = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        self.mock_design = types.SimpleNamespace(rootComponent=component)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("inspect_body_style", {"body_name": "Bracket"})

        self.assertIn("result", res)
        report = res["result"]["bodies"][0]
        self.assertEqual(report["bodyName"], "Bracket")
        self.assertEqual(report["appearance"]["name"], "Satin Steel")
        self.assertEqual(report["physicalMaterial"]["entityToken"], "material-token")

    def test_inspect_body_style_accepts_entity_tokens(self):
        appearance = types.SimpleNamespace(name="Red Paint", objectType="Appearance", entityToken="appearance-token")
        body = types.SimpleNamespace(
            name="DuplicateName",
            entityToken="body-token",
            isVisible=True,
            appearance=appearance,
            material=None,
            physicalMaterial=None,
        )
        component = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        self.mock_design = types.SimpleNamespace(rootComponent=component)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("inspect_body_style", {"body_entity_tokens": ["body-token"]})

        self.assertIn("result", res)
        self.assertEqual(res["result"]["count"], 1)
        self.assertEqual(res["result"]["bodies"][0]["entityToken"], "body-token")

    def test_apply_appearance_accepts_body_entity_tokens(self):
        utilities = importlib.import_module("tools.utilities")
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        old_appearance = types.SimpleNamespace(name="Old", objectType="Appearance", entityToken="old-token")
        new_appearance = types.SimpleNamespace(name="Logo Red", objectType="Appearance", entityToken="red-token")
        body = types.SimpleNamespace(
            name="LogoBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="logo-token",
            isVisible=True,
            appearance=old_appearance,
            material=None,
            physicalMaterial=None,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=1.0),
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[], sketches=[], constructionPlanes=[])
        body.parentComponent = root
        design = types.SimpleNamespace(
            rootComponent=root,
            appearances=[new_appearance],
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
        )
        _fake_app.activeProduct = design
        _fake_app.materialLibraries = []
        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("apply_appearance", {
                "appearance_name": "Logo Red",
                "body_entity_tokens": ["logo-token"],
                "expected_body_count": 1,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertTrue(res["result"]["applied"])
        self.assertEqual(body.appearance, new_appearance)
        self.assertEqual(res["result"]["targetBodies"][0]["appearance"]["name"], "Logo Red")
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_get_physical_properties_reports_converted_body_properties(self):
        appearance = types.SimpleNamespace(
            name="Blue Paint",
            objectType="Appearance",
            entityToken="appearance-token",
        )
        material = types.SimpleNamespace(
            name="Aluminum",
            objectType="PhysicalMaterial",
            entityToken="material-token",
        )
        point_min = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)
        point_max = types.SimpleNamespace(x=2.0, y=3.0, z=4.0)
        center = types.SimpleNamespace(x=1.0, y=1.5, z=2.0)
        props = types.SimpleNamespace(
            mass=0.42,
            volume=24.0,
            area=52.0,
            density=0.0175,
            centerOfMass=center,
        )
        body = types.SimpleNamespace(
            name="Bracket",
            entityToken="body-token",
            isVisible=True,
            isSolid=True,
            boundingBox=types.SimpleNamespace(minPoint=point_min, maxPoint=point_max),
            physicalProperties=props,
            physicalMaterial=material,
            appearance=appearance,
        )
        component = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        self.mock_design = types.SimpleNamespace(rootComponent=component)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("get_physical_properties", {"body_entity_token": "body-token"})

        self.assertIn("result", res)
        report = res["result"]["bodies"][0]
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(report["bodyName"], "Bracket")
        self.assertEqual(report["massKg"], 0.42)
        self.assertEqual(report["volumeMm3"], 24000.0)
        self.assertEqual(report["areaMm2"], 5200.0)
        self.assertEqual(report["centerOfMassMm"], [10.0, 15.0, 20.0])
        self.assertEqual(report["boundingBoxSizeMm"], [20.0, 30.0, 40.0])
        self.assertEqual(report["physicalMaterial"]["name"], "Aluminum")
        self.assertEqual(report["appearance"]["entityToken"], "appearance-token")

    def test_inspect_analysis_capabilities_reports_unsupported_exact_apis(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("inspect_analysis_capabilities", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertTrue(res["result"]["broadPhaseAvailable"])
        self.assertFalse(res["result"]["exactInterference"]["supported"])
        self.assertFalse(res["result"]["exactMinimumDistance"]["supported"])
        self.assertIn("Current interference_check and clearance_check remain broad-phase", " ".join(res["result"]["warnings"]))

    def test_inspect_analysis_capabilities_reports_candidate_apis_without_claiming_validation(self):
        inspection = importlib.import_module("tools.inspection")
        original_temp_manager = getattr(inspection.adsk.fusion, "TemporaryBRepManager", None)
        original_measure_manager = getattr(_fake_app, "measureManager", None)
        had_measure_manager = hasattr(_fake_app, "measureManager")

        class _TempBRepManager:
            @staticmethod
            def get():
                return _TempBRepManager()

            def copy(self, _body):
                return object()

            def booleanOperation(self, *_args):
                return True

        class _MeasureManager:
            def measureMinimumDistance(self, *_args):
                return types.SimpleNamespace(value=1.0)

        visible_body_a = types.SimpleNamespace(name="BodyA", isVisible=True)
        visible_body_b = types.SimpleNamespace(name="BodyB", isVisible=True)
        root = types.SimpleNamespace(name="Root", bRepBodies=[visible_body_a, visible_body_b], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        inspection.adsk.fusion.TemporaryBRepManager = _TempBRepManager
        _fake_app.measureManager = _MeasureManager()
        try:
            res = self.tools.execute_tool("inspect_analysis_capabilities", {})
        finally:
            if original_temp_manager is None:
                delattr(inspection.adsk.fusion, "TemporaryBRepManager")
            else:
                inspection.adsk.fusion.TemporaryBRepManager = original_temp_manager
            if had_measure_manager:
                _fake_app.measureManager = original_measure_manager
            else:
                delattr(_fake_app, "measureManager")

        self.assertTrue(res["result"]["exactInterference"]["supported"])
        self.assertEqual(res["result"]["exactInterference"]["booleanCandidate"]["method"], "booleanOperation")
        self.assertTrue(res["result"]["exactMinimumDistance"]["supported"])
        self.assertEqual(res["result"]["exactMinimumDistance"]["distanceCandidate"]["method"], "measureMinimumDistance")
        self.assertIn("Candidate API availability is not proof", res["result"]["warnings"][0])

    def test_interference_check_reports_bounding_box_collisions(self):
        body_a = types.SimpleNamespace(
            name="BodyA",
            entityToken="token-a",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=2.0, y=2.0, z=2.0),
            ),
        )
        body_b = types.SimpleNamespace(
            name="BodyB",
            entityToken="token-b",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=1.0, y=1.0, z=1.0),
                maxPoint=types.SimpleNamespace(x=3.0, y=3.0, z=3.0),
            ),
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body_a, body_b], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("interference_check", {"body_names": ["BodyA", "BodyB"]})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["method"], "axis_aligned_bounding_box")
        self.assertEqual(res["result"]["pairCount"], 1)
        self.assertEqual(res["result"]["interferenceCount"], 1)
        self.assertEqual(res["result"]["interferences"][0]["bboxOverlapMm"], [10.0, 10.0, 10.0])
        self.assertEqual(res["result"]["interferences"][0]["bboxOverlapVolumeMm3"], 1000.0)

    def test_interference_check_requires_two_bodies(self):
        body = types.SimpleNamespace(
            name="OnlyBody",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=1.0, y=1.0, z=1.0),
            ),
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("interference_check", {"body_names": ["OnlyBody"]})

        self.assertIn("error", res)
        self.assertIn("at least two", res["error"])

    def test_exact_interference_check_reports_unsupported_missing_api(self):
        body_a = types.SimpleNamespace(name="BodyA", entityToken="token-a", isVisible=True)
        body_b = types.SimpleNamespace(name="BodyB", entityToken="token-b", isVisible=True)
        root = types.SimpleNamespace(name="Root", bRepBodies=[body_a, body_b], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("exact_interference_check", {"body_names": ["BodyA", "BodyB"]})

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])
        self.assertIn("Exact interference APIs are not available", res["error"])

    def test_exact_interference_check_uses_temporary_brep_candidate(self):
        inspection = importlib.import_module("tools.inspection")
        original_temp_manager = getattr(inspection.adsk.fusion, "TemporaryBRepManager", None)

        class _TempBRepManager:
            @staticmethod
            def get():
                return _TempBRepManager()

            def copy(self, body):
                return types.SimpleNamespace(name=f"{body.name}_copy", volume=0)

            def booleanOperation(self, body_a, body_b):
                return types.SimpleNamespace(name=f"{body_a.name}_{body_b.name}_intersection", volume=1.25)

        body_a = types.SimpleNamespace(name="BodyA", entityToken="token-a", isVisible=True, boundingBox=None)
        body_b = types.SimpleNamespace(name="BodyB", entityToken="token-b", isVisible=True, boundingBox=None)
        root = types.SimpleNamespace(name="Root", bRepBodies=[body_a, body_b], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        inspection.adsk.fusion.TemporaryBRepManager = _TempBRepManager
        try:
            res = self.tools.execute_tool("exact_interference_check", {"body_names": ["BodyA", "BodyB"]})
        finally:
            if original_temp_manager is None:
                delattr(inspection.adsk.fusion, "TemporaryBRepManager")
            else:
                inspection.adsk.fusion.TemporaryBRepManager = original_temp_manager

        self.assertIn("result", res)
        self.assertEqual(res["result"]["method"], "temporary_brep_boolean_intersection")
        self.assertFalse(res["result"]["validatedExact"])
        self.assertEqual(res["result"]["interferenceCount"], 1)
        self.assertTrue(res["result"]["interferences"][0]["exactInterferes"])

    def test_clearance_check_reports_minimum_clearance_violation(self):
        target = types.SimpleNamespace(
            name="Target",
            entityToken="target-token",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=1.0, y=1.0, z=1.0),
            ),
        )
        tool = types.SimpleNamespace(
            name="Tool",
            entityToken="tool-token",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=1.04, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=2.0, y=1.0, z=1.0),
            ),
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[target, tool], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("clearance_check", {
            "target_body_names": ["Target"],
            "tool_body_names": ["Tool"],
            "minimum_clearance": "0.5 mm",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["pairCount"], 1)
        self.assertEqual(res["result"]["violationCount"], 1)
        self.assertAlmostEqual(res["result"]["violations"][0]["bboxDistanceMm"], 0.4)
        self.assertFalse(res["result"]["violations"][0]["clearanceOk"])

    def test_clearance_check_accepts_entity_tokens(self):
        target = types.SimpleNamespace(
            name="Target",
            entityToken="target-token",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=1.0, y=1.0, z=1.0),
            ),
        )
        tool = types.SimpleNamespace(
            name="Tool",
            entityToken="tool-token",
            isVisible=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=2.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=3.0, y=1.0, z=1.0),
            ),
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[target, tool], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("clearance_check", {
            "target_body_entity_tokens": ["target-token"],
            "tool_body_entity_tokens": ["tool-token"],
            "minimum_clearance": "5 mm",
        })

        self.assertIn("result", res)
        self.assertEqual(res["result"]["violationCount"], 0)
        self.assertTrue(res["result"]["checkedPairs"][0]["clearanceOk"])

    def test_verify_insert_alignment_blocks_separated_logo(self):
        def body(name, token, min_xyz, max_xyz):
            return types.SimpleNamespace(
                name=name,
                entityToken=token,
                isVisible=True,
                boundingBox=types.SimpleNamespace(
                    minPoint=types.SimpleNamespace(x=min_xyz[0], y=min_xyz[1], z=min_xyz[2]),
                    maxPoint=types.SimpleNamespace(x=max_xyz[0], y=max_xyz[1], z=max_xyz[2]),
                ),
            )

        plate = body("Plate", "plate-token", (0.0, 0.0, 0.0), (4.0, 3.0, 0.2))
        socket = body("Socket", "socket-token", (0.0, 0.0, 0.0), (4.0, 3.0, 0.2))
        logo = body("LogoText", "logo-token", (1.0, 1.0, 0.35), (2.0, 2.0, 0.45))
        root = types.SimpleNamespace(name="Root", bRepBodies=[plate, socket, logo], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("verify_insert_alignment", {
            "plate_body_name": "Plate",
            "socket_body_name": "Socket",
            "logo_body_names": ["LogoText"],
            "expected_plate_thickness": "2 mm",
            "thickness_axis": "z",
            "tolerance": "0.05 mm",
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertFalse(result["okToExport"])
        self.assertTrue(result["checks"]["plateSocketFootprintOverlap"])
        self.assertTrue(result["checks"]["socketDepthMatchesPlateThickness"])
        self.assertFalse(result["checks"]["logoBodiesOnOrIntersectPlate"])
        self.assertEqual(result["plate"]["sizeMm"], [40.0, 30.0, 2.0])
        self.assertTrue(result["logoBodies"][0]["separatedFromPlate"])
        self.assertGreater(result["logoBodies"][0]["minAbovePlateTopMm"], 0.05)
        self.assertIn("Logo bodies appear separated above the plate", " ".join(result["blockingReasons"]))

    def test_verify_insert_alignment_passes_touching_insert(self):
        def body(name, token, min_xyz, max_xyz):
            return types.SimpleNamespace(
                name=name,
                entityToken=token,
                isVisible=True,
                boundingBox=types.SimpleNamespace(
                    minPoint=types.SimpleNamespace(x=min_xyz[0], y=min_xyz[1], z=min_xyz[2]),
                    maxPoint=types.SimpleNamespace(x=max_xyz[0], y=max_xyz[1], z=max_xyz[2]),
                ),
            )

        plate = body("Plate", "plate-token", (0.0, 0.0, 0.0), (4.0, 3.0, 0.2))
        socket = body("Socket", "socket-token", (0.0, 0.0, 0.0), (4.0, 3.0, 0.2))
        logo = body("LogoText", "logo-token", (1.0, 1.0, 0.199), (2.0, 2.0, 0.4))
        root = types.SimpleNamespace(name="Root", bRepBodies=[plate, socket, logo], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("verify_insert_alignment", {
            "plate_body_entity_token": "plate-token",
            "socket_body_entity_token": "socket-token",
            "logo_body_entity_tokens": ["logo-token"],
            "expected_plate_thickness": "2 mm",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToExport"])
        self.assertEqual(res["result"]["blockingReasons"], [])
        self.assertTrue(res["result"]["checks"]["logoBodiesOnOrIntersectPlate"])

    def test_exact_clearance_check_uses_measure_manager_candidate(self):
        original_measure_manager = getattr(_fake_app, "measureManager", None)
        had_measure_manager = hasattr(_fake_app, "measureManager")

        class _MeasureManager:
            def measureMinimumDistance(self, body_a, body_b):
                return types.SimpleNamespace(value=0.04)

        target = types.SimpleNamespace(name="Target", entityToken="target-token", isVisible=True, boundingBox=None)
        tool = types.SimpleNamespace(name="Tool", entityToken="tool-token", isVisible=True, boundingBox=None)
        root = types.SimpleNamespace(name="Root", bRepBodies=[target, tool], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.measureManager = _MeasureManager()
        try:
            res = self.tools.execute_tool("exact_clearance_check", {
                "target_body_entity_tokens": ["target-token"],
                "tool_body_entity_tokens": ["tool-token"],
                "minimum_clearance": "0.5 mm",
            })
        finally:
            if had_measure_manager:
                _fake_app.measureManager = original_measure_manager
            else:
                delattr(_fake_app, "measureManager")

        self.assertIn("result", res)
        self.assertEqual(res["result"]["method"], "measure_manager_minimum_distance")
        self.assertFalse(res["result"]["validatedExact"])
        self.assertEqual(res["result"]["violationCount"], 1)
        self.assertAlmostEqual(res["result"]["violations"][0]["exactDistanceMm"], 0.4)

    def test_inspect_sheet_metal_rules_reports_rule_and_body_metadata(self):
        rule = types.SimpleNamespace(
            name="Default Sheet Metal",
            objectType="adsk::fusion::SheetMetalRule",
            thickness=types.SimpleNamespace(expression="1 mm", value=0.1),
            bendRadius=types.SimpleNamespace(expression="1.5 mm", value=0.15),
            kFactor=types.SimpleNamespace(expression="0.44", value=0.44),
        )
        body = types.SimpleNamespace(
            name="Panel",
            entityToken="panel-token",
            objectType="adsk::fusion::SheetMetalBody",
            isVisible=True,
            isSolid=True,
            isSheetMetal=True,
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=1.0, y=2.0, z=0.1),
            ),
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            activeSheetMetalRule=rule,
            sheetMetalRules=[rule],
            designType="SheetMetalDesignType",
        )

        res = self.tools.execute_tool("inspect_sheet_metal_rules", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["activeRule"]["name"], "Default Sheet Metal")
        self.assertEqual(res["result"]["activeRule"]["thicknessExpression"], "1 mm")
        self.assertEqual(res["result"]["sheetMetalBodyCount"], 1)
        self.assertTrue(res["result"]["bodies"][0]["isSheetMetal"])

    def test_preflight_flat_pattern_blocks_non_sheet_metal_design(self):
        body = types.SimpleNamespace(
            name="SolidBody",
            entityToken="solid-token",
            objectType="adsk::fusion::BRepBody",
            isVisible=True,
            isSolid=True,
            isSheetMetal=False,
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("preflight_flat_pattern", {"body_name": "SolidBody"})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["riskLevel"], "high")
        self.assertTrue(any("No active sheet-metal rule" in item for item in res["result"]["blockingReasons"]))
        self.assertTrue(any("not identified as sheet metal" in item for item in res["result"]["blockingReasons"]))

    def test_preflight_flat_pattern_reports_available_flat_pattern(self):
        rule = types.SimpleNamespace(
            name="Default Sheet Metal",
            thickness=types.SimpleNamespace(expression="1 mm", value=0.1),
            bendRadius=types.SimpleNamespace(expression="1 mm", value=0.1),
            kFactor=types.SimpleNamespace(value=0.44),
        )
        body = types.SimpleNamespace(
            name="Panel",
            entityToken="panel-token",
            objectType="adsk::fusion::SheetMetalBody",
            isVisible=True,
            isSolid=True,
            isSheetMetal=True,
        )
        flat_pattern = types.SimpleNamespace(
            name="Panel Flat Pattern",
            entityToken="flat-token",
            objectType="adsk::fusion::FlatPattern",
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[], flatPattern=flat_pattern)
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            activeSheetMetalRule=rule,
            sheetMetalRules=[rule],
        )

        res = self.tools.execute_tool("preflight_flat_pattern", {"body_name": "Panel"})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertTrue(res["result"]["flatPatternAvailable"])
        self.assertEqual(res["result"]["flatPattern"]["entityToken"], "flat-token")

    def test_plan_sheet_metal_workflow_requires_explicit_creation_inputs(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("plan_sheet_metal_workflow", {"operation": "create_flange"})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("rule_name is required", joined)
        self.assertIn("reason is required", joined)
        self.assertIn("edge_entity_tokens are required", joined)

    def test_plan_sheet_metal_workflow_accepts_complete_flange_plan(self):
        rule = types.SimpleNamespace(
            name="Default Sheet Metal",
            thickness=types.SimpleNamespace(expression="1 mm", value=0.1),
            bendRadius=types.SimpleNamespace(expression="1 mm", value=0.1),
            kFactor=types.SimpleNamespace(value=0.44),
        )
        body = types.SimpleNamespace(
            name="Panel",
            entityToken="panel-token",
            objectType="adsk::fusion::SheetMetalBody",
            isVisible=True,
            isSolid=True,
            isSheetMetal=True,
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            activeSheetMetalRule=rule,
            sheetMetalRules=[rule],
        )

        res = self.tools.execute_tool("plan_sheet_metal_workflow", {
            "operation": "create_flange",
            "body_entity_token": "panel-token",
            "edge_entity_tokens": ["edge-token"],
            "rule_name": "Default Sheet Metal",
            "parameters": {"height": "12 mm", "angle": "90 deg"},
            "reason": "Create explicit enclosure wall flange.",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["operation"], "create_flange")
        self.assertEqual(res["result"]["targetBody"]["bodyName"], "Panel")
        self.assertEqual(res["result"]["edgeEntityTokens"], ["edge-token"])
        self.assertEqual(res["result"]["parameters"]["height"], "12 mm")
        self.assertIn("does not create flanges", " ".join(res["result"]["warnings"]))

    def test_create_flange_blocks_failed_preflight(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("create_flange", {
            "edge_entity_tokens": ["edge-token"],
            "reason": "Create explicit enclosure wall flange.",
        })

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])
        joined = " ".join(res["preflight"]["blockingReasons"])
        self.assertIn("rule_name is required", joined)

    def test_create_flange_reports_unsupported_missing_feature_collection(self):
        rule = types.SimpleNamespace(name="Default Sheet Metal")
        edge = types.SimpleNamespace(name="FlangeEdge", entityToken="edge-token", faces=[])
        body = types.SimpleNamespace(
            name="Panel",
            entityToken="panel-token",
            objectType="adsk::fusion::SheetMetalBody",
            isVisible=True,
            isSolid=True,
            isSheetMetal=True,
            edges=[edge],
            faces=[],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[], features=types.SimpleNamespace())
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            activeSheetMetalRule=rule,
            sheetMetalRules=[rule],
        )

        res = self.tools.execute_tool("create_flange", {
            "body_entity_token": "panel-token",
            "edge_entity_tokens": ["edge-token"],
            "rule_name": "Default Sheet Metal",
            "parameters": {"height": "12 mm"},
            "reason": "Create explicit enclosure wall flange.",
        })

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])
        self.assertEqual(res["operation"], "create_flange")
        self.assertIn("flangeFeatures", res["error"])

    def test_create_flange_uses_writable_feature_collection(self):
        from tools import parametric

        class _SheetMetalFeatureCollection:
            def __init__(self):
                self.inputs = []

            def createInput(self, payload):
                feature_input = types.SimpleNamespace(
                    payload=payload,
                    height=types.SimpleNamespace(expression=""),
                )
                self.inputs.append(feature_input)
                return feature_input

            def add(self, feature_input):
                return types.SimpleNamespace(name="", featureInput=feature_input)

        rule = types.SimpleNamespace(name="Default Sheet Metal")
        edge = types.SimpleNamespace(name="FlangeEdge", entityToken="edge-token", faces=[])
        body = types.SimpleNamespace(
            name="Panel",
            entityToken="panel-token",
            objectType="adsk::fusion::SheetMetalBody",
            isVisible=True,
            isSolid=True,
            isSheetMetal=True,
            edges=[edge],
            faces=[],
        )
        flange_features = _SheetMetalFeatureCollection()
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[body],
            allOccurrences=[],
            features=types.SimpleNamespace(flangeFeatures=flange_features),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            activeSheetMetalRule=rule,
            sheetMetalRules=[rule],
        )
        old_snapshot = parametric._design_state_snapshot
        old_compare = parametric.compare_design_state
        snapshots = [{"snapshot": "before"}, {"snapshot": "after"}]
        try:
            parametric._design_state_snapshot = lambda include_selections=False: snapshots.pop(0)
            parametric.compare_design_state = lambda before, after: {"result": {"changed": before != after, "before": before, "after": after}}

            res = self.tools.execute_tool("create_flange", {
                "body_entity_token": "panel-token",
                "edge_entity_tokens": ["edge-token"],
                "rule_name": "Default Sheet Metal",
                "parameters": {"height": "12 mm"},
                "reason": "Create explicit enclosure wall flange.",
            })
        finally:
            parametric._design_state_snapshot = old_snapshot
            parametric.compare_design_state = old_compare

        self.assertIn("result", res)
        self.assertEqual(res["result"]["operation"], "create_flange")
        self.assertEqual(res["result"]["featureName"], "create_flange_Panel")
        self.assertEqual(res["result"]["ruleName"], "Default Sheet Metal")
        self.assertEqual(res["result"]["appliedParameters"]["height"], "height.expression")
        self.assertEqual(flange_features.inputs[0].height.expression, "12 mm")
        self.assertTrue(res["result"]["stateComparison"]["changed"])

    def test_inspect_surface_bodies_classifies_surface_and_open_edges(self):
        open_edge = types.SimpleNamespace(
            name="OpenEdge",
            entityToken="edge-token",
            objectType="adsk::fusion::BRepEdge",
            faces=[],
            length=2.5,
        )
        closed_edge = types.SimpleNamespace(
            name="ClosedEdge",
            faces=[types.SimpleNamespace(), types.SimpleNamespace()],
            length=1.0,
        )
        surface = types.SimpleNamespace(
            name="PatchSurface",
            entityToken="surface-token",
            objectType="adsk::fusion::BRepBody",
            isVisible=True,
            isSolid=False,
            faces=[types.SimpleNamespace()],
            edges=[open_edge, closed_edge],
        )
        solid = types.SimpleNamespace(
            name="SolidBody",
            entityToken="solid-token",
            objectType="adsk::fusion::BRepBody",
            isVisible=True,
            isSolid=True,
            faces=[types.SimpleNamespace() for _ in range(6)],
            edges=[],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[surface, solid], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("inspect_surface_bodies", {"include_edges": True})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["bodyCount"], 2)
        self.assertEqual(res["result"]["surfaceBodyCount"], 1)
        surface_report = [body for body in res["result"]["bodies"] if body["bodyName"] == "PatchSurface"][0]
        self.assertEqual(surface_report["classification"], "surface")
        self.assertEqual(surface_report["openEdgeCount"], 1)
        self.assertEqual(surface_report["openEdges"][0]["entityToken"], "edge-token")
        self.assertIn("stitch_surfaces", surface_report["candidateRepairTools"])

    def test_inspect_surface_bodies_reports_missing_targets(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("inspect_surface_bodies", {"body_names": ["MissingBody"]})

        self.assertIn("result", res)
        self.assertEqual(res["result"]["missingBodyNames"], ["MissingBody"])
        self.assertTrue(any("Body names not found" in warning for warning in res["result"]["warnings"]))

    def test_plan_surface_repair_requires_target_edges_and_reason(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("plan_surface_repair", {"operation": "stitch_surfaces"})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("body_name or body_entity_token is required", joined)
        self.assertIn("reason is required", joined)
        self.assertIn("edge_entity_tokens are required", joined)

    def test_plan_surface_repair_accepts_explicit_surface_target(self):
        open_edge = types.SimpleNamespace(
            name="OpenEdge",
            entityToken="edge-token",
            objectType="adsk::fusion::BRepEdge",
            faces=[],
            length=2.5,
        )
        surface = types.SimpleNamespace(
            name="PatchSurface",
            entityToken="surface-token",
            objectType="adsk::fusion::BRepBody",
            isVisible=True,
            isSolid=False,
            faces=[types.SimpleNamespace()],
            edges=[open_edge],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[surface], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("plan_surface_repair", {
            "operation": "stitch_surfaces",
            "body_entity_token": "surface-token",
            "edge_entity_tokens": ["edge-token"],
            "parameters": {"tolerance": "0.01 mm"},
            "reason": "Close imported surface gap before downstream solid conversion.",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["operation"], "stitch_surfaces")
        self.assertEqual(res["result"]["target"]["bodyName"], "PatchSurface")
        self.assertEqual(res["result"]["edgeEntityTokens"], ["edge-token"])
        self.assertEqual(res["result"]["parameters"]["tolerance"], "0.01 mm")
        self.assertIn("does not patch", " ".join(res["result"]["warnings"]))

    def test_patch_surface_blocks_failed_preflight(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("patch_surface", {"edge_entity_tokens": ["edge-token"]})

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])
        self.assertIn("body_name or body_entity_token is required", " ".join(res["preflight"]["blockingReasons"]))

    def test_patch_surface_reports_unsupported_missing_feature_collection(self):
        open_edge = types.SimpleNamespace(
            name="OpenEdge",
            entityToken="edge-token",
            objectType="adsk::fusion::BRepEdge",
            faces=[],
            length=2.5,
        )
        surface = types.SimpleNamespace(
            name="PatchSurface",
            entityToken="surface-token",
            objectType="adsk::fusion::BRepBody",
            isVisible=True,
            isSolid=False,
            faces=[],
            edges=[open_edge],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[surface], allOccurrences=[], features=types.SimpleNamespace())
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)

        res = self.tools.execute_tool("patch_surface", {
            "body_entity_token": "surface-token",
            "edge_entity_tokens": ["edge-token"],
            "reason": "Patch imported surface gap.",
        })

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])
        self.assertEqual(res["operation"], "patch_surface")
        self.assertIn("patchFeatures", res["error"])

    def test_patch_surface_uses_writable_feature_collection(self):
        from tools import parametric

        class _SurfaceFeatureCollection:
            def __init__(self):
                self.inputs = []

            def createInput(self, payload):
                feature_input = types.SimpleNamespace(
                    payload=payload,
                    tolerance=types.SimpleNamespace(expression=""),
                )
                self.inputs.append(feature_input)
                return feature_input

            def add(self, feature_input):
                return types.SimpleNamespace(name="", featureInput=feature_input)

        open_edge = types.SimpleNamespace(
            name="OpenEdge",
            entityToken="edge-token",
            objectType="adsk::fusion::BRepEdge",
            faces=[],
            length=2.5,
        )
        surface = types.SimpleNamespace(
            name="PatchSurface",
            entityToken="surface-token",
            objectType="adsk::fusion::BRepBody",
            isVisible=True,
            isSolid=False,
            faces=[],
            edges=[open_edge],
        )
        patch_features = _SurfaceFeatureCollection()
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[surface],
            allOccurrences=[],
            features=types.SimpleNamespace(patchFeatures=patch_features),
        )
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        old_snapshot = parametric._design_state_snapshot
        old_compare = parametric.compare_design_state
        snapshots = [{"snapshot": "before"}, {"snapshot": "after"}]
        try:
            parametric._design_state_snapshot = lambda include_selections=False: snapshots.pop(0)
            parametric.compare_design_state = lambda before, after: {"result": {"changed": before != after, "before": before, "after": after}}

            res = self.tools.execute_tool("patch_surface", {
                "body_entity_token": "surface-token",
                "edge_entity_tokens": ["edge-token"],
                "parameters": {"tolerance": "0.01 mm"},
                "reason": "Patch imported surface gap.",
            })
        finally:
            parametric._design_state_snapshot = old_snapshot
            parametric.compare_design_state = old_compare

        self.assertIn("result", res)
        self.assertEqual(res["result"]["operation"], "patch_surface")
        self.assertEqual(res["result"]["featureName"], "patch_surface_PatchSurface")
        self.assertEqual(res["result"]["appliedParameters"]["tolerance"], "tolerance.expression")
        self.assertEqual(patch_features.inputs[0].tolerance.expression, "0.01 mm")
        self.assertTrue(res["result"]["stateComparison"]["changed"])

    def test_inspect_manufacturing_workspace_reports_unavailable(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("inspect_manufacturing_workspace", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["workspaceAvailable"])
        self.assertFalse(res["result"]["okToInspectSetups"])
        self.assertIn("CAM/manufacturing", res["result"]["blockingReasons"][0])

    def test_list_manufacturing_setups_reports_setup_and_operations(self):
        operation = types.SimpleNamespace(
            name="Adaptive1",
            objectType="adsk::cam::Operation",
            entityToken="op-token",
            isValid=True,
            isSuppressed=False,
            hasToolpath=False,
            tool=types.SimpleNamespace(name="Flat End Mill", objectType="Tool", entityToken="tool-token"),
        )
        setup = types.SimpleNamespace(
            name="Setup1",
            objectType="adsk::cam::Setup",
            entityToken="setup-token",
            isValid=True,
            operations=[operation],
        )
        cam = types.SimpleNamespace(
            objectType="adsk::cam::CAM",
            productType="CAMProductType",
            setups=[setup],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, cam=cam)

        res = self.tools.execute_tool("list_manufacturing_setups", {"include_operations": True})

        self.assertIn("result", res)
        self.assertEqual(res["result"]["setupCount"], 1)
        self.assertEqual(res["result"]["setups"][0]["name"], "Setup1")
        self.assertEqual(res["result"]["setups"][0]["operations"][0]["name"], "Adaptive1")
        self.assertEqual(res["result"]["setups"][0]["operations"][0]["tool"]["name"], "Flat End Mill")

    def test_inspect_operation_requires_target_and_finds_by_name(self):
        operation = types.SimpleNamespace(name="Contour1", objectType="Operation", hasToolpath=True)
        setup = types.SimpleNamespace(name="Setup1", objectType="Setup", operations=[operation])
        cam = types.SimpleNamespace(objectType="adsk::cam::CAM", productType="CAMProductType", setups=[setup])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, cam=cam)

        missing_target = self.tools.execute_tool("inspect_operation", {})
        self.assertTrue(any("operation_name or operation_index is required" in reason for reason in missing_target["result"]["blockingReasons"]))

        res = self.tools.execute_tool("inspect_operation", {"setup_name": "Setup1", "operation_name": "Contour1"})
        self.assertIn("result", res)
        self.assertEqual(res["result"]["matchCount"], 1)
        self.assertEqual(res["result"]["operations"][0]["name"], "Contour1")

    def test_plan_manufacturing_operation_requires_explicit_production_inputs(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("plan_manufacturing_operation", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("setup_name is required", joined)
        self.assertIn("machine must be a non-empty object", joined)
        self.assertIn("feeds must be a non-empty object", joined)
        self.assertIn("requires_user_approval must be true", joined)
        self.assertIn("CAM/manufacturing", joined)

    def test_plan_manufacturing_operation_accepts_complete_explicit_plan(self):
        cam = types.SimpleNamespace(objectType="adsk::cam::CAM", productType="CAMProductType", setups=[])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, cam=cam)

        res = self.tools.execute_tool("plan_manufacturing_operation", {
            "setup_name": "Setup1",
            "operation_name": "Adaptive1",
            "operation_type": "adaptive",
            "machine": {"name": "Shop Mill", "controller": "generic"},
            "stock": {"x_mm": 100, "y_mm": 50, "z_mm": 12, "material": "6061"},
            "wcs": {"origin": "stock_box_point", "axis": "model_z"},
            "tool": {"name": "6mm flat end mill", "diameter_mm": 6, "flutes": 2},
            "feeds": {"cut_mm_per_min": 600, "plunge_mm_per_min": 120},
            "speeds": {"spindle_rpm": 12000},
            "post_processor": {"name": "generic", "output_extension": "nc"},
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["setup"]["machine"]["name"], "Shop Mill")
        self.assertEqual(res["result"]["operation"]["type"], "adaptive")
        self.assertEqual(res["result"]["operation"]["feeds"]["cut_mm_per_min"], 600)
        self.assertTrue(res["result"]["requiresUserApproval"])
        self.assertIn("does not create setups", " ".join(res["result"]["warnings"]))

    def test_inspect_simulation_workspace_reports_unavailable(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("inspect_simulation_workspace", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["workspaceAvailable"])
        self.assertFalse(res["result"]["okToInspectStudies"])
        self.assertIn("Simulation", res["result"]["blockingReasons"][0])

    def test_list_simulation_studies_reports_study_metadata(self):
        study = types.SimpleNamespace(
            name="Static Stress 1",
            objectType="SimulationStudy",
            entityToken="study-token",
            studyType="static_stress",
            isValid=True,
            solveStatus="not_solved",
            isSolved=False,
            loads=[types.SimpleNamespace(name="Load1")],
            constraints=[types.SimpleNamespace(name="Fixed1")],
            materials=[types.SimpleNamespace(name="Steel")],
            contacts=[],
            results=[],
            mesh=None,
        )
        sim = types.SimpleNamespace(
            objectType="adsk::fusion::SimulationProduct",
            productType="SimulationProductType",
            studies=[study],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, simulationProduct=sim)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("list_simulation_studies", {"include_details": True})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["studyCount"], 1)
        self.assertEqual(res["result"]["studies"][0]["name"], "Static Stress 1")
        self.assertEqual(res["result"]["studies"][0]["loadCount"], 1)
        self.assertEqual(res["result"]["studies"][0]["constraintCount"], 1)

    def test_plan_simulation_study_requires_explicit_inputs_and_approval(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("plan_simulation_study", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("study_name is required", joined)
        self.assertIn("target_body_names or target_body_entity_tokens are required", joined)
        self.assertIn("materials must be a non-empty object", joined)
        self.assertIn("requires_user_approval must be true", joined)
        self.assertIn("Simulation workspace is unavailable", joined)

    def test_plan_simulation_study_accepts_complete_explicit_plan(self):
        body = types.SimpleNamespace(
            name="Bracket",
            isVisible=True,
            isSolid=True,
            entityToken="body-token",
            boundingBox=None,
            physicalProperties=None,
        )
        sim = types.SimpleNamespace(
            objectType="adsk::fusion::SimulationProduct",
            productType="SimulationProductType",
            studies=[],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, simulationProduct=sim)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("plan_simulation_study", {
            "study_name": "Bracket Static Stress",
            "study_type": "static_stress",
            "target_body_entity_tokens": ["body-token"],
            "materials": {"Bracket": "Aluminum 6061"},
            "loads": {"load1": {"type": "force", "magnitude": "100 N", "direction": "z"}},
            "constraints": {"fixed1": {"type": "fixed", "target": "mounting face"}},
            "contacts": {"default": "bonded"},
            "mesh_settings": {"size": "3 mm", "order": "linear"},
            "result_outputs": {"plots": ["stress", "displacement"]},
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["blockingReasons"], [])
        self.assertEqual(res["result"]["study"]["type"], "static_stress")
        self.assertEqual(res["result"]["study"]["targetBodies"][0]["name"], "Bracket")
        self.assertTrue(res["result"]["requiresUserApproval"])

    def test_inspect_electronics_workspace_reports_unavailable(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("inspect_electronics_workspace", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["workspaceAvailable"])
        self.assertIn("Electronics", res["result"]["blockingReasons"][0])

    def test_inspect_electronics_workspace_reports_board_metadata(self):
        outline = types.SimpleNamespace(
            name="Board Outline",
            objectType="BoardOutline",
            entityToken="outline-token",
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0, y=0, z=0),
                maxPoint=types.SimpleNamespace(x=8.0, y=5.0, z=0.16),
            ),
        )
        connector = types.SimpleNamespace(
            name="J1 USB-C",
            objectType="Component",
            entityToken="j1-token",
            designator="J1",
            packageName="USB-C",
            boundingBox=None,
        )
        component = types.SimpleNamespace(
            name="U1 MCU",
            objectType="Component",
            entityToken="u1-token",
            designator="U1",
            packageName="QFN",
            boundingBox=None,
        )
        net = types.SimpleNamespace(name="GND", objectType="Net", entityToken="net-token")
        electronics = types.SimpleNamespace(
            objectType="ElectronicsProduct",
            productType="ElectronicsProductType",
            boards=[types.SimpleNamespace(name="Main Board", objectType="Board")],
            boardOutlines=[outline],
            components=[connector, component],
            nets=[net],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, electronicsProduct=electronics)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("inspect_electronics_workspace", {})

        self.assertIn("result", res)
        product = res["result"]["electronicsProduct"]
        self.assertEqual(product["boardOutlineCount"], 1)
        self.assertEqual(product["componentCount"], 2)
        self.assertEqual(product["netCount"], 1)
        self.assertEqual(product["connectorCandidateCount"], 1)
        self.assertEqual(product["boardOutlines"][0]["sizeMm"], [80.0, 50.0, 1.6])

    def test_plan_pcb_enclosure_fit_requires_explicit_inputs(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("plan_pcb_enclosure_fit", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("board_outline must be a non-empty object", joined)
        self.assertIn("connectors must be a non-empty object", joined)
        self.assertIn("requires_user_approval must be true", joined)
        self.assertIn("Electronics workspace is unavailable", joined)

    def test_plan_pcb_enclosure_fit_accepts_complete_explicit_plan(self):
        body = types.SimpleNamespace(
            name="Enclosure",
            isVisible=True,
            isSolid=True,
            entityToken="enclosure-token",
            boundingBox=None,
            physicalProperties=None,
        )
        electronics = types.SimpleNamespace(
            objectType="ElectronicsProduct",
            productType="ElectronicsProductType",
            boards=[types.SimpleNamespace(name="Main Board")],
            boardOutlines=[types.SimpleNamespace(name="Board Outline")],
            components=[types.SimpleNamespace(name="J1 USB-C", designator="J1")],
            nets=[types.SimpleNamespace(name="GND")],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[body], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, electronicsProduct=electronics)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("plan_pcb_enclosure_fit", {
            "board_outline": {"width": "80 mm", "height": "50 mm", "thickness": "1.6 mm"},
            "keepouts": {"antenna": {"width": "20 mm", "height": "8 mm"}},
            "connectors": {"J1": {"type": "usb-c", "insertion_direction": "front"}},
            "mounting_holes": {"H1": {"diameter": "3.2 mm", "x": "5 mm", "y": "5 mm"}},
            "clearance_rules": {"board_to_wall": "1.5 mm", "connector_service": "6 mm"},
            "enclosure_body_entity_token": "enclosure-token",
            "linked_mechanical_reference": "mechanical-link-1",
            "reason": "Validate PCB fit before enclosure edits.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["blockingReasons"], [])
        self.assertEqual(res["result"]["targetEnclosureBodies"][0]["name"], "Enclosure")
        self.assertEqual(res["result"]["connectors"]["J1"]["type"], "usb-c")

    def test_inspect_design_configurations_reports_unavailable(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            userParameters=[],
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("inspect_design_configurations", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["configurationCollectionAvailable"])
        self.assertIn("configuration collection", res["result"]["blockingReasons"][0])

    def test_inspect_design_configurations_reports_rows_and_parameters(self):
        default_row = types.SimpleNamespace(
            name="Default",
            objectType="ConfigurationRow",
            isActive=True,
            parameters=[types.SimpleNamespace(name="width", expression="80 mm", unit="mm")],
        )
        wide_row = types.SimpleNamespace(
            name="Wide",
            objectType="ConfigurationRow",
            isActive=False,
            parameters=[types.SimpleNamespace(name="width", expression="100 mm", unit="mm")],
        )
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            configurations=[default_row, wide_row],
            activeConfiguration=default_row,
            userParameters=[types.SimpleNamespace(name="width", expression="80 mm", value=8.0, unit="mm")],
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("inspect_design_configurations", {})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["configurationCollectionAvailable"])
        self.assertEqual(result["configurationCount"], 2)
        self.assertEqual(result["activeConfiguration"]["name"], "Default")
        self.assertEqual(result["configurations"][1]["parameters"][0]["expression"], "100 mm")
        self.assertEqual(result["userParameters"][0]["name"], "width")

    def test_plan_design_variant_requires_explicit_inputs_and_runtime_support(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, userParameters=[])

        res = self.tools.execute_tool("plan_design_variant", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("variant_name is required", joined)
        self.assertIn("parameter_changes must be a non-empty object", joined)
        self.assertIn("requires_user_approval must be true", joined)
        self.assertIn("configuration collection", joined)

    def test_plan_design_variant_accepts_complete_explicit_plan(self):
        row = types.SimpleNamespace(name="Default", objectType="ConfigurationRow", isActive=True, parameters=[])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            configurations=[row],
            activeConfiguration=row,
            userParameters=[
                types.SimpleNamespace(name="width", expression="80 mm", value=8.0, unit="mm"),
                types.SimpleNamespace(name="height", expression="50 mm", value=5.0, unit="mm"),
            ],
        )

        res = self.tools.execute_tool("plan_design_variant", {
            "variant_name": "Wide",
            "base_configuration": "Default",
            "parameter_changes": {"width": "100 mm", "height": "60 mm"},
            "expected_affected_bodies": ["BodyA"],
            "expected_affected_features": ["Extrude1"],
            "reason": "Create a wider configurable variant.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["blockingReasons"], [])
        self.assertEqual(res["result"]["variant"]["name"], "Wide")
        self.assertEqual(res["result"]["variant"]["parameterChanges"]["width"], "100 mm")

    def test_apply_design_variant_parameters_blocks_without_approved_plan(self):
        class FakeUserParameters(list):
            def itemByName(self, name):
                for param in self:
                    if param.name == name:
                        return param
                return None

        width = types.SimpleNamespace(name="width", expression="80 mm", value=8.0, unit="mm", comment="")
        row = types.SimpleNamespace(name="Default", objectType="ConfigurationRow", isActive=True, parameters=[])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            configurations=[row],
            activeConfiguration=row,
            userParameters=FakeUserParameters([width]),
            allParameters=[],
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
            designType="parametric",
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
        )

        res = self.tools.execute_tool("apply_design_variant_parameters", {
            "variant_name": "Wide",
            "parameter_changes": {"width": "100 mm"},
            "expected_affected_bodies": ["BodyA"],
            "reason": "Try to apply without explicit user approval.",
            "requires_user_approval": False,
        })

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])
        self.assertEqual(width.expression, "80 mm")

    def test_apply_design_variant_parameters_updates_existing_user_parameters(self):
        class FakeUserParameters(list):
            def itemByName(self, name):
                for param in self:
                    if param.name == name:
                        return param
                return None

        width = types.SimpleNamespace(name="width", expression="80 mm", value=8.0, unit="mm", comment="")
        height = types.SimpleNamespace(name="height", expression="50 mm", value=5.0, unit="mm", comment="")
        row = types.SimpleNamespace(name="Default", objectType="ConfigurationRow", isActive=True, parameters=[])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            configurations=[row],
            activeConfiguration=row,
            userParameters=FakeUserParameters([width, height]),
            allParameters=[],
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
            designType="parametric",
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
        )
        _fake_app.activeDocument = types.SimpleNamespace(name="VariantDoc", isModified=False)
        _fake_app.documents = [_fake_app.activeDocument]

        res = self.tools.execute_tool("apply_design_variant_parameters", {
            "variant_name": "Wide",
            "base_configuration": "Default",
            "parameter_changes": {"width": "100 mm", "height": "60 mm"},
            "expected_affected_bodies": ["BodyA"],
            "expected_affected_features": ["Extrude1"],
            "reason": "Apply approved wider parameter set.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["applied"])
        self.assertEqual(result["variantName"], "Wide")
        self.assertEqual(result["parameterCount"], 2)
        self.assertEqual(width.expression, "100 mm")
        self.assertEqual(height.expression, "60 mm")
        self.assertTrue(result["preflight"]["okToProceed"])
        self.assertIn("did not create or activate Fusion configuration rows", result["notes"][0])

    def test_inspect_render_workspace_reports_viewport_and_named_views(self):
        camera = types.SimpleNamespace(
            objectType="Camera",
            eye=types.SimpleNamespace(x=1, y=2, z=3),
            target=types.SimpleNamespace(x=0, y=0, z=0),
            upVector=types.SimpleNamespace(x=0, y=1, z=0),
            viewOrientation="iso",
            isFitView=True,
            isPerspective=False,
        )
        named_view = types.SimpleNamespace(name="Hero View", objectType="NamedView", camera=camera)
        render_settings = types.SimpleNamespace(objectType="RenderSettings", quality="draft", resolution="1280x720")
        render_product = types.SimpleNamespace(name="Render", objectType="RenderProduct", renderSettings=render_settings)
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeViewport = types.SimpleNamespace(camera=camera)
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            namedViews=[named_view],
            cameras=[],
            environments=[types.SimpleNamespace(name="Studio", objectType="Environment")],
            appearances=[types.SimpleNamespace(name="Paint")],
            renderProduct=render_product,
        )
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("inspect_render_workspace", {})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertTrue(result["activeViewportAvailable"])
        self.assertEqual(result["namedViews"][0]["name"], "Hero View")
        self.assertEqual(result["activeCamera"]["eye"], [1, 2, 3])
        self.assertEqual(result["renderSettings"]["quality"], "draft")

    def test_plan_render_output_requires_camera_path_reason_and_approval(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeViewport = None
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, namedViews=[], cameras=[], environments=[], appearances=[])
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("plan_render_output", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("camera_name or named_view is required", joined)
        self.assertIn("output_path is required", joined)
        self.assertIn("reason is required", joined)
        self.assertIn("requires_user_approval must be true", joined)

    def test_plan_render_output_accepts_complete_explicit_plan(self):
        camera = types.SimpleNamespace(name="activeViewport", viewOrientation="iso")
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeViewport = types.SimpleNamespace(camera=camera)
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, namedViews=[], cameras=[], environments=[], appearances=[])
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))
        output_path = os.path.join(self.temp_dir.name, "render.png")

        res = self.tools.execute_tool("plan_render_output", {
            "camera_name": "activeViewport",
            "output_path": output_path,
            "width": 1280,
            "height": 720,
            "visual_style": "shaded",
            "environment": "Studio",
            "reason": "Create review still.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["blockingReasons"], [])
        self.assertEqual(res["result"]["renderPlan"]["outputPath"], output_path)
        self.assertEqual(res["result"]["renderPlan"]["width"], 1280)

    def test_render_viewport_output_blocks_without_approved_plan(self):
        class FakeViewport:
            camera = types.SimpleNamespace(name="activeViewport")

            def saveAsImageFile(self, *_args):
                raise AssertionError("render_viewport_output should not capture when preflight fails")

        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        _fake_app.activeViewport = FakeViewport()
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            namedViews=[],
            cameras=[],
            environments=[],
            appearances=[],
            designType="parametric",
            userParameters=[],
            allParameters=[],
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
        )
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None), name="RenderDoc", isModified=False)
        output_path = os.path.join(self.temp_dir.name, "render.png")

        res = self.tools.execute_tool("render_viewport_output", {
            "camera_name": "activeViewport",
            "output_path": output_path,
            "reason": "Try without approval.",
            "requires_user_approval": False,
        })

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])
        self.assertFalse(os.path.exists(output_path))

    def test_render_viewport_output_writes_nonempty_file_after_preflight(self):
        class FakeViewport:
            def __init__(self):
                self.camera = types.SimpleNamespace(name="activeViewport")
                self.saved = []

            def saveAsImageFile(self, path, width, height):
                self.saved.append((path, width, height))
                with open(path, "wb") as f:
                    f.write(b"fake-render")

            def fit(self):
                pass

        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        viewport = FakeViewport()
        _fake_app.activeViewport = viewport
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            namedViews=[],
            cameras=[],
            environments=[],
            appearances=[],
            designType="parametric",
            userParameters=[],
            allParameters=[],
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
        )
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None), name="RenderDoc", isModified=False)
        _fake_app.documents = [_fake_app.activeDocument]
        output_path = os.path.join(self.temp_dir.name, "render.png")

        res = self.tools.execute_tool("render_viewport_output", {
            "camera_name": "activeViewport",
            "output_path": output_path,
            "width": 640,
            "height": 360,
            "visual_style": "shaded",
            "reason": "Create approved viewport still.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["rendered"])
        self.assertTrue(result["exists"])
        self.assertGreater(result["sizeBytes"], 0)
        self.assertEqual(viewport.saved[0], (output_path, 640, 360))
        self.assertTrue(result["preflight"]["okToProceed"])
        self.assertEqual(result["method"], "active_viewport_saveAsImageFile")

    def test_inspect_document_management_state_reports_data_file_and_refs(self):
        data_file = types.SimpleNamespace(
            name="SavedDesign",
            id="df-1",
            versionNumber=7,
            parentProject=types.SimpleNamespace(name="Project A", id="proj-1"),
            parentFolder=types.SimpleNamespace(name="Folder A", id="folder-1"),
            versions=[types.SimpleNamespace(name="v7", versionNumber=7, id="v7")],
        )
        ref_file = types.SimpleNamespace(name="LinkedPart", id="df-ref")
        reference = types.SimpleNamespace(
            name="LinkedPartRef",
            objectType="ExternalReference",
            dataFile=ref_file,
            isOutOfDate=False,
            isBroken=False,
        )
        doc = types.SimpleNamespace(
            name="SavedDesign",
            documentType="FusionDesignDocument",
            isModified=True,
            dataFile=data_file,
            references=[reference],
        )
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]

        res = self.tools.execute_tool("inspect_document_management_state", {})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertTrue(result["cloudDataAvailable"])
        self.assertEqual(result["activeDocument"]["dataFile"]["name"], "SavedDesign")
        self.assertEqual(result["activeDocument"]["externalReferenceCount"], 1)
        self.assertTrue(any("unsaved modifications" in warning for warning in result["warnings"]))

    def test_plan_document_management_action_requires_explicit_dry_run_approval(self):
        _fake_app.activeDocument = None
        _fake_app.documents = []

        res = self.tools.execute_tool("plan_document_management_action", {})

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("action must be one of", joined)
        self.assertIn("reason is required", joined)
        self.assertIn("requires_user_approval must be true", joined)

    def test_plan_document_management_action_accepts_complete_export_copy_plan(self):
        data_file = types.SimpleNamespace(name="SavedDesign", id="df-1", versionNumber=7)
        doc = types.SimpleNamespace(name="SavedDesign", isModified=False, dataFile=data_file)
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]
        target_path = os.path.join(self.temp_dir.name, "copy.f3d")

        res = self.tools.execute_tool("plan_document_management_action", {
            "action": "export_copy",
            "document_name": "SavedDesign",
            "target_path": target_path,
            "dry_run": True,
            "reason": "Archive reviewed design copy.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["blockingReasons"], [])
        self.assertEqual(res["result"]["actionPlan"]["action"], "export_copy")
        self.assertEqual(res["result"]["actionPlan"]["targetPath"], target_path)

    def test_plan_document_management_action_accepts_close_plan(self):
        doc = types.SimpleNamespace(name="FixtureDoc", isModified=True, dataFile=None)
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]

        res = self.tools.execute_tool("plan_document_management_action", {
            "action": "close",
            "document_name": "FixtureDoc",
            "dry_run": True,
            "reason": "Close controlled fixture document.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["actionPlan"]["action"], "close")
        self.assertEqual(res["result"]["actionPlan"]["documentName"], "FixtureDoc")

    def test_plan_document_management_action_accepts_new_design_plan(self):
        _fake_app.activeDocument = None
        _fake_app.documents = []

        res = self.tools.execute_tool("plan_document_management_action", {
            "action": "new_design",
            "document_name": "FixtureDoc",
            "dry_run": True,
            "reason": "Create controlled fixture document.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["actionPlan"]["action"], "new_design")
        self.assertEqual(res["result"]["actionPlan"]["documentName"], "FixtureDoc")

    def test_export_document_copy_blocks_without_approved_plan(self):
        data_file = types.SimpleNamespace(name="SavedDesign", id="df-1", versionNumber=7)
        doc = types.SimpleNamespace(name="SavedDesign", isModified=False, dataFile=data_file)
        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            userParameters=[],
            allParameters=[],
            designType="parametric",
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
            exportManager=types.SimpleNamespace(),
        )
        target_path = os.path.join(self.temp_dir.name, "copy.f3d")

        res = self.tools.execute_tool("export_document_copy", {
            "document_name": "SavedDesign",
            "target_path": target_path,
            "reason": "Try without approval.",
            "requires_user_approval": False,
        })

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])
        self.assertFalse(os.path.exists(target_path))

    def test_export_document_copy_reports_unsupported_without_archive_export_api(self):
        data_file = types.SimpleNamespace(name="SavedDesign", id="df-1", versionNumber=7)
        doc = types.SimpleNamespace(name="SavedDesign", isModified=False, dataFile=data_file)
        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            userParameters=[],
            allParameters=[],
            designType="parametric",
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
            exportManager=types.SimpleNamespace(execute=lambda _options: None),
        )
        target_path = os.path.join(self.temp_dir.name, "copy.f3d")

        res = self.tools.execute_tool("export_document_copy", {
            "document_name": "SavedDesign",
            "target_path": target_path,
            "reason": "Archive reviewed design copy.",
            "requires_user_approval": True,
        })

        self.assertTrue(res["unsupported"])
        self.assertIn("archive export-copy API", res["error"])

    def test_export_document_copy_writes_nonempty_archive_when_runtime_supports_it(self):
        class FakeExportManager:
            def __init__(self):
                self.options = []
                self.executed = []

            def createFusionArchiveExportOptions(self, path, design):
                option = types.SimpleNamespace(path=path, design=design)
                self.options.append(option)
                return option

            def execute(self, option):
                self.executed.append(option)
                with open(option.path, "wb") as f:
                    f.write(b"fake-f3d")

        data_file = types.SimpleNamespace(name="SavedDesign", id="df-1", versionNumber=7)
        doc = types.SimpleNamespace(name="SavedDesign", isModified=False, dataFile=data_file)
        root = types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], occurrences=[], allOccurrences=[])
        export_manager = FakeExportManager()
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            userParameters=[],
            allParameters=[],
            designType="parametric",
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
            exportManager=export_manager,
        )
        target_path = os.path.join(self.temp_dir.name, "copy.f3d")

        res = self.tools.execute_tool("export_document_copy", {
            "document_name": "SavedDesign",
            "target_path": target_path,
            "reason": "Archive reviewed design copy.",
            "requires_user_approval": True,
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["exported"])
        self.assertEqual(result["targetPath"], target_path)
        self.assertGreater(result["sizeBytes"], 0)
        self.assertEqual(len(export_manager.options), 1)
        self.assertEqual(len(export_manager.executed), 1)
        self.assertIn("did not save, upload, version", result["notes"][1])

    def _complete_manufacturing_args(self):
        return {
            "setup_name": "Setup1",
            "operation_name": "Adaptive1",
            "operation_type": "adaptive",
            "machine": {"name": "Shop Mill", "controller": "generic"},
            "stock": {"x_mm": 100, "y_mm": 50, "z_mm": 12, "material": "6061"},
            "wcs": {"origin": "stock_box_point", "axis": "model_z"},
            "tool": {"name": "6mm flat end mill", "diameter_mm": 6, "flutes": 2},
            "feeds": {"cut_mm_per_min": 600, "plunge_mm_per_min": 120},
            "speeds": {"spindle_rpm": 12000},
            "post_processor": {"name": "generic", "output_extension": "nc"},
            "requires_user_approval": True,
        }

    def test_create_manufacturing_setup_blocks_failed_plan(self):
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeDocument = types.SimpleNamespace(products=types.SimpleNamespace(itemByProductType=lambda _kind: None))

        res = self.tools.execute_tool("create_manufacturing_setup", {})

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])
        self.assertIn("setup_name is required", " ".join(res["preflight"]["blockingReasons"]))

    def test_create_manufacturing_operation_reports_missing_setup(self):
        cam = types.SimpleNamespace(objectType="adsk::cam::CAM", productType="CAMProductType", setups=[])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, cam=cam)

        res = self.tools.execute_tool("create_manufacturing_operation", self._complete_manufacturing_args())

        self.assertIn("error", res)
        self.assertIn("Setup1", res["error"])
        self.assertIn("preflight", res)

    def test_create_manufacturing_setup_uses_writable_setup_collection(self):
        class _SetupCollection:
            def __init__(self):
                self.inputs = []

            def add(self, payload):
                self.inputs.append(payload)
                return types.SimpleNamespace(name="", objectType="adsk::cam::Setup", operations=[])

        setups = _SetupCollection()
        cam = types.SimpleNamespace(objectType="adsk::cam::CAM", productType="CAMProductType", setups=setups)
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, cam=cam)

        res = self.tools.execute_tool("create_manufacturing_setup", self._complete_manufacturing_args())

        self.assertIn("result", res)
        self.assertEqual(res["result"]["setupName"], "Setup1")
        self.assertEqual(setups.inputs[0]["setup"]["machine"]["name"], "Shop Mill")
        self.assertIn("stateComparison", res["result"])

    def test_generate_toolpaths_and_post_process_require_explicit_approval_and_paths(self):
        operation = types.SimpleNamespace(name="Adaptive1", objectType="Operation", generateToolpath=lambda: True)
        setup = types.SimpleNamespace(name="Setup1", objectType="Setup", operations=[operation])
        cam = types.SimpleNamespace(objectType="adsk::cam::CAM", productType="CAMProductType", setups=[setup])
        root = types.SimpleNamespace(name="Root", bRepBodies=[], allOccurrences=[])
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=root, cam=cam)

        args = self._complete_manufacturing_args()
        res = self.tools.execute_tool("generate_toolpaths", args)
        self.assertIn("result", res)
        self.assertTrue(res["result"]["generated"])

        bad_path = self.tools.execute_tool("post_process", {**args, "output_path": "relative.nc"})
        self.assertIn("error", bad_path)
        self.assertIn("absolute", bad_path["error"])

    def test_change_journal_tools_and_resource(self):
        self.mcp_server.append_change_journal({
            "kind": "tools/call",
            "tool": "inspect_design",
            "arguments": {},
            "isError": False,
            "durationMs": 12,
            "changedDesign": False,
        })

        tool_result = self.tools.execute_tool("get_change_journal", {"limit": 10})
        self.assertIn("result", tool_result)
        self.assertEqual(tool_result["result"]["entries"][0]["tool"], "inspect_design")

        resource_result = self.tools.read_resource("fusion://runtime/change-journal")
        self.assertIn("result", resource_result)
        self.assertEqual(resource_result["result"]["entries"][0]["tool"], "inspect_design")

        clear_error = self.tools.execute_tool("clear_change_journal", {})
        self.assertIn("error", clear_error)
        clear_result = self.tools.execute_tool("clear_change_journal", {"reason": "unit test cleanup"})
        self.assertTrue(clear_result["result"]["cleared"])
        self.assertEqual(self.tools.execute_tool("get_change_journal", {})["result"]["entries"], [])

    def test_local_fusion_docs_resource_and_search_tool(self):
        resource = self.tools.read_resource("fusion://docs/fusion-api")
        self.assertIn("result", resource)
        self.assertIn("help_context.json", resource["result"]["sources"])
        self.assertTrue(any(entry["id"] == "api:sketch" for entry in resource["result"]["entries"]))

        result = self.tools.execute_tool("search_local_fusion_docs", {"query": "construction plane", "limit": 5})
        self.assertIn("result", result)
        self.assertLessEqual(len(result["result"]["entries"]), 5)
        joined = " ".join(entry["title"] + " " + entry["text"] for entry in result["result"]["entries"]).lower()
        self.assertIn("construction", joined)

    def test_recommend_mcp_workflow_routes_export_away_from_scripts(self):
        result = self.tools.execute_tool("recommend_mcp_workflow", {
            "task": "Export this model as a STEP file."
        })
        self.assertEqual(result["result"]["workflow"], "export")
        self.assertIn("doctor", result["result"]["requiredFirstTools"])
        self.assertIn("preflight_export", result["result"]["requiredFirstTools"])
        self.assertIn("export_asset", result["result"]["preferredTools"])
        self.assertIn("export_flat_pattern", result["result"]["preferredTools"])
        self.assertIn("plan_drawing_views", result["result"]["preferredTools"])
        self.assertEqual(result["result"]["rawScript"]["status"], "last_resort")

    def test_recommend_mcp_workflow_routes_parameterization_to_planner(self):
        result = self.tools.execute_tool("recommend_mcp_workflow", {
            "task": "Make this messy model fully parametric without changing geometry."
        })
        self.assertEqual(result["result"]["workflow"], "parameterize_existing_model")
        self.assertIn("plan_parameterization", result["result"]["requiredFirstTools"])
        self.assertIn("inspect_feature", result["result"]["preferredTools"])

    def test_create_parametric_feature_does_not_simulate_success(self):
        result = self.tools.execute_tool("create_parametric_feature", {"feature_type": "extrude", "parameters": {}})
        self.assertIn("error", result)
        self.assertIn("Unsupported", result["error"])

    def test_parametric_operation_parser_rejects_invalid_operation(self):
        parametric = importlib.import_module("tools.parametric")
        with self.assertRaises(ValueError):
            parametric._operation("jon")

    def test_csv_tools_reject_relative_paths_before_fusion_access(self):
        export_result = self.tools.execute_tool("export_parameters_csv", {"csv_path": "params.csv"})
        import_result = self.tools.execute_tool("import_parameters_csv", {"csv_path": "params.csv"})
        self.assertEqual(export_result, {"error": "CSV path must be absolute."})
        self.assertEqual(import_result, {"error": "CSV path must be absolute."})

    def test_undo_last_action_returns_state_comparison_when_safe(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        original_execute = getattr(_fake_app, "executeTextCommand", None)
        commands = []
        snapshots = iter([
            {"design": {"designType": "parametric"}, "counts": {"bodies": 1, "components": 1, "sketches": 1, "unhealthyTimelineItems": 0}},
            {"design": {"designType": "parametric"}, "counts": {"bodies": 1, "components": 1, "sketches": 1, "unhealthyTimelineItems": 0}},
        ])
        utilities._design_state_snapshot = lambda include_selections=False: next(snapshots)
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "diff": {"removed": {}, "countChanges": {}}}
        }
        _fake_app.executeTextCommand = lambda command: commands.append(command)
        try:
            res = self.tools.execute_tool("undo_last_action", {})
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare
            if original_execute is None:
                delattr(_fake_app, "executeTextCommand")
            else:
                _fake_app.executeTextCommand = original_execute

        self.assertIn("result", res)
        self.assertEqual(commands, ["NuIUndo"])
        self.assertEqual(res["result"]["guardReasons"], [])
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_undo_last_action_auto_redoes_risky_undo(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        original_execute = getattr(_fake_app, "executeTextCommand", None)
        commands = []
        snapshots = iter([
            {"design": {"designType": "parametric"}, "counts": {"bodies": 2, "components": 1, "sketches": 1, "unhealthyTimelineItems": 0}},
            {"design": {"designType": "direct"}, "counts": {"bodies": 1, "components": 1, "sketches": 1, "unhealthyTimelineItems": 1}},
            {"design": {"designType": "parametric"}, "counts": {"bodies": 2, "components": 1, "sketches": 1, "unhealthyTimelineItems": 0}},
        ])
        utilities._design_state_snapshot = lambda include_selections=False: next(snapshots)
        utilities.compare_design_state = lambda before, after: {
            "result": {
                "hasChanges": True,
                "riskLevel": "high",
                "diff": {"removed": {"bodies": ["BodyA"]}, "countChanges": {"bodies": -1}},
            }
        }
        _fake_app.executeTextCommand = lambda command: commands.append(command)
        try:
            res = self.tools.execute_tool("undo_last_action", {})
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare
            if original_execute is None:
                delattr(_fake_app, "executeTextCommand")
            else:
                _fake_app.executeTextCommand = original_execute

        self.assertIn("error", res)
        self.assertEqual(commands, ["NuIUndo", "NuIRedo"])
        self.assertTrue(res["redoAttempted"])
        self.assertIn("Undo changed the design type.", res["guardReasons"])
        self.assertIn("Undo increased unhealthy timeline items.", res["guardReasons"])

    def test_undo_last_action_requires_reason_for_risky_override(self):
        res = self.tools.execute_tool("undo_last_action", {"allow_risky": True})
        self.assertIn("error", res)
        self.assertIn("reason is required", res["error"])

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

    def test_inspect_selection_sets_reports_named_body_contents(self):
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None
        try:
            root = types.SimpleNamespace(name="Root", allOccurrences=[])
            body = types.SimpleNamespace(
                name="KioskBody",
                objectType="adsk::fusion::BRepBody",
                entityToken="body-token",
                parentComponent=root,
                isVisible=True,
                physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
            )
            selection_set = types.SimpleNamespace(name="Selection Set2", entities=[body])
            design = types.SimpleNamespace(rootComponent=root, selectionSets=[selection_set])
            _fake_app.activeProduct = design

            res = self.tools.execute_tool("inspect_selection_sets", {"names": ["Selection Set2"]})
        finally:
            fusion.BRepBody.cast = original_cast

        self.assertIn("result", res)
        self.assertEqual(res["result"]["count"], 1)
        item = res["result"]["selectionSets"][0]
        self.assertEqual(item["name"], "Selection Set2")
        self.assertEqual(item["entityCount"], 1)
        self.assertEqual(item["entities"][0]["bodyName"], "KioskBody")
        self.assertEqual(item["entities"][0]["entityToken"], "body-token")

    def test_export_asset_3mf_targets_selection_sets_and_restores_visibility(self):
        utilities = importlib.import_module("tools.utilities")
        import zipfile
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        executed = []
        export_path = os.path.join(self.temp_dir.name, "kiosk.3mf")

        def execute(options):
            executed.append(options)
            with zipfile.ZipFile(export_path, "w") as archive:
                archive.writestr(
                    "3D/3dmodel.model",
                    """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model"><mesh><vertices/><triangles/></mesh></object>
    <object id="2" type="model"><mesh><vertices/><triangles/></mesh></object>
  </resources>
  <build><item objectid="1"/><item objectid="2"/></build>
</model>""",
                )

        class FakeExportManager:
            def createC3MFExportOptions(self, bodies, path):
                return ("3mf", [body.name for body in bodies], path)

            def execute(self, options):
                execute(options)

        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        target = types.SimpleNamespace(
            name="KioskBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="target-token",
            parentComponent=root,
            isVisible=False,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        logo = types.SimpleNamespace(
            name="LogoBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="logo-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=0.2, area=0.5),
        )
        other = types.SimpleNamespace(
            name="OtherBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="other-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=0.2, area=0.5),
        )
        root.bRepBodies = [target, logo, other]
        root.sketches = []
        root.constructionPlanes = []
        selection_set = types.SimpleNamespace(name="Selection Set2", entities=[logo])
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[selection_set],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=FakeExportManager(),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 3, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("export_asset", {
                "format": "3mf",
                "export_path": export_path,
                "body_names": ["KioskBody"],
                "body_entity_tokens": ["logo-token"],
                "selection_set_names": ["Selection Set2"],
                "expected_body_count": 2,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertTrue(res["result"]["exported"])
        self.assertEqual(executed, [("3mf", ["KioskBody", "LogoBody"], export_path)])
        self.assertEqual(target.isVisible, False)
        self.assertEqual(logo.isVisible, True)
        self.assertEqual(other.isVisible, True)
        self.assertTrue(res["result"]["visibilityRestored"])
        self.assertEqual([body["name"] for body in res["result"]["targetBodies"]], ["KioskBody", "LogoBody"])
        self.assertTrue(res["result"]["archiveValidation"]["isZip"])
        self.assertTrue(res["result"]["archiveValidation"]["has3DModelPart"])
        self.assertTrue(res["result"]["archiveValidation"]["valid"])
        self.assertEqual(res["result"]["archiveValidation"]["objectCount"], 2)
        self.assertEqual(res["result"]["archiveValidation"]["meshObjectCount"], 2)
        self.assertEqual(res["result"]["archiveValidation"]["buildItemCount"], 2)
        self.assertEqual(res["result"]["archiveValidation"]["separateObjectCandidateCount"], 2)
        self.assertTrue(res["result"]["archiveValidation"]["slicerColorabilityLikely"])

    def test_inspect_3mf_archive_reports_existing_file_structure(self):
        import zipfile
        export_path = os.path.join(self.temp_dir.name, "inspectable.3mf")
        with zipfile.ZipFile(export_path, "w") as archive:
            archive.writestr(
                "3D/3dmodel.model",
                """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <metadata name="Application">FusionMCP Test</metadata>
  <resources>
    <object id="1" type="model"><mesh><vertices/><triangles/></mesh></object>
    <object id="2" type="model"><mesh><vertices/><triangles/></mesh></object>
  </resources>
  <build><item objectid="1"/><item objectid="2"/></build>
</model>""",
            )

        res = self.tools.execute_tool("inspect_3mf_archive", {
            "export_path": export_path,
            "expected_body_count": 2,
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["valid"])
        self.assertTrue(result["slicerColorabilityLikely"])
        self.assertEqual(result["printReadiness"]["status"], "warning")
        self.assertTrue(result["printReadiness"]["readyForSlicerImport"])
        self.assertTrue(result["printReadiness"]["readyForMulticolorAssignment"])
        self.assertFalse(result["embeddedColorEvidence"])
        self.assertFalse(result["validationScope"]["embeddedMaterialOrColorProperties"])
        self.assertFalse(result["validationScope"]["slicerAssignmentVerified"])
        self.assertTrue(any("embedded material/color" in warning for warning in result["warnings"]))
        self.assertEqual(result["metadata"]["Application"], "FusionMCP Test")
        self.assertEqual(result["objectIds"], ["1", "2"])
        self.assertEqual(result["missingBuildObjectIds"], [])

    def test_inspect_3mf_archive_reports_embedded_color_evidence(self):
        import zipfile
        export_path = os.path.join(self.temp_dir.name, "colored.3mf")
        with zipfile.ZipFile(export_path, "w") as archive:
            archive.writestr(
                "3D/3dmodel.model",
                """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter"
  xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
  xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
  <resources>
    <m:colorgroup id="10"><m:color color="#ff0000ff"/><m:color color="#0000ffff"/></m:colorgroup>
    <object id="1" type="model"><mesh><vertices/><triangles><triangle v1="0" v2="0" v3="0" pid="10" p1="0"/></triangles></mesh></object>
    <object id="2" type="model"><mesh><vertices/><triangles><triangle v1="0" v2="0" v3="0" pid="10" p1="1"/></triangles></mesh></object>
  </resources>
  <build><item objectid="1"/><item objectid="2"/></build>
</model>""",
            )

        res = self.tools.execute_tool("inspect_3mf_archive", {
            "export_path": export_path,
            "expected_body_count": 2,
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["valid"])
        self.assertTrue(result["embeddedColorEvidence"])
        self.assertEqual(result["colorGroupCount"], 1)
        self.assertEqual(result["colorPropertyCount"], 2)
        self.assertGreater(result["propertyReferenceCount"], 0)
        self.assertTrue(result["validationScope"]["embeddedMaterialOrColorProperties"])

    def test_inspect_3mf_archive_rejects_relative_path(self):
        res = self.tools.execute_tool("inspect_3mf_archive", {"export_path": "model.3mf"})

        self.assertIn("error", res)
        self.assertIn("absolute", res["error"])

    def test_export_asset_3mf_prefers_object_collection_targets(self):
        utilities = importlib.import_module("tools.utilities")
        import zipfile
        core = sys.modules["adsk.core"]
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_object_collection = core.ObjectCollection
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        core.ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())
        export_path = os.path.join(self.temp_dir.name, "collection.3mf")
        method_calls = []

        class FakeExportManager:
            def createC3MFExportOptions(self, bodies, path):
                method_calls.append(type(bodies).__name__)
                if not isinstance(bodies, MockObjectCollection):
                    raise TypeError("expected ObjectCollection")
                return ("3mf", [body.name for body in bodies], path)

            def execute(self, options):
                with zipfile.ZipFile(export_path, "w") as archive:
                    archive.writestr(
                        "3D/3dmodel.model",
                        """<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model"/></resources><build><item objectid="1"/></build></model>""",
                    )

        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        body = types.SimpleNamespace(
            name="KioskBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="target-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        root.bRepBodies = [body]
        root.sketches = []
        root.constructionPlanes = []
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=FakeExportManager(),
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
                "format": "3mf",
                "export_path": export_path,
                "body_entity_tokens": ["target-token"],
                "expected_body_count": 1,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            core.ObjectCollection = original_object_collection
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(method_calls, ["MockObjectCollection"])
        self.assertEqual(res["result"]["method"], "createC3MFExportOptions/2")

    def test_export_asset_3mf_restores_visibility_on_execute_failure(self):
        utilities = importlib.import_module("tools.utilities")
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        class FakeExportManager:
            def createC3MFExportOptions(self, bodies, path):
                return ("3mf", [body.name for body in bodies], path)

            def execute(self, options):
                raise RuntimeError("export failed")

        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        target = types.SimpleNamespace(
            name="KioskBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="target-token",
            parentComponent=root,
            isVisible=False,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        other = types.SimpleNamespace(
            name="OtherBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="other-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=0.2, area=0.5),
        )
        root.bRepBodies = [target, other]
        root.sketches = []
        root.constructionPlanes = []
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=FakeExportManager(),
        )
        _fake_app.activeProduct = design
        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 2, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("export_asset", {
                "format": "3mf",
                "export_path": os.path.join(self.temp_dir.name, "failure.3mf"),
                "body_entity_tokens": ["target-token"],
                "expected_body_count": 1,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertEqual(res["error"], "Fusion 3MF export failed during export manager execution.")
        self.assertIn("export failed", res["details"])
        self.assertEqual(target.isVisible, False)
        self.assertEqual(other.isVisible, True)
        self.assertTrue(res["visibilityRestored"])
        self.assertEqual([body["name"] for body in res["targetBodies"]], ["KioskBody"])

    def test_export_asset_3mf_warns_when_archive_collapses_color_targets(self):
        utilities = importlib.import_module("tools.utilities")
        import zipfile
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        export_path = os.path.join(self.temp_dir.name, "collapsed.3mf")

        class FakeExportManager:
            def createC3MFExportOptions(self, bodies, path):
                return ("3mf", [body.name for body in bodies], path)

            def execute(self, options):
                with zipfile.ZipFile(export_path, "w") as archive:
                    archive.writestr(
                        "3D/3dmodel.model",
                        """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model"><mesh><vertices/><triangles/></mesh></object>
  </resources>
  <build><item objectid="1"/></build>
</model>""",
                    )

        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        body_a = types.SimpleNamespace(
            name="BodyA",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-a-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        body_b = types.SimpleNamespace(
            name="BodyB",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-b-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        root.bRepBodies = [body_a, body_b]
        root.sketches = []
        root.constructionPlanes = []
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=FakeExportManager(),
        )
        _fake_app.activeProduct = design
        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 2, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("export_asset", {
                "format": "3mf",
                "export_path": export_path,
                "body_entity_tokens": ["body-a-token", "body-b-token"],
                "expected_body_count": 2,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        archive_validation = res["result"]["archiveValidation"]
        self.assertTrue(archive_validation["valid"])
        self.assertFalse(archive_validation["slicerColorabilityLikely"])
        self.assertEqual(archive_validation["printReadiness"]["status"], "warning")
        self.assertTrue(archive_validation["printReadiness"]["readyForSlicerImport"])
        self.assertFalse(archive_validation["printReadiness"]["readyForMulticolorAssignment"])
        self.assertEqual(archive_validation["separateObjectCandidateCount"], 1)
        self.assertTrue(any("separate object candidate" in warning for warning in archive_validation["warnings"]))

    def test_plan_multibody_3mf_export_resolves_tokens_and_selection_sets(self):
        utilities = importlib.import_module("tools.utilities")
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        body_a = types.SimpleNamespace(
            name="KioskBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-a-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        body_b = types.SimpleNamespace(
            name="LogoBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-b-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=0.2, area=0.5),
        )
        root.bRepBodies = [body_a, body_b]
        root.sketches = []
        root.constructionPlanes = []
        selection_set = types.SimpleNamespace(name="Selection Set2", entities=[body_b, types.SimpleNamespace(name="IgnoredSketch")])
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[selection_set],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=types.SimpleNamespace(),
        )
        _fake_app.activeProduct = design

        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 2, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("plan_multibody_3mf_export", {
                "export_path": os.path.join(self.temp_dir.name, "planned.3mf"),
                "body_entity_tokens": ["body-a-token"],
                "selection_set_names": ["Selection Set2"],
                "expected_body_count": 2,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["okToExport"])
        self.assertEqual(result["targetBodyCount"], 2)
        self.assertEqual(result["targetResolution"]["requestedBodyEntityTokens"], ["body-a-token"])
        self.assertEqual(result["targetResolution"]["selectionSets"][0]["nonBodyEntityCount"], 1)
        self.assertTrue(any("non-body" in warning for warning in result["warnings"]))

    def test_plan_multibody_3mf_export_blocks_expected_count_mismatch(self):
        utilities = importlib.import_module("tools.utilities")
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        root = types.SimpleNamespace(name="Root", allOccurrences=[], bRepBodies=[], sketches=[], constructionPlanes=[])
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=types.SimpleNamespace(),
        )
        _fake_app.activeProduct = design
        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 0, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("plan_multibody_3mf_export", {
                "export_path": os.path.join(self.temp_dir.name, "planned.3mf"),
                "body_entity_tokens": ["missing-token"],
                "expected_body_count": 1,
            })
        finally:
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertFalse(res["result"]["okToExport"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("missing-token", joined)
        self.assertIn("Resolved 0 target bodies, expected 1", joined)

    def test_plan_multibody_3mf_export_blocks_existing_path_without_overwrite(self):
        utilities = importlib.import_module("tools.utilities")
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        export_path = os.path.join(self.temp_dir.name, "existing.3mf")
        with open(export_path, "w", encoding="utf-8") as handle:
            handle.write("old")
        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        body = types.SimpleNamespace(
            name="KioskBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-token",
            parentComponent=root,
            isVisible=True,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        root.bRepBodies = [body]
        root.sketches = []
        root.constructionPlanes = []
        design = types.SimpleNamespace(
            rootComponent=root,
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=types.SimpleNamespace(),
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
            res = self.tools.execute_tool("plan_multibody_3mf_export", {
                "export_path": export_path,
                "body_entity_tokens": ["body-token"],
                "expected_body_count": 1,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertFalse(res["result"]["okToExport"])
        self.assertIn("allow_overwrite=true", " ".join(res["result"]["blockingReasons"]))

    def test_plan_multicolor_3mf_export_reports_color_assignments(self):
        utilities = importlib.import_module("tools.utilities")
        fusion = sys.modules["adsk.fusion"]
        original_cast = fusion.BRepBody.cast
        original_snapshot = utilities._design_state_snapshot
        original_compare = utilities.compare_design_state
        fusion.BRepBody.cast = lambda value: value if getattr(value, "objectType", "") == "adsk::fusion::BRepBody" else None

        appearance = types.SimpleNamespace(name="Logo Red", objectType="Appearance", entityToken="red-token")
        root = types.SimpleNamespace(name="Root", allOccurrences=[])
        body = types.SimpleNamespace(
            name="LogoBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="logo-token",
            parentComponent=root,
            isVisible=True,
            appearance=None,
            material=None,
            physicalMaterial=None,
            physicalProperties=types.SimpleNamespace(volume=1.0, area=2.0),
        )
        root.bRepBodies = [body]
        root.sketches = []
        root.constructionPlanes = []
        design = types.SimpleNamespace(
            rootComponent=root,
            appearances=[appearance],
            selectionSets=[],
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            computeAll=lambda: None,
            exportManager=types.SimpleNamespace(),
        )
        _fake_app.activeProduct = design
        _fake_app.materialLibraries = []
        utilities._design_state_snapshot = lambda include_selections=False: {
            "document": {"active": {"name": "DocA", "isModified": False}},
            "counts": {"bodies": 1, "timelineItems": 0, "unhealthyTimelineItems": 0},
        }
        utilities.compare_design_state = lambda before, after: {
            "result": {"hasChanges": False, "riskLevel": "none", "diff": {"countChanges": {}}}
        }
        try:
            res = self.tools.execute_tool("plan_multicolor_3mf_export", {
                "export_path": os.path.join(self.temp_dir.name, "colors.3mf"),
                "color_assignments": [
                    {"body_entity_token": "logo-token", "appearance_name": "Logo Red"}
                ],
                "expected_body_count": 1,
            })
        finally:
            fusion.BRepBody.cast = original_cast
            utilities._design_state_snapshot = original_snapshot
            utilities.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToExport"])
        assignment = res["result"]["colorAssignments"][0]
        self.assertEqual(assignment["appearance"]["name"], "Logo Red")
        self.assertEqual(assignment["applyAppearanceArguments"]["body_entity_tokens"], ["logo-token"])
        self.assertEqual(res["result"]["exportPlan"]["targetBodyCount"], 1)

    def test_export_flat_pattern_rejects_relative_path(self):
        res = self.tools.execute_tool("export_flat_pattern", {"export_path": "panel.dxf"})
        self.assertIn("error", res)
        self.assertIn("absolute", res["error"])

    def test_export_flat_pattern_blocks_failed_preflight(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_flat_pattern
        utilities.preflight_flat_pattern = lambda: {
            "result": {
                "okToProceed": False,
                "riskLevel": "high",
                "blockingReasons": ["No flat pattern is available."],
            }
        }
        try:
            res = self.tools.execute_tool("export_flat_pattern", {
                "export_path": os.path.join(self.temp_dir.name, "blocked.dxf"),
            })
        finally:
            utilities.preflight_flat_pattern = original_preflight

        self.assertIn("error", res)
        self.assertIn("blocked by preflight", res["error"])
        self.assertEqual(res["preflight"]["blockingReasons"], ["No flat pattern is available."])

    def test_export_flat_pattern_override_requires_reason(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_flat_pattern
        utilities.preflight_flat_pattern = lambda: {
            "result": {
                "okToProceed": False,
                "riskLevel": "high",
                "blockingReasons": ["Sheet-metal rule was not inspectable."],
            }
        }
        try:
            res = self.tools.execute_tool("export_flat_pattern", {
                "export_path": os.path.join(self.temp_dir.name, "override.dxf"),
                "allow_blocked_export": True,
            })
        finally:
            utilities.preflight_flat_pattern = original_preflight

        self.assertIn("error", res)
        self.assertIn("override_reason is required", res["error"])

    def test_export_flat_pattern_reports_unsupported_missing_export_api(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_flat_pattern
        utilities.preflight_flat_pattern = lambda: {
            "result": {"okToProceed": True, "riskLevel": "none", "blockingReasons": []}
        }
        _fake_app.activeProduct = types.SimpleNamespace(
            flatPattern=types.SimpleNamespace(),
            rootComponent=types.SimpleNamespace(name="Root"),
        )
        try:
            res = self.tools.execute_tool("export_flat_pattern", {
                "export_path": os.path.join(self.temp_dir.name, "unsupported.dxf"),
            })
        finally:
            utilities.preflight_flat_pattern = original_preflight

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])
        self.assertIn("supported export method", res["error"])

    def test_export_flat_pattern_success_uses_flat_pattern_export_manager(self):
        utilities = importlib.import_module("tools.utilities")
        original_preflight = utilities.preflight_flat_pattern
        executed = []

        class _FlatPatternExportManager:
            def createDXFExportOptions(self, path):
                return ("dxf", path)

            def execute(self, options):
                executed.append(options)
                return True

        utilities.preflight_flat_pattern = lambda: {
            "result": {"okToProceed": True, "riskLevel": "none", "blockingReasons": []}
        }
        _fake_app.activeProduct = types.SimpleNamespace(
            flatPattern=types.SimpleNamespace(exportManager=_FlatPatternExportManager()),
            rootComponent=types.SimpleNamespace(name="Root"),
        )
        try:
            export_path = os.path.join(self.temp_dir.name, "panel.dxf")
            res = self.tools.execute_tool("export_flat_pattern", {
                "format": "dxf",
                "export_path": export_path,
            })
        finally:
            utilities.preflight_flat_pattern = original_preflight

        self.assertTrue(res["result"]["exported"])
        self.assertEqual(res["result"]["format"], "dxf")
        self.assertEqual(res["result"]["method"], "flatPattern.exportManager.createDXFExportOptions")
        self.assertEqual(executed, [("dxf", export_path)])

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

    def test_inspect_drawing_documents_reports_sheets_and_views(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        drawing_module = types.ModuleType("adsk.drawing")
        view = types.SimpleNamespace(name="Base View", objectType="DrawingView", scale=1.0, orientation="front", viewStyle="visible")
        sheet = types.SimpleNamespace(
            name="Sheet 1",
            objectType="DrawingSheet",
            size="B",
            orientation="landscape",
            drawingViews=[view],
            titleBlock=types.SimpleNamespace(name="Title Block", objectType="TitleBlock"),
            partsLists=[],
            tables=[],
            dimensions=[types.SimpleNamespace()],
        )
        drawing_doc = types.SimpleNamespace(drawing=types.SimpleNamespace(objectType="Drawing", sheets=[sheet]))
        drawing_module.DrawingDocument = types.SimpleNamespace(cast=lambda doc: drawing_doc if getattr(doc, "name", "") == "DrawingDoc" else None)
        sys.modules["adsk.drawing"] = drawing_module
        drawing_document = types.SimpleNamespace(
            name="DrawingDoc",
            documentType=1,
            isModified=False,
            dataFile=types.SimpleNamespace(name="DrawingData"),
        )
        design_document = types.SimpleNamespace(
            name="DesignDoc",
            documentType=0,
            isModified=True,
            dataFile=None,
        )
        _fake_app.activeDocument = drawing_document
        _fake_app.documents = [drawing_document, design_document]
        try:
            res = self.tools.execute_tool("inspect_drawing_documents", {})
        finally:
            if original_drawing_module is None:
                sys.modules.pop("adsk.drawing", None)
            else:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertEqual(res["result"]["drawingDocumentCount"], 1)
        drawing_report = res["result"]["documents"][0]
        self.assertTrue(drawing_report["isDrawingDocument"])
        self.assertEqual(drawing_report["sheets"][0]["views"][0]["name"], "Base View")
        self.assertEqual(drawing_report["sheets"][0]["dimensionsCount"], 1)

    def test_preflight_drawing_creation_blocks_unsaved_or_relative_path(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        sys.modules.pop("adsk.drawing", None)
        _fake_app.activeDocument = types.SimpleNamespace(name="UnsavedDoc", isModified=True, dataFile=None)
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        try:
            res = self.tools.execute_tool("preflight_drawing_creation", {"export_pdf_path": "relative.pdf"})
        finally:
            if original_drawing_module is not None:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("result", res)
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("The active design must be saved", joined)
        self.assertIn("export_pdf_path must be absolute", joined)
        self.assertIn("DrawingManager is not available", joined)

    def test_preflight_drawing_creation_passes_for_saved_document_and_absolute_path(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        drawing_module = types.ModuleType("adsk.drawing")
        drawing_module.DrawingManager = types.SimpleNamespace(get=lambda: types.SimpleNamespace())
        sys.modules["adsk.drawing"] = drawing_module
        _fake_app.activeDocument = types.SimpleNamespace(
            name="SavedDoc",
            isModified=False,
            dataFile=types.SimpleNamespace(name="SavedData"),
        )
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        export_path = os.path.join(self.temp_dir.name, "drawing.pdf")
        try:
            res = self.tools.execute_tool("preflight_drawing_creation", {"export_pdf_path": export_path})
        finally:
            if original_drawing_module is None:
                sys.modules.pop("adsk.drawing", None)
            else:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("result", res)
        self.assertTrue(res["result"]["okToProceed"])
        self.assertTrue(res["result"]["drawingManagerAvailable"])
        self.assertEqual(res["result"]["exportPdfPath"], export_path)

    def test_plan_drawing_views_defaults_and_preflight(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        drawing_module = types.ModuleType("adsk.drawing")
        drawing_module.DrawingManager = types.SimpleNamespace(get=lambda: types.SimpleNamespace())
        sys.modules["adsk.drawing"] = drawing_module
        _fake_app.activeDocument = types.SimpleNamespace(
            name="SavedDoc",
            isModified=False,
            dataFile=types.SimpleNamespace(name="SavedData"),
        )
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        try:
            res = self.tools.execute_tool("plan_drawing_views", {})
        finally:
            if original_drawing_module is None:
                sys.modules.pop("adsk.drawing", None)
            else:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("result", res)
        self.assertTrue(res["result"]["readOnly"])
        self.assertTrue(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["sheet"]["standard"], "ASME")
        self.assertEqual(res["result"]["sheet"]["sheetSize"], "A")
        self.assertEqual(res["result"]["views"][0]["orientation"], "front")
        self.assertEqual(res["result"]["views"][0]["scale"], 1.0)

    def test_plan_drawing_views_validates_explicit_metadata(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        sys.modules.pop("adsk.drawing", None)
        _fake_app.activeDocument = types.SimpleNamespace(name="UnsavedDoc", isModified=True, dataFile=None)
        _fake_app.activeProduct = types.SimpleNamespace(rootComponent=types.SimpleNamespace(name="Root"))
        try:
            res = self.tools.execute_tool("plan_drawing_views", {
                "standard": "DIN",
                "sheet_size": "Z",
                "sheet_orientation": "diagonal",
                "units": "cm",
                "export_pdf_path": "relative.pdf",
                "views": [{"name": "Bad View", "orientation": "up", "style": "wire", "scale": 0}],
            })
        finally:
            if original_drawing_module is not None:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("result", res)
        self.assertFalse(res["result"]["okToProceed"])
        joined = " ".join(res["result"]["blockingReasons"])
        self.assertIn("standard must be one of", joined)
        self.assertIn("sheet_size must be one of", joined)
        self.assertIn("orientation must be one of", joined)
        self.assertIn("scale must be a positive number", joined)
        self.assertIn("export_pdf_path must be absolute", joined)
        self.assertIn("DrawingManager is not available", joined)

    def test_add_drawing_dimension_requires_tokens_and_reason(self):
        res = self.tools.execute_tool("add_drawing_dimension", {
            "view_name": "Front",
            "reason": "Add checked reference dimension.",
        })

        self.assertIn("error", res)
        self.assertIn("geometry_entity_tokens are required", res["error"])

        res = self.tools.execute_tool("add_revision_table", {})
        self.assertIn("error", res)
        self.assertIn("reason is required", res["error"])

    def test_add_drawing_callout_reports_unsupported_without_drawing_api(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        sys.modules.pop("adsk.drawing", None)
        try:
            res = self.tools.execute_tool("add_drawing_callout", {
                "text": "CHECK FIT",
                "reason": "Add review callout.",
            })
        finally:
            if original_drawing_module is not None:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("error", res)
        self.assertTrue(res["unsupported"])
        self.assertIn("Drawing API is not available", res["error"])

    def test_add_drawing_callout_uses_writable_note_collection(self):
        utilities = importlib.import_module("tools.utilities")
        original_drawing_module = sys.modules.get("adsk.drawing")
        old_snapshot = utilities._design_state_snapshot
        old_compare = utilities.compare_design_state

        class _NoteCollection:
            def __init__(self):
                self.payloads = []

            def add(self, payload):
                self.payloads.append(payload)
                return types.SimpleNamespace(name="Callout 1", objectType="DrawingNote")

        notes = _NoteCollection()
        sheet = types.SimpleNamespace(name="Sheet 1", notes=notes)
        drawing_doc = types.SimpleNamespace(drawing=types.SimpleNamespace(sheets=[sheet]))
        drawing_module = types.ModuleType("adsk.drawing")
        drawing_module.DrawingDocument = types.SimpleNamespace(cast=lambda doc: drawing_doc)
        sys.modules["adsk.drawing"] = drawing_module
        _fake_app.activeDocument = types.SimpleNamespace(name="DrawingDoc", dataFile=types.SimpleNamespace(name="DrawingData"))
        snapshots = [{"snapshot": "before"}, {"snapshot": "after"}]
        try:
            utilities._design_state_snapshot = lambda include_selections=False: snapshots.pop(0)
            utilities.compare_design_state = lambda before, after: {"result": {"changed": before != after}}

            res = self.tools.execute_tool("add_drawing_callout", {
                "text": "CHECK FIT",
                "placement": {"x": 10, "y": 20},
                "reason": "Add review callout.",
            })
        finally:
            utilities._design_state_snapshot = old_snapshot
            utilities.compare_design_state = old_compare
            if original_drawing_module is None:
                sys.modules.pop("adsk.drawing", None)
            else:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("result", res)
        self.assertEqual(res["result"]["operation"], "add_drawing_callout")
        self.assertEqual(res["result"]["createdName"], "Callout 1")
        self.assertEqual(notes.payloads[0]["text"], "CHECK FIT")
        self.assertTrue(res["result"]["stateComparison"]["changed"])

    def test_add_drawing_view_blocks_failed_plan(self):
        original_drawing_module = sys.modules.get("adsk.drawing")
        sys.modules.pop("adsk.drawing", None)
        _fake_app.activeDocument = types.SimpleNamespace(name="UnsavedDoc", isModified=True, dataFile=None)
        try:
            res = self.tools.execute_tool("add_drawing_view", {
                "view": {"name": "Bad", "orientation": "up", "scale": 0},
                "reason": "Add front view.",
            })
        finally:
            if original_drawing_module is not None:
                sys.modules["adsk.drawing"] = original_drawing_module

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["okToProceed"])

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

    def test_run_fusion_script_requires_fallback_justification(self):
        script = """
def run(context):
    print('raw fallback')
"""
        res = self.tools.execute_tool("run_fusion_script", {"script": script})
        self.assertIn("error", res)
        self.assertIn("script_intent", res["error"])

    def test_run_fusion_script_blocks_raw_export_api_by_default(self):
        script = """
def run(context):
    exportMgr = design.exportManager
    exportMgr.createSTEPExportOptions('C:/tmp/model.step', rootComp)
"""
        res = self.tools.execute_tool("run_fusion_script", {
            "script": script,
            "script_intent": "Exercise raw export blocking.",
            "mcp_tool_gap": "Unit test intentionally targets the fallback export guard.",
        })
        self.assertIn("error", res)
        self.assertIn("Scripted Fusion exports are blocked", res["error"])

    def test_run_fusion_script_export_override_requires_reason(self):
        script = """
def run(context):
    exportMgr = design.exportManager
"""
        res = self.tools.execute_tool("run_fusion_script", {
            "script": script,
            "script_intent": "Exercise raw export override validation.",
            "mcp_tool_gap": "Unit test intentionally targets the fallback export guard.",
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
        res = self.tools.execute_tool("run_fusion_script", {
            "script": script,
            "script_intent": "Exercise raw drawing export blocking.",
            "mcp_tool_gap": "Unit test intentionally targets the fallback drawing export guard.",
        })
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
            "script_intent": "Exercise raw drawing export override validation.",
            "mcp_tool_gap": "Unit test intentionally targets the fallback drawing export guard.",
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
            "script_intent": "Diagnostic script that mentions an export marker without writing a file.",
            "mcp_tool_gap": "Unit test intentionally verifies the export marker override path.",
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
        self.assertIn("streamable_http", payload["transports"])
        self.assertIn("task_manager_running", payload)
        self.assertIn("pending_tasks", payload)
        self.assertIn("discovery", payload)
        self.assertIn("source_root", payload)
        self.assertIn("source_fingerprint", payload)
        self.assertEqual(payload["source_fingerprint"]["algorithm"], "sha256")
        self.assertTrue(payload["source_fingerprint"]["fingerprint"])
        fingerprint_paths = [item["path"] for item in payload["source_fingerprint"]["files"]]
        self.assertIn("tools/features.py", fingerprint_paths)
        self.assertIn("install_metadata", payload)
        self.assertIn("active_http_sessions", payload)
        self.assertNotIn("sse_url", payload)
        self.assertNotIn("token", json.dumps(payload))

    def test_streamable_http_sessions_prune_expired_entries(self):
        self.mcp_server.http_sessions.clear()
        now = 1000.0
        self.mcp_server.http_sessions["fresh"] = now
        self.mcp_server.http_sessions["expired"] = now - self.mcp_server.HTTP_SESSION_TTL_SECONDS - 1

        expired = self.mcp_server.prune_http_sessions(now=now)

        self.assertEqual(expired, ["expired"])
        self.assertIn("fresh", self.mcp_server.http_sessions)
        self.assertNotIn("expired", self.mcp_server.http_sessions)

    def test_streamable_http_touch_refreshes_existing_session(self):
        self.mcp_server.http_sessions.clear()
        self.mcp_server.http_sessions["session-a"] = 1000.0

        self.assertTrue(self.mcp_server.touch_http_session("session-a", now=1200.0))

        self.assertEqual(self.mcp_server.http_sessions["session-a"], 1200.0)

    def test_streamable_http_touch_rejects_expired_session(self):
        self.mcp_server.http_sessions.clear()
        self.mcp_server.http_sessions["session-a"] = 1000.0

        self.assertFalse(
            self.mcp_server.touch_http_session(
                "session-a",
                now=1000.0 + self.mcp_server.HTTP_SESSION_TTL_SECONDS + 1,
            )
        )
        self.assertNotIn("session-a", self.mcp_server.http_sessions)

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

    def test_sse_allows_bearer_auth_without_tokenized_endpoint(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/sse",
                headers={"Authorization": f"Bearer {self.mcp_server.auth_token}"},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                first_line = response.readline().decode("utf-8").strip()
                second_line = response.readline().decode("utf-8").strip()
            self.assertEqual(response.status, 200)
            self.assertEqual(first_line, "event: endpoint")
            self.assertIn("/messages?session_id=", second_line)
            self.assertNotIn("&token=", second_line)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_http_messages_accepts_bearer_auth(self):
        session_id = "http-bearer-session"
        self.mcp_server.sessions[session_id] = queue.Queue()
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            url = f"http://127.0.0.1:{server.server_port}/messages?session_id={session_id}"
            request = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
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
        self.assertIn("doctor", message["result"]["instructions"])
        self.assertIn("run_fusion_script only as a last resort", message["result"]["instructions"])

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

    def test_streamable_http_initialize_requires_auth(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_streamable_http_initialize_creates_session(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                body = json.loads(response.read().decode("utf-8"))
                session_id = response.headers.get("Mcp-Session-Id")
            self.assertEqual(response.status, 200)
            self.assertTrue(session_id)
            self.assertEqual(body["result"]["serverInfo"]["name"], "fusion-mcp")
            self.assertIn("doctor", body["result"]["instructions"])
            self.assertIn("fusion://agent/tool-first-workflow", body["result"]["instructions"])
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
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=init_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(init_request, timeout=2) as response:
                session_id = response.headers.get("Mcp-Session-Id")

            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            tools_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=tools_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": session_id,
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(tools_request, timeout=2) as response:
                body = json.loads(response.read().decode("utf-8"))
            tool_names = {tool["name"] for tool in body["result"]["tools"]}
            self.assertIn("inspect_design", tool_names)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_streamable_http_rejects_malformed_session_header(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            init_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=init_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(init_request, timeout=2) as response:
                self.assertTrue(response.headers.get("Mcp-Session-Id"))

            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            tools_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=tools_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": "System.String[]",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(tools_request, timeout=2)
            self.assertEqual(ctx.exception.code, 400)
            body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertIn("PowerShell", body["error"]["message"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_streamable_http_followup_requires_auth(self):
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            init_payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).encode("utf-8")
            init_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=init_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(init_request, timeout=2) as response:
                session_id = response.headers.get("Mcp-Session-Id")

            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            tools_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=tools_payload,
                method="POST",
                headers={"Content-Type": "application/json", "Mcp-Session-Id": session_id},
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(tools_request, timeout=2)
            self.assertEqual(ctx.exception.code, 403)
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
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=init_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(init_request, timeout=2) as response:
                session_id = response.headers.get("Mcp-Session-Id")

            delete_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=b"",
                method="DELETE",
                headers={
                    "Mcp-Session-Id": session_id,
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with urllib.request.urlopen(delete_request, timeout=2) as response:
                self.assertEqual(response.status, 200)

            tools_payload = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}).encode("utf-8")
            tools_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/mcp",
                data=tools_payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Mcp-Session-Id": session_id,
                    "Authorization": f"Bearer {self.mcp_server.auth_token}",
                },
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(tools_request, timeout=2)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_sse_messages_delete_closes_session(self):
        session_id = "sse-delete-session"
        self.mcp_server.sessions[session_id] = queue.Queue()
        self.mcp_server.subscriptions[session_id] = {"fusion://runtime/change-journal"}
        server = self.mcp_server.ThreadedHTTPServer(("127.0.0.1", 0), self.mcp_server.MCPServerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            delete_request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/messages?session_id={session_id}&token={self.mcp_server.auth_token}",
                data=b"",
                method="DELETE",
            )
            with urllib.request.urlopen(delete_request, timeout=2) as response:
                self.assertEqual(response.status, 200)

            self.assertNotIn(session_id, self.mcp_server.sessions)
            self.assertNotIn(session_id, self.mcp_server.subscriptions)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.mcp_server.sessions.pop(session_id, None)
            self.mcp_server.subscriptions.pop(session_id, None)

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
        self.assertIn("get_projected_geometry_sources", tool_names)
        self.assertIn("inspect_feature", tool_names)
        self.assertIn("get_sketch_parameters", tool_names)
        self.assertIn("get_feature_parameters", tool_names)
        self.assertIn("get_parameter_usage", tool_names)
        self.assertIn("get_feature_dependencies", tool_names)
        self.assertIn("get_dependency_graph", tool_names)
        self.assertIn("assess_change_impact", tool_names)
        self.assertIn("plan_parameterization", tool_names)
        self.assertIn("map_coordinates", tool_names)
        self.assertIn("create_sketch", tool_names)
        self.assertIn("draw_line", tool_names)
        self.assertIn("draw_rectangle", tool_names)
        self.assertIn("draw_circle", tool_names)
        self.assertIn("project_geometry", tool_names)
        self.assertIn("create_offset_plane", tool_names)
        self.assertIn("create_construction_point", tool_names)
        self.assertIn("create_construction_axis", tool_names)
        self.assertIn("get_body_edges", tool_names)
        self.assertIn("get_body_faces", tool_names)
        self.assertIn("get_assembly_references", tool_names)
        self.assertIn("offset_face_or_press_pull", tool_names)
        self.assertIn("extrude_feature", tool_names)
        self.assertIn("revolve_feature", tool_names)
        self.assertIn("loft_feature", tool_names)
        self.assertIn("sweep_feature", tool_names)
        self.assertIn("fillet_feature", tool_names)
        self.assertIn("chamfer_feature", tool_names)
        self.assertIn("shell_body", tool_names)
        self.assertIn("preflight_model_change", tool_names)
        self.assertIn("extract_reference_dimensions", tool_names)
        self.assertIn("create_rounded_rectangle_body", tool_names)
        self.assertIn("create_rounded_slot_cut", tool_names)
        self.assertIn("create_rounded_pocket", tool_names)
        self.assertIn("create_hole_pattern", tool_names)
        self.assertIn("create_counterbore_hole_pattern", tool_names)
        self.assertIn("mirror_features_or_bodies", tool_names)
        self.assertIn("pattern_feature", tool_names)
        self.assertIn("set_visibility", tool_names)
        self.assertIn("capture_demo_sequence", tool_names)
        self.assertIn("revert_active_document", tool_names)
        self.assertIn("get_runtime_diagnostics", tool_names)
        self.assertIn("doctor", tool_names)
        self.assertIn("get_change_journal", tool_names)
        self.assertIn("clear_change_journal", tool_names)
        self.assertIn("inspect_printability", tool_names)

    def test_get_runtime_diagnostics_reports_missing_required_tools_and_redacts_token(self):
        utilities = importlib.import_module("tools.utilities")
        original_expanduser = utilities.os.path.expanduser
        discovery_dir = tempfile.TemporaryDirectory()
        self.addCleanup(discovery_dir.cleanup)
        discovery_path = os.path.join(discovery_dir.name, ".fusion_mcp.json")
        with open(discovery_path, "w", encoding="utf-8") as f:
            json.dump({
                "sse_url": "http://127.0.0.1:9100/sse?token=secret-token",
                "authorization_header": "Bearer secret-token",
                "port": 9100,
                "token": "secret-token",
            }, f)

        utilities.os.path.expanduser = (
            lambda path: discovery_dir.name if path == "~" else original_expanduser(path)
        )
        try:
            res = self.tools.execute_tool("get_runtime_diagnostics", {
                "required_tools": ["inspect_design", "missing_tool"],
            })
        finally:
            utilities.os.path.expanduser = original_expanduser

        self.assertIn("result", res)
        result = res["result"]
        self.assertIn("missing_tool", result["requiredTools"]["missingFromSchema"])
        self.assertIn("missing_tool", result["requiredTools"]["missingFromRegistry"])
        self.assertTrue(result["restartRecommended"])
        self.assertIn("sourceFingerprint", result["runtime"])
        self.assertEqual(result["runtime"]["sourceFingerprint"]["algorithm"], "sha256")
        self.assertTrue(result["runtime"]["sourceFingerprint"]["fingerprint"])
        fingerprint_paths = [item["path"] for item in result["runtime"]["sourceFingerprint"]["files"]]
        self.assertIn("tools/features.py", fingerprint_paths)
        self.assertIn("tools/utilities.py", fingerprint_paths)
        self.assertEqual(result["runtime"]["discovery"]["payload"]["token"], "<redacted>")
        self.assertEqual(result["runtime"]["discovery"]["payload"]["authorization_header"], "<redacted>")
        self.assertIn("token=<redacted>", result["runtime"]["discovery"]["payload"]["sse_url"])

    def test_doctor_reports_stale_discovery_and_task_manager_blockers(self):
        utilities = importlib.import_module("tools.utilities")
        original_expanduser = utilities.os.path.expanduser
        original_server_status = utilities._server_runtime_status
        discovery_dir = tempfile.TemporaryDirectory()
        self.addCleanup(discovery_dir.cleanup)
        discovery_path = os.path.join(discovery_dir.name, ".fusion_mcp.json")
        with open(discovery_path, "w", encoding="utf-8") as f:
            json.dump({
                "sse_url": "http://127.0.0.1:9100/sse?token=stale-token",
                "authorization_header": "Bearer stale-token",
                "port": 9100,
                "token": "stale-token",
            }, f)

        utilities.os.path.expanduser = (
            lambda path: discovery_dir.name if path == "~" else original_expanduser(path)
        )
        utilities._server_runtime_status = lambda: {
            "available": True,
            "authToken": "live-token",
            "defaultPort": 9100,
            "serverRunning": True,
            "taskManagerRunning": False,
            "pendingTasks": 0,
        }
        try:
            res = self.tools.execute_tool("doctor", {
                "required_tools": ["inspect_design"],
                "require_active_design": False,
            })
        finally:
            utilities.os.path.expanduser = original_expanduser
            utilities._server_runtime_status = original_server_status

        self.assertIn("result", res)
        result = res["result"]
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["toolExecutionReady"])
        self.assertIn("TaskManager is not running", " ".join(result["blockingReasons"]))
        self.assertIn("Discovery token does not match", " ".join(result["blockingReasons"]))
        self.assertEqual(result["checks"]["discovery"]["payload"]["token"], "<redacted>")
        self.assertEqual(result["checks"]["discovery"]["payload"]["authorization_header"], "<redacted>")

    def test_plan_parameterization_classifies_sketch_dimension_candidates(self):
        class ParamCollection:
            def __init__(self, params):
                self.params = params
                self.count = len(params)

            def item(self, index):
                return self.params[index]

            def itemByName(self, name):
                for param in self.params:
                    if param.name == name:
                        return param
                return None

            def __iter__(self):
                return iter(self.params)

        screen_width = types.SimpleNamespace(
            name="screenWidth",
            expression="100 mm",
            value=10.0,
            unit="mm",
            comment="Public screen width",
            objectType="UserParameter",
            entityToken="user-token",
            isFavorite=True,
            role=None,
        )
        literal_param = types.SimpleNamespace(
            name="d1",
            expression="42 mm",
            value=4.2,
            unit="mm",
            comment="",
            objectType="ModelParameter",
            entityToken="d1-token",
        )
        referenced_param = types.SimpleNamespace(
            name="d2",
            expression="screenWidth / 2",
            value=5.0,
            unit="mm",
            comment="",
            objectType="ModelParameter",
            entityToken="d2-token",
        )
        sketch = types.SimpleNamespace(
            name="ParamSketch",
            isVisible=True,
            isFullyConstrained=True,
            boundingBox=None,
            sketchDimensions=[
                types.SimpleNamespace(name="LiteralDim", objectType="SketchLinearDimension", parameter=literal_param),
                types.SimpleNamespace(name="BoundDim", objectType="SketchLinearDimension", parameter=referenced_param),
            ],
            geometricConstraints=[],
            sketchPoints=[],
            sketchCurves=types.SimpleNamespace(),
        )
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[],
            sketches=[sketch],
            occurrences=[],
            allOccurrences=[],
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
            designType="parametric",
            userParameters=ParamCollection([screen_width]),
            allParameters=ParamCollection([literal_param, referenced_param]),
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
        )
        _fake_app.activeDocument = types.SimpleNamespace(name="ParamDoc", isModified=False)
        _fake_app.documents = [_fake_app.activeDocument]

        res = self.tools.execute_tool("plan_parameterization", {"target_sketches": "ParamSketch"})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["summary"]["sketchesAnalyzed"], 1)
        self.assertEqual(result["summary"]["safeExpressionCandidates"], 1)
        self.assertEqual(result["summary"]["alreadyParameterized"], 1)
        self.assertEqual(result["safeExpressionCandidates"][0]["parameterName"], "d1")
        self.assertEqual(result["alreadyParameterized"][0]["parameter"]["name"], "d2")
        self.assertEqual(result["riskLevel"], "low")

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

    def test_inspect_printability_reports_fdm_risks_without_mutation(self):
        tiny_edge = types.SimpleNamespace(length=0.02)
        small_cylindrical_face = types.SimpleNamespace(
            area=0.2,
            geometry=types.SimpleNamespace(
                objectType="adsk::core::Cylinder",
                radius=0.04,
            ),
        )
        downward_face = types.SimpleNamespace(
            area=0.4,
            geometry=types.SimpleNamespace(
                objectType="adsk::core::Plane",
                normal=types.SimpleNamespace(x=0, y=0, z=-1),
            ),
        )
        body = types.SimpleNamespace(
            name="RiskyBody",
            isVisible=True,
            isSolid=True,
            entityToken="risk-token",
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0, y=0, z=0),
                maxPoint=types.SimpleNamespace(x=0.02, y=3.0, z=4.0),
            ),
            physicalProperties=types.SimpleNamespace(volume=0.24, area=25.0),
            edges=[tiny_edge],
            faces=[small_cylindrical_face, downward_face],
        )
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[body],
            sketches=[],
            occurrences=[],
            allOccurrences=[],
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("inspect_printability", {})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["bodyCount"], 1)
        self.assertEqual(result["riskLevel"], "high")
        self.assertEqual(result["bodies"][0]["sizeMm"], [0.2, 30.0, 40.0])
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("tiny_body_dimension", codes)
        self.assertIn("tiny_edge_features", codes)
        self.assertIn("small_hole_or_pin_candidate", codes)
        self.assertIn("risky_overhang_or_lip_candidate", codes)
        self.assertEqual(result["bodies"][0]["meshAnalysis"]["status"], "unavailable")

    def test_inspect_printability_reports_mesh_analysis_when_available(self):
        mesh = types.SimpleNamespace(
            nodeCoordinates=[
                types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                types.SimpleNamespace(x=0.0, y=0.01, z=0.0),
                types.SimpleNamespace(x=0.01, y=0.0, z=0.0),
            ],
            triangleNodeIndices=[0, 1, 2],
        )
        body = types.SimpleNamespace(
            name="MeshRiskBody",
            isVisible=True,
            isSolid=True,
            entityToken="mesh-risk-token",
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0, y=0, z=0),
                maxPoint=types.SimpleNamespace(x=10.0, y=10.0, z=10.0),
            ),
            physicalProperties=types.SimpleNamespace(volume=100.0, area=600.0),
            edges=[],
            faces=[],
            triangleMesh=mesh,
        )
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[body],
            sketches=[],
            occurrences=[],
            allOccurrences=[],
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("inspect_printability", {
            "minimum_feature_size": "0.5 mm",
            "overhang_angle_degrees": 45,
        })

        self.assertIn("result", res)
        result = res["result"]
        analysis = result["bodies"][0]["meshAnalysis"]
        self.assertEqual(analysis["status"], "analyzed")
        self.assertEqual(analysis["triangleCount"], 1)
        self.assertEqual(analysis["nodeCount"], 3)
        self.assertLess(analysis["minimumTriangleEdgeMm"], 0.5)
        codes = {warning["code"] for warning in result["warnings"]}
        self.assertIn("mesh_tiny_triangle_edges", codes)
        self.assertIn("mesh_overhang_triangles", codes)

    def test_inspect_mesh_bodies_reports_mesh_metadata(self):
        mesh = types.SimpleNamespace(
            nodeCoordinates=[
                types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                types.SimpleNamespace(x=1.0, y=0.0, z=0.0),
                types.SimpleNamespace(x=0.0, y=1.0, z=0.0),
            ],
            triangleNodeIndices=[0, 1, 2],
        )
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            isLightBulbOn=True,
            entityToken="mesh-token",
            objectType="MeshBody",
            boundingBox=types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0, y=0, z=0),
                maxPoint=types.SimpleNamespace(x=2.0, y=3.0, z=4.0),
            ),
            triangleMesh=mesh,
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshToBREPFeatures=object()),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("inspect_mesh_bodies", {})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertEqual(result["meshBodyCount"], 1)
        self.assertTrue(result["conversionCapabilities"]["meshToBrepAvailable"])
        body = result["meshBodies"][0]
        self.assertEqual(body["name"], "ScanMesh")
        self.assertEqual(body["entityToken"], "mesh-token")
        self.assertEqual(body["sizeMm"], [20.0, 30.0, 40.0])
        self.assertEqual(body["meshAnalysis"]["triangleCount"], 1)

    def test_plan_mesh_conversion_blocks_without_explicit_acknowledgement(self):
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshToBREPFeatures=object()),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("plan_mesh_conversion", {"body_name": "ScanMesh"})

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["readOnly"])
        self.assertFalse(result["ready"])
        self.assertTrue(any("reason" in blocker for blocker in result["blockers"]))
        self.assertTrue(any("acknowledge_quality_loss" in blocker for blocker in result["blockers"]))
        self.assertEqual(result["target"]["name"], "ScanMesh")

    def test_plan_mesh_conversion_ready_when_runtime_and_inputs_are_explicit(self):
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshToBREPFeatures=object()),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("plan_mesh_conversion", {
            "body_entity_token": "mesh-token",
            "conversion_intent": "convert_to_brep",
            "operation": "new_body",
            "acknowledge_quality_loss": True,
            "reason": "Convert imported scan reference into editable BRep.",
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["ready"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["normalizedRequest"]["conversionIntent"], "convert_to_brep")
        self.assertEqual(result["target"]["entityToken"], "mesh-token")

    def test_convert_mesh_to_solid_blocks_without_mesh_preflight_acknowledgement(self):
        class FakeMeshToBrepFeatures:
            def __init__(self):
                self.add_called = False

            def createInput(self, *_args):
                return types.SimpleNamespace()

            def add(self, *_args):
                self.add_called = True
                return types.SimpleNamespace(name="")

        mesh_features = FakeMeshToBrepFeatures()
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshToBREPFeatures=mesh_features),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("convert_mesh_to_solid", {"mesh_body_name": "ScanMesh"})

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["ready"])
        self.assertFalse(mesh_features.add_called)

    def test_convert_mesh_to_solid_uses_mesh_preflight_and_exact_token(self):
        class FakeMeshToBrepFeatures:
            def __init__(self):
                self.created = []
                self.added = []

            def createInput(self, mesh, operation):
                mesh_input = types.SimpleNamespace(mesh=mesh, operation=operation)
                self.created.append(mesh_input)
                return mesh_input

            def add(self, mesh_input):
                self.added.append(mesh_input)
                return types.SimpleNamespace(name="")

        mesh_features = FakeMeshToBrepFeatures()
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshToBREPFeatures=mesh_features),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("convert_mesh_to_solid", {
            "mesh_body_entity_token": "mesh-token",
            "operation": "new_body",
            "acknowledge_quality_loss": True,
            "reason": "Convert imported scan reference into editable BRep.",
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["converted"])
        self.assertEqual(result["meshBodyName"], "ScanMesh")
        self.assertEqual(result["meshBodyEntityToken"], "mesh-token")
        self.assertTrue(result["preflight"]["ready"])
        self.assertEqual(len(mesh_features.created), 1)
        self.assertEqual(mesh_features.created[0].mesh, mesh_body)
        self.assertEqual(len(mesh_features.added), 1)
        self.assertEqual(result["featureName"], "ScanMesh_Solid")

    def test_repair_mesh_body_blocks_without_mesh_preflight_acknowledgement(self):
        class FakeMeshRepairFeatures:
            def __init__(self):
                self.add_called = False

            def createInput(self, *_args):
                return types.SimpleNamespace()

            def add(self, *_args):
                self.add_called = True
                return types.SimpleNamespace(name="")

        repair_features = FakeMeshRepairFeatures()
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshRepairFeatures=repair_features),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("repair_mesh_body", {"mesh_body_name": "ScanMesh"})

        self.assertIn("error", res)
        self.assertIn("preflight", res)
        self.assertFalse(res["preflight"]["ready"])
        self.assertFalse(repair_features.add_called)

    def test_reduce_mesh_body_reports_unsupported_for_incompatible_runtime_collection(self):
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(meshReduceFeatures=types.SimpleNamespace()),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("reduce_mesh_body", {
            "mesh_body_entity_token": "mesh-token",
            "reduction_target": "50 percent triangle count",
            "acknowledge_quality_loss": True,
            "reason": "Reduce imported scan mesh before downstream conversion.",
        })

        self.assertTrue(res["unsupported"])
        self.assertIn("input builder", res["error"])
        self.assertTrue(res["preflight"]["ready"])

    def test_remesh_body_uses_mesh_preflight_and_runtime_collection(self):
        class FakeRemeshFeatures:
            def __init__(self):
                self.created = []
                self.added = []

            def createInput(self, mesh):
                mesh_input = types.SimpleNamespace(mesh=mesh)
                self.created.append(mesh_input)
                return mesh_input

            def add(self, mesh_input):
                self.added.append(mesh_input)
                return types.SimpleNamespace(name="")

        remesh_features = FakeRemeshFeatures()
        mesh_body = types.SimpleNamespace(
            name="ScanMesh",
            isVisible=True,
            entityToken="mesh-token",
            boundingBox=None,
            triangleMesh=types.SimpleNamespace(triangleCount=12, nodeCount=8),
        )
        root = types.SimpleNamespace(
            name="Root",
            meshBodies=[mesh_body],
            allOccurrences=[],
            features=types.SimpleNamespace(remeshFeatures=remesh_features),
        )
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
        )

        res = self.tools.execute_tool("remesh_body", {
            "mesh_body_entity_token": "mesh-token",
            "remesh_type": "uniform",
            "acknowledge_quality_loss": True,
            "reason": "Regularize imported scan triangle distribution.",
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["remeshed"])
        self.assertEqual(result["meshBodyName"], "ScanMesh")
        self.assertEqual(result["meshBodyEntityToken"], "mesh-token")
        self.assertTrue(result["preflight"]["ready"])
        self.assertEqual(len(remesh_features.created), 1)
        self.assertEqual(remesh_features.created[0].mesh, mesh_body)
        self.assertEqual(len(remesh_features.added), 1)
        self.assertEqual(result["featureName"], "ScanMesh_Remesh")

    def test_capture_demo_sequence_writes_frames_and_restores_visibility(self):
        class FakeViewport:
            def __init__(self):
                self.camera = types.SimpleNamespace(viewOrientation=None)
                self.fit_called = False
                self.saved = []

            def fit(self):
                self.fit_called = True

            def saveAsImageFile(self, path, width, height):
                self.saved.append((path, width, height))
                with open(path, "wb") as f:
                    f.write(b"fake-png")

        body = types.SimpleNamespace(
            name="BodyA",
            isVisible=True,
            isLightBulbOn=True,
            isSolid=True,
            entityToken="body-token",
            boundingBox=None,
            physicalProperties=None,
        )
        sketch = types.SimpleNamespace(
            name="SketchA",
            isVisible=True,
            isLightBulbOn=True,
            isFullyConstrained=True,
            boundingBox=None,
            sketchDimensions=[],
            geometricConstraints=[],
            sketchPoints=[],
            sketchCurves=types.SimpleNamespace(),
        )
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[body],
            sketches=[sketch],
            constructionPlanes=[],
            occurrences=[],
            allOccurrences=[],
        )
        _fake_app.activeViewport = FakeViewport()
        _fake_app.activeProduct = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(defaultLengthUnits="mm"),
            designType="parametric",
            userParameters=[],
            allParameters=[],
            timeline=types.SimpleNamespace(count=0, markerPosition=0, item=lambda idx: None),
        )
        _fake_app.activeDocument = types.SimpleNamespace(name="DemoDoc", isModified=False)
        _fake_app.documents = [_fake_app.activeDocument]
        output_dir = os.path.join(self.temp_dir.name, "frames")

        res = self.tools.execute_tool("capture_demo_sequence", {
            "output_dir": output_dir,
            "image_width": 320,
            "image_height": 180,
            "steps": [
                {
                    "name": "hide_body",
                    "view_name": "front",
                    "body_names": ["BodyA"],
                    "visible": False,
                }
            ],
        })

        self.assertIn("result", res)
        result = res["result"]
        self.assertEqual(result["frameCount"], 1)
        self.assertTrue(os.path.exists(result["frames"][0]["filePath"]))
        self.assertEqual(_fake_app.activeViewport.saved[0][1:], (320, 180))
        self.assertTrue(_fake_app.activeViewport.fit_called)
        self.assertTrue(body.isLightBulbOn)
        self.assertTrue(result["restoreVisibility"])

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

    def test_extrude_existing_profile_reports_create_input_failure_with_recovery(self):
        features_module = importlib.import_module("tools.features")

        class MockCollection:
            def __init__(self, items):
                self._items = items
                self.count = len(items)
            def item(self, index):
                return self._items[index]

        class MockExtrudes:
            def createInput(self, _profile, _operation):
                raise RuntimeError("profile is unstable")

        profile = types.SimpleNamespace(name="Profile0", areaProperties=lambda: types.SimpleNamespace())
        component = types.SimpleNamespace(name="Root", features=types.SimpleNamespace(extrudeFeatures=MockExtrudes()))
        sketch = types.SimpleNamespace(
            name="SketchA",
            parentComponent=component,
            isVisible=True,
            isComputeDeferred=False,
            profiles=MockCollection([profile]),
        )
        root = types.SimpleNamespace(name="Root", sketches=[sketch], bRepBodies=[], allOccurrences=[])
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("extrude_existing_profile", {
            "sketch_name": "SketchA",
            "distance": "5 mm",
            "operation": "NewBody",
        })

        self.assertIn("error", res)
        self.assertIn("profile is unstable", res["error"])
        self.assertEqual(res["diagnostics"]["stage"], "create_input")
        self.assertEqual(res["diagnostics"]["profileCount"], 1)
        self.assertTrue(any("copy_profile_loop" in action for action in res["diagnostics"]["recoveryActions"]))

    def test_copy_profile_loop_projects_only_selected_outer_loop(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state

        class MockCollection:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)
            def item(self, index):
                return self._items[index]
            def __iter__(self):
                return iter(self._items)

        source_line = types.SimpleNamespace(
            name="OuterLine",
            objectType="adsk::fusion::SketchLine",
            entityToken="outer-line-token",
            isConstruction=False,
        )
        inner_line = types.SimpleNamespace(name="InnerLine", objectType="adsk::fusion::SketchLine", entityToken="inner-line-token")
        outer_loop = types.SimpleNamespace(
            isOuter=True,
            profileCurves=MockCollection([types.SimpleNamespace(sketchEntity=source_line)]),
        )
        inner_loop = types.SimpleNamespace(
            isOuter=False,
            profileCurves=MockCollection([types.SimpleNamespace(sketchEntity=inner_line)]),
        )
        profile = types.SimpleNamespace(profileLoops=MockCollection([inner_loop, outer_loop]))
        projected = []

        class DestinationSketch:
            name = "LoopCopy"
            def project(self, entity):
                copied = types.SimpleNamespace(
                    name=f"Projected_{entity.name}",
                    objectType=entity.objectType,
                    entityToken=f"projected-{entity.entityToken}",
                    isConstruction=False,
                )
                projected.append(entity.name)
                return MockCollection([copied])

        component = types.SimpleNamespace(name="Root")
        source = types.SimpleNamespace(name="Sketch163", parentComponent=component, profiles=MockCollection([profile]))
        destination = DestinationSketch()
        root = types.SimpleNamespace(name="Root", sketches=[source, destination], bRepBodies=[], allOccurrences=[])
        self.mock_design = types.SimpleNamespace(rootComponent=root)
        _fake_app.activeProduct = self.mock_design
        features_module._design_state_snapshot = lambda include_selections=False: {"counts": {"sketches": 2}}
        features_module.compare_design_state = lambda before, after: {"result": {"hasChanges": True, "riskLevel": "low"}}
        try:
            res = self.tools.execute_tool("copy_profile_loop", {
                "source_sketch_name": "Sketch163",
                "profile_index": 0,
                "outer_loop": True,
                "destination_sketch_name": "LoopCopy",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(projected, ["OuterLine"])
        self.assertEqual(res["result"]["loopIndex"], 1)
        self.assertEqual(res["result"]["copiedCurveCount"], 1)
        self.assertEqual(res["result"]["copiedCurves"][0]["entityToken"], "projected-outer-line-token")

    def test_offset_profile_loop_offsets_only_loop_curves(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state

        class MockCollection:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)
            def item(self, index):
                return self._items[index]
            def add(self, item):
                self._items.append(item)
                self.count = len(self._items)
            def __iter__(self):
                return iter(self._items)

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        source_line = types.SimpleNamespace(name="OuterLine", objectType="adsk::fusion::SketchLine", entityToken="outer-line-token")
        ignored_line = types.SimpleNamespace(name="ReferenceLogoLine", objectType="adsk::fusion::SketchLine", entityToken="ignored-token")
        profile_loop = types.SimpleNamespace(
            isOuter=True,
            profileCurves=MockCollection([types.SimpleNamespace(sketchEntity=source_line)]),
        )
        profile = types.SimpleNamespace(
            profileLoops=MockCollection([profile_loop]),
            areaProperties=lambda: types.SimpleNamespace(centroid=types.SimpleNamespace(x=0, y=0, z=0)),
        )
        offset_inputs = []

        class MockSketch:
            name = "Sketch163"
            profiles = MockCollection([profile])
            def offset(self, curves, direction_point, distance):
                offset_inputs.append((list(curves), direction_point, distance))
                return MockCollection([types.SimpleNamespace(name="OffsetOuterLine", objectType="adsk::fusion::SketchLine", entityToken="offset-token", isConstruction=False)])

        root = types.SimpleNamespace(name="Root", sketches=[MockSketch()], bRepBodies=[], allOccurrences=[])
        self.mock_design = types.SimpleNamespace(
            rootComponent=root,
            unitsManager=types.SimpleNamespace(evaluateExpression=lambda expression, _units: 0.02),
        )
        _fake_app.activeProduct = self.mock_design
        core = sys.modules["adsk.core"]
        original_object_collection = core.ObjectCollection
        core.ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())
        features_module._design_state_snapshot = lambda include_selections=False: {"counts": {"sketches": 1}}
        features_module.compare_design_state = lambda before, after: {"result": {"hasChanges": True, "riskLevel": "low"}}
        try:
            res = self.tools.execute_tool("offset_profile_loop", {
                "sketch_name": "Sketch163",
                "profile_index": 0,
                "outer_loop": True,
                "offset_distance": "0.2 mm",
            })
        finally:
            core.ObjectCollection = original_object_collection
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(offset_inputs[0][0], [source_line])
        self.assertNotIn(ignored_line, offset_inputs[0][0])
        self.assertEqual(res["result"]["offsetCurveCount"], 1)
        self.assertEqual(res["result"]["offsetCurves"][0]["entityToken"], "offset-token")

    def test_create_insert_socket_creates_plate_cutter_and_socket_cut(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state

        class MockCollection:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)
            def item(self, index):
                return self._items[index]
            def add(self, item):
                self._items.append(item)
                self.count = len(self._items)
            def __iter__(self):
                return iter(self._items)

        def bbox():
            return types.SimpleNamespace(
                minPoint=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
                maxPoint=types.SimpleNamespace(x=4.0, y=3.0, z=0.2),
            )

        class MockUnits:
            defaultLengthUnits = "mm"
            def evaluateExpression(self, expression, _units):
                text = str(expression).strip().lower().replace("mm", "").strip()
                return float(text or 0) / 10.0

        source_line = types.SimpleNamespace(name="OuterLine", objectType="adsk::fusion::SketchLine", entityToken="outer-token")
        source_loop = types.SimpleNamespace(
            isOuter=True,
            profileCurves=MockCollection([types.SimpleNamespace(sketchEntity=source_line)]),
        )
        source_profile = types.SimpleNamespace(
            profileLoops=MockCollection([source_loop]),
            areaProperties=lambda: types.SimpleNamespace(centroid=types.SimpleNamespace(x=0, y=0, z=0)),
        )
        work_profile = types.SimpleNamespace(
            profileLoops=MockCollection([source_loop]),
            areaProperties=lambda: types.SimpleNamespace(centroid=types.SimpleNamespace(x=0, y=0, z=0)),
        )
        target = types.SimpleNamespace(name="Cabinet", entityToken="target-token", isVisible=True, boundingBox=bbox())
        root_bodies = [target]
        created_features = []
        combine_inputs = []

        class MockExtrudeInput:
            def __init__(self, profile, operation):
                self.profile = profile
                self.operation = operation
                self.distance = None
            def setDistanceExtent(self, _symmetric, distance):
                self.distance = distance

        class MockExtrudes:
            def createInput(self, profile, operation):
                return MockExtrudeInput(profile, operation)
            def add(self, input_obj):
                body = types.SimpleNamespace(name="", entityToken=f"body-token-{len(root_bodies)}", isVisible=True, boundingBox=bbox())
                root_bodies.append(body)
                feature = types.SimpleNamespace(name="", bodies=MockCollection([body]), input=input_obj)
                created_features.append(feature)
                return feature

        class MockCombineInput:
            def __init__(self, target_body, tools):
                self.targetBody = target_body
                self.toolBodies = tools
                self.operation = None
                self.isKeepToolBodies = None

        class MockCombines:
            def createInput(self, target_body, tools):
                combine_input = MockCombineInput(target_body, tools)
                combine_inputs.append(combine_input)
                return combine_input
            def add(self, input_obj):
                return types.SimpleNamespace(name="", input=input_obj)

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(extrudeFeatures=MockExtrudes(), combineFeatures=MockCombines()),
        )
        source = types.SimpleNamespace(name="Sketch163", parentComponent=component, profiles=MockCollection([source_profile]))

        class WorkSketch:
            name = "InsertWork"
            profiles = MockCollection([work_profile])
            def project(self, entity):
                return MockCollection([types.SimpleNamespace(name=f"Projected_{entity.name}", entityToken="projected-token")])

        work = WorkSketch()
        root = types.SimpleNamespace(name="Root", sketches=[source, work], bRepBodies=root_bodies, allOccurrences=[])
        component.sketches = MockCollection([source, work])
        self.mock_design = types.SimpleNamespace(rootComponent=root, unitsManager=MockUnits())
        _fake_app.activeProduct = self.mock_design
        features_module._design_state_snapshot = lambda include_selections=False: {"counts": {"bodies": len(root_bodies)}}
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "medium", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("create_insert_socket", {
                "source_sketch_name": "Sketch163",
                "target_body_name": "Cabinet",
                "insert_thickness": "2 mm",
                "work_sketch_name": "InsertWork",
                "plate_body_name": "LogoPlate",
                "cutter_body_name": "LogoSocketCutter",
                "socket_feature_name": "LogoSocketCut",
                "reason": "Create removable logo plate and matching cabinet pocket.",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare

        self.assertIn("result", res)
        result = res["result"]
        self.assertTrue(result["created"])
        self.assertEqual(result["plateBodyName"], "LogoPlate")
        self.assertEqual(result["cutterBodyName"], "LogoSocketCutter")
        self.assertEqual(result["socketFeatureName"], "LogoSocketCut")
        self.assertEqual(len(created_features), 2)
        self.assertEqual(combine_inputs[0].targetBody, target)
        self.assertFalse(combine_inputs[0].isKeepToolBodies)
        self.assertTrue(result["alignmentVerification"]["okToExport"])
        self.assertEqual(result["diagnostics"]["cutterCleanup"], "combine_cut_consumed_tool_body")

    def test_revolve_feature_creates_named_body_and_state_diff(self):
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
        axis = types.SimpleNamespace(name="Z Axis")
        result_body = types.SimpleNamespace(name="Body0")
        participant_body = types.SimpleNamespace(name="ParticipantBody")
        created_inputs = []

        class MockParticipantBodies:
            def __init__(self):
                self.items = []
            def add(self, body):
                self.items.append(body)

        class MockRevolveInput:
            def __init__(self, profile_arg, axis_arg, operation_arg):
                self.profile = profile_arg
                self.axis = axis_arg
                self.operation = operation_arg
                self.participantBodies = MockParticipantBodies()
                self.angle = None
            def setAngleExtent(self, _is_symmetric, angle):
                self.angle = angle

        class MockRevolves:
            def __bool__(self):
                return False
            def createInput(self, profile_arg, axis_arg, operation_arg):
                input_obj = MockRevolveInput(profile_arg, axis_arg, operation_arg)
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
            features=types.SimpleNamespace(revolveFeatures=MockRevolves()),
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
            zConstructionAxis=axis,
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
            res = self.tools.execute_tool("revolve_feature", {
                "sketch_name": "SketchA",
                "axis_name": "z",
                "angle": "180 deg",
                "operation": "NewBody",
                "name": "RevolveA",
                "body_name": "RevolvedBody",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect

        self.assertIn("result", res)
        self.assertEqual(res["result"]["featureName"], "RevolveA")
        self.assertEqual(res["result"]["operation"], "NewBody")
        self.assertEqual(res["result"]["angle"], "180 deg")
        self.assertEqual(res["result"]["axisName"], "Z Axis")
        self.assertEqual(res["result"]["resultBodies"], ["RevolvedBody"])
        self.assertEqual(created_inputs[0].profile, profile)
        self.assertEqual(created_inputs[0].axis, axis)
        self.assertEqual(created_inputs[0].angle, "180 deg")
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_loft_feature_creates_ordered_profile_sections(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockCollection:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)
            def item(self, index):
                return self._items[index]
            def add(self, item):
                self._items.append(item)
                self.count = len(self._items)

        profile_a = types.SimpleNamespace(name="ProfileA")
        profile_b = types.SimpleNamespace(name="ProfileB")
        result_body = types.SimpleNamespace(name="Body0")
        created_inputs = []

        class MockParticipantBodies:
            def __init__(self):
                self.items = []
            def add(self, body):
                self.items.append(body)

        class MockLoftInput:
            def __init__(self, operation_arg):
                self.operation = operation_arg
                self.loftSections = MockCollection()
                self.participantBodies = MockParticipantBodies()

        class MockLofts:
            def __bool__(self):
                return False
            def createInput(self, operation_arg):
                input_obj = MockLoftInput(operation_arg)
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
            features=types.SimpleNamespace(loftFeatures=MockLofts()),
        )
        sketch_a = types.SimpleNamespace(
            name="SectionA",
            parentComponent=component,
            profiles=MockCollection([profile_a]),
        )
        sketch_b = types.SimpleNamespace(
            name="SectionB",
            parentComponent=component,
            profiles=MockCollection([profile_b]),
        )
        root = types.SimpleNamespace(
            name="Root",
            sketches=[sketch_a, sketch_b],
            bRepBodies=[],
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
            res = self.tools.execute_tool("loft_feature", {
                "sections": [
                    {"sketch_name": "SectionA", "profile_index": 0},
                    {"sketch_name": "SectionB", "profile_index": 0},
                ],
                "operation": "NewBody",
                "name": "LoftA",
                "body_name": "LoftBody",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect

        self.assertIn("result", res)
        self.assertEqual(res["result"]["featureName"], "LoftA")
        self.assertEqual(res["result"]["operation"], "NewBody")
        self.assertEqual(res["result"]["resultBodies"], ["LoftBody"])
        self.assertEqual(res["result"]["sections"], [
            {"sketchName": "SectionA", "profileIndex": 0},
            {"sketchName": "SectionB", "profileIndex": 0},
        ])
        self.assertEqual(created_inputs[0].loftSections._items, [profile_a, profile_b])
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

    def test_sweep_feature_creates_profile_along_indexed_path_curve(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockCollection:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)
            def item(self, index):
                return self._items[index]
            def add(self, item):
                self._items.append(item)
                self.count = len(self._items)

        profile = types.SimpleNamespace(name="ProfileA")
        path_curve = types.SimpleNamespace(name="PathLine")
        result_body = types.SimpleNamespace(name="Body0")
        created_inputs = []
        created_paths = []

        class MockParticipantBodies:
            def __init__(self):
                self.items = []
            def add(self, body):
                self.items.append(body)

        class MockSweepInput:
            def __init__(self, profile_arg, path_arg, operation_arg):
                self.profile = profile_arg
                self.path = path_arg
                self.operation = operation_arg
                self.participantBodies = MockParticipantBodies()

        class MockSweeps:
            def __bool__(self):
                return False
            def createInput(self, profile_arg, path_arg, operation_arg):
                input_obj = MockSweepInput(profile_arg, path_arg, operation_arg)
                created_inputs.append(input_obj)
                return input_obj
            def add(self, input_obj):
                self.last_input = input_obj
                return types.SimpleNamespace(
                    name="",
                    bodies=MockCollection([result_body]),
                    participantBodies=MockCollection(input_obj.participantBodies.items),
                )

        def create_path(curve, chain):
            path = types.SimpleNamespace(curve=curve, chain=chain)
            created_paths.append(path)
            return path

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(
                sweepFeatures=MockSweeps(),
                createPath=create_path,
            ),
        )
        profile_sketch = types.SimpleNamespace(
            name="ProfileSketch",
            parentComponent=component,
            profiles=MockCollection([profile]),
        )
        path_sketch = types.SimpleNamespace(
            name="PathSketch",
            parentComponent=component,
            profiles=MockCollection([]),
            sketchCurves=types.SimpleNamespace(
                sketchLines=MockCollection([path_curve]),
                sketchCircles=MockCollection([]),
                sketchArcs=MockCollection([]),
                sketchEllipses=MockCollection([]),
                sketchFittedSplines=MockCollection([]),
                sketchFixedSplines=MockCollection([]),
                sketchConicCurves=MockCollection([]),
            ),
        )
        root = types.SimpleNamespace(
            name="Root",
            sketches=[profile_sketch, path_sketch],
            bRepBodies=[],
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
            res = self.tools.execute_tool("sweep_feature", {
                "profile_sketch_name": "ProfileSketch",
                "profile_index": 0,
                "path_sketch_name": "PathSketch",
                "path_curve_index": 0,
                "chain_path": True,
                "operation": "NewBody",
                "name": "SweepA",
                "body_name": "SweepBody",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect

        self.assertIn("result", res)
        self.assertEqual(res["result"]["featureName"], "SweepA")
        self.assertEqual(res["result"]["operation"], "NewBody")
        self.assertEqual(res["result"]["resultBodies"], ["SweepBody"])
        self.assertEqual(res["result"]["pathSketchName"], "PathSketch")
        self.assertEqual(res["result"]["pathCurveIndex"], 0)
        self.assertEqual(res["result"]["pathCurveGroup"], "lines")
        self.assertTrue(res["result"]["chainPath"])
        self.assertEqual(created_paths[0].curve, path_curve)
        self.assertTrue(created_paths[0].chain)
        self.assertEqual(created_inputs[0].profile, profile)
        self.assertEqual(created_inputs[0].path, created_paths[0])
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

    def test_fillet_feature_accepts_edge_entity_tokens(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        original_object_collection = sys.modules["adsk.core"].ObjectCollection
        sys.modules["adsk.core"].ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())

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
        body = types.SimpleNamespace(name="BodyA", parentComponent=component)
        edge = types.SimpleNamespace(
            name="EdgeToken",
            entityToken="edge-token",
            length=1.0,
            objectType="BRepEdge",
            body=body,
        )
        body.edges = types.SimpleNamespace(count=1, item=lambda index: edge)
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(bRepBodies=[body], allOccurrences=[]),
            findEntityByToken=lambda token: edge if token == "edge-token" else None,
        )
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {"result": {"featureName": feature_name}}
        try:
            res = self.tools.execute_tool("fillet_feature", {
                "edge_entity_tokens": ["edge-token"],
                "radius": "1 mm",
                "name": "FilletToken",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect
            sys.modules["adsk.core"].ObjectCollection = original_object_collection

        self.assertIn("result", res)
        self.assertEqual(res["result"]["targeting"], "entity_tokens")
        self.assertEqual(res["result"]["edgeIndices"], [0])
        self.assertEqual(created_inputs[0].edge_sets[0][0], [edge])

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

    def test_chamfer_feature_accepts_edge_entity_tokens(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        original_object_collection = sys.modules["adsk.core"].ObjectCollection
        sys.modules["adsk.core"].ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())

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
        body = types.SimpleNamespace(name="BodyA", parentComponent=component)
        edge = types.SimpleNamespace(
            name="EdgeToken",
            entityToken="edge-token",
            length=1.0,
            objectType="BRepEdge",
            body=body,
        )
        body.edges = types.SimpleNamespace(count=1, item=lambda index: edge)
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(bRepBodies=[body], allOccurrences=[]),
            findEntityByToken=lambda token: edge if token == "edge-token" else None,
        )
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {"result": {"featureName": feature_name}}
        try:
            res = self.tools.execute_tool("chamfer_feature", {
                "edge_entity_tokens": ["edge-token"],
                "distance": "1 mm",
                "name": "ChamferToken",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect
            sys.modules["adsk.core"].ObjectCollection = original_object_collection

        self.assertIn("result", res)
        self.assertEqual(res["result"]["targeting"], "entity_tokens")
        self.assertEqual(res["result"]["edgeIndices"], [0])
        self.assertEqual(created_inputs[0].edges, [edge])

    def test_offset_face_accepts_face_entity_tokens(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature
        created_inputs = []

        class MockOffsetFaces:
            def createInput(self, faces, distance):
                input_obj = types.SimpleNamespace(faces=list(faces), distance=distance)
                created_inputs.append(input_obj)
                return input_obj
            def add(self, input_obj):
                return types.SimpleNamespace(name="")

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(offsetFacesFeatures=MockOffsetFaces()),
        )
        body = types.SimpleNamespace(name="BodyA", parentComponent=component)
        face = types.SimpleNamespace(
            name="FaceToken",
            entityToken="face-token",
            area=10.0,
            objectType="BRepFace",
            body=body,
        )
        body.faces = types.SimpleNamespace(count=1, item=lambda index: face)
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(bRepBodies=[body], allOccurrences=[]),
            findEntityByToken=lambda token: face if token == "face-token" else None,
        )
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {"result": {"featureName": feature_name}}
        try:
            res = self.tools.execute_tool("offset_face_or_press_pull", {
                "face_entity_tokens": ["face-token"],
                "distance": "1 mm",
                "name": "OffsetToken",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect

        self.assertIn("result", res)
        self.assertEqual(res["result"]["targeting"], "entity_tokens")
        self.assertEqual(res["result"]["faceIndices"], [0])
        self.assertEqual(created_inputs[0].faces, [face])

    def test_shell_body_accepts_body_and_open_face_entity_tokens(self):
        features_module = importlib.import_module("tools.features")
        original_snapshot = features_module._design_state_snapshot
        original_compare = features_module.compare_design_state
        original_inspect = features_module.inspect_feature

        class MockObjectCollection(list):
            @property
            def count(self):
                return len(self)
            def add(self, item):
                self.append(item)

        original_object_collection = sys.modules["adsk.core"].ObjectCollection
        sys.modules["adsk.core"].ObjectCollection = types.SimpleNamespace(create=lambda: MockObjectCollection())
        created_inputs = []

        class MockShells:
            def createInput(self, input_entities, tangent_chain):
                input_obj = types.SimpleNamespace(
                    input_entities=list(input_entities),
                    tangent_chain=tangent_chain,
                    insideThickness=None,
                    outsideThickness=None,
                )
                created_inputs.append(input_obj)
                return input_obj
            def add(self, input_obj):
                return types.SimpleNamespace(name="")

        component = types.SimpleNamespace(
            name="Root",
            features=types.SimpleNamespace(shellFeatures=MockShells()),
        )
        body = types.SimpleNamespace(
            name="BodyA",
            objectType="BRepBody",
            entityToken="body-token",
            parentComponent=component,
        )
        face = types.SimpleNamespace(
            name="FaceToken",
            entityToken="face-token",
            area=10.0,
            objectType="BRepFace",
            body=body,
        )
        body.faces = types.SimpleNamespace(count=1, item=lambda index: face)
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(bRepBodies=[body], allOccurrences=[]),
            findEntityByToken=lambda token: {"body-token": body, "face-token": face}.get(token),
        )
        _fake_app.activeProduct = self.mock_design

        features_module._design_state_snapshot = lambda include_selections=False: {
            "counts": {"timelineItems": 0 if not created_inputs else 1}
        }
        features_module.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        features_module.inspect_feature = lambda feature_name: {"result": {"featureName": feature_name}}
        try:
            res = self.tools.execute_tool("shell_body", {
                "body_entity_token": "body-token",
                "open_face_entity_tokens": ["face-token"],
                "thickness": "2 mm",
                "name": "ShellToken",
            })
        finally:
            features_module._design_state_snapshot = original_snapshot
            features_module.compare_design_state = original_compare
            features_module.inspect_feature = original_inspect
            sys.modules["adsk.core"].ObjectCollection = original_object_collection

        self.assertIn("result", res)
        self.assertEqual(res["result"]["targeting"], "entity_tokens")
        self.assertEqual(res["result"]["openFaceIndices"], [0])
        self.assertEqual(created_inputs[0].input_entities, [face])
        self.assertEqual(created_inputs[0].insideThickness, "2 mm")

    def test_create_hole_pattern_countersink_uses_conical_loft_cut(self):
        class MockCollection:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)
            def item(self, index):
                return self._items[index]
            def add(self, item):
                self._items.append(item)
                self.count = len(self._items)

        class MockCircleCollection:
            def __init__(self):
                self.radii = []
            def addByCenterRadius(self, _center, radius):
                self.radii.append(radius)

        class MockSketch:
            def __init__(self, plane):
                self.plane = plane
                self.name = ""
                self.isLightBulbOn = True
                self.sketchCurves = types.SimpleNamespace(sketchCircles=MockCircleCollection())
                self.profiles = MockCollection([types.SimpleNamespace(sketch=self)])

        class MockSketches:
            def __init__(self):
                self.created = []
            def add(self, plane):
                sketch = MockSketch(plane)
                self.created.append(sketch)
                return sketch

        class MockConstructionPlaneInput:
            def __init__(self):
                self.base_plane = None
                self.offset = None
            def setByOffset(self, base_plane, offset):
                self.base_plane = base_plane
                self.offset = offset

        class MockConstructionPlanes:
            def __init__(self):
                self.created = []
            def createInput(self):
                return MockConstructionPlaneInput()
            def add(self, plane_input):
                plane = types.SimpleNamespace(name="", input=plane_input, isLightBulbOn=True)
                self.created.append(plane)
                return plane

        class MockLoftInput:
            def __init__(self, operation):
                self.operation = operation
                self.loftSections = MockCollection()

        class MockLoftFeatures:
            def __init__(self):
                self.inputs = []
            def createInput(self, operation):
                loft_input = MockLoftInput(operation)
                self.inputs.append(loft_input)
                return loft_input
            def add(self, _loft_input):
                return types.SimpleNamespace(name="")

        class MockExtrudeInput:
            def __init__(self, profile, operation):
                self.profile = profile
                self.operation = operation
                self.distance = None
            def setDistanceExtent(self, _is_symmetric, distance):
                self.distance = distance

        class MockExtrudeFeatures:
            def __init__(self):
                self.inputs = []
            def createInput(self, profile, operation):
                extrude_input = MockExtrudeInput(profile, operation)
                self.inputs.append(extrude_input)
                return extrude_input
            def add(self, _extrude_input):
                return types.SimpleNamespace(name="")

        class MockUnits:
            defaultLengthUnits = "mm"
            def evaluateExpression(self, expression, _units):
                text = str(expression).strip().split()[0]
                return float(text)

        sketches = MockSketches()
        construction_planes = MockConstructionPlanes()
        loft_features = MockLoftFeatures()
        extrude_features = MockExtrudeFeatures()
        root = types.SimpleNamespace(
            name="Root",
            xYConstructionPlane=types.SimpleNamespace(name="xy"),
            xZConstructionPlane=types.SimpleNamespace(name="xz"),
            yZConstructionPlane=types.SimpleNamespace(name="yz"),
            sketches=sketches,
            constructionPlanes=construction_planes,
            features=types.SimpleNamespace(
                loftFeatures=loft_features,
                extrudeFeatures=extrude_features,
            ),
            bRepBodies=[],
            allOccurrences=[],
        )
        body = types.SimpleNamespace(name="Plate", parentComponent=root)
        root.bRepBodies.append(body)
        self.mock_design = types.SimpleNamespace(rootComponent=root, unitsManager=MockUnits())
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("create_hole_pattern", {
            "target_body_name": "Plate",
            "name": "CSK",
            "hole_type": "countersink",
            "hole_diameter": "4 mm",
            "cut_depth": "8 mm",
            "countersink_diameter": "8 mm",
            "countersink_depth": "2 mm",
            "points": [["1 mm", "2 mm"]],
        })

        self.assertIn("result", res)
        self.assertEqual(res["result"]["holeType"], "countersink")
        self.assertEqual(res["result"]["countersinkGeometry"], "conical_loft_cut")
        self.assertEqual(res["result"]["featureNames"], ["CSK_1_Countersink", "CSK_1_Hole"])
        self.assertEqual(res["result"]["constructionPlaneNames"], ["CSK_1_Countersink_OffsetPlane"])
        self.assertEqual(res["result"]["warnings"], [])
        self.assertEqual(loft_features.inputs[0].operation, sys.modules["adsk.fusion"].FeatureOperations.CutFeatureOperation)
        self.assertEqual(loft_features.inputs[0].loftSections.count, 2)
        self.assertEqual(construction_planes.created[0].input.offset, "2 mm")
        self.assertEqual(extrude_features.inputs[0].distance, "8 mm")

    def test_inspect_sketch_returns_coordinate_mapping_and_curves(self):
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        user_param = types.SimpleNamespace(name="fixtureWidth", expression="10 cm", value=10.0, unit="cm", comment="Width control")
        mock_param = types.SimpleNamespace(name="d1", expression="fixtureWidth", value=10.0, unit="cm")
        mock_dim = types.SimpleNamespace(name="LengthDim", parameter=mock_param, objectType="SketchLinearDimension")
        source_body = types.SimpleNamespace(
            name="SourceBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-token",
            parentComponent=types.SimpleNamespace(name="Root"),
        )
        source_edge = types.SimpleNamespace(
            name="SourceEdge",
            objectType="adsk::fusion::BRepEdge",
            entityToken="edge-token",
            body=source_body,
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
            timeline=types.SimpleNamespace(
                count=1,
                item=lambda idx: types.SimpleNamespace(
                    name="SourceExtrude",
                    index=3,
                    entity=types.SimpleNamespace(
                        name="SourceExtrude",
                        objectType="adsk::fusion::ExtrudeFeature",
                        bodies=types.SimpleNamespace(count=1, item=lambda bidx: source_body),
                    ),
                ),
            ),
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
        self.assertEqual(result["curves"]["lines"][0]["source"]["bodyName"], "SourceBody")
        self.assertEqual(result["curves"]["lines"][0]["source"]["ownerFeature"]["featureName"], "SourceExtrude")

    def test_get_projected_geometry_sources_returns_source_owner_feature(self):
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        source_body = types.SimpleNamespace(
            name="SourceBody",
            objectType="adsk::fusion::BRepBody",
            entityToken="body-token",
            parentComponent=types.SimpleNamespace(name="Root"),
        )
        source_edge = types.SimpleNamespace(
            name="SourceEdge",
            objectType="adsk::fusion::BRepEdge",
            entityToken="edge-token",
            body=source_body,
        )
        mock_line = types.SimpleNamespace(
            name="ProjectedLine",
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
            name="ProjectSketch",
            objectType="adsk::fusion::Sketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            isVisible=True,
            isFullyConstrained=False,
            referencePlane=types.SimpleNamespace(
                name="XY",
                objectType="adsk::fusion::ConstructionPlane",
                geometry=types.SimpleNamespace(
                    origin=point(0, 0, 0),
                    uDirection=vector(1, 0, 0),
                    vDirection=vector(0, 1, 0),
                    normal=vector(0, 0, 1),
                ),
            ),
            sketchPoints=types.SimpleNamespace(count=0, item=lambda idx: None),
            sketchDimensions=types.SimpleNamespace(count=0, item=lambda idx: None),
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
            userParameters=types.SimpleNamespace(itemByName=lambda name: None),
            timeline=types.SimpleNamespace(
                count=1,
                item=lambda idx: types.SimpleNamespace(
                    name="SourceExtrude",
                    index=3,
                    entity=types.SimpleNamespace(
                        name="SourceExtrude",
                        objectType="adsk::fusion::ExtrudeFeature",
                        bodies=types.SimpleNamespace(count=1, item=lambda bidx: source_body),
                    ),
                ),
            ),
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("get_projected_geometry_sources", {"sketch_name": "ProjectSketch"})

        self.assertEqual(res["result"]["projectedCount"], 1)
        projected = res["result"]["projected"][0]
        self.assertEqual(projected["curveName"], "ProjectedLine")
        self.assertTrue(projected["sourceAvailable"])
        self.assertEqual(projected["source"]["kind"], "BRepEdge")
        self.assertEqual(projected["source"]["bodyName"], "SourceBody")
        self.assertEqual(projected["source"]["ownerFeature"]["timelineName"], "SourceExtrude")

    def test_get_sketch_parameters_returns_narrow_parameter_payload(self):
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        user_param = types.SimpleNamespace(name="fixtureWidth", expression="10 cm", value=10.0, unit="cm", comment="Width control")
        mock_param = types.SimpleNamespace(name="d1", expression="fixtureWidth", value=10.0, unit="cm")
        mock_dim = types.SimpleNamespace(name="LengthDim", parameter=mock_param, objectType="SketchLinearDimension")
        mock_sketch = types.SimpleNamespace(
            name="ParamSketch",
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
                sketchLines=types.SimpleNamespace(count=0, item=lambda idx: None),
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

        res = self.tools.execute_tool("get_sketch_parameters", {"sketch_name": "ParamSketch"})

        self.assertEqual(res["result"]["sketchName"], "ParamSketch")
        self.assertEqual(res["result"]["parameterCount"], 1)
        self.assertEqual(res["result"]["dimensionCount"], 1)
        self.assertEqual(res["result"]["parameters"][0]["name"], "d1")
        self.assertEqual(res["result"]["parameters"][0]["userParameterReferences"][0]["name"], "fixtureWidth")

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

    def test_get_feature_parameters_returns_narrow_parameter_payload(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        user_param = types.SimpleNamespace(name="slotDepth", expression="5 mm", value=0.5, unit="cm", comment="Slot depth")
        mock_distance_param = types.SimpleNamespace(
            name="d228",
            expression="slotDepth",
            value=0.5,
            unit="cm",
            objectType="adsk::fusion::ModelParameter",
        )
        mock_extrude = types.SimpleNamespace(
            name="CutSlot",
            objectType="adsk::fusion::ExtrudeFeature",
            healthState=0,
            operation=3,
            extentOne=types.SimpleNamespace(objectType="adsk::fusion::DistanceExtentDefinition", distance=mock_distance_param),
            extentTwo=None,
            isSymmetric=False,
            isSolid=True,
            participantBodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            bodies=types.SimpleNamespace(count=0, item=lambda idx: None),
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

            res = self.tools.execute_tool("get_feature_parameters", {"feature_name": "CutSlot"})
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude

        self.assertEqual(res["result"]["featureName"], "CutSlot")
        self.assertEqual(res["result"]["featureType"], "ExtrudeFeature")
        self.assertEqual(res["result"]["operation"], "Cut")
        self.assertEqual(res["result"]["parameterCount"], 1)
        self.assertEqual(res["result"]["parameters"][0]["role"], "extentOne.distance")
        self.assertEqual(res["result"]["parameters"][0]["userParameterReferences"][0]["name"], "slotDepth")

    def test_get_parameter_usage_finds_sketch_and_feature_references(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        point = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        vector = lambda x, y, z: types.SimpleNamespace(x=x, y=y, z=z)
        user_param = types.SimpleNamespace(name="slotDepth", expression="5 mm", value=0.5, unit="cm", comment="Slot depth")
        sketch_param = types.SimpleNamespace(name="d1", expression="slotDepth + 1 mm", value=0.6, unit="cm")
        sketch_dim = types.SimpleNamespace(name="LengthDim", parameter=sketch_param, objectType="SketchLinearDimension")
        mock_sketch = types.SimpleNamespace(
            name="UsageSketch",
            objectType="adsk::fusion::Sketch",
            parentComponent=types.SimpleNamespace(name="Root"),
            isVisible=True,
            isFullyConstrained=False,
            referencePlane=types.SimpleNamespace(
                geometry=types.SimpleNamespace(
                    origin=point(0, 0, 0),
                    uDirection=vector(1, 0, 0),
                    vDirection=vector(0, 1, 0),
                    normal=vector(0, 0, 1),
                ),
            ),
            sketchDimensions=types.SimpleNamespace(count=1, item=lambda idx: sketch_dim),
        )
        feature_param = types.SimpleNamespace(
            name="d228",
            expression="slotDepth",
            value=0.5,
            unit="cm",
            objectType="adsk::fusion::ModelParameter",
        )
        mock_extrude = types.SimpleNamespace(
            name="UsageExtrude",
            objectType="adsk::fusion::ExtrudeFeature",
            healthState=0,
            operation=3,
            extentOne=types.SimpleNamespace(objectType="adsk::fusion::DistanceExtentDefinition", distance=feature_param),
            extentTwo=None,
            isSymmetric=False,
            isSolid=True,
            participantBodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            bodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            profiles=types.SimpleNamespace(count=0, item=lambda idx: None),
        )
        sys.modules["adsk.fusion"].ExtrudeFeature = types.SimpleNamespace(cast=lambda value: value if value is mock_extrude else None)
        try:
            mock_item = types.SimpleNamespace(
                name="UsageExtrude",
                index=8,
                healthState=0,
                isSuppressed=False,
                entity=mock_extrude,
            )
            self.mock_design = types.SimpleNamespace(
                rootComponent=types.SimpleNamespace(sketches=[mock_sketch], allOccurrences=[]),
                timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
                userParameters=types.SimpleNamespace(itemByName=lambda name: user_param if name == "slotDepth" else None),
                allParameters=types.SimpleNamespace(count=0, item=lambda idx: None, itemByName=lambda name: None),
            )
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("get_parameter_usage", {"parameter_name": "slotDepth"})
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude

        self.assertEqual(res["result"]["parameterName"], "slotDepth")
        self.assertEqual(res["result"]["targetParameter"]["name"], "slotDepth")
        self.assertEqual(res["result"]["usageCount"], 2)
        self.assertEqual(res["result"]["sketchUsages"][0]["sketchName"], "UsageSketch")
        self.assertEqual(res["result"]["sketchUsages"][0]["parameters"][0]["name"], "d1")
        self.assertEqual(res["result"]["featureUsages"][0]["featureName"], "UsageExtrude")
        self.assertEqual(res["result"]["featureUsages"][0]["parameters"][0]["name"], "d228")

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

    def test_get_dependency_graph_links_profile_sketch_and_downstream_feature(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        original_sketch = sys.modules["adsk.fusion"].Sketch
        user_param = types.SimpleNamespace(name="fixtureDepth", expression="8 mm", value=0.8, unit="cm", comment="Depth")
        distance_param = types.SimpleNamespace(
            name="d1",
            expression="fixtureDepth",
            value=0.8,
            unit="cm",
            objectType="adsk::fusion::ModelParameter",
        )
        mock_body = types.SimpleNamespace(name="Body1")
        mock_sketch = types.SimpleNamespace(
            name="SketchA",
            objectType="adsk::fusion::Sketch",
            parentComponent=types.SimpleNamespace(name="Root"),
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
            extentOne=types.SimpleNamespace(distance=distance_param),
            extentTwo=None,
            taperAngle=None,
            startExtent=types.SimpleNamespace(offset=None),
            bodies=types.SimpleNamespace(count=1, item=lambda idx: mock_body),
            participantBodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            profiles=types.SimpleNamespace(count=1, item=lambda idx: mock_profile),
        )
        downstream_extrude = types.SimpleNamespace(
            name="CutB",
            objectType="adsk::fusion::ExtrudeFeature",
            extentOne=None,
            extentTwo=None,
            taperAngle=None,
            startExtent=types.SimpleNamespace(offset=None),
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
                userParameters=types.SimpleNamespace(itemByName=lambda name: user_param if name == "fixtureDepth" else None),
            )
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("get_dependency_graph", {})
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude
            sys.modules["adsk.fusion"].Sketch = original_sketch

        self.assertTrue(res["result"]["bestEffort"])
        relationships = {(edge["source"], edge["target"], edge["relationship"]) for edge in res["result"]["edges"]}
        self.assertIn(("sketch:SketchA", "feature:0:ExtrudeA", "providesProfile"), relationships)
        self.assertIn(("feature:0:ExtrudeA", "feature:1:CutB", "likelyDownstreamConsumer"), relationships)
        self.assertIn(("userParameter:fixtureDepth", "parameter:d1", "referencedByExpression"), relationships)

    def test_assess_change_impact_blocks_likely_downstream_consumers(self):
        original_extrude = sys.modules["adsk.fusion"].ExtrudeFeature
        mock_body = types.SimpleNamespace(name="Body1")
        target_extrude = types.SimpleNamespace(
            name="ExtrudeA",
            objectType="adsk::fusion::ExtrudeFeature",
            bodies=types.SimpleNamespace(count=1, item=lambda idx: mock_body),
            participantBodies=types.SimpleNamespace(count=0, item=lambda idx: None),
            profiles=types.SimpleNamespace(count=0, item=lambda idx: None),
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
        try:
            self.mock_design = types.SimpleNamespace(
                timeline=types.SimpleNamespace(count=2, item=lambda idx: items[idx]),
                rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
                userParameters=types.SimpleNamespace(itemByName=lambda name: None),
            )
            _fake_app.activeProduct = self.mock_design

            res = self.tools.execute_tool("assess_change_impact", {
                "target_features": "ExtrudeA",
                "change_type": "delete",
            })
        finally:
            sys.modules["adsk.fusion"].ExtrudeFeature = original_extrude

        self.assertFalse(res["result"]["okToProceed"])
        self.assertEqual(res["result"]["riskLevel"], "high")
        self.assertIn("likely downstream consumers", res["result"]["blockingReasons"][0])
        self.assertEqual(res["result"]["downstreamConsumers"][0]["consumer"]["timelineName"], "CutB")
        self.assertIn("explicit confirmation", res["result"]["recommendedNextStep"])

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

    def test_create_design_document_requires_approval_and_creates_unsaved_doc(self):
        core = sys.modules["adsk.core"]
        original_document_types = core.DocumentTypes
        created = []

        def add_doc(document_type):
            doc = types.SimpleNamespace(
                name="Untitled",
                isModified=False,
                activate=lambda: created.append("activated"),
            )
            created.append(document_type)
            _fake_app.activeDocument = doc
            return doc

        try:
            core.DocumentTypes = types.SimpleNamespace(FusionDesignDocumentType="fusion-design")
            _fake_app.activeDocument = None
            _fake_app.documents = types.SimpleNamespace(add=add_doc)

            blocked = self.tools.execute_tool("create_design_document", {
                "document_name": "FixtureDoc",
                "reason": "Missing explicit approval.",
            })
            self.assertIn("error", blocked)
            self.assertEqual(created, [])

            res = self.tools.execute_tool("create_design_document", {
                "document_name": "FixtureDoc",
                "requires_user_approval": True,
                "reason": "Create controlled fixture document.",
            })
        finally:
            core.DocumentTypes = original_document_types

        self.assertIn("result", res)
        self.assertTrue(res["result"]["created"])
        self.assertEqual(res["result"]["documentName"], "FixtureDoc")
        self.assertEqual(created, ["fusion-design", "activated"])

    def test_close_active_document_requires_approval_and_closes_active_doc(self):
        closed = []
        doc = types.SimpleNamespace(
            name="FixtureDoc",
            dataFile=None,
            isModified=True,
            close=lambda save: closed.append(save) or True,
        )
        _fake_app.activeDocument = doc
        _fake_app.documents = [doc]

        blocked = self.tools.execute_tool("close_active_document", {
            "document_name": "FixtureDoc",
            "save_changes": False,
            "reason": "Missing explicit approval.",
        })
        self.assertIn("error", blocked)
        self.assertEqual(closed, [])

        res = self.tools.execute_tool("close_active_document", {
            "document_name": "FixtureDoc",
            "save_changes": False,
            "requires_user_approval": True,
            "reason": "Close controlled fixture document.",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["closed"])
        self.assertEqual(res["result"]["documentName"], "FixtureDoc")
        self.assertFalse(res["result"]["saveChanges"])
        self.assertEqual(closed, [False])

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
        original_impact = parametric.assess_change_impact
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
        parametric.assess_change_impact = lambda target_features, change_type="edit": {
            "result": {
                "okToProceed": False,
                "riskLevel": "high",
                "targetFeatures": [target_features],
                "changeType": change_type,
                "blockingReasons": ["One or more target features have likely downstream consumers."],
                "downstreamConsumers": [{"targetFeature": target_features, "consumer": {"timelineName": "CutB"}}],
            }
        }
        try:
            res = self.tools.execute_tool("delete_timeline_feature", {
                "name": "FeatureA",
                "reason": "Remove obsolete test feature.",
            })
        finally:
            parametric.get_feature_dependencies = original_dependencies
            parametric.assess_change_impact = original_impact

        self.assertIn("error", res)
        self.assertIn("downstream consumers", res["error"])
        self.assertEqual(deleted, [])
        self.assertEqual(res["dependencyReport"]["likelyDownstreamConsumers"][0]["timelineName"], "CutB")
        self.assertEqual(res["impactReport"]["riskLevel"], "high")
        self.assertEqual(res["impactReport"]["downstreamConsumers"][0]["consumer"]["timelineName"], "CutB")

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

    def test_delete_named_experiment_dry_run_reports_matches_without_deleting(self):
        deleted = []
        mock_item = types.SimpleNamespace(name="Exp_Feature", deleteMe=lambda: deleted.append("timeline"))
        body = types.SimpleNamespace(name="Exp_Body", entityToken="body-token", deleteMe=lambda: deleted.append("body"))
        sketch = types.SimpleNamespace(name="KeepSketch", entityToken="sketch-token", deleteMe=lambda: deleted.append("sketch"))
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[body],
            sketches=[sketch],
            allOccurrences=[],
        )
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=root,
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("delete_named_experiment", {
            "prefixes": ["Exp_"],
            "reason": "Preview cleanup of failed experiment artifacts.",
        })

        self.assertIn("result", res)
        self.assertTrue(res["result"]["dryRun"])
        self.assertFalse(res["result"]["deleted"])
        self.assertEqual(res["result"]["matchCount"], 2)
        self.assertEqual(deleted, [])
        self.assertEqual({item["kind"] for item in res["result"]["matches"]}, {"timeline", "body"})

    def test_delete_named_experiment_confirmed_deletes_named_artifacts(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        deleted = []
        mock_item = types.SimpleNamespace(name="Exp_Feature", deleteMe=lambda: deleted.append("timeline"))
        body = types.SimpleNamespace(name="Exp_Body", entityToken="body-token", deleteMe=lambda: deleted.append("body"))
        sketch = types.SimpleNamespace(name="Exp_Sketch", entityToken="sketch-token", deleteMe=lambda: deleted.append("sketch"))
        root = types.SimpleNamespace(
            name="Root",
            bRepBodies=[body],
            sketches=[sketch],
            allOccurrences=[],
        )
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: mock_item),
            rootComponent=root,
        )
        _fake_app.activeProduct = self.mock_design
        parametric._design_state_snapshot = lambda include_selections=False: {"counts": {"deleted": len(deleted)}}
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "high", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("delete_named_experiment", {
                "names": ["Exp_Feature"],
                "prefixes": ["Exp_"],
                "reason": "Remove approved failed insert experiment.",
                "confirm_delete": True,
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertFalse(res["result"]["dryRun"])
        self.assertEqual(deleted, ["timeline", "body", "sketch"])
        self.assertEqual(res["result"]["deletedCount"], 3)
        self.assertEqual(res["result"]["errorCount"], 0)
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "high")

    def test_delete_named_experiment_rejects_short_prefix_without_override(self):
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=0, item=lambda idx: None),
            rootComponent=types.SimpleNamespace(name="Root", bRepBodies=[], sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("delete_named_experiment", {
            "prefixes": ["X"],
            "reason": "Try unsafe broad cleanup.",
        })

        self.assertIn("error", res)
        self.assertIn("short cleanup prefixes", res["error"])

    def test_suppress_timeline_feature_blocks_downstream_consumers(self):
        parametric = importlib.import_module("tools.parametric")
        original_dependencies = parametric.get_feature_dependencies
        original_impact = parametric.assess_change_impact
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
        parametric.assess_change_impact = lambda target_features, change_type="edit": {
            "result": {
                "okToProceed": False,
                "riskLevel": "high",
                "targetFeatures": [target_features],
                "changeType": change_type,
                "blockingReasons": ["One or more target features have likely downstream consumers."],
                "downstreamConsumers": [{"targetFeature": target_features, "consumer": {"timelineName": "CutB"}}],
            }
        }
        try:
            res = self.tools.execute_tool("suppress_timeline_feature", {
                "name": "FeatureA",
                "reason": "Temporarily isolate feature.",
            })
        finally:
            parametric.get_feature_dependencies = original_dependencies
            parametric.assess_change_impact = original_impact

        self.assertIn("error", res)
        self.assertFalse(mock_item.isSuppressed)
        self.assertEqual(res["impactReport"]["riskLevel"], "high")

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

    def _install_feature_edit_fixture(self, object_type, feature_name="FeatureA", parameters=None):
        parameters = parameters or [types.SimpleNamespace(name="d1", expression="1 mm", value=0.1, unit="cm")]
        feature = types.SimpleNamespace(
            name=feature_name,
            objectType=object_type,
            modelParameters=parameters,
        )
        item = types.SimpleNamespace(name=feature_name, index=0, healthState=0, entity=feature)
        self.mock_design = types.SimpleNamespace(
            timeline=types.SimpleNamespace(count=1, item=lambda idx: item),
            rootComponent=types.SimpleNamespace(sketches=[], allOccurrences=[]),
        )
        _fake_app.activeProduct = self.mock_design
        return feature, item, parameters

    def _patch_feature_edit_safety(self, parametric, downstream=None, impact=None, state=None):
        originals = (
            parametric.get_feature_dependencies,
            parametric.assess_change_impact,
            parametric._design_state_snapshot,
            parametric.compare_design_state,
            parametric.inspect_feature,
        )
        parametric.get_feature_dependencies = lambda feature_name: {
            "result": {
                "featureName": feature_name,
                "likelyDownstreamConsumers": downstream or [],
            }
        }
        parametric.assess_change_impact = lambda target_features, change_type="edit": {
            "result": impact or {
                "okToProceed": True,
                "riskLevel": "low",
                "targetFeatures": [target_features],
                "changeType": change_type,
            }
        }
        snapshots = list(state or [{"state": "before"}, {"state": "after"}])
        parametric._design_state_snapshot = lambda include_selections=False: snapshots.pop(0) if snapshots else {"state": "after"}
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        parametric.inspect_feature = lambda feature_name: {
            "result": {"featureName": feature_name, "parameters": []}
        }
        return originals

    def _restore_feature_edit_safety(self, parametric, originals):
        (
            parametric.get_feature_dependencies,
            parametric.assess_change_impact,
            parametric._design_state_snapshot,
            parametric.compare_design_state,
            parametric.inspect_feature,
        ) = originals

    def test_edit_extrude_feature_updates_distance_and_operation(self):
        parametric = importlib.import_module("tools.parametric")
        param = types.SimpleNamespace(name="d1", expression="10 mm", value=1.0, unit="cm")
        feature, _item, _params = self._install_feature_edit_fixture(
            "adsk::fusion::ExtrudeFeature",
            "ExtrudeA",
            [param],
        )
        feature.operation = sys.modules["adsk.fusion"].FeatureOperations.NewBodyFeatureOperation
        originals = self._patch_feature_edit_safety(parametric)
        try:
            res = self.tools.execute_tool("edit_extrude_feature", {
                "feature_name": "ExtrudeA",
                "distance": "15 mm",
                "operation": "cut",
            })
        finally:
            self._restore_feature_edit_safety(parametric, originals)

        self.assertIn("result", res)
        self.assertEqual(param.expression, "15 mm")
        self.assertEqual(feature.operation, sys.modules["adsk.fusion"].FeatureOperations.CutFeatureOperation)
        self.assertEqual(res["result"]["before"]["expression"], "10 mm")
        self.assertEqual(res["result"]["after"]["expression"], "15 mm")
        self.assertTrue(res["result"]["stateComparison"]["hasChanges"])

    def test_feature_edit_tools_update_supported_feature_parameters(self):
        cases = [
            ("edit_fillet_radius", "adsk::fusion::FilletFeature", {"radius": "2 mm"}, "2 mm"),
            ("edit_chamfer_distance", "adsk::fusion::ChamferFeature", {"distance": "1 mm"}, "1 mm"),
            ("edit_shell_thickness", "adsk::fusion::ShellFeature", {"thickness": "1.2 mm"}, "1.2 mm"),
            ("edit_pattern_parameter", "adsk::fusion::RectangularPatternFeature", {"parameter_name": "d1", "expression": "4"}, "4"),
            ("edit_hole_parameter", "adsk::fusion::HoleFeature", {"parameter_name": "d1", "expression": "3 mm"}, "3 mm"),
        ]
        for tool_name, object_type, args, expected in cases:
            with self.subTest(tool=tool_name):
                parametric = importlib.import_module("tools.parametric")
                param = types.SimpleNamespace(name="d1", expression="1 mm", value=0.1, unit="cm")
                self._install_feature_edit_fixture(object_type, "FeatureA", [param])
                originals = self._patch_feature_edit_safety(parametric)
                try:
                    res = self.tools.execute_tool(tool_name, {"feature_name": "FeatureA", **args})
                finally:
                    self._restore_feature_edit_safety(parametric, originals)

                self.assertIn("result", res)
                self.assertEqual(param.expression, expected)
                self.assertEqual(res["result"]["after"]["expression"], expected)

    def test_feature_edit_rejects_unsupported_feature_kind(self):
        parametric = importlib.import_module("tools.parametric")
        self._install_feature_edit_fixture("adsk::fusion::BoxFeature", "BoxA")
        originals = self._patch_feature_edit_safety(parametric)
        try:
            res = self.tools.execute_tool("edit_fillet_radius", {
                "feature_name": "BoxA",
                "radius": "2 mm",
            })
        finally:
            self._restore_feature_edit_safety(parametric, originals)

        self.assertIn("error", res)
        self.assertIn("supports only", res["error"])
        self.assertIn("toolGap", res)

    def test_feature_edit_blocks_downstream_risk_by_default(self):
        parametric = importlib.import_module("tools.parametric")
        param = types.SimpleNamespace(name="d1", expression="1 mm", value=0.1, unit="cm")
        self._install_feature_edit_fixture("adsk::fusion::FilletFeature", "FilletA", [param])
        originals = self._patch_feature_edit_safety(
            parametric,
            downstream=[{"timelineName": "CutB"}],
            impact={"okToProceed": False, "riskLevel": "high", "blockingReasons": ["downstream consumers"]},
        )
        try:
            res = self.tools.execute_tool("edit_fillet_radius", {
                "feature_name": "FilletA",
                "radius": "2 mm",
            })
        finally:
            self._restore_feature_edit_safety(parametric, originals)

        self.assertIn("error", res)
        self.assertEqual(param.expression, "1 mm")
        self.assertEqual(res["impactReport"]["riskLevel"], "high")

    def test_feature_edit_requires_reason_for_downstream_override(self):
        parametric = importlib.import_module("tools.parametric")
        param = types.SimpleNamespace(name="d1", expression="1 mm", value=0.1, unit="cm")
        self._install_feature_edit_fixture("adsk::fusion::FilletFeature", "FilletA", [param])
        originals = self._patch_feature_edit_safety(
            parametric,
            downstream=[{"timelineName": "CutB"}],
            impact={"okToProceed": False, "riskLevel": "high", "blockingReasons": ["downstream consumers"]},
        )
        try:
            res = self.tools.execute_tool("edit_fillet_radius", {
                "feature_name": "FilletA",
                "radius": "2 mm",
                "allow_downstream_risk": True,
            })
        finally:
            self._restore_feature_edit_safety(parametric, originals)

        self.assertIn("error", res)
        self.assertIn("reason is required", res["error"])
        self.assertEqual(param.expression, "1 mm")

    def test_feature_edit_downstream_override_returns_state_comparison(self):
        parametric = importlib.import_module("tools.parametric")
        param = types.SimpleNamespace(name="d1", expression="1 mm", value=0.1, unit="cm")
        self._install_feature_edit_fixture("adsk::fusion::FilletFeature", "FilletA", [param])
        originals = self._patch_feature_edit_safety(
            parametric,
            downstream=[{"timelineName": "CutB"}],
            impact={"okToProceed": False, "riskLevel": "high", "blockingReasons": ["downstream consumers"]},
        )
        try:
            res = self.tools.execute_tool("edit_fillet_radius", {
                "feature_name": "FilletA",
                "radius": "2 mm",
                "allow_downstream_risk": True,
                "reason": "User approved adjusting the parent fillet.",
            })
        finally:
            self._restore_feature_edit_safety(parametric, originals)

        self.assertIn("result", res)
        self.assertEqual(param.expression, "2 mm")
        self.assertTrue(res["result"]["allowedDownstreamRisk"])
        self.assertTrue(res["result"]["stateComparison"]["hasChanges"])

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
        self.assertIn("stateComparison", res["result"])

    def test_add_sketch_constraint_uses_fusion_curve_collections_for_entity_indices(self):
        added = []
        mock_constraints = types.SimpleNamespace(
            addCoincident=lambda e1, e2: added.append(("coincident", e1, e2))
        )
        mock_sketch = types.SimpleNamespace(
            name="TestSketch",
            sketchPoints=types.SimpleNamespace(count=1, item=lambda idx: "point1"),
            sketchCurves=types.SimpleNamespace(
                sketchLines=types.SimpleNamespace(count=1, item=lambda idx: "line1"),
                sketchCircles=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchArcs=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchEllipses=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchFittedSplines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchFixedSplines=types.SimpleNamespace(count=0, item=lambda idx: None),
                sketchConicCurves=types.SimpleNamespace(count=0, item=lambda idx: None),
            ),
            geometricConstraints=mock_constraints,
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
            "constraint_type": "coincident",
            "use_selection": False,
            "entity_indices": [0, 1],
        })

        self.assertIn("result", res)
        self.assertEqual(added, [("coincident", "point1", "line1")])

    def test_delete_sketch_constraint_requires_reason(self):
        mock_constraint = types.SimpleNamespace(isDeletable=True, deleteMe=lambda: None)
        mock_sketch = types.SimpleNamespace(
            name="TestSketch",
            geometricConstraints=types.SimpleNamespace(
                count=1,
                item=lambda idx: mock_constraint,
            ),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("delete_sketch_constraint", {
            "sketch_name": "TestSketch",
            "constraint_index": 0,
        })

        self.assertIn("error", res)
        self.assertIn("reason is required", res["error"])

    def test_delete_sketch_constraint(self):
        parametric = importlib.import_module("tools.parametric")
        original_snapshot = parametric._design_state_snapshot
        original_compare = parametric.compare_design_state
        deleted = []
        mock_constraint = types.SimpleNamespace(
            objectType="CoincidentConstraint",
            isDeletable=True,
            deleteMe=lambda: deleted.append(True),
        )
        mock_sketch = types.SimpleNamespace(
            name="TestSketch",
            geometricConstraints=types.SimpleNamespace(
                count=1,
                item=lambda idx: mock_constraint,
            ),
        )
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                sketches=[mock_sketch],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        parametric._design_state_snapshot = lambda include_selections=False: {
            "counts": {"constraints": 1 - len(deleted)}
        }
        parametric.compare_design_state = lambda before, after: {
            "result": {"hasChanges": True, "riskLevel": "low", "before": before, "after": after}
        }
        try:
            res = self.tools.execute_tool("delete_sketch_constraint", {
                "sketch_name": "TestSketch",
                "constraint_index": 0,
                "reason": "Remove obsolete coincident constraint.",
            })
        finally:
            parametric._design_state_snapshot = original_snapshot
            parametric.compare_design_state = original_compare

        self.assertIn("result", res)
        self.assertEqual(deleted, [True])
        self.assertEqual(res["result"]["constraintObjectType"], "CoincidentConstraint")
        self.assertEqual(res["result"]["stateComparison"]["riskLevel"], "low")

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
        self.assertIn("stateComparison", res["result"])

    def test_combine_bodies_requires_explicit_schema_operation(self):
        combine_schema = next(tool for tool in self.tools.get_tool_schemas() if tool["name"] == "combine_bodies")
        self.assertIn("operation", combine_schema["inputSchema"]["required"])

    def test_create_construction_point_targets_named_component(self):
        class MockSketchPoints:
            def add(self, point):
                return types.SimpleNamespace(name="", geometry=point)

        class MockSketches:
            def __init__(self):
                self.created = []
            def add(self, plane):
                sketch = types.SimpleNamespace(
                    name="",
                    isLightBulbOn=True,
                    sketchPoints=MockSketchPoints(),
                    plane=plane,
                )
                self.created.append(sketch)
                return sketch

        class MockPointInput:
            def __init__(self):
                self.source = None
            def setByPoint(self, source):
                self.source = source

        class MockConstructionPoints:
            def __init__(self):
                self.inputs = []
            def createInput(self):
                point_input = MockPointInput()
                self.inputs.append(point_input)
                return point_input
            def add(self, point_input):
                return types.SimpleNamespace(name="", input=point_input)

        class MockUnits:
            defaultLengthUnits = "mm"
            def evaluateExpression(self, expression, _units):
                return float(str(expression).split()[0])

        target = types.SimpleNamespace(
            name="TargetComp",
            xYConstructionPlane=types.SimpleNamespace(name="Target XY"),
            xZConstructionPlane=types.SimpleNamespace(name="Target XZ"),
            yZConstructionPlane=types.SimpleNamespace(name="Target YZ"),
            sketches=MockSketches(),
            constructionPoints=MockConstructionPoints(),
        )
        occurrence = types.SimpleNamespace(component=target)
        root = types.SimpleNamespace(
            name="Root",
            allOccurrences=[occurrence],
            xYConstructionPlane=types.SimpleNamespace(name="Root XY"),
            xZConstructionPlane=types.SimpleNamespace(name="Root XZ"),
            yZConstructionPlane=types.SimpleNamespace(name="Root YZ"),
        )
        self.mock_design = types.SimpleNamespace(rootComponent=root, unitsManager=MockUnits())
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("create_construction_point", {
            "name": "AnchorPoint",
            "mode": "coordinates",
            "x": "1 mm",
            "y": "2 mm",
            "target_component_name": "TargetComp",
        })

        self.assertIn("result", res)
        self.assertEqual(res["result"]["pointName"], "AnchorPoint")
        self.assertEqual(res["result"]["componentName"], "TargetComp")
        self.assertEqual(target.sketches.created[0].plane.name, "Target XY")
        self.assertEqual(target.constructionPoints.inputs[0].source.name, "AnchorPoint_SketchPoint")

    def test_combine_bodies_rejects_missing_operation_at_runtime(self):
        mock_target = types.SimpleNamespace(name="TargetBody")
        mock_tool = types.SimpleNamespace(name="ToolBody")
        self.mock_design = types.SimpleNamespace(
            rootComponent=types.SimpleNamespace(
                bRepBodies=[mock_target, mock_tool],
                allOccurrences=[],
            )
        )
        _fake_app.activeProduct = self.mock_design

        res = self.tools.execute_tool("combine_bodies", {
            "target_body_name": "TargetBody",
            "tool_body_names": ["ToolBody"],
        })

        self.assertIn("error", res)
        self.assertIn("operation must be explicitly set", res["error"])

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
