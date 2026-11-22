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

T_CLEAR = "Clear Selections"
T_DELETE = "Delete"
LAST = [None]       # the menu shown last (checks)


def _update(panel):
    for name in ("update", "_show", "_fill", "sync"):
        f = getattr(panel, name, None)
        if f is not None:
            f()
            return


# --------------------------------------------------------------------------- per PropertyManager
def _mirror():
    from . import mirrorpm
    return mirrorpm.current()


def _pattern():
    from . import patternpm
    return patternpm.current()


def _mirror_edit(name, row):
    """row None = all."""
    p = _mirror()
    if p is None:
        return None
    if name == "SWMirrorPlane":
        p.plane = None
        p.active = "plane"
    elif name == "SWMirrorPlane2":
        p.plane2 = None
    elif name == "SWMirrorFeatures":
        p.features = [] if row is None else [f for i, f in enumerate(p.features) if i != row]
    elif name == "SWMirrorFaces":
        p.faces = [] if row is None else [f for i, f in enumerate(p.faces) if i != row]
    elif name == "SWMirrorBodies":
        p.whole = False
    else:
        return None
    return p


def _pattern_edit(name, row):
    p = _pattern()
    if p is None:
        return None
    if name.startswith("SWPatternDirection"):
        p.dirs["dir" + name[-1]]["ref"] = None
        p.active = "dir" + name[-1]
    elif name.startswith("SWPatternUpTo") and name[-1].isdigit():
        p.dirs["dir" + name[-1]]["upto_ref"] = None
    elif name == "SWPatternFeatures":
        p.features = [] if row is None else [f for i, f in enumerate(p.features) if i != row]
    elif name == "SWPatternFaces":
        p.faces = [] if row is None else [f for i, f in enumerate(p.faces) if i != row]
    elif name == "SWPatternBodies":
        p.whole = False
    elif name == "SWPatternSkip":
        if row is None:
            p.skip = set()
        else:
            ordered = sorted(p.skip)
            if 0 <= row < len(ordered):
                p.skip.discard(ordered[row])
    else:
        return None
    return p


def _draft_edit(name, row):
    from . import filletpm
    p = filletpm.current()
    if p is None or not hasattr(p, "plane"):
        return None
    p.plane = None
    p.active = "plane"
    return p


def _owner(box, cls_name):
    w = box.parentWidget()
    while w is not None:
        for o in w.findChildren(QtCore.QObject):
            if type(o).__name__ == cls_name:
                return o
        w = w.parentWidget()
    return None


def _loft_edit(box, row):
    loft = _owner(box, "LoftBoxes")
    if loft is None:
        return False
    sections = list(getattr(loft.feature, "Sections", []) or [])
    objs = [(x[0] if isinstance(x, (list, tuple)) else x) for x in sections]
    rows = range(len(objs)) if row is None else [row - 1]      # row 0 is the first profile (the base)
    for i in sorted(rows, reverse=True):
        if 0 <= i < len(objs):
            o = objs[i]
            loft.removing = True
            loft._remove(o.Document.Name, o.Name, "")
    if row is None:

        # box then waits for a first profile again. Before, only the later profiles went and a one-profile box
        # stayed as it was.
        def base_out():
            try:
                loft.feature.Profile = None
                if loft.base_edit is not None:
                    loft.base_edit.clear()
                loft.sync()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: loft profiles: %s\n" % error)
        QtCore.QTimer.singleShot(300 if objs else 0, base_out)
    return True


def _sweep_edit(box, which):
    sweep = _owner(box, "SweepBoxes")
    if sweep is None:
        return False

    if hasattr(sweep, "take_out"):
        sweep.take_out(which)
    else:
        sweep.activate(which)
    edit = getattr(sweep, "profile_edit" if which == "profile" else "path_edit", None)
    try:
        if edit is not None:
            edit.clear()        # FreeCAD's own field keeps the old name, and the box is filled from it
    except RuntimeError as _fw_err:
        _fw_log("pmlistmenu.py:150", _fw_err)
    try:
        sweep.sync()
    except Exception as _fw_err:
        _fw_log("pmlistmenu.py:154", _fw_err)
    return box.count() == 0 if hasattr(box, "count") else True


def _multi_edit(name, row):
    """The Mate PM's Multiple mate boxes (asmpm): the common reference and the component references.
    Deleting a component reference takes its mate back; clearing the common reference starts over."""
    from . import asmpm
    p = asmpm.OPEN
    if p is None or not hasattr(p, "multi_refs"):
        return False
    if name == "FW_MultiCommon" or row is None and not p.multi_refs:
        p.drop()
        Gui.Selection.clearSelection()
        return True
    rows = range(len(p.multi_refs)) if row is None else [row]
    for i in sorted(rows, reverse=True):
        if not 0 <= i < len(p.multi_refs):
            continue
        ref = p.multi_refs.pop(i)
        joint = p.multi_pending.pop(i) if i < len(p.multi_pending) else None
        if joint is not None:
            try:
                joint.Document.removeObject(joint.Name)
            except Exception as _fw_err:
                _fw_log("pmlistmenu.py:179", _fw_err)
        p.picked = [x for x in p.picked if not (x[0] == getattr(ref[0], "Name", None) and x[1].endswith(ref[1]))]
        p.multi_list.takeItem(i)
    if not p.multi_pending:
        try:
            p.doc.abortTransaction()
        except Exception as _fw_err:
            _fw_log("pmlistmenu.py:186", _fw_err)
    try:
        p.doc.recompute()
    except Exception as _fw_err:
        _fw_log("pmlistmenu.py:190", _fw_err)
    return True


def _axis_edit(box):
    axis = _owner(box, "AxisBox")
    if axis is None:
        return False
    axis.wait()
    return True


HANDLED = ("SWMirrorPlane", "SWMirrorPlane2", "SWMirrorFeatures", "SWMirrorFaces", "SWMirrorBodies",
           "SWPatternDirection1", "SWPatternDirection2", "SWPatternUpTo1", "SWPatternUpTo2", "SWPatternFeatures",
           "SWPatternFaces", "SWPatternBodies", "SWPatternSkip", "SWDraftNeutralPlane", "SWStyle_LoftProfiles",
           "SWStyle_SweepProfile", "SWStyle_SweepPath", "SWStyle_AxisOfRevolution", "FW_MultiCommon", "FW_MultiRefs",
           "SWMirrorEntities", "SWMirrorAbout")


def _sketch_mirror_edit(box, name, row):
    """Sketch Mirror (nativepms.MirrorPage, drawings' sketch edit too): its entities list / mirror line."""
    page = box.parentWidget()
    while page is not None and not (hasattr(page, "entities") and hasattr(page, "about")):
        page = page.parentWidget()
    if page is None:
        return False
    if name == "SWMirrorAbout":
        page.axis = None
        page.about.clear()
        page.target = "about"
    else:
        if row is None:
            page.entities = []
            page.list.clear()
        elif 0 <= row < len(page.entities):
            page.entities.pop(row)
            page.list.takeItem(row)
        else:
            return False
    try:
        page._show_target()
    except Exception as _fw_err:
        _fw_log("pmlistmenu.py:232", _fw_err)
    page.changed()
    return True


def apply(box, row):
    """Delete row (None: Clear Selections) in box. True when done."""
    name = box.objectName()
    try:
        if name in ("SWMirrorEntities", "SWMirrorAbout"):
            return _sketch_mirror_edit(box, name, row)
        if name.startswith("SWMirror"):
            p = _mirror_edit(name, row)
        elif name.startswith("SWPattern"):
            p = _pattern_edit(name, row)
        elif name == "SWDraftNeutralPlane":
            p = _draft_edit(name, row)
        elif name == "SWStyle_LoftProfiles":
            return _loft_edit(box, row)
        elif name in ("SWStyle_SweepProfile", "SWStyle_SweepPath"):
            return _sweep_edit(box, "profile" if name.endswith("Profile") else "path")
        elif name == "SWStyle_AxisOfRevolution":
            return _axis_edit(box)
        elif name in ("FW_MultiCommon", "FW_MultiRefs"):
            return _multi_edit(name, row)
        else:
            return pm_boxes(box, row)
        if p is None:
            return False
        _update(p)
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: selection box %s: %s\n" % (name, error))
        return False


# --------------------------------------------------------------------------- any box that takes the Delete key
DELETE_KEY = "fwDeleteKey"      # set on a box whose PropertyManager takes the Delete key (its own filter)


def _uses_delete_key(code, depth=0):
    if code is None or depth > 3:
        return False
    if "Key_Delete" in code.co_names:
        return True
    return any(_uses_delete_key(c, depth + 1) for c in code.co_consts if hasattr(c, "co_names"))


def _watch_filters():
    """Notes which boxes get a Delete-key filter from their PropertyManager (QObject.installEventFilter,
    called from Python), so the fallback menu's Delete runs the PropertyManager's own Delete."""
    if getattr(QtCore.QObject.installEventFilter, "_fw_watch", False):
        return
    original = QtCore.QObject.installEventFilter

    def install_event_filter(target, flt):
        original(target, flt)
        try:
            f = getattr(type(flt), "eventFilter", None)
            f = getattr(f, "__wrapped__", f)        # safeguards' guard wraps the filter's own code
            if isinstance(target, QtWidgets.QAbstractItemView) and f is not None and \
                    _uses_delete_key(getattr(f, "__code__", None)):
                target.setProperty(DELETE_KEY, True)
        except Exception as _fw_err:
            _fw_log("pmlistmenu.py:296", _fw_err)
    install_event_filter._fw_watch = True
    QtCore.QObject.installEventFilter = install_event_filter


def _in_pm(box):
    w = box.parentWidget()
    while w is not None:
        if w.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox") or \
                w.objectName() in ("TaskView",):
            return True
        w = w.parentWidget()
    return False


def _std_delete_actions():
    try:
        return [a for a in Gui.Command.get("Std_Delete").getAction() if a is not None]
    except Exception:
        return []


def _press_delete(box):
    """The Delete key on the box for its PropertyManager's own filter. FreeCAD's Delete (Std_Delete) is
    switched off meanwhile: a key the page does not take must never delete the picked feature."""
    before = box.count()
    held = [(a, a.isEnabled()) for a in _std_delete_actions()]
    for a, _on in held:
        a.setEnabled(False)
    try:
        for target in (box, box.viewport()):       # the filter sits on one of them; a key on the viewport reaches the box
            QtWidgets.QApplication.sendEvent(target, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Delete,
                                                                     QtCore.Qt.NoModifier))
            if box.count() != before:
                return
    finally:
        for a, on in held:
            try:
                a.setEnabled(on)
            except RuntimeError as _fw_err:
                _fw_log("pmlistmenu.py:336", _fw_err)


def key_delete(box, row):
    """The PropertyManager's own Delete on row (None: every row, last first). True when a row went."""
    gone = False
    rows = [row] if row is not None else list(range(box.count() - 1, -1, -1))
    for r in rows:
        if not 0 <= r < box.count():
            continue
        before = box.count()
        box.clearSelection()
        box.setCurrentRow(r)
        box.item(r).setSelected(True)
        box.setFocus()
        _press_delete(box)
        if box.count() < before:
            gone = True
        elif row is None:
            break       # this PropertyManager takes one Delete at a time and this one did nothing
    if not gone:
        try:            # the page took no Delete key: take the rows out the way a second pick does
            from . import rcpanes
            gone = rcpanes._toggle_out(box, rows)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: selection box Delete: %s\n" % error)
    return gone



def _pm_handles(box):
    ""

    try:
        from . import pmboxes
        return bool(pmboxes.handles(box))
    except Exception:
        return False


def pm_boxes(box, row):
    """The PM thread's pmboxes does Delete (row) / Clear Selections (row None) for the boxes it owns: True when it did."""
    try:
        from . import pmboxes
    except ImportError:
        return False
    try:
        if row is None:
            return bool(pmboxes.clear_all(box))
        if 0 <= row < box.count():
            box.setCurrentRow(row)
        return bool(pmboxes.remove_current(box))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: pmboxes: %s\n" % error)
        return False


T_SAVE_SELECTION = "Save Selection"
T_NEW_SET = "New Selection Set"
BOX_MENU = "SelectionBox"       # Customize Menu key: RC.SelectionBox


def finish(menu, box, on_item):
    ""


    for a in list(menu.actions()):
        if a.text() == T_DELETE and not on_item:
            menu.removeAction(a)
        elif a.text() in (T_CLEAR, T_DELETE) and not a.isEnabled():
            menu.removeAction(a)    # an empty box: no greyed Clear Selections / Delete (NO DEAD CONTROLS; pkg216)
    doc = App.ActiveDocument
    sub = menu.addMenu(T_SAVE_SELECTION)
    sub.setObjectName("SWToolMenu_SaveSelection")
    try:
        from . import fmmenu
        if doc is not None:
            fmmenu._save_selection_menu(sub, doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Save Selection: %s\n" % error)
    if not sub.actions():           # nothing picked and no sets: no greyed New Selection Set (pkg216)
        menu.removeAction(sub.menuAction())
    custom = menu.addAction("Customize Menu")
    custom.setObjectName("SWToolMenu_CustomizeMenu")
    custom.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, _customize_box_menu))
    try:
        from . import fmmenu
        hidden = fmmenu.hidden_entries("RC." + BOX_MENU)
    except Exception:
        hidden = set()
    for a in menu.actions():
        if a.text().replace("&", "") in hidden:
            a.setVisible(False)
    try:
        from . import rcaccel
        rcaccel.decorate(menu)
    except Exception as _fw_err:
        _fw_log("pmlistmenu.py:431", _fw_err)
    return menu


def _customize_box_menu():
    try:
        from . import fmmenu
    except Exception:
        return
    rows = [(t, t) for t in (T_CLEAR, T_DELETE, T_SAVE_SELECTION)]
    fmmenu._run_dialog(fmmenu.CustomizeDialog("RC." + BOX_MENU, rows), lambda b: b.apply())


def fallback_menu(box, pos):
    """Clear Selections / Delete on a box with no menu of its own whose PropertyManager takes the Delete key."""
    menu = QtWidgets.QMenu(box)
    menu.setObjectName("SWToolMenu_SelectionBox")
    item = box.itemAt(pos) if pos is not None else None
    row = box.row(item) if item is not None else box.currentRow()
    clear = menu.addAction(T_CLEAR)
    clear.setEnabled(box.count() > 0)
    clear.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: pm_boxes(box, None) or key_delete(box, None)))
    delete = menu.addAction(T_DELETE)
    delete.setEnabled(0 <= row < box.count())
    delete.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: pm_boxes(box, row) or key_delete(box, row)))
    return finish(menu, box, item is not None or (pos is None and box.currentRow() >= 0))


def menu_for(box, pos):
    menu = QtWidgets.QMenu(box)
    menu.setObjectName("SWToolMenu_SelectionBox")
    item = box.itemAt(pos) if pos is not None else None
    row = box.row(item) if item is not None else (box.currentRow() if box.currentRow() >= 0 else -1)
    count = box.count()
    clear = menu.addAction(T_CLEAR)
    clear.setEnabled(count > 0)
    clear.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: apply(box, None)))
    delete = menu.addAction(T_DELETE)
    can = row >= 0 and not (box.objectName() == "SWStyle_LoftProfiles" and row == 0)
    delete.setEnabled(can or (count == 1 and box.objectName() != "SWStyle_LoftProfiles"))
    r = row if row >= 0 else 0
    delete.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, lambda: apply(box, r)))
    return finish(menu, box, item is not None or (pos is None and box.currentRow() >= 0))


class _Filter(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() != QtCore.QEvent.ContextMenu or not isinstance(obj, QtWidgets.QWidget):
            return False
        box = obj if isinstance(obj, QtWidgets.QListWidget) else obj.parentWidget()
        if not isinstance(box, QtWidgets.QListWidget):
            return False
        own = box.objectName() in HANDLED
        if not own and not ((box.property(DELETE_KEY) or _pm_handles(box))
                            and box.contextMenuPolicy() == QtCore.Qt.DefaultContextMenu
                            and type(box).contextMenuEvent is QtWidgets.QListWidget.contextMenuEvent and _in_pm(box)):
            return False
        try:
            pos = box.viewport().mapFrom(obj, event.pos()) if obj is not box.viewport() else event.pos()
            menu = menu_for(box, pos) if own else fallback_menu(box, pos)
            LAST[0] = menu
            menu.popup(event.globalPos())
            return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: selection box menu: %s\n" % error)
            return False


_FILTER = []


def install():
    if _FILTER:
        return _FILTER[0]
    _watch_filters()
    f = _Filter(QtWidgets.QApplication.instance())
    try:
        from . import events      # the add-on's one application filter (interface land263)
        events.register("pmlistmenu", (QtCore.QEvent.ContextMenu,), f.eventFilter)
    except ImportError:          # only without the shared dispatcher: never both (each event would run twice)
        QtWidgets.QApplication.instance().installEventFilter(f)
    _FILTER.append(f)
    return f


def remove():
    while _FILTER:
        f = _FILTER.pop()
        try:
            from . import events
            events.unregister("pmlistmenu")
        except Exception as _fw_err:
            _fw_log("pmlistmenu.py:525", _fw_err)
        QtWidgets.QApplication.instance().removeEventFilter(f)
