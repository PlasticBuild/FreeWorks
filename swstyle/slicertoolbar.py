"""The slicers' toolbar above the build plate, floating over FreeCAD's 3D view while the plate shows:
Add, Auto Orient, Arrange | Add/Remove Instance, Split to Objects | Move, Rotate, Scale, Lay on Face,
Cut. Move, Rotate, Scale and Cut open a small panel under the toolbar, as the slicers' gizmos do.
Keys as in the slicers: Ctrl+I add, Q orient, A arrange, + / - instances, M R S F C tools, Delete.
Objects on the plate: click to select (Ctrl adds), drag to move."""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import style
from . import slicersettings

Qt = QtCore.Qt
HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "slicer", "toolbar")

# key, icon, tooltip (the slicers' words), shortcut
BUTTONS = (
    ("add", "add", "Add", "Ctrl+I"),
    ("plate", "add_plate", "Add plate", None),
    ("orient", "toolbar_orient", "Auto orient", "Q"),
    ("arrange", "toolbar_arrange", "Arrange all objects", "A"),
    None,
    ("more", "instance_add", "Add instance", "+"),
    ("fewer", "instance_remove", "Remove instance", "-"),
    ("split", "split_objects", "Split to objects", None),
    ("parts", "split_parts", "Split to parts", None),
    None,
    ("move", "toolbar_move", "Move", "M"),
    ("rotate", "toolbar_rotate", "Rotate", "R"),
    ("scale", "toolbar_scale", "Scale", "S"),
    ("flatten", "toolbar_flatten", "Lay on face", "F"),
    ("cut", "toolbar_cut", "Cut", "C"),
    ("boolean", "mesh_boolean", "Mesh boolean", "B"),
    ("text", "text_emboss", "Text", "T"),
    ("measure", "measure", "Measure", "U"),
    None,
    ("support", "paint_support", "Support painting", "L"),
    ("seam", "paint_seam", "Seam painting", "P"),
    ("color", "paint_color", "Color painting", "N"),
    ("fuzzy", "paint_fuzzy", "Fuzzy skin painting", None),
    ("ears", "brim_ears", "Brim ears", "Ctrl+E"),
    None,
    ("layers", "layer_height", "Variable layer height", None),
    ("assembly", "assembly_view", "Assembly view", None),
)
# what works only through Orca Slicer's and Bambu Studio's project files (paint, brim ears, a layer height profile,
# modifier parts): not shown while PrusaSlicer is the slicer (PrusaSlicer gets plain meshes)
NOT_FOR = {"prusa": ("parts", "support", "seam", "color", "fuzzy", "ears", "layers")}
TOOLS = ("move", "rotate", "scale", "cut", "boolean", "text", "measure", "support", "seam", "color", "fuzzy", "ears", "layers", "assembly")      # buttons that open a panel
PAINT_TOOLS = ("support", "seam", "color", "fuzzy")



# view toolbar uses); the slicers' own icon otherwise
SW_ICONS = {
    "add": "STANDARD_OPEN",
    "more": "STANDARD_COPY",
    "split": "SKETCH_SPLIT_ENTITIES",
    "move": "SKETCH_MOVE_ENTITIES",
    "rotate": "SKETCH_ROTATE_ENTITIES",
    "scale": "FEATURES_SCALE",
    "cut": "DRAWINGS_SECTION_VIEW",
}


def button_icon(key, picture):
    from . import icons
    name = SW_ICONS.get(key)
    if name and icons.available():
        ic = icons.family(name)
        if not ic.isNull() and ic.availableSizes():
            return ic
    return icon(picture)


def icon(name):
    dark = os.path.join(HERE, name + "_dark.svg")
    if style.viewport_dark() and os.path.isfile(dark):
        return QtGui.QIcon(dark)
    return QtGui.QIcon(os.path.join(HERE, name + ".svg"))


def _spin(lo, hi, suffix, decimals=2, step=1.0):
    b = QtWidgets.QDoubleSpinBox()
    b.setRange(lo, hi)
    b.setDecimals(decimals)
    b.setSingleStep(step)
    b.setSuffix(suffix)
    b.setKeyboardTracking(False)
    b.setMinimumWidth(92)
    return b


class ToolPanel(QtWidgets.QFrame):
    """The panel a tool opens (the slicers' gizmo panel)."""

    def __init__(self, title, parent):
        super().__init__(parent)
        self.setObjectName("SWSlicerToolPanel")
        self.lay = QtWidgets.QGridLayout(self)
        self.lay.setContentsMargins(10, 8, 10, 8)
        self.lay.setHorizontalSpacing(8)
        self.lay.setVerticalSpacing(4)
        t = QtWidgets.QLabel("<b>%s</b>" % title)
        self.lay.addWidget(t, 0, 0, 1, 4)

    def row(self, label, *widgets):
        r = self.lay.rowCount()
        if label is not None:
            self.lay.addWidget(QtWidgets.QLabel(label), r, 0)
        for i, w in enumerate(widgets):
            self.lay.addWidget(w, r, 1 + i)
        return r


class PlateToolbar(QtWidgets.QFrame):
    def __init__(self, panel, host):
        super().__init__(host)
        self.panel = panel              # the SlicerPanel
        self.bed = panel.bed
        self.setObjectName("SWSlicerPlateBar")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(2)
        self.buttons = {}
        self.shortcuts = []
        for spec in BUTTONS:
            if spec is None:
                line = QtWidgets.QFrame()
                line.setFrameShape(QtWidgets.QFrame.VLine)
                line.setObjectName("SWSlicerBarLine")
                lay.addWidget(line)
                continue
            key, picture, tip, keys = spec
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSlicerBarButton")
            b.setIcon(button_icon(key, picture))
            b.setIconSize(QtCore.QSize(20, 20))
            b.setFixedSize(26, 26)
            b.setAutoRaise(True)
            b.setToolTip("%s [%s]" % (tip, keys) if keys else tip)
            b.setCheckable(key in TOOLS or key == "flatten")
            b.clicked.connect(lambda on=False, k=key: self.press(k))
            lay.addWidget(b)
            self.buttons[key] = b
            if keys:
                sc = QtGui.QShortcut(QtGui.QKeySequence(keys), host)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(lambda k=key: self.press(k, from_key=True))
                self.shortcuts.append(sc)
        for key in NOT_FOR.get(panel.key, ()):
            if key in self.buttons:
                self.buttons[key].hide()
        self.delete_key = QtGui.QShortcut(QtGui.QKeySequence(Qt.Key_Delete), host)
        self.delete_key.setContext(Qt.WidgetWithChildrenShortcut)
        self.delete_key.activated.connect(lambda: self.bed.delete())
        self.shortcuts.append(self.delete_key)
        self.tool = None
        self.tool_panel = None
        self.painter = None
        self.measurer = None            # the Measure tool's clicks (slicermeasure)
        self.ears = None                # the Brim Ears tool's clicks (slicerears)
        self.texter = None              # the Text tool's clicks (slicertext)
        self.assembly = None            # the Assembly view's pieces (slicerassembly)
        self.cut_plane = None
        from . import slicerinfo
        self.info = slicerinfo.ObjectInfo(self.bed, host)
        from . import slicercube
        self.cube = slicercube.ViewCube(self.bed, host)
        self._restyle()
        style.signals.theme_changed.connect(self._restyle)
        host.installEventFilter(self)
        self.adjustSize()
        self.place()
        self.show()

    def _restyle(self, *_):
        ""

        T = style.T
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(
            "#SWSlicerPlateBar { background:transparent; border:none; }"
            "#SWSlicerBarLine { color:%(line)s; max-width:1px; margin:4px 2px; }"
            "#SWSlicerBarButton { border:1px solid transparent; border-radius:0; padding:0; background:transparent; }"
            "#SWSlicerBarButton:hover { background:%(hover)s; border-color:%(hover_line)s; }"
            "#SWSlicerBarButton:checked, #SWSlicerBarButton:pressed { background:%(down)s; border-color:%(down_line)s; }"
            % {"line": T.hex("line_mid"), "hover": T.hex("hover"), "hover_line": T.hex("hover_line"),
               "down": T.hex("down"), "down_line": T.hex("down_line")})
        for spec in BUTTONS:
            if spec is not None:
                self.buttons[spec[0]].setIcon(button_icon(spec[0], spec[1]))
        if self.tool_panel is not None:
            self.tool_panel.setStyleSheet(self.panel_style())

    @staticmethod
    def panel_style():
        T = style.T
        return ("#SWSlicerToolPanel { background:%(pane)s; border:1px solid %(line)s; border-radius:0; }"
                "#SWSlicerToolPanel QLabel, #SWSlicerToolPanel QCheckBox { color:%(text)s; background:transparent; }"
                "#SWSlicerToolPanel QPushButton { color:%(text)s; background:%(base)s; border:1px solid %(line)s; "
                "padding:2px 8px; }"
                "#SWSlicerToolPanel QPushButton:hover { background:%(hover)s; }"
                % dict({k: T.hex(k) for k in ("pane", "text", "field", "field_text", "field_line", "base", "hover")},
                       line=T.hex("line_mid")))

    def place(self):
        host = self.parentWidget()
        if host is None:
            return
        # under the heads-up view toolbar, centred like the slicers', clear of the Prepare / Preview / Device /
        # Calibration tabs (right of them, or under them when the view is too narrow)
        x, y = max(0, (host.width() - self.width()) // 2), 36
        tabs = getattr(getattr(self, "panel", None), "modebar", None)
        if tabs is not None and tabs.isVisible():
            right = tabs.x() + tabs.width() + 8
            if x < right:
                if right + self.width() <= host.width():
                    x = right
                else:
                    y = tabs.y() + tabs.height() + 4
        self.move(x, y)
        self.raise_()
        if self.tool_panel is not None:
            self.tool_panel.adjustSize()
            b = self.buttons[self.tool]
            x = self.x() + b.x() + b.width() // 2 - self.tool_panel.width() // 2
            x = max(4, min(x, host.width() - self.tool_panel.width() - 4))
            self.tool_panel.move(x, self.y() + self.height() + 6)
            self.tool_panel.raise_()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if obj is self.parentWidget() and event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self.place()
        return False

    def remove(self):
        try:
            style.signals.theme_changed.disconnect(self._restyle)
        except Exception as _fw_err:
            _fw_log("slicertoolbar.py:221", _fw_err)
        self.close_tool()
        self.info.remove()
        self.cube.remove()
        host = self.parentWidget()
        if host is not None:
            host.removeEventFilter(self)
        for sc in self.shortcuts:
            sc.setEnabled(False)
            sc.setParent(None)
            sc.deleteLater()
        self.shortcuts = []
        self.hide()
        self.setParent(None)
        self.deleteLater()

    # ------------------------------------------------------------------ buttons
    def press(self, key, from_key=False):
        if key in NOT_FOR.get(self.panel.key, ()):
            return                      # (its shortcut too)
        bed = self.bed
        if key == "add":
            self.add_files()
        elif key == "plate":
            bed.add_plate()
        elif key == "orient":
            bed.auto_orient()
        elif key == "arrange":
            bed.arrange()
        elif key == "more":
            bed.add_instance()
        elif key == "fewer":
            bed.remove_instance()
        elif key == "split":
            if not bed.split():
                self.panel._say("Nothing to split: the object is one solid.")
        elif key == "parts":
            if bed.split_parts():
                self.panel._object_changed(True)
                self.panel._say("Split to parts: right-click the object in the list (Parts) to give a part a filament "
                                "of its own.")
            else:
                self.panel._say("Nothing to split: the object is one solid, or already in parts.")
        elif key == "flatten":
            b = self.buttons["flatten"]
            on = b.isChecked() if not from_key else not b.isChecked()
            b.setChecked(on)
            self.close_tool()
            if on:
                bed.start_pick(lambda ok: b.setChecked(False))
                self.panel._say("Click a face of an object: it goes down onto the plate.")
            else:
                bed.stop_pick()
        elif key in TOOLS:
            if self.tool == key:
                self.close_tool()
            else:
                self.open_tool(key)

    def add_files(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            Gui.getMainWindow(), "Add to the plate", App.ConfigGet("UserHomePath"),
            "Models (*.stl *.STL *.obj *.3mf *.step *.stp *.STEP *.STP *.iges *.igs *.ply);;All files (*)")
        for f in files:
            try:
                self.bed.add_file(f)
            except Exception as error:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Add", "Could not read %s:\n%s" % (f, error))

    # ------------------------------------------------------------------ tool panels
    def close_tool(self):
        if self.tool is not None and self.tool in self.buttons:
            self.buttons[self.tool].setChecked(False)
        if self.painter is not None:
            self.painter.stop()
            self.painter = None
        if self.measurer is not None:
            self.measurer.stop()
            self.measurer = None
        if self.ears is not None:
            self.ears.stop()
            self.ears = None
        if self.texter is not None:
            self.texter.stop()
            self.texter = None
        if self.assembly is not None:
            self.assembly.stop()
            self.assembly = None
        self.tool = None
        band = getattr(self.tool_panel, "band", None)
        if band is not None and self.bed.root is not None:
            try:
                self.bed.root.removeChild(band)       # the Variable layer height's colour band
            except Exception as _fw_err:
                _fw_log("slicertoolbar.py:band", _fw_err)
        if self.tool_panel is not None:
            self.tool_panel.hide()
            self.tool_panel.deleteLater()
            self.tool_panel = None
        self.bed.show_cut(None)
        self.bed.gizmo.set_mode(None)

    def open_tool(self, key):
        self.close_tool()
        if self.buttons["flatten"].isChecked():
            self.buttons["flatten"].setChecked(False)
            self.bed.stop_pick()
        self.tool = key
        self.buttons[key].setChecked(True)
        self.tool_panel = getattr(self, "_panel_" + key)()
        self.tool_panel.setStyleSheet(self.panel_style())
        slicersettings.guard_wheel(self.tool_panel)
        self.tool_panel.show()
        self.bed.gizmo.set_mode(key if key in ("move", "rotate", "scale") else None)
        if key in PAINT_TOOLS:
            from . import slicerpaint
            self.painter = slicerpaint.Painter(self, key)
            self.tool_panel.set_value(self.tool_panel.default)
            self.tool_panel.set_tool()
        if key == "measure":
            from . import slicermeasure
            self.measurer = slicermeasure.Measurer(self)
        self.refresh()
        self.place()

    def refresh(self):
        """Fill the open panel from the selection (the bed calls this through the slicer panel)."""
        p = self.tool_panel
        if p is None or not self.bed.items:
            return
        its = self.bed.targets()
        box = self.bed.placed_mesh(items=its).BoundBox
        it = its[0]
        if self.tool == "move":
            for w, v in ((p.px, (box.XMin + box.XMax) / 2), (p.py, (box.YMin + box.YMax) / 2)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        elif self.tool == "rotate":
            yaw, pitch, roll = it.rotation.getYawPitchRoll()
            for w, v in ((p.rx, roll), (p.ry, pitch), (p.rz, yaw)):
                w.blockSignals(True)
                w.setValue(round(v, 2))
                w.blockSignals(False)
        elif self.tool == "scale":
            for w, v in ((p.sx, it.scale.x), (p.sy, it.scale.y), (p.sz, it.scale.z)):
                w.blockSignals(True)
                w.setValue(v * 100.0)
                w.blockSignals(False)
            for w, v in ((p.wx, box.XLength), (p.wy, box.YLength), (p.wz, box.ZLength)):
                w.blockSignals(True)
                w.setValue(v)
                w.blockSignals(False)
        elif self.tool == "boolean":
            p.fill()
        elif self.tool == "assembly" and self.assembly is not None:
            self.assembly.build()
        elif self.tool == "cut":
            p.height.blockSignals(True)
            p.height.setMaximum(max(0.01, box.ZLength))
            if p.height.value() <= 0 or p.height.value() >= box.ZLength:
                p.height.setValue(box.ZLength / 2.0)
            p.height.blockSignals(False)
            self.bed.show_cut(p.height.value(), box)

    def _panel_move(self):
        p = ToolPanel("Move", self.parentWidget())
        p.px = _spin(-10000, 10000, " mm", 2)
        p.py = _spin(-10000, 10000, " mm", 2)
        p.row("X", p.px)
        p.row("Y", p.py)
        hint = QtWidgets.QLabel("Or drag an object on the plate.")
        p.lay.addWidget(hint, p.lay.rowCount(), 0, 1, 4)
        apply = lambda *_: self._move_to(p.px.value(), p.py.value())
        p.px.valueChanged.connect(apply)
        p.py.valueChanged.connect(apply)
        return p

    def _move_to(self, x, y):
        box = self.bed.placed_mesh().BoundBox
        self.bed.move_by(x - (box.XMin + box.XMax) / 2, y - (box.YMin + box.YMax) / 2)

    def _panel_rotate(self):
        p = ToolPanel("Rotate", self.parentWidget())
        p.rx = _spin(-360, 360, " °", 2, 5)
        p.ry = _spin(-360, 360, " °", 2, 5)
        p.rz = _spin(-360, 360, " °", 2, 5)
        for label, w, axis in (("X", p.rx, "x"), ("Y", p.ry, "y"), ("Z", p.rz, "z")):
            b = QtWidgets.QPushButton("+90°")
            b.setToolTip("Turn 90° about the plate's %s axis" % label)
            b.clicked.connect(lambda _=False, a=axis: self.bed.rotate(a, 90))
            p.row(label, w, b)
            w.valueChanged.connect(self._rotate_to)
        reset = QtWidgets.QPushButton("Reset rotation")
        reset.clicked.connect(lambda: self.bed.set_rotation(App.Rotation()))
        p.lay.addWidget(reset, p.lay.rowCount(), 0, 1, 3)
        return p

    def _rotate_to(self, *_):
        p = self.tool_panel
        self.bed.set_rotation(App.Rotation(p.rz.value(), p.ry.value(), p.rx.value()))

    def _panel_scale(self):
        p = ToolPanel("Scale", self.parentWidget())
        p.uniform = QtWidgets.QCheckBox("Uniform scale")
        p.uniform.setChecked(True)
        p.lay.addWidget(p.uniform, 1, 0, 1, 3)
        p.sx, p.sy, p.sz = (_spin(0.1, 100000, " %", 2, 10) for _ in range(3))
        p.wx, p.wy, p.wz = (_spin(0.01, 100000, " mm", 2) for _ in range(3))
        hdr = p.lay.rowCount()
        p.lay.addWidget(QtWidgets.QLabel("Scale"), hdr, 1)
        p.lay.addWidget(QtWidgets.QLabel("Size"), hdr, 2)
        for label, s, w, i in (("X", p.sx, p.wx, 0), ("Y", p.sy, p.wy, 1), ("Z", p.sz, p.wz, 2)):
            p.row(label, s, w)
            s.valueChanged.connect(lambda v, i=i: self._scale_percent(i, v))
            w.valueChanged.connect(lambda v, i=i: self._scale_size(i, v))
        reset = QtWidgets.QPushButton("Reset scale")
        reset.clicked.connect(lambda: self.bed.set_scale((1, 1, 1)))
        p.lay.addWidget(reset, p.lay.rowCount(), 0, 1, 3)
        return p

    def _scale_percent(self, axis, value):
        it = self.bed.targets()[0]
        f = [it.scale.x, it.scale.y, it.scale.z]
        if self.tool_panel.uniform.isChecked():
            k = value / 100.0 / (f[axis] or 1.0)
            f = [v * k for v in f]
        else:
            f[axis] = value / 100.0
        self.bed.set_scale(f)

    def _scale_size(self, axis, value):
        box = self.bed.placed_mesh().BoundBox
        now = (box.XLength, box.YLength, box.ZLength)[axis]
        if now <= 1e-9:
            return
        it = self.bed.targets()[0]
        f = [it.scale.x, it.scale.y, it.scale.z]
        k = value / now
        if self.tool_panel.uniform.isChecked():
            f = [v * k for v in f]
        else:
            # size along a bed axis: scale the model axis that lies along it after the rotation
            f[axis] *= k
        self.bed.set_scale(f)

    def _panel_cut(self):
        p = ToolPanel("Cut", self.parentWidget())
        p.height = _spin(0.0, 10000, " mm", 2, 0.5)
        p.height.setToolTip("Height of the cut above the plate")
        p.row("Height", p.height)
        p.upper = QtWidgets.QCheckBox("Keep upper part")
        p.lower = QtWidgets.QCheckBox("Keep lower part")
        p.flip = QtWidgets.QCheckBox("Place upper part on its cut face")
        for c in (p.upper, p.lower, p.flip):
            c.setChecked(True)
            p.lay.addWidget(c, p.lay.rowCount(), 0, 1, 3)
        go = QtWidgets.QPushButton("Perform cut")
        go.clicked.connect(self._cut)
        p.lay.addWidget(go, p.lay.rowCount(), 0, 1, 3)
        p.height.valueChanged.connect(lambda *_: self.refresh())
        return p

    # ------------------------------------------------------------------ painting (the slicers' paint tools)
    def _paint_panel(self, kind, choices):
        """choices: [(text, value, tooltip)]; value None = Erase."""
        from . import slicerpaint
        p = ToolPanel(slicerpaint.TITLES[kind], self.parentWidget())
        p.group = QtWidgets.QButtonGroup(p)
        p.choices = {}
        row = QtWidgets.QHBoxLayout()
        for text, value, tip in choices:
            b = QtWidgets.QPushButton(text)
            b.setCheckable(True)
            b.setToolTip(tip)
            p.group.addButton(b)
            p.choices[value] = b
            b.clicked.connect(lambda _=False, v=value: p.set_value(v))
            row.addWidget(b)
        p.lay.addLayout(row, p.lay.rowCount(), 0, 1, 4)

        def set_value(v):
            if v in p.choices:
                p.choices[v].setChecked(True)
            if self.painter is not None:
                self.painter.value = v
        p.set_value = set_value
        p.default = choices[0][1]
        # the slicers' Tool type: Circle (a round brush) or Fill (a whole face), and the brush size
        tools = QtWidgets.QHBoxLayout()
        tools.addWidget(QtWidgets.QLabel("Tool type"))
        p.tool = QtWidgets.QComboBox()
        p.tool.setObjectName("SWStyle_SlicerPaintTool")
        # the slicers' tool types: Circle and Sphere on every painting tool, Gap fill on support painting
        for text, key in (("Circle", "circle"), ("Sphere", "sphere"), ("Fill", "fill"), ("Smart fill", "smart")) + \
                ((("Gap fill", "gap"),) if kind == "support" else ()):
            p.tool.addItem(text, key)
        p.tool.setToolTip("Circle: a round brush across the view, paints the faces turned to you. Sphere: a ball, "
                          "paints everything inside it, both sides. Fill: paints a whole face. Smart fill: paints the "
                          "smooth region around the face, up to edges sharper than the angle."
                          + (" Gap fill: fills the small unpainted faces enclosed by paint." if kind == "support" else ""))
        tools.addWidget(p.tool, 1)
        p.size_label = QtWidgets.QLabel("Brush size")
        tools.addWidget(p.size_label)
        p.size = QtWidgets.QDoubleSpinBox()
        p.size.setObjectName("SWStyle_SlicerPaintSize")
        p.size.setRange(0.5, 50.0)
        p.size.setSingleStep(0.5)
        p.size.setDecimals(1)
        p.size.setSuffix(" mm")
        p.size.setValue(4.0)
        p.size.setToolTip("The brush's diameter")
        tools.addWidget(p.size)
        p.angle_label = QtWidgets.QLabel("Angle")
        tools.addWidget(p.angle_label)
        p.angle = QtWidgets.QDoubleSpinBox()
        p.angle.setObjectName("SWStyle_SlicerPaintAngle")
        p.angle.setRange(0.0, 90.0)
        p.angle.setSingleStep(5.0)
        p.angle.setDecimals(0)
        p.angle.setSuffix("\u00b0")
        p.angle.setValue(30.0)
        p.angle.setToolTip("Smart fill stops at edges where the surface turns more than this")
        tools.addWidget(p.angle)
        p.gap_label = QtWidgets.QLabel("Gap area")
        tools.addWidget(p.gap_label)
        p.gap = QtWidgets.QDoubleSpinBox()
        p.gap.setObjectName("SWStyle_SlicerPaintGap")
        p.gap.setRange(0.1, 500.0)
        p.gap.setDecimals(1)
        p.gap.setSuffix(" mm\u00b2")
        p.gap.setValue(10.0)
        p.gap.setToolTip("Gap fill fills unpainted faces up to this area")
        tools.addWidget(p.gap)
        p.lay.addLayout(tools, p.lay.rowCount(), 0, 1, 4)
        if kind == "support":
            # the slicers' overhang options of support painting
            oh = QtWidgets.QHBoxLayout()
            p.highlight = QtWidgets.QCheckBox("Highlight overhang areas")
            p.highlight.setObjectName("SWStyle_SlicerPaintHighlight")
            p.only = QtWidgets.QCheckBox("On overhangs only")
            p.only.setObjectName("SWStyle_SlicerPaintOnly")
            p.only.setToolTip("Paint only where the object overhangs more than the angle")
            p.oh_angle = QtWidgets.QDoubleSpinBox()
            p.oh_angle.setObjectName("SWStyle_SlicerPaintOverhang")
            p.oh_angle.setRange(0.0, 90.0)
            p.oh_angle.setDecimals(0)
            p.oh_angle.setSuffix("\u00b0")
            try:
                from . import slicerobject as _so
                p.oh_angle.setValue(float(str(_so.effective_process(self.panel).get("support_threshold_angle") or 30)
                                          .strip("%")) or 30.0)
            except Exception:
                p.oh_angle.setValue(30.0)
            p.oh_angle.setToolTip("Overhang angle (from the horizontal), as the process's support threshold angle")
            oh.addWidget(p.highlight)
            oh.addWidget(p.only)
            oh.addWidget(p.oh_angle)
            p.lay.addLayout(oh, p.lay.rowCount(), 0, 1, 4)

            def set_overhang(*_a):
                if self.painter is None:
                    return
                a = p.oh_angle.value()
                self.painter.overhang_only = a if p.only.isChecked() else None
                want = a if p.highlight.isChecked() else None
                from . import slicerpaint as _sp
                if _sp.HIGHLIGHT.get("angle") != want:
                    self.painter.highlight(want)
            p.highlight.toggled.connect(set_overhang)
            p.only.toggled.connect(set_overhang)
            p.oh_angle.valueChanged.connect(set_overhang)
            p.set_overhang = set_overhang
        # the slicers' Section view: cut the objects away from the eye's side to paint inside
        sec = QtWidgets.QHBoxLayout()
        sec.addWidget(QtWidgets.QLabel("Section view"))
        p.section = QtWidgets.QSlider(Qt.Horizontal)
        p.section.setObjectName("SWStyle_SlicerPaintSection")
        p.section.setRange(0, 100)
        p.section.setValue(100)
        p.section.setToolTip("Cuts the objects away from your side so faces inside can be painted (all the way "
                             "right: the whole objects)")
        p.section.valueChanged.connect(lambda v: self.painter is not None and self.painter.set_section(v / 100.0))
        sec.addWidget(p.section, 1)
        p.lay.addLayout(sec, p.lay.rowCount(), 0, 1, 4)
        hint = QtWidgets.QLabel()
        hint.setWordWrap(True)

        def set_tool(_i=None):
            t = p.tool.currentData()
            p.size.setVisible(t in ("circle", "sphere"))
            p.size_label.setVisible(t in ("circle", "sphere"))
            p.angle.setVisible(t == "smart")
            p.angle_label.setVisible(t == "smart")
            p.gap.setVisible(t == "gap")
            p.gap_label.setVisible(t == "gap")
            hint.setText({"circle": "Click or drag over an object to paint the faces turned to you under the brush.",
                          "sphere": "Click or drag over an object to paint everything inside the ball, both sides.",
                          "smart": "Click a face of an object to paint it and the smooth surface around it.",
                          "gap": "Click an object to fill the small unpainted faces enclosed by the paint "
                                 "(the paint choice above)."}.get(
                t, "Click a face of an object to paint it; drag to paint more faces."))
            if self.painter is not None:
                self.painter.tool = t
                self.painter.radius = p.size.value() / 2.0
                self.painter.smart_angle = p.angle.value()
                self.painter.gap_area = p.gap.value()
                self.painter.last = None

        def set_size(_v=None):
            if self.painter is not None:
                self.painter.radius = p.size.value() / 2.0
                self.painter.smart_angle = p.angle.value()
                self.painter.gap_area = p.gap.value()
        p.tool.currentIndexChanged.connect(set_tool)
        p.size.valueChanged.connect(set_size)
        p.angle.valueChanged.connect(set_size)
        p.gap.valueChanged.connect(set_size)
        p.set_tool = set_tool
        set_tool()
        p.lay.addWidget(hint, p.lay.rowCount(), 0, 1, 4)
        p.note = QtWidgets.QLabel(slicerpaint.hint(self.panel, kind))
        p.note.setWordWrap(True)
        p.lay.addWidget(p.note, p.lay.rowCount(), 0, 1, 4)
        clear = QtWidgets.QPushButton("Remove all")
        clear.setToolTip("Take this paint off every object on the plate")

        def do_clear():
            if slicerpaint.clear(self.bed, kind, panel=self.panel):
                self.panel._stale()
            p.note.setText(slicerpaint.hint(self.panel, kind))
        clear.clicked.connect(do_clear)
        p.lay.addWidget(clear, p.lay.rowCount(), 0, 1, 2)
        p.setMinimumWidth(300)
        return p

    def _panel_boolean(self):
        from . import slicerbool
        return slicerbool.panel(self, ToolPanel)

    def _panel_text(self):
        from . import slicertext
        self.texter = slicertext.TextTool(self)
        return slicertext.panel(self, ToolPanel)

    def _panel_assembly(self):
        from . import slicerassembly
        self.assembly = slicerassembly.AssemblyView(self)
        return slicerassembly.panel(self, ToolPanel)

    def _panel_measure(self):
        from . import slicermeasure
        return slicermeasure.panel(self, ToolPanel)

    def _panel_ears(self):
        from . import slicerears
        self.ears = slicerears.EarTool(self)
        return slicerears.panel(self, ToolPanel)

    def _panel_support(self):
        return self._paint_panel("support", [
            ("Enforce", "enforce", "Supports under these faces (with supports on)"),
            ("Block", "block", "No supports under these faces"),
            ("Erase", None, "Take the paint off a face")])

    def _panel_seam(self):
        return self._paint_panel("seam", [
            ("Enforce", "enforce", "Put the seam on these faces"),
            ("Block", "block", "Keep the seam off these faces"),
            ("Erase", None, "Take the paint off a face")])

    def _panel_fuzzy(self):
        return self._paint_panel("fuzzy", [
            ("Paint", "enforce", "Fuzzy skin on these faces"),
            ("Erase", None, "Take the paint off a face")])

    def _panel_color(self):
        n = max(1, len(getattr(self.panel.slots, "colours", [None])))
        choices = [("Filament %d" % i, i, "Print these faces with filament %d" % i) for i in range(1, n + 1)]
        choices.append(("Erase", None, "Back to the object's own filament"))
        p = self._paint_panel("color", choices)
        p.default = 2 if n > 1 else 1          # the slicers start Color Painting on the second filament
        for value, b in p.choices.items():
            if value is not None:
                c = self.panel.slots.colours[value - 1] if value - 1 < len(self.panel.slots.colours) else "#cccccc"
                pix = QtGui.QPixmap(12, 12)
                pix.fill(QtGui.QColor(c))
                b.setIcon(QtGui.QIcon(pix))
        if n == 1:
            p.note.setText(p.note.text() + "\nAdd a filament (Filament > Add) to paint with it.")
        return p

    # ------------------------------------------------------------------ variable layer height
    def _panel_layers(self):
        from . import slicerlayers as sl
        p = ToolPanel("Variable Layer Height", self.parentWidget())
        p.setMinimumWidth(300)
        its = self.bed.targets()
        if len(its) != 1:
            p.lay.addWidget(QtWidgets.QLabel("Select one object on the plate (click it)."), 1, 0, 1, 4)
            return p
        it = its[0]
        first, lo, hi, layer = sl.limits(self.panel)
        mesh = sl.placed_mesh(self.bed, it)
        height = mesh.BoundBox.ZLength
        p.item, p.mesh, p.height, p.first, p.lo, p.hi = it, mesh, height, first, lo, hi
        p.quality = QtWidgets.QSlider(Qt.Horizontal)
        p.quality.setRange(0, 100)
        p.quality.setValue(50)
        p.quality.setToolTip("Left: faster (thicker layers); right: finer surfaces")
        p.row("Speed", p.quality, QtWidgets.QLabel("Quality"))
        adaptive = QtWidgets.QPushButton("Adaptive")
        adaptive.setToolTip("Thin layers where the surface slopes, thick ones where the walls are straight")
        p.radius = _spin(0.2, 10.0, " mm", 1, 0.5)
        p.radius.setValue(1.0)
        smooth = QtWidgets.QPushButton("Smooth")
        reset = QtWidgets.QPushButton("Reset")
        reset.setToolTip("Back to the process's layer height")
        p.row(None, adaptive, smooth, reset)
        p.row("Radius", p.radius)
        p.curve = sl.Curve()
        p.lay.addWidget(p.curve, p.lay.rowCount(), 0, 1, 4)
        p.note = QtWidgets.QLabel()
        p.lay.addWidget(p.note, p.lay.rowCount(), 0, 1, 4)
        # the colour band's key: thin layers blue, thick ones red (the object shows the band while the tool is open)
        p.key = QtWidgets.QLabel("%.2f mm" % lo)
        p.key.setObjectName("SWStyle_SlicerLayerKey")
        stops = "".join(", stop:%.2f rgb(%d,%d,%d)" % ((t,) + tuple(int(v * 255) for v in c)) for t, c in sl.BAND_STOPS)
        p.key.setStyleSheet("QLabel{color:white;padding:1px 4px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0%s);}"
                            % stops)
        p.key_hi = QtWidgets.QLabel("%.2f mm" % hi)
        p.key_hi.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        p.key_hi.setStyleSheet("QLabel{color:white;padding:1px 4px;background:transparent;}")
        key_row = p.lay.rowCount()
        p.lay.addWidget(p.key, key_row, 0, 1, 4)
        p.lay.addWidget(p.key_hi, key_row, 0, 1, 4)
        p.band = None

        def show(prof, store=True):
            if store:
                it.layer_profile = list(prof) if prof else None
                it.layer_profile_sig = sl.signature(it) if prof else None
                self.panel._stale()
            shown = prof or sl.flat(height, first, layer)
            p.curve.set_curve(sl.resample(shown, height, first, lo, hi, step=max(0.05, height / 200.0)), height, lo, hi)
            try:
                p.band = sl.show_band(self.bed, it, shown, lo, hi, p.band)
            except Exception as error:
                App.Console.PrintLog("slicer layers: no colour band (%s)\n" % error)
            n = sl.layer_count(shown)
            p.note.setText("%d layers (%.2f to %.2f mm)%s" % (
                n, min(shown[1::2]), max(shown[1::2]), "" if prof else ", the process's layer height"))

        p.curve.radius = p.radius.value()
        p.radius.valueChanged.connect(lambda v: setattr(p.curve, "radius", v))
        adaptive.clicked.connect(lambda: show(sl.adaptive(mesh, first, lo, hi, p.quality.value() / 100.0)))
        smooth.clicked.connect(lambda: show(sl.smooth(sl.profile_of(it) or sl.flat(height, first, layer),
                                                      p.radius.value(), lo, hi)))
        reset.clicked.connect(lambda: show(None))
        p.curve.edited.connect(lambda: show(sl.from_curve(p.curve.curve, height, first, lo, hi)))
        p.adaptive, p.smooth, p.reset, p.show_profile = adaptive, smooth, reset, show
        show(sl.profile_of(it), store=False)
        return p

    def _cut(self):
        p = self.tool_panel
        if len(self.bed.targets()) != 1:
            self.panel._say("Select one object to cut (click it on the plate).")
            return
        keep = "both" if p.upper.isChecked() and p.lower.isChecked() else (
            "upper" if p.upper.isChecked() else "lower" if p.lower.isChecked() else None)
        if keep is None:
            return
        ok = self.bed.cut(p.height.value(), keep, p.flip.isChecked())
        self.close_tool()
        if not ok:
            self.panel._say("The cut height is outside the object.")
