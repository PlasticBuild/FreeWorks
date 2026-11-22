# SPDX-License-Identifier: LGPL-2.1-or-later
""











_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import math

import FreeCAD as App
import FreeCADGui as Gui

V = App.Vector
PROP = "FreeWorks2Dto3D"     # on a turned view: "view;base sketch name;dx;dy" (how to put it back)

VIEWS = ("Front", "Top", "Right", "Bottom", "Left", "Back", "Auxiliary")
COMMANDS = {"FreeWorks_2Dto3D" + v: v for v in VIEWS}
COMMANDS["FreeWorks_2Dto3DExtrude"] = "Extrude"
COMMANDS["FreeWorks_2Dto3DCut"] = "Cut"
TIPS = {"Front": "Makes the picked sketch entities the front view (a turned view comes back where it was drawn).",
        "Top": "Turns the picked sketch entities into the top view, on top of the front view.",
        "Right": "Turns the picked sketch entities into the right view, at the right of the front view.",
        "Bottom": "Turns the picked sketch entities into the bottom view, under the front view.",
        "Left": "Turns the picked sketch entities into the left view, at the left of the front view.",
        "Back": "Turns the picked sketch entities into the back view, behind the front view.",
        "Auxiliary": "Turns the picked sketch entities about the line picked last into an auxiliary view.",
        "Extrude": "Extrudes the picked closed sketch entities (Extruded Boss/Base).",
        "Cut": "Cuts with the picked closed sketch entities (Extruded Cut)."}
PIXMAPS = {"Front": "view-front", "Top": "view-top", "Right": "view-right", "Bottom": "view-bottom",
           "Left": "view-left", "Back": "view-rear", "Auxiliary": "view-axonometric",
           "Extrude": "PartDesign_Pad", "Cut": "PartDesign_Pocket"}


def _sketch3d():
    try:
        from . import sketch3d
        return sketch3d.editing()
    except Exception as _fw_err:
        _fw_log("twodto3d.py:57", _fw_err)
        return None


def _sketch():
    from . import contextbar
    return contextbar.sketch_in_edit()


def picked(sketch):
    """Geometry indices of the picked edges of sketch, in pick order."""
    out = []
    for sel in Gui.Selection.getSelectionEx():
        if sel.Object is None or sel.Object.Name != sketch.Name or sel.Object.Document is not sketch.Document:
            continue
        for name in sel.SubElementNames:
            name = name.split(".")[-1]
            if name.startswith("Edge"):
                try:
                    i = int(name[4:]) - 1
                except ValueError:
                    continue
                if 0 <= i < len(sketch.Geometry) and i not in out:
                    out.append(i)
    return out


def _box(sketch, indices):
    """(xmin, ymin, xmax, ymax) of the geometry indices, else None."""
    import Part
    box = None
    for i in indices:
        try:
            b = sketch.Geometry[i].toShape().BoundBox
        except Exception as _fw_err:
            _fw_log("twodto3d.py:92", _fw_err)
            continue
        box = b if box is None else box.united(b)
    return None if box is None else (box.XMin, box.YMin, box.XMax, box.YMax)


def _rot(axis, deg):
    return App.Rotation(V(*axis), deg)


def layout(view, box, front, hinge=None):
    """(attachment offset, 2D matrix taking the view's sketch coordinates to the new sketch's) for a view
    whose entities fill box, round the front view's box (front may be None: the origin)."""
    xmin, ymin, xmax, ymax = box
    fx0, fy0, fx1, fy1 = front if front is not None else (0.0, 0.0, 0.0, 0.0)
    m = App.Matrix()
    if view == "Top":
        # third angle: above the front view, its lower edge the front face; it lies on the front's top
        m.move(V(0, -ymin, 0))
        return App.Placement(V(0, fy1, 0), _rot((1, 0, 0), -90)), m
    if view == "Bottom":
        m.move(V(0, -ymax, 0))
        return App.Placement(V(0, fy0, 0), _rot((1, 0, 0), 90)), m
    if view == "Right":
        m.move(V(-xmin, 0, 0))
        return App.Placement(V(fx1, 0, 0), _rot((0, 1, 0), 90)), m
    if view == "Left":
        m.move(V(-xmax, 0, 0))
        return App.Placement(V(fx0, 0, 0), _rot((0, 1, 0), -90)), m
    if view == "Back":
        # seen from behind, it runs the other way: its right edge over the front's left edge
        m.move(V(-xmax, 0, 0))
        return App.Placement(V(fx0, 0, 0), _rot((0, 1, 0), 180)), m
    if view == "Auxiliary":
        a, b = hinge
        d = b - a
        d = d * (1.0 / d.Length)
        n = V(-d.y, d.x, 0)
        cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        if (V(cx, cy, 0) - a).dot(n) < 0:
            # the view is on the line's right: run the line the other way, so it is on its left
            a, d, n = b, -d, -n
        # u along the line, v away from it: the new sketch's X is the line, its Y goes away from the front
        r = App.Matrix(d.x, d.y, 0, 0, n.x, n.y, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        m = r.multiply(App.Matrix(1, 0, 0, -a.x, 0, 1, 0, -a.y, 0, 0, 1, 0, 0, 0, 0, 1))
        # the near edge of the view folds onto the line
        vmin = min((V(x, y, 0) - a).dot(n) for x in (xmin, xmax) for y in (ymin, ymax))
        m2 = App.Matrix()
        m2.move(V(0, -vmin, 0))
        m = m2.multiply(m)
        z = d.cross(V(0, 0, -1))
        rot = App.Rotation(d, V(0, 0, -1), z, "ZXY")
        return App.Placement(V(a.x, a.y, 0), rot), m
    raise ValueError(view)


def _container(sketch):
    for o in sketch.InList:
        if o.TypeId == "PartDesign::Body":
            return o
    return None


def turn(sketch, view, indices=None):
    """Moves the picked entities of sketch into a new sketch for view, attached to sketch; returns the new
    sketch, else a reason (str)."""
    if indices is None:
        indices = picked(sketch)
    hinge = None
    if view == "Auxiliary":
        lines = [i for i in indices if type(sketch.Geometry[i]).__name__ == "LineSegment"]
        if not lines or len(indices) < 2:
            return "Auxiliary: pick the view's entities, then the line it folds about."
        h = lines[-1]
        g = sketch.Geometry[h]
        hinge = (V(g.StartPoint.x, g.StartPoint.y, 0), V(g.EndPoint.x, g.EndPoint.y, 0))
        indices = [i for i in indices if i != h]
    if not indices:
        return "%s: pick the sketch entities of the view first." % view
    box = _box(sketch, indices)
    rest = [i for i in range(len(sketch.Geometry)) if i not in indices]
    front = _box(sketch, rest)
    offset, m = layout(view, box, front, hinge)
    doc = sketch.Document
    geos = []
    for i in indices:
        g = sketch.Geometry[i].copy()
        g.transform(m)
        geos.append((g, sketch.getConstruction(i)))
    body = _container(sketch)
    new = body.newObject("Sketcher::SketchObject", sketch.Name + view) if body is not None else \
        doc.addObject("Sketcher::SketchObject", sketch.Name + view)
    new.Label = "%s %s" % (sketch.Label, view)
    try:
        new.AttachmentSupport = [(sketch, "")]
    except Exception:
        new.Support = [(sketch, "")]
    new.MapMode = "ObjectXY"
    new.AttachmentOffset = offset
    for g, construction in geos:
        k = new.addGeometry(g, construction)
    inv = m.inverse()
    new.addProperty("App::PropertyString", PROP, "FreeCAD", "How this 2D to 3D view goes back")
    setattr(new, PROP, "%s;%s;%s" % (view, sketch.Name, ",".join("%.12g" % x for x in inv.A)))
    sketch.delGeometries(sorted(indices))
    doc.recompute()
    return new


def back_to_front(view_sketch):
    """Front on a turned view: its picked entities (all when none) back in the first sketch where they were
    drawn; the view sketch goes when it is empty. The first sketch, else a reason."""
    info = getattr(view_sketch, PROP, "")
    try:
        _, base_name, nums = info.split(";")
        base = view_sketch.Document.getObject(base_name)
        inv = App.Matrix(*[float(x) for x in nums.split(",")])
    except Exception as _fw_err:
        _fw_log("twodto3d.py:210", _fw_err)
        return "Front: the picked entities are the front view already."
    if base is None:
        return "Front: the sketch this view came from is gone."
    indices = picked(view_sketch) or list(range(len(view_sketch.Geometry)))
    for i in indices:
        g = view_sketch.Geometry[i].copy()
        g.transform(inv)
        base.addGeometry(g, view_sketch.getConstruction(i))
    view_sketch.delGeometries(sorted(indices))
    doc = view_sketch.Document
    doc.recompute()
    return base


def extrude(sketch, cut=False, indices=None):
    """Extrude... / Cut...: the picked entities (all when none) as a sketch of their own when only some are
    picked, then Extruded Boss/Base or Extruded Cut on it. The sketch extruded."""
    if indices is None:
        indices = picked(sketch)
    target = sketch
    if indices and len(indices) < len(sketch.Geometry):
        body = _container(sketch)
        doc = sketch.Document
        target = body.newObject("Sketcher::SketchObject", sketch.Name + ("Cut" if cut else "Extrude")) \
            if body is not None else doc.addObject("Sketcher::SketchObject", sketch.Name + "Extrude")
        target.Label = "%s %s" % (sketch.Label, "Cut" if cut else "Extrude")
        try:
            target.AttachmentSupport = [(sketch, "")]
        except Exception:
            target.Support = [(sketch, "")]
        target.MapMode = "ObjectXY"
        for i in indices:
            target.addGeometry(sketch.Geometry[i].copy(), False)
        doc.recompute()
    return target


def _run_feature(target, cut):
    """Leaves the sketch and starts Extruded Boss/Base (or Extruded Cut) on target."""
    try:
        Gui.ActiveDocument.resetEdit()
    except Exception as _fw_err:
        _fw_log("twodto3d.py:249", _fw_err)
    target.Document.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(target)
    try:
        from . import catalog
        natives = catalog.BY_KEY["CutExtrude" if cut else "BossExtrude"].natives
    except Exception:
        natives = ()
    natives = tuple(natives) + (("PartDesign_Pocket",) if cut else ("PartDesign_Pad",))
    name = next((n for n in natives if n in Gui.listCommands()), None)
    if name:
        Gui.runCommand(name)


class _Command:
    def __init__(self, name):
        self.name = name
        self.view = COMMANDS[name]

    def GetResources(self):
        text = self.view + ("..." if self.view in ("Extrude", "Cut") else "")
        return {"Pixmap": PIXMAPS[self.view], "MenuText": text, "ToolTip": TIPS[self.view], "CmdType": "ForEdit"}

    def IsActive(self):
        if _sketch3d() is not None:

            return self.view in ("Extrude", "Cut")
        sketch = _sketch()
        if sketch is None:
            return False
        if self.view == "Front":
            return bool(getattr(sketch, PROP, "")) or bool(picked(sketch))
        if self.view in ("Extrude", "Cut"):
            return len(sketch.Geometry) > 0
        return bool(picked(sketch))

    def Activated(self):
        if _sketch3d() is not None and self.view in ("Extrude", "Cut"):
            from . import sketch3d
            sketch3d.extrude_3d(self.view == "Cut")
            return
        sketch = _sketch()
        if sketch is None:
            return
        doc = sketch.Document
        view = self.view
        if view in ("Extrude", "Cut"):
            doc.openTransaction(view)
            try:
                target = extrude(sketch, view == "Cut")
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            _run_feature(target, view == "Cut")
            return
        doc.openTransaction("2D to 3D " + view)
        try:
            if view == "Front":
                got = back_to_front(sketch) if getattr(sketch, PROP, "") else \
                    "Front: the picked entities are the front view."
            else:
                got = turn(sketch, view)
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: 2D to 3D %s: %s\n" % (view, error))
            return
        doc.commitTransaction()
        if isinstance(got, str):
            App.Console.PrintMessage("FreeCAD: %s\n" % got)
            _status(got)
        else:
            Gui.Selection.clearSelection()
            _status("2D to 3D: %s view made (%s)." % (view, got.Label) if view != "Front" else
                    "2D to 3D: the entities are back in %s." % got.Label)


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception as _fw_err:
        _fw_log("twodto3d.py:327", _fw_err)


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
