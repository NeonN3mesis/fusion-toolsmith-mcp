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
