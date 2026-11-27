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

from . import contextbar, paths
from .widgets import alive

Qt = QtCore.Qt
GENERAL_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
TOOLS_GROUP = "User parameter:BaseApp/Preferences/Mod/Sketcher/Tools"
PREVIEW = "PreviewSketchDimension"

T_SET_VIEW = "Set Current View As..."
T_RS_OPTIONS = "Relations/Snaps Options..."
T_PROPERTIES = "Properties..."
T_LINK_VALUES = "Link Values"
T_REVERSE = "Reverse Direction"
T_DISPLAY_OPTIONS = "Display Options"
T_ANNOTATIONS = "Annotations"
T_ANNOT_VIEW = "Select Annotation View (Unassigned Items"
T_PREVIEW = "Preview Sketch Dimension"
T_NUMERIC = "Sketch Numeric Input"
T_MAKE_H, T_MAKE_V, T_MAKE_FIX = "Make Horizontal", "Make Vertical", "Make Fixed"
UNASSIGNED = "Unassigned Items"
ANNOTATION_VIEWS = (UNASSIGNED, "Notes Area", "Front", "Top", "Right")

DISPLAY_FLAGS = (("CenterDimension", "Center Dimension"), ("OffsetText", "Offset Text"),
                 ("ShowParentheses", "Show Parentheses"), ("ShowAsInspection", "Show as Inspection"))
DISPLAY_PROP = "FWDimDisplay"
VIEW_PROP = "FWAnnotationView"

ROW_SECOND = ("SelectOther", "ConstructionPlane", "MakeBlock", "ZoomSelection", "ReplaceEntity",
              "SketchNumericInput", "SmartDimension", "ExitSketch", "BossExtrude")
ROW_SECOND_POINT = ("SelectOther", "ConstructionPlane", "ZoomSelection", "ReplaceEntity",
                    "SketchNumericInput", "SmartDimension", "ExitSketch")
ROW_TOP = {"none": ("PreviewSketchDimension",),
           "line": ("Horizontal", "Vertical", "Fix", "PreviewSketchDimension"),
           "point": ("Fix", "PreviewSketchDimension"),
           "spline": ("Fix", "PreviewSketchDimension"),
           "origin": ("PreviewSketchDimension",)}     # the origin is fixed already; a point's 7 below
ROW_LABELS = {"Horizontal": T_MAKE_H, "Vertical": T_MAKE_V, "Fix": T_MAKE_FIX}


def _rc():
    from . import rcmenus
    return rcmenus


def _icon(label, *families):
    try:
        from . import icons
        for f in families:
            i = icons.family(f)
            if not i.isNull() and icons.paints(i):
                return i
        return icons.initials(label)
    except Exception:
        return QtGui.QIcon()




ITEM_ICONS = {
    "Delete...": "STANDARD_DELETE", "Delete": "STANDARD_DELETE",
    "Feature Properties...": "STANDARD_PROPERTIES", "Properties...": "STANDARD_PROPERTIES",
    "Configure Feature": "CONFIGURATION_TAB",
    "Create Plane Parallel to Screen": "REFGEO_PLANE",
    "Select Other": "SELECT_OTHER",
    "Change Layer": "FONTTOOLBAR_LAYER_PROP",
    "Display Grid": "VIEW_GRID",
    "Fully Define Sketch...": "DIMENSIONS_FULLY_DEFINE_SKETCH",

    "Add to Favorites": "FW_AddToFavorites", "Add to New Folder": "FW_AddToNewFolder",
    "Change Transparency": "FW_ChangeTransparency",
}


def item_icon(text):
    """The pack's picture for a right-click menu item by its text, or None (no picture, or no pack)."""
    name = ITEM_ICONS.get((text or "").split("\t")[0].replace("&", ""))
    if not name:
        return None
    try:
        from . import icons
        i = icons.family(name)
        return i if not i.isNull() and icons.paints(i) else None
    except Exception:
        return None


def _tip(label, detail=""):
    return "<b>%s</b>" % label + ("<br>%s" % detail if detail else "")


# --------------------------------------------------------------------------- parameters
def numeric_input_on():
    return App.ParamGet(GENERAL_GROUP).GetBool("OnScreenNumericInput", False)


def toggle_numeric_input():
    on = not numeric_input_on()
    App.ParamGet(GENERAL_GROUP).SetBool("OnScreenNumericInput", on)
    App.ParamGet(TOOLS_GROUP).SetInt("OnViewParameterVisibility", 1 if on else 0)
    return on


def preview_on():
    return paths.params().GetBool(PREVIEW, False)


def toggle_preview():
    on = not preview_on()
    paths.params().SetBool(PREVIEW, on)
    if on:
        _watch_preview()
        show_preview()
    return on


# --------------------------------------------------------------------------- dimension preview
def preview_text(sketch, element):
    """What Smart Dimension would put on a sketch edge: its length, radius or diameter."""
    try:
        g = sketch.Geometry[int(element[4:]) - 1]
    except Exception:
        return None
    name = type(g).__name__
    if name == "LineSegment":
        return length_text(g.length())
    if name == "Circle":
        return "⌀" + length_text(g.Radius * 2.0)
    if name == "ArcOfCircle":
        return "R" + length_text(g.Radius)
    return None


def length_text(mm):
    try:
        _s, factor, _unit = App.Units.Quantity(abs(mm), App.Units.Length).getUserPreferred()
        value = abs(mm) / factor if factor else abs(mm)
    except Exception:
        value = abs(mm)
    decimals = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
    return "%.*f" % (decimals, value)


def show_preview(pos=None):
    rc = _rc()
    from . import contextbar as cb
    sketch = cb.sketch_in_edit()
    if sketch is None:
        return None
    for e in rc.picked_elements(sketch):
        if e.startswith("Edge"):
            text = preview_text(sketch, e)
            if text:
                QtWidgets.QToolTip.showText(pos or QtGui.QCursor.pos(), text)
                return text
    return None


class _PreviewObserver:
    def addSelection(self, doc, name, sub, point):
        if preview_on() and sub and sub.split(".")[-1].startswith("Edge"):
            QtCore.QTimer.singleShot(0, show_preview)


_observer = []


def _watch_preview():
    if _observer:
        return
    o = _PreviewObserver()
    try:
        Gui.Selection.addObserver(o)
        _observer.append(o)
    except Exception as _fw_err:
        _fw_log("rcextras.py:185", _fw_err)


def install():
    try:
        from . import pmtips
        pmtips.install()
    except Exception as _fw_err:
        _fw_log("rcextras.py:193", _fw_err)
    try:
        from . import dimmenu
        dimmenu.install()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: dimension menu: %s\n" % error)
    if preview_on():
        _watch_preview()
    try:
        hook_sketch_bar()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sketch pick bar: %s\n" % error)


# --------------------------------------------------------------------------- the right-click rows by pick (pkg212)

# - a circle or an arc: Make Fixed, Preview Sketch Dimension / Select Other, Construction Geometry, Make Block, Zoom to
#   Selection, Exit Sketch, Extruded Boss/Base (Replace Entity, Sketch Numeric Input, Smart Dimension are line-only)

#   Make Fixed, Preview Sketch Dimension; two lines: Horizontal, Vertical, Collinear, Perpendicular, Parallel, Equal
# - a line and a point picked, right-click on the point: the point's second line keeps Make Block
# - a radius or diameter dimension: Display As Radius, Display As Diameter, Preview Sketch Dimension / the sketch line
#   without Extruded Boss/Base
ROW_SECOND_CURVE = ("SelectOther", "ConstructionPlane", "MakeBlock", "ZoomSelection", "ExitSketch", "BossExtrude")
REL_ORDER = ("RelHorizontal", "RelVertical", "RelCollinear", "RelPerpendicular", "RelParallel", "RelEqual",
             "RelMidpoint", "RelOnEdge", "RelCoincident")


def _curve(sketch, element):
    try:
        name = type(sketch.Geometry[int(element[4:]) - 1]).__name__
        return name in ("Circle", "ArcOfCircle", "Ellipse", "ArcOfEllipse")
    except Exception:
        return False


def pick_rows(sketch, element, rows):
    if not rows or element is None:
        return rows
    top, second, pressed = rows
    rc = _rc()
    sh = rc.shell()
    preview = [e for e in top if e.key == PREVIEW]
    picked = rc.picked_elements(sketch)
    if element.startswith("Constraint"):
        try:
            index = int(element[10:]) - 1
            c = sketch.Constraints[index]
        except Exception:
            return rows
        if c.Type in ("Radius", "Diameter"):
            out = []
            for kind, text, icon in (("Radius", rc.T_AS_RADIUS, "DIMENSIONS_RADIAL"),
                                     ("Diameter", rc.T_AS_DIAMETER, "DIMENSIONS_DIAMETER")):
                run = (lambda: None) if c.Type == kind else (lambda: rc.radius_diameter(sketch, index))
                out.append(contextbar.Entry("DisplayAs" + kind, text, _icon(text, icon), _tip(text), run))
                if c.Type == kind:
                    pressed = set(pressed) | {"DisplayAs" + kind}
            try:
                from . import dimdisplay
                out, pressed = dimdisplay.icon_row(sketch, index, out, pressed, _icon, _tip)
            except Exception as _fw_err:
                _fw_log("rcextras.py:dimdisplay row", _fw_err)
            return out + preview, [e for e in second if e.key != "BossExtrude"], pressed
        return rows
    if len(picked) > 1 and sh is not None:
        try:
            items = contextbar.sketch_items(sketch, picked)
            keys = [k for k in contextbar.relation_keys(items) if k not in ("RelConstruction", "RelFix")]
        except Exception:
            keys = []
        keys = sorted(keys, key=lambda k: REL_ORDER.index(k) if k in REL_ORDER else len(REL_ORDER))
        rel = [e for e in (contextbar._command_entry(sh, k) for k in keys) if e is not None]
        fix = [e for e in top if e.key == "Fix"] or [e for e in (_entry(sh, "Fix", ROW_LABELS["Fix"]),) if e is not None]
        top = rel + fix + preview
        if element.startswith("Vertex") and any(p.startswith("Edge") for p in picked) and \
                all(e.key != "MakeBlock" for e in second):
            mb = _entry(sh, "MakeBlock")
            if mb is not None:
                at = next((i + 1 for i, e in enumerate(second) if e.key == "ConstructionPlane"), 1)
                second = second[:at] + [mb] + second[at:]
        return top, second, pressed
    if element.startswith("Edge") and _curve(sketch, element):
        fix = _entry(sh, "Fix", ROW_LABELS["Fix"]) if sh is not None else None
        keep = {e.key: e for e in second}
        return ([fix] if fix is not None else []) + preview, [keep[k] for k in ROW_SECOND_CURVE if k in keep], pressed
    return rows


# --------------------------------------------------------------------------- the pick's context toolbar
def sketch_bar(sketch, subs, relations):
    """The left-click context toolbar of a sketch pick: the icons over its shortcut menu (screen read
    2d), in one row, without Select Other. The top line is the relations that fit the picks (Make
    Horizontal, Make Vertical, Make Fixed for a line; Make Fixed for a point; Parallel, Equal...
    for two lines) and Preview Sketch Dimension; then the sketch line: Construction Geometry, Make
    Block, Zoom to Selection, Replace Entity, Sketch Numeric Input, Smart Dimension, Exit Sketch,
    Extruded Boss/Base (a point: no Make Block, no Extruded Boss/Base)."""
    one_point = len(subs) == 1 and subs[0].startswith("Vertex")
    top, second, _pressed = row_entries(sketch, "point" if one_point else "none")
    out = [e for e in relations if e.key != "RelConstruction"]      # Construction Geometry: second line
    out += [e for e in top if e.key == PREVIEW]
    out += [e for e in second if e.key != "SelectOther"]
    return out


def hook_sketch_bar():
    if getattr(contextbar, "_fw_sketch_bar", False):
        return
    original = contextbar.sketch_entries

    def sketch_entries(shell, sketch, subs, *more, **named):
        relations = original(shell, sketch, subs, *more, **named)
        try:
            if contextbar.sketch_items(sketch, subs) is None:
                return relations        # a dimension or a relation glyph: theirs
            return sketch_bar(sketch, list(subs), relations)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sketch pick bar: %s\n" % error)
            return relations
    contextbar.sketch_entries = sketch_entries
    contextbar._fw_sketch_bar = True


# --------------------------------------------------------------------------- relations while drawing
class _Pending(QtCore.QObject):
    ""


    def __init__(self, sketch, tool, kind):
        super().__init__(Gui.getMainWindow())
        self.sketch, self.tool, self.kind = sketch, tool, kind
        self.count = len(sketch.Geometry)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(100)
        self.tries = 0
        self.locked = False
        if kind in ("Horizontal", "Vertical"):
            self.lock()


    def lock(self):
        tool, kind = self.tool, self.kind
        original = getattr(type(tool), "on_move", None)
        if original is None or not hasattr(tool, "start"):
            return

        def on_move(p, px, _orig=original, _tool=tool):
            result = _orig(_tool, p, px)
            try:
                if _tool.state != _tool.SECOND or getattr(_tool, "segment", None) != getattr(_tool, "LINE", "line"):
                    return result
                a, b = _tool.start, _tool.end_point
                if a is not None and b is not None:
                    end = (b[0], a[1]) if kind == "Horizontal" else (a[0], b[1])
                    _tool.end_point = end
                    _tool.preview([[a, end]])
                    _tool.sug2 = []
                    return []
            except Exception as _fw_err:
                _fw_log("rcextras.py:278", _fw_err)
            return result
        tool.on_move = on_move
        self.locked = True

    def unlock(self):
        if self.locked:
            try:
                del self.tool.on_move
            except Exception as _fw_err:
                _fw_log("rcextras.py:288", _fw_err)
            self.locked = False

    def poll(self):
        self.tries += 1
        try:
            n = len(self.sketch.Geometry)
        except Exception:
            n = self.count
        running = True
        try:
            from .fwsketch import toolbase
            running = toolbase.active() is self.tool
        except Exception as _fw_err:
            _fw_log("rcextras.py:302", _fw_err)
        if n > self.count:
            self.timer.stop()
            self.apply(n)
        elif not running or self.tries > 6000:
            self.timer.stop()
        if not self.timer.isActive():
            self.unlock()
            _pending[:] = [p for p in _pending if p is not self]
            self.deleteLater()

    def apply(self, n):
        import Sketcher
        s = self.sketch
        for i in range(self.count, n):
            if type(s.Geometry[i]).__name__ == "LineSegment" and not s.getConstruction(i):
                break
        else:
            return
        if self.kind == "Fix":
            c = Sketcher.Constraint("Block", i)
        else:
            c = Sketcher.Constraint(self.kind, i)
        doc = s.Document
        doc.openTransaction(ROW_LABELS.get(self.kind, self.kind))
        try:
            s.addConstraint(c)
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: %s: %s\n" % (self.kind, error))
            return
        try:
            s.solve()
        except Exception as _fw_err:
            _fw_log("rcextras.py:337", _fw_err)


_pending = []


def relation_while_drawing(sketch, tool, kind):
    _pending.append(_Pending(sketch, tool, kind))


def pending():
    return [p.kind for p in _pending]


# --------------------------------------------------------------------------- the icon row
def _entry(sh, key, label=None):
    """The catalog command as a row button, greyed when FreeCAD cannot run it now."""
    try:
        e = contextbar._command_entry(sh, key)
    except Exception:
        e = None
    if e is not None:
        if label:
            e = contextbar.Entry(e.key, label, e.icon, _tip(label), e.run, e.enabled)
        return e
    try:
        b = sh.binding(key)
        name = label or b.cmd.label
        return contextbar.Entry(key, name, b.icon(), _tip(name), lambda: None, False)
    except Exception:
        return None


def row_kind(sketch, element=None, tool=None):
    """'line', 'point' or 'none' for the top line of the icon row."""
    if tool is not None:
        title = ""
        try:
            title = tool.title()
        except Exception as _fw_err:
            _fw_log("rcextras.py:377", _fw_err)
        mid = False
        try:
            mid = not tool.is_first_state()
        except Exception as _fw_err:
            _fw_log("rcextras.py:382", _fw_err)
        if "Spline" in title and mid:
            return "point"
        if mid and hasattr(tool, "_end_chain"):
            return "line"
    if element is None and sketch is not None and tool is not None:
        p = _rc().picked_elements(sketch)
        if p and all(e.startswith("Edge") for e in p):
            element = p[0]
    if element is None:
        return "none"
    if element.startswith("Vertex"):
        return "point"
    if element == "RootPoint":
        return "origin"
    if element.startswith("Edge"):
        try:
            g = sketch.Geometry[int(element[4:]) - 1]
            name = type(g).__name__
            if name == "LineSegment":
                return "line"
            return "spline" if "BSpline" in name else "none"     # Make Fixed, Preview (read 2d), 9 below
        except Exception:
            return "none"
    return "none"


def row_entries(sketch, kind="none", tool=None):
    """(top line, second line, keys shown pressed)."""
    rc = _rc()
    sh = rc.shell()
    if sh is None:
        return [], [], set()
    drawing = tool is not None and kind == "line" and hasattr(tool, "_end_chain")
    top = []
    for key in ROW_TOP.get(kind, ROW_TOP["none"]):
        if key == "PreviewSketchDimension":
            top.append(contextbar.Entry(key, T_PREVIEW, _icon(T_PREVIEW, "SKETCH_PREVIEW_DIMENSION"),
                                        _tip(T_PREVIEW, "Shows the dimension of a picked line, circle or arc"),
                                        toggle_preview))
            continue
        label = ROW_LABELS.get(key)
        e = _entry(sh, key, label)
        if e is None:
            continue
        if drawing:
            e = contextbar.Entry(key, label, e.icon, _tip(label, "Goes on the segment the next click places"),
                                 lambda k=key, t=tool: relation_while_drawing(sketch, t, k), True)
        top.append(e)
    second = []
    for key in (ROW_SECOND_POINT if kind in ("point", "origin") and tool is None else ROW_SECOND):
        if key == "SelectOther":
            second.append(contextbar.Entry(key, rc.T_SELECT_OTHER, _icon(rc.T_SELECT_OTHER, "SELECT_OTHER"),
                                           _tip(rc.T_SELECT_OTHER, rc.T_SELECT_OTHER_TIP), rc.select_other))
        elif key == "SketchNumericInput":
            second.append(contextbar.Entry(key, T_NUMERIC, _icon(T_NUMERIC, "SKETCH_NUMERIC_INPUT"),
                                           _tip(T_NUMERIC, "Length and angle boxes beside the pointer while drawing"),
                                           toggle_numeric_input))
        elif key == "ConstructionPlane":
            # a picked line, arc or curve: toggles it; nothing picked: FreeCAD's construction mode for what is drawn

            live = rc._has_sketch_pick() or not Gui.Selection.getSelectionEx("", 0)
            e = _entry(sh, key) if live else None
            if e is not None:
                second.append(e)
        elif key == "ZoomSelection":
            e = _entry(sh, key) if Gui.Selection.getSelectionEx("", 0) else None      # same: only with a pick
            if e is not None:
                second.append(contextbar.Entry(key, e.label, e.icon, e.tip, rc.zoom_to_selection))
        else:
            e = _entry(sh, key)
            if e is not None:
                second.append(e)
    pressed = set()
    if preview_on():
        pressed.add("PreviewSketchDimension")
    if numeric_input_on():
        pressed.add("SketchNumericInput")
    title = ""
    try:
        title = tool.title() if tool is not None else ""
    except Exception as _fw_err:
        _fw_log("rcextras.py:457", _fw_err)
    if "Dimension" in title:
        pressed.add("SmartDimension")
    return top, second, pressed


def rows_in_menus():
    ""

    try:
        from . import customizedlg
        return bool(customizedlg.option("ShowInShortcutMenu"))
    except Exception:
        return True


def add_rows(menu, top, second, pressed=(), third=None):
    """The icon row over the menu: two (an assembly face: three) lines of buttons, the menu's own
    items where they were. None when Show in shortcut menu is off."""
    if not rows_in_menus():
        return []
    rc = _rc()
    sh = rc.shell()
    bar = getattr(sh, "context", None)
    holder = QtWidgets.QWidget(menu)
    holder.setObjectName("SWContextMenuRows")
    layout = QtWidgets.QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    rows = []
    for entries in (top, second, third):
        if not entries:
            continue
        row = contextbar.MenuRow(entries, holder)
        for b in row.buttons:
            if b.entry.key in pressed:
                b.setCheckable(True)
                b.setChecked(True)
        if bar is not None:
            row.chosen.connect(lambda entry, m=menu: bar._menu_chosen(m, entry))
        else:
            row.chosen.connect(lambda entry, m=menu: (m.close(), QtCore.QTimer.singleShot(0, entry.run)))
        layout.addWidget(row)
        rows.append(row)
    if not rows:
        return []
    action = QtWidgets.QWidgetAction(menu)
    action.setDefaultWidget(holder)
    actions = menu.actions()
    first = actions[0] if actions else None
    before = menu.geometry()
    menu.insertAction(first, action)
    if first is not None:
        menu.insertSeparator(first)
    menu.setProperty("swContextRow", True)
    menu.resize(menu.sizeHint())
    if menu.isVisible():
        grown = menu.height() - before.height()
        top_y = before.y() - grown
        screen = menu.screen().availableGeometry() if menu.screen() is not None else None
        if screen is not None:
            top_y = max(screen.top(), top_y)
        menu.move(before.x(), top_y)
    if bar is not None:
        bar.menu_row = rows[-1]
    menu.setProperty("swRowKeys", [[b.entry.key for b in r.buttons] for r in rows])
    return rows


# --------------------------------------------------------------------------- view and options
def set_view_menu(more=False):
    rc = _rc()
    try:
        from . import namedviews
    except Exception:
        return None
    items = [rc.action("SetView" + key, key, lambda k=key: namedviews.set_current_as(k, ask=True))
             for key in namedviews.SETTABLE]
    return rc.submenu("SetCurrentView", T_SET_VIEW, items, more)


def relations_snaps_options():
    try:
        from . import options
        box = options.OptionsDialog(tab=0)
        box.select("Relations/Snaps")
        options._open.append(box)
        try:
            box.exec()
        finally:
            options._open.remove(box)
            box.deleteLater()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Relations/Snaps Options: %s\n" % error)


def relations_snaps_item(more=True):
    return _rc().action("RelationsSnapsOptions", T_RS_OPTIONS, relations_snaps_options, more=more)


def properties(tool, sketch):
    """Properties... while a tool runs: the tool ends and the picked entities' own page shows
    (relationspm's Line Properties, Point, Arc ...), the picks kept."""
    rc = _rc()
    kept = rc.picks()
    rc._end_tool(tool)

    def again():
        try:
            Gui.Selection.clearSelection()
            for doc, name, sub in kept:
                Gui.Selection.addSelection(doc, name, sub)
        except Exception as _fw_err:
            _fw_log("rcextras.py:570", _fw_err)
    QtCore.QTimer.singleShot(50, again)


# --------------------------------------------------------------------------- dimension items
def value_text(sketch, index):
    c = sketch.Constraints[index]
    if c.Type == "Angle":
        decimals = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
        return "%.*f" % (decimals, math.degrees(abs(c.Value)))
    return length_text(c.Value)


def _flags(sketch, prop):
    try:
        return list(getattr(sketch, prop))
    except Exception:
        return []


def _set_flags(sketch, prop, values):
    if not hasattr(sketch, prop):
        sketch.addProperty("App::PropertyStringList", prop, "FreeCAD",
                           "Sketch dimension settings kept for drawings")
        try:
            sketch.setEditorMode(prop, 2)
        except Exception as _fw_err:
            _fw_log("rcextras.py:597", _fw_err)
    setattr(sketch, prop, values)


def display_flag(sketch, index, flag):
    key = "%s:%s" % (_rc()._mark_key(sketch, index), flag)
    return key in _flags(sketch, DISPLAY_PROP)


def toggle_display_flag(sketch, index, flag):
    rc = _rc()

    def body():
        key = "%s:%s" % (rc.stable_key(sketch, index), flag)
        now = _flags(sketch, DISPLAY_PROP)
        on = key not in now
        _set_flags(sketch, DISPLAY_PROP, now + [key] if on else [k for k in now if k != key])
        if flag == "CenterDimension" and on:
            _center_label(sketch, index)
    rc._sketch_transaction(sketch, dict(DISPLAY_FLAGS + (("HideDimLine", T_HIDE_DIM_LINE),)).get(flag, flag), body)



# block of a linear or angular dimension (Beginners-1 video, 8:30). FreeCAD draws a sketch dimension as one
# piece, so the sketch keeps the choice as a display flag (FWDimDisplay "...:HideDimLine") for drawings'
# model items, and the row reads back what is set.
T_HIDE_DIM_LINE = "Hide Dimension Line"
T_SHOW_DIM_LINE = "Show Dimension Line"
LINE_DIMS = ("Distance", "DistanceX", "DistanceY", "Angle")


def hide_dimension_line_item(sketch, index):
    try:
        if sketch.Constraints[index].Type not in LINE_DIMS:
            return None
    except Exception:
        return None
    hidden = display_flag(sketch, index, "HideDimLine")
    return _rc().action("HideDimensionLine", T_SHOW_DIM_LINE if hidden else T_HIDE_DIM_LINE,
                        lambda: _toggle_dim_line(sketch, index))


T_DIM_LINE_NOTE = "Dimension line %s in drawings (the sketch shows the whole dimension)."


def _toggle_dim_line(sketch, index):
    toggle_display_flag(sketch, index, "HideDimLine")
    try:
        hidden = display_flag(sketch, index, "HideDimLine")
        Gui.getMainWindow().statusBar().showMessage(T_DIM_LINE_NOTE % ("hidden" if hidden else "shown"), 6000)
    except Exception as _fw_err:
        _fw_log("rcextras.py:648", _fw_err)


def _center_label(sketch, index):
    for name in ("setLabelPosition", "moveDatumLabelPosition"):
        fn = getattr(sketch, name, None)
        if fn is not None:
            try:
                fn(index, 0.0)
                return True
            except Exception as _fw_err:
                _fw_log("rcextras.py:659", _fw_err)
    return False


def display_options_menu(sketch, index, as_kind=None, more=()):
    ""


    rc = _rc()
    flags = DISPLAY_FLAGS if as_kind is None else tuple(f for f in DISPLAY_FLAGS if f[0] != "OffsetText")
    items = [rc.action(key, text, lambda k=key: toggle_display_flag(sketch, index, k),
                       checked=display_flag(sketch, index, key)) for key, text in flags]
    if as_kind is not None:
        items.insert(1, as_kind)
        try:
            from . import dimdisplay
            items = dimdisplay.display_options(sketch, index, items)
        except Exception as _fw_err:
            _fw_log("rcextras.py:dimdisplay", _fw_err)
    items += [i for i in more if i is not None]
    return rc.submenu("DisplayOptions", T_DISPLAY_OPTIONS, items)


def annotation_view(sketch, index):
    key = _rc()._mark_key(sketch, index) + ":"
    for v in _flags(sketch, VIEW_PROP):
        if v.startswith(key):
            return v[len(key):]
    return UNASSIGNED


def select_annotation_view(sketch, index):
    rc = _rc()
    now = annotation_view(sketch, index)
    views = list(ANNOTATION_VIEWS)
    choice, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Select Annotation View",
                                                "Annotation view:", views, views.index(now) if now in views else 0,
                                                False)
    if not ok:
        return
    def body():
        key = rc.stable_key(sketch, index) + ":"
        values = [v for v in _flags(sketch, VIEW_PROP) if not v.startswith(key)]
        if choice != UNASSIGNED:
            values.append(key + choice)
        _set_flags(sketch, VIEW_PROP, values)
    rc._sketch_transaction(sketch, "Select Annotation View", body)


def can_reverse(sketch, index):
    # skrmb-1127: a line-length (aligned) dimension has Reverse Direction too (read 11-19); radius and diameter have none
    return sketch.Constraints[index].Type in ("DistanceX", "DistanceY", "Angle") or _aligned_ends(sketch, index) is not None


def _aligned_ends(sketch, index):
    """(fixed point, (geo, pos) of the point that moves) of a point-to-point or line-length Distance, else None."""
    c = sketch.Constraints[index]
    if c.Type != "Distance":
        return None
    try:
        if c.FirstPos in (1, 2) and c.Second >= 0 and c.SecondPos in (1, 2):
            return sketch.getPoint(c.First, c.FirstPos), (c.Second, c.SecondPos)
        if c.FirstPos == 0 and c.Second < 0 and type(sketch.Geometry[c.First]).__name__ == "LineSegment":
            return sketch.getPoint(c.First, 1), (c.First, 2)
    except Exception:
        return None
    return None


def reverse_direction(sketch, index):
    """The dimensioned geometry goes to the other side: a horizontal or vertical distance changes
    sign, an angle is measured the other way round."""
    rc = _rc()
    c = sketch.Constraints[index]

    def body():
        ends = _aligned_ends(sketch, index) if c.Type == "Distance" else None
        if ends is not None:        # skrmb-1127: the moving end goes to the other side of the fixed one
            fixed, (geo, pos) = ends
            moving = sketch.getPoint(geo, pos)
            sketch.moveGeometry(geo, pos, fixed - (moving - fixed), False)
            sketch.recompute()
        elif c.Type == "Angle":
            sketch.setDatum(index, App.Units.Quantity(-c.Value, App.Units.Unit(0, 0, 0, 0, 0, 0, 0, 1)))
        else:
            sketch.setDatum(index, App.Units.Quantity(-c.Value, App.Units.Length))
    rc._sketch_transaction(sketch, T_REVERSE, body)


def linked_names(sketch):
    out = []
    for i, c in enumerate(sketch.Constraints):
        if c.Name and c.Type in _rc().DIMENSION_TYPES and _is_link_master(sketch, i):
            out.append(c.Name)
    return out


def _is_link_master(sketch, index):
    try:
        return ("%s:LinkMaster" % sketch.Constraints[index].Name) in _flags(sketch, DISPLAY_PROP)
    except Exception:
        return False


T_UNLINK_VALUE = "Unlink Value"


def _equations():
    """features' part-wide linked values (equations.link_value, features/89), or None."""
    try:
        from . import equations
        return equations if hasattr(equations, "link_value") else None
    except Exception:
        return None


def _path(index):
    return "Constraints[%d]" % index


def linked_value_name(sketch, index):
    eq = _equations()
    if eq is None:
        return None
    try:
        return eq.linked_name(sketch, _path(index)) or eq.linked_name(sketch, "." + _path(index))
    except Exception:
        return None


def unlink_item(sketch, index):
    ""
    if linked_value_name(sketch, index) is None:
        return None
    rc = _rc()
    return rc.action("UnlinkValue", T_UNLINK_VALUE, lambda: unlink_value(sketch, index))


def unlink_value(sketch, index):
    eq = _equations()
    if eq is None:
        return
    doc = sketch.Document
    doc.openTransaction(T_UNLINK_VALUE)
    try:
        path = _path(index)
        if not eq.linked_name(sketch, path):
            path = "." + path
        eq.unlink_value(sketch, path)
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: Unlink Value: %s\n" % error)


def link_values(sketch, index):
    ""


    eq = _equations()
    if eq is not None:
        names = eq.linked_values(sketch.Document)
        current = linked_value_name(sketch, index)
        name, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Shared Values", "Name:", names or [""],
                                                  names.index(current) if current in names else 0, True)
        name = (name or "").strip()
        if not ok or not name:
            return
        doc = sketch.Document
        doc.openTransaction(T_LINK_VALUES)
        try:
            eq.link_value(sketch, _path(index), name)
            doc.commitTransaction()
        except Exception as error:
            doc.abortTransaction()
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), T_LINK_VALUES, str(error))
        return
    rc = _rc()
    names = linked_names(sketch)
    c = sketch.Constraints[index]
    name, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Shared Values", "Name:", names or [""], 0, True)
    name = (name or "").strip()
    if not ok or not name:
        return
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if safe[:1].isdigit():
        safe = "_" + safe

    def body():
        master = None
        for i, other in enumerate(sketch.Constraints):
            if other.Name == safe and i != index:
                master = i
        if master is None:
            if c.Name != safe:
                sketch.renameConstraint(index, safe)
            _set_flags(sketch, DISPLAY_PROP, _flags(sketch, DISPLAY_PROP) + ["%s:LinkMaster" % safe])
            return
        if sketch.Constraints[master].Type != c.Type and "Angle" in (c.Type, sketch.Constraints[master].Type):
            raise ValueError("an angle cannot share a value with a length")
        sketch.setExpression("Constraints[%d]" % index, "Constraints.%s" % safe)
    rc._sketch_transaction(sketch, T_LINK_VALUES, body)


# --------------------------------------------------------------------------- annotations
ANNOTATIONS = (
    ("Note", "Note...", "TEXT"), ("Balloon", "Balloon...", "BALLOON"),
    ("StackedBalloon", "Stacked Balloon...", "STACK"), ("SurfaceFinish", "Surface Finish Symbol...", "√ Ra 3.2"),
    ("WeldSymbol", "Weld Symbol...", "◣"), ("GeometricTolerance", "Geometric Tolerance...", "⌖ | 0.1 | A"),
    ("DatumFeature", "Datum Feature Symbol...", "DATUM"), ("DatumTarget", "Datum Target...", "TARGET"),
)
GROUP = "Annotations"


def _anchor(sketch, index):
    """A point near the dimension, in the model."""
    c = sketch.Constraints[index]
    try:
        g = sketch.Geometry[c.First] if c.First >= 0 else None
        p = g.toShape().BoundBox.Center if g is not None else App.Vector()
    except Exception:
        p = App.Vector()
    return sketch.getGlobalPlacement().multVec(p)


def _group(doc):
    g = doc.getObject("FWAnnotations")
    if g is None:
        g = doc.addObject("App::DocumentObjectGroup", "FWAnnotations")
        g.Label = GROUP
    return g


def _next_label(doc, prefix, letters=False):
    used = [o.LabelText[0] for o in doc.Objects if o.TypeId == "App::AnnotationLabel" and
            o.Name.startswith("FW" + prefix) and o.LabelText]
    if letters:
        for ch in "ABCDEFGHJKLMNPRSTUVWXYZ":
            if ch not in used:
                return ch
        return "A"
    n = 1
    while str(n) in used:
        n += 1
    return str(n)


def add_annotation(sketch, index, kind):
    doc = sketch.Document
    if kind == "Note":
        text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Note", "Note text:")
        if not ok or not text:
            return None
        lines = text.split("\n")
    elif kind == "Balloon":
        lines = [_next_label(doc, "Balloon")]
    elif kind == "StackedBalloon":
        first = int(_next_label(doc, "StackedBalloon"))
        lines = [str(first), str(first + 1)]
    elif kind == "DatumFeature":
        lines = [_next_label(doc, "DatumFeature", True)]
    elif kind == "DatumTarget":
        lines = [_next_label(doc, "DatumTarget", True) + "1"]
    else:
        lines = [dict((k, d) for k, _t, d in ANNOTATIONS)[kind]]
    doc.openTransaction(dict((k, t) for k, t, _d in ANNOTATIONS).get(kind, kind).rstrip("."))
    try:
        a = doc.addObject("App::AnnotationLabel", "FW" + kind)
        a.LabelText = lines
        at = _anchor(sketch, index)
        a.BasePosition = at
        a.TextPosition = at + App.Vector(5, 5, 0)
        a.Label = "%s %s" % (dict((k, t) for k, t, _d in ANNOTATIONS)[kind].rstrip("."), lines[0])
        _group(doc).addObject(a)
        doc.commitTransaction()
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: %s: %s\n" % (kind, error))
        return None
    doc.recompute()
    return a


def area_hatch(sketch):
    """Area Hatch/Fill: the sketch's closed regions filled (a hatch face in the Annotations folder)."""
    doc = sketch.Document
    doc.openTransaction("Area Hatch/Fill")
    try:
        f = doc.addObject("Part::Face", "FWAreaHatch")
        f.Sources = [sketch]
        f.Label = "Area Hatch"
        _group(doc).addObject(f)
        doc.recompute()
        if not f.isValid():
            # the sketch also has open entities (an arc, a spline...): Part's Face takes none of it. Fill the closed

            doc.removeObject(f.Name)
            import Part
            wires = [w for w in sketch.Shape.Wires if w.isClosed()]
            faces = []
            for w in wires:
                try:
                    faces.append(Part.Face(w))
                except Exception as _fw_err:
                    _fw_log("rcextras.py:area hatch wire", _fw_err)
            if not faces:
                raise ValueError("the sketch has no closed region")
            f = doc.addObject("Part::Feature", "FWAreaHatch")
            f.Shape = Part.makeCompound(faces)
            f.Label = "Area Hatch"
            _group(doc).addObject(f)
            doc.recompute()
        try:
            f.ViewObject.Transparency = 60
            f.ViewObject.LineColor = (0.2, 0.2, 0.2, 1.0)
        except Exception as _fw_err:
            _fw_log("rcextras.py:925", _fw_err)
        doc.commitTransaction()
        return f
    except Exception as error:
        doc.abortTransaction()
        App.Console.PrintWarning("FreeCAD: Area Hatch/Fill: %s\n" % error)
        return None


class _Painter:
    """Format Painter: the next dimensions picked in the sketch take this one's display options."""

    def __init__(self, sketch, index):
        self.sketch, self.flags = sketch, [k.split(":", 1)[1] for k in _flags(sketch, DISPLAY_PROP)
                                            if k.startswith(_rc()._mark_key(sketch, index) + ":")
                                            and not k.endswith(":LinkMaster")]
        self.source = index

    def addSelection(self, doc, name, sub, point):
        QtCore.QTimer.singleShot(0, lambda: self.paint(doc, name, sub))

    def paint(self, doc, name, sub):
        rc = _rc()
        s = self.sketch
        try:
            if contextbar.sketch_in_edit() is not s:
                stop_painter()
                return
        except Exception as _fw_err:
            _fw_log("rcextras.py:954", _fw_err)
        element = rc._sketch_element(s, (doc, name, sub))
        i = rc.constraint_index(element or "")
        if i is None or i == self.source or s.Constraints[i].Type not in rc.DIMENSION_TYPES:
            return
        key = rc._mark_key(s, i) + ":"

        def body():
            keep = [k for k in _flags(s, DISPLAY_PROP) if not k.startswith(key) or k.endswith(":LinkMaster")]
            _set_flags(s, DISPLAY_PROP, keep + [key + f for f in self.flags])
        rc._sketch_transaction(s, "Format Painter", body)


_painter = []


def format_painter(sketch, index):
    stop_painter()
    p = _Painter(sketch, index)
    try:
        Gui.Selection.addObserver(p)
        _painter.append(p)
    except Exception as _fw_err:
        _fw_log("rcextras.py:977", _fw_err)
    try:
        Gui.getMainWindow().statusBar().showMessage("Format Painter: pick the dimensions to take the format", 5000)
    except Exception as _fw_err:
        _fw_log("rcextras.py:981", _fw_err)


def stop_painter():
    while _painter:
        try:
            Gui.Selection.removeObserver(_painter.pop())
        except Exception as _fw_err:
            _fw_log("rcextras.py:989", _fw_err)


def annotations_menu(sketch, index):
    rc = _rc()
    items = [rc.action(key, text, lambda k=key: add_annotation(sketch, index, k),
                       icon=_icon(text.rstrip("."), "ANNOTATIONS_" + key.upper()))
             for key, text, _d in ANNOTATIONS]
    items.append(rc.action("AreaHatch", "Area Hatch/Fill", lambda: area_hatch(sketch),
                           icon=_icon("Area Hatch", "ANNOTATIONS_AREA_HATCH")))
    block = rc.entry("InsertBlock", "Insert Block")
    if block is not None:
        items.append(block)
    items.append(rc.action("FormatPainter", "Format Painter", lambda: format_painter(sketch, index),
                           icon=_icon("Format Painter", "FORMAT_PAINTER")))
    return rc.submenu("Annotations", T_ANNOTATIONS, items)
