import adsk.core, adsk.fusion


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    design = adsk.fusion.Design.cast(app.activeProduct)
    if not design:
        raise RuntimeError("No active Fusion design.")

    sel = ui.activeSelections
    if sel.count != 1:
        raise RuntimeError("Select the flat circular socket base face first.")

    face = adsk.fusion.BRepFace.cast(sel.item(0).entity)
    if not face or not adsk.core.Plane.cast(face.geometry):
        raise RuntimeError("Selection must be the flat circular base face, not the cylinder wall.")

    circles = []
    for i in range(face.edges.count):
        edge = face.edges.item(i)
        circle = adsk.core.Circle3D.cast(edge.geometry)
        if circle:
            circles.append((edge, circle))
    if not circles:
        raise RuntimeError("Selected face has no circular edge.")

    edge, source_circle = max(circles, key=lambda pair: pair[1].radius)
    comp = face.body.parentComponent

    for i in range(comp.sketches.count):
        sketch = comp.sketches.item(i)
        if sketch.name == "CoilManualCenterTarget_USE_THIS":
            sketch.name = "CoilManualCenterTarget_USE_THIS_old"

    sketch = comp.sketches.add(face)
    sketch.name = "CoilManualCenterTarget_USE_THIS"

    try:
        projected_entities = sketch.project2([edge], True)
        projected = adsk.core.ObjectCollection.create()
        for entity in projected_entities:
            projected.add(entity)
    except Exception:
        projected = sketch.project(edge)

    projected_circle = None
    for i in range(projected.count):
        projected_circle = adsk.fusion.SketchCircle.cast(projected.item(i))
        if projected_circle:
            break
    if not projected_circle:
        raise RuntimeError("Projection did not return a selectable sketch circle.")

    projected_circle.isConstruction = True
    center = projected_circle.centerSketchPoint.geometry

    target_circle = sketch.sketchCurves.sketchCircles.addByCenterRadius(center, 0.12)
    target_circle.isConstruction = True
    sketch.geometricConstraints.addConcentric(target_circle, projected_circle)

    model_center = sketch.sketchToModelSpace(target_circle.centerSketchPoint.geometry)
    delta_mm = model_center.distanceTo(source_circle.center) * 10.0

    print("Created CoilManualCenterTarget_USE_THIS.")
    print("Use the CENTER POINT of the small construction circle in that sketch.")
    print("Use CoilBasePlane or this same selected face as the Coil plane.")
    print("Center delta mm:", delta_mm)
