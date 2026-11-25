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
from PySide import QtCore, QtGui, QtWidgets

COLOUR = QtGui.QColor(255, 140, 0)
ITEMS = []                                # the overlay items drawn now
SHOWN = []                                # (dimension name, sub-element) highlighted now (checks)
_OBS = []
_PENDING = [False]


def enabled(doc):
    try:
        from . import drawdocprops as DP
        if DP.stored(doc):
            return bool(DP.prop(doc, "highlight_refs"))
    except Exception as _fw_err:
        _fw_log("drawrefhl.py:36", _fw_err)
    return True


def clear():
    for it in ITEMS:
        try:
            sc = it.scene()
            if sc is not None:
                sc.removeItem(it)
        except RuntimeError as _fw_err:
            _fw_log("drawrefhl.py:47", _fw_err)
    ITEMS[:] = []
    SHOWN[:] = []


def _page_of(o):
    return next((p for p in o.InList if p.TypeId == "TechDraw::DrawPage"), None)


def _scene(page):
    try:
        import TechDrawGui
        return TechDrawGui.getSceneForPage(page)
    except Exception:
        return None


def _to_scene(view, g):
    from . import drawings as D
    from . import drawviews as DV
    x0, y0 = D.view_position(view)
    k = DV.view_scale(view)
    return D.to_scene(x0 + g[0] * k, y0 + g[1] * k)


def _path(view, sub):
    """The scene path of a view's EdgeN / VertexN (view geometry), or None."""
    path = QtGui.QPainterPath()
    try:
        if sub.startswith("Edge"):
            e = view.getEdgeByIndex(int(sub[4:]))
            pts = e.discretize(48)
            for n, q in enumerate(pts):
                s = _to_scene(view, (q.x, q.y))
                path.moveTo(s) if n == 0 else path.lineTo(s)
        elif sub.startswith("Vertex"):
            v = view.getVertexByIndex(int(sub[6:]))
            path.addEllipse(_to_scene(view, (v.X, v.Y)), 8, 8)
        else:
            return None
    except Exception:
        return None
    return path


def highlight(dims):
    """The referenced edges and points of dims drawn in the highlight colour. Returns how many."""
    clear()
    n = 0
    for d in dims:
        page = _page_of(d)
        if page is None or not enabled(d.Document):
            continue
        sc = _scene(page)
        if sc is None:
            continue
        for view, subs in list(getattr(d, "References2D", []) or []):
            if view is None or not view.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            for sub in subs:
                p = _path(view, sub)
                if p is None:
                    continue
                pen = QtGui.QPen(COLOUR)
                pen.setWidthF(3)
                pen.setCosmetic(True)
                it = QtWidgets.QGraphicsPathItem(p)
                it.setPen(pen)
                it.setZValue(1e6)
                it.setAcceptedMouseButtons(QtCore.Qt.NoButton)
                sc.addItem(it)
                ITEMS.append(it)
                SHOWN.append((d.Name, sub))
                n += 1
    return n


def refresh():
    _PENDING[0] = False
    dims = [o for o in Gui.Selection.getSelection() if o.TypeId == "TechDraw::DrawViewDimension"]
    if dims:
        highlight(dims)
    else:
        clear()


def _later(*_):
    if _PENDING[0]:
        return
    _PENDING[0] = True
    QtCore.QTimer.singleShot(0, refresh)


class _Observer:
    def addSelection(self, *a):
        _later()

    def removeSelection(self, *a):
        _later()

    def setSelection(self, *a):
        _later()

    def clearSelection(self, *a):
        _later()


class _Moved:
    """A view of a highlighted dimension moved, turned, scaled or was drawn again: the highlight follows it."""
    def slotChangedObject(self, obj, prop):
        if ITEMS and prop in ("X", "Y", "Rotation", "Scale") and getattr(obj, "isDerivedFrom", None) and \
                obj.isDerivedFrom("TechDraw::DrawView"):
            _later()

    def slotRecomputedObject(self, obj):
        if ITEMS and getattr(obj, "isDerivedFrom", None) and obj.isDerivedFrom("TechDraw::DrawViewPart"):
            _later()


def install():
    if _OBS:
        return
    o = _Observer()
    Gui.Selection.addObserver(o)
    _OBS.append(o)
    m = _Moved()
    App.addDocumentObserver(m)
    _OBS.append(m)
