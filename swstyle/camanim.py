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
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

VIEW = "User parameter:BaseApp/Preferences/View"
DURATION_MS = 520
SLOWER_MS = {2: 850, 1: 1250}       # the slider's Medium and Slow stops


def duration_ms():
    """How long a move takes, from Options > View > Transitions > View transition (FreeCAD's
    AnimationDuration: 250 or less = Fast, up to 600 = Medium, more = Slow)."""
    try:
        ms = App.ParamGet(VIEW).GetInt("AnimationDuration", 250)
    except Exception:
        return DURATION_MS
    return DURATION_MS if ms <= 300 else SLOWER_MS[2 if ms <= 600 else 1]
TICK_MS = 15
_running = {}           # id(view) -> _Move
stats = {"moves": 0, "frames": 0, "last_ms": 0.0}


def enabled():
    try:
        return App.ParamGet(VIEW).GetBool("UseNavigationAnimations", True)
    except Exception:
        return True


def _ease(t):
    """Smooth start and stop (smootherstep)."""
    t = max(0.0, min(1.0, t))
    return t * t * t * (t * (t * 6 - 15) + 10)


def _state(cam):
    q = cam.orientation.getValue().getValue()
    p = cam.position.getValue().getValue()
    s = {"q": tuple(q), "p": tuple(p), "focal": cam.focalDistance.getValue()}
    if cam.isOfType(__import__("pivy").coin.SoOrthographicCamera.getClassTypeId()):
        s["height"] = cam.height.getValue()
    return s


def _apply(cam, s):
    from pivy import coin
    cam.orientation.setValue(coin.SbRotation(*s["q"]))
    cam.position.setValue(*s["p"])
    cam.focalDistance.setValue(s["focal"])
    if "height" in s:
        cam.height.setValue(s["height"])


def _slerp(a, b, t):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b, dot = tuple(-x for x in b), -dot
    if dot > 0.9995:
        out = tuple(x + (y - x) * t for x, y in zip(a, b))
    else:
        th = math.acos(dot)
        s = math.sin(th)
        wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
        out = tuple(wa * x + wb * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in out)) or 1.0
    return tuple(x / n for x in out)


def _focal_point(s):
    from pivy import coin
    r = coin.SbRotation(*s["q"])
    d = r.multVec(coin.SbVec3f(0, 0, -1)).getValue()
    return tuple(p + s["focal"] * di for p, di in zip(s["p"], d))


def _mix(a, b, t):
    """The camera between a and b: the look point and the distance move, the turn is a slerp, the
    zoom (ortho height) moves evenly on a log scale so it never seems to speed up."""
    from pivy import coin
    q = _slerp(a["q"], b["q"], t)
    fa, fb = _focal_point(a), _focal_point(b)
    focal_pt = tuple(x + (y - x) * t for x, y in zip(fa, fb))
    focal = a["focal"] + (b["focal"] - a["focal"]) * t
    d = coin.SbRotation(*q).multVec(coin.SbVec3f(0, 0, -1)).getValue()
    out = {"q": q, "p": tuple(f - focal * di for f, di in zip(focal_pt, d)), "focal": focal}
    if "height" in a and "height" in b and a["height"] > 0 and b["height"] > 0:
        out["height"] = math.exp(math.log(a["height"]) + (math.log(b["height"]) - math.log(a["height"])) * t)
    return out


class _Move(QtCore.QObject):
    def __init__(self, view, start, end):
        super().__init__(Gui.getMainWindow())
        self.view, self.start, self.end = view, start, end
        # menusweep-1119: the document the view belongs to; a move whose document closed stops before it
        # touches the deleted view (that crashed FreeCAD)
        try:
            self.doc = Gui.ActiveDocument.Document.Name if Gui.ActiveDocument is not None else None
        except Exception:
            self.doc = None
        _watch_documents()
        self.duration = duration_ms()
        self.t0 = time.time()
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.step)
        self.last = start
        self.timer.start()

    def step(self):
        if self.doc is not None and self.doc not in App.listDocuments():
            self.finish(False)
            return
        try:
            cam = self.view.getCameraNode()
            now = _state(cam)
            # the user (a mouse turn, a wheel zoom) moved the view: leave it to them
            if any(abs(x - y) > 1e-6 for x, y in zip(now["q"], self.last["q"])) or \
                    abs(now.get("height", 0) - self.last.get("height", 0)) > 1e-6 * max(1.0, now.get("height", 1)):
                self.finish(False)
                return
            t = (time.time() - self.t0) * 1000.0 / self.duration
            s = self.end if t >= 1.0 else _mix(self.start, self.end, _ease(t))
            _apply(cam, s)
            self.last = _state(cam)
            stats["frames"] += 1
            if t >= 1.0:
                stats["last_ms"] = (time.time() - self.t0) * 1000.0
                self.finish(True)
        except Exception as error:
            _fw_log("camanim.py:step", error)
            self.finish(False)

    def finish(self, done):
        self.timer.stop()
        _running.pop(id(self.view), None)
        self.deleteLater()


class _DocGone:
    """menusweep-1119: a document going stops its views' moves."""

    def slotDeletedDocument(self, doc):
        for key, move in list(_running.items()):
            if getattr(move, "doc", None) == doc.Name:
                move.finish(False)


_OBSERVER = []


def _watch_documents():
    if not _OBSERVER:
        _OBSERVER.append(_DocGone())
        try:
            App.addDocumentObserver(_OBSERVER[0])
        except Exception as _fw_err:
            _fw_log("camanim.py:observer", _fw_err)


def animate_to(view=None, rotation=None, fit=True):
    """Turns (rotation: App.Rotation or None to keep) and fits (fit) the view in one smooth move.
    Returns True when the move was started or done at once."""
    view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None)
    if view is None or not hasattr(view, "getCameraNode"):
        return False
    old = _running.pop(id(view), None)
    if old is not None:
        old.finish(False)
    try:
        view.stopAnimating()
    except Exception as _fw_err:
        _fw_log("camanim.py:stop", _fw_err)
    cam = view.getCameraNode()
    start = _state(cam)
    # where FreeCAD would put the camera: set it, read it back, put the start back
    try:
        if rotation is not None:
            from pivy import coin
            cam.orientation.setValue(coin.SbRotation(*rotation.Q))
            if not fit:
                # turn about the look point, as FreeCAD's own turns do
                end_q = cam.orientation.getValue().getValue()
                fp = _focal_point(start)
                d = coin.SbRotation(*end_q).multVec(coin.SbVec3f(0, 0, -1)).getValue()
                cam.position.setValue(*[f - start["focal"] * di for f, di in zip(fp, d)])
        if fit:
            # look-audit MF-4 (BB25): FreeCAD 1.1's fitAll() runs its own zoom animation, which zoomed
            # in, jumped back out when this move started, and zoomed in again (or snapped where its
            # timer was faster): its animation off while the end is read, as animate_command does
            grp = App.ParamGet(VIEW)
            was = grp.GetBool("UseNavigationAnimations", True)
            try:
                grp.SetBool("UseNavigationAnimations", False)
                view.fitAll()
            finally:
                grp.SetBool("UseNavigationAnimations", was)
            try:
                view.stopAnimating()
            except Exception as _fw_err:
                _fw_log("camanim.py:stop-fit", _fw_err)
            cam = view.getCameraNode()
        end = _state(cam)
    except Exception as error:
        _fw_log("camanim.py:end", error)
        return False
    if not enabled():
        return True             # FreeCAD's animation is off: the jump, as asked
    _apply(cam, start)
    stats["moves"] += 1
    _running[id(view)] = _Move(view, start, end)
    return True


def animate_command(name, view=None):
    """Runs FreeCAD's view command `name` (Align to Selection, View Sketch) with its own animation
    off, reads where it put the camera and eases there instead. False when it did not run."""
    view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None)
    if view is None or not hasattr(view, "getCameraNode") or not enabled():
        return False
    old = _running.pop(id(view), None)
    if old is not None:
        old.finish(False)
    cam = view.getCameraNode()
    start = _state(cam)
    grp = App.ParamGet(VIEW)
    try:
        grp.SetBool("UseNavigationAnimations", False)
        Gui.runCommand(name, 0)
    except Exception as error:
        _fw_log("camanim.py:command", error)
        return False
    finally:
        grp.SetBool("UseNavigationAnimations", True)
    end = _state(view.getCameraNode())
    _apply(cam, start)
    stats["moves"] += 1
    _running[id(view)] = _Move(view, start, end)
    return True


def animate_change(change, view=None):
    """Eases to wherever `change(view)` puts the camera (Previous View, Zoom to Selection, the second
    Normal To): it is run at once, the end is read back, the start put back, then eased to. False when
    it could not run; with FreeCAD's animation off the change simply stays, as a jump."""
    view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None)
    if view is None or not hasattr(view, "getCameraNode"):
        return False
    old = _running.pop(id(view), None)
    if old is not None:
        old.finish(False)
    try:
        view.stopAnimating()
    except Exception as _fw_err:
        _fw_log("camanim.py:stop2", _fw_err)
    start = _state(view.getCameraNode())
    try:
        if change(view) is False:
            return False
    except Exception as error:
        _fw_log("camanim.py:change", error)
        return False
    cam = view.getCameraNode()      # setCamera() can swap the camera node
    end = _state(cam)
    if not enabled() or set(start) != set(end):
        return True                 # animation off, or perspective <-> orthographic: the jump
    _apply(cam, start)
    stats["moves"] += 1
    _running[id(view)] = _Move(view, start, end)
    return True


def busy(view=None):
    """True while a move runs in the view."""
    view = view or (Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None)
    return view is not None and id(view) in _running
