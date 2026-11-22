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

import Part

from . import geom
from . import inference as I
from . import invalid
from . import snap as S
from . import relations as R
from . import topology as T
from .scene import Scene
from .cursor import drag_cursor, drag_tool_cursor, Tail, MERGE, ON_EDGE
from .toolbase import ViewMath, active as tool_active, GENERAL_GROUP, param_bool, other_buttons, preselected_subs

# Decisions that are a drop target (findDropTarget: a point candidate, else the nearest curve or axis)
TARGET_WINNERS = (S.SKETCH_POINT, S.MIDPOINT, S.QUADRANT, S.INTERSECTION, S.SKETCH_CURVE, S.AXIS)
GRID_WINNERS = (S.GRID, S.AXIS_GRID)
DRAG_STEP = "Drag Point"  # FreeCAD's own undo name for the drop (translated in the UI)


def no_targets(sketch, geo, pos):
    """Geo ids that offer no drop target for point pos of geo: its own geometry, geometry whose
    points are held to it (they move along), and curves it already lies on (a relation there
    would over-define the sketch). The axes count when the point lies on them."""
    out = {geo}
    joins = T.Joins(sketch, with_curves=False)
    for g in range(sketch.GeometryCount):
        for p in (I.START, I.END):
            if joins.joined(geo, pos, g, p):
                out.add(g)
    for c in sketch.Constraints:
        if c.Type == "Coincident" or (c.Type in ("Tangent", "Perpendicular") and c.FirstPos != I.NONE
                                      and c.SecondPos != I.NONE):
            if (c.First, c.FirstPos) == (geo, pos):
                out.add(c.Second)
            elif (c.Second, c.SecondPos) == (geo, pos):
                out.add(c.First)
        elif c.Type == "PointOnObject" and (c.First, c.FirstPos) == (geo, pos):
            out.add(c.Second)
    return out


def is_internal(sketch, geo):
    """Internal geometry of an ellipse or B-spline (axes, poles): FreeCAD moves those its own way."""
    return any(c.Type == "InternalAlignment" and c.First == geo for c in sketch.Constraints)


def preselected_point(sketch):
    """(geo, pos) of the sketch point under the pointer, or None (also for the origin, the axes
    and external geometry, which cannot be dragged)."""
    subs = preselected_subs(sketch)
    sub = subs[0] if subs else ""
    if not sub.startswith("Vertex"):
        return None
    try:
        geo, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
    except Exception:
        return None
    if geo < 0 or pos == I.NONE or is_internal(sketch, geo):
        return None
    return geo, pos


def vertex_names(sketch):
    """{(geo, pos): "VertexN"} of the sketch, for preselecting a target."""
    out = {}
    for i in range(3 * sketch.GeometryCount + 1):
        try:
            geo, pos = sketch.getGeoVertexIndex(i)
        except Exception:
            break
        if geo == I.GEO_UNDEF or geo < -2:
            break
        out[(geo, pos)] = "Vertex%d" % (i + 1)
    return out


def drop_suggestions(snapper, d):
    """The relations of a drop on decision d (addDropRelations): the same as a sketch tool's
    end point gets there."""
    return R.from_decision(snapper, d, R.VERTEX, (0.0, 0.0)) or []


def drag_ghost_wanted():
    """Mod/Sketcher/General DragGhost (package 35): the faint copy and the badge while dragging."""
    from . import sysopts       # Options > Sketch > Ghost image on drag (fix57)
    return param_bool(GENERAL_GROUP, "DragGhost", True) and sysopts.on(sysopts.GHOST_ON_DRAG)


def preselected_edge(sketch):
    """The sketch curve FreeCAD preselects ("EdgeN") as a geo index, else None."""
    try:
        from .toolbase import preselected_subs     # a sketch in a Body counts too (Body + "Sketch.Edge1")
        subs = preselected_subs(sketch)
        if not subs:
            return None
        name = subs[0]
    except Exception:
        return None
    if not name.startswith("Edge"):
        return None
    try:
        return int(name[4:]) - 1
    except ValueError:
        return None


def moving_geos(sketch, geo, pos):
    """The curves a drag moves: the curve itself, and for a point its Coincident partners."""
    out = [geo]
    if pos is None or pos == I.NONE:
        return out
    try:
        constraints = sketch.Constraints
    except Exception:
        return out
    for c in constraints:
        if c.Type not in ("Coincident", "Tangent", "Perpendicular") or c.FirstPos == I.NONE or c.SecondPos == I.NONE:
            continue
        if (c.First, c.FirstPos) == (geo, pos) and c.Second not in out and c.Second >= 0:
            out.append(c.Second)
        elif (c.Second, c.SecondPos) == (geo, pos) and c.First not in out and c.First >= 0:
            out.append(c.First)
    return out


def ghost_outlines(sketch, geo, pos):
    out = []
    for g in moving_geos(sketch, geo, pos):
        try:
            line = outline(sketch.Geometry[g])
        except Exception:
            line = []
        if line:
            out.append(line)
    return out


def outline(g):
    """Points along a line, circle or arc (sketch coordinates) for the highlight, [] otherwise."""
    if g is None:
        return []
    if isinstance(g, Part.LineSegment):
        return [(g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)]
    if isinstance(g, Part.ArcOfCircle):
        a0, a1 = g.FirstParameter, g.LastParameter
        return geom.arc_points((g.Center.x, g.Center.y), g.Radius, a0, a1 - a0)
    if isinstance(g, Part.Circle):
        return geom.circle_points((g.Center.x, g.Center.y), g.Radius)
    return []


class DragSession(ViewMath):
    """One left press on a point of the edited sketch, until its release."""

    def __init__(self, gdoc, sketch, geo, pos, start):
        self.setup_view(gdoc, sketch)
        self.geo, self.pos = geo, pos
        self.start = start               # global QPoint of the press
        self.dragged = False
        self.target = None               # the snap Decision the point will be dropped on
        self.snapper = S.Snapper(sketch, grid_size=self._grid_size, view_box=self._view_box)
        self.snapper.excluded = no_targets(sketch, geo, pos) if pos is not None else {geo}
        self.scene = None
        self.ghost = ghost_outlines(sketch, geo, pos) if drag_ghost_wanted() else []
        self.ghost_shown = False
        self.log = []                    # (winner, position) per move, for tests
        self.result = None               # what finish() did, for tests
        self.names_before = list(sketch.Document.UndoNames)
        # a whole curve being dragged (pos None): watch its start, or its centre for a circle
        # (getPoint(geo, None) raised TypeError, tester SK9-02/05/15)
        self.watch_pos = pos
        if pos is None:
            g = sketch.Geometry[geo] if 0 <= geo < len(sketch.Geometry) else None
            self.watch_pos = I.MID if isinstance(g, (Part.Circle, Part.Ellipse)) else I.START
        self.point_before = sketch.getPoint(geo, self.watch_pos)
        self.tries = 0

    # --- while the button is down ------------------------------------------------------------
    def moved_to(self, global_point):
        if not self.dragged and (global_point - self.start).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            self.dragged = True
            self.show_ghost()
        if self.dragged:
            self.update()
            invalid.drag_moved(self, global_point)

    def show_ghost(self):
        """A faint copy of what moves stays where the drag started, and the pointer gets the
        drag badge (package 35; the copy is drawn over the sketch, so only where something has
        moved away does it show)."""
        if not drag_ghost_wanted():
            return
        if self.scene is None:
            self.scene = Scene(self.view, self.matrix, self.ratio)
        self.scene.lines("ghost", self.ghost)
        try:
            self.viewport.setCursor(drag_cursor(self.ratio))
            self.ghost_shown = True
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/dragwatch.py:230", _fw_err)

    def update(self):
        if self.pos is None:
            return   # a curve drag: the ghost only
        p, px = self.pointer()
        if p is None:
            return
        d = self.snapper.snap(p, px, allow_point=True, allow_edge=True, allow_angle=False, allow_grid=False)
        self.target = d if d.winner in TARGET_WINNERS else None
        if self.target is None and self.snapper.p.grid:
            # Snap to grid on: a dragged point with nothing under it lands on the grid, as one
            # being sketched does (fix66)
            g = self.snapper.snap(p, px, allow_point=False, allow_edge=False, allow_angle=False, allow_grid=True)
            self.snapper.last = d       # the markers stay those of the curves passed over
            if g.winner in GRID_WINNERS:
                self.target = d = g
        self.log.append((d.winner, d.position))
        self.show()

    def show(self):
        """The target lights up in the preselection colour, with a marker where the point goes;
        the midpoint and quadrants of the curve passed over as hollow markers (showDropTarget).
        Drawn by the watcher itself: a preselection set from here would make FreeCAD drag the
        target instead of the point (it reads the preselection when its drag starts)."""
        if self.scene is None:
            self.scene = Scene(self.view, self.matrix, self.ratio)
        hints, active = self.snapper.markers(self.snapper.last)
        if self.target is None:
            active = []
        self.scene.points("hints", hints)
        self.scene.points("quadrants", getattr(self.snapper, "quadrant_marks", []))
        self.scene.points("active", active)
        lines, points = [], []
        d = self.target
        if d is not None and d.geo != I.GEO_UNDEF and d.geo not in (I.H_AXIS, I.V_AXIS):
            if d.winner == S.SKETCH_POINT:
                points.append(d.position)
            else:
                lines.append(outline(self.snapper.geometry(d.geo)))
                if d.winner == S.INTERSECTION and d.geo2 != I.GEO_UNDEF:
                    lines.append(outline(self.snapper.geometry(d.geo2)))
        self.scene.lines("hover", [l for l in lines if l])
        self.scene.points("hover", points)
        self.show_glyph(d)

    def show_glyph(self, d):
        ""

        glyph = None
        if d is not None and d.geo != I.GEO_UNDEF and d.geo not in (I.H_AXIS, I.V_AXIS):
            glyph = MERGE if d.winner == S.SKETCH_POINT else ON_EDGE if d.winner != S.INTERSECTION else None
        try:
            if getattr(self, "tail", None) is None:
                if glyph is None:
                    return None
                self.tail = Tail(self.viewport, drag_tool_cursor(self.ratio))
            self.tail.show([glyph] if glyph else [])
            self.glyph = glyph
        except Exception as _fw_err:
            _fw_log("fwsketch/dragwatch.py:show_glyph", _fw_err)
        return glyph

    def close(self):
        tail = getattr(self, "tail", None)
        if tail is not None:
            tail.close()
            self.tail = None
        if self.scene is not None:
            self.scene.remove()
            self.scene = None
        if self.ghost_shown:
            self.ghost_shown = False
            try:
                self.viewport.unsetCursor()
            except RuntimeError as _fw_err:
                _fw_log("fwsketch/dragwatch.py:283", _fw_err)

    # --- after the drop -----------------------------------------------------------------------
    def dropped(self):
        """FreeCAD has handled the release: the point moved, or an undo step came in."""
        sk = self.sketch
        try:
            if (sk.getPoint(self.geo, self.watch_pos) - self.point_before).Length > 1e-9:
                return True
        except Exception:
            return True
        return list(sk.Document.UndoNames) != self.names_before

    def drop_free(self):
        ""


        sk = self.sketch
        x, y = self.log[-1][1]
        try:
            now = sk.getPoint(self.geo, self.pos)
        except Exception:
            return False
        if (now - App.Vector(x, y, 0)).Length < 1e-7:
            return False
        doc = sk.Document
        names = list(doc.UndoNames)
        redo = bool(names) and names != self.names_before \
            and names[0] in (DRAG_STEP, QtCore.QCoreApplication.translate("Command", DRAG_STEP))
        if not redo:
            return False
        doc.undo()
        doc.openTransaction(names[0])
        try:
            sk.moveGeometries([(self.geo, self.pos)], App.Vector(x, y, 0))
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        self.result = ([], True)
        return True

    def finish(self):
        """FreeCAD has dropped the point: take its step back and do the move again, onto the
        target and with the relations, as one undo step (commitDragMove + addDropRelations).
        Returns (relations kept, FreeCAD's step was redone)."""
        d = self.target
        sk = self.sketch
        doc = sk.Document
        names = list(doc.UndoNames)
        redo = bool(names) and names != self.names_before \
            and names[0] in (DRAG_STEP, QtCore.QCoreApplication.translate("Command", DRAG_STEP))
        dropped_there = False
        if redo:
            try:
                # fix260: FreeCAD's own drop already brought the point onto the target: it can move
                dropped_there = (sk.getPoint(self.geo, self.pos) - App.Vector(d.position[0], d.position[1], 0)).Length < 1e-4
            except Exception:
                dropped_there = False
            doc.undo()
            # fix260: the solver has to be set up again after the Undo, else moveGeometries moves
            # nothing (a fully defined sketch + a free line: the drop looked "held", no Coincident)
            try:
                sk.solve()
            except Exception as _fw_err:
                _fw_log("fwsketch/dragwatch.py: solve after undo", _fw_err)
        doc.openTransaction(names[0] if redo else DRAG_STEP)
        try:
            target = App.Vector(d.position[0], d.position[1], 0)
            try:
                start = sk.getPoint(self.geo, self.pos)
            except Exception:
                start = None
            sk.moveGeometries([(self.geo, self.pos)], target)
            try:
                now = sk.getPoint(self.geo, self.pos)
                held = start is not None and (now - start).Length < 1e-6 and (target - start).Length > 1e-4
            except Exception:
                held = False
            if held and dropped_there:
                # fix260: after FreeCAD's own drop is taken back, moveGeometries can leave a point
                # that FreeCAD itself had just moved (a free line's end dropped on a fully defined

                held = False
            if held:
                # the point is held where it is (fully defined): the move stays as FreeCAD's own drop
                # (nothing moved), with no relation, so nothing else is pulled over to it
                # (auto relations review 11-19)
                doc.commitTransaction()
                doc.recompute()
                self.result = (0, redo)
                return self.result
            pending = []
            from .toolbase import automatic_relations, prune_unused_references
            e0 = len(sk.ExternalGeo)
            if automatic_relations():
                R.generate(pending, R.resolve_model(self.snapper, drop_suggestions(self.snapper, d)),
                           self.geo, self.pos, self.snapper.geometry)
            kept = R.add_without_redundancy(sk, pending, avoid_redundant=True)
            prune_unused_references(sk, e0)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
        doc.recompute()
        self.result = (kept, redo)
        return self.result


class DragWatcher(QtCore.QObject):
    ""

    def __init__(self):
        super().__init__()
        self.session = None
        self.frozen = None               # a press on a fully defined entity: its drag moves are kept from FreeCAD
        self.last = None                 # the last finished session, for tests
        self._app = QtWidgets.QApplication.instance()
        from . import appevents
        appevents.listen(self, (QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)

    def stop(self):
        try:
            from . import appevents
            appevents.stop(self)
        except RuntimeError as _fw_err:
            _fw_log("fwsketch/dragwatch.py:372", _fw_err)
        self._drop_session()

    def _drop_session(self):
        s, self.session = self.session, None
        if s is not None:
            s.close()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide on Windows can hand a filter a stale wrapper (a QWidgetItem) instead
        # an exception out of a Qt override takes FreeCAD down: keep them in here
        try:
            return self._filter(obj, event)
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD drag to connect: %s" % traceback.format_exc())
            self.session = None
            return False

    @staticmethod
    def _global(event):
        try:
            return event.globalPosition().toPoint()
        except AttributeError:
            return event.globalPos()

    def _filter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # a stale wrapper (a QWidgetItem) when a page re-lays its rows
        t = event.type()
        if self.frozen is not None:

            # place and commit an empty Drag Point / Drag Curve step that also wipes Redo; it never
            # sees the moves, so the press and release stay a plain click (the pick still works)
            if t == QtCore.QEvent.MouseMove and obj is self.frozen and (event.buttons() & QtCore.Qt.LeftButton):
                return True
            # (one press can come twice, to the viewport and then to its view: only a new press on
            # the viewport, a release or a move with the button up ends it)
            if t == QtCore.QEvent.MouseButtonRelease or (t == QtCore.QEvent.MouseButtonPress and obj is self.frozen) or \
                    (t == QtCore.QEvent.MouseMove and obj is self.frozen and not (event.buttons() & QtCore.Qt.LeftButton)):
                self.frozen = None
            if t != QtCore.QEvent.MouseButtonPress or self.frozen is not None:
                return False
        s = self.session
        if s is None:
            if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton \
                    and tool_active() is None:
                self._begin(obj, event)
            return False
        if t == QtCore.QEvent.MouseMove:
            if obj is s.viewport and not other_buttons(event):
                s.moved_to(self._global(event))
            return False
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            self.session = None
            if s.dragged:

                # until then; left picked, the next Smart Dimension would take it): after FreeCAD's drop
                QtCore.QTimer.singleShot(60, lambda: _unpick(s.sketch))
            if s.dragged and s.pos is not None:
                # package 37: an invalid result is taken back; else the drop target as before
                QtCore.QTimer.singleShot(0, lambda: self._after_drop(s))
            elif s.dragged and s.target is not None and not S.inference_suppressed():
                # after FreeCAD has handled this release and committed its own step
                QtCore.QTimer.singleShot(0, lambda: self._finish(s))
            else:
                s.close()
                self.last = s
            return False
        if t == QtCore.QEvent.KeyPress and isinstance(event, QtGui.QKeyEvent) and event.key() == QtCore.Qt.Key_Escape:
            self._drop_session()  # FreeCAD puts the point back
            return False
        if t == QtCore.QEvent.MouseButtonPress and event.button() != QtCore.Qt.LeftButton:
            self._drop_session()
            return False
        return False

    def _begin(self, obj, event):
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        if getattr(vp, "Object", None) is None or not vp.Object.isDerivedFrom("Sketcher::SketchObject"):
            return
        view = gdoc.ActiveView
        if not hasattr(view, "graphicsView"):
            return
        try:
            if obj is not view.graphicsView().viewport():
                return
        except RuntimeError:
            return
        sketch = vp.Object
        if fully_defined_pick(sketch):
            self.frozen = obj
            return
        point = preselected_point(sketch)
        if point is None:
            edge = preselected_edge(sketch)
            if edge is None or not drag_ghost_wanted():
                return
            point = (edge, None)   # FreeCAD drags the whole curve: the ghost and the badge only
        elif _drag_point_alone(sketch):
            # the cleared pick also cleared FreeCAD's point under the pointer: a move to the same
            # place finds it again before FreeCAD sees this press
            try:
                pos = event.position() if hasattr(event, "position") else QtCore.QPointF(event.pos())
                move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, pos, QtCore.QPointF(self._global(event)),
                                         QtCore.Qt.NoButton, QtCore.Qt.NoButton, event.modifiers())
                QtWidgets.QApplication.sendEvent(obj, move)
            except Exception as _fw_err:
                _fw_log("fwsketch/dragwatch.py: point alone move", _fw_err)
            if preselected_point(sketch) != point:
                return
        self.session = DragSession(gdoc, sketch, point[0], point[1], self._global(event))

    def _after_drop(self, s):
        if not s.dropped() and s.tries < 20:
            s.tries += 1
            QtCore.QTimer.singleShot(25, lambda: self._after_drop(s))
            return
        if invalid.drop_invalid(s):
            try:
                invalid.restore(s)
            finally:
                s.close()
                self.last = s
        elif s.target is not None and not S.inference_suppressed():
            self._finish(s)
        elif S.inference_suppressed() and s.log:
            try:
                s.drop_free()
            except Exception:
                import traceback
                App.Console.PrintError("FreeCAD drag with Ctrl: %s" % traceback.format_exc())
            finally:
                s.close()
                self.last = s
        else:
            s.close()
            self.last = s

    def _finish(self, s):
        if not s.dropped() and s.tries < 20:
            # FreeCAD's drop can come a moment later (the view's event queue): wait for it
            s.tries += 1
            QtCore.QTimer.singleShot(25, lambda: self._finish(s))
            return
        try:
            s.finish()
        except Exception:
            import traceback
            App.Console.PrintError("FreeCAD drag to connect: %s" % traceback.format_exc())
        finally:
            s.close()
            self.last = s


def fully_defined_pick(sketch):
    ""
    try:
        picked = preselected_point(sketch)
        geo = picked[0] if picked is not None else preselected_edge(sketch)
        if geo is None or geo < 0:
            return False             # the origin and the axes are FreeCAD's own (they do not drag)
        if getattr(sketch, "FullyConstrained", False):
            return True
        if not hasattr(sketch, "getGeometryWithDependentParameters"):
            return False
        return geo not in {g for g, _p in sketch.getGeometryWithDependentParameters()}
    except Exception as _fw_err:
        _fw_log("fwsketch/dragwatch.py:fully defined", _fw_err)
        return False


def _drag_point_alone(sketch):
    ""



    try:
        sels = [s for s in Gui.Selection.getSelectionEx() if s.Object == sketch]
        if not sels:
            return False
        subs = preselected_subs(sketch)
        if not subs or any(subs[0] in s.SubElementNames for s in sels):
            return False
        Gui.Selection.clearSelection()
        return True
    except Exception as _fw_err:
        _fw_log("fwsketch/dragwatch.py: point alone", _fw_err)
        return False


def _unpick(sketch):
    try:
        if any(sel.Object == sketch for sel in Gui.Selection.getSelectionEx()):
            Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("fwsketch/dragwatch.py:506", _fw_err)


_watcher = None


def start():
    """Install the watcher once; returns it."""
    global _watcher
    if _watcher is None:
        _watcher = DragWatcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None


def watcher():
    return _watcher
