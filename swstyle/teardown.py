# SPDX-License-Identifier: LGPL-2.1-or-later
"""Closing documents and quitting FreeCAD without touching deleted objects (exit crashes on the
PC, A7: 0xC0000409 aborts during the window teardown, review 1119).

FreeCAD's shutdown order: the event loop ends (aboutToQuit), the main window and the
QApplication are destroyed (Qt's post routines run first), then App closes the documents and
shuts Python down. Two things went wrong at that point:

- add-on document and selection observers were still registered. FreeCAD's document close then
  called them with the GUI gone (getCamera / getSceneGraph on None, deleted view objects);
- QObjects that Python owns and that have no parent (timers, filters, helper widgets kept in
  module globals) outlived the QApplication. Python deleted them during its shutdown, and
  their Qt destructors and window messages ran Python code with no QApplication left.

This module tracks the observers the add-on registers (App / Gui document observers and
selection observers). It drops them, and deletes the Python-owned parentless QObjects, in a Qt
post routine: after the main window is gone, before the QApplication is, while Python still
runs. For other modules it offers:

- closing(): True once FreeCAD is quitting. Use it to skip work in an observer or a timer.
- alive(obj): True for a usable Qt wrapper, FreeCAD document, document object, view provider or
  Coin node, False for None or a deleted one.
- doc_alive(doc): True while that document is still open.
- on_quit(fn): call fn at aboutToQuit (stop threads, timers, engine handles). Exceptions are logged.
- later(ms, fn, *objs): QTimer.singleShot that skips fn when quitting or any of objs is gone.
"""

import FreeCAD as App

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:         # FreeCAD's PySide shim
    from PySide import QtCore, QtWidgets

try:
    from shiboken6 import Shiboken as _shiboken
except Exception:
    _shiboken = None

PACKAGES = ("swstyle",)
_state = {"installed": False, "closing": False, "done": False}
_observers = []             # (kind, observer): kind in "app", "gui", "selection"
_quit_hooks = []
_originals = {}             # kind -> FreeCAD's own remove function


def _log(where, err):
    try:
        App.Console.PrintLog("FreeCAD teardown %s: %s\n" % (where, err))
    except Exception:
        pass


def _ours(obj):
    mod = getattr(type(obj), "__module__", "") or ""
    return mod.split(".")[0] in PACKAGES


def closing():
    return _state["closing"]


def alive(obj):
    """A usable object: not None and not deleted under its Python wrapper (Qt objects, Coin nodes,
    FreeCAD documents, document objects, view providers and views)."""
    try:
        if obj is None:
            return False
        if _shiboken is not None and isinstance(obj, QtCore.QObject):
            return bool(_shiboken.isValid(obj))
        if (type(obj).__module__ or "").startswith("pivy"):
            return getattr(obj, "this", None) is not None
        getattr(obj, "TypeId", None)      # FreeCAD raises "... of deleted object" once it is gone
        return True
    except Exception:
        return False


def doc_alive(doc):
    if doc is None:
        return False
    try:
        name = doc.Name
    except Exception:
        return False
    try:
        return App.listDocuments().get(name) is doc or name in App.listDocuments()
    except Exception:
        return False


def on_quit(fn):
    _quit_hooks.append(fn)
    return fn


def later(ms, fn, *objs):
    def run():
        if _state["closing"]:
            return
        for o in objs:
            if not alive(o):
                return
        try:
            fn()
        except Exception as err:
            _log("later %s" % getattr(fn, "__name__", fn), err)
    QtCore.QTimer.singleShot(int(ms), run)


# --- observer tracking ------------------------------------------------------------------------
def _wrap(owner, add_name, remove_name, kind):
    add, remove = getattr(owner, add_name, None), getattr(owner, remove_name, None)
    if add is None or remove is None or getattr(add, "_fw_teardown", False):
        return

    def added(observer, *args, _add=add):
        result = _add(observer, *args)
        if _ours(observer) and not _state["done"]:
            _observers.append((kind, observer))
        return result

    def removed(observer, *args, _remove=remove):
        for i in range(len(_observers) - 1, -1, -1):
            if _observers[i][1] is observer:
                del _observers[i]
        return _remove(observer, *args)

    _originals[kind] = remove
    added._fw_teardown = removed._fw_teardown = True
    setattr(owner, add_name, added)
    setattr(owner, remove_name, removed)


def drop_observers():
    """Take every tracked add-on observer off FreeCAD. Returns how many went."""
    count = 0
    for kind, observer in list(_observers):
        try:
            _originals[kind](observer)
            count += 1
        except Exception as err:
            _log("observer %s" % type(observer).__name__, err)
    del _observers[:]
    return count


# --- Python-owned Qt objects ------------------------------------------------------------------
def _holds_foreign(obj):
    """orphanfix-1127: True when obj has a child (at any depth) that Python did not create."""
    try:
        for child in obj.findChildren(QtCore.QObject):
            if not _shiboken.createdByPython(child):
                return True
    except Exception:
        return True
    return False


_LET_GO = []


def _let_go(obj):
    """orphanfix-1127: obj is not deleted here; a reference is kept so it stays as it is while FreeCAD ends (the PC:
    shiboken.invalidate on it crashed the same way as deleting it)."""
    _LET_GO.append(obj)


def delete_orphans():
    """Delete the QObjects Python created and owns that have no parent, while the QApplication
    still exists (otherwise Python deletes them after it, during its own shutdown)."""
    if _shiboken is None:
        return 0
    import gc
    orphans = []
    for obj in gc.get_objects():
        try:
            if not isinstance(obj, QtCore.QObject) or not _shiboken.isValid(obj):
                continue
            if isinstance(obj, QtCore.QCoreApplication):
                continue
            if not (_shiboken.createdByPython(obj) and _shiboken.ownedByPython(obj)):
                continue
            if obj.parent() is not None:
                continue
            orphans.append(obj)
        except Exception:
            continue
    count = 0
    for obj in orphans:
        try:
            if not _shiboken.isValid(obj):
                continue            # went with an orphan deleted before it
            if isinstance(obj, QtCore.QTimer):
                obj.stop()
            if _holds_foreign(obj):
                # orphanfix-1127: it holds Qt objects FreeCAD made and still points at (swmenus' SWLeftOutMenus parks
                # the menus a workbench change left behind): deleting it deleted them under FreeCAD, an access
                # violation in this post routine at every close (PC fault.txt, teardown.py:178). It is let go
                # instead: kept as it is while FreeCAD ends.
                _let_go(obj)
                continue
            if isinstance(obj, QtWidgets.QWidget):
                obj.hide()
            _shiboken.delete(obj)
            count += 1
        except Exception as err:
            _log("orphan %s" % type(obj).__name__, err)
    return count


# --- shutdown ---------------------------------------------------------------------------------
def _about_to_quit():
    _state["closing"] = True
    for fn in list(_quit_hooks):
        try:
            fn()
        except Exception as err:
            _log("quit hook %s" % getattr(fn, "__name__", fn), err)


def _post_routine():
    """Qt runs this as the QApplication goes, after the main window has gone."""
    if _state["done"]:
        return
    _state["closing"] = _state["done"] = True
    try:
        n_obs = drop_observers()
    except Exception as err:
        n_obs = -1
        _log("observers", err)
    try:
        n_qt = delete_orphans()
    except Exception as err:
        n_qt = -1
        _log("orphans", err)
    _log("done", "%d observers dropped, %d Python-owned Qt objects deleted" % (n_obs, n_qt))
    try:
        import os
        out = os.environ.get("FW_TEARDOWN_LOG")
        if out:
            with open(out, "a") as f:
                f.write("teardown post routine: observers %d, qt objects %d\n" % (n_obs, n_qt))
    except Exception:
        pass


def install():
    """Run first thing at start-up, before the modules that register observers are imported."""
    if _state["installed"]:
        return
    _state["installed"] = True
    import FreeCADGui as Gui
    _wrap(App, "addDocumentObserver", "removeDocumentObserver", "app")
    _wrap(Gui, "addDocumentObserver", "removeDocumentObserver", "gui")
    try:
        _wrap(Gui.Selection, "addObserver", "removeObserver", "selection")
    except Exception as err:
        _log("selection", err)
    app = QtCore.QCoreApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(_about_to_quit)
    try:
        QtCore.qAddPostRoutine(_post_routine)
    except Exception as err:
        _log("post routine", err)


# --- scripts and checks ending FreeCAD ---------------------------------------------------------
def exit_cleanly(code=0, wait_ms=20000):
    """Quit FreeCAD through its normal shutdown, as File > Exit does with Don't Save answered, instead
    of os._exit: on Windows os._exit while Qt and the add-on still run crashes in the C runtime's
    exit (0xC0000409 / access violation: every PC check run, review 1119). The documents are not
    saved. os._exit(code) only if the window is still up after wait_ms."""
    import os
    if _state.get("exiting"):
        return
    _state["exiting"] = True
    hard = getattr(os, "_fw_real_exit", os._exit)
    try:
        import FreeCADGui as Gui
        from . import closeprompt
        closeprompt.answer_hook = lambda docs: (closeprompt.DONT_SAVE, [])
        for name in list(App.listDocuments()):
            try:
                gdoc = Gui.getDocument(name)
                if gdoc is not None:
                    gdoc.Modified = False
            except Exception as err:
                _log("exit %s" % name, err)
        for w in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(w, QtWidgets.QDialog) and w.isModal() and w.isVisible():
                w.reject()          # a box a check left up
        mw = Gui.getMainWindow()
        QtCore.QTimer.singleShot(0, mw.close)
    except Exception as err:
        _log("exit", err)
        hard(code)
        return
    QtCore.QTimer.singleShot(int(wait_ms), lambda: hard(code))


def route_os_exit():
    """For check runners: os._exit(n) quits through exit_cleanly from now on."""
    import os
    if getattr(os, "_fw_real_exit", None) is None:
        os._fw_real_exit = os._exit
        os._exit = lambda code=0: exit_cleanly(code)
