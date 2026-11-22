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
from PySide import QtCore, QtGui, QtWidgets

DIM_LINE, EXT_LINE = "SWHideDimLine", "SWHideExtLine"
BREAK, BREAK_GAP = "SWBreakLines", "SWBreakGap"
_RAW = {}                  # dimension name -> (the sub-paths TechDraw drew, the signature of the path we set)
PATH_TYPE = 65553          # TechDraw's QGIDimLines
ARROW_TYPE = 65545         # QGIArrow
_TIMER = []                # the slow fallback timer (runs while some dimension hides a line)
_BUSY = [False]
_PENDING = [False]


def hidden(dim, which):
    return getattr(dim, which, "") == "1"


def set_hidden(dim, which, on):
    if which not in dim.PropertiesList:
        dim.addProperty("App::PropertyString", which, "FreeCAD",
                        "Hide Dimension Line" if which == DIM_LINE else "Hide Extension Line")
    setattr(dim, which, "1" if on else "")


def toggle(dim, which):
    doc = dim.Document
    doc.openTransaction("Show Dimension Line" if which == DIM_LINE and hidden(dim, which) else
                        "Hide Dimension Line" if which == DIM_LINE else
                        "Show Extension Line" if hidden(dim, which) else "Hide Extension Line")
    try:
        set_hidden(dim, which, not hidden(dim, which))
    finally:
        doc.commitTransaction()
    try:
        dim.ViewObject.Visibility = dim.ViewObject.Visibility
        dim.touch()
    except Exception as _fw_err:
        _fw_log("drawdimlines.py:72", _fw_err)
    doc.recompute()
    apply_all()


# --------------------------------------------------------------------------- the drawn path
def _segments(path):
    """The path's sub-paths: [[(type, x, y), ...]] (each starts at a moveTo)."""
    out = []
    for i in range(path.elementCount()):
        e = path.elementAt(i)
        t = int(getattr(e.type, "value", e.type))
        if t == 0 or not out:
            out.append([])
        out[-1].append((t, e.x, e.y))
    return out


def _is_dim_line(seg, tips):
    """A dimension line sub-path: it bends (an angle's arc) or it reaches an arrow tip at both... one end."""
    if any(t not in (0, 1) for t, _x, _y in seg):
        return True                       # curve: an angle's or a radius' arc
    ends = [(seg[0][1], seg[0][2]), (seg[-1][1], seg[-1][2])]
    return any(math.hypot(ex - ax, ey - ay) < 1.5 for ex, ey in ends for ax, ay in tips)


def filter_path(path, tips, hide_dim, hide_ext):
    """The path without the hidden sub-paths, or None when nothing is to go."""
    segs = _segments(path)
    keep, gone = [], False
    for seg in segs:
        dimline = _is_dim_line(seg, tips)
        if (dimline and hide_dim) or (not dimline and hide_ext):
            gone = True
            continue
        keep.append(seg)
    if not gone:
        return None
    p = QtGui.QPainterPath()
    for seg in keep:
        i = 0
        while i < len(seg):
            t, x, y = seg[i]
            if t == 0:
                p.moveTo(x, y)
            elif t == 1:
                p.lineTo(x, y)
            elif t == 2 and i + 2 < len(seg):
                p.cubicTo(x, y, seg[i + 1][1], seg[i + 1][2], seg[i + 2][1], seg[i + 2][2])
                i += 2
            i += 1
    return p


def _scenes():
    out = []
    for gv in Gui.getMainWindow().findChildren(QtWidgets.QGraphicsView):
        try:
            sc = gv.scene()
        except Exception:
            continue
        if sc is not None and sc not in out:
            out.append(sc)
    return out


def _dims(doc):
    return [o for o in doc.Objects if o.TypeId == "TechDraw::DrawViewDimension"
            and (hidden(o, DIM_LINE) or hidden(o, EXT_LINE) or breaks(o))]


def breaks(dim):
    return getattr(dim, BREAK, "") == "1"


def break_gap(dim):
    """The dimension's break gap (mm): its own, else Document Properties' (Break dimension/extension lines)."""
    try:
        own = float(getattr(dim, BREAK_GAP, "") or "nan")
        if own == own:
            return own
    except ValueError as _fw_err:
        _fw_log("drawdimlines.py:154", _fw_err)
    try:
        from . import drawdocprops as DDP
        return float(DDP.prop(dim.Document, "dim_break_gap") or 1.0)
    except Exception:
        return 1.0


def _arrows_only(dim):
    try:
        from . import drawdocprops as DDP
        return bool(DDP.prop(dim.Document, "dim_break_arrows"))
    except Exception:
        return False


def set_break(dim, on, gap=None):
    """Break Lines on a dimension; gap None keeps it, "" = the document's gap, else mm."""
    if BREAK not in dim.PropertiesList:
        dim.addProperty("App::PropertyString", BREAK, "FreeCAD", "Break Lines (gaps where other lines cross)")
    if BREAK_GAP not in dim.PropertiesList:
        dim.addProperty("App::PropertyString", BREAK_GAP, "FreeCAD", "Break Lines gap (mm), empty = document")
    setattr(dim, BREAK, "1" if on else "")
    if gap is not None:
        setattr(dim, BREAK_GAP, "" if gap == "" else "%g" % float(gap))
    _later()


def _signature(path):
    n = path.elementCount()
    if not n:
        return (0,)
    a, b = path.elementAt(0), path.elementAt(n - 1)
    return (n, round(a.x, 3), round(a.y, 3), round(b.x, 3), round(b.y, 3))


def _build(segs):
    p = QtGui.QPainterPath()
    for seg in segs:
        i = 0
        while i < len(seg):
            t, x, y = seg[i]
            if t == 0:
                p.moveTo(x, y)
            elif t == 1:
                p.lineTo(x, y)
            elif t == 2 and i + 2 < len(seg):
                p.cubicTo(x, y, seg[i + 1][1], seg[i + 1][2], seg[i + 2][1], seg[i + 2][2])
                i += 2
            i += 1
    return p


def _raw(name, item):
    """The sub-paths TechDraw drew for this dimension's line item (ours replaced: the ones we kept)."""
    path = item.path()
    keep = _RAW.get(name)
    if keep is not None and keep[1] == _signature(path):
        return keep[0]
    segs = _segments(path)
    _RAW[name] = (segs, None)
    return segs


def _lines(segs):
    """The straight pieces of sub-paths: [((x0, y0), (x1, y1))]."""
    out = []
    for seg in segs:
        if any(t not in (0, 1) for t, _x, _y in seg):
            continue
        for a, b in zip(seg, seg[1:]):
            out.append(((a[1], a[2]), (b[1], b[2])))
    return out


def break_subpaths(segs, cutters, gap):
    """The sub-paths with gaps where cutters cross their straight pieces (curves kept whole)."""
    from . import dimbreak
    out = []
    for seg in segs:
        if any(t not in (0, 1) for t, _x, _y in seg) or len(seg) < 2:
            out.append(seg)
            continue
        pieces = dimbreak.break_segments([((a[1], a[2]), (b[1], b[2])) for a, b in zip(seg, seg[1:])],
                                         cutters, gap)
        cur = None
        for (x0, y0), (x1, y1) in pieces:
            if cur is not None and abs(cur[-1][1] - x0) < 1e-9 and abs(cur[-1][2] - y0) < 1e-9:
                cur.append((1, x1, y1))       # the next piece of an unbroken polyline
            else:
                cur = [(0, x0, y0), (1, x1, y1)]
                out.append(cur)
    return out


TEXT_ITEMS = (8, 9)        # QGraphicsTextItem, QGraphicsSimpleTextItem (inside TechDraw's dimension label)
LABEL_TYPE = 65551         # TechDraw's QGIDatumLabel (the dimension text; its text sits in a group)


def _has_text(c, depth=0):
    if c.type() in TEXT_ITEMS:
        return True
    if depth > 3:
        return False
    return any(_has_text(k, depth + 1) for k in (c.childItems() or []))


def _text_rects(item):
    """A dimension item's text boxes in scene coordinates: its label (the child that holds the text)."""
    out = []
    for c in item.childItems() or []:
        if c.type() in (PATH_TYPE, ARROW_TYPE) or not c.isVisible():
            continue
        if c.type() == LABEL_TYPE or _has_text(c):
            r = c.mapRectToScene(c.childrenBoundingRect() | c.boundingRect())
            if r.width() > 0 and r.height() > 0:
                out.append(r)
    return out


def _clip_out(segs, rects):
    """The straight sub-paths with the parts inside rects (x0, y0, x1, y1) taken out (Liang-Barsky)."""
    if not rects:
        return segs
    out = []
    for seg in segs:
        if any(t not in (0, 1) for t, _x, _y in seg) or len(seg) < 2:
            out.append(seg)
            continue
        pieces = [((a[1], a[2]), (b[1], b[2])) for a, b in zip(seg, seg[1:])]
        for r in rects:
            nxt = []
            for p0, p1 in pieces:
                nxt.extend(_minus_rect(p0, p1, r))
            pieces = nxt
        cur = None
        for (x0, y0), (x1, y1) in pieces:
            if cur is not None and abs(cur[-1][1] - x0) < 1e-9 and abs(cur[-1][2] - y0) < 1e-9:
                cur.append((1, x1, y1))
            else:
                cur = [(0, x0, y0), (1, x1, y1)]
                out.append(cur)
    return out


def _minus_rect(p0, p1, r):
    x0, y0, x1, y1 = r
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, p0[0] - x0), (dx, x1 - p0[0]), (-dy, p0[1] - y0), (dy, y1 - p0[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return [(p0, p1)]           # parallel and outside
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    if t0 >= t1:
        return [(p0, p1)]                   # misses the box
    at = lambda t: (p0[0] + dx * t, p0[1] + dy * t)
    out = []
    if t0 > 1e-9:
        out.append((p0, at(t0)))
    if t1 < 1 - 1e-9:
        out.append((at(t1), p1))
    return out


def apply_all():
    """Takes the hidden lines out of every drawn dimension that hides some. Returns how many paths changed."""
    if _BUSY[0]:
        return 0
    _BUSY[0] = True
    n = 0
    try:
        want, alldims = {}, set()
        for doc in App.listDocuments().values():
            for o in doc.Objects:
                if o.TypeId == "TechDraw::DrawViewDimension":
                    alldims.add(o.Name)
            for o in _dims(doc):
                want[o.Name] = (hidden(o, DIM_LINE), hidden(o, EXT_LINE), breaks(o),
                                break_gap(o) if breaks(o) else 0.0, _arrows_only(o) if breaks(o) else False)
        _keep_timer(bool(want))
        if not want:
            return 0
        for sc in _scenes():
            items = [it for it in sc.items() if it.data(1) in alldims]
            cut_lines, cut_arrows = {}, {}           # dimension name -> its lines / arrowheads, in scene mm*10
            cut_text = {}                            # dimension name -> its text boxes (scene)
            if any(w[2] for w in want.values()):
                for it in items:
                    name = it.data(1)
                    try:
                        cut_text[name] = _text_rects(it)
                    except Exception as _fw_err:
                        _fw_log("drawdimlines.py:352", _fw_err)
                    for c in it.childItems() or []:
                        if c.type() == PATH_TYPE:
                            cut_lines.setdefault(name, []).extend(
                                ((c.mapToScene(QtCore.QPointF(*a)).toTuple(), c.mapToScene(QtCore.QPointF(*b)).toTuple())
                                 for a, b in _lines(_raw(name, c))))
                        elif c.type() == ARROW_TYPE and c.isVisible():
                            r = c.mapRectToScene(c.boundingRect())
                            cut_arrows.setdefault(name, []).extend(
                                [(r.topLeft().toTuple(), r.bottomRight().toTuple()),
                                 (r.topRight().toTuple(), r.bottomLeft().toTuple())])
            for it in items:
                name = it.data(1)
                if name not in want or it.childItems() is None:
                    continue
                hd, he, br, gap, arrows_only = want[name]
                kids = it.childItems()
                arrows = [c for c in kids if c.type() == ARROW_TYPE]
                tips = [(c.pos().x(), c.pos().y()) for c in arrows]
                for c in kids:
                    if c.type() != PATH_TYPE:
                        continue
                    if not br:
                        p = filter_path(c.path(), tips, hd, he)
                        if p is not None:
                            c.setPath(p)
                            n += 1
                        continue
                    raw = _raw(name, c)
                    segs = [seg for seg in raw if not ((_is_dim_line(seg, tips) and hd) or
                                                      (not _is_dim_line(seg, tips) and he))]
                    src = cut_arrows if arrows_only else cut_lines
                    cutters = []
                    for other, lines in src.items():
                        if other == name:
                            continue
                        for a, b in lines:
                            cutters.append((c.mapFromScene(QtCore.QPointF(*a)).toTuple(),
                                            c.mapFromScene(QtCore.QPointF(*b)).toTuple()))
                    broken = break_subpaths([list(x) for x in segs], cutters, gap * 10.0)
                    if not arrows_only:
                        rects = []
                        for other, boxes in cut_text.items():
                            if other == name:
                                continue
                            for b in boxes:
                                q = c.mapFromScene(b).boundingRect()
                                g = gap * 10.0 / 2.0
                                rects.append((q.left() - g, q.top() - g, q.right() + g, q.bottom() + g))
                        broken = _clip_out(broken, rects)
                    new = _build(broken)
                    if _signature(new) != _signature(c.path()) or new.elementCount() != c.path().elementCount():
                        c.setPath(new)
                        n += 1
                    _RAW[name] = (raw, _signature(c.path()))
                for c in arrows:
                    if c.isVisible() == hd:
                        c.setVisible(not hd)
    finally:
        _BUSY[0] = False
    return n


def _later(*_):
    if _PENDING[0] or _BUSY[0]:
        return
    _PENDING[0] = True

    def go():
        _PENDING[0] = False
        try:
            apply_all()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: hidden dimension lines: %s\n" % error)
    QtCore.QTimer.singleShot(0, go)


def _keep_timer(on):
    """The fallback for redraws no document event tells of; stopped when no dimension hides a line."""
    if not _TIMER:
        if not on:
            return
        t = QtCore.QTimer()
        t.setInterval(1500)
        t.timeout.connect(_later)
        _TIMER.append(t)
    t = _TIMER[0]
    if on and not t.isActive():
        t.start()
    elif not on and t.isActive():
        t.stop()


class _SelObserver:
    """Selecting a dimension makes TechDraw draw it again."""

    def addSelection(self, doc, obj, sub, pnt):
        self._go(doc, obj)

    def removeSelection(self, doc, obj, sub):
        self._go(doc, obj)

    def clearSelection(self, doc):
        if _TIMER and _TIMER[0].isActive():
            _later()

    def _go(self, doc, obj):
        try:
            o = App.getDocument(doc).getObject(obj)
            if o is not None and o.TypeId == "TechDraw::DrawViewDimension" and (hidden(o, DIM_LINE) or hidden(o, EXT_LINE) or breaks(o)):
                _later()
        except Exception as _fw_err:
            _fw_log("drawdimlines.py:464", _fw_err)


# --------------------------------------------------------------------------- Insert Model Items
def sketch_hides_dim_line(sk, index):
    """The sketch's Hide Dimension Line on constraint index (the right-click thread's FWDimDisplay flag)."""
    try:
        c = sk.Constraints[index]
        key = "%s:HideDimLine" % (c.Name or "#%d" % index)
        return key in list(getattr(sk, "FWDimDisplay", []) or [])
    except Exception as _fw_err:
        _fw_log("drawdimlines.py:476", _fw_err)
        return False


# --------------------------------------------------------------------------- the right-click items
def text_box(dim):
    """(half width, half height) in mm of the dimension's text round its place (drawmenu._place)."""
    try:
        fs = float(dim.ViewObject.Fontsize.Value if hasattr(dim.ViewObject.Fontsize, "Value")
                   else dim.ViewObject.Fontsize)
    except Exception:
        fs = 3.5
    try:
        from . import drawextras
        n = len(drawextras.dim_value_text(dim) or "") or 4
    except Exception:
        n = 4
    return 0.32 * fs * n + 0.3, 0.55 * fs


def on_line(drawmenu, dim):
    ""


    try:
        gv, pos = drawmenu._LAST.get("view"), drawmenu._LAST.get("pos")
        if gv is None or pos is None:
            return False
        x, y = drawmenu.page_point(gv, pos)
        x0, y0 = drawmenu._place(dim)
        hw, hh = text_box(dim)
        return not (abs(x - x0) <= hw and abs(y - y0) <= hh)
    except Exception:
        return False


def _wrap_menu():
    try:
        from . import drawmenu, rcmenus
    except Exception:
        return False
    if getattr(drawmenu, "_fw_dimlines", False):
        return True
    items0 = drawmenu.dimension_items

    def dimension_items(dim):
        out = items0(dim)
        if not on_line(drawmenu, dim):
            return out
        try:
            extra = [rcmenus.action("HideDimensionLine",
                                    "Show Dimension Line" if hidden(dim, DIM_LINE) else "Hide Dimension Line",
                                    lambda: toggle(dim, DIM_LINE)),
                     rcmenus.action("HideExtensionLine",
                                    "Show Extension Line" if hidden(dim, EXT_LINE) else "Hide Extension Line",
                                    lambda: toggle(dim, EXT_LINE))]
            at = next((i + 1 for i, it in enumerate(out) if getattr(it, "key", "") == "Hide"), None)
            if at is None:
                out = out + extra
            else:
                out = out[:at] + extra + out[at:]
        except Exception as error:
            App.Console.PrintLog("FreeCAD: dimension menu: %s\n" % error)
        return out
    drawmenu.dimension_items = dimension_items
    drawmenu._fw_dimlines = True
    return True


class _Observer:
    """A drawing dimension made or changed: the hidden lines go again (and new drawing scenes get hooked)."""

    def slotCreatedObject(self, obj):
        self._any(obj)

    def slotChangedObject(self, obj, prop):
        self._any(obj)

    def slotRecomputedObject(self, obj):
        try:
            if obj.TypeId == "TechDraw::DrawViewDimension" and (hidden(obj, DIM_LINE) or hidden(obj, EXT_LINE)
                                                                or breaks(obj)):
                _later()
        except Exception as _fw_err:
            _fw_log("drawdimlines.py:558", _fw_err)

    def slotRecomputedDocument(self, doc):
        try:
            if _dims(doc):
                _later()
        except Exception as _fw_err:
            _fw_log("drawdimlines.py:565", _fw_err)

    def _any(self, obj):
        try:
            if obj.TypeId in ("TechDraw::DrawViewDimension", "TechDraw::DrawPage"):
                _later()
        except Exception as _fw_err:
            _fw_log("drawdimlines.py:572", _fw_err)


_OBSERVER = []


def install():
    _wrap_menu()
    if not _OBSERVER:
        _OBSERVER.append(_Observer())
        App.addDocumentObserver(_OBSERVER[0])
        _OBSERVER.append(_SelObserver())
        try:
            Gui.Selection.addObserver(_OBSERVER[1])
        except Exception as _fw_err:
            _fw_log("drawdimlines.py:587", _fw_err)
