"""
Inspection and selection tools/resources package.
"""

import adsk.core, adsk.fusion
import json
from . import register_tool, register_resource

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
    data = {
        "objectType": _safe_value(lambda: entity.objectType),
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
    elif face:
        data.update({
            "kind": "BRepFace",
            "bodyName": _safe_value(lambda: face.body.name),
            "componentName": _safe_value(lambda: face.body.parentComponent.name),
        })
    elif edge:
        data.update({
            "kind": "BRepEdge",
            "bodyName": _safe_value(lambda: edge.body.name),
            "componentName": _safe_value(lambda: edge.body.parentComponent.name),
        })
    elif vertex:
        data.update({
            "kind": "BRepVertex",
            "bodyName": _safe_value(lambda: vertex.body.name),
            "componentName": _safe_value(lambda: vertex.body.parentComponent.name),
        })
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


def _parameter_to_dict(param, role=None, owner=None):
    if not param:
        return None
    data = {
        "name": _safe_value(lambda: param.name),
        "role": role,
        "expression": _safe_value(lambda: param.expression),
        "value": _safe_value(lambda: param.value),
        "unit": _safe_value(lambda: param.unit),
        "comment": _safe_value(lambda: param.comment),
        "objectType": _safe_value(lambda: param.objectType),
        "entityToken": _safe_value(lambda: param.entityToken),
        "owner": owner,
    }
    return {k: v for k, v in data.items() if v is not None}


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
