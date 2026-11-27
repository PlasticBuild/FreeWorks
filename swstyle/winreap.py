# SPDX-License-Identifier: LGPL-2.1-or-later
"""winreap-1127: a closed add-on window is freed once a new one of its kind opens.

Most of the add-on's windows (Print Preview, Pack and Go, Find References, Document Properties, External
References, Material, Help, the Property Tab Builder, Compare, Find/Modify, Design Study...) are made with the
main window as their parent and a new one is made each time the command runs. Closing one only hides it, and
the main window keeps it: every open and close kept a whole window (Print Preview 25-50 MB), so a long session
grew without end (PC dialog soak 11-27: 743 -> 1222 MB over 63 opens).

When the main window gets a new child window, this frees the hidden add-on windows of the same class made
before it (the newest of each class is always kept, shown or not, and nothing shown is ever touched). A
window the code keeps and shows again (Mass Properties, the Guide) stays the only one of its class, so it
stays too. One sweep per new child window, over the main window's own children: no timer, no app-wide filter.
"""

_FW_SEEN = set()


def _fw_log(site, err):
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        return


from PySide import QtCore, QtWidgets

Qt = QtCore.Qt
_state = {"filter": None, "due": False, "freed": 0}
_SKIP_TYPES = (Qt.Popup, Qt.ToolTip, Qt.SplashScreen, Qt.Desktop, Qt.SubWindow)


def _ours(w):
    try:
        return type(w).__module__.startswith("swstyle.") and w.isWindow() and w.windowType() not in _SKIP_TYPES
    except Exception:
        return False


def sweep():
    """Frees the hidden add-on windows a newer window of the same class has replaced. Returns how many."""
    _state["due"] = False
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
    except Exception:
        return 0
    if mw is None:
        return 0
    by_class = {}
    for w in mw.children():         # creation order: the last of a class is the newest
        if isinstance(w, QtWidgets.QWidget) and _ours(w):
            by_class.setdefault(type(w), []).append(w)
    n = 0
    for kind, wins in by_class.items():
        for w in wins[:-1]:
            try:
                if not w.isVisible() and not w.testAttribute(Qt.WA_DeleteOnClose):
                    w.deleteLater()
                    n += 1
            except Exception as _fw_err:
                _fw_log("winreap.py:sweep", _fw_err)
    _state["freed"] += n
    return n


class _Watch(QtCore.QObject):
    def eventFilter(self, watched, event):
        try:
            if event.type() == QtCore.QEvent.ChildAdded and not _state["due"]:
                _state["due"] = True
                QtCore.QTimer.singleShot(0, sweep)
        except Exception as _fw_err:
            _fw_log("winreap.py:filter", _fw_err)
        return False


def install():
    if _state["filter"] is not None:
        return
    try:
        import FreeCADGui as Gui
        mw = Gui.getMainWindow()
        _state["filter"] = _Watch(mw)
        mw.installEventFilter(_state["filter"])
    except Exception as _fw_err:
        _fw_log("winreap.py:install", _fw_err)


def remove():
    f = _state["filter"]
    _state["filter"] = None
    if f is not None:
        try:
            import FreeCADGui as Gui
            Gui.getMainWindow().removeEventFilter(f)
        except Exception as _fw_err:
            _fw_log("winreap.py:remove", _fw_err)
