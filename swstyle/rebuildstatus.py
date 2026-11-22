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

import time
import FreeCAD as App
import FreeCADGui as Gui

PAINT_GAP = 0.25        # s: one synchronous status-bar paint per quarter second at most
FEW = 40                # objects: a new or small document's first rebuild is not painted for (a
                        # 300-part assembly build made 20 parts, each forcing a 50 ms paint)
SLOW = 0.3              # s: a document whose last rebuild took less is not painted for (the message
                        # would be gone before anyone saw it; an assembly build runs hundreds of these)

from . import paths

PARAM = "RebuildStatus"
TEXT = "Rebuilding, Please wait ..."
PREVIEW_TEXT = "Press <ESC> to cancel Preview"
PREVIEW = [False]                                   # set by the page whose preview is building (filletpm)
ESC_TEXT = "Rebuilding, press Esc to stop it ..."
                        # the rebuild (Engine Cover 2026); FreeCAD's own "Allow aborting
                        # recomputation" option makes Esc ask "Abort the operation?" and stops it


def rebuild_text():
    """The rebuild message: it names Esc only while FreeCAD lets Esc stop a rebuild."""
    try:
        if App.ParamGet("User parameter:BaseApp/Preferences/Document").GetBool("CanAbortRecompute", True):
            return ESC_TEXT
    except Exception as _fw_err:
        _fw_log("rebuildstatus.py:46", _fw_err)
    return TEXT

_observer = None


def enabled():
    return paths.params().GetBool(PARAM, True)


def _bar():
    mw = Gui.getMainWindow()
    return mw.statusBar() if mw is not None else None


def _safe_to_paint(doc, bar):
    """A synchronous repaint is only done for a rebuild of the document in front, with the window
    up: a recompute that runs while a document closes (or before the window shows) repainted
    widgets being torn down and crashed FreeCAD (sweep 2026-11-05)."""
    try:
        if not bar.isVisible():
            return False
        gdoc = Gui.ActiveDocument
        if gdoc is None or gdoc.Document is not doc:
            return False
        return doc.Name in App.listDocuments()
    except Exception:
        return False


def _in_front(doc):
    """The document the user is looking at (or no GUI document at all, as in a check)."""
    try:
        gdoc = Gui.ActiveDocument
        return gdoc is None or gdoc.Document is doc
    except Exception:
        return True


class _Observer:
    def __init__(self):
        self.shown = []         # for checks: each message shown
        self._last_paint = 0.0  # time.monotonic() of the last synchronous repaint
        self.skipped = 0        # for checks: repaints coalesced away
        self._started = {}      # document name -> time.monotonic() its rebuild began
        self._took = {}         # document name -> how long its last rebuild took
        self._showing = False   # the message is up (only then is it cleared)

    def slotBeforeRecomputeDocument(self, doc):
        if not enabled():
            return
        try:
            name = doc.Name
            now = time.monotonic()
            self._started[name] = now
            if not _in_front(doc):
                self.skipped += 1       # a document in the background (a component an assembly
                return                  # build loads): no message (0.8 s in the pkg179 profile)
            bar = _bar()
            if bar is None:
                return
            text = PREVIEW_TEXT if PREVIEW[0] else rebuild_text()
            bar.showMessage(text)
            self._showing = True
            first = SLOW if len(doc.Objects) > FEW else 0.0     # never rebuilt yet: slow only when it is big
            if self._took.get(name, first) < SLOW:
                self.skipped += 1       # its rebuilds are quick: the message shows, no forced paint
            elif now - self._last_paint < PAINT_GAP:
                self.skipped += 1       # a page open recomputes twice: paint once
            elif _safe_to_paint(doc, bar):
                bar.repaint()           # painted now: no events run during the rebuild
                self._last_paint = now
            self.shown.append(text)
        except Exception as _fw_err:
            _fw_log("rebuildstatus.py:120", _fw_err)

    def slotRecomputedDocument(self, doc):
        try:
            began = self._started.pop(doc.Name, None)
            if began is not None:
                self._took[doc.Name] = time.monotonic() - began
        except Exception as _fw_err:
            _fw_log("rebuildstatus.py:128", _fw_err)
        if not self._showing:
            return
        try:
            bar = _bar()
            if bar is not None and bar.currentMessage() in (TEXT, ESC_TEXT, PREVIEW_TEXT):
                bar.clearMessage()
            self._showing = False
        except Exception as _fw_err:
            _fw_log("rebuildstatus.py:137", _fw_err)

    def slotDeletedDocument(self, doc):
        try:
            self._took.pop(doc.Name, None)
            self._started.pop(doc.Name, None)
        except Exception as _fw_err:
            _fw_log("rebuildstatus.py:144", _fw_err)


def observer():
    return _observer


def install():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
