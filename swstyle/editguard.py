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
from PySide import QtCore

FROZEN = "%s is frozen. Move the Freeze bar above it to edit it."
ROLLED = "%s is rolled back. Roll forward past it to edit it."
refused = []        # (label, message) for the checks


def _body(obj):
    try:
        from . import rollbackbar
        return rollbackbar.body_of(obj)
    except Exception:
        return None


def rolled_back(obj):
    body = _body(obj)
    if body is None or obj is body:
        return False
    try:
        from . import rollbackbar
        solids = rollbackbar.solid_features(body)
    except Exception:
        return False
    group = list(body.Group)
    tip = body.Tip
    if tip is None:
        cut = 0
    elif tip in solids:
        cut = solids.index(tip) + 1
    else:
        cut = 0
        try:
            at = group.index(tip)
            cut = len([o for o in solids if group.index(o) <= at])
        except ValueError as _fw_err:
            _fw_log("editguard.py:64", _fw_err)
    return obj in solids[cut:]


def why_not(obj):
    """The message when obj cannot be edited now, else ''."""
    try:
        from . import freezebar
        if freezebar.frozen(obj):
            return FROZEN % obj.Label
    except Exception as _fw_err:
        _fw_log("editguard.py:75", _fw_err)
    try:
        if rolled_back(obj):
            return ROLLED % obj.Label
    except Exception as _fw_err:
        _fw_log("editguard.py:80", _fw_err)
    return ""


class _Watch:
    def slotInEdit(self, vp):
        try:
            obj = vp.Object
        except Exception:
            return
        text = why_not(obj)
        if text:
            refused.append((obj.Label, text))
            QtCore.QTimer.singleShot(0, lambda d=obj.Document.Name, t=text: _close(d, t))


def _close(doc_name, text):
    try:
        Gui.Control.closeDialog()
    except Exception as _fw_err:
        _fw_log("editguard.py:100", _fw_err)
    try:
        gdoc = Gui.getDocument(doc_name)
        if gdoc.getInEdit() is not None:
            gdoc.resetEdit()
    except Exception as _fw_err:
        _fw_log("editguard.py:106", _fw_err)
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 6000)
    except Exception as _fw_err:
        _fw_log("editguard.py:110", _fw_err)
    App.Console.PrintMessage("FreeCAD: %s\n" % text)


_watch = []


def install():
    if Gui is None or _watch:
        return
    _watch.append(_Watch())
    Gui.addDocumentObserver(_watch[0])
