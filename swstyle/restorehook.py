"""One working "a document finished opening" hook for the whole add-on.

FreeCAD 1.1 never sends slotStartRestoreDocument / slotFinishRestoreDocument to Python document
observers, so every module that waited for them did nothing when a file opened. This module watches
what FreeCAD does send: slotCreatedDocument (the document exists, Restoring is True while the file
is read), slotActivateDocument (the file may become active before it is done) and, should FreeCAD
ever send it, slotFinishRestoreDocument. From the first of those it polls the document every 100 ms
until Restoring is False and its Gui document exists, then calls every registered callback once per
document, in registration order, each in its own try. A document opened before install() ran (a
file given to FreeCAD at start) is reported when install() runs.

    from . import restorehook
    restorehook.on_restored(my_function)        # my_function(doc) after the file has opened
    restorehook.on_restored(other, delay=600)   # 600 ms later still
"""

_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return

import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

POLL_MS = 100
GIVE_UP_S = 120          # a huge file: stop polling after this long and report it anyway
_callbacks = []          # [(callback, delay ms)]
_fired = set()           # document names reported
_polling = {}            # document name -> start time
_observer = []
_timer = []


def on_restored(callback, delay=0):
    """Registers callback(doc) for every document that finishes opening; returns callback."""
    for cb, _d in _callbacks:
        if cb is callback:
            return callback
    _callbacks.append((callback, int(delay)))
    install()
    return callback


def remove(callback):
    _callbacks[:] = [(cb, d) for cb, d in _callbacks if cb is not callback]


def fired(name):
    return name in _fired


def _gui(name):
    try:
        return Gui.getDocument(name)
    except Exception:
        return None


def _ready(doc):
    try:
        if getattr(doc, "Restoring", False):
            return False
    except Exception as _fw_err:
        _fw_log("restorehook.py:73", _fw_err)
    return _gui(doc.Name) is not None or not App.GuiUp


def _report(doc):
    name = doc.Name
    if name in _fired:
        return
    _fired.add(name)
    _polling.pop(name, None)
    for cb, delay in list(_callbacks):
        if delay:
            QtCore.QTimer.singleShot(delay, lambda cb=cb, name=name: _call(cb, name))
        else:
            _call(cb, name)


def _call(cb, name):
    doc = App.listDocuments().get(name)
    if doc is None:
        return
    try:
        cb(doc)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: after open, %s: %s\n" % (getattr(cb, "__name__", cb), error))


def _watch(doc):
    """A document that is opening (or may be): poll it until it is ready."""
    name = doc.Name
    if name in _fired or name in _polling:
        return
    _polling[name] = time.monotonic()
    _ensure_timer()


def _tick():
    for name in list(_polling):
        doc = App.listDocuments().get(name)
        if doc is None:
            _polling.pop(name, None)
            continue
        if _ready(doc) or time.monotonic() - _polling[name] > GIVE_UP_S:
            _report(doc)
    if not _polling and _timer:
        _timer[0].stop()


def _ensure_timer():
    if not _timer:
        t = QtCore.QTimer()
        t.setInterval(POLL_MS)
        t.timeout.connect(_tick)
        _timer.append(t)
    if not _timer[0].isActive():
        _timer[0].start()


class _Observer:
    def slotCreatedDocument(self, doc):
        # a new empty document is not an opened file: only one that is restoring, or has a file
        try:
            restoring = bool(getattr(doc, "Restoring", False)) or bool(doc.FileName)
        except Exception:
            restoring = False
        if restoring:
            _watch(doc)
        else:
            # FreeCAD sets Restoring right after creating the document: look again in a moment
            QtCore.QTimer.singleShot(0, lambda name=doc.Name: _late_check(name))

    def slotActivateDocument(self, doc):
        # only a document still restoring: a new document that was just saved has a FileName too
        try:
            if getattr(doc, "Restoring", False) and doc.Name not in _fired:
                _watch(doc)
        except Exception as _fw_err:
            _fw_log("restorehook.py:150", _fw_err)

    def slotFinishRestoreDocument(self, doc):
        _report(doc)

    def slotDeletedDocument(self, doc):
        _fired.discard(doc.Name)
        _polling.pop(doc.Name, None)


def _late_check(name):
    doc = App.listDocuments().get(name)
    try:
        if doc is not None and (getattr(doc, "Restoring", False) or doc.FileName):
            _watch(doc)
    except Exception as _fw_err:
        _fw_log("restorehook.py:166", _fw_err)


def install():
    if _observer:
        return
    _observer.append(_Observer())
    App.addDocumentObserver(_observer[0])
    for doc in App.listDocuments().values():
        try:
            if doc.FileName:
                _watch(doc)
        except Exception as _fw_err:
            _fw_log("restorehook.py:179", _fw_err)


def remove_all():
    if _observer:
        try:
            App.removeDocumentObserver(_observer[0])
        except Exception as _fw_err:
            _fw_log("restorehook.py:187", _fw_err)
        del _observer[:]
    if _timer:
        _timer[0].stop()
    _callbacks[:] = []
    _fired.clear()
    _polling.clear()
