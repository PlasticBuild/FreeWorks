# SPDX-License-Identifier: LGPL-2.1-or-later
""













_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeWorks %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCAD as App
from PySide import QtCore

TYPES = ("PartDesign::Plane", "Part::DatumPlane")
MARGIN = 0.12          # the plane reaches this much past the model, in parts of the model's size
LEAST_MARGIN = 1.0     # mm
stats = {"sized": 0}
_state = {"observer": None, "timer": None, "docs": set()}


def _owner_shapes(plane):
    """The body's shape (the plane's own body), else every shown solid in the document."""
    for parent in getattr(plane, "InList", []):
        if parent.TypeId == "PartDesign::Body":
            shape = getattr(parent, "Shape", None)
            if shape is not None and not shape.isNull() and shape.BoundBox.isValid():
                return [shape]
            return []
    out = []
    for obj in plane.Document.Objects:
        if obj is plane or obj.TypeId in TYPES:
            continue
        if obj.TypeId == "PartDesign::Body" or (obj.TypeId.startswith("Part::") and not obj.TypeId.startswith("Part::Datum")):
            shape = getattr(obj, "Shape", None)
            vo = getattr(obj, "ViewObject", None)
            if shape is not None and not shape.isNull() and shape.BoundBox.isValid() and shape.Volume > 0 \
                    and (vo is None or vo.Visibility):
                out.append(shape)
    return out


def square(plane):
    """(umin, umax, vmin, vmax) of the square to draw in the plane's own x/y, or None (FreeCAD's size)."""
    if getattr(plane, "ResizeMode", "Automatic") != "Automatic":
        return None
    shapes = _owner_shapes(plane)
    if not shapes:
        return None
    inv = plane.getGlobalPlacement().inverse()
    us, vs = [], []
    for shape in shapes:
        bb = shape.BoundBox
        for x in (bb.XMin, bb.XMax):
            for y in (bb.YMin, bb.YMax):
                for z in (bb.ZMin, bb.ZMax):
                    p = inv.multVec(App.Vector(x, y, z))
                    us.append(p.x)
                    vs.append(p.y)
    umin, umax, vmin, vmax = min(us), max(us), min(vs), max(vs)
    size = max(umax - umin, vmax - vmin)
    if size < 1e-6:
        return None
    m = max(MARGIN * size, LEAST_MARGIN)
    # a model seen edge-on along one direction still gets a square, not a sliver
    du, dv = umax - umin, vmax - vmin
    if du < 0.2 * size:
        c = (umin + umax) / 2.0
        umin, umax = c - 0.1 * size, c + 0.1 * size
    if dv < 0.2 * size:
        c = (vmin + vmax) / 2.0
        vmin, vmax = c - 0.1 * size, c + 0.1 * size
    return umin - m, umax + m, vmin - m, vmax + m


def _coords(plane):
    vo = getattr(plane, "ViewObject", None)
    if vo is None:
        return None
    from pivy import coin
    sa = coin.SoSearchAction()
    sa.setType(coin.SoCoordinate3.getClassTypeId())
    sa.setInterest(coin.SoSearchAction.FIRST)
    sa.apply(vo.RootNode)
    path = sa.getPath()
    if path is None:
        return None
    node = path.getTail()
    return node if node.point.getNum() == 4 else None


def size(plane):
    """Sizes one plane's square. True when it was set."""
    try:
        sq = square(plane)
        node = _coords(plane) if sq is not None else None
        if node is None:
            return False
        umin, umax, vmin, vmax = sq
        want = [(umax, vmax, 0.0), (umin, vmax, 0.0), (umin, vmin, 0.0), (umax, vmin, 0.0)]  # FreeCAD's order
        have = [tuple(node.point[i].getValue()) for i in range(4)]
        if all(abs(a - b) < 1e-6 for p, q in zip(have, want) for a, b in zip(p, q)):
            return True
        node.point.setValues(0, 4, want)
        stats["sized"] += 1
        return True
    except Exception as error:
        _fw_log("datumsize.py:size", error)
        return False


def size_all(doc=None):
    docs = [doc] if doc is not None else list(App.listDocuments().values())
    for d in docs:
        try:
            for obj in d.Objects:
                if obj.TypeId in TYPES:
                    size(obj)
        except Exception as error:
            _fw_log("datumsize.py:all", error)


def _flush():
    names, _state["docs"] = _state["docs"], set()
    for name in names:
        doc = App.listDocuments().get(name)
        if doc is not None:
            size_all(doc)


def soon(doc):
    _state["docs"].add(doc.Name)
    _state["timer"].start()


class _Observer:
    def slotRecomputedDocument(self, doc):
        soon(doc)

    def slotFinishRestoreDocument(self, doc):
        soon(doc)

    def slotCreatedObject(self, obj):
        if getattr(obj, "TypeId", "") in TYPES:
            soon(obj.Document)

    def slotChangedObject(self, obj, prop):
        # FreeCAD redraws the square at its own size when the plane moves or resizes
        if prop in ("Placement", "Length", "Width", "ResizeMode", "Visibility") and getattr(obj, "TypeId", "") in TYPES:
            soon(obj.Document)


def start():
    if _state["observer"] is not None:
        return
    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.setInterval(0)
    timer.timeout.connect(_flush)
    _state["timer"] = timer
    _state["observer"] = _Observer()
    App.addDocumentObserver(_state["observer"])
    size_all()
