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

CLEAR = "swstyle_clear_selections"
_ORIGINAL = "swstyle_menu_original"
_REMOVE_TEXTS = ("Remove", "Delete")


def install(view):
    """Add Clear Selections to every selection box in view. Safe to repeat."""
    for box in view.findChildren(QtWidgets.QListWidget):
        if box.contextMenuPolicy() != QtCore.Qt.ActionsContextMenu:
            continue
        if any(a.objectName() == CLEAR for a in box.actions()):
            continue
        remove = _remove_action(box)
        if remove is None:
            continue
        remove.setProperty(_ORIGINAL, remove.text())
        remove.setText("Delete")
        clear = QtGui.QAction("Clear Selections", box)
        clear.setObjectName(CLEAR)
        clear.triggered.connect(lambda checked=False, b=box, r=remove: clear_all(b, r))
        actions = box.actions()
        after = actions.index(remove) + 1
        if after < len(actions):
            box.insertAction(actions[after], clear)
        else:
            box.addAction(clear)


def uninstall(view):
    for box in view.findChildren(QtWidgets.QListWidget):
        try:
            for action in box.actions():
                if action.objectName() == CLEAR:
                    box.removeAction(action)
                    action.deleteLater()
                elif action.property(_ORIGINAL) is not None:
                    action.setText(action.property(_ORIGINAL))
                    action.setProperty(_ORIGINAL, None)
        except RuntimeError as _fw_err:
            _fw_log("selectionbox.py:64", _fw_err)


def _remove_action(box):
    for action in box.actions():
        if action.text().replace("&", "") in _REMOVE_TEXTS:
            return action
    return None


def clear_all(box, remove):
    """Remove every item, using FreeCAD's Remove so the feature follows."""
    single = box.selectionMode() in (QtWidgets.QAbstractItemView.SingleSelection,
                                     QtWidgets.QAbstractItemView.NoSelection)
    for _ in range(box.count() + 1):
        before = box.count()
        if before == 0:
            break
        if single:
            box.setCurrentRow(0)
            box.item(0).setSelected(True)
        else:
            box.selectAll()
        remove.trigger()
        if box.count() >= before:
            break  # FreeCAD kept the rest (a feature that needs one): stop.
