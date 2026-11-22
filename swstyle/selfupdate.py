# SPDX-License-Identifier: LGPL-2.1-or-later
""







import os
import queue
import shutil
import threading
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

import fwupdate_boot as boot
from . import extupdate, paths

CHECK_EVERY = 20 * 3600        # at most about once a day at start-up
_jobs = queue.Queue()
_state = {"busy": False, "timer": None, "info": None}


# ------------------------------------------------------------------ settings
def enabled():
    return paths.params().GetBool("UpdateCheck", True)


def repo():
    return paths.params().GetString("UpdateRepo", "").strip().strip("/")


def token():
    return paths.params().GetString("UpdateToken", "").strip()


def _set(key, value):
    paths.params().SetString(key, str(value))


# ------------------------------------------------------------------ the check (worker thread: no Qt here)
def newer_info(repo_name, tok, installed, skip=""):
    """The newest version in repo_name when it is newer than installed (and not skipped), else None."""
    extupdate.TOKEN = tok
    try:
        info = extupdate.latest(repo_name)
    finally:
        extupdate.TOKEN = ""
    if not extupdate.is_newer(info["tag"], installed) or info["tag"] == skip:
        return None
    return info


def _stage(info, tok):
    """Downloads info into updates/staged and writes pending.json last, so a partial copy is never applied."""
    d = boot.updates_dir()
    os.makedirs(d, exist_ok=True)
    work = os.path.join(d, "download")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    archive = os.path.join(d, "download.zip")
    extupdate.TOKEN = tok
    try:
        extupdate._download(info["zip"], archive, "", None, extupdate.MAX_BYTES)
    finally:
        extupdate.TOKEN = ""
    try:
        import zipfile
        if not zipfile.is_zipfile(archive):
            raise extupdate.UpdateError("the download is not a zip file")
        extupdate.safe_extract(archive, work)
        root = boot.addon_root(work)
        if not root or not os.path.isdir(os.path.join(root, "swstyle")):
            raise extupdate.UpdateError("the download holds no complete copy")
        staged = os.path.join(d, "staged")
        shutil.rmtree(staged, ignore_errors=True)
        shutil.copytree(root, staged, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.lck"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
        try:
            os.remove(archive)
        except OSError:
            pass
    boot._write("pending.json", {"tag": info["tag"], "version": boot.package_version(staged), "rollback": False})


def _worker(kind, info=None):
    try:
        if extupdate.network_off():
            _jobs.put((kind, None, "update checks are off on this run"))
        elif kind == "check":
            _jobs.put((kind, newer_info(repo(), token(), boot.installed_tag(), skip_tag()), ""))
        else:
            _stage(info, token())
            _jobs.put((kind, info, ""))
    except extupdate.UpdateError as error:
        _jobs.put((kind, None, _explain(str(error))))
    except Exception as error:
        _jobs.put((kind, None, str(error)))


def _explain(text):
    if "has no release, tag or commit" in text and not token():
        text += " (a private repository needs a token: Options > General > Software updates)"
    return text


def skip_tag():
    return paths.params().GetString("UpdateSkipTag", "")


# ------------------------------------------------------------------ the notice (GUI thread)
def _parent():
    return Gui.getMainWindow() if Gui is not None else None


def _box(title, text, buttons, default=0, icon=None):
    msg = QtWidgets.QMessageBox(_parent())
    msg.setWindowTitle(title)
    msg.setText(text)
    msg.setIcon(icon or QtWidgets.QMessageBox.Information)
    made = [msg.addButton(label, role) for label, role in buttons]
    msg.setDefaultButton(made[default])
    msg.exec_()
    clicked = msg.clickedButton()
    return made.index(clicked) if clicked in made else -1


def _message(text):
    try:
        _parent().statusBar().showMessage(text, 15000)
    except Exception:
        App.Console.PrintMessage("FreeCAD: %s\n" % text)


def _poll():
    """Runs on a QTimer: takes a finished worker result and shows the next step."""
    try:
        kind, info, error = _jobs.get_nowait()
    except queue.Empty:
        return
    _state["busy"] = False
    _state["timer"].stop()
    manual = _state.get("manual", False)
    if kind == "check":
        _set("UpdateLastCheck", time.time())
        if error:
            App.Console.PrintLog("FreeCAD update check: %s\n" % error)
            if manual:
                _box("FreeCAD Update", "FreeCAD could not check for updates.\n\n%s" % error,
                     [("OK", QtWidgets.QMessageBox.AcceptRole)], icon=QtWidgets.QMessageBox.Warning)
        elif info is None:
            if manual:
                _box("FreeCAD Update", "You have the latest version of FreeCAD's interface add-on (%s)."
                     % boot.installed_tag(), [("OK", QtWidgets.QMessageBox.AcceptRole)])
        else:
            _offer(info)
    else:
        if error:
            _box("FreeCAD Update", "The update could not be downloaded.\n\n%s" % error,
                 [("OK", QtWidgets.QMessageBox.AcceptRole)], icon=QtWidgets.QMessageBox.Warning)
        else:
            _message("Update %s is ready. Restart FreeCAD to finish installing it." % info["tag"])
            _box("FreeCAD Update", "Version %s has been downloaded.\n\nIt is installed the next time FreeCAD "
                 "starts. The version you have now is kept, and Go Back to Previous Version (Options > General "
                 "> Software updates) returns to it." % info["tag"], [("OK", QtWidgets.QMessageBox.AcceptRole)])


def _offer(info):
    notes = (info.get("notes") or "").strip()
    if len(notes) > 600:
        notes = notes[:600].rstrip() + "..."
    text = ("A new version of FreeCAD's interface add-on is available.\n\nAvailable: %s\nInstalled: %s"
            % (info["tag"], boot.installed_tag() or "unknown"))
    if notes:
        text += "\n\nWhat's new:\n" + notes
    pick = _box("FreeCAD Update", text,
                [("Download Update", QtWidgets.QMessageBox.AcceptRole),
                 ("Remind Me Later", QtWidgets.QMessageBox.RejectRole),
                 ("Skip This Version", QtWidgets.QMessageBox.DestructiveRole)])
    if pick == 0:
        _message("Downloading update %s..." % info["tag"])
        _start("download", info)
    elif pick == 2:
        _set("UpdateSkipTag", info["tag"])


def _start(kind, info=None, manual=False):
    if _state["busy"]:
        return False
    _state["busy"], _state["manual"] = True, manual
    if _state["timer"] is None:
        _state["timer"] = QtCore.QTimer()
        _state["timer"].setInterval(300)
        _state["timer"].timeout.connect(_poll)
    _state["timer"].start()
    threading.Thread(target=_worker, args=(kind, info), daemon=True).start()
    return True


# ------------------------------------------------------------------ entry points
def check_now(parent=None):
    """The Check for Updates Now button: asks even when the switch is off or the version was skipped."""
    if not repo():
        _box("FreeCAD Update", "Enter the update repository (owner/name) first.",
             [("OK", QtWidgets.QMessageBox.AcceptRole)], icon=QtWidgets.QMessageBox.Warning)
        return
    _set("UpdateSkipTag", "")
    if not _start("check", manual=True):
        _message("An update check is already running.")
    else:
        _message("Checking for updates...")


def go_back(parent=None):
    """Go Back to Previous Version: stages the copy kept at the last update; applied at the next start."""
    tag = boot.previous_tag()
    if not tag:
        _box("FreeCAD Update", "There is no earlier version to go back to.",
             [("OK", QtWidgets.QMessageBox.AcceptRole)])
        return
    if _box("FreeCAD Update", "Go back to version %s? It is put back the next time FreeCAD starts." % tag,
            [("Go Back", QtWidgets.QMessageBox.AcceptRole), ("Cancel", QtWidgets.QMessageBox.RejectRole)],
            default=1, icon=QtWidgets.QMessageBox.Question) != 0:
        return
    try:
        boot.stage_rollback()
        _message("Version %s comes back when FreeCAD restarts." % tag)
    except Exception as error:
        _box("FreeCAD Update", "Going back did not work.\n\n%s" % error,
             [("OK", QtWidgets.QMessageBox.AcceptRole)], icon=QtWidgets.QMessageBox.Warning)


def _announce_applied():
    rec = boot.last_result(mark_shown=True)
    if not rec:
        return
    if rec.get("ok"):
        what = "went back to" if rec.get("rollback") else "updated to"
        _message("FreeCAD's interface add-on %s version %s." % (what, rec.get("to")))
    else:
        _box("FreeCAD Update", "The update to %s could not be installed, so your version %s stays.\n\n%s"
             % (rec.get("to"), rec.get("from"), rec.get("error")),
             [("OK", QtWidgets.QMessageBox.AcceptRole)], icon=QtWidgets.QMessageBox.Warning)


def _start_up_check():
    try:
        _announce_applied()
        if not enabled() or not repo() or extupdate.network_off():
            return
        try:
            last = float(paths.params().GetString("UpdateLastCheck", "0") or 0)
        except ValueError:
            last = 0
        if time.time() - last >= CHECK_EVERY:
            _start("check")
    except Exception as error:
        App.Console.PrintLog("FreeCAD update check: %s\n" % error)


def install():
    """From InitGui: a quiet check 20 seconds after start-up (no window opens unless there is news)."""
    if Gui is None:
        return
    QtCore.QTimer.singleShot(20000, _start_up_check)
