# SPDX-License-Identifier: LGPL-2.1-or-later
""










import re

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore
except ImportError:                                  # pragma: no cover (no GUI)
    Gui = None
    QtCore = None

OLD = "FreeWorks"
NEW = "FreeCAD"
_NAME = re.compile(r"free\s?works", re.I)
CHUNK = 100
PARAM = "User parameter:BaseApp/Preferences/Mod/FreeWorks"

_state = {"observer": None, "done": set(), "queue": [], "busy": False, "fixed": 0, "hidden": 0, "no_api": 0}


def fix_object(obj):
    """Rename the group and tooltip, hide the name-carrying properties of one object. Returns (renamed, hidden)."""
    renamed = hidden = 0
    try:
        names = list(obj.PropertiesList)
    except Exception:
        return 0, 0
    for name in names:
        try:
            group = obj.getGroupOfProperty(name)
        except Exception:
            continue
        if group and OLD in group:
            setter = getattr(obj, "setGroupOfProperty", None)
            if setter is None:
                _state["no_api"] += 1
            else:
                try:
                    setter(name, group.replace(OLD, NEW))
                    renamed += 1
                    doc = obj.getDocumentationOfProperty(name)
                    if doc and OLD in doc:
                        obj.setDocumentationOfProperty(name, doc.replace(OLD, NEW))
                except Exception:
                    pass
        if _NAME.search(name):
            try:
                modes = list(obj.getEditorMode(name))
                if "Hidden" not in modes:
                    obj.setEditorMode(name, modes + ["Hidden"])
                    hidden += 1
            except Exception:
                pass
    return renamed, hidden


def _modified(doc):
    try:
        return Gui.getDocument(doc.Name).Modified
    except Exception:
        return None


def sweep(doc, objects=None):
    """The whole document at once (the PC check and tests use this); returns (renamed, hidden)."""
    was = _modified(doc)
    renamed = hidden = 0
    for obj in (doc.Objects if objects is None else objects):
        r, h = fix_object(obj)
        renamed += r
        hidden += h
    if was is False and _modified(doc):
        try:
            Gui.getDocument(doc.Name).Modified = False
        except Exception:
            pass
    _state["fixed"] += renamed
    _state["hidden"] += hidden
    return renamed, hidden


def _step():
    """One chunk of the queued documents."""
    _state["busy"] = False
    if not _state["queue"]:
        return
    name, objs = _state["queue"][0]
    doc = App.listDocuments().get(name)
    if doc is None:
        _state["queue"].pop(0)
    else:
        chunk, rest = objs[:CHUNK], objs[CHUNK:]
        try:
            sweep(doc, [o for o in chunk if _alive(o)])
        except Exception as error:
            App.Console.PrintLog("FreeCAD: property names sweep: %s\n" % error)
        if rest:
            _state["queue"][0] = (name, rest)
        else:
            _state["queue"].pop(0)
    if _state["queue"] and not _state["busy"] and QtCore is not None:
        _state["busy"] = True
        QtCore.QTimer.singleShot(20, _step)


def _alive(obj):
    try:
        obj.Name
        return True
    except Exception:
        return False


def schedule(doc):
    """Queue a document once (until it is closed)."""
    if doc.Name in _state["done"]:
        return False
    _state["done"].add(doc.Name)
    _state["queue"].append((doc.Name, list(doc.Objects)))
    if not _state["busy"] and QtCore is not None:
        _state["busy"] = True
        QtCore.QTimer.singleShot(0, _step)
    return True


class _Observer:
    def slotActivateDocument(self, doc):
        try:
            schedule(doc)
        except Exception:
            pass

    def slotDeletedDocument(self, doc):
        try:
            _state["done"].discard(doc.Name)
        except Exception:
            pass


def install():
    """At start-up: sweep each document the first time it is activated (and any already open)."""
    if _state["observer"] is not None:
        return 0
    if not App.ParamGet(PARAM).GetBool("UiNameFix", True):
        return 0
    _state["observer"] = _Observer()
    App.addDocumentObserver(_state["observer"])
    n = 0
    for doc in list(App.listDocuments().values()):
        n += 1 if schedule(doc) else 0
    return n
