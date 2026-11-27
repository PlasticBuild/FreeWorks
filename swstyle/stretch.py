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
from PySide import QtWidgets

from . import contextbar, dimtools, relationspm, sketchmove, sketchtoolpm

START, END, MID = 1, 2, 3
TOLERANCE = 1e-4


def _points_of(geo):
    """The points that move a whole entity: a circle or an ellipse by its centre (its edge
    would change the size), a line by its ends, an arc by its ends and centre."""
    kind = dimtools._kind(geo)
    if kind in ("circle", "ellipse"):
        return (MID,)
    if kind == "point":
        return (START,)
    if kind in ("arc", "conic_arc"):
        return (START, END, MID)
    return (START, END)


def moving_points(sketch, entities, points):
    """{(geo, pos)} that move: every point of the entities picked whole, the points picked, and
    all of an entity whose ends are both picked."""
    out = set()
    geometry = sketch.Geometry
    for g in entities:
        if 0 <= g < len(geometry):
            out.update((g, p) for p in _points_of(geometry[g]))
    out.update((g, p) for g, p in points if g >= 0)
    for g, geo in enumerate(geometry):
        ends = _points_of(geo)
        if START in ends and END in ends and (g, START) in out and (g, END) in out:
            out.update((g, p) for p in ends)
    return out


def _with_coincident(sketch, moving):
    ""
    pairs = [((c.First, c.FirstPos), (c.Second, c.SecondPos)) for c in sketch.Constraints
             if c.Type == "Coincident"]
    out = set(moving)
    grown = True
    while grown:
        grown = False
        for a, b in pairs:
            if (a in out) != (b in out):
                out.add(b if a in out else a)
                grown = True
    return out


def _hold_the_rest(sketch, moving):
    ""



    import Sketcher
    held = []
    for g, geo in enumerate(sketch.Geometry):
        for pos in _points_of(geo):
            if (g, pos) in moving:
                continue
            p = sketch.getPoint(g, pos)
            for kind, value in (("DistanceX", p.x), ("DistanceY", p.y)):
                try:
                    held.append(sketch.addConstraint(Sketcher.Constraint(kind, -1, 1, g, pos, value)))
                except Exception as _fw_err:
                    _fw_log("stretch.py:93", _fw_err)
    if not held:
        return []
    sketch.solve()
    bad = {i - 1 for i in list(sketch.RedundantConstraints) + list(sketch.ConflictingConstraints)}
    for i in sorted((i for i in held if i in bad), reverse=True):
        sketch.delConstraint(i)
    n = len(sketch.Constraints)
    keep = len([i for i in held if i not in bad])
    return list(range(n - keep, n))[::-1]


def _send(sketch, moving, offset, held, before):
    """fix288: temporary horizontal and vertical distances from the origin to each moving point's new
    place, then a solve. A hold or a distance that makes the sketch redundant or conflicting is taken
    off (holds first: a point the relations already fix, or tie to a moving one, need none) until the
    sketch solves; FreeCAD's solver moves nothing while any is left (gaps: a 160-constraint sketch).
    Returns the temporary constraints' indices, holds and distances together."""
    import Sketcher
    held = sorted(held)
    count = len(sketch.Constraints)
    for g, pos in sorted(moving):
        try:
            p = before[(g, pos)] + App.Vector(offset.x, offset.y, 0)
        except Exception as _fw_err:
            _fw_log("stretch.py: point", _fw_err)
            continue
        for kind, value in (("DistanceX", p.x), ("DistanceY", p.y)):
            try:
                sketch.addConstraint(Sketcher.Constraint(kind, -1, 1, g, pos, value))
            except Exception as _fw_err:
                _fw_log("stretch.py:send", _fw_err)
    temp = list(range(count, len(sketch.Constraints)))
    for _round in range(12):
        result = sketch.solve()
        bad = {i - 1 for i in list(sketch.RedundantConstraints) + list(sketch.ConflictingConstraints)}
        if result == 0 and not bad:
            break
        drop = [i for i in held if i in bad] or [i for i in temp if i in bad]
        if not drop:
            break
        for i in sorted(drop, reverse=True):
            sketch.delConstraint(i)
            held = [h - (h > i) for h in held if h != i]
            temp = [t - (t > i) for t in temp if t != i]
    return sorted(held + temp)


def stretch(sketch, entities, points, offset):
    """Moves the points by offset (sketch coordinates) with the relations kept; dimensions that
    the stretch changes take their new values. Returns the points that could not follow."""
    moving = moving_points(sketch, entities, points)
    if not moving:
        return []
    touched = {g for g, _p in _with_coincident(sketch, moving) if g >= 0}
    toggled = []
    for i, c in enumerate(sketch.Constraints):
        if c.Type not in relationspm.DIMENSIONS or not c.Driving:
            continue
        if any(r in touched for r in sketchmove._refs(c)):
            toggled.append(i)
    before = {gp: App.Vector(sketch.getPoint(*gp)) for gp in moving}
    for i in toggled:
        sketch.setDriving(i, False)
    sketch.solve()
    held = _hold_the_rest(sketch, _with_coincident(sketch, moving))
    sketch.moveGeometries(sorted(moving), App.Vector(offset.x, offset.y, 0), True)
    if any((App.Vector(sketch.getPoint(*gp)) - (p + offset)).Length > TOLERANCE for gp, p in before.items()):
        # fix288: in an open sketch moveGeometries can move nothing once the holds are on (Stretch did
        # nothing): the points go by temporary distances and a solve instead
        held = _send(sketch, moving, offset, held, before)
    for i in sorted(held, reverse=True):
        sketch.delConstraint(i)
    for i in toggled:
        sketch.setDriving(i, True)
    sketch.solve()
    stuck = []
    for gp, p in before.items():
        if (App.Vector(sketch.getPoint(*gp)) - (p + offset)).Length > TOLERANCE:
            stuck.append(gp)
    return stuck


class StretchPage(sketchmove.MovePage):
    TITLE = "Stretch"
    VERB = "Stretch"
    ICON = "SKETCH_STRETCH_ENTITIES"
    PIXMAP = "Sketcher_Translate"
    TRANSACTION = "Stretch Entities"

    def build(self):
        self.points_picked = []          # (geo, pos)
        self.base_active = False
        super().build()
        self.keep.hide()
        self.list.itemPressed.connect(lambda *a: self._activate(False))
        body = self.from_to.parentWidget()
        self.base_box = QtWidgets.QPushButton("Base point", body)
        self.base_box.setObjectName("SWStretchBasePoint")
        self.base_box.setCheckable(True)
        self.base_box.setToolTip("Pick the point the stretch is measured from")
        self.base_box.clicked.connect(lambda on: self._activate(on))
        layout = body.layout()
        layout.insertWidget(layout.indexOf(self.from_to) + 1, self.base_box)
        self.from_to.toggled.connect(lambda *a: self.base_box.setVisible(self.from_to.isChecked()))
        self.base_box.setVisible(self.from_to.isChecked())
        if self.entities or self.points_picked:
            self._activate(True)         # picked before the command: the base point comes next
        self.show_note("" if self.entities or self.points_picked else
                       "Pick the entities and points to stretch, or drag a box round them.")

    def _activate(self, base):
        self.base_active = bool(base) and self.from_to.isChecked()
        self.base_box.setChecked(self.base_active)
        self.list.setProperty("swActive", not self.base_active)
        self.list.style().unpolish(self.list)
        self.list.style().polish(self.list)

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("stretch.py:176", _fw_err)
        if item is None:
            return
        if self.wants_point():
            if item.pos in (START, END, MID) or item.geo < 0 or dimtools._kind(self.sketch.Geometry[item.geo]) == "point":
                self.point_picked(self.sketch.getPoint(item.geo, item.pos if item.pos else START), item)
            # fix288: a click on a line gives the point under the pointer (as Move), not the line's start
            return
        if item.geo < 0:
            return
        if item.pos in (START, END, MID):
            if dimtools._kind(self.sketch.Geometry[item.geo]) == "point":
                if item.geo in self.entities:
                    return
                self.entities.append(item.geo)
                self.list.addItem(relationspm._entity_names(self.sketch.Geometry)[item.geo])
            else:
                key = (item.geo, item.pos)
                if key in self.points_picked:
                    return
                self.points_picked.append(key)
                self.list.addItem(sketchtoolpm.point_name(self.sketch, *key))
        else:
            if item.geo in self.entities:
                return
            self.entities.append(item.geo)
            self.list.addItem(relationspm._entity_names(self.sketch.Geometry)[item.geo])
        self.show_note("")
        self.changed()

    def wants_point(self):
        return self.base_active and self.from_to.isChecked() and self._to_point is None

    def point_picked(self, point, item):
        super().point_picked(point, item)
        if self._to_point is not None:
            self._activate(False)

    def changed(self, *args):
        if self._filling:
            return
        self.undo_work()
        if not (self.entities or self.points_picked) or not self.ready():
            return
        offset = self.placement().Base * self.times
        if offset.Length < 1e-9:
            return                       # nothing to do: an empty history entry would stay behind
        self.begin()
        try:
            stuck = stretch(self.sketch, self.entities, self.points_picked, offset)
        except Exception as error:
            self.show_note("Could not stretch: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        bad = list(self.sketch.ConflictingConstraints) + list(self.sketch.RedundantConstraints)
        if bad:
            self.show_note("This over-defines the sketch.", True)
        elif stuck:
            self.show_note("Some points could not move: relations hold them.", True)
        else:
            self.show_note("")


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_Translate", "MenuText": "Stretch Entities",
                "ToolTip": "Stretches sketch entities: the points picked move, the rest stay, relations kept",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(StretchPage(sketch))


def register():
    if "SWStyle_StretchEntities" not in Gui.listCommands():
        Gui.addCommand("SWStyle_StretchEntities", _Command())
