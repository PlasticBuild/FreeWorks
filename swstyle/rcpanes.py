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
from PySide import QtCore, QtWidgets

LAST = [None]


def _later(run):
    return lambda checked=False: QtCore.QTimer.singleShot(0, run)


def _add(menu, text, run, enabled=True, checked=None):
    a = menu.addAction(text)
    a.setEnabled(bool(enabled))
    if checked is not None:
        a.setCheckable(True)
        a.setChecked(bool(checked))
    a.triggered.connect(_later(run))
    return a


# --------------------------------------------------------------------------- Display Pane
def display_pane_menu(pane, pos):
    from . import displaypane as dp
    index, column = pane.cell_at(pos)
    if index is None:
        return None
    got = dp.cells(pane.view, pane.view.fm.node(index)).get(column)
    if got is None:
        return None
    obj, level = got
    menu = QtWidgets.QMenu(pane)
    menu.setObjectName("SWToolMenu_DisplayPane")

    def done(fn):
        def run():
            try:
                fn()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: Display Pane: %s\n" % error)
            pane.update()
        return run
    if column == "hide":
        _add(menu, "Show" if not dp.shown(obj) else "Hide", done(lambda: dp.toggle_hide(obj)))
    elif column == "mode":
        now = dp.mode(obj)
        for label, freecad_mode in dp.MODES:
            _add(menu, label, done(lambda m=freecad_mode: dp.set_mode(obj, m)), checked=freecad_mode == now)
    elif column == "appearance":
        _add(menu, "Appearance...", done(lambda: dp.edit_appearance(obj, level)))
        _add(menu, "Remove Appearance", done(lambda: _remove_appearance(obj, level)),
             enabled=_has_appearance(obj, level))
    elif column == "transparency":
        _add(menu, "Change Transparency", done(lambda: dp.toggle_transparency(obj)), checked=dp.transparent(obj))
    else:
        return None
    return menu


def _target(obj, level):
    from . import appearance
    return appearance.target_for(level or "body", obj, "")


def _has_appearance(obj, level):
    try:
        from . import appearance
        t = _target(obj, level)
        return t is not None and any(t.key() in appearance.stored(b) for b in t.bodies())
    except Exception:
        return False


def _remove_appearance(obj, level):
    from . import appearance
    t = _target(obj, level)
    if t is not None:
        appearance.remove([t])


# --------------------------------------------------------------------------- Design Checker results
def _checker_window(tree):
    w = tree.parentWidget()
    while w is not None and w.objectName() != "SWDesignCheckerResults":
        w = w.parentWidget()
    return w


def checker_menu(tree, pos):
    win = _checker_window(tree)
    if win is None:
        return None
    item = tree.itemAt(pos)
    if item is not None and not item.isSelected():
        tree.clearSelection()
        item.setSelected(True)
        tree.setCurrentItem(item)
    menu = QtWidgets.QMenu(tree)
    menu.setObjectName("SWToolMenu_DesignChecker")
    if item is not None and item.parent() is not None:
        name = item.data(0, QtCore.Qt.UserRole)
        _add(menu, "Select", lambda: win._select(item, 0), bool(name) and win.doc.getObject(name) is not None)
        menu.addSeparator()
    failing = item is not None and (item.parent() or item).text(2) != "Pass"
    _add(menu, "Correct Selected", win.correct_selected, failing)
    _add(menu, "Correct All", win.correct_all, any(not r[2] for r in getattr(win, "results", [])))
    menu.addSeparator()
    _add(menu, "Run Again", win.refresh)
    _add(menu, "Save Report...", win._save_report)
    return menu


# --------------------------------------------------------------------------- a list with its own buttons
def button_list_menu(box, pos):
    """A PropertyManager list with Delete / Delete All buttons under it (SketchXpert's Conflicting
    Relations/Dimensions): the same two on a right-click, running those buttons."""
    holder = box.parentWidget()
    if holder is None:
        return None
    buttons = {b.text(): b for b in holder.findChildren(QtWidgets.QPushButton)}
    if "Delete" not in buttons or "Delete All" not in buttons:
        return None
    item = box.itemAt(pos)
    if item is not None and not item.isSelected():
        box.clearSelection()
        item.setSelected(True)
    menu = QtWidgets.QMenu(box)
    menu.setObjectName("SWToolMenu_ConflictList")
    _add(menu, "Delete", buttons["Delete"].click, bool(box.selectedItems()) and buttons["Delete"].isEnabled())
    _add(menu, "Delete All", buttons["Delete All"].click, box.count() > 0 and buttons["Delete All"].isEnabled())
    return menu


# --------------------------------------------------------------------------- What's Wrong, MateXpert, Visualization
def _ancestor(w, name):
    while w is not None and w.objectName() != name:
        w = w.parentWidget()
    return w


def _row(tree, pos):
    item = tree.itemAt(pos)
    if item is not None and not item.isSelected():
        tree.clearSelection()
        item.setSelected(True)
        tree.setCurrentItem(item)
    return item


def _sketch_of(obj):
    if obj.TypeId == "Sketcher::SketchObject":
        return obj
    prof = getattr(obj, "Profile", None)
    sk = prof[0] if isinstance(prof, (tuple, list)) and prof else prof
    return sk if getattr(sk, "TypeId", "") == "Sketcher::SketchObject" else None


def _edit(dlg, obj):
    def run():
        try:
            dlg.close()
        except Exception as _fw_err:
            _fw_log("rcpanes.py:192", _fw_err)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj.Document.Name, obj.Name)
        Gui.getDocument(obj.Document.Name).setEdit(obj.Name, 0)
    return run


def whatswrong_menu(tree, pos):
    dlg = _ancestor(tree, "SWWhatsWrong")
    item = _row(tree, pos)
    name = item.data(0, QtCore.Qt.UserRole) if item is not None else None
    doc = App.getDocument(dlg.doc_name) if dlg is not None and getattr(dlg, "doc_name", None) else None
    obj = doc.getObject(name) if doc is not None and name else None
    if obj is None:
        return None
    menu = QtWidgets.QMenu(tree)
    menu.setObjectName("SWToolMenu_WhatsWrong")
    if obj.TypeId == "Sketcher::SketchObject":
        _add(menu, "Edit Sketch", _edit(dlg, obj))
    else:
        _add(menu, "Edit Feature", _edit(dlg, obj), hasattr(obj, "ViewObject"))
        sk = _sketch_of(obj)
        if sk is not None:
            _add(menu, "Edit Sketch", _edit(dlg, sk))
    _add(menu, "Go To Feature", lambda: dlg._pick(item, 0))
    return menu


def matexpert_menu(tree, pos):
    item = _row(tree, pos)
    if item is None or not item.data(0, QtCore.Qt.UserRole):
        return None
    button = tree.window().findChild(QtWidgets.QPushButton, "FW_MateXpertSuppress")
    if button is None:
        return None
    menu = QtWidgets.QMenu(tree)
    menu.setObjectName("SWToolMenu_MateXpert")
    _add(menu, "Suppress", button.click, button.isEnabled())
    return menu


def visualization_menu(tree, pos):
    item = _row(tree, pos)
    picks = item.data(0, QtCore.Qt.UserRole) if item is not None else None
    comps = []
    for docname, name, _sub in picks or []:
        try:
            o = App.getDocument(docname).getObject(name)
        except Exception:
            o = None
        if o is not None:
            comps.append(o)
    if not comps:
        return None
    from . import asmmenu
    menu = QtWidgets.QMenu(tree)
    menu.setObjectName("SWToolMenu_Visualization")
    for key, label, run, enabled in asmmenu.component_items(comps[0]):
        if key == "HideComponents":
            run = (lambda: [asmmenu.hide_show(c) for c in comps])
        _add(menu, label, run, enabled)
    return menu


TREES = {"SWWhatsWrongTable": whatswrong_menu, "FW_MateXpertProblems": matexpert_menu,
         "FW_MateXpertMates": matexpert_menu}


def _list_handler(tree):
    if tree.contextMenuPolicy() != QtCore.Qt.DefaultContextMenu:
        return None
    fn = TREES.get(tree.objectName())
    if fn is not None:
        return fn
    tab = _ancestor(tree, "SWAssemblyVisualizationTab")
    if tab is not None and getattr(tab, "table", None) is tree:
        return visualization_menu
    return None


# --------------------------------------------------------------------------- simplefeature's selection boxes
def _simple_owner(box):
    """The simplefeature Panel whose pick box this is, and the field's name."""
    try:
        from . import simplefeature
    except Exception:
        return None, None
    import gc
    for o in gc.get_objects():
        try:
            if isinstance(o, simplefeature.Panel):
                for name, w in getattr(o, "lists", {}).items():
                    if w is box:
                        return o, name
        except Exception:
            continue
    return None, None


def _pick_rows(value):
    """The rows a pick box shows for value, in its order: (item index, sub index)."""
    items = value if isinstance(value, (list, tuple)) else ([value] if value else [])
    rows = []
    for i, item in enumerate(items):
        if isinstance(item, App.DocumentObject):
            rows.append((i, None))
        else:
            subs = item[1] if isinstance(item[1], (list, tuple)) else [item[1]]
            rows += [(i, k) for k in range(max(1, len(subs)))]
    return rows


def simple_remove(panel, name, row=None):
    """Clear Selections (row None) or Delete row of a simplefeature box; one recompute."""
    obj = panel.obj
    value = getattr(obj, name)
    if row is None:
        new = [] if isinstance(value, (list, tuple)) else None
    elif isinstance(value, (list, tuple)):
        rows = _pick_rows(value)
        if not 0 <= row < len(rows):
            return False
        i, k = rows[row]
        items = list(value)
        if k is None:
            items.pop(i)
        else:
            source, subs = items[i]
            subs = list(subs if isinstance(subs, (list, tuple)) else [subs])
            subs.pop(k)
            if subs:
                items[i] = (source, subs)
            else:
                items.pop(i)
        new = items
    else:
        new = None
    try:
        setattr(obj, name, new)
    except Exception:
        setattr(obj, name, [] if new is None else new)
    panel._changed()
    try:
        panel._show()
    except Exception as _fw_err:
        _fw_log("rcpanes.py:337", _fw_err)
    return True



def _pm(box, row):
    """The PM thread's pmboxes first (the boxes it owns), as the Delete key and its own menu do."""
    from . import pmlistmenu
    return pmlistmenu.pm_boxes(box, row)


def simple_box_menu(box, pos):
    panel, name = _simple_owner(box)
    if panel is None:
        return None
    item = box.itemAt(pos)
    row = box.row(item) if item is not None else (box.currentRow() if box.currentRow() >= 0 else -1)
    count = box.count()
    menu = QtWidgets.QMenu(box)
    menu.setObjectName("SWToolMenu_SelectionBox")
    _add(menu, "Clear Selections", lambda: _pm(box, None) or simple_remove(panel, name, None), count > 0)
    r = row if row >= 0 else 0
    _add(menu, "Delete", lambda: _pm(box, r) or simple_remove(panel, name, r), row >= 0 or count == 1)
    from . import pmlistmenu
    return pmlistmenu.finish(menu, box, item is not None or (pos is None and box.currentRow() >= 0))


# --------------------------------------------------------------------------- the flyout feature tree
def _in_flyout(w):
    while w is not None:
        if w.objectName() == "SWFlyoutTree":
            return True
        w = w.parentWidget()
    return False


def _flyout_tree_menu(obj, event):
    ""


    tree = obj if isinstance(obj, QtWidgets.QTreeWidget) else obj.parentWidget()
    if not isinstance(tree, QtWidgets.QTreeWidget) or not _in_flyout(tree):
        return False
    if event.modifiers() & QtCore.Qt.ShiftModifier:
        return False        # Shift: FreeCAD's own menu, as in the FeatureManager (fmtree)
    pos = event.pos() if obj is tree.viewport() else tree.viewport().mapFrom(obj, event.pos())
    item = tree.itemAt(pos)
    doc = App.ActiveDocument
    if doc is None:
        return False
    target = None
    if item is not None:
        label = item.text(0)
        if label == doc.Label and item.parent() is None:
            target = doc
        else:
            found = doc.getObjectsByLabel(label)
            target = found[0] if found else None
    if target is None:
        return item is not None     # a row we cannot name (a FreeCAD folder): no FreeCAD menu either
    try:
        from . import fmmenu, rcmenus
        if target is not doc:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(target)
        m = fmmenu.show(rcmenus.shell(), target, event.globalPos())
        LAST[0] = m
        return m is not None
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: flyout tree menu: %s\n" % error)
        return False


# --------------------------------------------------------------------------- any other PM selection box
import re as _re
_SUB = _re.compile(r"^(Face|Edge|Vertex)\d+$")


def entity_of(text, doc=None):
    """(object, [subs]) for a selection box row: "Face6@Pad", "Pad Face1,Face2", "Pad.Face6", "Sketch1"."""
    doc = doc or App.ActiveDocument
    if doc is None or not text:
        return None
    text = str(text).strip()
    label, subs = text, [""]
    if "@" in text:
        sub, label = text.split("@", 1)
        subs = [sub]
    elif " " in text and all(_SUB.match(x) for x in text.rsplit(" ", 1)[1].split(",")):
        label, rest = text.rsplit(" ", 1)
        subs = rest.split(",")
    elif "." in text and _SUB.match(text.rsplit(".", 1)[1]):
        label, sub = text.rsplit(".", 1)
        subs = [sub]
    found = doc.getObjectsByLabel(label) or ([doc.getObject(label)] if doc.getObject(label) else [])
    if not found:
        return None
    return found[0], subs


def _pickbox(box):
    try:
        from . import refgeom2
        return isinstance(box, refgeom2.PickBox)
    except Exception:
        return False


def _lit(obj, sub):
    """(top object name, its subname) of obj.sub in the selection, else None."""
    try:
        for sel in Gui.Selection.getSelectionEx("", 0):
            for name in sel.SubElementNames or ("",):
                if sel.Object is obj and name == sub:
                    return sel.Object.Name, name
                path = name.split(".")
                if len(path) >= 2 and path[-1] == sub and path[-2] == obj.Name:
                    return sel.Object.Name, name
                if not sub and path[-1] == "" and len(path) >= 2 and path[-2] == obj.Name:
                    return sel.Object.Name, name
    except Exception as _fw_err:
        _fw_log("rcpanes.py:458", _fw_err)
    return None


def _toggle_out(box, rows):
    ""

    before = box.count()
    if _pickbox(box):
        for r in sorted(rows, reverse=True):
            if 0 <= r < len(box.items):
                del box.items[r]
        box.show_items()
        try:
            box.panel.update()
        except Exception as _fw_err:
            _fw_log("rcpanes.py:474", _fw_err)
        return box.count() < before
    texts = [box.item(r).text() for r in rows if 0 <= r < box.count()]
    doc = App.ActiveDocument
    for t in texts:
        got = entity_of(t, doc)
        if got is None:
            continue
        obj, subs = got
        for sub in subs:
            try:
                lit = _lit(obj, sub)
                if lit is not None:
                    Gui.Selection.removeSelection(obj.Document.Name, lit[0], lit[1])  # a PM that keeps its picks lit
                else:
                    Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)     # a second pick takes it out
            except Exception as _fw_err:
                _fw_log("rcpanes.py:491", _fw_err)
            QtWidgets.QApplication.processEvents()
    for _i in range(3):
        QtWidgets.QApplication.processEvents()
    return box.count() < before


def _toggle_later(box, rows):
    def run():
        QtCore.QTimer.singleShot(0, lambda: _toggle_out(box, rows))
    return run


def other_box_menu(box, pos):
    item = box.itemAt(pos)
    row = box.row(item) if item is not None else (box.currentRow() if box.currentRow() >= 0 else -1)
    count = box.count()
    menu = QtWidgets.QMenu(box)
    menu.setObjectName("SWToolMenu_SelectionBox")
    _add(menu, "Clear Selections", lambda: _pm(box, None) or _toggle_out(box, list(range(box.count()))), count > 0)
    r = row if row >= 0 else 0
    _add(menu, "Delete", lambda: _pm(box, r) or _toggle_out(box, [r]), row >= 0 or count == 1)
    from . import pmlistmenu
    return pmlistmenu.finish(menu, box, item is not None or (pos is None and box.currentRow() >= 0))


def _other_box(box):
    if not isinstance(box, QtWidgets.QListWidget) or box.contextMenuPolicy() != QtCore.Qt.DefaultContextMenu:
        return False
    if type(box).contextMenuEvent is not QtWidgets.QListWidget.contextMenuEvent or _pmlist_handles(box):
        return False
    try:
        from . import pmlistmenu
        return pmlistmenu._in_pm(box)
    except Exception:
        return False


def _pmlist_handles(box):
    try:
        from . import pmlistmenu
        return box.objectName() in pmlistmenu.HANDLED or bool(box.property(pmlistmenu.DELETE_KEY))
    except Exception:
        return False


# --------------------------------------------------------------------------- the tree: What's Wrong?, MateXpert...
def _after_heading(out, add):
    if not add:
        return out
    for i, e in enumerate(out):
        if e[0] is None:
            return out[:i + 1] + add + out[i + 1:]
    return add + out


def _form_new_subassembly(out, target):
    ""

    from . import asmmenu
    if asmmenu.kind(target) != "component" or any(e[0] == "FormNewSubassembly" for e in out):
        return out
    got = [e for e in asmmenu.sw_component_items(target) if e[0] == "FormNewSubassembly"]
    if not got:
        return out
    entry = tuple(got[0][:4])
    for i, e in enumerate(out):
        if e[0] == "FixFloat":
            return out[:i + 1] + [entry] + out[i + 1:]
    return out


def _assembly_feature_rows(out, target):
    ""

    doc = getattr(target, "Document", None)
    if doc is None or not any(o.TypeId == "Assembly::AssemblyObject" for o in doc.Objects):
        return out
    out = [e for e in out if e[0] != "FeatureWorks"]
    from . import asmcpattern
    if asmcpattern.is_pattern(target) and not any(e[0] == "DissolvePattern" for e in out):
        row = ("DissolvePattern", "Dissolve Pattern", lambda: asmcpattern.dissolve(target), True)
        out = _after_heading(list(out), [row])
    return out


def tree_additions(target):
    add = []
    if target is None or isinstance(target, App.Document) or not hasattr(target, "TypeId"):
        return add
    doc = target.Document
    try:
        from . import fmtree
        marked = fmtree._failed(target) or fmtree._warned(target)
    except Exception:
        marked = False
    if marked:
        add.append(("WhatsWrong", "What's Wrong?", lambda: _whats_wrong(doc), True))
    try:
        from . import asmmenu, asmcore
        k = asmmenu.kind(target)
        bad = False
        if k == "mate" and not asmmenu.suppressed(target):
            bad = bool(asmcore.mate_error(target))
            if not bad:
                try:
                    bad = not asmcore.satisfied(target)
                except Exception:
                    bad = False
        if k == "matesfolder" or bad:
            from . import asmevaluate
            add.append(("MateXpert", "MateXpert...", asmevaluate.matexpert, True))
    except Exception as _fw_err:
        _fw_log("rcpanes.py:604", _fw_err)
    return add


EDIT_PLANE = "SWStyle_EditSketchPlane"


def _plane_command():
    try:
        return Gui.Command.get(EDIT_PLANE) if EDIT_PLANE in Gui.listCommands() else None
    except Exception:
        return None


def install_sketch_plane():
    """Edit Sketch Plane (tree menu) and Edit > Sketch Plane run the add-on's Sketch Plane PM;
    FreeCAD's Map Sketch only when that command is not there."""
    from . import fmmenu, swmenus
    if not getattr(fmmenu.edit_sketch_plane, "_fw_plane", False):
        original = fmmenu.edit_sketch_plane

        def edit_sketch_plane(sketch, *more, **named):
            if _plane_command() is not None:
                try:
                    fmmenu._select(sketch)
                    from . import sketchplane
                    if sketchplane.open_for(sketch):
                        return True
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: Edit Sketch Plane: %s\n" % error)
            return original(sketch, *more, **named)
        edit_sketch_plane._fw_plane = True
        fmmenu.edit_sketch_plane = edit_sketch_plane
    if not getattr(swmenus._command_item, "_fw_plane", False):
        original_item = swmenus._command_item

        def _command_item(name, label, *more, **named):
            if name == "Sketcher_MapSketch" and _plane_command() is not None:
                item = original_item(EDIT_PLANE, label, *more, **named)
                if item is not None:
                    return item
            return original_item(name, label, *more, **named)
        _command_item._fw_plane = True
        swmenus._command_item = _command_item


def _whats_wrong(doc):
    try:
        if "SWStyle_WhatsWrong" in Gui.listCommands():
            Gui.runCommand("SWStyle_WhatsWrong", 0)
            return
    except Exception as _fw_err:
        _fw_log("rcpanes.py:656", _fw_err)
    from . import whatswrong
    whatswrong.show(doc)


def install_tree():
    try:
        install_sketch_plane()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Edit Sketch Plane hook: %s\n" % error)
    from . import fmmenu
    if getattr(fmmenu.entries, "_fw_rcpanes", False):
        return
    try:
        from . import asmmenu
        asmmenu.install()       # theirs first, so these go on its assembly rows too
    except Exception as _fw_err:
        _fw_log("rcpanes.py:673", _fw_err)
    original = fmmenu.entries

    def entries(shell, target, view=None, *more, **named):
        out = original(shell, target, view, *more, **named)
        try:
            have = set(e[0] for e in out if e and e[0])
            add = [e for e in tree_additions(target) if e[0] not in have]     # asmhealth may add MateXpert too
            first = [e for e in add if e[0] == "WhatsWrong"]
            rest = [e for e in add if e[0] != "WhatsWrong"]
            out2 = _after_heading(list(out), rest)
            if first:
                out2 = first + [("-", None, None, False)] + out2
            try:
                out2 = _form_new_subassembly(out2, target)
            except Exception as _fw_err:
                _fw_log("rcpanes.py:689", _fw_err)
            try:
                out2 = _assembly_feature_rows(out2, target)
            except Exception as _fw_err:
                _fw_log("rcpanes.py:693", _fw_err)
            return out2
        except Exception as error:
            App.Console.PrintLog("FreeCAD: tree additions: %s\n" % error)
            return out
    entries._fw_rcpanes = True
    fmmenu.entries = entries


# --------------------------------------------------------------------------- the filter
class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() != QtCore.QEvent.ContextMenu or not isinstance(obj, QtWidgets.QWidget):
            return False
        try:
            menu = None
            flown = _flyout_tree_menu(obj, event)
            if flown:
                return True
            if obj.objectName() == "SWDisplayPane":
                menu = display_pane_menu(obj, event.pos())
            else:
                tree = obj if isinstance(obj, QtWidgets.QTreeWidget) else obj.parentWidget()
                handler = _list_handler(tree) if isinstance(tree, QtWidgets.QTreeWidget) else None
                if handler is not None:
                    pos = event.pos() if obj is tree.viewport() else tree.viewport().mapFrom(obj, event.pos())
                    menu = handler(tree, pos)
                    if menu is None:
                        return True
                elif isinstance(tree, QtWidgets.QTreeWidget) and tree.objectName() == "SWDesignCheckerTree":
                    pos = event.pos() if obj is tree.viewport() else tree.viewport().mapFrom(obj, event.pos())
                    menu = checker_menu(tree, pos)
                    if menu is None:
                        return False
                elif obj.objectName() != "SWDisplayPane":
                    box = obj if isinstance(obj, QtWidgets.QListWidget) else obj.parentWidget()
                    if isinstance(box, QtWidgets.QListWidget) and box.objectName().startswith("SWStyle_") \
                            and box.contextMenuPolicy() == QtCore.Qt.DefaultContextMenu and not _pmlist_handles(box):
                        pos = event.pos() if obj is box.viewport() else box.viewport().mapFrom(obj, event.pos())
                        menu = simple_box_menu(box, pos)
                        if menu is None and _other_box(box):
                            menu = other_box_menu(box, pos)
                        if menu is None:
                            return False
                        LAST[0] = menu
                        menu.popup(event.globalPos())
                        return True
                    if not (isinstance(box, QtWidgets.QListWidget) and box.objectName() == "SWSelectedEntities"
                            and box.contextMenuPolicy() == QtCore.Qt.DefaultContextMenu):
                        if box is not None and _other_box(box):
                            pos = event.pos() if obj is box.viewport() else box.viewport().mapFrom(obj, event.pos())
                            menu = other_box_menu(box, pos)
                            LAST[0] = menu
                            menu.popup(event.globalPos())
                            return True
                        return False
                    pos = event.pos() if obj is box.viewport() else box.viewport().mapFrom(obj, event.pos())
                    menu = button_list_menu(box, pos)
                    if menu is None:
                        return False
            if menu is None:
                return True
            LAST[0] = menu
            menu.popup(event.globalPos())
            return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: pane menu: %s\n" % error)
            return False


_FILTER = []


def install_tree_long():
    ""

    from . import fmmenu, rcmenus
    if getattr(fmmenu.build, "_fw_long", False):
        return
    build, reopen = fmmenu.build, fmmenu._reopen

    def full_build(shell, target, view=None, full=False, *more, **named):
        if not full:
            try:
                full = rcmenus.sticky_long()
            except Exception as _fw_err:
                _fw_log("rcpanes.py:781", _fw_err)
        return build(shell, target, view, full, *more, **named)

    def long_reopen(*args, **named):
        try:
            rcmenus.LONG.add(rcmenus._doc_key())
        except Exception as _fw_err:
            _fw_log("rcpanes.py:788", _fw_err)
        return reopen(*args, **named)
    full_build._fw_long = True
    fmmenu.build, fmmenu._reopen = full_build, long_reopen


def install():
    if _FILTER:
        return _FILTER[0]
    try:
        install_tree()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tree What's Wrong?/MateXpert: %s\n" % error)
    try:
        install_tree_long()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: tree menu long form: %s\n" % error)
    f = _Filter(QtWidgets.QApplication.instance())
    try:
        from . import events      # the add-on's one application filter (interface land263)
        events.register("rcpanes", (QtCore.QEvent.ContextMenu,), f.eventFilter)
    except ImportError:          # only without the shared dispatcher: never both (each event would run twice)
        QtWidgets.QApplication.instance().installEventFilter(f)
    _FILTER.append(f)
    return f
