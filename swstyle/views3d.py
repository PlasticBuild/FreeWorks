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

import json
import os
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .widgets import alive

META = "SW3DViews"
LAST = [None]
_pane = []


def _doc():
    return App.ActiveDocument


def views(doc=None):
    doc = doc or _doc()
    if doc is None:
        return {}
    try:
        return json.loads(doc.Meta.get(META, "") or "{}")
    except Exception:
        return {}


def _store(doc, data):
    meta = doc.Meta
    meta[META] = json.dumps(data)
    doc.Meta = meta


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def _shown(doc):
    return [o.Name for o in doc.Objects if getattr(o, "ViewObject", None) is not None and hasattr(o, "Shape")
            and o.ViewObject.Visibility]


def _picture(doc, name):
    v = _view()
    if v is None:
        return ""
    folder = os.path.join(tempfile.gettempdir(), "FreeWorks3DViews")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s_%s.png" % (doc.Name, "".join(c if c.isalnum() else "_" for c in name)))
    try:
        v.saveImage(path, 160, 120, "Current")
    except Exception as _fw_err:
        _fw_log("views3d.py:81", _fw_err)
        return ""
    return path


def capture(name=None, doc=None):
    ""
    doc = doc or _doc()
    v = _view()
    if doc is None or v is None:
        return None
    data = views(doc)
    if not name:
        n = 1
        while "3D View%d" % n in data:
            n += 1
        name = "3D View%d" % n
    data[name] = {"camera": v.getCamera(), "orientation": list(v.getCameraOrientation().Q), "shown": _shown(doc)}
    _store(doc, data)
    _picture(doc, name)
    refresh()
    return name


def open_view(name, doc=None):
    doc = doc or _doc()
    d = views(doc).get(name)
    v = _view()
    if d is None or v is None:
        return False
    shown = set(d.get("shown", []))
    for o in doc.Objects:
        vo = getattr(o, "ViewObject", None)
        if vo is not None and hasattr(o, "Shape") and (o.Name in shown) != bool(vo.Visibility):
            vo.Visibility = o.Name in shown
    try:
        try:
            v.stopAnimating()       # a view change still turning would take the camera away again
        except Exception as _fw_err:
            _fw_log("views3d.py:118", _fw_err)
        v.setCamera(d["camera"])
        if d.get("orientation"):
            try:
                v.stopAnimating()
            except Exception as _fw_err:
                _fw_log("views3d.py:124", _fw_err)
            try:
                v.getCameraNode().orientation.setValue(*d["orientation"])     # at once, no turning
            except Exception:
                v.setCameraOrientation(tuple(d["orientation"]))
    except Exception:
        return False
    return True


def update_view(name, doc=None):
    doc = doc or _doc()
    data = views(doc)
    if name not in data:
        return False
    return capture(name, doc) == name


def rename(name, new, doc=None):
    doc = doc or _doc()
    data = views(doc)
    new = (new or "").strip()
    if name not in data or not new or new in data:
        return False
    data = {(new if k == name else k): val for k, val in data.items()}
    _store(doc, data)
    refresh()
    return True


def delete(name, doc=None):
    doc = doc or _doc()
    data = views(doc)
    if name not in data:
        return False
    del data[name]
    _store(doc, data)
    refresh()
    return True


# --------------------------------------------------------------------------- the tab
class Pane(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SW3DViewsPane")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        side = QtWidgets.QVBoxLayout()
        self.capture = QtWidgets.QToolButton(self)
        self.capture.setObjectName("SW3DViewsCapture")
        self.capture.setText("Capture 3D View")
        self.capture.setToolTip("Capture 3D View: keeps the current view under a name")
        self.capture.clicked.connect(lambda checked=False: capture())
        side.addWidget(self.capture)
        side.addStretch(1)
        lay.addLayout(side)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SW3DViewsList")
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setIconSize(QtCore.QSize(96, 72))
        self.list.setFlow(QtWidgets.QListView.LeftToRight)
        self.list.setWrapping(False)
        self.list.setMovement(QtWidgets.QListView.Static)
        self.list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda it: open_view(it.text()))
        lay.addWidget(self.list, 1)
        self.refresh()

    def refresh(self):
        doc = _doc()
        self.list.clear()
        if doc is None:
            return
        folder = os.path.join(tempfile.gettempdir(), "FreeWorks3DViews")
        for name in views(doc):
            path = os.path.join(folder, "%s_%s.png" % (doc.Name, "".join(c if c.isalnum() else "_" for c in name)))
            icon = QtGui.QIcon(path) if os.path.exists(path) else QtGui.QIcon()
            self.list.addItem(QtWidgets.QListWidgetItem(icon, name))

    def menu_for(self, pos):
        it = self.list.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWToolMenu_3DViews")

        def add(text, run, on=True):
            a = menu.addAction(text)
            a.setEnabled(bool(on))
            a.triggered.connect(lambda checked=False: QtCore.QTimer.singleShot(0, run))
        if it is None:
            add("Capture 3D View", capture, _view() is not None)
            return menu
        name = it.text()
        add("Open", lambda: open_view(name))
        add("Update View", lambda: update_view(name))
        menu.addSeparator()
        add("Rename", lambda: self._rename(name))
        add("Delete", lambda: delete(name))
        return menu

    def _rename(self, name):
        text, ok = QtWidgets.QInputDialog.getText(self, "Rename", "Name:", text=name)
        if ok:
            rename(name, text)

    def _menu(self, pos):
        m = self.menu_for(pos)
        LAST[0] = m
        m.popup(self.list.viewport().mapToGlobal(pos))


def refresh():
    for p in _pane:
        if alive(p):
            p.widget().refresh()


def dock():
    mw = Gui.getMainWindow()
    if _pane and alive(_pane[0]):
        return _pane[0]
    d = QtWidgets.QDockWidget("3D Views", mw)
    d.setObjectName("SW3DViewsDock")
    d.setWidget(Pane(d))
    d.setFeatures(QtWidgets.QDockWidget.DockWidgetClosable)
    mw.addDockWidget(QtCore.Qt.BottomDockWidgetArea, d)
    d.hide()
    _pane[:] = [d]
    return d


def show_pane(on=None):
    d = dock()
    on = not d.isVisible() if on is None else on
    d.setVisible(on)
    if on:
        d.widget().refresh()
        d.raise_()
    return d


class PaneCommand:
    def GetResources(self):
        return {"MenuText": "3D Views", "ToolTip": "Shows the 3D Views tab: the views captured under a name"}

    def IsActive(self):
        return True

    def Activated(self):
        show_pane()


class CaptureCommand:
    def GetResources(self):
        return {"MenuText": "Capture 3D View", "ToolTip": "Keeps the current view under a name in the 3D Views tab"}

    def IsActive(self):
        return _view() is not None

    def Activated(self):
        show_pane(True)
        capture()


def register():
    names = Gui.listCommands()
    if "SWStyle_3DViews" not in names:
        Gui.addCommand("SWStyle_3DViews", PaneCommand())
    if "SWStyle_Capture3DView" not in names:
        Gui.addCommand("SWStyle_Capture3DView", CaptureCommand())
