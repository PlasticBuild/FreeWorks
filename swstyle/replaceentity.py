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

from . import contextbar, dimtools, relationspm, sketchtoolpm

START, END, MID = 1, 2, 3
NAMES = {START: "start", END: "end", MID: "centre"}
# relations and dimensions on a whole entity, and the entity kinds each can apply to
LINES = ("line",)
ROUND = ("circle", "arc")
EDGE_KINDS = {
    "Horizontal": LINES, "Vertical": LINES, "Parallel": LINES, "Perpendicular": LINES + ROUND,
    "Angle": LINES, "Distance": LINES + ROUND, "DistanceX": LINES, "DistanceY": LINES,
    "Radius": ROUND, "Diameter": ROUND, "Equal": None, "Tangent": None, "PointOnObject": None,
    "Symmetric": LINES, "Block": None, "Weight": ("spline",), "SnellsLaw": None,
}


def _params():
    return App.ParamGet("User parameter:BaseApp/Preferences/Mod/FreeWorks/ReplaceEntity")


def _points(sketch, geo):
    kind = dimtools._kind(sketch.Geometry[geo])
    return {pos: sketch.getPoint(geo, pos) for pos in dimtools._positions(kind)}


def point_map(sketch, old, new):
    """{old pos: new pos}: ends go to the nearer end, a centre to the centre."""
    a, b = _points(sketch, old), _points(sketch, new)
    out = {}
    if MID in a and MID in b:
        out[MID] = MID
    ends_a = [p for p in (START, END) if p in a]
    ends_b = [p for p in (START, END) if p in b]
    if len(ends_a) == 2 and len(ends_b) == 2:
        straight = (a[START] - b[START]).Length + (a[END] - b[END]).Length
        crossed = (a[START] - b[END]).Length + (a[END] - b[START]).Length
        out.update({START: START, END: END} if straight <= crossed else {START: END, END: START})
    elif ends_a and ends_b:
        for p in ends_a:
            out[p] = min(ends_b, key=lambda q: (a[p] - b[q]).Length)
    elif len(ends_a) == 1 and MID in b and MID not in out:
        out[ends_a[0]] = MID          # a point becomes a circle's centre
    return out


def _refs(c):
    return [("First", "FirstPos"), ("Second", "SecondPos"), ("Third", "ThirdPos")]


def plan(sketch, old, new):
    """([(index, mapped constraint)], [(index, reason)]): what moves to the new entity, and what
    cannot, for the relations and dimensions on the old one."""
    moved, dropped = [], []
    kinds = {old: dimtools._kind(sketch.Geometry[old]), new: dimtools._kind(sketch.Geometry[new])}
    points = point_map(sketch, old, new)
    for i, c in enumerate(sketch.Constraints):
        uses = [(getattr(c, g), getattr(c, p)) for g, p in _refs(c)]
        if not any(g == old for g, _ in uses):
            continue
        if any(g == new for g, _ in uses):
            dropped.append((i, "it ties the two entities together"))
            continue
        copy = c                      # each read of Constraints gives fresh copies
        reason = None
        for (g_attr, p_attr), (g, pos) in zip(_refs(c), uses):
            if g != old:
                continue
            if pos == 0:
                allowed = EDGE_KINDS.get(c.Type, None)
                if allowed is not None and kinds[new] not in allowed:
                    reason = "needs %s" % " or ".join("a " + k for k in allowed)
                setattr(copy, g_attr, new)
            elif pos in points:
                setattr(copy, g_attr, new)
                setattr(copy, p_attr, points[pos])
            else:
                reason = "the new entity has no %s point" % NAMES.get(pos, "matching")
        if reason:
            dropped.append((i, reason))
        else:
            moved.append((i, copy))
    return moved, dropped


def replace(sketch, old, new, construction=False):
    """Replaces geometry old by new in sketch. Returns (moved, dropped): constraint names or types."""
    if old == new or old < 0 or new < 0:
        raise ValueError("Pick two different entities of this sketch")
    moved, dropped = plan(sketch, old, new)
    label = lambda c: c.Name or c.Type
    kept, lost = [], [(label(sketch.Constraints[i]), why) for i, why in dropped]
    # the old entity's relations go, then each one that fits comes back on the new entity
    gone = sorted({i for i, _ in moved} | {i for i, _ in dropped}, reverse=True)
    for i in gone:
        sketch.delConstraint(i)
    for _, c in moved:
        try:
            index = sketch.addConstraint(c)
        except Exception as error:
            lost.append((label(c), str(error)))
            continue
        if sketch.solve() != 0 or index in [k - 1 for k in sketch.ConflictingConstraints] or \
                index in [k - 1 for k in sketch.RedundantConstraints]:
            sketch.delConstraint(index)
            lost.append((label(c), "it would over-define the sketch"))
            continue
        kept.append(label(c))
    # the new entity takes the old one's id, so faces and edges named after it keep their names
    try:
        old_id, new_id = sketch.getGeometryId(old), sketch.getGeometryId(new)
        sketch.setGeometryIds([(old, new_id), (new, old_id)])
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Replace Entity kept the geometry ids (%s)\n" % error)
    if sketch.getConstruction(new) and not sketch.getConstruction(old):
        sketch.toggleConstruction(new)
    if construction:
        if not sketch.getConstruction(old):
            sketch.toggleConstruction(old)
    else:
        sketch.delGeometry(old)
    sketch.solve()
    return kept, lost


class ReplacePage(sketchtoolpm.ToolPage):
    TITLE = "Replace Entity"
    ICON = "SKETCH_REPLACE_ENTITY"
    PIXMAP = "Sketcher_SwitchVirtualSpace"
    TRANSACTION = "Replace Entity"

    def build(self):
        self.old = None
        self.new = None
        g = self.group("Replace Entity")
        g.content.addWidget(QtWidgets.QLabel("Entity to replace", g.body))
        self.old_box = self._box(g, "SWReplaceOld", "The sketch entity to replace")
        g.content.addWidget(QtWidgets.QLabel("Replace with", g.body))
        self.new_box = self._box(g, "SWReplaceNew", "The sketch entity that takes its place")
        self.construction = QtWidgets.QCheckBox("Make construction", g.body)
        self.construction.setObjectName("SWReplaceConstruction")
        self.construction.setToolTip("Keep the replaced entity as construction geometry instead of deleting it")
        self.construction.setChecked(_params().GetBool("MakeConstruction", False))
        g.content.addWidget(self.construction)
        self.old_box.itemPressed.connect(lambda *a: self._activate(self.old_box))
        self.new_box.itemPressed.connect(lambda *a: self._activate(self.new_box))
        self._activate(self.old_box)
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        for sub in relationspm.picked_subs(self.sketch):
            self.picked(sub)
        self._explain()

    def _box(self, g, name, tip):
        box = QtWidgets.QListWidget(g.body)
        box.setObjectName(name)
        box.setFixedHeight(26)
        box.setToolTip(tip)
        g.content.addWidget(box)
        return box

    def _activate(self, box):
        self.active = box
        for b in (self.old_box, self.new_box):
            b.setProperty("swActive", b is box)
            b.style().unpolish(b)
            b.style().polish(b)

    def picked(self, sub):
        item = sketchtoolpm.item_of(self.sketch, sub)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("replaceentity.py:200", _fw_err)
        if item is None or item.geo < 0:
            return
        if item.pos in (START, END, MID) and dimtools._kind(self.sketch.Geometry[item.geo]) != "point":
            return
        name = relationspm._entity_names(self.sketch.Geometry)[item.geo]
        if self.active is self.old_box:
            if item.geo == self.new:
                return
            self.old = item.geo
            self.old_box.clear()
            self.old_box.addItem(name)
            self._activate(self.new_box)
        else:
            if item.geo == self.old:
                return
            self.new = item.geo
            self.new_box.clear()
            self.new_box.addItem(name)
        self._explain()

    def selection_changed(self):
        pass

    def _explain(self):
        if self.old is None:
            self.show_note("Pick the sketch entity to replace.")
            return
        if self.new is None:
            self.show_note("Pick the entity that replaces it.")
            return
        moved, dropped = plan(self.sketch, self.old, self.new)
        text = "%d relation%s and dimension%s move to the new entity." % (
            len(moved), "" if len(moved) == 1 else "s", "" if len(moved) == 1 else "s")
        if dropped:
            cons = self.sketch.Constraints
            text += " Left out: " + "; ".join("%s (%s)" % (cons[i].Name or cons[i].Type, why) for i, why in dropped) + "."
        self.show_note(text)

    def finish(self):
        _params().SetBool("MakeConstruction", self.construction.isChecked())
        if self.old is None or self.new is None:
            return
        self.begin()
        kept, lost = replace(self.sketch, self.old, self.new, self.construction.isChecked())
        sketchtoolpm._refresh(self.sketch)
        if lost:
            App.Console.PrintMessage("Replace Entity left out: %s\n" % "; ".join("%s (%s)" % x for x in lost))

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("replaceentity.py:253", _fw_err)
        self.observer.page = None


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_SwitchVirtualSpace", "MenuText": "Replace Entity",
                "ToolTip": "Replaces a sketch entity with another, keeping its relations, dimensions and "
                           "the features that use it",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(ReplacePage(sketch))


def register():
    if "SWStyle_ReplaceEntity" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ReplaceEntity", _Command())
