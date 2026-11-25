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
import Part

from PySide import QtCore

from . import geom
from . import glyphs
from . import inference as I
from .scene import Scene
from .toolbase import ViewMath

DELAY_MS = 40


def outline(g):
    if isinstance(g, Part.LineSegment):
        return [(g.StartPoint.x, g.StartPoint.y), (g.EndPoint.x, g.EndPoint.y)]
    if isinstance(g, Part.ArcOfCircle):
        return geom.arc_points((g.Center.x, g.Center.y), g.Radius, g.FirstParameter, g.LastParameter - g.FirstParameter)
    if isinstance(g, Part.Circle):
        return geom.circle_points((g.Center.x, g.Center.y), g.Radius)
    if hasattr(g, "discretize"):
        try:
            return [(p.x, p.y) for p in g.discretize(Number=48)]
        except Exception:
            return []
    return []


def geometry_of(sketch, geo):
    try:
        if geo >= 0:
            return sketch.Geometry[geo]
        if geo <= -3:
            return sketch.ExternalGeo[-geo - 1]
    except Exception as _fw_err:
        _fw_log("fwsketch/overdefined.py:63", _fw_err)
    return None


def clashing(sketch):
    """(yellow constraint indexes, red constraint indexes), 0-based: the redundant and conflicting
    relations; when the sketch cannot be solved, the newest of the conflicting or malformed ones
    is the red one (package 34)."""
    def listed(name):
        try:
            return [i - 1 for i in getattr(sketch, name)]
        except Exception:
            return []
    redundant = listed("RedundantConstraints") + listed("PartiallyRedundantConstraints")
    conflicting = listed("ConflictingConstraints")
    malformed = listed("MalformedConstraints")
    unsolved = sorted(set(conflicting + malformed))
    red = [unsolved[-1]] if unsolved else []
    yellow = sorted(set(redundant + conflicting + malformed) - set(red))
    return yellow, red


def dangling(sketch):
    ""

    try:
        from .. import relationspm
        refs = relationspm.external_references(sketch)
    except Exception:
        return []
    lost = {k for k, v in refs.items() if not v[2]}
    out = []
    from . import sysopts
    hide_suppressed = sysopts.on(sysopts.HIDE_SUPPRESSED_MISSING)
    for i, c in enumerate(sketch.Constraints):
        if hide_suppressed and not getattr(c, "IsActive", True):
            continue        # Options > Sketch: a suppressed dimension's missing geometry is no error
        # a gone element is either listed as not found, or FreeCAD dropped its reference and the
        # relation still names the external id it had
        if any(g in lost or (g <= -3 and g not in refs) for g in (c.First, c.Second, c.Third)
               if g != I.GEO_UNDEF):
            out.append(i)
    return out


def geos_of(sketch, indexes):
    out = []
    try:
        constraints = sketch.Constraints
    except Exception:
        return out
    for i in indexes:
        if not 0 <= i < len(constraints):
            continue
        c = constraints[i]
        for geo in (c.First, c.Second, c.Third):
            if geo != I.GEO_UNDEF and geo not in (I.H_AXIS, I.V_AXIS) and geo not in out:
                out.append(geo)
    return out


class Overlay(ViewMath):
    """The coloured copy over one sketch in edit."""

    def __init__(self, gdoc, sketch):
        self.setup_view(gdoc, sketch)
        self.scene = None
        self.state = ([], [])        # the last (yellow, red) geo ids, for tests
        self.brown = []              # the last dangling geo ids
        self.clash = ([], [])        # the last (yellow, red) constraint indexes
        self._pending = False
        self.repaint = glyphs.SelectionRepaint(self.paint_nodes)

    def paint_nodes(self):
        glyphs.paint(self.view, self.sketch, *self.clash)

    def schedule(self):
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(DELAY_MS, self.refresh)

    def refresh(self):
        self._pending = False
        try:
            yellow_c, red_c = clashing(self.sketch)
        except Exception:
            return
        self.clash = (yellow_c, red_c)
        self.paint_nodes()
        try:
            brown_c = dangling(self.sketch)
        except Exception:
            brown_c = []
        if not yellow_c and not red_c and not brown_c:
            self.state = ([], [])
            self.brown = []
            if self.scene is not None:
                self.scene.clear()
            return
        red = geos_of(self.sketch, red_c)
        yellow = [g for g in geos_of(self.sketch, yellow_c) if g not in red]
        brown = [g for g in geos_of(self.sketch, brown_c) if g >= 0 and g not in red and g not in yellow]
        self.state = (yellow, red)
        self.brown = brown
        if self.scene is None:
            try:
                self.scene = Scene(self.view, self.matrix, self.ratio)
            except Exception:
                return
        for name, geos in (("conflict", yellow), ("unsolvable", red), ("dangling", brown)):
            lines, points = [], []
            for geo in geos:
                g = geometry_of(self.sketch, geo)
                if isinstance(g, Part.Point):
                    points.append((g.X, g.Y))
                elif g is not None:
                    lines.append(outline(g))
            self.scene.lines(name, [l for l in lines if l])
            self.scene.points(name, points)

    def remove(self):
        self.repaint.stop()
        if self.scene is not None:
            self.scene.remove()
            self.scene = None


class Watcher:
    """Follows the sketch in edit (Gui observer) and its changes (App observer)."""

    def __init__(self):
        self.overlay = None
        App.addDocumentObserver(self)
        # the Gui side gets its own observer with only the edit slots: a Gui observer that has
        # slotChangedObject breaks FreeCAD's FEM mesh objects ("Cannot add static property")
        self.gui = _GuiSide(self)
        Gui.addDocumentObserver(self.gui)
        self.attach_current()

    def stop(self):
        try:
            App.removeDocumentObserver(self)
        except Exception as _fw_err:
            _fw_log("fwsketch/overdefined.py:207", _fw_err)
        try:
            Gui.removeDocumentObserver(self.gui)
        except Exception as _fw_err:
            _fw_log("fwsketch/overdefined.py:211", _fw_err)
        self.detach()

    def attach_current(self):
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        if vp is not None:
            self.slotInEdit(vp)

    def attach(self, gdoc, sketch):
        self.detach()
        try:
            self.overlay = Overlay(gdoc, sketch)
        except Exception:
            self.overlay = None
            return
        self.overlay.schedule()

    def detach(self):
        if self.overlay is not None:
            self.overlay.remove()
            self.overlay = None

    # Gui observer
    def slotInEdit(self, vp):
        try:
            obj = vp.Object
            if not obj.isDerivedFrom("Sketcher::SketchObject"):
                return
            gdoc = Gui.getDocument(obj.Document.Name)
        except Exception:
            return
        self.attach(gdoc, obj)

    def slotResetEdit(self, _vp):
        self.detach()

    # App observer
    def slotChangedObject(self, obj, prop):
        o = self.overlay
        if o is not None and obj == o.sketch and prop in ("Constraints", "Geometry", "ExternalGeo"):
            o.schedule()
            if prop == "Constraints" and not getattr(self, "_settling", False):
                try:
                    stale = "Invalid" in obj.State
                except Exception:
                    stale = False
                if stale:
                    self._settling = True
                    QtCore.QTimer.singleShot(0, lambda s=obj: self._settle(s))

    def _settle(self, sketch):
        ""



        self._settling = False
        try:
            if "Invalid" not in sketch.State or sketch.ConflictingConstraints or sketch.RedundantConstraints \
                    or sketch.MalformedConstraints:
                return
            sketch.recompute()
        except Exception as _fw_err:
            _fw_log("fwsketch/overdefined.py:274", _fw_err)

    def slotRecomputedObject(self, obj):
        # the sketch, or the model it references (an edge gone: Dangling at once, dimension review 11-19)
        o = self.overlay
        try:
            same_doc = obj.Document == o.sketch.Document if o is not None else False
        except Exception:
            same_doc = False
        if o is not None and (obj == o.sketch or same_doc):
            o.schedule()

    def slotDeletedDocument(self, doc):
        o = self.overlay
        if o is not None and o.sketch.Document == doc:
            self.overlay = None


class _GuiSide:
    def __init__(self, watcher):
        self.watcher = watcher

    def slotInEdit(self, vp):
        self.watcher.slotInEdit(vp)

    def slotResetEdit(self, vp):
        self.watcher.slotResetEdit(vp)


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None


def watcher():
    return _watcher
