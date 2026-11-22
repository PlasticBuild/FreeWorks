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


from PySide import QtCore, QtWidgets

KEEP = "fw_keep_grey"
INTERVAL = 250
CLASSES = ("SettingsDialog", "AddInsDialog", "TaskSchedulerWindow", "ToolboxSettings", "PackAndGoDialog", "PrintDialog",
           "PageSetupDialog", "PrintPreviewDialog", "FindReferencesDialog", "ReloadDialog", "FilePropertiesDialog",
           "NewDocumentDialog", "AdvancedSaveDialog", "ReferencesDialog", "PreviousVersionsDialog", "MarginsDialog",
           "HeaderFooterDialog", "SimplifyDialog", "FindReplaceDialog", "MacroButtonDialog", "QFileDialog")
STOCK_CHILDREN = ("executeButton", "buttonStart")       # FreeCAD's macro list and Record box
CONTROLS = (QtWidgets.QAbstractButton, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox, QtWidgets.QLineEdit)
_state = {"filter": None}


def _ours(dlg):
    if type(dlg).__name__ in CLASSES or any(c.__name__ in CLASSES for c in type(dlg).__mro__):
        return True
    return any(dlg.findChild(QtWidgets.QWidget, n) is not None for n in STOCK_CHILDREN)


def _skipped(w):
    p = w.parent()
    while p is not None:
        if isinstance(p, (QtWidgets.QDialogButtonBox, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
            return True
        if isinstance(p, QtWidgets.QWidget) and p.property(KEEP):
            return True
        p = p.parent()
    return bool(w.property(KEEP)) or isinstance(w, QtWidgets.QLineEdit) and isinstance(w.parent(), (
        QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox))


def sweep(dlg):
    hidden = dlg.property("fw_dg_hidden") or []
    for w in dlg.findChildren(QtWidgets.QWidget):
        if not isinstance(w, CONTROLS) or _skipped(w):
            continue
        key = id(w)
        if not w.isEnabled() and w.isVisibleTo(dlg):
            w.setVisible(False)
            hidden.append(key)
            _held.setdefault(id(dlg), {})[key] = w
        elif w.isEnabled() and key in _held.get(id(dlg), {}):
            _held[id(dlg)].pop(key, None)
            w.setVisible(True)


_held = {}


class _Watch(QtCore.QObject):
    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QDialog) and obj.isWindow() \
                    and not obj.property("fw_dg") and _ours(obj):
                obj.setProperty("fw_dg", True)
                timer = QtCore.QTimer(obj)
                timer.setInterval(INTERVAL)
                timer.timeout.connect(lambda d=obj: sweep(d))
                timer.start()
                QtCore.QTimer.singleShot(0, lambda d=obj: sweep(d))
                obj.destroyed.connect(lambda *_, k=id(obj): _held.pop(k, None))
        except Exception as error:
            _fw_log("dialogsgrey.py:watch", error)
        return False


def install():
    if _state["filter"] is not None:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    _state["filter"] = _Watch(app)
    app.installEventFilter(_state["filter"])
