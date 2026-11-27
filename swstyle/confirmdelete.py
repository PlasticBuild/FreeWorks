# SPDX-License-Identifier: LGPL-2.1-or-later
""


















from . import editobj

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

COMMAND = "Std_Delete"
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/ConfirmDelete"
DIMENSIONS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
SKETCH = "Sketcher::SketchObject"
BODY = "PartDesign::Body"
SKETCHER_TEXT = ("This item has dimensions on it or is referenced outside the sketch. "
                 "Do you want to delete it anyway?")
# links that only say where a feature sits in the body, not what it is built from
ORDER_LINKS = ("BaseFeature", "Group", "Tip", "Origin", "_GroupTouched")

_passing = [False]      # our own call of FreeCAD's Delete
LAST = []               # the last dialog, for checks


def params():
    return App.ParamGet(PARAMS)


# ---- what an object depends on --------------------------------------------------------------

def _refs(value):
    """[(object, [subs])] in a property value."""
    out = []
    if isinstance(value, App.DocumentObject):
        out.append((value, []))
    elif isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], App.DocumentObject):
        subs = value[1]
        out.append((value[0], list(subs) if isinstance(subs, (list, tuple)) else [subs]))
    elif isinstance(value, (list, tuple)):
        for v in value:
            out += _refs(v)
    return out


def links_to(obj, target):
    """{property: [subs]} of obj that point at target."""
    out = {}
    for prop in obj.PropertiesList:
        if prop in ORDER_LINKS:
            continue
        try:
            if "Link" not in obj.getTypeIdOfProperty(prop):
                continue
            value = getattr(obj, prop)
        except Exception:
            continue
        for o, subs in _refs(value):
            if o == target:
                out.setdefault(prop, []).extend(subs)
    return out


def _helper(obj):
    return type(getattr(obj, "Proxy", None)).__name__ in ("SelectedContours", "NoMerge")


def users(target):
    """The objects built from target (not the body's order links), each once."""
    out = []
    for obj in target.InList:
        if obj.TypeId == BODY or obj in out:
            continue
        if links_to(obj, target):
            out.append(obj)
    return out


def dependents(target):
    """[(object, used)] everything built on target, directly or not; used = what it uses."""
    out = []
    seen = {target.Name}
    todo = [target]
    while todo:
        cur = todo.pop(0)
        for obj in users(cur):
            if obj.Name in seen:
                continue
            seen.add(obj.Name)
            todo.append(obj)
            if _helper(obj):
                continue
            out.append((obj, cur))
    return out


def _feature_users(sketch):
    """The features built on a sketch, straight or through its Selected Contours."""
    out = []
    for u in users(sketch):
        for f in ([o for o in users(u) if not _helper(o)] if _helper(u) else [u]):
            if f not in out:
                out.append(f)
    return out


def shared(sketch, feature):
    """The other features a sketch also makes (a shared sketch), besides feature."""
    return [f for f in _feature_users(sketch) if f is not feature and f.TypeId != SKETCH]


def absorbed(feature, shared_too=False):
    ""

    out = []
    for prop in ("Profile", "Spine", "Sections", "AuxiliarySpine"):
        try:
            value = getattr(feature, prop)
        except Exception:
            continue
        for o, _subs in _refs(value):
            if _helper(o) and getattr(o, "Sketch", None) is not None:
                o = o.Sketch
            if o.TypeId == SKETCH and o not in out and (shared_too or not shared(o, feature)):
                out.append(o)
    return out


def _mentions(expr, obj):
    """True when an expression uses obj (by its name, or its label in << >>)."""
    import re
    try:
        if re.search(r"(?<![\w.])%s\." % re.escape(obj.Name), expr):
            return True
        return ("<<%s>>" % obj.Label) in expr
    except Exception:
        return False


def dangling_equations(gone):
    ""


    if not gone:
        return []
    doc = gone[0].Document
    names = {o.Name for o in gone}
    try:
        from . import equations
        rows = equations.equations(doc)
    except Exception:
        rows = []
        for o in doc.Objects:
            for path, expr in getattr(o, "ExpressionEngine", []) or []:
                rows.append((o, path, expr))
    return [(o, path, expr) for o, path, expr in rows
            if o.Name not in names and any(_mentions(expr, g) for g in gone)]


def _equation_text(o, path, expr):
    try:
        from . import equations
        left = '"%s"' % equations.sw_name(o, path)
        right = equations.to_sw(o.Document, expr)
    except Exception:
        left, right = "%s%s" % (o.Label, path), expr
    return "%s = %s" % (left, right)


def kind(obj):
    return "Sketch" if obj.TypeId == SKETCH else "Feature"


def entry(obj):
    return "%s ( %s )" % (obj.Label, kind(obj))


def body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == BODY:
            return parent
    return None


# ---- the feature dialog ---------------------------------------------------------------------

class ConfirmDelete(QtWidgets.QDialog):
    YES, YES_ALL, NO, CANCEL = 1, 2, 3, 4

    def __init__(self, item, many, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.item = item
        self.answer = self.CANCEL
        self.setWindowTitle("Confirm Delete")
        self.setObjectName("SWConfirmDelete")
        p = params()
        self.absorbed = absorbed(item)
        self.children = dependents(item)
        row = QtWidgets.QHBoxLayout(self)
        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel("Delete the following item?"))
        self.name = QtWidgets.QLineEdit(entry(item))
        self.name.setReadOnly(True)
        self.name.setObjectName("SWConfirmDeleteItem")
        left.addWidget(self.name)
        left.addWidget(QtWidgets.QLabel("And all dependent items:"))
        self.list = QtWidgets.QTreeWidget()
        self.list.setObjectName("SWConfirmDeleteDependents")
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        self.list.setMinimumSize(270, 120)
        left.addWidget(self.list)
        self.absorbed_box = QtWidgets.QCheckBox("Delete absorbed features")
        self.absorbed_box.setObjectName("SWConfirmDeleteAbsorbed")
        self.absorbed_box.setVisible(bool(self.absorbed))      # msgbox-1119: options that do not apply are left out
        self.absorbed_box.setChecked(bool(self.absorbed) and p.GetBool("DeleteAbsorbed", False))
        self.absorbed_box.setToolTip("Also deletes the sketch the feature was made from")
        self.child_box = QtWidgets.QCheckBox("Delete child features")
        self.child_box.setObjectName("SWConfirmDeleteChildren")
        self.child_box.setChecked(p.GetBool("DeleteChildren", True))
        self.child_box.setVisible(bool(self.children))
        self.child_box.setToolTip("Also deletes the sketches and features built on it")

        self.equations = dangling_equations([item] + [o for o, _u in self.children])
        self.equation_box = QtWidgets.QCheckBox("Delete equations")
        self.equation_box.setObjectName("SWConfirmDeleteEquations")
        self.equation_box.setVisible(bool(self.equations))
        self.equation_box.setChecked(bool(self.equations) and p.GetBool("DeleteEquations", False))
        self.equation_box.setToolTip("Also deletes the equations that use the deleted items")
        self.again = QtWidgets.QCheckBox("Don't show again")
        self.again.setObjectName("SWConfirmDeleteDontShow")
        for w in (self.absorbed_box, self.child_box, self.equation_box, self.again):
            left.addWidget(w)
        row.addLayout(left)
        right = QtWidgets.QVBoxLayout()
        self.buttons = {}
        for key, text, answer in (("Yes", "&Yes", self.YES), ("YesToAll", "Yes to &All", self.YES_ALL),
                                  ("No", "&No", self.NO), ("Cancel", "&Cancel", self.CANCEL)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("SWConfirmDelete" + key)
            b.clicked.connect(lambda _c=False, a=answer: self.done_with(a))
            right.addWidget(b)
            self.buttons[key] = b
        self.buttons["YesToAll"].setVisible(bool(many))
        self.buttons["Yes"].setDefault(True)
        helpb = QtWidgets.QPushButton("&Help")
        helpb.setObjectName("SWConfirmDeleteHelp")
        helpb.clicked.connect(self.show_help)
        right.addWidget(helpb)
        right.addStretch(1)
        self.advanced = QtWidgets.QPushButton("Advanced")
        self.advanced.setObjectName("SWConfirmDeleteAdvanced")
        self.advanced.setCheckable(True)
        self.advanced.setToolTip("Shows each dependent item under the item it is built on")
        self.advanced.setVisible(bool(self.children))
        self.advanced.toggled.connect(self.fill)
        right.addWidget(self.advanced)
        row.addLayout(right)
        self.absorbed_box.toggled.connect(self.fill)
        self.child_box.toggled.connect(self.fill)
        self.child_box.toggled.connect(self._equations_again)
        self.equation_box.toggled.connect(self.fill)
        self.fill()
        LAST[:] = [self]

    def fill(self, *args):
        self.list.clear()
        tree = self.advanced.isChecked()
        self.list.setRootIsDecorated(tree)
        made = {}
        if self.child_box.isChecked():
            for obj, used in self.children:
                parent = made.get(used.Name) if tree else None
                item = QtWidgets.QTreeWidgetItem([entry(obj)])
                if parent is not None:
                    parent.addChild(item)
                else:
                    self.list.addTopLevelItem(item)
                made[obj.Name] = item
        if self.absorbed_box.isChecked():
            for obj in self.absorbed:
                if obj.Name not in made:
                    self.list.addTopLevelItem(QtWidgets.QTreeWidgetItem(["%s ( Absorbed )" % obj.Label]))
        if self.equation_box.isChecked():
            for o, path, expr in self.equations:
                self.list.addTopLevelItem(QtWidgets.QTreeWidgetItem(["%s ( Equation )" % _equation_text(o, path, expr)]))
        self.list.expandAll()

    def _equations_again(self, *args):
        gone = [self.item] + ([o for o, _u in self.children] if self.child_box.isChecked() else [])
        self.equations = dangling_equations(gone)
        self.equation_box.setVisible(bool(self.equations))
        if not self.equations:
            self.equation_box.setChecked(False)

    def listed(self):
        return [self.list.topLevelItem(i).text(0) for i in range(self.list.topLevelItemCount())]

    def show_help(self):
        try:
            from . import helpguide
            if helpguide.show_topic("confirm delete") is not None:
                return
            import Help
            Help.show("Std_Delete")
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: no help page for Delete (%s)\n" % error)

    def done_with(self, answer):
        self.answer = answer
        if answer != self.CANCEL:
            p = params()
            p.SetBool("DeleteChildren", self.child_box.isChecked())
            if self.absorbed:
                p.SetBool("DeleteAbsorbed", self.absorbed_box.isChecked())
            if self.equations:
                p.SetBool("DeleteEquations", self.equation_box.isChecked())
            if self.again.isChecked():
                p.SetBool("FeatureAsk", False)
        self.accept() if answer != self.CANCEL else self.reject()


def remove(objects):
    """Deletes objects (dependents first), as one Undo step; the body's order is kept."""
    if not objects:
        return
    doc = objects[0].Document
    order = []
    names = {o.Name for o in objects}
    # an object goes after everything built on it
    pending = list(objects)
    while pending:
        progress = False
        for obj in list(pending):
            if not any(u.Name in names and u in pending for u in users(obj) if u is not obj):
                order.append(obj)
                pending.remove(obj)
                progress = True
        if not progress:
            order += pending
            break
    for obj in order:
        if doc.getObject(obj.Name) is None:
            continue
        for helper in [u for u in obj.InList if _helper(u)]:
            if not [o for o in helper.InList if o.TypeId != BODY and o.Name not in names]:
                _drop(helper)
        _drop(obj)


def _drop(obj):
    doc = obj.Document
    body = body_of(obj)
    if body is not None:
        try:
            body.removeObject(obj)       # the next feature takes over its base, as FreeCAD's Delete does
        except Exception as _fw_err:
            _fw_log("confirmdelete.py:380", _fw_err)
    if doc.getObject(obj.Name) is not None:
        doc.removeObject(obj.Name)


def delete_features(objects):
    """Asks about each object (unless told not to) and deletes. True when it handled them."""
    doc = objects[0].Document
    p = params()
    gone = []
    shown = []
    ask = p.GetBool("FeatureAsk", True)
    all_yes = False
    for i, obj in enumerate(objects):
        if obj.Name in {g.Name for g in gone}:
            continue
        if ask and not all_yes:
            dialog = ConfirmDelete(obj, len(objects) - i > 1)
            dialog.exec()
            answer = dialog.answer
            if answer == ConfirmDelete.CANCEL:
                return True
            if answer == ConfirmDelete.NO:
                continue
            if answer == ConfirmDelete.YES_ALL:
                all_yes = True
            ask = p.GetBool("FeatureAsk", True)
        gone.append(obj)
        if p.GetBool("DeleteChildren", True):
            gone += [o for o, _u in dependents(obj) if o not in gone]
        for sketch in absorbed(obj):
            if p.GetBool("DeleteAbsorbed", False):
                if sketch not in gone:
                    gone.append(sketch)
            else:
                shown.append(sketch)
    if p.GetBool("DeleteAbsorbed", False):
        # a shared sketch goes too once every feature it makes is being deleted
        names = {g.Name for g in gone}
        for obj in list(gone):
            for sketch in absorbed(obj, shared_too=True):
                if sketch not in gone and all(f.Name in names for f in _feature_users(sketch)):
                    gone.append(sketch)
    if not gone:
        return True
    doc.openTransaction("Delete")
    bodies = {b.Name for b in (body_of(o) for o in gone) if b is not None}
    try:
        if p.GetBool("DeleteEquations", False):
            for o, path, _expr in dangling_equations(gone):
                try:
                    o.setExpression(path, None)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: delete equation %s%s: %s\n" % (o.Name, path, error))
        remove(gone)
        # the feature that is now last shows the part: FreeCAD leaves it hidden (it was hidden
        # under the deleted one), so the whole part seemed gone (ChatGPT 62-1109 item 6)
        for name in bodies:
            body = doc.getObject(name)
            tip = getattr(body, "Tip", None) if body is not None else None
            if tip is not None and App.GuiUp and tip.ViewObject is not None and not tip.ViewObject.Visibility:
                tip.ViewObject.Visibility = True
        for sketch in shown:
            if doc.getObject(sketch.Name) is not None and App.GuiUp:
                sketch.ViewObject.Visibility = True
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


# ---- the sketch dialog ----------------------------------------------------------------------

def edge_flags(sketch, geo):
    """(has dimensions, referenced outside the sketch) for geometry index geo."""
    dims = any(c.Type in DIMENSIONS and geo in (c.First, c.Second, c.Third) for c in sketch.Constraints)
    name = "Edge%d" % (geo + 1)
    outside = False
    for obj in sketch.InList:
        for subs in links_to(obj, sketch).values():
            if any(str(s).split(".")[-1] == name for s in subs):
                outside = True
    return dims, outside


class SketcherConfirmDelete(QtWidgets.QDialog):
    YES, YES_ALL, NO, CANCEL, REPLACE = 1, 2, 3, 4, 5

    def __init__(self, many, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.answer = self.CANCEL
        self.setWindowTitle("Sketcher Confirm Delete")
        self.setObjectName("SWSketcherConfirmDelete")
        lay = QtWidgets.QVBoxLayout(self)
        text = QtWidgets.QLabel(SKETCHER_TEXT)
        text.setWordWrap(True)
        text.setAlignment(QtCore.Qt.AlignCenter)
        text.setObjectName("SWSketcherConfirmDeleteText")
        lay.addWidget(text)
        row = QtWidgets.QHBoxLayout()
        self.buttons = {}
        for key, label, answer in (("Yes", "&Yes", self.YES), ("YesToAll", "Yes to &All", self.YES_ALL),
                                   ("No", "&No", self.NO), ("Cancel", "&Cancel", self.CANCEL)):
            b = QtWidgets.QPushButton(label)
            b.setObjectName("SWSketcherConfirmDelete" + key)
            b.clicked.connect(lambda _c=False, a=answer: self.done_with(a))
            row.addWidget(b)
            self.buttons[key] = b
        self.buttons["YesToAll"].setVisible(bool(many))
        self.buttons["Yes"].setDefault(True)
        lay.addLayout(row)
        replace = QtWidgets.QPushButton("Replace Entity")
        replace.setObjectName("SWSketcherConfirmDeleteReplace")
        replace.setToolTip("Keeps this entity and starts Replace Entity on it, so what uses it moves to the new one")
        replace.clicked.connect(lambda: self.done_with(self.REPLACE))
        self.buttons["Replace"] = replace
        middle = QtWidgets.QHBoxLayout()
        middle.addStretch(1)
        middle.addWidget(replace)
        middle.addStretch(1)
        lay.addLayout(middle)
        self.again = QtWidgets.QCheckBox("&Do not ask again")
        self.again.setObjectName("SWSketcherConfirmDeleteDontAsk")
        lay.addWidget(self.again)
        LAST[:] = [self]

    def done_with(self, answer):
        self.answer = answer
        if self.again.isChecked() and answer in (self.YES, self.YES_ALL):
            params().SetBool("SketcherAsk", False)
        self.accept() if answer != self.CANCEL else self.reject()


def _editing_sketch():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        obj = editobj.of(vp) if vp is not None else None
        return obj if obj is not None and obj.TypeId == SKETCH else None
    except Exception:
        return None


def delete_in_sketch(sketch):
    """Asks about the picked entities that have dimensions or outside users. True when it
    handled the Delete (asked, and then ran FreeCAD's Delete on what goes, or nothing)."""
    if not params().GetBool("SketcherAsk", True):
        return False
    picks = []      # (object name, sub name as picked, element)
    for sel in Gui.Selection.getSelectionEx("", 0):
        for sub in sel.SubElementNames:
            picks.append((sel.ObjectName, sub, sub.split(".")[-1]))
    edges = [int(e[4:]) - 1 for _o, _s, e in picks if e.startswith("Edge") and e[4:].isdigit()]
    flagged = [g for g in edges if any(edge_flags(sketch, g))]
    if not flagged:
        return False
    doc = sketch.Document.Name

    def pick_of(geo):
        return [p for p in picks if p[2] == "Edge%d" % (geo + 1)]

    keep = set()
    all_yes = False
    for i, geo in enumerate(flagged):
        if all_yes:
            break
        _reselect(doc, pick_of(geo))
        dialog = SketcherConfirmDelete(len(flagged) - i > 1)
        dialog.exec()
        answer = dialog.answer
        if answer == SketcherConfirmDelete.CANCEL:
            _reselect(doc, picks)
            return True
        if answer == SketcherConfirmDelete.REPLACE:
            _reselect(doc, pick_of(geo))
            QtCore.QTimer.singleShot(0, lambda: Gui.runCommand("SWStyle_ReplaceEntity", 0))
            return True
        if answer == SketcherConfirmDelete.NO:
            keep.add(geo)
        if answer == SketcherConfirmDelete.YES_ALL:
            all_yes = True
    going = [p for p in picks if not (p[2].startswith("Edge") and p[2][4:].isdigit() and int(p[2][4:]) - 1 in keep)]
    _reselect(doc, going)
    if going:
        _freecad_delete()
    return True


def _reselect(doc, picks):
    Gui.Selection.clearSelection()
    for obj, sub, _e in picks:
        try:
            Gui.Selection.addSelection(doc, obj, sub)
        except Exception as _fw_err:
            _fw_log("confirmdelete.py:573", _fw_err)


# ---- taking over FreeCAD's Delete -------------------------------------------------------------

def _feature_picks():
    """The picked part features and sketches (whole objects), or None when FreeCAD's own Delete
    fits better (faces picked, objects outside a body, a body itself...)."""
    out = []
    for sel in Gui.Selection.getSelectionEx("", 0):
        subs = [s for s in sel.SubElementNames if s]
        obj = sel.Object
        for s in subs:
            last = s.split(".")[-1]
            if last:
                return None
            for part in s.split("."):
                found = obj.Document.getObject(part)
                if found is not None:
                    obj = found
        if obj.TypeId == BODY or body_of(obj) is None or _helper(obj):
            return None
        if obj.TypeId in ("App::Origin", "App::Line", "App::Plane", "App::Point"):
            return None
        if obj not in out:
            out.append(obj)
    return out or None


def handle():
    """Our Delete. True when handled (or asked and cancelled)."""
    if Gui.ActiveDocument is None:
        return False
    sketch = _editing_sketch()
    if sketch is not None:
        return delete_in_sketch(sketch)
    if Gui.ActiveDocument.getInEdit() is not None or Gui.Control.activeDialog():
        return False
    picks = _feature_picks()
    if not picks:
        return False
    return delete_features(picks)


def _freecad_delete():
    original = getattr(Gui.runCommand, "swstyle_confirm_original", Gui.runCommand)
    _passing[0] = True
    try:
        original(COMMAND, 0)
    finally:
        _passing[0] = False


def _delete(*args):
    if _passing[0]:
        return
    try:
        if handle():
            return
    except Exception as error:
        App.Console.PrintWarning("FreeCAD Confirm Delete: %s\n" % error)
    _freecad_delete()


_state = {"action": None}


def install():
    """FreeCAD's Delete action and Gui.runCommand('Std_Delete') come here first."""
    if not hasattr(Gui.runCommand, "swstyle_confirm_original"):
        original = Gui.runCommand

        def run_command(name, *args, **kw):
            if name == COMMAND and not _passing[0]:
                _delete()
                return None
            return original(name, *args, **kw)
        run_command.swstyle_confirm_original = original
        Gui.runCommand = run_command
    try:
        actions = Gui.Command.get(COMMAND).getAction()
    except Exception:
        actions = []
    for action in actions:
        if action is None or action.property("swstyle_confirm_delete"):
            continue
        try:
            action.triggered.disconnect()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD Confirm Delete not hooked: %s\n" % error)
            continue
        action.setProperty("swstyle_confirm_delete", True)
        action.triggered.connect(_delete)
        _state["action"] = action
