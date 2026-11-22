# SPDX-License-Identifier: LGPL-2.1-or-later
""


import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

_state = {"timer": None}


def _tree():
    try:
        from . import rcmenus
        sh = rcmenus.shell()
        pane = getattr(sh, "left_pane", None) if sh is not None and getattr(sh, "enabled", False) else None
        return pane.tree_widget() if pane is not None else None
    except Exception:
        return None


def plain_roots(tree=None):
    """Takes the bold off the document rows. The number of rows changed."""
    tree = tree or _tree()
    if tree is None:
        return 0
    n = 0
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if not isinstance(top, QtWidgets.QTreeWidgetItem):
            continue        # sweep-1121: a stale wrapper while the tree is rebuilt (was a traceback every 0.4 s)
        docs = [top] if top.childCount() == 0 or top.text(0) != "Application" else [top.child(j) for j in range(top.childCount())]
        for item in docs:
            if not isinstance(item, QtWidgets.QTreeWidgetItem):
                continue
            f = item.font(0)
            if f.bold():
                f.setBold(False)
                item.setFont(0, f)
                n += 1
    return n


def install():
    if _state["timer"] is not None:
        return
    t = QtCore.QTimer(QtWidgets.QApplication.instance())
    t.setObjectName("FW_TreeLook")
    t.timeout.connect(plain_roots)          # FreeCAD sets the bold again when a document becomes active
    t.start(400)
    _state["timer"] = t
    plain_roots()
