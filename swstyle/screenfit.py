# SPDX-License-Identifier: LGPL-2.1-or-later
"""Every window FreeCAD opens fits its screen, with its buttons on it.

A dialog sized for a big screen (Pack and Go 980 x 620, Print Preview 900 x 760) ran off the bottom of a
1080p screen at 200 % (960 x 540 logical) or a 1366 x 768 laptop: OK / Cancel fell below the taskbar. When a
window shows, it is made no bigger than the available screen less its title bar, and put back on the screen.
A window that fits is not touched. fit(widget) does the same for one window (BB44 DS-2 sweep, fh246).
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


from PySide import QtCore, QtWidgets

TITLE_BAR = 32          # a title bar not drawn yet (Windows at 100 %)
_FILTER = []


def _screen_rect(w):
    try:
        s = w.screen() if hasattr(w, "screen") else None
        centre = w.frameGeometry().center()
        at = QtWidgets.QApplication.screenAt(centre) if hasattr(QtWidgets.QApplication, "screenAt") else None
        s = at or s or QtWidgets.QApplication.primaryScreen()
        return s.availableGeometry()
    except Exception as _fw_err:
        _fw_log("screenfit.py:screen", _fw_err)
        return None


def fit(w):
    """w (a top-level window) no bigger than its screen, and on it. True when it was changed."""
    area = _screen_rect(w)
    if area is None or area.width() < 200 or area.height() < 200:
        return False
    bar = w.frameGeometry().height() - w.height()
    bar = bar if bar > 0 else TITLE_BAR
    side = max(0, (w.frameGeometry().width() - w.width()) // 2)
    max_w, max_h = area.width() - 2 * side, area.height() - bar - side
    changed = False
    if w.width() > max_w or w.height() > max_h:
        if w.minimumWidth() > max_w:
            w.setMinimumWidth(max_w)
        if w.minimumHeight() > max_h:
            w.setMinimumHeight(max_h)
        w.resize(min(w.width(), max_w), min(w.height(), max_h))
        changed = True
    f = w.frameGeometry()
    x = min(max(f.x(), area.x()), area.right() + 1 - f.width())
    y = min(max(f.y(), area.y()), area.bottom() + 1 - f.height())
    x, y = max(x, area.x()), max(y, area.y())
    if (x, y) != (f.x(), f.y()):
        w.move(x, y)
        changed = True
    return changed


def _home_window(w):
    """The window a dialog belongs over: its parent's window, else FreeCAD's main window (None when neither)."""
    try:
        p = w.parentWidget()
        if p is not None:
            return p.window()
        import FreeCADGui
        return FreeCADGui.getMainWindow()
    except Exception as _fw_err:
        _fw_log("screenfit.py:home", _fw_err)
        return None


def home(w):
    ""



    if w.property("fw_screenfit_homed"):
        return False
    w.setProperty("fw_screenfit_homed", True)
    owner = _home_window(w)
    if owner is None or owner is w or not owner.isVisible():
        return False
    try:
        at = owner.frameGeometry().center()
        s = QtWidgets.QApplication.screenAt(at) if hasattr(QtWidgets.QApplication, "screenAt") else None
        s = s or owner.screen() or QtWidgets.QApplication.primaryScreen()
        area = s.availableGeometry()
        f = w.frameGeometry()
        if area.contains(f.center()):
            return False
        x = at.x() - f.width() // 2
        y = at.y() - f.height() // 2
        x = min(max(x, area.x()), area.right() + 1 - f.width())
        y = min(max(y, area.y()), area.bottom() + 1 - f.height())
        w.move(max(x, area.x()), max(y, area.y()))
        return True
    except Exception as _fw_err:
        _fw_log("screenfit.py:homed", _fw_err)
        return False


class _ShowFilter(QtCore.QObject):
    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QDialog) and obj.isWindow() \
                    and not obj.property("fw_no_screenfit"):
                home(obj)           # fh262: on the screen of the window it belongs to, then fitted to that screen
                fit(obj)
                QtCore.QTimer.singleShot(0, lambda o=obj: _again(o))     # after the window's own first layout
        except Exception as _fw_err:
            _fw_log("screenfit.py:show", _fw_err)
        return False


def _again(w):
    try:
        if w.isVisible():
            fit(w)
    except (RuntimeError, Exception) as _fw_err:
        _fw_log("screenfit.py:again", _fw_err)


def install():
    if _FILTER:
        return
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    f = _ShowFilter(app)
    app.installEventFilter(f)
    _FILTER.append(f)
