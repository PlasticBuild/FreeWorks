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

TITLE = "Feature Paint"
COPIED = ("App::PropertyLength", "App::PropertyDistance", "App::PropertyAngle", "App::PropertyFloat",
          "App::PropertyFloatConstraint", "App::PropertyInteger", "App::PropertyIntegerConstraint",
          "App::PropertyBool", "App::PropertyEnumeration", "App::PropertyQuantity",
          "App::PropertyQuantityConstraint", "App::PropertyPercent")
SKIPPED = {"Visibility", "Label", "Label2", "Placement", "_GroupTouched", "Refine", "SuppressedShape",
           "MapReversed", "MapMode", "MapPathParameter", "AttachmentOffset", "SWStyleKind"}
SKIPPED_GROUPS = {"Base", "Attachment"}


def parameters(obj):
    """The settings of obj Feature Paint can copy: [property name]."""
    out = []
    for name in obj.PropertiesList:
        if name in SKIPPED or obj.getGroupOfProperty(name) in SKIPPED_GROUPS:
            continue
        if obj.getTypeIdOfProperty(name) not in COPIED:
            continue
        mode = obj.getEditorMode(name)
        if "Hidden" in mode or "ReadOnly" in mode:
            continue
        out.append(name)
    return out


def words(name):
    """TaperAngle -> Taper Angle, as the Property View shows it."""
    import re
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)


def same_kind(a, b):
    return a.TypeId == b.TypeId and getattr(a, "SWStyleKind", None) == getattr(b, "SWStyleKind", None)


def paint(source, targets, names):
    """Copies names from source onto each target of its kind; the targets changed."""
    done = []
    for t in targets:
        if t is source or not same_kind(source, t):
            continue
        for name in names:
            if name not in t.PropertiesList:
                continue
            try:
                setattr(t, name, getattr(source, name))
            except Exception as _fw_err:
                _fw_log("featurepaint.py:74", _fw_err)
        done.append(t)
    return done


class _Focus(QtCore.QObject):
    """Tells the panel which box the user clicked into."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() == QtCore.QEvent.FocusIn and self.panel is not None:
            self.panel.focused(obj)
        return False


class _Box(QtWidgets.QWidget):
    def __init__(self, focus, key, title, name, height):
        super().__init__()
        self.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName(name)
        self.list.setFixedHeight(height)
        self.list.installEventFilter(focus)
        lay.addWidget(self.list)
        self.key = key


class FeaturePaintPanel:
    def __init__(self, doc, picks=()):
        self.doc = doc
        self.source = None
        self.targets = []
        self.active = "source"
        self.focus = _Focus(self)
        self.copy = _Box(self.focus, "source", "Copy Settings", "SWPaintSource", 26)
        self.paste = _Box(self.focus, "targets", "Paste Settings", "SWPaintTargets", 80)
        self.copy.setProperty("swstyle_pm_title", TITLE)
        self.note = QtWidgets.QLabel("Pick the feature to copy from in the FeatureManager tree.", self.copy)
        self.note.setObjectName("SWPaintNote")
        self.note.setWordWrap(True)
        self.copy.layout().insertWidget(0, self.note)
        self.params = QtWidgets.QWidget()
        self.params.setWindowTitle("Parameters")
        lay = QtWidgets.QVBoxLayout(self.params)
        self.list = QtWidgets.QListWidget(self.params)
        self.list.setObjectName("SWPaintParameters")
        self.list.setFixedHeight(120)
        lay.addWidget(self.list)
        self.form = [self.copy, self.paste, self.params]
        for obj in picks:
            self._picked(obj)
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    def focused(self, box):
        self.active = "source" if box is self.copy.list else "targets"
        self._show()

    def _gone(self):
        """True when the PM went without OK or Cancel (another dialog took the task panel, or its
        document closed): stop listening."""
        try:
            import shiboken6 as shiboken
        except ImportError:
            import shiboken2 as shiboken
        try:
            alive = shiboken.isValid(self.list) and self.doc.Name is not None
        except ReferenceError:
            alive = False
        if not alive:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("featurepaint.py:153", _fw_err)
        return not alive

    def addSelection(self, doc, name, sub, pnt):
        if self._gone() or doc != self.doc.Name or sub:
            return          # features come from the tree
        obj = self.doc.getObject(name)
        if obj is not None:
            QtCore.QTimer.singleShot(0, lambda: self._picked(obj))

    def _picked(self, obj):
        if obj.isDerivedFrom("PartDesign::Body") or obj.isDerivedFrom("App::Origin") or \
                obj.TypeId in ("App::Line", "App::Plane", "App::Point"):
            return
        if self.active == "source" or self.source is None:
            self.source = obj
            self.active = "targets"
            self._fill_parameters()
        elif obj is not self.source and obj not in self.targets:
            self.targets.append(obj)
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("featurepaint.py:176", _fw_err)
        self._show()

    def _fill_parameters(self):
        self.list.clear()
        for name in parameters(self.source):
            item = QtWidgets.QListWidgetItem(words(name))
            item.setData(QtCore.Qt.UserRole, name)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self.list.addItem(item)

    def _show(self):
        self.copy.list.clear()
        if self.source is not None:
            self.copy.list.addItem(self.source.Label)
        self.paste.list.clear()
        for t in self.targets:
            ok = self.source is not None and same_kind(self.source, t)
            self.paste.list.addItem(t.Label + ("" if ok else "  (another kind: left alone)"))
        for box in (self.copy, self.paste):
            box.list.setStyleSheet("QListWidget { background: #dcecff; }" if box.key == self.active else "")
        if self.source is None:
            self.note.setText("Pick the feature to copy from in the FeatureManager tree.")
        elif not self.targets:
            self.note.setText("Pick the features to copy onto.")
        else:
            self.note.setText("")
        self.note.setVisible(bool(self.note.text()))

    def chosen(self):
        return [self.list.item(i).data(QtCore.Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == QtCore.Qt.Checked]

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        self.focus.panel = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("featurepaint.py:218", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if self.source is None or not self.targets:
            self._show()
            return False
        names = self.chosen()
        self.doc.openTransaction(TITLE)
        done = paint(self.source, self.targets, names)
        if done:
            self.doc.recompute()
            self.doc.commitTransaction()
        else:
            self.doc.abortTransaction()
        self._close()
        return True

    def reject(self):
        self._close()
        return True


class _Command:
    def GetResources(self):
        return {"Pixmap": "Std_DlgParameter", "MenuText": TITLE,
                "ToolTip": "Copies one feature's settings onto other features of the same kind"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        picks = [s.Object for s in Gui.Selection.getSelectionEx() if not s.SubElementNames]
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(FeaturePaintPanel(doc, picks)))


def register():
    if "SWStyle_FeaturePaint" not in Gui.listCommands():
        Gui.addCommand("SWStyle_FeaturePaint", _Command())
