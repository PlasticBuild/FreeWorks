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
from . import unitbox

from . import contextbar, dimtools, relationspm, sketchtoolpm
from .widgets import alive

Qt = QtCore.Qt
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchTools"
LINE_TOOLS = ("Sketcher_CreatePolyline", "Sketcher_CreateLine")
MIDPOINT_LINE = "Sketcher_CreateMidpointLine"
FW_LINE = "FreeWorks_Line"
FW_MIDPOINT_LINE = "FreeWorks_MidpointLine"
NOT_YET = "Not in FreeCAD yet"
NUMERIC = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"     # OnScreenNumericInput (patch 22)
TRIM_TOOLS = ("Sketcher_Trimming",)
MIRROR = "SWStyle_MirrorEntities"
CENTERLINE = "SWStyle_Centerline"
_centerline_next = False    # the next Insert Line page starts with For construction (Centerline)


def _params():
    return App.ParamGet(PARAMS)


def _line_params():
    try:
        from .fwsketch import line
        return App.ParamGet(line.TOOL_PARAMS)
    except Exception:
        return App.ParamGet(PARAMS)


def _shell():
    return sketchtoolpm._shell()


def _tool_running():
    shell = _shell()
    return shell is not None and contextbar.tool_running(shell)


def _cursor_key():
    """The running tool's picture cursor, to tell one tool from the next."""
    shell = _shell()
    view = shell.view_widget() if shell is not None else None
    if view is None or not alive(view):
        return None
    widget = view.viewport() if hasattr(view, "viewport") else view
    return widget.cursor().pixmap().cacheKey()


def _end_tool():
    """Ends FreeCAD's running sketch tool the way Esc does, without leaving the sketch."""
    try:
        from .fwsketch import toolbase
        if toolbase.active() is not None:
            return
    except Exception as _fw_err:
        _fw_log("nativepms.py:93", _fw_err)
    shell = _shell()
    view = shell.view_widget() if shell is not None else None
    if view is None or not alive(view):
        return
    from PySide import QtGui
    for _ in range(3):
        if not _tool_running():
            return
        for t in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(view, QtGui.QKeyEvent(t, Qt.Key_Escape, Qt.NoModifier))
        Gui.updateGui()


GAP = 5     # polls without the tool before its page goes


class _WrapCheck(QtWidgets.QCheckBox):
    """trimwrap-1121: a check box whose text sits in a wrapping label beside it; text() still gives that text."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text
        self.label = None

    def text(self):
        return self._text

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.EnabledChange and self.label is not None and alive(self.label):
            self.label.setEnabled(self.isEnabled())


class _WrapLabel(QtWidgets.QLabel):
    def __init__(self, text, box, parent=None):
        super().__init__(text, parent)
        self.box = box
        self.setWordWrap(True)
        self.setBuddy(box)

    def mousePressEvent(self, event):
        if self.box.isEnabled():
            self.box.toggle()


def _wrap_check(group, text, name):
    row = QtWidgets.QWidget(group.body)
    lay = QtWidgets.QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)               # the text starts where the radio buttons' texts do
    box = _WrapCheck(text, row)
    box.setObjectName(name)
    box.setAccessibleName(text)
    lab = _WrapLabel(text, box, row)
    lab.setObjectName(name + "Text")
    try:
        grey = relationspm._tok("text_disabled", "#a0a0a0").name()
        lab.setStyleSheet("QLabel:disabled { color: %s; }" % grey)
    except Exception as _fw_err:
        _fw_log("nativepms.py:wrap_check", _fw_err)
    box.label = lab
    lay.addWidget(box, 0, Qt.AlignTop)
    lay.addWidget(lab, 1)
    group.content.addWidget(row)
    return box


class _GeometryObserver:
    def __init__(self, page):
        self.page = page

    def slotChangedObject(self, obj, prop):
        page = self.page
        if prop == "Geometry" and page is not None and obj is page.sketch:
            QtCore.QTimer.singleShot(0, lambda: alive(page) and page.tick())


class _ToolOptionsPage(sketchtoolpm.ToolPage):
    """A page that rides along with a running FreeCAD tool and closes when it ends."""

    def __init__(self, sketch, native, parent=None):
        self.native = native
        super().__init__(sketch, parent)
        self.setProperty("swstyle_pm_title", self.TITLE)
        self.seen = False           # the tool was seen running
        self.cursor = None          # its picture cursor at the last poll
        self.idle = 0
        self.watch = QtCore.QTimer(self)
        self.watch.setInterval(150)
        self.watch.timeout.connect(self._poll)
        self.watch.start()
        # each new entity gets the page's settings as soon as the tool adds it
        self.observer = _GeometryObserver(self)
        App.addDocumentObserver(self.observer)

    def message(self, text):
        g = self.group("Message")
        label = QtWidgets.QLabel(text, g.body)
        label.setWordWrap(True)
        g.content.addWidget(label)
        return label

    def _poll(self):
        if _tool_running():
            self.seen, self.idle = True, 0
            self.cursor = _cursor_key()
            self.tick()
            return
        self.idle += 1
        # a tool in continuous mode starts again after each chain: a short gap is not the end
        if self.seen and self.idle >= GAP or self.idle >= 14:
            self.tick()
            self.watch.stop()
            self.leave()

    def tick(self):
        pass

    def accept(self):
        self.watch.stop()
        _end_tool()
        self.tick()
        super().accept()

    def reject(self):

        self.watch.stop()
        _end_tool()
        self.tick()
        sketchtoolpm.close(self)

    def taken_over(self):
        """Another FreeCAD tool replaced this one: close the page and leave the new tool running."""
        self.watch.stop()
        self.tick()
        self.leave()

    def closing(self):
        self.watch.stop()
        self.observer.page = None
        try:
            App.removeDocumentObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("nativepms.py:186", _fw_err)


# --------------------------------------------------------------------------- Insert Line
ORIENTATIONS = ("As sketched", "Horizontal", "Vertical", "Angle")
INSERT_LINE_MESSAGE = "Edit the settings of the next line, or sketch a line in the graphics area."
LINE_PROPERTIES_MESSAGE = ("Edit the settings of the current line, sketch a new line, or select OK to change "
                           "the settings for the next line.")


class LinePage(_ToolOptionsPage):
    OK_ONLY = True
    TITLE = "Insert Line"
    ICON = "SKETCH_LINE"
    PIXMAP = "Sketcher_CreateLine"

    def build(self):
        p = _params()
        self.count = len(self.sketch.Geometry)
        self.msg = self.message(INSERT_LINE_MESSAGE)
        g = self.group("Orientation")
        self.orient_group = g
        self.orientation = QtWidgets.QButtonGroup(g.body)
        chosen = p.GetString("LineOrientation", "As sketched")
        for i, name in enumerate(ORIENTATIONS):
            b = QtWidgets.QRadioButton(name, g.body)
            b.setObjectName("SWLine" + name.replace(" ", ""))
            b.setChecked(name == chosen)
            self.orientation.addButton(b, i)
            g.content.addWidget(b)
        if self.orientation.checkedButton() is None:
            self.orientation.button(0).setChecked(True)
        self.angle = unitbox.UnitSpinBox(g.body)
        self.angle.setObjectName("SWLineAngle")
        self.angle.setRange(-360.0, 360.0)
        self.angle.setDecimals(2)
        self.angle.setSuffix("°")
        self.angle.setValue(p.GetFloat("LineAngle", 45.0))
        self.angle.setToolTip("Angle from the horizontal for the next lines")
        g = self.group("Options")
        options = g
        self.options_group = g
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWLineForConstruction")
        global _centerline_next
        self.centerline = _centerline_next
        _centerline_next = False
        self.construction.setChecked(self.centerline or p.GetBool("LineForConstruction", False))
        g.content.addWidget(self.construction)

        # Midpoint line (the line grows both ways from its first click) and Add dimensions (a

        self.infinite = QtWidgets.QCheckBox("Infinite length", g.body)
        self.infinite.setObjectName("SWLineInfiniteLength")
        fw_line = _fw_tool() is not None
        commands = Gui.listCommands()

        # which draws it (fix57: no greyed box)
        can_infinite = fw_line or FW_LINE in commands
        self.infinite.setEnabled(can_infinite)
        line_params = _line_params()
        self.infinite.setChecked(fw_line and line_params.GetBool("LineInfinite", False))
        self.infinite.setToolTip("Each line runs on past its two clicks (%d mm each way)" % 5000
                                 if can_infinite else NOT_YET)
        self.infinite.toggled.connect(self._infinite)
        g.content.addWidget(self.infinite)
        self.midpoint = QtWidgets.QCheckBox("Midpoint line", g.body)
        self.midpoint.setObjectName("SWLineMidpoint")
        self.midpoint.setChecked(self.native in (MIDPOINT_LINE, FW_MIDPOINT_LINE))
        has_midpoint = MIDPOINT_LINE in commands or FW_MIDPOINT_LINE in commands
        self.midpoint.setEnabled(has_midpoint)
        self.midpoint.setToolTip("Sketches a line from its midpoint" if has_midpoint else NOT_YET)
        g.content.addWidget(self.midpoint)
        self.dimensions = QtWidgets.QCheckBox("Add dimensions", g.body)
        self.dimensions.setObjectName("SWLineAddDimensions")
        numeric = App.ParamGet(NUMERIC).GetBool("OnScreenNumericInput", False)
        # relations patch 27: a Sketcher that can leave a typed length without its dimension
        try:
            from . import native
            optional = "typed_dimension" in native.features()
        except Exception:
            optional = False
        optional = optional or _fw_tool() is not None
        keeps = App.ParamGet(NUMERIC).GetBool("NumericInputAddsDimension", True) if optional else True
        self.dimensions.setChecked(numeric and keeps)


        self.dimensions.setEnabled(optional)
        if not numeric and optional:
            self.dimensions.setToolTip("Turns on the on-screen numeric input (Options > Sketch): "
                                       "a length typed in its box is kept as a dimension")
        elif not numeric:
            self.dimensions.setToolTip("Turn on Enable on-screen numeric input in Options > Sketch to type lengths")
        elif optional:
            self.dimensions.setToolTip("A length typed in the on-screen box is kept as a dimension")
        else:
            self.dimensions.setToolTip("A length typed in the on-screen box is kept as a dimension "
                                       "(this FreeCAD always keeps it)")
        self.dimensions.toggled.connect(self._dimensions_toggled)
        g.content.addWidget(self.dimensions)

        # sketched) and, for Angle, the angle
        self.params_group = self.group("Parameters")
        form = QtWidgets.QFormLayout()
        self.length = unitbox.UnitSpinBox(self.params_group.body)
        self.length.setObjectName("SWLineLength")
        self.length.setRange(0.0, 1e6)
        self.length.setDecimals(2)
        self.length.setSuffix(" mm")
        self.length.setSpecialValueText("As sketched")
        self.length.setValue(_line_params().GetFloat("LineLengthValue", 0.0))
        self.length.setToolTip("Length of the next lines (as sketched when 0)")
        self.angle.setParent(self.params_group.body)
        self.length_label = QtWidgets.QLabel("Length:", self.params_group.body)
        self.angle_label = QtWidgets.QLabel("Angle:", self.params_group.body)
        form.addRow(self.length_label, self.length)
        form.addRow(self.angle_label, self.angle)
        self.params_group.content.addLayout(form)
        if _fw_tool() is None:              # FreeCAD's own Line has no length to hold to
            self.length.hide()
            self.length_label.hide()
        self.length.valueChanged.connect(self._remember)
        self.midpoint.toggled.connect(self._switch_tool)
        self.orientation.buttonClicked.connect(self._remember)
        self.construction.toggled.connect(self._construction_toggled)
        self.angle.valueChanged.connect(self._remember)
        self._remember()

        from . import currententity
        self.current = currententity.CurrentEntity(self, self.orient_group)

    # ------------------------------------------------------------ Line Properties
    def _properties_mode(self):
        cur = getattr(self, "current", None)
        return cur is not None and cur.active()

    def show_line(self, geo):
        ""
        cur = getattr(self, "current", None)
        if cur is None or not cur.show_for(geo):
            return
        self.title.setText("Line Properties")
        self.setProperty("swstyle_pm_title", "Line Properties")
        self.msg.setText(LINE_PROPERTIES_MESSAGE)
        for w in (self.orient_group, getattr(self, "params_group", None), self.midpoint, self.dimensions):
            if w is not None:
                w.hide()
        for box, on in ((self.construction, cur.construction()), (self.infinite, cur.infinite())):
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)

    def show_next(self):
        """OK in Line Properties: back to the settings of the next line, the tool still running."""
        cur = getattr(self, "current", None)
        if cur is not None:
            cur.hide()
        self.title.setText(self.TITLE)
        self.setProperty("swstyle_pm_title", self.TITLE)
        self.msg.setText(INSERT_LINE_MESSAGE)
        self.orient_group.show()
        self.midpoint.show()
        self.dimensions.show()
        p = _params()
        for box, on in ((self.construction, self.centerline or p.GetBool("LineForConstruction", False)),
                        (self.infinite, _fw_tool() is not None and _line_params().GetBool("LineInfinite", False))):
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)
        self._remember()

    def accept(self):
        if self._properties_mode() and _tool_running():
            self.show_next()
            return
        super().accept()

    def _dimensions_toggled(self, on):
        App.ParamGet(NUMERIC).SetBool("NumericInputAddsDimension", bool(on))
        if on and not App.ParamGet(NUMERIC).GetBool("OnScreenNumericInput", False):
            App.ParamGet(NUMERIC).SetBool("OnScreenNumericInput", True)

    def _construction_toggled(self, on):
        if self._properties_mode():
            self.current.set_construction(on)
            return
        self._remember()

    def _infinite(self, on):
        ""
        if self._properties_mode():
            self.current.set_infinite(on)
            return
        _line_params().SetBool("LineInfinite", bool(on))
        if on and _fw_tool() is None and FW_LINE in Gui.listCommands():
            self._hand_over(FW_LINE)

    def _switch_tool(self, on):
        """Midpoint line ticked or unticked: the other tool takes over, with its own page."""
        if on:
            name = MIDPOINT_LINE if MIDPOINT_LINE in Gui.listCommands() else FW_MIDPOINT_LINE
        else:
            name = LINE_TOOLS[0]
        if name == self.native:
            return
        self._hand_over(name)

    def _hand_over(self, name):
        global _centerline_next
        _centerline_next = self.centerline
        self.watch.stop()
        _end_tool()
        self.tick()
        sketchtoolpm.close(self)        # quietly: the cross would end the next tool too
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(name, 0))

    def chosen(self):
        b = self.orientation.checkedButton()
        return b.text() if b is not None else "As sketched"

    def _remember(self, *args):
        fixed = self.chosen() != "As sketched"
        self.angle.setEnabled(self.chosen() == "Angle")
        dims = getattr(self, "dimensions", None)
        if dims is not None:

            # Horizontal, Vertical and Angle (triple clamp 5:08: As sketched, no numeric input)
            numeric = App.ParamGet(NUMERIC).GetBool("OnScreenNumericInput", False)
            dims.setVisible((numeric or fixed) and not self._properties_mode())
        group = getattr(self, "params_group", None)
        if group is not None:
            group.setVisible(fixed and not self._properties_mode())
            self.angle.setVisible(self.chosen() == "Angle")
            self.angle_label.setVisible(self.chosen() == "Angle")

            if fixed and _fw_tool() is not None and not self.dimensions.isEnabled():
                self.dimensions.setEnabled(True)
                self.dimensions.blockSignals(True)
                self.dimensions.setChecked(App.ParamGet(NUMERIC).GetBool("NumericInputAddsDimension", True))
                self.dimensions.blockSignals(False)
                self.dimensions.setToolTip("The length set in Parameters (or typed) is kept as a dimension")
            _line_params().SetFloat("LineLengthValue", self.length.value())
            _line_params().SetFloat("LineLength", self.length.value() if fixed else 0.0)
        p = _params()
        p.SetString("LineOrientation", self.chosen())
        if not self.centerline:     # Centerline's ticked box is not the next Line's default
            p.SetBool("LineForConstruction", self.construction.isChecked())
        p.SetFloat("LineAngle", self.angle.value())

    def tick(self):
        """New lines get the page's orientation and construction setting."""
        sketch = self.sketch
        try:
            geos = sketch.Geometry
        except Exception:
            return
        n = len(geos)
        if n < self.count:
            self.count = n          # Undo took some back
        if n == self.count:
            return
        new = [i for i in range(self.count, n) if type(geos[i]).__name__ == "LineSegment"]
        self.count = n
        if not new:
            if self._properties_mode():
                self.current.fill()
            return
        if self._properties_mode():
            p = _params()
            construction = self.centerline or p.GetBool("LineForConstruction", False)
        else:
            construction = self.construction.isChecked()
        apply_line_options(sketch, new, self.chosen(), self.angle.value(), construction)
        self.show_line(new[-1])


def _has(sketch, kind, geo):
    return any(c.Type == kind and c.First == geo and (c.Second is None or c.Second <= -2000)
               for c in sketch.Constraints)


def apply_line_options(sketch, lines, orientation, angle, construction):
    """Horizontal/Vertical/Angle relations and construction for the lines just drawn."""
    C = dimtools._constraint
    cons = []
    for g in lines:
        if construction and not sketch.getConstruction(g):
            sketch.setConstruction(g, True)
        if orientation in ("Horizontal", "Vertical") and not _has(sketch, orientation, g):
            cons.append(C(orientation, g))
        elif orientation == "Angle" and not _has(sketch, "Angle", g):
            seg = sketch.Geometry[g]
            d = seg.EndPoint - seg.StartPoint
            want = math.radians(angle)
            # the line keeps the direction it was drawn in: the angle or its opposite
            if math.cos(math.atan2(d.y, d.x) - want) < 0:
                want += math.pi
            cons.append(C("Angle", g, want))
    for c in cons:
        dimtools.attempt(sketch, c)
    if cons or construction:
        sketchtoolpm._refresh(sketch)


# --------------------------------------------------------------------------- Trim Entities
TRIM_MODES = ("Power trim", "Corner", "Trim away inside", "Trim away outside", "Trim to closest")


def _trim_mode_icon(index, widget):
    ""


    pal = widget.palette()
    ink = pal.color(QtGui.QPalette.WindowText)
    dark = pal.color(QtGui.QPalette.Window).lightness() < 128
    blue, red = QtGui.QColor(70, 140, 230), QtGui.QColor(225, 70, 60)
    icons = []
    for on in (False, True):
        pm = QtGui.QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(2, 2)
        frame = QtGui.QColor(60, 140, 220) if on else QtGui.QColor(130, 130, 130)
        fill = (QtGui.QColor(44, 74, 102) if dark else QtGui.QColor(204, 228, 247)) if on else Qt.transparent
        p.setPen(QtGui.QPen(frame, 1))
        p.setBrush(fill)
        p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, 31, 31), 2, 2)

        def pen(colour, dash=False, width=1.6):
            q = QtGui.QPen(colour, width)
            q.setCapStyle(Qt.RoundCap)
            if dash:
                q.setDashPattern([2, 2])
            p.setPen(q)
            p.setBrush(Qt.NoBrush)

        def line(x1, y1, x2, y2):
            p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
        if index == 0:          # power trim: a pointer trail across a curve
            pen(ink)
            path = QtGui.QPainterPath(QtCore.QPointF(8, 26))
            path.cubicTo(8, 12, 14, 7, 26, 7)
            p.drawPath(path)
            pen(red, True)
            line(6, 14, 22, 22)
        elif index == 1:        # corner: two lines carried to their meeting point
            pen(ink)
            line(7, 25, 7, 12)
            line(12, 7, 25, 7)
            pen(blue, True)
            line(7, 12, 7, 7)
            line(7, 7, 12, 7)
        elif index in (2, 3):   # trim away inside / outside: two bounds and a line across
            pen(blue)
            line(11, 5, 11, 27)
            line(21, 5, 21, 27)
            if index == 2:
                pen(ink)
                line(4, 16, 11, 16)
                line(21, 16, 28, 16)
                pen(red, True)
                line(11, 16, 21, 16)
            else:
                pen(ink)
                line(11, 16, 21, 16)
                pen(red, True)
                line(4, 16, 11, 16)
                line(21, 16, 28, 16)
        else:                   # trim to closest: a line cut back to the nearest bound
            pen(blue)
            line(20, 5, 20, 27)
            pen(ink)
            line(5, 16, 20, 16)
            pen(red, True)
            line(20, 16, 28, 16)
        p.end()
        pm.setDevicePixelRatio(2)
        icons.append(QtGui.QIcon(pm))
    return icons            # (unchecked, checked): a radio button paints only its Off icon
OWN_MODES = ("Corner", "Trim away inside", "Trim away outside")     # FreeCAD's Trim has none of these
BOUNDED = ("Trim away inside", "Trim away outside")
TRIM_HINTS = {
    "Power trim": "Hold the left button and drag across the entities to trim them, or click an entity.",
    "Corner": "Select two entities to extend or trim them until they meet at a corner.",
    "Trim away inside": "Select two bounding entities, then select the entities to trim away inside them.",
    "Trim away outside": "Select two bounding entities, then select the entities to keep inside them.",
    "Trim to closest": "Click the part of an entity to trim back to the closest intersection.",
}


def _native(marker):
    try:
        from . import native
        return native.has(marker)
    except Exception:
        return False


def trim_options():
    """(keep trimmed entities as construction, ignore trimming of construction geometry)."""
    p = _params()
    return p.GetBool("TrimKeepConstruction", False), p.GetBool("TrimIgnoreConstruction", False)


def set_trim_options(keep, ignore):
    """Both Trim options, for the Trim page and for FreeCAD's own Trim (the relations thread's
    package 31 reads TrimKeepAsConstruction and TrimIgnoreConstruction live)."""
    p = _params()
    p.SetBool("TrimKeepConstruction", bool(keep))
    p.SetBool("TrimIgnoreConstruction", bool(ignore))
    general = App.ParamGet(NUMERIC)
    general.SetBool("TrimKeepAsConstruction", bool(keep))
    general.SetBool("TrimIgnoreConstruction", bool(ignore))
    page = sketchtoolpm.current()
    if isinstance(page, TrimPage) and alive(page):
        page.options_changed(bool(keep), bool(ignore))


class TrimPage(_ToolOptionsPage):
    TITLE = "Trim"
    ICON = "SKETCH_TRIM"
    PIXMAP = "Sketcher_Trimming"

    def build(self):
        p = _params()
        self.drag = None            # entities trimmed in this drag
        self.pressed = False        # a click the page handles itself
        self.picks = []             # Corner: [(entity, sketch point)]; inside/outside: bounding entities
        self.view = None
        self.hint = self.message("")
        g = self.group("Options")
        self.modes = QtWidgets.QButtonGroup(g.body)
        chosen = p.GetString("TrimMode", "Power trim")
        for i, name in enumerate(TRIM_MODES):
            b = QtWidgets.QRadioButton(name, g.body)
            b.setObjectName("SWTrim" + name.replace(" ", ""))
            b.setChecked(name == chosen)

            off, on = _trim_mode_icon(i, g.body)
            b.setIcon(on if b.isChecked() else off)
            b.toggled.connect(lambda checked, b=b, off=off, on=on: b.setIcon(on if checked else off))
            b.setIconSize(QtCore.QSize(32, 32))
            b.setStyleSheet("QRadioButton { spacing: 0px; padding: 1px 0px; }"
                            " QRadioButton::indicator { width: 0px; height: 0px; border: none; margin: 0px; }")
            b.setProperty("fw_trim_icon", True)
            self.modes.addButton(b, i)
            g.content.addWidget(b)
        if self.modes.checkedButton() is None:
            self.modes.button(0).setChecked(True)
        self.bounds_label = QtWidgets.QLabel("Bounding entities:", g.body)
        self.bounds = QtWidgets.QListWidget(g.body)
        self.bounds.setObjectName("SWTrimBounds")
        self.bounds.setFixedHeight(44)
        self.bounds.setToolTip("The two entities to trim inside or outside of")
        g.content.addWidget(self.bounds_label)
        g.content.addWidget(self.bounds)

        # pane and its fold arrows were cut off at the right
        self.keep = _wrap_check(g, "Keep trimmed entities as construction geometry", "SWTrimKeepConstruction")
        self.keep.setChecked(p.GetBool("TrimKeepConstruction", False))
        self.ignore = _wrap_check(g, "Ignore trimming of construction geometry", "SWTrimIgnoreConstruction")
        self.ignore.setChecked(p.GetBool("TrimIgnoreConstruction", False))
        self.modes.buttonClicked.connect(self._mode_changed)
        self.keep.toggled.connect(self._remember)
        self.ignore.toggled.connect(self._remember)
        self._remember()
        # FreeCAD's Trim puts the arrow cursor back after each trim although it goes on: after a
        # click the page keeps Trim running until Esc, a right click or another tool
        self.clicked = False
        self.keys = None
        shell = _shell()
        view = shell.view_widget() if shell is not None else None
        if view is not None and alive(view):
            self.view = view.viewport() if hasattr(view, "viewport") and view.viewport() else view
            self.view.installEventFilter(self)
            if self.view is not view:
                self.keys = view
                view.installEventFilter(self)

    def _poll(self):
        if self.clicked and self.seen and not _tool_running():
            self.idle = 0
            return
        super()._poll()

    def _end_trim(self):
        self.watch.stop()
        if self.clicked and not _tool_running():
            shell = _shell()
            view = shell.view_widget() if shell is not None else None
            if view is not None and alive(view):
                from PySide import QtGui
                for t in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                    QtWidgets.QApplication.sendEvent(view, QtGui.QKeyEvent(t, Qt.Key_Escape, Qt.NoModifier))
        self.clicked = False

    def accept(self):
        self._end_trim()
        super().accept()

    def reject(self):
        self._end_trim()
        super().reject()

    def mode(self):
        b = self.modes.checkedButton()
        return b.text() if b is not None else "Power trim"

    def power(self):
        return self.mode() == "Power trim"

    def _mode_changed(self, *args):
        self.picks = []
        self._show_picks()
        self._remember()

    def _remember(self, *args):
        mode = self.mode()
        self.hint.setText(TRIM_HINTS[mode])
        bounded = mode in BOUNDED
        self.bounds_label.setVisible(bounded)
        self.bounds.setVisible(bounded)
        self.keep.setEnabled(mode != "Corner")
        p = _params()
        p.SetString("TrimMode", mode)
        p.SetBool("TrimKeepConstruction", self.keep.isChecked())
        p.SetBool("TrimIgnoreConstruction", self.ignore.isChecked())
        set_trim_options(self.keep.isChecked(), self.ignore.isChecked())

    def options_changed(self, keep, ignore):
        """The sketch-tool menu switched an option: the boxes follow."""
        for box, on in ((self.keep, keep), (self.ignore, ignore)):
            if box.isChecked() != on:
                box.setChecked(on)

    def _own_click(self):
        """The page trims this click itself (FreeCAD's Trim would do something else)."""
        return self.mode() in OWN_MODES or (self.keep.isChecked() and not _native("trim_construction"))

    def _hovered_edge(self):
        try:
            hit = relationspm.preselected_element(self.sketch)   # Body-edited sketches too
            if hit is not None and hit[0].startswith("Edge"):
                return int(hit[0][4:]) - 1, hit[1]
        except Exception as _fw_err:
            _fw_log("nativepms.py:565", _fw_err)
        return None

    def _skip(self, geo):
        try:
            return self.ignore.isChecked() and self.sketch.getConstruction(geo)
        except Exception:
            return False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter555(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter nativepms.py: %s\n" % exc)
            return False

    def _fw_filter555(self, obj, event):
        t = event.type()
        if t == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Escape or \
                t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            self.clicked = False        # FreeCAD ends Trim: the cursor tells from here
            return False
        if obj is self.keys:
            return False
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            hit = self._hovered_edge()
            if hit is not None:
                self.clicked = True
            if hit is not None and self._skip(hit[0]):
                return True             # construction geometry is left alone
            if hit is not None and self._own_click():
                self.pressed = True
                self.drag = {self._key(hit[0])} if self.power() else None
                if hit[1] is not None:
                    # after the click: changing the sketch inside FreeCAD's mouse handling ends its tool
                    QtCore.QTimer.singleShot(0, lambda h=hit: alive(self) and self.picked(*h))
                return True
            self.drag = set() if self.power() else None
            if hit is not None and self.drag is not None:
                self.drag.add(self._key(hit[0]))
        elif t == QtCore.QEvent.MouseMove and self.drag is not None and event.buttons() & Qt.LeftButton:
            hit = self._hovered_edge()
            if hit is not None and hit[1] is not None and self._key(hit[0]) not in self.drag \
                    and not self._skip(hit[0]) and not (self.keep.isChecked() and self.sketch.getConstruction(hit[0])):
                self.drag.add(self._key(hit[0]))
                self.trim(hit[0], hit[1])
        elif t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.drag = None
            if self.pressed:
                self.pressed = False
                return True
        return False

    def _key(self, geo):
        """An entity by its shape, as trimming renumbers the rest."""
        try:
            g = self.sketch.Geometry[geo]
            return (type(g).__name__, round(g.StartPoint.x, 6), round(g.StartPoint.y, 6),
                    round(g.EndPoint.x, 6), round(g.EndPoint.y, 6))
        except Exception:
            return geo

    def _local(self, picked):
        local = self.sketch.getGlobalPlacement().inverse().multVec(App.Vector(*picked))
        return App.Vector(local.x, local.y, 0)

    def _show_picks(self):
        self.bounds.clear()
        names = relationspm._entity_names(self.sketch.Geometry)
        geos = [g for g, _p in self.picks] if self.mode() == "Corner" else self.picks
        if self.mode() in BOUNDED:
            for g in geos:
                if 0 <= g < len(names):
                    self.bounds.addItem(names[g])

    def picked(self, geo, picked):
        """A click on entity geo at picked (global) in one of the page's own modes."""
        from . import trimmodes
        mode = self.mode()
        sketch = self.sketch
        try:
            local = self._local(picked)
        except Exception:
            return
        deleted = None
        try:
            if mode == "Corner":
                if not self.picks or self.picks[0][0] == geo:
                    self.picks = [(geo, local)]
                    self._show_picks()
                    return
                (first, at), self.picks = self.picks[0], []
                trimmodes.corner(sketch, first, at, geo, local)
            elif mode in BOUNDED:
                if len(self.picks) < 2:
                    if geo not in self.picks:
                        self.picks.append(geo)
                    self._show_picks()
                    return
                if geo in self.picks:
                    return
                trim = trimmodes.trim_inside if mode == "Trim away inside" else trimmodes.trim_outside
                deleted = trim(sketch, geo, self.picks, local, self.keep.isChecked())
                self.picks = [g for g in trimmodes.shift(self.picks, deleted or []) if g is not None]
            else:
                trimmodes.trim(sketch, geo, local, construction=self.keep.isChecked(),
                               skip_construction=self.ignore.isChecked())
        except ValueError as error:
            self.show_note(str(error), True)
            self._show_picks()
            return
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: trim: %s\n" % error)
            return
        self.show_note("")
        sketchtoolpm._refresh(sketch)
        self._show_picks()
        try:
            Gui.Selection.clearPreselection()
        except Exception as _fw_err:
            _fw_log("nativepms.py:688", _fw_err)

    def trim(self, geo, picked):
        """Trims entity geo at the point under the pointer (picked is global)."""
        if self.keep.isChecked():
            self.picked(geo, picked)
            return
        sketch = self.sketch
        try:
            local = self._local(picked)
        except Exception:
            return
        doc = sketch.Document
        doc.openTransaction("Trim")
        try:
            sketch.trim(geo, local)
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: power trim: %s\n" % error)
            return
        sketchtoolpm._refresh(sketch)
        try:
            Gui.Selection.clearPreselection()
        except Exception as _fw_err:
            _fw_log("nativepms.py:713", _fw_err)

    def closing(self):
        super().closing()
        for w in (self.view, self.keys):
            if w is not None and alive(w):
                w.removeEventFilter(self)


# --------------------------------------------------------------------------- Mirror Entities
class _ViewOnly(QtCore.QObject):
    """Hands the picker only the events of one view's viewport."""

    def __init__(self, picker, viewport):
        super().__init__()
        self.picker, self.viewport = picker, viewport

    def eventFilter(self, obj, event):
        if self.viewport is None or obj is not self.viewport:
            return False
        return self.picker.eventFilter(obj, event)


class MirrorPage(sketchtoolpm.ToolPage):
    TITLE = "Mirror"
    ICON = "SKETCH_MIRROR_ENTITIES"
    PIXMAP = "Sketcher_Symmetry"
    TRANSACTION = "Mirror Entities"

    def build(self):
        self.setProperty("swstyle_pm_title", self.TITLE)
        self.entities = []
        self.axis = None
        self.target = "entities"        # the box picks go to
        g = self.group("Message")
        label = QtWidgets.QLabel("Select entities to mirror and a line or centerline to mirror about.", g.body)
        label.setWordWrap(True)
        g.content.addWidget(label)
        g = self.group("Options")
        self.list = QtWidgets.QListWidget(g.body)
        self.list.setObjectName("SWMirrorEntities")
        self.list.setFixedHeight(80)
        self.list.setToolTip("Entities to mirror")
        g.content.addWidget(QtWidgets.QLabel("Entities to mirror:", g.body))
        g.content.addWidget(self.list)
        self.copy = QtWidgets.QCheckBox("Copy", g.body)
        self.copy.setObjectName("SWMirrorCopy")
        self.copy.setChecked(_params().GetBool("MirrorCopy", True))
        self.copy.setToolTip("Off: the originals go and only the mirrored entities stay")
        g.content.addWidget(self.copy)
        g.content.addWidget(QtWidgets.QLabel("Mirror about:", g.body))
        self.about = QtWidgets.QListWidget(g.body)
        self.about.setObjectName("SWMirrorAbout")
        self.about.setFixedHeight(26)
        g.content.addWidget(self.about)
        # set before the filters go on: the boxes send events at once ("no attribute _region_view")
        self._region_view = None
        self._press_at = None
        for box, name in ((self.list, "entities"), (self.about, "about")):
            box.viewport().installEventFilter(self)
            box.setProperty("swTarget", name)
        self.copy.toggled.connect(self.changed)
        self._show_target()
        try:
            vp = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
            vp.installEventFilter(self)
            self._region_view = vp
        except Exception as _fw_err:
            _fw_log("nativepms.py:781", _fw_err)
        self.observer = sketchtoolpm.PickObserver(self)
        Gui.Selection.addObserver(self.observer)
        from . import convertentities as _CE
        self.model_picker = _CE._Picker(self)
        self.model_picker.install()
        # on the application, so it sees a press on the view before other application-level
        # filters of the sketch (those took the click on a model edge first)
        self._app_picker = _ViewOnly(self.model_picker, self._region_view)
        QtWidgets.QApplication.instance().installEventFilter(self._app_picker)
        picks = relationspm.picked_subs(self.sketch)
        for sub in picks:
            self.picked(sub, clear=False)
        if self.entities and self.axis is None:

            # is the active box, waiting for the line
            self.target = "about"
            self._show_target()
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("nativepms.py:802", _fw_err)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter741(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter nativepms.py: %s\n" % exc)
            return False

    def _fw_filter741(self, obj, event):
        if obj is self._region_view and self._region_view is not None:
            self._region_click(event)
            return False
        if event.type() == QtCore.QEvent.MouseButtonPress:
            for box, name in ((self.list, "entities"), (self.about, "about")):
                if obj is box.viewport():
                    self.target = name
                    self._show_target()
        return False

    def _region_click(self, event):
        ""

        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self._press_at = event.position()
            self._serial_at_press = getattr(self, "_pick_serial", 0)
            return
        if t != QtCore.QEvent.MouseButtonRelease or event.button() != QtCore.Qt.LeftButton or self._press_at is None:
            return
        p, at = event.position(), self._press_at
        self._press_at = None
        if self.target != "entities" or (p - at).manhattanLength() > 4:
            return          # a box drag: the usual picking
        x, y, serial = p.x(), p.y(), self._serial_at_press
        # after FreeCAD's own pick of the click: only when that picked no entity
        QtCore.QTimer.singleShot(60, lambda: getattr(self, "_pick_serial", 0) == serial and self._pick_region(x, y))

    def _pick_region(self, x, y):
        try:
            from . import rcmenus
            w = self._region_view
            dpr = w.devicePixelRatioF()
            point = Gui.ActiveDocument.ActiveView.getPoint(int(x * dpr), int((w.height() - y) * dpr))
            edges = rcmenus.contour_at(self.sketch, point)
        except Exception:
            return
        if not edges:
            return
        for i in edges:
            self.picked("Edge%d" % (i + 1), clear=False)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("nativepms.py:859", _fw_err)

    def _show_target(self):
        accent = relationspm._tok("accent", "#5a9bd5").name()
        for box, name in ((self.list, "entities"), (self.about, "about")):
            box.setStyleSheet("QListWidget { border: 1px solid %s; }" % accent if name == self.target else "")

    def picked(self, sub, clear=True):
        self._pick_serial = getattr(self, "_pick_serial", 0) + 1
        item = sketchtoolpm.item_of(self.sketch, sub)
        if clear:
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("nativepms.py:873", _fw_err)
        if item is None or item.pos != relationspm.NONE:
            return
        names = relationspm._entity_names(self.sketch.Geometry)
        axis = item.geo in (dimtools.H_AXIS, dimtools.V_AXIS)
        line = axis or (item.geo >= 0 and dimtools._kind(self.sketch.Geometry[item.geo]) == "line")

        # too (Triple Clamp video 2:01); the mirror line goes in once Mirror about is the active box
        if self.target == "about" or (axis and item.geo not in self.entities):
            if not line:
                self.show_note("Mirror about a line or centerline.", True)
                return
            self.axis = item.geo
            self.about.clear()
            self.about.addItem({dimtools.H_AXIS: "X axis", dimtools.V_AXIS: "Y axis"}.get(item.geo)
                               or names[item.geo])
            self.target = "entities"
            self._show_target()
        elif item.geo >= 0 and item.geo not in self.entities:
            self.entities.append(item.geo)
            self.list.addItem(names[item.geo])
        self.changed()

    def selection_changed(self):
        pass

    def changed(self, *args):
        self.undo_work()
        geos = [g for g in self.entities if g != self.axis]
        if not geos or self.axis is None:
            return
        self.begin()
        try:
            from . import dimcommands
            keep = [] if self.copy.isChecked() else _own_relations(self.sketch, geos, self.axis)
            copies = dimcommands.mirror_entities(self.sketch, geos, self.axis)
            if not self.copy.isChecked():
                self.sketch.delGeometries(sorted(geos))
                _carry_relations(self.sketch, keep, geos, copies)
        except Exception as error:
            self.show_note("Could not mirror: %s" % error, True)
            return
        sketchtoolpm._refresh(self.sketch)
        self.show_note("")

    def source_of(self, sub):
        return None

    def picked_model(self, obj, sub):
        """A straight model edge: the mirror line, linked to the model (through an ExtRef binder
        when the edge is outside the sketch's Body)."""
        from . import convertentities as _CE
        try:
            edge = obj.Shape.getElement(sub)
            straight = sub.startswith("Edge") and type(edge.Curve).__name__ in ("Line", "LineSegment")
        except Exception:
            straight = False
        if not straight:
            self.show_note("Mirror about a line, centerline or straight model edge.", True)
            return
        before = len(self.sketch.ExternalGeo)
        if _CE.add_external_linked(self.sketch, obj, sub) is None:
            self.show_note("Could not use that edge.", True)
            return
        self.sketch.solve()
        if len(self.sketch.ExternalGeo) <= before:
            return
        self.axis = -(before + 1)
        self.about.clear()
        self.about.addItem("%s@%s" % (sub, obj.Label))
        self.target = "entities"
        self._show_target()
        self.changed()

    def finish(self):
        _params().SetBool("MirrorCopy", self.copy.isChecked())

    def closing(self):
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("nativepms.py:952", _fw_err)
        self.observer.page = None
        try:
            self.model_picker.remove()
            QtWidgets.QApplication.instance().removeEventFilter(self._app_picker)
        except Exception as _fw_err:
            _fw_log("nativepms.py:958", _fw_err)
        try:
            if self._region_view is not None:
                self._region_view.removeEventFilter(self)
        except Exception as _fw_err:
            _fw_log("nativepms.py:963", _fw_err)
        self._region_view = None


# fix261: Copy cleared moves the entities across (the originals go). FreeCAD's mirror copies only
# the Coincident relations among them, so the moved lines lost their Horizontal, Vertical, Equal,

_CARRY = ("Horizontal", "Vertical", "Parallel", "Perpendicular", "Equal", "Tangent", "Distance",
          "Radius", "Diameter")


def _own_relations(sketch, geos, axis):
    """The relations and dimensions among the given entities only (not to other geometry).
    Horizontal and Vertical stay what they are only across a horizontal or vertical line."""
    from . import dimcommands
    try:
        a, b = dimcommands._axis_ends(sketch, axis)
        dx, dy = abs(b.x - a.x), abs(b.y - a.y)
        square = dx <= 1e-9 * max(1.0, dy) or dy <= 1e-9 * max(1.0, dx)
    except Exception:
        square = False
    inside = set(geos)
    out = []
    for c in sketch.Constraints:
        if c.Type not in _CARRY or (c.Type in ("Horizontal", "Vertical") and not square):
            continue
        refs = [g for g in (c.First, c.Second, c.Third) if g is not None and g != -2000]
        if refs and all(g in inside for g in refs):
            out.append((c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, c.Value))
    return out


def _carry_relations(sketch, keep, geos, copies):
    """keep (relations of the deleted originals) put back on their mirrored entities."""
    import Sketcher
    if not keep:
        return
    geos = list(geos)
    expanded = list(geos)
    try:
        from .fwsketch import helpers as _helpers
        expanded = list(_helpers.with_helpers(sketch, geos))
    except Exception as _fw_err:
        _fw_log("nativepms.py:carry helpers", _fw_err)
    gone = sorted(geos)
    to = {}
    for g, c in zip(expanded, copies):
        if g in geos:
            to[g] = c - sum(1 for d in gone if d < c)
    for kind, first, fpos, second, spos, value in keep:
        try:
            one = second in (None, -2000)
            f = to[first]
            if kind in ("Horizontal", "Vertical") and one:
                made = Sketcher.Constraint(kind, f)
            elif kind in ("Radius", "Diameter", "Distance") and one and fpos == 0:
                made = Sketcher.Constraint(kind, f, value)
            elif one:
                made = None
            elif kind == "Distance":
                made = (Sketcher.Constraint(kind, f, to[second], value) if fpos == 0 and spos == 0
                        else Sketcher.Constraint(kind, f, fpos, to[second], spos, value))
            elif fpos == 0 and spos == 0:
                made = Sketcher.Constraint(kind, f, to[second])
            else:
                made = Sketcher.Constraint(kind, f, fpos, to[second], spos)
        except Exception:
            made = None
        if made is not None:
            dimtools.attempt(sketch, made)


class MirrorCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_Symmetry", "MenuText": "Mirror Entities",
                "ToolTip": "Copies sketch entities across a line", "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            sketchtoolpm.open_page(MirrorPage(sketch))


class CenterlineCommand:
    ""

    def GetResources(self):
        return {"Pixmap": "Sketcher_CreateLine", "MenuText": "Centerline",
                "ToolTip": "Sketches centerlines (construction lines) for symmetry and mirroring",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        global _centerline_next
        page = sketchtoolpm.current()
        if isinstance(page, LinePage) and alive(page) and _tool_running():
            page.construction.setChecked(True)
            return
        _centerline_next = True
        if contextbar.sketch_in_edit() is not None:
            Gui.runCommand(LINE_TOOLS[0], 0)
            return
        from . import sketchstart
        if not sketchstart.run_draw(LINE_TOOLS[0]):
            _centerline_next = False


# --------------------------------------------------------------------------- Circle, Arc, Rectangle

# method in the tool's own list or None, icon family, FreeCAD pixmap)
SHAPES = {
    "Circle": (("Circle", "Sketcher_CreateCircle", None, "SKETCH_CIRCLE", "Sketcher_CreateCircle"),
               ("Perimeter Circle", "Sketcher_Create3PointCircle", None, "SKETCH_CTRPT_CIRCLE",
                "Sketcher_Create3PointCircle")),
    "Arc": (("Centerpoint Arc", "Sketcher_CreateArc", None, "SKETCH_CPRPT_ARC", "Sketcher_CreateArc"),
            ("Tangent Arc", "Sketcher_CreatePolyline", None, "SKETCH_TANGET_ARC", "Sketcher_CreatePolyline"),
            ("3 Point Arc", "Sketcher_Create3PointArc", None, "SKETCH_3PT_ARC", "Sketcher_Create3PointArc")),
    "Rectangle": (("Corner Rectangle", "Sketcher_CreateRectangle", 0, "SKETCH_CORNER_RECT", "Sketcher_CreateRectangle"),
                  ("Center Rectangle", "Sketcher_CreateRectangle_Center", 1, "SKETCH_CTR_RECT",
                   "Sketcher_CreateRectangle_Center"),
                  ("3 Point Corner Rectangle", "Sketcher_CreateRectangle", 2, "SKETCH_3PT_CORNER_RECT",
                   "Sketcher_CreateRectangle"),
                  ("3 Point Center Rectangle", "Sketcher_CreateRectangle", 3, "SKETCH_3PT_CENTER_RECT",
                   "Sketcher_CreateRectangle_Center"),
                  ("Parallelogram", "Sketcher_CreateRectangle", 2, "SKETCH_PARALLELOGRAM", "Sketcher_CreateRectangle")),
    # the relations thread's package 30 adds the two middle methods to FreeCAD's slot tools
    "Slot": (("Straight Slot", "Sketcher_CreateSlot", 0, "SKETCH_STRAIGHT_SLOT", "Sketcher_CreateSlot"),
             ("Centerpoint Straight Slot", "Sketcher_CreateSlot", 1, "SKETCH_CTRPT_STRAIGHT_SLOT", "Sketcher_CreateSlot"),
             ("3 Point Arc Slot", "Sketcher_CreateArcSlot", 2, "SKETCH_3PT_ARC_SLOT", "Sketcher_CreateArcSlot"),
             ("Centerpoint Arc Slot", "Sketcher_CreateArcSlot", 0, "SKETCH_CTRPT_ARC_SLOT", "Sketcher_CreateArcSlot")),
}
# types only a rebuilt Sketcher draws: native.py's marker for each; greyed without it
SHAPE_NEEDS = {"Centerpoint Straight Slot": "centerpoint_slot", "3 Point Arc Slot": "three_point_arc_slot"}


def _shape_available(name):
    need = SHAPE_NEEDS.get(name)
    if need is None:
        return True
    try:
        from . import native
        return native.has(need)
    except Exception:
        return False
SQUARED = ("3 Point Corner Rectangle", "3 Point Center Rectangle")     # FreeCAD draws these as parallelograms
CONSTRUCTION_LINES = ("From Corners", "From Midpoints")
SLOT_LENGTHS = ("Center to Center", "Overall Length")
_shape_next = None      # the type the next shape page starts with (a type button restarted the tool)


def _tool_method_box():
    """The construction method list of FreeCAD's running sketch tool (its tool widget)."""
    for box in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "comboBox1"):
        parent = box.parent()
        while parent is not None:
            if "SketcherToolDefaultWidget" in parent.objectName():
                return box if alive(box) and box.count() else None
            parent = parent.parent()
    return None


class ShapePage(_ToolOptionsPage):
    ""



    KIND = "Circle"

    def build(self):
        global _shape_next
        p = _params()
        self.types = SHAPES[self.KIND]
        self.count = len(self.sketch.Geometry)
        self.kind_type = _shape_next or self._type_of_tool(p)
        _shape_next = None
        self.message("Set the properties of the %s, or sketch it in the graphics area." % self.KIND.lower())
        g = self.group("%s Type" % self.KIND)
        try:
            from . import icons
            family = icons.family
        except Exception:
            family = lambda name: QtGui.QIcon()

        def icon(name):
            entry = next(t for t in self.types if t[0] == name)
            i = family(entry[3])
            return i if not i.isNull() else Gui.getIcon(entry[4])
        big = dict(rows=(2, 3), big=True) if self.KIND == "Rectangle" and len(self.types) == 5 else {}
        self.type_buttons = self.toggles(g, [t[0] for t in self.types], icon, lambda k: k == self.kind_type, **big)
        for name, b in self.type_buttons.items():
            b.clicked.connect(lambda _c=False, n=name: self.choose(n))
            if self._entry(name)[1] is None or not _shape_available(name):
                b.setEnabled(False)
                b.setToolTip("%s: %s" % (name, NOT_YET))
        g = self.group("Options")
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWShapeForConstruction")
        self.construction.setChecked(p.GetBool(self.KIND + "ForConstruction", False))
        g.content.addWidget(self.construction)
        self.lines = None
        if self.KIND == "Rectangle":
            self.lines = QtWidgets.QCheckBox("Add construction lines", g.body)
            self.lines.setObjectName("SWRectangleConstructionLines")
            center = self.kind_type == "Center Rectangle"
            self.lines.setChecked(p.GetBool("RectangleConstructionLines" + ("Center" if center else ""), center))
            g.content.addWidget(self.lines)
            self.line_kind = QtWidgets.QButtonGroup(g.body)
            chosen = p.GetString("RectangleConstructionLinesFrom", "From Corners")
            for i, name in enumerate(CONSTRUCTION_LINES):
                b = QtWidgets.QRadioButton(name, g.body)
                b.setObjectName("SWRectangle" + name.replace(" ", ""))
                b.setChecked(name == chosen)
                self.line_kind.addButton(b, i)
                g.content.addWidget(b)
            if self.line_kind.checkedButton() is None:
                self.line_kind.button(0).setChecked(True)
            self.lines.toggled.connect(self._remember)
            self.lines.toggled.connect(self._show_line_kinds)
            self.line_kind.buttonClicked.connect(lambda *a: self._picked(self.lines))
            self._show_line_kinds()
        self.dims = None
        if self.KIND == "Slot":
            self.dims = QtWidgets.QCheckBox("Add dimensions", g.body)
            self.dims.setObjectName("SWSlotAddDimensions")
            self.dims.setChecked(p.GetBool("SlotAddDimensions", False))
            g.content.addWidget(self.dims)
            self.length_kind = QtWidgets.QButtonGroup(g.body)
            chosen = p.GetString("SlotLength", SLOT_LENGTHS[0])
            for i, name in enumerate(SLOT_LENGTHS):
                b = QtWidgets.QRadioButton(name, g.body)
                b.setObjectName("SWSlot" + name.title().replace(" ", ""))
                b.setChecked(name == chosen)
                self.length_kind.addButton(b, i)
                g.content.addWidget(b)
            if self.length_kind.checkedButton() is None:
                self.length_kind.button(0).setChecked(True)
            self.dims.toggled.connect(self._remember)
            self.length_kind.buttonClicked.connect(lambda *a: self._picked(self.dims))
        self.construction.toggled.connect(self._remember)
        self._remember()
        # FreeCAD wires its tool to the list a little after the tool starts
        QtCore.QTimer.singleShot(300, lambda: alive(self) and self._set_method(True))

    def _type_of_tool(self, p):
        """The type the running FreeCAD tool draws."""
        if self.KIND != "Rectangle":
            return next((t[0] for t in self.types if t[1] == self.native), self.types[0][0])
        if self.native == "Sketcher_CreateRectangle_Center":
            return "Center Rectangle"
        box = _tool_method_box()
        method = box.currentIndex() if box is not None else 0
        if method == 2:
            last = p.GetString("RectangleThreePoint", "3 Point Corner Rectangle")
            return last if last in ("3 Point Corner Rectangle", "Parallelogram") else "3 Point Corner Rectangle"
        return {0: "Corner Rectangle", 1: "Center Rectangle", 3: "3 Point Center Rectangle"}.get(method, "Corner Rectangle")

    def _entry(self, name=None):
        name = name or self.kind_type
        return next(t for t in self.types if t[0] == name)

    def _set_method(self, fresh=False):
        """FreeCAD's tool draws the chosen type (its construction method list). fresh: the tool
        just started and its list may still show the last tool's method, so it is set again."""
        method = self._entry()[2]
        box = _tool_method_box()
        if method is None or box is None or method >= box.count():
            return
        if fresh and box.currentIndex() == method and box.count() > 1:
            box.setCurrentIndex((method + 1) % box.count())
        if box.currentIndex() != method:
            box.setCurrentIndex(method)

    def choose(self, name):
        """A type button: the same FreeCAD tool changes its method, another tool takes over."""
        for key, b in self.type_buttons.items():
            b.setChecked(key == name)
        entry = self._entry(name)
        if name in ("3 Point Corner Rectangle", "Parallelogram"):
            _params().SetString("RectangleThreePoint", name)
        if entry[1] == self.native:
            self.kind_type = name
            self._set_method()
            return
        global _shape_next
        _shape_next = name
        self.watch.stop()
        _end_tool()
        self.tick()
        sketchtoolpm.close(self)
        QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(entry[1], 0))

    def _remember(self, *args):
        p = _params()
        p.SetBool(self.KIND + "ForConstruction", self.construction.isChecked())
        if self.lines is not None:
            center = self.kind_type == "Center Rectangle"
            p.SetBool("RectangleConstructionLines" + ("Center" if center else ""), self.lines.isChecked())
            b = self.line_kind.checkedButton()
            p.SetString("RectangleConstructionLinesFrom", b.text() if b is not None else "From Corners")
        if self.dims is not None:
            p.SetBool("SlotAddDimensions", self.dims.isChecked())
            p.SetString("SlotLength", self.length_kind.checkedButton().text())

    def _show_line_kinds(self, *args):
        ""
        if self.lines is not None:
            for b in self.line_kind.buttons():
                b.setVisible(self.lines.isChecked())

    def _picked(self, box):
        """No dead (greyed) choice: picking one of a box's choices turns that box on."""
        if not box.isChecked():
            box.setChecked(True)
        else:
            self._remember()

    def _overall(self):
        """Slot lengths are measured overall (arc end to arc end), not centre to centre."""
        return self.length_kind.checkedButton().text() == SLOT_LENGTHS[1]

    def tick(self):
        sketch = self.sketch
        try:
            geos = sketch.Geometry
        except Exception:
            return
        n = len(geos)
        if n < self.count:
            self.count = n
        if n == self.count:
            return
        new = list(range(self.count, n))
        self.count = n
        if self.KIND == "Rectangle":
            self._rectangle(sketch, new)
        if self.KIND == "Slot":
            self._slot(sketch, new)
            new = list(range(new[0], len(sketch.Geometry)))
        if self.construction.isChecked():
            for g in new:
                if not sketch.getConstruction(g):
                    sketch.setConstruction(g, True)
            sketchtoolpm._refresh(sketch)
        self.count = len(sketch.Geometry)

    def _rectangle(self, sketch, new):
        """Square corners for the 3 point rectangles, then the construction lines."""
        C = dimtools._constraint
        geos = sketch.Geometry
        sides = [g for g in new if type(geos[g]).__name__ == "LineSegment" and not sketch.getConstruction(g)]
        if len(sides) != 4:
            return
        if self.kind_type in SQUARED and not any(c.Type == "Perpendicular" and {c.First, c.Second} == {sides[0], sides[1]}
                                                 for c in sketch.Constraints):
            dimtools.attempt(sketch, C("Perpendicular", sides[0], sides[1]))
        if self.lines is None or not self.lines.isChecked():
            sketchtoolpm._refresh(sketch)
            return
        geos = sketch.Geometry
        import Part
        import Sketcher
        if self.line_kind.checkedButton().text() == "From Corners":
            corners = [geos[g].StartPoint for g in sides]
            have = [g for g in new if type(geos[g]).__name__ == "LineSegment" and sketch.getConstruction(g)]
            if len(have) >= 2:          # FreeCAD's center rectangle drew its diagonals already
                sketchtoolpm._refresh(sketch)
                return
            for a, b in ((0, 2), (1, 3)):
                d = sketch.addGeometry(Part.LineSegment(corners[a], corners[b]), True)
                sketch.addConstraint(Sketcher.Constraint("Coincident", d, 1, sides[a], 1))
                sketch.addConstraint(Sketcher.Constraint("Coincident", d, 2, sides[b], 1))
        else:
            mids = [(geos[g].StartPoint + geos[g].EndPoint) * 0.5 for g in sides]
            for a, b in ((0, 2), (1, 3)):
                d = sketch.addGeometry(Part.LineSegment(mids[a], mids[b]), True)
                sketch.addConstraint(Sketcher.Constraint("Symmetric", sides[a], 1, sides[a], 2, d, 1))
                sketch.addConstraint(Sketcher.Constraint("Symmetric", sides[b], 1, sides[b], 2, d, 2))
        sketchtoolpm._refresh(sketch)


    def _slot(self, sketch, new):
        ""

        import Part
        C = dimtools._constraint
        geos = sketch.Geometry
        arcs = [g for g in new if type(geos[g]).__name__ == "ArcOfCircle"]
        lines = [g for g in new if type(geos[g]).__name__ == "LineSegment" and not sketch.getConstruction(g)]
        if len(arcs) == 2 and len(lines) == 2:
            a1, a2 = arcs
            c1, c2, r = geos[a1].Center, geos[a2].Center, geos[a1].Radius
            if (c2 - c1).Length < 1e-9:
                return
            u = (c2 - c1).normalize()
            overall = self.dims is not None and self.dims.isChecked() and self._overall()
            # the centerpoint method draws its own centerline (its midpoint is the centre point)
            def joins_centres(g):
                a, b = geos[g].StartPoint, geos[g].EndPoint
                return min((a - c1).Length + (b - c2).Length, (a - c2).Length + (b - c1).Length) < 1e-6
            own = [g for g in new if type(geos[g]).__name__ == "LineSegment" and sketch.getConstruction(g)
                   and joins_centres(g)]
            if own and not overall:
                axis = own[0]
            elif overall:
                axis = sketch.addGeometry(Part.LineSegment(c1 - u * r, c2 + u * r), True)
                for c in (C("PointOnObject", axis, 1, a1), C("PointOnObject", axis, 2, a2),
                          C("PointOnObject", a1, 3, axis), C("PointOnObject", a2, 3, axis)):
                    sketch.addConstraint(c)
            else:
                axis = sketch.addGeometry(Part.LineSegment(c1, c2), True)
                sketch.addConstraint(C("Coincident", axis, 1, a1, 3))
                sketch.addConstraint(C("Coincident", axis, 2, a2, 3))
            if self.dims is not None and self.dims.isChecked():
                geos = sketch.Geometry
                dimtools.attempt(sketch, C("Distance", axis, geos[axis].length()))
                dimtools.attempt(sketch, C("Distance", lines[0], 1, lines[1], 2 * r))
        elif len(arcs) == 4 and not lines and self.dims is not None and self.dims.isChecked():
            ends = sorted(arcs, key=lambda g: geos[g].Radius)[:2]
            outer = max(arcs, key=lambda g: geos[g].Radius)
            dimtools.attempt(sketch, C("Distance", outer, 3, ends[0], 3, (geos[ends[0]].Center - geos[outer].Center).Length))
            dimtools.attempt(sketch, C("Diameter", ends[0], 2 * geos[ends[0]].Radius))
        sketchtoolpm._refresh(sketch)


class CirclePage(ShapePage):
    OK_ONLY = True
    TITLE = "Circle"
    ICON = "SKETCH_CIRCLE"
    PIXMAP = "Sketcher_CreateCircle"
    KIND = "Circle"


class ArcPage(ShapePage):
    OK_ONLY = True
    TITLE = "Arc"
    ICON = "SKETCH_CPRPT_ARC"
    PIXMAP = "Sketcher_CreateArc"
    KIND = "Arc"


class RectanglePage(ShapePage):
    OK_ONLY = True
    TITLE = "Rectangle"
    ICON = "SKETCH_CORNER_RECT"
    PIXMAP = "Sketcher_CreateRectangle"
    KIND = "Rectangle"


class SlotPage(ShapePage):
    OK_ONLY = True
    TITLE = "Slot"
    ICON = "SKETCH_STRAIGHT_SLOT"
    PIXMAP = "Sketcher_CreateSlot"
    KIND = "Slot"


POLYGON_TOOLS = ("Sketcher_CreateRegularPolygon", "Sketcher_CreateTriangle", "Sketcher_CreateSquare",
                 "Sketcher_CreatePentagon", "Sketcher_CreateHexagon", "Sketcher_CreateHeptagon",
                 "Sketcher_CreateOctagon")
POLYGON_PARAM = "PolygonInscribedCircle"      # relations package 31; true = Inscribed circle


class PolygonPage(_ToolOptionsPage):
    ""


    OK_ONLY = True

    TITLE = "Polygon"
    ICON = "SKETCH_POLYGON"
    PIXMAP = "Sketcher_CreateRegularPolygon"

    def build(self):
        self.message("Set the polygon's properties, or sketch it in the graphics area.")
        g = self.group("Parameters")
        self.inscribed = QtWidgets.QRadioButton("Inscribed circle", g.body)
        self.inscribed.setObjectName("SWPolygonInscribed")
        self.circumscribed = QtWidgets.QRadioButton("Circumscribed circle", g.body)
        self.circumscribed.setObjectName("SWPolygonCircumscribed")
        general = App.ParamGet(NUMERIC)
        on = general.GetBool(POLYGON_PARAM, False)
        (self.inscribed if on else self.circumscribed).setChecked(True)
        g.content.addWidget(self.inscribed)
        g.content.addWidget(self.circumscribed)
        if not _native("polygon_inscribed"):
            self.inscribed.setChecked(True)
            for b in (self.inscribed, self.circumscribed):
                b.setEnabled(False)
                b.setToolTip(NOT_YET)
        self.inscribed.toggled.connect(self._remember)

    def _remember(self, *args):
        App.ParamGet(NUMERIC).SetBool(POLYGON_PARAM, self.inscribed.isChecked())


def _fw_tool():
    ""
    try:
        from .fwsketch import toolbase
        return toolbase.active()
    except Exception as _fw_err:
        _fw_log("nativepms.py:1383", _fw_err)
        return None


class _FwToolPage:
    ""



    def _own_tool(self):
        if not hasattr(self, "_tool"):
            self._tool = _fw_tool()
        return self._tool

    def _end_own(self):
        self.watch.stop()
        tool = self._own_tool()
        if tool is not None and _fw_tool() is tool:
            try:
                tool.end()
            except Exception as _fw_err:
                _fw_log("nativepms.py:1402", _fw_err)
        self.tick()

    def accept(self):
        self._end_own()
        sketchtoolpm.ToolPage.accept(self)

    def reject(self):
        self._end_own()
        sketchtoolpm.close(self)


class FwPolygonPage(_FwToolPage, PolygonPage):
    ""



    def build(self):
        self._own_tool()
        self.message("Set the polygon's properties, or sketch it in the graphics area.")
        g = self.group("Options")
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWPolygonForConstruction")
        self.construction.setChecked(_params().GetBool("PolygonForConstruction", False))
        g.content.addWidget(self.construction)
        g = self.group("Parameters")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Sides", g.body))
        self.sides = QtWidgets.QSpinBox(g.body)
        self.sides.setObjectName("SWPolygonSides")
        self.sides.setRange(3, 40)
        tool = _fw_tool()
        self.sides.setValue(getattr(tool, "sides", 6))
        row.addWidget(self.sides)
        row.addStretch(1)
        g.content.addLayout(row)
        self.inscribed = QtWidgets.QRadioButton("Inscribed circle", g.body)
        self.inscribed.setObjectName("SWPolygonInscribed")
        self.circumscribed = QtWidgets.QRadioButton("Circumscribed circle", g.body)
        self.circumscribed.setObjectName("SWPolygonCircumscribed")
        on = App.ParamGet(NUMERIC).GetBool(POLYGON_PARAM, False)
        (self.inscribed if on else self.circumscribed).setChecked(True)
        g.content.addWidget(self.inscribed)
        g.content.addWidget(self.circumscribed)

        self.fields = {}
        for key, label in (("cx", "Center X"), ("cy", "Center Y"), ("diameter", "Diameter"), ("angle", "Angle")):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(label, g.body))
            f = QtWidgets.QLineEdit("0.00°" if key == "angle" else "0.00", g.body)
            f.setObjectName("SWPolygon" + key)
            f.setReadOnly(True)      # placed, the polygon's own PM (Edit Polygon) takes typed values
            row.addWidget(f, 1)
            g.content.addLayout(row)
            self.fields[key] = f
        from . import paramedit      # fix57: typed values change the last polygon placed
        paramedit.wire(self, self.fields, "polygon")
        self.new_polygon = QtWidgets.QPushButton("New Polygon", g.body)
        self.new_polygon.setObjectName("SWPolygonNew")
        g.content.addWidget(self.new_polygon)
        self.inscribed.toggled.connect(self._remember)
        self.sides.valueChanged.connect(self._to_tool)
        self.construction.toggled.connect(self._to_tool)
        self.new_polygon.clicked.connect(self._new)
        self._to_tool()

    def _remember(self, *args):
        App.ParamGet(NUMERIC).SetBool(POLYGON_PARAM, self.inscribed.isChecked())
        self._to_tool()

    def _to_tool(self, *args):
        _params().SetBool("PolygonForConstruction", self.construction.isChecked())
        tool = _fw_tool()
        if tool is None or not hasattr(tool, "sides"):
            return
        tool.sides = self.sides.value()
        tool.construction = self.construction.isChecked()
        try:
            tool._move()
        except Exception as _fw_err:
            _fw_log("nativepms.py:1482", _fw_err)

    def tick(self):
        # U / J in the 3D view change the tool's sides: show them
        tool = _fw_tool()
        n = getattr(tool, "sides", None)
        if n is not None and alive(self.sides) and self.sides.value() != n:
            self.sides.blockSignals(True)
            self.sides.setValue(n)
            self.sides.blockSignals(False)
        centre = getattr(tool, "centre", None)
        if not alive(self.sides) or not getattr(self, "fields", None):
            return
        from . import paramedit
        if paramedit.editing(self.fields):
            return
        if centre is None:

            placed = paramedit.placed_values(self, "polygon")
            for key, v in placed.items():
                text = "%.2f°" % v if key == "angle" else "%.2f" % v
                if key in self.fields and self.fields[key].text() != text:
                    self.fields[key].setText(text)
            return
        corner = getattr(tool, "corner", None)
        radius = getattr(tool, "radius", 0.0) or 0.0
        values = {"cx": centre[0], "cy": centre[1], "diameter": 0.0, "angle": 0.0}
        if corner is not None and radius > 1e-9 and n:
            inscribed = App.ParamGet(NUMERIC).GetBool(POLYGON_PARAM, False)
            circle = radius * math.cos(math.pi / n) if inscribed else radius
            values["diameter"] = 2.0 * circle
            values["angle"] = math.degrees(math.atan2(corner[1] - centre[1], corner[0] - centre[0]))
        for key, v in values.items():
            text = "%.2f°" % v if key == "angle" else "%.2f" % v
            if self.fields[key].text() != text:
                self.fields[key].setText(text)

    def _new(self):
        ""
        tool = _fw_tool()
        if tool is not None and hasattr(tool, "reset"):
            tool.reset()
            self._to_tool()


FW_ARCS = (("Centerpoint Arc", "FreeWorks_CenterArc", "SKETCH_CPRPT_ARC", "Sketcher_CreateArc"),
           ("Tangent Arc", "FreeWorks_TangentArc", "SKETCH_TANGET_ARC", "Sketcher_CreatePolyline"),
           ("3 Point Arc", "FreeWorks_ThreePointArc", "SKETCH_3PT_ARC", "Sketcher_Create3PointArc"))


class FwArcPage(_FwToolPage, _ToolOptionsPage):
    ""


    OK_ONLY = True

    TITLE = "Arc"
    ICON = "SKETCH_CPRPT_ARC"
    PIXMAP = "Sketcher_CreateArc"
    KIND = "Centerpoint Arc"

    def build(self):
        self._own_tool()
        self.message("Set the properties of the arc, or sketch it in the graphics area.")
        g = self.group("Arc Type")
        try:
            from . import icons
            family = icons.family
        except Exception:
            family = lambda name: QtGui.QIcon()

        def icon(name):
            entry = next(t for t in FW_ARCS if t[0] == name)
            i = family(entry[2])
            return i if not i.isNull() else Gui.getIcon(entry[3])
        self.type_buttons = self.toggles(g, [t[0] for t in FW_ARCS], icon, lambda k: k == self.KIND)
        for name, b in self.type_buttons.items():
            b.clicked.connect(lambda checked=False, n=name: self._switch(n))
        g = self.group("Options")
        options = g
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWArcForConstruction")
        tool = _fw_tool()
        self.construction.setChecked(bool(getattr(tool, "construction", False)))
        self.construction.toggled.connect(self._to_tool)
        g.content.addWidget(self.construction)
        g = self.group("Parameters")
        self.fields = {}

        for key, label in (("cx", "Center X"), ("cy", "Center Y"), ("sx", "Start X"), ("sy", "Start Y"),
                           ("ex", "End X"), ("ey", "End Y"), ("radius", "Radius"), ("angle", "Angle")):
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(label, g.body))
            f = QtWidgets.QLineEdit(g.body)
            f.setObjectName("SWArc" + key)
            f.setReadOnly(True)      # shows the arc being placed; typed values come with the dimension
            row.addWidget(f, 1)
            g.content.addLayout(row)
            self.fields[key] = f
        from . import paramedit      # fix57: typed values change the last arc placed
        paramedit.wire(self, self.fields, "arc")

        from . import currententity
        self.current = currententity.CurrentEntity(self, options, parameters=False)
        self.tick()

    def _switch(self, name):
        for n, b in self.type_buttons.items():
            b.setChecked(n == name)
        if name == self.KIND:
            return
        command = next(t[1] for t in FW_ARCS if t[0] == name)
        construction = self.construction.isChecked()
        try:
            Gui.runCommand(command, 0)
        except Exception:
            return
        tool = _fw_tool()
        if tool is not None and construction:
            tool.construction = True

    def _to_tool(self, *args):
        tool = _fw_tool()
        if tool is not None:
            tool.construction = self.construction.isChecked()

    def tick(self):
        tool = _fw_tool()
        if tool is None or not alive(self.construction):
            return
        centre = getattr(tool, "center", None)
        radius = getattr(tool, "radius", 0.0) or 0.0
        angle = abs(getattr(tool, "arc_angle", 0.0) or 0.0)
        values = {"cx": centre[0] if centre else None, "cy": centre[1] if centre else None,
                  "radius": radius if centre and radius else None,
                  "angle": angle if centre and angle else None}
        start = getattr(tool, "start_angle", None)
        arc = getattr(tool, "arc", None)
        from . import paramedit
        if paramedit.editing(self.fields):
            return
        cur = getattr(self, "current", None)
        if cur is not None:
            from . import currententity
            cur.follow(currententity.last_placed(self, ("ArcOfCircle",)))
        if not centre:

            values = paramedit.placed_values(self, "arc") or values
        if centre and radius and (start is not None or arc):
            a0 = start if start is not None else arc[0]
            a1 = a0 + (getattr(tool, "arc_angle", 0.0) or 0.0) if start is not None else arc[1]
            values.update(sx=centre[0] + radius * math.cos(a0), sy=centre[1] + radius * math.sin(a0))
            if angle:
                values.update(ex=centre[0] + radius * math.cos(a1), ey=centre[1] + radius * math.sin(a1))
        for key in self.fields:
            v = values.get(key)

            text = ("%.2f°" % math.degrees(v or 0.0)) if key == "angle" else "%.2f" % (v or 0.0)
            if self.fields[key].text() != text:
                self.fields[key].setText(text)


class FwTangentArcPage(FwArcPage):
    KIND = "Tangent Arc"
    ICON = "SKETCH_TANGET_ARC"


class FwThreePointArcPage(FwArcPage):
    KIND = "3 Point Arc"
    ICON = "SKETCH_3PT_ARC"
    PIXMAP = "Sketcher_Create3PointArc"


FW_RECTANGLES = (("Corner Rectangle", "FreeWorks_CornerRectangle"),
                 ("Center Rectangle", "FreeWorks_CenterRectangle"),
                 ("3 Point Corner Rectangle", "FreeWorks_3PointCornerRectangle"),
                 ("3 Point Center Rectangle", "FreeWorks_3PointCenterRectangle"),
                 ("Parallelogram", "FreeWorks_Parallelogram"))
_CENTERED = ("Center Rectangle", "3 Point Center Rectangle")


class FwRectanglePage(_FwToolPage, _ToolOptionsPage):
    ""



    OK_ONLY = True

    TITLE = "Rectangle"
    ICON = "SKETCH_CORNER_RECT"
    PIXMAP = "Sketcher_CreateRectangle"

    def _kind(self):
        tool = self._own_tool()
        try:
            title = tool.title() if tool is not None else None
        except Exception:
            title = None
        if title in [k for k, _c in FW_RECTANGLES]:
            return title
        name = getattr(self, "native", None) or ""
        return next((k for k, c in FW_RECTANGLES if c == name), "Corner Rectangle")

    def build(self):
        self._own_tool()
        self.kind = self._kind()
        p = _params()
        self.message("Set the properties of the rectangle, or sketch it in the graphics area.")
        g = self.group("Rectangle Type")
        try:
            from . import icons
            family = icons.family
        except Exception:
            family = lambda name: QtGui.QIcon()
        shapes = {t[0]: t for t in SHAPES["Rectangle"]}

        def icon(name):
            entry = shapes.get(name)
            if entry is None:
                return QtGui.QIcon()
            i = family(entry[3])
            return i if not i.isNull() else Gui.getIcon(entry[4])
        self.type_buttons = self.toggles(g, [k for k, _c in FW_RECTANGLES], icon, lambda k: k == self.kind,
                                         rows=(2, 3), big=True)
        for name, b in self.type_buttons.items():
            b.clicked.connect(lambda checked=False, n=name: self._switch(n))
            command = next(c for k, c in FW_RECTANGLES if k == name)
            if Gui.Command.get(command) is None:
                b.setEnabled(False)
                b.setToolTip("%s: %s" % (name, NOT_YET))
        tg = g
        g = self.group("Options")
        tool = _fw_tool()
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWShapeForConstruction")
        self.construction.setChecked(bool(getattr(tool, "construction", p.GetBool("RectangleForConstruction", False))))
        g.content.addWidget(self.construction)
        g = tg
        self.lines = QtWidgets.QCheckBox("Add construction lines", g.body)
        self.lines.setObjectName("SWRectangleConstructionLines")
        center = self.kind in _CENTERED
        self.lines.setChecked(p.GetBool("RectangleConstructionLines" + ("Center" if center else ""), center))
        g.content.addWidget(self.lines)
        self.line_kind = QtWidgets.QButtonGroup(g.body)
        chosen = p.GetString("RectangleConstructionLinesFrom", "From Corners")
        for i, name in enumerate(CONSTRUCTION_LINES):
            b = QtWidgets.QRadioButton(name, g.body)
            b.setObjectName("SWRectangle" + name.replace(" ", ""))
            b.setChecked(name == chosen)
            self.line_kind.addButton(b, i)
            g.content.addWidget(b)
        if self.line_kind.checkedButton() is None:
            self.line_kind.button(0).setChecked(True)
        g = self.group("Parameters")
        self.fields = {}
        rows = []
        for i in range(1, 5):
            rows += [("x%d" % i, "Point %d X" % i), ("y%d" % i, "Point %d Y" % i)]
        rows += [("cx", "Center X"), ("cy", "Center Y")]
        for key, label in rows:
            row = QtWidgets.QHBoxLayout()
            text = QtWidgets.QLabel(label, g.body)
            row.addWidget(text)
            f = QtWidgets.QLineEdit(g.body)
            f.setObjectName("SWRect" + key)
            f.setReadOnly(True)      # the rectangle being placed; typed sizes come with the dimensions
            row.addWidget(f, 1)
            g.content.addLayout(row)
            self.fields[key] = (f, text)
        from . import paramedit      # fix57: typed values change the last rectangle placed
        paramedit.wire(self, {k: v[0] for k, v in self.fields.items()}, "rect")
        for key in ("cx", "cy"):
            for w in self.fields[key]:
                w.setVisible(center)
        self.construction.toggled.connect(self._to_tool)
        self.lines.toggled.connect(self._to_tool)
        self.line_kind.buttonClicked.connect(self._lines_picked)
        self.lines.toggled.connect(self._show_line_kinds)
        self._show_line_kinds()
        self._to_tool()
        self.tick()

    def _show_line_kinds(self, *args):
        ""
        for b in self.line_kind.buttons():
            b.setVisible(self.lines.isChecked())

    def _lines_picked(self, *args):
        # no dead (greyed) choice: picking From Corners / From Midpoints turns the lines on
        if not self.lines.isChecked():
            self.lines.setChecked(True)     # _to_tool runs from its toggled signal
        else:
            self._to_tool()

    def _switch(self, name):
        for n, b in self.type_buttons.items():
            b.setChecked(n == name)
        if name == self.kind:
            return
        command = next(c for k, c in FW_RECTANGLES if k == name)
        construction = self.construction.isChecked()
        try:
            Gui.runCommand(command, 0)
        except Exception:
            return
        tool = _fw_tool()
        if tool is not None and construction:
            tool.construction = True

    def _to_tool(self, *args):
        p = _params()
        center = self.kind in _CENTERED
        b = self.line_kind.checkedButton()
        lines_from = b.text() if b is not None else "From Corners"
        p.SetBool("RectangleForConstruction", self.construction.isChecked())
        p.SetBool("RectangleConstructionLines" + ("Center" if center else ""), self.lines.isChecked())
        p.SetString("RectangleConstructionLinesFrom", lines_from)
        tool = _fw_tool()
        if tool is None or tool is not self._own_tool():
            return
        tool.construction = self.construction.isChecked()
        tool.add_lines = self.lines.isChecked()
        tool.lines_from = lines_from
        try:
            tool._move()
        except Exception as _fw_err:
            _fw_log("nativepms.py:1785", _fw_err)

    def tick(self):
        tool = _fw_tool()
        if tool is None or not alive(self.construction):
            return
        corners = getattr(tool, "corners", None) or []
        centre = getattr(tool, "center", None)
        values = {}
        for i in range(4):
            c = corners[i] if i < len(corners) else None
            values["x%d" % (i + 1)] = c[0] if c else None
            values["y%d" % (i + 1)] = c[1] if c else None
        values["cx"] = centre[0] if centre else None
        values["cy"] = centre[1] if centre else None
        from . import paramedit
        if paramedit.editing(self.fields):
            return
        if not corners:

            values.update(paramedit.placed_values(self, "rect"))
        for key, v in values.items():
            f = self.fields[key][0]

            text = "%.2f" % (0.0 if v is None else v)
            if f.text() != text:
                f.setText(text)


class FwCenterRectanglePage(FwRectanglePage):
    ICON = "SKETCH_CTR_RECT"
    PIXMAP = "Sketcher_CreateRectangle_Center"


class FwSplinePage(_FwToolPage, _ToolOptionsPage):
    ""


    OK_ONLY = True

    TITLE = "Spline"
    ICON = "SKETCH_SPLINE"
    PIXMAP = "Sketcher_CreateBSpline"
    MESSAGE = "Click to place the spline's points; double-click or Esc ends the spline."
    STYLE = False

    def build(self):
        from . import splinepm
        tool = self._own_tool()
        self.message(self.MESSAGE)
        options = self.group("Options")
        self.construction = QtWidgets.QCheckBox("For construction", options.body)
        self.construction.setObjectName("SWSplineForConstruction")
        self.construction.setChecked(bool(getattr(tool, "construction", False)))
        self.construction.toggled.connect(self._to_tool)
        options.content.addWidget(self.construction)
        parameters = self.group("Parameters")
        self.fields = f = splinepm.SplineFields(self, options, parameters, style=self.STYLE, placing=self._placing)
        # the fields' widgets, as the page's own (x and y hide QWidget's methods, as before)
        for name in ("index", "x", "y", "weight1", "weight2", "angle", "driving", "reset_one", "reset_all",
                     "relax_button", "curvature", "continuity", "proportional", "labels"):
            setattr(self, name, getattr(f, name))
        if tool is not None and hasattr(tool, "listeners"):
            tool.listeners.append(self._made)
        self.fields.fill()

    @property
    def geo(self):
        fields = self.__dict__.get("fields")
        return fields.geo if fields is not None else None

    def closing(self):
        tool = getattr(self, "_tool", None)
        try:
            tool.listeners.remove(self._made)
        except Exception as _fw_err:
            _fw_log("nativepms.py:1860", _fw_err)
        try:
            super().closing()
        except AttributeError as _fw_err:
            _fw_log("nativepms.py:1864", _fw_err)

    def _to_tool(self, *args):
        tool = _fw_tool()
        if tool is not None:
            tool.construction = self.construction.isChecked()

    def _made(self, sketch, geo):
        QtCore.QTimer.singleShot(0, lambda: alive(self.construction) and self.fields.set_spline(geo, new=True))

    def _placing(self):
        tool = _fw_tool()
        return list(getattr(tool, "points", []) or []) if tool is getattr(self, "_tool", None) else []

    def _fill(self, last=False):
        self.fields.fill(last)

    def tick(self):
        fields = self.__dict__.get("fields")
        if fields is not None and alive(fields.index) and self._placing():
            n = len(self._placing())
            if fields.index.maximum() != n or fields.index.value() != n:
                fields.fill()


class FwStyleSplinePage(FwSplinePage):
    ""



    TITLE = "Style Spline"
    STYLE = True
    MESSAGE = "Click to place the control vertices; double-click or Esc ends the spline."

    def build(self):
        super().build()

        # degree 3, 5 or 7 (any number of vertices); the next style spline is made so
        from .fwsketch import stylespline as SS
        g = self.group("Spline Type")
        self.column.removeWidget(g)
        self.column.insertWidget(max(0, self.column.indexOf(self.construction.parentWidget().parentWidget())), g)
        self.spline_types = QtWidgets.QButtonGroup(g.body)
        chosen = SS.spline_type()
        for i, name in enumerate(SS.SPLINE_TYPES):
            b = QtWidgets.QRadioButton(name, g.body)
            b.setObjectName("SWStyleSpline" + name.replace(" ", "").replace(":", ""))
            b.setChecked(name == chosen)
            self.spline_types.addButton(b, i)
            g.content.addWidget(b)
        self.spline_types.buttonClicked.connect(
            lambda b: App.ParamGet(SS.TOOL_PARAMS).SetString("StyleSplineType", b.text()))


# --------------------------------------------------------------------------- Parabola
class ParabolaPage(_ToolOptionsPage):
    ""


    OK_ONLY = True

    TITLE = "Parabola"
    ICON = "SKETCH_PARABOLA"
    PIXMAP = "Sketcher_CreateParabolic_Arc"
    ROWS = (("Start", "start"), ("End", "end"), ("Focus", "focus"), ("Vertex", "vertex"))

    def build(self):
        self.count = len(self.sketch.Geometry)
        self.message("Click the focus, then the vertex, then the two ends of the parabola.")
        g = self.group("Options")
        self.construction = QtWidgets.QCheckBox("For construction", g.body)
        self.construction.setObjectName("SWParabolaForConstruction")
        self.construction.setChecked(_params().GetBool("ParabolaForConstruction", False))
        self.construction.toggled.connect(lambda on: _params().SetBool("ParabolaForConstruction", bool(on)))
        g.content.addWidget(self.construction)
        g = self.group("Parameters")
        form = QtWidgets.QFormLayout()
        self.values = {}
        for label, key in self.ROWS:
            for axis in ("X", "Y"):
                v = QtWidgets.QLineEdit("", g.body)
                v.setReadOnly(True)
                v.setObjectName("SWParabola%s%s" % (label, axis))
                self.values[key + axis] = v
                form.addRow("%s %s:" % (label, axis), v)
        g.content.addLayout(form)
        self.params_group = g
        g.setVisible(False)
        self.last = None

    def tick(self):
        try:
            geos = self.sketch.Geometry
        except Exception:
            return
        n = len(geos)
        if n < self.count:
            self.count = n
        new = [i for i in range(self.count, n) if type(geos[i]).__name__ == "ArcOfParabola"]
        self.count = n
        for g in new:
            if self.construction.isChecked() and not self.sketch.getConstruction(g):
                self.sketch.setConstruction(g, True)
            self.last = g
        if new:
            sketchtoolpm._refresh(self.sketch)
            self.show_values()

    def show_values(self):
        try:
            arc = self.sketch.Geometry[self.last]
            pts = {"start": arc.StartPoint, "end": arc.EndPoint, "focus": arc.Parabola.Focus, "vertex": arc.Center}
        except Exception:
            return
        for key, p in pts.items():
            self.values[key + "X"].setText("%.2f" % p.x)
            self.values[key + "Y"].setText("%.2f" % p.y)
        self.params_group.setVisible(True)


# --------------------------------------------------------------------------- watching FreeCAD's tools
PAGES = {name: LinePage for name in LINE_TOOLS + (MIDPOINT_LINE,)}
PAGES["Sketcher_CreateArcOfParabola"] = ParabolaPage
PAGES["FreeWorks_Polygon"] = FwPolygonPage
PAGES["FreeWorks_Spline"] = FwSplinePage
PAGES["FreeWorks_StyleSpline"] = FwStyleSplinePage
PAGES.update({"FreeWorks_CenterArc": FwArcPage, "FreeWorks_TangentArc": FwTangentArcPage,
              "FreeWorks_ThreePointArc": FwThreePointArcPage})
PAGES.update({"FreeWorks_CornerRectangle": FwRectanglePage, "FreeWorks_CenterRectangle": FwCenterRectanglePage,
              "FreeWorks_3PointCornerRectangle": FwRectanglePage,
              "FreeWorks_3PointCenterRectangle": FwCenterRectanglePage,
              "FreeWorks_Parallelogram": FwRectanglePage})
PAGES.update({name: TrimPage for name in TRIM_TOOLS})
PAGES.update({name: PolygonPage for name in POLYGON_TOOLS})
for _kind, _page in (("Circle", CirclePage), ("Arc", ArcPage), ("Rectangle", RectanglePage), ("Slot", SlotPage)):
    for _t in SHAPES[_kind]:
        if _t[1] and _t[1] not in PAGES:
            PAGES[_t[1]] = _page


# the rest of the fwsketch tools: Line, Circle, Slot, Point, Ellipse, Trim, Extend (land196)
try:
    from . import fwtoolpms
    PAGES.update(fwtoolpms.PAGES)
except Exception as _error:
    App.Console.PrintWarning("FreeCAD: sketch tool pages not loaded: %s\n" % _error)


def _page_for(name):
    """The page a starting tool gets: the Arc page when its Tangent Arc button started Polyline."""
    if name == "Sketcher_CreatePolyline" and _shape_next == "Tangent Arc":
        return ArcPage
    return PAGES[name]


# FreeCAD commands that start a sketch tool of their own: started while another tool's page is
# open, they end that tool, so its page goes too (Extend Entities picked during Trim Entities)
TAKEOVER = ("Sketcher_Create", "Sketcher_Extend", "Sketcher_Split", "Sketcher_Trimming", "Sketcher_Join",
            "Sketcher_Dimension", "Sketcher_CompDimension", "Sketcher_External", "Sketcher_CarbonCopy",
            "Sketcher_Offset", "Sketcher_Translate", "Sketcher_Rotate", "Sketcher_Scale")


class _Watcher(QtCore.QObject):
    """Opens the page of a FreeCAD sketch tool shortly after the tool starts."""

    def __init__(self):
        super().__init__()
        self.actions = []
        self.original = None
        # FreeCAD makes a command's actions when its workbench first loads: look again now and then
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(2000)
        self.timer.timeout.connect(self.hook_actions)

    def install(self):
        self.original = Gui.runCommand
        original = self.original

        def run_command(name, *args, **kw):
            if name.startswith(FEATURE_COMMANDS):
                return _run_feature_command(original, name, args, kw)
            self.other_tool(name)
            result = original(name, *args, **kw)
            if name in PAGES:
                self.started(name)
            return result
        run_command.swstyle_original = original
        Gui.runCommand = run_command
        self.hook_actions()
        self.timer.start()

    def hook_actions(self):
        for name in PAGES:
            try:
                actions = Gui.Command.get(name).getAction()
            except Exception:
                actions = []
            for action in actions:
                if action is None or action in self.actions:
                    continue
                action.triggered.connect(lambda *a, n=name: self.started(n))
                self.actions.append(action)
        try:
            names = [n for n in Gui.listCommands() if n.startswith(TAKEOVER) and n not in PAGES]
        except Exception:
            names = []
        for name in names:
            try:
                actions = Gui.Command.get(name).getAction()
            except Exception:
                actions = []
            for action in actions:
                if action is None or action in self.actions:
                    continue
                # FreeCAD's own slot has run by now: compare with the cursor the page last saw
                action.triggered.connect(lambda *a, n=name: self.other_tool(n, polled=True))
                self.actions.append(action)

    def other_tool(self, name, polled=False):
        """A tool without a page of its own may be taking over: once it runs, the open page goes."""
        page = sketchtoolpm.current()
        if not (isinstance(page, _ToolOptionsPage) and alive(page)) or name == page.native:
            return
        if name in PAGES or not name.startswith(TAKEOVER):
            return
        before = page.cursor if polled else _cursor_key()

        def look(left=6):
            if not alive(page) or sketchtoolpm.current() is not page:
                return
            if _tool_running() and _cursor_key() != before:
                page.taken_over()
            elif left > 0:
                QtCore.QTimer.singleShot(50, lambda: look(left - 1))
        QtCore.QTimer.singleShot(0, look)

    def remove(self):
        self.timer.stop()
        if self.original is not None and getattr(Gui.runCommand, "swstyle_original", None) is self.original:
            Gui.runCommand = self.original
        self.original = None

    def started(self, name):
        def look(left=12):
            sketch = contextbar.sketch_in_edit()
            if sketch is None or not _tool_running():
                if left > 0:
                    QtCore.QTimer.singleShot(100, lambda: look(left - 1))
                return
            page = sketchtoolpm.current()
            if isinstance(page, _ToolOptionsPage) and page.native == name and alive(page):
                return
            shell = _shell()
            if shell is None or not shell.enabled or not _params().GetBool("ToolPropertyManagers", True):
                return
            running = _fw_tool()
            if isinstance(page, _FwToolPage) and running is not None and getattr(page, "_tool", running) is running:

                # swapping its PM must not end it
                page._tool = None
            sketchtoolpm.open_page(_page_for(name)(sketch, name))
        QtCore.QTimer.singleShot(60, look)


# --------------------------------------------------------------------------- feature commands
# A part feature (Loft, Sweep, Pad...) started through Gui.runCommand passes here too. None of the
# sketch-tool logic above applies to it, so it goes straight to FreeCAD's command, with the active
# body set from the picks when there is none (FreeCAD asks or fails otherwise), and a line in

# crash inside FreeCAD's command.
FEATURE_COMMANDS = ("PartDesign_",)
_LOG = [None]


def _breadcrumb(text):
    try:
        if _LOG[0] is None:
            import os
            _LOG[0] = os.path.join(App.getUserAppDataDir(), "FreeWorks-commands.log")
            if os.path.exists(_LOG[0]) and os.path.getsize(_LOG[0]) > 200000:
                os.replace(_LOG[0], _LOG[0] + ".old")
        import time
        with open(_LOG[0], "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
            f.flush()
    except Exception as _fw_err:
        _fw_log("nativepms.py:2146", _fw_err)
    try:
        App.Console.PrintLog("FreeCAD: %s\n" % text)
    except Exception as _fw_err:
        _fw_log("nativepms.py:2150", _fw_err)


def _state():
    try:
        doc, gdoc = App.ActiveDocument, Gui.ActiveDocument
        view = gdoc.ActiveView if gdoc is not None else None
        body = view.getActiveObject("pdbody") if view is not None and hasattr(view, "getActiveObject") else None
        sel = ["%s.%s" % (o.Object.Name, ",".join(o.SubElementNames)) for o in Gui.Selection.getSelectionEx()]
        return "doc=%s gui=%s edit=%s dialog=%s body=%s sel=%s" % (
            doc.Name if doc else None, gdoc.Document.Name if gdoc else None,
            bool(gdoc.getInEdit()) if gdoc else None, type(Gui.Control.activeDialog()).__name__ if
            Gui.Control.activeDialog() else None, body.Name if body is not None else None, sel)
    except Exception as e:
        return "state? %s" % e


def _active_body_from_picks():
    ""

    try:
        gdoc = Gui.ActiveDocument
        if gdoc is None or App.ActiveDocument is None or gdoc.Document is not App.ActiveDocument:
            return
        view = gdoc.ActiveView
        if not hasattr(view, "getActiveObject") or view.getActiveObject("pdbody") is not None:
            return
        for pick in Gui.Selection.getSelectionEx(App.ActiveDocument.Name):
            obj = pick.Object
            body = obj if obj.TypeId == "PartDesign::Body" else None
            if body is None:
                for parent in obj.InList:
                    if parent.TypeId == "PartDesign::Body":
                        body = parent
                        break
            if body is not None:
                view.setActiveObject("pdbody", body)
                return
    except Exception as e:
        _breadcrumb("active body: %s" % e)


def _run_feature_command(original, name, args, kw):
    if _page_open_elsewhere():

        # tried to open the second page over the first and hung on the PC (pmhd2: Loft over
        # the Hole page). The open page keeps the keyboard; the status bar says why.
        _breadcrumb("refused %s: a page is open %s" % (name, _state()))
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "Finish or cancel the open PropertyManager first (OK, Cancel or Esc).", 4000)
        except Exception as _fw_err:
            _fw_log("nativepms.py:2202", _fw_err)
        return None
    _active_body_from_picks()
    _breadcrumb("start %s %s" % (name, _state()))
    try:
        result = original(name, *args, **kw)
    except Exception as e:
        _breadcrumb("failed %s: %s" % (name, e))
        raise
    _breadcrumb("started %s %s" % (name, _state()))
    return result


def _page_open_elsewhere():
    """A task dialog is open and it is not a sketch's (a feature started from a sketch closes
    the sketch first, featureflow)."""
    try:
        if not Gui.Control.activeDialog():
            return False
        from . import featureflow
        return featureflow.editing_sketch() is None
    except Exception:
        return False


_watcher = None


def install():
    global _watcher
    try:
        for name, command in ((MIRROR, MirrorCommand), (CENTERLINE, CenterlineCommand)):
            if name not in Gui.listCommands():
                Gui.addCommand(name, command())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Mirror Entities, Centerline not added: %s\n" % error)
    if _watcher is None:
        _watcher = _Watcher()
        _watcher.install()
    else:
        _watcher.hook_actions()


def remove():
    global _watcher
    if _watcher is not None:
        _watcher.remove()
        _watcher = None
