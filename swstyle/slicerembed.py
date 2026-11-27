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

import ctypes
import os
import subprocess
import sys
import time

import FreeCAD as App
from PySide import QtCore, QtGui, QtWidgets

Qt = QtCore.Qt

FIND_SECONDS = 120          # a cold start of a slicer scans its presets; Bambu Studio took 25 s on the PC. Past this
                            # the tab says so and keeps looking (slower) for as long as the program runs: its window
                            # is taken into the tab whenever it shows (PrusaSlicer 3.0's first start copies its presets
                            # and may wait on a message box first), never left on its own on the desktop
SLOW_POLL_MS = 1000
POLL_MS = 300
MAIN_SIZE = 700            # the main window is bigger than a splash; after SPLASH_WAIT seconds any window of MIN_SIZE will do
SPLASH_WAIT = 45
MIN_SIZE = 300              # a splash or tool window smaller than this is not the main window


# ---------------------------------------------------------------------- finding a program's window
class _Win:
    """Windows: the main window of a process."""

    @staticmethod
    def main_window(pid, least=MIN_SIZE):
        user32 = ctypes.windll.user32
        from ctypes import wintypes
        found = []
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def each(hwnd, _):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value != pid or not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):   # GW_OWNER
                return True
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w >= least and h >= least * 2 // 3:
                found.append((w * h, int(hwnd)))
            return True
        user32.EnumWindows(proc(each), 0)
        return max(found)[1] if found else None

    @staticmethod
    def close(wid):
        ctypes.windll.user32.PostMessageW(wid, 0x0010, 0, 0)      # WM_CLOSE

    @staticmethod
    def alive(wid):
        return bool(ctypes.windll.user32.IsWindow(wid))

    @staticmethod
    def fit(wid, w, h):
        ctypes.windll.user32.MoveWindow(wid, 0, 0, w, h, True)

    @staticmethod
    def show(wid, on):
        ctypes.windll.user32.ShowWindow(wid, 5 if on else 0)      # SW_SHOW / SW_HIDE


class _X11:
    """X11 (the Linux bench): the window with the process id in _NET_WM_PID."""

    def __init__(self):
        self.x = ctypes.CDLL("libX11.so.6")
        self.x.XOpenDisplay.restype = ctypes.c_void_p
        self.x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x.XInternAtom.restype = ctypes.c_ulong
        self.x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        self.x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                      ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
                                      ctypes.POINTER(ctypes.c_uint)]
        self.x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                              ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                              ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                              ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                              ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
        self.x.XFree.argtypes = [ctypes.c_void_p]

    class _Attr(ctypes.Structure):
        _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
                    ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p),
                    ("root", ctypes.c_ulong), ("klass", ctypes.c_int), ("bit_gravity", ctypes.c_int),
                    ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
                    ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
                    ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
                    ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long),
                    ("your_event_mask", ctypes.c_long), ("do_not_propagate_mask", ctypes.c_long),
                    ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p)]

    def main_window(self, pid, least=MIN_SIZE):
        x = self.x
        x.XGetWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(self._Attr)]
        x.XGetWindowAttributes.restype = ctypes.c_int
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        d = x.XOpenDisplay(None)
        if not d:
            return None
        try:
            root = x.XDefaultRootWindow(d)
            atom = x.XInternAtom(d, b"_NET_WM_PID", 0)
            found = []

            def walk(win, depth):
                if depth > 6:
                    return
                r, p, kids, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.POINTER(ctypes.c_ulong)(), ctypes.c_uint()
                if not x.XQueryTree(d, win, ctypes.byref(r), ctypes.byref(p), ctypes.byref(kids), ctypes.byref(n)):
                    return
                children = [kids[i] for i in range(n.value)]
                if kids:
                    x.XFree(kids)
                for child in children:
                    typ, fmt, items, after = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
                    data = ctypes.POINTER(ctypes.c_ubyte)()
                    ok = x.XGetWindowProperty(d, child, atom, 0, 1, 0, 6, ctypes.byref(typ), ctypes.byref(fmt),
                                              ctypes.byref(items), ctypes.byref(after), ctypes.byref(data))
                    if ok == 0 and items.value and data:
                        owner = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0]
                        x.XFree(data)
                        if owner == pid:
                            attr = self._Attr()
                            x.XGetWindowAttributes(d, child, ctypes.byref(attr))
                            if attr.map_state == 2 and attr.width >= least and attr.height >= least * 2 // 3:
                                found.append((attr.width * attr.height, int(child)))
                            continue
                    walk(child, depth + 1)
            walk(root, 0)
            return max(found)[1] if found else None
        finally:
            x.XCloseDisplay(d)

    @staticmethod
    def close(wid):
        pass

    @staticmethod
    def alive(wid):
        return True

    def fit(self, wid, w, h):
        x = self.x
        x.XOpenDisplay.restype = ctypes.c_void_p
        d = x.XOpenDisplay(None)
        if not d:
            return
        x.XMoveResizeWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_uint, ctypes.c_uint]
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XMoveResizeWindow(d, wid, 0, 0, max(1, w), max(1, h))
        x.XFlush(d)
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x.XCloseDisplay(d)

    def show(self, wid, on):
        x = self.x
        x.XOpenDisplay.restype = ctypes.c_void_p
        d = x.XOpenDisplay(None)
        if not d:
            return
        x.XMapWindow.argtypes = x.XUnmapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x.XFlush.argtypes = [ctypes.c_void_p]
        (x.XMapWindow if on else x.XUnmapWindow)(d, wid)
        x.XFlush(d)
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x.XCloseDisplay(d)


def backend():
    if sys.platform == "win32":
        return _Win()
    return _X11()


# ---------------------------------------------------------------------- the tab's widget
def cstyle_line(words):
    """The slicers' own format for a command line sent between two copies of the program: each word quoted when
    it holds a space, a backslash, a quote, ';' or a line end (backslash and quote escaped), joined by ';'."""
    out = []
    for word in words:
        if word == "" or any(c in word for c in ' ;\t\\"\r\n'):
            word = '"' + word.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n") + '"'
        out.append(word)
    return ";".join(out)


class EmbedHost(QtWidgets.QWidget):
    """A slicer's window as a child of this widget."""

    embedded = QtCore.Signal(int)       # the window's native id
    failed = QtCore.Signal(str)
    ended = QtCore.Signal()             # the program closed

    def __init__(self, title, exe, args=(), env=None, cwd=None, parent=None):
        super().__init__(parent)
        self.title = title
        self.exe = str(exe)
        self.args = [str(a) for a in args]
        self.lead_args = []            # words every start begins with (a settings folder of its own: --datadir)
        self.env = env
        self.cwd = cwd
        self.proc = None
        self.wid = None
        self.container = None
        self._began = 0.0
        self._backend = None
        self.second_args = ()          # extra words for the second start that hands files over (--single-instance)
        self.hand_over = "start"       # "start": a second start hands the files over; "message": straight to the window
        self.setObjectName("SWStyle_SlicerEmbed")
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.note = QtWidgets.QLabel("Starting %s..." % title)
        self.note.setAlignment(Qt.AlignCenter)
        self.note.setWordWrap(True)
        try:                                   # the CommandManager's colours while the slicer starts
            from . import style
            t = style.tokens()
            self.note.setStyleSheet("background:%s;color:%s;" % (t["pane"], t["text_dim"]))
        except Exception as _fw_err:
            _fw_log("slicerembed.py:227", _fw_err)
        self._layout.addWidget(self.note, 1)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    # ------------------------------------------------------------------ run
    def start(self):
        if self.proc is not None and self.proc.poll() is None:
            return True
        env = dict(os.environ if self.env is None else self.env)
        # the embedded program is a separate program: not FreeCAD's Python or Qt
        for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONUTF8"):
            env.pop(name, None)
        flags = 0
        try:
            self.proc = subprocess.Popen([self.exe] + list(self.lead_args) + self.args, env=env, cwd=self.cwd or os.path.dirname(self.exe),
                                         creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            self._fail("Could not start %s: %s" % (self.title, error))
            return False
        self._began = time.time()
        self._backend = backend()
        self._timer.start()
        return True

    def _poll(self):
        if self.proc is None:
            return
        if self.wid is not None:
            if self.proc.poll() is not None:
                self._timer.stop()
                self.wid = None
                self.ended.emit()
                return
            try:
                gone = not self._backend.alive(self.wid)
            except Exception:
                gone = False
            if gone:
                # the program replaced its main window (a restart of its interface): take the new one
                self._drop_container()
                self.note.setText("Opening %s..." % self.title)
                self.note.show()
            return
        code = self.proc.poll()
        if code is not None:
            self._timer.stop()
            self._fail("%s closed straight away (code %s). If another copy of it is already open, close that "
                       "one first: a second start hands its files to the first." % (self.title, code))
            return
        if time.time() - self._began > FIND_SECONDS and self._timer.interval() != SLOW_POLL_MS:
            self._timer.setInterval(SLOW_POLL_MS)
            self.note.setText("%s is still starting (its first start sets up its presets). Its window opens in this "
                              "tab as soon as it shows; if it asks something in a message box, answer it there."
                              % self.title)
        try:
            late = time.time() - self._began > SPLASH_WAIT
            wid = self._backend.main_window(self.proc.pid, MIN_SIZE if late else MAIN_SIZE)
        except Exception as error:
            App.Console.PrintWarning("Slicer embed: looking for the window: %s\n" % error)
            wid = None
        if wid:
            self._take(wid)

    def _drop_container(self):
        self.wid = None
        if self.container is not None:
            try:
                self._layout.removeWidget(self.container)
                self.container.setParent(None)
                self.container.deleteLater()
            except Exception as _fw_err:
                _fw_log("slicerembed.py:drop", _fw_err)
            self.container = None
        self._began = time.time()

    def _take(self, wid):
        if sys.platform == "win32":      # no title bar or frame inside the tab (as edgehost.py does)
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(wid, -16)
            user32.SetWindowLongW(wid, -16, style & ~(0x00C00000 | 0x00040000 | 0x00080000 | 0x20000 | 0x10000))
        window = QtGui.QWindow.fromWinId(wid)
        if window is None:
            self._fail("Qt could not take the window of %s." % self.title)
            self._timer.stop()
            return
        self.container = QtWidgets.QWidget.createWindowContainer(window, self)
        self.container.setFocusPolicy(Qt.StrongFocus)
        self.container.setObjectName("SWStyle_SlicerEmbedWindow")
        self._layout.addWidget(self.container, 1)
        self.container.hide()
        try:
            self._backend.show(wid, False)
        except Exception as _fw_err:
            _fw_log("slicerembed.py:299", _fw_err)
        # a placeholder shows until the slicer has painted at its new size
        self.note.setText("Opening %s..." % self.title)
        self.wid = wid
        from . import safe_later as _sl; _sl.later(250, self._reveal, self, "container")
        for ms in (600, 1200, 2500):          # after the layout has settled
            QtCore.QTimer.singleShot(ms, self.fit)
        self.embedded.emit(wid)

    def _reveal(self):
        if self.container is None or self.wid is None:
            return
        self.container.show()
        try:
            self._backend.show(self.wid, True)
        except Exception as _fw_err:
            _fw_log("slicerembed.py:315", _fw_err)
        self.fit()
        from . import safe_later as _sl; _sl.later(1300, self._painted, self, "note")

    def _painted(self):
        self.fit()
        self.note.hide()

    def fit(self):
        """The slicer keeps its own size unless told: put its window at the tab's corner at the tab's size
        (Bambu Studio did not follow the container by itself)."""
        if not (self.wid and self.container is not None and self._backend is not None):
            return
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        try:
            self._backend.fit(self.wid, int(self.container.width() * dpr), int(self.container.height() * dpr))
        except Exception as error:
            App.Console.PrintWarning("Slicer embed: could not fit the window: %s\n" % error)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit()

    def follow(self, active):
        """Show the slicer's window only while its tab is the one in front (a native window would stay on
        top of the document that came forward)."""
        if self.wid and self._backend is not None:
            self._backend.show(self.wid, bool(active))

    def hideEvent(self, event):
        """Another document's tab came forward: the slicer's window goes with its tab (Qt leaves a foreign
        window showing)."""
        super().hideEvent(event)
        if self.wid and self._backend is not None:
            self._backend.show(self.wid, False)

    def showEvent(self, event):
        super().showEvent(event)
        if self.wid and self._backend is not None:
            self._backend.show(self.wid, True)

    def _fail(self, text):
        self.note.setText(text)
        self.note.show()
        self.failed.emit(text)

    # ------------------------------------------------------------------ hand over
    def open_files(self, paths):
        """Files for the slicer to open on its plate: the program's second start hands them to the copy
        that is open."""
        paths = [str(p) for p in paths]
        if not paths:
            return False
        if self.proc is None or self.proc.poll() is not None:
            self.args = paths
            return self.start()
        if self.hand_over == "message" and self.message_files(paths):
            return True
        try:
            second = subprocess.Popen([self.exe] + list(self.second_args) + paths, cwd=os.path.dirname(self.exe),
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            QtCore.QTimer.singleShot(12000, lambda: self._stray(second, 0, paths))
            return True
        except OSError as error:
            App.Console.PrintWarning("Slicer embed: could not hand over files: %s\n" % error)
            return False

    def message_files(self, paths):
        """Hand files straight to the open window, the way the slicer's own second start does it (Windows:
        WM_COPYDATA with the command line, each part C-style quoted, joined by ';'). No second program is started.
        True when the window took the message."""
        if sys.platform != "win32" or not self.wid:
            return False
        try:
            from ctypes import wintypes
            text = cstyle_line([self.exe] + [str(p) for p in paths])
            buf = ctypes.create_unicode_buffer(text)

            class CopyData(ctypes.Structure):
                _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]
            data = CopyData(1, ctypes.sizeof(buf), ctypes.cast(buf, ctypes.c_void_p))
            answer = ctypes.c_size_t(0)
            send = ctypes.windll.user32.SendMessageTimeoutW
            send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p, wintypes.UINT,
                             wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
            send.restype = ctypes.c_size_t
            done = send(self.wid, 0x004A, 0, ctypes.byref(data), 0x0002, 5000, ctypes.byref(answer))
            return bool(done and answer.value)
        except Exception as error:
            App.Console.PrintWarning("Slicer embed: could not message the window: %s\n" % error)
            return False

    def reload_from_disk(self):
        """Select all objects (Ctrl+A) and Reload from Disk (F5) in the slicer: keeps each object's
        orientation, position and settings. Needs the slicer window to take the keys, so it is given the
        focus first. Windows only (the bench cannot press keys into another program)."""
        if sys.platform != "win32" or not self.wid or self.container is None:
            return False
        self.container.setFocus()
        user32 = ctypes.windll.user32
        user32.SetForegroundWindow(self.wid)
        time.sleep(0.15)

        def key(code, up=False):
            user32.keybd_event(code, 0, 2 if up else 0, 0)
        key(0x11)
        key(0x41)
        key(0x41, True)
        key(0x11, True)
        time.sleep(0.1)
        key(0x74)
        key(0x74, True)
        return True

    stray_copy = QtCore.Signal(str)

    def _stray(self, second, tries, paths=()):
        """A second start should hand its file to the open copy and end. If it stayed and opened a window of
        its own (the single-instance check did not work here), close that window politely and say so."""
        if second.poll() is not None:
            return
        try:
            wid = self._backend.main_window(second.pid, MIN_SIZE) if self._backend else None
        except Exception:
            wid = None
        if not wid:
            if tries < 6:          # a cold start shows its window late: look again
                QtCore.QTimer.singleShot(8000, lambda: self._stray(second, tries + 1, paths))
            return
        if wid:
            try:
                self._backend.close(wid)
            except Exception as _fw_err:
                _fw_log("slicerembed.py:421", _fw_err)
            if second.poll() is None and sys.platform != "win32":
                second.terminate()
            if paths and self.message_files(paths):
                # the second start did not find this tab's window: the files went to it directly instead
                self.hand_over = "message"
                self.stray_copy.emit("%s opened the part in a second window, so that window was closed and the "
                                     "part was handed to this tab." % self.title)
                return
            self.stray_copy.emit("%s opened the part in a second window instead of this tab, so that window "
                                 "was closed. Use File > Import in this tab for the part file." % self.title)

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def shutdown(self, wait=6.0):
        """Ask the program to close; True when it has gone. It may ask to save first: then it stays."""
        self._timer.stop()
        if self.proc is None or self.proc.poll() is not None:
            return True
        try:
            if sys.platform == "win32" and self.wid:
                self._backend.close(self.wid)
            else:
                self.proc.terminate()
        except Exception as _fw_err:
            _fw_log("slicerembed.py:441", _fw_err)
        end = time.time() + wait
        while time.time() < end and self.proc.poll() is None:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.05)
        return self.proc.poll() is not None
