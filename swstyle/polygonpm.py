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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets
from . import unitbox

from . import contextbar, dimtools, relationspm, sketchtoolpm
from . import geomkeep


def _is_line(sketch, g):
    return g >= 0 and dimtools._kind(sketch.Geometry[g]) == "line"


def find_polygon(sketch, line):
    ""


    if not _is_line(sketch, line):
        return None
    on_circle, tangent = {}, {}
    for c in sketch.Constraints:
        if c.Type == "PointOnObject" and c.Second >= 0 and sketch.getConstruction(c.Second) \
                and dimtools._kind(sketch.Geometry[c.Second]) == "circle" and _is_line(sketch, c.First):
            on_circle.setdefault(c.Second, set()).add(c.First)
        if c.Type == "Tangent" and c.SecondPos == 0 and c.FirstPos == 0:
            for a, b in ((c.First, c.Second), (c.Second, c.First)):
                if a >= 0 and b >= 0 and dimtools._kind(sketch.Geometry[a]) == "circle" \
                        and sketch.getConstruction(a) and _is_line(sketch, b):
                    tangent.setdefault(a, set()).add(b)
    for table, mode in ((on_circle, "circumscribed"), (tangent, "inscribed")):
        for circle, lines in table.items():
            if line in lines and len(lines) >= 3:
                return circle, _ordered(sketch, sorted(lines)), mode
    return None


def _ordered(sketch, lines):
    """The sides in drawing order, following shared corners from the first."""
    left = list(lines)
    out = [left.pop(0)]
    while left:
        end = sketch.getPoint(out[-1], 2)
        nxt = min(left, key=lambda g: (sketch.getPoint(g, 1) - end).Length)
        out.append(nxt)
        left.remove(nxt)
    return out


def describe(sketch, circle, sides):
    c = sketch.getPoint(circle, 3)
    r = sketch.Geometry[circle].Radius
    first = sketch.getPoint(sides[0], 1)
    return {"sides": len(sides), "cx": c.x, "cy": c.y, "diameter": 2 * r,
            "angle": math.degrees(math.atan2(first.y - c.y, first.x - c.x)) % 360.0}


def rebuild(sketch, circle, sides, n, mode, angle_deg, construction=False):
    """Deletes the old sides and draws n new ones about the circle; their ids."""
    import Part
    C = dimtools._constraint
    sketch.delGeometries(sorted(sides))
    shift = sum(1 for g in sides if g < circle)
    circle -= shift
    c = sketch.getPoint(circle, 3)
    r = sketch.Geometry[circle].Radius
    corner = r if mode == "circumscribed" else r / math.cos(math.pi / n)
    a0 = math.radians(angle_deg)
    pts = [App.Vector(c.x + corner * math.cos(a0 + 2 * math.pi * k / n),
                      c.y + corner * math.sin(a0 + 2 * math.pi * k / n), 0) for k in range(n)]
    new = [sketch.addGeometry(Part.LineSegment(pts[k], pts[(k + 1) % n]), construction) for k in range(n)]
    cons = []
    for k in range(n):
        cons.append(C("Coincident", new[k], 2, new[(k + 1) % n], 1))
    for k in range(n):
        if mode == "circumscribed":
            cons.append(C("PointOnObject", new[k], 1, circle))
        else:
            cons.append(C("Tangent", circle, new[k]))
    # as FreeCAD's ProfileLib (package 31): with the sides touching the circle an even polygon's
    # last Equal follows from the others and would leave it free to flatten; a hidden angle
    # (virtual space) holds it regular
    even = mode == "inscribed" and n % 2 == 0
    for k in range(1, n - 1 if even else n):
        cons.append(C("Equal", new[0], new[k]))
    sketch.addConstraint(cons)
    if even:
        sketch.setVirtualSpace(sketch.addConstraint(C("Angle", new[0], new[1], 2 * math.pi / n)), True)
    sketch.solve()
    return circle, new


def _set_circle(sketch, circle, cx, cy, diameter):
    """Moves and sizes the construction circle: through its dimension when it has one, else its geometry."""
    sized = False
    for i, c in enumerate(sketch.Constraints):
        if c.First == circle and c.Type in ("Diameter", "Radius") and c.Driving:
            sketch.setDatum(i, App.Units.Quantity("%.9g mm" % (diameter if c.Type == "Diameter" else diameter / 2)))
            sized = True
    geos = geomkeep.read(sketch)
    g = geos[circle]
    if not sized:
        g.Radius = diameter / 2
    g.Center = App.Vector(cx, cy, 0)
    geos[circle] = g
    sketch.Geometry = geos
    sketch.solve()


class EditPolygonPage(sketchtoolpm.ToolPage):
    TITLE = "Polygon"
    ICON = "SKETCH_POLYGON"
    PIXMAP = "Sketcher_CreateRegularPolygon"
    TRANSACTION = "Edit Polygon"

    def __init__(self, sketch, circle, sides, mode, parent=None):
        self.circle, self.sides, self.mode = circle, sides, mode
        super().__init__(sketch, parent)

    def build(self):
        values = describe(self.sketch, self.circle, self.sides)
        self._filling = True
        g = self.group("Parameters")
        form = QtWidgets.QFormLayout()
        self.count = QtWidgets.QSpinBox(g.body)
        self.count.setRange(3, 40)
        self.count.setValue(values["sides"])
        self.count.setToolTip("Number of sides")
        form.addRow("Sides:", self.count)
        g.content.addLayout(form)
        self.inscribed = QtWidgets.QRadioButton("Inscribed circle", g.body)
        self.circumscribed = QtWidgets.QRadioButton("Circumscribed circle", g.body)
        (self.inscribed if self.mode == "inscribed" else self.circumscribed).setChecked(True)
        g.content.addWidget(self.inscribed)
        g.content.addWidget(self.circumscribed)
        form = QtWidgets.QFormLayout()
        self.cx = self._length(g, values["cx"], -1e6)
        self.cy = self._length(g, values["cy"], -1e6)
        self.diameter = self._length(g, values["diameter"], 1e-3)
        self.angle = unitbox.UnitSpinBox(g.body)
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setValue(values["angle"])
        form.addRow("Center X:", self.cx)
        form.addRow("Center Y:", self.cy)
        form.addRow("Diameter:", self.diameter)
        form.addRow("Angle:", self.angle)
        g.content.addLayout(form)
        self.new_button = QtWidgets.QPushButton("New Polygon", g.body)
        self.new_button.clicked.connect(self.new_polygon)
        g.content.addWidget(self.new_button)
        for w in (self.count, self.cx, self.cy, self.diameter, self.angle):
            w.valueChanged.connect(self.changed)
            w.setKeyboardTracking(False)
        self.inscribed.toggled.connect(self.changed)
        self._filling = False

    def _length(self, g, value, low):
        box = unitbox.UnitSpinBox(g.body)
        box.setRange(low, 1e6)
        box.setDecimals(3)
        box.setSuffix(" mm")
        box.setValue(value)
        return box

    def changed(self, *args):
        if self._filling:
            return
        self.begin()
        try:
            values = describe(self.sketch, self.circle, self.sides)
            if (abs(values["cx"] - self.cx.value()) > 1e-9 or abs(values["cy"] - self.cy.value()) > 1e-9
                    or abs(values["diameter"] - self.diameter.value()) > 1e-9):
                _set_circle(self.sketch, self.circle, self.cx.value(), self.cy.value(), self.diameter.value())
            mode = "inscribed" if self.inscribed.isChecked() else "circumscribed"
            construction = all(self.sketch.getConstruction(g) for g in self.sides)
            self.circle, self.sides = rebuild(self.sketch, self.circle, self.sides, self.count.value(), mode,
                                              self.angle.value(), construction)
            self.mode = mode
        except Exception as error:
            self.show_note("Could not redraw the polygon: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        self._fill_back()
        self.show_note("")

    def _fill_back(self):
        """The fields show what the solver made of it (a dimension on the circle wins)."""
        values = describe(self.sketch, self.circle, self.sides)
        self._filling = True
        try:
            for box, key in ((self.cx, "cx"), (self.cy, "cy"), (self.diameter, "diameter")):
                if abs(box.value() - values[key]) > 1e-6:
                    box.setValue(values[key])
        finally:
            self._filling = False

    def new_polygon(self):
        self.accept()
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand("Sketcher_CreateRegularPolygon"))


class EditPolygonCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateRegularPolygon", "MenuText": "Edit Polygon",
                "ToolTip": "Changes a polygon's sides, size, centre and angle", "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            return
        found = None
        for item in relationspm.items_of(sketch, relationspm.picked_subs(sketch)):
            found = find_polygon(sketch, item.geo)
            if found:
                break
        if found is None:
            Gui.getMainWindow().statusBar().showMessage("Edit Polygon: pick a side of a polygon first.", 8000)
            return
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("polygonpm.py:251", _fw_err)
        circle, sides, mode = found
        sketchtoolpm.open_page(EditPolygonPage(sketch, circle, sides, mode))


COMMAND = "SWStyle_EditPolygon"


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, EditPolygonCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
