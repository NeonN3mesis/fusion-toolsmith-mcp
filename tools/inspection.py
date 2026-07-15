"""
Inspection and selection tools/resources package.
"""

import adsk.core, adsk.fusion
import json
import math
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


def _joint_motion_report(joint):
    motion = _safe_value(lambda: joint.jointMotion)
    return {
        "objectType": _safe_value(lambda: motion.objectType),
        "jointType": _safe_value(lambda: motion.jointType),
        "rotationAxis": _safe_value(lambda: motion.rotationAxis),
        "slideDirection": _safe_value(lambda: motion.slideDirection),
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
