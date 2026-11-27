# SPDX-License-Identifier: LGPL-2.1-or-later
""




from .. import editobj

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

VIEW = "User parameter:BaseApp/Preferences/View"
KEPT = "FreeWorksSelectionColorOutsideSketch"
DEFAULT = 0x53A9FFFF


def _p():
    return App.ParamGet(VIEW)


def swap_in():
    p = _p()
    want = p.GetUnsigned("SketchSelectionColor", DEFAULT)
    now = p.GetUnsigned("SelectionColor", 0x1CAD1CFF)
    if p.GetBool(KEPT + "Set", False):
        if now != want:          # changed in Options while a sketch was open: that is the new one
            p.SetUnsigned(KEPT, now)
    else:
        p.SetUnsigned(KEPT, now)
        p.SetBool(KEPT + "Set", True)
    if now != want:
        p.SetUnsigned("SelectionColor", want)


def swap_out():
    p = _p()
    if not p.GetBool(KEPT + "Set", False):
        return
    p.SetUnsigned("SelectionColor", p.GetUnsigned(KEPT, 0x0058C0FF))

    p.RemUnsigned(KEPT)
    p.RemBool(KEPT + "Set")


class _Watch:
    def slotInEdit(self, vp):
        try:
            if editobj.derived(vp, "Sketcher::SketchObject"):
                swap_in()
        except Exception as _fw_err:
            _fw_log("fwsketch/selcolour.py:60", _fw_err)

    def slotResetEdit(self, vp):
        try:
            if editobj.derived(vp, "Sketcher::SketchObject"):
                swap_out()
                doc = editobj.of(vp).Document
                from PySide import QtCore as _qc
                _qc.QTimer.singleShot(0, lambda: _prune(doc))
        except Exception as _fw_err:
            _fw_log("fwsketch/selcolour.py:70", _fw_err)


def _prune(doc):
    """Silhouette edges picked in the sketch but never used go (fwsketch/silhouette.py)."""
    from .. import teardown
    if not teardown.doc_alive(doc):
        return
    try:
        from . import silhouette
        silhouette.prune(doc)
    except Exception as _fw_err:
        _fw_log("fwsketch/selcolour.py:79", _fw_err)


_watch = []


def start():
    if _watch:
        return
    try:
        gdoc = Gui.ActiveDocument
        vp = gdoc.getInEdit() if gdoc else None
        sketching = vp is not None and editobj.derived(vp, "Sketcher::SketchObject")
    except Exception:
        sketching = False
    if sketching:
        swap_in()
    else:
        swap_out()          # FreeCAD stopped while a sketch was open: put the colour back
    w = _Watch()
    Gui.addDocumentObserver(w)
    _watch.append(w)
