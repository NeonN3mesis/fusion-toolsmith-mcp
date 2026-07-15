"""
Parametric modeling and parameter management tools.
Includes support for parametric box, cylinder, and coil creation.
"""

import adsk.core, adsk.fusion
import math
import os
import traceback
from . import register_tool
from .inspection import _design_state_snapshot, assess_change_impact, compare_design_state, get_active_design, get_feature_dependencies

def _operation(value):
    mapping = {
        "newbody": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "new_body": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
        "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
    }
    key = (value or "new_body").replace(" ", "").lower()
    if key not in mapping:
        raise ValueError("operation must be one of new_body, join, cut, or intersect.")
    return mapping[key]


def _require_reason(reason, operation):
    if not isinstance(reason, str) or not reason.strip():
        return {"error": f"reason is required before {operation}. State why this model change is intentional."}
    return None


def _capture_design_state():
    try:
        return _design_state_snapshot(include_selections=False)
    except Exception:
        return None


def _compare_after_mutation(before):
    if not before:
        return None
    after = _capture_design_state()
    if not after:
        return None
    try:
        return compare_design_state(before, after).get("result")
    except Exception:
        return None


def _find_timeline_item(timeline, name=None, index=None):
    if index is not None:
        try:
            idx = int(index)
            if 0 <= idx < timeline.count:
                return timeline.item(idx)
        except (TypeError, ValueError):
            pass

    if name:
        for i in range(timeline.count):
            item = timeline.item(i)
            if item.name == name:
                return item
    return None


def _downstream_dependency_report(feature_name):
    if not feature_name:
        return {"likelyDownstreamConsumers": [], "bestEffort": True}
    dependencies = get_feature_dependencies(feature_name)
    if "error" in dependencies:
        return {"error": dependencies["error"], "likelyDownstreamConsumers": [], "bestEffort": True}
    return dependencies.get("result") or {}


def _has_downstream_consumers(dependency_report):
    return bool((dependency_report or {}).get("likelyDownstreamConsumers") or [])


def _impact_report(feature_name, change_type):
    impact = assess_change_impact(feature_name, change_type=change_type)
    if "error" in impact:
        return {"error": impact["error"], "okToProceed": False, "riskLevel": "unknown"}
    return impact.get("result") or {}


@register_tool("create_parametric_feature")
def create_parametric_feature(feature_type, parameters):
    if not isinstance(parameters, dict):
        parameters = {}
    if feature_type != "sketch":
        return {
            "error": (
                f"Unsupported parametric feature type '{feature_type}'. "
                "Use create_box, create_cylinder, create_coil, create_sketch_offset, "
                "or another structured MCP tool. Use run_fusion_script only as an explicitly justified last resort."
            )
        }
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = parameters.get("name", "AutoSketch")
    return {
        "result": {
            "message": f"Created sketch {sketch.name}",
            "sketchName": sketch.name,
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_box")
def create_box(name="Box", base_plane="xy", length="5 cm", width="5 cm", height="5 cm", x_offset="0 cm", z_offset="0 cm", operation="new_body"):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()
    
    # 1. Resolve base plane
    plane = root.xYConstructionPlane
    if base_plane.lower() in ["xz", "xZConstructionPlane"]:
        plane = root.xZConstructionPlane
    elif base_plane.lower() in ["yz", "yZConstructionPlane"]:
        plane = root.yZConstructionPlane
        
    # 2. Create sketch
    sketch = root.sketches.add(plane)
    sketch.name = f"{name}_Sketch"
    
    # 3. Draw rectangle on sketch
    val_l = design.unitsManager.evaluateExpression(length, "cm")
    val_w = design.unitsManager.evaluateExpression(width, "cm")
    val_x = design.unitsManager.evaluateExpression(x_offset, "cm")
    val_z = design.unitsManager.evaluateExpression(z_offset, "cm")
    
    x1 = val_x - val_l/2.0
    z1 = val_z - val_w/2.0
    x2 = val_x + val_l/2.0
    z2 = val_z + val_w/2.0
    
    p1 = adsk.core.Point3D.create(x1, z1, 0)
    p2 = adsk.core.Point3D.create(x2, z2, 0)
    
    rect_lines = sketch.sketchCurves.sketchLines.addTwoPointRectangle(p1, p2)
    
    # 4. Extrude
    profile = sketch.profiles.item(0)
    extrudes = root.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, _operation(operation))
    
    ext_dist = adsk.core.ValueInput.createByString(height)
    ext_input.setDistanceExtent(False, ext_dist)
    
    extrude = extrudes.add(ext_input)
    extrude.name = name
    
    if extrude.bodies.count > 0:
        extrude.bodies.item(0).name = name
        
    return {
        "result": {
            "message": f"Successfully created parametric box '{name}' of height {height}",
            "featureName": extrude.name,
            "sketchName": sketch.name,
            "bodyName": name if extrude.bodies.count > 0 else None,
            "operation": operation,
            "height": height,
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_cylinder")
def create_cylinder(name="Cylinder", base_plane="xy", radius="2.5 cm", height="5 cm", x_offset="0 cm", z_offset="0 cm", operation="new_body"):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()
    
    plane = root.xYConstructionPlane
    if base_plane.lower() in ["xz", "xZConstructionPlane"]:
        plane = root.xZConstructionPlane
    elif base_plane.lower() in ["yz", "yZConstructionPlane"]:
        plane = root.yZConstructionPlane
        
    sketch = root.sketches.add(plane)
    sketch.name = f"{name}_Sketch"
    
    val_r = design.unitsManager.evaluateExpression(radius, "cm")
    val_x = design.unitsManager.evaluateExpression(x_offset, "cm")
    val_z = design.unitsManager.evaluateExpression(z_offset, "cm")
    
    center = adsk.core.Point3D.create(val_x, val_z, 0)
    circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center, val_r)
    
    profile = sketch.profiles.item(0)
    
    extrudes = root.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, _operation(operation))
    
    ext_dist = adsk.core.ValueInput.createByString(height)
    ext_input.setDistanceExtent(False, ext_dist)
    
    extrude = extrudes.add(ext_input)
    extrude.name = name
    
    if extrude.bodies.count > 0:
        extrude.bodies.item(0).name = name
        
    return {
        "result": {
            "message": f"Successfully created parametric cylinder '{name}' of height {height}",
            "featureName": extrude.name,
            "sketchName": sketch.name,
            "bodyName": name if extrude.bodies.count > 0 else None,
            "operation": operation,
            "height": height,
            "radius": radius,
            "stateComparison": _compare_after_mutation(before),
        }
    }


# --- Coil Creation Implementation from AppData ---

def _value(expression):
    if isinstance(expression, (int, float)):
        return adsk.core.ValueInput.createByReal(float(expression))
    return adsk.core.ValueInput.createByString(str(expression))

def _real_length(design, expression):
    if isinstance(expression, (int, float)):
        return float(expression)
    units = design.unitsManager.defaultLengthUnits
    value = design.unitsManager.evaluateExpression(str(expression), units)
    if value is None:
        raise ValueError(f"Could not evaluate length expression: {expression}")
    return float(value)

def _base_plane(root, base_plane):
    plane_name = (base_plane or "xy").lower()
    if plane_name in ("xz", "xzconstructionplane"):
        return root.xZConstructionPlane
    if plane_name in ("yz", "yzconstructionplane"):
        return root.yZConstructionPlane
    return root.xYConstructionPlane

def _point_on_sketch(u, v):
    return adsk.core.Point3D.create(float(u), float(v), 0)

def _find_body(root, body_name):
    if not body_name:
        return None
    for component in _all_components(root):
        for body in component.bRepBodies:
            if getattr(body, "name", None) == body_name:
                return body
    return None

def _normalize_name_list(names):
    if names is None:
        return []
    if isinstance(names, str):
        return [names]
    return [str(name) for name in names]

def _collection_add(collection, entity):
    try:
        collection.add(entity)
    except AttributeError:
        collection.append(entity)

def _collection_names(collection):
    names = []
    try:
        count = collection.count
        for index in range(count):
            names.append(_safe_name(collection.item(index)))
        return [name for name in names if name]
    except Exception:
        pass
    for item in collection or []:
        name = _safe_name(item)
        if name:
            names.append(name)
    return names

def _find_feature_entity(design, feature_name):
    if not feature_name:
        return None
    timeline = getattr(design, "timeline", None)
    if not timeline:
        return None
    for index in range(timeline.count):
        item = timeline.item(index)
        entity = getattr(item, "entity", None)
        if getattr(entity, "name", None) == feature_name or getattr(item, "name", None) == feature_name:
            return entity
    return None

def _entity_component(entity):
    component = getattr(entity, "parentComponent", None)
    if component:
        return component
    body = getattr(entity, "body", None)
    if body:
        return getattr(body, "parentComponent", None)
    return None

def _find_named_axis(root, name):
    if not name:
        return None, None
    key = str(name).lower()
    standard = {
        "x": getattr(root, "xConstructionAxis", None),
        "xconstructionaxis": getattr(root, "xConstructionAxis", None),
        "y": getattr(root, "yConstructionAxis", None),
        "yconstructionaxis": getattr(root, "yConstructionAxis", None),
        "z": getattr(root, "zConstructionAxis", None),
        "zconstructionaxis": getattr(root, "zConstructionAxis", None),
    }
    if key in standard and standard[key]:
        return standard[key], root
    for component in _all_components(root):
        for axis in getattr(component, "constructionAxes", []) or []:
            if getattr(axis, "name", None) == name:
                return axis, component
    return None, None

def _selected_axis():
    app = adsk.core.Application.get()
    ui = app.userInterface
    if ui.activeSelections.count < 1:
        return None, None
    entity = ui.activeSelections.item(0).entity
    axis = adsk.fusion.ConstructionAxis.cast(entity)
    if axis:
        return axis, axis.parentComponent
    edge = adsk.fusion.BRepEdge.cast(entity)
    if edge:
        return edge, edge.body.parentComponent
    return None, None

def _pattern_compute_option(value):
    options = getattr(adsk.fusion, "PatternComputeOptions", None)
    if not options:
        return None
    key = (value or "optimized").replace("_", "").replace(" ", "").lower()
    mapping = {
        "optimized": "OptimizedPatternCompute",
        "identical": "IdenticalPatternCompute",
        "adjust": "AdjustPatternCompute",
    }
    attr = mapping.get(key, "OptimizedPatternCompute")
    return getattr(options, attr, None)

def _pattern_distance_type(value):
    distance_types = getattr(adsk.fusion, "PatternDistanceType", None)
    if not distance_types:
        return None
    key = (value or "spacing").replace("_", "").replace(" ", "").lower()
    attr = "ExtentPatternDistanceType" if key == "extent" else "SpacingPatternDistanceType"
    return getattr(distance_types, attr, None)

def _set_participant_body(ext_input, body):
    if not body:
        return
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass

def _cut_depth_expression(depth, cut_direction):
    text = str(depth)
    if (cut_direction or "positive").lower() == "negative" and not text.strip().startswith("-"):
        return f"-({text})"
    return text

def _hole_pattern_points(design, points=None, pattern_type="explicit", origin=None, spacing=None, count=None, center=None, radius=None, start_angle_deg=0, total_angle_deg=360):
    pattern = (pattern_type or "explicit").lower()
    generated = []
    if pattern == "explicit":
        if not isinstance(points, list) or not points:
            raise ValueError("points must be a non-empty list of [x, y] length-expression pairs for explicit hole patterns.")
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("Each point must be [x, y] using Fusion length expressions, e.g. ['10 mm', '5 mm'].")
            generated.append((_real_length(design, point[0]), _real_length(design, point[1]), [point[0], point[1]]))
        return generated

    if pattern == "rectangular":
        if not isinstance(count, (list, tuple)) or len(count) != 2:
            raise ValueError("rectangular pattern requires count=[columns, rows].")
        if not isinstance(spacing, (list, tuple)) or len(spacing) != 2:
            raise ValueError("rectangular pattern requires spacing=[x_spacing, y_spacing].")
        origin = origin or ["0 mm", "0 mm"]
        if not isinstance(origin, (list, tuple)) or len(origin) != 2:
            raise ValueError("rectangular pattern origin must be [x, y].")
        columns = int(count[0])
        rows = int(count[1])
        if columns <= 0 or rows <= 0:
            raise ValueError("rectangular pattern count values must be positive.")
        origin_x = _real_length(design, origin[0])
        origin_y = _real_length(design, origin[1])
        spacing_x = _real_length(design, spacing[0])
        spacing_y = _real_length(design, spacing[1])
        for row in range(rows):
            for column in range(columns):
                generated.append((origin_x + column * spacing_x, origin_y + row * spacing_y, [origin[0], origin[1], column, row]))
        return generated

    if pattern == "circular":
        if count is None:
            raise ValueError("circular pattern requires count.")
        count_value = int(count if not isinstance(count, (list, tuple)) else count[0])
        if count_value <= 0:
            raise ValueError("circular pattern count must be positive.")
        center = center or ["0 mm", "0 mm"]
        if not isinstance(center, (list, tuple)) or len(center) != 2:
            raise ValueError("circular pattern center must be [x, y].")
        if radius is None:
            raise ValueError("circular pattern requires radius.")
        center_x = _real_length(design, center[0])
        center_y = _real_length(design, center[1])
        radius_value = _real_length(design, radius)
        if radius_value <= 0:
            raise ValueError("circular pattern radius must be positive.")
        span = float(total_angle_deg)
        step = 0 if count_value == 1 else span / count_value
        for index in range(count_value):
            angle = math.radians(float(start_angle_deg) + index * step)
            generated.append((center_x + radius_value * math.cos(angle), center_y + radius_value * math.sin(angle), [center[0], center[1], index]))
        return generated

    raise ValueError("pattern_type must be explicit, rectangular, or circular.")

def _draw_rounded_rectangle(sketch, center_u, center_v, width, height, radius):
    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    half_w = width / 2.0
    half_h = height / 2.0
    radius = max(0.0, min(radius, half_w, half_h))
    if radius <= 0:
        lines.addTwoPointRectangle(
            _point_on_sketch(center_u - half_w, center_v - half_h),
            _point_on_sketch(center_u + half_w, center_v + half_h),
        )
        return

    left = center_u - half_w
    right = center_u + half_w
    bottom = center_v - half_h
    top = center_v + half_h

    lines.addByTwoPoints(_point_on_sketch(left + radius, top), _point_on_sketch(right - radius, top))
    lines.addByTwoPoints(_point_on_sketch(right, top - radius), _point_on_sketch(right, bottom + radius))
    lines.addByTwoPoints(_point_on_sketch(right - radius, bottom), _point_on_sketch(left + radius, bottom))
    lines.addByTwoPoints(_point_on_sketch(left, bottom + radius), _point_on_sketch(left, top - radius))

    arcs.addByCenterStartEnd(_point_on_sketch(right - radius, top - radius), _point_on_sketch(right - radius, top), _point_on_sketch(right, top - radius))
    arcs.addByCenterStartEnd(_point_on_sketch(right - radius, bottom + radius), _point_on_sketch(right, bottom + radius), _point_on_sketch(right - radius, bottom))
    arcs.addByCenterStartEnd(_point_on_sketch(left + radius, bottom + radius), _point_on_sketch(left + radius, bottom), _point_on_sketch(left, bottom + radius))
    arcs.addByCenterStartEnd(_point_on_sketch(left + radius, top - radius), _point_on_sketch(left, top - radius), _point_on_sketch(left + radius, top))

def _draw_rounded_slot(sketch, center_u, center_v, length, width, axis):
    if length <= width:
        raise ValueError("slot length must be larger than slot width.")
    radius = width / 2.0
    half_straight = (length - width) / 2.0
    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    if (axis or "x").lower() == "y":
        lines.addByTwoPoints(_point_on_sketch(center_u - radius, center_v - half_straight), _point_on_sketch(center_u - radius, center_v + half_straight))
        lines.addByTwoPoints(_point_on_sketch(center_u + radius, center_v + half_straight), _point_on_sketch(center_u + radius, center_v - half_straight))
        arcs.addByCenterStartEnd(_point_on_sketch(center_u, center_v + half_straight), _point_on_sketch(center_u - radius, center_v + half_straight), _point_on_sketch(center_u + radius, center_v + half_straight))
        arcs.addByCenterStartEnd(_point_on_sketch(center_u, center_v - half_straight), _point_on_sketch(center_u + radius, center_v - half_straight), _point_on_sketch(center_u - radius, center_v - half_straight))
        return

    lines.addByTwoPoints(_point_on_sketch(center_u - half_straight, center_v + radius), _point_on_sketch(center_u + half_straight, center_v + radius))
    lines.addByTwoPoints(_point_on_sketch(center_u + half_straight, center_v - radius), _point_on_sketch(center_u - half_straight, center_v - radius))
    arcs.addByCenterStartEnd(_point_on_sketch(center_u + half_straight, center_v), _point_on_sketch(center_u + half_straight, center_v + radius), _point_on_sketch(center_u + half_straight, center_v - radius))
    arcs.addByCenterStartEnd(_point_on_sketch(center_u - half_straight, center_v), _point_on_sketch(center_u - half_straight, center_v - radius), _point_on_sketch(center_u - half_straight, center_v + radius))

@register_tool("create_rounded_rectangle_body")
def create_rounded_rectangle_body(name="Rounded Rectangle", base_plane="xy", width="100 mm", height="50 mm", thickness="4 mm", corner_radius="3 mm", x_offset="0 mm", y_offset="0 mm", operation="new_body", hide_sketch=True):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()

    width_value = _real_length(design, width)
    height_value = _real_length(design, height)
    radius_value = _real_length(design, corner_radius)
    x_value = _real_length(design, x_offset)
    y_value = _real_length(design, y_offset)
    if width_value <= 0 or height_value <= 0:
        return {"error": "width and height must be positive length expressions."}
    if radius_value * 2 > min(width_value, height_value):
        return {"error": "corner_radius cannot exceed half of the smaller rectangle dimension."}

    sketch = root.sketches.add(_base_plane(root, base_plane))
    sketch.name = f"{name}_Sketch"
    _draw_rounded_rectangle(sketch, x_value, y_value, width_value, height_value, radius_value)

    profile = sketch.profiles.item(0)
    ext_input = root.features.extrudeFeatures.createInput(profile, _operation(operation))
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(str(thickness)))
    extrude = root.features.extrudeFeatures.add(ext_input)
    extrude.name = name
    body_name = None
    if extrude.bodies.count > 0:
        body_name = name
        extrude.bodies.item(0).name = name
    if hide_sketch:
        sketch.isLightBulbOn = False

    return {
        "result": {
            "message": f"Created rounded rectangle body '{name}'.",
            "featureName": extrude.name,
            "sketchName": sketch.name,
            "bodyName": body_name,
            "operation": operation,
            "dimensions": {
                "width": width,
                "height": height,
                "thickness": thickness,
                "cornerRadius": corner_radius,
            },
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_rounded_slot_cut")
def create_rounded_slot_cut(target_body_name, name="Rounded Slot Cut", base_plane="xy", length="20 mm", width="8 mm", cut_depth="5 mm", x_offset="0 mm", y_offset="0 mm", axis="x", hide_sketch=True):
    design = get_active_design()
    root = design.rootComponent
    target_body = _find_body(root, target_body_name)
    if not target_body:
        return {"error": f"Target body '{target_body_name}' not found."}
    before = _capture_design_state()

    length_value = _real_length(design, length)
    width_value = _real_length(design, width)
    x_value = _real_length(design, x_offset)
    y_value = _real_length(design, y_offset)
    if width_value <= 0 or length_value <= 0:
        return {"error": "length and width must be positive length expressions."}

    sketch = root.sketches.add(_base_plane(root, base_plane))
    sketch.name = f"{name}_Sketch"
    _draw_rounded_slot(sketch, x_value, y_value, length_value, width_value, axis)

    profile = sketch.profiles.item(0)
    ext_input = root.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    _set_participant_body(ext_input, target_body)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(str(cut_depth)))
    feature = root.features.extrudeFeatures.add(ext_input)
    feature.name = name
    if hide_sketch:
        sketch.isLightBulbOn = False

    return {
        "result": {
            "message": f"Created rounded slot cut '{name}' in '{target_body_name}'.",
            "featureName": feature.name,
            "sketchName": sketch.name,
            "targetBodyName": target_body_name,
            "dimensions": {"length": length, "width": width, "cutDepth": cut_depth, "axis": axis},
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_rounded_pocket")
def create_rounded_pocket(target_body_name, name="Rounded Pocket", base_plane="xy", width="40 mm", height="20 mm", depth="2 mm", corner_radius="3 mm", x_offset="0 mm", y_offset="0 mm", cut_direction="positive", use_selected_plane=False, hide_sketch=True):
    design = get_active_design()
    root = design.rootComponent
    target_body = _find_body(root, target_body_name)
    if not target_body:
        return {"error": f"Target body '{target_body_name}' not found."}
    before = _capture_design_state()

    width_value = _real_length(design, width)
    height_value = _real_length(design, height)
    radius_value = _real_length(design, corner_radius)
    x_value = _real_length(design, x_offset)
    y_value = _real_length(design, y_offset)
    if width_value <= 0 or height_value <= 0:
        return {"error": "width and height must be positive length expressions."}
    if radius_value * 2 > min(width_value, height_value):
        return {"error": "corner_radius cannot exceed half of the smaller pocket dimension."}

    target_component = getattr(target_body, "parentComponent", None) or root
    if use_selected_plane:
        sketch_plane, selected_component = _selected_base_plane()
        if not sketch_plane:
            return {"error": "No selected construction plane or planar face found for pocket placement."}
        target_component = selected_component or target_component
    else:
        sketch_plane = _base_plane(target_component, base_plane)

    sketch = target_component.sketches.add(sketch_plane)
    sketch.name = f"{name}_Sketch"
    _draw_rounded_rectangle(sketch, x_value, y_value, width_value, height_value, radius_value)

    profile = sketch.profiles.item(0)
    ext_input = target_component.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    _set_participant_body(ext_input, target_body)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(_cut_depth_expression(depth, cut_direction)))
    feature = target_component.features.extrudeFeatures.add(ext_input)
    feature.name = name
    if hide_sketch:
        sketch.isLightBulbOn = False

    return {
        "result": {
            "message": f"Created rounded pocket '{name}' in '{target_body_name}'.",
            "featureName": feature.name,
            "sketchName": sketch.name,
            "targetBodyName": target_body_name,
            "usedSelectedPlane": bool(use_selected_plane),
            "dimensions": {
                "width": width,
                "height": height,
                "depth": depth,
                "cornerRadius": corner_radius,
                "cutDirection": cut_direction,
            },
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_counterbore_hole_pattern")
def create_counterbore_hole_pattern(target_body_name, points, name="Counterbore Pattern", base_plane="xy", hole_diameter="4 mm", counterbore_diameter="8 mm", counterbore_depth="2 mm", through_depth="10 mm", hide_sketch=True):
    if not isinstance(points, list) or not points:
        return {"error": "points must be a non-empty list of [x, y] length-expression pairs."}
    design = get_active_design()
    root = design.rootComponent
    target_body = _find_body(root, target_body_name)
    if not target_body:
        return {"error": f"Target body '{target_body_name}' not found."}
    before = _capture_design_state()

    hole_radius = _real_length(design, hole_diameter) / 2.0
    counterbore_radius = _real_length(design, counterbore_diameter) / 2.0
    if hole_radius <= 0 or counterbore_radius <= 0:
        return {"error": "hole_diameter and counterbore_diameter must be positive length expressions."}
    created_features = []
    created_sketches = []
    for index, point in enumerate(points, start=1):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return {"error": "Each point must be [x, y] using Fusion length expressions, e.g. ['10 mm', '5 mm']."}
        x_value = _real_length(design, point[0])
        y_value = _real_length(design, point[1])

        for label, radius, depth in (
            ("Counterbore", counterbore_radius, counterbore_depth),
            ("Through", hole_radius, through_depth),
        ):
            sketch = root.sketches.add(_base_plane(root, base_plane))
            sketch.name = f"{name}_{index}_{label}_Sketch"
            sketch.sketchCurves.sketchCircles.addByCenterRadius(_point_on_sketch(x_value, y_value), radius)
            profile = sketch.profiles.item(0)
            ext_input = root.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            _set_participant_body(ext_input, target_body)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(str(depth)))
            feature = root.features.extrudeFeatures.add(ext_input)
            feature.name = f"{name}_{index}_{label}"
            created_features.append(feature.name)
            created_sketches.append(sketch.name)
            if hide_sketch:
                sketch.isLightBulbOn = False

    return {
        "result": {
            "message": f"Created {len(points)} counterbore holes in '{target_body_name}'.",
            "targetBodyName": target_body_name,
            "featureNames": created_features,
            "sketchNames": created_sketches,
            "dimensions": {
                "holeDiameter": hole_diameter,
                "counterboreDiameter": counterbore_diameter,
                "counterboreDepth": counterbore_depth,
                "throughDepth": through_depth,
            },
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_hole_pattern")
def create_hole_pattern(
    target_body_name,
    name="Hole Pattern",
    hole_type="through",
    base_plane="xy",
    hole_diameter="4 mm",
    cut_depth="10 mm",
    points=None,
    pattern_type="explicit",
    origin=None,
    spacing=None,
    count=None,
    center=None,
    radius=None,
    start_angle_deg=0,
    total_angle_deg=360,
    counterbore_diameter=None,
    counterbore_depth=None,
    countersink_diameter=None,
    countersink_depth=None,
    cut_direction="positive",
    hide_sketch=True,
):
    design = get_active_design()
    root = design.rootComponent
    target_body = _find_body(root, target_body_name)
    if not target_body:
        return {"error": f"Target body '{target_body_name}' not found."}
    hole_kind = (hole_type or "through").lower()
    if hole_kind not in ("through", "blind", "counterbore", "countersink"):
        return {"error": "hole_type must be one of through, blind, counterbore, or countersink."}

    before = _capture_design_state()
    target_component = getattr(target_body, "parentComponent", None) or root
    try:
        generated_points = _hole_pattern_points(
            design,
            points=points,
            pattern_type=pattern_type,
            origin=origin,
            spacing=spacing,
            count=count,
            center=center,
            radius=radius,
            start_angle_deg=start_angle_deg,
            total_angle_deg=total_angle_deg,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    hole_radius = _real_length(design, hole_diameter) / 2.0
    if hole_radius <= 0:
        return {"error": "hole_diameter must be a positive length expression."}

    cut_specs = []
    warnings = []
    if hole_kind == "counterbore":
        if not counterbore_diameter or not counterbore_depth:
            return {"error": "counterbore hole_type requires counterbore_diameter and counterbore_depth."}
        counterbore_radius = _real_length(design, counterbore_diameter) / 2.0
        if counterbore_radius <= hole_radius:
            return {"error": "counterbore_diameter must be larger than hole_diameter."}
        cut_specs.append(("Counterbore", counterbore_radius, counterbore_depth))
    elif hole_kind == "countersink":
        if not countersink_diameter or not countersink_depth:
            return {"error": "countersink hole_type requires countersink_diameter and countersink_depth."}
        countersink_radius = _real_length(design, countersink_diameter) / 2.0
        if countersink_radius <= hole_radius:
            return {"error": "countersink_diameter must be larger than hole_diameter."}
        cut_specs.append(("CountersinkRelief", countersink_radius, countersink_depth))
        warnings.append("Countersink is represented as a cylindrical relief cut; true conical countersink support is still a roadmap item.")

    cut_specs.append(("Hole", hole_radius, cut_depth))

    created_features = []
    created_sketches = []
    for index, (x_value, y_value, source_point) in enumerate(generated_points, start=1):
        for label, radius_value, depth in cut_specs:
            sketch = target_component.sketches.add(_base_plane(target_component, base_plane))
            sketch.name = f"{name}_{index}_{label}_Sketch"
            sketch.sketchCurves.sketchCircles.addByCenterRadius(_point_on_sketch(x_value, y_value), radius_value)
            profile = sketch.profiles.item(0)
            ext_input = target_component.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            _set_participant_body(ext_input, target_body)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByString(_cut_depth_expression(depth, cut_direction)))
            feature = target_component.features.extrudeFeatures.add(ext_input)
            feature.name = f"{name}_{index}_{label}"
            created_features.append(feature.name)
            created_sketches.append(sketch.name)
            if hide_sketch:
                sketch.isLightBulbOn = False

    return {
        "result": {
            "message": f"Created {len(generated_points)} {hole_kind} hole(s) in '{target_body_name}'.",
            "targetBodyName": target_body_name,
            "holeType": hole_kind,
            "patternType": pattern_type,
            "pointCount": len(generated_points),
            "featureNames": created_features,
            "sketchNames": created_sketches,
            "generatedPoints": [
                {"index": index, "x": x_value, "y": y_value, "source": source_point}
                for index, (x_value, y_value, source_point) in enumerate(generated_points, start=1)
            ],
            "dimensions": {
                "holeDiameter": hole_diameter,
                "cutDepth": cut_depth,
                "counterboreDiameter": counterbore_diameter,
                "counterboreDepth": counterbore_depth,
                "countersinkDiameter": countersink_diameter,
                "countersinkDepth": countersink_depth,
                "cutDirection": cut_direction,
            },
            "warnings": warnings,
            "stateComparison": _compare_after_mutation(before),
        }
    }

def _all_components(root):
    components = [root]
    for occ in root.allOccurrences:
        comp = occ.component
        if comp not in components:
            components.append(comp)
    return components

def _find_named_base_plane(root, name):
    if not name:
        return None, None

    standard = {
        "xy": root.xYConstructionPlane,
        "xz": root.xZConstructionPlane,
        "yz": root.yZConstructionPlane,
        "xYConstructionPlane": root.xYConstructionPlane,
        "xZConstructionPlane": root.xZConstructionPlane,
        "yZConstructionPlane": root.yZConstructionPlane,
    }
    if name in standard:
        return standard[name], root

    for comp in _all_components(root):
        for plane in comp.constructionPlanes:
            if plane.name == name:
                return plane, comp
    return None, None

def _selected_base_plane():
    app = adsk.core.Application.get()
    ui = app.userInterface
    if ui.activeSelections.count < 1:
        return None, None

    entity = ui.activeSelections.item(0).entity
    plane = adsk.fusion.ConstructionPlane.cast(entity)
    if plane:
        return plane, plane.parentComponent

    face = adsk.fusion.BRepFace.cast(entity)
    if face:
        surface = face.geometry
        if adsk.core.Plane.cast(surface):
            return face, face.body.parentComponent

    return None, None

def _base_plane_geometry(base_plane):
    if isinstance(base_plane, adsk.fusion.ConstructionPlane):
        return base_plane.geometry
    face = adsk.fusion.BRepFace.cast(base_plane)
    if face:
        return face.geometry
    raise ValueError("Base plane must be a ConstructionPlane or planar BRepFace.")

def _find_center_point(component, root, name):
    if not name:
        return None

    for point in component.constructionPoints:
        if point.name == name:
            return point.geometry

    for sketch in component.sketches:
        for sketch_point in sketch.sketchPoints:
            if sketch_point.name == name:
                return sketch_point.worldGeometry

    for comp in _all_components(root):
        if comp == component:
            continue
        for point in comp.constructionPoints:
            if point.name == name:
                return point.geometry
        for sketch in comp.sketches:
            for sketch_point in sketch.sketchPoints:
                if sketch_point.name == name:
                    return sketch_point.worldGeometry

    return None

def _find_named_point_entity(component, root, name):
    if not name:
        return None, None

    for point in getattr(component, "constructionPoints", []) or []:
        if getattr(point, "name", None) == name:
            return point, component

    for sketch in getattr(component, "sketches", []) or []:
        for sketch_point in getattr(sketch, "sketchPoints", []) or []:
            if getattr(sketch_point, "name", None) == name:
                return sketch_point, component

    for comp in _all_components(root):
        if comp == component:
            continue
        for point in getattr(comp, "constructionPoints", []) or []:
            if getattr(point, "name", None) == name:
                return point, comp
        for sketch in getattr(comp, "sketches", []) or []:
            for sketch_point in getattr(sketch, "sketchPoints", []) or []:
                if getattr(sketch_point, "name", None) == name:
                    return sketch_point, comp

    return None, None

def _selected_point_entity():
    app = adsk.core.Application.get()
    ui = app.userInterface
    if ui.activeSelections.count < 1:
        return None, None
    entity = ui.activeSelections.item(0).entity
    for class_name in ("ConstructionPoint", "SketchPoint", "BRepVertex"):
        caster = getattr(adsk.fusion, class_name, None)
        cast = getattr(caster, "cast", None)
        selected = cast(entity) if cast else None
        if selected:
            parent = getattr(selected, "parentComponent", None)
            if not parent and getattr(selected, "body", None):
                parent = selected.body.parentComponent
            if not parent and getattr(selected, "parentSketch", None):
                parent = selected.parentSketch.parentComponent
            return selected, parent
    return None, None

def _selected_line_entity():
    app = adsk.core.Application.get()
    ui = app.userInterface
    if ui.activeSelections.count < 1:
        return None, None
    entity = ui.activeSelections.item(0).entity
    for class_name in ("ConstructionAxis", "SketchLine", "BRepEdge"):
        caster = getattr(adsk.fusion, class_name, None)
        cast = getattr(caster, "cast", None)
        selected = cast(entity) if cast else None
        if selected:
            parent = getattr(selected, "parentComponent", None)
            if not parent and getattr(selected, "body", None):
                parent = selected.body.parentComponent
            if not parent and getattr(selected, "parentSketch", None):
                parent = selected.parentSketch.parentComponent
            return selected, parent
    return None, None

def _create_reference_sketch_point(component, base_plane_name, x, y, point_name, hide_sketch=True):
    sketch = component.sketches.add(_base_plane(component, base_plane_name))
    sketch.name = f"{point_name}_ReferenceSketch"
    point = sketch.sketchPoints.add(_point_on_sketch(x, y))
    point.name = f"{point_name}_SketchPoint"
    if hide_sketch:
        sketch.isLightBulbOn = False
    return point, sketch

def _is_coordinate_pair(value):
    return isinstance(value, (list, tuple)) and len(value) == 2

def _section_type(value):
    mapping = {
        "circular": adsk.fusion.PipeSectionTypes.CircularPipeSectionType,
        "square": adsk.fusion.PipeSectionTypes.SquarePipeSectionType,
        "triangular": adsk.fusion.PipeSectionTypes.TriangularPipeSectionType,
    }
    return mapping.get((value or "circular").lower(), adsk.fusion.PipeSectionTypes.CircularPipeSectionType)

def _point_on_plane(origin, u_dir, v_dir, normal, x, y, z):
    point = origin.copy()
    u = u_dir.copy()
    v = v_dir.copy()
    n = normal.copy()
    u.scaleBy(x)
    v.scaleBy(y)
    n.scaleBy(z)
    point.translateBy(u)
    point.translateBy(v)
    point.translateBy(n)
    return point

@register_tool("create_construction_point")
def create_construction_point(name="Construction Point", mode="coordinates", base_plane_name="xy", x="0 mm", y="0 mm", point_name=None, use_selected_point=False, hide_reference_sketch=True):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()
    target_component = root
    source_entity = None
    reference_sketch_name = None

    point_mode = (mode or "coordinates").lower()
    if use_selected_point or point_mode == "selected":
        source_entity, selected_component = _selected_point_entity()
        if not source_entity:
            return {"error": "No selected construction point, sketch point, or vertex found."}
        target_component = selected_component or root
    elif point_mode == "named":
        source_entity, found_component = _find_named_point_entity(root, root, point_name)
        if not source_entity:
            return {"error": f"Point '{point_name}' not found."}
        target_component = found_component or root
    elif point_mode == "coordinates":
        x_value = _real_length(design, x)
        y_value = _real_length(design, y)
        source_entity, sketch = _create_reference_sketch_point(root, base_plane_name, x_value, y_value, name, hide_reference_sketch)
        reference_sketch_name = _safe_name(sketch)
        target_component = root
    else:
        return {"error": "mode must be coordinates, named, or selected."}

    points = target_component.constructionPoints
    point_input = points.createInput()
    point_input.setByPoint(source_entity)
    point = points.add(point_input)
    point.name = name

    return {
        "result": {
            "message": f"Created construction point '{name}'.",
            "pointName": point.name,
            "mode": point_mode,
            "componentName": _safe_name(target_component),
            "referenceSketchName": reference_sketch_name,
            "sourceName": point_name if point_mode == "named" else _safe_name(source_entity),
            "stateComparison": _compare_after_mutation(before),
        }
    }


@register_tool("create_construction_axis")
def create_construction_axis(name="Construction Axis", mode="two_points", point_name_one=None, point_name_two=None, point_one=None, point_two=None, base_plane_name="xy", use_selected_line=False, hide_reference_sketch=True):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()
    axis_mode = (mode or "two_points").lower()
    target_component = root
    reference_sketches = []

    axes = target_component.constructionAxes
    axis_input = axes.createInput()

    if use_selected_line or axis_mode == "selected_line":
        line_entity, selected_component = _selected_line_entity()
        if not line_entity:
            return {"error": "No selected construction axis, sketch line, or linear edge found."}
        target_component = selected_component or root
        axes = target_component.constructionAxes
        axis_input = axes.createInput()
        axis_input.setByLine(line_entity)
    elif axis_mode == "two_points":
        first = second = None
        if point_name_one:
            first, first_component = _find_named_point_entity(root, root, point_name_one)
            target_component = first_component or target_component
        if point_name_two:
            second, second_component = _find_named_point_entity(root, root, point_name_two)
            target_component = second_component or target_component
        if not first and point_one:
            if not _is_coordinate_pair(point_one):
                return {"error": "point_one must be a two-item [x, y] coordinate array."}
            x_value = _real_length(design, point_one[0])
            y_value = _real_length(design, point_one[1])
            first, sketch = _create_reference_sketch_point(target_component, base_plane_name, x_value, y_value, f"{name}_Point1", hide_reference_sketch)
            reference_sketches.append(_safe_name(sketch))
        if not second and point_two:
            if not _is_coordinate_pair(point_two):
                return {"error": "point_two must be a two-item [x, y] coordinate array."}
            x_value = _real_length(design, point_two[0])
            y_value = _real_length(design, point_two[1])
            second, sketch = _create_reference_sketch_point(target_component, base_plane_name, x_value, y_value, f"{name}_Point2", hide_reference_sketch)
            reference_sketches.append(_safe_name(sketch))
        if not first or not second:
            return {"error": "two_points mode requires point_name_one/point_name_two or point_one/point_two coordinates."}
        axes = target_component.constructionAxes
        axis_input = axes.createInput()
        axis_input.setByTwoPoints(first, second)
    else:
        return {"error": "mode must be two_points or selected_line."}

    axis = axes.add(axis_input)
    axis.name = name

    return {
        "result": {
            "message": f"Created construction axis '{name}'.",
            "axisName": axis.name,
            "mode": axis_mode,
            "componentName": _safe_name(target_component),
            "referenceSketchNames": reference_sketches,
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_offset_plane")
def create_offset_plane(name="Offset Plane", base_plane_name="xy", offset="0 mm", use_selected_plane=False):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()

    base_plane = None
    target_component = None
    if use_selected_plane:
        base_plane, target_component = _selected_base_plane()
        if not base_plane:
            return {"error": "No selected construction plane or planar face found."}
    else:
        base_plane, target_component = _find_named_base_plane(root, base_plane_name)
        if not base_plane:
            return {"error": f"Base plane '{base_plane_name}' not found. Use xy, xz, yz, a named construction plane, or use_selected_plane=true."}

    if not target_component:
        target_component = root

    planes = target_component.constructionPlanes
    plane_input = planes.createInput()
    plane_input.setByOffset(base_plane, adsk.core.ValueInput.createByString(str(offset)))
    plane = planes.add(plane_input)
    plane.name = name

    return {
        "result": {
            "message": f"Created offset construction plane '{name}'.",
            "planeName": plane.name,
            "basePlaneName": base_plane_name if not use_selected_plane else None,
            "usedSelectedPlane": bool(use_selected_plane),
            "offset": offset,
            "componentName": _safe_name(target_component),
            "stateComparison": _compare_after_mutation(before),
        }
    }

def _safe_name(entity):
    try:
        return entity.name
    except Exception:
        return None

@register_tool("mirror_features_or_bodies")
def mirror_features_or_bodies(name="Mirror", body_names=None, feature_names=None, mirror_plane_name="yz", use_selected_plane=False, use_selected_entities=False):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()

    mirror_plane = None
    target_component = root
    if use_selected_plane:
        mirror_plane, selected_component = _selected_base_plane()
        if not mirror_plane:
            return {"error": "No selected construction plane or planar face found for mirror plane."}
        target_component = selected_component or root
    else:
        mirror_plane, selected_component = _find_named_base_plane(root, mirror_plane_name)
        if not mirror_plane:
            return {"error": f"Mirror plane '{mirror_plane_name}' not found. Use xy, xz, yz, a named construction plane, or use_selected_plane=true."}
        target_component = selected_component or root

    entities = adsk.core.ObjectCollection.create()
    resolved = {"bodies": [], "features": [], "selected": []}
    missing = {"bodies": [], "features": []}

    for body_name in _normalize_name_list(body_names):
        body = _find_body(root, body_name)
        if body:
            _collection_add(entities, body)
            resolved["bodies"].append(body_name)
        else:
            missing["bodies"].append(body_name)

    for feature_name in _normalize_name_list(feature_names):
        feature = _find_feature_entity(design, feature_name)
        if feature:
            _collection_add(entities, feature)
            resolved["features"].append(feature_name)
        else:
            missing["features"].append(feature_name)

    if use_selected_entities:
        app = adsk.core.Application.get()
        selections = getattr(getattr(app, "userInterface", None), "activeSelections", None)
        selection_count = getattr(selections, "count", 0) if selections else 0
        for index in range(selection_count):
            entity = selections.item(index).entity
            if entity == mirror_plane:
                continue
            _collection_add(entities, entity)
            resolved["selected"].append(_safe_name(entity) or getattr(entity, "objectType", None) or f"selection[{index}]")

    entity_count = getattr(entities, "count", len(entities) if hasattr(entities, "__len__") else 0)
    if entity_count == 0:
        return {"error": "No mirror input entities resolved. Provide body_names, feature_names, or use_selected_entities=true."}
    if missing["bodies"] or missing["features"]:
        return {"error": f"Mirror input entities were not found: bodies={missing['bodies']}, features={missing['features']}."}

    mirror_features = target_component.features.mirrorFeatures
    mirror_input = mirror_features.createInput(entities, mirror_plane)
    try:
        mirror_input.patternComputeOption = adsk.fusion.PatternComputeOptions.OptimizedPatternCompute
    except Exception:
        pass
    mirror_feature = mirror_features.add(mirror_input)
    mirror_feature.name = name

    return {
        "result": {
            "message": f"Created mirror feature '{name}'.",
            "featureName": mirror_feature.name,
            "mirrorPlaneName": mirror_plane_name if not use_selected_plane else None,
            "usedSelectedPlane": bool(use_selected_plane),
            "resolvedInputs": resolved,
            "resultBodies": _collection_names(getattr(mirror_feature, "bodies", None)),
            "resultFeatures": _collection_names(getattr(mirror_feature, "resultFeatures", None)),
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("pattern_feature")
def pattern_feature(
    name="Pattern",
    pattern_type="rectangular",
    body_names=None,
    feature_names=None,
    use_selected_entities=False,
    direction_one_axis="x",
    quantity_one=2,
    distance_one="10 mm",
    direction_two_axis=None,
    quantity_two=None,
    distance_two=None,
    axis_name="z",
    use_selected_axis=False,
    quantity=2,
    total_angle="360 deg",
    distance_type="spacing",
    compute_option="optimized",
):
    design = get_active_design()
    root = design.rootComponent
    before = _capture_design_state()

    entities = adsk.core.ObjectCollection.create()
    resolved = {"bodies": [], "features": [], "selected": []}
    missing = {"bodies": [], "features": []}
    target_component = None

    for body_name in _normalize_name_list(body_names):
        body = _find_body(root, body_name)
        if body:
            _collection_add(entities, body)
            resolved["bodies"].append(body_name)
            target_component = target_component or _entity_component(body)
        else:
            missing["bodies"].append(body_name)

    for feature_name in _normalize_name_list(feature_names):
        feature = _find_feature_entity(design, feature_name)
        if feature:
            _collection_add(entities, feature)
            resolved["features"].append(feature_name)
            target_component = target_component or _entity_component(feature)
        else:
            missing["features"].append(feature_name)

    if use_selected_entities:
        app = adsk.core.Application.get()
        selections = getattr(getattr(app, "userInterface", None), "activeSelections", None)
        selection_count = getattr(selections, "count", 0) if selections else 0
        for index in range(selection_count):
            entity = selections.item(index).entity
            _collection_add(entities, entity)
            resolved["selected"].append(_safe_name(entity) or getattr(entity, "objectType", None) or f"selection[{index}]")
            target_component = target_component or _entity_component(entity)

    entity_count = getattr(entities, "count", len(entities) if hasattr(entities, "__len__") else 0)
    if entity_count == 0:
        return {"error": "No pattern input entities resolved. Provide body_names, feature_names, or use_selected_entities=true."}
    if missing["bodies"] or missing["features"]:
        return {"error": f"Pattern input entities were not found: bodies={missing['bodies']}, features={missing['features']}."}

    target_component = target_component or root
    pattern_kind = (pattern_type or "rectangular").lower()
    compute = _pattern_compute_option(compute_option)

    if pattern_kind == "rectangular":
        direction_one, _ = _find_named_axis(root, direction_one_axis)
        if not direction_one:
            return {"error": f"Direction axis '{direction_one_axis}' not found. Use x, y, z, or a named construction axis."}
        quantity_one_input = adsk.core.ValueInput.createByString(str(quantity_one))
        distance_one_input = adsk.core.ValueInput.createByString(str(distance_one))
        distance_kind = _pattern_distance_type(distance_type)
        pattern_features = target_component.features.rectangularPatternFeatures
        try:
            pattern_input = pattern_features.createInput(entities, direction_one, quantity_one_input, distance_one_input, distance_kind)
        except TypeError:
            pattern_input = pattern_features.createInput(entities, quantity_one_input, distance_one_input, direction_one)

        if direction_two_axis:
            direction_two, _ = _find_named_axis(root, direction_two_axis)
            if not direction_two:
                return {"error": f"Direction axis '{direction_two_axis}' not found. Use x, y, z, or a named construction axis."}
            quantity_two_input = adsk.core.ValueInput.createByString(str(quantity_two or 1))
            distance_two_input = adsk.core.ValueInput.createByString(str(distance_two or "0 mm"))
            try:
                pattern_input.setDirectionTwo(direction_two, quantity_two_input, distance_two_input)
            except Exception:
                for attr, val in (
                    ("directionTwoEntity", direction_two),
                    ("quantityTwo", quantity_two_input),
                    ("distanceTwo", distance_two_input),
                ):
                    try:
                        setattr(pattern_input, attr, val)
                    except Exception:
                        pass
        feature = pattern_features.add(pattern_input)

    elif pattern_kind == "circular":
        if use_selected_axis:
            axis, _ = _selected_axis()
            if not axis:
                return {"error": "No selected construction axis or linear edge found for circular pattern axis."}
        else:
            axis, _ = _find_named_axis(root, axis_name)
            if not axis:
                return {"error": f"Pattern axis '{axis_name}' not found. Use x, y, z, a named construction axis, or use_selected_axis=true."}
        quantity_input = adsk.core.ValueInput.createByString(str(quantity))
        total_angle_input = adsk.core.ValueInput.createByString(str(total_angle))
        pattern_features = target_component.features.circularPatternFeatures
        try:
            pattern_input = pattern_features.createInput(entities, axis, quantity_input, total_angle_input)
        except TypeError:
            pattern_input = pattern_features.createInput(entities, quantity_input, total_angle_input, axis)
        feature = pattern_features.add(pattern_input)

    else:
        return {"error": "pattern_type must be rectangular or circular."}

    try:
        if compute is not None:
            pattern_input.patternComputeOption = compute
    except Exception:
        pass
    feature.name = name

    return {
        "result": {
            "message": f"Created {pattern_kind} pattern feature '{name}'.",
            "featureName": feature.name,
            "patternType": pattern_kind,
            "resolvedInputs": resolved,
            "resultBodies": _collection_names(getattr(feature, "bodies", None)),
            "resultFeatures": _collection_names(getattr(feature, "resultFeatures", None)),
            "stateComparison": _compare_after_mutation(before),
        }
    }

@register_tool("create_coil")
def create_coil(
    name: str = "MCP_Coil",
    base_plane_name: str = "",
    center_point_name: str = "",
    diameter: str = "1 cm",
    height: str = "2 cm",
    revolutions: float = 5.0,
    section_size: str = "0.1 cm",
    section_type: str = "circular",
    operation: str = "new_body",
    clockwise: bool = True,
    points_per_revolution: int = 24,
    create_path_sketch: bool = True,
    hollow_thickness: str = ""
) -> dict:
    try:
        design = get_active_design()
        root = design.rootComponent
        before = _capture_design_state()

        base_plane, target_comp = _find_named_base_plane(root, base_plane_name)
        if not base_plane:
            base_plane, target_comp = _selected_base_plane()
        if not base_plane:
            base_plane, target_comp = root.xYConstructionPlane, root
        plane = _base_plane_geometry(base_plane)

        center = _find_center_point(target_comp, root, center_point_name) or plane.origin
        radius = _real_length(design, diameter) / 2.0
        height_value = _real_length(design, height)
        revolutions = float(revolutions)
        points_per_revolution = max(8, min(int(points_per_revolution), 96))
        total_points = max(12, int(math.ceil(abs(revolutions) * points_per_revolution)) + 1)
        direction = -1.0 if clockwise else 1.0

        points = adsk.core.ObjectCollection.create()
        for i in range(total_points):
            t = i / (total_points - 1)
            angle = direction * 2.0 * math.pi * revolutions * t
            x = math.cos(angle) * radius
            y = math.sin(angle) * radius
            z = height_value * t
            points.add(_point_on_plane(center, plane.uDirection, plane.vDirection, plane.normal, x, y, z))

        old_3d_setting = design.is3DSketchingAllowed
        design.is3DSketchingAllowed = True
        try:
            sketch = target_comp.sketches.add(base_plane if base_plane else target_comp.xYConstructionPlane)
            sketch.name = f"{name}_Path"
            spline = sketch.sketchCurves.sketchFittedSplines.add(points)
        finally:
            design.is3DSketchingAllowed = old_3d_setting

        if not spline:
            raise RuntimeError("Failed to create helix spline.")

        path = target_comp.features.createPath(spline, False)
        pipe_input = target_comp.features.pipeFeatures.createInput(path, _operation(operation))
        pipe_input.sectionType = _section_type(section_type)
        pipe_input.sectionSize = _value(section_size)
        if hollow_thickness:
            pipe_input.isHollow = True
            pipe_input.sectionThickness = _value(hollow_thickness)

        pipe = target_comp.features.pipeFeatures.add(pipe_input)
        if not pipe:
            raise RuntimeError("Failed to create pipe feature from helix path.")

        pipe.name = name
        if not create_path_sketch:
            sketch.isLightBulbOn = False

        return {
            "result": {
                "featureName": pipe.name,
                "pathSketchName": sketch.name,
                "componentName": target_comp.name,
                "basePlane": getattr(base_plane, "name", "selected planar face"),
                "centerPoint": center_point_name or "base plane origin",
                "diameter": diameter,
                "height": height,
                "revolutions": revolutions,
                "sectionSize": section_size,
                "points": total_points,
                "operation": operation,
                "stateComparison": _compare_after_mutation(before),
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating coil: {e}\n{err}")
        return {"error": f"Failed to create coil: {str(e)}"}


# --- Parameter and Validation Tools ---

@register_tool("modify_parameters")
def modify_parameters(param_name, new_expression):
    if not isinstance(param_name, str) or not param_name:
        return {"error": "Parameter name must be a non-empty string."}
    if not isinstance(new_expression, str) or not new_expression:
        return {"error": "New expression must be a non-empty string."}
    design = get_active_design()
    param = design.userParameters.itemByName(param_name)
    if not param:
        return {"error": f"Parameter '{param_name}' not found."}
    old_expr = param.expression
    before_state = _capture_design_state()
    param.expression = new_expression
    return {
        "result": {
            "message": f"Successfully updated '{param_name}' from '{old_expr}' to '{new_expression}'",
            "parameterName": param_name,
            "beforeExpression": old_expr,
            "afterExpression": new_expression,
            "stateComparison": _compare_after_mutation(before_state),
        }
    }

def _param_to_dict(param):
    return {
        "name": param.name,
        "expression": param.expression,
        "value": param.value,
        "unit": param.unit,
        "comment": param.comment
    }

@register_tool("get_parameter")
def get_parameter(name=""):
    design = get_active_design()
    if name:
        param = design.userParameters.itemByName(name)
        if not param:
            return {"error": f"Parameter '{name}' not found."}
        return {"result": _param_to_dict(param)}
    return {"result": {"parameters": [_param_to_dict(param) for param in design.userParameters]}}

@register_tool("set_parameter")
def set_parameter(name, expression):
    if not isinstance(name, str) or not name:
        return {"error": "Parameter name must be a non-empty string."}
    if not isinstance(expression, str) or not expression:
        return {"error": "Parameter expression must be a non-empty string."}

    design = get_active_design()
    param = design.userParameters.itemByName(name)
    if not param:
        return {"error": f"Parameter '{name}' not found."}
    before = _param_to_dict(param)
    before_state = _capture_design_state()
    param.expression = expression
    return {"result": {"before": before, "after": _param_to_dict(param), "stateComparison": _compare_after_mutation(before_state)}}

@register_tool("validate_model")
def validate_model():
    design = get_active_design()
    issues = []
    timeline = design.timeline
    for i in range(timeline.count):
        obj = timeline.item(i)
        if obj.healthState != adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState:
            issues.append(f"Timeline issue at '{obj.name}'")
    if not issues:
        return {"result": {"status": "Healthy", "issues": []}}
    else:
        return {"result": {"status": "Issues Found", "issues": issues}}

@register_tool("create_sketch_offset")
def create_sketch_offset(sketch_name, distance):
    try:
        design = get_active_design()
        root = design.rootComponent
        
        # 1. Find the sketch
        target_sketch = None
        for comp in _all_components(root):
            for sk in comp.sketches:
                if sk.name == sketch_name:
                    target_sketch = sk
                    break
            if target_sketch:
                break
                
        if not target_sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
            
        # 2. Get all curves in the sketch safely
        curves = adsk.core.ObjectCollection.create()
        curves_classes = [
            target_sketch.sketchCurves.sketchLines,
            target_sketch.sketchCurves.sketchCircles,
            target_sketch.sketchCurves.sketchArcs,
            target_sketch.sketchCurves.sketchEllipses,
            target_sketch.sketchCurves.sketchFittedSplines,
            target_sketch.sketchCurves.sketchFixedSplines,
            target_sketch.sketchCurves.sketchConicCurves
        ]
        for curve_class in curves_classes:
            for i in range(curve_class.count):
                curves.add(curve_class.item(i))
            
        if curves.count == 0:
            return {"error": f"Sketch '{sketch_name}' contains no curves to offset."}
            
        # 3. Calculate distance value (evaluated to cm)
        val_dist = design.unitsManager.evaluateExpression(distance, "cm")
        
        # 4. Calculate centroid of sketch points for direction point
        pts = []
        for i in range(target_sketch.sketchPoints.count):
            pt = target_sketch.sketchPoints.item(i)
            if pt and pt.geometry:
                pts.append(pt.geometry)
                
        if not pts:
            dir_pt = adsk.core.Point3D.create(1.0, 1.0, 0.0)
        else:
            avg_x = sum(p.x for p in pts) / len(pts)
            avg_y = sum(p.y for p in pts) / len(pts)
            # Use offset direction: outward (positive) or inward (negative)
            dir_pt = adsk.core.Point3D.create(avg_x + val_dist, avg_y + val_dist, 0.0)
            
        # 5. Perform the offset
        offset_curves = target_sketch.offset(curves, dir_pt, val_dist)
        
        return {
            "result": f"Successfully created sketch offset of {distance} in sketch '{sketch_name}'",
            "offsetCurvesCount": offset_curves.count
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error creating sketch offset: {e}\n{err}")
        return {"error": f"Failed to create sketch offset: {str(e)}"}

@register_tool("suppress_timeline_feature")
def suppress_timeline_feature(name=None, index=None, suppress=True, reason=None, allow_downstream_risk=False):
    try:
        reason_error = _require_reason(reason, "suppressing or unsuppressing a timeline feature")
        if reason_error:
            return reason_error

        design = get_active_design()
        timeline = design.timeline
        target_item = _find_timeline_item(timeline, name=name, index=index)
                    
        if not target_item:
            return {"error": f"Timeline item not found (name='{name}', index={index})"}

        feature_name = target_item.name
        dependency_report = _downstream_dependency_report(feature_name)
        impact_report = _impact_report(feature_name, "suppress" if suppress else "unsuppress")
        if _has_downstream_consumers(dependency_report) and not allow_downstream_risk:
            return {
                "error": "Suppressing this timeline feature may affect downstream consumers. Inspect dependencies or set allow_downstream_risk=true with a reason.",
                "dependencyReport": dependency_report,
                "impactReport": impact_report,
            }

        before = _design_state_snapshot(include_selections=False)
        target_item.isSuppressed = bool(suppress)
        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        status_str = "suppressed" if suppress else "unsuppressed"
        return {
            "result": {
                "message": f"Successfully {status_str} timeline feature '{feature_name}'",
                "featureName": feature_name,
                "suppressed": bool(suppress),
                "reason": reason,
                "allowedDownstreamRisk": bool(allow_downstream_risk),
                "dependencyReport": dependency_report,
                "impactReport": impact_report,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error suppressing timeline feature: {e}\n{err}")
        return {"error": f"Failed to suppress/unsuppress timeline feature: {str(e)}"}

@register_tool("delete_timeline_feature")
def delete_timeline_feature(name=None, index=None, reason=None, allow_downstream_risk=False):
    try:
        reason_error = _require_reason(reason, "deleting a timeline feature")
        if reason_error:
            return reason_error

        design = get_active_design()
        timeline = design.timeline
        target_item = _find_timeline_item(timeline, name=name, index=index)
                    
        if not target_item:
            return {"error": f"Timeline item not found (name='{name}', index={index})"}
            
        feature_name = target_item.name
        dependency_report = _downstream_dependency_report(feature_name)
        impact_report = _impact_report(feature_name, "delete")
        if _has_downstream_consumers(dependency_report) and not allow_downstream_risk:
            return {
                "error": "Deleting this timeline feature may affect downstream consumers. Inspect dependencies or set allow_downstream_risk=true with a reason.",
                "dependencyReport": dependency_report,
                "impactReport": impact_report,
            }

        before = _design_state_snapshot(include_selections=False)
        target_item.deleteMe()
        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        return {
            "result": {
                "message": f"Successfully deleted timeline feature '{feature_name}'",
                "featureName": feature_name,
                "reason": reason,
                "allowedDownstreamRisk": bool(allow_downstream_risk),
                "dependencyReport": dependency_report,
                "impactReport": impact_report,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error deleting timeline feature: {e}\n{err}")
        return {"error": f"Failed to delete timeline feature: {str(e)}"}

@register_tool("export_parameters_csv")
def export_parameters_csv(csv_path):
    import csv
    try:
        if not isinstance(csv_path, str) or not csv_path:
            return {"error": "CSV path must be a non-empty string."}
        if "\x00" in csv_path:
            return {"error": "CSV path contains an invalid null byte."}
        if not os.path.isabs(csv_path):
            return {"error": "CSV path must be absolute."}

        design = get_active_design()
        csv_dir = os.path.dirname(csv_path)
        if csv_dir and not os.path.exists(csv_dir):
            os.makedirs(csv_dir, exist_ok=True)
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Expression", "Unit", "Comment"])
            for param in design.userParameters:
                writer.writerow([param.name, param.expression, param.unit, param.comment])
        return {"result": f"Successfully exported parameters to {csv_path}"}
    except Exception as e:
        return {"error": f"Failed to export parameters to CSV: {str(e)}"}

@register_tool("import_parameters_csv")
def import_parameters_csv(csv_path):
    import csv
    try:
        if not isinstance(csv_path, str) or not csv_path:
            return {"error": "CSV path must be a non-empty string."}
        if "\x00" in csv_path:
            return {"error": "CSV path contains an invalid null byte."}
        if not os.path.isabs(csv_path):
            return {"error": "CSV path must be absolute."}
        if not os.path.isfile(csv_path):
            return {"error": f"CSV file not found: {csv_path}"}

        design = get_active_design()
        updated_count = 0
        created_count = 0
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            
            for row in reader:
                if len(row) < 2:
                    continue
                name = row[0].strip()
                expression = row[1].strip()
                unit = row[2].strip() if len(row) > 2 else "mm"
                comment = row[3].strip() if len(row) > 3 else ""
                
                if not name or not expression:
                    continue
                    
                param = design.userParameters.itemByName(name)
                if param:
                    param.expression = expression
                    if comment:
                        param.comment = comment
                    updated_count += 1
                else:
                    val_input = adsk.core.ValueInput.createByString(expression)
                    design.userParameters.add(name, val_input, unit, comment)
                    created_count += 1
                    
        return {"result": f"CSV Import Complete: Created {created_count} parameters, updated {updated_count} parameters."}
    except Exception as e:
        return {"error": f"Failed to import parameters from CSV: {str(e)}"}

@register_tool("convert_mesh_to_solid")
def convert_mesh_to_solid(mesh_body_name, operation="new_body"):
    try:
        design = get_active_design()
        root = design.rootComponent
        
        # 1. Find the mesh body
        target_mesh = None
        for mesh in root.meshBodies:
            if mesh.name == mesh_body_name:
                target_mesh = mesh
                break
                
        if not target_mesh:
            for occ in root.allOccurrences:
                for mesh in occ.component.meshBodies:
                    if mesh.name == mesh_body_name:
                        target_mesh = mesh
                        break
                if target_mesh:
                    break
                    
        if not target_mesh:
            return {"error": f"Mesh body '{mesh_body_name}' not found."}
            
        # 2. Convert mesh to B-Rep
        features = root.features
        mesh_to_brep_feats = features.meshToBREPFeatures
        
        op = _operation(operation)
        mesh_to_brep_input = mesh_to_brep_feats.createInput(target_mesh, op)
        before = _capture_design_state()
        feat = mesh_to_brep_feats.add(mesh_to_brep_input)
        feat.name = f"{mesh_body_name}_Solid"
        
        return {
            "result": {
                "message": f"Successfully converted mesh body '{mesh_body_name}' to solid body '{feat.name}'",
                "featureName": feat.name,
                "meshBodyName": mesh_body_name,
                "operation": operation,
                "stateComparison": _compare_after_mutation(before),
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error converting mesh to BRep: {e}\n{err}")
        return {"error": f"Failed to convert mesh to solid: {str(e)}"}


@register_tool("edit_sketch_dimension")
def edit_sketch_dimension(sketch_name, parameter_name, expression):
    import traceback
    try:
        from .inspection import _find_sketch_by_name
    except ImportError:
        from inspection import _find_sketch_by_name

    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        
        target_dim = None
        for i in range(sketch.sketchDimensions.count):
            dim = sketch.sketchDimensions.item(i)
            if dim.parameter and dim.parameter.name == parameter_name:
                target_dim = dim
                break
                
        if not target_dim:
            try:
                idx = int(parameter_name)
                if 0 <= idx < sketch.sketchDimensions.count:
                    target_dim = sketch.sketchDimensions.item(idx)
            except ValueError:
                pass
                
        if not target_dim:
            return {"error": f"Dimension parameter '{parameter_name}' not found in sketch '{sketch_name}'."}
            
        before_param = {
            "name": target_dim.parameter.name if target_dim.parameter else None,
            "expression": target_dim.parameter.expression if target_dim.parameter else None,
            "value": getattr(target_dim.parameter, "value", None) if target_dim.parameter else None,
        }
        before_state = _capture_design_state()
        target_dim.parameter.expression = expression
        return {
            "result": {
                "message": f"Updated dimension '{parameter_name}' expression to '{expression}'.",
                "sketchName": sketch_name,
                "parameterName": parameter_name,
                "before": before_param,
                "after": {
                    "name": target_dim.parameter.name if target_dim.parameter else None,
                    "expression": target_dim.parameter.expression if target_dim.parameter else None,
                    "value": getattr(target_dim.parameter, "value", None) if target_dim.parameter else None,
                },
                "stateComparison": _compare_after_mutation(before_state),
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error editing sketch dimension: {e}\n{err}")
        return {"error": f"Failed to edit sketch dimension: {str(e)}"}


@register_tool("delete_sketch_dimension")
def delete_sketch_dimension(sketch_name, parameter_name, reason=None):
    import traceback
    try:
        from .inspection import _find_sketch_by_name
    except ImportError:
        from inspection import _find_sketch_by_name

    try:
        reason_error = _require_reason(reason, "deleting a sketch dimension")
        if reason_error:
            return reason_error

        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        
        target_dim = None
        for i in range(sketch.sketchDimensions.count):
            dim = sketch.sketchDimensions.item(i)
            if dim.parameter and dim.parameter.name == parameter_name:
                target_dim = dim
                break
                
        if not target_dim:
            try:
                idx = int(parameter_name)
                if 0 <= idx < sketch.sketchDimensions.count:
                    target_dim = sketch.sketchDimensions.item(idx)
            except ValueError:
                pass
                
        if not target_dim:
            return {"error": f"Dimension parameter '{parameter_name}' not found in sketch '{sketch_name}'."}

        before = _design_state_snapshot(include_selections=False)
        target_dim.deleteMe()
        after = _design_state_snapshot(include_selections=False)
        comparison = compare_design_state(before, after).get("result")
        return {
            "result": {
                "message": f"Successfully deleted dimension '{parameter_name}' from sketch '{sketch_name}'.",
                "sketchName": sketch_name,
                "parameterName": parameter_name,
                "reason": reason,
                "stateComparison": comparison,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error deleting sketch dimension: {e}\n{err}")
        return {"error": f"Failed to delete sketch dimension: {str(e)}"}


@register_tool("add_sketch_constraint")
def add_sketch_constraint(sketch_name, constraint_type, use_selection=True, selection_indices=None, entity_indices=None):
    import traceback
    try:
        from .inspection import _find_sketch_by_name
    except ImportError:
        from inspection import _find_sketch_by_name

    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        
        app = adsk.core.Application.get()
        ui = app.userInterface
        constraints = sketch.geometricConstraints
        
        entities = []
        if use_selection:
            active_sels = ui.activeSelections
            indices = selection_indices if selection_indices is not None else list(range(active_sels.count))
            for idx in indices:
                if 0 <= idx < active_sels.count:
                    entities.append(active_sels.item(idx).entity)
        elif entity_indices is not None:
            flat_entities = _sketch_constraint_entities(sketch)
            for idx in entity_indices:
                if 0 <= int(idx) < len(flat_entities):
                    entities.append(flat_entities[int(idx)]["entity"])

        if not entities:
            return {"error": "No valid sketch entities found for constraint."}

        before = _capture_design_state()
        c_type = constraint_type.lower()
        if c_type == "midpoint":
            if len(entities) < 2:
                return {"error": "Midpoint constraint requires 2 entities (a point and a line/arc)."}
            constraints.addMidPoint(entities[0], entities[1])
        elif c_type == "horizontal_points":
            if len(entities) < 2:
                return {"error": "Horizontal points constraint requires 2 point entities."}
            constraints.addHorizontalPoints(entities[0], entities[1])
        elif c_type == "vertical_points":
            if len(entities) < 2:
                return {"error": "Vertical points constraint requires 2 point entities."}
            constraints.addVerticalPoints(entities[0], entities[1])
        elif c_type == "coincident":
            if len(entities) < 2:
                return {"error": "Coincident constraint requires 2 entities."}
            constraints.addCoincident(entities[0], entities[1])
        elif c_type == "parallel":
            if len(entities) < 2:
                return {"error": "Parallel constraint requires 2 line entities."}
            constraints.addParallel(entities[0], entities[1])
        elif c_type == "perpendicular":
            if len(entities) < 2:
                return {"error": "Perpendicular constraint requires 2 line entities."}
            constraints.addPerpendicular(entities[0], entities[1])
        elif c_type == "tangent":
            if len(entities) < 2:
                return {"error": "Tangent constraint requires 2 entities (at least one curve)."}
            constraints.addTangent(entities[0], entities[1])
        elif c_type == "equal":
            if len(entities) < 2:
                return {"error": "Equal constraint requires 2 entities."}
            constraints.addEqual(entities[0], entities[1])
        elif c_type == "horizontal":
            constraints.addHorizontal(entities[0])
        elif c_type == "vertical":
            constraints.addVertical(entities[0])
        else:
            return {"error": f"Unsupported constraint type: {constraint_type}"}

        return {
            "result": {
                "message": f"Successfully created geometric constraint of type '{constraint_type}'.",
                "sketchName": sketch_name,
                "constraintType": constraint_type,
                "entityCount": len(entities),
                "stateComparison": _compare_after_mutation(before),
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error adding geometric constraint: {e}\n{err}")
        return {"error": f"Failed to add geometric constraint: {str(e)}"}


def _find_body_by_name(name):
    design = get_active_design()
    for body in design.rootComponent.bRepBodies:
        if body.name == name:
            return body
    for occ in design.rootComponent.allOccurrences:
        for body in occ.component.bRepBodies:
            if body.name == name:
                return body
    return None


def _sketch_constraint_entities(sketch):
    entities = []
    for i in range(getattr(getattr(sketch, "sketchPoints", None), "count", 0) or 0):
        entities.append({
            "kind": "point",
            "index": len(entities),
            "entity": sketch.sketchPoints.item(i),
        })
    curves = getattr(sketch, "sketchCurves", None)
    added_curves = 0
    for attr in (
        "sketchLines",
        "sketchCircles",
        "sketchArcs",
        "sketchEllipses",
        "sketchFittedSplines",
        "sketchFixedSplines",
        "sketchConicCurves",
    ):
        collection = getattr(curves, attr, None)
        for i in range(getattr(collection, "count", 0) or 0):
            entities.append({
                "kind": attr,
                "index": len(entities),
                "entity": collection.item(i),
            })
            added_curves += 1
    if added_curves == 0 and hasattr(curves, "count") and hasattr(curves, "item"):
        for i in range(curves.count):
            entities.append({
                "kind": "curve",
                "index": len(entities),
                "entity": curves.item(i),
            })
    return entities


@register_tool("combine_bodies")
def combine_bodies(target_body_name, tool_body_names, operation=None, keep_tool_bodies=False):
    import traceback
    try:
        design = get_active_design()
        root = design.rootComponent
        if not isinstance(operation, str) or operation.lower() not in ("join", "cut", "intersect"):
            return {"error": "operation must be explicitly set to join, cut, or intersect."}
        
        target_body = _find_body_by_name(target_body_name)
        if not target_body:
            return {"error": f"Target body '{target_body_name}' not found."}
            
        tool_bodies = []
        for name in tool_body_names:
            body = _find_body_by_name(name)
            if not body:
                return {"error": f"Tool body '{name}' not found."}
            tool_bodies.append(body)
            
        combines = root.features.combineFeatures
        tool_collection = adsk.core.ObjectCollection.create()
        for body in tool_bodies:
            if hasattr(tool_collection, "add"):
                tool_collection.add(body)
            else:
                tool_collection.append(body)
            
        op = _operation(operation)
        combine_input = combines.createInput(target_body, tool_collection)
        combine_input.operation = op
        combine_input.isKeepToolBodies = keep_tool_bodies
        
        before = _capture_design_state()
        combine_feat = combines.add(combine_input)
        combine_feat.name = f"Combine_{target_body.name}"
        
        return {
            "result": {
                "message": f"Successfully executed Boolean Combine ({operation}) on target body '{target_body_name}'.",
                "featureName": combine_feat.name,
                "targetBodyName": target_body_name,
                "toolBodyNames": tool_body_names,
                "operation": operation,
                "keepToolBodies": bool(keep_tool_bodies),
                "stateComparison": _compare_after_mutation(before),
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error combining bodies: {e}\n{err}")
        return {"error": f"Failed to combine bodies: {str(e)}"}


@register_tool("reorganize_body_to_component")
def reorganize_body_to_component(body_name, target_component_name=None, new_component_name=None):
    import traceback
    try:
        design = get_active_design()
        root = design.rootComponent
        
        body = _find_body_by_name(body_name)
        if not body:
            return {"error": f"Body '{body_name}' not found."}
            
        target_occurrence = None
        
        if new_component_name:
            transform = adsk.core.Matrix3D.create()
            new_occ = root.occurrences.addNewComponent(transform)
            new_occ.component.name = new_component_name
            target_occurrence = new_occ
        elif target_component_name:
            for occ in root.allOccurrences:
                if occ.component.name == target_component_name or occ.name == target_component_name:
                    target_occurrence = occ
                    break
            if not target_occurrence:
                return {"error": f"Target component/occurrence '{target_component_name}' not found."}
        else:
            return {"error": "Either target_component_name or new_component_name must be specified."}
            
        before = _capture_design_state()
        body.moveToComponent(target_occurrence)
        
        return {
            "result": {
                "message": f"Successfully moved body '{body_name}' to component '{target_occurrence.component.name}'.",
                "bodyName": body_name,
                "targetComponentName": target_occurrence.component.name,
                "stateComparison": _compare_after_mutation(before),
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error reorganizing body to component: {e}\n{err}")
        return {"error": f"Failed to reorganize body to component: {str(e)}"}
