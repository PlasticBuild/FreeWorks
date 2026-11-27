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
# pick-449: every way a page writes a picked element, as (owner, element): "Boss-Extrude1.Edge9" (Curve
# Driven Pattern), "Body: Face2", "Body:Face2", "Face2 of Body", "Body Face2", "Body@Face2"
_OWNED = (_re.compile(r"^(.+?)(?:\.|: ?|@| )((?:Edge|Face|Vertex)\d+)$"),
          _re.compile(r"^((?:Edge|Face|Vertex)\d+) of (.+)$"))


def _split(t):
    """(kind, owner) of a picked element's text, owner "" when it has none; None for any other text."""
    got = _split_n(t)
    return got and got[:2]


def _split_n(t):
    """(kind, owner, FreeCAD's number) of a picked element's text; None for any other text."""
    m = _SUB.match(t)
    if m is not None:
        return m.group(1), (m.group(3) or "")[1:], int(m.group(2))
    m = _OWNED[0].match(t)
    if m is not None:
        kind = _re.match(r"[A-Za-z]+", m.group(2)).group(0)
        return kind, m.group(1), int(m.group(2)[len(kind):])
    m = _OWNED[1].match(t)
    if m is not None:
        kind = _re.match(r"[A-Za-z]+", m.group(1)).group(0)
        return kind, m.group(2), int(m.group(1)[len(kind):])
    return None


def _sketch_of(owner, doc):
    try:
        for o in doc.getObjectsByLabel(owner) if owner and doc is not None else ():
            if o.isDerivedFrom("Sketcher::SketchObject"):
                return o
    except Exception:
        pass
    return None


def sketch_entity(sketch, edge):
    ""

    try:
        from . import relationspm
        geos = sketch.Geometry
        names = relationspm._entity_names(geos)
        edges = sketch.Shape.Edges
        if not 1 <= edge <= len(edges):
            return None
        shown = [i for i, g in enumerate(geos)
                 if type(g).__name__ != "Point" and not sketch.getConstruction(i) and names[i]]
        target = edges[edge - 1]

        def same(i):
            e = geos[i].toShape()
            return abs(e.Length - target.Length) < 1e-6 and e.Vertexes[0].Point.distanceToPoint(target.Vertexes[0].Point) < 1e-6

        if edge <= len(shown) and same(shown[edge - 1]):
            return names[shown[edge - 1]]
        for i in shown:      # the shape's edges were built in another order: find it by shape
            if same(i):
                return names[i]
    except Exception as _fw_err:
        _fw_log("pmboxes:sketch-entity", _fw_err)
    return None


_ASM = [None, 0.0, False]        # document, when looked, is an assembly


def _in_assembly(doc):
    import time
    now = time.monotonic()
    if _ASM[0] is doc and now - _ASM[1] < 1.0:
        return _ASM[2]
    try:
        from . import asmcore
        found = bool(doc is not None and asmcore.is_assembly(doc))
    except Exception:
        found = False
    _ASM[:] = [doc, now, found]
    return found


def _keeps_owner(owner, doc):
    ""

    if not owner:
        return False
    if _in_assembly(doc):
        return True
    try:
        return any(o.isDerivedFrom("Sketcher::SketchObject") for o in doc.getObjectsByLabel(owner))
    except Exception:
        return False


def sw_names(texts, doc=None):
    ""


    if doc is None:
        try:
            doc = __import__("FreeCAD").ActiveDocument
        except Exception:
            doc = None
    seen, out = {}, []
    for t in texts:
        got = _split(t or "")
        if got is None:
            out.append(t)
            continue
        kind, owner = got
        if kind == "Edge" and owner:        # pick-451: an edge of a sketch is its entity: Line1@Sketch2
            sk = _sketch_of(owner, doc)
            ent = sketch_entity(sk, _split_n(t or "")[2]) if sk is not None else None
            if ent:
                out.append("%s@%s" % (ent, owner))
                continue
        seen[kind] = seen.get(kind, 0) + 1
        out.append("%s<%d>%s" % (kind, seen[kind], ("@" + owner) if _keeps_owner(owner, doc) else ""))
    return out


def sw_name(text, doc=None):
    ""
    return sw_names([text], doc)[0]


class _Names(QtWidgets.QStyledItemDelegate):
    ""


    def paint(self, painter, option, index):
        model = index.model()
        texts = [model.data(model.index(r, 0, index.parent())) for r in range(index.row() + 1)]
        shown = sw_names([str(t or "") for t in texts])[-1]      # pick-449: owner kept only in an assembly / sketch
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
    key = id(box)
    _names[key] = (box, d)
    try:        # perf-1126: the entry (and the box it holds) goes when the box is destroyed
        box.destroyed.connect(lambda *_a, k=key: _names.pop(k, None))
    except Exception as _fw_err:
        _fw_log("pmboxes:names-gc", _fw_err)


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
