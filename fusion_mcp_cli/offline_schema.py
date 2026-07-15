import sys
import types


def install_adsk_schema_stub():
    if "adsk" in sys.modules:
        return
    adsk = types.ModuleType("adsk")
    core = types.ModuleType("adsk.core")
    fusion = types.ModuleType("adsk.fusion")

    class _Application:
        @staticmethod
        def get():
            return types.SimpleNamespace(
                activeProduct=None,
                userInterface=types.SimpleNamespace(activeCommand="SelectCommand"),
                log=lambda *_args, **_kwargs: None,
                registerCustomEvent=lambda event_id: types.SimpleNamespace(eventId=event_id, add=lambda _handler: None, remove=lambda _handler: None),
                unregisterCustomEvent=lambda _event_id: None,
            )

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


def load_offline_mcp_surface():
    install_adsk_schema_stub()
    import tools
    from server import mcp_server

    return {
        "server": mcp_server.make_initialize_result(),
        "tools": tools.get_tool_schemas(),
        "resources": tools.get_resources_schemas(),
        "resourceTemplates": tools.get_resource_templates(),
        "prompts": mcp_server.PROMPTS,
        "profiles": tools.read_tool_profiles(),
        "serverCapabilities": tools.read_server_capabilities(),
    }
