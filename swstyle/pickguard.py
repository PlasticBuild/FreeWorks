# SPDX-License-Identifier: LGPL-2.1-or-later
"""A PropertyManager's selection observer outliving its page.

A page that FreeCAD closes without OK or Cancel (another command, the document closed) never
removes its selection observer, and the next pick in any document then reaches a page whose
feature or document is gone. stale(observer, thing) says so, and takes the observer away, so
addSelection can return at once.
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

import FreeCAD as App
import FreeCADGui as Gui


def _drop(observer):
    try:
        Gui.Selection.removeObserver(observer)
    except Exception as _fw_err:
        _fw_log("pickguard.py:29", _fw_err)


def stale(observer, *things):
    """True when any of things (a document object, a document or a Qt widget) is gone; the
    observer is then removed."""
    for thing in things:
        try:
            if thing is None:
                raise ReferenceError
            if hasattr(thing, "isVisible") and not hasattr(thing, "Name"):
                thing.objectName()          # a deleted Qt widget raises RuntimeError
                continue
            doc = thing if isinstance(thing, App.Document) else thing.Document
            if doc.Name not in App.listDocuments():
                raise ReferenceError
            if not isinstance(thing, App.Document) and doc.getObject(thing.Name) is None:
                raise ReferenceError
        except (ReferenceError, RuntimeError, AttributeError):
            _drop(observer)
            return True
    return False
