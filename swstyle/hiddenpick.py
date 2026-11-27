# SPDX-License-Identifier: LGPL-2.1-or-later
""














_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

VIEW = "User parameter:BaseApp/Preferences/View"
MAX_POINTS = 60000          # screen points kept for one camera at most (projected again when it moves)
CELL = 32                   # px: the projected segments are bucketed in a grid of this size, once per camera
DELAY = 30                  # ms: pointer moves are looked at once per this time, at the last position
DRAG = 4                    # px the pointer moves with the button down before a press on a hidden edge is a drag


class HiddenPick:
    def __init__(self):
        self.hover = None       # (doc name, leaf object name, "EdgeN") under the pointer, hidden
        self.cache = None       # (camera key, [(key, [(x, y)], [App.Vector])])
        self.press = None       # (doc, obj, edge, modifiers) while a click on the hovered edge is down
        self.picks = 0          # hidden edges picked by a click, for checks
        self.hovers = 0         # hovers that found a hidden edge, for checks
        self.looks = 0          # pointer positions looked at, for checks
        self.at = None          # (widget, pixels y up) of the last move, looked at by the timer
        self.sending = False    # a press handed back to FreeCAD (a drag), not ours
        self.timer = None

    # -- what applies -------------------------------------------------------------------------
    @staticmethod
    def active():
        try:
            from . import hlv, boxselect, contextbar
            if hlv.HIDDEN.mode not in ("hlv", "hlr", "shd") or not hlv.HIDDEN.keyed:
                return False
            if contextbar.sketch_in_edit() is not None:
                return False
            if not App.ParamGet(VIEW).GetBool("EnablePreselection", True) and hlv.HIDDEN.mode != "hlv":
                return False
            return boxselect.hidden_allowed()
        except Exception as _fw_err:
            _fw_log("hiddenpick.py:active", _fw_err)
            return False

    @staticmethod
    def _view():
        gdoc = Gui.ActiveDocument
        view = getattr(gdoc, "ActiveView", None) if gdoc is not None else None
        return view if view is not None and hasattr(view, "getObjectInfo") else None

    # -- finding the edge ---------------------------------------------------------------------
    def _projected(self, view):
        from . import hlv
        try:
            cam = view.getCameraNode()
            key = (tuple(cam.position.getValue().getValue()), tuple(cam.orientation.getValue().getValue()),
                   view.getSize() if hasattr(view, "getSize") else None, id(hlv.HIDDEN.keyed), hlv.HIDDEN.doc_name)
            try:
                key = key + (float(cam.height.getValue()),)
            except Exception:
                key = key + (float(getattr(cam, "heightAngle").getValue()),) if hasattr(cam, "heightAngle") else key
        except Exception as _fw_err:
            _fw_log("hiddenpick.py:camera", _fw_err)
            return ([], {})
        if self.cache is not None and self.cache[0] == key:
            return self.cache[1]
        out, n, grid = [], 0, {}
        for k, pts in hlv.HIDDEN.keyed.items():
            n += len(pts)
            if n > MAX_POINTS:
                _fw_log("hiddenpick.py:size", "more than %d edge points: hidden edge hover off for this view" % MAX_POINTS)
                out = []
                break
            try:
                scr = [tuple(view.getPointOnScreen(p)) for p in pts]
            except Exception as _fw_err:
                _fw_log("hiddenpick.py:project", _fw_err)
                continue
            e = len(out)
            out.append((k, scr, pts))
            for i in range(len(scr) - 1):
                (x0, y0), (x1, y1) = scr[i], scr[i + 1]
                for cx in range(int(min(x0, x1) // CELL), int(max(x0, x1) // CELL) + 1):
                    for cy in range(int(min(y0, y1) // CELL), int(max(y0, y1) // CELL) + 1):
                        grid.setdefault((cx, cy), []).append((e, i))
        if n > MAX_POINTS:
            out, grid = [], {}
        self.cache = (key, (out, grid))
        return self.cache[1]

    def nearest(self, view, at):
        """((object, "EdgeN"), 3D point) of the edge nearest at (pixels, y up) within the pick radius."""
        radius = float(App.ParamGet(VIEW).GetFloat("PickRadius", 5.0))
        try:
            radius *= Gui.getMainWindow().devicePixelRatioF()
        except Exception:
            pass
        best = None
        ax, ay = at
        edges, grid = self._projected(view) or ([], {})
        near = set()
        for cx in range(int((ax - radius) // CELL), int((ax + radius) // CELL) + 1):
            for cy in range(int((ay - radius) // CELL), int((ay + radius) // CELL) + 1):
                near.update(grid.get((cx, cy), ()))
        for e, i in near:
            k, scr, pts = edges[e]
            (x0, y0), (x1, y1) = scr[i], scr[i + 1]
            dx, dy = x1 - x0, y1 - y0
            ll = dx * dx + dy * dy
            t = 0.0 if ll <= 1e-12 else max(0.0, min(1.0, ((ax - x0) * dx + (ay - y0) * dy) / ll))
            ex, ey = x0 + t * dx - ax, y0 + t * dy - ay
            d = (ex * ex + ey * ey) ** 0.5
            if d <= radius and (best is None or d < best[0]):
                best = (d, k, pts[i] + (pts[i + 1] - pts[i]) * t)
        return None if best is None else (best[1], best[2])

    def hidden_at(self, view, at):
        """(doc, object, "EdgeN") when the edge nearest the pointer lies behind the model there, else None."""
        found = self.nearest(view, at)
        if found is None:
            return None
        (obj, edge), p = found
        from . import hlv
        try:
            info = view.getObjectInfo((int(at[0]), int(at[1])))
        except Exception:
            info = None
        if not info:
            return None                     # nothing in front of it: FreeCAD picks it
        if info.get("Object") == obj and str(info.get("Component", "")).endswith(edge):
            return None
        try:
            hit = App.Vector(info["x"], info["y"], info["z"])
            d = App.Vector(*view.getViewDirection())
            d.normalize()
            x, y = int(at[0]), int(at[1])
            px = (App.Vector(view.getPoint(x + 1, y)) - App.Vector(view.getPoint(x, y))).Length
            radius = float(App.ParamGet(VIEW).GetFloat("PickRadius", 5.0)) + 2.0
            if (p - hit).dot(d) <= 3.0 * radius * px + 1e-6:
                return None                 # in front, or on the face under the pointer: a seen edge
        except Exception as _fw_err:
            _fw_log("hiddenpick.py:depth", _fw_err)
            return None
        return hlv.HIDDEN.doc_name, obj, edge

    # -- hover ----------------------------------------------------------------------------------
    def set_hover(self, hover):
        if hover == self.hover:
            return
        self.hover = hover
        if hover is not None:
            self.hovers += 1
            try:
                from . import shell
                fh = getattr(shell.shell(), "face_hover", None)
                if fh is not None and fh.key is not None and not fh.held:
                    fh.hide()
            except Exception as _fw_err:
                _fw_log("hiddenpick.py:facehover", _fw_err)
        try:
            from . import hlv
            hlv.HIDDEN.hl_timer.start()
        except Exception as _fw_err:
            _fw_log("hiddenpick.py:redraw", _fw_err)

    def lines(self):
        """The hovered hidden edge's points, for hlv's highlight."""
        if self.hover is None:
            return []
        from . import hlv
        pts = hlv.HIDDEN.keyed.get((self.hover[1], self.hover[2]))
        return [pts] if pts else []

    # -- events -------------------------------------------------------------------------------
    def event(self, obj, event):
        if not isinstance(event, QtCore.QEvent) or not isinstance(obj, QtCore.QObject):
            return False
        t = event.type()
        if t == QtCore.QEvent.Leave:
            if obj.inherits("QOpenGLWidget"):
                self.cancel()
                self.set_hover(None)
            return False
        if not obj.inherits("QOpenGLWidget"):
            return False
        if self.sending:
            return False
        if t == QtCore.QEvent.MouseMove:
            if self.press is not None:
                if event.buttons() & QtCore.Qt.LeftButton:
                    d = event.position() - self.press[4]
                    if abs(d.x()) + abs(d.y()) > DRAG:
                        self._hand_back(obj)        # a drag, not a click: FreeCAD gets its press after all
                return False
            if event.buttons() != QtCore.Qt.NoButton or not self.active():
                self.at = None
                self.set_hover(None)
                return False
            dpr = obj.devicePixelRatioF() or 1.0
            pos = event.position()
            self.at = (obj, (pos.x() * dpr, (obj.height() - pos.y()) * dpr))
            if self.timer is None:
                self.timer = QtCore.QTimer()
                self.timer.setSingleShot(True)
                self.timer.setInterval(DELAY)
                self.timer.timeout.connect(self._look)
            if not self.timer.isActive():
                self.timer.start()
            return False
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() != QtCore.Qt.LeftButton or event.buttons() != QtCore.Qt.LeftButton:
                self.press = None
                return False
            if self.timer is not None and self.timer.isActive():
                self.timer.stop()
                self._look()                        # the hover where the button went down
            if self.hover is None or not self.active():
                return False
            # held back until the release (a click picks the hidden edge) or a move past DRAG (a drag: handed back)
            self.press = self.hover + (event.modifiers(), QtCore.QPointF(event.position()), QtCore.QPointF(event.globalPosition()))
            return True
        if t == QtCore.QEvent.MouseButtonRelease and self.press is not None and event.button() == QtCore.Qt.LeftButton:
            press, self.press = self.press, None
            QtCore.QTimer.singleShot(0, lambda: self.pick(*press[:4]))
            return True
        return False

    def cancel(self):
        """Drops a hover still waiting on the timer (the pointer left the view, or the module is taken off):
        without this a point queued just before Leave lit the hidden edge again after it (review b10)."""
        self.at = None
        if self.timer is not None:
            try:
                self.timer.stop()
            except RuntimeError as _fw_err:
                _fw_log("hiddenpick.py:cancel", _fw_err)

    def _look(self):
        at, self.at = self.at, None
        if at is None or self.press is not None:
            return
        view = self._view()
        if view is None or not self.active():
            self.set_hover(None)
            return
        self.looks += 1
        self.set_hover(self.hidden_at(view, at[1]))

    def _hand_back(self, widget):
        """The button went down on a hidden edge and the pointer moved on: give FreeCAD the press it was
        kept from, where it happened, so the drag goes on as it would without this module."""
        press, self.press = self.press, None
        self.set_hover(None)
        if press is None:
            return
        from PySide import QtGui
        e = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, press[4], press[5], QtCore.Qt.LeftButton,
                              QtCore.Qt.LeftButton, press[3])
        self.sending = True
        try:
            QtWidgets.QApplication.sendEvent(widget, e)
        finally:
            self.sending = False

    def pick(self, doc, obj, edge, modifiers):
        try:
            from . import contextbar
            leaf = App.getDocument(doc).getObject(obj)
            top, path = leaf, ""
            parent = leaf.getParentGeoFeatureGroup()
            while parent is not None:
                path = top.Name + "." + path
                top = parent
                parent = parent.getParentGeoFeatureGroup()
            sub = path + edge
            ctrl = bool(modifiers & QtCore.Qt.ControlModifier)
            if ctrl and Gui.Selection.isSelected(top, sub):
                Gui.Selection.removeSelection(doc, top.Name, sub)
                return
            if not ctrl and not (modifiers & QtCore.Qt.ShiftModifier) and not contextbar.dialog_open():
                Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc, top.Name, sub)
            self.picks += 1
        except Exception as _fw_err:
            _fw_log("hiddenpick.py:pick", _fw_err)


PICK = HiddenPick()
_ORIGINAL = []          # facehover.FaceHover.show before the wrap, for uninstall()


def install():
    from . import events, facehover
    events.register("hiddenpick", (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress,
                                   QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.Leave), PICK.event)
    current = facehover.FaceHover.show
    if getattr(current, "_fw_hiddenpick", False):
        return                              # wrapped already (a second install or a reload)
    show0 = current

    def show(self, doc, obj, sub, *a, **k):
        if PICK.hover is not None:
            self.key = None                 # the hidden edge is the one under the pointer
            return None
        return show0(self, doc, obj, sub, *a, **k)
    show.__wrapped__ = show0
    show._fw_hiddenpick = True
    _ORIGINAL[:] = [show0]
    facehover.FaceHover.show = show


def uninstall():
    from . import events, facehover
    events.unregister("hiddenpick")
    PICK.cancel()
    PICK.set_hover(None)
    shown = facehover.FaceHover.show
    if getattr(shown, "_fw_hiddenpick", False):
        facehover.FaceHover.show = getattr(shown, "__wrapped__", None) or (_ORIGINAL[0] if _ORIGINAL else shown)
    _ORIGINAL[:] = []
