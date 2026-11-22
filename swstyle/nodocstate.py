# -*- coding: utf-8 -*-
""









import FreeCAD as App
from PySide import QtWidgets

# the quick access buttons that work with nothing open; the rest wait for a document
QAT_LIVE = ("Home", "New", "Open", "Options")
STATUS_HIDE = ("SWUnits", "SWStatusTags", "SWQuickTipsButton")

_state = {"empty": None, "saved": []}


def _alive(w):
    try:
        import shiboken6
        return w is not None and shiboken6.isValid(w)
    except Exception:
        return w is not None


def empty():
    """True while no document is open."""
    try:
        return not App.listDocuments()
    except Exception:
        return False


def _targets(shell):
    out = []
    top = getattr(shell, "topbar", None)
    if top is not None and _alive(top):
        out += [top.tabs, top.stack, top.chevron, top.collapse_button]
    out.append(getattr(shell, "left_dock", None))
    out.append(getattr(shell, "bottom_tb", None))
    bar = shell.window.statusBar() if shell.window is not None else None
    if bar is not None:
        for name in STATUS_HIDE:
            out.append(bar.findChild(QtWidgets.QWidget, name))
    return [w for w in out if w is not None and _alive(w)]


def _qat_flag(shell, on):
    top = getattr(shell, "topbar", None)
    qat = getattr(top, "qat", None) if top is not None else None
    if qat is None or not _alive(qat):
        return
    changed = False
    for b in qat.left:
        hide = on and b.binding.cmd.key not in QAT_LIVE
        if bool(getattr(b, "fw_no_document", False)) != hide:
            b.fw_no_document = hide
            changed = True
    if changed:
        qat.relayout()


def sync(shell):
    now = empty()
    top = getattr(shell, "topbar", None)
    if now and _state["empty"]:
        # still nothing open: keep them hidden if something showed one again (tabstrip, a refresh)
        for w in _targets(shell):
            if not w.isHidden():
                w.hide()
        return
    if now == _state["empty"]:
        return
    _state["empty"] = now
    if now:
        _state["saved"] = [(w, w.isHidden()) for w in _targets(shell)]
        for w, _hidden in _state["saved"]:
            w.hide()
    else:
        for w, hidden in _state["saved"]:
            if _alive(w):
                w.setHidden(hidden)
        _state["saved"] = []
    if top is not None and _alive(top):
        top.setProperty("swNoDocument", now)
        try:
            top._apply_height()
            if not now:
                top._layout_pages()
        except Exception as error:
            App.Console.PrintLog("FreeCAD nodocstate: %s\n" % error)
    _qat_flag(shell, now)
    try:
        from . import tabstrip
        tabstrip.place()
    except Exception as error:
        App.Console.PrintLog("FreeCAD nodocstate: %s\n" % error)
