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

from . import asmcore as ac

TAGS = {}           # id(panel) -> Tags


def _centre(refs):
    pts = []
    for ref in refs[:2]:
        try:
            s = ac.element(*ref)
            pts.append(s.CenterOfMass)
        except Exception as _fw_err:
            _fw_log("asmwidthtags.py:33", _fw_err)
    if not pts:
        return None
    c = App.Vector()
    for p in pts:
        c += p
    return c * (1.0 / len(pts))


class Tags(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.labels = {}
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def _view(self):
        try:
            v = Gui.ActiveDocument.ActiveView
            return v, v.graphicsView().viewport()
        except Exception:
            return None, None

    def _label(self, name, parent):
        lab = self.labels.get(name)
        if lab is not None:
            try:
                lab.parent()
                return lab
            except RuntimeError as _fw_err:
                _fw_log("asmwidthtags.py:66", _fw_err)
        lab = QtWidgets.QLabel(name, parent)
        lab.setObjectName("FW_WidthTag_" + name.split()[0])
        lab.setStyleSheet("QLabel { background: #ffffe1; color: #000; border: 1px solid #808080;"
                          " padding: 1px 4px; font-size: 8pt; }")
        lab.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.labels[name] = lab
        return lab

    def update(self):
        view, vp = self._view()
        if view is None:
            return
        for name, refs in (("Width Reference", getattr(self.panel, "width_sel", [])),
                           ("Tab Reference", getattr(self.panel, "tab_sel", []))):
            at = _centre(refs) if getattr(self.panel, "kind", None) == "Width" else None
            if at is None:
                lab = self.labels.get(name)
                if lab is not None:
                    try:
                        lab.hide()
                    except RuntimeError as _fw_err:
                        _fw_log("asmwidthtags.py:88", _fw_err)
                continue
            lab = self._label(name, vp)
            try:
                x, y = view.getPointOnViewport(at)
                dpr = vp.devicePixelRatioF()
                lab.adjustSize()
                lab.move(int(x / dpr) + 12, int(vp.height() - y / dpr) - lab.height() - 12)
                lab.show()
                lab.raise_()
            except Exception:
                lab.hide()

    def close(self):
        self.timer.stop()
        for lab in self.labels.values():
            try:
                lab.hide()
                lab.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("asmwidthtags.py:108", _fw_err)
        self.labels = {}


def show(panel):
    t = TAGS.get(id(panel))
    if t is None:
        t = TAGS[id(panel)] = Tags(panel)
    t.update()


def close(panel):
    t = TAGS.pop(id(panel), None)
    if t is not None:
        t.close()


def labels(panel):
    t = TAGS.get(id(panel))
    return {} if t is None else {k: v for k, v in t.labels.items() if _alive(v) and v.isVisible()}


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False
