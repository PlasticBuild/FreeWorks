# SPDX-License-Identifier: LGPL-2.1-or-later
"""Move a sketch with a scene-graph dragger, preserving attachment and undo.

Dragger translations are measured in the scaled coordinate system used to display the
handles. Sketch placements, meanwhile, may be relative to a body or an attachment.
Each drag therefore captures its starting placement and converts the global movement
into the frame of the property being changed.
"""

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
from pivy import coin


class SketchDrag:
    def __init__(self, sketch, on_change=None):
        self.sketch = sketch
        self.on_change = on_change
        self._undo = []
        self._drag = None
        self._last_recompute = 0.0
        self._removed = False

        self._size = max(10.0, 0.25 * sketch.Shape.BoundBox.DiagonalLength)
        self._scene = Gui.ActiveDocument.ActiveView.getSceneGraph()
        self._root = coin.SoSeparator()
        self._position = coin.SoTranslation()
        self._scale = coin.SoScale()
        self._dragger = coin.SoDragPointDragger()       # translate only (a transformer's rotate/scale handles would do nothing)

        self._scale.scaleFactor.setValue(self._size, self._size, self._size)
        self._root.addChild(self._position)
        self._root.addChild(self._scale)
        self._root.addChild(self._dragger)

        # Keep the Python callback objects alive for as long as Coin can call them.
        self._start_callback = self._on_start
        self._motion_callback = self._on_motion
        self._finish_callback = self._on_finish
        self._dragger.addStartCallback(self._start_callback)
        self._dragger.addMotionCallback(self._motion_callback)
        self._dragger.addFinishCallback(self._finish_callback)

        self._anchor()
        self._scene.addChild(self._root)

    def _anchor(self):
        """Put the handles at the sketch and clear their accumulated translation."""
        point = self.sketch.getGlobalPlacement().Base
        self._dragger.translation.setValue(0.0, 0.0, 0.0)
        self._position.translation.setValue(point.x, point.y, point.z)

    def _snapshot(self):
        attached = self.sketch.MapMode != "Deactivated"
        name = "AttachmentOffset" if attached else "Placement"
        placement = App.Placement(getattr(self.sketch, name))

        # Global placement includes any enclosing body transform. Removing the
        # property's rotation leaves the world rotation of its parent frame.
        world_rotation = self.sketch.getGlobalPlacement().Rotation
        frame_rotation = world_rotation.multiply(placement.Rotation.inverted())
        return name, placement, frame_rotation.inverted()

    def _begin(self):
        snapshot = self._snapshot()
        name, placement, _ = snapshot
        self._undo.append((name, App.Placement(placement)))
        return snapshot

    def _move(self, snapshot, global_delta):
        name, original, world_to_frame = snapshot
        local_delta = world_to_frame.multVec(global_delta)
        placement = App.Placement(original)
        placement.Base = original.Base + local_delta
        setattr(self.sketch, name, placement)

    def _notify(self):
        self.sketch.Document.recompute()
        if self.on_change is not None:
            try:
                self.on_change(self.sketch)
            except Exception as e:
                App.Console.PrintLog("FreeCAD dragsketch: %s\n" % e)

    def _dragger_delta(self):
        value = self._dragger.translation.getValue()
        return App.Vector(
            value[0] * self._size,
            value[1] * self._size,
            value[2] * self._size,
        )

    def _on_start(self, *args):
        try:
            self._drag = self._begin()
            self._last_recompute = 0.0
        except Exception as e:
            self._drag = None
            App.Console.PrintLog("FreeCAD dragsketch: %s\n" % e)

    def _on_motion(self, *args):
        try:
            if self._drag is None:
                return
            self._move(self._drag, self._dragger_delta())
            now = time.monotonic()
            if now - self._last_recompute >= 0.1:
                self._last_recompute = now
                self._notify()
        except Exception as e:
            App.Console.PrintLog("FreeCAD dragsketch: %s\n" % e)

    def _on_finish(self, *args):
        try:
            if self._drag is None:
                return
            self._move(self._drag, self._dragger_delta())
            self._drag = None
            try:
                self._notify()
            finally:
                self._anchor()
        except Exception as e:
            self._drag = None
            App.Console.PrintLog("FreeCAD dragsketch: %s\n" % e)

    def drag_by(self, vector):
        """Apply one global translation, recording it as one undoable drag."""
        snapshot = self._begin()
        self._move(snapshot, vector)
        try:
            self._notify()
        finally:
            self._anchor()

    def undo(self):
        if not self._undo:
            return False
        name, placement = self._undo.pop()
        setattr(self.sketch, name, App.Placement(placement))
        try:
            self._notify()
        finally:
            self._anchor()
        return True

    def can_undo(self):
        return bool(self._undo)

    def remove(self):
        """Remove the handles without changing the sketch."""
        if self._removed:
            return
        self._removed = True
        try:
            if self._scene.findChild(self._root) >= 0:
                self._scene.removeChild(self._root)
        except (RuntimeError, ReferenceError) as _fw_err:
            _fw_log("dragsketch.py:172", _fw_err)
