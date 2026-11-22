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

from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt
ACTIVE = "swActive"
_bound = {}         # id(list) -> (list, remove, clear)
_filters = {}


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _repolish(w):
    try:
        w.style().unpolish(w)
        w.style().polish(w)
        QtWidgets.QWidget.update(w)      # a list's own update() wants an index
    except RuntimeError as _fw_err:
        _fw_log("pmboxes.py:47", _fw_err)


def mark(box, active, need=False):
    """Pink while the box takes the picks (or still needs one)."""
    value = "true" if (active or need) else ""
    if bool(box.property("swNeed")) != bool(need):
        box.setProperty("swNeed", bool(need))        # pkg99: pmkeys.accept waits for a needed pick
    if box.property(ACTIVE) != value:
        box.setProperty(ACTIVE, value)
        if box.styleSheet():
            box.setStyleSheet("")
        _repolish(box)


def bind(box, remove=None, clear=None):
    """The page's own way to take an item (row) or all of them out of this list."""
    _bound[id(box)] = (box, remove, clear)
    _watch(box)


def _bound_of(box):
    entry = _bound.get(id(box))
    return entry if entry is not None and entry[0] is box else None


def _remove_action(box):
    for action in box.actions():
        if action.text().replace("&", "") in ("Remove", "Delete"):
            return action
    return None


def handles(box):
    """True when this list is one pmboxes can empty: a page bound its own callbacks (bind) or the
    list carries a Remove/Delete action of FreeCAD's own (the right-click thread calls this first)."""
    try:
        return isinstance(box, QtWidgets.QListWidget) and (_bound_of(box) is not None or _remove_action(box) is not None)
    except RuntimeError:
        return False


def remove_current(box):
    """Delete: the highlighted item goes."""
    row = box.currentRow()
    if row < 0:
        return False
    entry = _bound_of(box)
    if entry is not None and entry[1] is not None:
        entry[1](row)
        return True
    action = _remove_action(box)
    if action is not None:
        action.trigger()
        return True
    return _menu_delete(box, row) or _other_delete(box, row)


OTHER_BOXES = ("SWAxisSelections",)


def _other_delete(box, row):
    """The other PropertyManager boxes the right-click menu serves (Axis, Point, Coordinate System,
    Helix and the rest of the refgeom2 pages): Delete does what that menu's Delete does."""
    try:
        from . import rcpanes
        # only the boxes with no Delete of their own: refgeom2's PickBox and the Axis list
        # (rcpanes._other_box leaves them out once this filter marks them fwDeleteKey)
        if not (rcpanes._pickbox(box) or box.objectName() in OTHER_BOXES):
            return False
        return bool(rcpanes._toggle_out(box, [row]))
    except Exception:
        return False


_in_menu = [False]


def _menu_delete(box, row):
    ""

    if _in_menu[0]:
        return False
    try:
        from . import pmlistmenu
        if box.objectName() not in getattr(pmlistmenu, "HANDLED", ()):
            return False
        _in_menu[0] = True
        try:
            return bool(pmlistmenu.apply(box, row))
        finally:
            _in_menu[0] = False
    except Exception:
        return False


def clear_all(box):
    """Clear Selections: every item goes."""
    entry = _bound_of(box)
    if entry is not None and entry[2] is not None:
        entry[2]()
        return True
    action = _remove_action(box)
    if action is None:
        return False
    from . import selectionbox
    selectionbox.clear_all(box, action)
    return True


def menu(box, pos):
    m = QtWidgets.QMenu(box)
    item = box.itemAt(pos)
    clear = m.addAction("Clear Selections")
    clear.setEnabled(box.count() > 0)
    delete = m.addAction("Delete")
    delete.setEnabled(item is not None)
    if item is not None:
        box.setCurrentItem(item)
    chosen = m.exec_(box.mapToGlobal(pos))
    if chosen is None:
        return
    # after the right-click has been handled: a page may rebuild the box while clearing it, and
    # the event filter must not return into a deleted box (Full Round Fillet crashed here)
    if chosen is clear:
        QtCore.QTimer.singleShot(0, lambda: _alive(box) and clear_all(box))
    elif chosen is delete:
        QtCore.QTimer.singleShot(0, lambda: _alive(box) and remove_current(box))



class _Filter(QtCore.QObject):
    def eventFilter(self, box, event):
        if not isinstance(event, QtCore.QEvent) or not isinstance(box, QtWidgets.QListWidget):
            return False
        kind = event.type()
        if kind == QtCore.QEvent.ShortcutOverride and event.key() in (Qt.Key_Delete, Qt.Key_Backspace) \
                and not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):

            # Std_Delete (Del) must not get it: it deleted the model feature the face belonged to.
            event.accept()
            return True
        if kind == QtCore.QEvent.KeyPress and event.key() in (Qt.Key_Delete, Qt.Key_Backspace) \
                and not event.isAutoRepeat():
            if remove_current(box):
                return True
            # not ours: the page's own key filter (pickfirst) or the list still gets it; the
            # ShortcutOverride above already kept it from FreeCAD's Delete
        elif kind == QtCore.QEvent.ContextMenu and box.contextMenuPolicy() == Qt.DefaultContextMenu:
            menu(box, box.viewport().mapFromGlobal(event.globalPos()))
            return True
        return False


def _watch(box):
    if id(box) in _filters and _filters[id(box)][0] is box:
        return
    f = _Filter(box)
    box.installEventFilter(f)
    _filters[id(box)] = (box, f)
    # soak-1120 (Assemblies, patch-merge): the entry goes with its box; kept, every PM ever opened stayed
    # in memory as Python wrappers (about 17 lists and their children per Insert + Mate cycle)
    box.destroyed.connect(lambda *_a, k=id(box): _filters.pop(k, None))


import re as _re

_SUB = _re.compile(r"^(Edge|Face|Vertex)<?(\d+)>?(@.*)?$")
_DOTTED = _re.compile(r"^(.+)\.((?:Edge|Face|Vertex)\d+)$")     # "Boss-Extrude1.Edge9" (Curve Driven Pattern)


def sw_names(texts):
    ""

    seen, out = {}, []
    for t in texts:
        d = _DOTTED.match(t or "")
        if d is not None:
            t = "%s@%s" % (d.group(2), d.group(1))      # the same "Edge<1>@Boss-Extrude1" as the other boxes
        m = _SUB.match(t or "")
        if m is None:
            out.append(t)
            continue
        seen[m.group(1)] = seen.get(m.group(1), 0) + 1
        out.append("%s<%d>%s" % (m.group(1), seen[m.group(1)], m.group(3) or ""))
    return out


class _Names(QtWidgets.QStyledItemDelegate):
    ""


    def paint(self, painter, option, index):
        model = index.model()
        texts = [model.data(model.index(r, 0, index.parent())) for r in range(index.row() + 1)]
        shown = sw_names([str(t or "") for t in texts])[-1]
        if shown == str(texts[-1] or ""):
            return super().paint(painter, option, index)
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = shown
        w = opt.widget
        style = w.style() if w is not None else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, w)


_names = {}         # id(list) -> (list, delegate)


def _name_box(box):
    if id(box) in _names and _names[id(box)][0] is box:
        return
    if type(box.itemDelegate()) is not QtWidgets.QStyledItemDelegate:
        return          # the page draws its items itself
    d = _Names(box)
    box.setItemDelegate(d)
    _names[id(box)] = (box, d)


def install(view):
    ""

    for box in view.findChildren(QtWidgets.QListWidget):
        try:
            _name_box(box)
        except RuntimeError:
            continue
        except Exception as _fw_err:
            _fw_log("pmboxes:names", _fw_err)
        try:
            policy = box.contextMenuPolicy()
            if policy == Qt.CustomContextMenu:
                continue        # the page draws its own menu (the dress-up pages)
            if policy == Qt.ActionsContextMenu and _remove_action(box) is None:
                continue
            _watch(box)
        except RuntimeError:
            continue
