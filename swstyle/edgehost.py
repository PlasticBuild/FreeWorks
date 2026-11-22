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

import os
import sys
import time

import FreeCAD as App

try:
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    QtCore = None

WIN = sys.platform == "win32"
if WIN:
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0x00C00000, 0x00040000, 0x00080000, 0x20000, 0x10000
CLASS = "Chrome_WidgetWin_1"


CANDIDATES = (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe",
              r"BraveSoftware\Brave-Browser\Application\brave.exe", r"Chromium\Application\chrome.exe")


def _registered(name):
    """App Paths entry of an installed browser (any install location)."""
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + name) as k:
                    path = winreg.QueryValue(k, None)
                    if path and os.path.isfile(path):
                        return path
            except OSError as _fw_err:
                _fw_log("edgehost.py:60", _fw_err)
    except ImportError:
        pass
    return None


def browser_path():
    """Edge first, then Chrome, Brave, Chromium: any Chromium browser takes the same app-mode flags."""
    if not WIN:
        return None
    for rel in CANDIDATES:
        for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base and os.path.isfile(os.path.join(base, rel)):
                return os.path.join(base, rel)
    for exe in ("msedge.exe", "chrome.exe", "brave.exe"):
        path = _registered(exe)
        # Brave Origin opens its own purchase/restore start page in a new profile, never the page asked for
        if path and "origin" not in path.lower():
            return path
    return None


def why_not():
    """Why the page cannot go in a tab here, for the report view."""
    if not WIN:
        return "not Windows"
    if QtCore is None:
        return "no Qt"
    if browser_path() is None:
        return "no Edge, Chrome or Brave found"
    return ""


def available():
    return not why_not()


def _top_windows():
    found = {}

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, name, 256)
            if name.value == CLASS:
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, title, 512)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found[hwnd] = (pid.value, title.value)
        return True
    user32.EnumWindows(WNDENUMPROC(each), 0)
    return found


if QtCore is not None:
    class EdgePanel(QtWidgets.QWidget):
        """The page in a tab. extra_buttons: [(text, callable)] shown in the slim bar above it."""
        failed = QtCore.Signal()

        def __init__(self, title, url, profile, extra_buttons=(), note=""):
            super().__init__()
            self.setWindowTitle(title)
            self.url, self.proc, self.hwnd, self.tries = url, None, None, 0
            self.before = {}
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            bar = QtWidgets.QWidget()
            bar.setObjectName("fwExtBar")
            row = QtWidgets.QHBoxLayout(bar)
            row.setContentsMargins(4, 2, 4, 2)
            self.note = QtWidgets.QLabel(note or title)
            self.note.setObjectName("fwExtNote")
            row.addWidget(self.note, 1)
            for text, fn in extra_buttons:
                b = QtWidgets.QToolButton()
                b.setText(text)
                b.clicked.connect(fn)
                row.addWidget(b)
            lay.addWidget(bar)
            self.holder = QtWidgets.QVBoxLayout()
            lay.addLayout(self.holder, 1)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self._poll)
            self._start(profile)

        def _start(self, profile):
            import subprocess
            os.makedirs(profile, exist_ok=True)
            self.before = _top_windows()
            args = [browser_path(), "--app=" + self.url, "--user-data-dir=" + profile, "--no-first-run",
                    "--no-default-browser-check", "--disable-features=Translate", "--window-position=-32000,-32000",
                    "--window-size=1280,800"]
            App.Console.PrintMessage("FreeCAD add-in apps: starting %s for %s\n" % (args[0], self.url))
            self.proc = subprocess.Popen(args)
            self.timer.start(250)

        def _poll(self):
            self.tries += 1
            for hwnd, (pid, title) in _top_windows().items():
                if hwnd not in self.before and title:
                    self.timer.stop()
                    self._embed(hwnd)
                    return
            if self.tries > 80:        # 20 s
                self.timer.stop()
                App.Console.PrintWarning("FreeCAD add-in apps: no new %s window in 20 s (process %s, %d windows seen)\n" % (
                    CLASS, "running" if self.proc.poll() is None else "ended %s" % self.proc.poll(), len(_top_windows())))
                self.note.setText("The page window did not appear: opening it in your browser")
                self.failed.emit()

        def _embed(self, hwnd):
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX))
            self.hwnd = hwnd
            window = QtGui.QWindow.fromWinId(hwnd)
            self.container = QtWidgets.QWidget.createWindowContainer(window, self)
            self.holder.addWidget(self.container)
            App.Console.PrintMessage("FreeCAD add-in apps: page window %#x embedded\n" % hwnd)

        def stop(self):
            self.timer.stop()
            if self.proc is not None and self.proc.poll() is None:
                try:
                    self.proc.terminate()
                except OSError as _fw_err:
                    _fw_log("edgehost.py:188", _fw_err)

        def closeEvent(self, event):
            self.stop()
            super().closeEvent(event)
