# SPDX-License-Identifier: LGPL-2.1-or-later
""












import json
import os
import re
import shutil
import time

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
# checked-hash bytecode (make_pycache.py) travels with the copy: Python re-validates it against the source,
# so a stale one is recompiled, never run, and another Python version ignores it
_IGNORE = shutil.ignore_patterns("*.lck")


def updates_dir():
    try:
        import FreeCAD
        base = FreeCAD.getUserAppDataDir()
    except Exception:
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "FreeCAD")
    return os.path.join(base, "FreeWorks-updates")


def _read(name, default=None):
    try:
        with open(os.path.join(updates_dir(), name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(name, data):
    d = updates_dir()
    os.makedirs(d, exist_ok=True)
    temp = os.path.join(d, name + ".new")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(temp, os.path.join(d, name))


def package_version(folder=None):
    try:
        with open(os.path.join(folder or ADDON_DIR, "package.xml"), encoding="utf-8") as f:
            m = re.search(r"<version>\s*([^<\s]+)\s*</version>", f.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def installed_tag():
    """The tag of the copy in use: what the last update recorded, else package.xml's version."""
    rec = _read("installed.json", {}) or {}
    return rec.get("tag") or package_version()


def previous_tag():
    """The tag a rollback would go back to, or '' when there is no earlier copy."""
    if os.path.isfile(os.path.join(updates_dir(), "previous", "tree", "InitGui.py")):
        return (_read("previous.json", {}) or {}).get("tag", "") or "previous"
    return ""


def addon_root(folder):
    """The folder inside an unpacked archive that holds the add-on (the one with InitGui.py)."""
    if os.path.isfile(os.path.join(folder, "InitGui.py")):
        return folder
    for here, dirs, files in os.walk(folder):
        if "InitGui.py" in files and "swstyle" in dirs:
            return here
        if here[len(folder):].count(os.sep) >= 3:
            dirs[:] = []
    return None


def _clear(folder):
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name == "__pycache__":
            continue
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def _copy_in(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_IGNORE)


def stage_rollback():
    """Makes the previous copy the pending one, for the next start. Returns its tag, or '' if there is none."""
    tag = previous_tag()
    if not tag:
        return ""
    d = updates_dir()
    shutil.rmtree(os.path.join(d, "staged"), ignore_errors=True)
    shutil.copytree(os.path.join(d, "previous", "tree"), os.path.join(d, "staged"))
    _write("pending.json", {"tag": tag, "version": package_version(os.path.join(d, "staged")), "rollback": True})
    return tag


def apply_pending():
    """At start-up: a staged update replaces this folder; any failure puts the old files back. Never raises."""
    d = updates_dir()
    pend = _read("pending.json")
    staged = os.path.join(d, "staged")
    if not pend:
        return None
    old_tag = installed_tag()
    result = {"ok": False, "from": old_tag, "to": pend.get("tag", ""), "at": time.time(),
              "rollback": bool(pend.get("rollback")), "shown": False, "error": ""}
    backup = os.path.join(d, "backup-now")
    try:
        os.remove(os.path.join(d, "pending.json"))          # one try only: a failing update must not loop
        root = addon_root(staged)
        if not root or not os.path.isdir(os.path.join(root, "swstyle")):
            raise RuntimeError("the downloaded copy is not complete")
        shutil.rmtree(backup, ignore_errors=True)
        _copy_in(ADDON_DIR, backup)
        try:
            _clear(ADDON_DIR)
            _copy_in(root, ADDON_DIR)
            if not os.path.isfile(os.path.join(ADDON_DIR, "InitGui.py")):
                raise RuntimeError("InitGui.py is missing after the copy")
        except Exception:
            _clear(ADDON_DIR)
            _copy_in(backup, ADDON_DIR)
            raise
        # the copy that was in use becomes the way back (after a rollback too: it can be rolled forward again)
        shutil.rmtree(os.path.join(d, "previous"), ignore_errors=True)
        os.makedirs(os.path.join(d, "previous"))
        os.replace(backup, os.path.join(d, "previous", "tree"))
        _write("previous.json", {"tag": old_tag})
        _write("installed.json", {"tag": pend.get("tag") or package_version()})
        result["ok"] = True
    except Exception as error:
        result["error"] = str(error)
    finally:
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(staged, ignore_errors=True)
    try:
        _write("last.json", result)
    except OSError:
        pass
    return result


def last_result(mark_shown=False):
    """The outcome of the last apply_pending() that was not shown yet, else None."""
    rec = _read("last.json")
    if not rec or rec.get("shown"):
        return None
    if mark_shown:
        rec["shown"] = True
        try:
            _write("last.json", rec)
        except OSError:
            pass
    return rec
