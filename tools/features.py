"""
Typed feature creation tools with built-in before/after state checks.
"""

import traceback

import adsk.core, adsk.fusion

from . import register_tool
from .inspection import (
    _body_names,
    _collection_items,
    _design_state_snapshot,
    _find_sketch_by_name,
    _safe_value,
    compare_design_state,
    get_active_design,
    inspect_feature,
)


def _feature_operation(value):
    operations = {
        "newbody": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "new_body": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
        "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
    }
    key = (value or "").replace(" ", "").lower()
    if key not in operations:
        raise ValueError("operation must be one of NewBody, Join, Cut, or Intersect.")
    return operations[key]


def _operation_label(value):
    labels = {
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation: "NewBody",
        adsk.fusion.FeatureOperations.JoinFeatureOperation: "Join",
        adsk.fusion.FeatureOperations.CutFeatureOperation: "Cut",
        adsk.fusion.FeatureOperations.IntersectFeatureOperation: "Intersect",
    }
    return labels.get(value, str(value))


def _profile_by_index(sketch, profile_index):
    profiles = _safe_value(lambda: sketch.profiles)
    if not profiles:
        raise ValueError(f"Sketch '{sketch.name}' has no profiles.")
    index = int(profile_index)
    count = _safe_value(lambda: profiles.count, 0) or 0
    if index < 0 or index >= count:
        raise ValueError(f"profile_index {index} is out of range for sketch '{sketch.name}' with {count} profiles.")
    return profiles.item(index)


def _set_participant_bodies(ext_input, body_names):
    if not body_names:
        return []
    design = get_active_design()
    root = design.rootComponent
    requested = set(body_names)
    resolved = []
    for body in _collection_items(_safe_value(lambda: root.bRepBodies)):
        if _safe_value(lambda body=body: body.name) in requested:
            resolved.append(body)
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            if _safe_value(lambda body=body: body.name) in requested:
                resolved.append(body)
    missing = sorted(requested - {body.name for body in resolved})
    if missing:
        raise ValueError(f"Participant bodies not found: {', '.join(missing)}")

    participant_bodies = _safe_value(lambda: ext_input.participantBodies)
    if participant_bodies:
        for body in resolved:
            participant_bodies.add(body)
    return [_safe_value(lambda body=body: body.name) for body in resolved]


def _find_body_by_name(body_name):
    design = get_active_design()
    root = design.rootComponent
    for body in _collection_items(_safe_value(lambda: root.bRepBodies)):
        if _safe_value(lambda body=body: body.name) == body_name:
            return body
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            if _safe_value(lambda body=body: body.name) == body_name:
                return body
    return None


def _body_edges_by_indices(body, edge_indices=None):
    edges = _safe_value(lambda: body.edges)
    count = _safe_value(lambda: edges.count, 0) or 0
    if count == 0:
        raise ValueError(f"Body '{body.name}' has no edges.")
    indices = list(range(count)) if edge_indices is None else [int(index) for index in edge_indices]
    selected = []
    for index in indices:
        if index < 0 or index >= count:
            raise ValueError(f"edge index {index} is out of range for body '{body.name}' with {count} edges.")
        selected.append(edges.item(index))
    return selected


def _edge_collection(edges):
    collection = adsk.core.ObjectCollection.create()
    for edge in edges:
        collection.add(edge)
    return collection

def _all_components(root):
    components = [root]
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        if component and component not in components:
            components.append(component)
    return components


def _find_named_axis(root, name):
    if not name:
        return None, None
    key = str(name).replace(" ", "").lower()
    standard = {
        "x": getattr(root, "xConstructionAxis", None),
        "xaxis": getattr(root, "xConstructionAxis", None),
        "xconstructionaxis": getattr(root, "xConstructionAxis", None),
        "y": getattr(root, "yConstructionAxis", None),
        "yaxis": getattr(root, "yConstructionAxis", None),
        "yconstructionaxis": getattr(root, "yConstructionAxis", None),
        "z": getattr(root, "zConstructionAxis", None),
        "zaxis": getattr(root, "zConstructionAxis", None),
        "zconstructionaxis": getattr(root, "zConstructionAxis", None),
    }
    if key in standard and standard[key]:
        return standard[key], root
    for component in _all_components(root):
        for axis in _collection_items(_safe_value(lambda component=component: component.constructionAxes)):
            if _safe_value(lambda axis=axis: axis.name) == name:
                return axis, component
    return None, None


def _selected_axis():
    app = adsk.core.Application.get()
    selections = _safe_value(lambda: app.userInterface.activeSelections)
    if not selections or _safe_value(lambda: selections.count, 0) == 0:
        return None, None
    entity = _safe_value(lambda: selections.item(0).entity)
    axis = adsk.fusion.ConstructionAxis.cast(entity)
    if axis:
        return axis, _safe_value(lambda: axis.parentComponent)
    edge = adsk.fusion.BRepEdge.cast(entity)
    if edge:
        return edge, _safe_value(lambda: edge.body.parentComponent)
    return None, None


def _edge_refs(edges):
    return [
        {
            "index": index,
            "name": _safe_value(lambda edge=edge: edge.name),
            "entityToken": _safe_value(lambda edge=edge: edge.entityToken),
            "length": _safe_value(lambda edge=edge: edge.length),
            "objectType": _safe_value(lambda edge=edge: edge.objectType),
        }
        for index, edge in enumerate(edges)
    ]


def _edge_body_index(body, edge):
    edges = _safe_value(lambda: body.edges)
    count = _safe_value(lambda: edges.count, 0) or 0
    for index in range(count):
        if edges.item(index) == edge:
            return index
    return None


def _vertex_point(vertex):
    point = _safe_value(lambda: vertex.geometry)
    if not point:
        return None
    return [
        _safe_value(lambda: point.x),
        _safe_value(lambda: point.y),
        _safe_value(lambda: point.z),
    ]


def _edge_ref(body, edge, index):
    geometry = _safe_value(lambda: edge.geometry)
    evaluator = _safe_value(lambda: geometry.evaluator)
    midpoint = None
    if evaluator:
        parameter_range = _safe_value(lambda: evaluator.getParameterExtents())
        try:
            if isinstance(parameter_range, tuple) and parameter_range[0]:
                start_param = parameter_range[1]
                end_param = parameter_range[2]
                _, point = evaluator.getPointAtParameter((start_param + end_param) / 2.0)
                midpoint = [
                    _safe_value(lambda: point.x),
                    _safe_value(lambda: point.y),
                    _safe_value(lambda: point.z),
                ] if point else None
        except Exception:
            midpoint = None
    return {
        "index": index,
        "name": _safe_value(lambda: edge.name),
        "entityToken": _safe_value(lambda: edge.entityToken),
        "length": _safe_value(lambda: edge.length),
        "objectType": _safe_value(lambda: edge.objectType),
        "geometryType": _safe_value(lambda: geometry.objectType) if geometry else None,
        "startVertex": _vertex_point(_safe_value(lambda: edge.startVertex)),
        "endVertex": _vertex_point(_safe_value(lambda: edge.endVertex)),
        "midpoint": midpoint,
    }


def _body_faces_by_indices(body, face_indices=None):
    faces = _safe_value(lambda: body.faces)
    count = _safe_value(lambda: faces.count, 0) or 0
    if count == 0:
        raise ValueError(f"Body '{body.name}' has no faces.")
    indices = list(range(count)) if face_indices is None else [int(index) for index in face_indices]
    selected = []
    for index in indices:
        if index < 0 or index >= count:
            raise ValueError(f"face index {index} is out of range for body '{body.name}' with {count} faces.")
        selected.append(faces.item(index))
    return selected


def _face_body_index(body, face):
    faces = _safe_value(lambda: body.faces)
    count = _safe_value(lambda: faces.count, 0) or 0
    for index in range(count):
        if faces.item(index) == face:
            return index
    return None


def _face_ref(body, face, index):
    geometry = _safe_value(lambda: face.geometry)
    centroid = _safe_value(lambda: face.centroid)
    return {
        "index": index,
        "name": _safe_value(lambda: face.name),
        "entityToken": _safe_value(lambda: face.entityToken),
        "area": _safe_value(lambda: face.area),
        "objectType": _safe_value(lambda: face.objectType),
        "geometryType": _safe_value(lambda: geometry.objectType) if geometry else None,
        "centroid": [
            _safe_value(lambda: centroid.x),
            _safe_value(lambda: centroid.y),
            _safe_value(lambda: centroid.z),
        ] if centroid else None,
    }


def _selected_brep_faces():
    app = adsk.core.Application.get()
    selections = _safe_value(lambda: app.userInterface.activeSelections)
    if not selections or _safe_value(lambda: selections.count, 0) == 0:
        return []

    faces = []
    for index in range(selections.count):
        entity = _safe_value(lambda index=index: selections.item(index).entity)
        face = adsk.fusion.BRepFace.cast(entity)
        if face:
            faces.append(face)
    return faces


def _face_parent_component(face):
    return _safe_value(lambda: face.body.parentComponent)


def _same_component_faces(faces):
    components = [_face_parent_component(face) for face in faces]
    first = components[0] if components else None
    return bool(first) and all(component == first for component in components)


@register_tool("get_body_edges")
def get_body_edges(body_name, edge_indices=None):
    """
    Return indexed edge metadata for a named body.

    This is the safe targeting companion for fillet_feature and
    chamfer_feature. It gives agents stable edge indices plus tokens and basic
    geometry hints before they choose edges for a mutating operation.
    """
    try:
        body = _find_body_by_name(body_name)
        if not body:
            return {"error": f"Body '{body_name}' not found."}
        edges = _body_edges_by_indices(body, edge_indices)
        return {
            "result": {
                "bodyName": _safe_value(lambda: body.name),
                "componentName": _safe_value(lambda: body.parentComponent.name),
                "edgeCount": _safe_value(lambda: body.edges.count, len(edges)),
                "edges": [
                    _edge_ref(body, edge, _edge_body_index(body, edge))
                    for edge in edges
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting body edges: {e}\n{err}")
        return {"error": f"Failed to inspect body edges: {str(e)}"}


@register_tool("get_body_faces")
def get_body_faces(body_name, face_indices=None):
    """
    Return indexed face metadata for a named body.

    This is the safe targeting companion for shell_body and selected-face
    workflows. It gives agents stable face indices plus tokens and basic
    geometry hints before they choose open faces for a mutating operation.
    """
    try:
        body = _find_body_by_name(body_name)
        if not body:
            return {"error": f"Body '{body_name}' not found."}
        faces = _body_faces_by_indices(body, face_indices)
        return {
            "result": {
                "bodyName": _safe_value(lambda: body.name),
                "componentName": _safe_value(lambda: body.parentComponent.name),
                "faceCount": _safe_value(lambda: body.faces.count, len(faces)),
                "faces": [
                    _face_ref(body, face, _face_body_index(body, face))
                    for face in faces
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting body faces: {e}\n{err}")
        return {"error": f"Failed to inspect body faces: {str(e)}"}


@register_tool("offset_face_or_press_pull")
def offset_face_or_press_pull(body_name=None, face_indices=None, distance=None, name=None, use_selection=False):
    """
    Create a controlled Offset Face feature on explicit or selected BRep faces.

    This intentionally implements the face-offset branch of Fusion's Press Pull
    behavior. It does not try to emulate Press Pull for edges or sketch profiles,
    where Fusion may create fillets or extrudes instead.
    """
    try:
        if not distance:
            return {"error": "distance is required, e.g. '1 mm' or '-0.5 mm'."}

        body = None
        if use_selection:
            faces = _selected_brep_faces()
            if not faces:
                return {"error": "No selected BRep faces found."}
        else:
            if not body_name:
                return {"error": "body_name is required unless use_selection=true."}
            if face_indices is None or len(face_indices) == 0:
                return {"error": "face_indices is required. Use get_body_faces first to choose explicit face indices."}
            body = _find_body_by_name(body_name)
            if not body:
                return {"error": f"Body '{body_name}' not found."}
            faces = _body_faces_by_indices(body, face_indices)

        if not _same_component_faces(faces):
            return {"error": "All offset faces must belong to the same component."}

        component = _face_parent_component(faces[0]) or get_active_design().rootComponent
        offset_faces = _safe_value(lambda: component.features.offsetFacesFeatures)
        if not offset_faces:
            return {"error": "This Fusion runtime does not expose offsetFacesFeatures for API-created Offset Face features."}

        before = _design_state_snapshot(include_selections=False)
        distance_input = adsk.core.ValueInput.createByString(str(distance))
        offset_input = offset_faces.createInput(faces, distance_input)
        if offset_input is None:
            return {"error": "Fusion failed to create Offset Face input for the supplied faces and distance."}

        feature = offset_faces.add(offset_input)
        if not feature:
            return {"error": "Fusion failed to create the Offset Face feature. The distance or selected faces may be geometrically invalid."}
        if name:
            feature.name = name

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: feature.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        resolved_body = body or _safe_value(lambda: faces[0].body)
        return {
            "result": {
                "featureName": feature_name,
                "bodyName": _safe_value(lambda: resolved_body.name),
                "componentName": _safe_value(lambda: component.name),
                "faceIndices": [
                    _face_body_index(_safe_value(lambda face=face: face.body), face)
                    for face in faces
                ],
                "faces": [
                    _face_ref(_safe_value(lambda face=face: face.body), face, _face_body_index(_safe_value(lambda face=face: face.body), face))
                    for face in faces
                ],
                "distance": distance,
                "useSelection": bool(use_selection),
                "warnings": [
                    "This tool creates a Fusion Offset Face feature only; it does not emulate Press Pull for edges or sketch profiles.",
                    "Positive distance follows the selected face normal; negative distance offsets the opposite direction.",
                ],
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating offset face feature: {e}\n{err}")
        return {"error": f"Failed to create offset face feature: {str(e)}"}


@register_tool("extrude_feature")
def extrude_feature(sketch_name, distance, operation, name=None, profile_index=0, body_name=None, participant_body_names=None):
    """
    Create an extrusion from a named sketch profile.

    The tool intentionally requires an explicit operation because NewBody/Join/Cut
    ambiguity is one of the easiest ways for agents to damage existing models.
    """
    try:
        if not operation:
            return {"error": "operation is required and must be one of NewBody, Join, Cut, or Intersect."}
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}

        before = _design_state_snapshot(include_selections=False)
        profile = _profile_by_index(sketch, profile_index)
        op = _feature_operation(operation)
        component = _safe_value(lambda: sketch.parentComponent) or get_active_design().rootComponent
        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, op)
        participants = _set_participant_bodies(ext_input, participant_body_names)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(distance))
        extrude = extrudes.add(ext_input)
        if name:
            extrude.name = name

        result_body_names = []
        bodies = _safe_value(lambda: extrude.bodies)
        for index, body in enumerate(_collection_items(bodies)):
            if body_name:
                body.name = body_name if index == 0 else f"{body_name}_{index}"
            result_body_names.append(_safe_value(lambda body=body: body.name))

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: extrude.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "sketchName": sketch.name,
                "profileIndex": int(profile_index),
                "operation": _operation_label(op),
                "distance": distance,
                "participantBodies": participants or _body_names(_safe_value(lambda: extrude.participantBodies)),
                "resultBodies": result_body_names,
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating extrude feature: {e}\n{err}")
        return {"error": f"Failed to create extrude feature: {str(e)}"}


@register_tool("revolve_feature")
def revolve_feature(sketch_name, axis_name="z", operation=None, angle="360 deg", name=None, profile_index=0, body_name=None, participant_body_names=None, use_selected_axis=False):
    """
    Create a revolve feature from a named sketch profile around an explicit axis.

    The operation is required for the same reason as extrude_feature: revolve
    features can create, join, cut, or intersect geometry, and guessing can
    damage an existing model.
    """
    try:
        if not operation:
            return {"error": "operation is required and must be one of NewBody, Join, Cut, or Intersect."}
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}

        design = get_active_design()
        root = design.rootComponent
        if use_selected_axis:
            axis, axis_component = _selected_axis()
            if not axis:
                return {"error": "No selected construction axis or linear BRep edge found."}
        else:
            axis, axis_component = _find_named_axis(root, axis_name)
            if not axis:
                return {"error": f"Revolve axis '{axis_name}' not found. Use x, y, z, a named construction axis, or use_selected_axis=true."}

        before = _design_state_snapshot(include_selections=False)
        profile = _profile_by_index(sketch, profile_index)
        op = _feature_operation(operation)
        component = _safe_value(lambda: sketch.parentComponent) or axis_component or root
        revolves = _safe_value(lambda: component.features.revolveFeatures)
        if not revolves:
            return {"error": "This Fusion runtime does not expose revolveFeatures for API-created revolve features."}
        revolve_input = revolves.createInput(profile, axis, op)
        participants = _set_participant_bodies(revolve_input, participant_body_names)
        revolve_input.setAngleExtent(False, adsk.core.ValueInput.createByString(str(angle)))
        revolve = revolves.add(revolve_input)
        if name:
            revolve.name = name

        result_body_names = []
        bodies = _safe_value(lambda: revolve.bodies)
        for index, body in enumerate(_collection_items(bodies)):
            if body_name:
                body.name = body_name if index == 0 else f"{body_name}_{index}"
            result_body_names.append(_safe_value(lambda body=body: body.name))

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: revolve.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "sketchName": sketch.name,
                "profileIndex": int(profile_index),
                "axisName": _safe_value(lambda: axis.name) or axis_name,
                "operation": _operation_label(op),
                "angle": angle,
                "useSelectedAxis": bool(use_selected_axis),
                "participantBodies": participants or _body_names(_safe_value(lambda: revolve.participantBodies)),
                "resultBodies": result_body_names,
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating revolve feature: {e}\n{err}")
        return {"error": f"Failed to create revolve feature: {str(e)}"}


@register_tool("fillet_feature")
def fillet_feature(body_name, edge_indices, radius, name=None, tangent_chain=True):
    """
    Create a constant-radius fillet on selected edges of a named body.

    Edge indices are required so callers make the target selection explicit.
    Use inspect/selection tools first when edge identity is uncertain.
    """
    try:
        if edge_indices is None or len(edge_indices) == 0:
            return {"error": "edge_indices is required. Inspect the body or use selection before choosing edges."}
        body = _find_body_by_name(body_name)
        if not body:
            return {"error": f"Body '{body_name}' not found."}

        before = _design_state_snapshot(include_selections=False)
        edges = _body_edges_by_indices(body, edge_indices)
        edge_collection = _edge_collection(edges)
        component = _safe_value(lambda: body.parentComponent) or get_active_design().rootComponent
        fillets = component.features.filletFeatures
        fillet_input = fillets.createInput()
        radius_input = adsk.core.ValueInput.createByString(radius)
        fillet_input.addConstantRadiusEdgeSet(edge_collection, radius_input, bool(tangent_chain))
        fillet = fillets.add(fillet_input)
        if name:
            fillet.name = name

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: fillet.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "bodyName": body.name,
                "edgeIndices": [int(index) for index in edge_indices],
                "edges": _edge_refs(edges),
                "radius": radius,
                "tangentChain": bool(tangent_chain),
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating fillet feature: {e}\n{err}")
        return {"error": f"Failed to create fillet feature: {str(e)}"}


@register_tool("chamfer_feature")
def chamfer_feature(body_name, edge_indices, distance, name=None, tangent_chain=True):
    """
    Create an equal-distance chamfer on selected edges of a named body.

    Edge indices are required for the same reason as fillets: chamfering the
    wrong edge is easy to miss visually and hard to diagnose after export.
    """
    try:
        if edge_indices is None or len(edge_indices) == 0:
            return {"error": "edge_indices is required. Inspect the body or use selection before choosing edges."}
        body = _find_body_by_name(body_name)
        if not body:
            return {"error": f"Body '{body_name}' not found."}

        before = _design_state_snapshot(include_selections=False)
        edges = _body_edges_by_indices(body, edge_indices)
        edge_collection = _edge_collection(edges)
        component = _safe_value(lambda: body.parentComponent) or get_active_design().rootComponent
        chamfers = component.features.chamferFeatures
        chamfer_input = chamfers.createInput(edge_collection, bool(tangent_chain))
        chamfer_input.setToEqualDistance(adsk.core.ValueInput.createByString(distance))
        chamfer = chamfers.add(chamfer_input)
        if name:
            chamfer.name = name

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: chamfer.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "bodyName": body.name,
                "edgeIndices": [int(index) for index in edge_indices],
                "edges": _edge_refs(edges),
                "distance": distance,
                "chamferType": "EqualDistance",
                "tangentChain": bool(tangent_chain),
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating chamfer feature: {e}\n{err}")
        return {"error": f"Failed to create chamfer feature: {str(e)}"}


@register_tool("shell_body")
def shell_body(body_name, thickness, open_face_indices=None, name=None, thickness_side="inside", outside_thickness=None, tangent_chain=True):
    """
    Shell a named solid body with explicit wall thickness.

    If open_face_indices is supplied, those faces are removed/opened by the
    shell feature. Use get_body_faces first when face identity is uncertain.
    """
    try:
        if not thickness:
            return {"error": "thickness is required, e.g. '2 mm'."}
        body = _find_body_by_name(body_name)
        if not body:
            return {"error": f"Body '{body_name}' not found."}

        before = _design_state_snapshot(include_selections=False)
        input_entities = adsk.core.ObjectCollection.create()
        opened_faces = []
        if open_face_indices:
            opened_faces = _body_faces_by_indices(body, open_face_indices)
            for face in opened_faces:
                input_entities.add(face)
        else:
            input_entities.add(body)

        component = _safe_value(lambda: body.parentComponent) or get_active_design().rootComponent
        shells = component.features.shellFeatures
        shell_input = shells.createInput(input_entities, bool(tangent_chain))
        side = (thickness_side or "inside").replace("_", "").replace(" ", "").lower()
        if side in ("inside", "both"):
            shell_input.insideThickness = adsk.core.ValueInput.createByString(thickness)
        if side == "outside":
            shell_input.outsideThickness = adsk.core.ValueInput.createByString(outside_thickness or thickness)
        elif side == "both":
            shell_input.outsideThickness = adsk.core.ValueInput.createByString(outside_thickness or thickness)
        if side not in ("inside", "outside", "both"):
            return {"error": "thickness_side must be inside, outside, or both."}

        shell = shells.add(shell_input)
        if name:
            shell.name = name

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: shell.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "bodyName": body.name,
                "thickness": thickness,
                "outsideThickness": outside_thickness,
                "thicknessSide": thickness_side,
                "openFaceIndices": [int(index) for index in (open_face_indices or [])],
                "openedFaces": [
                    _face_ref(body, face, _face_body_index(body, face))
                    for face in opened_faces
                ],
                "tangentChain": bool(tangent_chain),
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating shell feature: {e}\n{err}")
        return {"error": f"Failed to create shell feature: {str(e)}"}
