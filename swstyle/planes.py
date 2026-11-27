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
from PySide import QtCore

from . import paths

PARAM = "PickedPlane"        # addon parameter (default on)
ANNOTATION = "SWStylePickedPlane"
PLANE = "App::Plane"
DATUMS = ("PartDesign::Plane", "Part::DatumPlane")    # the person's own planes (Plane1...)
ORIGIN = "App::Origin"

# #5aa1f3 to #6fb4f5), round dots on the corners and edge middles, the name in the plane
LINE = {False: "0.353 0.631 0.953", True: "0.502 0.706 1.0"}
DOT = 7                      # the handle dots, in pixels across
MARGIN = 0.12                # the plane reaches this much past the part, in parts of its size
LEAST = 25.0                 # half size of the plane when the body has no shape yet, in mm
TEXT_IN = 0.04               # the name sits this far inside the corner, in parts of the size
TEXT_SIZE = 0.055            # a shown plane's name, in parts of the plane's size

SHOWN_LINE = {False: "0.357 0.549 0.937", True: "0.502 0.659 1.0"}
CROSS_LINE = {False: "0.1 0.1 0.1", True: "0.72 0.72 0.72"}      # dotted, where two shown planes cross
MUTE = "SWPlaneMute"         # the node that makes FreeCAD's own drawing of a shown plane invisible


def enabled():
    return paths.params().GetBool(PARAM, True)


# --------------------------------------------------------------------------- geometry
def _shapes(plane):
    """The shapes the plane belongs to: its body's, or every shown shape in the document."""
    doc = plane.Document
    for origin in _origins(plane):
        for owner in getattr(origin, "InList", []):
            shape = getattr(owner, "Shape", None)
            if shape is not None and not shape.isNull() and shape.BoundBox.isValid():
                return [shape]
    out = []
    for obj in doc.Objects:
        if obj.TypeId.startswith("PartDesign::Body") or obj.TypeId.startswith("Part::"):
            shape = getattr(obj, "Shape", None)
            vo = getattr(obj, "ViewObject", None)
            if shape is not None and not shape.isNull() and shape.BoundBox.isValid() \
                    and (vo is None or vo.Visibility):
                out.append(shape)
    return out


def _origins(plane):
    return [o for o in plane.InList if getattr(o, "TypeId", "") == ORIGIN]


def is_datum(plane):
    return getattr(plane, "TypeId", "") in DATUMS


def _datum_coords(plane):
    """The rectangle FreeCAD draws for a datum plane (its own size: automatic or Length x Width),
    in the plane's coordinates."""
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setType(coin.SoCoordinate3.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.FIRST)
    sa.apply(plane.ViewObject.RootNode)
    path = sa.getPath()
    if path is None:
        return None
    pts = path.getTail().point.getValues()
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def manual_box(plane):
    ""

    try:
        box = [float(x) for x in (getattr(plane, "SWPlaneBox", None) or [])]
    except Exception:
        return None
    if len(box) == 4 and box[1] > box[0] and box[3] > box[2]:
        return tuple(box)
    return None


def extents(plane):
    """(origin, u, v, umin, umax, vmin, vmax) of the square to draw for the plane, in model space."""
    placement = plane.getGlobalPlacement()
    o = placement.Base
    u = placement.Rotation.multVec(App.Vector(1, 0, 0))
    v = placement.Rotation.multVec(App.Vector(0, 1, 0))
    if not is_datum(plane):
        box = manual_box(plane)
        if box is not None:
            return (o, u, v) + box
    if is_datum(plane):
        try:
            box = _datum_coords(plane)        # the size FreeCAD gives it (and the handles change)
            if box is not None:
                return (o, u, v) + tuple(box)
        except Exception as _fw_err:
            _fw_log("planes.py:datum-size", _fw_err)
    us, vs = [], []
    for shape in _shapes(plane):
        bb = shape.BoundBox
        for x in (bb.XMin, bb.XMax):
            for y in (bb.YMin, bb.YMax):
                for z in (bb.ZMin, bb.ZMax):
                    d = App.Vector(x, y, z) - o
                    us.append(d.dot(u))
                    vs.append(d.dot(v))
    if not us:
        return o, u, v, -LEAST, LEAST, -LEAST, LEAST
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)

    size = max(umax - umin, vmax - vmin)
    if size < 1e-6:
        return o, u, v, -LEAST, LEAST, -LEAST, LEAST
    m = max(MARGIN * size, 1.0)
    return o, u, v, umin - m, umax + m, vmin - m, vmax + m


def corners(plane):
    """The square's four corners, from the lower left round to the upper left, in model space."""
    o, u, v, umin, umax, vmin, vmax = extents(plane)
    return [o + u * umin + v * vmin, o + u * umax + v * vmin, o + u * umax + v * vmax, o + u * umin + v * vmax]


def _p(p):
    return "%.9g %.9g %.9g" % (p.x, p.y, p.z)


def _text(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def _dark():
    try:
        from . import style
        return style.dark()
    except Exception:
        return False


def _frame(u, v):
    """Coin rotation text taking the x and y axes to u and v."""
    rot = App.Rotation(u, v, u.cross(v), "ZXY")
    axis, angle = rot.Axis, rot.Angle
    return "%.9g %.9g %.9g %.9g" % (axis.x, axis.y, axis.z, angle)


def crossing(a, b):
    """(start, end) of the segment where planes a and b cross inside both squares, or None."""
    ea, eb = extents(a), extents(b)
    na, nb = ea[1].cross(ea[2]), eb[1].cross(eb[2])
    d = na.cross(nb)
    if d.Length < 1e-9:
        return None
    ha, hb = na.dot(ea[0]), nb.dot(eb[0])
    p0 = (nb.cross(d) * ha + d.cross(na) * hb) * (1.0 / d.dot(d))
    lo, hi = -1e18, 1e18
    for o, u, v, umin, umax, vmin, vmax in (ea, eb):
        for axis, least, most in ((u, umin, umax), (v, vmin, vmax)):
            at, step = (p0 - o).dot(axis), d.dot(axis)
            if abs(step) < 1e-12:
                if not least <= at <= most:
                    return None
                continue
            t1, t2 = (least - at) / step, (most - at) / step
            lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
    if hi - lo < 1e-9:
        return None
    return p0 + d * lo, p0 + d * hi


def inventor(planes, shown=()):
    """Open Inventor text drawing each picked plane (the outline, eight round handles and its
    name in the plane) and the dotted lines where two shown planes cross (the shown planes draw themselves:
    mute)."""
    dark = _dark()
    lines = ["#Inventor V2.1 ascii", "Separator {", "PickStyle { style UNPICKABLE }",
             "LightModel { model BASE_COLOR }"]
    plain = [p for p in shown if p not in planes]
    for p in shown:
        if is_datum(p):
            o, u, v = extents(p)[:3]
            lines += ["Separator {", "Transform { translation %s rotation %s }" % (_p(o), _frame(u, v)),
                      _local(p, dark).split("\n", 1)[1], "}"]
    every = list(planes) + plain
    pairs = [(a, b) for i, a in enumerate(every) for b in every[i + 1:]]
    segments = [seg for seg in (crossing(a, b) for a, b in pairs) if seg is not None] if len(shown) > 1 else []
    if segments:
        lines += ["Separator {",
                  "BaseColor { rgb %s }" % CROSS_LINE[dark],
                  "DrawStyle { lineWidth 1 linePattern 0x3333 }",
                  "Coordinate3 { point [ %s ] }" % ", ".join(_p(p) for seg in segments for p in seg),
                  "LineSet { numVertices [ %s ] }" % ", ".join("2" for _ in segments),
                  "}"]
    marker = _dot_marker()
    for plane in planes:
        c = corners(plane)
        mids = [(c[i] + c[(i + 1) % 4]) * 0.5 for i in range(4)]
        lines += ["Separator {",
                  "BaseColor { rgb %s }" % LINE[dark],
                  "DrawStyle { lineWidth 1 pointSize %d }" % DOT,
                  "Coordinate3 { point [ %s ] }" % ", ".join(_p(p) for p in c + [c[0]]),
                  "LineSet { numVertices [ 5 ] }",
                  "Coordinate3 { point [ %s ] }" % ", ".join(_p(p) for p in c + mids),
                  ("MarkerSet { markerIndex [ %d ] numPoints 8 }" % marker) if marker is not None
                  else "PointSet { numPoints 8 }"]
        if plane not in shown:   # a shown plane already has its name on its edge
            lines += _name_in_plane(plane)
        lines.append("}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _dot_marker():
    """FreeCAD's index of a round filled marker DOT pixels across, or None (square points then)."""
    try:
        return int(Gui.getMarkerIndex("CIRCLE_FILLED", DOT))
    except Exception:
        pass
    try:
        from pivy import coin
        return int(getattr(coin.SoMarkerSet, "CIRCLE_FILLED_%d_%d" % (DOT, DOT)))
    except Exception:
        return None


def _name_in_plane(plane):
    ""

    o, u, v, umin, umax, vmin, vmax = extents(plane)
    size = max(umax - umin, vmax - vmin)
    h = TEXT_SIZE * size
    inset = TEXT_IN * size
    return ["Transform { translation %s rotation %s }" % (_p(o), _frame(u, v)),
            "Translation { translation %.9g %.9g 0 }" % (umin + inset, vmax - inset - h),
            'Font { name "Century Gothic" size %.9g }' % h,
            "AsciiText { string %s justification LEFT }" % _text(plane.Label)]


# --------------------------------------------------------------------------- the watch
def drawn_by_freecad(plane):
    """True when FreeCAD shows the plane itself: its origin and the plane are both visible."""
    try:
        if not plane.ViewObject.Visibility:
            return False
        for origin in _origins(plane):
            vo = getattr(origin, "ViewObject", None)
            if vo is not None and vo.Visibility:
                return True
    except Exception as _fw_err:
        _fw_log("planes.py:211", _fw_err)
    return False


def picked_planes(doc_name):
    try:
        objects = Gui.Selection.getSelection(doc_name)
    except Exception:
        return []
    out = []
    for obj in objects:
        if (obj.TypeId == PLANE or obj.TypeId in DATUMS) and obj not in out:
            out.append(obj)
    return out


def shown_planes(doc_name):
    """The origin planes FreeCAD shows (View > Hide / Show > Planes, or the origin shown)."""
    doc = App.getDocument(doc_name)
    return [o for o in doc.Objects if (o.TypeId == PLANE and _origins(o) and drawn_by_freecad(o))
            or (o.TypeId in DATUMS and _datum_shown(o))]


def _datum_shown(plane):
    try:
        from . import refplane          # the Plane PropertyManager previews its planes its own way
        pm = refplane.current()
        if pm is not None and plane in getattr(pm, "planes", ()):
            return False
    except Exception as _fw_err:
        _fw_log("planes.py:pm-preview", _fw_err)
    try:
        return bool(plane.ViewObject.Visibility) and plane.ViewObject.RootNode is not None
    except Exception:
        return False


_kept = {}            # (document, plane) -> FreeCAD's own drawing, while ours stands in for it


def _local(plane, dark):
    """A shown plane in its own coordinates: the outline and the name along the top edge."""
    o, u, v, umin, umax, vmin, vmax = extents(plane)
    size = max(umax - umin, vmax - vmin)
    h = TEXT_SIZE * size
    inset = TEXT_IN * size
    c = [(umin, vmin), (umax, vmin), (umax, vmax), (umin, vmax), (umin, vmin)]
    return "\n".join([
        "#Inventor V2.1 ascii", "Separator {",
        "LightModel { model BASE_COLOR }",
        "BaseColor { rgb %s }" % SHOWN_LINE[dark],
        "DrawStyle { lineWidth 1 }",
        "Coordinate3 { point [ %s ] }" % ", ".join("%.9g %.9g 0" % xy for xy in c),
        "LineSet { numVertices [ 5 ] }",
        "Translation { translation %.9g %.9g 0 }" % (umin + inset, vmax - inset - h),
        'Font { name "Century Gothic" size %.9g }' % h,
        "AsciiText { string %s justification LEFT }" % _text(plane.Label),
        "}"]) + "\n"


def _holder(plane):
    """(the node holding FreeCAD's drawing of the plane, the index of that drawing) or (None, -1)."""
    from pivy import coin
    root = plane.ViewObject.RootNode
    for i in range(root.getNumChildren()):
        sw = root.getChild(i)
        if isinstance(sw, coin.SoSwitch) and sw.getName() == "ModeSwitch" and sw.getNumChildren():
            sel = sw.getChild(max(0, sw.whichChild.getValue()))
            for j in range(sel.getNumChildren() if hasattr(sel, "getNumChildren") else 0):
                child = sel.getChild(j)
                if child.getTypeId().getName() in ("SoShapeScale", "Separator") \
                        and (child.getName() == MUTE or child.getTypeId().getName() == "SoShapeScale"):
                    return sel, j
    return None, -1


def _mute_datum(plane, on):
    """A shown datum plane: FreeCAD's yellow fill and edge made see-through (still picked and
    hovered there); the outline and name are drawn with the picked planes."""
    from pivy import coin
    kind = coin.SoType.fromName("SoBrepFaceSet")
    sa = coin.SoSearchAction()
    sa.setType(kind)
    sa.setInterest(coin.SoSearchAction.FIRST)
    sa.apply(plane.ViewObject.RootNode)
    path = sa.getPath()
    if path is None or path.getLength() < 2:
        return False
    inner = path.getNodeFromTail(1)
    for i in reversed(range(inner.getNumChildren())):
        if inner.getChild(i).getName() == MUTE:
            inner.removeChild(i)
    if not on:
        return True
    for i in reversed(range(inner.getNumChildren())):
        name = inner.getChild(i).getTypeId().getName()
        if name in ("SoBrepFaceSet", "SoBrepEdgeSet"):
            m = coin.SoMaterial()
            m.setName(MUTE)
            m.transparency.setValue(1.0)
            inner.insertChild(m, i)
    return True


def mute(plane, on=True, dark=False):
    ""

    if is_datum(plane):
        try:
            return _mute_datum(plane, on)
        except Exception as _fw_err:
            _fw_log("planes.py:mute-datum", _fw_err)
            return False
    try:
        from pivy import coin
        sel, j = _holder(plane)
    except Exception:
        return False
    if sel is None:
        return False
    key = (plane.Document.Name, plane.Name)
    current = sel.getChild(j)
    if on:
        node = _read(_local(plane, dark))
        if node is None:
            return False
        node.setName(MUTE)
        if current.getName() != MUTE:
            # pivy's wrapper holds no reference: without ref() FreeCAD's node is freed as soon as
            # it leaves the scene, and giving it back crashed FreeCAD (hiding a shown plane)
            current.ref()
            _kept[key] = current
        sel.replaceChild(j, node)
    elif current.getName() == MUTE and key in _kept:
        kept = _kept.pop(key)
        sel.replaceChild(j, kept)
        kept.unref()
    return True


def _read(text):
    """The Inventor text as a node. SoInput keeps only a pointer to the text: the text must
    outlive the read (a stream handed back on its own read freed memory and crashed FreeCAD
    later, on hiding a plane)."""
    from pivy import coin
    stream = coin.SoInput()
    stream.setBuffer(text)
    node = coin.SoDB.readAll(stream)
    del stream
    return node


def _view(doc_name):
    try:
        view = Gui.getDocument(doc_name).ActiveView
    except Exception:
        return None
    return view if hasattr(view, "setAnnotation") else None


class _Observer:
    def __init__(self, owner):
        self.owner = owner

    def addSelection(self, doc, obj, sub, pnt):
        self.owner.soon()

    def removeSelection(self, doc, obj, sub):
        self.owner.soon()

    def setSelection(self, doc):
        self.owner.soon()

    def clearSelection(self, doc):
        self.owner.soon()


class _DocObserver:
    """Planes shown or hidden (their Visibility, or their origin's)."""

    def __init__(self, owner):
        self.owner = owner

    def slotChangedObject(self, obj, prop):
        if prop == "Visibility" and getattr(obj, "TypeId", "") in (PLANE, ORIGIN):
            self.owner.soon()

    def slotCreatedObject(self, obj):
        if getattr(obj, "TypeId", "") == PLANE:
            self.owner.soon()

    def slotDeletedDocument(self, doc):
        self.owner.forget(doc.Name)


class PickedPlane(QtCore.QObject):
    """Draws the picked origin planes in each document's 3D view while they are picked."""

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.shown = {}            # document name -> names of the planes drawn there
        self._text = {}            # document name -> the drawing last set there
        self.draws = 0             # for checks
        self.error = None          # the last failure, for checks
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.refresh)
        self.muted = {}            # document name -> names of the planes whose FreeCAD drawing is hidden
        self._observer = _Observer(self)
        Gui.Selection.addObserver(self._observer)
        self._doc_observer = _DocObserver(self)
        App.addDocumentObserver(self._doc_observer)
        try:
            from . import style
            style.signals.theme_changed.connect(self.soon)
        except Exception as _fw_err:
            _fw_log("planes.py:380", _fw_err)
        try:
            from . import originaxes
            originaxes.start()
        except Exception as _fw_err:
            _fw_log("planes.py:385", _fw_err)
        try:
            from . import datumsize
            datumsize.start()
        except Exception as _fw_err:
            _fw_log("planes.py:datumsize", _fw_err)
        self.soon()

    def soon(self):
        self._timer.start()

    def refresh(self):
        if not (self.shell.enabled and enabled()):
            self.clear()
            return
        docs = {}
        try:
            for doc in App.listDocuments().values():
                shown = shown_planes(doc.Name)
                picked = [p for p in picked_planes(doc.Name) if p in shown or not drawn_by_freecad(p)]
                docs[doc.Name] = (picked, shown)
        except Exception as error:
            self.error = "finding: %s" % error
            docs = {}
        for name in list(self.shown):
            if not any(docs.get(name, ((), ()))):
                self._hide(name)
        for name, (picked, shown) in docs.items():
            self._mute(name, shown)
            if any(is_datum(p) or _origins(p) for p in picked):
                try:
                    from . import planehandles
                    planehandles.watch(name)
                except Exception as _fw_err:
                    _fw_log("planes.py:handles", _fw_err)
            if picked or shown:
                self._show(name, picked, shown)

    def _mute(self, doc_name, shown):
        was = self.muted.get(doc_name, set())
        now = set(p.Name for p in shown)
        doc = App.listDocuments().get(doc_name)
        dark = _dark()
        for name in now:
            mute(doc.getObject(name), True, dark)
        for name in was - now:
            obj = doc.getObject(name) if doc is not None else None
            if obj is not None:
                mute(obj, False)
        self.muted[doc_name] = now

    def forget(self, doc_name):
        for key in [k for k in _kept if k[0] == doc_name]:
            try:
                _kept.pop(key).unref()
            except Exception as _fw_err:
                _fw_log("planes.py:430", _fw_err)
        self.muted.pop(doc_name, None)
        self.shown.pop(doc_name, None)
        self._text.pop(doc_name, None)

    def _show(self, doc_name, planes, shown=()):
        names = [p.Name for p in planes] + ["+" + p.Name for p in shown]
        view = _view(doc_name)
        if view is None:
            return
        try:
            text = inventor(planes, shown)
        except Exception as error:
            self.error = "drawing: %s" % error
            App.Console.PrintLog("FreeCAD: picked plane: %s\n" % error)
            return
        if self._text.get(doc_name) == text and self.shown.get(doc_name) == names:
            return                 # as drawn already
        if doc_name in self._text:      # only one we drew (a fresh view has none: removing it logged an error)
            try:
                view.removeAnnotation(ANNOTATION)
            except Exception as _fw_err:
                _fw_log("planes.py:451", _fw_err)
        try:
            view.setAnnotation(ANNOTATION, text)
        except Exception as error:
            self.error = "setting: %s" % error
            App.Console.PrintLog("FreeCAD: picked plane: %s\n" % error)
            self._text.pop(doc_name, None)
            return
        self.shown[doc_name] = names
        self._text[doc_name] = text
        self.draws += 1

    def _hide(self, doc_name):
        view = _view(doc_name)
        if view is not None and doc_name in self._text:     # nothing to take off when none was drawn
            try:
                view.removeAnnotation(ANNOTATION)
            except Exception as _fw_err:
                _fw_log("planes.py:469", _fw_err)
        self.shown.pop(doc_name, None)
        self._text.pop(doc_name, None)

    def clear(self):
        for name in list(self.shown):
            self._hide(name)
        for doc_name, names in list(self.muted.items()):
            doc = App.listDocuments().get(doc_name)
            for name in names:
                obj = doc.getObject(name) if doc is not None else None
                if obj is not None:
                    mute(obj, False)
        self.muted = {}

    def remove(self):
        self._timer.stop()
        try:
            from . import originaxes
            originaxes.stop()
        except Exception as _fw_err:
            _fw_log("planes.py:490", _fw_err)
        try:
            Gui.Selection.removeObserver(self._observer)
        except Exception as _fw_err:
            _fw_log("planes.py:494", _fw_err)
        try:
            App.removeDocumentObserver(self._doc_observer)
        except Exception as _fw_err:
            _fw_log("planes.py:498", _fw_err)
        self.clear()
