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

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
TYPES = ("PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove")
SKIP = {"Profile", "BaseFeature", "Shape", "AddSubShape", "Placement", "Label", "Label2", "ExpressionEngine",
        "Visibility", "_Body", "SuppressedShape", "PreviewShape", "Suppressed",
        "ShapeMaterial"}
RECOMPUTE_S = 0.25
STATE = {}
LAST = {}
TRACE = []          # the last presses the filter saw (why a drag did or did not start), for checks


def _trace(**info):
    TRACE.append(info)
    del TRACE[:-20]


def _held_keys():
    """Shift/Ctrl/Alt held right now, from Windows itself (GetAsyncKeyState): Qt reads the key state
    of its own input queue, which misses a key that went down while another window had the focus."""
    import sys
    if sys.platform != "win32":
        return Qt.NoModifier
    try:
        import ctypes
        state = ctypes.windll.user32.GetAsyncKeyState
        out = Qt.NoModifier
        for vk, mod in ((0x10, Qt.ShiftModifier), (0x11, Qt.ControlModifier), (0x12, Qt.AltModifier)):
            if state(vk) & 0x8000:
                out |= mod
        return out
    except Exception:
        return Qt.NoModifier


def _reset():
    STATE.clear()


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def _gl(widget, pos):
    dpr = widget.devicePixelRatioF()
    return int(pos.x() * dpr), int((widget.height() - pos.y()) * dpr)


def _busy():
    try:
        return bool(Gui.Control.activeDialog()) or Gui.ActiveDocument.getInEdit() is not None
    except Exception:
        return True


def _on():
    try:
        from . import instant3d
        return bool(instant3d.enabled())
    except Exception:
        return True


def _sketch(feature):
    try:
        from . import contours
        return contours.sketch_of(feature)
    except Exception:
        prof = getattr(feature, "Profile", None)
        return prof[0] if prof else None


def feature_at(doc, point):
    """The newest sketch-based feature of the active part whose own tool holds point (global)."""
    try:
        from . import multibody
    except Exception:
        multibody = None
    for body in [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]:
        try:
            local = body.getGlobalPlacement().inverse().multVec(point)
        except Exception:
            local = point
        chain = list(body.Group)
        tip = body.Tip
        if tip in chain:
            chain = chain[:chain.index(tip) + 1]
        for f in reversed(chain):
            if f.TypeId not in TYPES or _sketch(f) is None:
                continue
            try:
                tool = f.AddSubShape
                if not tool.isNull() and tool.isInside(local, 1e-4, True):
                    return f
            except Exception:
                continue
    return None


def _plane(sketch):
    """The sketch's plane in the document: (global placement)."""
    try:
        return sketch.getGlobalPlacement()
    except Exception:
        return sketch.Placement


def _on_plane(widget, pos, placement):
    """Where the pointer's ray meets the plane of placement (global)."""
    view = _view()
    if view is None:
        return None
    try:
        x, y = _gl(widget, pos)
        p = App.Vector(view.getPoint(x, y))
        d = App.Vector(view.getViewDirection())
        n = placement.Rotation.multVec(App.Vector(0, 0, 1))
        den = d.dot(n)
        if abs(den) < 1e-9:
            return None
        t = (placement.Base - p).dot(n) / den
        return p + d * t
    except Exception:
        return None


def copy_sketch(sketch, body):
    new = body.newObject("Sketcher::SketchObject", "Sketch")
    for prop in ("AttachmentSupport", "MapMode", "MapReversed", "MapPathParameter", "AttachmentOffset"):
        try:
            setattr(new, prop, getattr(sketch, prop))
        except Exception as _fw_err:
            _fw_log("featuredrag.py:167", _fw_err)
    if new.MapMode == "Deactivated":
        new.Placement = sketch.Placement
    try:
        for ext in sketch.ExternalGeometry:
            for sub in ext[1]:
                new.addExternal(ext[0].Name, sub)
    except Exception as _fw_err:
        _fw_log("featuredrag.py:175", _fw_err)
    new.addGeometry(sketch.Geometry, False)
    for i, g in enumerate(sketch.Geometry):
        try:
            if sketch.getConstruction(i):
                new.setConstruction(i, True)
        except Exception as _fw_err:
            _fw_log("featuredrag.py:182", _fw_err)
    try:
        new.addConstraint(list(sketch.Constraints))
    except Exception as _fw_err:
        _fw_log("featuredrag.py:186", _fw_err)
    return new


def copy_feature(feature, sketch, body):
    new = body.newObject(feature.TypeId, feature.TypeId.split("::")[-1])
    for prop in feature.PropertiesList:
        if prop in SKIP:
            continue
        try:
            group = feature.getGroupOfProperty(prop)
            if not group or group == "Base":
                continue
            if "ReadOnly" in feature.getEditorMode(prop):
                continue
            value = getattr(feature, prop)
            if feature.getTypeIdOfProperty(prop).startswith("App::PropertyLink"):
                # an axis on the old sketch is the same axis of the new one
                old = _sketch(feature)
                if isinstance(value, tuple) and value and value[0] is old:
                    value = (sketch, value[1])
                elif value is old:
                    value = sketch
            setattr(new, prop, value)
        except Exception:
            continue
    new.Profile = sketch
    try:
        from . import contours
        helper = contours.helper_of(feature)
        if helper is not None and list(helper.Picks):
            contours.set_picks(new, list(helper.Picks))
    except Exception as _fw_err:
        _fw_log("featuredrag.py:219", _fw_err)
    return new


def _move_sketch(sketch, base_offset, base_placement, delta):
    """Slides sketch by the global vector delta (in its own plane)."""
    rot = _plane(sketch).Rotation
    local = rot.inverted().multVec(delta)
    local.z = 0.0
    if sketch.MapMode == "Deactivated":
        pl = App.Placement(base_placement)
        pl.Base = pl.Base + rot.multVec(local)
        sketch.Placement = pl
    else:
        off = App.Placement(base_offset)
        off.Base = off.Base + off.Rotation.multVec(local)
        sketch.AttachmentOffset = off


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        QE = QtCore.QEvent
        if STATE.get("sending"):
            return False
        try:
            if t == QE.KeyPress and STATE.get("doc") is not None and event.key() == Qt.Key_Escape:
                self._cancel()
                return True
            if t not in (QE.MouseButtonPress, QE.MouseMove, QE.MouseButtonRelease):
                return False
            if not obj.inherits("QOpenGLWidget"):
                return False
            if t == QE.MouseButtonPress:
                if STATE.get("doc") is not None:
                    return False
                _reset()
                # Windows can hand the press over without the held Shift/Ctrl (keys pressed by another
                # program or before the view had the focus): the keyboard's live state counts too.
                mods = event.modifiers() | QtWidgets.QApplication.queryKeyboardModifiers() | _held_keys()
                kind = "copy" if mods & (Qt.ControlModifier | Qt.AltModifier) else "move" if mods & Qt.ShiftModifier else "sketch"
                busy = _busy()
                if event.button() == Qt.LeftButton and not busy:
                    self._candidate(obj, event.position(), kind)
                _trace(kind=kind, mods=int(getattr(mods, "value", mods)), busy=busy,
                       found=getattr(STATE.get("feature"), "Name", None), why=STATE.pop("why", None))
                return False
            if t == QE.MouseMove:
                if not STATE.get("feature") or not (event.buttons() & Qt.LeftButton):
                    return False
                if STATE.get("doc") is None:
                    moved = (event.position() - STATE["press"]).manhattanLength()
                    if moved < max(6, QtWidgets.QApplication.startDragDistance()):
                        return False
                    if not self._begin():
                        _reset()
                        return False
                self._follow(obj, event.position())
                return True
            if t == QE.MouseButtonRelease and event.button() == Qt.LeftButton:
                if STATE.get("doc") is not None:
                    self._follow(obj, event.position(), final=True)
                    self._finish()
                    return True       # the view had its release when the drag began
                _reset()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: feature drag: %s\n" % error)
            _trace(error="%s: %s" % (type(error).__name__, error))
            self._cancel()
        return False

    def _candidate(self, widget, pos, kind):
        view = _view()
        doc = App.ActiveDocument
        if view is None or doc is None or not _on():
            STATE["why"] = "no view or Instant3D off"
            return
        if any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects):
            STATE["why"] = "assembly"
            return        # in an assembly Ctrl+drag copies a component (asmctrlcopy)
        try:
            info = view.getObjectInfo(_gl(widget, pos))
        except Exception:
            info = None
        if kind == "sketch":
            for obj, point in _sketches_under(doc, widget, pos, info):
                hit = sketch_hit(obj, point)
                if hit is not None:
                    STATE.update(feature=obj, sketch=obj, kind=kind, hit=hit, press=QtCore.QPointF(pos), widget=widget)
                    return
            return
        if not info or "x" not in info:
            STATE["why"] = "nothing under the pointer"
            return
        point = App.Vector(info["x"], info["y"], info["z"])
        feature = feature_at(doc, point)
        if feature is None:
            STATE["why"] = "no sketch feature at %s (%s)" % (point, info.get("SubName"))
            return
        sketch = _sketch(feature)
        STATE.update(feature=feature, sketch=sketch, kind=kind, press=QtCore.QPointF(pos), widget=widget)

    def _begin(self):
        feature, sketch = STATE["feature"], STATE["sketch"]
        doc = feature.Document
        if STATE["kind"] == "sketch":
            doc.openTransaction("Drag Sketch")
            STATE["doc"] = doc
            self._release_view()
            STATE["plane"] = _plane(sketch)
            STATE["start"] = _on_plane(STATE["widget"], STATE["press"], STATE["plane"])
            STATE["last"] = 0.0
            STATE["prev"] = STATE["start"]
            if STATE["start"] is None:
                self._cancel()
                return False
            events_keys()
            return True
        body = feature.getParentGeoFeatureGroup()
        if body is None or body.TypeId != "PartDesign::Body":
            return False
        doc.openTransaction("Copy Feature" if STATE["kind"] == "copy" else "Move Feature")
        STATE["doc"] = doc
        if STATE["kind"] == "copy":
            new_sketch = copy_sketch(sketch, body)
            doc.recompute()
            new = copy_feature(feature, new_sketch, body)
            STATE["made"] = (new_sketch, new)
            sketch = new_sketch
            try:
                new_sketch.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("featuredrag.py:353", _fw_err)
        self._release_view()
        STATE["moving"] = sketch
        STATE["offset"] = App.Placement(sketch.AttachmentOffset)
        STATE["placement"] = App.Placement(sketch.Placement)
        STATE["plane"] = _plane(sketch)
        STATE["start"] = _on_plane(STATE["widget"], STATE["press"], STATE["plane"])
        STATE["last"] = 0.0
        if STATE["start"] is None:
            self._cancel()
            return False
        events_keys()
        return True

    def _release_view(self):
        """Ends the view's own click at the press point, so the face is picked as on a click and
        its long-press (Clarify Selection) and box select never start while the drag runs."""
        widget, pos = STATE["widget"], STATE["press"]
        try:
            event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, pos, widget.mapToGlobal(pos),
                                      Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
            STATE["sending"] = True
            QtWidgets.QApplication.sendEvent(widget, event)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: feature drag release: %s\n" % error)
        finally:
            STATE.pop("sending", None)

    def _follow(self, widget, pos, final=False):
        now = _on_plane(widget, pos, STATE["plane"])
        if now is None:
            return
        if STATE["kind"] == "sketch":
            drag_geometry(STATE["sketch"], STATE["hit"], STATE["plane"], STATE["prev"], now)
            STATE["prev"] = now
            STATE["delta"] = now - STATE["start"]
            t = time.monotonic()
            if final or t - STATE["last"] >= RECOMPUTE_S:
                STATE["last"] = t
                STATE["doc"].recompute()
            return
        _move_sketch(STATE["moving"], STATE["offset"], STATE["placement"], now - STATE["start"])
        STATE["delta"] = now - STATE["start"]
        t = time.monotonic()
        if final or t - STATE["last"] >= RECOMPUTE_S:
            STATE["last"] = t
            STATE["doc"].recompute()

    def _finish(self):
        doc = STATE["doc"]
        doc.recompute()
        doc.commitTransaction()
        LAST.clear()
        LAST.update(kind=STATE.get("kind"), feature=STATE.get("feature"), made=STATE.get("made"),
                    delta=STATE.get("delta"))
        made = STATE.get("made")
        _unkeys()
        _reset()
        try:
            Gui.Selection.clearSelection()
            if made:
                Gui.Selection.addSelection(made[1])
        except Exception as _fw_err:
            _fw_log("featuredrag.py:416", _fw_err)

    def _cancel(self):
        doc = STATE.get("doc")
        _unkeys()
        _reset()
        if doc is not None:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception as _fw_err:
                _fw_log("featuredrag.py:427", _fw_err)


def _keys(obj, event):
    if STATE.get("doc") is None:
        return False
    if event.type() == QtCore.QEvent.ShortcutOverride:
        event.accept()
        return True
    if event.key() == Qt.Key_Escape and _FILTER:
        _FILTER[0]._cancel()
        return True
    return False


def events_keys():
    try:
        from . import events
        events.register("featuredrag-keys", (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride), _keys)
    except Exception as _fw_err:
        _fw_log("featuredrag.py:447", _fw_err)


def _sketches_under(doc, widget, pos, info):
    """The shown sketches (not in edit) with the point where the pointer's ray meets each plane;
    the one the view picked first. A sketch's lines are thin, so the plane test finds them even
    when the view's pick radius misses."""
    first = []
    if info and info.get("Object"):
        sub = (info.get("SubName") or "").split(".")
        names = [info["Object"]] + sub[:-1]
        for name in names:
            obj = doc.getObject(name)
            if obj is not None and obj.TypeId == "Sketcher::SketchObject":
                first.append(obj)
    shown = [o for o in doc.Objects if o.TypeId == "Sketcher::SketchObject" and o not in first
             and getattr(getattr(o, "ViewObject", None), "Visibility", False)]
    out = []
    for obj in first + shown:
        try:
            at = _on_plane(widget, pos, _plane(obj))
        except Exception:
            at = None
        if at is not None:
            out.append((obj, at))
    return out


def sketch_hit(sketch, point, tol=None):
    """(geo index, point pos) of the sketch geometry under point (global): an end point (1, 2), a
    centre (3) or the curve itself (0). None when nothing of the sketch is near."""
    pl = _plane(sketch)
    local = pl.inverse().multVec(point)
    local.z = 0
    best = None
    try:
        size = max(sketch.Shape.BoundBox.DiagonalLength, 1.0)
    except Exception:
        size = 10.0
    tol = tol or max(0.02 * size, 0.5)
    for i, geo in enumerate(sketch.Geometry):
        try:
            if sketch.getConstruction(i):
                continue
        except Exception as _fw_err:
            _fw_log("featuredrag.py:492", _fw_err)
        for pos in (1, 2, 3):
            try:
                v = sketch.getPoint(i, pos)
            except Exception:
                continue
            d = (v - local).Length
            if d < tol and (best is None or d < best[0] - 1e-9 or (best[2] == 0 and d < tol)):
                best = (d, i, pos)
        try:
            d = geo.toShape().distToShape(Part_vertex(local))[0]
        except Exception:
            continue
        if d < tol * 0.5 and (best is None or (best[2] == 0 and d < best[0])):
            best = (d, i, 0)
    return None if best is None else (best[1], best[2])


def Part_vertex(v):
    import Part
    return Part.Vertex(v)


def drag_geometry(sketch, hit, plane, before, now):
    """Moves the picked point or curve of sketch, keeping its relations, as the pointer goes
    from before to now (global points on the sketch plane)."""
    geo, pos = hit
    inv = plane.inverse()
    a, b = inv.multVec(before), inv.multVec(now)
    a.z = b.z = 0
    if pos == 0:
        sketch.moveGeometry(geo, 0, b - a, True)
    else:
        sketch.moveGeometry(geo, pos, b, False)


def _unkeys():
    try:
        from . import events
        events.unregister("featuredrag-keys")
    except Exception as _fw_err:
        _fw_log("featuredrag.py:533", _fw_err)


_FILTER = []


def install():
    if _FILTER:
        return
    _FILTER.append(_Filter())
    try:
        from . import events
        events.register("featuredrag", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove,
                                        QtCore.QEvent.MouseButtonRelease), _FILTER[0].eventFilter)
    except ImportError:
        QtWidgets.QApplication.instance().installEventFilter(_FILTER[0])
