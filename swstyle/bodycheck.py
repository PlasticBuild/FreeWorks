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

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

from . import paths

PARAMS = paths.PARAM_PATH + "/BodiesToKeep"
CUT_TYPES = ("PartDesign::Pocket", "PartDesign::Groove", "PartDesign::Hole", "PartDesign::SubtractiveLoft",
             "PartDesign::SubtractivePipe", "PartDesign::SubtractiveHelix", "PartDesign::FeatureSubtractivePython",
             "PartDesign::Boolean")
_asked = set()          # (doc, feature name) already asked or seen split at creation
_known = {}             # doc name -> feature names seen, so only new cuts ask


def enabled():
    return App.ParamGet(PARAMS).GetBool("Ask", True)


def _body_of(obj):
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def pieces_after(feature):
    """(solids before, solids after) the feature."""
    base = getattr(feature, "BaseFeature", None)
    before = len(base.Shape.Solids) if base is not None and not base.Shape.isNull() else 0
    return before, len(feature.Shape.Solids) if not feature.Shape.isNull() else 0


def needs_asking(feature):
    if feature.TypeId not in CUT_TYPES or not feature.isValid():
        return False
    key = (feature.Document.Name, feature.Name)
    if key in _asked:
        return False
    body = _body_of(feature)
    if body is None or body.Tip is not feature:
        return False
    before, after = pieces_after(feature)
    return before >= 1 and after > before


def keep(feature, indexes):
    """A Body-Delete/Keep after feature that keeps the solids at these indexes."""
    from . import multibody
    doc = feature.Document
    body = _body_of(feature)
    solids = feature.Shape.Solids
    refs = [multibody.ref_text(i, solids[i]) for i in indexes if 0 <= i < len(solids)]
    obj = doc.addObject("PartDesign::FeaturePython", "DeleteKeep")
    multibody.OPS["DeleteKeep"](obj)
    if App.GuiUp and obj.ViewObject is not None:
        multibody.BodyOpView(obj.ViewObject)
    try:
        from . import naming
        obj.Label = naming.next_label(doc, multibody.OPS["DeleteKeep"].TITLE)
    except Exception as _fw_err:
        _fw_log("bodycheck.py:87", _fw_err)
    body.addObject(obj)
    obj.Keep = True
    obj.Bodies = refs
    doc.recompute()
    if App.GuiUp:
        try:
            feature.ViewObject.Visibility = False
            obj.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("bodycheck.py:97", _fw_err)
    return obj


if Gui is not None:
    class BodiesToKeep(QtWidgets.QDialog):
        def __init__(self, feature):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWBodiesToKeep")
            self.setWindowTitle("Bodies to Keep")
            self.feature = feature
            lay = QtWidgets.QVBoxLayout(self)
            lay.addWidget(QtWidgets.QLabel("%s made %d bodies. Which should stay?" %
                                           (feature.Label, len(feature.Shape.Solids))))
            self.all = QtWidgets.QRadioButton("All bodies")
            self.all.setObjectName("SWBodiesToKeepAll")
            self.some = QtWidgets.QRadioButton("Selected bodies")
            self.some.setObjectName("SWBodiesToKeepSelected")
            self.all.setChecked(True)
            lay.addWidget(self.all)
            lay.addWidget(self.some)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("SWBodiesToKeepList")
            for i, s in enumerate(feature.Shape.Solids):
                item = QtWidgets.QListWidgetItem("Body %d   (volume %.2f)" % (i + 1, s.Volume))
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked)
                self.list.addItem(item)
            self.list.setEnabled(False)
            self.list.currentRowChanged.connect(self._show)
            self.some.toggled.connect(self.list.setEnabled)
            lay.addWidget(self.list)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            lay.addWidget(buttons)

        def chosen(self):
            if self.all.isChecked():
                return None
            return [i for i in range(self.list.count())
                    if self.list.item(i).checkState() == QtCore.Qt.Checked]

        def _show(self, row):
            try:
                from . import multibody
                body = _body_of(self.feature)
                Gui.Selection.clearSelection()
                solid = self.feature.Shape.Solids[row]
                names = []
                for k, f in enumerate(self.feature.Shape.Faces, 1):
                    if any(f.isSame(g) for g in solid.Faces):
                        names.append("Face%d" % k)
                for n in names:
                    Gui.Selection.addSelection(self.feature.Document.Name, body.Name, "%s.%s" % (self.feature.Name, n))
            except Exception as _fw_err:
                _fw_log("bodycheck.py:153", _fw_err)

        def done_choice(self):
            picked = self.chosen()
            if picked is None or len(picked) == self.list.count():
                return None
            if not picked:
                QtWidgets.QMessageBox.information(self, "Bodies to Keep", "Keep at least one body.")
                return False
            doc = self.feature.Document
            doc.openTransaction("Bodies to Keep")
            try:
                obj = keep(self.feature, picked)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            return obj

        def accept(self):
            if self.done_choice() is False:
                return
            super().accept()

    LAST = [None]

    def ask(feature):
        _asked.add((feature.Document.Name, feature.Name))
        box = BodiesToKeep(feature)
        LAST[0] = box
        box.setModal(True)
        box.show()
        return box

    class _Watch:
        """Looks at the bodies' tips after each rebuild (an App observer, no Gui slots)."""

        def slotRecomputedDocument(self, doc):
            if not enabled():
                return
            QtCore.QTimer.singleShot(300, lambda name=doc.Name: _look(name))

        def slotCreatedObject(self, obj):
            try:
                if obj.TypeId in CUT_TYPES:
                    _known.setdefault(obj.Document.Name, set()).add(obj.Name)
            except Exception as _fw_err:
                _fw_log("bodycheck.py:196", _fw_err)

    def _look(doc_name, tries=40):
        try:
            doc = App.getDocument(doc_name)
        except Exception:
            return
        new = _known.get(doc_name, set())
        if not new:
            return
        if Gui.Control.activeDialog():
            if tries > 0:          # after the cut's PropertyManager is closed with OK
                QtCore.QTimer.singleShot(500, lambda: _look(doc_name, tries - 1))
            return
        for name in list(new):
            feature = doc.getObject(name)
            if feature is None:
                new.discard(name)
                continue
            if needs_asking(feature):
                new.discard(name)
                ask(feature)
                return
            if feature.isValid() and not feature.Shape.isNull():
                new.discard(name)       # made without a split: it does not ask later

    WATCH = [None]

    def install():
        if WATCH[0] is None:
            WATCH[0] = _Watch()
            App.addDocumentObserver(WATCH[0])
else:
    def install():
        pass
