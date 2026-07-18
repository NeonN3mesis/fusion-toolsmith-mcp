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


def _profile_loop_by_index(profile, loop_index=None, outer_loop=False):
    loops = _safe_value(lambda: profile.profileLoops) or _safe_value(lambda: profile.profileLoops)
    loop_items = _collection_items(loops)
    if not loop_items:
        raise ValueError("Selected profile does not expose profileLoops in this Fusion runtime.")
    if outer_loop:
        for loop in loop_items:
            if _safe_value(lambda loop=loop: loop.isOuter):
                return loop, loop_items.index(loop)
        return loop_items[0], 0
    index = int(loop_index or 0)
    if index < 0 or index >= len(loop_items):
        raise ValueError(f"loop_index {index} is out of range for profile with {len(loop_items)} loop(s).")
    return loop_items[index], index


def _loop_profile_curves(profile_loop):
    curves = (
        _safe_value(lambda: profile_loop.profileCurves)
        or _safe_value(lambda: profile_loop.profileCurves)
        or _safe_value(lambda: profile_loop.curves)
    )
    items = _collection_items(curves)
    if not items:
        raise ValueError("Selected profile loop does not expose profile curves.")
    return items


def _profile_curve_entity(profile_curve):
    return (
        _safe_value(lambda: profile_curve.sketchEntity)
        or _safe_value(lambda: profile_curve.curve)
        or _safe_value(lambda: profile_curve.geometry)
        or profile_curve
    )


def _object_collection(entities):
    collection = adsk.core.ObjectCollection.create()
    for entity in entities:
        add = _safe_value(lambda: collection.add)
        if callable(add):
            add(entity)
        elif hasattr(collection, "append"):
            collection.append(entity)
        else:
            raise ValueError("Fusion ObjectCollection did not expose add/append.")
    return collection


def _curve_summary(entity, index):
    return {
        "index": index,
        "name": _safe_value(lambda: entity.name),
        "objectType": _safe_value(lambda: entity.objectType),
        "entityToken": _safe_value(lambda: entity.entityToken),
        "isConstruction": _safe_value(lambda: entity.isConstruction),
    }


def _ensure_destination_sketch(source_sketch, destination_sketch_name=None, destination_plane=None):
    if destination_sketch_name:
        existing = _find_sketch_by_name(destination_sketch_name)
        if existing:
            return existing, False
    component = _safe_value(lambda: source_sketch.parentComponent) or get_active_design().rootComponent
    sketches = _safe_value(lambda: component.sketches)
    if not sketches:
        raise ValueError("Source sketch component does not expose a sketches collection.")
    plane = None
    if destination_plane:
        key = str(destination_plane).lower()
        if key in ("xy", "xyconstructionplane"):
            plane = _safe_value(lambda: component.xYConstructionPlane)
        elif key in ("xz", "xzconstructionplane"):
            plane = _safe_value(lambda: component.xZConstructionPlane)
        elif key in ("yz", "yzconstructionplane"):
            plane = _safe_value(lambda: component.yZConstructionPlane)
        else:
            for candidate in _collection_items(_safe_value(lambda: component.constructionPlanes)):
                if _safe_value(lambda candidate=candidate: candidate.name) == destination_plane:
                    plane = candidate
                    break
    plane = plane or _safe_value(lambda: source_sketch.referencePlane) or _safe_value(lambda: source_sketch.parentConstructionPlane) or _safe_value(lambda: component.xYConstructionPlane)
    if not plane:
        raise ValueError("Could not resolve a destination sketch plane.")
    sketch = sketches.add(plane)
    sketch.name = destination_sketch_name or f"{_safe_value(lambda: source_sketch.name) or 'Profile'}_LoopCopy"
    return sketch, True


def _require_reason(reason, operation):
    if not isinstance(reason, str) or not reason.strip():
        return {"error": f"reason is required before {operation}. State why this model change is intentional."}
    return None


def _nonzero_length_expression(design, expression):
    if expression is None:
        return False
    try:
        return abs(float(design.unitsManager.evaluateExpression(str(expression), "cm"))) > 1e-9
    except Exception:
        return bool(str(expression).strip() not in {"0", "0mm", "0 mm", "0.0", "0.0 mm"})


def _profiles_from_sections(sections):
    if not isinstance(sections, list) or len(sections) < 2:
        raise ValueError("sections must contain at least two items with sketch_name and optional profile_index.")
    resolved = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            raise ValueError(f"sections[{index}] must be an object with sketch_name and optional profile_index.")
        sketch_name = section.get("sketch_name")
        if not sketch_name:
            raise ValueError(f"sections[{index}].sketch_name is required.")
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            raise ValueError(f"Sketch '{sketch_name}' not found.")
        profile_index = int(section.get("profile_index", 0))
        resolved.append({
            "sketch": sketch,
            "profile": _profile_by_index(sketch, profile_index),
            "profileIndex": profile_index,
        })
    return resolved


def _sketch_curves(sketch):
    curves = _safe_value(lambda: sketch.sketchCurves)
    if not curves:
        return []
    groups = [
        ("lines", _safe_value(lambda: curves.sketchLines)),
        ("circles", _safe_value(lambda: curves.sketchCircles)),
        ("arcs", _safe_value(lambda: curves.sketchArcs)),
        ("ellipses", _safe_value(lambda: curves.sketchEllipses)),
        ("fittedSplines", _safe_value(lambda: curves.sketchFittedSplines)),
        ("fixedSplines", _safe_value(lambda: curves.sketchFixedSplines)),
        ("conics", _safe_value(lambda: curves.sketchConicCurves)),
    ]
    result = []
    for group_name, collection in groups:
        for item in _collection_items(collection):
            result.append((group_name, item))
    return result


def _sketch_curve_by_index(sketch, curve_index):
    curves = _sketch_curves(sketch)
    if not curves:
        raise ValueError(f"Sketch '{sketch.name}' has no path curves.")
    index = int(curve_index)
    if index < 0 or index >= len(curves):
        raise ValueError(f"path_curve_index {index} is out of range for sketch '{sketch.name}' with {len(curves)} path curves.")
    return curves[index]


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


def _normalize_tokens(tokens):
    if tokens is None:
        return []
    if isinstance(tokens, str):
        return [tokens]
    return [str(token) for token in tokens if token is not None]


def _find_entity_by_token(entity_token):
    if not entity_token:
        return None
    design = get_active_design()
    found = _safe_value(lambda: design.findEntityByToken(entity_token))
    if not found:
        return None
    if isinstance(found, (list, tuple)):
        return found[0] if found else None
    if hasattr(found, "count") and hasattr(found, "item"):
        return found.item(0) if found.count else None
    return found


def _find_body_by_token(body_entity_token):
    entity = _find_entity_by_token(body_entity_token)
    if not entity:
        return None
    body = adsk.fusion.BRepBody.cast(entity)
    if body:
        return body
    if _safe_value(lambda: entity.objectType, "").lower().endswith("brepbody"):
        return entity
    if hasattr(entity, "faces") or hasattr(entity, "edges"):
        return entity
    return None


def _body_from_name_or_token(body_name=None, body_entity_token=None):
    if body_entity_token:
        body = _find_body_by_token(body_entity_token)
        if not body:
            raise ValueError(f"Body entity token '{body_entity_token}' did not resolve to a BRep body.")
        return body
    if body_name:
        body = _find_body_by_name(body_name)
        if not body:
            raise ValueError(f"Body '{body_name}' not found.")
        return body
    return None


def _entity_kind(entity):
    object_type = (_safe_value(lambda: entity.objectType) or "").lower()
    if "brepedge" in object_type:
        return "edge"
    if "brepface" in object_type:
        return "face"
    if "brepbody" in object_type:
        return "body"
    if hasattr(entity, "length") and hasattr(entity, "body"):
        return "edge"
    if hasattr(entity, "area") and hasattr(entity, "body"):
        return "face"
    if hasattr(entity, "faces") or hasattr(entity, "edges"):
        return "body"
    return None


def _entities_by_tokens(entity_tokens, expected_kind):
    entities = []
    for token in _normalize_tokens(entity_tokens):
        entity = _find_entity_by_token(token)
        if not entity:
            raise ValueError(f"Entity token '{token}' did not resolve to a Fusion entity.")
        kind = _entity_kind(entity)
        if kind != expected_kind:
            raise ValueError(f"Entity token '{token}' resolved to {kind or 'unknown'}, expected {expected_kind}.")
        entities.append(entity)
    return entities


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


def _resolve_edges(body_name=None, edge_indices=None, edge_entity_tokens=None, body_entity_token=None):
    edges = _entities_by_tokens(edge_entity_tokens, "edge")
    if edges:
        body = _safe_value(lambda: edges[0].body)
        if body_entity_token or body_name:
            requested_body = _body_from_name_or_token(body_name, body_entity_token)
            if body and requested_body and body != requested_body:
                raise ValueError("Resolved edge tokens do not belong to the requested body.")
            body = requested_body or body
        if not body:
            raise ValueError("Edge tokens resolved, but their parent body could not be determined. Provide body_name or body_entity_token.")
        for edge in edges:
            edge_body = _safe_value(lambda edge=edge: edge.body)
            if edge_body and edge_body != body:
                raise ValueError("All edge tokens must belong to the same body.")
        return body, edges, "entity_tokens"

    if edge_indices is None or len(edge_indices) == 0:
        raise ValueError("edge_indices is required unless edge_entity_tokens are provided. Use get_body_edges first to choose explicit edges.")
    body = _body_from_name_or_token(body_name, body_entity_token)
    if not body:
        raise ValueError("body_name or body_entity_token is required unless edge_entity_tokens are provided.")
    return body, _body_edges_by_indices(body, edge_indices), "indices"


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


def _resolve_faces(body_name=None, face_indices=None, face_entity_tokens=None, body_entity_token=None):
    faces = _entities_by_tokens(face_entity_tokens, "face")
    if faces:
        body = _safe_value(lambda: faces[0].body)
        if body_entity_token or body_name:
            requested_body = _body_from_name_or_token(body_name, body_entity_token)
            if body and requested_body and body != requested_body:
                raise ValueError("Resolved face tokens do not belong to the requested body.")
            body = requested_body or body
        if not body:
            raise ValueError("Face tokens resolved, but their parent body could not be determined. Provide body_name or body_entity_token.")
        for face in faces:
            face_body = _safe_value(lambda face=face: face.body)
            if face_body and face_body != body:
                raise ValueError("All face tokens must belong to the same body.")
        return body, faces, "entity_tokens"

    if face_indices is None or len(face_indices) == 0:
        raise ValueError("face_indices is required unless face_entity_tokens are provided. Use get_body_faces first to choose explicit faces.")
    body = _body_from_name_or_token(body_name, body_entity_token)
    if not body:
        raise ValueError("body_name or body_entity_token is required unless face_entity_tokens are provided.")
    return body, _body_faces_by_indices(body, face_indices), "indices"


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
def offset_face_or_press_pull(body_name=None, face_indices=None, distance=None, name=None, use_selection=False, body_entity_token=None, face_entity_tokens=None):
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
        targeting = "selection" if use_selection else "indices"
        if use_selection:
            faces = _selected_brep_faces()
            if not faces:
                return {"error": "No selected BRep faces found."}
        else:
            body, faces, targeting = _resolve_faces(
                body_name=body_name,
                face_indices=face_indices,
                face_entity_tokens=face_entity_tokens,
                body_entity_token=body_entity_token,
            )

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
                "targeting": targeting,
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


@register_tool("extrude_existing_profile")
def extrude_existing_profile(sketch_name, distance, operation, name=None, profile_index=0, body_name=None, participant_body_names=None):
    """
    Hardened wrapper for extruding an existing sketch profile.

    Compared with extrude_feature, this reports profile counts, createInput/add
    failure stage, participant resolution, and likely recovery actions so agents
    do not fall back to raw scripts just to learn why profile reuse failed.
    """
    diagnostics = {
        "sketchName": sketch_name,
        "profileIndex": profile_index,
        "operation": operation,
        "distance": distance,
        "stage": "start",
        "profileCount": None,
        "participantBodies": [],
        "recoveryActions": [],
    }
    try:
        if not operation:
            return {"error": "operation is required and must be one of NewBody, Join, Cut, or Intersect.", "diagnostics": diagnostics}
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            diagnostics["stage"] = "resolve_sketch"
            return {"error": f"Sketch '{sketch_name}' not found.", "diagnostics": diagnostics}
        profiles = _safe_value(lambda: sketch.profiles)
        diagnostics["profileCount"] = _safe_value(lambda: profiles.count, 0) or 0
        diagnostics["isSketchVisible"] = _safe_value(lambda: sketch.isVisible)
        diagnostics["isSketchComputeDeferred"] = _safe_value(lambda: sketch.isComputeDeferred)

        diagnostics["stage"] = "resolve_profile"
        profile = _profile_by_index(sketch, profile_index)
        diagnostics["profileObjectType"] = _safe_value(lambda: profile.objectType)
        diagnostics["profileAreaPropertiesAvailable"] = bool(_safe_value(lambda: profile.areaProperties()))

        before = _design_state_snapshot(include_selections=False)
        op = _feature_operation(operation)
        component = _safe_value(lambda: sketch.parentComponent) or get_active_design().rootComponent
        extrudes = _safe_value(lambda: component.features.extrudeFeatures)
        if not extrudes:
            diagnostics["stage"] = "resolve_extrude_features"
            return {"error": "Target component does not expose extrudeFeatures.", "diagnostics": diagnostics}
        try:
            diagnostics["stage"] = "create_input"
            ext_input = extrudes.createInput(profile, op)
        except Exception as exc:
            diagnostics["recoveryActions"] = [
                "Run copy_profile_loop with outer_loop=true into a fresh sketch and retry extrude_existing_profile on that copied profile.",
                "Run offset_profile_loop only on the intended loop if reference/projection curves are polluting the source sketch.",
                "Inspect the sketch profile count and choose the intended profile_index explicitly.",
            ]
            return {"error": f"Fusion rejected the existing profile during extrude input creation: {exc}", "diagnostics": diagnostics}

        diagnostics["stage"] = "participant_bodies"
        diagnostics["participantBodies"] = _set_participant_bodies(ext_input, participant_body_names)
        diagnostics["stage"] = "set_extent"
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(distance))
        try:
            diagnostics["stage"] = "add_feature"
            extrude = extrudes.add(ext_input)
        except Exception as exc:
            diagnostics["recoveryActions"] = [
                "If this is a Cut/Join/Intersect, supply participant_body_names explicitly.",
                "If Fusion reports profile instability, copy the desired loop into a fresh sketch and extrude that profile.",
                "Run preflight_model_change and inspect_feature on nearby timeline items before retrying.",
            ]
            return {"error": f"Fusion created the extrude input but failed to add the feature: {exc}", "diagnostics": diagnostics}
        if name:
            extrude.name = name

        result_body_names = []
        bodies = _safe_value(lambda: extrude.bodies)
        for index, body in enumerate(_collection_items(bodies)):
            if body_name:
                body.name = body_name if index == 0 else f"{body_name}_{index}"
            result_body_names.append(_safe_value(lambda body=body: body.name))

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result") if before and after else None
        feature_name = _safe_value(lambda: extrude.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        diagnostics["stage"] = "complete"
        return {
            "result": {
                "featureName": feature_name,
                "sketchName": sketch.name,
                "profileIndex": int(profile_index),
                "operation": _operation_label(op),
                "distance": distance,
                "participantBodies": diagnostics["participantBodies"] or _body_names(_safe_value(lambda: extrude.participantBodies)),
                "resultBodies": result_body_names,
                "diagnostics": diagnostics,
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error extruding existing profile: {e}\n{err}")
        return {"error": f"Failed to extrude existing profile: {str(e)}", "diagnostics": diagnostics}


@register_tool("copy_profile_loop")
def copy_profile_loop(source_sketch_name, profile_index=0, loop_index=0, outer_loop=False, destination_sketch_name=None, destination_plane=None, construction=False):
    try:
        source_sketch = _find_sketch_by_name(source_sketch_name)
        if not source_sketch:
            return {"error": f"Source sketch '{source_sketch_name}' not found."}
        profile = _profile_by_index(source_sketch, profile_index)
        profile_loop, resolved_loop_index = _profile_loop_by_index(profile, loop_index=loop_index, outer_loop=outer_loop)
        loop_curves = _loop_profile_curves(profile_loop)
        entities = [_profile_curve_entity(curve) for curve in loop_curves]
        if not entities:
            return {"error": "Selected profile loop did not resolve any sketch entities."}

        before = _design_state_snapshot(include_selections=False)
        destination_sketch, created_destination = _ensure_destination_sketch(
            source_sketch,
            destination_sketch_name=destination_sketch_name,
            destination_plane=destination_plane,
        )
        copied = []
        unsupported = []
        for entity in entities:
            result = _safe_value(lambda entity=entity: destination_sketch.project(entity))
            result_items = _collection_items(result)
            if not result_items and destination_sketch == source_sketch:
                copy_method = _safe_value(lambda: destination_sketch.copy)
                if callable(copy_method):
                    result = copy_method(_object_collection([entity]))
                    result_items = _collection_items(result)
            if not result_items:
                unsupported.append(_curve_summary(entity, len(unsupported)))
                continue
            for item in result_items:
                _safe_value(lambda item=item: setattr(item, "isConstruction", bool(construction)))
                copied.append(_curve_summary(item, len(copied)))
        after = _design_state_snapshot(include_selections=False)
        if unsupported and not copied:
            return {
                "error": "Fusion did not expose project/copy support for any curve in the selected profile loop.",
                "sourceSketchName": _safe_value(lambda: source_sketch.name),
                "profileIndex": int(profile_index),
                "loopIndex": resolved_loop_index,
                "unsupportedCurves": unsupported,
            }
        return {
            "result": {
                "sourceSketchName": _safe_value(lambda: source_sketch.name),
                "destinationSketchName": _safe_value(lambda: destination_sketch.name),
                "createdDestinationSketch": bool(created_destination),
                "profileIndex": int(profile_index),
                "loopIndex": resolved_loop_index,
                "outerLoop": bool(_safe_value(lambda: profile_loop.isOuter)),
                "sourceCurveCount": len(entities),
                "copiedCurveCount": len(copied),
                "copiedCurves": copied,
                "unsupportedCurves": unsupported,
                "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
                "warnings": [
                    "Fusion projects/copies the loop curves exposed by the profile; constraints and dimensions from the source sketch are not guaranteed to copy.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error copying profile loop: {e}\n{err}")
        return {"error": f"Failed to copy profile loop: {str(e)}"}


@register_tool("create_insert_socket")
def create_insert_socket(source_sketch_name, target_body_name, insert_thickness, clearance="0 mm", mode="flush", profile_index=0, loop_index=0, outer_loop=True, work_sketch_name=None, destination_plane=None, plate_body_name=None, plate_feature_name=None, cutter_body_name=None, cutter_feature_name=None, socket_feature_name=None, socket_depth=None, cutter_profile_index=0, keep_cutter_body=False, allow_alignment_blockers=False, reason=None):
    """
    Create a removable insert plate and matching target-body socket cut.

    The workflow is intentionally structured: copy one profile loop, create a
    plate body, create a cutter body, verify broad-phase alignment, then use the
    cutter to cut the target body. If Fusion fails after creating intermediates,
    the returned recovery action points to delete_named_experiment.
    """
    diagnostics = {
        "stage": "start",
        "sourceSketchName": source_sketch_name,
        "targetBodyName": target_body_name,
        "profileIndex": profile_index,
        "loopIndex": loop_index,
        "outerLoop": bool(outer_loop),
        "createdArtifacts": [],
        "warnings": [],
        "recoveryActions": [],
    }
    try:
        reason_error = _require_reason(reason, "creating an insert plate and socket cut")
        if reason_error:
            return reason_error
        if not insert_thickness:
            return {"error": "insert_thickness is required, e.g. '2 mm'.", "diagnostics": diagnostics}
        mode_key = str(mode or "flush").strip().lower()
        if mode_key not in {"flush", "proud", "recessed"}:
            return {"error": "mode must be one of flush, proud, or recessed.", "diagnostics": diagnostics}
        if mode_key != "flush" and not socket_depth:
            diagnostics["warnings"].append("mode is proud/recessed but socket_depth was not supplied; using insert_thickness as the cut depth.")
        socket_depth = socket_depth or insert_thickness

        design = get_active_design()
        source_sketch = _find_sketch_by_name(source_sketch_name)
        if not source_sketch:
            diagnostics["stage"] = "resolve_source_sketch"
            return {"error": f"Source sketch '{source_sketch_name}' not found.", "diagnostics": diagnostics}
        target_body = _find_body_by_name(target_body_name)
        if not target_body:
            diagnostics["stage"] = "resolve_target_body"
            return {"error": f"Target body '{target_body_name}' not found.", "diagnostics": diagnostics}

        component = _safe_value(lambda: source_sketch.parentComponent) or get_active_design().rootComponent
        extrudes = _safe_value(lambda: component.features.extrudeFeatures)
        combines = _safe_value(lambda: component.features.combineFeatures)
        if not extrudes:
            return {"error": "Target component does not expose extrudeFeatures.", "diagnostics": diagnostics}
        if not combines:
            return {"error": "Target component does not expose combineFeatures.", "diagnostics": diagnostics}

        diagnostics["stage"] = "resolve_profile_loop"
        profile = _profile_by_index(source_sketch, profile_index)
        profile_loop, resolved_loop_index = _profile_loop_by_index(profile, loop_index=loop_index, outer_loop=outer_loop)
        loop_curves = _loop_profile_curves(profile_loop)
        entities = [_profile_curve_entity(curve) for curve in loop_curves]
        if not entities:
            return {"error": "Selected profile loop did not resolve any sketch entities.", "diagnostics": diagnostics}

        artifact_prefix = work_sketch_name or f"{source_sketch_name}_InsertSocket"
        work_sketch_name = work_sketch_name or f"{artifact_prefix}_Sketch"
        plate_body_name = plate_body_name or f"{artifact_prefix}_Plate"
        cutter_body_name = cutter_body_name or f"{artifact_prefix}_Cutter"
        plate_feature_name = plate_feature_name or f"{artifact_prefix}_PlateExtrude"
        cutter_feature_name = cutter_feature_name or f"{artifact_prefix}_CutterExtrude"
        socket_feature_name = socket_feature_name or f"{artifact_prefix}_SocketCut"

        before = _design_state_snapshot(include_selections=False)
        diagnostics["stage"] = "copy_loop"
        work_sketch, created_work_sketch = _ensure_destination_sketch(
            source_sketch,
            destination_sketch_name=work_sketch_name,
            destination_plane=destination_plane,
        )
        diagnostics["createdWorkSketch"] = bool(created_work_sketch)
        if created_work_sketch:
            diagnostics["createdArtifacts"].append({"kind": "sketch", "name": _safe_value(lambda: work_sketch.name)})
        copied_entities = []
        unsupported = []
        for entity in entities:
            result = _safe_value(lambda entity=entity: work_sketch.project(entity))
            result_items = _collection_items(result)
            if not result_items:
                unsupported.append(_curve_summary(entity, len(unsupported)))
            copied_entities.extend(result_items)
        diagnostics["copiedCurveCount"] = len(copied_entities)
        diagnostics["unsupportedCurves"] = unsupported
        if not copied_entities:
            return {"error": "Fusion did not project any curves from the selected profile loop.", "diagnostics": diagnostics}

        offset_items = []
        if _nonzero_length_expression(design, clearance):
            diagnostics["stage"] = "offset_clearance_loop"
            distance_cm = design.unitsManager.evaluateExpression(str(clearance), "cm")
            direction_point = _safe_value(lambda: profile.areaProperties().centroid) or adsk.core.Point3D.create(0, 0, 0)
            offset_result = work_sketch.offset(_object_collection(copied_entities), direction_point, distance_cm)
            offset_items = _collection_items(offset_result)
            diagnostics["clearanceApplied"] = bool(offset_items)
            diagnostics["offsetCurveCount"] = len(offset_items)
            if not offset_items:
                diagnostics["warnings"].append("Fusion did not return offset curves for clearance; cutter_profile_index must target the intended profile explicitly.")
        else:
            diagnostics["clearanceApplied"] = False
            diagnostics["offsetCurveCount"] = 0

        diagnostics["stage"] = "create_plate"
        plate_profile = _profile_by_index(work_sketch, 0)
        plate_input = extrudes.createInput(plate_profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        plate_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(str(insert_thickness)))
        plate_feature = extrudes.add(plate_input)
        plate_feature.name = plate_feature_name
        plate_bodies = _collection_items(_safe_value(lambda: plate_feature.bodies))
        if not plate_bodies:
            return {"error": "Plate extrusion did not return a result body.", "diagnostics": diagnostics}
        plate_body = plate_bodies[0]
        plate_body.name = plate_body_name
        diagnostics["createdArtifacts"].append({"kind": "feature", "name": plate_feature_name})
        diagnostics["createdArtifacts"].append({"kind": "body", "name": plate_body_name})

        diagnostics["stage"] = "create_cutter"
        cutter_profile = _profile_by_index(work_sketch, cutter_profile_index)
        cutter_input = extrudes.createInput(cutter_profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        cutter_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(str(socket_depth)))
        cutter_feature = extrudes.add(cutter_input)
        cutter_feature.name = cutter_feature_name
        cutter_bodies = _collection_items(_safe_value(lambda: cutter_feature.bodies))
        if not cutter_bodies:
            return {"error": "Cutter extrusion did not return a result body.", "diagnostics": diagnostics}
        cutter_body = cutter_bodies[0]
        cutter_body.name = cutter_body_name
        diagnostics["createdArtifacts"].append({"kind": "feature", "name": cutter_feature_name})
        diagnostics["createdArtifacts"].append({"kind": "body", "name": cutter_body_name})

        diagnostics["stage"] = "verify_alignment"
        try:
            from .inspection import verify_insert_alignment
        except ImportError:
            from inspection import verify_insert_alignment
        alignment = verify_insert_alignment(
            plate_body_name=plate_body_name,
            socket_body_name=cutter_body_name,
            thickness_axis="z",
            expected_plate_thickness=str(insert_thickness),
            flush_mode=mode_key,
        )
        alignment_result = alignment.get("result") if isinstance(alignment, dict) else None
        if alignment_result and not alignment_result.get("okToExport", False) and not allow_alignment_blockers:
            diagnostics["recoveryActions"] = [
                f"Call delete_named_experiment with prefixes='{artifact_prefix}' and confirm_delete=true if the generated plate/cutter artifacts should be removed.",
                "Inspect verify_insert_alignment blockingReasons before retrying with explicit socket_depth, cutter_profile_index, or clearance.",
            ]
            return {
                "error": "Insert socket alignment verification failed before cutting the target body.",
                "alignmentVerification": alignment_result,
                "diagnostics": diagnostics,
            }

        diagnostics["stage"] = "combine_cut"
        tool_collection = _object_collection([cutter_body])
        combine_input = combines.createInput(target_body, tool_collection)
        combine_input.operation = adsk.fusion.FeatureOperations.CutFeatureOperation
        combine_input.isKeepToolBodies = bool(keep_cutter_body)
        combine_feature = combines.add(combine_input)
        combine_feature.name = socket_feature_name
        diagnostics["createdArtifacts"].append({"kind": "feature", "name": socket_feature_name})
        if not keep_cutter_body:
            diagnostics["cutterCleanup"] = "combine_cut_consumed_tool_body"

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result") if before and after else None
        diagnostics["stage"] = "complete"
        return {
            "result": {
                "created": True,
                "sourceSketchName": _safe_value(lambda: source_sketch.name),
                "workSketchName": _safe_value(lambda: work_sketch.name),
                "targetBodyName": target_body_name,
                "plateBodyName": plate_body_name,
                "cutterBodyName": cutter_body_name,
                "plateFeatureName": plate_feature_name,
                "cutterFeatureName": cutter_feature_name,
                "socketFeatureName": socket_feature_name,
                "insertThickness": str(insert_thickness),
                "socketDepth": str(socket_depth),
                "clearance": str(clearance),
                "mode": mode_key,
                "keepCutterBody": bool(keep_cutter_body),
                "loopIndex": resolved_loop_index,
                "alignmentVerification": alignment_result,
                "diagnostics": diagnostics,
                "stateComparison": comparison,
                "warnings": diagnostics["warnings"] + [
                    "Profile-loop constraints and dimensions are not guaranteed to copy into the generated work sketch.",
                    "If clearance creates multiple work-sketch profiles, set cutter_profile_index explicitly after inspecting the work sketch.",
                ],
            }
        }
    except Exception as e:
        diagnostics["recoveryActions"] = [
            "Run inspect_sketch on the generated work sketch and inspect_feature on generated features before retrying.",
            "Use delete_named_experiment with the generated artifact prefix to clean up partial plate/cutter/socket attempts.",
        ]
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating insert socket: {e}\n{err}")
        return {"error": f"Failed to create insert socket: {str(e)}", "diagnostics": diagnostics}


@register_tool("offset_profile_loop")
def offset_profile_loop(sketch_name, profile_index=0, loop_index=0, outer_loop=False, offset_distance=None, construction=False):
    try:
        if not offset_distance:
            return {"error": "offset_distance is required, e.g. '0.2 mm' or '-0.15 mm'."}
        design = get_active_design()
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        profile = _profile_by_index(sketch, profile_index)
        profile_loop, resolved_loop_index = _profile_loop_by_index(profile, loop_index=loop_index, outer_loop=outer_loop)
        loop_curves = _loop_profile_curves(profile_loop)
        entities = [_profile_curve_entity(curve) for curve in loop_curves]
        if not entities:
            return {"error": "Selected profile loop did not resolve any sketch entities."}
        distance_cm = design.unitsManager.evaluateExpression(str(offset_distance), "cm")
        direction_point = _safe_value(lambda: profile.areaProperties().centroid)
        if not direction_point:
            direction_point = adsk.core.Point3D.create(0, 0, 0)

        before = _design_state_snapshot(include_selections=False)
        offset_result = sketch.offset(_object_collection(entities), direction_point, distance_cm)
        offset_items = _collection_items(offset_result)
        for item in offset_items:
            _safe_value(lambda item=item: setattr(item, "isConstruction", bool(construction)))
        after = _design_state_snapshot(include_selections=False)
        return {
            "result": {
                "sketchName": _safe_value(lambda: sketch.name),
                "profileIndex": int(profile_index),
                "loopIndex": resolved_loop_index,
                "outerLoop": bool(_safe_value(lambda: profile_loop.isOuter)),
                "offsetDistance": str(offset_distance),
                "sourceCurveCount": len(entities),
                "offsetCurveCount": len(offset_items),
                "offsetCurves": [_curve_summary(item, index) for index, item in enumerate(offset_items)],
                "stateComparison": compare_design_state(before, after).get("result") if before and after else None,
                "warnings": [
                    "Only curves from the selected profile loop were offset; unrelated projected/reference curves in the sketch were not included.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error offsetting profile loop: {e}\n{err}")
        return {"error": f"Failed to offset profile loop: {str(e)}"}


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
        if revolves is None:
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


@register_tool("loft_feature")
def loft_feature(sections, operation=None, name=None, body_name=None, participant_body_names=None):
    """
    Create a solid loft from an ordered list of named sketch profiles.

    Section ordering is deliberately explicit. Rails, centerlines, and surface
    lofts are separate behavior and should not be inferred by this first solid
    loft tool.
    """
    try:
        if not operation:
            return {"error": "operation is required and must be one of NewBody, Join, Cut, or Intersect."}

        resolved_sections = _profiles_from_sections(sections)
        first_sketch = resolved_sections[0]["sketch"]
        component = _safe_value(lambda: first_sketch.parentComponent) or get_active_design().rootComponent
        lofts = _safe_value(lambda: component.features.loftFeatures)
        if lofts is None:
            return {"error": "This Fusion runtime does not expose loftFeatures for API-created loft features."}

        before = _design_state_snapshot(include_selections=False)
        op = _feature_operation(operation)
        loft_input = lofts.createInput(op)
        for section in resolved_sections:
            loft_input.loftSections.add(section["profile"])
        participants = _set_participant_bodies(loft_input, participant_body_names)
        loft = lofts.add(loft_input)
        if name:
            loft.name = name

        result_body_names = []
        bodies = _safe_value(lambda: loft.bodies)
        for index, body in enumerate(_collection_items(bodies)):
            if body_name:
                body.name = body_name if index == 0 else f"{body_name}_{index}"
            result_body_names.append(_safe_value(lambda body=body: body.name))

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: loft.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "sections": [
                    {
                        "sketchName": section["sketch"].name,
                        "profileIndex": section["profileIndex"],
                    }
                    for section in resolved_sections
                ],
                "operation": _operation_label(op),
                "participantBodies": participants or _body_names(_safe_value(lambda: loft.participantBodies)),
                "resultBodies": result_body_names,
                "warnings": [
                    "Loft sections are consumed in the supplied order.",
                    "This tool creates solid/profile lofts only; rails, centerlines, and surface lofts are not yet implemented.",
                ],
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating loft feature: {e}\n{err}")
        return {"error": f"Failed to create loft feature: {str(e)}"}


@register_tool("sweep_feature")
def sweep_feature(profile_sketch_name, path_sketch_name, operation=None, name=None, profile_index=0, path_curve_index=0, chain_path=False, body_name=None, participant_body_names=None):
    """
    Create a solid sweep from a named sketch profile along an explicit path curve.

    Path selection is index-based so callers can inspect the path sketch first
    and avoid depending on whatever happens to be selected in the UI.
    """
    try:
        if not operation:
            return {"error": "operation is required and must be one of NewBody, Join, Cut, or Intersect."}
        profile_sketch = _find_sketch_by_name(profile_sketch_name)
        if not profile_sketch:
            return {"error": f"Profile sketch '{profile_sketch_name}' not found."}
        path_sketch = _find_sketch_by_name(path_sketch_name)
        if not path_sketch:
            return {"error": f"Path sketch '{path_sketch_name}' not found."}

        before = _design_state_snapshot(include_selections=False)
        profile = _profile_by_index(profile_sketch, profile_index)
        path_group, path_curve = _sketch_curve_by_index(path_sketch, path_curve_index)
        op = _feature_operation(operation)
        component = _safe_value(lambda: profile_sketch.parentComponent) or get_active_design().rootComponent
        sweeps = _safe_value(lambda: component.features.sweepFeatures)
        if sweeps is None:
            return {"error": "This Fusion runtime does not expose sweepFeatures for API-created sweep features."}
        create_path = _safe_value(lambda: component.features.createPath)
        if not create_path:
            return {"error": "This Fusion runtime does not expose features.createPath for API-created sweep paths."}
        path = component.features.createPath(path_curve, bool(chain_path))
        sweep_input = sweeps.createInput(profile, path, op)
        participants = _set_participant_bodies(sweep_input, participant_body_names)
        sweep = sweeps.add(sweep_input)
        if name:
            sweep.name = name

        result_body_names = []
        bodies = _safe_value(lambda: sweep.bodies)
        for index, body in enumerate(_collection_items(bodies)):
            if body_name:
                body.name = body_name if index == 0 else f"{body_name}_{index}"
            result_body_names.append(_safe_value(lambda body=body: body.name))

        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        feature_name = _safe_value(lambda: sweep.name) or name
        inspected = inspect_feature(feature_name).get("result") if feature_name else None
        return {
            "result": {
                "featureName": feature_name,
                "profileSketchName": profile_sketch.name,
                "profileIndex": int(profile_index),
                "pathSketchName": path_sketch.name,
                "pathCurveIndex": int(path_curve_index),
                "pathCurveGroup": path_group,
                "chainPath": bool(chain_path),
                "operation": _operation_label(op),
                "participantBodies": participants or _body_names(_safe_value(lambda: sweep.participantBodies)),
                "resultBodies": result_body_names,
                "warnings": [
                    "Use inspect_sketch on the path sketch before choosing path_curve_index.",
                    "This tool creates a single-path solid sweep; guide rails and surface sweeps are not yet implemented.",
                ],
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating sweep feature: {e}\n{err}")
        return {"error": f"Failed to create sweep feature: {str(e)}"}


@register_tool("fillet_feature")
def fillet_feature(body_name=None, edge_indices=None, radius=None, name=None, tangent_chain=True, body_entity_token=None, edge_entity_tokens=None):
    """
    Create a constant-radius fillet on selected edges of a named body.

    Edge indices are required so callers make the target selection explicit.
    Use inspect/selection tools first when edge identity is uncertain.
    """
    try:
        if not radius:
            return {"error": "radius is required, e.g. '1 mm'."}

        body, edges, targeting = _resolve_edges(
            body_name=body_name,
            edge_indices=edge_indices,
            edge_entity_tokens=edge_entity_tokens,
            body_entity_token=body_entity_token,
        )
        before = _design_state_snapshot(include_selections=False)
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
                "edgeIndices": [
                    _edge_body_index(body, edge)
                    for edge in edges
                ],
                "edges": _edge_refs(edges),
                "radius": radius,
                "tangentChain": bool(tangent_chain),
                "targeting": targeting,
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating fillet feature: {e}\n{err}")
        return {"error": f"Failed to create fillet feature: {str(e)}"}


@register_tool("chamfer_feature")
def chamfer_feature(body_name=None, edge_indices=None, distance=None, name=None, tangent_chain=True, body_entity_token=None, edge_entity_tokens=None):
    """
    Create an equal-distance chamfer on selected edges of a named body.

    Edge indices are required for the same reason as fillets: chamfering the
    wrong edge is easy to miss visually and hard to diagnose after export.
    """
    try:
        if not distance:
            return {"error": "distance is required, e.g. '1 mm'."}

        body, edges, targeting = _resolve_edges(
            body_name=body_name,
            edge_indices=edge_indices,
            edge_entity_tokens=edge_entity_tokens,
            body_entity_token=body_entity_token,
        )
        before = _design_state_snapshot(include_selections=False)
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
                "edgeIndices": [
                    _edge_body_index(body, edge)
                    for edge in edges
                ],
                "edges": _edge_refs(edges),
                "distance": distance,
                "chamferType": "EqualDistance",
                "tangentChain": bool(tangent_chain),
                "targeting": targeting,
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating chamfer feature: {e}\n{err}")
        return {"error": f"Failed to create chamfer feature: {str(e)}"}


@register_tool("shell_body")
def shell_body(body_name=None, thickness=None, open_face_indices=None, name=None, thickness_side="inside", outside_thickness=None, tangent_chain=True, body_entity_token=None, open_face_entity_tokens=None):
    """
    Shell a named solid body with explicit wall thickness.

    If open_face_indices is supplied, those faces are removed/opened by the
    shell feature. Use get_body_faces first when face identity is uncertain.
    """
    try:
        if not thickness:
            return {"error": "thickness is required, e.g. '2 mm'."}
        body = _body_from_name_or_token(body_name, body_entity_token)
        if not body and open_face_entity_tokens:
            body, _faces, _targeting = _resolve_faces(face_entity_tokens=open_face_entity_tokens)
        if not body:
            return {"error": "body_name or body_entity_token is required unless open_face_entity_tokens are provided."}

        before = _design_state_snapshot(include_selections=False)
        input_entities = adsk.core.ObjectCollection.create()
        opened_faces = []
        targeting = "body"
        if open_face_entity_tokens:
            resolved_body, opened_faces, targeting = _resolve_faces(
                body_name=body_name,
                face_indices=open_face_indices,
                face_entity_tokens=open_face_entity_tokens,
                body_entity_token=body_entity_token,
            )
            body = resolved_body or body
            for face in opened_faces:
                input_entities.add(face)
        elif open_face_indices:
            opened_faces = _body_faces_by_indices(body, open_face_indices)
            targeting = "indices"
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
                "openFaceIndices": [
                    _face_body_index(body, face)
                    for face in opened_faces
                ],
                "openedFaces": [
                    _face_ref(body, face, _face_body_index(body, face))
                    for face in opened_faces
                ],
                "tangentChain": bool(tangent_chain),
                "targeting": targeting,
                "feature": inspected,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating shell feature: {e}\n{err}")
        return {"error": f"Failed to create shell feature: {str(e)}"}
