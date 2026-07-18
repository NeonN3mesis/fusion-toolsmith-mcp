"""
Inspection and selection tools/resources package.
"""

import adsk.core, adsk.fusion
import importlib
import json
import math
import os
import re
import traceback
from . import register_tool, register_resource

_EXPRESSION_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_EXPRESSION_FUNCTION_NAMES = {
    "abs", "acos", "asin", "atan", "atan2", "ceil", "cos", "floor", "ln", "log",
    "max", "min", "round", "sin", "sqrt", "tan",
}

def get_active_design():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise Exception("No active Fusion 360 Design found. Ensure you are in the Design workspace.")
    return design

@register_tool("inspect_design")
def inspect_design():
    design = get_active_design()
    summary = {
        "rootComponent": design.rootComponent.name,
        "components": [occ.component.name for occ in design.rootComponent.allOccurrences],
        "units": design.unitsManager.defaultLengthUnits
    }
    return {"result": summary}


def _bbox_size_mm(bbox):
    if not bbox or not bbox.get("min") or not bbox.get("max"):
        return None
    return [round((bbox["max"][i] - bbox["min"][i]) * 10.0, 4) for i in range(3)]


def _cm_to_mm(value):
    if isinstance(value, (int, float)):
        return round(float(value) * 10.0, 4)
    return None


def _area_cm2_to_mm2(value):
    if isinstance(value, (int, float)):
        return round(float(value) * 100.0, 4)
    return None


def _length_expression_to_mm(design, expression, default_mm):
    if expression is None:
        return float(default_mm)
    if isinstance(expression, (int, float)):
        return float(expression)
    match = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*(mm|millimeter|millimeters|cm|centimeter|centimeters|in|inch|inches)?\s*", str(expression), re.IGNORECASE)
    if match:
        value = float(match.group(1))
        unit = (match.group(2) or "mm").lower()
        if unit.startswith("cm"):
            return value * 10.0
        if unit.startswith("in"):
            return value * 25.4
        return value
    value_cm = _safe_value(lambda: design.unitsManager.evaluateExpression(str(expression), "cm"))
    if value_cm is None:
        value_default_units = _safe_value(lambda: design.unitsManager.evaluateExpression(str(expression), design.unitsManager.defaultLengthUnits))
        if value_default_units is None:
            raise ValueError(f"Could not evaluate length expression: {expression}")
        value_cm = value_default_units
    return float(value_cm) * 10.0


def _axis_vector(axis):
    key = (axis or "z").lower()
    if key == "x":
        return (1.0, 0.0, 0.0)
    if key == "y":
        return (0.0, 1.0, 0.0)
    if key == "-x":
        return (-1.0, 0.0, 0.0)
    if key == "-y":
        return (0.0, -1.0, 0.0)
    if key == "-z":
        return (0.0, 0.0, -1.0)
    return (0.0, 0.0, 1.0)


def _vector_tuple(vector):
    if not vector:
        return None
    return (
        _safe_value(lambda: vector.x),
        _safe_value(lambda: vector.y),
        _safe_value(lambda: vector.z),
    )


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _unit(vector):
    if not vector or any(value is None for value in vector):
        return None
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0:
        return None
    return tuple(value / length for value in vector)


def _angle_degrees_between(a, b):
    unit_a = _unit(a)
    unit_b = _unit(b)
    if not unit_a or not unit_b:
        return None
    value = max(-1.0, min(1.0, _dot(unit_a, unit_b)))
    return math.degrees(math.acos(value))


def _name_filter(names):
    if names is None:
        return None
    if isinstance(names, str):
        return {names}
    return {str(name) for name in names}


def _slot_inference(sketch, bbox):
    counts = _curve_counts(sketch)
    if counts.get("lines") != 2 or counts.get("arcs") != 2:
        return None
    arcs = _collection_items(_safe_value(lambda: sketch.sketchCurves.sketchArcs))
    radii = [_safe_value(lambda arc=arc: arc.radius) for arc in arcs]
    radii = [radius for radius in radii if isinstance(radius, (int, float))]
    size = _bbox_size_mm(bbox)
    return {
        "kind": "rounded_slot_candidate",
        "confidence": "medium",
        "reason": "Sketch has two lines and two arcs.",
        "sizeMm": size,
        "averageRadiusMm": round((sum(radii) / len(radii)) * 10.0, 4) if radii else None,
    }


@register_tool("extract_reference_dimensions")
def extract_reference_dimensions(body_names=None, sketch_names=None, include_parameters=True, infer_slots=True):
    """
    Read-only dimensional summary for recreating reference geometry with structured tools.
    Values derived from Fusion bounding boxes are reported in millimeters.
    """
    design = get_active_design()
    root = design.rootComponent
    body_filter = _name_filter(body_names)
    sketch_filter = _name_filter(sketch_names)

    bodies = []
    sketches = []
    for component in _component_snapshots(root):
        component_name = component.get("name")
        for body in _collection_items(_safe_value(lambda component_name=component_name: _find_component_by_name(root, component_name).bRepBodies)):
            body_name = _safe_value(lambda body=body: body.name)
            if body_filter and body_name not in body_filter:
                continue
            bbox = _bbox_to_dict(body)
            bodies.append({
                "name": body_name,
                "componentName": component_name,
                "boundingBox": bbox,
                "sizeMm": _bbox_size_mm(bbox),
                "isVisible": _safe_value(lambda body=body: body.isVisible),
                "isSolid": _safe_value(lambda body=body: body.isSolid),
            })

        component_obj = _find_component_by_name(root, component_name)
        for sketch in _collection_items(_safe_value(lambda component_obj=component_obj: component_obj.sketches)):
            sketch_name = _safe_value(lambda sketch=sketch: sketch.name)
            if sketch_filter and sketch_name not in sketch_filter:
                continue
            bbox = _bbox_to_dict(sketch)
            sketch_data = {
                "name": sketch_name,
                "componentName": component_name,
                "boundingBox": bbox,
                "sizeMm": _bbox_size_mm(bbox),
                "isVisible": _safe_value(lambda sketch=sketch: sketch.isVisible),
                "isFullyConstrained": _safe_value(lambda sketch=sketch: sketch.isFullyConstrained),
                "curveCounts": _curve_counts(sketch),
                "dimensionCount": len(_collection_items(_safe_value(lambda sketch=sketch: sketch.sketchDimensions))),
            }
            if infer_slots:
                slot = _slot_inference(sketch, bbox)
                if slot:
                    sketch_data["inference"] = slot
            sketches.append(sketch_data)

    parameters = []
    if include_parameters:
        parameters = [
            _parameter_snapshot(param, "user")
            for param in _collection_items(_safe_value(lambda: design.userParameters))
        ]

    return {
        "result": {
            "units": design.unitsManager.defaultLengthUnits,
            "bodyCount": len(bodies),
            "sketchCount": len(sketches),
            "bodies": sorted(bodies, key=lambda item: (item.get("componentName") or "", item.get("name") or "")),
            "sketches": sorted(sketches, key=lambda item: (item.get("componentName") or "", item.get("name") or "")),
            "parameters": sorted(parameters, key=lambda item: item.get("name") or ""),
            "notes": [
                "boundingBox values use Fusion internal model units; sizeMm is converted for agent planning.",
                "slot inference is geometric best-effort and should be verified before cutting production geometry.",
            ],
        }
    }


def _warning(code, severity, body_name, message, evidence=None, suggestion=None):
    warning = {
        "code": code,
        "severity": severity,
        "bodyName": body_name,
        "message": message,
    }
    if evidence:
        warning["evidence"] = evidence
    if suggestion:
        warning["suggestion"] = suggestion
    return warning


def _body_size_warning(body_name, size_mm, min_wall_mm, min_slot_mm, min_feature_mm):
    if not size_mm:
        return []
    sorted_size = sorted(size_mm)
    warnings = []
    min_dim = sorted_size[0]
    mid_dim = sorted_size[1] if len(sorted_size) > 1 else None
    max_dim = sorted_size[-1]
    if min_dim < min_feature_mm:
        warnings.append(_warning(
            "tiny_body_dimension",
            "high",
            body_name,
            "One body bounding-box dimension is smaller than the configured minimum feature size.",
            {"sizeMm": size_mm, "minimumFeatureMm": min_feature_mm},
            "Increase the feature size or expect it to be lost or weak after slicing.",
        ))
    elif min_dim < min_wall_mm and max_dim >= min_wall_mm * 3:
        warnings.append(_warning(
            "thin_wall_candidate",
            "medium",
            body_name,
            "One body bounding-box dimension is below the configured minimum wall thickness.",
            {"sizeMm": size_mm, "minimumWallMm": min_wall_mm},
            "Verify this is an intentional wall and that it is at least 2-3 extrusion widths.",
        ))
    if min_dim < min_slot_mm and mid_dim and max_dim >= min_slot_mm * 4:
        warnings.append(_warning(
            "narrow_slot_or_gap_candidate",
            "medium",
            body_name,
            "Body proportions include a narrow dimension that may represent a slot, gap, rib, or thin flange.",
            {"sizeMm": size_mm, "minimumSlotMm": min_slot_mm},
            "Check slicer preview for merged walls or missing clearance.",
        ))
    return warnings


def _edge_warnings(body, body_name, min_feature_mm, max_items):
    warnings = []
    short_edges = []
    for index, edge in enumerate(_collection_items(_safe_value(lambda: body.edges))):
        length = _edge_length(edge)
        length_mm = _cm_to_mm(length)
        if length_mm is not None and length_mm < min_feature_mm:
            short_edges.append({"index": index, "lengthMm": length_mm})
        if len(short_edges) >= max_items:
            break
    if short_edges:
        warnings.append(_warning(
            "tiny_edge_features",
            "medium",
            body_name,
            "Short BRep edges may indicate tiny details, slivers, or tight notches that are hard to print cleanly.",
            {"minimumFeatureMm": min_feature_mm, "edges": short_edges},
            "Inspect these edges and simplify or enlarge them if they matter functionally.",
        ))
    return warnings


def _face_radius_mm(face):
    geometry = _safe_value(lambda: face.geometry)
    radius = _safe_value(lambda: geometry.radius)
    if radius is None:
        cylinder = _safe_value(lambda: geometry.cylinder)
        radius = _safe_value(lambda: cylinder.radius)
    return _cm_to_mm(radius)


def _face_normal(face):
    geometry = _safe_value(lambda: face.geometry)
    normal = _vector_tuple(_safe_value(lambda: geometry.normal))
    if normal:
        return normal
    plane = _safe_value(lambda: geometry.plane)
    return _vector_tuple(_safe_value(lambda: plane.normal))


def _face_warnings(body, body_name, min_hole_mm, overhang_angle_degrees, build_axis, max_items):
    warnings = []
    small_round_faces = []
    risky_down_faces = []
    axis = _axis_vector(build_axis)
    overhang_cutoff = 180.0 - float(overhang_angle_degrees)

    for index, face in enumerate(_collection_items(_safe_value(lambda: body.faces))):
        radius_mm = _face_radius_mm(face)
        if radius_mm is not None:
            diameter_mm = round(radius_mm * 2.0, 4)
            if diameter_mm < min_hole_mm:
                small_round_faces.append({
                    "index": index,
                    "diameterMm": diameter_mm,
                    "geometryType": _safe_value(lambda face=face: face.geometry.objectType),
                })

        normal = _face_normal(face)
        angle = _angle_degrees_between(normal, axis)
        if angle is not None and angle >= overhang_cutoff:
            risky_down_faces.append({
                "index": index,
                "normal": [round(value, 4) for value in _unit(normal)],
                "angleFromBuildAxisDegrees": round(angle, 2),
                "areaMm2": _area_cm2_to_mm2(_safe_value(lambda face=face: face.area)),
            })

        if len(small_round_faces) >= max_items and len(risky_down_faces) >= max_items:
            break

    if small_round_faces:
        warnings.append(_warning(
            "small_hole_or_pin_candidate",
            "medium",
            body_name,
            "Cylindrical or rounded faces are below the configured minimum printable hole/pin diameter.",
            {"minimumHoleDiameterMm": min_hole_mm, "faces": small_round_faces[:max_items]},
            "Enlarge functional holes, add tolerance, or plan cleanup with a drill/reamer.",
        ))
    if risky_down_faces:
        warnings.append(_warning(
            "risky_overhang_or_lip_candidate",
            "medium",
            body_name,
            "Downward-facing planar faces may create unsupported lips, bridges, or overhangs.",
            {"overhangAngleDegrees": overhang_angle_degrees, "buildAxis": build_axis, "faces": risky_down_faces[:max_items]},
            "Reorient the part, add chamfers/fillets, split the model, or plan supports where needed.",
        ))
    return warnings


def _point_mm(point):
    if not point:
        return None
    return (
        _safe_value(lambda: point.x, 0.0) * 10.0,
        _safe_value(lambda: point.y, 0.0) * 10.0,
        _safe_value(lambda: point.z, 0.0) * 10.0,
    )


def _distance_mm(a, b):
    if not a or not b:
        return None
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _triangle_area_mm2(a, b, c):
    if not a or not b or not c:
        return None
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return 0.5 * math.sqrt(sum(value * value for value in cross))


def _triangle_normal(a, b, c):
    if not a or not b or not c:
        return None
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return _unit((
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    ))


def _triangle_mesh(body, quality):
    direct = _safe_value(lambda: body.triangleMesh)
    if direct:
        return direct
    direct = _safe_value(lambda: body.mesh)
    if direct:
        return direct
    manager = _safe_value(lambda: body.meshManager)
    calculator = _safe_value(lambda: manager.createMeshCalculator()) if manager else None
    if not calculator:
        return None
    for setter in ("setQuality", "quality"):
        try:
            if setter == "setQuality":
                calculator.setQuality(quality)
            else:
                setattr(calculator, "quality", quality)
        except Exception:
            pass
    return _safe_value(lambda: calculator.calculate())


def _mesh_points(mesh):
    for attr in ("nodeCoordinates", "coordinates", "vertices", "nodes"):
        points = _collection_items(_safe_value(lambda attr=attr: getattr(mesh, attr)))
        if points:
            return [_point_mm(point) for point in points]
    return []


def _mesh_indices(mesh):
    for attr in ("triangleNodeIndices", "nodeIndices", "indices", "triangles"):
        values = _collection_items(_safe_value(lambda attr=attr: getattr(mesh, attr)))
        if values:
            flattened = []
            for value in values:
                if isinstance(value, (list, tuple)):
                    flattened.extend(int(item) for item in value)
                else:
                    flattened.append(int(value))
            return flattened
    return []


def _mesh_printability_analysis(body, body_name, thresholds, max_items, mesh_quality):
    mesh = _triangle_mesh(body, mesh_quality)
    if not mesh:
        return {
            "status": "unavailable",
            "reason": "Fusion did not expose triangle mesh data for this body in the current runtime.",
        }, []

    points = _mesh_points(mesh)
    indices = _mesh_indices(mesh)
    if not points or len(indices) < 3:
        return {
            "status": "unavailable",
            "reason": "Triangle mesh was available but did not expose node coordinates and triangle indices.",
        }, []

    axis = _axis_vector(thresholds["buildAxis"])
    overhang_cutoff = 180.0 - float(thresholds["overhangAngleDegrees"])
    min_edge_mm = None
    max_edge_mm = None
    tiny_edges = []
    overhangs = []
    triangle_count = 0
    total_area = 0.0

    for i in range(0, len(indices) - 2, 3):
        try:
            a = points[indices[i]]
            b = points[indices[i + 1]]
            c = points[indices[i + 2]]
        except Exception:
            continue
        triangle_count += 1
        lengths = [_distance_mm(a, b), _distance_mm(b, c), _distance_mm(c, a)]
        lengths = [length for length in lengths if length is not None]
        if lengths:
            tri_min = min(lengths)
            tri_max = max(lengths)
            min_edge_mm = tri_min if min_edge_mm is None else min(min_edge_mm, tri_min)
            max_edge_mm = tri_max if max_edge_mm is None else max(max_edge_mm, tri_max)
            if tri_min < thresholds["minimumFeatureSizeMm"] and len(tiny_edges) < max_items:
                tiny_edges.append({"triangleIndex": triangle_count - 1, "minimumEdgeMm": round(tri_min, 4)})
        area = _triangle_area_mm2(a, b, c)
        if area is not None:
            total_area += area
        normal = _triangle_normal(a, b, c)
        angle = _angle_degrees_between(normal, axis)
        if angle is not None and angle >= overhang_cutoff and len(overhangs) < max_items:
            overhangs.append({
                "triangleIndex": triangle_count - 1,
                "angleFromBuildAxisDegrees": round(angle, 2),
                "areaMm2": round(area, 4) if area is not None else None,
            })

    warnings = []
    if tiny_edges:
        warnings.append(_warning(
            "mesh_tiny_triangle_edges",
            "medium",
            body_name,
            "Triangle mesh contains edges below the configured minimum feature size.",
            {"minimumFeatureMm": thresholds["minimumFeatureSizeMm"], "triangles": tiny_edges},
            "Inspect slicer preview for slivers, disappearing details, or over-tessellated geometry.",
        ))
    if overhangs:
        warnings.append(_warning(
            "mesh_overhang_triangles",
            "medium",
            body_name,
            "Triangle mesh contains downward-facing facets beyond the configured overhang angle.",
            {"overhangAngleDegrees": thresholds["overhangAngleDegrees"], "buildAxis": thresholds["buildAxis"], "triangles": overhangs},
            "Confirm support and bridge behavior in the slicer preview.",
        ))

    return {
        "status": "analyzed",
        "quality": mesh_quality,
        "triangleCount": triangle_count,
        "nodeCount": len(points),
        "surfaceAreaMm2Approx": round(total_area, 4),
        "minimumTriangleEdgeMm": round(min_edge_mm, 4) if min_edge_mm is not None else None,
        "maximumTriangleEdgeMm": round(max_edge_mm, 4) if max_edge_mm is not None else None,
        "sampledWarningCount": len(warnings),
    }, warnings


def _printability_body_report(body, component_name, thresholds, max_items, include_mesh_analysis, mesh_quality):
    body_name = _safe_value(lambda: body.name)
    bbox = _bbox_to_dict(body)
    size_mm = _bbox_size_mm(bbox)
    physical_props = _safe_value(lambda: body.physicalProperties)
    warnings = []
    warnings.extend(_body_size_warning(
        body_name,
        size_mm,
        thresholds["minimumWallThicknessMm"],
        thresholds["minimumSlotWidthMm"],
        thresholds["minimumFeatureSizeMm"],
    ))
    warnings.extend(_edge_warnings(body, body_name, thresholds["minimumFeatureSizeMm"], max_items))
    warnings.extend(_face_warnings(
        body,
        body_name,
        thresholds["minimumHoleDiameterMm"],
        thresholds["overhangAngleDegrees"],
        thresholds["buildAxis"],
        max_items,
    ))
    mesh_analysis = {"status": "disabled"}
    if include_mesh_analysis:
        mesh_analysis, mesh_warnings = _mesh_printability_analysis(body, body_name, thresholds, max_items, mesh_quality)
        warnings.extend(mesh_warnings)
    return {
        "name": body_name,
        "componentName": component_name,
        "isVisible": _safe_value(lambda: body.isVisible),
        "isSolid": _safe_value(lambda: body.isSolid),
        "boundingBox": bbox,
        "sizeMm": size_mm,
        "volumeMm3": round(_safe_value(lambda: physical_props.volume, 0) * 1000.0, 4) if physical_props else None,
        "areaMm2": round(_safe_value(lambda: physical_props.area, 0) * 100.0, 4) if physical_props else None,
        "faceCount": _collection_count(_safe_value(lambda: body.faces)),
        "edgeCount": _collection_count(_safe_value(lambda: body.edges)),
        "meshAnalysis": mesh_analysis,
        "warnings": warnings,
    }


def _iter_mesh_bodies(root):
    component_entries = [(root, None)]
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        if component:
            component_entries.append((component, occ))
    seen = set()
    for component, occ in component_entries:
        component_name = _safe_value(lambda component=component: component.name)
        occurrence_name = _safe_value(lambda occ=occ: occ.name) if occ else None
        for mesh_body in _collection_items(_safe_value(lambda component=component: component.meshBodies)):
            token = _safe_value(lambda mesh_body=mesh_body: mesh_body.entityToken)
            identity = token or id(mesh_body)
            if identity in seen:
                continue
            seen.add(identity)
            yield component, component_name, occurrence_name, mesh_body


def _mesh_body_snapshot(mesh_body, component_name, occurrence_name=None, mesh_quality="low"):
    mesh = _triangle_mesh(mesh_body, mesh_quality)
    points = _mesh_points(mesh) if mesh else []
    indices = _mesh_indices(mesh) if mesh else []
    node_count = len(points) if points else _safe_value(lambda: mesh.nodeCount if mesh else None)
    triangle_count = len(indices) // 3 if indices else _safe_value(lambda: mesh.triangleCount if mesh else None)
    bbox = _bbox_to_dict(mesh_body)
    return {
        "name": _safe_value(lambda: mesh_body.name),
        "componentName": component_name,
        "occurrenceName": occurrence_name,
        "entityToken": _safe_value(lambda: mesh_body.entityToken),
        "isVisible": _safe_value(lambda: mesh_body.isVisible),
        "isLightBulbOn": _safe_value(lambda: mesh_body.isLightBulbOn),
        "objectType": _safe_value(lambda: mesh_body.objectType),
        "boundingBox": bbox,
        "sizeMm": _bbox_size_mm(bbox),
        "meshAnalysis": {
            "status": "available" if mesh else "unavailable",
            "quality": mesh_quality,
            "nodeCount": node_count,
            "triangleCount": triangle_count,
            "indexCount": len(indices) if indices else None,
        },
        "conversionBlockers": [
            "Run plan_mesh_conversion with explicit target, intent, operation, quality-loss acknowledgement, and reason before conversion.",
        ],
    }


def _mesh_conversion_capabilities(root):
    features = _safe_value(lambda: root.features)
    return {
        "meshToBrepAvailable": bool(_safe_value(lambda: features.meshToBREPFeatures) if features else None),
        "repairAvailable": bool(_safe_value(lambda: features.meshRepairFeatures) if features else None),
        "reduceAvailable": bool(_safe_value(lambda: features.meshReduceFeatures) if features else None),
        "remeshAvailable": bool(_safe_value(lambda: features.remeshFeatures) if features else None),
    }


@register_tool("inspect_mesh_bodies")
def inspect_mesh_bodies(body_names=None, include_invisible=False, mesh_quality="low"):
    """
    Read-only inspection of mesh bodies before any mesh conversion or repair workflow.
    """
    try:
        design = get_active_design()
        root = design.rootComponent
        name_filter = _name_filter(body_names)
        mesh_quality = str(mesh_quality or "low")
        mesh_bodies = []
        skipped = []

        for _component, component_name, occurrence_name, mesh_body in _iter_mesh_bodies(root):
            name = _safe_value(lambda mesh_body=mesh_body: mesh_body.name)
            visible = _safe_value(lambda mesh_body=mesh_body: mesh_body.isVisible, True)
            if name_filter and name not in name_filter:
                continue
            if not include_invisible and visible is False:
                skipped.append({"name": name, "componentName": component_name, "reason": "invisible"})
                continue
            mesh_bodies.append(_mesh_body_snapshot(mesh_body, component_name, occurrence_name, mesh_quality))

        return {
            "result": {
                "readOnly": True,
                "units": _safe_value(lambda: design.unitsManager.defaultLengthUnits),
                "meshBodyCount": len(mesh_bodies),
                "meshBodies": sorted(mesh_bodies, key=lambda item: (item.get("componentName") or "", item.get("name") or "")),
                "skippedBodies": skipped,
                "conversionCapabilities": _mesh_conversion_capabilities(root),
                "notes": [
                    "This tool does not convert or repair mesh bodies.",
                    "Mesh-to-BRep conversion can lose detail and should be gated by plan_mesh_conversion.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting mesh bodies: {e}\n{err}")
        return {"error": f"Failed to inspect mesh bodies: {str(e)}"}


@register_tool("plan_mesh_conversion")
def plan_mesh_conversion(body_name=None, body_entity_token=None, conversion_intent="convert_to_brep", operation="new_body", tolerance=None, detail_level=None, acknowledge_quality_loss=False, reason=None):
    """
    Read-only preflight for mesh conversion, repair, reduction, or remeshing.
    """
    try:
        design = get_active_design()
        root = design.rootComponent
        intent = str(conversion_intent or "convert_to_brep")
        op = str(operation or "new_body")
        blockers = []
        warnings = []
        supported_intents = {"convert_to_brep", "repair_mesh", "reduce_mesh", "remesh"}
        supported_operations = {"new_body", "join", "cut"}

        if intent not in supported_intents:
            blockers.append(f"Unsupported conversion_intent '{intent}'. Use one of: {', '.join(sorted(supported_intents))}.")
        if op not in supported_operations:
            blockers.append(f"Unsupported operation '{op}'. Use one of: {', '.join(sorted(supported_operations))}.")
        if not body_name and not body_entity_token:
            blockers.append("Provide body_name or body_entity_token from inspect_mesh_bodies.")
        if not reason:
            blockers.append("Provide a reason explaining why mesh conversion or repair is needed.")
        if not acknowledge_quality_loss:
            blockers.append("Set acknowledge_quality_loss=true after accepting that mesh conversion can lose detail or create heavy BRep geometry.")

        matches = []
        for _component, component_name, occurrence_name, mesh_body in _iter_mesh_bodies(root):
            name = _safe_value(lambda mesh_body=mesh_body: mesh_body.name)
            token = _safe_value(lambda mesh_body=mesh_body: mesh_body.entityToken)
            if (body_name and name == body_name) or (body_entity_token and token == body_entity_token):
                matches.append(_mesh_body_snapshot(mesh_body, component_name, occurrence_name, "low"))

        if body_name or body_entity_token:
            if not matches:
                blockers.append("Target mesh body was not found in the active design.")
            elif len(matches) > 1:
                blockers.append("Target matched multiple mesh bodies; use body_entity_token for an exact target.")

        capabilities = _mesh_conversion_capabilities(root)
        capability_key = {
            "convert_to_brep": "meshToBrepAvailable",
            "repair_mesh": "repairAvailable",
            "reduce_mesh": "reduceAvailable",
            "remesh": "remeshAvailable",
        }.get(intent)
        if capability_key and not capabilities.get(capability_key):
            blockers.append(f"Fusion runtime does not expose a compatible {intent} API surface.")

        if intent == "convert_to_brep":
            warnings.append("Mesh-to-BRep conversion may create very large timeline features; inspect triangle count before proceeding.")

        return {
            "result": {
                "readOnly": True,
                "ready": len(blockers) == 0,
                "blockers": blockers,
                "warnings": warnings,
                "target": matches[0] if len(matches) == 1 else None,
                "conversionCapabilities": capabilities,
                "normalizedRequest": {
                    "conversionIntent": intent,
                    "operation": op,
                    "tolerance": tolerance,
                    "detailLevel": detail_level,
                    "acknowledgeQualityLoss": bool(acknowledge_quality_loss),
                    "reason": reason,
                },
                "notes": [
                    "This preflight does not mutate the design.",
                    "Run inspect_mesh_bodies first and use entity-token targeting when names are ambiguous.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error planning mesh conversion: {e}\n{err}")
        return {"error": f"Failed to plan mesh conversion: {str(e)}"}


@register_tool("inspect_printability")
def inspect_printability(body_names=None, include_invisible=False, build_axis="z", nozzle_diameter="0.4 mm", layer_height="0.2 mm", minimum_wall_thickness=None, minimum_hole_diameter="2.0 mm", minimum_slot_width="1.0 mm", minimum_feature_size=None, overhang_angle_degrees=45, max_items_per_warning=25, include_mesh_analysis=True, mesh_quality="low"):
    """
    Read-only FDM printability sanity report.

    This is intentionally heuristic. It reports candidates for human review and
    slicer verification; it does not mutate geometry or claim printability.
    """
    try:
        design = get_active_design()
        root = design.rootComponent
        body_filter = _name_filter(body_names)
        nozzle_mm = _length_expression_to_mm(design, nozzle_diameter, 0.4)
        layer_mm = _length_expression_to_mm(design, layer_height, 0.2)
        min_wall_mm = _length_expression_to_mm(design, minimum_wall_thickness, nozzle_mm * 3.0)
        min_feature_mm = _length_expression_to_mm(design, minimum_feature_size, max(nozzle_mm, layer_mm * 2.0))
        thresholds = {
            "buildAxis": build_axis or "z",
            "nozzleDiameterMm": round(nozzle_mm, 4),
            "layerHeightMm": round(layer_mm, 4),
            "minimumWallThicknessMm": round(min_wall_mm, 4),
            "minimumHoleDiameterMm": round(_length_expression_to_mm(design, minimum_hole_diameter, 2.0), 4),
            "minimumSlotWidthMm": round(_length_expression_to_mm(design, minimum_slot_width, 1.0), 4),
            "minimumFeatureSizeMm": round(min_feature_mm, 4),
            "overhangAngleDegrees": float(overhang_angle_degrees),
        }
        max_items = max(1, min(int(max_items_per_warning or 25), 200))
        mesh_quality = str(mesh_quality or "low")

        bodies = []
        skipped = []
        for body, component_name in _body_objects(root):
            body_name = _safe_value(lambda body=body: body.name)
            if body_filter and body_name not in body_filter:
                continue
            if not include_invisible and _safe_value(lambda body=body: body.isVisible) is False:
                skipped.append({"name": body_name, "componentName": component_name, "reason": "hidden"})
                continue
            bodies.append(_printability_body_report(
                body,
                component_name,
                thresholds,
                max_items,
                bool(include_mesh_analysis),
                mesh_quality,
            ))

        all_warnings = [warning for body in bodies for warning in body.get("warnings", [])]
        severity_rank = {"high": 3, "medium": 2, "low": 1}
        highest = "none"
        if all_warnings:
            highest = max((warning["severity"] for warning in all_warnings), key=lambda level: severity_rank.get(level, 0))
        return {
            "result": {
                "readOnly": True,
                "units": design.unitsManager.defaultLengthUnits,
                "bodyCount": len(bodies),
                "warningCount": len(all_warnings),
                "riskLevel": highest,
                "thresholds": thresholds,
                "bodies": sorted(bodies, key=lambda item: (item.get("componentName") or "", item.get("name") or "")),
                "warnings": all_warnings,
                "skippedBodies": skipped,
                "limitations": [
                    "Heuristic report only; verify final results in the slicer preview.",
                    "Thin walls, narrow slots, and unsupported regions are inferred from BRep/bounding-box hints and may include false positives.",
                    "Hole warnings are based on rounded or cylindrical face radii when Fusion exposes them.",
                    "Mesh analysis uses Fusion-exposed triangle mesh data when available; it is still not a replacement for slicer simulation.",
                ],
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting printability: {e}\n{err}")
        return {"error": f"Failed to inspect printability: {str(e)}"}


def _find_component_by_name(root, component_name):
    if _safe_value(lambda: root.name) == component_name:
        return root
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        if _safe_value(lambda component=component: component.name) == component_name:
            return component
    return root


def _document_snapshot(app):
    documents = []
    for index, doc in enumerate(_collection_items(_safe_value(lambda: app.documents))):
        documents.append({
            "index": index,
            "name": _safe_value(lambda doc=doc: doc.name),
            "isModified": _safe_value(lambda doc=doc: doc.isModified),
            "isActive": doc == _safe_value(lambda: app.activeDocument),
        })
    active_doc = _safe_value(lambda: app.activeDocument)
    return {
        "active": {
            "name": _safe_value(lambda: active_doc.name),
            "isModified": _safe_value(lambda: active_doc.isModified),
        } if active_doc else None,
        "openDocuments": documents,
        "openDocumentCount": len(documents),
    }


def _parameter_snapshot(parameter, parameter_type):
    return {
        "name": _safe_value(lambda: parameter.name),
        "parameterType": parameter_type,
        "expression": _safe_value(lambda: parameter.expression),
        "value": _safe_value(lambda: parameter.value),
        "unit": _safe_value(lambda: parameter.unit),
        "role": _safe_value(lambda: parameter.role),
        "isFavorite": _safe_value(lambda: parameter.isFavorite),
    }


def _parameters_snapshot(design):
    user_parameters = [
        _parameter_snapshot(param, "user")
        for param in _collection_items(_safe_value(lambda: design.userParameters))
    ]
    model_parameters = [
        _parameter_snapshot(param, "model")
        for param in _collection_items(_safe_value(lambda: design.allParameters))
    ]
    return {
        "user": sorted(user_parameters, key=lambda p: p.get("name") or ""),
        "model": sorted(model_parameters, key=lambda p: p.get("name") or ""),
    }


def _component_signature(component, occurrence=None):
    return {
        "name": _safe_value(lambda: component.name),
        "occurrenceName": _safe_value(lambda: occurrence.name) if occurrence else None,
        "bodyCount": len(_collection_items(_safe_value(lambda: component.bRepBodies))),
        "sketchCount": len(_collection_items(_safe_value(lambda: component.sketches))),
        "occurrenceCount": len(_collection_items(_safe_value(lambda: component.occurrences))),
    }


def _component_snapshots(root):
    components = [_component_signature(root)]
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        if component:
            components.append(_component_signature(component, occ))
    return sorted(components, key=lambda c: (c.get("occurrenceName") or "", c.get("name") or ""))


def _body_snapshot(body, component_name):
    physical_props = _safe_value(lambda: body.physicalProperties)
    return {
        "key": f"{component_name}/{_safe_value(lambda: body.name)}",
        "name": _safe_value(lambda: body.name),
        "componentName": component_name,
        "isVisible": _safe_value(lambda: body.isVisible),
        "isSolid": _safe_value(lambda: body.isSolid),
        "entityToken": _safe_value(lambda: body.entityToken),
        "boundingBox": _bbox_to_dict(body),
        "volume": _safe_value(lambda: physical_props.volume) if physical_props else None,
        "area": _safe_value(lambda: physical_props.area) if physical_props else None,
    }


def _body_snapshots(root):
    bodies = []
    root_name = _safe_value(lambda: root.name)
    for body in _collection_items(_safe_value(lambda: root.bRepBodies)):
        bodies.append(_body_snapshot(body, root_name))
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        component_name = _safe_value(lambda component=component: component.name)
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            bodies.append(_body_snapshot(body, component_name))
    return sorted(bodies, key=lambda b: b.get("key") or "")


def _body_objects(root):
    bodies = []
    root_name = _safe_value(lambda: root.name)
    for body in _collection_items(_safe_value(lambda: root.bRepBodies)):
        bodies.append((body, root_name))
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        component_name = _safe_value(lambda component=component: component.name)
        for body in _collection_items(_safe_value(lambda component=component: component.bRepBodies)):
            bodies.append((body, component_name))
    return bodies


def _body_matches_name(body, component_name, requested_name):
    if not requested_name:
        return True
    body_name = _safe_value(lambda: body.name)
    key = f"{component_name}/{body_name}"
    return requested_name in (body_name, key)


def _body_matches_token(body, entity_token):
    if not entity_token:
        return True
    return _safe_value(lambda: body.entityToken) == entity_token


def _resolve_bodies(body_name=None, body_entity_token=None, include_all=False):
    design = get_active_design()
    include_everything = bool(include_all) or (body_name is None and body_entity_token is None)
    bodies = []
    for body, component_name in _body_objects(design.rootComponent):
        if include_everything:
            bodies.append((body, component_name))
            continue
        if _body_matches_name(body, component_name, body_name) and _body_matches_token(body, body_entity_token):
            bodies.append((body, component_name))
    return bodies


def _physical_properties_report(body, component_name):
    props = _safe_value(lambda: body.physicalProperties)
    material = _safe_value(lambda: body.physicalMaterial)
    appearance = _safe_value(lambda: body.appearance)
    bbox = _bbox_to_dict(body)
    center = _safe_value(lambda: props.centerOfMass) if props else None
    mass = _safe_value(lambda: props.mass) if props else None
    volume = _safe_value(lambda: props.volume) if props else None
    area = _safe_value(lambda: props.area) if props else None
    density = _safe_value(lambda: props.density) if props else None
    return {
        "bodyName": _safe_value(lambda: body.name),
        "componentName": component_name,
        "entityToken": _safe_value(lambda: body.entityToken),
        "isVisible": _safe_value(lambda: body.isVisible),
        "isSolid": _safe_value(lambda: body.isSolid),
        "boundingBox": bbox,
        "boundingBoxSizeMm": _bbox_size_mm(bbox),
        "massKg": mass,
        "volumeCm3": volume,
        "volumeMm3": round(volume * 1000.0, 6) if isinstance(volume, (int, float)) else None,
        "areaCm2": area,
        "areaMm2": round(area * 100.0, 6) if isinstance(area, (int, float)) else None,
        "densityKgPerCm3": density,
        "centerOfMassCm": _point_to_list(center),
        "centerOfMassMm": [round(value * 10.0, 6) for value in _point_to_list(center)] if center else None,
        "physicalMaterial": _entity_ref(material),
        "appearance": _entity_ref(appearance),
        "warnings": [] if props else ["Fusion did not expose physicalProperties for this body."],
    }


def _rule_report(rule, index=None, active=False):
    if not rule:
        return None
    fields = {
        "index": index,
        "active": bool(active),
        "name": _safe_value(lambda: rule.name),
        "objectType": _safe_value(lambda: rule.objectType),
        "entityToken": _safe_value(lambda: rule.entityToken),
        "thicknessExpression": _safe_value(lambda: rule.thickness.expression),
        "thicknessValue": _safe_value(lambda: rule.thickness.value),
        "bendRadiusExpression": _safe_value(lambda: rule.bendRadius.expression),
        "bendRadiusValue": _safe_value(lambda: rule.bendRadius.value),
        "kFactorExpression": _safe_value(lambda: rule.kFactor.expression),
        "kFactorValue": _safe_value(lambda: rule.kFactor.value),
        "reliefWidthExpression": _safe_value(lambda: rule.reliefWidth.expression),
        "reliefDepthExpression": _safe_value(lambda: rule.reliefDepth.expression),
        "description": _safe_value(lambda: rule.description),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _body_sheet_metal_report(body, component_name):
    object_type = str(_safe_value(lambda: body.objectType) or "")
    is_sheet_metal = _safe_value(lambda: body.isSheetMetal)
    if is_sheet_metal is None:
        is_sheet_metal = "sheetmetal" in object_type.replace(" ", "").lower()
    return {
        "bodyName": _safe_value(lambda: body.name),
        "componentName": component_name,
        "entityToken": _safe_value(lambda: body.entityToken),
        "objectType": object_type or None,
        "isVisible": _safe_value(lambda: body.isVisible),
        "isSolid": _safe_value(lambda: body.isSolid),
        "isSheetMetal": bool(is_sheet_metal),
        "boundingBox": _bbox_to_dict(body),
    }


def _surface_body_report(body, component_name, include_edges=False):
    faces = _collection_items(_safe_value(lambda: body.faces))
    edges = _collection_items(_safe_value(lambda: body.edges))
    is_solid = _safe_value(lambda: body.isSolid)
    open_edges = []
    for index, edge in enumerate(edges):
        adjacent_faces = _collection_items(_safe_value(lambda edge=edge: edge.faces))
        face_count = len(adjacent_faces)
        if face_count and face_count >= 2:
            continue
        if face_count == 0:
            co_edges = _collection_items(_safe_value(lambda edge=edge: edge.coEdges))
            face_count = len(co_edges)
            if face_count >= 2:
                continue
        entry = {
            "index": index,
            "name": _safe_value(lambda edge=edge: edge.name),
            "entityToken": _safe_value(lambda edge=edge: edge.entityToken),
            "objectType": _safe_value(lambda edge=edge: edge.objectType),
            "adjacentFaceCount": face_count,
            "length": _safe_value(lambda edge=edge: edge.length),
        }
        open_edges.append({key: value for key, value in entry.items() if value is not None})
    candidate_repairs = []
    if is_solid is False:
        candidate_repairs.extend(["patch_surface", "stitch_surfaces", "thicken_surface"])
        if open_edges:
            candidate_repairs.extend(["extend_surface", "trim_surface"])
    return {
        "bodyName": _safe_value(lambda: body.name),
        "componentName": component_name,
        "entityToken": _safe_value(lambda: body.entityToken),
        "objectType": _safe_value(lambda: body.objectType),
        "isVisible": _safe_value(lambda: body.isVisible),
        "isSolid": is_solid,
        "classification": "solid" if is_solid else "surface",
        "faceCount": len(faces),
        "edgeCount": len(edges),
        "openEdgeCount": len(open_edges),
        "openEdges": open_edges if include_edges else open_edges[:10],
        "openEdgesTruncated": (not include_edges and len(open_edges) > 10),
        "boundingBox": _bbox_to_dict(body),
        "candidateRepairTools": candidate_repairs,
        "warnings": [] if is_solid is not None else ["Fusion did not expose isSolid for this body; classification is best-effort."],
    }


def _active_manufacturing_product():
    app = adsk.core.Application.get()
    design = get_active_design()
    products = []
    for candidate in (
        _safe_value(lambda: app.activeProduct),
        _safe_value(lambda: design.cam),
        _safe_value(lambda: design.manufacturingProduct),
        _safe_value(lambda: app.activeDocument.products.itemByProductType("CAMProductType")),
        _safe_value(lambda: app.activeDocument.products.itemByProductType("CAM")),
        _safe_value(lambda: app.activeDocument.products.itemByProductType("ManufactureProductType")),
    ):
        if candidate and candidate not in products:
            products.append(candidate)
    for product in products:
        text = f"{_safe_value(lambda product=product: product.objectType)} {product.__class__.__name__}".lower()
        if "cam" in text or "manufactur" in text:
            return product
    return None


def _cam_setup_collection(cam_product):
    for attr in ("setups", "allSetups", "setupSheets"):
        collection = _safe_value(lambda attr=attr: getattr(cam_product, attr))
        if collection:
            return collection
    return None


def _operation_report(operation, index=None, setup_name=None):
    if not operation:
        return None
    tool = _safe_value(lambda: operation.tool)
    strategy = _safe_value(lambda: operation.strategy)
    return {
        "index": index,
        "setupName": setup_name,
        "name": _safe_value(lambda: operation.name),
        "objectType": _safe_value(lambda: operation.objectType),
        "entityToken": _safe_value(lambda: operation.entityToken),
        "operationType": _safe_value(lambda: operation.operationType),
        "strategy": _safe_value(lambda: strategy.name) or _safe_value(lambda: operation.strategyType),
        "isValid": _safe_value(lambda: operation.isValid),
        "isSuppressed": _safe_value(lambda: operation.isSuppressed),
        "hasToolpath": _safe_value(lambda: operation.hasToolpath),
        "toolpathState": _safe_value(lambda: operation.toolpathState),
        "tool": _entity_ref(tool) if tool else None,
    }


def _setup_report(setup, index=None, include_operations=True):
    operations = []
    if include_operations:
        for op_index, operation in enumerate(_collection_items(_safe_value(lambda: setup.operations))):
            operations.append(_operation_report(operation, index=op_index, setup_name=_safe_value(lambda: setup.name)))
    return {
        "index": index,
        "name": _safe_value(lambda: setup.name),
        "objectType": _safe_value(lambda: setup.objectType),
        "entityToken": _safe_value(lambda: setup.entityToken),
        "isActive": _safe_value(lambda: setup.isActive),
        "isValid": _safe_value(lambda: setup.isValid),
        "operationType": _safe_value(lambda: setup.operationType),
        "stockMode": _safe_value(lambda: setup.stockMode),
        "wcsOrientationMode": _safe_value(lambda: setup.wcsOrientationMode),
        "machine": _entity_ref(_safe_value(lambda: setup.machine)),
        "operationCount": len(operations),
        "operations": operations,
    }


def _drawing_document_report(doc, index=None, include_sheets=True):
    drawing_doc = None
    drawing_error = None
    try:
        adsk_drawing = importlib.import_module("adsk.drawing")
        drawing_doc = _safe_value(lambda: adsk_drawing.DrawingDocument.cast(doc))
    except Exception as exc:
        drawing_error = str(exc)
    drawing = _safe_value(lambda: drawing_doc.drawing) if drawing_doc else None
    sheets = []
    if include_sheets and drawing:
        for sheet_index, sheet in enumerate(_collection_items(_safe_value(lambda: drawing.sheets))):
            views = []
            for view_index, view in enumerate(_collection_items(_safe_value(lambda sheet=sheet: sheet.drawingViews))):
                views.append({
                    "index": view_index,
                    "name": _safe_value(lambda view=view: view.name),
                    "objectType": _safe_value(lambda view=view: view.objectType),
                    "scale": _safe_value(lambda view=view: view.scale),
                    "orientation": _safe_value(lambda view=view: view.orientation),
                    "viewStyle": _safe_value(lambda view=view: view.viewStyle),
                })
            sheets.append({
                "index": sheet_index,
                "name": _safe_value(lambda sheet=sheet: sheet.name),
                "objectType": _safe_value(lambda sheet=sheet: sheet.objectType),
                "size": _safe_value(lambda sheet=sheet: sheet.size),
                "orientation": _safe_value(lambda sheet=sheet: sheet.orientation),
                "viewCount": len(views),
                "views": views,
                "titleBlock": _entity_ref(_safe_value(lambda sheet=sheet: sheet.titleBlock)),
                "partsListsCount": len(_collection_items(_safe_value(lambda sheet=sheet: sheet.partsLists))),
                "tablesCount": len(_collection_items(_safe_value(lambda sheet=sheet: sheet.tables))),
                "dimensionsCount": len(_collection_items(_safe_value(lambda sheet=sheet: sheet.dimensions))),
            })
    data_file = _safe_value(lambda: doc.dataFile)
    app = adsk.core.Application.get()
    return {
        "index": index,
        "name": _safe_value(lambda: doc.name),
        "documentType": _safe_value(lambda: doc.documentType),
        "isActive": doc is _safe_value(lambda: app.activeDocument),
        "isModified": _safe_value(lambda: doc.isModified),
        "isSaved": bool(data_file),
        "dataFileName": _safe_value(lambda: data_file.name),
        "isDrawingDocument": bool(drawing_doc),
        "drawingObjectType": _safe_value(lambda: drawing.objectType) if drawing else None,
        "sheetCount": len(sheets),
        "sheets": sheets,
        "drawingApiError": drawing_error if not drawing_doc else None,
    }


@register_tool("inspect_drawing_documents")
def inspect_drawing_documents(include_sheets=True):
    try:
        app = adsk.core.Application.get()
        docs = _collection_items(_safe_value(lambda: app.documents))
        reports = [_drawing_document_report(doc, index=index, include_sheets=include_sheets) for index, doc in enumerate(docs)]
        drawing_docs = [doc for doc in reports if doc.get("isDrawingDocument")]
        return {
            "result": {
                "readOnly": True,
                "openDocumentCount": len(reports),
                "drawingDocumentCount": len(drawing_docs),
                "activeDocument": _safe_value(lambda: app.activeDocument.name),
                "documents": reports,
                "warnings": [
                    "This tool inspects open drawing documents only; it does not create sheets, views, dimensions, callouts, BOMs, or exports.",
                    "Drawing API availability depends on the Fusion runtime and document type.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect drawing documents: {str(e)}"}


@register_tool("preflight_drawing_creation")
def preflight_drawing_creation(export_pdf_path=None):
    try:
        app = adsk.core.Application.get()
        doc = _safe_value(lambda: app.activeDocument)
        blockers = []
        warnings = []
        if not doc:
            blockers.append("No active Fusion document is open.")
        data_file = _safe_value(lambda: doc.dataFile) if doc else None
        if not data_file:
            blockers.append("The active design must be saved to Fusion before a drawing can be created.")
        if export_pdf_path is not None:
            if not isinstance(export_pdf_path, str) or not export_pdf_path.strip():
                blockers.append("export_pdf_path must be a non-empty string when supplied.")
            elif "\x00" in export_pdf_path:
                blockers.append("export_pdf_path contains an invalid null byte.")
            elif not os.path.isabs(export_pdf_path):
                blockers.append("export_pdf_path must be absolute.")
        drawing_manager_available = False
        drawing_api_error = None
        try:
            adsk_drawing = importlib.import_module("adsk.drawing")
            drawing_manager_available = bool(_safe_value(lambda: adsk_drawing.DrawingManager.get()))
        except Exception as exc:
            drawing_api_error = str(exc)
        if not drawing_manager_available:
            blockers.append("Fusion DrawingManager is not available in this runtime.")
        if _safe_value(lambda: doc.isModified):
            warnings.append("Active document has unsaved changes; save before creating production drawing output.")
        active_design_available = False
        try:
            active_design_available = bool(get_active_design())
        except Exception:
            active_design_available = False
        return {
            "result": {
                "readOnly": True,
                "okToProceed": not blockers,
                "riskLevel": "low" if not blockers else "high",
                "blockingReasons": blockers,
                "warnings": warnings,
                "activeDocument": {
                    "name": _safe_value(lambda: doc.name),
                    "isModified": _safe_value(lambda: doc.isModified),
                    "isSaved": bool(data_file),
                    "dataFileName": _safe_value(lambda: data_file.name),
                },
                "activeDesignAvailable": active_design_available,
                "exportPdfPath": export_pdf_path,
                "drawingManagerAvailable": drawing_manager_available,
                "drawingApiError": drawing_api_error,
            }
        }
    except Exception as e:
        return {"error": f"Failed to preflight drawing creation: {str(e)}"}


_DRAWING_STANDARDS = {
    "ASME": "ASME",
    "ISO": "ISO",
}
_DRAWING_SHEET_SIZES = {"A", "B", "C", "D", "E", "A4", "A3", "A2", "A1", "A0"}
_DRAWING_SHEET_ORIENTATIONS = {"landscape", "portrait"}
_DRAWING_VIEW_ORIENTATIONS = {"front", "back", "left", "right", "top", "bottom", "iso", "current"}
_DRAWING_VIEW_STYLES = {"visible", "visible_hidden", "shaded", "shaded_hidden"}


def _normalize_drawing_views(views):
    if views is None:
        views = [{"name": "Base View", "orientation": "front", "scale": 1.0, "style": "visible", "placement": "center"}]
    if isinstance(views, dict):
        views = [views]
    if not isinstance(views, list) or not views:
        raise ValueError("views must be a non-empty object or array of objects.")

    normalized = []
    blockers = []
    for index, view in enumerate(views):
        if not isinstance(view, dict):
            blockers.append(f"View {index} must be an object.")
            continue
        name = str(view.get("name") or f"View {index + 1}").strip()
        orientation = str(view.get("orientation") or "front").lower()
        style = str(view.get("style") or "visible").lower()
        placement = str(view.get("placement") or ("center" if index == 0 else f"auto_{index + 1}")).strip()
        try:
            scale = float(view.get("scale", 1.0))
        except (TypeError, ValueError):
            scale = None
        if not name:
            blockers.append(f"View {index} name must be non-empty.")
        if orientation not in _DRAWING_VIEW_ORIENTATIONS:
            blockers.append(f"View '{name}' orientation must be one of {sorted(_DRAWING_VIEW_ORIENTATIONS)}.")
        if style not in _DRAWING_VIEW_STYLES:
            blockers.append(f"View '{name}' style must be one of {sorted(_DRAWING_VIEW_STYLES)}.")
        if scale is None or scale <= 0:
            blockers.append(f"View '{name}' scale must be a positive number.")
        normalized.append({
            "index": index,
            "name": name,
            "orientation": orientation,
            "style": style,
            "scale": scale,
            "placement": placement,
            "source": str(view.get("source") or "active_design").strip(),
        })
    return normalized, blockers


@register_tool("plan_drawing_views")
def plan_drawing_views(standard="ASME", sheet_size="A", sheet_orientation="landscape", units="mm", views=None, title_block=None, export_pdf_path=None):
    """
    Read-only drawing plan validator.

    This normalizes explicit sheet and view intent with documented defaults. It
    does not create drawing documents, views, dimensions, callouts, or exports.
    """
    try:
        normalized_standard = str(standard or "ASME").upper()
        normalized_sheet_size = str(sheet_size or "A").upper()
        normalized_orientation = str(sheet_orientation or "landscape").lower()
        normalized_units = str(units or "mm").lower()
        blockers = []
        warnings = []

        if normalized_standard not in _DRAWING_STANDARDS:
            blockers.append(f"standard must be one of {sorted(_DRAWING_STANDARDS)}.")
        if normalized_sheet_size not in _DRAWING_SHEET_SIZES:
            blockers.append(f"sheet_size must be one of {sorted(_DRAWING_SHEET_SIZES)}.")
        if normalized_orientation not in _DRAWING_SHEET_ORIENTATIONS:
            blockers.append(f"sheet_orientation must be one of {sorted(_DRAWING_SHEET_ORIENTATIONS)}.")
        if normalized_units not in {"mm", "in"}:
            blockers.append("units must be 'mm' or 'in'.")
        if export_pdf_path and not os.path.isabs(export_pdf_path):
            blockers.append("export_pdf_path must be absolute when supplied.")
        normalized_views, view_blockers = _normalize_drawing_views(views)
        blockers.extend(view_blockers)

        preflight = preflight_drawing_creation(export_pdf_path=export_pdf_path).get("result")
        if preflight:
            warnings.extend(preflight.get("warnings") or [])
        else:
            warnings.append("Drawing creation preflight could not be evaluated in this runtime.")

        ok_to_proceed = not blockers and bool(preflight and preflight.get("okToProceed"))
        return {
            "result": {
                "readOnly": True,
                "okToProceed": ok_to_proceed,
                "riskLevel": "low" if ok_to_proceed else "medium",
                "blockingReasons": blockers + ((preflight or {}).get("blockingReasons") or []),
                "sheet": {
                    "standard": normalized_standard,
                    "sheetSize": normalized_sheet_size,
                    "orientation": normalized_orientation,
                    "units": normalized_units,
                    "titleBlock": title_block,
                },
                "views": normalized_views,
                "exportPdfPath": export_pdf_path,
                "preflight": preflight,
                "warnings": warnings + [
                    "This tool plans drawing views only; it does not create sheets, views, dimensions, callouts, BOMs, revision tables, or files.",
                    "Defaults are documented for planning and must still be accepted explicitly by any mutating drawing tool.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan drawing views: {str(e)}"}


def _cam_product_report(cam_product):
    if not cam_product:
        return None
    setups = _collection_items(_cam_setup_collection(cam_product))
    return {
        "objectType": _safe_value(lambda: cam_product.objectType),
        "productName": _safe_value(lambda: cam_product.productType) or _safe_value(lambda: cam_product.name),
        "setupCount": len(setups),
        "setupsAvailable": _cam_setup_collection(cam_product) is not None,
    }


def _active_simulation_product():
    app = adsk.core.Application.get()
    doc = _safe_value(lambda: app.activeDocument)
    products = _safe_value(lambda: doc.products) if doc else None
    for product_type in (
        "SimulationProductType",
        "SIMProductType",
        "Simulation",
        "adsk::fusion::SimulationProduct",
    ):
        product = _safe_value(lambda product_type=product_type: products.itemByProductType(product_type)) if products else None
        if product:
            return product
    design = _safe_value(lambda: app.activeProduct)
    for attr in ("simulation", "simulationProduct", "simulationManager", "studies"):
        product = _safe_value(lambda attr=attr: getattr(design, attr))
        if product:
            return product
    return None


def _simulation_study_collection(sim_product):
    if not sim_product:
        return None
    for attr in ("studies", "simulationStudies", "studyCollection", "analyses"):
        collection = _safe_value(lambda attr=attr: getattr(sim_product, attr))
        if collection is not None:
            return collection
    return None


def _simulation_product_report(sim_product):
    if not sim_product:
        return None
    studies = _collection_items(_simulation_study_collection(sim_product))
    return {
        "objectType": _safe_value(lambda: sim_product.objectType),
        "productName": _safe_value(lambda: sim_product.productType) or _safe_value(lambda: sim_product.name),
        "studyCount": len(studies),
        "studiesAvailable": _simulation_study_collection(sim_product) is not None,
    }


def _simulation_study_report(study, index=0):
    loads = _collection_items(_safe_value(lambda: study.loads))
    constraints = _collection_items(_safe_value(lambda: study.constraints))
    materials = _collection_items(_safe_value(lambda: study.materials))
    contacts = _collection_items(_safe_value(lambda: study.contacts))
    results = _collection_items(_safe_value(lambda: study.results))
    mesh = _safe_value(lambda: study.mesh) or _safe_value(lambda: study.meshData)
    return {
        "index": index,
        "name": _safe_value(lambda: study.name),
        "objectType": _safe_value(lambda: study.objectType),
        "entityToken": _safe_value(lambda: study.entityToken),
        "studyType": _safe_value(lambda: study.studyType) or _safe_value(lambda: study.analysisType),
        "isValid": _safe_value(lambda: study.isValid),
        "solveStatus": _safe_value(lambda: study.solveStatus) or _safe_value(lambda: study.status),
        "isSolved": _safe_value(lambda: study.isSolved),
        "loadCount": len(loads),
        "constraintCount": len(constraints),
        "materialCount": len(materials),
        "contactCount": len(contacts),
        "resultCount": len(results),
        "meshAvailable": bool(mesh),
        "meshStatus": _safe_value(lambda: mesh.status) if mesh else None,
    }


def _active_electronics_product():
    app = adsk.core.Application.get()
    doc = _safe_value(lambda: app.activeDocument)
    products = _safe_value(lambda: doc.products) if doc else None
    for product_type in (
        "ElectronicsProductType",
        "PCBProductType",
        "BoardProductType",
        "adsk::electronics::ElectronicsProduct",
    ):
        product = _safe_value(lambda product_type=product_type: products.itemByProductType(product_type)) if products else None
        if product:
            return product
    active_product = _safe_value(lambda: app.activeProduct)
    for attr in ("electronics", "electronicsProduct", "pcb", "board", "pcbProduct"):
        product = _safe_value(lambda attr=attr: getattr(active_product, attr))
        if product:
            return product
    return None


def _electronics_collection(product, names):
    if not product:
        return []
    for attr in names:
        collection = _safe_value(lambda attr=attr: getattr(product, attr))
        items = _collection_items(collection)
        if items:
            return items
    return []


def _electronics_item_report(item, index=0):
    bbox = _bbox_to_dict(item)
    return {
        "index": index,
        "name": _safe_value(lambda: item.name),
        "objectType": _safe_value(lambda: item.objectType),
        "entityToken": _safe_value(lambda: item.entityToken),
        "boundingBox": bbox,
        "sizeMm": _bbox_size_mm(bbox),
        "designator": _safe_value(lambda: item.designator) or _safe_value(lambda: item.refDes),
        "value": _safe_value(lambda: item.value),
        "packageName": _safe_value(lambda: item.packageName) or _safe_value(lambda: item.footprintName),
        "netName": _safe_value(lambda: item.netName),
        "isVisible": _safe_value(lambda: item.isVisible),
    }


def _electronics_product_report(product):
    if not product:
        return None
    boards = _electronics_collection(product, ("boards", "pcbBoards", "boardDocuments"))
    board_outlines = _electronics_collection(product, ("boardOutlines", "outlines", "profiles"))
    components = _electronics_collection(product, ("components", "pcbComponents", "devices", "instances"))
    nets = _electronics_collection(product, ("nets", "signals", "electricalNets"))
    connectors = [
        item for item in components
        if any(token in str(_safe_value(lambda item=item: item.name) or _safe_value(lambda item=item: item.designator) or "").lower() for token in ("conn", "j", "usb", "header"))
    ]
    return {
        "objectType": _safe_value(lambda: product.objectType),
        "productName": _safe_value(lambda: product.productType) or _safe_value(lambda: product.name),
        "boardCount": len(boards),
        "boardOutlineCount": len(board_outlines),
        "componentCount": len(components),
        "netCount": len(nets),
        "connectorCandidateCount": len(connectors),
        "boards": [_electronics_item_report(item, index=index) for index, item in enumerate(boards[:25])],
        "boardOutlines": [_electronics_item_report(item, index=index) for index, item in enumerate(board_outlines[:25])],
        "components": [_electronics_item_report(item, index=index) for index, item in enumerate(components[:50])],
        "nets": [_electronics_item_report(item, index=index) for index, item in enumerate(nets[:50])],
        "connectorCandidates": [_electronics_item_report(item, index=index) for index, item in enumerate(connectors[:25])],
    }


def _configuration_collection(design):
    for attr in ("configurations", "configurationRows", "configurationTable", "configurationTableRows"):
        collection = _safe_value(lambda attr=attr: getattr(design, attr))
        if collection is not None:
            return collection, attr
    root = _safe_value(lambda: design.rootComponent)
    for attr in ("configurations", "configurationRows"):
        collection = _safe_value(lambda attr=attr: getattr(root, attr))
        if collection is not None:
            return collection, f"rootComponent.{attr}"
    return None, None


def _configuration_item_report(item, index=0):
    parameters = []
    for attr in ("parameters", "parameterValues", "configurationParameters", "values"):
        collection = _collection_items(_safe_value(lambda attr=attr: getattr(item, attr)))
        if collection:
            for param_index, param in enumerate(collection):
                parameters.append({
                    "index": param_index,
                    "name": _safe_value(lambda param=param: param.name),
                    "expression": _safe_value(lambda param=param: param.expression),
                    "value": _safe_value(lambda param=param: param.value),
                    "unit": _safe_value(lambda param=param: param.unit),
                    "role": _safe_value(lambda param=param: param.role),
                })
            break
    return {
        "index": index,
        "name": _safe_value(lambda: item.name),
        "objectType": _safe_value(lambda: item.objectType),
        "entityToken": _safe_value(lambda: item.entityToken),
        "isActive": bool(_safe_value(lambda: item.isActive, False)),
        "description": _safe_value(lambda: item.description),
        "parameterCount": len(parameters),
        "parameters": parameters,
    }


def _camera_report(camera, index=0, name=None):
    return {
        "index": index,
        "name": name or _safe_value(lambda: camera.name),
        "objectType": _safe_value(lambda: camera.objectType),
        "eye": _point_to_list(_safe_value(lambda: camera.eye)),
        "target": _point_to_list(_safe_value(lambda: camera.target)),
        "upVector": _vector_to_list(_safe_value(lambda: camera.upVector)),
        "viewOrientation": _safe_value(lambda: camera.viewOrientation),
        "isFitView": _safe_value(lambda: camera.isFitView),
        "isPerspective": _safe_value(lambda: camera.isPerspective),
    }


def _render_product():
    app = adsk.core.Application.get()
    doc = _safe_value(lambda: app.activeDocument)
    products = _safe_value(lambda: doc.products) if doc else None
    for product_type in ("RenderProductType", "RenderingProductType", "adsk::fusion::RenderProduct"):
        product = _safe_value(lambda product_type=product_type: products.itemByProductType(product_type)) if products else None
        if product:
            return product
    active_product = _safe_value(lambda: app.activeProduct)
    for attr in ("render", "renderProduct", "renderManager", "rendering"):
        product = _safe_value(lambda attr=attr: getattr(active_product, attr))
        if product:
            return product
    return None


def _data_file_report(data_file):
    if not data_file:
        return None
    parent_project = _safe_value(lambda: data_file.parentProject)
    parent_folder = _safe_value(lambda: data_file.parentFolder)
    versions = _collection_items(_safe_value(lambda: data_file.versions))
    latest_version = _safe_value(lambda: data_file.latestVersion) or (versions[-1] if versions else None)
    return {
        "name": _safe_value(lambda: data_file.name),
        "id": _safe_value(lambda: data_file.id),
        "urn": _safe_value(lambda: data_file.urn),
        "versionId": _safe_value(lambda: data_file.versionId),
        "versionNumber": _safe_value(lambda: data_file.versionNumber),
        "isComplete": _safe_value(lambda: data_file.isComplete),
        "isReadOnly": _safe_value(lambda: data_file.isReadOnly),
        "isInUse": _safe_value(lambda: data_file.isInUse),
        "fileExtension": _safe_value(lambda: data_file.fileExtension),
        "description": _safe_value(lambda: data_file.description),
        "createdBy": _safe_value(lambda: data_file.createdBy),
        "lastUpdatedBy": _safe_value(lambda: data_file.lastUpdatedBy),
        "dateCreated": str(_safe_value(lambda: data_file.dateCreated)) if _safe_value(lambda: data_file.dateCreated) else None,
        "dateModified": str(_safe_value(lambda: data_file.dateModified)) if _safe_value(lambda: data_file.dateModified) else None,
        "parentProject": {
            "name": _safe_value(lambda: parent_project.name),
            "id": _safe_value(lambda: parent_project.id),
        } if parent_project else None,
        "parentFolder": {
            "name": _safe_value(lambda: parent_folder.name),
            "id": _safe_value(lambda: parent_folder.id),
        } if parent_folder else None,
        "versionCount": len(versions),
        "latestVersion": {
            "name": _safe_value(lambda: latest_version.name),
            "versionNumber": _safe_value(lambda: latest_version.versionNumber),
            "id": _safe_value(lambda: latest_version.id),
        } if latest_version else None,
    }


def _document_management_doc_report(doc, index=0, active_doc=None):
    data_file = _safe_value(lambda: doc.dataFile)
    references = []
    for attr in ("references", "externalReferences", "referencedDataFiles"):
        for ref_index, ref in enumerate(_collection_items(_safe_value(lambda attr=attr: getattr(doc, attr)))):
            references.append({
                "index": ref_index,
                "name": _safe_value(lambda ref=ref: ref.name),
                "objectType": _safe_value(lambda ref=ref: ref.objectType),
                "dataFile": _data_file_report(_safe_value(lambda ref=ref: ref.dataFile)),
                "isOutOfDate": _safe_value(lambda ref=ref: ref.isOutOfDate),
                "isBroken": _safe_value(lambda ref=ref: ref.isBroken),
            })
        if references:
            break
    return {
        "index": index,
        "name": _safe_value(lambda: doc.name),
        "documentType": _safe_value(lambda: doc.documentType),
        "isActive": doc == active_doc,
        "isModified": _safe_value(lambda: doc.isModified),
        "isSaved": bool(data_file),
        "dataFile": _data_file_report(data_file),
        "externalReferenceCount": len(references),
        "externalReferences": references[:50],
    }


@register_tool("inspect_document_management_state")
def inspect_document_management_state(include_open_documents=True, include_external_references=True):
    try:
        app = adsk.core.Application.get()
        active_doc = _safe_value(lambda: app.activeDocument)
        docs = _collection_items(_safe_value(lambda: app.documents)) if include_open_documents else []
        if active_doc and active_doc not in docs:
            docs.insert(0, active_doc)
        reports = [
            _document_management_doc_report(doc, index=index, active_doc=active_doc)
            for index, doc in enumerate(docs)
        ]
        if not include_external_references:
            for report in reports:
                report["externalReferenceCount"] = None
                report["externalReferences"] = []
        active_report = _document_management_doc_report(active_doc, index=None, active_doc=active_doc) if active_doc else None
        cloud_available = bool(active_report and active_report.get("dataFile"))
        warnings = []
        blockers = []
        if not active_doc:
            blockers.append("No active Fusion document is available.")
        elif not active_report.get("dataFile"):
            warnings.append("Active document is not associated with a Fusion dataFile; cloud/version metadata is unavailable.")
        if active_report and active_report.get("isModified"):
            warnings.append("Active document has unsaved modifications.")
        return {
            "result": {
                "readOnly": True,
                "activeDocument": active_report,
                "openDocumentCount": len(reports),
                "openDocuments": reports,
                "cloudDataAvailable": cloud_available,
                "blockingReasons": blockers,
                "warnings": warnings + [
                    "This tool does not save, upload, version, promote, or relink documents.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect document management state: {str(e)}"}


_DOCUMENT_MANAGEMENT_ACTIONS = {
    "close",
    "new_design",
    "save",
    "save_as",
    "export_copy",
    "version_snapshot",
    "promote_version",
    "relink_reference",
    "open_data_file",
}


@register_tool("plan_document_management_action")
def plan_document_management_action(action=None, document_name=None, data_file_id=None, target_path=None, target_folder_id=None, reference_name=None, version_id=None, dry_run=True, reason=None, requires_user_approval=False):
    """
    Read-only preflight for save/version/export/relink/cloud document actions.
    """
    try:
        action_value = str(action or "").strip().lower()
        blockers = []
        warnings = []
        if action_value not in _DOCUMENT_MANAGEMENT_ACTIONS:
            blockers.append(f"action must be one of {sorted(_DOCUMENT_MANAGEMENT_ACTIONS)}.")
        if not reason:
            blockers.append("reason is required for document-management planning.")
        if requires_user_approval is not True:
            blockers.append("requires_user_approval must be true before any close, save, upload, version, relink, or cloud document action.")
        if dry_run is not True:
            blockers.append("dry_run must remain true for planning; mutation tools must perform a separate explicit action.")

        if action_value in {"export_copy", "save_as"}:
            if not target_path:
                blockers.append(f"target_path is required for {action_value}.")
            elif not os.path.isabs(str(target_path)):
                blockers.append("target_path must be absolute.")
            elif not os.path.isdir(os.path.dirname(str(target_path))):
                blockers.append(f"target_path directory does not exist: {os.path.dirname(str(target_path))}")
        if action_value in {"save_as", "open_data_file"} and not (target_folder_id or data_file_id):
            blockers.append(f"target_folder_id or data_file_id is required for {action_value}.")
        if action_value in {"promote_version", "open_data_file"} and not (data_file_id or version_id):
            blockers.append(f"data_file_id or version_id is required for {action_value}.")
        if action_value == "relink_reference" and not reference_name:
            blockers.append("reference_name is required for relink_reference.")
        if action_value == "relink_reference" and not data_file_id:
            blockers.append("data_file_id is required for relink_reference.")

        inspection = inspect_document_management_state()
        inspection_result = inspection.get("result") if isinstance(inspection, dict) else None
        if not inspection_result:
            blockers.append("Document-management inspection failed before planning action.")
        else:
            warnings.extend(inspection_result.get("warnings") or [])
            active_doc = inspection_result.get("activeDocument")
            documents = inspection_result.get("openDocuments") or []
            if document_name and action_value != "new_design":
                matches = [doc for doc in documents if doc.get("name") == document_name]
                if not matches:
                    blockers.append(f"document_name '{document_name}' was not found among open documents.")
            elif action_value in {"close", "save", "save_as", "export_copy", "version_snapshot"} and not active_doc:
                blockers.append("An active document is required for this action.")
            if action_value in {"version_snapshot", "promote_version"} and active_doc and not active_doc.get("dataFile"):
                blockers.append("Cloud dataFile metadata is required for version actions.")

        return {
            "result": {
                "readOnly": True,
                "okToProceed": len(blockers) == 0,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "actionPlan": {
                    "action": action_value,
                    "documentName": document_name,
                    "dataFileId": data_file_id,
                    "targetPath": target_path,
                    "targetFolderId": target_folder_id,
                    "referenceName": reference_name,
                    "versionId": version_id,
                    "dryRun": bool(dry_run),
                    "reason": reason,
                },
                "requiresUserApproval": bool(requires_user_approval),
                "inspection": inspection_result,
                "warnings": warnings + [
                    "This is a read-only document-management plan; it does not save, upload, version, open, promote, or relink data.",
                    "Cloud and version actions affect user data outside the active model and require a separate guarded mutation path.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan document management action: {str(e)}"}


@register_tool("inspect_render_workspace")
def inspect_render_workspace():
    try:
        app = adsk.core.Application.get()
        design = get_active_design()
        viewport = _safe_value(lambda: app.activeViewport)
        active_camera = _safe_value(lambda: viewport.camera) if viewport else None
        render_product = _render_product()
        named_views = []
        for index, view in enumerate(_collection_items(_safe_value(lambda: design.namedViews))):
            named_views.append({
                "index": index,
                "name": _safe_value(lambda view=view: view.name),
                "objectType": _safe_value(lambda view=view: view.objectType),
                "camera": _camera_report(_safe_value(lambda view=view: view.camera), index=index) if _safe_value(lambda view=view: view.camera) else None,
            })
        cameras = []
        for index, camera in enumerate(_collection_items(_safe_value(lambda: design.cameras))):
            cameras.append(_camera_report(camera, index=index))
        if active_camera:
            cameras.insert(0, _camera_report(active_camera, index=None, name="activeViewport"))
        environments = [
            _entity_ref(env)
            for env in _collection_items(_safe_value(lambda: design.environments))
        ]
        render_settings = _safe_value(lambda: render_product.renderSettings) if render_product else None
        warnings = []
        if not render_product:
            warnings.append("Fusion did not expose a dedicated render product/manager in this runtime.")
        if not named_views:
            warnings.append("No named views were exposed; render planning should use an explicit camera or standard view.")
        return {
            "result": {
                "readOnly": True,
                "renderWorkspaceAvailable": bool(render_product),
                "activeViewportAvailable": bool(viewport),
                "activeCamera": _camera_report(active_camera, index=None, name="activeViewport") if active_camera else None,
                "cameraCount": len(cameras),
                "cameras": cameras[:50],
                "namedViewCount": len(named_views),
                "namedViews": named_views[:50],
                "appearanceCount": len(_collection_items(_safe_value(lambda: design.appearances))),
                "environmentCount": len(environments),
                "environments": environments[:50],
                "renderProduct": _entity_ref(render_product) if render_product else None,
                "renderSettings": {
                    "objectType": _safe_value(lambda: render_settings.objectType),
                    "quality": _safe_value(lambda: render_settings.quality),
                    "resolution": _safe_value(lambda: render_settings.resolution),
                } if render_settings else None,
                "warnings": warnings + [
                    "This tool only inspects render-related metadata; it does not render images or change viewport state.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect render workspace: {str(e)}"}


@register_tool("plan_render_output")
def plan_render_output(camera_name=None, named_view=None, output_path=None, width=1920, height=1080, visual_style="shaded", environment=None, background=None, reason=None, requires_user_approval=False):
    """
    Read-only render/output plan validator.
    """
    try:
        blockers = []
        warnings = []
        camera_value = str(camera_name or "").strip()
        named_view_value = str(named_view or "").strip()
        if not camera_value and not named_view_value:
            blockers.append("camera_name or named_view is required.")
        if not output_path:
            blockers.append("output_path is required and must be absolute.")
            output_value = None
        else:
            output_value = os.path.abspath(str(output_path)) if not os.path.isabs(str(output_path)) else str(output_path)
            if not os.path.isabs(str(output_path)):
                blockers.append("output_path must be absolute; relative render paths are not allowed.")
            output_dir = os.path.dirname(output_value)
            if output_dir and not os.path.isdir(output_dir):
                blockers.append(f"output_path directory does not exist: {output_dir}")
        try:
            width_value = int(width)
            height_value = int(height)
        except (TypeError, ValueError):
            width_value = height_value = 0
            blockers.append("width and height must be integers.")
        if width_value <= 0 or height_value <= 0:
            blockers.append("width and height must be greater than zero.")
        if width_value > 8192 or height_value > 8192:
            blockers.append("width and height must be 8192 or less until output validation is implemented.")
        if not reason:
            blockers.append("reason is required for render output planning.")
        if requires_user_approval is not True:
            blockers.append("requires_user_approval must be true before any render/export action.")

        workspace = inspect_render_workspace()
        workspace_result = workspace.get("result") if isinstance(workspace, dict) else None
        if not workspace_result:
            blockers.append("Render workspace inspection failed before planning output.")
        else:
            warnings.extend(workspace_result.get("warnings") or [])
            named_view_names = {
                item.get("name")
                for item in workspace_result.get("namedViews", [])
                if item.get("name")
            }
            camera_names = {
                item.get("name")
                for item in workspace_result.get("cameras", [])
                if item.get("name")
            }
            if named_view_value and named_view_names and named_view_value not in named_view_names:
                blockers.append(f"named_view '{named_view_value}' was not found in inspected named views.")
            if camera_value and camera_names and camera_value not in camera_names:
                blockers.append(f"camera_name '{camera_value}' was not found in inspected cameras.")

        return {
            "result": {
                "readOnly": True,
                "okToProceed": len(blockers) == 0,
                "riskLevel": "low" if not blockers else "high",
                "blockingReasons": blockers,
                "renderPlan": {
                    "cameraName": camera_value or None,
                    "namedView": named_view_value or None,
                    "outputPath": output_value,
                    "width": width_value,
                    "height": height_value,
                    "visualStyle": visual_style,
                    "environment": environment,
                    "background": background,
                    "reason": reason,
                },
                "requiresUserApproval": bool(requires_user_approval),
                "workspace": workspace_result,
                "warnings": warnings + [
                    "This is a read-only render plan; it does not render, export, change cameras, or alter scene settings.",
                    "Validate generated files separately for existence and nonblank output before publishing.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan render output: {str(e)}"}


@register_tool("inspect_design_configurations")
def inspect_design_configurations(include_parameters=True):
    try:
        design = get_active_design()
        collection, source = _configuration_collection(design)
        items = _collection_items(collection)
        active = (
            _safe_value(lambda: design.activeConfiguration)
            or _safe_value(lambda: design.activeConfigurationRow)
            or _safe_value(lambda: design.configuration)
        )
        configs = [_configuration_item_report(item, index=index) for index, item in enumerate(items)]
        active_name = _safe_value(lambda: active.name)
        for config in configs:
            if active_name and config.get("name") == active_name:
                config["isActive"] = True
        warnings = []
        blockers = []
        if collection is None:
            blockers.append("Fusion did not expose a design configuration collection in this runtime.")
        if collection is not None and not items:
            warnings.append("A configuration collection was exposed, but it did not contain rows/items.")
        parameter_report = []
        if include_parameters:
            parameter_report = [
                _parameter_snapshot(param, "user")
                for param in _collection_items(_safe_value(lambda: design.userParameters))
            ]
        return {
            "result": {
                "readOnly": True,
                "configurationCollectionAvailable": collection is not None,
                "collectionSource": source,
                "activeConfiguration": _configuration_item_report(active, index=None) if active else None,
                "configurationCount": len(configs),
                "configurations": configs,
                "userParameters": sorted(parameter_report, key=lambda item: item.get("name") or ""),
                "blockingReasons": blockers,
                "warnings": warnings + [
                    "This tool only inspects exposed configuration metadata; it does not create, activate, or edit design variants.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect design configurations: {str(e)}"}


@register_tool("plan_design_variant")
def plan_design_variant(variant_name=None, base_configuration=None, parameter_changes=None, expected_affected_bodies=None, expected_affected_features=None, reason=None, requires_user_approval=False):
    """
    Read-only design-variant plan validator.

    This validates target configuration and explicit parameter changes before
    any future configuration creation or parameter-set mutation.
    """
    try:
        blockers = []
        warnings = []
        variant_name_value = str(variant_name or "").strip()
        base_config_value = str(base_configuration or "").strip()
        if not variant_name_value:
            blockers.append("variant_name is required.")
        if not isinstance(parameter_changes, dict) or not parameter_changes:
            blockers.append("parameter_changes must be a non-empty object mapping parameter names to explicit expressions.")
            parameter_data = {}
        else:
            parameter_data = dict(parameter_changes)
            empty_values = [key for key, value in parameter_data.items() if value in (None, "")]
            if empty_values:
                blockers.append(f"parameter_changes contains empty values for: {', '.join(str(key) for key in empty_values)}.")
        if not reason:
            blockers.append("reason is required for design-variant planning.")
        if requires_user_approval is not True:
            blockers.append("requires_user_approval must be true before any configuration or parameter-set mutation.")

        inspection = inspect_design_configurations(include_parameters=True)
        inspection_result = inspection.get("result") if isinstance(inspection, dict) else None
        if not inspection_result:
            blockers.append("Configuration inspection failed before variant planning.")
        elif not inspection_result.get("configurationCollectionAvailable"):
            blockers.extend(inspection_result.get("blockingReasons") or [])
        else:
            warnings.extend(inspection_result.get("warnings") or [])

        config_names = {
            config.get("name")
            for config in (inspection_result or {}).get("configurations", [])
            if config.get("name")
        }
        if base_config_value and config_names and base_config_value not in config_names:
            blockers.append(f"base_configuration '{base_config_value}' was not found in inspected configurations.")

        user_parameters = {
            param.get("name"): param
            for param in (inspection_result or {}).get("userParameters", [])
            if param.get("name")
        }
        missing_parameters = [
            name for name in parameter_data
            if user_parameters and name not in user_parameters
        ]
        if missing_parameters:
            blockers.append(f"parameter_changes reference unknown user parameters: {', '.join(sorted(missing_parameters))}.")

        affected_body_names = _normalize_name_list(expected_affected_bodies)
        affected_feature_names = _normalize_name_list(expected_affected_features)
        if not affected_body_names and not affected_feature_names:
            warnings.append("No expected affected bodies or features were supplied; downstream impact should be checked before mutation.")

        return {
            "result": {
                "readOnly": True,
                "okToProceed": len(blockers) == 0,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "variant": {
                    "name": variant_name_value,
                    "baseConfiguration": base_config_value or None,
                    "parameterChanges": parameter_data,
                    "expectedAffectedBodies": affected_body_names,
                    "expectedAffectedFeatures": affected_feature_names,
                },
                "requiresUserApproval": bool(requires_user_approval),
                "inspection": inspection_result,
                "reason": reason,
                "warnings": warnings + [
                    "This is a read-only variant plan; it does not create configurations, activate rows, or edit parameters.",
                    "Run dependency and design-state checks before applying any planned variant.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan design variant: {str(e)}"}


@register_tool("inspect_electronics_workspace")
def inspect_electronics_workspace():
    try:
        product = _active_electronics_product()
        blockers = []
        warnings = []
        if not product:
            blockers.append("Fusion did not expose an active Electronics or PCB product for this document.")
        report = _electronics_product_report(product)
        if product and report and not report.get("boardOutlineCount"):
            warnings.append("An electronics-like product was found, but no board outline collection was exposed.")
        if product and report and not report.get("componentCount"):
            warnings.append("An electronics-like product was found, but no component collection was exposed.")
        return {
            "result": {
                "readOnly": True,
                "workspaceAvailable": bool(product),
                "okToInspectBoards": bool(product),
                "blockingReasons": blockers,
                "electronicsProduct": report,
                "warnings": warnings,
                "notes": [
                    "This tool does not edit boards, components, nets, or mechanical links.",
                    "Mechanical enclosure-fit work should be routed through plan_pcb_enclosure_fit before any bridge action.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect electronics workspace: {str(e)}"}


@register_tool("plan_pcb_enclosure_fit")
def plan_pcb_enclosure_fit(board_outline=None, keepouts=None, connectors=None, mounting_holes=None, clearance_rules=None, enclosure_body_name=None, enclosure_body_entity_token=None, linked_mechanical_reference=None, reason=None, requires_user_approval=False):
    """
    Read-only planner for PCB-to-enclosure fit work.

    Requires explicit board outline, keepouts, connectors, mounting holes, and
    clearance rules before any future electronics/mechanical bridge mutation.
    """
    try:
        blockers = []
        warnings = []
        if not isinstance(board_outline, dict) or not board_outline:
            blockers.append("board_outline must be a non-empty object with explicit dimensions or entity references.")
            board_outline_data = {}
        else:
            board_outline_data = dict(board_outline)
        keepout_data = _non_empty_mapping(keepouts, "keepouts", blockers)
        connector_data = _non_empty_mapping(connectors, "connectors", blockers)
        hole_data = _non_empty_mapping(mounting_holes, "mounting_holes", blockers)
        clearance_data = _non_empty_mapping(clearance_rules, "clearance_rules", blockers)
        if not reason:
            blockers.append("reason is required for PCB enclosure-fit planning.")
        if requires_user_approval is not True:
            blockers.append("requires_user_approval must be true before any electronics/mechanical bridge action.")

        target_names = _normalize_name_list(enclosure_body_name)
        target_tokens = _normalize_name_list(enclosure_body_entity_token)
        target_matches = _resolve_named_body_set(names=target_names, entity_tokens=target_tokens, include_all=False)[0] if (target_names or target_tokens) else []
        if enclosure_body_name or enclosure_body_entity_token:
            if not target_matches:
                blockers.append("No matching enclosure body was found for the supplied enclosure body target.")
        else:
            warnings.append("No enclosure body target was supplied; plan is limited to PCB-side fit requirements.")

        workspace = inspect_electronics_workspace()
        workspace_result = workspace.get("result") if isinstance(workspace, dict) else None
        if not workspace_result or not workspace_result.get("workspaceAvailable"):
            blockers.append("Electronics workspace is unavailable in the active document.")
        else:
            warnings.extend(workspace_result.get("warnings") or [])

        return {
            "result": {
                "readOnly": True,
                "okToProceed": len(blockers) == 0,
                "riskLevel": "medium" if not blockers else "high",
                "blockingReasons": blockers,
                "boardOutline": board_outline_data,
                "keepouts": keepout_data,
                "connectors": connector_data,
                "mountingHoles": hole_data,
                "clearanceRules": clearance_data,
                "targetEnclosureBodies": [
                    _body_snapshot(body, component_name)
                    for body, component_name in target_matches
                ],
                "linkedMechanicalReference": linked_mechanical_reference,
                "reason": reason,
                "requiresUserApproval": bool(requires_user_approval),
                "workspace": workspace_result,
                "warnings": warnings + [
                    "This is a read-only PCB enclosure-fit plan; it does not sync boards, move components, or edit mechanical geometry.",
                    "Connector, keepout, mounting-hole, and clearance data must come from explicit user input or inspected electronics metadata.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan PCB enclosure fit: {str(e)}"}


@register_tool("inspect_simulation_workspace")
def inspect_simulation_workspace():
    try:
        sim_product = _active_simulation_product()
        blockers = []
        warnings = []
        if not sim_product:
            blockers.append("Fusion did not expose an active Simulation product for this document.")
        report = _simulation_product_report(sim_product)
        if sim_product and report and not report.get("studiesAvailable"):
            warnings.append("A simulation-like product was found, but no study collection was exposed.")
        return {
            "result": {
                "readOnly": True,
                "workspaceAvailable": bool(sim_product),
                "okToInspectStudies": bool(sim_product and report and report.get("studiesAvailable")),
                "blockingReasons": blockers,
                "simulationProduct": report,
                "warnings": warnings,
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect simulation workspace: {str(e)}"}


@register_tool("list_simulation_studies")
def list_simulation_studies(include_details=True):
    try:
        workspace = inspect_simulation_workspace()
        if "error" in workspace:
            return workspace
        sim_product = _active_simulation_product()
        if not sim_product:
            return {
                "result": {
                    "readOnly": True,
                    "studyCount": 0,
                    "studies": [],
                    "blockingReasons": (workspace.get("result") or {}).get("blockingReasons") or ["Simulation workspace unavailable."],
                    "warnings": (workspace.get("result") or {}).get("warnings") or [],
                }
            }
        studies = _collection_items(_simulation_study_collection(sim_product))
        return {
            "result": {
                "readOnly": True,
                "studyCount": len(studies),
                "includeDetails": bool(include_details),
                "studies": [
                    _simulation_study_report(study, index=index) if include_details else {
                        "index": index,
                        "name": _safe_value(lambda study=study: study.name),
                        "studyType": _safe_value(lambda study=study: study.studyType) or _safe_value(lambda study=study: study.analysisType),
                    }
                    for index, study in enumerate(studies)
                ],
                "blockingReasons": [],
                "warnings": [
                    "This tool only inspects exposed Simulation study metadata; it does not mesh, solve, or export results.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to list simulation studies: {str(e)}"}


_SIMULATION_STUDY_TYPES = {
    "static_stress",
    "modal_frequencies",
    "thermal",
    "thermal_stress",
    "buckling",
    "shape_optimization",
    "event_simulation",
}


@register_tool("plan_simulation_study")
def plan_simulation_study(study_name=None, study_type=None, target_body_names=None, target_body_entity_tokens=None, materials=None, loads=None, constraints=None, contacts=None, mesh_settings=None, result_outputs=None, requires_user_approval=False):
    """
    Read-only simulation study plan validator.

    This deliberately requires study scope, materials, loads, constraints, mesh
    settings, requested outputs, and explicit approval before future mutators
    could create, mesh, solve, or export a Simulation study.
    """
    try:
        blockers = []
        warnings = []
        study_name = str(study_name or "").strip()
        study_type_value = str(study_type or "").strip().lower()
        if not study_name:
            blockers.append("study_name is required.")
        if study_type_value not in _SIMULATION_STUDY_TYPES:
            blockers.append(f"study_type must be one of {sorted(_SIMULATION_STUDY_TYPES)}.")

        target_names = _normalize_name_list(target_body_names)
        target_tokens = _normalize_name_list(target_body_entity_tokens)
        target_matches = _resolve_named_body_set(names=target_names, entity_tokens=target_tokens, include_all=False)[0] if (target_names or target_tokens) else []
        if not target_names and not target_tokens:
            blockers.append("target_body_names or target_body_entity_tokens are required.")
        elif not target_matches:
            blockers.append("No matching target bodies were found for the simulation study.")

        material_data = _non_empty_mapping(materials, "materials", blockers)
        load_data = _non_empty_mapping(loads, "loads", blockers)
        constraint_data = _non_empty_mapping(constraints, "constraints", blockers)
        mesh_data = _non_empty_mapping(mesh_settings, "mesh_settings", blockers)
        output_data = _non_empty_mapping(result_outputs, "result_outputs", blockers)
        contact_data = dict(contacts or {}) if isinstance(contacts, dict) else {}
        if contacts is not None and not isinstance(contacts, dict):
            blockers.append("contacts must be an object when supplied.")
        if requires_user_approval is not True:
            blockers.append("requires_user_approval must be true before any simulation study creation, meshing, solving, or result export.")

        workspace = inspect_simulation_workspace()
        workspace_result = workspace.get("result") if isinstance(workspace, dict) else None
        if not workspace_result or not workspace_result.get("workspaceAvailable"):
            blockers.append("Simulation workspace is unavailable in the active document.")
        else:
            warnings.extend(workspace_result.get("warnings") or [])

        target_reports = [
            _body_snapshot(body, component_name)
            for body, component_name in target_matches
        ]
        ok_to_proceed = not blockers
        return {
            "result": {
                "readOnly": True,
                "okToProceed": ok_to_proceed,
                "riskLevel": "medium" if ok_to_proceed else "high",
                "blockingReasons": blockers,
                "study": {
                    "name": study_name,
                    "type": study_type_value,
                    "targetBodies": target_reports,
                    "materials": material_data,
                    "loads": load_data,
                    "constraints": constraint_data,
                    "contacts": contact_data,
                    "meshSettings": mesh_data,
                    "resultOutputs": output_data,
                },
                "requiresUserApproval": bool(requires_user_approval),
                "workspace": workspace_result,
                "warnings": warnings + [
                    "This is a read-only simulation plan; it does not create studies, apply loads, mesh, solve, or export results.",
                    "Simulation assumptions must be explicit and verified by a qualified user before relying on results.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan simulation study: {str(e)}"}


@register_tool("inspect_manufacturing_workspace")
def inspect_manufacturing_workspace():
    try:
        cam_product = _active_manufacturing_product()
        blockers = []
        warnings = []
        if not cam_product:
            blockers.append("Fusion did not expose an active CAM/manufacturing product for this document.")
        report = _cam_product_report(cam_product)
        if cam_product and not report.get("setupsAvailable"):
            warnings.append("A manufacturing-like product was found, but no setup collection was exposed.")
        return {
            "result": {
                "readOnly": True,
                "workspaceAvailable": bool(cam_product),
                "okToInspectSetups": bool(cam_product and report and report.get("setupsAvailable")),
                "blockingReasons": blockers,
                "manufacturingProduct": report,
                "warnings": warnings,
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect manufacturing workspace: {str(e)}"}


@register_tool("list_manufacturing_setups")
def list_manufacturing_setups(include_operations=True):
    try:
        workspace = inspect_manufacturing_workspace()
        if "error" in workspace:
            return workspace
        cam_product = _active_manufacturing_product()
        if not cam_product:
            return {
                "result": {
                    "readOnly": True,
                    "setupCount": 0,
                    "setups": [],
                    "blockingReasons": (workspace.get("result") or {}).get("blockingReasons") or ["Manufacturing workspace unavailable."],
                    "warnings": (workspace.get("result") or {}).get("warnings") or [],
                }
            }
        setups = _collection_items(_cam_setup_collection(cam_product))
        return {
            "result": {
                "readOnly": True,
                "setupCount": len(setups),
                "includeOperations": bool(include_operations),
                "setups": [_setup_report(setup, index=index, include_operations=include_operations) for index, setup in enumerate(setups)],
                "blockingReasons": [],
                "warnings": [],
            }
        }
    except Exception as e:
        return {"error": f"Failed to list manufacturing setups: {str(e)}"}


@register_tool("inspect_operation")
def inspect_operation(operation_name=None, setup_name=None, operation_index=None):
    try:
        setups_result = list_manufacturing_setups(include_operations=True)
        if "error" in setups_result:
            return setups_result
        result = setups_result.get("result") or {}
        matches = []
        for setup in result.get("setups") or []:
            if setup_name and setup.get("name") != setup_name:
                continue
            for operation in setup.get("operations") or []:
                if operation_name and operation.get("name") != operation_name:
                    continue
                if operation_index is not None:
                    try:
                        if int(operation_index) != int(operation.get("index")):
                            continue
                    except Exception:
                        continue
                matches.append(operation)
        blockers = []
        if result.get("blockingReasons"):
            blockers.extend(result.get("blockingReasons"))
        if not operation_name and operation_index is None:
            blockers.append("operation_name or operation_index is required.")
        if not matches and not blockers:
            blockers.append("No matching manufacturing operation was found.")
        return {
            "result": {
                "readOnly": True,
                "matchCount": len(matches),
                "operations": matches,
                "blockingReasons": blockers,
                "warnings": [
                    "This tool only inspects exposed CAM operation metadata; it does not generate toolpaths or post-process output.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect manufacturing operation: {str(e)}"}


_MANUFACTURING_OPERATION_TYPES = {
    "2d_contour",
    "2d_pocket",
    "adaptive",
    "drill",
    "face",
    "trace",
}


def _non_empty_mapping(value, label, blockers):
    if not isinstance(value, dict) or not value:
        blockers.append(f"{label} must be a non-empty object.")
        return {}
    missing = [key for key, item in value.items() if item in (None, "")]
    if missing:
        blockers.append(f"{label} contains empty values for: {', '.join(str(key) for key in missing)}.")
    return dict(value)


def _numeric_positive_mapping(value, label, blockers):
    data = _non_empty_mapping(value, label, blockers)
    for key, item in data.items():
        try:
            number = float(item)
        except (TypeError, ValueError):
            blockers.append(f"{label}.{key} must be numeric.")
            continue
        if number <= 0:
            blockers.append(f"{label}.{key} must be greater than zero.")
    return data


@register_tool("plan_manufacturing_operation")
def plan_manufacturing_operation(setup_name=None, operation_name=None, operation_type=None, machine=None, stock=None, wcs=None, tool=None, feeds=None, speeds=None, post_processor=None, requires_user_approval=False):
    """
    Read-only CAM setup/operation plan validator.

    This deliberately requires production-critical inputs and never infers
    machines, stock, WCS, tools, feeds, speeds, or post processors.
    """
    try:
        blockers = []
        warnings = []
        setup_name = str(setup_name or "").strip()
        operation_name = str(operation_name or "").strip()
        operation_type = str(operation_type or "").strip().lower()
        if not setup_name:
            blockers.append("setup_name is required.")
        if not operation_name:
            blockers.append("operation_name is required.")
        if operation_type not in _MANUFACTURING_OPERATION_TYPES:
            blockers.append(f"operation_type must be one of {sorted(_MANUFACTURING_OPERATION_TYPES)}.")

        machine_data = _non_empty_mapping(machine, "machine", blockers)
        stock_data = _non_empty_mapping(stock, "stock", blockers)
        wcs_data = _non_empty_mapping(wcs, "wcs", blockers)
        tool_data = _non_empty_mapping(tool, "tool", blockers)
        feed_data = _numeric_positive_mapping(feeds, "feeds", blockers)
        speed_data = _numeric_positive_mapping(speeds, "speeds", blockers)
        post_data = _non_empty_mapping(post_processor, "post_processor", blockers)

        workspace = inspect_manufacturing_workspace().get("result")
        if workspace:
            warnings.extend(workspace.get("warnings") or [])
        else:
            warnings.append("Manufacturing workspace preflight could not be evaluated in this runtime.")
        if workspace and workspace.get("blockingReasons"):
            blockers.extend(workspace.get("blockingReasons"))

        approved = bool(requires_user_approval)
        if not approved:
            blockers.append("requires_user_approval must be true before any future toolpath generation or post-processing step.")

        ok_to_proceed = not blockers
        return {
            "result": {
                "readOnly": True,
                "okToProceed": ok_to_proceed,
                "riskLevel": "medium" if ok_to_proceed else "high",
                "blockingReasons": blockers,
                "setup": {
                    "name": setup_name,
                    "machine": machine_data,
                    "stock": stock_data,
                    "wcs": wcs_data,
                },
                "operation": {
                    "name": operation_name,
                    "type": operation_type,
                    "tool": tool_data,
                    "feeds": feed_data,
                    "speeds": speed_data,
                },
                "postProcessor": post_data,
                "requiresUserApproval": approved,
                "workspace": workspace,
                "warnings": warnings + [
                    "This is a read-only manufacturing plan; it does not create setups, create operations, generate toolpaths, or post-process output.",
                    "Production parameters must come from the user or verified shop data; FusionMCP does not infer them.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan manufacturing operation: {str(e)}"}


def _manufacturing_plan_or_error(setup_name=None, operation_name=None, operation_type=None, machine=None, stock=None, wcs=None, tool=None, feeds=None, speeds=None, post_processor=None, requires_user_approval=False, action="manufacturing action"):
    plan = plan_manufacturing_operation(
        setup_name=setup_name,
        operation_name=operation_name,
        operation_type=operation_type,
        machine=machine,
        stock=stock,
        wcs=wcs,
        tool=tool,
        feeds=feeds,
        speeds=speeds,
        post_processor=post_processor,
        requires_user_approval=requires_user_approval,
    )
    if "error" in plan:
        return None, plan
    plan_result = plan.get("result") or {}
    if not plan_result.get("okToProceed"):
        return None, {
            "error": f"Manufacturing preflight failed before {action}.",
            "preflight": plan_result,
        }
    return plan_result, None


def _cam_collection_add(collection, payload):
    if not collection or not hasattr(collection, "add"):
        return None, "CAM collection did not expose add()."
    if hasattr(collection, "createInput"):
        variants = [(payload,), tuple()]
        last_error = None
        for args in variants:
            try:
                input_obj = collection.createInput(*args)
                if input_obj is not None:
                    for key, value in payload.items():
                        if hasattr(input_obj, key):
                            setattr(input_obj, key, value)
                    return collection.add(input_obj), None
            except TypeError as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)
                break
        if last_error:
            return None, f"CAM collection createInput failed: {last_error}"
    variants = [(payload,), tuple(payload.values()), tuple()]
    last_error = None
    for args in variants:
        try:
            return collection.add(*args), None
        except TypeError as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
            break
    return None, f"CAM collection did not accept a compatible add() signature: {last_error}"


def _find_cam_setup(cam_product, setup_name=None):
    for setup in _collection_items(_cam_setup_collection(cam_product)):
        if not setup_name or _safe_value(lambda setup=setup: setup.name) == setup_name:
            return setup
    return None


def _find_cam_operation(cam_product, setup_name=None, operation_name=None):
    setup = _find_cam_setup(cam_product, setup_name=setup_name)
    if not setup:
        return None, None
    for operation in _collection_items(_safe_value(lambda: setup.operations)):
        if not operation_name or _safe_value(lambda operation=operation: operation.name) == operation_name:
            return setup, operation
    return setup, None


def _compare_manufacturing_mutation(before):
    try:
        after = _design_state_snapshot(include_selections=False)
        return compare_design_state(before, after).get("result")
    except Exception:
        return None


@register_tool("create_manufacturing_setup")
def create_manufacturing_setup(setup_name=None, operation_name=None, operation_type=None, machine=None, stock=None, wcs=None, tool=None, feeds=None, speeds=None, post_processor=None, requires_user_approval=False):
    try:
        plan_result, error = _manufacturing_plan_or_error(
            setup_name=setup_name,
            operation_name=operation_name,
            operation_type=operation_type,
            machine=machine,
            stock=stock,
            wcs=wcs,
            tool=tool,
            feeds=feeds,
            speeds=speeds,
            post_processor=post_processor,
            requires_user_approval=requires_user_approval,
            action="creating manufacturing setup",
        )
        if error:
            return error
        cam_product = _active_manufacturing_product()
        setups = _cam_setup_collection(cam_product)
        if not setups:
            return {
                "error": "Fusion did not expose a writable CAM setup collection.",
                "unsupported": True,
                "preflight": plan_result,
            }
        before = _design_state_snapshot(include_selections=False)
        setup, add_error = _cam_collection_add(setups, {"setup": plan_result.get("setup"), "operation": plan_result.get("operation"), "postProcessor": plan_result.get("postProcessor")})
        if add_error:
            return {"error": add_error, "unsupported": True, "preflight": plan_result}
        if setup_name and hasattr(setup, "name"):
            setup.name = setup_name
        return {
            "result": {
                "message": "Created manufacturing setup from explicit plan.",
                "setupName": _safe_value(lambda: setup.name) or setup_name,
                "setupObjectType": _safe_value(lambda: setup.objectType),
                "preflight": plan_result,
                "stateComparison": _compare_manufacturing_mutation(before),
            }
        }
    except Exception as e:
        return {"error": f"Failed to create manufacturing setup: {str(e)}"}


@register_tool("create_manufacturing_operation")
def create_manufacturing_operation(setup_name=None, operation_name=None, operation_type=None, machine=None, stock=None, wcs=None, tool=None, feeds=None, speeds=None, post_processor=None, requires_user_approval=False):
    try:
        plan_result, error = _manufacturing_plan_or_error(
            setup_name=setup_name,
            operation_name=operation_name,
            operation_type=operation_type,
            machine=machine,
            stock=stock,
            wcs=wcs,
            tool=tool,
            feeds=feeds,
            speeds=speeds,
            post_processor=post_processor,
            requires_user_approval=requires_user_approval,
            action="creating manufacturing operation",
        )
        if error:
            return error
        cam_product = _active_manufacturing_product()
        setup = _find_cam_setup(cam_product, setup_name=setup_name)
        if not setup:
            return {"error": f"Manufacturing setup '{setup_name}' was not found.", "preflight": plan_result}
        operations = _safe_value(lambda: setup.operations)
        if not operations:
            return {"error": "Fusion did not expose a writable operation collection for this setup.", "unsupported": True, "preflight": plan_result}
        before = _design_state_snapshot(include_selections=False)
        operation, add_error = _cam_collection_add(operations, {"setup": plan_result.get("setup"), "operation": plan_result.get("operation"), "postProcessor": plan_result.get("postProcessor")})
        if add_error:
            return {"error": add_error, "unsupported": True, "preflight": plan_result}
        if operation_name and hasattr(operation, "name"):
            operation.name = operation_name
        return {
            "result": {
                "message": "Created manufacturing operation from explicit plan.",
                "setupName": _safe_value(lambda: setup.name),
                "operationName": _safe_value(lambda: operation.name) or operation_name,
                "operationObjectType": _safe_value(lambda: operation.objectType),
                "preflight": plan_result,
                "stateComparison": _compare_manufacturing_mutation(before),
            }
        }
    except Exception as e:
        return {"error": f"Failed to create manufacturing operation: {str(e)}"}


@register_tool("generate_toolpaths")
def generate_toolpaths(setup_name=None, operation_name=None, operation_type=None, machine=None, stock=None, wcs=None, tool=None, feeds=None, speeds=None, post_processor=None, requires_user_approval=False):
    try:
        plan_result, error = _manufacturing_plan_or_error(
            setup_name=setup_name,
            operation_name=operation_name,
            operation_type=operation_type,
            machine=machine,
            stock=stock,
            wcs=wcs,
            tool=tool,
            feeds=feeds,
            speeds=speeds,
            post_processor=post_processor,
            requires_user_approval=requires_user_approval,
            action="generating toolpaths",
        )
        if error:
            return error
        cam_product = _active_manufacturing_product()
        setup, operation = _find_cam_operation(cam_product, setup_name=setup_name, operation_name=operation_name)
        target = operation or setup
        if not target:
            return {"error": "Target setup or operation was not found for toolpath generation.", "preflight": plan_result}
        method = _safe_value(lambda: target.generateToolpath) or _safe_value(lambda: cam_product.generateToolpath)
        if not callable(method):
            return {"error": "Fusion did not expose a compatible toolpath generation method.", "unsupported": True, "preflight": plan_result}
        before = _design_state_snapshot(include_selections=False)
        try:
            generated = method(target)
        except TypeError:
            generated = method()
        return {
            "result": {
                "message": "Generated manufacturing toolpaths from explicit approved plan.",
                "setupName": _safe_value(lambda: setup.name),
                "operationName": _safe_value(lambda: operation.name),
                "generated": bool(True if generated is None else generated),
                "preflight": plan_result,
                "stateComparison": _compare_manufacturing_mutation(before),
            }
        }
    except Exception as e:
        return {"error": f"Failed to generate toolpaths: {str(e)}"}


@register_tool("post_process")
def post_process(output_path=None, setup_name=None, operation_name=None, operation_type=None, machine=None, stock=None, wcs=None, tool=None, feeds=None, speeds=None, post_processor=None, requires_user_approval=False):
    try:
        if not isinstance(output_path, str) or not output_path.strip():
            return {"error": "output_path must be a non-empty absolute path."}
        if "\x00" in output_path:
            return {"error": "output_path contains an invalid null byte."}
        if not os.path.isabs(output_path):
            return {"error": "output_path must be absolute."}
        plan_result, error = _manufacturing_plan_or_error(
            setup_name=setup_name,
            operation_name=operation_name,
            operation_type=operation_type,
            machine=machine,
            stock=stock,
            wcs=wcs,
            tool=tool,
            feeds=feeds,
            speeds=speeds,
            post_processor=post_processor,
            requires_user_approval=requires_user_approval,
            action="post-processing manufacturing output",
        )
        if error:
            return error
        cam_product = _active_manufacturing_product()
        setup, operation = _find_cam_operation(cam_product, setup_name=setup_name, operation_name=operation_name)
        target = operation or setup
        if not target:
            return {"error": "Target setup or operation was not found for post-processing.", "preflight": plan_result}
        method = _safe_value(lambda: target.postProcess) or _safe_value(lambda: cam_product.postProcess)
        if not callable(method):
            return {"error": "Fusion did not expose a compatible post-processing method.", "unsupported": True, "preflight": plan_result}
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        before = _design_state_snapshot(include_selections=False)
        payload = {"outputPath": output_path, "postProcessor": plan_result.get("postProcessor"), "target": target}
        try:
            posted = method(payload)
        except TypeError:
            try:
                posted = method(output_path)
            except TypeError:
                posted = method()
        return {
            "result": {
                "message": "Post-processed manufacturing output from explicit approved plan.",
                "setupName": _safe_value(lambda: setup.name),
                "operationName": _safe_value(lambda: operation.name),
                "outputPath": output_path,
                "posted": bool(True if posted is None else posted),
                "preflight": plan_result,
                "stateComparison": _compare_manufacturing_mutation(before),
                "warnings": ["Verify posted code in the target controller/simulator before running any machine."],
            }
        }
    except Exception as e:
        return {"error": f"Failed to post-process manufacturing output: {str(e)}"}


@register_tool("inspect_surface_bodies")
def inspect_surface_bodies(body_names=None, body_entity_tokens=None, include_invisible=False, include_edges=False):
    try:
        requested_names = set(_normalize_name_list(body_names))
        requested_tokens = set(_normalize_name_list(body_entity_tokens))
        include_all = not requested_names and not requested_tokens
        bodies, missing_names, missing_tokens = _resolve_named_body_set(
            names=requested_names,
            entity_tokens=requested_tokens,
            include_all=include_all,
        )
        reports = []
        for body, component_name in bodies:
            if not include_invisible and _safe_value(lambda body=body: body.isVisible) is False:
                continue
            reports.append(_surface_body_report(body, component_name, include_edges=include_edges))
        surface_reports = [report for report in reports if report.get("classification") == "surface"]
        warnings = [
            "This is a read-only classification report. Repair tools must require explicit targets and reasons.",
            "Open-edge counts are best-effort and depend on Fusion exposing edge-to-face adjacency.",
        ]
        if missing_names:
            warnings.append(f"Body names not found: {', '.join(missing_names)}")
        if missing_tokens:
            warnings.append(f"Body entity tokens not found: {', '.join(missing_tokens)}")
        return {
            "result": {
                "readOnly": True,
                "bodyCount": len(reports),
                "surfaceBodyCount": len(surface_reports),
                "solidBodyCount": len([report for report in reports if report.get("classification") == "solid"]),
                "bodies": reports,
                "missingBodyNames": missing_names,
                "missingBodyEntityTokens": missing_tokens,
                "recommendedWorkflow": [
                    "Use entityToken/bodyName from this report before any surface repair.",
                    "Run patch/stitch/thicken/trim/extend only as explicit separate mutations with reason fields.",
                    "Validate model health after every repair mutation.",
                ],
                "warnings": warnings,
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect surface bodies: {str(e)}"}


_SURFACE_REPAIR_OPERATIONS = {
    "patch_surface",
    "stitch_surfaces",
    "thicken_surface",
    "trim_surface",
    "extend_surface",
    "create_ruled_surface",
}
_SURFACE_REPAIR_REASONED_OPERATIONS = {
    "stitch_surfaces",
    "thicken_surface",
    "trim_surface",
    "extend_surface",
}


@register_tool("plan_surface_repair")
def plan_surface_repair(operation=None, body_name=None, body_entity_token=None, edge_entity_tokens=None, face_entity_tokens=None, parameters=None, reason=None, allow_solid_body=False):
    """
    Read-only surface repair/creation plan validator.

    This verifies explicit targets and reason fields before any future surface
    mutator is allowed. It does not patch, stitch, thicken, trim, extend, or
    create ruled surfaces.
    """
    try:
        operation_name = str(operation or "").strip().lower()
        blockers = []
        warnings = []
        if operation_name not in _SURFACE_REPAIR_OPERATIONS:
            blockers.append(f"operation must be one of {sorted(_SURFACE_REPAIR_OPERATIONS)}.")
        if not body_name and not body_entity_token:
            blockers.append("body_name or body_entity_token is required.")
        if operation_name in _SURFACE_REPAIR_REASONED_OPERATIONS and (not isinstance(reason, str) or not reason.strip()):
            blockers.append(f"reason is required for {operation_name}.")
        if parameters is not None and not isinstance(parameters, dict):
            blockers.append("parameters must be an object when supplied.")

        edge_tokens = _normalize_name_list(edge_entity_tokens)
        face_tokens = _normalize_name_list(face_entity_tokens)
        if operation_name in {"patch_surface", "stitch_surfaces", "extend_surface"} and not edge_tokens:
            blockers.append(f"edge_entity_tokens are required for {operation_name}.")
        if operation_name in {"trim_surface", "create_ruled_surface"} and not face_tokens and not edge_tokens:
            blockers.append(f"face_entity_tokens or edge_entity_tokens are required for {operation_name}.")

        inspection = inspect_surface_bodies(
            body_names=[body_name] if body_name else None,
            body_entity_tokens=[body_entity_token] if body_entity_token else None,
            include_edges=True,
        )
        inspection_result = inspection.get("result") if isinstance(inspection, dict) else None
        target = None
        if inspection_result:
            warnings.extend(inspection_result.get("warnings") or [])
            bodies = inspection_result.get("bodies") or []
            if bodies:
                target = bodies[0]
                if target.get("classification") == "solid" and not allow_solid_body:
                    blockers.append("Target body is solid; set allow_solid_body=true only when the selected operation intentionally works on solid-body faces.")
                candidate_tools = set(target.get("candidateRepairTools") or [])
                if operation_name in _SURFACE_REPAIR_OPERATIONS and operation_name not in candidate_tools and operation_name != "create_ruled_surface":
                    warnings.append(f"Operation '{operation_name}' was not listed as a candidate repair for the target body.")
            else:
                blockers.append("No matching target body was found.")
        else:
            blockers.append("Surface inspection failed before planning repair.")

        ok_to_proceed = not blockers
        return {
            "result": {
                "readOnly": True,
                "okToProceed": ok_to_proceed,
                "riskLevel": "medium" if ok_to_proceed else "high",
                "blockingReasons": blockers,
                "operation": operation_name,
                "target": target,
                "edgeEntityTokens": edge_tokens,
                "faceEntityTokens": face_tokens,
                "parameters": dict(parameters or {}),
                "reason": reason,
                "allowSolidBody": bool(allow_solid_body),
                "inspection": inspection_result,
                "warnings": warnings + [
                    "This is a read-only surface repair plan; it does not patch, stitch, thicken, trim, extend, or create ruled surfaces.",
                    "Future repair tools must compare design state after mutation and validate model health.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan surface repair: {str(e)}"}


def _sheet_metal_rules(design):
    rules = []
    for attr in ("sheetMetalRules", "sheetMetalRuleLibrary", "sheetMetalRuleLibraries"):
        exposed = _safe_value(lambda attr=attr: getattr(design, attr))
        if not exposed:
            continue
        if hasattr(exposed, "rules"):
            exposed = _safe_value(lambda exposed=exposed: exposed.rules)
        rules.extend(_collection_items(exposed))
    seen = set()
    unique = []
    for rule in rules:
        key = _safe_value(lambda rule=rule: rule.name) or id(rule)
        if key in seen:
            continue
        seen.add(key)
        unique.append(rule)
    return unique


@register_tool("inspect_sheet_metal_rules")
def inspect_sheet_metal_rules():
    try:
        design = get_active_design()
        active_rule = (
            _safe_value(lambda: design.activeSheetMetalRule)
            or _safe_value(lambda: design.sheetMetalRule)
            or _safe_value(lambda: design.defaultSheetMetalRule)
        )
        rules = _sheet_metal_rules(design)
        active_name = _safe_value(lambda: active_rule.name)
        bodies = [_body_sheet_metal_report(body, component_name) for body, component_name in _body_objects(design.rootComponent)]
        sheet_bodies = [body for body in bodies if body.get("isSheetMetal")]
        warnings = []
        if not active_rule:
            warnings.append("Fusion did not expose an active sheet-metal rule for this design.")
        if not rules:
            warnings.append("Fusion did not expose a sheet-metal rule collection through this API surface.")
        if not sheet_bodies:
            warnings.append("No sheet-metal bodies were detected by exposed body metadata.")
        return {
            "result": {
                "readOnly": True,
                "designType": _safe_value(lambda: design.designType),
                "activeRule": _rule_report(active_rule, active=True),
                "ruleCount": len(rules),
                "rules": [
                    _rule_report(rule, index=index, active=(_safe_value(lambda rule=rule: rule.name) == active_name))
                    for index, rule in enumerate(rules)
                ],
                "bodyCount": len(bodies),
                "sheetMetalBodyCount": len(sheet_bodies),
                "bodies": bodies,
                "warnings": warnings,
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect sheet-metal rules: {str(e)}"}


@register_tool("preflight_flat_pattern")
def preflight_flat_pattern(body_name=None, body_entity_token=None):
    try:
        inspection = inspect_sheet_metal_rules()
        if "error" in inspection:
            return inspection
        result = inspection.get("result") or {}
        matches = _resolve_bodies(body_name=body_name, body_entity_token=body_entity_token, include_all=False)
        if body_name is None and body_entity_token is None:
            matches = [
                (body, component_name)
                for body, component_name in _body_objects(get_active_design().rootComponent)
                if _body_sheet_metal_report(body, component_name).get("isSheetMetal")
            ]
        blockers = []
        warnings = list(result.get("warnings") or [])
        if not result.get("activeRule"):
            blockers.append("No active sheet-metal rule was exposed.")
        if not matches:
            blockers.append("No target sheet-metal body was found. Provide body_name/body_entity_token from inspection or create a sheet-metal body first.")
        target_reports = [_body_sheet_metal_report(body, component_name) for body, component_name in matches]
        for target in target_reports:
            if not target.get("isSheetMetal"):
                blockers.append(f"Target body '{target.get('bodyName')}' is not identified as sheet metal by exposed metadata.")

        design = get_active_design()
        flat_pattern = _safe_value(lambda: design.flatPattern) or _safe_value(lambda: design.rootComponent.flatPattern)
        if not flat_pattern and matches:
            flat_pattern = _safe_value(lambda: matches[0][0].flatPattern)
        can_export = bool(flat_pattern) and not blockers
        if not flat_pattern:
            warnings.append("Fusion did not expose an existing flatPattern object; unfold/export tooling should remain blocked until a reliable API path is verified.")

        return {
            "result": {
                "readOnly": True,
                "okToProceed": can_export,
                "riskLevel": "low" if can_export else "high",
                "blockingReasons": blockers,
                "activeRule": result.get("activeRule"),
                "targetBodies": target_reports,
                "flatPatternAvailable": bool(flat_pattern),
                "flatPattern": _entity_ref(flat_pattern) if flat_pattern else None,
                "warnings": warnings,
            }
        }
    except Exception as e:
        return {"error": f"Failed to preflight flat pattern: {str(e)}"}


_SHEET_METAL_OPERATIONS = {
    "create_flange",
    "create_bend",
    "unfold_sheet_metal",
    "refold_sheet_metal",
    "export_flat_pattern",
}


@register_tool("plan_sheet_metal_workflow")
def plan_sheet_metal_workflow(operation=None, body_name=None, body_entity_token=None, edge_entity_tokens=None, face_entity_tokens=None, rule_name=None, parameters=None, reason=None):
    """
    Read-only sheet-metal workflow planner.

    This validates explicit operation intent, targets, rule selection, and
    parameters before future sheet-metal mutators are allowed. It does not
    create flanges/bends, unfold/refold, or export files.
    """
    try:
        operation_name = str(operation or "").strip().lower()
        blockers = []
        warnings = []
        if operation_name not in _SHEET_METAL_OPERATIONS:
            blockers.append(f"operation must be one of {sorted(_SHEET_METAL_OPERATIONS)}.")
        if parameters is not None and not isinstance(parameters, dict):
            blockers.append("parameters must be an object when supplied.")
        if operation_name in {"create_flange", "create_bend"} and not rule_name:
            blockers.append("rule_name is required for creation operations; do not infer sheet-metal rules.")
        if operation_name in {"create_flange", "create_bend", "unfold_sheet_metal", "refold_sheet_metal"} and (not isinstance(reason, str) or not reason.strip()):
            blockers.append(f"reason is required for {operation_name}.")

        edge_tokens = _normalize_name_list(edge_entity_tokens)
        face_tokens = _normalize_name_list(face_entity_tokens)
        if operation_name == "create_flange" and not edge_tokens:
            blockers.append("edge_entity_tokens are required for create_flange.")
        if operation_name == "create_bend" and not face_tokens and not edge_tokens:
            blockers.append("face_entity_tokens or edge_entity_tokens are required for create_bend.")

        inspection = inspect_sheet_metal_rules()
        inspection_result = inspection.get("result") if isinstance(inspection, dict) else None
        target_report = None
        if inspection_result:
            warnings.extend(inspection_result.get("warnings") or [])
            rules = inspection_result.get("rules") or []
            active_rule = inspection_result.get("activeRule")
            rule_names = {rule.get("name") for rule in rules if rule.get("name")}
            if active_rule and active_rule.get("name"):
                rule_names.add(active_rule.get("name"))
            if rule_name and rule_name not in rule_names:
                blockers.append(f"rule_name '{rule_name}' was not found in inspected sheet-metal rules.")
            matches = []
            for body in inspection_result.get("bodies") or []:
                if body_name and body.get("bodyName") != body_name and body.get("key") != body_name:
                    continue
                if body_entity_token and body.get("entityToken") != body_entity_token:
                    continue
                if body_name or body_entity_token:
                    matches.append(body)
            if body_name or body_entity_token:
                if not matches:
                    blockers.append("No matching target sheet-metal body was found.")
                else:
                    target_report = matches[0]
                    if not target_report.get("isSheetMetal"):
                        blockers.append(f"Target body '{target_report.get('bodyName')}' is not identified as sheet metal by exposed metadata.")
            elif operation_name in {"unfold_sheet_metal", "refold_sheet_metal", "export_flat_pattern"}:
                blockers.append("body_name or body_entity_token is required for existing sheet-metal body operations.")
        else:
            blockers.append("Sheet-metal inspection failed before planning workflow.")

        flat_preflight = None
        if operation_name in {"unfold_sheet_metal", "refold_sheet_metal", "export_flat_pattern"}:
            flat = preflight_flat_pattern(body_name=body_name, body_entity_token=body_entity_token)
            flat_preflight = flat.get("result") if isinstance(flat, dict) else None
            if flat_preflight:
                warnings.extend(flat_preflight.get("warnings") or [])
                if flat_preflight.get("blockingReasons") and operation_name == "export_flat_pattern":
                    blockers.extend(flat_preflight.get("blockingReasons"))
            else:
                blockers.append("Flat-pattern preflight failed before planning workflow.")

        ok_to_proceed = not blockers
        return {
            "result": {
                "readOnly": True,
                "okToProceed": ok_to_proceed,
                "riskLevel": "medium" if ok_to_proceed else "high",
                "blockingReasons": blockers,
                "operation": operation_name,
                "targetBody": target_report,
                "ruleName": rule_name,
                "edgeEntityTokens": edge_tokens,
                "faceEntityTokens": face_tokens,
                "parameters": dict(parameters or {}),
                "reason": reason,
                "inspection": inspection_result,
                "flatPatternPreflight": flat_preflight,
                "warnings": warnings + [
                    "This is a read-only sheet-metal workflow plan; it does not create flanges, create bends, unfold, refold, or export files.",
                    "Sheet-metal rules, material, bend allowances, and manufacturing parameters must be explicit; FusionMCP does not infer them.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan sheet-metal workflow: {str(e)}"}


def _normalize_name_list(names):
    if names is None:
        return []
    if isinstance(names, str):
        return [names]
    try:
        return [str(name) for name in names if str(name).strip()]
    except TypeError:
        return [str(names)]


def _body_key(body, component_name):
    return f"{component_name}/{_safe_value(lambda: body.name)}"


def _resolve_named_body_set(names=None, entity_tokens=None, include_all=False):
    design = get_active_design()
    requested_names = set(_normalize_name_list(names))
    requested_tokens = set(_normalize_name_list(entity_tokens))
    include_everything = bool(include_all) or (not requested_names and not requested_tokens)
    matches = []
    missing_names = set(requested_names)
    missing_tokens = set(requested_tokens)

    for body, component_name in _body_objects(design.rootComponent):
        body_name = _safe_value(lambda body=body: body.name)
        key = _body_key(body, component_name)
        token = _safe_value(lambda body=body: body.entityToken)
        name_match = body_name in requested_names or key in requested_names
        token_match = token in requested_tokens if token else False
        if include_everything or name_match or token_match:
            matches.append((body, component_name))
            missing_names.discard(body_name)
            missing_names.discard(key)
            if token:
                missing_tokens.discard(token)

    return matches, sorted(missing_names), sorted(missing_tokens)


def _bbox_axis_gap_cm(a, b, axis):
    if a["max"][axis] < b["min"][axis]:
        return b["min"][axis] - a["max"][axis]
    if b["max"][axis] < a["min"][axis]:
        return a["min"][axis] - b["max"][axis]
    return 0.0


def _bbox_axis_overlap_cm(a, b, axis):
    return min(a["max"][axis], b["max"][axis]) - max(a["min"][axis], b["min"][axis])


def _bbox_axis_size_mm(bbox, axis):
    if not bbox:
        return None
    return round((bbox["max"][axis] - bbox["min"][axis]) * 10.0, 6)


def _bbox_axis_center_mm(bbox, axis):
    if not bbox:
        return None
    return round(((bbox["min"][axis] + bbox["max"][axis]) / 2.0) * 10.0, 6)


def _axis_index(axis):
    key = str(axis or "z").strip().lower().lstrip("+-")
    return {"x": 0, "y": 1, "z": 2}.get(key, 2)


def _footprint_axes(thickness_axis):
    axis = _axis_index(thickness_axis)
    return [index for index in range(3) if index != axis]


def _bbox_footprint_overlap_report(a, b, footprint_axes):
    overlaps_cm = [_bbox_axis_overlap_cm(a, b, axis) for axis in footprint_axes]
    overlaps_mm = [round(max(0.0, overlap) * 10.0, 6) for overlap in overlaps_cm]
    return {
        "overlaps": all(overlap > 0 for overlap in overlaps_cm),
        "overlapMm": overlaps_mm,
        "overlapAreaMm2": round(overlaps_mm[0] * overlaps_mm[1], 6) if len(overlaps_mm) == 2 else None,
    }


def _bbox_pair_report(body_a, component_a, body_b, component_b, minimum_clearance_mm=0.0):
    bbox_a = _bbox_to_dict(body_a)
    bbox_b = _bbox_to_dict(body_b)
    if not bbox_a or not bbox_b:
        return None
    gaps_cm = [_bbox_axis_gap_cm(bbox_a, bbox_b, axis) for axis in range(3)]
    overlaps_cm = [_bbox_axis_overlap_cm(bbox_a, bbox_b, axis) for axis in range(3)]
    distance_cm = math.sqrt(sum(gap * gap for gap in gaps_cm))
    distance_mm = round(distance_cm * 10.0, 6)
    bbox_intersects = all(overlap >= 0 for overlap in overlaps_cm)
    overlap_mm = [round(max(0.0, overlap) * 10.0, 6) for overlap in overlaps_cm]
    overlap_volume_mm3 = round(overlap_mm[0] * overlap_mm[1] * overlap_mm[2], 6) if bbox_intersects else 0.0
    clearance_ok = not bbox_intersects and distance_mm >= float(minimum_clearance_mm)
    return {
        "bodyA": {
            "bodyName": _safe_value(lambda: body_a.name),
            "componentName": component_a,
            "entityToken": _safe_value(lambda: body_a.entityToken),
            "boundingBox": bbox_a,
        },
        "bodyB": {
            "bodyName": _safe_value(lambda: body_b.name),
            "componentName": component_b,
            "entityToken": _safe_value(lambda: body_b.entityToken),
            "boundingBox": bbox_b,
        },
        "bboxIntersects": bool(bbox_intersects),
        "bboxOverlapMm": overlap_mm if bbox_intersects else [0.0, 0.0, 0.0],
        "bboxOverlapVolumeMm3": overlap_volume_mm3,
        "bboxDistanceMm": distance_mm,
        "minimumClearanceMm": float(minimum_clearance_mm),
        "clearanceOk": bool(clearance_ok),
        "method": "axis_aligned_bounding_box",
    }


def _unique_body_pairs(targets, tools=None):
    if tools is None:
        pairs = []
        for i, first in enumerate(targets):
            for second in targets[i + 1:]:
                pairs.append((first, second))
        return pairs
    pairs = []
    seen = set()
    for first in targets:
        for second in tools:
            if first[0] is second[0]:
                continue
            key = tuple(sorted((id(first[0]), id(second[0]))))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((first, second))
    return pairs


def _api_candidate_status(owner, method_names):
    if owner is None:
        return {"available": False, "method": None}
    for method_name in method_names:
        method = getattr(owner, method_name, None)
        if callable(method):
            return {"available": True, "method": method_name}
    return {"available": False, "method": None}


def _exact_analysis_context():
    app = adsk.core.Application.get()
    design = get_active_design()
    root = design.rootComponent
    temp_brep_cls = getattr(adsk.fusion, "TemporaryBRepManager", None)
    temp_brep_manager = _safe_value(lambda: temp_brep_cls.get()) if temp_brep_cls is not None else None
    boolean_candidate = _api_candidate_status(
        temp_brep_manager,
        (
            "booleanOperation",
            "executeBooleanOperation",
            "booleanOperations",
            "intersect",
        ),
    )
    copy_candidate = _api_candidate_status(temp_brep_manager, ("copy", "copyBody"))
    measure_manager = (
        _safe_value(lambda: app.measureManager)
        or _safe_value(lambda: design.measureManager)
        or _safe_value(lambda: root.measureManager)
    )
    distance_candidate = _api_candidate_status(
        measure_manager,
        (
            "measureMinimumDistance",
            "measureDistance",
            "minimumDistance",
        ),
    )
    return {
        "design": design,
        "root": root,
        "temporaryBRepManager": temp_brep_manager,
        "booleanCandidate": boolean_candidate,
        "copyCandidate": copy_candidate,
        "measureManager": measure_manager,
        "distanceCandidate": distance_candidate,
        "exactInterferenceSupported": bool(temp_brep_manager and boolean_candidate["available"] and copy_candidate["available"]),
        "exactMinimumDistanceSupported": bool(measure_manager and distance_candidate["available"]),
    }


def _temporary_copy(temp_brep_manager, copy_method_name, body):
    method = getattr(temp_brep_manager, copy_method_name, None)
    if not callable(method):
        return None
    return method(body)


def _intersection_operation_type():
    for enum_name in ("BooleanTypes", "FeatureOperations"):
        enum = getattr(adsk.fusion, enum_name, None)
        for attr in ("IntersectionBooleanType", "IntersectBooleanType", "IntersectFeatureOperation"):
            value = getattr(enum, attr, None) if enum is not None else None
            if value is not None:
                return value
    return None


def _truthy_exact_body_result(result):
    if result is None:
        return False
    if isinstance(result, bool):
        return result
    for attr in ("volume", "area"):
        value = _safe_value(lambda attr=attr: getattr(result, attr))
        if isinstance(value, (int, float)) and value > 0:
            return True
    return True


def _run_exact_boolean_intersection(context, body_a, body_b):
    temp_brep_manager = context["temporaryBRepManager"]
    copy_method = context["copyCandidate"]["method"]
    boolean_method = context["booleanCandidate"]["method"]
    copy_a = _temporary_copy(temp_brep_manager, copy_method, body_a)
    copy_b = _temporary_copy(temp_brep_manager, copy_method, body_b)
    if copy_a is None or copy_b is None:
        return None, "TemporaryBRepManager copy method did not return both body copies."
    method = getattr(temp_brep_manager, boolean_method, None)
    if not callable(method):
        return None, f"TemporaryBRepManager method '{boolean_method}' is not callable."
    op_type = _intersection_operation_type()
    variants = []
    if op_type is not None:
        variants.extend([(copy_a, copy_b, op_type), (copy_a, op_type, copy_b)])
    variants.extend([(copy_a, copy_b), (copy_b,), tuple()])
    last_error = None
    for args in variants:
        try:
            result = method(*args)
            return _truthy_exact_body_result(result if result is not None else copy_a), None
        except TypeError as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
            break
    return None, f"Exact Boolean intersection candidate did not accept a supported signature: {last_error}"


def _distance_value_mm(result):
    if result is None:
        return None
    if isinstance(result, (int, float)):
        return float(result) * 10.0
    for attr in ("value", "distance", "minimumDistance"):
        value = _safe_value(lambda attr=attr: getattr(result, attr))
        if isinstance(value, (int, float)):
            return float(value) * 10.0
    return None


def _run_exact_minimum_distance(context, body_a, body_b):
    measure_manager = context["measureManager"]
    method_name = context["distanceCandidate"]["method"]
    method = getattr(measure_manager, method_name, None)
    if not callable(method):
        return None, f"MeasureManager method '{method_name}' is not callable."
    variants = [(body_a, body_b), ([body_a], [body_b]), (body_a,), tuple()]
    last_error = None
    for args in variants:
        try:
            result = method(*args)
            distance_mm = _distance_value_mm(result)
            if distance_mm is None:
                return None, "Exact distance candidate returned no numeric distance value."
            return round(distance_mm, 6), None
        except TypeError as exc:
            last_error = str(exc)
        except Exception as exc:
            last_error = str(exc)
            break
    return None, f"Exact minimum-distance candidate did not accept a supported signature: {last_error}"


@register_tool("inspect_analysis_capabilities")
def inspect_analysis_capabilities():
    """
    Read-only capability probe for exact analysis APIs.

    This does not run exact BRep analysis. It reports whether the current Fusion
    runtime exposes API candidates that would be required before exact
    interference or minimum-distance tools can be implemented honestly.
    """
    try:
        context = _exact_analysis_context()
        root = context["root"]
        bodies = [
            body
            for body, _component_name in _body_objects(root)
            if _safe_value(lambda body=body: body.isVisible, True)
        ]
        exact_interference_ready = context["exactInterferenceSupported"]
        exact_distance_ready = context["exactMinimumDistanceSupported"]
        blockers = []
        if not exact_interference_ready:
            blockers.append("Exact interference is not enabled because a verified TemporaryBRepManager copy plus Boolean intersection path is not exposed.")
        if not exact_distance_ready:
            blockers.append("Exact minimum-distance analysis is not enabled because a verified measure-manager distance path is not exposed.")
        if len(bodies) < 2:
            blockers.append("At least two visible bodies are required for a live exact-analysis fixture probe.")

        return {
            "result": {
                "readOnly": True,
                "broadPhaseAvailable": True,
                "visibleBodyCount": len(bodies),
                "exactInterference": {
                    "supported": exact_interference_ready,
                    "status": "candidate_api_available" if exact_interference_ready else "unsupported",
                    "temporaryBRepManagerAvailable": bool(context["temporaryBRepManager"]),
                    "copyCandidate": context["copyCandidate"],
                    "booleanCandidate": context["booleanCandidate"],
                },
                "exactMinimumDistance": {
                    "supported": exact_distance_ready,
                    "status": "candidate_api_available" if exact_distance_ready else "unsupported",
                    "measureManagerAvailable": bool(context["measureManager"]),
                    "distanceCandidate": context["distanceCandidate"],
                },
                "blockingReasons": blockers,
                "nextStep": "Validate candidate APIs against a throwaway two-body fixture before enabling exact interference or minimum-distance tools.",
                "warnings": [
                    "Candidate API availability is not proof of exact-analysis correctness.",
                    "Current interference_check and clearance_check remain broad-phase unless a verified exact-analysis implementation is added.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect analysis capabilities: {str(e)}"}


@register_tool("interference_check")
def interference_check(body_names=None, body_entity_tokens=None, include_invisible=False, max_pairs=200):
    """
    Read-only broad-phase interference report.

    This reports bounding-box intersections and overlap estimates. It does not
    claim exact BRep Boolean intersection volume unless a future Fusion API path
    is added explicitly.
    """
    try:
        bodies, missing_names, missing_tokens = _resolve_named_body_set(
            names=body_names,
            entity_tokens=body_entity_tokens,
            include_all=not body_names and not body_entity_tokens,
        )
        if not include_invisible:
            bodies = [(body, component) for body, component in bodies if _safe_value(lambda body=body: body.isVisible, True)]
        if len(bodies) < 2:
            return {"error": "interference_check requires at least two matching bodies."}
        try:
            max_pairs = max(1, min(int(max_pairs), 1000))
        except (TypeError, ValueError):
            max_pairs = 200
        checked_pairs = []
        collisions = []
        for first, second in _unique_body_pairs(bodies)[:max_pairs]:
            report = _bbox_pair_report(first[0], first[1], second[0], second[1])
            if not report:
                continue
            checked_pairs.append(report)
            if report["bboxIntersects"]:
                collisions.append(report)
        return {
            "result": {
                "readOnly": True,
                "method": "axis_aligned_bounding_box",
                "bodyCount": len(bodies),
                "pairCount": len(checked_pairs),
                "interferenceCount": len(collisions),
                "interferences": collisions,
                "checkedPairs": checked_pairs,
                "missingBodyNames": missing_names,
                "missingEntityTokens": missing_tokens,
                "warnings": [
                    "This is a broad-phase bounding-box interference check, not an exact Boolean intersection report.",
                    "Use inspect bodies/faces or a future exact-analysis tool before making manufacturing decisions.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to run interference check: {str(e)}"}


@register_tool("clearance_check")
def clearance_check(target_body_names=None, tool_body_names=None, target_body_entity_tokens=None, tool_body_entity_tokens=None, minimum_clearance="0 mm", include_invisible=False, max_pairs=200):
    """
    Read-only broad-phase clearance report between explicit target and tool sets.
    """
    try:
        design = get_active_design()
        minimum_clearance_mm = _length_expression_to_mm(design, minimum_clearance, 0.0)
        targets, missing_target_names, missing_target_tokens = _resolve_named_body_set(
            names=target_body_names,
            entity_tokens=target_body_entity_tokens,
            include_all=False,
        )
        tools, missing_tool_names, missing_tool_tokens = _resolve_named_body_set(
            names=tool_body_names,
            entity_tokens=tool_body_entity_tokens,
            include_all=False,
        )
        if not include_invisible:
            targets = [(body, component) for body, component in targets if _safe_value(lambda body=body: body.isVisible, True)]
            tools = [(body, component) for body, component in tools if _safe_value(lambda body=body: body.isVisible, True)]
        if not targets:
            return {"error": "clearance_check requires at least one target body name or entity token."}
        if not tools:
            return {"error": "clearance_check requires at least one tool body name or entity token."}
        try:
            max_pairs = max(1, min(int(max_pairs), 1000))
        except (TypeError, ValueError):
            max_pairs = 200
        checked_pairs = []
        violations = []
        for first, second in _unique_body_pairs(targets, tools)[:max_pairs]:
            report = _bbox_pair_report(first[0], first[1], second[0], second[1], minimum_clearance_mm)
            if not report:
                continue
            checked_pairs.append(report)
            if report["bboxIntersects"] or report["bboxDistanceMm"] < minimum_clearance_mm:
                violations.append(report)
        return {
            "result": {
                "readOnly": True,
                "method": "axis_aligned_bounding_box",
                "minimumClearanceMm": round(minimum_clearance_mm, 6),
                "targetCount": len(targets),
                "toolCount": len(tools),
                "pairCount": len(checked_pairs),
                "violationCount": len(violations),
                "violations": violations,
                "checkedPairs": checked_pairs,
                "missingTargetBodyNames": missing_target_names,
                "missingTargetEntityTokens": missing_target_tokens,
                "missingToolBodyNames": missing_tool_names,
                "missingToolEntityTokens": missing_tool_tokens,
                "warnings": [
                    "This is a broad-phase bounding-box clearance check, not an exact minimum-distance BRep solver.",
                    "Do not infer manufacturing tolerances; minimum_clearance must be supplied explicitly.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to run clearance check: {str(e)}"}


@register_tool("verify_insert_alignment")
def verify_insert_alignment(plate_body_name=None, socket_body_name=None, logo_body_names=None, plate_body_entity_token=None, socket_body_entity_token=None, logo_body_entity_tokens=None, thickness_axis="z", expected_plate_thickness=None, flush_mode="flush", tolerance="0.05 mm", include_invisible=False):
    """
    Read-only insert/socket pre-export alignment guard.

    This uses axis-aligned bounding boxes as a conservative broad-phase check for
    removable plates, matching sockets/pockets/cutters, and raised logo bodies.
    It does not modify visibility, sketches, features, or bodies.
    """
    try:
        design = get_active_design()
        tolerance_mm = max(0.0, _length_expression_to_mm(design, tolerance, 0.05))
        expected_thickness_mm = (
            _length_expression_to_mm(design, expected_plate_thickness, 0.0)
            if expected_plate_thickness is not None
            else None
        )
        axis = _axis_index(thickness_axis)
        footprint_axes = _footprint_axes(thickness_axis)

        blockers = []
        if not _normalize_name_list(plate_body_name) and not _normalize_name_list(plate_body_entity_token):
            blockers.append("plate_body_name or plate_body_entity_token is required.")
        if not _normalize_name_list(socket_body_name) and not _normalize_name_list(socket_body_entity_token):
            blockers.append("socket_body_name or socket_body_entity_token is required.")
        if blockers:
            return {
                "result": {
                    "readOnly": True,
                    "okToExport": False,
                    "method": "axis_aligned_bounding_box",
                    "blockingReasons": blockers,
                    "warnings": [
                        "This is a broad-phase axis-aligned bounding-box check, not exact BRep contact validation.",
                        "Set thickness_axis to the plate/socket depth axis for the active model orientation.",
                    ],
                }
            }

        plate_matches, missing_plate_names, missing_plate_tokens = _resolve_named_body_set(
            names=plate_body_name,
            entity_tokens=plate_body_entity_token,
            include_all=False,
        )
        socket_matches, missing_socket_names, missing_socket_tokens = _resolve_named_body_set(
            names=socket_body_name,
            entity_tokens=socket_body_entity_token,
            include_all=False,
        )
        requested_logo_names = _normalize_name_list(logo_body_names)
        requested_logo_tokens = _normalize_name_list(logo_body_entity_tokens)
        if requested_logo_names or requested_logo_tokens:
            logo_matches, missing_logo_names, missing_logo_tokens = _resolve_named_body_set(
                names=requested_logo_names,
                entity_tokens=requested_logo_tokens,
                include_all=False,
            )
        else:
            logo_matches, missing_logo_names, missing_logo_tokens = [], [], []
        if not include_invisible:
            plate_matches = [(body, component) for body, component in plate_matches if _safe_value(lambda body=body: body.isVisible, True)]
            socket_matches = [(body, component) for body, component in socket_matches if _safe_value(lambda body=body: body.isVisible, True)]
            logo_matches = [(body, component) for body, component in logo_matches if _safe_value(lambda body=body: body.isVisible, True)]

        warnings = [
            "This is a broad-phase axis-aligned bounding-box check, not exact BRep contact validation.",
            "Set thickness_axis to the plate/socket depth axis for the active model orientation.",
        ]
        if len(plate_matches) != 1:
            blockers.append(f"Expected exactly one plate body, found {len(plate_matches)}.")
        if len(socket_matches) != 1:
            blockers.append(f"Expected exactly one socket/cutter body, found {len(socket_matches)}.")
        if missing_plate_names:
            blockers.append(f"Missing plate body names: {', '.join(missing_plate_names)}.")
        if missing_socket_names:
            blockers.append(f"Missing socket body names: {', '.join(missing_socket_names)}.")
        if missing_logo_names:
            blockers.append(f"Missing logo body names: {', '.join(missing_logo_names)}.")
        if missing_plate_tokens:
            blockers.append(f"Missing plate body entity tokens: {', '.join(missing_plate_tokens)}.")
        if missing_socket_tokens:
            blockers.append(f"Missing socket body entity tokens: {', '.join(missing_socket_tokens)}.")
        if missing_logo_tokens:
            blockers.append(f"Missing logo body entity tokens: {', '.join(missing_logo_tokens)}.")
        if blockers:
            return {
                "result": {
                    "readOnly": True,
                    "okToExport": False,
                    "method": "axis_aligned_bounding_box",
                    "blockingReasons": blockers,
                    "warnings": warnings,
                    "missingBodyNames": sorted(set(missing_plate_names + missing_socket_names + missing_logo_names)),
                    "missingEntityTokens": sorted(set(missing_plate_tokens + missing_socket_tokens + missing_logo_tokens)),
                }
            }

        plate, plate_component = plate_matches[0]
        socket, socket_component = socket_matches[0]
        plate_bbox = _bbox_to_dict(plate)
        socket_bbox = _bbox_to_dict(socket)
        if not plate_bbox:
            blockers.append(f"Plate body '{_safe_value(lambda: plate.name)}' has no bounding box.")
        if not socket_bbox:
            blockers.append(f"Socket body '{_safe_value(lambda: socket.name)}' has no bounding box.")
        if blockers:
            return {
                "result": {
                    "readOnly": True,
                    "okToExport": False,
                    "method": "axis_aligned_bounding_box",
                    "blockingReasons": blockers,
                    "warnings": warnings,
                }
            }

        footprint = _bbox_footprint_overlap_report(plate_bbox, socket_bbox, footprint_axes)
        plate_thickness_mm = _bbox_axis_size_mm(plate_bbox, axis)
        socket_depth_mm = _bbox_axis_size_mm(socket_bbox, axis)
        depth_delta_mm = (
            round(abs(socket_depth_mm - plate_thickness_mm), 6)
            if plate_thickness_mm is not None and socket_depth_mm is not None
            else None
        )
        expected_delta_mm = (
            round(abs(plate_thickness_mm - expected_thickness_mm), 6)
            if expected_thickness_mm is not None and plate_thickness_mm is not None
            else None
        )
        center_delta_mm = [
            round(abs(_bbox_axis_center_mm(plate_bbox, fp_axis) - _bbox_axis_center_mm(socket_bbox, fp_axis)), 6)
            for fp_axis in footprint_axes
        ]

        checks = {
            "plateSocketFootprintOverlap": bool(footprint["overlaps"]),
            "socketDepthMatchesPlateThickness": depth_delta_mm is not None and depth_delta_mm <= tolerance_mm,
            "expectedPlateThicknessMatches": True if expected_delta_mm is None else expected_delta_mm <= tolerance_mm,
            "flushMode": str(flush_mode or "flush").lower(),
            "centerOffsetMm": center_delta_mm,
            "depthDeltaMm": depth_delta_mm,
            "expectedThicknessDeltaMm": expected_delta_mm,
            "toleranceMm": round(tolerance_mm, 6),
            "thicknessAxis": str(thickness_axis or "z").lower(),
        }
        if not checks["plateSocketFootprintOverlap"]:
            blockers.append("Plate footprint does not overlap socket footprint.")
        if checks["flushMode"] == "flush" and not checks["socketDepthMatchesPlateThickness"]:
            blockers.append("Socket depth does not match plate thickness within tolerance for flush mode.")
        elif checks["flushMode"] not in {"flush", "proud", "recessed"}:
            warnings.append("flush_mode should be one of flush, proud, or recessed; depth equality was still reported.")
        if not checks["expectedPlateThicknessMatches"]:
            blockers.append("Plate thickness does not match expected_plate_thickness within tolerance.")

        logo_reports = []
        separated_logos = []
        non_overlapping_logos = []
        for logo, logo_component in logo_matches:
            logo_bbox = _bbox_to_dict(logo)
            if not logo_bbox:
                logo_reports.append({
                    "bodyName": _safe_value(lambda logo=logo: logo.name),
                    "componentName": logo_component,
                    "hasBoundingBox": False,
                })
                warnings.append(f"Logo body '{_safe_value(lambda logo=logo: logo.name)}' has no bounding box.")
                continue
            logo_footprint = _bbox_footprint_overlap_report(logo_bbox, plate_bbox, footprint_axes)
            separation_mm = round((logo_bbox["min"][axis] - plate_bbox["max"][axis]) * 10.0, 6)
            below_plate_mm = round((plate_bbox["min"][axis] - logo_bbox["max"][axis]) * 10.0, 6)
            separated = separation_mm > tolerance_mm
            below_plate = below_plate_mm > tolerance_mm
            if separated:
                separated_logos.append(_safe_value(lambda logo=logo: logo.name))
            if below_plate or not logo_footprint["overlaps"]:
                non_overlapping_logos.append(_safe_value(lambda logo=logo: logo.name))
            logo_reports.append({
                "bodyName": _safe_value(lambda logo=logo: logo.name),
                "componentName": logo_component,
                "entityToken": _safe_value(lambda logo=logo: logo.entityToken),
                "boundingBox": logo_bbox,
                "sizeMm": _bbox_size_mm(logo_bbox),
                "footprintOverlapWithPlate": logo_footprint,
                "minAbovePlateTopMm": separation_mm,
                "maxBelowPlateBottomMm": below_plate_mm,
                "separatedFromPlate": bool(separated),
                "belowPlate": bool(below_plate),
            })
        if separated_logos:
            blockers.append(f"Logo bodies appear separated above the plate: {', '.join(separated_logos)}.")
        if non_overlapping_logos:
            blockers.append(f"Logo bodies do not have usable plate contact/footprint overlap: {', '.join(non_overlapping_logos)}.")
        checks["logoBodiesOnOrIntersectPlate"] = not separated_logos and not non_overlapping_logos
        checks["logoBodyCount"] = len(logo_reports)
        checks["mirroredOrSeparatedGeometrySuspect"] = bool(blockers)

        return {
            "result": {
                "readOnly": True,
                "okToExport": not blockers,
                "method": "axis_aligned_bounding_box",
                "blockingReasons": blockers,
                "warnings": warnings,
                "checks": checks,
                "plate": {
                    "bodyName": _safe_value(lambda: plate.name),
                    "componentName": plate_component,
                    "entityToken": _safe_value(lambda: plate.entityToken),
                    "boundingBox": plate_bbox,
                    "sizeMm": _bbox_size_mm(plate_bbox),
                },
                "socket": {
                    "bodyName": _safe_value(lambda: socket.name),
                    "componentName": socket_component,
                    "entityToken": _safe_value(lambda: socket.entityToken),
                    "boundingBox": socket_bbox,
                    "sizeMm": _bbox_size_mm(socket_bbox),
                    "footprintOverlapWithPlate": footprint,
                },
                "logoBodies": logo_reports,
                "nextActions": [
                    "Fix blocking alignment issues before calling plan_multibody_3mf_export or export_asset.",
                    "Use exact Fusion inspection or section analysis if bounding boxes are too coarse for the geometry.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to verify insert alignment: {str(e)}"}


@register_tool("exact_interference_check")
def exact_interference_check(body_names=None, body_entity_tokens=None, include_invisible=False, max_pairs=200):
    """
    Read-only exact BRep interference attempt using Fusion TemporaryBRepManager.

    This refuses to run when candidate exact APIs are absent and returns
    structured unsupported/error payloads instead of overstating broad-phase
    bounding-box results.
    """
    try:
        context = _exact_analysis_context()
        if not context["exactInterferenceSupported"]:
            return {
                "error": "Exact interference APIs are not available in this Fusion runtime.",
                "unsupported": True,
                "capabilities": {
                    "copyCandidate": context["copyCandidate"],
                    "booleanCandidate": context["booleanCandidate"],
                    "temporaryBRepManagerAvailable": bool(context["temporaryBRepManager"]),
                },
            }
        bodies, missing_names, missing_tokens = _resolve_named_body_set(
            names=body_names,
            entity_tokens=body_entity_tokens,
            include_all=not body_names and not body_entity_tokens,
        )
        if not include_invisible:
            bodies = [(body, component) for body, component in bodies if _safe_value(lambda body=body: body.isVisible, True)]
        if len(bodies) < 2:
            return {"error": "exact_interference_check requires at least two matching bodies."}
        try:
            max_pairs = max(1, min(int(max_pairs), 1000))
        except (TypeError, ValueError):
            max_pairs = 200
        checked_pairs = []
        interferences = []
        errors = []
        for first, second in _unique_body_pairs(bodies)[:max_pairs]:
            bbox_report = _bbox_pair_report(first[0], first[1], second[0], second[1])
            exact_interferes, exact_error = _run_exact_boolean_intersection(context, first[0], second[0])
            report = {
                **(bbox_report or {}),
                "method": "temporary_brep_boolean_intersection",
                "exactInterferes": bool(exact_interferes) if exact_error is None else None,
                "exactError": exact_error,
            }
            checked_pairs.append(report)
            if exact_error:
                errors.append(exact_error)
            elif exact_interferes:
                interferences.append(report)
        return {
            "result": {
                "readOnly": True,
                "method": "temporary_brep_boolean_intersection",
                "validatedExact": False,
                "bodyCount": len(bodies),
                "pairCount": len(checked_pairs),
                "interferenceCount": len(interferences),
                "interferences": interferences,
                "checkedPairs": checked_pairs,
                "missingBodyNames": missing_names,
                "missingEntityTokens": missing_tokens,
                "errors": errors,
                "warnings": [
                    "This uses candidate Fusion exact-analysis APIs and still needs live fixture validation for this runtime.",
                    "Use broad-phase interference_check first for fast triage; use this only when exact API capability is present.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to run exact interference check: {str(e)}"}


@register_tool("exact_clearance_check")
def exact_clearance_check(target_body_names=None, tool_body_names=None, target_body_entity_tokens=None, tool_body_entity_tokens=None, minimum_clearance="0 mm", include_invisible=False, max_pairs=200):
    """
    Read-only exact minimum-distance attempt using Fusion measure manager.
    """
    try:
        context = _exact_analysis_context()
        if not context["exactMinimumDistanceSupported"]:
            return {
                "error": "Exact minimum-distance APIs are not available in this Fusion runtime.",
                "unsupported": True,
                "capabilities": {
                    "distanceCandidate": context["distanceCandidate"],
                    "measureManagerAvailable": bool(context["measureManager"]),
                },
            }
        design = get_active_design()
        minimum_clearance_mm = _length_expression_to_mm(design, minimum_clearance, 0.0)
        targets, missing_target_names, missing_target_tokens = _resolve_named_body_set(
            names=target_body_names,
            entity_tokens=target_body_entity_tokens,
            include_all=False,
        )
        tools, missing_tool_names, missing_tool_tokens = _resolve_named_body_set(
            names=tool_body_names,
            entity_tokens=tool_body_entity_tokens,
            include_all=False,
        )
        if not include_invisible:
            targets = [(body, component) for body, component in targets if _safe_value(lambda body=body: body.isVisible, True)]
            tools = [(body, component) for body, component in tools if _safe_value(lambda body=body: body.isVisible, True)]
        if not targets:
            return {"error": "exact_clearance_check requires at least one target body name or entity token."}
        if not tools:
            return {"error": "exact_clearance_check requires at least one tool body name or entity token."}
        try:
            max_pairs = max(1, min(int(max_pairs), 1000))
        except (TypeError, ValueError):
            max_pairs = 200
        checked_pairs = []
        violations = []
        errors = []
        for first, second in _unique_body_pairs(targets, tools)[:max_pairs]:
            bbox_report = _bbox_pair_report(first[0], first[1], second[0], second[1], minimum_clearance_mm)
            distance_mm, exact_error = _run_exact_minimum_distance(context, first[0], second[0])
            clearance_ok = distance_mm is not None and distance_mm >= minimum_clearance_mm
            report = {
                **(bbox_report or {}),
                "method": "measure_manager_minimum_distance",
                "exactDistanceMm": distance_mm,
                "minimumClearanceMm": round(minimum_clearance_mm, 6),
                "clearanceOk": clearance_ok if exact_error is None else None,
                "exactError": exact_error,
            }
            checked_pairs.append(report)
            if exact_error:
                errors.append(exact_error)
            elif not clearance_ok:
                violations.append(report)
        return {
            "result": {
                "readOnly": True,
                "method": "measure_manager_minimum_distance",
                "validatedExact": False,
                "minimumClearanceMm": round(minimum_clearance_mm, 6),
                "targetCount": len(targets),
                "toolCount": len(tools),
                "pairCount": len(checked_pairs),
                "violationCount": len(violations),
                "violations": violations,
                "checkedPairs": checked_pairs,
                "missingTargetBodyNames": missing_target_names,
                "missingTargetEntityTokens": missing_target_tokens,
                "missingToolBodyNames": missing_tool_names,
                "missingToolEntityTokens": missing_tool_tokens,
                "errors": errors,
                "warnings": [
                    "This uses candidate Fusion exact minimum-distance APIs and still needs live fixture validation for this runtime.",
                    "Do not infer manufacturing tolerances; minimum_clearance must be supplied explicitly.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to run exact clearance check: {str(e)}"}


@register_tool("get_physical_properties")
def get_physical_properties(body_name=None, body_entity_token=None, include_all=False):
    """
    Read-only physical-property report for one body, an entity token, or all bodies.

    Fusion reports raw volumes in cm^3 and areas in cm^2; this tool also returns
    mm-based conversions for print/CAD review workflows.
    """
    try:
        bodies = _resolve_bodies(
            body_name=body_name,
            body_entity_token=body_entity_token,
            include_all=bool(include_all),
        )
        if not bodies:
            target = body_entity_token or body_name or "active design bodies"
            return {"error": f"No body matched {target!r}."}
        reports = [
            _physical_properties_report(body, component_name)
            for body, component_name in bodies
        ]
        return {
            "result": {
                "readOnly": True,
                "bodyCount": len(reports),
                "bodies": reports,
                "warnings": [
                    "Physical properties are read directly from Fusion and depend on assigned materials and model health.",
                    "Raw Fusion units are centimeters, square centimeters, and cubic centimeters; mm conversions are included for review.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to get physical properties: {str(e)}"}


def _curve_counts(sketch):
    curves = _safe_value(lambda: sketch.sketchCurves)
    if not curves:
        return {}
    return {
        "lines": len(_collection_items(_safe_value(lambda: curves.sketchLines))),
        "circles": len(_collection_items(_safe_value(lambda: curves.sketchCircles))),
        "arcs": len(_collection_items(_safe_value(lambda: curves.sketchArcs))),
        "ellipses": len(_collection_items(_safe_value(lambda: curves.sketchEllipses))),
        "splines": (
            len(_collection_items(_safe_value(lambda: curves.sketchFittedSplines))) +
            len(_collection_items(_safe_value(lambda: curves.sketchFixedSplines)))
        ),
        "conics": len(_collection_items(_safe_value(lambda: curves.sketchConicCurves))),
    }


def _sketch_snapshot(sketch, component_name):
    return {
        "key": f"{component_name}/{_safe_value(lambda: sketch.name)}",
        "name": _safe_value(lambda: sketch.name),
        "componentName": component_name,
        "isVisible": _safe_value(lambda: sketch.isVisible),
        "isFullyConstrained": _safe_value(lambda: sketch.isFullyConstrained),
        "dimensionCount": len(_collection_items(_safe_value(lambda: sketch.sketchDimensions))),
        "constraintCount": len(_collection_items(_safe_value(lambda: sketch.geometricConstraints))),
        "pointCount": len(_collection_items(_safe_value(lambda: sketch.sketchPoints))),
        "curveCounts": _curve_counts(sketch),
        "boundingBox": _bbox_to_dict(sketch),
    }


def _sketch_snapshots(root):
    sketches = []
    root_name = _safe_value(lambda: root.name)
    for sketch in _collection_items(_safe_value(lambda: root.sketches)):
        sketches.append(_sketch_snapshot(sketch, root_name))
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        component_name = _safe_value(lambda component=component: component.name)
        for sketch in _collection_items(_safe_value(lambda component=component: component.sketches)):
            sketches.append(_sketch_snapshot(sketch, component_name))
    return sorted(sketches, key=lambda s: s.get("key") or "")


def _timeline_snapshot(design):
    timeline = _safe_value(lambda: design.timeline)
    if not timeline:
        return {"count": 0, "markerPosition": None, "items": [], "unhealthyItems": []}
    items = []
    unhealthy = []
    for i in range(_safe_value(lambda: timeline.count, 0) or 0):
        item = timeline.item(i)
        entity = _safe_value(lambda item=item: item.entity)
        data = {
            "index": i,
            "name": _safe_value(lambda item=item: item.name),
            "objectType": _safe_value(lambda entity=entity: entity.objectType) if entity else "SystemEvent",
            "featureName": _safe_value(lambda entity=entity: entity.name) if entity else None,
            "health": _health_to_string(_safe_value(lambda item=item: item.healthState)),
            "isSuppressed": _safe_value(lambda item=item: item.isSuppressed),
            "isBeforeMarker": i < (_safe_value(lambda: timeline.markerPosition, 0) or 0),
        }
        items.append(data)
        if data["health"] not in ("Healthy", "0", "None"):
            unhealthy.append(data)
    return {
        "count": _safe_value(lambda: timeline.count, len(items)),
        "markerPosition": _safe_value(lambda: timeline.markerPosition),
        "items": items,
        "unhealthyItems": unhealthy,
    }


def _selection_snapshot(app):
    ui = _safe_value(lambda: app.userInterface)
    active_selections = _safe_value(lambda: ui.activeSelections)
    selections = []
    for i, selection in enumerate(_collection_items(active_selections)):
        info = _describe_selected_entity(_safe_value(lambda selection=selection: selection.entity))
        info["selectionIndex"] = i
        selections.append(info)
    return {"count": len(selections), "items": selections}


def _selection_set_collections(app, design, root):
    candidates = [
        _safe_value(lambda: design.selectionSets),
        _safe_value(lambda: root.selectionSets),
        _safe_value(lambda: app.userInterface.selectionSets),
    ]
    seen = set()
    for collection in candidates:
        if not collection:
            continue
        key = id(collection)
        if key in seen:
            continue
        seen.add(key)
        yield collection


def _selection_set_entities(selection_set):
    candidates = [
        _safe_value(lambda: selection_set.entities),
        _safe_value(lambda: selection_set.selectionEntities),
        _safe_value(lambda: selection_set.items),
        selection_set,
    ]
    for collection in candidates:
        items = _collection_items(collection)
        if items:
            entities = []
            for item in items:
                entities.append(_safe_value(lambda item=item: item.entity, item))
            return [entity for entity in entities if entity is not None]
    return []


def _selection_set_snapshots(names=None, include_entities=True):
    app = adsk.core.Application.get()
    design = get_active_design()
    root = design.rootComponent
    name_filter = _name_filter(names)
    sets = []
    seen_names = set()
    for collection in _selection_set_collections(app, design, root):
        for index, selection_set in enumerate(_collection_items(collection)):
            name = _safe_value(lambda selection_set=selection_set: selection_set.name) or f"Selection Set {index + 1}"
            if name_filter and name not in name_filter:
                continue
            if name in seen_names:
                continue
            seen_names.add(name)
            entities = _selection_set_entities(selection_set)
            item = {
                "name": name,
                "entityCount": len(entities),
            }
            if include_entities:
                item["entities"] = [_describe_selected_entity(entity) for entity in entities]
            sets.append(item)
    return sorted(sets, key=lambda item: item.get("name") or "")


@register_tool("inspect_selection_sets")
def inspect_selection_sets(names=None, include_entities=True):
    """
    Read named Fusion selection sets and their contents.

    This covers export and targeting workflows where active UI selection is not
    enough and agents should not fall back to raw scripts just to inspect saved
    selection sets.
    """
    try:
        sets = _selection_set_snapshots(names=names, include_entities=include_entities)
        requested = sorted(_name_filter(names) or [])
        found = {item.get("name") for item in sets}
        missing = [name for name in requested if name not in found]
        return {
            "result": {
                "count": len(sets),
                "selectionSets": sets,
                "missingSelectionSets": missing,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting selection sets: {e}\n{err}")
        return {"error": f"Failed to inspect selection sets: {str(e)}"}


def _design_state_snapshot(include_selections=True):
    app = adsk.core.Application.get()
    design = get_active_design()
    root = design.rootComponent
    components = _component_snapshots(root)
    bodies = _body_snapshots(root)
    sketches = _sketch_snapshots(root)
    timeline = _timeline_snapshot(design)
    parameters = _parameters_snapshot(design)
    snapshot = {
        "schemaVersion": 1,
        "document": _document_snapshot(app),
        "design": {
            "rootComponent": _safe_value(lambda: root.name),
            "units": _safe_value(lambda: design.unitsManager.defaultLengthUnits),
            "designType": _safe_value(lambda: design.designType),
        },
        "counts": {
            "components": len(components),
            "bodies": len(bodies),
            "sketches": len(sketches),
            "userParameters": len(parameters["user"]),
            "modelParameters": len(parameters["model"]),
            "timelineItems": timeline["count"],
            "unhealthyTimelineItems": len(timeline["unhealthyItems"]),
        },
        "components": components,
        "bodies": bodies,
        "sketches": sketches,
        "parameters": parameters,
        "timeline": timeline,
        "warnings": [],
    }
    if include_selections:
        snapshot["selection"] = _selection_snapshot(app)
    if timeline["unhealthyItems"]:
        snapshot["warnings"].append("Timeline contains warning or error health states.")
    active_doc = snapshot["document"].get("active")
    if active_doc and active_doc.get("isModified"):
        snapshot["warnings"].append("Active document has unsaved changes.")
    return snapshot


@register_tool("capture_design_state")
def capture_design_state(include_selections=True):
    import traceback
    try:
        return {"result": _design_state_snapshot(include_selections=include_selections)}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error capturing design state: {e}\n{err}")
        return {"error": f"Failed to capture design state: {str(e)}"}


def _list_by_key(items, key):
    result = {}
    for index, item in enumerate(items or []):
        item_key = str(item.get(key) or item.get("key") or item.get("name") or index)
        if item_key in result:
            item_key = f"{item_key}#{index}"
        result[item_key] = item
    return result


def _changed_items(before_items, after_items, key, fields):
    before_map = _list_by_key(before_items, key)
    after_map = _list_by_key(after_items, key)
    changed = []
    for item_key in sorted(set(before_map).intersection(after_map)):
        field_changes = {}
        before_item = before_map[item_key]
        after_item = after_map[item_key]
        for field in fields:
            if before_item.get(field) != after_item.get(field):
                field_changes[field] = {
                    "before": before_item.get(field),
                    "after": after_item.get(field),
                }
        if field_changes:
            changed.append({"key": item_key, "changes": field_changes})
    return {
        "added": sorted(set(after_map) - set(before_map)),
        "removed": sorted(set(before_map) - set(after_map)),
        "changed": changed,
    }


def _compare_parameters(before, after, parameter_type):
    before_items = (before.get("parameters") or {}).get(parameter_type, [])
    after_items = (after.get("parameters") or {}).get(parameter_type, [])
    return _changed_items(before_items, after_items, "name", ["expression", "value", "unit"])


@register_tool("compare_design_state")
def compare_design_state(before, after):
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"error": "before and after must be snapshot objects returned by capture_design_state."}

    document_changed = before.get("document", {}).get("active") != after.get("document", {}).get("active")
    counts_before = before.get("counts") or {}
    counts_after = after.get("counts") or {}
    count_changes = {}
    for key in sorted(set(counts_before).union(counts_after)):
        if counts_before.get(key) != counts_after.get(key):
            count_changes[key] = {"before": counts_before.get(key), "after": counts_after.get(key)}

    diff = {
        "documentChanged": document_changed,
        "countChanges": count_changes,
        "components": _changed_items(before.get("components"), after.get("components"), "occurrenceName", ["name", "bodyCount", "sketchCount", "occurrenceCount"]),
        "bodies": _changed_items(before.get("bodies"), after.get("bodies"), "key", ["name", "componentName", "isVisible", "isSolid", "boundingBox", "volume", "area"]),
        "sketches": _changed_items(before.get("sketches"), after.get("sketches"), "key", ["isVisible", "isFullyConstrained", "dimensionCount", "constraintCount", "pointCount", "curveCounts", "boundingBox"]),
        "userParameters": _compare_parameters(before, after, "user"),
        "modelParameters": _compare_parameters(before, after, "model"),
        "timeline": _changed_items(
            (before.get("timeline") or {}).get("items"),
            (after.get("timeline") or {}).get("items"),
            "index",
            ["name", "objectType", "featureName", "health", "isSuppressed", "isBeforeMarker"],
        ),
        "warnings": [],
    }

    before_unhealthy = counts_before.get("unhealthyTimelineItems") or 0
    after_unhealthy = counts_after.get("unhealthyTimelineItems") or 0
    if after_unhealthy > before_unhealthy:
        diff["warnings"].append("New unhealthy timeline items appeared.")
    if before.get("design", {}).get("units") != after.get("design", {}).get("units"):
        diff["warnings"].append("Default design units changed.")
    if document_changed:
        diff["warnings"].append("Active document state changed.")

    changed_categories = [
        name for name in ("components", "bodies", "sketches", "userParameters", "modelParameters", "timeline")
        if diff[name]["added"] or diff[name]["removed"] or diff[name]["changed"]
    ]
    has_changes = bool(document_changed or count_changes or changed_categories)
    risk_level = "none"
    if has_changes:
        risk_level = "low"
    if diff["warnings"]:
        risk_level = "medium"
    if after_unhealthy > before_unhealthy:
        risk_level = "high"

    return {
        "result": {
            "hasChanges": has_changes,
            "riskLevel": risk_level,
            "changedCategories": changed_categories,
            "diff": diff,
        }
    }

@register_tool("query_selection")
def query_selection():
    app = adsk.core.Application.get()
    ui = app.userInterface
    selections = []
    for i in range(ui.activeSelections.count):
        try:
            item = ui.activeSelections.item(i)
            if item and item.entity:
                entity = item.entity
                selections.append({"type": str(type(entity)), "name": getattr(entity, 'name', 'Unknown')})
        except Exception:
            continue
    return {"result": {"selected": selections}}

def _safe_value(getter, default=None):
    try:
        return getter()
    except Exception:
        return default

def _collection_items(collection):
    if not collection:
        return []
    if hasattr(collection, "count") and hasattr(collection, "item"):
        return [collection.item(i) for i in range(collection.count)]
    try:
        return list(collection)
    except TypeError:
        return []

def _collection_count(collection):
    if not collection:
        return 0
    count = getattr(collection, "count", None)
    if isinstance(count, int):
        return count
    try:
        return len(collection)
    except TypeError:
        return len(_collection_items(collection))

def _point_to_list(point):
    if not point:
        return None
    return [point.x, point.y, point.z]

def _bbox_to_dict(entity):
    bbox = _safe_value(lambda: entity.boundingBox)
    if not bbox:
        return None
    return {
        "min": _point_to_list(bbox.minPoint),
        "max": _point_to_list(bbox.maxPoint)
    }

def _edge_length(edge):
    length = _safe_value(lambda: edge.length)
    if length is not None:
        return length
    evaluator = _safe_value(lambda: edge.geometry.evaluator)
    if not evaluator:
        return None
    success, start_param, end_param = evaluator.getParameterExtents()
    if not success:
        return None
    success, length = evaluator.getLengthAtParameter(start_param, end_param)
    return length if success else None

def _describe_selected_entity(entity):
    if not entity:
        return {"objectType": "None", "className": "NoneType"}
    info = {
        "objectType": _safe_value(lambda: entity.objectType, str(type(entity))),
        "className": entity.__class__.__name__,
        "name": _safe_value(lambda: entity.name),
        "tempId": _safe_value(lambda: entity.tempId),
        "entityToken": _safe_value(lambda: entity.entityToken),
        "boundingBox": _bbox_to_dict(entity)
    }

    face = adsk.fusion.BRepFace.cast(entity)
    if face:
        info.update({
            "kind": "BRepFace",
            "area": _safe_value(lambda: face.area),
            "bodyName": _safe_value(lambda: face.body.name),
            "componentName": _safe_value(lambda: face.body.parentComponent.name)
        })
        return {k: v for k, v in info.items() if v is not None}

    edge = adsk.fusion.BRepEdge.cast(entity)
    if edge:
        info.update({
            "kind": "BRepEdge",
            "length": _edge_length(edge),
            "bodyName": _safe_value(lambda: edge.body.name),
            "componentName": _safe_value(lambda: edge.body.parentComponent.name)
        })
        return {k: v for k, v in info.items() if v is not None}

    vertex = adsk.fusion.BRepVertex.cast(entity)
    if vertex:
        info.update({
            "kind": "BRepVertex",
            "point": _point_to_list(_safe_value(lambda: vertex.geometry)),
            "bodyName": _safe_value(lambda: vertex.body.name),
            "componentName": _safe_value(lambda: vertex.body.parentComponent.name)
        })
        return {k: v for k, v in info.items() if v is not None}

    body = adsk.fusion.BRepBody.cast(entity)
    if body:
        physical_props = _safe_value(lambda: body.physicalProperties)
        info.update({
            "kind": "BRepBody",
            "bodyName": _safe_value(lambda: body.name),
            "componentName": _safe_value(lambda: body.parentComponent.name),
            "volume": _safe_value(lambda: physical_props.volume) if physical_props else None,
            "area": _safe_value(lambda: physical_props.area) if physical_props else None
        })
        return {k: v for k, v in info.items() if v is not None}

    occurrence = adsk.fusion.Occurrence.cast(entity)
    if occurrence:
        info.update({
            "kind": "Occurrence",
            "occurrenceName": _safe_value(lambda: occurrence.name),
            "componentName": _safe_value(lambda: occurrence.component.name),
            "transform": _safe_value(lambda: occurrence.transform.asArray())
        })
        return {k: v for k, v in info.items() if v is not None}

    sketch_entity = adsk.fusion.SketchEntity.cast(entity)
    if sketch_entity:
        info.update({
            "kind": "SketchEntity",
            "sketchName": _safe_value(lambda: sketch_entity.parentSketch.name)
        })

    return {k: v for k, v in info.items() if v is not None}

@register_tool("get_current_selection")
def get_current_selection():
    app = adsk.core.Application.get()
    ui = app.userInterface
    selections = []
    for i in range(ui.activeSelections.count):
        selection = ui.activeSelections.item(i)
        entity_info = _describe_selected_entity(selection.entity)
        entity_info["selectionIndex"] = i
        selections.append(entity_info)
    return {"result": {"count": len(selections), "selections": selections}}

@register_tool("measure_entity")
def measure_entity(entity_name=None):
    design = get_active_design()
    app = adsk.core.Application.get()
    ui = app.userInterface
        
    entity = None
    if entity_name:
        for occ in design.rootComponent.allOccurrences:
            if occ.component.name == entity_name or occ.name == entity_name:
                entity = occ
                break
            for body in occ.bRepBodies:
                if body.name == entity_name:
                    entity = body
                    break
    else:
        if ui.activeSelections.count > 0:
            entity = ui.activeSelections.item(0).entity
            
    if not entity:
        return {"error": "Entity not found or nothing selected"}
        
    try:
        if not hasattr(entity, 'boundingBox'):
            return {"error": f"Entity of type {type(entity)} does not have a bounding box."}
            
        bbox = entity.boundingBox
        result = {
            "min": [bbox.minPoint.x, bbox.minPoint.y, bbox.minPoint.z],
            "max": [bbox.maxPoint.x, bbox.maxPoint.y, bbox.maxPoint.z]
        }
        
        if hasattr(entity, 'physicalProperties'):
            props = entity.physicalProperties
            result["volume"] = props.volume
            result["area"] = props.area
        elif hasattr(entity, 'volume'):
            result["volume"] = entity.volume
            result["area"] = getattr(entity, 'area', None)
            
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}

@register_tool("get_assembly_tree")
def get_assembly_tree(max_depth=1):
    try:
        max_depth = int(max_depth)
    except (TypeError, ValueError):
        max_depth = 1
    max_depth = max(0, min(max_depth, 50))
    design = get_active_design()
        
    def traverse(comp, current_depth):
        node = {"name": comp.name, "occurrences": []}
        if current_depth > max_depth:
            return node
            
        for occ in comp.occurrences:
            transform = occ.transform
            data = transform.asArray()
            node["occurrences"].append({
                "name": occ.name,
                "transform": data,
                "sub": traverse(occ.component, current_depth + 1) if occ.childOccurrences.count > 0 else None
            })
        return node
        
    return {"result": traverse(design.rootComponent, 1)}

def _entity_ref(entity):
    return {
        "name": _safe_value(lambda: entity.name),
        "entityToken": _safe_value(lambda: entity.entityToken),
        "objectType": _safe_value(lambda: entity.objectType),
    }


def _plane_to_dict(plane, index):
    geometry = _safe_value(lambda: plane.geometry)
    data = _entity_ref(plane)
    data.update({
        "index": index,
        "origin": _point_to_list(_safe_value(lambda: geometry.origin)),
        "normal": _vector_to_list(_safe_value(lambda: geometry.normal)),
        "uDirection": _vector_to_list(_safe_value(lambda: geometry.uDirection)),
        "vDirection": _vector_to_list(_safe_value(lambda: geometry.vDirection)),
        "isLightBulbOn": _safe_value(lambda: plane.isLightBulbOn),
        "isVisible": _safe_value(lambda: plane.isVisible),
    })
    return data


def _component_reference_report(component):
    return {
        "componentName": _safe_value(lambda: component.name),
        "origin": {
            "xAxis": _entity_ref(_safe_value(lambda: component.xConstructionAxis)),
            "yAxis": _entity_ref(_safe_value(lambda: component.yConstructionAxis)),
            "zAxis": _entity_ref(_safe_value(lambda: component.zConstructionAxis)),
            "xyPlane": _entity_ref(_safe_value(lambda: component.xYConstructionPlane)),
            "xzPlane": _entity_ref(_safe_value(lambda: component.xZConstructionPlane)),
            "yzPlane": _entity_ref(_safe_value(lambda: component.yZConstructionPlane)),
            "originPoint": _entity_ref(_safe_value(lambda: component.originConstructionPoint)),
        },
        "constructionAxes": [_entity_ref(axis) for axis in _collection_items(_safe_value(lambda: component.constructionAxes))],
        "constructionPlanes": [_plane_to_dict(plane, index) for index, plane in enumerate(_collection_items(_safe_value(lambda: component.constructionPlanes)))],
        "constructionPoints": [_entity_ref(point) for point in _collection_items(_safe_value(lambda: component.constructionPoints))],
    }


def _joint_limit_report(limits):
    if not limits:
        return None
    fields = {
        "isMinimumValueEnabled": _safe_value(lambda: limits.isMinimumValueEnabled),
        "minimumValue": _safe_value(lambda: limits.minimumValue),
        "minimumExpression": _safe_value(lambda: limits.minimumValue.expression),
        "isMaximumValueEnabled": _safe_value(lambda: limits.isMaximumValueEnabled),
        "maximumValue": _safe_value(lambda: limits.maximumValue),
        "maximumExpression": _safe_value(lambda: limits.maximumValue.expression),
        "isRestValueEnabled": _safe_value(lambda: limits.isRestValueEnabled),
        "restValue": _safe_value(lambda: limits.restValue),
        "restExpression": _safe_value(lambda: limits.restValue.expression),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _joint_motion_report(joint):
    motion = _safe_value(lambda: joint.jointMotion)
    return {
        "objectType": _safe_value(lambda: motion.objectType),
        "jointType": _safe_value(lambda: motion.jointType),
        "rotationAxis": _safe_value(lambda: motion.rotationAxis),
        "slideDirection": _safe_value(lambda: motion.slideDirection),
        "normalDirection": _safe_value(lambda: motion.normalDirection),
        "pitch": _safe_value(lambda: motion.pitch),
        "rotationLimits": _joint_limit_report(_safe_value(lambda: motion.rotationLimits)),
        "slideLimits": _joint_limit_report(_safe_value(lambda: motion.slideLimits)),
    } if motion else None


def _joint_report(joint, index, source):
    return {
        "index": index,
        "source": source,
        "name": _safe_value(lambda: joint.name),
        "objectType": _safe_value(lambda: joint.objectType),
        "entityToken": _safe_value(lambda: joint.entityToken),
        "isLightBulbOn": _safe_value(lambda: joint.isLightBulbOn),
        "isSuppressed": _safe_value(lambda: joint.isSuppressed),
        "healthState": _safe_value(lambda: joint.healthState),
        "jointMotion": _joint_motion_report(joint),
        "occurrenceOne": _entity_ref(_safe_value(lambda: joint.occurrenceOne)),
        "occurrenceTwo": _entity_ref(_safe_value(lambda: joint.occurrenceTwo)),
        "geometryOrOriginOne": _entity_ref(_safe_value(lambda: joint.geometryOrOriginOne)),
        "geometryOrOriginTwo": _entity_ref(_safe_value(lambda: joint.geometryOrOriginTwo)),
    }


@register_tool("get_assembly_references")
def get_assembly_references(include_all_components=True):
    """
    Return origin and construction references for repeatable assembly placement.

    This is intentionally read-only. Use it before creating construction
    references, mirrors, patterns, or future joint-related operations.
    """
    try:
        design = get_active_design()
        root = design.rootComponent
        components = [root]
        if include_all_components:
            for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
                component = _safe_value(lambda occ=occ: occ.component)
                if component and component not in components:
                    components.append(component)
        return {
            "result": {
                "readOnly": True,
                "componentCount": len(components),
                "components": [_component_reference_report(component) for component in components],
                "occurrences": [
                    {
                        "name": _safe_value(lambda occ=occ: occ.name),
                        "componentName": _safe_value(lambda occ=occ: occ.component.name),
                        "transform": _safe_value(lambda occ=occ: occ.transform.asArray()),
                    }
                    for occ in _collection_items(_safe_value(lambda: root.allOccurrences))
                ],
                "warnings": [
                    "This tool reports assembly and origin references only; it does not create joints or move components.",
                    "Use component-targeted construction references before creating or aligning repeated assembly features.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect assembly references: {str(e)}"}


@register_tool("get_assembly_joints")
def get_assembly_joints(include_as_built=True):
    """
    Read-only report of assembly joints and as-built joints exposed by Fusion.

    Use this before creating or editing assembly relationships so agents can
    avoid duplicating existing constraints or changing the wrong components.
    """
    try:
        design = get_active_design()
        root = design.rootComponent
        joints = [
            _joint_report(joint, index, "joints")
            for index, joint in enumerate(_collection_items(_safe_value(lambda: root.joints)))
        ]
        as_built = []
        if include_as_built:
            as_built = [
                _joint_report(joint, index, "asBuiltJoints")
                for index, joint in enumerate(_collection_items(_safe_value(lambda: root.asBuiltJoints)))
            ]
        return {
            "result": {
                "readOnly": True,
                "jointCount": len(joints),
                "asBuiltJointCount": len(as_built),
                "joints": joints,
                "asBuiltJoints": as_built,
                "warnings": [
                    "This tool reports existing assembly relationships only; create_rigid_joint is the narrow mutating companion for point-to-point rigid joints.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to inspect assembly joints: {str(e)}"}


_JOINT_LIMIT_TYPES = {"rotation", "slide"}
_JOINT_TYPES_WITH_ROTATION_LIMITS = {"revolute", "cylindrical", "pin_slot", "pin-slot", "planar", "ball"}
_JOINT_TYPES_WITH_SLIDE_LIMITS = {"slider", "cylindrical", "pin_slot", "pin-slot", "planar"}


@register_tool("plan_joint_limits")
def plan_joint_limits(joint_name=None, joint_entity_token=None, limit_type=None, minimum=None, maximum=None, rest=None, enable_minimum=True, enable_maximum=True, enable_rest=False, reason=None):
    """
    Read-only assembly joint limit plan validator.

    This validates target joint identity, motion type, limit expressions, and
    reason before any future mutating limit setter can run.
    """
    try:
        limit_kind = str(limit_type or "").strip().lower()
        blockers = []
        warnings = []
        if not joint_name and not joint_entity_token:
            blockers.append("joint_name or joint_entity_token is required.")
        if limit_kind not in _JOINT_LIMIT_TYPES:
            blockers.append(f"limit_type must be one of {sorted(_JOINT_LIMIT_TYPES)}.")
        if not isinstance(reason, str) or not reason.strip():
            blockers.append("reason is required for joint limit changes.")
        if enable_minimum and (not isinstance(minimum, str) or not minimum.strip()):
            blockers.append("minimum expression is required when enable_minimum=true.")
        if enable_maximum and (not isinstance(maximum, str) or not maximum.strip()):
            blockers.append("maximum expression is required when enable_maximum=true.")
        if enable_rest and (not isinstance(rest, str) or not rest.strip()):
            blockers.append("rest expression is required when enable_rest=true.")
        if not enable_minimum and not enable_maximum and not enable_rest:
            blockers.append("At least one of enable_minimum, enable_maximum, or enable_rest must be true.")

        inspection = get_assembly_joints(include_as_built=True)
        inspection_result = inspection.get("result") if isinstance(inspection, dict) else None
        target = None
        if inspection_result:
            warnings.extend(inspection_result.get("warnings") or [])
            candidates = list(inspection_result.get("joints") or []) + list(inspection_result.get("asBuiltJoints") or [])
            for joint in candidates:
                if joint_name and joint.get("name") != joint_name:
                    continue
                if joint_entity_token and joint.get("entityToken") != joint_entity_token:
                    continue
                target = joint
                break
            if not target and (joint_name or joint_entity_token):
                blockers.append("No matching joint was found.")
        else:
            blockers.append("Assembly joint inspection failed before planning limits.")

        motion = (target or {}).get("jointMotion") or {}
        joint_type = str(motion.get("jointType") or "").strip().lower()
        if target and limit_kind == "rotation" and joint_type and joint_type not in _JOINT_TYPES_WITH_ROTATION_LIMITS:
            blockers.append(f"Joint type '{joint_type}' does not expose rotation limits through this planning contract.")
        if target and limit_kind == "slide" and joint_type and joint_type not in _JOINT_TYPES_WITH_SLIDE_LIMITS:
            blockers.append(f"Joint type '{joint_type}' does not expose slide limits through this planning contract.")
        existing_limits = motion.get(f"{limit_kind}Limits") if limit_kind in _JOINT_LIMIT_TYPES else None
        if target and limit_kind in _JOINT_LIMIT_TYPES and existing_limits is None:
            warnings.append(f"Fusion did not expose existing {limit_kind}Limits metadata for this joint; mutating tools must verify API support before applying limits.")

        ok_to_proceed = not blockers
        return {
            "result": {
                "readOnly": True,
                "okToProceed": ok_to_proceed,
                "riskLevel": "medium" if ok_to_proceed else "high",
                "blockingReasons": blockers,
                "joint": target,
                "limitType": limit_kind,
                "requestedLimits": {
                    "enableMinimum": bool(enable_minimum),
                    "minimum": minimum,
                    "enableMaximum": bool(enable_maximum),
                    "maximum": maximum,
                    "enableRest": bool(enable_rest),
                    "rest": rest,
                },
                "existingLimits": existing_limits,
                "reason": reason,
                "inspection": inspection_result,
                "warnings": warnings + [
                    "This is a read-only joint limit plan; it does not edit assembly joints or motion limits.",
                    "Future joint limit tools must verify Fusion API support for the exact joint motion type before mutation.",
                ],
            }
        }
    except Exception as e:
        return {"error": f"Failed to plan joint limits: {str(e)}"}

# Resource Readers
@register_resource("fusion://design/parameters")
def read_parameters():
    design = get_active_design()
    params_dict = {}
    for param in design.userParameters:
        params_dict[param.name] = {
            "expression": param.expression,
            "value": param.value,
            "unit": param.unit
        }
    return {"userParameters": params_dict}

@register_resource("fusion://design/tree")
def read_tree():
    return get_assembly_tree(max_depth=999).get("result", {})

@register_resource("fusion://design/tree/*")
def read_tree_depth(depth_str):
    try:
        depth = int(depth_str)
    except Exception:
        depth = 1
    return get_assembly_tree(max_depth=depth).get("result", {})

@register_resource("fusion://design/summary")
def read_summary():
    return inspect_design().get("result", {})

@register_tool("clone_timeline_feature")
def clone_timeline_feature(name=None, index=None):
    import traceback
    try:
        design = get_active_design()
        timeline = design.timeline
        target_item = None
        
        if index is not None:
            try:
                idx = int(index)
                if 0 <= idx < timeline.count:
                    target_item = timeline.item(idx)
            except ValueError:
                pass
                
        if not target_item and name:
            for i in range(timeline.count):
                item = timeline.item(i)
                if item.name == name:
                    target_item = item
                    break
                    
        if not target_item:
            return {"error": f"Timeline item not found (name='{name}', index={index})"}
            
        entity = target_item.entity
        if not entity:
            return {
                "result": {
                    "name": target_item.name,
                    "index": target_item.index,
                    "type": "SystemEvent/NonFeature",
                    "health": str(target_item.healthState)
                }
            }
            
        obj_type = entity.objectType
        properties = {
            "name": target_item.name,
            "index": target_item.index,
            "objectType": obj_type,
            "health": str(target_item.healthState),
            "isSuppressed": target_item.isSuppressed
        }
        
        # Extrude Feature
        try:
            extrude = adsk.fusion.ExtrudeFeature.cast(entity)
            if extrude:
                properties.update({
                    "featureType": "ExtrudeFeature",
                    "operation": str(extrude.operation),
                    "extentOne": extrude.extentOne.distance.expression if hasattr(extrude.extentOne, 'distance') else None,
                    "isSymmetric": extrude.isSymmetric,
                    "profileCount": extrude.profiles.count if extrude.profiles else 0
                })
        except Exception:
            pass
            
        # Fillet Feature
        try:
            fillet = adsk.fusion.FilletFeature.cast(entity)
            if fillet:
                radius_exprs = []
                for i in range(fillet.edgeSetInputCount):
                    try:
                        edge_set = fillet.edgeSet(i)
                        radius_exprs.append(edge_set.radius.expression)
                    except Exception:
                        pass
                properties.update({
                    "featureType": "FilletFeature",
                    "radii": radius_exprs
                })
        except Exception:
            pass
            
        # Chamfer Feature
        try:
            chamfer = adsk.fusion.ChamferFeature.cast(entity)
            if chamfer:
                properties.update({
                    "featureType": "ChamferFeature",
                    "width": chamfer.width.expression if hasattr(chamfer, 'width') else None
                })
        except Exception:
            pass
            
        # Emboss Feature
        try:
            emboss = adsk.fusion.EmbossFeature.cast(entity)
            if emboss:
                properties.update({
                    "featureType": "EmbossFeature",
                    "depth": emboss.depth.expression if hasattr(emboss, 'depth') else None,
                    "operation": str(emboss.operation),
                    "isTangentAlign": emboss.isTangentAlign
                })
        except Exception:
            pass
            
        return {"result": properties}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error cloning timeline feature: {e}\n{err}")
        return {"error": f"Failed to clone timeline feature: {str(e)}"}

@register_tool("get_timeline")
def get_timeline():
    try:
        design = get_active_design()
        timeline = design.timeline
        marker_pos = timeline.markerPosition
        
        items = []
        for i in range(timeline.count):
            item = timeline.item(i)
            entity = item.entity
            entity_type = entity.objectType if entity else "SystemEvent"
            
            health_mapping = {
                adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState: "Healthy",
                adsk.fusion.FeatureHealthStates.WarningFeatureHealthState: "Warning",
                adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState: "Error"
            }
            health_str = health_mapping.get(item.healthState, "Unknown")
            
            items.append({
                "index": i,
                "name": item.name,
                "objectType": entity_type,
                "health": health_str,
                "isSuppressed": item.isSuppressed,
                "isBeforeMarker": i < marker_pos
            })
            
        return {
            "result": {
                "count": timeline.count,
                "markerPosition": marker_pos,
                "items": items
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error getting timeline: {e}\n{err}")
        return {"error": f"Failed to retrieve timeline: {str(e)}"}

@register_tool("set_timeline_marker")
def set_timeline_marker(index=None, name=None):
    try:
        design = get_active_design()
        timeline = design.timeline
        
        target_pos = None
        if index is not None:
            try:
                idx = int(index)
                if 0 <= idx <= timeline.count:
                    target_pos = idx
            except ValueError:
                pass
                
        if target_pos is None and name:
            for i in range(timeline.count):
                item = timeline.item(i)
                if item.name == name:
                    target_pos = i + 1
                    break
                    
        if target_pos is None:
            return {"error": f"Invalid timeline marker target (index={index}, name='{name}')"}
            
        timeline.markerPosition = target_pos
        return {"result": f"Moved timeline marker to position {target_pos} of {timeline.count}."}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error setting timeline marker: {e}\n{err}")
        return {"error": f"Failed to set timeline marker: {str(e)}"}


def _find_sketch_by_name(name):
    design = get_active_design()
    for sketch in design.rootComponent.sketches:
        if sketch.name == name:
            return sketch
    for occ in design.rootComponent.allOccurrences:
        for sketch in occ.component.sketches:
            if sketch.name == name:
                return sketch
    return None


def _find_component_context_by_name(name):
    design = get_active_design()
    root = design.rootComponent
    if not name or name in ("root", root.name):
        return root, None
    for occ in root.allOccurrences:
        if occ.name == name or occ.component.name == name:
            return occ.component, occ
    return None, None


def _find_component_by_name(name):
    component, _occurrence = _find_component_context_by_name(name)
    return component


def _vector_to_list(vector):
    if not vector:
        return None
    return [vector.x, vector.y, vector.z]


def _matrix_to_list(matrix):
    if not matrix:
        return None
    return _safe_value(lambda: matrix.asArray())


def _transform_point(point, matrix):
    if not point or not matrix:
        return point
    transformed = point.copy()
    transformed.transformBy(matrix)
    return transformed


def _inverse_matrix(matrix):
    if not matrix:
        return None
    inverse = matrix.copy()
    if inverse.invert():
        return inverse
    return None


def _entity_ref_to_dict(entity):
    if not entity:
        return None
    body = adsk.fusion.BRepBody.cast(entity)
    face = adsk.fusion.BRepFace.cast(entity)
    edge = adsk.fusion.BRepEdge.cast(entity)
    vertex = adsk.fusion.BRepVertex.cast(entity)
    sketch_entity = adsk.fusion.SketchEntity.cast(entity)
    occurrence = adsk.fusion.Occurrence.cast(entity)
    object_type = _safe_value(lambda: entity.objectType, "")
    object_type_lower = object_type.lower() if isinstance(object_type, str) else ""
    data = {
        "objectType": object_type,
        "name": _safe_value(lambda: entity.name),
        "entityToken": _safe_value(lambda: entity.entityToken),
        "tempId": _safe_value(lambda: entity.tempId),
        "className": entity.__class__.__name__,
    }
    if body:
        data.update({
            "kind": "BRepBody",
            "bodyName": _safe_value(lambda: body.name),
            "componentName": _safe_value(lambda: body.parentComponent.name),
        })
        owner = _body_owner_feature(body)
        if owner:
            data["ownerFeature"] = owner
    elif face:
        data.update({
            "kind": "BRepFace",
            "bodyName": _safe_value(lambda: face.body.name),
            "componentName": _safe_value(lambda: face.body.parentComponent.name),
        })
        owner = _body_owner_feature(_safe_value(lambda: face.body))
        if owner:
            data["ownerFeature"] = owner
    elif edge:
        data.update({
            "kind": "BRepEdge",
            "bodyName": _safe_value(lambda: edge.body.name),
            "componentName": _safe_value(lambda: edge.body.parentComponent.name),
        })
        owner = _body_owner_feature(_safe_value(lambda: edge.body))
        if owner:
            data["ownerFeature"] = owner
    elif vertex:
        data.update({
            "kind": "BRepVertex",
            "bodyName": _safe_value(lambda: vertex.body.name),
            "componentName": _safe_value(lambda: vertex.body.parentComponent.name),
        })
        owner = _body_owner_feature(_safe_value(lambda: vertex.body))
        if owner:
            data["ownerFeature"] = owner
    elif "brepbody" in object_type_lower:
        data.update({
            "kind": "BRepBody",
            "bodyName": _safe_value(lambda: entity.name),
            "componentName": _safe_value(lambda: entity.parentComponent.name),
        })
        owner = _body_owner_feature(entity)
        if owner:
            data["ownerFeature"] = owner
    elif "brepface" in object_type_lower:
        source_body = _safe_value(lambda: entity.body)
        data.update({
            "kind": "BRepFace",
            "bodyName": _safe_value(lambda: source_body.name),
            "componentName": _safe_value(lambda: source_body.parentComponent.name),
        })
        owner = _body_owner_feature(source_body)
        if owner:
            data["ownerFeature"] = owner
    elif "brepedge" in object_type_lower:
        source_body = _safe_value(lambda: entity.body)
        data.update({
            "kind": "BRepEdge",
            "bodyName": _safe_value(lambda: source_body.name),
            "componentName": _safe_value(lambda: source_body.parentComponent.name),
        })
        owner = _body_owner_feature(source_body)
        if owner:
            data["ownerFeature"] = owner
    elif "brepvertex" in object_type_lower:
        source_body = _safe_value(lambda: entity.body)
        data.update({
            "kind": "BRepVertex",
            "bodyName": _safe_value(lambda: source_body.name),
            "componentName": _safe_value(lambda: source_body.parentComponent.name),
        })
        owner = _body_owner_feature(source_body)
        if owner:
            data["ownerFeature"] = owner
    elif sketch_entity:
        data.update({
            "kind": "SketchEntity",
            "sketchName": _safe_value(lambda: sketch_entity.parentSketch.name),
            "componentName": _safe_value(lambda: sketch_entity.parentSketch.parentComponent.name),
        })
    elif occurrence:
        data.update({
            "kind": "Occurrence",
            "occurrenceName": _safe_value(lambda: occurrence.name),
            "componentName": _safe_value(lambda: occurrence.component.name),
        })
    return {k: v for k, v in data.items() if v is not None}


def _body_owner_feature(body):
    if not body:
        return None
    body_name = _safe_value(lambda: body.name)
    design = _safe_value(get_active_design)
    timeline = _safe_value(lambda: design.timeline) if design else None
    if not timeline:
        return None
    for i in range(_safe_value(lambda: timeline.count, 0) or 0):
        item = _safe_value(lambda i=i: timeline.item(i))
        feature = _safe_value(lambda item=item: item.entity)
        for attr, relationship in (("bodies", "resultBody"), ("participantBodies", "participantBody")):
            for candidate in _collection_items(_safe_value(lambda attr=attr, feature=feature: getattr(feature, attr))):
                if candidate is body or (body_name and _safe_value(lambda candidate=candidate: candidate.name) == body_name):
                    return {
                        "timelineName": _safe_value(lambda item=item: item.name),
                        "timelineIndex": _safe_value(lambda item=item: item.index),
                        "featureName": _safe_value(lambda feature=feature: feature.name),
                        "objectType": _safe_value(lambda feature=feature: feature.objectType),
                        "relationship": relationship,
                    }
    return None


def _parameter_to_dict(param, role=None, owner=None):
    if not param:
        return None
    expression = _safe_value(lambda: param.expression)
    data = {
        "name": _safe_value(lambda: param.name),
        "role": role,
        "expression": expression,
        "value": _safe_value(lambda: param.value),
        "unit": _safe_value(lambda: param.unit),
        "comment": _safe_value(lambda: param.comment),
        "objectType": _safe_value(lambda: param.objectType),
        "entityToken": _safe_value(lambda: param.entityToken),
        "owner": owner,
    }
    user_refs = _user_parameter_references(expression)
    if user_refs:
        data["userParameterReferences"] = user_refs
    return {k: v for k, v in data.items() if v is not None}


def _user_parameter_references(expression):
    if not isinstance(expression, str) or not expression:
        return []
    design = _safe_value(get_active_design)
    user_parameters = _safe_value(lambda: design.userParameters) if design else None
    if not user_parameters:
        return []
    refs = []
    seen = set()
    for name in _EXPRESSION_IDENTIFIER_RE.findall(expression):
        if name in seen or name.lower() in _EXPRESSION_FUNCTION_NAMES:
            continue
        user_param = _safe_value(lambda name=name: user_parameters.itemByName(name))
        if not user_param:
            continue
        seen.add(name)
        refs.append({
            "name": _safe_value(lambda user_param=user_param: user_param.name),
            "expression": _safe_value(lambda user_param=user_param: user_param.expression),
            "value": _safe_value(lambda user_param=user_param: user_param.value),
            "unit": _safe_value(lambda user_param=user_param: user_param.unit),
            "comment": _safe_value(lambda user_param=user_param: user_param.comment),
        })
    return refs


def _dedupe_parameters(parameters):
    result = []
    seen = set()
    for param in parameters:
        if not param:
            continue
        key = (
            param.get("name"),
            param.get("role"),
            param.get("expression"),
            param.get("owner"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(param)
    return result


def _reference_source_to_dict(entity):
    if not entity:
        return None
    candidate_attrs = (
        "referencedEntity",
        "referenceEntity",
        "sourceEntity",
        "projectedEntity",
        "baseEntity",
        "nativeObject",
    )
    for attr in candidate_attrs:
        source = _safe_value(lambda attr=attr: getattr(entity, attr))
        source_info = _entity_ref_to_dict(source)
        if source_info:
            source_info["sourceAttribute"] = attr
            return source_info
    return None


def _dimension_to_dict(dim, index):
    param = _safe_value(lambda: dim.parameter)
    return {
        "index": index,
        "name": _safe_value(lambda: dim.name),
        "objectType": _safe_value(lambda: dim.objectType),
        "parameterName": _safe_value(lambda: param.name) if param else None,
        "expression": _safe_value(lambda: param.expression) if param else None,
        "value": _safe_value(lambda: param.value) if param else None,
        "unit": _safe_value(lambda: param.unit) if param else None,
        "parameter": _parameter_to_dict(param, role="dimension", owner=f"dimension[{index}]"),
    }


def _constraint_to_dict(constraint, index):
    entities = []
    for attr in ("entityOne", "entityTwo", "point", "line", "curve"):
        entity = _safe_value(lambda attr=attr: getattr(constraint, attr))
        if entity:
            entities.append({
                "role": attr,
                "objectType": _safe_value(lambda entity=entity: entity.objectType),
                "name": _safe_value(lambda entity=entity: entity.name),
            })
    return {
        "index": index,
        "objectType": _safe_value(lambda: constraint.objectType),
        "isDeletable": _safe_value(lambda: constraint.isDeletable),
        "isSuppressed": _safe_value(lambda: constraint.isSuppressed),
        "entities": entities,
    }


def _sketch_point_to_dict(point, index):
    geometry = _safe_value(lambda: point.geometry)
    world_geometry = _safe_value(lambda: point.worldGeometry)
    return {
        "index": index,
        "name": _safe_value(lambda: point.name),
        "objectType": _safe_value(lambda: point.objectType),
        "geometry": _point_to_list(geometry),
        "worldGeometry": _point_to_list(world_geometry),
        "isFixed": _safe_value(lambda: point.isFixed),
        "isReference": _safe_value(lambda: point.isReference),
        "entityToken": _safe_value(lambda: point.entityToken),
        "source": _reference_source_to_dict(point),
    }


def _curve_common(curve, index, curve_type):
    return {
        "index": index,
        "curveType": curve_type,
        "name": _safe_value(lambda: curve.name),
        "objectType": _safe_value(lambda: curve.objectType),
        "isFixed": _safe_value(lambda: curve.isFixed),
        "isReference": _safe_value(lambda: curve.isReference),
        "isConstruction": _safe_value(lambda: curve.isConstruction),
        "entityToken": _safe_value(lambda: curve.entityToken),
        "source": _reference_source_to_dict(curve),
        "boundingBox": _bbox_to_dict(curve),
    }


def _line_to_dict(line, index):
    data = _curve_common(line, index, "line")
    data.update({
        "startSketchPoint": _point_to_list(_safe_value(lambda: line.startSketchPoint.geometry)),
        "endSketchPoint": _point_to_list(_safe_value(lambda: line.endSketchPoint.geometry)),
        "startPoint": _point_to_list(_safe_value(lambda: line.geometry.startPoint)),
        "endPoint": _point_to_list(_safe_value(lambda: line.geometry.endPoint)),
        "worldStartPoint": _point_to_list(_safe_value(lambda: line.worldGeometry.startPoint)),
        "worldEndPoint": _point_to_list(_safe_value(lambda: line.worldGeometry.endPoint)),
        "length": _safe_value(lambda: line.length),
    })
    return data


def _circle_to_dict(circle, index):
    data = _curve_common(circle, index, "circle")
    data.update({
        "center": _point_to_list(_safe_value(lambda: circle.centerSketchPoint.geometry)),
        "worldCenter": _point_to_list(_safe_value(lambda: circle.centerSketchPoint.worldGeometry)),
        "radius": _safe_value(lambda: circle.radius),
    })
    return data


def _arc_to_dict(arc, index):
    data = _curve_common(arc, index, "arc")
    data.update({
        "center": _point_to_list(_safe_value(lambda: arc.centerSketchPoint.geometry)),
        "startPoint": _point_to_list(_safe_value(lambda: arc.startSketchPoint.geometry)),
        "endPoint": _point_to_list(_safe_value(lambda: arc.endSketchPoint.geometry)),
        "worldCenter": _point_to_list(_safe_value(lambda: arc.centerSketchPoint.worldGeometry)),
        "radius": _safe_value(lambda: arc.radius),
        "startAngle": _safe_value(lambda: arc.startAngle),
        "endAngle": _safe_value(lambda: arc.endAngle),
    })
    return data


def _generic_curve_to_dict(curve, index, curve_type):
    data = _curve_common(curve, index, curve_type)
    data.update({
        "geometryType": _safe_value(lambda: curve.geometry.objectType),
        "worldGeometryType": _safe_value(lambda: curve.worldGeometry.objectType),
    })
    return data


def _sketch_curves_to_dict(sketch):
    curves = _safe_value(lambda: sketch.sketchCurves)
    if not curves:
        return {}
    result = {}
    curve_specs = [
        ("lines", "sketchLines", _line_to_dict),
        ("circles", "sketchCircles", _circle_to_dict),
        ("arcs", "sketchArcs", _arc_to_dict),
        ("ellipses", "sketchEllipses", lambda curve, i: _generic_curve_to_dict(curve, i, "ellipse")),
        ("fittedSplines", "sketchFittedSplines", lambda curve, i: _generic_curve_to_dict(curve, i, "fittedSpline")),
        ("fixedSplines", "sketchFixedSplines", lambda curve, i: _generic_curve_to_dict(curve, i, "fixedSpline")),
        ("conics", "sketchConicCurves", lambda curve, i: _generic_curve_to_dict(curve, i, "conic")),
    ]
    for key, attr, mapper in curve_specs:
        collection = _safe_value(lambda attr=attr: getattr(curves, attr))
        result[key] = [mapper(curve, i) for i, curve in enumerate(_collection_items(collection))]
    return result


def _sketch_coordinate_system(sketch):
    reference_plane = _safe_value(lambda: sketch.referencePlane)
    plane = _safe_value(lambda: reference_plane.geometry) or _safe_value(lambda: sketch.referencePlane.geometry)
    origin = _safe_value(lambda: plane.origin)
    u_dir = _safe_value(lambda: plane.uDirection)
    v_dir = _safe_value(lambda: plane.vDirection)
    normal = _safe_value(lambda: plane.normal)
    return {
        "referencePlaneName": _safe_value(lambda: reference_plane.name),
        "referencePlaneObjectType": _safe_value(lambda: reference_plane.objectType),
        "transform": _matrix_to_list(_safe_value(lambda: sketch.transform)),
        "origin": _point_to_list(origin),
        "localXAxisInModel": _vector_to_list(u_dir),
        "localYAxisInModel": _vector_to_list(v_dir),
        "normalInModel": _vector_to_list(normal),
        "mappingNote": "Sketch geometry is local XY. Use sketchToModelSpace/modelToSketchSpace or map_coordinates before creating model-aligned geometry.",
    }


@register_tool("inspect_sketch")
def inspect_sketch(sketch_name):
    import traceback
    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}

        dimensions = [
            _dimension_to_dict(dim, i)
            for i, dim in enumerate(_collection_items(_safe_value(lambda: sketch.sketchDimensions)))
        ]
        parameters = _dedupe_parameters([
            _parameter_to_dict(
                _safe_value(lambda dim=dim: dim.parameter),
                role="dimension",
                owner=f"dimension[{i}]",
            )
            for i, dim in enumerate(_collection_items(_safe_value(lambda: sketch.sketchDimensions)))
        ])
        constraints = [
            _constraint_to_dict(constraint, i)
            for i, constraint in enumerate(_collection_items(_safe_value(lambda: sketch.geometricConstraints)))
        ]
        points = [
            _sketch_point_to_dict(point, i)
            for i, point in enumerate(_collection_items(_safe_value(lambda: sketch.sketchPoints)))
        ]
        return {
            "result": {
                "name": sketch.name,
                "objectType": _safe_value(lambda: sketch.objectType),
                "componentName": _safe_value(lambda: sketch.parentComponent.name),
                "isVisible": _safe_value(lambda: sketch.isVisible),
                "isFullyConstrained": _safe_value(lambda: sketch.isFullyConstrained),
                "boundingBox": _bbox_to_dict(sketch),
                "coordinateSystem": _sketch_coordinate_system(sketch),
                "points": points,
                "curves": _sketch_curves_to_dict(sketch),
                "dimensions": dimensions,
                "parameters": parameters,
                "constraints": constraints,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting sketch: {e}\n{err}")
        return {"error": f"Failed to inspect sketch: {str(e)}"}


@register_tool("get_sketch_parameters")
def get_sketch_parameters(sketch_name):
    inspected = inspect_sketch(sketch_name)
    if "error" in inspected:
        return inspected
    result = inspected.get("result") or {}
    dimensions = result.get("dimensions") or []
    parameters = result.get("parameters") or []
    return {
        "result": {
            "sketchName": result.get("name"),
            "componentName": result.get("componentName"),
            "parameterCount": len(parameters),
            "dimensionCount": len(dimensions),
            "parameters": parameters,
            "dimensions": dimensions,
        }
    }


@register_tool("get_projected_geometry_sources")
def get_projected_geometry_sources(sketch_name):
    inspected = inspect_sketch(sketch_name)
    if "error" in inspected:
        return inspected
    result = inspected.get("result") or {}
    projected = []
    for group_name, curves in (result.get("curves") or {}).items():
        for curve in curves or []:
            source = curve.get("source")
            if not source and not curve.get("isReference"):
                continue
            projected.append({
                "kind": "curve",
                "curveGroup": group_name,
                "curveType": curve.get("curveType"),
                "curveIndex": curve.get("index"),
                "curveName": curve.get("name"),
                "curveEntityToken": curve.get("entityToken"),
                "isReference": curve.get("isReference"),
                "isConstruction": curve.get("isConstruction"),
                "sourceAvailable": bool(source),
                "source": source,
            })
    for point in result.get("points") or []:
        source = point.get("source")
        if not source and not point.get("isReference"):
            continue
        projected.append({
            "kind": "point",
            "pointIndex": point.get("index"),
            "pointName": point.get("name"),
            "pointEntityToken": point.get("entityToken"),
            "isReference": point.get("isReference"),
            "sourceAvailable": bool(source),
            "source": source,
        })
    return {
        "result": {
            "sketchName": result.get("name"),
            "componentName": result.get("componentName"),
            "projectedCount": len(projected),
            "projected": projected,
        }
    }


def _health_to_string(value):
    mapping = {
        adsk.fusion.FeatureHealthStates.HealthyFeatureHealthState: "Healthy",
        adsk.fusion.FeatureHealthStates.WarningFeatureHealthState: "Warning",
        adsk.fusion.FeatureHealthStates.ErrorFeatureHealthState: "Error",
    }
    return mapping.get(value, str(value))


def _operation_to_string(value):
    mapping = {
        adsk.fusion.FeatureOperations.NewBodyFeatureOperation: "NewBody",
        adsk.fusion.FeatureOperations.JoinFeatureOperation: "Join",
        adsk.fusion.FeatureOperations.CutFeatureOperation: "Cut",
        adsk.fusion.FeatureOperations.IntersectFeatureOperation: "Intersect",
    }
    return mapping.get(value, str(value))


def _body_names(collection):
    return [
        _safe_value(lambda body=body: body.name)
        for body in _collection_items(collection)
        if body is not None
    ]


def _profile_info(profile, index):
    return {
        "index": index,
        "objectType": _safe_value(lambda: profile.objectType),
        "area": _safe_value(lambda: profile.areaProperties().area),
        "boundingBox": _bbox_to_dict(profile),
    }


def _extent_to_dict(extent):
    if not extent:
        return None
    data = {
        "objectType": _safe_value(lambda: extent.objectType),
        "distanceExpression": _safe_value(lambda: extent.distance.expression),
        "distanceValue": _safe_value(lambda: extent.distance.value),
        "toEntityName": _safe_value(lambda: extent.toEntity.name),
        "toEntityObjectType": _safe_value(lambda: extent.toEntity.objectType),
        "isChained": _safe_value(lambda: extent.isChained),
    }
    return {k: v for k, v in data.items() if v is not None}


def _extent_parameters(extent, role_prefix):
    if not extent:
        return []
    candidates = [
        ("distance", f"{role_prefix}.distance"),
        ("offset", f"{role_prefix}.offset"),
        ("taperAngle", f"{role_prefix}.taperAngle"),
    ]
    params = []
    for attr, role in candidates:
        params.append(_parameter_to_dict(_safe_value(lambda attr=attr: getattr(extent, attr)), role=role))
    return _dedupe_parameters(params)


def _feature_parameters(feature):
    params = []
    if not feature:
        return params

    extrude = adsk.fusion.ExtrudeFeature.cast(feature)
    if extrude:
        params.extend(_extent_parameters(_safe_value(lambda: extrude.extentOne), "extentOne"))
        params.extend(_extent_parameters(_safe_value(lambda: extrude.extentTwo), "extentTwo"))
        params.append(_parameter_to_dict(_safe_value(lambda: extrude.taperAngle), role="taperAngle"))
        params.append(_parameter_to_dict(_safe_value(lambda: extrude.startExtent.offset), role="startOffset"))
        return _dedupe_parameters(params)

    for attr, role in (
        ("depth", "depth"),
        ("distance", "distance"),
        ("angle", "angle"),
        ("radius", "radius"),
        ("width", "width"),
        ("sectionSize", "sectionSize"),
        ("sectionThickness", "sectionThickness"),
    ):
        params.append(_parameter_to_dict(_safe_value(lambda attr=attr: getattr(feature, attr)), role=role))
    return _dedupe_parameters(params)


def _find_feature_by_name(name):
    design = get_active_design()
    timeline = design.timeline
    for i in range(timeline.count):
        item = timeline.item(i)
        entity = _safe_value(lambda: item.entity)
        if item.name == name or _safe_value(lambda: entity.name) == name:
            return item, entity
    return None, None


def _feature_ref_to_dict(timeline_item, entity):
    return {
        "timelineName": _safe_value(lambda: timeline_item.name),
        "timelineIndex": _safe_value(lambda: timeline_item.index),
        "objectType": _safe_value(lambda: entity.objectType) if entity else "SystemEvent",
        "featureName": _safe_value(lambda: entity.name) if entity else None,
        "entityToken": _safe_value(lambda: entity.entityToken) if entity else None,
        "health": _health_to_string(_safe_value(lambda: timeline_item.healthState)),
    }


def _feature_profiles(feature):
    return _collection_items(_safe_value(lambda: feature.profiles))


def _profile_parent_sketch(profile):
    loops = _safe_value(lambda: profile.profileLoops)
    for loop in _collection_items(loops):
        curves = _safe_value(lambda: loop.profileCurves)
        for profile_curve in _collection_items(curves):
            sketch_entity = _safe_value(lambda: profile_curve.sketchEntity)
            parent_sketch = _safe_value(lambda: sketch_entity.parentSketch)
            if parent_sketch:
                return parent_sketch
    return None


@register_tool("inspect_feature")
def inspect_feature(feature_name):
    import traceback
    try:
        item, entity = _find_feature_by_name(feature_name)
        if not item:
            return {"error": f"Feature '{feature_name}' not found in the design timeline."}

        result = {
            "timelineName": item.name,
            "timelineIndex": _safe_value(lambda: item.index),
            "timelineHealth": _health_to_string(_safe_value(lambda: item.healthState)),
            "isSuppressed": _safe_value(lambda: item.isSuppressed),
            "objectType": _safe_value(lambda: entity.objectType) if entity else "SystemEvent",
            "featureName": _safe_value(lambda: entity.name) if entity else None,
            "featureHealth": _health_to_string(_safe_value(lambda: entity.healthState)) if entity else None,
            "errorOrWarningMessage": _safe_value(lambda: entity.errorOrWarningMessage) if entity else None,
        }

        extrude = adsk.fusion.ExtrudeFeature.cast(entity)
        if extrude:
            result.update({
                "featureType": "ExtrudeFeature",
                "operation": _operation_to_string(_safe_value(lambda: extrude.operation)),
                "extentOne": _extent_to_dict(_safe_value(lambda: extrude.extentOne)),
                "extentTwo": _extent_to_dict(_safe_value(lambda: extrude.extentTwo)),
                "isSymmetric": _safe_value(lambda: extrude.isSymmetric),
                "isSolid": _safe_value(lambda: extrude.isSolid),
                "participantBodies": _body_names(_safe_value(lambda: extrude.participantBodies)),
                "resultBodies": _body_names(_safe_value(lambda: extrude.bodies)),
                "parameters": _feature_parameters(extrude),
                "profiles": [
                    _profile_info(profile, i)
                    for i, profile in enumerate(_collection_items(_safe_value(lambda: extrude.profiles)))
                ],
            })
            return {"result": {k: v for k, v in result.items() if v is not None}}

        for class_name in ("FilletFeature", "ChamferFeature", "EmbossFeature", "CombineFeature", "PipeFeature"):
            cast_type = _safe_value(lambda class_name=class_name: getattr(adsk.fusion, class_name))
            casted = _safe_value(lambda cast_type=cast_type: cast_type.cast(entity)) if cast_type else None
            if casted:
                result.update({
                    "featureType": class_name,
                    "operation": _operation_to_string(_safe_value(lambda: casted.operation)),
                    "participantBodies": _body_names(_safe_value(lambda: casted.participantBodies)),
                    "resultBodies": _body_names(_safe_value(lambda: casted.bodies)),
                    "parameters": _feature_parameters(casted),
                })
                break

        return {"result": {k: v for k, v in result.items() if v is not None}}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error inspecting feature: {e}\n{err}")
        return {"error": f"Failed to inspect feature: {str(e)}"}


@register_tool("get_feature_parameters")
def get_feature_parameters(feature_name):
    inspected = inspect_feature(feature_name)
    if "error" in inspected:
        return inspected
    result = inspected.get("result") or {}
    parameters = result.get("parameters") or []
    return {
        "result": {
            "featureName": result.get("featureName"),
            "timelineName": result.get("timelineName"),
            "timelineIndex": result.get("timelineIndex"),
            "featureType": result.get("featureType"),
            "operation": result.get("operation"),
            "parameterCount": len(parameters),
            "parameters": parameters,
        }
    }


def _parameter_matches_name(parameter, parameter_name):
    if not parameter:
        return False
    if parameter.get("name") == parameter_name:
        return True
    expression = parameter.get("expression")
    if isinstance(expression, str) and parameter_name in _EXPRESSION_IDENTIFIER_RE.findall(expression):
        return True
    for ref in parameter.get("userParameterReferences") or []:
        if ref.get("name") == parameter_name:
            return True
    return False


def _all_sketch_contexts(design):
    root = design.rootComponent
    contexts = [
        {
            "sketch": sketch,
            "componentName": _safe_value(lambda: root.name),
            "occurrenceName": None,
        }
        for sketch in _collection_items(_safe_value(lambda: root.sketches))
    ]
    for occ in _collection_items(_safe_value(lambda: root.allOccurrences)):
        component = _safe_value(lambda occ=occ: occ.component)
        for sketch in _collection_items(_safe_value(lambda component=component: component.sketches)):
            contexts.append({
                "sketch": sketch,
                "componentName": _safe_value(lambda component=component: component.name),
                "occurrenceName": _safe_value(lambda occ=occ: occ.name),
            })
    return contexts


def _parameter_by_name(design, parameter_name):
    user_param = _safe_value(lambda: design.userParameters.itemByName(parameter_name))
    if user_param:
        return _parameter_to_dict(user_param, role="targetUserParameter")
    all_parameters = _safe_value(lambda: design.allParameters)
    direct_model_param = _safe_value(lambda: all_parameters.itemByName(parameter_name)) if all_parameters else None
    if direct_model_param:
        return _parameter_to_dict(direct_model_param, role="targetModelParameter")
    for param in _collection_items(all_parameters):
        if _safe_value(lambda param=param: param.name) == parameter_name:
            return _parameter_to_dict(param, role="targetModelParameter")
    return None


@register_tool("get_parameter_usage")
def get_parameter_usage(parameter_name):
    if not isinstance(parameter_name, str) or not parameter_name.strip():
        return {"error": "parameter_name must be a non-empty string."}
    parameter_name = parameter_name.strip()
    design = get_active_design()

    sketch_usages = []
    for context in _all_sketch_contexts(design):
        sketch = context["sketch"]
        dimensions = [
            _dimension_to_dict(dim, i)
            for i, dim in enumerate(_collection_items(_safe_value(lambda sketch=sketch: sketch.sketchDimensions)))
        ]
        parameters = _dedupe_parameters([
            _parameter_to_dict(
                _safe_value(lambda dim=dim: dim.parameter),
                role="dimension",
                owner=f"dimension[{i}]",
            )
            for i, dim in enumerate(_collection_items(_safe_value(lambda sketch=sketch: sketch.sketchDimensions)))
        ])
        matching_dimensions = [
            dim for dim in dimensions
            if _parameter_matches_name(dim.get("parameter"), parameter_name)
        ]
        matching_parameters = [
            param for param in parameters
            if _parameter_matches_name(param, parameter_name)
        ]
        if matching_parameters or matching_dimensions:
            sketch_usages.append({
                "kind": "sketch",
                "sketchName": _safe_value(lambda sketch=sketch: sketch.name),
                "componentName": context.get("componentName"),
                "occurrenceName": context.get("occurrenceName"),
                "parameters": matching_parameters,
                "dimensions": matching_dimensions,
            })

    feature_usages = []
    timeline = _safe_value(lambda: design.timeline)
    for i in range(_safe_value(lambda: timeline.count, 0) or 0):
        item = _safe_value(lambda i=i: timeline.item(i))
        entity = _safe_value(lambda item=item: item.entity)
        parameters = [
            param for param in _feature_parameters(entity)
            if _parameter_matches_name(param, parameter_name)
        ]
        if parameters:
            feature_usages.append({
                "kind": "feature",
                "timelineName": _safe_value(lambda item=item: item.name),
                "timelineIndex": _safe_value(lambda item=item: item.index),
                "featureName": _safe_value(lambda entity=entity: entity.name),
                "objectType": _safe_value(lambda entity=entity: entity.objectType),
                "parameters": parameters,
            })

    return {
        "result": {
            "parameterName": parameter_name,
            "targetParameter": _parameter_by_name(design, parameter_name),
            "usageCount": len(sketch_usages) + len(feature_usages),
            "sketchUsages": sketch_usages,
            "featureUsages": feature_usages,
        }
    }


def _point_from_input(point):
    if not isinstance(point, (list, tuple)) or len(point) != 3:
        raise ValueError("point must be an array of three numbers.")
    return adsk.core.Point3D.create(float(point[0]), float(point[1]), float(point[2]))


@register_tool("map_coordinates")
def map_coordinates(point, from_sketch, to_component="root", direction="both"):
    import traceback
    try:
        sketch = _find_sketch_by_name(from_sketch)
        if not sketch:
            return {"error": f"Sketch '{from_sketch}' not found."}
        component, occurrence = _find_component_context_by_name(to_component)
        if not component:
            return {"error": f"Component or occurrence '{to_component}' not found."}

        input_point = _point_from_input(point)
        direction = (direction or "both").lower()
        occurrence_transform = _safe_value(lambda: occurrence.transform) if occurrence else None
        inverse_transform = _inverse_matrix(occurrence_transform)
        result = {
            "inputPoint": list(point),
            "sketchName": sketch.name,
            "componentName": _safe_value(lambda: component.name),
            "occurrenceName": _safe_value(lambda: occurrence.name) if occurrence else None,
            "targetTransformToModel": _matrix_to_list(occurrence_transform),
            "coordinateSystem": _sketch_coordinate_system(sketch),
        }
        if direction in ("sketch_to_model", "both"):
            model_point = sketch.sketchToModelSpace(input_point)
            result["sketchToModel"] = _point_to_list(model_point)
            result["sketchToTargetComponent"] = _point_to_list(_transform_point(model_point, inverse_transform)) if inverse_transform else _point_to_list(model_point)
        if direction in ("model_to_sketch", "both"):
            model_input = _transform_point(input_point, occurrence_transform) if occurrence_transform else input_point
            result["targetComponentToModel"] = _point_to_list(model_input)
            result["modelToSketch"] = _point_to_list(sketch.modelToSketchSpace(model_input))
        if direction not in ("sketch_to_model", "model_to_sketch", "both"):
            return {"error": "direction must be 'sketch_to_model', 'model_to_sketch', or 'both'."}
        return {"result": result}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error mapping coordinates: {e}\n{err}")
        return {"error": f"Failed to map coordinates: {str(e)}"}


@register_tool("get_feature_dependencies")
def get_feature_dependencies(feature_name):
    import traceback
    try:
        design = get_active_design()
        timeline = design.timeline
        target_item, target_entity = _find_feature_by_name(feature_name)
        if not target_item:
            return {"error": f"Feature '{feature_name}' not found in the design timeline."}

        target_index = _safe_value(lambda: target_item.index)
        direct_inputs = []
        warnings = [
            "Fusion does not expose a complete parent-child breakage graph through this MCP tool; dependencies are inferred from visible API relationships."
        ]

        for param in _feature_parameters(target_entity):
            direct_inputs.append({
                "kind": "featureParameter",
                "parameter": param,
                "role": param.get("role"),
                "confidence": "high",
            })

        profiles = _feature_profiles(target_entity)
        for profile_index, profile in enumerate(profiles):
            parent_sketch = _profile_parent_sketch(profile)
            if parent_sketch:
                direct_inputs.append({
                    "kind": "profileSketch",
                    "profileIndex": profile_index,
                    "sketchName": _safe_value(lambda: parent_sketch.name),
                    "componentName": _safe_value(lambda: parent_sketch.parentComponent.name),
                    "confidence": "high",
                })
            else:
                direct_inputs.append({
                    "kind": "profile",
                    "profileIndex": profile_index,
                    "objectType": _safe_value(lambda profile=profile: profile.objectType),
                    "boundingBox": _bbox_to_dict(profile),
                    "confidence": "unknown",
                    "note": "Profile exists, but Fusion did not expose a parent sketch through the inspected API path.",
                })

        sketch = adsk.fusion.Sketch.cast(target_entity)
        if sketch:
            reference_plane = _safe_value(lambda: sketch.referencePlane)
            direct_inputs.append({
                "kind": "referencePlane",
                "name": _safe_value(lambda: reference_plane.name),
                "objectType": _safe_value(lambda: reference_plane.objectType),
                "source": _entity_ref_to_dict(reference_plane),
                "confidence": "high" if reference_plane else "unknown",
            })
            for curve_type, curves in _sketch_curves_to_dict(sketch).items():
                for curve in curves:
                    if curve.get("source"):
                        direct_inputs.append({
                            "kind": "projectedGeometry",
                            "curveType": curve_type,
                            "curveIndex": curve.get("index"),
                            "source": curve.get("source"),
                            "confidence": "medium",
                        })

        result_bodies = set(_body_names(_safe_value(lambda: target_entity.bodies)))
        if not result_bodies:
            result_bodies.update(_body_names(_safe_value(lambda: target_entity.participantBodies)))

        timeline_predecessors = []
        likely_downstream = []
        for i in range(timeline.count):
            item = timeline.item(i)
            entity = _safe_value(lambda item=item: item.entity)
            ref = _feature_ref_to_dict(item, entity)
            if i < target_index:
                if i >= max(0, target_index - 10):
                    timeline_predecessors.append(ref)
                continue
            if i == target_index:
                continue

            participant_names = set(_body_names(_safe_value(lambda entity=entity: entity.participantBodies)))
            body_names = set(_body_names(_safe_value(lambda entity=entity: entity.bodies)))
            profile_sketches = [
                _safe_value(lambda profile=profile: _profile_parent_sketch(profile).name)
                for profile in _feature_profiles(entity)
                if _profile_parent_sketch(profile)
            ]
            reasons = []
            confidence = "low"
            if result_bodies and participant_names.intersection(result_bodies):
                reasons.append("usesResultBodyAsParticipant")
                confidence = "medium"
            if sketch and profile_sketches and sketch.name in profile_sketches:
                reasons.append("usesTargetSketchProfile")
                confidence = "high"
            if reasons:
                ref.update({
                    "reasons": reasons,
                    "participantBodies": sorted(participant_names),
                    "resultBodies": sorted(body_names),
                    "profileSketches": profile_sketches,
                    "confidence": confidence,
                })
                likely_downstream.append(ref)

        return {
            "result": {
                "feature": _feature_ref_to_dict(target_item, target_entity),
                "bestEffort": True,
                "directInputs": direct_inputs,
                "timelinePredecessors": timeline_predecessors,
                "likelyDownstreamConsumers": likely_downstream,
                "warnings": warnings,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error getting feature dependencies: {e}\n{err}")
        return {"error": f"Failed to get feature dependencies: {str(e)}"}


def _graph_add_node(nodes, node_id, kind, label=None, **metadata):
    if not node_id:
        return
    node = nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label or node_id})
    for key, value in metadata.items():
        if value is not None:
            node[key] = value


def _graph_add_edge(edges, edge_keys, source, target, relationship, confidence="medium", **metadata):
    if not source or not target:
        return
    key = (source, target, relationship)
    if key in edge_keys:
        return
    edge_keys.add(key)
    edge = {
        "source": source,
        "target": target,
        "relationship": relationship,
        "confidence": confidence,
    }
    for meta_key, value in metadata.items():
        if value is not None:
            edge[meta_key] = value
    edges.append(edge)


def _graph_feature_node_id(feature_ref):
    index = feature_ref.get("timelineIndex")
    name = feature_ref.get("timelineName") or feature_ref.get("featureName")
    return f"feature:{index}:{name}" if index is not None else f"feature:{name}"


@register_tool("get_dependency_graph")
def get_dependency_graph():
    import traceback
    try:
        design = get_active_design()
        timeline = design.timeline
        nodes = {}
        edges = []
        edge_keys = set()
        warnings = [
            "Fusion does not expose a complete authoritative parent-child graph through this MCP tool; this graph is inferred from visible API relationships."
        ]
        feature_nodes_by_timeline_name = {}
        feature_nodes_by_feature_name = {}

        for i in range(timeline.count):
            item = timeline.item(i)
            entity = _safe_value(lambda item=item: item.entity)
            feature_ref = _feature_ref_to_dict(item, entity)
            feature_node_id = _graph_feature_node_id(feature_ref)
            _graph_add_node(
                nodes,
                feature_node_id,
                "feature",
                feature_ref.get("timelineName") or feature_ref.get("featureName"),
                timelineIndex=feature_ref.get("timelineIndex"),
                timelineName=feature_ref.get("timelineName"),
                featureName=feature_ref.get("featureName"),
                objectType=feature_ref.get("objectType"),
                health=feature_ref.get("health"),
            )
            if feature_ref.get("timelineName"):
                feature_nodes_by_timeline_name[feature_ref["timelineName"]] = feature_node_id
            if feature_ref.get("featureName"):
                feature_nodes_by_feature_name[feature_ref["featureName"]] = feature_node_id

        for i in range(timeline.count):
            item = timeline.item(i)
            entity = _safe_value(lambda item=item: item.entity)
            feature_name = _safe_value(lambda entity=entity: entity.name) or _safe_value(lambda item=item: item.name)
            deps = get_feature_dependencies(feature_name)
            if "error" in deps:
                warnings.append(deps["error"])
                continue
            report = deps.get("result") or {}
            feature_ref = report.get("feature") or {}
            feature_node_id = _graph_feature_node_id(feature_ref)
            for input_ref in report.get("directInputs") or []:
                kind = input_ref.get("kind")
                if kind == "featureParameter":
                    parameter = input_ref.get("parameter") or {}
                    param_name = parameter.get("name")
                    param_node_id = f"parameter:{param_name}" if param_name else None
                    _graph_add_node(
                        nodes,
                        param_node_id,
                        "parameter",
                        param_name,
                        expression=parameter.get("expression"),
                        role=parameter.get("role"),
                        unit=parameter.get("unit"),
                    )
                    _graph_add_edge(
                        edges,
                        edge_keys,
                        param_node_id,
                        feature_node_id,
                        "drivesFeatureParameter",
                        input_ref.get("confidence") or "high",
                        role=input_ref.get("role"),
                    )
                    for ref in parameter.get("userParameterReferences") or []:
                        user_node_id = f"userParameter:{ref.get('name')}"
                        _graph_add_node(
                            nodes,
                            user_node_id,
                            "userParameter",
                            ref.get("name"),
                            expression=ref.get("expression"),
                            unit=ref.get("unit"),
                        )
                        _graph_add_edge(
                            edges,
                            edge_keys,
                            user_node_id,
                            param_node_id,
                            "referencedByExpression",
                            "high",
                        )
                elif kind == "profileSketch":
                    sketch_name = input_ref.get("sketchName")
                    sketch_node_id = f"sketch:{sketch_name}" if sketch_name else None
                    _graph_add_node(
                        nodes,
                        sketch_node_id,
                        "sketch",
                        sketch_name,
                        componentName=input_ref.get("componentName"),
                    )
                    _graph_add_edge(
                        edges,
                        edge_keys,
                        sketch_node_id,
                        feature_node_id,
                        "providesProfile",
                        input_ref.get("confidence") or "high",
                        profileIndex=input_ref.get("profileIndex"),
                    )
                elif kind == "projectedGeometry":
                    source = input_ref.get("source") or {}
                    token = source.get("entityToken") or source.get("tempId") or source.get("name")
                    source_node_id = f"source:{token}" if token else None
                    _graph_add_node(
                        nodes,
                        source_node_id,
                        "projectedSource",
                        source.get("name") or source.get("bodyName") or token,
                        sourceKind=source.get("kind"),
                        objectType=source.get("objectType"),
                        bodyName=source.get("bodyName"),
                        componentName=source.get("componentName"),
                    )
                    _graph_add_edge(
                        edges,
                        edge_keys,
                        source_node_id,
                        feature_node_id,
                        "projectedIntoSketch",
                        input_ref.get("confidence") or "medium",
                        curveType=input_ref.get("curveType"),
                        curveIndex=input_ref.get("curveIndex"),
                    )
                    owner = source.get("ownerFeature") or {}
                    owner_node_id = (
                        feature_nodes_by_timeline_name.get(owner.get("timelineName"))
                        or feature_nodes_by_feature_name.get(owner.get("featureName"))
                    )
                    if owner_node_id:
                        _graph_add_edge(
                            edges,
                            edge_keys,
                            owner_node_id,
                            source_node_id,
                            "ownsProjectedSource",
                            "medium",
                            ownerRelationship=owner.get("relationship"),
                        )
            for consumer in report.get("likelyDownstreamConsumers") or []:
                consumer_node_id = (
                    feature_nodes_by_timeline_name.get(consumer.get("timelineName"))
                    or feature_nodes_by_feature_name.get(consumer.get("featureName"))
                    or _graph_feature_node_id(consumer)
                )
                _graph_add_edge(
                    edges,
                    edge_keys,
                    feature_node_id,
                    consumer_node_id,
                    "likelyDownstreamConsumer",
                    consumer.get("confidence") or "low",
                    reasons=consumer.get("reasons"),
                )

        return {
            "result": {
                "bestEffort": True,
                "nodeCount": len(nodes),
                "edgeCount": len(edges),
                "nodes": list(nodes.values()),
                "edges": edges,
                "warnings": warnings,
            }
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error getting dependency graph: {e}\n{err}")
        return {"error": f"Failed to get dependency graph: {str(e)}"}


def _impact_risk_level(blocking_reasons, warnings, dependency_reports):
    if blocking_reasons:
        return "high"
    if warnings:
        return "medium"
    for report in dependency_reports:
        for input_ref in report.get("directInputs") or []:
            if input_ref.get("confidence") == "unknown":
                return "medium"
    return "low"


@register_tool("assess_change_impact")
def assess_change_impact(target_features, change_type="edit"):
    if isinstance(target_features, str):
        target_features = [target_features]
    if not isinstance(target_features, list) or not target_features:
        return {"error": "target_features must be a feature name or non-empty list of feature names."}
    clean_targets = [name.strip() for name in target_features if isinstance(name, str) and name.strip()]
    if not clean_targets:
        return {"error": "target_features must include at least one non-empty feature name."}

    dependency_reports = []
    downstream_consumers = []
    blocking_reasons = []
    warnings = []
    missing_features = []

    for feature_name in clean_targets:
        deps = get_feature_dependencies(feature_name)
        if "error" in deps:
            missing_features.append(feature_name)
            dependency_reports.append({"featureName": feature_name, "error": deps["error"]})
            continue
        report = deps.get("result") or {}
        dependency_reports.append(report)
        for consumer in report.get("likelyDownstreamConsumers") or []:
            downstream_consumers.append({
                "targetFeature": feature_name,
                "consumer": consumer,
            })
        for input_ref in report.get("directInputs") or []:
            if input_ref.get("confidence") == "unknown":
                warnings.append(f"Feature '{feature_name}' has unresolved dependency input: {input_ref.get('kind')}.")

    if missing_features:
        blocking_reasons.append("One or more target features were not found.")
    if downstream_consumers:
        blocking_reasons.append("One or more target features have likely downstream consumers.")

    risk_level = _impact_risk_level(blocking_reasons, warnings, dependency_reports)
    return {
        "result": {
            "okToProceed": not blocking_reasons,
            "riskLevel": risk_level,
            "changeType": change_type or "edit",
            "targetFeatures": clean_targets,
            "blockingReasons": blocking_reasons,
            "warnings": warnings,
            "analysisNote": "Impact is best-effort; Fusion does not expose a complete authoritative parent-child graph through this MCP tool.",
            "downstreamConsumers": downstream_consumers,
            "dependencyReports": dependency_reports,
            "recommendedNextStep": (
                "Inspect downstream consumers and ask for explicit confirmation before changing target features."
                if blocking_reasons
                else "Proceed with normal preflight_model_change before modifying the model."
            ),
        }
    }


def _normalize_optional_names(value, arg_name):
    if value is None:
        return None, None
    if isinstance(value, str):
        names = [value]
    elif isinstance(value, list):
        names = value
    else:
        return None, f"{arg_name} must be a string, list of strings, or omitted."
    clean_names = [name.strip() for name in names if isinstance(name, str) and name.strip()]
    return clean_names, None


def _parameterization_bucket(parameter):
    if not parameter:
        return "unknown", "No parameter metadata was available."
    refs = parameter.get("userParameterReferences") or []
    if refs:
        return "alreadyParameterized", "Expression already references one or more user parameters."
    expression = parameter.get("expression")
    if isinstance(expression, str) and expression.strip():
        return "safeExpressionCandidate", "Expression can usually be rebound to a user parameter at the same current value."
    return "needsInspection", "Parameter has no readable expression."


def _parameterization_parameter_entry(parameter, owner_kind, owner_name, extra=None):
    bucket, reason = _parameterization_bucket(parameter)
    entry = {
        "ownerKind": owner_kind,
        "ownerName": owner_name,
        "bucket": bucket,
        "reason": reason,
        "parameter": parameter,
    }
    if extra:
        entry.update(extra)
    return entry


def _count_projected_entities(sketch):
    projected = []
    for group_name, curves in (_sketch_curves_to_dict(sketch) or {}).items():
        for curve in curves or []:
            if curve.get("isReference") or curve.get("source"):
                projected.append({
                    "kind": "curve",
                    "curveGroup": group_name,
                    "curveType": curve.get("curveType"),
                    "curveIndex": curve.get("index"),
                    "sourceAvailable": bool(curve.get("source")),
                    "source": curve.get("source"),
                })
    for i, point in enumerate(_collection_items(_safe_value(lambda: sketch.sketchPoints))):
        point_info = _sketch_point_to_dict(point, i)
        if point_info.get("isReference") or point_info.get("source"):
            projected.append({
                "kind": "point",
                "pointIndex": point_info.get("index"),
                "sourceAvailable": bool(point_info.get("source")),
                "source": point_info.get("source"),
            })
    return projected


@register_tool("plan_parameterization")
def plan_parameterization(target_sketches=None, target_features=None):
    sketch_filter, error = _normalize_optional_names(target_sketches, "target_sketches")
    if error:
        return {"error": error}
    feature_filter, error = _normalize_optional_names(target_features, "target_features")
    if error:
        return {"error": error}

    design = get_active_design()
    snapshot = _design_state_snapshot(include_selections=False)
    user_parameters = snapshot.get("parameters", {}).get("user", [])
    timeline_items = snapshot.get("timeline", {}).get("items", [])
    unhealthy_items = snapshot.get("timeline", {}).get("unhealthyItems", [])

    sketch_reports = []
    missing_sketches = set(sketch_filter or [])
    parameter_entries = []
    already_parameterized = []
    safe_candidates = []
    needs_inspection = []
    rebuild_candidates = []
    warnings = [
        "Read-only planning report. Do not delete, suppress, rebuild, or edit geometry from this report without explicit user confirmation.",
        "Expression rebinding can preserve current geometry only when the new expression evaluates to the same current value.",
    ]

    for context in _all_sketch_contexts(design):
        sketch = context["sketch"]
        sketch_name = _safe_value(lambda sketch=sketch: sketch.name)
        if sketch_filter and sketch_name not in sketch_filter:
            continue
        missing_sketches.discard(sketch_name)

        dimensions = [
            _dimension_to_dict(dim, i)
            for i, dim in enumerate(_collection_items(_safe_value(lambda sketch=sketch: sketch.sketchDimensions)))
        ]
        projected = _count_projected_entities(sketch)
        sketch_report = {
            "sketchName": sketch_name,
            "componentName": context.get("componentName"),
            "occurrenceName": context.get("occurrenceName"),
            "isFullyConstrained": _safe_value(lambda sketch=sketch: sketch.isFullyConstrained),
            "dimensionCount": len(dimensions),
            "constraintCount": len(_collection_items(_safe_value(lambda sketch=sketch: sketch.geometricConstraints))),
            "projectedGeometryCount": len(projected),
            "projectedGeometry": projected,
            "dimensions": [],
            "recommendations": [],
        }
        if sketch_report["isFullyConstrained"] is False:
            sketch_report["recommendations"].append("Sketch is not fully constrained; parameterize dimensions before changing constraints or curves.")
            needs_inspection.append({
                "kind": "sketch",
                "name": sketch_name,
                "reason": "Sketch is not fully constrained.",
            })
        if projected:
            sketch_report["recommendations"].append("Projected geometry exists; preserve projection relationships instead of hardcoding source coordinates.")

        for dim in dimensions:
            parameter = dim.get("parameter")
            entry = _parameterization_parameter_entry(
                parameter,
                "sketchDimension",
                sketch_name,
                {
                    "dimensionIndex": dim.get("index"),
                    "dimensionType": dim.get("objectType"),
                    "parameterName": dim.get("parameterName"),
                    "currentExpression": dim.get("expression"),
                    "currentValue": dim.get("value"),
                    "unit": dim.get("unit"),
                },
            )
            sketch_report["dimensions"].append(entry)
            parameter_entries.append(entry)
            if entry["bucket"] == "alreadyParameterized":
                already_parameterized.append(entry)
            elif entry["bucket"] == "safeExpressionCandidate":
                safe_candidates.append(entry)
            else:
                needs_inspection.append(entry)
        sketch_reports.append(sketch_report)

    feature_reports = []
    missing_features = set(feature_filter or [])
    for item in timeline_items:
        feature_name = item.get("featureName") or item.get("name")
        timeline_name = item.get("name")
        if feature_filter and feature_name not in feature_filter and timeline_name not in feature_filter:
            continue
        missing_features.discard(feature_name)
        missing_features.discard(timeline_name)

        feature_params = get_feature_parameters(feature_name or timeline_name)
        feature_inspection = inspect_feature(feature_name or timeline_name)
        dependency_report = get_feature_dependencies(feature_name or timeline_name)
        params = (feature_params.get("result") or {}).get("parameters") if "error" not in feature_params else []
        inspected = feature_inspection.get("result") or {}
        dependencies = dependency_report.get("result") or {}
        downstream = dependencies.get("likelyDownstreamConsumers") or []

        report = {
            "timelineName": timeline_name,
            "featureName": feature_name,
            "timelineIndex": item.get("index"),
            "objectType": item.get("objectType"),
            "health": item.get("health"),
            "featureType": inspected.get("featureType"),
            "operation": inspected.get("operation"),
            "parameterCount": len(params or []),
            "downstreamConsumerCount": len(downstream),
            "parameters": [],
            "recommendations": [],
        }
        if item.get("health") not in ("Healthy", "0", "None"):
            report["recommendations"].append("Feature is unhealthy; fix or inspect health before parameterizing it.")
            needs_inspection.append({
                "kind": "feature",
                "name": feature_name or timeline_name,
                "reason": "Feature is not healthy.",
            })
        if downstream:
            report["recommendations"].append("Feature has likely downstream consumers; ask for confirmation before editing feature definitions.")
        if "error" in feature_params:
            report["parameterError"] = feature_params["error"]
            needs_inspection.append({
                "kind": "feature",
                "name": feature_name or timeline_name,
                "reason": feature_params["error"],
            })
        for parameter in params or []:
            entry = _parameterization_parameter_entry(
                parameter,
                "featureParameter",
                feature_name or timeline_name,
                {
                    "timelineName": timeline_name,
                    "timelineIndex": item.get("index"),
                    "featureType": inspected.get("featureType"),
                    "operation": inspected.get("operation"),
                    "downstreamConsumerCount": len(downstream),
                },
            )
            report["parameters"].append(entry)
            parameter_entries.append(entry)
            if entry["bucket"] == "alreadyParameterized":
                already_parameterized.append(entry)
            elif entry["bucket"] == "safeExpressionCandidate":
                safe_candidates.append(entry)
            else:
                needs_inspection.append(entry)
        if not params and inspected.get("featureType") is None and item.get("objectType") != "SystemEvent":
            rebuild_candidates.append({
                "kind": "feature",
                "name": feature_name or timeline_name,
                "reason": "No parameter metadata was exposed for this feature type; a clean parametric rebuild may be required, but only with explicit approval.",
                "objectType": item.get("objectType"),
            })
        feature_reports.append(report)

    blocking_reasons = []
    if missing_sketches:
        blocking_reasons.append("One or more requested sketches were not found.")
    if missing_features:
        blocking_reasons.append("One or more requested features were not found.")
    if unhealthy_items:
        blocking_reasons.append("Timeline contains unhealthy items.")
    risk_level = "high" if blocking_reasons else ("medium" if needs_inspection or rebuild_candidates else "low")

    return {
        "result": {
            "bestEffort": True,
            "readOnly": True,
            "okToProceedWithParameterOnlyEdits": not blocking_reasons,
            "riskLevel": risk_level,
            "blockingReasons": blocking_reasons,
            "warnings": warnings,
            "targets": {
                "sketches": sketch_filter,
                "features": feature_filter,
                "missingSketches": sorted(missing_sketches),
                "missingFeatures": sorted(missing_features),
            },
            "summary": {
                "userParameterCount": len(user_parameters),
                "sketchesAnalyzed": len(sketch_reports),
                "featuresAnalyzed": len(feature_reports),
                "parameterEntries": len(parameter_entries),
                "alreadyParameterized": len(already_parameterized),
                "safeExpressionCandidates": len(safe_candidates),
                "needsInspection": len(needs_inspection),
                "rebuildCandidates": len(rebuild_candidates),
                "unhealthyTimelineItems": len(unhealthy_items),
            },
            "recommendedWorkflow": [
                "Capture design state before edits.",
                "Create or reuse user parameters whose current expressions evaluate to the same current values.",
                "Rebind safeExpressionCandidate expressions one at a time.",
                "Run compare_design_state and validate_model after edits.",
                "Stop for user approval before rebuilding features, changing constraints, or replacing projected geometry.",
            ],
            "sketches": sketch_reports,
            "features": feature_reports,
            "alreadyParameterized": already_parameterized,
            "safeExpressionCandidates": safe_candidates,
            "needsInspection": needs_inspection,
            "rebuildCandidates": rebuild_candidates,
            "unhealthyTimelineItems": unhealthy_items,
        }
    }


@register_tool("get_sketch_dimensions")
def get_sketch_dimensions(sketch_name):
    import traceback
    try:
        sketch = _find_sketch_by_name(sketch_name)
        if not sketch:
            return {"error": f"Sketch '{sketch_name}' not found."}
        
        dimensions = []
        for i in range(sketch.sketchDimensions.count):
            dim = sketch.sketchDimensions.item(i)
            param = dim.parameter
            dimensions.append({
                "index": i,
                "parameterName": param.name if param else None,
                "expression": param.expression if param else None,
                "value": param.value if param else None,
                "type": dim.objectType
            })
        return {"result": {"sketch": sketch_name, "dimensions": dimensions}}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error getting sketch dimensions: {e}\n{err}")
        return {"error": f"Failed to retrieve sketch dimensions: {str(e)}"}
