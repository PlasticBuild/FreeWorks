# -*- coding: utf-8 -*-
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


import FreeCAD as App
import Part

SUFFIX = "_Centerlines"
TYPE = "SWSketchCenterlines"
_PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Sketch"
COLOUR = (0.25, 0.25, 0.25)


def enabled():
    return App.ParamGet(_PARAM).GetBool("ShowConstructionInClosedSketch", True)


# --------------------------------------------------------------------------- geometry
def construction_ids(sketch):
    out = []
    for i, g in enumerate(sketch.Geometry):
        try:
            if sketch.getConstruction(i) and not isinstance(g, Part.Point):
                out.append(i)
        except Exception as _fw_err:
            _fw_log("sketchcenterlines.py:51", _fw_err)
    return out


def container_of(sketch):
    """The group the companion goes in (None = the document root), and its global placement."""
    parent = sketch.getParentGeoFeatureGroup()
    if parent is not None and parent.isDerivedFrom("PartDesign::Body"):
        parent = parent.getParentGeoFeatureGroup()
    pl = parent.getGlobalPlacement() if parent is not None else App.Placement()
    return parent, pl


def edges_of(sketch, ids, container_placement):
    """The construction edges, in the container's coordinates, one per id (in order)."""
    local = container_placement.inverse().multiply(sketch.getGlobalPlacement())
    edges = []
    for i in ids:
        e = sketch.Geometry[i].toShape()
        e.Placement = local.multiply(e.Placement)
        edges.append(e)
    return edges


def axis_index(sketch, geo):
    """FreeCAD's AxisK for a construction line (construction lines counted in geometry order)."""
    k = 0
    for i, g in enumerate(sketch.Geometry):
        if isinstance(g, Part.LineSegment) and sketch.getConstruction(i):
            if i == geo:
                return k
            k += 1
    return None


# --------------------------------------------------------------------------- the companion
class Centerlines:
    def __init__(self, obj, sketch):
        obj.Proxy = self
        obj.addProperty("App::PropertyLinkGlobal", "Sketch", "Centerlines", "The sketch whose construction geometry this draws")
        obj.addProperty("App::PropertyIntegerList", "GeoIds", "Centerlines", "Sketch geometry index of Edge1, Edge2, ...")
        obj.addProperty("App::PropertyString", "SWType", "Centerlines", "").SWType = TYPE
        for p in ("Sketch", "GeoIds", "SWType"):
            obj.setEditorMode(p, 1)
        obj.Sketch = sketch

    def execute(self, obj):
        sketch = obj.Sketch
        if sketch is None:
            obj.Shape = Part.Shape()
            return
        ids = construction_ids(sketch)
        _, cpl = container_of(sketch)
        edges = edges_of(sketch, ids, cpl)
        obj.GeoIds = ids
        obj.Shape = Part.makeCompound(edges) if edges else Part.Shape()
        obj.Placement = App.Placement()

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def dumps(self):
        return {"type": TYPE}

    def loads(self, state):
        return None

    __getstate__, __setstate__ = dumps, loads


class _View:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ""

    def dumps(self):
        return {"type": TYPE}

    def loads(self, state):
        return None

    __getstate__, __setstate__ = dumps, loads


def companion(sketch):
    doc = sketch.Document
    for o in sketch.InList:
        if getattr(o, "SWType", "") == TYPE and getattr(o, "Sketch", None) is sketch:
            return o
    return None


def is_companion(obj):
    return getattr(obj, "SWType", "") == TYPE


def make(sketch):
    doc = sketch.Document
    obj = doc.addObject("Part::FeaturePython", sketch.Name + SUFFIX)
    Centerlines(obj, sketch)
    obj.Label = sketch.Label + " centerlines"
    parent, _ = container_of(sketch)
    if parent is not None:
        try:
            parent.addObject(obj)
        except Exception as _fw_err:
            _fw_log("sketchcenterlines.py:162", _fw_err)
    if App.GuiUp:
        _View(obj.ViewObject)
        _style(obj.ViewObject)
    obj.recompute()
    return obj


def _style(v):
    for prop, value in (("ShowInTree", False), ("LineColor", COLOUR), ("PointColor", COLOUR),
                        ("LineWidth", 1.0), ("PointSize", 1.0), ("DrawStyle", "Dashdot"),
                        ("Selectable", True)):
        try:
            setattr(v, prop, value)
        except Exception as _fw_err:
            _fw_log("sketchcenterlines.py:177", _fw_err)


def reference_of(obj, sub):
    """A pick on a companion (obj, "EdgeN") as the sketch's own reference:
    (sketch, "AxisK", geo) for a construction line, (sketch, None, geo) for other construction curves."""
    if not is_companion(obj) or not sub.startswith("Edge"):
        return None
    try:
        n = int(sub[4:]) - 1
        geo = obj.GeoIds[n]
    except Exception:
        return None
    sketch = obj.Sketch
    k = axis_index(sketch, geo)
    return (sketch, "Axis%d" % k if k is not None else None, geo)


# --------------------------------------------------------------------------- keeping it in step
def _in_edit(sketch):
    try:
        import FreeCADGui as Gui
        gdoc = Gui.getDocument(sketch.Document.Name)
        vp = gdoc.getInEdit() if gdoc is not None else None
        return getattr(vp, "Object", None) is sketch
    except Exception:
        return False


def sync_document(doc):
    """Make, update and show/hide the companions of doc's sketches."""
    if doc is None or not enabled():
        return
    for sketch in [o for o in doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")]:
        try:
            # The legacy watcher is no longer started. Keep every existing companion for references,
            # but never leave one visible beside the canonical one (or while the sketch is edited).
            from .fwsketch import centerlines as legacy
            for old in legacy.all_of(sketch):
                if old.ViewObject.Visibility:
                    old.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("sketchcenterlines.py:219", _fw_err)
        ids = construction_ids(sketch)
        c = companion(sketch)
        editing = _in_edit(sketch)
        try:
            shown = bool(sketch.ViewObject.Visibility)
        except Exception:
            shown = False
        if c is None:
            if not ids or editing or not shown:
                continue            # made once the sketch is shown, closed, with construction geometry
            c = make(sketch)
        elif not editing and (list(c.GeoIds) != ids or "Touched" in (c.State or [])):
            c.recompute()
        try:
            want = shown and not editing and bool(ids)
            if c.ViewObject.Visibility != want:
                c.ViewObject.Visibility = want
        except Exception as _fw_err:
            _fw_log("sketchcenterlines.py:238", _fw_err)


_TIMER = []


def _tick():
    try:
        sync_document(App.ActiveDocument)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sketch centerlines: %s\n" % error)


def install():
    if _TIMER or not App.GuiUp:
        return
    from PySide import QtCore
    t = QtCore.QTimer()
    t.setInterval(600)
    t.timeout.connect(_tick)
    t.start()
    _TIMER.append(t)
