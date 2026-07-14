"""
Typed sketch creation and sketch-geometry tools.
"""

import traceback

import adsk.core, adsk.fusion

from . import register_tool
from .inspection import (
    _circle_to_dict,
    _design_state_snapshot,
    _find_component_context_by_name,
    _find_sketch_by_name,
    _line_to_dict,
    _safe_value,
    _sketch_coordinate_system,
    _collection_items,
    compare_design_state,
    get_active_design,
)


def _point3d(value, default_z=0.0):
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
        raise ValueError("Point must be [x, y] or [x, y, z].")
    z = value[2] if len(value) == 3 else default_z
    return adsk.core.Point3D.create(float(value[0]), float(value[1]), float(z))


def _resolve_plane(component, plane):
    plane_name = (plane or "xy").lower()
    if plane_name in ("xy", "xyconstructionplane"):
        return component.xYConstructionPlane
    if plane_name in ("xz", "xzconstructionplane"):
        return component.xZConstructionPlane
    if plane_name in ("yz", "yzconstructionplane"):
        return component.yZConstructionPlane

    construction_planes = _safe_value(lambda: component.constructionPlanes)
    for construction_plane in _collection_items(construction_planes):
        if _safe_value(lambda construction_plane=construction_plane: construction_plane.name) == plane:
            return construction_plane
    raise ValueError(f"Construction plane '{plane}' not found in component '{component.name}'.")


def _capture_design_state():
    return _safe_value(lambda: _design_state_snapshot(include_selections=False))


def _compare_after_mutation(before):
    if not before:
        return None
    after = _capture_design_state()
    if not after:
        return None
    return _safe_value(lambda: compare_design_state(before, after).get("result"))


def _sketch_result(sketch, action, extra=None, state_comparison=None):
    result = {
        "action": action,
        "sketchName": _safe_value(lambda: sketch.name),
        "componentName": _safe_value(lambda: sketch.parentComponent.name),
        "coordinateSystem": _sketch_coordinate_system(sketch),
    }
    if extra:
        result.update(extra)
    if state_comparison is not None:
        result["stateComparison"] = state_comparison
    return {"result": result}


def _find_body_by_name(root, name):
    for body in _collection_items(_safe_value(lambda: root.bRepBodies)):
        if _safe_value(lambda body=body: body.name) == name:
            return body
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            if _safe_value(lambda body=body: body.name) == name:
                return body
    return None


def _find_projection_entity(design, entity_name=None, entity_token=None):
    root = design.rootComponent
    if entity_token:
        found = _safe_value(lambda: design.findEntityByToken(entity_token))
        if isinstance(found, (list, tuple)):
            if len(found) >= 2 and isinstance(found[0], bool):
                found = found[1]
            else:
                found = found[0] if found else None
            if isinstance(found, (list, tuple)):
                found = found[0] if found else None
        elif hasattr(found, "count") and hasattr(found, "item"):
            found = found.item(0) if found.count > 0 else None
        if found:
            return found
    if entity_name:
        body = _find_body_by_name(root, entity_name)
        if body:
            return body
        for sketch in _collection_items(_safe_value(lambda: root.sketches)):
            if _safe_value(lambda sketch=sketch: sketch.name) == entity_name:
                return sketch
        for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
            component = _safe_value(lambda occ=occ: occ.component)
            for sketch in _collection_items(_safe_value(lambda component=component: component.sketches)):
                if _safe_value(lambda sketch=sketch: sketch.name) == entity_name:
                    return sketch
    return None


def _find_sketch_curve(sketch_name, curve_type="lines", curve_index=0):
    sketch = _find_sketch_by_name(sketch_name)
    if not sketch:
        raise ValueError(f"Source sketch '{sketch_name}' not found.")
    curves = sketch.sketchCurves
    curve_map = {
        "line": "sketchLines",
        "lines": "sketchLines",
        "circle": "sketchCircles",
        "circles": "sketchCircles",
        "arc": "sketchArcs",
        "arcs": "sketchArcs",
        "ellipse": "sketchEllipses",
        "ellipses": "sketchEllipses",
        "fittedSpline": "sketchFittedSplines",
        "fittedSplines": "sketchFittedSplines",
        "fixedSpline": "sketchFixedSplines",
        "fixedSplines": "sketchFixedSplines",
        "conic": "sketchConicCurves",
        "conics": "sketchConicCurves",
    }
    attr = curve_map.get(curve_type)
    if not attr:
        raise ValueError(f"Unsupported curve_type '{curve_type}'.")
    collection = _safe_value(lambda: getattr(curves, attr))
    index = int(curve_index)
    if index < 0 or index >= _safe_value(lambda: collection.count, 0):
        raise ValueError(f"Curve index {index} is out of range for {curve_type}.")
    return collection.item(index)


@register_tool("create_sketch")
def create_sketch(name, plane="xy", component="root"):
    try:
        design = get_active_design()
        target_component, _occurrence = _find_component_context_by_name(component)
        if not target_component:
            return {"error": f"Component or occurrence '{component}' not found."}
        before = _capture_design_state()
        sketch = target_component.sketches.add(_resolve_plane(target_component, plane))
        sketch.name = name
        return _sketch_result(sketch, "created", state_comparison=_compare_after_mutation(before))
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating sketch: {e}\n{err}")
        return {"error": f"Failed to create sketch: {str(e)}"}


@register_tool("draw_line")
def draw_line(sketch_name, start, end, name=None, construction=False):
    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        before = _capture_design_state()
        line = sketch.sketchCurves.sketchLines.addByTwoPoints(_point3d(start), _point3d(end))
        if name:
            _safe_value(lambda: setattr(line, "name", name))
        _safe_value(lambda: setattr(line, "isConstruction", bool(construction)))
        return _sketch_result(
            sketch,
            "lineCreated",
            {"line": _line_to_dict(line, 0)},
            state_comparison=_compare_after_mutation(before),
        )
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error drawing line: {e}\n{err}")
        return {"error": f"Failed to draw line: {str(e)}"}


@register_tool("draw_rectangle")
def draw_rectangle(sketch_name, corner1=None, corner2=None, center=None, width=None, height=None, name_prefix=None, construction=False):
    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        before = _capture_design_state()
        if corner1 is None or corner2 is None:
            if center is None or width is None or height is None:
                return {"error": "Provide corner1/corner2 or center/width/height."}
            design = get_active_design()
            width_value = design.unitsManager.evaluateExpression(str(width), "cm") if isinstance(width, str) else float(width)
            height_value = design.unitsManager.evaluateExpression(str(height), "cm") if isinstance(height, str) else float(height)
            center_point = _point3d(center)
            corner1 = [center_point.x - width_value / 2.0, center_point.y - height_value / 2.0, 0]
            corner2 = [center_point.x + width_value / 2.0, center_point.y + height_value / 2.0, 0]

        lines = sketch.sketchCurves.sketchLines.addTwoPointRectangle(_point3d(corner1), _point3d(corner2))
        created = []
        for index, line in enumerate(_collection_items(lines)):
            if name_prefix:
                _safe_value(lambda line=line, index=index: setattr(line, "name", f"{name_prefix}_{index}"))
            _safe_value(lambda line=line: setattr(line, "isConstruction", bool(construction)))
            created.append(_line_to_dict(line, index))
        return _sketch_result(
            sketch,
            "rectangleCreated",
            {"lines": created},
            state_comparison=_compare_after_mutation(before),
        )
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error drawing rectangle: {e}\n{err}")
        return {"error": f"Failed to draw rectangle: {str(e)}"}


@register_tool("draw_circle")
def draw_circle(sketch_name, center, radius, name=None, construction=False):
    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        design = get_active_design()
        radius_value = design.unitsManager.evaluateExpression(str(radius), "cm") if isinstance(radius, str) else float(radius)
        before = _capture_design_state()
        circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(_point3d(center), radius_value)
        if name:
            _safe_value(lambda: setattr(circle, "name", name))
        _safe_value(lambda: setattr(circle, "isConstruction", bool(construction)))
        return _sketch_result(
            sketch,
            "circleCreated",
            {"circle": _circle_to_dict(circle, 0)},
            state_comparison=_compare_after_mutation(before),
        )
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error drawing circle: {e}\n{err}")
        return {"error": f"Failed to draw circle: {str(e)}"}


@register_tool("project_geometry")
def project_geometry(sketch_name, entity_name=None, entity_token=None, use_selection=False, selection_indices=None, source_sketch_name=None, curve_type="lines", curve_index=0):
    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        design = get_active_design()
        before = _capture_design_state()
        entities = []
        if use_selection:
            selections = _safe_value(lambda: adsk.core.Application.get().userInterface.activeSelections)
            selection_count = _safe_value(lambda: selections.count, 0) or 0
            indices = selection_indices if selection_indices is not None else list(range(selection_count))
            for index in indices:
                if 0 <= index < selection_count:
                    entity = _safe_value(lambda index=index: selections.item(index).entity)
                    if entity:
                        entities.append(entity)
        elif source_sketch_name:
            entities.append(_find_sketch_curve(source_sketch_name, curve_type, curve_index))
        else:
            entity = _find_projection_entity(design, entity_name=entity_name, entity_token=entity_token)
            if entity:
                entities.append(entity)

        if not entities:
            return {"error": "No projection entity found. Provide entity_name/entity_token or use_selection=true."}

        projected_count = 0
        projected = []
        for entity in entities:
            result = sketch.project(entity)
            result_items = _collection_items(result)
            projected_count += len(result_items)
            projected.extend({
                "objectType": _safe_value(lambda item=item: item.objectType),
                "name": _safe_value(lambda item=item: item.name),
                "entityToken": _safe_value(lambda item=item: item.entityToken),
            } for item in result_items)
        return _sketch_result(sketch, "geometryProjected", {
            "projectedCount": projected_count,
            "projected": projected,
        }, state_comparison=_compare_after_mutation(before))
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error projecting geometry: {e}\n{err}")
        return {"error": f"Failed to project geometry: {str(e)}"}
