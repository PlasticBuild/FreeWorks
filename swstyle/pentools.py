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

import json
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

V = App.Vector
TITLE = "Pen Sketch"
PROP = "FreeWorksInk"
MODES = ("Draw", "Eraser", "Select", "Power Modify", "Ruler", "Protractor")
PICK_PX = 10            # how near the pointer counts, in screen pixels
GUIDE_PX = 14           # how near a guide ink has to stay to follow it


# Auto Convert to Entities
SETTINGS = {"FreeWorks_PenTouch": ("Touch", "PenTouch", True,
                                   "Draws ink with a finger on a touch screen too (off: pen and mouse only)."),
            "FreeWorks_PenAutoShape": ("Auto Convert to Shape", "PenAutoShape", False,
                                       "Each stroke becomes lines, arcs or circles as it is drawn."),
            "FreeWorks_PenAutoEntities": ("Auto Convert to Entities", "PenAutoEntities", False,
                                          "Each stroke becomes a spline as it is drawn."),
            # the Sketch Ink tab's third switch: each stroke becomes the sketch entity it looks like (a line,
            # an arc, a circle), else a spline
            "FreeWorks_PenAutoSketchEntities": ("Auto Sketch Entities", "PenAutoSketchEntities", False,
                                                "Each stroke becomes the sketch entity it looks like (line, arc, "
                                                "circle), else a spline, as it is drawn.")}
AUTO = ("PenAutoShape", "PenAutoEntities", "PenAutoSketchEntities")


def params():
    from . import paths
    return App.ParamGet(paths.PARAM_PATH + "/Pen")


def setting(key):
    for _cmd, (_text, name, default, _tip) in SETTINGS.items():
        if name == key:
            return params().GetBool(name, default)
    return False


def ink_colour():
    c = params().GetUnsigned("InkColor", 0x1A4DE6FF)
    return ((c >> 24) & 255) / 255.0, ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0


def ink_width():
    return max(1, params().GetInt("InkWidth", 2))


COMMANDS = {"FreeWorks_PenSketch": ("Pen Sketch", "Draw", "Sketcher_CreateBSpline",
                                    "Draws ink in the sketch with the mouse or a pen; convert it to sketch entities."),
            "FreeWorks_PenDraw": ("Draw", "Draw", "Sketcher_CreateBSpline", "Draws ink in the sketch."),
            "FreeWorks_PenEraser": ("Eraser", "Eraser", "edit-delete", "Rubs out the ink you drag over."),
            "FreeWorks_PenSelect": ("Select", "Select", "edit-select-box", "Picks ink: click a stroke."),
            "FreeWorks_PenPowerModify": ("Power Modify", "Power Modify", "edit-delete",
                                         "Scratch back and forth over sketch entities or ink to delete them."),
            "FreeWorks_PenRuler": ("Ruler", "Ruler", "umf-measurement",
                                   "Lays a ruler (drag along it): ink drawn along it comes out straight."),
            "FreeWorks_PenProtractor": ("Protractor", "Protractor", "Sketcher_CreateCircle",
                                        "Lays a protractor (drag from its center out): ink along its rim comes out "
                                        "round."),
            "FreeWorks_PenConvertToShape": ("Convert to Shape", None, "Sketcher_CreatePolyline",
                                            "Turns the ink (the picked ink, else all) into lines, arcs and circles."),
            "FreeWorks_PenConvertToEntities": ("Convert to Entities", None, "Sketcher_CreateBSpline",
                                               "Turns the ink (the picked ink, else all) into splines.")}


# --------------------------------------------------------------------------- ink kept in the sketch
def ink(sketch):
    """The sketch's ink: [[(x, y), ...], ...]."""
    try:
        return [[(float(x), float(y)) for x, y in s] for s in json.loads(getattr(sketch, PROP, "") or "[]")]
    except Exception:
        return []


def set_ink(sketch, strokes):
    if not hasattr(sketch, PROP):
        sketch.addProperty("App::PropertyString", PROP, "FreeCAD", "Pen Sketch ink, not yet converted")
        try:
            sketch.setEditorMode(PROP, 2)
        except Exception as _fw_err:
            _fw_log("pentools.py:108", _fw_err)
    setattr(sketch, PROP, json.dumps([[[round(x, 6), round(y, 6)] for x, y in s] for s in strokes]))


# --------------------------------------------------------------------------- geometry
# Power Modify does more than delete (fwsketch-fix164)
COMMANDS["FreeWorks_PenPowerModify"] = COMMANDS["FreeWorks_PenPowerModify"][:3] + (
    "Edits the sketch with pen strokes: scratch to delete, stroke across to trim, an X to split, two strokes side "
    "by side to offset, an arc or a line on a corner for a fillet or a chamfer.",)


def _dist_seg(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


def _near_stroke(stroke, p, tol):
    if len(stroke) == 1:
        return math.hypot(stroke[0][0] - p[0], stroke[0][1] - p[1]) <= tol
    return any(_dist_seg(p, a, b) <= tol for a, b in zip(stroke[:-1], stroke[1:]))


def _seg_seg(a, b, c, d):
    """The least distance between segments ab and cd (0 when they cross)."""
    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])
    d1, d2, d3, d4 = cross(c, d, a), cross(c, d, b), cross(a, b, c), cross(a, b, d)
    if (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0) and d1 * d2 < 0 and d3 * d4 < 0:
        return 0.0
    return min(_dist_seg(a, c, d), _dist_seg(b, c, d), _dist_seg(c, a, b), _dist_seg(d, a, b))


def _near_path(stroke, a, b, tol):
    """True when the eraser's move from a to b passes within tol of the stroke (a fast drag sends few moves)."""
    if len(stroke) == 1:
        return _dist_seg(stroke[0], a, b) <= tol
    return any(_seg_seg(a, b, c, d) <= tol for c, d in zip(stroke[:-1], stroke[1:]))


def follow_ruler(stroke, ruler, tol):
    """The stroke straight along the ruler when it stays within tol of it, else as drawn."""
    (ax, ay), (bx, by) = ruler
    dx, dy = bx - ax, by - ay
    L = math.hypot(dx, dy)
    if L < 1e-9 or len(stroke) < 2:
        return stroke
    ux, uy = dx / L, dy / L
    if any(abs((x - ax) * uy - (y - ay) * ux) > tol for x, y in stroke):
        return stroke
    t0 = (stroke[0][0] - ax) * ux + (stroke[0][1] - ay) * uy
    t1 = (stroke[-1][0] - ax) * ux + (stroke[-1][1] - ay) * uy
    return [(ax + ux * t0, ay + uy * t0), (ax + ux * t1, ay + uy * t1)]


def follow_protractor(stroke, protractor, tol):
    """The stroke on the protractor's rim when it stays within tol of it, else as drawn."""
    (cx, cy), r = protractor
    if r < 1e-9 or len(stroke) < 2:
        return stroke
    if any(abs(math.hypot(x - cx, y - cy) - r) > tol for x, y in stroke):
        return stroke
    angles = [math.atan2(y - cy, x - cx) for x, y in stroke]
    out, a = [], angles[0]
    for i, b in enumerate(angles):
        if i:
            a += ((b - angles[i - 1] + math.pi) % (2 * math.pi)) - math.pi
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return out


def _rdp(points, eps):
    if len(points) < 3:
        return list(points)
    a, b = points[0], points[-1]
    worst, k = -1.0, 0
    for i in range(1, len(points) - 1):
        d = _dist_seg(points[i], a, b)
        if d > worst:
            worst, k = d, i
    if worst <= eps:
        return [a, b]
    return _rdp(points[:k + 1], eps)[:-1] + _rdp(points[k:], eps)


def _length(points):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points[:-1], points[1:]))


def shapes(stroke):
    """Convert to Shape: what a stroke is, as sketchink shapes: one line, circle or arc; a stroke with
    corners as the lines between them (joined end to end, closed when its ends meet)."""
    from . import sketchink
    pts = [V(x, y, 0) for x, y in stroke]
    one = sketchink.recognise(pts)
    if one is None or one[0] != "spline":
        return [one] if one is not None else []
    L = _length(stroke)
    corners = _rdp(stroke, 0.04 * L)
    closed = math.hypot(stroke[0][0] - stroke[-1][0], stroke[0][1] - stroke[-1][1]) <= sketchink.CLOSED * L
    if closed and len(corners) > 2:
        corners[-1] = corners[0]
    if 2 <= len(corners) <= 13:
        # straight between the corners: lines
        ok = True
        for a, b in zip(corners[:-1], corners[1:]):
            seg = math.hypot(b[0] - a[0], b[1] - a[1])
            if seg < 1e-9:
                ok = False
                break
        if ok:
            return [("line", V(a[0], a[1], 0), V(b[0], b[1], 0)) for a, b in zip(corners[:-1], corners[1:])]
    return [one]


PM_WAIT_MS = 700        # Power Modify: how long a stroke across an entity waits for a second stroke (X, parallel)


def _chord_dir(stroke):
    a, b = stroke[0], stroke[-1]
    n = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / n, (b[1] - a[1]) / n) if n > 1e-12 else None


def _bulge(stroke):
    """Largest distance of the stroke from its chord, as a share of its length."""
    L = _length(stroke)
    if L < 1e-12:
        return 0.0
    return max(_dist_seg(p, stroke[0], stroke[-1]) for p in stroke) / L


def crossings(sketch, stroke):
    """[(geo, (x, y))]: where the stroke crosses the sketch's curves (points left out), in stroke order."""
    import Part
    path = [V(x, y, 0) for x, y in stroke]
    segs = [(k, Part.LineSegment(a, b)) for k, (a, b) in enumerate(zip(path[:-1], path[1:])) if (b - a).Length > 1e-9]
    out = []
    for g, geo in enumerate(sketch.Geometry):
        if geo.TypeId == "Part::GeomPoint":
            continue
        seen = []
        for k, seg in segs:
            try:
                hits = seg.intersect(geo)
            except Exception as _fw_err:
                _fw_log("pentools.py:258", _fw_err)
                continue
            for h in hits:
                q = (h.X, h.Y) if hasattr(h, "X") else (h.x, h.y)
                if all(math.hypot(q[0] - r[0], q[1] - r[1]) > 1e-6 for _, r in seen):
                    seen.append((k + math.hypot(q[0] - stroke[k][0], q[1] - stroke[k][1]) * 1e-6, q))
        out.extend((g, q) for _, q in sorted(seen))
    return out


def _nearest_line(sketch, p, tol):
    best = None
    for g, geo in enumerate(sketch.Geometry):
        if geo.TypeId != "Part::GeomLineSegment" or sketch.getConstruction(g):
            continue
        d = _dist_seg(p, (geo.StartPoint.x, geo.StartPoint.y), (geo.EndPoint.x, geo.EndPoint.y))
        if d <= tol and (best is None or d < best[0]):
            best = (d, g)
    return best[1] if best else None


def corner_gesture(sketch, stroke, tol):
    ""



    from . import sketchink
    if len(stroke) < 3:
        return None
    a, b = stroke[0], stroke[-1]
    ga, gb = _nearest_line(sketch, a, tol), _nearest_line(sketch, b, tol)
    if ga is None or gb is None or ga == gb:
        return None
    corner = None
    for i in (1, 2):
        for j in (1, 2):
            p, q = sketch.getPoint(ga, i), sketch.getPoint(gb, j)
            if (p - q).Length < 1e-6:
                corner = (p.x, p.y)
    if corner is None:
        return None
    da = math.hypot(a[0] - corner[0], a[1] - corner[1])
    db = math.hypot(b[0] - corner[0], b[1] - corner[1])
    if da < 1e-9 or db < 1e-9:
        return None
    if _bulge(stroke) <= 0.06:
        return ("chamfer", corner, (da, db, ga))
    fit = sketchink._circle([V(x, y, 0) for x, y in stroke]) if len(stroke) >= 5 else None
    if fit is None or fit[2] > 0.15:
        return None
    # the fillet that touches both lines where the stroke meets them: its radius from the corner angle
    ua = sketch.getPoint(ga, 1) - V(corner[0], corner[1], 0)
    if ua.Length < 1e-9:
        ua = sketch.getPoint(ga, 2) - V(corner[0], corner[1], 0)
    ub = sketch.getPoint(gb, 1) - V(corner[0], corner[1], 0)
    if ub.Length < 1e-9:
        ub = sketch.getPoint(gb, 2) - V(corner[0], corner[1], 0)
    phi = ua.getAngle(ub)
    radius = 0.5 * (da + db) * math.tan(phi / 2.0)
    return ("fillet", corner, radius) if radius > 1e-9 else None


def convert(sketch, strokes, as_shapes):
    """Adds the strokes to sketch (as shapes, else splines); the new geometry indices."""
    from . import sketchink
    import Sketcher
    made = []
    for stroke in strokes:
        if len(stroke) < 2:
            continue
        if as_shapes == "recognise":
            parts = [sketchink.recognise([V(x, y, 0) for x, y in stroke])]
        elif as_shapes:
            parts = shapes(stroke)
        else:
            pts = [V(x, y, 0) for x, y in stroke]
            parts = [("spline", pts)] if len(stroke) > 2 else [("line", pts[0], pts[-1])]
        idx = []
        for shape in parts:
            idx.append(sketchink.add(sketch, shape))
        # lines from one stroke join end to end
        lines = [(i, s) for i, s in zip(idx, parts) if s[0] == "line"]
        for (i, s), (j, t) in zip(lines[:-1], lines[1:]):
            if (s[2] - t[1]).Length < 1e-6:
                sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, j, 1))
        if len(lines) > 2 and (lines[-1][1][2] - lines[0][1][1]).Length < 1e-6:
            sketch.addConstraint(Sketcher.Constraint("Coincident", lines[-1][0], 2, lines[0][0], 1))
        made.extend(idx)
    return made


# --------------------------------------------------------------------------- the page
_page = None


def page():
    """The open Pen page, else None."""
    return _page if _page is not None and getattr(_page, "_alive", False) else None


def _page_class():
    from pivy import coin
    from . import overridedrag, sketchtoolpm

    class _Filter(QtCore.QObject):
        def __init__(self, owner):
            super().__init__()
            self.owner = owner
            from .fwsketch import appevents
            appevents.listen(self, (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseMove))   # one application filter (fix65)

        def stop(self):
            self.owner = None
            try:
                from .fwsketch import appevents
                appevents.stop(self)
            except Exception as _fw_err:
                _fw_log("pentools.py:373", _fw_err)

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
            try:
                return self._fw_filter263(obj, event)
            except Exception as exc:
                import FreeCAD
                FreeCAD.Console.PrintWarning("FreeCAD event filter pentools.py: %s\n" % exc)
                return False

        def _fw_filter263(self, obj, event):
            owner = self.owner
            try:
                if owner is None or not isinstance(event, QtCore.QEvent) or not isinstance(obj, QtWidgets.QWidget) \
                        or not obj.inherits("QOpenGLWidget"):
                    return False
                QE = QtCore.QEvent
                t = event.type()
                if t not in (QE.MouseButtonPress, QE.MouseMove, QE.MouseButtonRelease):
                    return False
                if t != QE.MouseMove and event.button() != QtCore.Qt.LeftButton:
                    return False
                if not setting("PenTouch") and event.source() == QtCore.Qt.MouseEventSynthesizedBySystem:
                    return False        # Touch off: a finger on the screen does not draw ink

                pos = event.position()
                p = overridedrag.local(owner.sketch, obj, pos)
                q = overridedrag.local(owner.sketch, obj, QtCore.QPointF(pos.x() + 1.0, pos.y()))
                owner.px = max((q - p).Length, 1e-9)
                if t == QE.MouseButtonPress:
                    owner.press((p.x, p.y))
                    return True
                if t == QE.MouseMove and owner.dragging:
                    owner.drag((p.x, p.y))
                    return True
                if t == QE.MouseButtonRelease and owner.dragging:
                    owner.release((p.x, p.y))
                    return True
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Pen Sketch: %s\n" % error)
            return False

    class PenPage(sketchtoolpm.ToolPage):
        TITLE = TITLE
        PIXMAP = "Sketcher_CreateBSpline"

        def build(self):
            self._alive = True
            self.mode = "Draw"
            self.strokes = ink(self.sketch)
            self.picked = set()
            self.ruler = None
            self.protractor = None
            self.current = None
            self.dragging = False
            self.px = 0.1
            g = self.group("Pen Tools")
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(2)
            self.buttons = {}
            for m in MODES:
                b = QtWidgets.QToolButton(g.body)
                b.setText(m)
                b.setCheckable(True)
                b.setObjectName("SWPen" + m.replace(" ", ""))
                b.setToolTip(COMMANDS["FreeWorks_Pen" + m.replace(" ", "")][3])
                b.clicked.connect(lambda checked=False, m=m: self.set_mode(m))
                self.buttons[m] = b
                row.addWidget(b)
            row.addStretch(1)
            g.content.addLayout(row)
            self.count = QtWidgets.QLabel("", g.body)
            self.count.setObjectName("SWPenCount")
            g.content.addWidget(self.count)
            c = self.group("Convert")
            for name, text, shapes_on in (("SWPenConvertShape", "Convert to Shape", True),
                                          ("SWPenConvertEntities", "Convert to Entities", False)):
                b = QtWidgets.QPushButton(text, c.body)
                b.setObjectName(name)
                b.clicked.connect(lambda checked=False, s=shapes_on: self.convert(s))
                c.content.addWidget(b)
            self.node = coin.SoSeparator()
            self._sets = {}
            for key, colour, width in (("ink", ink_colour(), ink_width()), ("picked", (1.0, 0.55, 0.0), ink_width() + 1),
                                       ("guide", (0.45, 0.45, 0.45), 1)):
                sep = coin.SoSeparator()
                style = coin.SoDrawStyle()
                style.lineWidth.setValue(width)
                col = coin.SoBaseColor()
                col.rgb.setValue(*colour)
                coords = coin.SoCoordinate3()
                lines = coin.SoLineSet()
                for child in (style, col, coords, lines):
                    sep.addChild(child)
                self.node.addChild(sep)
                self._sets[key] = (coords, lines)
            try:
                Gui.ActiveDocument.ActiveView.getSceneGraph().addChild(self.node)
            except Exception as _fw_err:
                _fw_log("pentools.py:474", _fw_err)
            self.filter = _Filter(self)
            self.set_mode("Draw")

        # ---------------------------------------------------------- state
        def set_mode(self, mode):
            if mode in ("Ruler", "Protractor") and self.mode == mode:
                # the button again: the guide goes
                if mode == "Ruler":
                    self.ruler = None
                else:
                    self.protractor = None
                mode = "Draw"
            self.mode = mode
            for m, b in self.buttons.items():
                b.setChecked(m == mode)
            self.redraw()

        def save(self, name):
            self.doc.openTransaction(name)
            try:
                set_ink(self.sketch, self.strokes)
            finally:
                self.doc.commitTransaction()

        # ---------------------------------------------------------- mouse
        def press(self, p):
            self.dragging = True
            if self.mode in ("Draw", "Power Modify"):
                self.current = [p]
            elif self.mode == "Eraser":
                self.erase_at = p
                self.erase(p)
            elif self.mode == "Select":
                hit = next((i for i, s in enumerate(self.strokes) if _near_stroke(s, p, PICK_PX * self.px)), None)
                if hit is None:
                    self.picked = set()
                elif hit in self.picked:
                    self.picked.discard(hit)
                else:
                    self.picked.add(hit)
                self.dragging = False
            elif self.mode == "Ruler":
                self.ruler = (p, p)
            elif self.mode == "Protractor":
                self.protractor = (p, 0.0)
            self.redraw()

        def drag(self, p):
            if self.mode in ("Draw", "Power Modify") and self.current is not None:
                last = self.current[-1]
                if math.hypot(p[0] - last[0], p[1] - last[1]) > 1e-9:
                    self.current.append(p)
            elif self.mode == "Eraser":
                self.erase(p)
            elif self.mode == "Ruler" and self.ruler is not None:
                self.ruler = (self.ruler[0], p)
            elif self.mode == "Protractor" and self.protractor is not None:
                c = self.protractor[0]
                self.protractor = (c, math.hypot(p[0] - c[0], p[1] - c[1]))
            self.redraw()

        def release(self, p):
            self.dragging = False
            if self.mode == "Eraser":
                self.erase(p)
                self.erase_at = None
            if self.mode == "Draw" and self.current is not None:
                self.drag(p)
                stroke, self.current = self.current, None
                self.add_stroke(stroke)
            elif self.mode == "Power Modify" and self.current is not None:
                self.drag(p)
                stroke, self.current = self.current, None
                self.power_modify(stroke)
            elif self.mode == "Ruler" and self.ruler is not None:
                self.ruler = (self.ruler[0], p)
                if math.hypot(p[0] - self.ruler[0][0], p[1] - self.ruler[0][1]) < 1e-9:
                    self.ruler = None
                self.set_mode("Draw")
            elif self.mode == "Protractor" and self.protractor is not None:
                if self.protractor[1] < 1e-9:
                    self.protractor = None
                self.set_mode("Draw")
            self.redraw()

        def add_stroke(self, stroke):
            if len(stroke) < 2:
                return
            tol = GUIDE_PX * self.px
            if self.ruler is not None:
                stroke = follow_ruler(stroke, self.ruler, tol)
            if self.protractor is not None:
                stroke = follow_protractor(stroke, self.protractor, tol)
            self.strokes.append(stroke)
            self.save("Pen Sketch ink")
            if setting("PenAutoShape") or setting("PenAutoEntities") or setting("PenAutoSketchEntities"):
                # Auto Convert: the new stroke becomes sketch entities at once
                self.picked = {len(self.strokes) - 1}
                self.convert("recognise" if setting("PenAutoSketchEntities") else setting("PenAutoShape"))
            self.redraw()

        def power_modify(self, stroke):
            ""


            if len(stroke) < 2:
                return []
            xs, ys = [p[0] for p in stroke], [p[1] for p in stroke]
            span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            if span < 1e-9 or _length(stroke) < 2.2 * span:
                return self.pm_gesture(stroke)
            self.pm_flush()
            return self.pm_scratch(stroke)

        # Power Modify's two-stroke gestures wait a moment for the second stroke
        def pm_gesture(self, stroke):
            pending = getattr(self, "pm_pending", None)
            tol = GUIDE_PX * self.px
            # a stroke that only starts or ends on an entity does not cross it (a fillet arc drawn line to line)
            hits = [(g, q) for g, q in crossings(self.sketch, stroke)
                    if math.hypot(q[0] - stroke[0][0], q[1] - stroke[0][1]) > tol
                    and math.hypot(q[0] - stroke[-1][0], q[1] - stroke[-1][1]) > tol]
            if pending is not None:
                first, first_hits = pending
                self.pm_pending = None
                same = {g for g, _ in hits} & {g for g, _ in first_hits}
                if same and any(_seg_seg(a, b, c, d) == 0.0 for a, b in zip(stroke[:-1], stroke[1:])
                                for c, d in zip(first[:-1], first[1:])):
                    g = sorted(same)[0]
                    pts = [q for h, q in hits + first_hits if h == g]
                    at = (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
                    return self.pm_apply("Split", lambda: self._pm_split(g, at), "Power Modify: split.")
                d1, d2 = _chord_dir(first), _chord_dir(stroke)
                if same and d1 and d2 and abs(d1[0] * d2[1] - d1[1] * d2[0]) < math.sin(math.radians(20)):
                    return self._pm_offset(sorted(same)[0])
                self._pm_trim(first_hits)
            if hits:
                if _bulge(stroke) <= 0.2:
                    self.pm_pending = (stroke, hits)
                    token = object()
                    self._pm_token = token
                    QtCore.QTimer.singleShot(PM_WAIT_MS, lambda t=token: self._pm_timeout(t))
                    return []
                return self._pm_trim(hits)
            found = corner_gesture(self.sketch, stroke, tol)
            if found is not None:
                return self._pm_offer(found)
            self.show_note("Power Modify: scratch to delete, stroke across to trim, X to split, two strokes side by "
                           "side to offset, an arc or a line on a corner for a fillet or a chamfer.", True)
            return []

        def _pm_timeout(self, token):
            if getattr(self, "_pm_token", None) is token and getattr(self, "pm_pending", None) is not None:
                self.pm_flush()

        def pm_flush(self):
            """Runs a waiting stroke as a trim."""
            pending = getattr(self, "pm_pending", None)
            self.pm_pending = None
            if pending is not None:
                self._pm_trim(pending[1])

        def pm_apply(self, name, work, note):
            self.doc.openTransaction("Power Modify")
            try:
                out = work()
                self.sketch.solve()
            except Exception as error:
                self.doc.abortTransaction()
                self.show_note("Power Modify: %s did not work here (%s)." % (name.lower(), error), True)
                return []
            self.doc.commitTransaction()
            self.picked = set()
            sketchtoolpm._refresh(self.sketch)
            self.show_note(note)
            return out or []

        def _pm_trim(self, hits):
            # the piece each crossing is on, last first so earlier ids stay put
            def work():
                done = []
                for g, q in sorted(hits, key=lambda h: -h[0]):
                    if g < len(self.sketch.Geometry):
                        self.sketch.trim(g, V(q[0], q[1], 0))
                        done.append(g)
                return done
            return self.pm_apply("Trim", work, "Power Modify: trimmed.")

        def _pm_split(self, g, at):
            from .fwsketch import split as S
            geo = self.sketch.Geometry[g]
            at = S.on_curve(geo, at)
            if S.is_closed(geo):
                raise ValueError("a closed entity needs two split points")
            S.split(self.sketch, g, at)
            return [g]

        def _pm_offset(self, g):
            """Two strokes side by side across an entity: Offset Entities on it (its PropertyManager)."""
            try:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge%d" % (g + 1))
            except Exception as _fw_err:
                _fw_log("pentools.py:678", _fw_err)
            self.pm_offset_geo = g
            self.show_note("Power Modify: offset the picked entity.")
            QtCore.QTimer.singleShot(0, lambda: Gui.runCommand("SWStyle_OffsetEntities", 0))
            return [g]

        def _pm_offer(self, found):
            ""
            kind, corner, detail = found
            menu = QtWidgets.QMenu(self.widget() if hasattr(self, "widget") and callable(self.widget) else None)
            menu.setObjectName("SWPowerModifyOffer")
            if kind == "fillet":
                act = menu.addAction("Convert to Sketch Fillet")
                act.triggered.connect(lambda: self.pm_apply("Fillet", lambda: self._pm_fillet(corner, detail),
                                                            "Power Modify: sketch fillet R%.4g." % detail))
            else:
                act = menu.addAction("Convert to Sketch Chamfer")
                act.triggered.connect(lambda: self.pm_apply("Chamfer", lambda: self._pm_chamfer(corner, detail),
                                                            "Power Modify: sketch chamfer."))
            self.pm_offer_menu = menu
            from PySide import QtGui
            menu.popup(QtGui.QCursor.pos())
            return []

        def _pm_fillet(self, corner, radius):
            from . import sketchfillet
            arcs, failed = sketchfillet.make_fillets(self.sketch, [V(corner[0], corner[1], 0)], radius)
            if failed or not arcs:
                raise ValueError("no fillet")
            return arcs

        def _pm_chamfer(self, corner, detail):
            from . import sketchchamfer
            da, db, ga = detail
            line = sketchchamfer.chamfer_corner(self.sketch, V(corner[0], corner[1], 0), da, db, False, first=ga)
            if line is None:
                raise ValueError("no chamfer")
            return [line]

        def pm_scratch(self, stroke):
            """Scratch to delete: the sketch entities and the ink the scratch passes over (one Undo step)."""
            tol = PICK_PX * self.px
            hits = []
            for i, g in enumerate(self.sketch.Geometry):
                try:
                    edge = g.toShape()
                    samples = [(v.x, v.y) for v in edge.discretize(Number=48)]
                except Exception as _fw_err:
                    _fw_log("pentools.py:728", _fw_err)
                    continue
                if any(_near_path(stroke, a, b, tol) for a, b in zip(samples[:-1], samples[1:])):
                    hits.append(i)
            keep = [s for s in self.strokes if not any(_near_path(s, a, b, tol) for a, b in zip(stroke[:-1], stroke[1:]))]
            gone_ink = len(self.strokes) - len(keep)
            if not hits and not gone_ink:
                self.show_note("Power Modify: nothing under the scratch.", True)
                return []
            self.doc.openTransaction("Power Modify")
            try:
                if hits:
                    self.sketch.delGeometries(sorted(hits))
                if gone_ink:
                    self.strokes = keep
                    set_ink(self.sketch, self.strokes)
            finally:
                self.doc.commitTransaction()
            self.picked = set()
            sketchtoolpm._refresh(self.sketch)
            self.show_note("Power Modify: %d sketch entities and %d strokes of ink deleted." % (len(hits), gone_ink))
            return hits

        def erase(self, p):
            """Rubs out the ink the eraser passes over since its last place."""
            a = getattr(self, "erase_at", None) or p
            tol = PICK_PX * self.px
            keep = [s for s in self.strokes if not _near_path(s, a, p, tol)]
            self.erase_at = p
            if len(keep) != len(self.strokes):
                self.strokes = keep
                self.picked = set()
                self.save("Erase ink")

        def convert(self, as_shapes):
            chosen = sorted(self.picked) if self.picked else list(range(len(self.strokes)))
            if not chosen:
                self.show_note("There is no ink to convert.", True)
                return []
            name = "Convert to Shape" if as_shapes else "Convert to Entities"
            self.doc.openTransaction(name)
            try:
                made = convert(self.sketch, [self.strokes[i] for i in chosen], as_shapes)
                self.strokes = [s for i, s in enumerate(self.strokes) if i not in chosen]
                set_ink(self.sketch, self.strokes)
            finally:
                self.doc.commitTransaction()
            self.picked = set()
            sketchtoolpm._refresh(self.sketch)
            self.show_note("%s: %d sketch entities added." % (name, len(made)))
            self.redraw()
            return made

        # ---------------------------------------------------------- drawing
        def _put(self, key, polylines):
            coords, lines = self._sets[key]
            pl = self.sketch.getGlobalPlacement()
            pts, counts = [], []
            for poly in polylines:
                if len(poly) < 2:
                    continue
                for x, y in poly:
                    v = pl.multVec(V(x, y, 0))
                    pts.append((v.x, v.y, v.z))
                counts.append(len(poly))
            coords.point.setNum(0)
            lines.numVertices.setNum(0)
            if pts:
                coords.point.setValues(0, len(pts), pts)
                lines.numVertices.setValues(0, len(counts), counts)

        def redraw(self):
            plain = [s for i, s in enumerate(self.strokes) if i not in self.picked]
            if self.current:
                plain = plain + [self.current]
            self._put("ink", plain)
            self._put("picked", [self.strokes[i] for i in sorted(self.picked) if i < len(self.strokes)])
            guides = []
            if self.ruler is not None:
                (ax, ay), (bx, by) = self.ruler
                guides.append([(ax, ay), (bx, by)])
                L = math.hypot(bx - ax, by - ay)
                if L > 1e-9:
                    nx, ny = -(by - ay) / L, (bx - ax) / L
                    step = 10.0 if L > 20 else max(L / 10.0, 1e-6)
                    t = 0.0
                    while t <= L + 1e-9:
                        x, y = ax + (bx - ax) * t / L, ay + (by - ay) * t / L
                        size = 3.0 if abs(t / step) % 5 < 1e-9 else 1.5
                        guides.append([(x, y), (x + nx * size, y + ny * size)])
                        t += step
            if self.protractor is not None:
                (cx, cy), r = self.protractor
                if r > 1e-9:
                    guides.append([(cx + r * math.cos(a * math.pi / 36), cy + r * math.sin(a * math.pi / 36))
                                   for a in range(73)])
                    for a in range(0, 360, 15):
                        u, w = math.cos(math.radians(a)), math.sin(math.radians(a))
                        k = 0.85 if a % 45 else 0.75
                        guides.append([(cx + r * k * u, cy + r * k * w), (cx + r * u, cy + r * w)])
            self._put("guide", guides)
            self.count.setText("%d strokes of ink%s" % (len(self.strokes), ", %d picked" % len(self.picked)
                                                       if self.picked else ""))

        def closing(self):
            global _page
            self._alive = False
            self.filter.stop()
            try:
                Gui.ActiveDocument.ActiveView.getSceneGraph().removeChild(self.node)
            except Exception as _fw_err:
                _fw_log("pentools.py:836", _fw_err)
            if _page is self:
                _page = None

    return PenPage


def open_page(sketch, mode=None):
    """The Pen page for sketch (opened when it is not), in mode."""
    global _page
    from . import sketchtoolpm
    cur = sketchtoolpm.current()
    if cur is None or cur is not _page or _page is None or _page.sketch is not sketch:
        _page = _page_class()(sketch)
        sketchtoolpm.open_page(_page)
    if mode:
        _page.set_mode(mode)
    return _page


def _sketch():
    from . import contextbar
    return contextbar.sketch_in_edit()


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.mode, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"Pixmap": self.pixmap, "MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit"}

    def _sketch3d(self):
        try:
            from . import sketch3d
            return sketch3d.editing()
        except Exception as _fw_err:
            _fw_log("pentools.py:877", _fw_err)
            return None

    def IsActive(self):
        if self._sketch3d() is not None:

            # greyed; the converts need ink
            if self.name == "FreeWorks_PenProtractor":
                return False
            if self.mode is None:
                from . import sketch3d
                s = sketch3d.session()
                return s is not None and bool(s.ink)
            return True
        sketch = _sketch()     # a 2D sketch
        if sketch is None:
            return False
        if self.mode is None:
            return bool(ink(sketch))
        return True

    def Activated(self):
        if self._sketch3d() is not None:
            from . import sketch3d
            s = sketch3d.session()
            if s is None:
                return
            if self.mode is None:
                s.convert_ink(self.name == "FreeWorks_PenConvertToShape")
                return
            if not isinstance(s.tool, sketch3d.PenTool):
                sketch3d.start_tool("pen")
            if isinstance(s.tool, sketch3d.PenTool):
                s.tool.set_mode(self.mode)
            return
        sketch = _sketch()
        if sketch is None:
            return
        if self.mode is not None:
            open_page(sketch, self.mode)
        else:
            open_page(sketch).convert(self.name == "FreeWorks_PenConvertToShape")


class _Setting:
    """A Pen Settings switch (ticked in the menu while on)."""

    def __init__(self, name):
        self.name = name
        self.text, self.key, self.default, self.tip = SETTINGS[name]

    def GetResources(self):
        res = {"MenuText": self.text, "ToolTip": self.tip, "Checkable": setting(self.key), "CmdType": "ForEdit"}
        try:
            from . import simicons      # its own drawing (the icon pack has none)
            pix = simicons.svg(self.key)
            if pix:
                res["Pixmap"] = pix
        except Exception as _fw_err:
            _fw_log("pentools.py:pixmap", _fw_err)
        return res

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self, checked=None):
        on = (not setting(self.key)) if checked is None else bool(checked)
        params().SetBool(self.key, on)
        if on and self.key in AUTO:
            for other in AUTO:
                if other != self.key:
                    params().SetBool(other, False)
        _sync_ticks()


def _sync_ticks():
    try:
        for a in Gui.getMainWindow().findChildren(QtWidgets.QAction):
            name = a.objectName() or ""
            for cmd, (_t, key, _d, _tip) in SETTINGS.items():
                if name == cmd and a.isCheckable():
                    a.blockSignals(True)
                    a.setChecked(setting(key))
                    a.blockSignals(False)
    except Exception as _fw_err:
        _fw_log("pentools.py:950", _fw_err)


class _Properties:
    """Pen Properties: the ink's colour and width."""

    def GetResources(self):
        return {"MenuText": "Pen Properties", "ToolTip": "The color and width of the ink.", "CmdType": "ForEdit"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from PySide import QtGui
        mw = Gui.getMainWindow()
        dlg = QtWidgets.QDialog(mw)
        dlg.setWindowTitle("Pen Properties")
        form = QtWidgets.QFormLayout(dlg)
        r, g, b = ink_colour()
        colour = [QtGui.QColor.fromRgbF(r, g, b)]
        swatch = QtWidgets.QPushButton(dlg)
        swatch.setObjectName("SWPenPropertiesColour")

        def paint():
            swatch.setStyleSheet("background: %s;" % colour[0].name())

        def pick():
            c = QtWidgets.QColorDialog.getColor(colour[0], dlg, "Ink color")
            if c.isValid():
                colour[0] = c
                paint()
        paint()
        swatch.clicked.connect(pick)
        form.addRow("Color", swatch)
        width = QtWidgets.QSpinBox(dlg)
        width.setObjectName("SWPenPropertiesWidth")
        width.setRange(1, 12)
        width.setValue(ink_width())
        form.addRow("Width", width)
        box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, dlg)
        box.accepted.connect(dlg.accept)
        box.rejected.connect(dlg.reject)
        form.addRow(box)
        if (dlg.exec() if hasattr(dlg, "exec") else dlg.exec_()):
            c = colour[0]
            params().SetUnsigned("InkColor", (c.red() << 24) | (c.green() << 16) | (c.blue() << 8) | 255)
            params().SetInt("InkWidth", width.value())
            page = _page
            if page is not None and getattr(page, "_sets", None):
                try:
                    page.node.getChild(0).getChild(1).rgb.setValue(*ink_colour())
                    page.node.getChild(0).getChild(0).lineWidth.setValue(ink_width())
                except Exception as _fw_err:
                    _fw_log("pentools.py:1003", _fw_err)


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    for name in SETTINGS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Setting(name))
    if "FreeWorks_PenProperties" not in Gui.listCommands():
        Gui.addCommand("FreeWorks_PenProperties", _Properties())
