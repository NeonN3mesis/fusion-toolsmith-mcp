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
