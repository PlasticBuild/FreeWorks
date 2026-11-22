# SPDX-License-Identifier: LGPL-2.1-or-later
"""Selection observers that outlive what they watch.

A PropertyManager adds a selection observer and removes it when it closes. When its document is
closed under it (or the panel is closed without its own reject), the observer stays and every
later pick in any document raises "Cannot access attribute ... of deleted object" from it, over
and over. install() wraps Gui.Selection.addObserver/removeObserver: each observer is called
through a guard that drops it the first time it touches a deleted object."""

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

_ORIG = {}
_GUARDS = {}            # id(observer) -> guard


def _dead(error):
    text = str(error)
    return isinstance(error, ReferenceError) or "already deleted" in text or "of deleted object" in text


class _Guard:
    def __init__(self, obs):
        self._obs = obs

    def __getattr__(self, name):
        f = getattr(self._obs, name)            # AttributeError when the observer lacks it, as before
        if not callable(f):
            return f

        def call(*args, **kw):
            try:
                return f(*args, **kw)
            except Exception as error:
                if not _dead(error):
                    raise
                drop(self._obs)
                App.Console.PrintLog("FreeCAD: dropped a selection observer whose object is gone (%s)\n"
                                     % type(self._obs).__name__)
                return None
        return call


def drop(obs):
    g = _GUARDS.pop(id(obs), None)
    if g is not None:
        try:
            _ORIG["remove"](g)
        except Exception as _fw_err:
            _fw_log("selguard.py:61", _fw_err)


def _add(obs, *args):
    if id(obs) in _GUARDS:
        return None                 # FreeCAD ignores a second add of the same observer too
    g = _Guard(obs)
    _GUARDS[id(obs)] = g
    return _ORIG["add"](g, *args)


def _remove(obs):
    g = _GUARDS.pop(id(obs), None)
    return _ORIG["remove"](g if g is not None else obs)


def install():
    if _ORIG:
        return
    sel = Gui.Selection
    _ORIG.update(add=sel.addObserver, remove=sel.removeObserver)
    sel.addObserver = _add
    sel.removeObserver = _remove


def count():
    return len(_GUARDS)


def quiet(fn):
    """Run a deferred pick: its document or panel may have closed since it was queued (a
    timer fired after the window went), which is not an error."""
    try:
        return fn()
    except (ReferenceError, RuntimeError) as error:
        if _dead(error) or "already deleted" in str(error) or "deleted object" in str(error):
            return None
        raise
