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

_DONE = []


def _sheet_views(widget):
    out = []
    try:
        for w in widget.findChildren(QtWidgets.QGraphicsView):
            if "QGVPage" in w.metaObject().className():
                out.append(w)
        if isinstance(widget, QtWidgets.QGraphicsView) and "QGVPage" in widget.metaObject().className():
            out.append(widget)
    except Exception as _fw_err:
        _fw_log("drawclose.py:39", _fw_err)
    return out


def calm_view(vw):
    """The scene's hover ends now, and no more mouse input reaches it; it comes back by itself if the window is
    still there afterwards (a close that was cancelled, another document's sheet of the same name)."""
    try:
        QtWidgets.QApplication.sendEvent(vw.viewport(), QtCore.QEvent(QtCore.QEvent.Leave))
        vw.setInteractive(False)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sheet close: %s\n" % error)
        return
    QtCore.QTimer.singleShot(300, lambda w=vw: _wake(w))


def _wake(vw):
    try:
        import shiboken6 as shiboken
    except Exception:
        try:
            import shiboken2 as shiboken
        except Exception:
            return
    try:
        if shiboken.isValid(vw):
            vw.setInteractive(True)
    except Exception as _fw_err:
        _fw_log("drawclose.py:67", _fw_err)


def calm_document(doc):
    """Every sheet window of doc calmed (before the document closes). Returns how many."""
    if doc is None:
        return 0
    try:
        Gui.Selection.clearPreselection()
    except Exception as _fw_err:
        _fw_log("drawclose.py:77", _fw_err)
    names = {o.Name for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")}
    if not names:
        return 0
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    n = 0
    for sub in (mdi.subWindowList() if mdi is not None else []):
        try:
            w = sub.widget()
            if w is None or "MDIViewPage" not in w.metaObject().className() or w.objectName() not in names:
                continue
        except Exception as _fw_err:
            _fw_log("drawclose.py:90", _fw_err)
            continue
        for vw in _sheet_views(sub):
            calm_view(vw)
            n += 1
    return n


def SHOWN_GONE(D, doc):
    """A drawing PM of doc (or of a drawing of doc's model) that something else already closed, its step open."""
    try:
        held = getattr(D, "SHOWN", None)
        p = held[0] if held else None
        pdoc = getattr(p, "doc", None) if p is not None else None
        return pdoc is not None and not Gui.Control.activeDialog() and \
            (pdoc.Name == doc.Name or doc in pdoc.getDependentDocuments())
    except Exception:
        return False


def end_pm_of(doc):
    ""



    if doc is None:
        return False
    ended = False
    try:
        from . import drawings as D
    except Exception as _fw_err:
        _fw_log("drawclose.py:end pm import", _fw_err)
        return False
    for held in (getattr(D, "SHOWN", None), getattr(D, "VIEW_PM", None)):
        if not held:
            continue
        panel = held[0]
        try:
            pdoc = getattr(panel, "doc", None)
            mine = pdoc is not None and (pdoc.Name == doc.Name or doc in pdoc.getDependentDocuments())
        except Exception:            # the panel's document is already gone
            mine = False
        if not mine or not Gui.Control.activeDialog():
            continue
        held[:] = []
        try:
            if getattr(panel, "made", None):
                panel.accept()
            else:
                panel.reject()
            ended = True
        except Exception as _fw_err:
            _fw_log("drawclose.py:end pm", _fw_err)
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        except Exception as _fw_err:
            _fw_log("drawclose.py:end pm close", _fw_err)
    if ended:
        try:
            if getattr(doc, "HasPendingTransaction", False):
                doc.abortTransaction()
        except Exception as _fw_err:
            _fw_log("drawclose.py:end pm abort", _fw_err)
    if ended or (SHOWN_GONE(D, doc)):
        try:
            D.close_command_step(True)     # FreeCAD's step for the drawing tool whose PM was ended
        except Exception as _fw_err:
            _fw_log("drawclose.py:end pm step", _fw_err)
    return ended


def _on_close(obj, event):
    """A window closing: its sheet views calmed first."""
    try:
        if event.type() != QtCore.QEvent.Close or not isinstance(obj, QtWidgets.QWidget):
            return False
        if isinstance(obj, QtWidgets.QMdiSubWindow) or "MDIView" in obj.metaObject().className():
            views = _sheet_views(obj)
            if views:
                try:
                    Gui.Selection.clearPreselection()
                except Exception as _fw_err:
                    _fw_log("drawclose.py:107", _fw_err)
            for vw in views:
                calm_view(vw)
    except Exception as _fw_err:
        _fw_log("drawclose.py:111", _fw_err)
    return False


class _Observer:
    def slotDeletedDocument(self, doc):
        try:
            calm_document(doc)
        except Exception as _fw_err:
            _fw_log("drawclose.py:120", _fw_err)


def install():
    if _DONE:
        return
    _DONE.append(_Observer())
    App.addDocumentObserver(_DONE[0])
    try:
        from . import events
        events.register("drawclose.close", (QtCore.QEvent.Close,), _on_close)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: sheet close guard: %s\n" % error)
    orig = getattr(App, "closeDocument", None)
    if orig is not None and not getattr(orig, "_fw_calm", False):
        def closeDocument(name, *args, **kw):
            try:
                end_pm_of(App.listDocuments().get(name))
            except Exception as _fw_err:
                _fw_log("drawclose.py:end pm", _fw_err)
            try:
                calm_document(App.listDocuments().get(name))
            except Exception as _fw_err:
                _fw_log("drawclose.py:139", _fw_err)
            return orig(name, *args, **kw)
        closeDocument._fw_calm = True
        closeDocument.__doc__ = getattr(orig, "__doc__", None)
        try:
            App.closeDocument = closeDocument
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sheet close guard (closeDocument): %s\n" % error)
