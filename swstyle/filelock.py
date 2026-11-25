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

import json
import os
import socket
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

PARAM = "User parameter:BaseApp/Preferences/Mod/SolidWorksStyle"
STALE_S = 300            # a marker from another computer not refreshed for this long: its FreeCAD is gone
BEAT_MS = 60000
_HELD = {}               # document name -> marker path this FreeCAD wrote
_STAMP = {}              # document name -> (path, mtime_ns, size) of the file as opened or last saved here
_TELL = []               # (file, who) waiting for one box
_installed = []


def enabled():
    return App.ParamGet(PARAM).GetBool("FileLocks", True)


def is_marker(name):
    """A file-in-use marker's file name (left out of Pack and Go's zip)."""
    n = os.path.basename(name)
    return n.startswith(".~$") and n.lower().endswith(".lck")


def marker(path):
    d, b = os.path.split(os.path.abspath(path))
    return os.path.join(d, ".~$" + b + ".lck")


def _me():
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "?"
    return {"user": user, "host": socket.gethostname(), "pid": os.getpid()}


def _alive(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return bool(ok) and code.value == 259        # STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def read_marker(path):
    try:
        with open(marker(path), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def held_by_other(path):
    """The marker's {user, host, pid, time} when another FreeCAD that is still running has the file; else None."""
    m = read_marker(path)
    if not m:
        return None
    me = _me()
    same_host = str(m.get("host", "")).lower() == me["host"].lower()
    if same_host and int(m.get("pid", -1) or -1) == me["pid"]:
        return None
    if same_host and not _alive(m.get("pid")):
        return None             # its FreeCAD crashed or was ended: the marker is taken over
    try:
        age = time.time() - float(m.get("time", 0))
    except Exception:
        age = STALE_S + 1
    try:
        age = min(age, time.time() - os.path.getmtime(marker(path)))
    except OSError:
        pass
    # a running FreeCAD refreshes its marker every minute: one not refreshed for 5 minutes (another computer that
    # crashed, or this computer's process number now used by another program) is taken over
    return m if age < STALE_S else None


def _write(path):
    m = marker(path)
    data = dict(_me(), time=time.time(), file=os.path.basename(path))
    try:
        if os.name == "nt" and os.path.exists(m):
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(m, 0x80)     # a hidden file cannot be written over
        with open(m, "w", encoding="utf-8") as f:
            json.dump(data, f)
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(m, 0x2)
        return m
    except Exception as error:
        App.Console.PrintLog("FreeCAD: file in use marker %s: %s\n" % (m, error))   # a read-only folder: no marker
        return None


def _remove(m):
    try:
        if m and os.path.isfile(m):
            mine = None
            try:
                with open(m, encoding="utf-8") as f:
                    mine = json.load(f)
            except Exception:
                mine = None
            me = _me()
            if mine and (int(mine.get("pid", -1) or -1) != me["pid"] or str(mine.get("host", "")).lower() != me["host"].lower()):
                return          # another FreeCAD took it over meanwhile: leave it
            if os.name == "nt":
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(m, 0x80)
            os.remove(m)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: file in use marker %s: %s\n" % (m, error))


def _stamp(path):
    try:
        st = os.stat(path)
        return (os.path.normcase(os.path.abspath(path)), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _read_only(doc):
    try:
        from . import filecmds
        return filecmds.is_read_only(doc)
    except Exception:
        return False


def take(doc):
    """Marks the document's file as open here (on open and after Save / Save As)."""
    path = getattr(doc, "FileName", "") or ""
    if not path.lower().endswith(".fcstd") or not os.path.isfile(path):
        return
    _STAMP[doc.Name] = _stamp(path)
    if not enabled() or _read_only(doc):
        return
    old = _HELD.get(doc.Name)
    if old and os.path.normcase(old) != os.path.normcase(marker(path)):
        _remove(old)            # Save As: the old file is no longer open here
        _HELD.pop(doc.Name, None)
    if held_by_other(path):
        return
    m = _write(path)
    if m:
        _HELD[doc.Name] = m


def release(name):
    _STAMP.pop(name, None)
    _remove(_HELD.pop(name, None))


def release_all():
    for name in list(_HELD):
        release(name)


def _beat():
    for name, m in list(_HELD.items()):
        doc = App.listDocuments().get(name)
        if doc is None:
            release(name)
            continue
        path = getattr(doc, "FileName", "") or ""
        if path and os.path.normcase(marker(path)) == os.path.normcase(m) and not held_by_other(path):
            _write(path)


def on_opened(doc):
    """restorehook: a file another running FreeCAD has open opens read-only and says who has it."""
    path = getattr(doc, "FileName", "") or ""
    if not path.lower().endswith(".fcstd") or not os.path.isfile(path):
        return
    other = held_by_other(path) if enabled() else None
    if other:
        try:
            from . import filecmds
            filecmds.set_read_only(doc, True)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s could not be made read-only: %s\n" % (doc.Label, error))
        _STAMP[doc.Name] = _stamp(path)
        _TELL.append((os.path.basename(path), other))
        if len(_TELL) == 1:
            QtCore.QTimer.singleShot(300, _tell)
        return
    take(doc)


def in_use_text(items):
    me = _me()
    lines = []
    for name, m in items:
        if str(m.get("host", "")).lower() == me["host"].lower():
            who = "another FreeCAD window on this computer"
        else:
            who = "FreeCAD on %s (%s)" % (m.get("host", "?"), m.get("user", "?"))
        lines.append("%s is open in %s." % (name, who))
    one = len(items) == 1
    return ("\n".join(lines) + "\n\n%s opened read-only, so that Save cannot write over the other copy's work. "
            "Close %s there and open %s again to change %s, or use File > Save As to keep a copy."
            % ("It was" if one else "They were", "it" if one else "them", "it" if one else "them", "it" if one else "them"))


def _tell():
    items = list(_TELL)
    del _TELL[:]
    if not items:
        return
    text = in_use_text(items)
    App.Console.PrintWarning("FreeCAD: %s\n" % text.replace("\n", " "))
    try:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "File In Use", text)
    except Exception as _fw_err:
        _fw_log("filelock.py:tell", _fw_err)


def changed_on_disk(doc):
    """True when the document's file was written by someone else after it was opened or saved here."""
    path = getattr(doc, "FileName", "") or ""
    was = _STAMP.get(doc.Name)
    if not path or was is None or not os.path.isfile(path):
        return False
    now = _stamp(path)
    return bool(now) and now[0] == was[0] and now[1:] != was[1:]


def save_over_ok(doc):
    """Save: True to write the file; a file changed on disk after it was opened here asks first (default No)."""
    if not changed_on_disk(doc):
        return True
    name = os.path.basename(doc.FileName)
    text = ("%s was changed on disk after you opened it, by another program or another FreeCAD.\n\nSave over it "
            "with your version? No keeps the file as it is; File > Save As saves your version under a new name." % name)
    yes, no = QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.No
    if QtWidgets.QMessageBox.question(Gui.getMainWindow(), "Save", text, yes | no, no) == yes:
        return True
    return False


class _Observer:
    def slotFinishSaveDocument(self, doc, filename):
        try:
            if doc.FileName and os.path.normcase(os.path.abspath(filename)) == os.path.normcase(os.path.abspath(doc.FileName)):
                take(doc)       # a saved copy (Save as copy, recovery) is not the document's file
        except Exception as _fw_err:
            _fw_log("filelock.py:saved", _fw_err)

    def slotDeletedDocument(self, doc):
        try:
            release(doc.Name)
        except Exception as _fw_err:
            _fw_log("filelock.py:closed", _fw_err)


def install():
    if _installed:
        return
    obs = _Observer()
    App.addDocumentObserver(obs)
    from . import restorehook
    restorehook.on_restored(on_opened)
    t = QtCore.QTimer(Gui.getMainWindow())
    t.timeout.connect(_beat)
    t.start(BEAT_MS)
    import atexit
    atexit.register(release_all)
    try:
        QtWidgets.QApplication.instance().aboutToQuit.connect(release_all)
    except Exception as _fw_err:
        _fw_log("filelock.py:quit", _fw_err)
    _installed.extend([obs, t])
