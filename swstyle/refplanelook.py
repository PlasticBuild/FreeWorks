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


import FreeCAD as App
import FreeCADGui as Gui

BOX_COLOURS = ((0x50, 0xa8, 0xff), (0xf5, 0x7e, 0xc0), (0x7f, 0x00, 0xfc))   # the boxes' strips
DONE_CSS = "background: #80ff80; border: 1px solid #80ff80;"
PREVIEW_COLOUR = (0.55, 0.64, 0.75)
PREVIEW_TRANSPARENCY = 45
OUTLINE = (1.0, 0.92, 0.0)                    # not yet defined: a yellow outline
ARROW = (0.0, 0.25, 1.0)


# --------------------------------------------------------------------------- names
def _is_sketch(obj):
    try:
        return obj.isDerivedFrom("Sketcher::SketchObject")
    except Exception:
        return False


def _sketch_name(sketch, sub):
    """A pick on a closed sketch names its shape's EdgeN / VertexN: matched to the sketch's own
    geometry by place (the shape's numbering need not follow the geometry's)."""
    import Part
    from . import relationspm
    names = relationspm._entity_names(sketch.Geometry)
    inv = sketch.Placement.inverse()
    if sub.startswith("Edge"):
        k = int(sub[4:]) - 1
        e = sketch.Shape.Edges[k]
        mid = Part.Vertex(inv.multVec(e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)))
        for g, geo in enumerate(sketch.Geometry):
            try:
                if sketch.getConstruction(g) or type(geo).__name__ == "Point":
                    continue
                ge = geo.toShape()
                if abs(ge.Length - e.Length) < 1e-6 and ge.distToShape(mid)[0] < 1e-6:
                    return names[g]
            except Exception:
                continue
        return "Edge%d" % (k + 1)
    if sub.startswith("Vertex"):
        k = int(sub[6:]) - 1
        p = inv.multVec(sketch.Shape.Vertexes[k].Point)
        for g, geo in enumerate(sketch.Geometry):
            if type(geo).__name__ == "Point" and (App.Vector(geo.X, geo.Y, geo.Z) - p).Length < 1e-6:
                return names[g]
        return "Point%d" % (k + 1)
    return sub


def sw_label(obj, sub, before=()):
    ""


    sub = sub or ""
    try:
        if sub and _is_sketch(obj):
            name = _sketch_name(obj, sub)
            return name if "@" in name else "%s@%s" % (name, obj.Label)
        for kind in ("Face", "Edge", "Vertex"):
            if sub.startswith(kind):
                n = 1 + sum(1 for o, s in before if (s or "").startswith(kind) and not _is_sketch(o))
                return "%s<%d>" % (kind, n)
    except Exception as _fw_err:
        _fw_log("refplanelook.py:name", _fw_err)
    return obj.Label if not sub else "%s@%s" % (sub, obj.Label)


def sw_name(ref, refs):
    """A Plane reference box's text: model picks count across the three boxes."""
    before = []
    for r in refs:
        if r is ref:
            break
        if r is not None:
            before.append((r.obj, r.sub))
    return sw_label(ref.obj, ref.sub, before)


def sw_labels(pairs):
    """The texts of one selection list, in pick order."""
    out = []
    for i, (o, s) in enumerate(pairs):
        out.append(sw_label(o, s, pairs[:i]))
    return out


# --------------------------------------------------------------------------- buttons in order
def order(box, offered, curve):
    """The offered constraint buttons first, in the order given, "Set origin on curve" right
    under Perpendicular for a curve."""
    key = (tuple(offered), bool(curve))
    if getattr(box, "_fw_order", None) == key:
        return
    lay = box.layout()
    widgets = [box.buttons[k] for k in offered if k in box.buttons]
    widgets += [b for k, b in box.buttons.items() if k not in offered]
    for w in widgets + [box.on_curve]:
        lay.removeWidget(w)
    at = 1                                  # under the pick box
    for w in widgets:
        lay.insertWidget(at, w)
        at += 1
        if curve and w is box.buttons.get("Perpendicular"):
            lay.insertWidget(at, box.on_curve)
            at += 1
    if not curve:
        lay.addWidget(box.on_curve)
    box._fw_order = key


# --------------------------------------------------------------------------- the message
def paint_label(label, done):
    ""
    try:
        if done:
            label.setStyleSheet("QLabel { color: #000000; border: none; background: transparent; }")
        w = label.parentWidget()
        while w is not None and w.property("swMessage") is None:
            w = w.parentWidget()
            if w is not None and w.inherits("Gui::TaskView::TaskView"):
                w = None
        if w is not None:
            want = ("*[swMessage] { %s }" % DONE_CSS) if done else ""
            if w.styleSheet() != want:
                w.setStyleSheet(want)
    except RuntimeError:
        return
    except Exception as _fw_err:
        _fw_log("refplanelook.py:message", _fw_err)


def paint_message(panel):
    """Green bar for "Fully defined", the plain message box otherwise."""
    paint_label(panel.message, bool(panel.ok))


def paint_later(label, state):
    """The PropertyManager dresses its Message box after the page opens: paint again then, as the
    page stands at that moment (state() -> done)."""
    from PySide import QtCore

    def go():
        if _alive(label):
            try:
                paint_label(label, bool(state()))
            except RuntimeError:
                return
    for ms in (0, 250, 800):
        QtCore.QTimer.singleShot(ms, go)


def _alive(w):
    try:
        import shiboken6 as shiboken
    except ImportError:
        try:
            import shiboken2 as shiboken
        except ImportError:
            return True
    try:
        return shiboken.isValid(w)
    except Exception:
        return False


# --------------------------------------------------------------------------- plane colours
def colour_planes(panel):
    """The planes being made show see-through blue-grey while the PropertyManager is open."""
    kept = panel.__dict__.setdefault("_fw_colours", {})
    for pl in panel.planes:
        try:
            vo = pl.ViewObject
            if vo is None or not hasattr(vo, "ShapeColor"):
                continue
            if pl.Name not in kept:
                kept[pl.Name] = (tuple(vo.ShapeColor), int(getattr(vo, "Transparency", 0)))
            if tuple(round(c, 3) for c in vo.ShapeColor[:3]) != PREVIEW_COLOUR:
                vo.ShapeColor = PREVIEW_COLOUR
            if getattr(vo, "Transparency", None) is not None and vo.Transparency != PREVIEW_TRANSPARENCY:
                vo.Transparency = PREVIEW_TRANSPARENCY
        except Exception as _fw_err:
            _fw_log("refplanelook.py:colour", _fw_err)


def restore_planes(panel):
    """The plane kept keeps its usual look."""
    kept = panel.__dict__.get("_fw_colours", {})
    for pl in panel.planes:
        try:
            if pl.Name in kept:
                colour, transparency = kept[pl.Name]
                pl.ViewObject.ShapeColor = colour
                pl.ViewObject.Transparency = transparency
        except Exception as _fw_err:
            _fw_log("refplanelook.py:restore", _fw_err)
    kept.clear()


# --------------------------------------------------------------------------- the overlay
def global_shape(obj, sub):
    import Part
    s = Part.getShape(obj, sub or "", needSubElement=bool(sub), transform=True)
    owner = obj.getParentGeoFeatureGroup()
    if owner is not None:
        s = s.copy()
        s.transformShape(owner.getGlobalPlacement().toMatrix())
    return s


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def _model_size(doc):
    box = App.BoundBox()
    for o in doc.Objects:
        try:
            if o.isDerivedFrom("PartDesign::Body") or o.isDerivedFrom("Part::Feature") and o.getParentGeoFeatureGroup() is None:
                s = o.Shape
                if not s.isNull():
                    box.add(s.BoundBox)
        except Exception:
            continue
    return max(20.0, (box.DiagonalLength if box.isValid() else 0.0) * 0.35)


def _anchor_and_normal(ref, view):
    """Where an under-defined plane would sit, and which way it would face."""
    s = global_shape(ref.obj, ref.sub)
    try:
        toward = -App.Vector(*view.getViewDirection()) if view is not None else App.Vector(0, 0, 1)
    except Exception:
        toward = App.Vector(0, 0, 1)
    if toward.Length < 1e-12:
        toward = App.Vector(0, 0, 1)
    toward.normalize()
    if s.ShapeType == "Vertex":
        return s.Point, toward
    if s.ShapeType == "Edge":
        mid = s.valueAt((s.FirstParameter + s.LastParameter) / 2.0)
        d = s.tangentAt((s.FirstParameter + s.LastParameter) / 2.0)
        n = d.cross(toward).cross(d)
        if n.Length < 1e-9:
            n = toward
        return mid, n.normalize()
    f = s.Faces[0] if s.Faces else None
    if f is not None:
        u0, u1, v0, v1 = f.ParameterRange
        uv = ((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        return f.valueAt(*uv), f.normalAt(*uv)
    return s.BoundBox.Center, toward


class Overlay:
    """Coin drawing over the view: references in their box colour, the under-defined plane."""

    def __init__(self):
        self.root = None
        self.graph = None

    def _attach(self):
        if self.root is not None:
            return True
        view = _view()
        if view is None:
            return False
        from pivy import coin
        self.root = coin.SoAnnotation()
        self.root.setName("FwPlaneRefs")
        self.graph = view.getSceneGraph()
        self.graph.addChild(self.root)
        return True

    def clear(self):
        if self.root is not None:
            self.root.removeAllChildren()

    def detach(self):
        try:
            if self.root is not None and self.graph is not None:
                self.graph.removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("refplanelook.py:detach", _fw_err)
        self.root = self.graph = None

    def _lines(self, segs, colour, width):
        from pivy import coin
        sep = coin.SoSeparator()
        m = coin.SoBaseColor()
        m.rgb.setValue(*colour)
        st = coin.SoDrawStyle()
        st.lineWidth = width
        co = coin.SoCoordinate3()
        pts = [tuple(p) for seg in segs for p in seg]
        co.point.setValues(0, len(pts), pts)
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(segs), [len(seg) for seg in segs])
        for x in (m, st, co, ls):
            sep.addChild(x)
        self.root.addChild(sep)

    def _points(self, pts, colour, size):
        from pivy import coin
        sep = coin.SoSeparator()
        m = coin.SoBaseColor()
        m.rgb.setValue(*colour)
        st = coin.SoDrawStyle()
        st.pointSize = size
        co = coin.SoCoordinate3()
        co.point.setValues(0, len(pts), [tuple(p) for p in pts])
        ps = coin.SoPointSet()
        for x in (m, st, co, ps):
            sep.addChild(x)
        self.root.addChild(sep)

    def reference(self, ref, colour):
        s = global_shape(ref.obj, ref.sub)
        c = tuple(v / 255.0 for v in colour)
        if s.ShapeType == "Vertex":
            self._points([s.Point], c, 9)
            return
        edges = s.Edges if s.ShapeType != "Edge" else [s]
        segs = []
        for e in edges[:200]:
            try:
                pts = e.discretize(Deflection=max(1e-3, e.Length / 200.0))
            except Exception:
                pts = [v.Point for v in e.Vertexes]
            if len(pts) >= 2:
                segs.append(pts)
        if segs:
            self._lines(segs, c, 3)

    def outline(self, centre, normal, size):
        """The yellow outline of a plane still waiting for references, with its blue normal."""
        x = App.Vector(1, 0, 0) if abs(normal.x) < 0.9 else App.Vector(0, 1, 0)
        u = normal.cross(x).normalize()
        v = normal.cross(u).normalize()
        h, w = size * 0.5, size * 0.35
        rect = [centre + u * h + v * w, centre - u * h + v * w, centre - u * h - v * w,
                centre + u * h - v * w, centre + u * h + v * w]
        self._lines([rect], OUTLINE, 2)
        tip = centre + normal * size * 0.12
        head = size * 0.03
        self._lines([[centre, tip], [tip, tip - normal * head * 1.6 + u * head],
                     [tip, tip - normal * head * 1.6 - u * head]], ARROW, 3)

    def show(self, panel):
        if not self._attach():
            return
        self.clear()
        for i, r in enumerate(panel.refs):
            if r is None:
                continue
            try:
                self.reference(r, BOX_COLOURS[i])
            except Exception as _fw_err:
                _fw_log("refplanelook.py:reference", _fw_err)
        first = next((r for r in panel.refs if r is not None), None)
        if first is not None and not panel.ok:
            try:
                centre, normal = _anchor_and_normal(first, _view())
                self.outline(centre, normal, _model_size(panel.doc))
            except Exception as _fw_err:
                _fw_log("refplanelook.py:outline", _fw_err)


def after_update(panel):
    paint_message(panel)
    paint_later(panel.message, lambda: panel.ok)
    colour_planes(panel)
    ov = panel.__dict__.setdefault("_fw_overlay", Overlay())
    try:
        ov.show(panel)
    except Exception as _fw_err:
        _fw_log("refplanelook.py:overlay", _fw_err)


def close(panel):
    ov = panel.__dict__.get("_fw_overlay")
    if ov is not None:
        ov.detach()
