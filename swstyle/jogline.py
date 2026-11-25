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
from . import geomkeep

V = App.Vector
UNDEF = -2000


def _like(old, new):
    new.Name = old.Name
    try:
        new.Driving = old.Driving
    except Exception as _fw_err:
        _fw_log("jogline.py:37", _fw_err)
    return new


def cut(sketch, geo, p1, p2):
    """Line geo (A to B) becomes A to p1 and a new line p2 to B; the far end's relations move to
    the new line and lengths along the line span both. Returns the new line."""
    import Part
    import Sketcher
    C = Sketcher.Constraint
    line = sketch.Geometry[geo]
    a, b = line.StartPoint, line.EndPoint
    construction = bool(sketch.getConstruction(geo))
    expressions = [(path, text) for path, text in sketch.ExpressionEngine if path.startswith(".Constraints.")]
    old = list(sketch.Constraints)
    geos = geomkeep.read(sketch)
    geos[geo] = geomkeep.like(geos[geo], Part.LineSegment(a, p1))
    sketch.Geometry = geos
    last = sketch.addGeometry(Part.LineSegment(p2, b), construction)
    out = []
    for c in old:
        if c.Type in ("Distance", "DistanceX", "DistanceY") and c.First == geo and c.FirstPos == 0 \
                and c.Second == UNDEF:
            out.append(_like(c, C(c.Type, geo, 1, last, 2, c.Value)))
            continue
        for key in ("First", "Second", "Third"):
            if getattr(c, key) == geo and getattr(c, key + "Pos") == 2:
                setattr(c, key, last)
        out.append(c)
    sketch.Constraints = out
    kept = dict(sketch.ExpressionEngine)
    for path, text in expressions:
        if path not in kept:
            try:
                sketch.setExpression(path[1:], text)
            except Exception as _fw_err:
                _fw_log("jogline.py:73", _fw_err)
    return last


def jog(sketch, geo, at, width, depth):
    """Puts a jog into line geo, centred at distance at from its start, width long, depth deep
    (to the line's left; negative to its right). Returns the three new sides."""
    import Part
    import Sketcher
    C = Sketcher.Constraint
    line = sketch.Geometry[geo]
    if line.TypeId != "Part::GeomLineSegment":
        raise ValueError("Pick a line")
    a, b = line.StartPoint, line.EndPoint
    length = (b - a).Length
    if width <= 0 or abs(depth) < 1e-9:
        raise ValueError("The jog needs a width and a depth")
    if at - width / 2 <= 1e-6 or at + width / 2 >= length - 1e-6:
        raise ValueError("The jog does not fit on the line there")
    d = (b - a) * (1.0 / length)
    n = V(-d.y, d.x, 0) * depth
    p1, p2 = a + d * (at - width / 2), a + d * (at + width / 2)
    q1, q2 = p1 + n, p2 + n
    construction = bool(sketch.getConstruction(geo))
    first = geo
    last = cut(sketch, geo, p1, p2)
    up = sketch.addGeometry(Part.LineSegment(p1, q1), construction)
    top = sketch.addGeometry(Part.LineSegment(q1, q2), construction)
    down = sketch.addGeometry(Part.LineSegment(q2, p2), construction)
    sketch.addConstraint([C("Coincident", first, 2, up, 1), C("Coincident", up, 2, top, 1),
                          C("Coincident", top, 2, down, 1), C("Coincident", down, 2, last, 1),
                          C("Perpendicular", up, first), C("Parallel", down, up), C("Parallel", top, first)])
    # the two ends stay on one line, unless the line's own relations hold that already
    sketch.solve()
    before = len(sketch.RedundantConstraints) + len(sketch.ConflictingConstraints)
    k = sketch.addConstraint(C("Tangent", first, last))
    sketch.solve()
    if len(sketch.RedundantConstraints) + len(sketch.ConflictingConstraints) > before:
        sketch.delConstraint(k)
        sketch.solve()
    return up, top, down


def _page_class():
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
    from . import relationspm, sketchtoolpm

    class Observer:
        def __init__(self, page):
            self.page = page

        def addSelection(self, doc, obj, sub, pnt):
            page = self.page
            if page is None or obj != page.sketch.Name or not sub:
                return
            point = page.sketch.getGlobalPlacement().inverse().multVec(V(*pnt))
            QtCore.QTimer.singleShot(0, lambda s=sub.rsplit(".", 1)[-1], p=point: page.picked(s, p))

    class JogPage(sketchtoolpm.ToolPage):
        TITLE = "Jog Line"
        ICON = "SKETCH_JOG_LINE"
        PIXMAP = "Sketcher_CreatePolyline"
        TRANSACTION = "Jog Line"

        def build(self):
            self.count = self.sketch.GeometryCount
            self.line = None
            self.at = 0.0
            g = self.group("Jog")
            self.box = QtWidgets.QListWidget(g.body)
            self.box.setObjectName("SWJogLine")
            self.box.setFixedHeight(26)
            self.box.addItem("Click the line where the jog goes")
            g.content.addWidget(self.box)
            form = QtWidgets.QFormLayout()
            self.width = self._number(g, "SWJogWidth", 10.0)
            self.depth = self._number(g, "SWJogDepth", 5.0)
            form.addRow("Width:", self.width)
            form.addRow("Depth:", self.depth)
            g.content.addLayout(form)
            self.flip = QtWidgets.QCheckBox("Flip side", g.body)
            self.flip.setObjectName("SWJogFlip")
            self.flip.toggled.connect(self.changed)
            g.content.addWidget(self.flip)
            self.observer = Observer(self)
            Gui.Selection.addObserver(self.observer)
            Gui.Selection.clearSelection()

        def _number(self, g, name, value):
            box = QtWidgets.QDoubleSpinBox(g.body)
            box.setObjectName(name)
            box.setRange(0.001, 1e6)
            box.setDecimals(3)
            box.setSuffix(" mm")
            box.setValue(value)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(self.changed)
            return box

        def picked(self, sub, point):
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("jogline.py:177", _fw_err)
            if not sub.startswith("Edge"):
                return
            geo = int(sub[4:]) - 1
            if self.line is not None:
                return          # the preview's pieces: the jog is placed
            if geo >= self.count or self.sketch.Geometry[geo].TypeId != "Part::GeomLineSegment":
                self.show_note("Pick a line.", True)
                return
            line = self.sketch.Geometry[geo]
            d = line.EndPoint - line.StartPoint
            self.at = max(0.0, min(d.Length, (point - line.StartPoint).dot(d) / d.Length))
            self.line = geo
            self.box.clear()
            self.box.addItem(relationspm._entity_names(self.sketch.Geometry)[geo])
            if self.width.value() >= d.Length / 2:
                self.width.blockSignals(True)
                self.width.setValue(round(d.Length / 4, 3))
                self.width.blockSignals(False)
            self.changed()

        def changed(self, *args):
            self.undo_work()
            if self.line is None:
                return
            self.begin()
            depth = self.depth.value() * (-1 if self.flip.isChecked() else 1)
            try:
                jog(self.sketch, self.line, self.at, self.width.value(), depth)
            except Exception as error:
                self.undo_work()
                self.show_note(str(error), True)
                return
            sketchtoolpm._refresh(self.sketch)
            self.show_note("")

        def closing(self):
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("jogline.py:217", _fw_err)
            self.observer.page = None

    return JogPage


class _Command:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreatePolyline", "MenuText": "Jog Line",
                "ToolTip": "Puts a rectangular jog into a line", "CmdType": "ForEdit"}

    def IsActive(self):
        from . import contextbar
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        from . import contextbar, sketchtoolpm
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(_page_class()(sketch))


def register():
    import FreeCADGui as Gui
    try:
        if "SWStyle_JogLine" not in Gui.listCommands():
            Gui.addCommand("SWStyle_JogLine", _Command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Jog Line command not added (%s)\n" % error)
