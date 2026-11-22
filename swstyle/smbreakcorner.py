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

from . import naming, paths
from . import pmboxes
from .smbaseflange import _active_body, _box, _spin
from .smedgeflange import _DeleteKey, _root, error_label

COMMAND = "SWStyle_SMBreakCorner"
TITLE = "Break Corner"
LABEL = "Break-Corner"
PARAMS = paths.PARAM_PATH + "/SheetMetal"
TYPES = (("Chamfer", "PartDesign::Chamfer"), ("Fillet", "PartDesign::Fillet"))
HINT = "Please select corner edge(s) or flange face(s)."


def _thickness(obj):
    root = _root(obj)
    if root is not None and hasattr(root, "Thickness"):
        return root.Thickness.Value
    return None


def corner_edges(obj, face_name):
    """The corner edges at a flange face's corners: straight edges through the sheet's thickness
    that meet the face at one of its vertexes."""
    shape = obj.Shape
    face = shape.getElement(face_name)
    thk = _thickness(obj)
    own = [e.hashCode() for e in face.Edges]
    out = []
    for v in face.Vertexes:
        for i, e in enumerate(shape.Edges, 1):
            if e.hashCode() in own or e.Curve.TypeId != "Part::GeomLine":
                continue
            if thk is not None and abs(e.Length - thk) > 1e-6:
                continue
            if any(x.Point.distanceToPoint(v.Point) < 1e-7 for x in e.Vertexes):
                name = "Edge%d" % i
                if name not in out:
                    out.append(name)
    return out


class Panel:
    """The Break Corner PropertyManager on a new or edited Chamfer/Fillet feature."""

    def __init__(self, obj, new, base=None):
        self.obj = obj
        self.new = new
        self.base = obj.Base[0] if obj is not None else base
        self.busy = True
        p = App.ParamGet(PARAMS)
        options = _box("Break Corner Options")
        f = options.layout()
        self.picks = QtWidgets.QListWidget()
        self.picks.setObjectName("SWSMCornerPicks")
        self.picks.setMaximumHeight(64)
        self.picks.setToolTip("Corner edges or flange faces. Delete removes one.")
        pmboxes.mark(self.picks, True)
        self._keys = _DeleteKey(self)       # kept: an unreferenced filter is collected and Delete went dead
        self.picks.installEventFilter(self._keys)
        f.addRow(self.picks)
        f.addRow(QtWidgets.QLabel("Break type:"))
        row = QtWidgets.QHBoxLayout()
        self.types = QtWidgets.QButtonGroup(options)
        kind = obj.TypeId if obj is not None else ("PartDesign::Fillet" if p.GetString("BreakType", "Chamfer") == "Fillet"
                                                    else "PartDesign::Chamfer")
        for i, (text, type_id) in enumerate(TYPES):
            b = QtWidgets.QToolButton()
            b.setObjectName("SWSMCorner" + text)
            b.setText(text)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(type_id == kind)
            self.types.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        f.addRow(row)
        size = (obj.Size.Value if obj.TypeId == "PartDesign::Chamfer" else obj.Radius.Value) if obj is not None \
            else p.GetFloat("BreakSize", 2.0)
        self.size = _spin("SWSMCornerSize", size, 0.01, 10000.0)
        self.size.setToolTip("Distance")
        f.addRow(self.size)
        self.error = error_label()
        f.addRow(self.error)
        options.setProperty("swstyle_pm_title", TITLE)
        options.setProperty("swstyle_pm_icon", "SheetMetal_AddCornerRelief")
        options.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        self.form = [options]
        self.subs = []          # what was picked: edges and faces
        if obj is not None:
            self.subs = list(getattr(obj, "SWBreakPicks", []) or obj.Base[1])
            for sub in self.subs:
                self.picks.addItem(sub)
        self.types.buttonClicked.connect(self._type_changed)
        self.size.valueChanged.connect(self._changed)
        self.busy = False
        if obj is None:
            self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- feature
    def _kind(self):
        return TYPES[max(0, self.types.checkedId())]

    def _edges(self):
        out = []
        for sub in self.subs:
            names = corner_edges(self.base, sub) if sub.startswith("Face") else [sub]
            for n in names:
                if n not in out:
                    out.append(n)
        return out

    def _make(self):
        doc = self.base.Document
        body = next((p for p in self.base.InList if p.TypeId == "PartDesign::Body"), None) or _active_body(doc)
        text, type_id = self._kind()
        if not doc.HasPendingTransaction:
            doc.openTransaction(TITLE)
        obj = body.newObject(type_id, "BreakCorner")
        obj.Base = (self.base, self._edges())
        obj.addProperty("App::PropertyStringList", "SWBreakPicks", "Sheet Metal", "Corner edges and flange faces picked")
        obj.SWBreakPicks = self.subs
        obj.Label = naming.next_label(doc, LABEL)
        return obj

    def _type_changed(self, *args):
        if self.obj is None or self.obj.TypeId == self._kind()[1]:
            self._changed()
            return
        old, doc = self.obj, self.obj.Document
        label = old.Label
        body = next((p for p in old.InList if p.TypeId == "PartDesign::Body"), None)
        if body is not None:
            body.removeObject(old)
        doc.removeObject(old.Name)
        self.obj = None
        self.obj = self._make()
        self.obj.Label = label
        self._changed()

    def _changed(self, *args):
        if self.busy or self.obj is None:
            return
        obj = self.obj
        if obj.TypeId == "PartDesign::Chamfer":
            obj.Size = self.size.value()
        else:
            obj.Radius = self.size.value()
        obj.Base = (self.base, self._edges())
        obj.SWBreakPicks = self.subs
        obj.Document.recompute()
        self._report()

    def _report(self):
        if self.obj is None:
            self.error.setText(HINT)
            self.error.setVisible(True)
            return False
        invalid = "Invalid" in self.obj.State
        self.error.setText(self.obj.getStatusString() if invalid else "")
        self.error.setVisible(invalid)
        return not invalid

    # ---------------------------------------------------------------- selection
    def addSelection(self, doc, name, sub, point):
        if sub.startswith(("Edge", "Face")):
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub))

    def _picked(self, doc_name, name, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smbreakcorner.py:196", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None:
            return
        if self.base is None:
            self.base = picked
        if picked is not self.base:
            element = picked.Shape.getElement(sub)
            elements = self.base.Shape.Edges if sub.startswith("Edge") else self.base.Shape.Faces
            kind = "Edge" if sub.startswith("Edge") else "Face"
            match = [i for i, e in enumerate(elements, 1)
                     if e.CenterOfMass.distanceToPoint(element.CenterOfMass) < 1e-6
                     and abs((e.Length if kind == "Edge" else e.Area) - (element.Length if kind == "Edge" else element.Area)) < 1e-6]
            if not match:
                return
            sub = "%s%d" % (kind, match[0])
        if sub in self.subs:
            return
        self.subs.append(sub)
        self.picks.addItem(sub)
        self._apply()

    def remove_current(self):
        row = self.picks.currentRow()
        if row >= 0:
            self.picks.takeItem(row)
            del self.subs[row]
            self._apply()

    def _apply(self):
        if not self._edges():
            self._report()
            return
        if self.obj is None:
            self.obj = self._make()
            try:
                self.base.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("smbreakcorner.py:234", _fw_err)
        self._changed()

    # ---------------------------------------------------------------- closing
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smbreakcorner.py:245", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smbreakcorner.py:251", _fw_err)

    def accept(self):
        self._changed()
        if not self._report():
            return False
        p = App.ParamGet(PARAMS)
        p.SetString("BreakType", self._kind()[0])
        p.SetFloat("BreakSize", self.size.value())
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.obj is not None:
            doc = self.obj.Document
            base = self.base if self.new else None
            doc.abortTransaction()
            doc.recompute()
            if base is not None:
                try:
                    base.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("smbreakcorner.py:274", _fw_err)
        self._close()
        return True


def start():
    doc = App.ActiveDocument
    if doc is None:
        return
    base, subs = None, []
    for s in Gui.Selection.getSelectionEx():
        names = [n for n in s.SubElementNames if n.startswith(("Edge", "Face"))]
        if names and base is None:
            base, subs = s.Object, names
    if base is None:
        body = _active_body(doc)
        base = body.Tip if body is not None else None
    panel = Panel(None, True, base=base)
    Gui.Control.showDialog(panel)
    if subs:
        panel.subs = list(subs)
        for sub in subs:
            panel.picks.addItem(sub)
        panel._apply()


def is_break_corner(obj):
    return obj.TypeId in ("PartDesign::Chamfer", "PartDesign::Fillet") and "SWBreakPicks" in obj.PropertiesList


class Command:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Chamfer", "MenuText": "Break-Corner/Corner-Trim",
                "ToolTip": "Chamfers or rounds the corners of the sheet."}

    def IsActive(self):
        if App.ActiveDocument is None:
            return False
        try:
            return not Gui.Control.activeDialog()
        except Exception:
            return True

    def Activated(self):
        from . import smflatten
        if smflatten.is_flat():
            Gui.runCommand("SWStyle_SMCornerTrim", 0)
            return
        start()


class _EditWatch:
    """Editing a Break-Corner (double-click, Edit Feature) swaps FreeCAD's Chamfer/Fillet panel for
    the Break Corner PropertyManager."""

    def slotInEdit(self, view_provider):
        try:
            obj = view_provider.Object
        except Exception:
            return
        if is_break_corner(obj) and paths.params().GetBool("Enabled", True):
            QtCore.QTimer.singleShot(0, lambda: self._swap(obj))

    def _swap(self, obj):
        try:
            dialog = Gui.Control.activeDialog()
        except Exception:
            dialog = False
        if dialog:
            Gui.Control.closeDialog()
        try:
            Gui.getDocument(obj.Document.Name).resetEdit()      # so a type change can replace it
        except Exception as _fw_err:
            _fw_log("smbreakcorner.py:347", _fw_err)
        if not obj.Document.HasPendingTransaction:
            obj.Document.openTransaction("Edit " + TITLE)
        Gui.Control.showDialog(Panel(obj, False))


_watch = []


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
    if not _watch:
        _watch.append(_EditWatch())
        Gui.addDocumentObserver(_watch[0])
