"""
Parametric modeling and parameter management tools.
Includes support for parametric box, cylinder, and coil creation.
"""

import adsk.core, adsk.fusion
import math
import os
import traceback
from . import register_tool
from .inspection import get_active_design

def _operation(value):
    mapping = {
        "new_body": adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
        "join": adsk.fusion.FeatureOperations.JoinFeatureOperation,
        "cut": adsk.fusion.FeatureOperations.CutFeatureOperation,
        "intersect": adsk.fusion.FeatureOperations.IntersectFeatureOperation,
    }
    return mapping.get((value or "new_body").lower(), adsk.fusion.FeatureOperations.NewBodyFeatureOperation)

@register_tool("create_parametric_feature")
def create_parametric_feature(feature_type, parameters):
    if not isinstance(parameters, dict):
        parameters = {}
    if feature_type != "sketch":
        return {
            "error": (
                f"Unsupported parametric feature type '{feature_type}'. "
                "Use create_box, create_cylinder, create_coil, create_sketch_offset, "
                "or run_fusion_script for this operation."
            )
        }
    design = get_active_design()
    root = design.rootComponent
    sketch = root.sketches.add(root.xYConstructionPlane)
    sketch.name = parameters.get("name", "AutoSketch")
    return {"result": f"Created sketch {sketch.name}"}

@register_tool("create_box")
def create_box(name="Box", base_plane="xy", length="5 cm", width="5 cm", height="5 cm", x_offset="0 cm", z_offset="0 cm", operation="new_body"):
    design = get_active_design()
    root = design.rootComponent
    
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
        
    return {"result": f"Successfully created parametric box '{name}' of height {height}"}

@register_tool("create_cylinder")
def create_cylinder(name="Cylinder", base_plane="xy", radius="2.5 cm", height="5 cm", x_offset="0 cm", z_offset="0 cm", operation="new_body"):
    design = get_active_design()
    root = design.rootComponent
    
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
        
    return {"result": f"Successfully created parametric cylinder '{name}' of height {height}"}


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
            "operation": operation
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
    param.expression = new_expression
    return {"result": f"Successfully updated '{param_name}' from '{old_expr}' to '{new_expression}'"}

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
    param.expression = expression
    return {"result": {"before": before, "after": _param_to_dict(param)}}

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
def suppress_timeline_feature(name=None, index=None, suppress=True):
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
            
        target_item.isSuppressed = bool(suppress)
        status_str = "suppressed" if suppress else "unsuppressed"
        return {"result": f"Successfully {status_str} timeline feature '{target_item.name}'"}
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error suppressing timeline feature: {e}\n{err}")
        return {"error": f"Failed to suppress/unsuppress timeline feature: {str(e)}"}

@register_tool("delete_timeline_feature")
def delete_timeline_feature(name=None, index=None):
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
            
        feature_name = target_item.name
        target_item.deleteMe()
        return {"result": f"Successfully deleted timeline feature '{feature_name}'"}
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
        feat = mesh_to_brep_feats.add(mesh_to_brep_input)
        feat.name = f"{mesh_body_name}_Solid"
        
        return {"result": f"Successfully converted mesh body '{mesh_body_name}' to solid body '{feat.name}'"}
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
            
        target_dim.parameter.expression = expression
        return {
            "result": f"Updated dimension '{parameter_name}' expression to '{expression}'."
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error editing sketch dimension: {e}\n{err}")
        return {"error": f"Failed to edit sketch dimension: {str(e)}"}


@register_tool("delete_sketch_dimension")
def delete_sketch_dimension(sketch_name, parameter_name):
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
            
        target_dim.deleteMe()
        return {"result": f"Successfully deleted dimension '{parameter_name}' from sketch '{sketch_name}'."}
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
            for idx in entity_indices:
                if idx < sketch.sketchPoints.count:
                    entities.append(sketch.sketchPoints.item(idx))
                else:
                    curve_idx = idx - sketch.sketchPoints.count
                    if 0 <= curve_idx < sketch.sketchCurves.count:
                        entities.append(sketch.sketchCurves.item(curve_idx))

        if not entities:
            return {"error": "No valid sketch entities found for constraint."}

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

        return {"result": f"Successfully created geometric constraint of type '{constraint_type}'."}
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


@register_tool("combine_bodies")
def combine_bodies(target_body_name, tool_body_names, operation="join", keep_tool_bodies=False):
    import traceback
    try:
        design = get_active_design()
        root = design.rootComponent
        
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
        
        combine_feat = combines.add(combine_input)
        combine_feat.name = f"Combine_{target_body.name}"
        
        return {"result": f"Successfully executed Boolean Combine ({operation}) on target body '{target_body_name}'."}
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
            
        body.moveToComponent(target_occurrence)
        
        return {
            "result": f"Successfully moved body '{body_name}' to component '{target_occurrence.component.name}'."
        }
    except Exception as e:
        err = traceback.format_exc()
        adsk.core.Application.get().log(f"Error reorganizing body to component: {e}\n{err}")
        return {"error": f"Failed to reorganize body to component: {str(e)}"}
