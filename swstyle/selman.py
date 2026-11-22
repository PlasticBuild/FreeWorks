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

from . import pmtakeover

Qt = QtCore.Qt
NAME = "SWStyle_SelectionManager"
PAGES = {"Sweep", "Cut-Sweep", "Loft", "Cut-Loft", "Boundary Boss/Base", "Boundary Cut",
         "Surface-Sweep", "Surface-Loft", "Boundary-Surface", "Surface-Extrude", "Surface-Revolve"}
MODES = (("closed", "Select Closed Loop", "A click on an edge takes the closed loop it is on"),
         ("open", "Select Open Loop", "A click on an edge takes the open chain of edges it is on"),
         ("group", "Select Group", "Each click adds an edge to the group"),
         ("region", "Select Region", "A click on a face takes the region it bounds"),
         ("standard", "Standard Selection", "Picks go to the page as usual"))
TANGENT = math.radians(5.0)
_current = [None]


# --------------------------------------------------------------------------- where it applies
def _header_title():
    from . import propertymanager as pm
    for dock in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget):
        view = pm._view(dock)
        if view is None or not view.isVisible():
            continue
        header = view.findChild(QtWidgets.QWidget, pm.HEADER)
        if header is not None and header.isVisible():
            try:
                return header.title.text()
            except Exception:
                return None
    return None


def available():
    """True while a page that takes profiles, paths or guides from the model is open."""
    try:
        return bool(Gui.Control.activeDialog()) and _header_title() in PAGES
    except Exception:
        return False


def is_open():
    bar = _current[0]
    return bar is not None and _alive(bar) and bar.isVisible()


def _alive(widget):
    try:
        return widget is not None and widget.isVisible() is not None
    except RuntimeError:
        return False


# --------------------------------------------------------------------------- the loops
def _same(a, b):
    return (a - b).Length < 1e-6


def _tangent_at(edge, point):
    """The edge's unit tangent at its end nearest the point, pointing away from the point."""
    try:
        p0, p1 = edge.firstVertex().Point, edge.lastVertex().Point
        if _same(point, p0):
            t = edge.tangentAt(edge.FirstParameter)
        else:
            t = edge.tangentAt(edge.LastParameter).negative()
        return t.normalize() if t.Length > 1e-9 else None
    except Exception:
        return None


def _other_end(edge, point):
    p0, p1 = edge.firstVertex().Point, edge.lastVertex().Point
    return p1 if _same(point, p0) else p0


def _next_edge(shape, index, point, taken, propagate):
    """The edge continuing from point (the end of edge index): the tangent one while propagate is
    in, else the only other edge there."""
    here = []
    for i, e in enumerate(shape.Edges, 1):
        if i == index or i in taken:
            continue
        try:
            if _same(e.firstVertex().Point, point) or _same(e.lastVertex().Point, point):
                here.append(i)
        except Exception:
            continue
    if not here:
        return None
    if len(here) == 1 and not propagate:
        return here[0]
    this = shape.Edges[index - 1]
    try:
        arriving = _tangent_at(this, point)
        if arriving is not None:
            arriving = arriving.negative()        # the direction we travel in
    except Exception:
        arriving = None
    best, best_angle = None, None
    for i in here:
        leaving = _tangent_at(shape.Edges[i - 1], point)
        if arriving is None or leaving is None:
            continue
        angle = arriving.getAngle(leaving)
        if best_angle is None or angle < best_angle:
            best, best_angle = i, angle
    if propagate and best is not None and best_angle <= TANGENT:
        return best
    if len(here) == 1:
        return here[0]
    if not propagate:
        return None       # Propagate off: on a solid (several edges meet here) the chain stops at the corner
    return best if (best is not None and best_angle <= TANGENT) else None


def loop_from(shape, index, propagate=True, closed=True):
    """The edges of the loop through edge index (1-based), in order; closed: stops when the walk
    returns to the start (an open chain comes back as far as it goes both ways)."""
    edge = shape.Edges[index - 1]
    start, point = edge.firstVertex().Point, edge.lastVertex().Point
    chain = [index]
    taken = {index}
    while True:
        if _same(point, start):
            return chain, True
        nxt = _next_edge(shape, chain[-1], point, taken, propagate)
        if nxt is None:
            break
        chain.append(nxt)
        taken.add(nxt)
        point = _other_end(shape.Edges[nxt - 1], point)
    if closed:
        return chain, False
    # the other way, from the start vertex
    point = start
    while True:
        nxt = _next_edge(shape, chain[0], point, taken, propagate)
        if nxt is None:
            break
        chain.insert(0, nxt)
        taken.add(nxt)
        point = _other_end(shape.Edges[nxt - 1], point)
    return chain, False


def _face_loops(shape, index):
    ""

    edge = shape.Edges[index - 1]
    out = []
    for fi, face in enumerate(shape.Faces, 1):
        try:
            if any(e.isSame(edge) for e in face.OuterWire.Edges):
                out.append((face.Area, fi, region_of(shape, fi)))
        except Exception:
            continue
    out.sort(key=lambda t: -t[0])
    return [(fi, loop) for _a, fi, loop in out]


def closed_loop(shape, index, propagate=True):
    """Select Closed Loop: the tangent chain through the edge when it closes on itself, else the
    outer loop of the (larger) face the edge bounds."""
    chain, closed = loop_from(shape, index, propagate, closed=True)
    if closed:
        return chain, True
    loops = _face_loops(shape, index)
    if loops:
        return loops[0][1], True
    return chain, False


def region_of(shape, face_index):
    """The face's outer loop as edge indexes of the shape."""
    face = shape.Faces[face_index - 1]
    out = []
    for e in face.OuterWire.OrderedEdges:
        for i, se in enumerate(shape.Edges, 1):
            if se.isSame(e):
                out.append(i)
                break
    return out


# --------------------------------------------------------------------------- the bar
class _Bar(QtWidgets.QFrame):
    ""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName(NAME)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        from .propertymanager import OK_GREEN
        self.ok = self._button("ok", "OK", self._glyph_check(OK_GREEN), False)
        self.ok.clicked.connect(commit)
        self.cancel = self._button("cancel", "Cancel", self._glyph_cross(), False)
        self.cancel.clicked.connect(close)
        self.clear = self._button("clear", "Clear All", self._glyph_clear(), False)
        self.clear.clicked.connect(lambda: _current[0] and _current[0].clear_all())
        lay.addWidget(self.ok)
        lay.addWidget(self.cancel)
        lay.addWidget(self.clear)
        lay.addSpacing(6)
        self.modes = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for key, text, tip in MODES:
            b = self._button(key, text, getattr(self, "_glyph_" + key)(), True)
            b.setToolTip("%s: %s" % (text, tip))
            group.addButton(b)
            lay.addWidget(b)
            self.modes[key] = b
        lay.addSpacing(6)
        self.propagate = self._button("propagate", "Propagate", self._glyph_propagate(), True)
        self.propagate.setToolTip("Propagate: a loop follows tangent edges on")
        self.propagate.setChecked(True)
        lay.addWidget(self.propagate)
        self.modes["closed"].setChecked(True)
        self.ok.setEnabled(False)
        self.suspended = []         # the page's own pick buttons let go while the bar is up
        self.picked = []            # [(obj, "EdgeN")] in loop order, or [(obj, "FaceN")] for a region
        self.closed = None
        self.adjustSize()
        self.move(12, 12)

    def _button(self, key, tip, icon, checkable):
        b = QtWidgets.QToolButton(self)
        b.setObjectName("SWStyle_SelMan_%s" % key)
        b.setAutoRaise(True)
        b.setCheckable(checkable)
        b.setIconSize(QtCore.QSize(18, 18))
        b.setIcon(icon)
        b.setToolTip(tip)
        return b

    # --- glyphs (drawn: the icon pack has no SelectionManager pictures)
    def _pix(self):
        from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
        pix = _hidpi.canvas(36, 36)
        pix.fill(Qt.transparent)
        p = QtGui.QPainter(pix)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        return pix, p

    def _ink(self):
        return self.palette().color(QtGui.QPalette.WindowText)

    def _pen(self, p, color=None, width=2.4):
        pen = QtGui.QPen(QtGui.QColor(color) if color else self._ink())
        pen.setWidthF(width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

    def _done(self, pix, p):
        p.end()
        pix.setDevicePixelRatio(2.0)
        return QtGui.QIcon(pix)

    def _glyph_check(self, color):
        pix, p = self._pix()
        self._pen(p, color, 3.2)
        p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(7, 19), QtCore.QPointF(15, 27), QtCore.QPointF(29, 9)]))
        return self._done(pix, p)

    def _glyph_cross(self):
        pix, p = self._pix()
        self._pen(p, "#c0392b", 3.0)
        p.drawLine(QtCore.QPointF(9, 9), QtCore.QPointF(27, 27))
        p.drawLine(QtCore.QPointF(27, 9), QtCore.QPointF(9, 27))
        return self._done(pix, p)

    def _glyph_clear(self):
        pix, p = self._pix()
        self._pen(p)
        p.drawRect(QtCore.QRectF(8, 8, 20, 20))
        self._pen(p, "#c0392b", 2.2)
        p.drawLine(QtCore.QPointF(13, 13), QtCore.QPointF(23, 23))
        p.drawLine(QtCore.QPointF(23, 13), QtCore.QPointF(13, 23))
        return self._done(pix, p)

    def _glyph_closed(self):
        pix, p = self._pix()
        self._pen(p)
        p.drawRoundedRect(QtCore.QRectF(7, 9, 22, 18), 7, 7)
        self._pen(p, "#4f8fe0", 3.0)
        p.drawArc(QtCore.QRectF(7, 9, 22, 18), 30 * 16, 120 * 16)
        return self._done(pix, p)

    def _glyph_open(self):
        pix, p = self._pix()
        self._pen(p)
        path = QtGui.QPainterPath(QtCore.QPointF(6, 27))
        path.cubicTo(QtCore.QPointF(10, 6), QtCore.QPointF(24, 30), QtCore.QPointF(30, 9))
        p.drawPath(path)
        self._pen(p, "#4f8fe0", 3.0)
        p.drawEllipse(QtCore.QPointF(6, 27), 2.2, 2.2)
        p.drawEllipse(QtCore.QPointF(30, 9), 2.2, 2.2)
        return self._done(pix, p)

    def _glyph_group(self):
        pix, p = self._pix()
        self._pen(p)
        p.drawLine(QtCore.QPointF(6, 10), QtCore.QPointF(18, 10))
        p.drawLine(QtCore.QPointF(22, 18), QtCore.QPointF(31, 26))
        self._pen(p, "#4f8fe0", 2.6)
        p.drawLine(QtCore.QPointF(8, 26), QtCore.QPointF(18, 18))
        return self._done(pix, p)

    def _glyph_region(self):
        pix, p = self._pix()
        self._pen(p)
        p.setBrush(QtGui.QColor(79, 143, 224, 110))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(7, 27), QtCore.QPointF(12, 8), QtCore.QPointF(29, 11), QtCore.QPointF(25, 28)]))
        return self._done(pix, p)

    def _glyph_standard(self):
        pix, p = self._pix()
        self._pen(p, None, 2.2)
        p.setBrush(self._ink())
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(9, 6), QtCore.QPointF(9, 27), QtCore.QPointF(15, 21),
                                       QtCore.QPointF(20, 30), QtCore.QPointF(24, 28), QtCore.QPointF(19, 19),
                                       QtCore.QPointF(27, 18)]))
        return self._done(pix, p)

    def _glyph_propagate(self):
        pix, p = self._pix()
        self._pen(p)
        p.drawLine(QtCore.QPointF(5, 24), QtCore.QPointF(14, 24))
        path = QtGui.QPainterPath(QtCore.QPointF(14, 24))
        path.cubicTo(QtCore.QPointF(22, 24), QtCore.QPointF(22, 12), QtCore.QPointF(31, 12))
        p.drawPath(path)
        return self._done(pix, p)

    # --- state
    def mode(self):
        for key, b in self.modes.items():
            if b.isChecked():
                return key
        return "closed"

    def clear_all(self):
        self.picked = []
        self.closed = None
        QtCore.QTimer.singleShot(0, lambda: _show([]))
        self.ok.setEnabled(False)

    def take(self, obj, sub):
        """A pick in the graphics area while the bar is up."""
        mode = self.mode()
        if mode == "standard":
            return False
        try:
            shape = obj.Shape
        except Exception:
            return False
        if mode == "region" or (mode == "closed" and sub.startswith("Face")):
            if not sub.startswith("Face"):
                return True
            if mode == "closed":        # the other loop: the clicked face's outer loop
                self.picked = [(obj, "Edge%d" % i) for i in region_of(shape, int(sub[4:]))]
            else:
                self.picked = [(obj, sub)]
            self.closed = True
        elif mode == "group":
            if not sub.startswith("Edge"):
                return True
            key = (obj, sub)
            if key in self.picked:
                self.picked.remove(key)
            else:
                self.picked.append(key)
            self.closed = None
        else:
            if not sub.startswith("Edge"):
                return True
            index = int(sub[4:])
            if mode == "closed":
                chain, closed = closed_loop(shape, index, self.propagate.isChecked())
            else:
                chain, closed = loop_from(shape, index, self.propagate.isChecked(), closed=False)
            self.picked = [(obj, "Edge%d" % i) for i in chain]
            self.closed = closed
        picked = list(self.picked)
        QtCore.QTimer.singleShot(0, lambda: _show(picked))     # not inside FreeCAD's selection call
        self.ok.setEnabled(bool(self.picked))
        return True


class _Observer:
    def __init__(self, bar):
        self.bar = bar
        self.busy = False

    def addSelection(self, doc, name, sub, pnt):
        if self.busy or not _alive(self.bar):
            return
        try:
            obj = App.getDocument(doc).getObject(name)
        except Exception:
            return
        if obj is None or not sub:
            return
        self.busy = True
        try:
            handled = self.bar.take(obj, sub)
        finally:
            self.busy = False
        if handled:
            pass

    def removeSelection(self, doc, name, sub):
        pass

    def clearSelection(self, doc):
        pass

    def setSelection(self, doc):
        pass


_observer = [None]


def _show(picked, again=(250, 600)):
    """The loop highlighted in the graphics area (the picks are made again, quietly). FreeCAD's page
    may clear the selection a moment later, so the highlight is checked again while the bar holds
    the same picks."""
    if again:
        def recheck(picked=picked, rest=again[1:]):
            bar = _current[0]
            if bar is not None and _alive(bar) and list(bar.picked) == list(picked):
                _show(picked, rest)
        QtCore.QTimer.singleShot(again[0], recheck)
    obs = _observer[0]
    if obs is not None:
        obs.busy = True
    try:
        want = [(obj.Document.Name, obj.Name, sub) for obj, sub in picked]
        have = [(x.DocumentName, x.ObjectName, s) for x in Gui.Selection.getSelectionEx() for s in (x.SubElementNames or ("",))]
        for key in have:
            if key not in want:
                Gui.Selection.removeSelection(*key)
        for _try in range(3):
            # FreeCAD's own pick mode (the page's pressed button) may still take the first edge
            # as its pick and clear the selection: add what is missing until it all shows
            now = [(x.DocumentName, x.ObjectName, s) for x in Gui.Selection.getSelectionEx() for s in (x.SubElementNames or ("",))]
            missing = [key for key in want if key not in now]
            if not missing:
                break
            for key in missing:
                Gui.Selection.addSelection(*key)
    except Exception as error:
        App.Console.PrintLog("FreeCAD SelectionManager: show %s\n" % error)
    finally:
        if obs is not None:
            obs.busy = False


# --------------------------------------------------------------------------- open, commit, close
def open_manager():
    """The bar, over the graphics area. False when no page of ours waits for a model pick."""
    if not available():
        return False
    close()
    view = pmtakeover.view_widget()
    if view is None:
        return False
    bar = _Bar(view)
    _current[0] = bar
    box = _waiting_box()
    bar.target = box.objectName() if box is not None else ""
    App.Console.PrintLog("FreeCAD SelectionManager: for %s\n" % (bar.target or "the page"))
    _suspend_native(bar)
    bar.show()
    bar.raise_()
    obs = _Observer(bar)
    _observer[0] = obs
    Gui.Selection.addObserver(obs)
    Gui.Selection.clearSelection()
    try:
        Gui.getMainWindow().statusBar().showMessage(
            "SelectionManager: click an edge for its loop, a face for its region, then OK.", 6000)
    except Exception as _fw_err:
        _fw_log("selman.py:506", _fw_err)
    return True


NATIVE_BUTTONS = ("buttonSpineBase", "buttonProfileBase", "buttonRefAdd", "buttonSectionAdd", "buttonProfile")


def _suspend_native(bar):
    """FreeCAD's own pick buttons (pressed = its selection gate) let go while the bar takes the
    picks; Cancel presses them again."""
    try:
        for b in Gui.getMainWindow().findChildren(QtWidgets.QAbstractButton):
            if b.objectName() in NATIVE_BUTTONS and b.isVisible() and b.isChecked():
                b.setChecked(False)
                bar.suspended.append(b)
    except Exception as _fw_err:
        _fw_log("selman.py:522", _fw_err)
    try:
        Gui.Selection.removeSelectionGate()
    except Exception as _fw_err:
        _fw_log("selman.py:526", _fw_err)


def _resume_native(bar):
    for b in list(getattr(bar, "suspended", ())):
        try:
            if b.isVisible() and not b.isChecked():
                b.setChecked(True)
        except RuntimeError as _fw_err:
            _fw_log("selman.py:535", _fw_err)
    bar.suspended = []


def close(resume=True):
    bar, obs = _current[0], _observer[0]
    _current[0] = None
    _observer[0] = None
    if bar is not None and _alive(bar) and resume:
        _resume_native(bar)
    if obs is not None:
        try:
            Gui.Selection.removeObserver(obs)
        except Exception as _fw_err:
            _fw_log("selman.py:549", _fw_err)
    if bar is not None and _alive(bar):
        bar.hide()
        bar.deleteLater()
    try:
        Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("selman.py:556", _fw_err)


def _waiting_box():
    """The selection box the page waits for (the active list), or None."""
    from . import propertymanager as pm
    for dock in Gui.getMainWindow().findChildren(QtWidgets.QDockWidget):
        view = pm._view(dock)
        if view is None or not view.isVisible():
            continue
        for box in view.findChildren(QtWidgets.QListWidget):
            if box.isVisible() and box.property("swActive") in ("true", True):
                return box
    return None


def commit():
    """OK: the picks go to the waiting box as if clicked one by one (the page's own pick
    handling takes them; FreeCAD's Sweep path collects the edges of one object)."""
    bar = _current[0]
    if bar is None or not bar.picked:
        return False
    picked = list(bar.picked)
    bar.ok.setEnabled(False)
    obs = _observer[0]
    if obs is not None:
        obs.busy = True
    try:
        Gui.Selection.clearSelection()
        name = getattr(bar, "target", "") or ""
        if name == "SWStyle_SweepPath" or name.endswith("Path"):
            _commit_path(picked)
        else:
            _commit_profile(picked)
    finally:
        if obs is not None:
            obs.busy = False
    if bar is not None:
        bar.suspended = []          # the box has its pick: FreeCAD's button stays let go
    QtCore.QTimer.singleShot(0, close)
    return True


def _editing():
    try:
        edit = Gui.ActiveDocument.getInEdit()
        return edit.Object if edit is not None else None
    except Exception:
        return None


def _commit_path(picked):
    """A sweep path of edges: FreeCAD's Spine takes (object, [edges]); set and shown in the page."""
    feature = _editing()
    obj = picked[0][0]
    subs = [sub for o, sub in picked if o is obj]
    if feature is not None and hasattr(feature, "Spine"):
        try:
            feature.Spine = (obj, subs)
            feature.Document.recompute()
        except Exception as error:
            App.Console.PrintLog("FreeCAD SelectionManager: path: %s\n" % error)
        _refresh_native("spineBaseEdit", obj, subs)
        QtCore.QTimer.singleShot(200, lambda: _refresh_native("spineBaseEdit", obj, subs))   # after FreeCAD's own update
        return
    for o, sub in picked:
        Gui.Selection.addSelection(o.Document.Name, o.Name, sub)


def _commit_profile(picked):
    """A face, or the loop's edges, as the profile / section: through the page's own picks (one
    pick of the face, or the edges of one object); FreeCAD's Loft and Sweep take both."""
    feature = _editing()
    obj = picked[0][0]
    subs = [sub for o, sub in picked if o is obj]
    if feature is None:
        for o, sub in picked:
            Gui.Selection.addSelection(o.Document.Name, o.Name, sub)
        return
    try:
        if feature.TypeId in ("PartDesign::AdditivePipe", "PartDesign::SubtractivePipe") and not feature.Profile:
            feature.Profile = (obj, subs)
            feature.Document.recompute()
            _refresh_native("profileBaseEdit", obj, subs)
            return
        if feature.TypeId in ("PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft"):
            if not feature.Profile:
                feature.Profile = (obj, subs)
                _refresh_native("profileBaseEdit", obj, subs)
            else:
                feature.Sections = list(feature.Sections or []) + [(obj, sub) for sub in subs]
            feature.Document.recompute()
            return
    except Exception as error:
        App.Console.PrintLog("FreeCAD SelectionManager: profile: %s\n" % error)
    for o, sub in picked:
        Gui.Selection.addSelection(o.Document.Name, o.Name, sub)


def _refresh_native(edit_name, obj, subs):
    """FreeCAD's own line edit (which the page's box reads) shows the pick, and its pick button
    lets go, as after a pick of FreeCAD's own."""
    try:
        for edit in Gui.getMainWindow().findChildren(QtWidgets.QLineEdit, edit_name):
            if edit.isVisible():
                edit.setText("%s:%s" % (obj.Label, ",".join(subs)) if subs and subs[0] else obj.Label)
        button = {"spineBaseEdit": "buttonSpineBase", "profileBaseEdit": "buttonProfileBase"}.get(edit_name)
        for b in Gui.getMainWindow().findChildren(QtWidgets.QAbstractButton, button or "-"):
            if b.isVisible() and b.isChecked():
                b.setChecked(False)
    except Exception as _fw_err:
        _fw_log("selman.py:667", _fw_err)


def menu_action():
    """The graphics-area menu item while a page that takes model picks is open, else None."""
    if not available():
        return None
    from . import rcmenus
    return rcmenus.action("SelectionManager", "SelectionManager", open_manager)
