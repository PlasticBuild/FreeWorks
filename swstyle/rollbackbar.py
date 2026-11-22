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

from . import paths, sketchstatus, treefolders
from .widgets import alive

Qt = QtCore.Qt

PARAM = "RollbackBar"

LIGHT = QtGui.QColor(54, 142, 196)
DARK = QtGui.QColor(35, 18, 157)
LIGHT_PX, DARK_PX = 2.5, 0.5     # logical pixels
GRAB = 4                         # px from the bar's middle where the hand pointer takes it
TICK = 250                       # ms between looks at the tree and the bodies' Tips
BODY = "PartDesign::Body"
MENU = (("RollForward", "Roll Forward"), ("RollToPrevious", "Roll to Previous"), ("RollToEnd", "Roll to End"),
        ("DeleteBelow", "Delete Features Below Rollback"))


def _role(value):
    return getattr(value, "value", value)


LOOK_ROLES = {_role(Qt.ForegroundRole), _role(Qt.DecorationRole)}


def enabled():
    return paths.params().GetBool(PARAM, True)


# --------------------------------------------------------------------------- bodies and Tips
def arrow_keys():
    ""
    try:
        from . import optionspages
        return optionspages.stored("Fixed", "Arrow key navigation", False)
    except Exception:
        return True


def _derived(obj, type_name):
    try:
        return obj.isDerivedFrom(type_name)
    except Exception:
        return False


def solid_features(body):
    """The body's solid features in order, as PartDesign's Body::isSolidFeature counts them:
    PartDesign features that are not datums and not the steps inside a MultiTransform."""
    group = list(body.Group)
    inner = set()
    for obj in group:
        if _derived(obj, "PartDesign::MultiTransform"):
            for step in getattr(obj, "Transformations", None) or []:
                inner.add(step.Name)
    return [obj for obj in group if _derived(obj, "PartDesign::Feature") and not _derived(obj, "Part::Datum")
            and not _derived(obj, "App::DatumElement") and obj.Name not in inner]


def body_of(obj):
    """The PartDesign body a feature is in, or None."""
    try:
        for parent in obj.InList:
            if parent.TypeId == BODY and parent.hasObject(obj):
                return parent
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:115", _fw_err)
    return None


def editing():
    ""
    try:
        if Gui.Control.activeDialog():
            return True
        doc = Gui.ActiveDocument
        return doc is not None and doc.getInEdit() is not None
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:128", _fw_err)
        return False


def tip_before(body, feature):
    ""



    solids = solid_features(body)
    names = [obj.Name for obj in solids]
    if feature.Name not in names:
        return None
    k = names.index(feature.Name)
    if k > 0:
        return solids[k - 1]
    # above the first feature: no Tip. A sketch as the Tip put the Body itself in error ("Linked

    # shows); a new feature still goes in at the bar (_NewAboveFirst)
    return None


LAST_BOX = []        # the Delete Features Below Rollback question (checks answer it)


T_FROZEN = "The rollback bar cannot go above the Freeze bar: move the Freeze bar up first."


def above_freeze(body, tip):
    ""

    try:
        from . import freezebar
        if not freezebar.enabled():
            return False
        group = [o for o in body.Group]
        names = [o.Name for o in group]
        start = names.index(tip.Name) + 1 if tip is not None and tip.Name in names else 0
        return any(freezebar.frozen(o) for o in group[start:])
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:above_freeze", _fw_err)
        return False


def _say(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 5000)
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:say", _fw_err)


class Rolls:
    """Moves Tips and remembers each body's last position, for Roll to Previous."""

    def __init__(self):
        self.previous = {}       # (document name, body name) -> name of the Tip before the last move, "" for none
        self.count = 0           # moves, for checks
        self.after = []          # called with the body after each move (the bar redraws at once)
        self.errors = set()      # bodies Stop and Repair rolled back (stoprepair.py): the bar's tooltip says so

    @staticmethod
    def key(body):
        return (body.Document.Name, body.Name)

    def roll(self, body, tip, label="Rollback"):
        """Makes tip the body's Tip as FreeCAD's Set Tip does: shown, the old Tip hidden and the
        part rebuilt, in one Undo step (so Undo also puts the body's shape back)."""
        old = body.Tip
        if tip is old or (tip is not None and old is not None and tip.Name == old.Name):
            return False
        if above_freeze(body, tip):
            _say(T_FROZEN)
            return False
        doc = body.Document
        doc.openTransaction(label)
        try:
            body.Tip = tip
            if tip is not None:
                tip.Visibility = True
            if old is not None:
                old.Visibility = False
            doc.recompute()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintError("FreeCAD: rollback: %s\n" % error)
            return False
        doc.commitTransaction()
        self.previous[self.key(body)] = old.Name if old is not None else ""
        self.errors.discard(self.key(body))
        self.count += 1
        for call in list(self.after):
            try:
                call(body)
            except Exception as _fw_err:
                _fw_log("rollbackbar.py:191", _fw_err)
        return True

    def back_to(self, feature):
        """Rollback on a feature: the bar just above it."""
        body = body_of(feature)
        if body is None or feature.Name not in [obj.Name for obj in solid_features(body)]:
            return False
        before = tip_before(body, feature)
        if before is None:          # nothing above the first feature: no Tip, new features go in on top
            _watch_new()
        return self.roll(body, before)

    def forward(self, body):
        solids = solid_features(body)
        names = [obj.Name for obj in solids]
        tip = body.Tip
        k = names.index(tip.Name) + 1 if tip is not None and tip.Name in names else 0
        return k < len(solids) and self.roll(body, solids[k], "Roll Forward")

    def to_end(self, body):
        solids = solid_features(body)
        return bool(solids) and self.roll(body, solids[-1], "Roll to End")

    def previous_tip(self, body):
        name = self.previous.get(self.key(body))
        if name is None:
            return False, None   # never moved
        if name == "":
            return body.Tip is not None, None     # it was above the first feature
        obj = body.Document.getObject(name)
        tip = body.Tip
        if obj is None or not body.hasObject(obj) or (tip is not None and tip.Name == obj.Name):
            return False, None
        if above_freeze(body, obj):
            return False, None      # behind the Freeze bar now: no Roll to Previous that would refuse
        return True, obj

    def to_previous(self, body):
        ok, tip = self.previous_tip(body)
        return ok and self.roll(body, tip, "Roll to Previous")

    def can(self, body):
        """Which of the bar's menu entries apply."""
        solids = solid_features(body)
        at_end = not solids or body.Tip is solids[-1] or (body.Tip is not None and body.Tip.Name == solids[-1].Name)
        return {"RollForward": not at_end, "RollToEnd": not at_end, "RollToPrevious": self.previous_tip(body)[0],
                "DeleteBelow": bool(self.below(body))}

    @staticmethod
    def below(body):
        """The body's items under the bar (after its Tip): features, their sketches and planes."""
        group = list(body.Group)
        tip = body.Tip
        if tip is None:
            return [o for o in group if o.TypeId != "App::Origin"]
        names = [o.Name for o in group]
        if tip.Name not in names:
            return []
        return group[names.index(tip.Name) + 1:]

    def delete_below(self, body, ask=True):
        ""

        items = self.below(body)
        if not items:
            return False
        if ask and App.GuiUp:
            box = QtWidgets.QMessageBox(Gui.getMainWindow())
            box.setObjectName("SWDeleteBelowRollback")
            box.setWindowTitle("Delete Features Below Rollback")
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setText("Delete the %d item%s below the rollback bar?" % (len(items), "" if len(items) == 1 else "s"))
            box.setDetailedText("\n".join(o.Label for o in items))
            box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            box.setDefaultButton(QtWidgets.QMessageBox.No)
            LAST_BOX[:] = [box]
            if box.exec() != QtWidgets.QMessageBox.Yes:
                return False
        doc = body.Document
        tip = body.Tip
        doc.openTransaction("Delete Features Below Rollback")
        try:
            from . import confirmdelete
            confirmdelete.remove(items)
            body.Tip = tip if tip is not None and doc.getObject(tip.Name) is not None else body.Tip
            doc.recompute()
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintError("FreeCAD: delete below rollback: %s\n" % error)
            return False
        doc.commitTransaction()
        self.previous.pop(self.key(body), None)
        self.count += 1
        for call in list(self.after):
            try:
                call(body)
            except Exception as _fw_err:
                _fw_log("rollbackbar.py:287", _fw_err)
        return True


ROLLS = Rolls()


class _NewAboveFirst:
    ""



    def slotCreatedObject(self, obj):
        doc = obj.Document
        empty = [b.Name for b in doc.findObjects("PartDesign::Body") if b.TypeId == "PartDesign::Body" and b.Tip is None
                 and ROLLS.previous.get(ROLLS.key(b)) is not None]
        if empty:           # FreeCAD makes a new solid feature the Tip before this runs again
            QtCore.QTimer.singleShot(0, lambda name=obj.Name, d=doc.Name: _to_top(d, name, empty))


def _to_top(doc_name, name, empty=()):
    try:
        doc = App.getDocument(doc_name)
        obj = doc.getObject(name)
        body = body_of(obj) if obj is not None else None
        if body is None or body.Name not in empty or (body.Tip is not None and body.Tip.Name != obj.Name):
            return
        group = list(body.Group)
        solids = [o for o in solid_features(body) if o.Name != obj.Name]
        if not solids or group[-1].Name != obj.Name:
            return
        names = [o.Name for o in group]
        top = names.index(solids[0].Name)
        profile = getattr(solids[0], "Profile", None)
        if profile and profile[0] is not None and profile[0].Name in names:
            top = min(top, names.index(profile[0].Name))   # the first feature keeps its sketch
            sketch = getattr(profile[0], "Sketch", None)   # through its Selected Contours object
            if sketch is not None and getattr(sketch, "Name", None) in names:
                top = min(top, names.index(sketch.Name))
        group.pop()
        group.insert(top, obj)
        body.Group = group
        if _is_solid(obj):
            body.Tip = obj
    except Exception as error:
        App.Console.PrintLog("FreeCAD rollback: %s\n" % error)


_WATCH = []


def _watch_new():
    if not _WATCH:
        _WATCH.append(_NewAboveFirst())
        App.addDocumentObserver(_WATCH[0])


def can_roll_back(feature):
    ""

    if not enabled() or editing():
        return False
    body = body_of(feature)
    if body is None or body.Tip is None:
        return False
    solids = solid_features(body)
    names = [obj.Name for obj in solids]
    if feature.Name not in names:
        return False
    before = tip_before(body, feature)
    if above_freeze(body, before):
        return False
    return before is None or before.Name != body.Tip.Name


def roll_back_to(feature):
    return ROLLS.back_to(feature)


def step_back_feature():
    ""

    if Gui.Selection.getSelection():
        return None
    body = None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:370", _fw_err)
    if body is None and App.ActiveDocument is not None:
        bodies = [o for o in App.ActiveDocument.Objects if o.TypeId == "PartDesign::Body"]
        body = bodies[0] if len(bodies) == 1 else None
    tip = getattr(body, "Tip", None)
    return tip if tip is not None and can_roll_back(tip) else None


def mark_error_roll(body):
    """The bar of this body was rolled back to a feature with an error (Stop and Repair)."""
    if body is not None:
        ROLLS.errors.add(Rolls.key(body))


def bar_tip(body):
    ""
    if body is not None and Rolls.key(body) in ROLLS.errors:
        from .stoprepair import ROLLBACK_TIP
        return ROLLBACK_TIP
    return ""


# --------------------------------------------------------------------------- the tree
class Layout:
    """One body as the tree shows it: where its bar goes and where it may be dropped."""
    __slots__ = ("doc", "body", "bar_y", "end_y", "gaps")

    def __init__(self, doc, body, bar_y, end_y, gaps):
        self.doc, self.body = doc, body
        self.bar_y = bar_y       # viewport y of the bar's top edge
        self.end_y = end_y       # just below the body's last row
        self.gaps = gaps         # [(y, Tip)] where the bar may go

    def key(self):
        return (self.doc.Name, self.body.Name)


def _shown(tree, index):
    rect = tree.visualRect(index)
    return rect if rect.isValid() and rect.height() > 0 else None


def _bottom(tree, index):
    """Bottom of a row and of whatever is open under it."""
    rect = _shown(tree, index)
    bottom = rect.bottom() if rect is not None else -1
    if tree.isExpanded(index):
        model = tree.model()
        for row in range(model.rowCount(index) - 1, -1, -1):
            child = model.index(row, 0, index)
            if _shown(tree, child) is not None:
                return max(bottom, _bottom(tree, child))
    return bottom


def _recomputing():
    """A document is being rebuilt."""
    try:
        from . import asmgen
        if asmgen._busy:
            return True
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:432", _fw_err)
    try:
        return any("Recomputing" in doc.State for doc in App.listDocuments().values())
    except Exception:
        return False


def body_rows(tree, every=False):
    ""

    own = getattr(tree, "fm_body_rows", None)
    if own is not None:
        return own(every)
    model = tree.model()
    docs = {}
    for doc in App.listDocuments().values():
        docs.setdefault(doc.Label, doc)
    out = []

    def walk(parent, doc, bodies, depth):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            body = bodies.get(index.data(Qt.DisplayRole))
            if body is not None:
                out.append((doc, body, index))
            elif depth < 8 and (every or tree.isExpanded(index)):
                walk(index, doc, bodies, depth + 1)

    for row in range(model.rowCount()):
        index = model.index(row, 0)
        doc = docs.get(index.data(Qt.DisplayRole))
        if doc is None or not (every or tree.isExpanded(index)):
            continue
        bodies = {obj.Label: obj for obj in doc.Objects if obj.TypeId == BODY}
        if bodies:
            walk(index, doc, bodies, 0)
    return out


def _by_label(body):
    """The body's objects (its features, its Origin and the Origin's planes) by label, the tree
    showing labels; the same label twice is taken in order."""
    objs = list(body.Group)
    origin = getattr(body, "Origin", None)
    if origin is not None:
        objs.append(origin)
        objs.extend(getattr(origin, "OriginFeatures", None) or [])
    out = {}
    for obj in objs:
        out.setdefault(obj.Label, []).append(obj)
    return out


def _same(by_label, text):
    """The objects a row's text names: the text as it is, else without the sketch state the style
    puts first ("(-) Sketch1")."""
    return by_label.get(text or "") or by_label.get(sketchstatus.label_of(text))


def _named(names, text):
    return names.get(text) if text in names else names.get(sketchstatus.label_of(text))


def body_children(tree, body, index):
    """(model index, object or None, rolled back) for each row right under a body's row, in
    order. Rolled back: from the first solid feature after the Tip on."""
    model = tree.model()
    by_label = _by_label(body)
    solid = {obj.Name for obj in solid_features(body)}
    order = {obj.Name: k for k, obj in enumerate(body.Group)}
    tip = body.Tip
    tip_at = order.get(tip.Name, -1) if tip is not None else -1
    out, back = [], False
    folder_labels = {f.Label: f for f in treefolders.folders(body.Document)}
    rows = []                    # (model index, the folder row it sits in or None)
    for row in range(model.rowCount(index)):
        child = model.index(row, 0, index)
        rows.append((child, None))
        text = child.data(Qt.DisplayRole)
        if text in folder_labels:

            rows.extend((model.index(k, 0, child), child) for k in range(model.rowCount(child)))
    objs = []
    for child, _in in rows:
        text = child.data(Qt.DisplayRole)
        same = _same(by_label, text)
        objs.append(same.pop(0) if same else folder_labels.get(text))
    for k, (child, _in) in enumerate(rows):
        obj = objs[k]
        if obj is not None and obj.Name in solid and order.get(obj.Name, -1) > tip_at:
            back = True
        elif not back and obj is not None and treefolders.is_folder(obj):

            # the bar goes above it, right after the last live feature
            inside = [objs[j] for j in range(k + 1, len(rows)) if rows[j][1] == child
                      and objs[j] is not None and objs[j].Name in solid]
            if inside and all(order.get(o.Name, -1) > tip_at for o in inside):
                back = True
        out.append((child, obj, back))
    return out


def folder_back(folder):
    ""
    try:
        if not enabled():
            return False
        inside = treefolders.items(folder)
        body = body_of(inside[0]) if inside else None
        if body is None or body.Tip is None:
            return False
        solid = {obj.Name for obj in solid_features(body)}
        order = {obj.Name: k for k, obj in enumerate(body.Group)}
        tip_at = order.get(body.Tip.Name, -1)
        inside = [o for o in inside if o.Name in solid]
        return bool(inside) and all(order.get(o.Name, -1) > tip_at for o in inside)
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:folder-back", _fw_err)
        return False


def folders_to_open(tree, body, index):
    ""

    out, seen = [], {}
    for child, obj, back in body_children(tree, body, index):
        parent = child.parent()
        if parent != index:
            seen.setdefault((parent.row(), parent.internalId()), [parent, set()])[1].add(back)
    for parent, backs in seen.values():
        if backs == {True, False} and not tree.isExpanded(parent):
            out.append(parent)
    return out


def layout(tree, doc, body, index):
    """Where the body's bar goes, or None while the body is folded or out of sight."""
    if not tree.isExpanded(index) or _shown(tree, index) is None:
        return None
    solids = solid_features(body)
    solid_names = [obj.Name for obj in solids]
    rows = []                    # (object or None, rolled back, top, bottom with what is open under it)
    for child, obj, back in body_children(tree, body, index):
        rect = _shown(tree, child)
        if rect is not None:
            rows.append((obj, back, rect.top(), _bottom(tree, child)))
    mine = [row for row in rows if row[0] is not None] or rows    # not rows after the body's (fmtree)
    end_y = (mine[-1][3] if mine else _shown(tree, index).bottom()) + 1
    bar_y = next((top for obj, back, top, bottom in rows if back), end_y)
    gaps, first = [], True
    for obj, back, top, bottom in rows:
        if obj is not None and treefolders.is_folder(obj):
            inside = [o for o in treefolders.items(obj) if o.Name in solid_names]
            if inside:
                # above a folder: the Tip is the feature before its first one
                k = min(solid_names.index(o.Name) for o in inside)
                gaps.append((top, solids[k - 1] if k > 0 else None))
                first = False
            continue
        if obj is None or obj.Name not in solid_names:
            continue
        if first:
            gaps.append((top, None))
        else:
            gaps.append((top, solids[solid_names.index(obj.Name) - 1]))
        first = False
    gaps.append((end_y, solids[-1] if solids else None))
    return Layout(doc, body, bar_y, end_y, gaps)


def layouts(tree):
    """The bars of the tree's bodies (paint and tick ask in the same pass: kept until the event
    loop runs, keyed on what moves them)."""
    from . import tickcache
    try:
        first = tree.model().index(0, 0)
        anchor = tree.visualRect(first).top() if first.isValid() else 0
        # rows a filter hid (setHidden on the items: no model signal) move the bar too
        key = ("rollback layouts", id(tree), tree.viewport().width(),
               tuple((d.Name, b.Name, getattr(b.Tip, "Name", None), len(b.Group), _hidden_rows(tree, i))
                     for d, b, i in body_rows(tree)))
    except Exception:
        return _layouts(tree)
    # scrolling only shifts the rows: a layout is moved, not made again, until the tree's rows
    # change (expand, collapse, rows added, moved or removed, a reset)
    held = _HELD.get(id(tree))
    if held is not None and held[0] == key:
        was, lays = held[1], held[2]
    else:
        was, lays = tickcache.get(key, lambda: (anchor, _layouts(tree)))
        _watch_rows(tree)
        _HELD[id(tree)] = (key, was, lays)
    if was == anchor:
        return lays
    d = anchor - was
    return [Layout(l.doc, l.body, l.bar_y + d, l.end_y + d, [(y + d, f) for y, f in l.gaps]) for l in lays]


def _hidden_rows(tree, index):
    """Which rows under a body row are hidden now (the tree filter hides rows without telling the model)."""
    model = tree.model()
    return tuple(r for r in range(model.rowCount(index)) if tree.isRowHidden(r, index))


_HELD = {}          # id(tree) -> (key, anchor y, layouts)
_WATCHED = {}


def _forget_layouts(tree_id):
    _HELD.pop(tree_id, None)


def _watch_rows(tree):
    """Drops the held layout whenever the tree's rows move."""
    model = tree.model()
    tid = id(tree)
    if _WATCHED.get(tid) is model:
        return
    _WATCHED[tid] = model
    drop = lambda *a, t=tid: _forget_layouts(t)
    for sig in (tree.expanded, tree.collapsed, model.rowsInserted, model.rowsRemoved, model.rowsMoved,
                model.layoutChanged, model.modelReset):
        try:
            sig.connect(drop)
        except Exception as _fw_err:
            _fw_log("rollbackbar.py:606", _fw_err)
    try:
        tree.destroyed.connect(lambda *a, t=tid: (_HELD.pop(t, None), _WATCHED.pop(t, None)))
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:610", _fw_err)


def _layouts(tree):
    out = []
    for doc, body, index in body_rows(tree):
        try:
            lay = layout(tree, doc, body, index)
        except Exception:
            lay = None
        if lay is not None:
            out.append(lay)
    return out


def _descendants(model, index, depth=0):
    for row in range(model.rowCount(index)):
        child = model.index(row, 0, index)
        yield child
        if depth < 6:
            yield from _descendants(model, child, depth + 1)


def _plain(obj):
    """No error, no rebuild due and not suppressed: FreeCAD's row then has no marks on its icon."""
    try:
        if obj.ViewObject is None or not obj.isValid() or getattr(obj, "Suppressed", False):
            return False
        state = obj.State
        return "Touched" not in state and "Invalid" not in state and "Error" not in state
    except Exception:
        return False


def _is_solid(obj):
    return (_derived(obj, "PartDesign::Feature") and not _derived(obj, "Part::Datum")
            and not _derived(obj, "App::DatumElement"))


def _object(key):
    doc = App.listDocuments().get(key[0]) if key else None
    return doc.getObject(key[1]) if doc is not None else None


def _fg(index):
    value = index.data(Qt.ForegroundRole)
    if isinstance(value, QtGui.QBrush):
        return value.color()
    return value if isinstance(value, QtGui.QColor) else None


_MARKS = {}


def _mark(name, dpr):
    """One of FreeCAD's small marks on a tree icon, 10 px as FreeCAD draws them."""
    key = (name, dpr)
    if key not in _MARKS:
        pixmap = None
        try:
            from PySide6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(":/icons/%s.svg" % name)
            if renderer.isValid():
                pixmap = QtGui.QPixmap(QtCore.QSize(10, 10) * dpr)
                pixmap.setDevicePixelRatio(dpr)
                pixmap.fill(Qt.transparent)
                painter = QtGui.QPainter(pixmap)
                renderer.render(painter, QtCore.QRectF(0, 0, 10, 10))
                painter.end()
        except Exception:
            pixmap = None
        if pixmap is None:
            try:
                pixmap = Gui.getIcon(name).pixmap(10, 10)
            except Exception:
                pixmap = QtGui.QPixmap()
        _MARKS[key] = pixmap
    return _MARKS[key]


def _marks(obj, body):
    ""


    out = []
    if obj.TypeId == "Sketcher::SketchObject" and not getattr(obj, "FullyConstrained", True):
        out.append("Sketcher_NotFullyConstrained")
    return out


def _is_tip(obj, body):
    tip = getattr(body, "Tip", None)
    return tip is not None and obj is not None and tip.Name == obj.Name


def _status_mark(obj):
    """The mark FreeCAD puts at the top right of a row's icon for its state (Tree.cpp testStatus):
    an error, or a rebuild due. None for a feature that is up to date."""
    try:
        state = obj.State
        if "Invalid" in state or "Error" in state or not obj.isValid():
            return "overlay_error"
        if "Touched" in state or getattr(obj, "MustExecute", False):
            return "overlay_recompute"
    except Exception as _fw_err:
        _fw_log("rollbackbar.py:712", _fw_err)
    return None


def row_icon(tree, obj, body, grey):
    """The icon FreeCAD gives a row of the object, shown (grey False) or hidden (grey True), with
    the same pixmap for the Disabled mode: FreeCAD paints a hidden object's row disabled. With
    FreeCAD's own marks: an error or a rebuild due at the top right, the Tip's and a sketch's at
    the bottom right. So a row keeps the same picture in every state, and only the marks change."""
    size = tree.iconSize()
    side = size.width() if size.isValid() and size.width() > 0 else \
        tree.style().pixelMetric(QtWidgets.QStyle.PM_SmallIconSize)
    source = obj.ViewObject.Icon
    if source is None or source.isNull():
        return None
    dpr = tree.devicePixelRatioF()
    marks = [_mark(name, dpr) for name in _marks(obj, body)]
    status = _status_mark(obj)
    status = _mark(status, dpr) if status else None
    mode = QtGui.QIcon.Disabled if grey else QtGui.QIcon.Normal
    icon = QtGui.QIcon()
    for state in (QtGui.QIcon.Off, QtGui.QIcon.On):
        pixmap = source.pixmap(side, side, mode, state)
        if pixmap.isNull():
            continue
        if marks or status is not None:
            painter = QtGui.QPainter(pixmap)
            if status is not None and not status.isNull():
                painter.drawPixmap(side - 10, 0, 10, 10, status)              # top right, as FreeCAD puts it
            for mark in marks:
                if not mark.isNull():
                    painter.drawPixmap(side - 10, side - 10, 10, 10, mark)    # bottom right, as FreeCAD puts them
            painter.end()
        icon.addPixmap(pixmap, QtGui.QIcon.Normal, state)
        icon.addPixmap(pixmap, QtGui.QIcon.Disabled, state)
    return icon


def _icon_key(index):
    """What tells one icon of a row from another (FreeCAD's rewritten one from the one set here)."""
    try:
        value = index.data(Qt.DecorationRole)
        return value.cacheKey() if isinstance(value, (QtGui.QIcon, QtGui.QPixmap)) else None
    except Exception:
        return None


def _usable(obj):
    try:
        return obj.ViewObject is not None
    except Exception:
        return False


class Overlay(QtWidgets.QWidget):
    """Paints the bars over the tree's viewport. A sibling of the viewport, not a child: the tree
    scrolls its viewport's children along with the rows."""

    def __init__(self, owner, tree):
        super().__init__(tree)
        self.owner = owner
        self.tree = tree
        self.setObjectName("SWRollbackBar")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.place()
        self.show()
        self.raise_()

    def place(self):
        viewport = self.tree.viewport()
        if self.geometry() != viewport.geometry():
            self.setGeometry(viewport.geometry())
        self.raise_()

    def paintEvent(self, event):
        try:
            shown = self.owner.shown(self.tree)
        except Exception:
            return
        if not shown:
            return
        painter = QtGui.QPainter(self)
        dpr = self.devicePixelRatioF()
        light = max(2, round(LIGHT_PX * dpr)) / dpr
        dark = max(1, round(DARK_PX * dpr)) / dpr
        width = self.width()
        picked = set(self.owner.picked_ys(self.tree))
        for bar_y in shown:
            if bar_y in picked:
                # the picked bar: dark all through, with a dotted edge as a picked row has
                painter.fillRect(QtCore.QRectF(0, bar_y - 0.5, width, light + dark + 1), DARK)
                pen = QtGui.QPen(LIGHT, 1, Qt.DotLine)
                painter.setPen(pen)
                painter.drawRect(QtCore.QRectF(0.5, bar_y - 1.5, width - 1, light + dark + 3))
                continue
            painter.fillRect(QtCore.QRectF(0, bar_y, width, light), LIGHT)
            painter.fillRect(QtCore.QRectF(0, bar_y + light, width, dark), DARK)
        painter.end()


class RollbackBar(QtCore.QObject):
    """The bars on FreeCAD's tree in the left pane, wherever that tree is shown (also while the
    flyout feature tree has it)."""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.tree = None
        self.overlay = None
        self.drag = None             # (body key, gaps, preview (y, Tip)) while the bar is dragged
        self.menu = None             # the bar's right-click menu while it is up
        self._menu_body = None
        self._right = None           # body key of a right-press on a bar
        self.picked = None           # body key of the bar a click picked (Up / Down move it)
        self._cursor = False         # the hand pointer is set on the viewport
        self._sig = None
        self._opened = []            # persistent indexes of bodies already opened (or seen open)
        self._changed = {}           # row (internal id) -> (document name, object name) whose look this set
        self._applying = False
        self._looks_due = False
        self.drags = 0               # for checks
        ROLLS.after.append(self._rolled)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.tick()

    # ------------------------------------------------------------ the tree
    def _find_tree(self):
        ""

        pane = getattr(self.shell, "left_pane", None)
        tree = pane.tree_widget() if pane is not None and alive(pane) else None
        if tree is None and self.tree is not None and alive(self.tree):
            tree = self.source
        manager = getattr(self.shell, "feature_manager", None)
        view = getattr(manager, "view", None)
        if tree is not None and view is not None and alive(view) and view.tree is tree:
            return view
        return tree

    @property
    def source(self):
        """FreeCAD's tree, whose rows get the grey looks (the ordered tree shows them from there)."""
        return getattr(self.tree, "tree", self.tree)

    def _signals(self, tree):
        model = getattr(tree, "tree", tree).model()
        return ((tree.verticalScrollBar().valueChanged, self._repaint), (tree.expanded, self._repaint),
                (tree.collapsed, self._repaint), (model.dataChanged, self._data_changed),
                (model.rowsInserted, self._rows_inserted))

    def attach(self, tree):
        if tree is self.tree and self.overlay is not None and alive(self.overlay):
            self.overlay.place()
            return
        self.detach()
        self.tree = tree
        self.overlay = Overlay(self, tree)
        tree.installEventFilter(self)
        tree.viewport().installEventFilter(self)
        for signal, slot in self._signals(tree):
            signal.connect(slot)

    def detach(self):
        tree, overlay = self.tree, self.overlay
        self.drag = None
        self._close_menu()
        if tree is not None and alive(tree):
            self._set_cursor(tree.viewport(), False)
            tree.removeEventFilter(self)
            tree.viewport().removeEventFilter(self)
            for signal, slot in self._signals(tree):
                try:
                    signal.disconnect(slot)
                except Exception as _fw_err:
                    _fw_log("rollbackbar.py:892", _fw_err)
        self._restore_looks()
        self.tree = self.overlay = None
        if overlay is not None and alive(overlay):
            overlay.hide()
            overlay.setParent(None)
            overlay.deleteLater()
        self._sig = None

    def _repaint(self, *args):
        if self.overlay is not None and alive(self.overlay):
            self.overlay.update()

    def tick(self):
        if not enabled():
            self.detach()
            return
        if _recomputing():
            self._looks_last = None      # one full pass when the rebuild ends
            return
        tree = self._find_tree()
        if tree is None or not alive(tree):
            self.detach()
            return
        self.attach(tree)
        try:
            self._open_new_bodies(tree)
            if self.source is not tree:
                self._open_new_bodies(self.source)    # FreeCAD's tree under the ordered one too (the flyout lends it)
            looks = self._looks_sig()
            self._looks_ticks = getattr(self, "_looks_ticks", 0) + 1
            # The rows' data and row signals already ask for the looks (_looks_soon); the tick only
            # catches what they miss, so it walks every row when the bodies changed, else every 8th
            # tick (27 ms a tick on a 200-feature part, about 4 a second, were the idle cost).
            if looks != getattr(self, "_looks_last", None) or self._looks_ticks >= 8:
                self._looks_last = looks
                self._looks_ticks = 0
                self.apply_looks()
            sig = tuple((lay.key(), lay.bar_y, lay.end_y) for lay in layouts(tree))
        except Exception:
            sig = None
        sig = (sig, tree.viewport().size().width(), tree.verticalScrollBar().value())
        if sig != self._sig:
            self._sig = sig
            self._repaint()

    @staticmethod
    def _looks_sig():
        """What the grey-under-the-bar looks hang on: each open document's bodies, their Tip and size."""
        out = []
        for doc in App.listDocuments().values():
            for obj in doc.Objects:
                if obj.TypeId == "PartDesign::Body":
                    tip = obj.Tip
                    out.append((doc.Name, obj.Name, tip.Name if tip is not None else "", len(obj.Group)))
        return tuple(out)

    def _open_new_bodies(self, tree):
        ""
        self._opened = [p for p in self._opened if p.isValid()]
        for doc, body, index in body_rows(tree):
            if any(p == index for p in self._opened):
                continue
            self._opened.append(QtCore.QPersistentModelIndex(index))
            if not tree.isExpanded(index):
                tree.expand(index)

    def _rolled(self, body):
        self._open_folders(body)
        self._repaint()
        self._looks_soon()

    def _open_folders(self, body):
        ""
        tree = self.tree
        if tree is None or not alive(tree):
            return
        try:
            for doc, b, index in body_rows(tree):
                if b is body and tree.isExpanded(index):
                    for folder in folders_to_open(tree, body, index):
                        tree.expand(folder)
        except Exception as _fw_err:
            _fw_log("rollbackbar.py:open-folders", _fw_err)

    def shown(self, tree):
        """The bars' y to paint, the dragged one where it would land."""
        out = []
        for lay in layouts(tree):
            bar_y = lay.bar_y
            if self.drag is not None and self.drag[0] == lay.key() and self.drag[2] is not None:
                bar_y = self.drag[2][0]
            out.append(bar_y)
        return out

    def picked_ys(self, tree):
        if self.picked is None or self.drag is not None:
            return []
        return [lay.bar_y for lay in layouts(tree) if lay.key() == self.picked]

    def pick(self, key):
        self.picked = key
        self._repaint()

    def step(self, up):
        """Up or Down with the bar picked: one feature up (Rollback) or down (Roll Forward)."""
        body = self._body(self.picked) if self.picked is not None else None
        if body is None or editing():
            return False
        if up:
            tip = body.Tip
            solids = [obj.Name for obj in solid_features(body)]
            done = tip is not None and tip.Name in solids and ROLLS.back_to(tip)
        else:
            done = ROLLS.forward(body)
        self._repaint()
        return done

    # ------------------------------------------------------------ grey means rolled back
    def apply_looks(self):
        """The text of rows above a bar as usual and grey under it, in every body of the tree (also
        folded ones, so nothing flickers when they open)."""
        tree = self.source
        if tree is None or not alive(tree):
            return
        model = tree.model()
        seen, seen_objects = set(), set()
        self._applying = True
        try:
            for doc, body, index in body_rows(tree, every=True):
                names = None
                for child, obj, back in body_children(tree, body, index):
                    self._look(child, obj, body, back, seen, seen_objects)
                    if not model.rowCount(child) or treefolders.is_folder(obj):
                        continue        # a folder's rows come one by one from body_children
                    if names is None:
                        names = {label: objs[0] for label, objs in _by_label(body).items()}
                    for sub in _descendants(model, child):
                        self._look(sub, _named(names, sub.data(Qt.DisplayRole)), body, back, seen, seen_objects)
        finally:
            self._applying = False
        for row in [row for row in self._changed if row not in seen]:
            key = self._changed.pop(row)[0]
            if key not in seen_objects:
                self._restore(key)
        if self.tree is not tree and self.tree is not None and alive(self.tree):
            self.tree.viewport().update()     # the ordered tree's own folder rows grey with the rest (fmtree)

    def _look(self, index, obj, body, back, seen, seen_objects):
        """Sets the row's look when FreeCAD's (or an earlier one of ours) does not fit: the text
        colour is not the one wanted, or FreeCAD has drawn the icon again since it was set here
        (it does so when the feature is touched, rebuilt, fails or is edited, and draws a hidden
        feature's icon grey; every feature of a part but the last is hidden)."""
        if obj is None or not _usable(obj):
            return
        row = index.internalId()
        key = (obj.Document.Name, obj.Name)
        colour = _fg(index)
        palette = self.source.palette()
        grey = back or bool(getattr(obj, "Suppressed", False))
        if grey:
            wrong = colour != palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        else:
            wrong = colour is not None and colour != palette.color(QtGui.QPalette.Active, QtGui.QPalette.Text)
        known = self._changed.get(row)
        if not wrong and known is not None and (len(known) < 4 or known[3] != _icon_key(index)):
            wrong = True
        if not wrong and known is None and _is_tip(obj, body):
            wrong = True
        if wrong:
            self._set_look(index, obj, body, grey)
            self._changed[row] = (key, (body.Document.Name, body.Name), back, _icon_key(index))
        if row in self._changed:
            seen.add(row)
            seen_objects.add(key)

    def _set_look(self, index, obj, body, grey):
        """Grey text under the bar, the usual text above it: set outright, FreeCAD's tree takes an
        explicit colour even on a row it paints disabled. The icon: grey under the bar; above it
        a feature's own icon as usual, a hidden sketch's or plane's grey as FreeCAD has it."""
        palette = self.source.palette()
        colour = palette.color(QtGui.QPalette.Disabled if grey else QtGui.QPalette.Active, QtGui.QPalette.Text)
        model = index.model()
        model.setData(index, QtGui.QBrush(colour), Qt.ForegroundRole)
        hidden = not obj.ViewObject.Visibility
        icon = row_icon(self.source, obj, body, grey or (hidden and not _is_solid(obj)))
        if icon is not None:
            model.setData(index, icon, Qt.DecorationRole)

    @staticmethod
    def _restore(key):
        """FreeCAD's own look for every row of the object."""
        obj = _object(key)
        try:
            if obj is not None and obj.ViewObject is not None:
                obj.ViewObject.signalChangeIcon()
        except Exception as _fw_err:
            _fw_log("rollbackbar.py:1071", _fw_err)

    def _restore_looks(self):
        changed, self._changed = self._changed, {}
        self._applying = True
        try:
            for key in set(entry[0] for entry in changed.values()):
                self._restore(key)
        finally:
            self._applying = False

    def _looks_soon(self):
        """Once FreeCAD has finished with the rows: before the tree is painted, which Qt posts with
        a lower priority than this."""
        if not self._looks_due:
            self._looks_due = True
            QtCore.QTimer.singleShot(0, self._looks_now)

    def _looks_now(self):
        self._looks_due = False
        if _recomputing():
            # rows change by the hundred while a rebuild runs (FreeCAD lets the event loop run):
            # the looks are put right once, by the first tick after it
            self._looks_last = None
            return
        if self.tree is not None and enabled():
            try:
                self.apply_looks()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: rollback bar: %s\n" % error)

    def _data_changed(self, first, last, roles=()):
        """FreeCAD rewrites a row's look when its object is shown, hidden, touched, rebuilt or made
        the Tip. A row this set is set again at once, before anything is painted."""
        if self._applying or self.tree is None or (roles and not any(_role(role) in LOOK_ROLES for role in roles)):
            return
        known = self._changed.get(first.internalId()) if first.column() == 0 else None
        if known is None:
            self._looks_soon()
            return
        key, body_key, back = known[:3]
        obj, body = _object(key), _object(body_key)
        if obj is None or body is None or body.TypeId != BODY or not _usable(obj):
            self._looks_soon()
            return
        self._applying = True
        try:
            self._set_look(first, obj, body, back or bool(getattr(obj, "Suppressed", False)))
            self._changed[first.internalId()] = (key, body_key, back, _icon_key(first))
        except Exception as _fw_err:
            _fw_log("rollbackbar.py:1121", _fw_err)
        finally:
            self._applying = False

    def _rows_inserted(self, *args):
        if not self._applying:
            self._looks_soon()

    # ------------------------------------------------------------ the mouse
    def _at_bar(self, y):
        tree = self.tree
        if tree is None:
            return None
        for lay in layouts(tree):
            middle = lay.bar_y + (LIGHT_PX + DARK_PX) / 2.0
            if abs(y - middle) <= GRAB:
                return lay
        return None

    def _set_cursor(self, viewport, on, shape=Qt.OpenHandCursor):
        if on:
            viewport.setCursor(shape)
            self._cursor = True
        elif self._cursor:
            viewport.unsetCursor()
            self._cursor = False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        tree = self.tree
        if tree is None or not alive(tree):
            return False
        t = event.type()
        if obj is tree:
            if t == QtCore.QEvent.KeyPress and self.picked is not None and arrow_keys():
                key = event.key()
                if key in (Qt.Key_Up, Qt.Key_Down) and not event.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
                    self.step(key == Qt.Key_Up)
                    return True
                if key == Qt.Key_Escape:
                    self.pick(None)
                    return True
                self.pick(None)
                return False
            if t == QtCore.QEvent.FocusOut and self.picked is not None and event.reason() != Qt.PopupFocusReason:
                self.pick(None)
            if t in (QtCore.QEvent.Resize, QtCore.QEvent.LayoutRequest, QtCore.QEvent.Show):
                if self.overlay is not None and alive(self.overlay):
                    self.overlay.place()
            return False
        if obj is not tree.viewport():
            return False
        try:
            return self._viewport_event(obj, event, t)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: rollback bar: %s\n" % error)
            self.drag = None
            return False

    def _cancel_drag(self, viewport):
        self.drag = None
        self._set_cursor(viewport, False)
        self._repaint()

    def _viewport_event(self, viewport, event, t):
        if t == QtCore.QEvent.Resize:
            if self.overlay is not None and alive(self.overlay):
                self.overlay.place()
            return False
        if t in (QtCore.QEvent.MouseMove, QtCore.QEvent.HoverMove):
            y = event.position().y()
            if self.drag is not None:
                if t == QtCore.QEvent.MouseMove:
                    if not event.buttons() & Qt.LeftButton:
                        self._cancel_drag(viewport)     # the release went somewhere else
                        return False
                    self._drag_to(y)
                return True
            if t == QtCore.QEvent.MouseMove and event.buttons() != Qt.NoButton:
                return False
            self._set_cursor(viewport, self._at_bar(y) is not None and not editing())
            return False
        if t == QtCore.QEvent.MouseButtonPress:
            if self.drag is not None:
                self._cancel_drag(viewport)
            lay = self._at_bar(event.position().y())
            if lay is None or editing():
                if self.picked is not None:
                    self.pick(None)
                return False
            if event.button() == Qt.LeftButton:
                self.drag = (lay.key(), lay.gaps, (lay.bar_y, lay.body.Tip))
                self._set_cursor(viewport, True, Qt.ClosedHandCursor)
                self._repaint()
                return True
            if event.button() == Qt.RightButton:
                self._right = lay.key()
                return True
            return False
        if t == QtCore.QEvent.MouseButtonRelease:
            if self.drag is not None and event.button() == Qt.LeftButton:
                self._drop()
                self._set_cursor(viewport, self._at_bar(event.position().y()) is not None)
                return True
            if self._right is not None and event.button() == Qt.RightButton:
                key, self._right = self._right, None
                self.open_menu(key, viewport.mapToGlobal(event.position().toPoint()))
                return True
            return False
        if t == QtCore.QEvent.MouseButtonDblClick:
            return self._at_bar(event.position().y()) is not None and not editing()
        if t == QtCore.QEvent.ToolTip:
            lay = self._at_bar(event.pos().y())
            text = bar_tip(lay.body) if lay is not None else ""
            if text:
                QtWidgets.QToolTip.showText(event.globalPos(), text, viewport)
                return True
            return False
        if t == QtCore.QEvent.ContextMenu:
            return self._right is not None or (self._at_bar(event.pos().y()) is not None and not editing())
        if t in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave) and self.drag is None:
            self._set_cursor(viewport, False)
        return False

    def _drag_to(self, y):
        key, gaps, preview = self.drag
        body = self._body(key)
        if body is not None:
            gaps = [g for g in gaps if not above_freeze(body, g[1])]     # the bar stops at the Freeze bar
        if gaps:
            best = min(gaps, key=lambda gap: abs(gap[0] - y))
            if preview is None or best[0] != preview[0]:
                self.drag = (key, gaps, best)
                self._repaint()

    def _drop(self):
        key, gaps, preview = self.drag
        self.drag = None
        self.drags += 1
        body = self._body(key)
        moved = False
        if body is not None and preview is not None:
            tip = preview[1]
            if tip is None:         # the gap above the first feature: no Tip (Rollback on the first feature)
                solids = solid_features(body)
                moved = bool(solids) and ROLLS.back_to(solids[0])
            else:
                moved = ROLLS.roll(body, tip)
        # a click that did not move it picks the bar, for the arrow keys
        self.picked = None if moved else key
        if not moved and self.tree is not None and alive(self.tree):
            self.tree.setFocus(Qt.MouseFocusReason)
        self._repaint()

    @staticmethod
    def _body(key):
        doc = App.getDocument(key[0]) if key[0] in App.listDocuments() else None
        body = doc.getObject(key[1]) if doc is not None else None
        return body if body is not None and body.TypeId == BODY else None

    # ------------------------------------------------------------ the menu
    def open_menu(self, key, global_pos):
        ""
        body = self._body(key)
        if body is None:
            return None
        self._close_menu()
        can = ROLLS.can(body)
        if not any(can.values()):
            return None             # nothing applies (at the end, never moved): no menu of dead entries
        menu = QtWidgets.QMenu(self.tree)
        menu.setObjectName("SWRollbackMenu")
        for name, text in MENU:
            if not can[name]:
                continue            # only what applies now (no greyed entries)
            action = menu.addAction(text)
            action.setObjectName(name)
            action.triggered.connect(lambda checked=False, name=name, key=key: self._chosen(name, key))
        menu.aboutToHide.connect(self._menu_hidden)
        self.menu, self._menu_body = menu, key
        menu.popup(global_pos)
        return menu

    def _chosen(self, name, key):
        body = self._body(key)
        if body is None:
            return
        {"RollForward": ROLLS.forward, "RollToPrevious": ROLLS.to_previous, "RollToEnd": ROLLS.to_end,
         "DeleteBelow": ROLLS.delete_below}[name](body)
        self._repaint()

    def _menu_hidden(self):
        menu = self.menu
        self.menu = self._menu_body = None
        if menu is not None and alive(menu):
            menu.deleteLater()

    def _close_menu(self):
        menu = self.menu
        if menu is not None and alive(menu):
            menu.hide()

    def remove(self):
        self.timer.stop()
        try:
            ROLLS.after.remove(self._rolled)
        except ValueError as _fw_err:
            _fw_log("rollbackbar.py:1323", _fw_err)
        self.detach()
