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

import collections
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, events, paths
from .widgets import alive

Qt = QtCore.Qt
PARAM = "SketchToolMenu"


T_SELECT = "Select"
T_END_CHAIN = "End chain  (double-click)"
T_TO_ARC = "Switch to arc ( A )"
T_TO_LINE = "Switch to Line ( A )"               # 37583
T_SELECTED = "Selected Entity"                   # 13286
T_SELECTED_N = "Selected Entities"               # 13287
T_CLEAR = "Clear Selections"                     # 34245
T_SELECT_OTHER = "Select Other"                  # 32946
T_SELECT_OTHER_TIP = "Lists what is under the pointer, behind the face in front, so a hidden item can be picked."
T_SELECT_CHAIN = "Select Chain"                  # 5893
T_SELECT_TANGENCY = "Select Tangency"            # 13332
T_SELECT_LOOP = "Select Loop"                    # 13323
T_SELECT_MIDPOINT = "Select Midpoint"            # 32785
T_CONTOUR_SELECT = "Contour Select Tool"         # recordings (1332-line-right-click-menu)
T_MARK_FOR_DRAWING = "Mark For Drawing"          # recordings (1956-dimension-right-click-menu)
T_CUSTOMIZE = "Customize Menu"                   # 38232
T_ZOOM = "Zoom/Pan/Rotate"                       # 15657
T_ENTITIES = "Sketch Entities"                   # 17288
T_TOOLS = "Sketch Tools"                         # 20156
T_RELATIONS = "Relations"                        # 14554
T_DISPLAY_DELETE = "Display/Delete Relations..."  # 34169
T_FULLY_DEFINE = "Fully Define Sketch..."        # 20635
T_TOGGLE_SUPPRESSION = "Toggle Suppression"      # 38216
T_DRIVEN = "Driven"                              # 13187
T_AS_DIAMETER = "Display As Diameter"            # 12131
T_AS_RADIUS = "Display As Radius"                # 12130
T_DISPLAY_GRID = "Display Grid"                  # 10887
T_DETACH = "Detach Segment On Drag"              # 34252
T_EXIT_SKETCH = "Exit Sketch"                    # 20593
T_QUICK_SNAPS = "Quick Snaps"                    # 38452
T_RECENT = "Recent Commands"                     # recordings
T_MORE_DIMS = "More Dimensions"                  # recordings
T_SELECTION_TOOLS = "Selection Tools"            # recordings
T_DELETE = "Delete"                              # 37735
T_HIDE = "Hide"
T_OK, T_CANCEL = "OK", "Cancel"                  # 13300, 13301
CHEVRON = "»"

SEP = None

SKETCH_ENTITIES = (
    ("Line", "Line"), ("CornerRectangle", "Corner Rectangle"), ("CenterRectangle", "Center Rectangle"),
    ("ThreePointCornerRectangle", "3 Point Corner Rectangle"), ("ThreePointCenterRectangle", "3 Point Center Rectangle"),
    ("Parallelogram", "Parallelogram"), ("Slot", "Straight Slot"), ("CenterpointSlot", "Centerpoint Straight Slot"),
    ("ThreePointArcSlot", "3 Point Arc Slot"), ("ArcSlot", "Centerpoint Arc Slot"), ("Polygon", "Polygon"), SEP,
    ("Circle", "Circle"), ("PerimeterCircle", "Perimeter Circle"), ("CenterArc", "Centerpoint Arc"),
    ("TangentArc", "Tangent Arc"), ("ThreePointArc", "3 Point Arc"), SEP,
    ("Ellipse", "Ellipse"), ("PartialEllipse", "Partial Ellipse"), ("Parabola", "Parabola"), ("Conic", "Conic"),
    ("Spline", "Spline"), ("StyleSpline", "Style Spline"), ("SplineOnSurface", "Spline on Surface"),
    ("EquationDrivenCurve", "Equation Driven Curve"), ("SketchPoint", "Point"), ("Centerline", "Centerline"),
    ("MidpointLine", "Midpoint Line"), ("Text", "Text..."), ("BeltChain", "Belt/Chain"))
# Tools > Sketch Tools
SKETCH_TOOLS = (
    ("SketchFillet", "Fillet..."), ("SketchChamfer", "Chamfer..."), ("Offset", "Offset Entities..."),
    ("OffsetOnSurface", "Offset On Surface"), ("Convert", "Convert Entities"),
    ("SilhouetteEntities", "Silhouette Entities"), ("IntersectionCurve", "Intersection Curve"),
    ("FaceCurves", "Face Curves"), SEP,
    ("Segment", "Segment"), ("Trim", "Trim"), ("Extend", "Extend"), ("Split", "Split Entities"),
    ("JogLine", "Jog Line"), ("ConstructionPlane", "Construction Geometry"), ("MakePath", "Make Path"), SEP,
    ("MirrorEntities", "Mirror"), ("DynamicMirror", "Dynamic Mirror"), ("StretchEntities", "Stretch Entities"),
    ("MoveEntities", "Move..."), ("RotateEntities", "Rotate..."), ("ScaleEntities", "Scale..."),
    ("CopyEntities", "Copy..."), ("ReplaceEntity", "Replace Entity..."),
    ("LinearSketchPattern", "Linear Pattern..."), ("CircularSketchPattern", "Circular Pattern..."), SEP,
    ("EditPolygon", "Edit Polygon..."), SEP,
    ("SketchXpert", "SketchXpert..."), ("ModifySketch", "Modify..."), ("CloseSketchToModel", "Close Sketch to Model"),
    ("CheckSketchForFeature", "Check Sketch for Feature..."), SEP,
    ("SketchPicture", "Sketch Picture..."))
# Tools > Dimensions without Smart (the right-click's More Dimensions); Chamfer from the flyout
MORE_DIMENSIONS = (
    ("HorizontalDimension", None), ("VerticalDimension", None), ("BaselineDimension", None),
    ("ChainDimension", None), ("SymmetricLinearDiameterDimension", None), ("OrdinateDimension", None),
    ("HorizontalOrdinateDimension", None), ("VerticalOrdinateDimension", None),
    ("AngularRunningDimension", None), ("PathLengthDimension", None), ("ChamferDimension", None))
# Relations > Quick Snaps
QUICK_SNAPS = (
    ("QSPoint", None), ("QSCenterPoint", None), ("QSMidpoint", None), ("QSQuadrant", None),
    ("QSIntersection", None), SEP, ("QSNearest", None), ("QSTangent", None), ("QSPerpendicular", None),
    ("QSParallel", None), ("QSHV", None), ("QSHVPoint", None), SEP, ("QSLength", None), ("QSGrid", None),
    ("QSAngle", None))
# View > Modify, the parts FreeCAD has a command for
ZOOM_PAN_ROTATE = (("ZoomFit", "Zoom to Fit"), ("ZoomArea", "Zoom to Area"), ("ZoomSelection", "Zoom to Selection"),
                   ("PreviousView", "Previous View"))
DIMENSION_TYPES = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle", "Weight")

LAST = []           # [the menu shown last, its name, its spec], for checks
LONG = set()
                    # chevron until a new document (screen read 2)


def _doc_key():
    try:
        return App.ActiveDocument.Name if App.ActiveDocument is not None else ""
    except Exception:
        return ""


def sticky_long():
    """True when a chevron was opened in this document: menus open in the long form."""
    return _doc_key() in LONG


def reset_long(doc=None):
    """Menus open short again (a new document does this by itself)."""
    if doc is None:
        LONG.clear()
    else:
        LONG.discard(getattr(doc, "Name", doc))
RECENT = collections.deque(maxlen=10)     # command names, newest first (Recent Commands)


def enabled():
    return paths.params().GetBool(PARAM, True)


def shell():
    try:
        from . import shell as shell_module
        return shell_module.shell()
    except Exception as _fw_err:
        _fw_log("rcmenus.py:178", _fw_err)
        return None


def later(fn):
    QtCore.QTimer.singleShot(0, fn)


# --------------------------------------------------------------------------- recent commands
def note_command(name):
    if not name:
        return
    try:
        if name in RECENT:
            RECENT.remove(name)
    except ValueError as _fw_err:
        _fw_log("rcmenus.py:192", _fw_err)
    RECENT.appendleft(name)


def hook_recent(sh=None):
    """Recent Commands: every command viewkeys' Repeat Last Command notes goes on the list too."""
    sh = sh or shell()
    last = getattr(getattr(sh, "viewkeys", None), "last", None)
    if last is None or getattr(last, "_rc_hooked", False):
        return last is not None
    note = last.note

    def note_and_keep(name, _note=note):
        _note(name)
        if getattr(last, "name", None) == name:
            note_command(name)
    last.note = note_and_keep
    last._rc_hooked = True
    return True


def _command_info(name):
    try:
        cmd = Gui.Command.get(name)
        info = cmd.getInfo() if cmd is not None else None
    except Exception:
        return None
    if not info:
        return None
    text = (info.get("menuText") or name).replace("&", "")
    icon = QtGui.QIcon()
    pix = info.get("pixmap") or ""
    if pix:
        try:
            icon = QtGui.QIcon(Gui.getIcon(pix)) if hasattr(Gui, "getIcon") else QtGui.QIcon(pix)
        except Exception:
            icon = QtGui.QIcon()
    return text, icon


def run_command(name):
    try:
        from . import featureflow
        if featureflow.run(name):
            return
    except Exception as _fw_err:
        _fw_log("rcmenus.py:238", _fw_err)
    try:
        Gui.runCommand(name, 0)
    except Exception as error:
        App.Console.PrintError("FreeCAD: %s failed: %s\n" % (name, error))


# --------------------------------------------------------------------------- menu spec
KEYBOARD = [False]     # the menu being built was opened from the keyboard (Shift+F10, the Menu key)


class Item:
    """One row of a menu: an action, a submenu (sub = list of Items), a header or a separator.
    more: shown only in the long form (after »)."""

    def __init__(self, kind, key="", text="", run=None, icon=None, sub=None, enabled=True, checked=None,
                 more=False, tip="", toggle=None, short=False, command=None):
        self.command = command    # the FreeCAD command it runs, when it is one (its key shows beside it)
        self.short = short        # shown only in the short form (the long form has it elsewhere)
        self.toggle = toggle      # a checkable item: called with the new state, also on setChecked
        self.kind, self.key, self.text, self.run, self.icon = kind, key, text, run, icon
        self.sub, self.enabled, self.checked, self.more, self.tip = sub, enabled, checked, more, tip


def action(key, text, run, **kw):
    if key == "SelectOther" and not kw.get("tip"):
        kw["tip"] = T_SELECT_OTHER_TIP
    return Item("action", key, text, run, **kw)


def header(text, key="", more=False):
    return Item("header", key or "Header", text, more=more)


def short_only(item):
    if item is not None:
        item.short = True
    return item


def separator(more=False):
    return Item("sep", more=more)


def submenu(key, text, items, more=False):
    return Item("sub", key, text, sub=[i for i in items if i is not None], more=more)


def dynamic(key, text, fill, more=False):
    """A submenu filled each time it opens: fill(QMenu) (fmmenu's Comment and Save Selection)."""
    return Item("dyn", key, text, run=fill, more=more)


def entry(key, text=None, more=False):
    ""
    sh = shell()
    if sh is None:
        return None
    try:
        e = contextbar._command_entry(sh, key)
    except Exception:
        e = None
    if e is None:
        return None
    try:
        command = sh.binding(key).native
    except Exception:
        command = None
    return Item("action", key, text or e.label, e.run, icon=e.icon, more=more, tip=e.tip, command=command)


def entries(keys, more=False):
    out = []
    for k in keys:
        if k is SEP:
            if out and out[-1].kind != "sep":
                out.append(separator())
            continue
        it = entry(k[0], k[1], more)
        if it is not None:
            out.append(it)
    while out and out[-1].kind == "sep":
        out.pop()
    return out


def hidden(name):
    try:
        from . import fmmenu
        return fmmenu.hidden_entries("RC." + name)
    except Exception:
        return set()


def _flat(items):
    for it in items:
        if it.kind in ("action", "sub", "dyn"):
            yield it


class MenuHeader(QtWidgets.QLabel):
    ""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SWMenuHeader")
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self.setContentsMargins(8, 3, 8, 1)
        # the theme's dimmed text: palette(mid) is near the menu's own colour in Dark (alpha AE3: unreadable)
        colour = "palette(mid)"
        try:
            from . import style
            colour = style.tokens()["text_disabled"]
        except Exception as _fw_err:
            _fw_log("rcmenus.py:header-colour", _fw_err)
        self.setStyleSheet("color: %s;" % colour)


class Builder:
    """Turns a list of Items into a QMenu (kept alive until the next one)."""

    def __init__(self, name, items, long_form=False, row=None, readout=None, chevron=False, line_before_customize=False):
        self.name, self.items, self.row = name, items, row
        self.line_before_customize = line_before_customize
        self.long_form = long_form or sticky_long()
        self.chevron = chevron
        self.readout = readout
        self.keep = []
        self.hidden = hidden(name)

    def build(self, parent=None):
        menu = QtWidgets.QMenu(parent or Gui.getMainWindow())
        menu.setObjectName("SWRightClickMenu")
        menu.setProperty("swRightClickMenu", self.name)
        menu.setProperty("swContextRow", True)   # contextbar adds no row of its own to this one
        menu.setToolTipsVisible(True)
        self.keep = [menu]
        if self.readout:
            w = QtWidgets.QWidgetAction(menu)
            label = QtWidgets.QLabel(self.readout, menu)
            label.setObjectName("SWMenuReadout")
            label.setContentsMargins(8, 1, 8, 1)
            w.setDefaultWidget(label)
            w.setObjectName("SWMenuReadout")
            w.setEnabled(False)
            menu.addAction(w)
            self.keep.append(label)
        has_more = self._fill(menu, self.items, top=True) or self.chevron
        if has_more and not self.long_form:
            more = menu.addAction(CHEVRON)
            more.setObjectName("SWToolMenu_More")
            more.setToolTip("Show all items")
            more.triggered.connect(lambda: later(self._expand))
        else:

            acts = menu.actions()
            if self.line_before_customize and acts and not acts[-1].isSeparator():
                menu.addSeparator()
            custom = menu.addAction(T_CUSTOMIZE)
            custom.setObjectName("SWToolMenu_CustomizeMenu")
            custom.triggered.connect(lambda: later(self.customize))
        self.menu = menu
        menu.setProperty("swLong", bool(self.long_form))
        try:
            from . import rcaccel
            rcaccel.decorate(menu, keyboard=KEYBOARD[0])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: menu keys: %s\n" % error)
        return menu

    def _fill(self, menu, items, top=False):
        has_more = False
        pending_sep = False
        for it in items:
            if it.more and not self.long_form:
                has_more = True
                continue
            if getattr(it, "short", False) and self.long_form:
                continue
            if it.kind in ("action", "sub", "dyn") and it.key in self.hidden and not self.long_form:
                has_more = True
                continue
            if it.kind == "sep":
                pending_sep = bool(menu.actions())
                continue
            if pending_sep:
                menu.addSeparator()
                pending_sep = False
            if it.kind == "header":
                w = QtWidgets.QWidgetAction(menu)
                label = MenuHeader(it.text, menu)
                w.setDefaultWidget(label)
                w.setObjectName("SWMenuHeader_" + it.text)
                w.setText(it.text)          # (not drawn: the label is) for checks that read action texts
                w.setEnabled(False)
                menu.addAction(w)
                self.keep.append(label)
            elif it.kind == "dyn":
                sub = QtWidgets.QMenu(it.text, menu)
                sub.setObjectName("SWToolMenu_" + it.key)
                self.keep.append(sub)

                def fill(sub=sub, fn=it.run):
                    sub.clear()
                    try:
                        fn(sub)
                    except Exception as error:
                        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (sub.title(), error))
                sub.aboutToShow.connect(fill)
                sub.addAction("").setVisible(False)     # Qt shows an empty menu greyed
                menu.addMenu(sub)
                sub.menuAction().setObjectName("SWToolMenu_" + it.key)
            elif it.kind == "sub":
                sub = QtWidgets.QMenu(it.text, menu)
                sub.setObjectName("SWToolMenu_" + it.key)
                sub.setToolTipsVisible(True)
                self.keep.append(sub)
                self._fill(sub, it.sub)
                if sub.isEmpty() and not getattr(it, "keep_empty", False):
                    continue
                menu.addMenu(sub)
                sub.setEnabled(not sub.isEmpty())
                sub.menuAction().setObjectName("SWToolMenu_" + it.key)
            else:
                try:
                    from . import rcextras
                    pic = rcextras.item_icon(it.text) or it.icon
                except Exception:
                    pic = it.icon
                from . import menunoicon
                if menunoicon.none_for(getattr(it, "command", None)):
                    pic = None
                a = menu.addAction(pic or QtGui.QIcon(), it.text)
                a.setObjectName("SWToolMenu_" + it.key)
                if it.tip:
                    a.setToolTip(it.tip)
                if it.checked is not None:
                    a.setCheckable(True)
                    a.setChecked(bool(it.checked))
                a.setEnabled(bool(it.enabled))
                if getattr(it, "command", None):
                    a.setProperty("swCommand", it.command)
                if it.toggle is not None:
                    a.toggled.connect(it.toggle)
                elif it.run is not None:
                    a.triggered.connect(lambda _c=False, run=it.run: later(run))
        return has_more

    def _expand(self):
        LONG.add(_doc_key())
        pos = self.pos if getattr(self, "pos", None) is not None else QtGui.QCursor.pos()
        b = Builder(self.name, self.items, long_form=True, row=self.row, readout=self.readout, chevron=self.chevron)
        show(b, pos)

    def customize(self):
        try:
            from . import fmmenu
        except Exception:
            return
        rows = [(it.key, it.text) for it in _flat(self.items)]
        box = fmmenu.CustomizeDialog("RC." + self.name, rows)
        fmmenu._run_dialog(box, lambda b: b.apply())


def show(builder, pos):
    """Pops the menu up at pos (its top left), the context toolbar row above it."""
    old = LAST[0] if LAST else None
    if old is not None and alive(old):
        try:
            old.close()
        except RuntimeError as _fw_err:
            _fw_log("rcmenus.py:494", _fw_err)
    menu = builder.build()
    menu.setProperty("fwSplineEntries", True)   # our sketch menus place the spline entries themselves
    builder.pos = pos
    LAST[:] = [menu, builder.name, builder]
    menu.popup(pos)
    from . import rcextras as _rx
    if builder.row and _rx.rows_in_menus():
        try:
            if isinstance(builder.row, tuple):
                from . import rcextras
                rcextras.add_rows(menu, *builder.row)
            else:
                bar = getattr(shell(), "context", None)
                if bar is not None:
                    bar.add_row(menu, builder.row)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: right-click toolbar: %s\n" % error)
    _audit(builder.name, menu)
    return menu


def _audit(name, menu):
    """Checks only (FW_RC_AUDIT = a file): every greyed item of the menu and its icon rows, one JSON line."""
    import os
    path = os.environ.get("FW_RC_AUDIT")
    if not path:
        return
    try:
        import json
        grey = []

        def walk(m, where):
            for a in m.actions():
                if a.isSeparator() or not a.isVisible():
                    continue
                if a.menu() is not None:
                    walk(a.menu(), where + [a.text()])
                elif not a.isEnabled() and a.text() and not isinstance(a, QtWidgets.QWidgetAction):
                    grey.append(" > ".join(where + [a.text()]))
        walk(menu, [])
        for b in menu.findChildren(QtWidgets.QAbstractButton):
            if not b.isEnabled():
                grey.append("[row] " + (b.toolTip().split("\n")[0] or b.objectName() or b.text()))
        with open(path, "a") as f:
            f.write(json.dumps({"menu": name, "grey": grey}) + "\n")
    except Exception as _fw_err:
        _fw_log("rcmenus.py:540", _fw_err)


# --------------------------------------------------------------------------- shared pieces
def sketch_entities_menu(more=False):
    return submenu("SketchEntities", T_ENTITIES, entries(SKETCH_ENTITIES), more)


CONSTRUCTION_KEYS = ("ConstructionPlane", "RelConstruction", "ConstructionGeometry")


def _has_sketch_pick():
    try:
        selections = Gui.Selection.getSelectionEx("", 0)
    except Exception:
        return False
    for s in selections:
        for sub in s.SubElementNames or ():
            leaf = sub.split(".")[-1]
            if leaf.startswith(("Edge", "ExternalEdge")):
                return True
            if not leaf.startswith("Vertex"):
                continue
            try:
                gi, _pos = s.Object.getGeoVertexIndex(int(leaf[6:]) - 1)
                if gi >= 0 and s.Object.Geometry[gi].TypeId == "Part::GeomPoint":
                    return True
            except Exception as _fw_err:
                _fw_log("rcmenus.py:568", _fw_err)
    return False


def sketch_tools_menu(more=False):
    items = entries(SKETCH_TOOLS)
    for it in items:
        if it.key in CONSTRUCTION_KEYS:
            it.enabled = _has_sketch_pick()     # it turns the picked entities to construction
    items = [it for it in items if it.kind != "action" or it.enabled]   # none picked: left out, not greyed (pkg218)
    return submenu("SketchTools", T_TOOLS, items, more)


def more_dimensions_menu(more=False):
    return submenu("MoreDimensions", T_MORE_DIMS, entries(MORE_DIMENSIONS), more)


def quick_snaps_menu(more=False):
    return submenu("QuickSnaps", T_QUICK_SNAPS, entries(QUICK_SNAPS), more)


def zoom_menu(more=False):
    items = entries(ZOOM_PAN_ROTATE)
    for it in items:
        if it.key == "ZoomSelection" and editing_sketch() is not None:
            it.run = zoom_to_selection         # FreeCAD's Fit Selection does nothing on sketch geometry
            it.enabled = bool(Gui.Selection.getSelectionEx("", 0))
    items = [it for it in items if it.kind != "action" or it.enabled]   # nothing picked: no greyed Zoom to Selection (pkg218)
    return submenu("ZoomPanRotate", T_ZOOM, items, more)


def editing_sketch():
    """The sketch open for editing, or None."""
    try:
        gd = Gui.ActiveDocument
        obj = gd.getInEdit().Object if gd is not None and gd.getInEdit() is not None else None
    except Exception as _fw_err:
        _fw_log("rcmenus.py:605", _fw_err)
        return None
    return obj if obj is not None and obj.TypeId == "Sketcher::SketchObject" else None


def _sketch_pick_box(sketch):
    """The global bounding box of the sketch elements picked now (Edge/ExternalEdge/Vertex in edit)."""
    box = App.BoundBox()
    pl = sketch.getGlobalPlacement()
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in s.SubElementNames:
            leaf = sub.split(".")[-1]
            pts = []
            try:
                if leaf.startswith("Edge"):
                    g = sketch.Geometry[int(leaf[4:]) - 1]
                    sh = g.toShape()
                    bb = sh.BoundBox
                    pts = [App.Vector(bb.XMin, bb.YMin, bb.ZMin), App.Vector(bb.XMax, bb.YMax, bb.ZMax)]
                elif leaf.startswith("ExternalEdge"):
                    i = int(leaf[12:]) - 1
                    bb = sketch.ExternalGeo[i + 2].toShape().BoundBox
                    pts = [App.Vector(bb.XMin, bb.YMin, bb.ZMin), App.Vector(bb.XMax, bb.YMax, bb.ZMax)]
                elif leaf.startswith("Vertex"):
                    gi, pi = sketch.getGeoVertexIndex(int(leaf[6:]) - 1)
                    pts = [sketch.getPoint(gi, pi)]
                elif leaf.startswith("Constraint"):

                    # constraint rows have no box, so Zoom to Selection did nothing on them)
                    c = sketch.Constraints[int(leaf[10:]) - 1]
                    for gi, pi in ((c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos)):
                        if gi is None or gi < 0 or gi >= len(sketch.Geometry):
                            continue
                        if pi:
                            pts.append(sketch.getPoint(gi, pi))
                        else:
                            bb = sketch.Geometry[gi].toShape().BoundBox
                            pts += [App.Vector(bb.XMin, bb.YMin, bb.ZMin), App.Vector(bb.XMax, bb.YMax, bb.ZMax)]
            except Exception:
                pts = []
            for p in pts:
                box.add(pl.multVec(p))
    return box if box.isValid() else None


def _mate_box(obj):
    ""
    try:
        from . import asmcore as ac, asmisolate
        asm = ac.assembly_of(obj.Document)
        if asm is None or obj not in ac.mates(asm):
            return None
        import Part
        box = App.BoundBox()
        for c in asmisolate._mated(asm, obj):
            shape = Part.getShape(c)
            if shape is not None and not shape.isNull():
                box.add(shape.BoundBox)
        return box if box.isValid() else None
    except Exception as _fw_err:
        _fw_log("rcmenus.py:mate_box", _fw_err)
        return None


def _model_pick_box():
    ""

    box = App.BoundBox()
    elements = False
    for e in Gui.Selection.getSelectionEx("", 0):
        mate_box = _mate_box(e.Object)
        if mate_box is not None:
            box.add(mate_box)
            elements = True
            continue
        for sub in e.SubElementNames or ():
            name = sub.split(".")[-1]
            if not name or not name.rstrip("0123456789") in ("Face", "Edge", "Vertex"):
                continue
            try:
                import Part
                shape = Part.getShape(e.Object, sub, needSubElement=True)
                if shape is not None and not shape.isNull():
                    box.add(shape.BoundBox)
                    elements = True
            except Exception as _fw_err:
                _fw_log("rcmenus.py:664", _fw_err)
    return box if elements and box.isValid() else None


class ZoomToSelectionCommand:
    def GetResources(self):
        return {"MenuText": "Zoom to Selection", "ToolTip": "Zooms to the picked faces, edges or items",
                "Pixmap": "zoom-selection", "CmdType": "ForEdit"}

    def IsActive(self):
        return Gui.ActiveDocument is not None      # as FreeCAD's Fit Selection (menus grey it themselves)

    def Activated(self):
        zoom_to_selection()


def _eased_zoom(box):
    ""
    try:
        from . import camanim
        if box is None:
            return camanim.animate_command("Std_ViewFitSelection")

        def fit(view):
            from pivy import coin
            cam = view.getCameraNode()
            pad = max(box.DiagonalLength * 0.15, 1.0)
            vb = coin.SbBox3f(box.XMin - pad, box.YMin - pad, box.ZMin - pad, box.XMax + pad, box.YMax + pad, box.ZMax + pad)
            vp = view.getViewer().getSoRenderManager().getViewportRegion()
            cam.viewBoundingBox(vb, vp.getViewportAspectRatio(), 1.0)
        return camanim.animate_change(fit)
    except Exception as _fw_err:
        App.Console.PrintLog("zoom to selection, eased: %s\n" % _fw_err)
        return False


def zoom_to_selection():
    ""

    sketch = editing_sketch()
    box = _sketch_pick_box(sketch) if sketch is not None else _model_pick_box()
    if _eased_zoom(box):
        return
    if box is None:
        Gui.runCommand("Std_ViewFitSelection", 0)
        return
    try:
        from pivy import coin
        view = Gui.ActiveDocument.ActiveView
        cam = view.getCameraNode()
        pad = max(box.DiagonalLength * 0.15, 1.0)
        vb = coin.SbBox3f(box.XMin - pad, box.YMin - pad, box.ZMin - pad, box.XMax + pad, box.YMax + pad, box.ZMax + pad)
        vp = view.getViewer().getSoRenderManager().getViewportRegion()
        cam.viewBoundingBox(vb, vp.getViewportAspectRatio(), 1.0)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: zoom to selection: %s\n" % error)
        Gui.runCommand("Std_ViewFitSelection", 0)


def selection_tools_menu(more=False):
    items = []
    try:
        from . import boxselect
        for kind in ("Box", "Lasso"):
            items.append(action(kind + "Selection", "%s Selection" % kind,
                                lambda k=kind: boxselect.set_bulk(k), checked=boxselect.bulk() == kind))
    except Exception as _fw_err:
        _fw_log("rcmenus.py:709", _fw_err)
    items += entries((("SelectAll", "Select All"), ("InvertSelection", "Invert Selection")))
    return submenu("SelectionTools", T_SELECTION_TOOLS, items, more)


def recent_menu(more=False):
    items = []
    for name in list(RECENT):
        info = _command_info(name)
        if info is None:
            continue
        try:
            if not Gui.Command.get(name).isActive():
                continue
        except Exception:
            continue
        items.append(action("Recent_" + name, info[0], lambda n=name: run_command(n), icon=info[1]))

    # command has run (an empty submenu is left out by _clean)
    return submenu("RecentCommands", T_RECENT, items, more)


def box_lasso_select(select_run):
    ""
    out = []
    try:
        from . import boxselect
        for kind in ("Box", "Lasso"):
            out.append(action(kind + "Select", "%s Selection" % kind,
                              lambda k=kind: _bulk_and_select(boxselect, k, select_run)))
    except Exception as _fw_err:
        _fw_log("rcmenus.py:740", _fw_err)
    out.append(action("Select", T_SELECT, select_run))
    return out


def _bulk_and_select(boxselect, kind, select_run):
    boxselect.set_bulk(kind)
    select_run()


def clear_selections():
    try:
        Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("rcmenus.py:754", _fw_err)


def picks():
    try:
        return [(s.DocumentName, s.ObjectName, sub) for s in Gui.Selection.getSelectionEx("", 0)
                for sub in (tuple(s.SubElementNames) or ("",))]
    except Exception:
        return []


def run_key(key):
    sh = shell()
    if sh is not None:
        try:
            contextbar.run_key(sh, key)
            return
        except Exception as _fw_err:
            _fw_log("rcmenus.py:772", _fw_err)


def exit_sketch():
    run_key("ExitSketch")


# --------------------------------------------------------------------------- sketch helpers
def _sketch_element(sketch, sub):
    try:
        from . import relationspm
        element = relationspm.sketch_element(App.getDocument(sub[0]).getObject(sub[1]), sub[2], sketch)
    except Exception:
        return None
    # a pick made through the pointer is kept by FreeCAD 1.1 as 'Sketch.;g1.edge1' (lower-case old-style name):
    # the same Edge1 (real-click pass 11-21: two picked lines lost their pair relations in the icon row)
    if element and element[:1].islower():
        head = element.rstrip("0123456789")
        if head in ("edge", "vertex", "constraint") and element[len(head):].isdigit():
            element = head.capitalize() + element[len(head):]
    return element


def under_pointer(sketch, at=None):
    """(doc, object, element path, element) under the pointer or at inside sketch, else None."""
    if at is not None:
        view = _view()
        try:
            where = (at.x(), at.y()) if hasattr(at, "x") else at
            info = view.getObjectInfo(where) if view is not None else None
        except Exception:
            info = None
        if info and info.get("Object"):
            item = (info.get("Document"), info.get("Object"), info.get("Component", "") or "")
            element = _sketch_element(sketch, item)
            return item + (element,) if element else None
        for item in picks():
            element = _sketch_element(sketch, item)
            if element:
                return item + (element,)
        return None
    try:
        pre = Gui.Selection.getPreselection()
    except Exception:
        return None
    if pre is None or not getattr(pre, "ObjectName", ""):
        return None
    subs = tuple(pre.SubElementNames)
    if not subs:
        return None
    item = (pre.DocumentName, pre.ObjectName, subs[0])
    element = _sketch_element(sketch, item)
    if not element:
        return None
    return item + (element,)


def pick_under(item, sketch=None):
    ""



    if item is None:
        return
    doc, name, sub = item[:3]
    element = str(item[3]).lower() if sketch is not None and len(item) > 3 and item[3] else None
    for p in picks():
        if p[:3] == (doc, name, sub):
            return
        if element and str(_sketch_element(sketch, p) or "").lower() == element:
            return
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc, name, sub)
    except Exception as _fw_err:
        _fw_log("rcmenus.py:834", _fw_err)


def picked_elements(sketch):
    out = []
    for p in picks():
        e = _sketch_element(sketch, p)
        if e:
            out.append(e)
    return out


def element_name(sketch, element):
    ""
    try:
        from . import relationspm
        if element.startswith("Edge"):
            return relationspm._entity_names(sketch.Geometry)[int(element[4:]) - 1]
        if element.startswith("Vertex"):
            return "Point%d" % int(element[6:])
    except Exception as _fw_err:
        _fw_log("rcmenus.py:855", _fw_err)
    if element.startswith("Constraint"):
        return dimension_name(sketch, int(element[10:]) - 1)
    return element


def dimension_name(sketch, index):
    n = 0
    for i, c in enumerate(sketch.Constraints):
        if c.Type in DIMENSION_TYPES:
            n += 1
        if i == index:
            return "D%d@%s" % (n, sketch.Label)
    return "D@%s" % sketch.Label


def constraint_index(element):
    try:
        return int(element[10:]) - 1 if element.startswith("Constraint") else None
    except ValueError:
        return None


def _sketch_transaction(sketch, name, body):
    doc = sketch.Document
    doc.openTransaction(name)
    try:
        body()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (name, error))
        return
    doc.commitTransaction()
    try:
        sketch.solve()
        sketch.recompute()
    except Exception as _fw_err:
        _fw_log("rcmenus.py:892", _fw_err)


def toggle_driven(sketch, index):
    _sketch_transaction(sketch, "Driven", lambda: sketch.setDriving(index, not sketch.getDriving(index)))


def toggle_suppression(sketch, indices):
    def body():
        for i in indices:
            sketch.setActive(i, not sketch.getActive(i))
    _sketch_transaction(sketch, T_TOGGLE_SUPPRESSION, body)


def hide_dimension(sketch, index):
    _sketch_transaction(sketch, "Hide", lambda: sketch.setVirtualSpace(index, True))


def radius_diameter(sketch, index):
    """Display As Diameter / Display As Radius: the same circle size as the other kind of dimension."""
    import Sketcher
    c = sketch.Constraints[index]
    kind = "Diameter" if c.Type == "Radius" else "Radius"
    value = c.Value * 2.0 if kind == "Diameter" else c.Value / 2.0
    name, driving = c.Name, sketch.getDriving(index)

    def body():
        sketch.delConstraint(index)
        new = sketch.addConstraint(Sketcher.Constraint(kind, c.First, value))
        if name:
            sketch.renameConstraint(new, name)
        if not driving:
            sketch.setDriving(new, False)
    _sketch_transaction(sketch, T_AS_DIAMETER if kind == "Diameter" else T_AS_RADIUS, body)


def grid_shown(sketch):
    try:
        return bool(sketch.ViewObject.ShowGrid)
    except Exception:
        return None


def toggle_grid(sketch):
    try:
        sketch.ViewObject.ShowGrid = not sketch.ViewObject.ShowGrid
    except Exception as _fw_err:
        _fw_log("rcmenus.py:939", _fw_err)


def _end_points(geo):
    try:
        return [geo.StartPoint, geo.EndPoint]
    except Exception:
        return []


def chain_of(sketch, index):
    ""
    geos = sketch.Geometry
    tol = 1e-6
    ends = [_end_points(g) for g in geos]

    def construction(i):
        try:
            return bool(sketch.getConstruction(i))
        except Exception:
            return False
    own = construction(index)
    chain, todo = {index}, [index]
    while todo:
        i = todo.pop()
        for p in ends[i]:
            for j, pts in enumerate(ends):
                if j in chain or construction(j) != own:
                    continue
                if any((p - q).Length < tol for q in pts):
                    chain.add(j)
                    todo.append(j)
    return sorted(chain)


def select_chain(item, sketch, index):
    doc, name, sub = item[:3]
    prefix = sub[:len(sub) - len("Edge%d" % (index + 1))]
    for j in chain_of(sketch, index):
        try:
            Gui.Selection.addSelection(doc, name, "%sEdge%d" % (prefix, j + 1))
        except Exception as _fw_err:
            _fw_log("rcmenus.py:981", _fw_err)


# --------------------------------------------------------------------------- Select Midpoint
def _has_midpoint(sketch, index):
    try:
        return type(sketch.Geometry[index]).__name__ == "LineSegment"
    except Exception:
        return False


def _midpoint(geo):
    a, b = geo.FirstParameter, geo.LastParameter
    return geo.value((a + b) / 2.0)


def select_midpoint(item, sketch, index):
    ""


    import Part
    import Sketcher
    geo = sketch.Geometry[index]
    mid = _midpoint(geo)
    found = None
    for c in sketch.Constraints:
        if c.Type == "Symmetric" and c.First == index and c.FirstPos == 1 and c.Second == index \
                and c.SecondPos == 2 and c.Third >= 0 and c.ThirdPos == 1:
            found = c.Third
        elif c.Type == "PointOnObject" and c.Second == index and c.First >= 0 \
                and type(sketch.Geometry[c.First]).__name__ == "Point" \
                and (sketch.Geometry[c.First].X - mid.x) ** 2 + (sketch.Geometry[c.First].Y - mid.y) ** 2 < 1e-12:
            found = c.First
    if found is None:
        made = []

        def body():
            g = sketch.addGeometry(Part.Point(mid), True)
            sketch.addConstraint(Sketcher.Constraint("Symmetric", index, 1, index, 2, g, 1))
            made.append(g)
        _sketch_transaction(sketch, T_SELECT_MIDPOINT, body)
        if not made:
            return
        found = made[0]
    vertex = _vertex_of(sketch, found, 1)
    if vertex is None:
        return
    doc, name, sub = item[:3]
    prefix = sub[:len(sub) - len("Edge%d" % (index + 1))]
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc, name, "%sVertex%d" % (prefix, vertex + 1))
    except Exception as _fw_err:
        _fw_log("rcmenus.py:1034", _fw_err)



# Up To Vertex). FreeCAD has no such element, so the edge is picked at its middle and remembered here:
# midpoint_pick(doc, obj, sub) gives the point while that edge stays picked from Select Midpoint.
MIDPOINTS = {}


def _edge_midpoint(doc, name, sub):
    """The middle of a model edge, in global coordinates (through links and assembly placements)."""
    try:
        import Part
        obj = App.getDocument(doc).getObject(name)
        edge = Part.getShape(obj, sub, needSubElement=True)
        if edge is None or edge.isNull() or edge.ShapeType != "Edge":
            return None
        return edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
    except Exception as _fw_err:
        _fw_log("rcmenus.py:edge-midpoint", _fw_err)
        return None


def _is_picked(doc, name, sub):
    try:
        return any(s.DocumentName == doc and s.ObjectName == name and sub in s.SubElementNames
                   for s in Gui.Selection.getSelectionEx("", 0))
    except Exception:
        return False


def midpoint_pick(doc, obj, sub):
    """The global midpoint when this edge pick came from Select Midpoint (and is still picked), else None."""
    p = MIDPOINTS.get((doc, obj, sub))
    if p is None:
        return None
    if not _is_picked(doc, obj, sub):
        MIDPOINTS.pop((doc, obj, sub), None)
        return None
    return App.Vector(p)


class _MidpointWatch:
    """A later ordinary click on the same edge (picked at another spot) is an edge pick again."""

    def addSelection(self, doc, obj, sub, pnt):
        p = MIDPOINTS.get((doc, obj, sub))
        if p is not None and pnt and (App.Vector(*pnt) - p).Length > 1e-4:
            MIDPOINTS.pop((doc, obj, sub), None)


_MID_WATCH = []


def select_edge_midpoint(item):
    ""


    doc, name, sub = item[:3]
    p = _edge_midpoint(doc, name, sub)
    if p is None:
        found = _resolve_edge(doc, name, sub)
        if found is None:
            return
        try:
            edge = found[2].Edges[found[1] - 1]
            p = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1048", _fw_err)
            return
    for key in [k for k in MIDPOINTS if not _is_picked(*k)]:
        MIDPOINTS.pop(key, None)
    MIDPOINTS[(doc, name, sub)] = App.Vector(p)
    if not _MID_WATCH:
        _MID_WATCH.append(_MidpointWatch())
        try:
            Gui.Selection.addObserver(_MID_WATCH[0])
        except Exception as _fw_err:
            _fw_log("rcmenus.py:midpoint-watch", _fw_err)
    try:
        if _is_picked(doc, name, sub):
            Gui.Selection.removeSelection(doc, name, sub)   # picked again, so a PropertyManager hears the point
        Gui.Selection.addSelection(doc, name, sub, p.x, p.y, p.z)
    except Exception as _fw_err:
        _fw_log("rcmenus.py:1048", _fw_err)
    try:
        Gui.getMainWindow().statusBar().showMessage(
            "Midpoint of %s (%.2f, %.2f, %.2f)" % (sub.split(".")[-1], p.x, p.y, p.z), 6000)
    except Exception as _fw_err:
        _fw_log("rcmenus.py:midpoint-status", _fw_err)


def _vertex_of(sketch, geo, pos):
    for v in range(100000):
        try:
            g, p = sketch.getGeoVertexIndex(v)
        except Exception:
            return None
        if g == -2000:
            return None
        if g == geo and int(p) == pos:
            return v
    return None


# --------------------------------------------------------------------------- Contour Select Tool
class ContourSelect(QtCore.QObject):
    ""


    def __init__(self, sketch, widget):
        super().__init__(widget)
        self.sketch, self.widget = sketch, widget
        widget.installEventFilter(self)
        try:
            Gui.getMainWindow().statusBar().showMessage("Click inside a closed contour to select it.", 5000)
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1076", _fw_err)

    def end(self):
        if alive(self.widget):
            self.widget.removeEventFilter(self)
        if _contour[:1] == [self]:
            _contour[:] = []

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.end()
            return True
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            self.end()
            return True
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            p = event.position()
            self.pick(p.x(), p.y())
            self.end()
            return True
        return False

    def pick(self, x, y):
        view = _view()
        if view is None:
            return
        try:
            dpr = self.widget.devicePixelRatioF()
            point = view.getPoint(int(x * dpr), int((self.widget.height() - y) * dpr))
        except Exception:
            return
        edges = contour_at(self.sketch, point)
        doc = self.sketch.Document.Name
        Gui.Selection.clearSelection()
        for i in edges:
            try:
                Gui.Selection.addSelection(doc, self.sketch.Name, "Edge%d" % (i + 1))
            except Exception as _fw_err:
                _fw_log("rcmenus.py:1119", _fw_err)


_contour = []


def contour_at(sketch, global_point):
    """Geometry indices of the smallest closed contour of sketch around global_point."""
    import Part
    try:
        local = sketch.getGlobalPlacement().inverse().multVec(global_point)
    except Exception:
        local = global_point
    own = []
    for i, g in enumerate(sketch.Geometry):
        try:
            if sketch.getConstruction(i) or type(g).__name__ == "Point":
                continue
            own.append((i, g.toShape()))
        except Exception:
            continue
    if not own:
        return []
    best = None
    for edges in Part.sortEdges([e for _, e in own]):
        try:
            wire = Part.Wire(edges)
            if not wire.isClosed():
                continue
            face = Part.Face(wire)
            if not face.isInside(App.Vector(local.x, local.y, 0), 1e-7, True):
                continue
        except Exception:
            continue
        if best is None or face.Area < best[0]:
            best = (face.Area, edges)
    if best is None:
        return []
    out = []
    for i, shape in own:
        if any(shape.isSame(e) or (abs(shape.Length - e.Length) < 1e-9 and shape.CenterOfMass.distanceToPoint(e.CenterOfMass) < 1e-9)
               for e in best[1]):
            out.append(i)
    return out


def contour_select_tool(sketch):
    for old in _contour:
        old.end()
    sh = shell()
    view = sh.view_widget() if sh is not None else None
    if view is None:
        return None
    widget = view.viewport() if hasattr(view, "viewport") else view
    _contour[:] = [ContourSelect(sketch, widget)]
    return _contour[0]


# --------------------------------------------------------------------------- Mark For Drawing
MARK_PROP = "FWNotForDrawing"


def _mark_key(sketch, index):
    c = sketch.Constraints[index]
    return c.Name or "#%d" % index


KEPT_PROPS = (MARK_PROP, "FWDimDisplay", "FWAnnotationView")   # right-click choices kept per dimension


def stable_key(sketch, index):
    ""



    c = sketch.Constraints[index]
    if c.Name:
        return c.Name
    try:
        from . import configtable
        sw = [(i, s) for i, s, _n in configtable.dimension_names(sketch)]
    except Exception:
        sw = []
    wanted = next((s for i, s in sw if i == index), None) or "D%d" % (len(sw) + 1)
    taken = {k.Name for k in sketch.Constraints if k.Name} | {s for i, s in sw if i != index}
    name, k = wanted, 1
    while name in taken:
        k += 1
        name = "%s_%d" % (wanted, k)
    sketch.renameConstraint(index, name)
    old = "#%d" % index
    for prop in KEPT_PROPS:
        values = list(getattr(sketch, prop, []) or [])
        moved = [name + v[len(old):] if v == old or v.startswith(old + ":") else v for v in values]
        if moved != values:
            setattr(sketch, prop, moved)
    return name


def marked_for_drawing(sketch, index):
    ""
    return _mark_key(sketch, index) not in list(getattr(sketch, MARK_PROP, []) or [])


def toggle_mark_for_drawing(sketch, index):
    def body():
        key = stable_key(sketch, index)
        if not hasattr(sketch, MARK_PROP):
            sketch.addProperty("App::PropertyStringList", MARK_PROP, "FreeCAD",
                               "Dimensions not marked for drawing")
            try:
                sketch.setEditorMode(MARK_PROP, 2)
            except Exception as _fw_err:
                _fw_log("rcmenus.py:1201", _fw_err)
        now = list(getattr(sketch, MARK_PROP) or [])
        setattr(sketch, MARK_PROP, [k for k in now if k != key] if key in now else now + [key])
    _sketch_transaction(sketch, T_MARK_FOR_DRAWING, body)


def _delete():
    try:
        Gui.runCommand("Std_Delete", 0)
    except Exception as _fw_err:
        _fw_log("rcmenus.py:1211", _fw_err)


def _display_delete():
    run_key("Relations")


def relations_head(more_rs=True):
    """The Relations heading with Display/Delete Relations... and Fully Define Sketch..."""
    out = [header(T_RELATIONS, "HeaderRelations"),
           entry("Relations", T_DISPLAY_DELETE),
           entry("FullyDefineSketch", T_FULLY_DEFINE)]
    if _has_dangling():

        out.append(entry("RepairDanglingRelations", "Repair Dangling Relations"))
    return out


def _has_dangling():
    try:
        from . import relationspm
        fn = getattr(relationspm, "_missing_externals", None)
        sketch = contextbar.sketch_in_edit()
        return bool(fn is not None and sketch is not None and fn(sketch))
    except Exception:
        return False


def _rs_options(more=True):
    from . import rcextras
    return rcextras.relations_snaps_item(more)


def sketch_rows(sketch, element=None, tool=None):
    ""
    try:
        from . import rcextras
        kind = rcextras.row_kind(sketch, element, tool)
        rows = rcextras.row_entries(sketch, kind, tool)
        if tool is None and hasattr(rcextras, "pick_rows"):
            rows = rcextras.pick_rows(sketch, element, rows)
        return rows
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: right-click icon row: %s\n" % error)
        return None


def sketch_row(sketch):
    """Kept for older callers: the second line of the icon row."""
    rows = sketch_rows(sketch)
    return list(rows[0]) + list(rows[1]) if rows else []


# --------------------------------------------------------------------------- menus in a sketch
def tool_menu(tool, pos=None):
    ""

    if not enabled():
        return False
    sh = shell()
    if sh is None or not getattr(sh, "enabled", True):
        return False
    pos = pos or QtGui.QCursor.pos()
    sketch = contextbar.sketch_in_edit() or getattr(tool, "sketch", None)
    try:
        if tool is not None and hasattr(tool, "_close_numeric_input"):
            tool._close_numeric_input()
    except Exception as _fw_err:
        _fw_log("rcmenus.py:1276", _fw_err)
    title = ""
    try:
        title = tool.title() if tool is not None else ""
    except Exception:
        title = ""
    if "Spline" in title and not _spline_menu_wanted(tool):
        return False        # Insert Spline Point and older spline tools keep their own right-click
    name, items = tool_items(tool, sketch, title)
    show(Builder(name, items, row=sketch_rows(sketch, None, tool), readout=_readout(tool)), pos)
    return True


def _readout(tool):
    ""
    if not _in_chain(tool):
        return None
    try:
        a, b = tool.start, tool.end_point
        if a is None or b is None:
            return None
        from . import rcextras
        return rcextras.length_text(math.hypot(b[0] - a[0], b[1] - a[1]))
    except Exception:
        return None


def _spline_menu_wanted(tool):
    ""

    try:
        return bool(getattr(tool, "WANTS_CONTEXT_MENU", False))
    except Exception:
        return False


def tool_items(tool, sketch, title=None, trimming=False):
    """(menu name, items) for a running tool (None: FreeCAD's own tool; trimming: FreeCAD's Trim)."""
    if title is None:
        try:
            title = tool.title() if tool is not None else ""
        except Exception:
            title = ""
    end = (lambda t=tool: _end_tool(t))
    if trimming or title.startswith("Trim"):
        return "SketchTrim", trim_items(end)
    if title == "Smart Dimension" or "Dimension" in title:
        return "SketchDimensionTool", dimension_tool_items(tool, sketch, end)
    return "SketchTool", drawing_tool_items(tool, sketch, end)


def _end_tool(tool):
    if tool is None:
        # FreeCAD's own tool: one Esc ends it (the second would leave the sketch)
        sh = shell()
        view = sh.view_widget() if sh is not None else None
        if view is not None:
            w = view.viewport() if hasattr(view, "viewport") else view
            for t in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(w, QtGui.QKeyEvent(t, Qt.Key_Escape, Qt.NoModifier))
        return
    try:
        tool.end()
    except Exception as _fw_err:
        _fw_log("rcmenus.py:1340", _fw_err)


def _in_chain(tool):
    try:
        return hasattr(tool, "_end_chain") and tool.state == tool.SECOND
    except Exception:
        return False


def _drawing(tool):
    """A point of the entity is placed (the tool is past its first click)."""
    if tool is None:
        return False
    if _in_chain(tool):
        return True
    try:
        return not tool.is_first_state()
    except Exception:
        return False


def drawing_tool_items(tool, sketch, end):
    ""



    items = [action("Select", T_SELECT, end)]
    if _in_chain(tool):
        items.append(action("EndChain", T_END_CHAIN, tool._end_chain))
        try:
            arc = tool.segment == getattr(tool, "ARC", "arc")
            can = tool.previous_curve != -1
        except Exception:
            arc, can = False, False
        if can:     # pkg259: on the first segment there is no end to turn an arc from: left out, not greyed
            items.append(action("SwitchToArc", T_TO_LINE if arc else T_TO_ARC, lambda: tool.on_key(Qt.Key_A)))
    items += [sketch_entities_menu(), recent_menu(), more_dimensions_menu()]
    p = picked_elements(sketch) if sketch is not None else []
    if p or _drawing(tool):
        items.append(header(T_SELECTED_N if len(p) > 1 else T_SELECTED, "HeaderSelected"))
    if p:
        from . import rcextras
        items.append(action("Delete", T_DELETE, _delete, icon=_std_icon("Std_Delete")))
        items.append(action("Properties", rcextras.T_PROPERTIES, lambda: rcextras.properties(tool, sketch), more=True))
    items += [_rs_options(), quick_snaps_menu()]
    return [i for i in items if i is not None]


def trim_items(end):
    """Trim Entities (screen read 10): Box Selection, Lasso Selection, Select, the two construction
    check boxes, Extend Entities, Redraw, Sketch Entities >, More Dimensions >, Customize Menu."""
    from . import nativepms
    keep, ignore = nativepms.trim_options()
    items = box_lasso_select(end) + [
        separator(),
        action("TrimKeepConstruction", "Keep trimmed entities as construction geometry", None, checked=keep,
               toggle=lambda on: nativepms.set_trim_options(on, nativepms.trim_options()[1])),
        action("TrimIgnoreConstruction", "Ignore trimming of construction geometry", None, checked=ignore,
               toggle=lambda on: nativepms.set_trim_options(nativepms.trim_options()[0], on)),
        separator(), entry("Extend", "Extend Entities"), entry("Redraw"),
        separator(), sketch_entities_menu(), more_dimensions_menu()]
    return [i for i in items if i is not None]


def dimension_tool_items(tool, sketch, end):
    """Smart Dimension running (screen read 9): Box Selection, Lasso Selection, Select, More
    Dimensions >, Sketch Entities >, Redraw, Clear Selections, Customize Menu (Display As Diameter
    too with a radius or diameter picked)."""
    items = box_lasso_select(end) + [more_dimensions_menu(), sketch_entities_menu(), entry("Redraw")]
    items += _radius_items(sketch)
    try:
        mid = tool is not None and not tool.is_first_state()
    except Exception:
        mid = False

    def clear(tool=tool):
        try:
            if tool is not None and not tool.is_first_state():
                tool.cancel_current()
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1421", _fw_err)
        clear_selections()
    if mid or picks():      # pkg259: nothing picked, nothing to clear: left out, not greyed (no dead controls)
        items.append(action("ClearSelections", T_CLEAR, clear))
    return [i for i in items if i is not None]


def _radius_items(sketch):
    if sketch is None:
        return []
    for e in picked_elements(sketch):
        i = constraint_index(e)
        if i is not None and 0 <= i < len(sketch.Constraints) and sketch.Constraints[i].Type in ("Radius", "Diameter"):
            text = T_AS_DIAMETER if sketch.Constraints[i].Type == "Radius" else T_AS_RADIUS
            return [action("DisplayAsDiameter", text, lambda i=i: radius_diameter(sketch, i))]
    return []


def _grid_item(sketch, more=False):
    on = grid_shown(sketch) if sketch is not None else None
    if on is None:
        return None
    return action("DisplayGrid", T_DISPLAY_GRID, lambda: toggle_grid(sketch), checked=on, more=more)


def _std_icon(name):
    try:
        return QtGui.QIcon(Gui.getIcon(Gui.Command.get(name).getInfo()["pixmap"]))
    except Exception:
        return None


def sketch_menu(sketch, item, pos=None):
    """No tool running: the menu for what is under the pointer (item from under_pointer)."""
    pos = pos or QtGui.QCursor.pos()
    name, items, row = sketch_items(sketch, item)
    show(Builder(name, items, row=row), pos)
    return True


def sketch_items(sketch, item):
    """(menu name, items, icon row) with no tool running; item under the pointer is picked."""
    element = None
    hit = _model_hit(sketch) if item is None else None
    if hit is not None:

        items = sketch_model_items(sketch, hit)
        name = "SketchModelEdge" if hit[2].split(".")[-1].startswith("Edge") else "SketchModelFace"
    elif item is None:
        items, name = empty_items(sketch), "SketchEmpty"
    else:
        pick_under(item, sketch)
        element = item[3]
        index = constraint_index(element)
        if index is not None and 0 <= index < len(sketch.Constraints):
            if sketch.Constraints[index].Type in DIMENSION_TYPES:
                items, name = dimension_items(sketch, index), "SketchDimension"
            else:
                items, name = relation_items(sketch, index), "SketchRelation"
        elif element.startswith("Vertex") or element in ("RootPoint",):
            items, name = point_items(sketch, item), "SketchPoint"
        else:
            items, name = entity_items(sketch, item), "SketchEntity"
    row_element = element if element and not element.startswith("Constraint") else None
    return name, items, sketch_rows(sketch, row_element)


def _select_mode():
    run_key("Select")


def _model_hit(sketch, at=None):
    """(doc, object, element, xyz) of the model face or edge under the pointer while a sketch is open, or None."""
    try:
        from .multibody import is_helper
    except Exception:
        is_helper = lambda o: False
    found = []
    for doc, name, sub, xyz in objects_under_pointer(at):
        leaf = (sub or "").split(".")[-1]
        if not (leaf.startswith("Face") or leaf.startswith("Edge")):
            continue
        try:
            obj = App.getDocument(doc).getObject(name)
        except Exception:
            continue
        if obj is None or obj is sketch or obj.TypeId == "Sketcher::SketchObject" or is_helper(obj):
            continue
        found.append((doc, name, sub, xyz))

    edges = [f for f in found if f[2].split(".")[-1].startswith("Edge")]
    return (edges or found or [None])[0]



MODEL_SKETCH_TOOLS = (("Offset", "Offset Entities..."), ("Convert", "Convert Entities"), ("Trim", "Trim Entities"),
                      ("SketchFillet", "Sketch Fillet..."), ("MirrorEntities", "Mirror Entities..."), ("MakePath", "Make Path"))


def sketch_model_items(sketch, hit):
    ""


    from . import partextras as px, partmenu
    doc, name, sub = hit[:3]
    leaf = sub.split(".")[-1]
    try:
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc, name, sub)
    except Exception as _fw_err:
        _fw_log("rcmenus.py:model-pick", _fw_err)
    item = (doc, name, sub)
    items = []
    if leaf.startswith("Edge"):
        items += [action("SelectMidpoint", T_SELECT_MIDPOINT, lambda: select_edge_midpoint(item)),
                  action("SelectLoop", T_SELECT_LOOP, lambda: select_loop(item))]
    else:
        items.append(action("SelectConnected", px.T_SELECT_CONNECTED, lambda: px.select_connected_faces(item), more=True))
    items += view_items(sketch)
    items += [header(T_RELATIONS, "HeaderRelations"), entry("Relations", T_DISPLAY_DELETE), _rs_options()]
    items.append(submenu("SketchTools", T_TOOLS, entries(MODEL_SKETCH_TOOLS)))
    feature = None
    try:
        feature = partmenu.owner_feature(doc, name, sub)
    except Exception as _fw_err:
        _fw_log("rcmenus.py:model-feature", _fw_err)
    if feature is not None:
        items += [header(partmenu.T_BODY, "HeaderBody"),
                  action("HideBody", "Hide", lambda: px.hide_body(feature)),
                  action("BodyProperties", px.T_BODY_PROPERTIES, lambda: px.body_properties(feature), more=True)]
    return [i for i in items if i is not None]


def view_items(sketch, contour=True):
    """The top of every no-tool sketch menu (screen read 4-8): [Contour Select Tool], Selection
    Tools >, Zoom/Pan/Rotate >, [Set Current View As... >], Display Grid, Recent Commands >,
    Sketch Entities >, More Dimensions > ([...] only behind the chevron)."""
    from . import rcextras
    items = []
    if contour:
        items.append(action("ContourSelect", T_CONTOUR_SELECT, lambda: contour_select_tool(sketch), more=True))
    items += [selection_tools_menu(), zoom_menu(), rcextras.set_view_menu(True), _grid_item(sketch), recent_menu(),
              sketch_entities_menu(), more_dimensions_menu()]
    return items


def empty_items(sketch):
    """No tool, empty space (screen read 4)."""
    items = view_items(sketch) + relations_head() + [_rs_options(), sketch_tools_menu(), sketch_display_menu()]
    return [i for i in items if i is not None]


def _selected_header(sketch, element, p):
    if len(p) > 1:
        return header(T_SELECTED_N, "HeaderSelected")
    return header("%s (%s)" % (T_SELECTED, element_name(sketch, element)), "HeaderSelected")


def entity_items(sketch, item):
    """No tool, on a line, arc or circle (screen read 5)."""
    element = item[3]
    p = picked_elements(sketch)
    items = []
    if element.startswith("Edge"):
        index = int(element[4:]) - 1
        items.append(action("SelectChain", T_SELECT_CHAIN, lambda: select_chain(item, sketch, index)))
        if _has_midpoint(sketch, index):
            items.append(action("SelectMidpoint", T_SELECT_MIDPOINT, lambda: select_midpoint(item, sketch, index)))
    items += view_items(sketch)
    items += relations_head() + [_rs_options()]
    items.append(_selected_header(sketch, element, p))
    if element not in SKETCH_AXES:      # FreeCAD's sketch axes cannot be deleted or detached (pkg206)
        items.append(action("Delete", T_DELETE, _delete, icon=_std_icon("Std_Delete")))
        items.append(entry("DetachSegmentOnDrag", T_DETACH))
    if element.startswith("Edge"):
        items += _spline_items(sketch, int(element[4:]) - 1)
        items += _freecad_entity_items(sketch, int(element[4:]) - 1)
    items.append(sketch_tools_menu())
    if element.startswith("Edge"):
        items += _block_items(sketch, int(element[4:]) - 1)
        items += _path_items(sketch, int(element[4:]) - 1)
    return [i for i in items if i is not None]


def _path_items(sketch, index):
    ""
    try:
        from . import sketchpath
        if sketchpath.path_of(sketch, index) is None:
            return []
    except Exception:
        return []
    def dissolve():
        sketchpath._pick(sketch, [index])
        sketchpath.dissolve_path()
    return [action("DissolvePath", "Dissolve Path", dissolve)]


SKETCH_AXES = ("H_Axis", "V_Axis")
SPLINE_ITEMS = (("InsertSplinePoint", "Insert Spline Point"), ("ShowSplineHandles", "Show Spline Handles"),
                ("ShowCurvatureCombs", "Show Curvature"), ("ShowInflectionPoints", "Show Inflection Points"),
                ("ShowMinimumRadius", "Show Minimum Radius of Curvature"), ("SimplifySpline", "Simplify Spline..."),
                ("FitSpline", "Fit Spline..."), ("ConvertToStyleSpline", "Convert to Style Spline"),
                ("AddTangencyControl", "Add Tangency Control"), ("AddCurvatureControl", "Add Curvature Control"))


def _spline_items(sketch, index):
    ""

    try:
        g = sketch.Geometry[index]
    except Exception:
        return []
    if "BSpline" not in type(g).__name__:
        return []
    items = [entry(key, text) for key, text in SPLINE_ITEMS]
    items += [entry(key, text, more=True) for key, text in SPLINE_MORE]
    for it in items:
        if it is not None and it.key in SPLINE_MARKS:
            it.checked = _spline_mark(sketch, index, it.key)
    return items + [spline_display_menu(), spline_tools_menu()]


# Relax Spline and Proportional (the Spline PM's own buttons) stay reachable behind the chevron; the

# unordered copy of these entries below the chevron).
SPLINE_MORE = (("RelaxSpline", "Relax Spline"), ("SplineProportional", "Proportional"))
SPLINE_MARKS = ("ShowCurvatureCombs", "ShowInflectionPoints", "ShowMinimumRadius", "SplineProportional")


def _spline_mark(sketch, index, key):
    try:
        from .fwsketch import splinecommands
        mark = splinecommands.checked("FreeWorks_" + key, sketch, index)
        return None if mark is None else bool(mark)
    except Exception:
        return None


SPLINE_TOOLS = (("SplineIncreaseDegree", "Increase Degree"), ("SplineDecreaseDegree", "Decrease Degree"),
                ("SplineIncreaseKnotMultiplicity", "Increase Knot Multiplicity"),
                ("SplineDecreaseKnotMultiplicity", "Decrease Knot Multiplicity"),
                ("ToggleInternalGeometry", "Show/Hide Internal Geometry"))


def spline_tools_menu(more=True):
    """FreeCAD's spline commands (degree, knots, internal geometry): behind the chevron."""
    return submenu("SplineToolsFC", "Spline Tools (FreeCAD)", [entry(k, t) for k, t in SPLINE_TOOLS], more)


def _freecad_entity_items(sketch, index):
    """FreeCAD's own entity commands, behind the chevron: Remove Axes Alignment, and an ellipse's or
    conic's Show/Hide Internal Geometry."""
    try:
        g = sketch.Geometry[index]
    except Exception:
        return []
    out = [entry("RemoveAxesAlignment", "Remove Axes Alignment (FreeCAD)", more=True)]
    kind = type(g).__name__
    if any(k in kind for k in ("Ellipse", "Hyperbola", "Parabola")):
        out.append(entry("ToggleInternalGeometry", "Show/Hide Internal Geometry (FreeCAD)", more=True))
    return out


SPLINE_DISPLAY = (("SplineShowDegree", "Degree"), ("SplineShowPolygon", "Control Polygon"),
                  ("SplineShowComb", "Curvature Comb"), ("SplineShowKnotMultiplicity", "Knot Multiplicity"),
                  ("SplineShowPoleWeight", "Control Point Weight"))


def spline_display_menu(more=True):
    ""
    return submenu("SplineDisplay", "Spline Display (FreeCAD)", [entry(k, t) for k, t in SPLINE_DISPLAY], more)


RENDER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
RENDER_KEYS = ("TopRenderGeometryId", "MidRenderGeometryId", "LowRenderGeometryId")
RENDER_KINDS = ((1, "Normal Geometry"), (2, "Construction Geometry"), (3, "External Geometry"))


def rendering_order():
    """FreeCAD's sketch rendering order, top first: [1 normal, 2 construction, 3 external]."""
    p = App.ParamGet(RENDER_PARAMS)
    order = [p.GetInt(k, d) for k, d in zip(RENDER_KEYS, (1, 2, 3))]
    return order if sorted(order) == [1, 2, 3] else [1, 2, 3]


def set_rendering_top(kind):
    """That kind of geometry is drawn on top; the other two keep their order (FreeCAD's Rendering
    Order, which the sketch in edit follows at once)."""
    order = [kind] + [k for k in rendering_order() if k != kind]
    p = App.ParamGet(RENDER_PARAMS)
    for key, k in zip(RENDER_KEYS, order):
        p.SetInt(key, k)
    return order


def _rendering_order_fill(menu):
    """FreeCAD's Rendering Order (which kind of geometry is drawn on top of the others)."""
    top = rendering_order()[0]
    for kind, text in RENDER_KINDS:
        a = menu.addAction("%s on Top" % text)
        a.setObjectName("SWRenderTop%d" % kind)
        a.setCheckable(True)
        a.setChecked(kind == top)
        a.triggered.connect(lambda checked=False, k=kind: set_rendering_top(k))


def sketch_display_menu(more=True):
    """FreeCAD's sketch display helpers: arc helpers, rendering order and the spline toggles (behind the chevron)."""
    return submenu("SketchDisplayFC", "Sketch Display (FreeCAD)",
                   [entry("SketchArcOverlay", "Arc Helpers"), dynamic("RenderingOrder", "Rendering Order", _rendering_order_fill),
                    spline_display_menu(False), entry("SectionSketch", "Section View")], more)


def _block_items(sketch, index):
    ""

    try:
        from . import blocks
        rec = blocks.block_of(sketch, index)
    except Exception:
        rec = None
    if not rec:
        return []
    return [header("Block (%s)" % rec.get("name", "Block"), "HeaderBlock"),
            entry("EditBlock", "Edit Block"), entry("AddRemoveBlockEntities", "Add/Remove Entities..."),
            entry("SaveBlock", "Save Block..."), entry("ExplodeBlock", "Explode Block"),
            entry("HideShowBlock", "Hide Block")]


def point_items(sketch, item):
    """No tool, on a point (screen read 6): no Delete, no Select Chain; Sketch Tools > sits under
    Relations in the short form and under "Selected Entity (Point5)" in the long one."""
    element = item[3]
    p = picked_elements(sketch)
    items = view_items(sketch) + relations_head()
    items += [short_only(sketch_tools_menu()), _rs_options()]
    h = _selected_header(sketch, element, p)
    h.more = True
    items += [h, sketch_tools_menu(True)]
    return [i for i in items if i is not None]


def dimension_heading_name(sketch, index):
    from . import rcextras
    try:
        return "%s(%s)" % (dimension_name(sketch, index), rcextras.value_text(sketch, index))
    except Exception:
        return dimension_name(sketch, index)


def dimension_items(sketch, index):
    """No tool, on a dimension (screen read 7)."""
    from . import rcextras
    c = sketch.Constraints[index]
    named = dimension_heading_name(sketch, index)
    items = view_items(sketch) + relations_head()
    items += [_rs_options(), sketch_tools_menu(), action("Delete", T_DELETE, _delete, icon=_std_icon("Std_Delete")),
              header("Dimension (%s)" % named, "HeaderDimension"),
              action("LinkValues", rcextras.T_LINK_VALUES, lambda: rcextras.link_values(sketch, index)),
              rcextras.unlink_item(sketch, index),
              action("ReverseDirection", rcextras.T_REVERSE, lambda: rcextras.reverse_direction(sketch, index))
              if rcextras.can_reverse(sketch, index) else None,     # no greyed item (pkg206)
              action("Driven", T_DRIVEN, lambda: toggle_driven(sketch, index), checked=not sketch.getDriving(index)),
              action("MarkForDrawing", T_MARK_FOR_DRAWING, lambda: toggle_mark_for_drawing(sketch, index),
                     checked=marked_for_drawing(sketch, index)),
              _configure_dimension(sketch, index),
              entry("SelectAssociatedGeometry", "Select Associated Geometry (FreeCAD)", more=True)]


    as_kind = None
    if c.Type in ("Radius", "Diameter"):
        as_kind = action("DisplayAsDiameter", T_AS_DIAMETER if c.Type == "Radius" else T_AS_RADIUS,
                         lambda: radius_diameter(sketch, index))
    items += [rcextras.display_options_menu(sketch, index, as_kind, [rcextras.hide_dimension_line_item(sketch, index)]),
              rcextras.annotations_menu(sketch, index),
              header("%s (%s)" % (T_SELECTED, named), "HeaderSelected"),
              action("Hide", T_HIDE, lambda: hide_dimension(sketch, index)),
              action("SelectAnnotationView", rcextras.T_ANNOT_VIEW,
                     lambda: rcextras.select_annotation_view(sketch, index))]
    return [i for i in items if i is not None]


T_CONFIGURE_DIMENSION = "Configure Dimension"


def _configure_dimension(sketch, index):
    ""

    try:
        from . import configtable
    except Exception:
        return None
    if not hasattr(configtable, "configure_dimension"):
        return None
    return action("ConfigureDimension", T_CONFIGURE_DIMENSION, lambda: configtable.configure_dimension(sketch, index),
                  more=True)       # not in the short menu of screen read 7: behind the chevron


def relation_items(sketch, index):
    """No tool, on a relation glyph (screen read 8): no Contour Select Tool, no Selected Entity."""
    picked = [constraint_index(e) for e in picked_elements(sketch)]
    picked = [i for i in picked if i is not None and sketch.Constraints[i].Type not in DIMENSION_TYPES] or [index]
    items = view_items(sketch, contour=False) + relations_head()
    items += [action("ToggleSuppression", T_TOGGLE_SUPPRESSION, lambda: toggle_suppression(sketch, picked)),
              action("Delete", T_DELETE, _delete, icon=_std_icon("Std_Delete")),
              _rs_options(), sketch_tools_menu(),
              entry("SelectAssociatedGeometry", "Select Associated Geometry (FreeCAD)", more=True)]
    return [i for i in items if i is not None]


# --------------------------------------------------------------------------- Select Other, Select Tangency
def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def objects_under_pointer(at=None):
    """Everything under the pointer (or the view point at), nearest first: [(doc, object, element, (x, y, z))]."""
    view = _view()
    if view is None:
        return []
    try:
        infos = view.getObjectsInfo(tuple(at) if at is not None else view.getCursorPos()) or []
    except Exception:
        return []
    out, seen = [], set()
    for i in infos:
        key = (i.get("Document"), i.get("Object"), i.get("Component", ""))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        out.append(key + ((i.get("x", 0.0), i.get("y", 0.0), i.get("z", 0.0)),))
    return out


T_SELECT_OTHER_HIDE = "Tab hides the body of the highlighted item; Shift+Tab shows it again"
T_SELECT_OTHER_FACES = ("Right-click in the graphics area hides the face under the pointer; "
                        "Shift+right-click shows it again")


def _is_face(sub):
    return bool(sub) and sub.split(".")[-1].startswith("Face")


class _FaceHider:
    ""



    def __init__(self):
        self.saved = {}         # (doc, name) -> (appearance list, document modified)
        self.hidden = []        # (doc, name, face index from 0), newest last

    def _object(self, doc, name):
        d = App.listDocuments().get(doc)
        return d.getObject(name) if d is not None else None

    def _leaf(self, doc, name, sub):
        """(object that owns the face, index) for a pick path, else None."""
        obj = self._object(doc, name)
        if obj is None or not _is_face(sub):
            return None
        parts = [p for p in sub.split(".") if p]
        owner = obj
        for part in parts[:-1]:
            o = obj.Document.getObject(part)
            if o is not None:
                owner = o
        try:
            index = int(parts[-1][4:]) - 1
        except ValueError:
            return None
        # a face of a body's Tip is drawn by the body
        shown = owner
        if owner.TypeId != "PartDesign::Body":
            try:
                for parent in owner.InList:
                    if parent.TypeId == "PartDesign::Body" and parent.Tip is owner:
                        shown = parent
            except Exception as _fw_err:
                _fw_log("rcmenus.py:select_other_leaf", _fw_err)
        return shown, index

    def is_hidden(self, doc, name, sub):
        leaf = self._leaf(doc, name, sub)
        return leaf is not None and (leaf[0].Document.Name, leaf[0].Name, leaf[1]) in self.hidden

    def _apply(self, obj):
        key = (obj.Document.Name, obj.Name)
        vo = getattr(obj, "ViewObject", None)
        if vo is None or "ShapeAppearance" not in vo.PropertiesList:
            return False
        if key not in self.saved:
            try:
                modified = Gui.getDocument(obj.Document.Name).Modified
            except Exception:
                modified = None
            self.saved[key] = (list(vo.ShapeAppearance), modified)
        base = self.saved[key][0]
        count = len(obj.Shape.Faces)
        mats = []
        for i in range(count):
            src = base[i] if i < len(base) else base[0]
            m = App.Material()
            for attr in ("DiffuseColor", "AmbientColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency"):
                try:
                    setattr(m, attr, getattr(src, attr))
                except Exception as _fw_err:
                    _fw_log("rcmenus.py:select_other_mat", _fw_err)
            if (key[0], key[1], i) in self.hidden:
                m.Transparency = 1.0
            mats.append(m)
        vo.ShapeAppearance = mats
        return True

    def hide(self, doc, name, sub):
        leaf = self._leaf(doc, name, sub)
        if leaf is None:
            return False
        obj, index = leaf
        entry = (obj.Document.Name, obj.Name, index)
        if entry in self.hidden:
            return False
        self.hidden.append(entry)
        if not self._apply(obj):
            self.hidden.pop()
            return False
        return True

    def show_last(self):
        if not self.hidden:
            return False
        doc, name, _i = self.hidden.pop()
        obj = self._object(doc, name)
        if obj is not None:
            self._apply(obj)
        return True

    def restore(self):
        self.hidden = []
        for (doc, name), (mats, modified) in list(self.saved.items()):
            obj = self._object(doc, name)
            try:
                if obj is not None:
                    obj.ViewObject.ShapeAppearance = mats
                if modified is not None:
                    Gui.getDocument(doc).Modified = modified
            except Exception as _fw_err:
                _fw_log("rcmenus.py:select_other_restore", _fw_err)
        self.saved = {}


class SelectOtherBox(QtWidgets.QWidget):
    ""







    EVENTS = (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick,
              QtCore.QEvent.ContextMenu, QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride)
    KEYS = (QtCore.Qt.Key_Escape, QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab)

    def __init__(self, at, pos):
        mw = Gui.getMainWindow()
        super().__init__(mw, QtCore.Qt.Tool | QtCore.Qt.CustomizeWindowHint | QtCore.Qt.WindowTitleHint
                         | QtCore.Qt.WindowCloseButtonHint)
        self.setObjectName("SWSelectOther")
        self.setWindowTitle(" ")
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.at, self.pos0 = at, pos
        self.faces = _FaceHider()
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWSelectOtherList")
        self.list.setMouseTracking(True)
        self.list.setToolTip(T_SELECT_OTHER_FACES)
        self.list.itemEntered.connect(self._entered)
        self.list.currentRowChanged.connect(lambda r: self._entered(self.list.item(r)) if r >= 0 else None)
        self.list.itemClicked.connect(self._clicked)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(self.list)
        self._name = "selectother-%d" % id(self)
        self._closing = False

    # ---------------------------------------------------------------- the rows
    def found(self, at=None):
        out = []
        from .multibody import is_helper
        for doc, name, sub, xyz in objects_under_pointer(at if at is not None else self.at):
            if self.faces.is_hidden(doc, name, sub):
                continue
            try:
                obj = App.getDocument(doc).getObject(name)
                if is_helper(obj):
                    continue            # the add-on's own rows are never picked
            except Exception as _fw_err:
                _fw_log("rcmenus.py:select_other_found", _fw_err)
            out.append((doc, name, sub, xyz))
        return out

    def refill(self):
        for a in list(self.actions()):
            self.removeAction(a)
        self.list.clear()
        for doc, name, sub, xyz in self.found():
            try:
                label = App.getDocument(doc).getObject(name).Label
            except Exception:
                label = name
            leaf = sub.split(".")[-1] if sub else ""
            text = "%s@%s" % (leaf, label) if leaf else label
            a = (QtGui.QAction if hasattr(QtGui, "QAction") else QtWidgets.QAction)(text, self)
            a.setObjectName("SWSelectOther_%s_%s" % (name, leaf))
            a.setData((doc, name, sub))
            a.setToolTip(T_SELECT_OTHER_HIDE)
            a.hovered.connect(lambda d=doc, n=name, s=sub: _preselect(d, n, s))
            a.triggered.connect(lambda _c=False, d=doc, n=name, s=sub, p=xyz: self._pick(d, n, s, p))
            self.addAction(a)
            item = QtWidgets.QListWidgetItem(text, self.list)
            item.setData(QtCore.Qt.UserRole, len(self.actions()) - 1)
        self.list.setFixedHeight(min(10, max(1, self.list.count())) * (self.list.sizeHintForRow(0) + 2) + 6
                                 if self.list.count() else 30)
        self.adjustSize()

    def activeAction(self):
        item = self.list.currentItem()
        if item is None:
            return None
        acts = self.actions()
        k = item.data(QtCore.Qt.UserRole)
        return acts[k] if k is not None and k < len(acts) else None

    def _entered(self, item):
        if item is None:
            return
        self.list.setCurrentItem(item)
        a = self.activeAction()
        if a is not None:
            a.hover()

    def _clicked(self, item):
        self.list.setCurrentItem(item)
        a = self.activeAction()
        if a is not None:
            a.trigger()

    def _pick(self, doc, name, sub, xyz):
        _add_pick(doc, name, sub, xyz)
        later(self.close)

    # ---------------------------------------------------------------- open, close
    def open(self):
        first = self.found()

        if len(first) > 1 and _is_face(first[0][2]):
            self.faces.hide(*first[0][:3])
        self.refill()
        if not self.list.count():
            self.faces.restore()
            return False
        events.register(self._name, self.EVENTS, self._view_event)
        for t in self.EVENTS:     # ahead of the add-on's own right-click handling
            lst = events._BY_TYPE.get(t, [])
            mine = [e for e in lst if e[0] == self._name]
            lst[:] = mine + [e for e in lst if e[0] != self._name]
        self.move(self.pos0 + QtCore.QPoint(16, 16))
        self.show()
        self.raise_()
        return True

    def closeEvent(self, event):
        self._closing = True
        events.unregister(self._name)
        self.faces.restore()
        try:
            Gui.Selection.removePreselection()
            clear = globals().get("clear_list_preview")
            if clear is not None:
                clear()                 # the hovered row's outline in the view
        except Exception as _fw_err:
            _fw_log("rcmenus.py:select_other_close", _fw_err)
        if _keep_select_other and _keep_select_other[0] is self:
            _keep_select_other[:] = []
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()
            return
        if event.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            shift = event.key() == QtCore.Qt.Key_Backtab or bool(event.modifiers() & QtCore.Qt.ShiftModifier)
            if select_other_show_last() if shift else select_other_hide(self.activeAction()):
                self.refill()
            return
        super().keyPressEvent(event)

    def event(self, e):
        if e.type() == QtCore.QEvent.KeyPress and e.key() in (QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab):
            self.keyPressEvent(e)       # Tab would move the focus instead
            return True
        return super().event(e)

    # ---------------------------------------------------------------- the graphics area while open
    def _in_view(self, obj):
        try:
            w = obj if isinstance(obj, QtWidgets.QWidget) else None
            while w is not None:
                if w.metaObject().className() == "Gui::View3DInventorViewer":
                    return True
                w = w.parentWidget()
        except Exception:
            return False
        return False

    def _cursor_at(self):
        try:
            return tuple(Gui.ActiveDocument.ActiveView.getCursorPos())
        except Exception:
            return None

    def right_click(self, shift, at=None):
        """Right-click in the graphics area: the face under the pointer hidden (Shift: the last one shown)."""
        if shift:
            done = self.faces.show_last()
        else:
            at = at if at is not None else self._cursor_at()
            faces = [f for f in self.found(at) if _is_face(f[2])]
            done = bool(faces) and self.faces.hide(*faces[0][:3])
        if done:
            self.refill()
        return done

    def left_click(self, at=None):
        """A click on the model: the first item under the pointer that is not hidden is picked."""
        items = self.found(at if at is not None else self._cursor_at())
        if items:
            self._pick(*items[0])
        return bool(items)

    def _typing(self):
        """A text box or a number box (not the list's own) has the keyboard: its Esc and Tab are left to it."""
        fw = QtWidgets.QApplication.focusWidget()
        return isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit,
                               QtWidgets.QPlainTextEdit)) and not self.isAncestorOf(fw)

    def _view_event(self, obj, event):
        if self._closing or not alive(self):
            return False
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
            # The list does not take the keyboard, and Tab reaches the main window's QWindow (and the add-on's
            # own Tab handlers) before any widget: Esc, Tab and Shift+Tab are the open list's, wherever they arrive
            # (the old menu grabbed them; without this Esc left the list open and Tab never reached it).
            if event.key() not in self.KEYS or self._typing():
                return False
            event.accept()
            if t == QtCore.QEvent.KeyPress:
                self.keyPressEvent(event)
            return True
        if not self._in_view(obj):
            return False
        if t == QtCore.QEvent.ContextMenu:
            return True
        if not hasattr(event, "button"):
            return False
        if event.button() == QtCore.Qt.RightButton:
            if t == QtCore.QEvent.MouseButtonRelease:
                self.right_click(bool(event.modifiers() & QtCore.Qt.ShiftModifier))
            return True
        if event.button() == QtCore.Qt.LeftButton and not (event.modifiers() & QtCore.Qt.ControlModifier):
            if t == QtCore.QEvent.MouseButtonRelease:
                self.left_click()
            return True
        return False


def select_other(pos=None, at=None):
    ""

    view = _view()
    if at is None and view is not None:
        try:
            at = tuple(view.getCursorPos())
        except Exception:
            at = None
    pos = pos or QtGui.QCursor.pos()
    old = _keep_select_other[0] if _keep_select_other else None
    if old is not None and alive(old):
        old.close()
    box = SelectOtherBox(at, pos)
    if not box.open():
        try:
            Gui.getMainWindow().statusBar().showMessage("Select Other: nothing under the pointer to pick", 4000)
        except Exception as _fw_err:
            _fw_log("rcmenus.py:select_other", _fw_err)
        box.deleteLater()
        return None
    _keep_select_other[:] = [box]
    return box


_select_other_hidden = []       # (doc, body) Tab hid from the Select Other list, newest last


def _hover_keys():
    try:
        from . import swkeys
        return swkeys, swkeys._hover
    except Exception:
        return None, None


def select_other_hide(action):
    """Tab in the Select Other list: hides the body the highlighted item belongs to."""
    data = action.data() if action is not None else None
    if not data:
        return False
    doc_name, name, _sub = data
    swkeys, hover = _hover_keys()
    try:
        obj = App.getDocument(doc_name).getObject(name)
        body = swkeys.top_body(obj) if swkeys is not None else obj
    except Exception:
        body = None
    if body is None or getattr(body, "ViewObject", None) is None:
        return False
    doc = body.Document
    doc.openTransaction("Hide")
    try:
        body.ViewObject.Visibility = False
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    _select_other_hidden.append((doc.Name, body.Name))
    if hover is not None:
        hover.hidden.append((doc.Name, body.Name))     # Ctrl+Shift+Tab in the view shows these too
    return True


def select_other_show_last():
    """Shift+Tab in the Select Other list: shows the body hidden last from it."""
    while _select_other_hidden:
        doc_name, name = _select_other_hidden.pop()
        doc = App.listDocuments().get(doc_name)
        obj = doc.getObject(name) if doc is not None else None
        if obj is None or obj.ViewObject is None:
            continue
        doc.openTransaction("Show")
        try:
            obj.ViewObject.Visibility = True
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        _swk, hover = _hover_keys()
        if hover is not None:
            hover.hidden = [h for h in hover.hidden if h != (doc_name, name)]
        return True
    return False


_keep_select_other = []


_list_preview = []      # [(scene root, node)] of the Select Other row being hovered


def clear_list_preview():
    while _list_preview:
        root, node = _list_preview.pop()
        try:
            root.removeChild(node)
        except Exception as _fw_err:
            _fw_log("rcmenus.py:preview-clear", _fw_err)


def _preselect(doc, name, sub):
    ""


    clear_list_preview()
    try:
        from pivy import coin
        from . import facehover
        leaf = sub.rsplit(".", 1)[-1]
        view = Gui.getDocument(doc).ActiveView
        if leaf.startswith("Vertex"):
            import Part
            lines = [[Part.getShape(App.getDocument(doc).getObject(name), sub, needSubElement=True).Point]]
        else:
            lines = facehover._lines(doc, name, sub)
        if not lines:
            return
        node = coin.SoSeparator()
        node.setName("SWSelectOtherPreview")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        colour = coin.SoBaseColor()
        colour.rgb.setValue(*facehover._colour())
        draw = coin.SoDrawStyle()
        dpr = Gui.getMainWindow().devicePixelRatioF()
        draw.lineWidth = facehover.WIDTH * dpr
        draw.pointSize = facehover.POINT_PX * dpr
        depth = coin.SoDepthBuffer()
        depth.test = False
        coords = coin.SoCoordinate3()
        points = [(p.x, p.y, p.z) if hasattr(p, "x") else tuple(p) for line in lines for p in line]
        coords.point.setValues(0, len(points), points)
        if leaf.startswith("Vertex"):
            shape = coin.SoPointSet()
            shape.numPoints.setValue(len(points))
        else:
            shape = coin.SoLineSet()
            shape.numVertices.setValues(0, len(lines), [len(line) for line in lines])
        for child in (pick, light, colour, draw, depth, coords, shape):
            node.addChild(child)
        root = view.getSceneGraph()
        root.addChild(node)
        _list_preview.append((root, node))
    except Exception as _fw_err:
        _fw_log("rcmenus.py:1896", _fw_err)


def _add_pick(doc, name, sub, xyz):
    try:
        Gui.Selection.addSelection(doc, name, sub, *xyz)
    except Exception:
        try:
            Gui.Selection.addSelection(doc, name, sub)
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1906", _fw_err)


def _resolve_edge(doc, name, sub):
    """(object, edge index from 1, the shape) for an edge path."""
    try:
        obj = App.getDocument(doc).getObject(name)
        leaf_obj, leaf = obj, sub
        if "." in sub:
            parts = [p for p in sub.split(".") if p and not p.startswith(";")]
            leaf = parts[-1]
            if len(parts) > 1:
                leaf_obj = App.getDocument(doc).getObject(parts[-2]) or obj
        if not leaf.startswith("Edge"):
            return None
        return leaf_obj, int(leaf[4:]), leaf_obj.Shape
    except Exception:
        return None


def tangent_edges(shape, index, angle=1e-3):
    ""
    edges = shape.Edges
    chain, todo = {index}, [index]

    def tangents(e):
        out = []
        try:
            a, b = e.ParameterRange
            out.append((e.valueAt(a), e.tangentAt(a)))
            out.append((e.valueAt(b), e.tangentAt(b)))
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1938", _fw_err)
        return out
    while todo:
        i = todo.pop()
        for p, t in tangents(edges[i - 1]):
            for j, e in enumerate(edges, 1):
                if j in chain:
                    continue
                for q, u in tangents(e):
                    if (p - q).Length < 1e-6 and t.Length > 0 and u.Length > 0:
                        cos = abs(t.dot(u)) / (t.Length * u.Length)
                        if cos > math.cos(angle):
                            chain.add(j)
                            todo.append(j)
                            break
    return sorted(chain)


def select_tangency(item):
    doc, name, sub = item[:3]
    got = _resolve_edge(doc, name, sub)
    if got is None:
        return
    _obj, index, shape = got
    prefix = sub[:len(sub) - len("Edge%d" % index)]
    for j in tangent_edges(shape, index):
        try:
            Gui.Selection.addSelection(doc, name, "%sEdge%d" % (prefix, j))
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1967", _fw_err)


def loop_edges(shape, index, flip=0):
    """Edge indices (from 1) of the loop through edge index on one of its faces (flip: the other face)."""
    edge = shape.Edges[index - 1]
    faces = [f for f in shape.Faces if any(e.isSame(edge) for e in f.Edges)]
    if not faces:
        return [index]
    face = faces[flip % len(faces)]
    for wire in face.Wires:
        if any(e.isSame(edge) for e in wire.Edges):
            return sorted(j for j, e in enumerate(shape.Edges, 1) if any(e.isSame(w) for w in wire.Edges))
    return [index]


def select_loop(item, flip=0):
    ""
    doc, name, sub = item[:3]
    got = _resolve_edge(doc, name, sub)
    if got is None:
        return
    _obj, index, shape = got
    prefix = sub[:len(sub) - len("Edge%d" % index)]
    for j in loop_edges(shape, index, flip):
        try:
            Gui.Selection.addSelection(doc, name, "%sEdge%d" % (prefix, j))
        except Exception as _fw_err:
            _fw_log("rcmenus.py:1995", _fw_err)


T_SELECT_PARTIAL_LOOP = "Select Partial Loop"


def partial_loop_edges(shape, first, last, flip=0):
    ""


    a, b = shape.Edges[first - 1], shape.Edges[last - 1]
    for face in shape.Faces:
        for wire in face.Wires:
            ordered = list(getattr(wire, "OrderedEdges", wire.Edges))
            ia = next((k for k, e in enumerate(ordered) if e.isSame(a)), None)
            ib = next((k for k, e in enumerate(ordered) if e.isSame(b)), None)
            if ia is None or ib is None or ia == ib:
                continue
            n = len(ordered)
            fwd = [ordered[(ia + k) % n] for k in range((ib - ia) % n + 1)]
            back = [ordered[(ia - k) % n] for k in range((ia - ib) % n + 1)]
            ways = sorted((fwd, back), key=len)
            path = ways[flip % 2]
            return [j for j, e in enumerate(shape.Edges, 1) if any(e.isSame(p) for p in path)]
    return []


def picked_edge_pair():
    """(doc, name, prefix, first, last) when exactly two edges of one object are picked, else None."""
    try:
        sel = [(s.DocumentName, s.ObjectName, sub) for s in Gui.Selection.getSelectionEx("", 0)
               for sub in (s.SubElementNames or ()) if sub.split(".")[-1].startswith("Edge")]
    except Exception:
        return None
    if len(sel) != 2 or sel[0][:2] != sel[1][:2]:
        return None
    out = []
    for doc, name, sub in sel:
        leaf = sub.split(".")[-1]
        out.append((sub[:len(sub) - len(leaf)], int(leaf[4:])))
    if out[0][0] != out[1][0]:
        return None
    return sel[0][0], sel[0][1], out[0][0], out[0][1], out[1][1]


def can_select_partial_loop():
    pair = picked_edge_pair()
    if pair is None:
        return False
    doc, name, prefix, first, last = pair
    got = _resolve_edge(doc, name, prefix + "Edge%d" % first)
    return got is not None and bool(partial_loop_edges(got[2], first, last))


def select_partial_loop(flip=0):
    ""

    pair = picked_edge_pair()
    if pair is None:
        return []
    doc, name, prefix, first, last = pair
    got = _resolve_edge(doc, name, prefix + "Edge%d" % first)
    if got is None:
        return []
    picked = partial_loop_edges(got[2], first, last, flip)
    for j in picked:
        try:
            Gui.Selection.addSelection(doc, name, "%sEdge%d" % (prefix, j))
        except Exception as _fw_err:
            _fw_log("rcmenus.py:2064", _fw_err)
    return picked


# --------------------------------------------------------------------------- install
def install(sh=None):
    hook_recent(sh)
    if "SWStyle_ZoomToSelection" not in Gui.listCommands():
        Gui.addCommand("SWStyle_ZoomToSelection", ZoomToSelectionCommand())
    try:
        from . import viewspeeds        # Options > View: Mouse speed and the Transitions speeds
        viewspeeds.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: view speeds: %s\n" % error)
    try:
        from . import statustips        # the status-bar hint under buttons and menu entries
        statustips.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: status-bar hints: %s\n" % error)
    try:
        from . import recentdocs
        recentdocs.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: recent documents: %s\n" % error)
    try:
        from . import recovery          # auto-recover on the Options interval, the Document Recovery tab
        recovery.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: document recovery: %s\n" % error)
    try:
        from . import appearextras      # component Change Transparency, Appearances PM swatches
        appearextras.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: appearance extras: %s\n" % error)
    try:
        from . import viewtools         # Zoom to Area and Zoom In/Out stay on until Esc
        viewtools.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: view tools: %s\n" % error)
    try:
        from . import quicktips         # the status bar ? and its Quick Tips panel
        from . import shell as _sh
        quicktips.install(_sh.shell())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: quick tips: %s\n" % error)
    try:
        from . import cmfloat           # a CommandManager tab dragged off floats as its own window
        from . import shell as _sh2
        cmfloat.install(_sh2.shell())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: floating tabs: %s\n" % error)
    try:
        from . import mousespeed        # Options > View > Mouse speed slows a middle-drag rotate
        mousespeed.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: mouse speed: %s\n" % error)
    try:
        from . import touchlens         # Touch Mode: hold still on the view to open the precision lens
        touchlens.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: touch lens: %s\n" % error)
    try:
        from . import fcextratabs       # 2D Drafting, Part Tools and Mesh Tools tabs for FreeCAD-only tools
        fcextratabs.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: FreeCAD tool tabs: %s\n" % error)
    try:
        from . import viewanim          # Esc stops a view change while it turns; the status bar says so
        viewanim.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: view animation Esc: %s\n" % error)
    try:
        from . import activewin
        activewin.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: active window outline: %s\n" % error)
    try:
        from . import altface           # Alt hides the face under the pointer while a PropertyManager is open
        altface.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Alt hides a face: %s\n" % error)
    try:
        from . import simplifiedui
        QtCore.QTimer.singleShot(3000, simplifiedui.install)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Simplified Interface note: %s\n" % error)
    try:
        from . import treelook
        treelook.install()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tree look: %s\n" % error)
    try:
        from . import rcextras
        rcextras.install()
    except Exception as _fw_err:
        _fw_log("rcmenus.py:2159", _fw_err)
