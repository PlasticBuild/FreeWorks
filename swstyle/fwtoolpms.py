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
from PySide import QtCore, QtGui, QtWidgets

from . import nativepms as N
from . import sketchtoolpm
from .widgets import alive

LINE = "FreeWorks_Line"
CENTERLINE = "FreeWorks_Centerline"
MIDPOINT = "FreeWorks_MidpointLine"
GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"    # the slot tool's own options

FW_CIRCLES = (("Circle", "FreeWorks_Circle", "SKETCH_CIRCLE", "Sketcher_CreateCircle"),
              ("Perimeter Circle", "FreeWorks_PerimeterCircle", "SKETCH_CTRPT_CIRCLE", "Sketcher_Create3PointCircle"))
FW_SLOTS = (("Straight Slot", "FreeWorks_StraightSlot", "SKETCH_STRAIGHT_SLOT", "Sketcher_CreateSlot"),
            ("Centerpoint Straight Slot", "FreeWorks_CenterpointStraightSlot", "SKETCH_CTRPT_STRAIGHT_SLOT",
             "Sketcher_CreateSlot"),
            ("3 Point Arc Slot", "FreeWorks_ThreePointArcSlot", "SKETCH_3PT_ARC_SLOT", "Sketcher_CreateArcSlot"),
            ("Centerpoint Arc Slot", "FreeWorks_CenterpointArcSlot", "SKETCH_CTRPT_ARC_SLOT", "Sketcher_CreateArcSlot"))
FW_ELLIPSES = (("Ellipse", "FreeWorks_Ellipse", "SKETCH_ELLIPSE", "Sketcher_CreateEllipseByCenter"),
               ("Partial Ellipse", "FreeWorks_PartialEllipse", "SKETCH_PARTIAL_ELLIPSE", "Sketcher_CreateElliptical_Arc"))


def _tool():
    return N._fw_tool()


def _icon_for(entries):
    try:
        from . import icons
        family = icons.family
    except Exception:
        family = lambda name: QtGui.QIcon()

    def icon(name):
        entry = next(t for t in entries if t[0] == name)
        i = family(entry[2])
        return i if not i.isNull() else Gui.getIcon(entry[3])
    return icon


def _mm(v):
    return "%.2f" % (0.0 if v is None else v)


def _deg(v):
    return "%.2f°" % (0.0 if v is None else v)


class _TypedPage(N._FwToolPage, N._ToolOptionsPage):
    ""


    ENTRIES = ()
    KIND = ""
    MESSAGE = ""
    PARAMS = ()         # (key, label, "mm" | "deg")
    TYPE_OPTIONS = False
    EDIT_KIND = ""          # paramedit kind: the boxes edit the last entity placed
    CURRENT = ()            # geometry types whose last placed entity gets Existing/Add Relations
    BIG_TYPES = False
    TYPE_GROUP = ""
    TYPE_ROWS = None        # buttons on each row of the type grid (Slot Types: 2 then 2)

    def build(self):
        self._own_tool()
        if self.MESSAGE:
            self.message(self.MESSAGE)
        type_group = None
        if self.ENTRIES:
            g = self.group(self.TYPE_GROUP or "%s Type" % self.TITLE)
            g.setObjectName("SWGroup_%sType" % self.TITLE.replace(" ", ""))
            self.type_buttons = self.toggles(g, [t[0] for t in self.ENTRIES], _icon_for(self.ENTRIES),
                                             lambda k: k == self.KIND, rows=self.TYPE_ROWS, big=self.BIG_TYPES)
            for name, b in self.type_buttons.items():
                b.clicked.connect(lambda checked=False, n=name: self._switch(n))
            type_group = g
        g = self.group("Options")
        options = g
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SW%sForConstruction" % self.TITLE.replace(" ", ""))
        tool = _tool()
        self.construction.setChecked(bool(getattr(tool, "construction", False)))
        self.construction.toggled.connect(self._to_tool)
        g.content.addWidget(self.construction)
        self.more_options(type_group if self.TYPE_OPTIONS and type_group is not None else g)
        self.fields = {}
        if self.PARAMS:
            g = self.group("Parameters")
            for key, label, _unit in self.PARAMS:
                row = QtWidgets.QHBoxLayout()
                row.addWidget(QtWidgets.QLabel(label, g.body))
                f = QtWidgets.QLineEdit(g.body)
                f.setObjectName("SW%s%s" % (self.TITLE.replace(" ", ""), key))
                f.setReadOnly(True)     # shows the entity being placed; typed values come with the dimension
                row.addWidget(f, 1)
                g.content.addLayout(row)
                self.fields[key] = f
            if self.EDIT_KIND:
                from . import paramedit
                paramedit.wire(self, self.fields, self.EDIT_KIND)
        if self.CURRENT:

            from . import currententity
            self.current = currententity.CurrentEntity(self, options, parameters=False)
        self.tick()

    def more_options(self, group):
        pass

    def _switch(self, name):
        for n, b in self.type_buttons.items():
            b.setChecked(n == name)
        if name == self.KIND:
            return
        command = next(t[1] for t in self.ENTRIES if t[0] == name)
        construction = self.construction.isChecked()
        try:
            Gui.runCommand(command, 0)
        except Exception:
            return
        tool = _tool()
        if tool is not None and construction:
            tool.construction = True

    def _to_tool(self, *args):
        tool = _tool()
        if tool is not None:
            tool.construction = self.construction.isChecked()

    def values(self, tool):
        return {}

    def tick(self):
        tool = _tool()
        cur = getattr(self, "current", None)
        if cur is not None and tool is not None and alive(self.construction):
            from . import currententity
            cur.follow(currententity.last_placed(self, self.CURRENT))
        if tool is None or not self.fields or not alive(self.construction):
            return
        from . import paramedit
        if paramedit.editing(self.fields):
            return
        try:
            values = self.values(tool)
        except Exception:
            return
        if self.EDIT_KIND and not any(v is not None for v in values.values()):

            values = paramedit.placed_values(self, self.EDIT_KIND) or values
        for key, _label, unit in self.PARAMS:
            v = values.get(key)
            text = _deg(v) if unit == "deg" else _mm(v)
            if self.fields[key].text() != text:
                self.fields[key].setText(text)


# --------------------------------------------------------------------------- Insert Line
class FwLinePage(N._FwToolPage, N.LinePage):
    ""




    def build(self):
        self._own_tool()
        N.LinePage.build(self)
        tool = _tool()
        if self.native == CENTERLINE or (tool is not None and getattr(tool, "construction", False)):
            self.centerline = True
            self.construction.setChecked(True)
        self.midpoint.blockSignals(True)
        self.midpoint.setChecked(self.native == MIDPOINT)
        self.midpoint.setEnabled(True)
        self.midpoint.setToolTip("Sketches a line from its midpoint")
        self.midpoint.blockSignals(False)
        self.construction.toggled.connect(self._to_tool)
        self._to_tool()

    def _to_tool(self, *args):
        if self._properties_mode():
            return      # Line Properties: the box is the current line's, not the next one's
        tool = _tool()
        if tool is not None:
            tool.construction = self.construction.isChecked()

    def accept(self):

        if self._properties_mode() and _tool() is not None and _tool() is self._own_tool():
            self.show_next()
            return
        N._FwToolPage.accept(self)

    def show_next(self):
        N.LinePage.show_next(self)
        tool = _tool()
        if tool is not None:
            self.construction.blockSignals(True)
            self.construction.setChecked(bool(getattr(tool, "construction", False)))
            self.construction.blockSignals(False)

    def _switch_tool(self, on):
        name = MIDPOINT if on else (CENTERLINE if self.construction.isChecked() else LINE)
        if name == self.native:
            return
        N._centerline_next = self.construction.isChecked()
        self._end_own()
        sketchtoolpm.close(self)        # quietly: the cross would end the next tool too
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(name, 0))

    def tick(self):
        # the tool applies Orientation and For construction itself: nothing to post-process
        # (apply_line_options here would double the relations). A new line makes the page that

        try:
            geos = self.sketch.Geometry
        except Exception:
            return
        n = len(geos)
        count = getattr(self, "count", n)
        if n < count:
            self.count = n
            if self._properties_mode() and (self.current.geo is None or self.current.geo >= n):
                self.show_next()
            return
        if n == count:
            if self._properties_mode():
                self.current.fill()
            return
        new = [i for i in range(count, n) if type(geos[i]).__name__ == "LineSegment"]
        self.count = n
        if new:
            self.show_line(new[-1])


# --------------------------------------------------------------------------- Circle
class FwCirclePage(_TypedPage):
    OK_ONLY = True
    TITLE = "Circle"
    ICON = "SKETCH_CIRCLE"
    PIXMAP = "Sketcher_CreateCircle"
    ENTRIES = FW_CIRCLES
    KIND = "Circle"
    MESSAGE = ""
    EDIT_KIND = "circle"
    CURRENT = ("Circle",)
    PARAMS = (("cx", "Center X", "mm"), ("cy", "Center Y", "mm"), ("radius", "Radius", "mm"))
    BIG_TYPES = True

    def more_options(self, group):
        ""


        general = App.ParamGet(N.NUMERIC)
        self.dims = QtWidgets.QCheckBox("Add dimensions", group.body)
        self.dims.setObjectName("SWCircleAddDimensions")
        self.dims.setChecked(general.GetBool("NumericInputAddsDimension", True))
        self.dims.setToolTip("A radius typed in the on-screen box is kept as a dimension")
        self.dims.toggled.connect(lambda on: App.ParamGet(N.NUMERIC).SetBool("NumericInputAddsDimension", bool(on)))
        group.content.addWidget(self.dims)
        self.diameter = QtWidgets.QCheckBox("Diameter dimensions", group.body)
        self.diameter.setObjectName("SWCircleDiameterDimensions")
        self.diameter.setChecked(general.GetBool("CircleDiameterDimension", True))
        self.diameter.setToolTip("The kept dimension is the circle's diameter (off: its radius)")
        self.diameter.toggled.connect(lambda on: App.ParamGet(N.NUMERIC).SetBool("CircleDiameterDimension", bool(on)))
        group.content.addWidget(self.diameter)
        self._numeric_rows()

    def _numeric_rows(self):
        numeric = App.ParamGet(N.NUMERIC).GetBool("OnScreenNumericInput", False)
        for box in (self.dims, self.diameter):
            if alive(box) and box.isHidden() == numeric:
                box.setVisible(numeric)

    def tick(self):
        if hasattr(self, "dims"):
            self._numeric_rows()
        _TypedPage.tick(self)

    def values(self, tool):
        c = getattr(tool, "center", None)
        r = getattr(tool, "radius", 0.0) or 0.0
        return {"cx": c[0] if c else None, "cy": c[1] if c else None, "radius": r if c and r > 1e-9 else None}


class FwPerimeterCirclePage(FwCirclePage):
    KIND = "Perimeter Circle"
    ICON = "SKETCH_CTRPT_CIRCLE"
    PIXMAP = "Sketcher_Create3PointCircle"


# --------------------------------------------------------------------------- Slot
def _slot_length_icon(kind, widget):
    """Original art for the slot length buttons: a slot outline with its dimension, from centre to
    centre (kind 0) or over the whole length (kind 1)."""
    pm = QtGui.QPixmap(64, 64)
    pm.fill(QtCore.Qt.transparent)
    qp = QtGui.QPainter(pm)
    qp.setRenderHint(QtGui.QPainter.Antialiasing)
    ink = widget.palette().color(QtGui.QPalette.WindowText)
    accent = QtGui.QColor(70, 140, 230)
    pen = QtGui.QPen(ink, 3)
    qp.setPen(pen)
    qp.setBrush(QtCore.Qt.NoBrush)
    qp.drawRoundedRect(QtCore.QRectF(6, 30, 52, 22), 11, 11)
    qp.setPen(QtGui.QPen(ink, 2, QtCore.Qt.DashLine))
    qp.drawLine(QtCore.QPointF(17, 41), QtCore.QPointF(47, 41))
    a, b = (17.0, 47.0) if kind == 0 else (6.0, 58.0)
    qp.setPen(QtGui.QPen(accent, 2.5))
    qp.drawLine(QtCore.QPointF(a, 12), QtCore.QPointF(b, 12))
    qp.drawLine(QtCore.QPointF(a, 6), QtCore.QPointF(a, 28))
    qp.drawLine(QtCore.QPointF(b, 6), QtCore.QPointF(b, 28))
    qp.setBrush(accent)
    qp.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(a, 12), QtCore.QPointF(a + 7, 8), QtCore.QPointF(a + 7, 16)]))
    qp.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(b, 12), QtCore.QPointF(b - 7, 8), QtCore.QPointF(b - 7, 16)]))
    qp.end()
    return QtGui.QIcon(pm)


class FwSlotPage(_TypedPage):
    ""



    TYPE_OPTIONS = True
    OK_ONLY = True
    TYPE_GROUP = "Slot Types"
    TYPE_ROWS = (2, 2)
    BIG_TYPES = True

    TITLE = "Slot"
    ICON = "SKETCH_STRAIGHT_SLOT"
    PIXMAP = "Sketcher_CreateSlot"
    ENTRIES = FW_SLOTS
    KIND = "Straight Slot"
    MESSAGE = ""
    EDIT_KIND = "slot"
    PARAMS = (("sx", "Start X", "mm"), ("sy", "Start Y", "mm"), ("ex", "End X", "mm"), ("ey", "End Y", "mm"),
              ("length", "Length", "mm"), ("width", "Width", "mm"))

    def more_options(self, g):
        general = App.ParamGet(GENERAL)
        self.dims = QtWidgets.QCheckBox("Add dimensions", g.body)
        self.dims.setObjectName("SWSlotAddDimensions")
        self.dims.setChecked(general.GetBool("SlotAddDimensions", False))
        g.content.addWidget(self.dims)
        self.length_kind = QtWidgets.QButtonGroup(g.body)
        chosen = general.GetString("SlotLength", N.SLOT_LENGTHS[0])

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)
        for i, name in enumerate(N.SLOT_LENGTHS):
            b = QtWidgets.QToolButton(g.body)
            b.setText(name)
            b.setCheckable(True)
            b.setIcon(_slot_length_icon(i, g.body))
            b.setIconSize(QtCore.QSize(32, 32))
            b.setFixedSize(46, 46)
            b.setToolTip(name)
            b.setProperty("swToggle", True)
            b.setObjectName("SWSlot" + name.title().replace(" ", ""))
            b.setChecked(name == chosen)
            self.length_kind.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        g.content.addLayout(row)
        if self.length_kind.checkedButton() is None:
            self.length_kind.button(0).setChecked(True)
        self.dims.toggled.connect(self._remember)
        self.length_kind.buttonClicked.connect(self._length_picked)
        self._remember()

    def _length_picked(self, *args):
        # no dead (greyed) choice: picking how the slot is dimensioned turns Add dimensions on,
        # which is the only time it counts
        if not self.dims.isChecked():
            self.dims.setChecked(True)      # _remember runs from its toggled signal
        else:
            self._remember()

    def _remember(self, *args):
        on = self.dims.isChecked()
        b = self.length_kind.checkedButton()
        kind = b.text() if b is not None else N.SLOT_LENGTHS[0]
        for button in self.length_kind.buttons():
            button.setEnabled(True)
        general = App.ParamGet(GENERAL)
        general.SetBool("SlotAddDimensions", on)
        general.SetString("SlotLength", kind)
        p = N._params()                 # the FreeCAD-tool Slot page keeps the same choice
        p.SetBool("SlotAddDimensions", on)
        p.SetString("SlotLength", kind)

    def values(self, tool):
        s = getattr(tool, "start", None)
        e = getattr(tool, "second", None)
        if e is None:
            e = getattr(tool, "end_point", None)
        length = getattr(tool, "length", 0.0) or 0.0
        r = getattr(tool, "r", None)
        if r is None:
            r = getattr(tool, "radius", 0.0) or 0.0
        return {"sx": s[0] if s else None, "sy": s[1] if s else None,
                "ex": e[0] if e else None, "ey": e[1] if e else None,
                "length": length if s and e and length > 1e-9 else None,
                "width": 2 * r if s and e and r > 1e-9 else None}


class FwCenterpointSlotPage(FwSlotPage):
    KIND = "Centerpoint Straight Slot"
    ICON = "SKETCH_CTRPT_STRAIGHT_SLOT"


class FwThreePointArcSlotPage(FwSlotPage):
    KIND = "3 Point Arc Slot"
    ICON = "SKETCH_3PT_ARC_SLOT"
    PIXMAP = "Sketcher_CreateArcSlot"


class FwCenterpointArcSlotPage(FwSlotPage):
    KIND = "Centerpoint Arc Slot"
    ICON = "SKETCH_CTRPT_ARC_SLOT"
    PIXMAP = "Sketcher_CreateArcSlot"


# --------------------------------------------------------------------------- Point
class FwPointPage(_TypedPage):
    ""
    OK_ONLY = True

    TITLE = "Point"
    ICON = "SKETCH_POINT"
    PIXMAP = "Sketcher_CreatePoint"
    MESSAGE = "Click in the graphics area to place a point; the tool stays for the next one."
    EDIT_KIND = "point"
    PARAMS = (("x", "X", "mm"), ("y", "Y", "mm"))

    def values(self, tool):
        created = getattr(tool, "created", None) or []
        if not created:
            return {}
        geo = self.sketch.Geometry[created[-1]]
        p = getattr(geo, "X", None)
        if p is None:
            return {}
        return {"x": geo.X, "y": geo.Y}


# --------------------------------------------------------------------------- Ellipse
class FwEllipsePage(_TypedPage):
    OK_ONLY = True
    TITLE = "Ellipse"
    ICON = "SKETCH_ELLIPSE"
    PIXMAP = "Sketcher_CreateEllipseByCenter"
    ENTRIES = FW_ELLIPSES
    KIND = "Ellipse"
    MESSAGE = "Set the properties of the ellipse, or sketch it in the graphics area."
    EDIT_KIND = "ellipse"
    CURRENT = ("Ellipse", "ArcOfEllipse")
    PARAMS = (("cx", "Center X", "mm"), ("cy", "Center Y", "mm"), ("a", "Radius 1", "mm"), ("b", "Radius 2", "mm"),
              ("phi", "Angle", "deg"))

    def values(self, tool):
        c = getattr(tool, "center", None)
        a = getattr(tool, "a", 0.0) or 0.0
        b = getattr(tool, "b", 0.0) or 0.0
        phi = getattr(tool, "phi", 0.0) or 0.0
        out = {"cx": c[0] if c else None, "cy": c[1] if c else None,
               "a": a if c and a > 1e-9 else None, "b": b if c and b > 1e-9 else None,
               "phi": math.degrees(phi) % 360.0 if c and a > 1e-9 else None}
        sweep = getattr(tool, "sweep", None)
        if sweep is not None:
            out["sweep"] = abs(math.degrees(sweep)) if c and b > 1e-9 and abs(sweep) > 1e-9 else None
        return out


class FwPartialEllipsePage(FwEllipsePage):
    TITLE = "Partial Ellipse"
    KIND = "Partial Ellipse"
    ICON = "SKETCH_PARTIAL_ELLIPSE"
    PIXMAP = "Sketcher_CreateElliptical_Arc"
    PARAMS = FwEllipsePage.PARAMS + (("sweep", "Arc angle", "deg"),)


# --------------------------------------------------------------------------- Trim / Extend
class FwTrimPage(N._FwToolPage, N.TrimPage):
    ""



    def build(self):
        super().build()
        from .fwsketch import trim as T
        T.PAGE = self               # Corner and Trim away inside/outside take the tool's clicks

    def own_mode(self):
        return alive(self) and self.mode() in N.OWN_MODES

    def own_pick(self, geo, at):
        """The tool's click on entity geo at sketch point at, in one of the page's own modes."""
        if self._skip(geo):
            return
        self.picked(geo, self.sketch.getGlobalPlacement().multVec(App.Vector(at[0], at[1], 0)))

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter382(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter fwtoolpms.py: %s\n" % exc)
            return False

    def _fw_filter382(self, obj, event):
        return False

    def closing(self):
        from .fwsketch import trim as T
        if T.PAGE is self:
            T.PAGE = None
        try:
            super().closing()
        except AttributeError as _fw_err:
            _fw_log("fwtoolpms.py:414", _fw_err)

    def _end_trim(self):
        self.watch.stop()
        self.clicked = False


class FwExtendPage(N._FwToolPage, N._ToolOptionsPage):
    ""


    TITLE = "Extend Entities"
    ICON = "SKETCH_EXTEND_ENTITIES"
    PIXMAP = "Sketcher_Extend"

    def build(self):
        self._own_tool()
        self.message("Move over the end of a line or arc to see how far it extends, then click to extend it.")


PAGES = {LINE: FwLinePage, CENTERLINE: FwLinePage, MIDPOINT: FwLinePage,
         "FreeWorks_Circle": FwCirclePage, "FreeWorks_PerimeterCircle": FwPerimeterCirclePage,
         "FreeWorks_StraightSlot": FwSlotPage, "FreeWorks_CenterpointStraightSlot": FwCenterpointSlotPage,
         "FreeWorks_ThreePointArcSlot": FwThreePointArcSlotPage, "FreeWorks_CenterpointArcSlot": FwCenterpointArcSlotPage,
         "FreeWorks_Point": FwPointPage,
         "FreeWorks_Ellipse": FwEllipsePage, "FreeWorks_PartialEllipse": FwPartialEllipsePage,
         "FreeWorks_Trim": FwTrimPage, "FreeWorks_Extend": FwExtendPage}
