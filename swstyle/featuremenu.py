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
from PySide import QtCore, QtGui, QtWidgets

from . import paths, rcmenus
from .widgets import alive

Qt = QtCore.Qt

PARAM = "FeatureMenu"
TYPES = ("PartDesign::Pad", "PartDesign::Pocket")       # Reverse Direction and end conditions
SKIP = ("Sketcher::SketchObject", "Assembly::AssemblyObject")
LAST = rcmenus.LAST


def enabled():
    return paths.params().GetBool(PARAM, True)


def page():
    ""
    try:
        from . import filletpm
        p = filletpm.current()
        return p if p is not None and not getattr(p, "closing", False) else None
    except Exception:
        return None


def _in_edit():
    try:
        vp = Gui.ActiveDocument.getInEdit()
        return getattr(vp, "Object", None) if vp is not None else None
    except Exception:
        return None


def _dialog_open():
    try:
        return bool(Gui.Control.activeDialog())
    except Exception:
        return False


def edited():
    ""
    p = page()
    if p is not None:
        return getattr(p, "feature", None) or p
    if not _dialog_open():
        return None
    if _mate_panel() is not None:
        return MATE
    obj = _in_edit()
    if obj is None:



        # ready yet: Extrude, Revolve, Rib, Base Flange ...): its Cancel is there, so it gets the menu,

        # keep FreeCAD's own menu and their Finish / Close items
        if _sketch3d_open():
            return None
        if _button(QtWidgets.QDialogButtonBox.AcceptRole) is None:
            if _button(QtWidgets.QDialogButtonBox.RejectRole) is None or not _own_page():
                return None
        return PM
    t = getattr(obj, "TypeId", "")
    if t in SKIP or not (t.startswith("PartDesign::") or t.startswith("Part::")):
        return None
    return obj


PM = "PropertyManager"      # edited() for a PropertyManager with no object in edit
MATE = "Mate"               # edited() for the assembly's Mate PropertyManager


def _mate_panel():
    try:
        from . import asmviewmenu
        return asmviewmenu.mate_panel()
    except Exception:
        return None


def _sketch3d_open():
    try:
        from . import sketch3d
        return bool(sketch3d.editing())
    except Exception:
        return False


def _own_page():
    ""
    try:
        window = Gui.getMainWindow()
        for w in window.findChildren(QtWidgets.QWidget):
            if w.property("swstyle_pm_title") and w.isVisible() and _class_chain(w):
                return True
    except Exception as _fw_err:
        _fw_log("featuremenu.py:own-page", _fw_err)
    return False


def _class_chain(w):
    while w is not None:
        try:
            if w.metaObject().className() == "Gui::TaskView::TaskView":
                return True
            w = w.parentWidget()
        except RuntimeError:
            return False
    return False


def _button(role):
    ""

    try:
        window = Gui.getMainWindow()
    except Exception:
        return None
    for box in window.findChildren(QtWidgets.QDialogButtonBox):
        if not _class_chain(box):
            continue
        for b in box.buttons():
            if box.buttonRole(b) == role and b.isEnabled():
                return b
    return None


def ok():
    p = page()
    if p is not None:
        p.accept()
        return
    b = _button(QtWidgets.QDialogButtonBox.AcceptRole)
    if b is None:
        return
    try:
        from . import pmkeys
        pmkeys.accept(b)
    except Exception:
        b.click()


def cancel():
    p = page()
    if p is not None:
        p.reject()
        return
    b = _button(QtWidgets.QDialogButtonBox.RejectRole)
    if b is not None:
        b.click()


def _visible(cls, name):
    window = Gui.getMainWindow()
    for w in window.findChildren(cls, name):
        if w.isVisible() and _class_chain(w):
            return w
    for w in window.findChildren(cls, name):
        if _class_chain(w):
            return w
    return None


def _pick(combo, index):
    """As if the person chose it in the list: pmfields acts on activated, not on the index."""
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


# ---------------------------------------------------------------- Clear Selections
def clearable():
    """(what to clear, how) for the active selection box, else None."""
    p = page()
    if p is not None:
        active = getattr(p, "active", "items")
        if active == "multi" and getattr(p, "multi", None):
            return p.clear_multi
        if active == "plane" and getattr(p, "plane", None) is not None:
            def clear_plane(p=p):
                p.plane = None
                p.update()
            return clear_plane
        if getattr(p, "items", None):
            return p.clear_items
        return None
    try:
        from . import extrudepm
        for pick in getattr(extrudepm, "_picks", []):
            box = getattr(pick, "box", None)
            if box is not None and alive(box) and box.isVisible() and box.text():
                return pick.clear
    except Exception as _fw_err:
        _fw_log("featuremenu.py:212", _fw_err)
    if Gui.Selection.getSelectionEx("", 0):
        return lambda: Gui.Selection.clearSelection()
    return None


def _page_type(p=None):
    p = p if p is not None else page()
    if p is not None:
        return getattr(p, "TYPE", None)
    obj = edited()
    return getattr(obj, "TypeId", None)


def right_click_accepts(on_model=False):
    ""


    if on_model:
        return False        # only a right-click in empty space is OK; on the model the menu opens
    p = page()
    if p is None:
        return False
    try:
        from . import filletpm
        if p.TYPE == filletpm.SHELL:
            if getattr(p, "_fw_rc_tried", False):
                return False
            p._fw_rc_tried = True
            return True
        if p.TYPE not in (filletpm.FILLET, filletpm.CHAMFER):
            return False
        return not p.missing() and bool(p.ok)
    except Exception:
        return False


def _check_by_text(text):
    try:
        window = Gui.getMainWindow()
    except Exception:
        return None
    for w in window.findChildren(QtWidgets.QCheckBox):
        try:
            if w.text() == text and _class_chain(w):
                return w
        except RuntimeError:
            continue
    return None


def _mirror(key, text, box):
    """A menu item that is the PropertyManager's own check box (ticked and greyed as it is)."""
    if box is None:
        return None
    return rcmenus.action(key, text, lambda: alive(box) and box.click(), checked=box.isChecked(),
                          enabled=box.isEnabled(), tip=box.toolTip())


def _selection_items():
    out = []
    try:
        from . import boxselect
        for kind in ("Box", "Lasso"):
            out.append(rcmenus.action(kind + "Select", "%s Selection" % kind, lambda k=kind: boxselect.set_bulk(k)))
    except Exception as _fw_err:
        _fw_log("featuremenu.py:278", _fw_err)
    out.append(rcmenus.action("SelectOther", rcmenus.T_SELECT_OTHER, rcmenus.select_other))
    clear = clearable()
    if clear is not None:       # pkg260: nothing picked, nothing to clear: left out, not greyed (no dead controls)
        out.append(rcmenus.action("ClearSelections", rcmenus.T_CLEAR, clear))
    try:
        from . import selman
        sm = selman.menu_action()   # None when no page takes model picks: left out, not greyed
        if sm is not None:
            out.append(sm)
    except Exception as _fw_err:
        _fw_log("featuremenu.py:selman", _fw_err)
    out.append(rcmenus.zoom_menu())

    # PM's graphics-area menu (pmconfirm.view_menu); Qt's Windows icons only when those cannot be had
    style = QtWidgets.QApplication.style()
    ok_icon = cancel_icon = None
    try:
        from . import pmconfirm
        from .propertymanager import OK_GREEN
        ok_icon = pmconfirm._icon("CHECK_MARK", OK_GREEN)
        cancel_icon = pmconfirm._icon("STANDARD_CANCEL")
    except Exception as _fw_err:
        _fw_log("featuremenu.py:icons", _fw_err)
    if ok_icon is None or ok_icon.isNull():
        ok_icon = style.standardIcon(QtWidgets.QStyle.SP_DialogApplyButton)
    if cancel_icon is None or cancel_icon.isNull():
        cancel_icon = style.standardIcon(QtWidgets.QStyle.SP_DialogCancelButton)
    if page() is not None or _mate_panel() is not None or _button(QtWidgets.QDialogButtonBox.AcceptRole) is not None:
        # pkg427: a page whose OK is not ready yet leaves OK out (not greyed: no dead controls, as pkg260)
        out.append(rcmenus.action("OK", rcmenus.T_OK, ok, icon=ok_icon))
    out.append(rcmenus.action("Cancel", rcmenus.T_CANCEL, cancel, icon=cancel_icon))
    return out


def _direction_items():
    out = []
    reverse = _visible(QtWidgets.QAbstractButton, "SWStyle_ReverseDirection") or \
        _visible(QtWidgets.QCheckBox, "checkBoxReversed")
    end = _visible(QtWidgets.QComboBox, "SWStyle_EndCondition")
    if (reverse is None or not reverse.isEnabled()) and (end is None or not end.isEnabled()):
        return out
    out.append(rcmenus.header("Direction 1", "HeaderDirection1"))
    if reverse is not None and reverse.isEnabled():
        out.append(rcmenus.action("ReverseDirection", "Reverse Direction",
                                  lambda: alive(reverse) and reverse.click()))
    if end is not None and end.isEnabled():
        for i in range(end.count()):
            out.append(rcmenus.action("End%d" % i, end.itemText(i), lambda i=i: alive(end) and _pick(end, i),
                                      checked=i == end.currentIndex()))
    second = _visible(QtWidgets.QCheckBox, "SWStyle_Direction2")
    mode2 = _visible(QtWidgets.QComboBox, "changeMode2")
    if second is not None and second.isEnabled():
        out.append(rcmenus.header("Direction 2", "HeaderDirection2"))
        on = second.isChecked()
        out.append(rcmenus.action("Direction2Off", "Direction 2 Off",
                                  lambda: alive(second) and second.isChecked() and second.click(), checked=not on))
        current = _side2_current(mode2) if on else None
        for text in DIRECTION2_ITEMS:
            if _side2_index(mode2, text) is None and mode2 is not None:
                continue
            out.append(rcmenus.action("End2_" + text.replace(" ", ""), text,
                                      lambda t=text: _set_side2(second, t), checked=current == text))
    return out



DIRECTION2_ITEMS = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Up To Body")
SIDE2_MODES = {"Blind": ("Blind", "Dimension", "Length"), "Up To Vertex": ("Up To Surface", "Up to face", "UpToFace"),
               "Up To Surface": ("Up To Surface", "Up to face", "UpToFace"),
               "Offset From Surface": ("Up To Surface", "Up to face", "UpToFace"),
               "Up To Body": ("Up To Body", "Up to shape", "UpToShape")}


def _side2_index(mode2, text):
    if mode2 is None:
        return None
    for name in SIDE2_MODES.get(text, ()):
        i = mode2.findText(name)
        if i >= 0:
            return i
    return None


def _side2_current(mode2):
    if mode2 is None:
        return None
    now = mode2.currentText()
    for text in ("Blind", "Up To Surface", "Up To Body"):
        if now in SIDE2_MODES[text]:
            return text
    return None


def _set_side2(second, text):
    if not alive(second):
        return
    if not second.isChecked():
        second.click()

    def pick(tries=0):
        mode2 = _visible(QtWidgets.QComboBox, "changeMode2")
        i = _side2_index(mode2, text)
        if i is None:
            if tries < 10:
                QtCore.QTimer.singleShot(50, lambda: pick(tries + 1))
            return
        _pick(mode2, i)
    pick()


def _panel_of(widget):
    ""
    import gc
    if widget is None:
        return None
    for r in gc.get_referrers(widget):
        if isinstance(r, dict):
            for o in gc.get_referrers(r):
                if getattr(o, "__dict__", None) is r and hasattr(o, "accept"):
                    return o
    return None


class _DepthPick:
    """Up To Vertex / Up To Surface / Offset From Surface for a page that has only a depth box:
    the next vertex or face picked sets the depth to its distance from the sketch plane."""

    def __init__(self):
        self.spin = self.plane = None
        self.kind, self.offset = "", 0.0
        self.on = False

    def start(self, spin, plane, kind, offset=0.0):
        self.stop()
        self.spin, self.plane, self.kind, self.offset = spin, plane, kind, offset
        Gui.Selection.addObserver(self)
        self.on = True
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "%s: pick a %s" % (kind, "vertex" if kind == "Up To Vertex" else "face"), 8000)
        except Exception as _fw_err:
            _fw_log("featuremenu.py:397", _fw_err)

    def stop(self):
        if self.on:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("featuremenu.py:404", _fw_err)
        self.on = False

    def addSelection(self, doc, name, sub, point):
        leaf = (sub or "").split(".")[-1]
        want = "Vertex" if self.kind == "Up To Vertex" else "Face"
        mid = rcmenus.midpoint_pick(doc, name, sub) if want == "Vertex" and leaf.startswith("Edge") else None
        if not leaf.startswith(want) and mid is None:   # pkg228: an edge's Select Midpoint counts as a vertex
            return
        self.stop()
        try:
            obj = App.getDocument(doc).getObject(name)
            el = obj.getSubObject(sub)
            p = mid if mid is not None else (el.Point if want == "Vertex" else el.CenterOfMass)
        except Exception:
            p = App.Vector(*point)
        base, normal = self.plane
        depth = abs((p - base).dot(normal)) + self.offset
        if alive(self.spin) and depth > 1e-6:
            self.spin.setValue(depth)
        QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)


DEPTH_PICK = _DepthPick()


FLANGE_END1 = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface", "Mid Plane")
FLANGE_END2 = ("Blind", "Up To Vertex", "Up To Surface", "Offset From Surface")


def _sketch_plane(panel):
    obj = getattr(panel, "obj", None)
    sketch = getattr(obj, "BendSketch", None)
    if sketch is None:
        return None
    pl = sketch.getGlobalPlacement()
    return pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))


def _end_to(panel, combo, spin, text, second=None):
    """One end condition from the menu: Blind / Mid Plane in the page's list, the others by a pick."""
    if second is not None and alive(second) and not second.isChecked():
        second.click()
    if combo is not None and alive(combo):
        i = combo.findText(text)
        if i >= 0:
            _pick(combo, i)
            return True
        if text != "Mid Plane":
            i = combo.findText("Blind")
            if i >= 0 and combo.currentIndex() != i:
                _pick(combo, i)
    if text in ("Blind", "Mid Plane"):
        return True
    plane = _sketch_plane(panel)
    if plane is None or spin is None:
        return False
    offset = 0.0
    if text == "Offset From Surface":
        value, ok_ = QtWidgets.QInputDialog.getDouble(Gui.getMainWindow(), text, "Offset distance (mm):", 0.0, -1e6, 1e6, 3)
        if not ok_:
            return False
        offset = value
    DEPTH_PICK.start(spin, plane, text, offset)
    return True


def _base_flange_items():
    """Base Flange PropertyManager (screen read 2, B1): Direction 1: Reverse Direction, Blind,
    Up To Vertex, Up To Surface, Offset From Surface, Mid Plane; Direction 2: Direction 2 Off,
    Blind, Up To Vertex, Up To Surface, Offset From Surface."""
    end = _visible(QtWidgets.QComboBox, "SWSMEnd")
    if end is None:
        return None
    panel = _panel_of(end)
    reverse = _visible(QtWidgets.QCheckBox, "SWSMReverse")
    depth = _visible(QtWidgets.QDoubleSpinBox, "SWSMDepth")
    second = _visible(QtWidgets.QCheckBox, "SWSMDirection2")
    end2 = _visible(QtWidgets.QComboBox, "SWSMEnd2")
    depth2 = _visible(QtWidgets.QDoubleSpinBox, "SWSMDepth2")
    out = [rcmenus.header("Direction 1", "HeaderDirection1")]
    if reverse is not None:
        out.append(rcmenus.action("ReverseDirection", "Reverse Direction", lambda: alive(reverse) and reverse.click()))
    now = end.currentText()
    for text in FLANGE_END1:
        out.append(rcmenus.action("End_" + text.replace(" ", ""), text,
                                  lambda t=text: _end_to(panel, end, depth, t), checked=text == now))
    if second is not None:
        on = second.isChecked()
        out.append(rcmenus.header("Direction 2", "HeaderDirection2"))
        out.append(rcmenus.action("Direction2Off", "Direction 2 Off",
                                  lambda: alive(second) and second.isChecked() and second.click(), checked=not on,
                                  enabled=second.isEnabled()))
        now2 = end2.currentText() if (end2 is not None and on) else None
        for text in FLANGE_END2:
            out.append(rcmenus.action("End2_" + text.replace(" ", ""), text,
                                      lambda t=text: _end_to(panel, end2, depth2, t, second),
                                      checked=text == now2, enabled=second.isEnabled()))
    return out


def edge_flange_panel():
    """The Edge Flange PropertyManager when one is open with an edge picked, else None."""
    length = _visible(QtWidgets.QDoubleSpinBox, "SWSMLength")
    profile = _visible(QtWidgets.QPushButton, "SWSMEditProfile")
    edges = _visible(QtWidgets.QListWidget, "SWSMEdges")
    if length is None or profile is None or edges is None or edges.count() == 0:
        return None
    panel = _panel_of(length)
    return panel if panel is not None and getattr(panel, "obj", None) is not None else None


def _pointer_point(view, plane_point, plane_normal):
    """The 3D point under the pointer: on the model where it is on it, else where the pointer's
    line of sight meets the plane."""
    pos = view.getCursorPos()
    try:
        info = view.getObjectInfo(pos)
    except Exception:
        info = None
    if info:
        return App.Vector(info["x"], info["y"], info["z"])
    p = view.getPoint(*pos)
    d = view.getViewDirection()
    den = d.dot(plane_normal)
    if abs(den) < 1e-9:
        return None
    t = (plane_point - p).dot(plane_normal) / den
    return p + d * t


def edge_flange_height(panel, view=None):
    ""

    view = view or Gui.ActiveDocument.ActiveView
    obj, base = panel.obj, panel.base
    sub = panel.edges.item(0).text()
    edge = base.Shape.getElement(sub)
    a = edge.Vertexes[0].Point
    b = edge.Vertexes[-1].Point
    axis = (b - a)
    if axis.Length < 1e-9:
        return None
    axis.normalize()

    def off_line(p):
        v = p - a
        return v - axis * v.dot(axis)

    far = max((off_line(v.Point) for v in obj.Shape.Vertexes), key=lambda v: v.Length, default=None)
    if far is None or far.Length < 1e-9:
        return None
    up = App.Vector(far).normalize()
    p = _pointer_point(view, a, axis.cross(up))
    if p is None:
        return None
    if hasattr(panel, "height_at"):
        try:
            return panel.height_at(p)       # the page's own (commands pkg170): the same as a left-click
        except Exception as _fw_err:
            _fw_log("featuremenu.py:563", _fw_err)
    h = off_line(p).dot(up)
    current = float(panel.length.value())
    new = current + (h - far.Length)
    return max(0.01, new)


def edge_flange_accept(panel):
    try:
        h = edge_flange_height(panel)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Edge Flange height from the pointer: %s\n" % error)
        h = None
    if h is not None and alive(panel.length):
        panel.length.setValue(h)
    ok()
    return h


def _fillet_items(edge):
    out = [_mirror("TangentPropagation", "Tangent Propagation", _visible(QtWidgets.QCheckBox, "SWFilletTangent")),
           _mirror("MultipleRadius", "Multiple Radius", _check_by_text("Multi Radius Fillet"))]
    if edge is not None:
        out.append(rcmenus.action("SelectMidpoint", rcmenus.T_SELECT_MIDPOINT, lambda: rcmenus.select_edge_midpoint(edge)))
        out.append(rcmenus.action("SelectLoop", rcmenus.T_SELECT_LOOP, lambda: rcmenus.select_loop(edge)))
    return out


def _shell_items(p):
    out = [rcmenus.action("CheckBodyFaces", "Check Body/Faces", lambda: check_body(p)),
           rcmenus.action("DisplayMesh", "Display Mesh", lambda: toggle_overlay(p, "mesh"),
                          checked=_overlay_on("mesh")),
           rcmenus.action("DisplayCurvature", "Display Curvature", lambda: toggle_overlay(p, "curvature"),
                          checked=_overlay_on("curvature"))]
    out.append(_mirror("ShellOutward", "Shell Outward", getattr(p, "outward", None) if p is not None else None)
               or _mirror("ShellOutward", "Shell Outward", _visible(QtWidgets.QCheckBox, "SWStyle_ShellOutward")))
    return out


def _flex_items():
    ""

    obj = _in_edit()
    if obj is None or "FlexType" not in getattr(obj, "PropertiesList", []):
        return None
    try:
        from . import flex
        return [rcmenus.action(k, t, run, enabled=on) for k, t, run, on in flex.menu_entries(obj)]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Flex menu: %s\n" % error)
        return None


def items(edge=None):
    ""


    mate = _mate_panel()
    if mate is not None:
        from . import asmviewmenu
        return asmviewmenu.mate_pm_items(mate, ok, cancel)     # screen read 2, A4
    p = page()
    out = _selection_items()
    try:
        from . import filletpm
        kind = _page_type(p)
        if kind in (filletpm.FILLET, filletpm.CHAMFER):
            out += _fillet_items(edge)
            edge = None
        elif kind == filletpm.SHELL:
            out += _shell_items(p)
        elif _flex_items() is not None:
            out += _flex_items()
        else:
            flange = _base_flange_items()
            out += flange if flange is not None else _direction_items()
    except Exception:
        out += _direction_items()
    if edge is not None:
        out.append(rcmenus.action("SelectMidpoint", rcmenus.T_SELECT_MIDPOINT, lambda: rcmenus.select_edge_midpoint(edge)))
    return [i for i in out if i is not None]


# ---------------------------------------------------------------- Shell's Error Diagnostics items
def _shell_shape(p):
    feature = getattr(p, "feature", None) or getattr(p, "edit", None)
    for obj in (getattr(p, "base", None), feature, getattr(feature, "BaseFeature", None)):
        try:
            if obj is not None and not obj.Shape.isNull():
                return obj.Shape
        except Exception:
            continue
    return None


def check_body(p):
    """Check Body/Faces: FreeCAD's shape check on the body the shell works on."""
    shape = _shell_shape(p)
    if shape is None:
        text = "There is no body to check."
    else:
        try:
            shape.check(True)
            text = "No errors were found in the body (%d faces)." % len(shape.Faces)
        except Exception as error:
            text = "The body has errors:\n%s" % error
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Check Body/Faces", text)
    return text


_overlays = {}      # kind -> (view, node)


def _overlay_on(kind):
    return kind in _overlays


def _remove_overlay(kind):
    view, node = _overlays.pop(kind, (None, None))
    if view is not None:
        try:
            view.getSceneGraph().removeChild(node)
        except Exception as _fw_err:
            _fw_log("featuremenu.py:686", _fw_err)


def _watch_close(p):
    def check():
        if page() is not p:
            for k in list(_overlays):
                _remove_overlay(k)
            return
        QtCore.QTimer.singleShot(500, check)
    QtCore.QTimer.singleShot(500, check)


def toggle_overlay(p, kind):
    """Display Mesh (the faces' triangles as lines) and Display Curvature (the faces coloured by
    mean curvature, blue flat to red tight), drawn over the body until the PropertyManager closes."""
    if kind in _overlays:
        _remove_overlay(kind)
        return False
    shape = _shell_shape(p)
    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    if shape is None or view is None:
        return False
    from pivy import coin
    node = coin.SoSeparator()
    coords = coin.SoCoordinate3()
    points, index, colours = [], [], []
    for face in shape.Faces:
        try:
            pts, tris = face.tessellate(0.05)
        except Exception:
            continue
        base = len(points)
        for v in pts:
            points.append((v.x, v.y, v.z))
            if kind == "curvature":
                try:
                    u, w = face.Surface.parameter(v)
                    colours.append(abs(face.Surface.curvature(u, w, "Mean")))
                except Exception:
                    colours.append(0.0)
        for a, b, c in tris:
            if kind == "mesh":
                index += [base + a, base + b, base + c, base + a, -1]
            else:
                index += [base + a, base + b, base + c, -1]
    if not points:
        return False
    coords.point.setValues(0, len(points), points)
    node.addChild(coords)
    if kind == "mesh":
        style = coin.SoDrawStyle()
        style.lineWidth = 1
        mat = coin.SoBaseColor()
        mat.rgb = (0.1, 0.1, 0.1)
        node.addChild(style)
        node.addChild(mat)
        lines = coin.SoIndexedLineSet()
        lines.coordIndex.setValues(0, len(index), index)
        node.addChild(lines)
    else:
        top = max(colours) or 1.0
        mat = coin.SoMaterial()
        rgb = []
        for k in colours:
            t = min(1.0, k / top)
            rgb.append((t, 0.2 + 0.6 * (1 - abs(2 * t - 1)), 1.0 - t))
        mat.diffuseColor.setValues(0, len(rgb), rgb)
        bind = coin.SoMaterialBinding()
        bind.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
        node.addChild(mat)
        node.addChild(bind)
        faces = coin.SoIndexedFaceSet()
        faces.coordIndex.setValues(0, len(index), index)
        faces.materialIndex.setValues(0, len(index), index)
        node.addChild(faces)
    view.getSceneGraph().addChild(node)
    _overlays[kind] = (view, node)
    _watch_close(p)
    return True


def _icon(name):
    try:
        icon = QtGui.QIcon(Gui.getIcon(name)) if hasattr(Gui, "getIcon") else None
        return icon if icon is not None and not icon.isNull() else None
    except Exception:
        return None


def _model_under_pointer():
    """True when the pointer is on the model (a face, edge or point), False in empty space."""
    try:
        view = Gui.ActiveDocument.ActiveView
        return bool(view.getObjectInfo(view.getCursorPos()))
    except Exception:
        return False


def _edge_under_pointer():
    """(doc, object, element path) of the model edge right under the pointer, else None (FreeCAD's
    preselection can still name an edge the pointer has left)."""
    try:
        view = Gui.ActiveDocument.ActiveView
        info = view.getObjectInfo(view.getCursorPos())
    except Exception:
        info = False
    if info is False:
        try:
            pre = Gui.Selection.getPreselection()
            subs = tuple(pre.SubElementNames) if pre is not None and pre.ObjectName else ()
        except Exception:
            return None
        if subs and subs[0].split(".")[-1].startswith("Edge"):
            return (pre.DocumentName, pre.ObjectName, subs[0])
        return None
    if not info:
        return None
    sub = info.get("Component", "") or ""
    if sub.split(".")[-1].startswith("Edge"):
        return (info.get("Document"), info.get("Object"), sub)
    return None


class FeatureMenu(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell
        self._pending = False
        self._watched = []
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.attach)
        QtCore.QTimer.singleShot(0, self.attach)

    def attach(self, *args):
        self._watched = [w for w in self._watched if alive(w)]
        view = self.shell.view_widget()
        if view is None or not alive(view) or not hasattr(view, "viewport"):
            return
        widget = view.viewport()
        if widget is None or widget in self._watched:
            return
        widget.installEventFilter(self)
        self._watched.append(widget)

    def remove(self):
        for widget in self._watched:
            if alive(widget):
                widget.removeEventFilter(self)
        self._watched = []
        if self.mdi is not None and alive(self.mdi):
            try:
                self.mdi.subWindowActivated.disconnect(self.attach)
            except Exception as _fw_err:
                _fw_log("featuremenu.py:841", _fw_err)

    def _here(self):
        return getattr(self.shell, "enabled", True) and enabled() and edited() is not None

    def _wanted(self, event):
        if event.button() != Qt.RightButton or event.modifiers() != Qt.NoModifier:
            return False
        return self._here()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        try:
            if t == QtCore.QEvent.MouseButtonPress:
                if not self._wanted(event):
                    return False
                g = getattr(self.shell, "gestures", None)
                if g is not None and not getattr(g, "_replaying", False):
                    try:
                        from .gestures import enabled_here
                        if enabled_here():
                            return False    # gestures holds the press; its replay comes back here
                    except Exception as _fw_err:
                        _fw_log("featuremenu.py:866", _fw_err)
                self._pending = True
                return True
            if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.RightButton and self._pending:
                self._pending = False
                pos = event.globalPosition().toPoint()
                QtCore.QTimer.singleShot(0, lambda: self.show_menu(pos))
                return True
            if t == QtCore.QEvent.ContextMenu and self._here():
                return True         # FreeCAD's view menu stays shut while ours is used
        except Exception:
            return False
        return False

    def build(self):
        return rcmenus.Builder("FeaturePM", items(_edge_under_pointer())).build()

    def show_menu(self, pos):
        if edited() is None:
            return None
        flange = edge_flange_panel()
        if flange is not None:
            edge_flange_accept(flange)
            return None
        edge = _edge_under_pointer()
        if right_click_accepts(edge is not None or _model_under_pointer()):
            ok()
            return None
        return rcmenus.show(rcmenus.Builder("FeaturePM", items(edge)), pos)


_menu = []


def install(shell=None):
    """Watches the 3D views (sketchtoolmenu installs it with the look; extrudepm calls it again)."""
    if shell is None:
        try:
            from . import shell as shell_module
            shell = shell_module.shell()
        except Exception:
            shell = None
    if shell is None:
        return None
    if _menu and _menu[0].shell is shell:
        _menu[0].attach()
        return _menu[0]
    remove()
    _menu.append(FeatureMenu(shell))
    return _menu[0]


def remove():
    while _menu:
        _menu.pop().remove()
