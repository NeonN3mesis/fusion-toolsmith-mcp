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
