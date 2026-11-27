# SPDX-License-Identifier: LGPL-2.1-or-later
""







import json
import os
import subprocess
import sys
import tempfile
import time

import FreeCAD as App

from . import params, warn

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "swhelper.py")
_python = None          # cached: path, or "" when none was found


def on_windows():
    return sys.platform == "win32"


def solidworks_installed():
    ""
    if not on_windows():
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID"))
        return True
    except OSError:
        return False


def use_solidworks():
    ""
    return params().GetBool("UseSolidWorks", True) and solidworks_installed()


def _flags():
    return 0x08000000 if on_windows() else 0      # CREATE_NO_WINDOW


def _can_drive(python):
    try:
        r = subprocess.run([python, "-I", "-c", "import win32com.client, pythoncom"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60,
                           creationflags=_flags())
        return r.returncode == 0
    except Exception:
        return False


def helper_env():
    ""
    return os.environ.get("FREEWORKS_HELPER_ENV") or os.path.join(App.getUserAppDataDir(), "FreeWorks",
                                                                   "swpython")


def _base_python():
    home = App.getHomePath()
    for p in (os.path.join(home, "bin", "python.exe"), os.path.join(home, "python.exe")):
        if os.path.isfile(p):
            return p
    return None


def candidates():
    out = []
    own = params().GetString("ComPython", "") or os.environ.get("FREEWORKS_COM_PYTHON", "")
    if own:
        out.append(own)
    out.append(os.path.join(helper_env(), "Scripts", "python.exe"))
    home = App.getHomePath()
    for p in (os.path.join(home, "bin", "python.exe"), os.path.join(home, "python.exe")):
        out.append(p)
    if os.path.basename(sys.executable).lower().startswith("python"):
        out.append(sys.executable)
    for d in os.environ.get("PATH", "").split(os.pathsep):
        out.append(os.path.join(d, "python.exe"))
    seen, keep = set(), []
    for p in out:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen and os.path.isfile(p):
            seen.add(k)
            keep.append(p)
    return keep


def setup_helper_python(ask=True):
    ""

    base = _base_python()
    if base is None:
        return None
    if ask and App.GuiUp:
        from PySide import QtGui
        box = QtGui.QMessageBox.question(
            None, "FreeCAD",
            "To open and save SolidWorks files, FreeCAD talks to SolidWorks through a small helper "
            "(pywin32, about 10 MB, downloaded once from the Python Package Index).\n\nSet it up now?",
            QtGui.QMessageBox.Yes | QtGui.QMessageBox.No, QtGui.QMessageBox.Yes)
        if box != QtGui.QMessageBox.Yes:
            return None
    env = helper_env()
    python = os.path.join(env, "Scripts", "python.exe")
    try:
        if not os.path.isfile(python):
            os.makedirs(os.path.dirname(env), exist_ok=True)
            subprocess.run([base, "-I", "-m", "venv", env], check=True, timeout=600,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=_flags())
        r = subprocess.run([python, "-I", "-m", "pip", "install", "--disable-pip-version-check", "pywin32"],
                           timeout=900, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           creationflags=_flags())
        if r.returncode != 0:
            warn("setting up the SolidWorks helper failed:\n%s" % r.stdout.decode(errors="replace")[-2000:])
            return None
    except Exception as exc:
        warn("setting up the helper failed: %s" % exc)
        return None
    return python if _can_drive(python) else None


def com_python():
    ""
    global _python
    if _python is None:
        _python = next((p for p in candidates() if _can_drive(p)), "")
        if not _python and on_windows() and solidworks_installed():
            _python = setup_helper_python() or ""
        if not _python:
            warn("no Python with pywin32 found to drive SolidWorks; set one in "
                 "Mod/FreeWorks/SolidWorksFiles ComPython, or run: python -m pip install pywin32")
    return _python or None


class HelperError(RuntimeError):
    pass


def run(command, args, label="Working with the other CAD program...", timeout=900):
    """Runs `swhelper.py command args...` and returns its JSON result. Shows a progress box
    with Cancel in the GUI. Raises HelperError with the helper's message on failure."""
    python = com_python()
    if not python:
        raise HelperError("No Python that can drive SolidWorks was found (pywin32 is needed).")
    fd, out = tempfile.mkstemp(prefix="fw-sw-", suffix=".json")
    os.close(fd)
    os.remove(out)
    cmd = [python, "-I", HELPER, command, out] + [str(a) for a in args]
    log = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=_flags())
    cancelled = _wait(proc, label, timeout)
    log.seek(0)
    text = log.read()
    log.close()
    keep = os.environ.get("FW_HELPER_LOGS")     # tests: keep every helper's output
    if keep:
        try:
            os.makedirs(keep, exist_ok=True)
            name = "%s-%s.log" % (time.strftime("%H%M%S"), command)
            with open(os.path.join(keep, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:
            pass
    if cancelled:
        raise HelperError("Cancelled.")
    result = None
    if os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as fh:
                result = json.load(fh)
        finally:
            os.remove(out)
    if result is None or not result.get("ok"):
        why = (result or {}).get("error") or (text.strip().splitlines() or ["no answer from the other CAD program"])[-1]
        App.Console.PrintLog("FreeCAD swhelper %s:\n%s\n" % (command, text))
        raise HelperError(why)
    return result


def _wait(proc, label, timeout):
    """Waits for the helper; True when the user cancelled or it timed out."""
    start = time.time()
    dialog = None
    if App.GuiUp:
        from PySide import QtCore, QtGui
        import FreeCADGui as Gui
        dialog = QtGui.QProgressDialog(label, "Cancel", 0, 0, Gui.getMainWindow())
        dialog.setWindowTitle("SolidWorks")
        dialog.setWindowModality(QtCore.Qt.WindowModal)
        dialog.setMinimumDuration(400)
    try:
        while proc.poll() is None:
            if dialog is not None:
                from PySide import QtGui
                QtGui.QApplication.processEvents()
                if dialog.wasCanceled():
                    proc.kill()
                    return True
            if time.time() - start > timeout:
                proc.kill()
                warn("The other CAD program did not answer within %d s" % timeout)
                return True
            time.sleep(0.05)
    finally:
        if dialog is not None:
            dialog.close()
    return False
