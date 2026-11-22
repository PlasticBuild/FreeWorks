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


import sys

import FreeCAD as App
from PySide import QtCore

MONITOR_DEFAULTTONEAREST = 2

_filter = None


def _win32():
    import ctypes
    from ctypes import wintypes

    class MINMAXINFO(ctypes.Structure):
        _fields_ = [("ptReserved", wintypes.POINT), ("ptMaxSize", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT), ("ptMinTrackSize", wintypes.POINT),
                    ("ptMaxTrackSize", wintypes.POINT)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    return ctypes, wintypes, user32, MINMAXINFO, MONITORINFO


def monitor_areas(hwnd):
    """(monitor rect, work rect) of the monitor the window is on, as (l, t, r, b)."""
    ctypes, wintypes, user32, _mmi, MONITORINFO = _win32()
    mon = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        return None
    m, w = info.rcMonitor, info.rcWork
    return (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)


class WorkAreaFilter(QtCore.QObject):
    """Watches the main window's state; each time it becomes maximized (button,
    double-click on the title row, Win+Up, Aero snap) it is moved into the work
    area. A Qt event filter, so Python does not see every native message."""

    EVENTS = (QtCore.QEvent.WindowStateChange, QtCore.QEvent.Show)

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.hwnd = int(mw.winId())
        self.fits = 0

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            if obj is self.mw and event.type() in self.EVENTS:
                QtCore.QTimer.singleShot(0, self._fit)
                QtCore.QTimer.singleShot(150, self._fit)   # Windows sizes a maximize late
        except Exception as _fw_err:
            _fw_log("workarea.py:88", _fw_err)
        return False

    def _fit(self):
        if fit_now(self.mw):
            self.fits += 1


def install(mw):
    """Keep the frameless main window inside the work area when maximized."""
    global _filter
    if not sys.platform.startswith("win") or mw is None:
        return None
    try:
        if _filter is not None and _filter.mw is mw:
            fit_now(mw)
            return _filter
        uninstall()
        _filter = WorkAreaFilter(mw)
        mw.installEventFilter(_filter)
        fit_now(mw)
        App.Console.PrintLog("FreeCAD: maximized window kept above the taskbar\n")
    except Exception as error:
        App.Console.PrintLog("FreeCAD: work area filter not set: %s\n" % error)
    return _filter


def fit_now(mw):
    """A window maximized before the filter was in place still covers the taskbar:
    move it into the work area without leaving the maximized state."""
    if not sys.platform.startswith("win") or mw is None or not mw.isMaximized():
        return False
    try:
        _ctypes, wintypes, user32, _mmi, _mi = _win32()
        hwnd = int(mw.winId())
        areas = monitor_areas(hwnd)
        if areas is None:
            return False
        _mon, (wl, wt, wr, wb) = areas
        rect = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes_byref(rect))
        if (rect.left, rect.top, rect.right, rect.bottom) == (wl, wt, wr, wb):
            return False
        SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0004, 0x0010, 0x0020
        user32.SetWindowPos(wintypes.HWND(hwnd), None, wl, wt, wr - wl, wb - wt,
                            SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: work area fit failed: %s\n" % error)
    return False


def ctypes_byref(obj):
    import ctypes
    return ctypes.byref(obj)


def uninstall():
    global _filter
    if _filter is not None:
        try:
            _filter.mw.removeEventFilter(_filter)
        except Exception as _fw_err:
            _fw_log("workarea.py:151", _fw_err)
        _filter = None
