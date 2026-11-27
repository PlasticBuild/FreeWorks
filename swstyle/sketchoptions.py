# SPDX-License-Identifier: LGPL-2.1-or-later
""







import copy

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

PREFERENCES = "User parameter:BaseApp/Preferences/"
SKETCHER = "Mod/Sketcher"
GENERAL = "Mod/Sketcher/General"
SNAP = "Mod/Sketcher/Snap"
GROUP = "Sketcher"   # FreeCAD's own group, so the pages sit next to its sketcher pages


def _param(path):
    return App.ParamGet(PREFERENCES + path)


class Setting:
    """One parameter. Only a value changed on the page is written: FreeCAD's own pages show some of
    the same parameters, and a page saved after theirs must not undo a change made there."""

    def __init__(self, path, key, default, text, tip="", needs=None, indent=False):
        self.path, self.key, self.default, self.text, self.tip = path, key, default, text, tip
        self.needs = needs   # key of the checkbox that must be on for this one to apply
        self.indent = indent

    def tag(self, widget):
        # FreeCAD's Reset button removes the parameters named by these two properties
        widget.setProperty("prefPath", self.path)
        widget.setProperty("prefEntry", self.key)
        widget.setToolTip(self.tip)

    def changed(self):
        return self.value() != self.loaded


class Bool(Setting):
    def widget(self):
        self.box = QtWidgets.QCheckBox(self.text)
        self.tag(self.box)
        if not self.indent:
            return self.box
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(20, 0, 0, 0)
        lay.addWidget(self.box)
        return row

    def value(self):
        return self.box.isChecked()

    def load(self):
        self.box.setChecked(_param(self.path).GetBool(self.key, self.default))
        self.loaded = self.value()

    def save(self):
        # FreeCAD's own widget for the same parameter, if any, follows the write by itself
        if self.changed():
            _param(self.path).SetBool(self.key, self.value())
            self.loaded = self.value()


class Number(Setting):
    """An integer (pixels) or a float (degrees), with its unit after the box."""

    def __init__(self, path, key, default, text, unit, low, high, decimals=0, tip="", needs=None):
        super().__init__(path, key, default, text, tip, needs)
        self.unit, self.low, self.high, self.decimals = unit, low, high, decimals

    def widget(self):
        if self.decimals:
            self.box = QtWidgets.QDoubleSpinBox()
            self.box.setDecimals(self.decimals)
        else:
            self.box = QtWidgets.QSpinBox()
        self.box.setRange(self.low, self.high)
        self.box.setSuffix(" " + self.unit)
        self.tag(self.box)
        row = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QtWidgets.QLabel(self.text)
        self.label.setToolTip(self.tip)
        self.label.setBuddy(self.box)
        lay.addWidget(self.label)
        lay.addWidget(self.box)
        lay.addStretch(1)
        return row

    def value(self):
        return self.box.value()

    def load(self):
        grp = _param(self.path)
        if self.decimals:
            self.box.setValue(grp.GetFloat(self.key, self.default))
        else:
            self.box.setValue(grp.GetInt(self.key, self.default))
        self.loaded = self.value()

    def save(self):
        if not self.changed():
            return
        if self.decimals:
            _param(self.path).SetFloat(self.key, self.value())
        else:
            _param(self.path).SetInt(self.key, self.value())
        self.loaded = self.value()



RELATIONS_SNAPS = ("Relations/Snaps", [
    (None, [
        Bool(SNAP, "Snap", True, "Enable snapping",
             "Snap the pointer to sketch points, edges and inference lines while a sketch tool runs"),
        Bool(SNAP, "SnapToModel", True, "Snap to model geometry",
             "Also snap to edges and corners of the part; they become reference geometry",
             needs="Snap"),
        Bool(GENERAL, "AutoConstraints", True, "Automatic relations",
             "Add relations (Coincident, Horizontal, Tangent...) while drawing. Hold Ctrl to leave "
             "them out for one click"),
    ]),
    ("Sketch snaps", [

        Bool(SNAP, "SnapToEndPoints", True, "End points and sketch points", needs="Snap"),
        Bool(SNAP, "SnapToCenterPoints", True, "Center Points", needs="Snap"),
        Bool(SNAP, "SnapToMidpoints", True, "Mid-points", needs="Snap"),
        Bool(SNAP, "SnapToQuadrants", True, "Quadrant Points", needs="Snap"),
        Bool(SNAP, "SnapToIntersections", True, "Intersections", needs="Snap"),
        Bool(SNAP, "SnapToNearest", True, "Nearest", "Snap onto the curve under the pointer", needs="Snap"),
        Bool(SNAP, "SnapToTangent", True, "Tangent", "Tangent points on arcs and circles from the line's start",
             needs="Snap"),
        Bool(SNAP, "SnapToPerpendicular", True, "Perpendicular",
             "Perpendicular points and dotted lines square to a line the pointer passed over", needs="Snap"),
        Bool(SNAP, "SnapToParallel", True, "Parallel",
             "Dotted lines parallel to a line the pointer passed over", needs="Snap"),
        Bool(SNAP, "SnapToHVLines", True, "Horizontal/vertical lines",
             "Lines snap level or upright and get the Horizontal or Vertical relation", needs="Snap"),
        Bool(SNAP, "SnapToAlignments", True, "Horizontal/vertical to points",
             "Dotted lines level with, or straight above or below, other points", needs="Snap"),
        Bool(SNAP, "SnapToLength", True, "Length",
             "Hold Shift while drawing to round a line's length to the grid step", needs="Snap"),
        Bool(SNAP, "SnapToGrid", False, "Grid", needs="Snap"),
        Bool(SNAP, "SnapToGridWhenShown", True, "Snap only when grid is displayed", needs="SnapToGrid", indent=True),
        Bool(SNAP, "SnapToAngle", True, "Angle",
             "Lines snap to multiples of the snap angle from the X axis or from the line being "
             "continued. Snap only: no relation is added", needs="Snap"),
        Bool(SNAP, "SnapToExtensions", True, "Extensions of lines", needs="Snap"),
        Bool(SNAP, "ExtensionAddsRelation", False, "Extensions add a relation",
             "A point placed on the extension of a line gets a point-on-line (Coincident) relation",
             needs="SnapToExtensions", indent=True),
    ]),
    ("Angle and distance", [
        Number(SNAP, "SnapAngle", 45.0, "Snap angle", "°", 0.01, 90.0, 2, needs="SnapToAngle"),
        Number(SNAP, "AxisBandAngle", 0.5, "Horizontal/vertical within", "°", 0.1, 15.0, 1,
               "How close to level or upright a line must be to snap there and get the relation"),
        Number(SNAP, "SnapRadius", 5, "Snap distance", "pixels", 1, 50,
               tip="How close the pointer must come to a point or an edge", needs="Snap"),
    ]),
])

SKETCH = ("Sketch", [
    ("Dimensions", [
        Bool(SKETCHER, "ShowDialogOnDistanceConstraint", True, "Input dimension value",
             "Open the value box when a dimension is placed"),
        Bool(SKETCHER, "KeepDimensionOnCancel", True,
             "Keep a new dimension when its value box is canceled",
             "It keeps the measured size. Off: Cancel removes the dimension",
             needs="ShowDialogOnDistanceConstraint", indent=True),
    ]),
    ("Over defining dimensions", [
        Bool(SKETCHER, "PromptDrivenState", True, "Prompt to set driven state",
             "A dimension that would over-define the sketch asks \"Make Dimension Driven?\" when it "
             "is placed"),
        Bool(SKETCHER, "DrivenWhenOverDefining", True, "Set driven by default",
             "A dimension that would over-define the sketch is added as a driven (reference) "
             "dimension; with the prompt on, the box offers driven first. Off: it is added as "
             "driving and the sketch shows the conflict"),
    ]),
    ("Drawing", [
        Bool(SKETCHER, "ClickDragDrawing", True, "Draw with press, drag and release",
             "A line, rectangle, circle or arc in one press, drag and release, as well as with two "
             "clicks"),
        Bool(SKETCHER, "ContinuousCreationMode", True, "Sketch tools stay active after drawing"),
        Bool(SKETCHER, "EscapeEndsTool", True, "Esc ends the sketch tool",
             "Off: the first Esc only cancels what is being drawn"),
        Bool(SKETCHER, "LeaveSketchWithEscape", False, "Esc with no tool running leaves the sketch",
             "Off: Esc ends the tool and clears the selection, and you stay in the "
             "sketch (leave it with the confirmation corner or Exit Sketch)"),
        Bool(GENERAL, "AvoidRedundantAutoconstraints", True,
             "Leave out automatic relations that would over-define the sketch"),
        Bool(GENERAL, "OnScreenNumericInput", False,
             "Enable on-screen numeric input on entity creation",
             "Type a line's length while drawing it: Enter ends the line at that length, keeps it "
             "as a dimension and the next line goes on"),
        Bool(GENERAL, "CenterRectangleDiagonals", True,
             "Center Rectangle adds construction lines from corners",
             "Two construction diagonals, the center point where they cross"),
        Bool(GENERAL, "LineContextMenu", True,
             "Right-click in the Line tool shows its menu",
             "Select, End Chain and Switch to Arc. Off: a right-click ends the chain"),
    ]),
])


# Options that only work with a sketch patch in the running FreeCAD (native.py); stock FreeCAD
# leaves them off the pages
NEEDS_PATCH = {
    "SnapToModel": "snap_points", "SnapToMidpoints": "snap_points", "SnapToQuadrants": "snap_points",
    "SnapToIntersections": "snap_points", "SnapRadius": "snap_points",
    "SnapToParallels": "inference_lines", "SnapToAlignments": "inference_lines",
    "SnapToExtensions": "inference_lines", "ExtensionAddsRelation": "inference_lines",
    "AxisBandAngle": "inference_lines",
    "SnapToLength": "length_snap",
    "PromptDrivenState": "driven_prompt",
    "DrivenWhenOverDefining": "drag_relations", "KeepDimensionOnCancel": "drag_relations",
    "ClickDragDrawing": "click_drag",
    "EscapeEndsTool": "escape_ends_tool",
    "OnScreenNumericInput": "numeric_input",
    "CenterRectangleDiagonals": "center_diagonals",
    "LineContextMenu": "line_menu",
}


def _tool_menu_owns_right_click():
    ""
    try:
        from . import sketchtoolmenu
        return bool(sketchtoolmenu.enabled())
    except Exception:
        return False


def available(setting):
    """False for an option the running FreeCAD's Sketcher cannot honour."""
    if setting.key == "LineContextMenu" and _tool_menu_owns_right_click():
        return False    # the look's sketch-tool menu has the right-click
    feature = NEEDS_PATCH.get(setting.key)
    if feature is None:
        return True
    try:
        from . import native
        return native.has(feature)
    except Exception:
        return True


class Page:
    """A page for Gui.addPreferencePage, which takes the class and makes one for each dialog."""

    PAGE = None

    def __init__(self):
        title, sections = self.PAGE
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(title)
        self.settings = []
        lay = QtWidgets.QVBoxLayout(self.form)
        for heading, settings in sections:
            settings = [s for s in settings if available(s)]
            if not settings:
                continue
            if heading:
                box = QtWidgets.QGroupBox(heading)
                inner = QtWidgets.QVBoxLayout(box)
                lay.addWidget(box)
            else:
                inner = lay
            for setting in settings:
                setting = copy.copy(setting)   # each dialog gets its own widgets
                setting.row = setting.widget()
                inner.addWidget(setting.row)
                self.settings.append(setting)
        lay.addStretch(1)
        self.boxes = {s.key: s.box for s in self.settings if isinstance(s, Bool)}
        for box in self.boxes.values():
            box.toggled.connect(self.update_enabled)

    def update_enabled(self):
        ""
        for setting in self.settings:
            on, key = True, setting.needs
            while on and key in self.boxes:
                on = self.boxes[key].isChecked()
                key = next((s.needs for s in self.settings if s.key == key), None)
            setting.row.setEnabled(on)

    def loadSettings(self):
        for setting in self.settings:
            setting.load()
        self.update_enabled()

    def saveSettings(self):
        for setting in self.settings:
            setting.save()


class SketchPage(Page):
    PAGE = SKETCH


class RelationsSnapsPage(Page):
    PAGE = RELATIONS_SNAPS


def _sketch_in_edit():
    doc = Gui.ActiveDocument
    vp = doc.getInEdit() if doc else None
    return vp if vp is not None and hasattr(vp, "Autoconstraints") else None


class AutomaticRelationsCommand:
    """Tools > Sketch Settings > Automatic Relations: on or off for every sketch, and at once for
    the sketch being edited."""

    def GetResources(self):
        return {
            "MenuText": "Automatic Relations",
            "ToolTip": "Ties new sketch entities together as you draw",
            "Checkable": _param(GENERAL).GetBool("AutoConstraints", True),
            # Without it FreeCAD greys the command out while the sketch's task panel is open
            "CmdType": "ForEdit",
        }

    def Activated(self, checked):
        on = bool(checked)
        _param(GENERAL).SetBool("AutoConstraints", on)
        vp = _sketch_in_edit()
        if vp is not None:
            vp.Autoconstraints = on

    def IsActive(self):
        # Follow changes made elsewhere: the Options page, the sketcher's task panel
        vp = _sketch_in_edit()
        on = vp.Autoconstraints if vp is not None else _param(GENERAL).GetBool("AutoConstraints", True)
        try:
            actions = Gui.Command.get("SWStyle_AutomaticRelations").getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != on:
                blocked = action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(blocked)
        return App.ActiveDocument is not None


ESCAPE_MOVED = "EscapeStaysInSketchSet"   # in the look's own group: the move below is done


BAND_SET = "AxisBandSolidWorksSet"


def _band_once():
    ""


    from . import paths
    own = paths.params()
    if own.GetBool(BAND_SET, False):
        return
    p = _param("Mod/Sketcher/Snap")
    if abs(p.GetFloat("AxisBandAngle", 0.5) - 1.5) < 1e-9:
        p.SetFloat("AxisBandAngle", 0.5)
    own.SetBool(BAND_SET, True)


def _escape_leaves_sketch_once():
    ""


    from . import paths
    own = paths.params()
    if own.GetBool(ESCAPE_MOVED, False):
        return
    _param(SKETCHER).SetBool("LeaveSketchWithEscape", False)
    own.SetBool(ESCAPE_MOVED, True)


DIAGONALS_SET = "CenterRectangleDiagonalsSet"   # in the look's own group


def _center_diagonals_once():
    ""

    from . import paths
    own = paths.params()
    if own.GetBool(DIAGONALS_SET, False):
        return
    _param(GENERAL).SetBool("CenterRectangleDiagonals", True)
    own.SetBool(DIAGONALS_SET, True)


LINE_MENU_SET = "LineContextMenuSet"   # in the look's own group


def _line_menu_once():
    ""

    from . import paths
    own = paths.params()
    if own.GetBool(LINE_MENU_SET, False):
        return
    _param(GENERAL).SetBool("LineContextMenu", True)
    own.SetBool(LINE_MENU_SET, True)


LOOK29_SET = "SolidWorksSketchLookSet"   # in the look's own group


def _sketch_look_once():
    ""


    from . import paths
    own = paths.params()
    if own.GetBool(LOOK29_SET, False):
        return
    _param(GENERAL).SetBool("SolidWorksGlyphs", True)
    _param(GENERAL).SetBool("SelectNewRectangle", True)
    _param("Mod/Sketcher/View").SetInt("ConstructionPattern", 0xFFCC)   # long dash, dot
    # picked sketch lines light blue (picked faces keep the look's SelectionColor)
    _param("View").SetUnsigned("SketchSelectionColor", 0x53A9FFFF)
    own.SetBool(LOOK29_SET, True)


POLYGON31_SET = "SolidWorksPolygonSet"   # in the look's own group


def _polygon_once():
    ""


    from . import paths
    own = paths.params()
    if own.GetBool(POLYGON31_SET, False):
        return
    _param(GENERAL).SetBool("PolygonInscribedCircle", True)
    own.SetBool(POLYGON31_SET, True)


SNAP_RADIUS_RESET = "SnapRadiusReset1"   # in Mod/Sketcher/Snap: the 8 px to 5 px move is done


def _snap_radius_once():
    ""

    grp = _param(SNAP)
    if grp.GetBool(SNAP_RADIUS_RESET, False):
        return
    if grp.GetInt("SnapRadius", 0) == 8:
        grp.RemInt("SnapRadius")
    if grp.GetFloat("SnapRadius", 0.0) == 8.0:
        grp.RemFloat("SnapRadius")
    grp.SetBool(SNAP_RADIUS_RESET, True)


def register():
    """Adds the two pages and the command. Call once while FreeCAD starts."""
    try:
        _snap_radius_once()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: snap distance not reset: %s\n" % error)
    try:
        _polygon_once()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: polygon default not set: %s\n" % error)
    try:
        _sketch_look_once()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sketch look settings not set: %s\n" % error)
    try:
        _escape_leaves_sketch_once()
        _band_once()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Esc setting not moved: %s\n" % error)
    try:
        _center_diagonals_once()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Center Rectangle setting not set: %s\n" % error)
    try:
        _line_menu_once()
        if _tool_menu_owns_right_click():
            # one menu only: the look's sketch-tool menu, whose End chain needs FreeCAD's own
            # right-click to end the chain
            _param(GENERAL).SetBool("LineContextMenu", False)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Line menu setting not set: %s\n" % error)
    Gui.addPreferencePage(SketchPage, GROUP)
    Gui.addPreferencePage(RelationsSnapsPage, GROUP)
    Gui.addCommand("SWStyle_AutomaticRelations", AutomaticRelationsCommand())
