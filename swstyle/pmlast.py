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
from PySide import QtCore, QtWidgets

from . import paths

PARAM = "PMLastValues"
DONE = "swPMLastDone"
HOOKED = "swPMLastHooked"
NEW_WINDOW = 4.0                 # s: an object created this long before the page opened = a new feature
SKIP_TITLES = ("Mate", "Move Component", "Rotate Component", "Insert Components", "Smart Dimension",
               "Model View", "Projected View", "Section View", "Detail View", "Note", "Balloon",
               "Bill of Materials", "Hole Callout", "Exploded View", "Measure", "Mass Properties")
OWN_DEPTH = ("lengthEdit",)      # pmkeys: Extrude and Cut start at the last depth already

_created = [0.0]


class _Watch:
    def slotCreatedObject(self, obj):
        _created[0] = time.time()


_watch = None


def _start_watch():
    global _watch
    if _watch is None:
        _watch = _Watch()
        App.addDocumentObserver(_watch)


def _on():
    try:
        return paths.params().GetBool(PARAM, True)
    except Exception:
        return True


def _group(title):
    safe = "".join(c if c.isalnum() else "_" for c in title)[:60] or "Page"
    return paths.params().GetGroup("PMLast").GetGroup(safe)


def _fields(view):
    out, n = [], 0
    for w in view.findChildren(QtWidgets.QAbstractSpinBox):
        try:
            if not (w.isVisible() and w.isEnabled()) or w.isReadOnly():
                continue
        except RuntimeError:
            continue
        n += 1
        name = w.objectName()
        if name in OWN_DEPTH or name.startswith("qt_"):
            continue
        if isinstance(w, QtWidgets.QSpinBox):
            continue        # counts (pattern instances) start at the page's own: a count of 1 left from a
            # last run made Instances to Vary do nothing
        out.append((name or "#%d" % n, w))
    return out


def _skip(title):
    return not title or any(title.startswith(t) for t in SKIP_TITLES)


def _accept_buttons(view):
    out = []
    for box in view.findChildren(QtWidgets.QDialogButtonBox):
        for b in box.buttons():
            if box.buttonRole(b) in (QtWidgets.QDialogButtonBox.AcceptRole, QtWidgets.QDialogButtonBox.YesRole):
                out.append(b)
    return out


def remember(view, title):
    if not _on() or _skip(title):
        return
    _start_watch()
    for b in _accept_buttons(view):
        if b.property(HOOKED) == title:
            continue
        b.setProperty(HOOKED, title)
        b.pressed.connect(lambda v=view, t=title: _save(v, t))


def _save(view, title):
    from . import pmvalues
    try:
        g = _group(title)
        for key, w in _fields(view):
            try:
                g.SetFloat(key, float(pmvalues._value(w)))
            except Exception as _fw_err:
                _fw_log("pmlast.py:123", _fw_err)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PM last values: %r\n" % (error,))


def restore(view, title):
    if not _on() or _skip(title):
        return
    _start_watch()
    buttons = _accept_buttons(view)
    if not buttons or buttons[0].property(DONE):
        return          # once per page: a new page has a new button box
    buttons[0].setProperty(DONE, True)
    if time.time() - _created[0] > NEW_WINDOW:
        return          # Edit Feature (or a page that makes nothing): its own values stay
    from . import pmvalues
    g = _group(title)
    try:
        have = {name for kind, name, _v in (g.GetContents() or []) if kind == "Float"}
    except Exception:
        have = set()
    for name, w in _fields(view):
        if name not in have:
            continue
        try:
            value = g.GetFloat(name)
            if abs(float(pmvalues._value(w)) - value) > 1e-12:
                pmvalues._set_value(w, value)
        except Exception as _fw_err:
            _fw_log("pmlast.py:152", _fw_err)
