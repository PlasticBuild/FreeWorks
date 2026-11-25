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

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import FreeCAD as App

from . import slicer as backend

REPOS = {"orca": "OrcaSlicer/OrcaSlicer", "bambu": "bambulab/BambuStudio", "prusa": "prusa3d/PrusaSlicer"}
PREVIEW_BY_DEFAULT = ("prusa",)     # PrusaSlicer 3.0 is still a preview (alpha) release: offered unless switched off
API = "https://api.github.com/repos/%s/releases?per_page=15"
AGENT = "FreeWorks-slicer-updates"
DAY = 24 * 3600
KEEP = 2                        # unpacked releases kept per slicer (the one in use and the one before)
SKIP_WORDS = ("mac", "linux", "appimage", "ubuntu", "flatpak", "debug", "pdb", "symbol", "source", "sha256",
              "sha1", ".txt", ".sig", ".asc", ".md5", "arm64", "aarch64", ".msi", ".dmg", ".deb", ".rpm", "validator",
              "profile")


# ---------------------------------------------------------------------- versions
def version_of(text):
    """'v2.4.1' -> (2, 4, 1); 'v02.08.02.61' -> (2, 8, 2, 61); 'version_3.0.0-alpha14' -> (3, 0, 0, -2986) (an alpha, beta
    or rc counts as just before the final release); '' -> ()."""
    m = re.search(r"\d+(?:\.\d+)+", text or "")
    if not m:
        return ()
    out = tuple(int(x) for x in m.group(0).split("."))
    pre = re.search(r"(alpha|beta|rc)[._-]?(\d+)", (text or "")[m.end():], re.I)
    if pre:
        out += ({"alpha": -3000, "beta": -2000, "rc": -1000}[pre.group(1).lower()] + int(pre.group(2)),)
    return out


def newer(a, b):
    """Version tuple a is newer than b (missing parts count as 0)."""
    n = max(len(a), len(b))
    return tuple(a) + (0,) * (n - len(a)) > tuple(b) + (0,) * (n - len(b))


def same(a, b):
    n = max(len(a), len(b))
    return tuple(a) + (0,) * (n - len(a)) == tuple(b) + (0,) * (n - len(b))


def show(version):
    return ".".join(str(x) for x in version) if version else "unknown"


_VERSIONS = {}


def installed_version(slicer):
    """The version of the program the add-on uses, or () when it cannot tell: the program's file
    version (Windows), else its own --help line, else the version in its settings file."""
    exe = slicer.exe()
    if exe is None:
        return ()
    try:
        stamp = (str(exe), exe.stat().st_mtime)
    except OSError:
        return ()
    hit = _VERSIONS.get(slicer.key)
    if hit and hit[0] == stamp:
        return hit[1]
    # a copy unpacked by Slicer Updates knows its release: a preview's program only says "3.0.0", its tag says alpha 14
    tagged = version_of(installed_tag(slicer.key, exe))
    found = tagged if tagged and tagged[-1] < 0 else ()
    if not found and sys.platform == "win32":
        found = _file_version(exe)
    if not found:
        found = _help_version(slicer, exe)
    if not found:
        found = tagged
    if not found:
        try:
            data = slicer.read_conf()[0]
            found = version_of(str((data.get("app") or {}).get("version", "")))
        except Exception:
            found = ()
    _VERSIONS[slicer.key] = (stamp, found)
    return found


def installed_tag(key, exe):
    """The release tag of the copy Slicer Updates unpacked, when exe is that copy; else ''."""
    try:
        rec = json.loads(params().GetString(key + "Installed", "") or "{}")
    except ValueError:
        return ""
    return (rec.get("tag") or "") if exe is not None and rec.get("exe") == str(exe) else ""


def _file_version(exe):
    """ProductVersion of a Windows program, from its version resource."""
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.WinDLL("version", use_last_error=True)
        size = ver.GetFileVersionInfoSizeW(str(exe), None)
        if not size:
            return ()
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(exe), 0, size, buf):
            return ()
        ptr, length = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) \
                or length.value < 4:
            return ()
        lang, page = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        for name in ("ProductVersion", "FileVersion"):
            sub = "\\StringFileInfo\\%04x%04x\\%s" % (lang, page, name)
            if ver.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                v = version_of(ctypes.wstring_at(ptr.value, length.value).strip("\0"))
                if v:
                    return v
    except Exception as _fw_err:
        _fw_log("slicerupdate.py:133", _fw_err)
    return ()


def _help_version(slicer, exe):
    """The first line of --help names the version: 'OrcaSlicer-2.4.1:' / 'BambuStudio-02.08.02.61:'."""
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0
        r = subprocess.run([str(exe), "--help"], capture_output=True, timeout=30, creationflags=flags)
        text = (r.stdout + r.stderr).decode("utf-8", "replace")
    except Exception:
        return ()
    m = re.search(r"(?:Orca|Bambu|Prusa)\w*-(\d+(?:\.\d+)+)", text)
    return version_of(m.group(1)) if m else ()


# ---------------------------------------------------------------------- the release page
def _network_off():
    ""
    return os.environ.get("FREEWORKS_NO_NET", "") not in ("", "0")


def fetch_json(url, timeout=20):
    if _network_off():
        raise OSError("network is off for this run (FREEWORKS_NO_NET=1)")
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def pick_asset(assets):
    """The Windows release to download: the portable zip, else any Windows zip, else the installer. A zip or program
    whose name says no system at all (PrusaSlicer-2.9.7.zip, beside a .dmg) is the Windows one; it counts a little
    less than a file that says Windows."""
    best, score = None, 0
    for a in assets or []:
        name = (a.get("name") or "").lower()
        if not name or any(w in name for w in SKIP_WORDS):
            continue
        if name.endswith(".zip"):
            s = 30 if "portable" in name else 20
        elif name.endswith(".exe"):
            s = 10 if "portable" not in name else 25
        else:
            continue
        if not any(w in name for w in ("win", "windows")):
            s -= 5
        if s > score:
            best, score = a, s
    return best


def wants_preview(key):
    """Preview (alpha / beta) releases are offered for this slicer: PrusaSlicer's 3.0, unless the person chose stable."""
    saved = params().GetString(key + "Channel", "")
    return (saved == "preview") if saved else key in PREVIEW_BY_DEFAULT


def label(version, tag=""):
    """The version as shown: '3.0.0-alpha14' for a preview, else 2.9.7."""
    m = re.search(r"(alpha|beta|rc)[._-]?\d+", tag or "", re.I)
    if m and version:
        return re.sub(r"^\D*", "", tag).replace("_", "-")
    return show(version)


def latest(key, include_pre=None, fetch=None):
    """The newest release of a slicer: {"tag", "version", "title", "page", "notes", "asset"} where
    asset = {"name", "url", "size", "sha256"} or None; raises on a network error."""
    template = os.environ.get("SWSTYLE_RELEASE_API", API)
    if include_pre is None:
        include_pre = wants_preview(key)
    url = template % REPOS[key]
    releases = (fetch or fetch_json)(url)
    found = _newest(releases, include_pre)
    if found is None and not include_pre:
        # a long run of previews can push the finished release off the first page: GitHub's own "latest" is it
        try:
            one = (fetch or fetch_json)(url.split("?", 1)[0] + "/latest")
        except Exception:
            one = None
        found = _newest([one] if isinstance(one, dict) else [], include_pre)
    return found


def _newest(releases, include_pre):
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        tag = r.get("tag_name") or ""
        if not include_pre and (r.get("prerelease") or "nightly" in tag.lower()):
            continue
        version = version_of(tag) or version_of(r.get("name") or "")
        if not version:
            continue
        asset = pick_asset(r.get("assets"))
        out = None
        if asset:
            digest = asset.get("digest") or ""
            out = {"name": asset.get("name"), "url": asset.get("browser_download_url"),
                   "size": int(asset.get("size") or 0),
                   "sha256": digest.split(":", 1)[1].lower() if digest.lower().startswith("sha256:") else ""}
        return {"tag": tag, "version": version, "title": r.get("name") or tag, "page": r.get("html_url") or "",
                "notes": r.get("body") or "", "asset": out}
    return None


# ---------------------------------------------------------------------- state kept between runs
def params():
    return backend.params()


def apps_dir(key):
    path = Path(App.getUserAppDataDir()) / "SolidWorksStyle" / "slicer-apps" / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def status(key):
    """What the Updates box shows for one slicer, from the last look (no network)."""
    s = backend.get(key)
    have = installed_version(s)
    try:
        last = json.loads(params().GetString(key + "Latest", "") or "{}")
    except ValueError:
        last = {}
    latest_v = tuple(last.get("version") or ())
    own = s.own_exe() is not None
    return {"key": key, "title": s.title, "installed": have, "latest": latest_v, "info": last, "own": own,
            "latest_text": label(latest_v, last.get("tag") or ""),
            "installed_text": label(have, installed_tag(key, s.exe())), "preview": wants_preview(key),
            # a newer release of a copy that is in use (the count on the Slicer Updates button); a slicer that was
            # never downloaded is on offer in the box but does not count
            "update": bool(latest_v and have and newer(latest_v, have)),
            "source": s.exe_source(),

            "available": bool(latest_v and (not have or newer(latest_v, have)
                                            or (not own and os.environ.get("SWSTYLE_NO_SLICER") != "1"))),
            "checked": params().GetFloat(key + "Checked", 0.0), "exe": s.exe(),
            "can_roll_back": bool(params().GetString(key + "ExePrev", ""))}


def look(key, fetch=None):
    """Ask the release page and remember the answer. Returns the release, or raises."""
    rel = latest(key, fetch=fetch)
    params().SetFloat(key + "Checked", time.time())
    if rel is None:
        params().SetString(key + "Latest", "")
        return None
    keep = dict(rel)
    keep["version"] = list(rel["version"])
    keep["notes"] = rel["notes"][:4000]
    params().SetString(key + "Latest", json.dumps(keep))
    return rel


def look_all(fetch=None):
    """Both slicers; returns {key: release or Exception}."""
    out = {}
    for key in REPOS:
        try:
            out[key] = look(key, fetch=fetch)
        except Exception as error:
            out[key] = error
    return out


def due():
    """A daily look is due and allowed (once per slicer panel open)."""
    if not params().GetBool("CheckUpdates", True):
        return False
    last = min(params().GetFloat(k + "Checked", 0.0) for k in REPOS)
    return time.time() - last > DAY


def available_count():
    """Slicers in use that have a newer release (not the ones that were never downloaded)."""
    return sum(1 for k in REPOS if status(k)["update"])


# ---------------------------------------------------------------------- download and unpack
class Cancelled(Exception):
    pass


class NoSpace(Exception):
    pass


# dl109: a release zip needs room for itself and for what it unpacks to (the program folder is about twice the zip)
SPACE_FACTOR = 3


def megabytes(n):
    """dl109: a byte count as testers read it: 6 MB, 1.2 GB."""
    if not n:
        return "unknown size"
    mb = n / 1048576.0
    return "%.1f GB" % (mb / 1024.0) if mb >= 1024 else "%d MB" % max(1, round(mb))


def check_space(folder, size):
    """dl109: raises NoSpace when the drive of folder has less room than the download and its unpacked program need."""
    if not size:
        return
    try:
        free = shutil.disk_usage(str(folder)).free
    except OSError:
        return
    need = size * SPACE_FACTOR
    if free < need:
        raise NoSpace("not enough free disk space: %s is needed (the download and the unpacked program), %s is free "
                      "on the drive of %s. Free some space, then press Download again." % (megabytes(need), megabytes(free), folder))


def download(asset, folder, progress=None, cancel=None):
    """The asset into folder (name.part while it comes, checked, then its name). Returns the path.
    dl109: the drive's free space is checked first; a broken or short download leaves no .part behind."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.\-]", "_", asset["name"])
    target, part = folder / name, folder / (name + ".part")
    req = urllib.request.Request(asset["url"], headers={"User-Agent": AGENT})
    digest = hashlib.sha256()
    got = 0
    if _network_off():
        raise OSError("network is off for this run (FREEWORKS_NO_NET=1)")
    check_space(folder, int(asset.get("size") or 0))
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            if not asset.get("size"):
                check_space(folder, total)
            while True:
                if cancel is not None and cancel():
                    raise Cancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if progress is not None:
                    progress(got, total)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    whole = int(asset.get("size") or 0) or total
    if whole and got != whole:          # dl109: a cut connection is said as such, before the checksum
        part.unlink(missing_ok=True)
        raise RuntimeError("the download stopped at %s of %s (the connection was lost)" % (megabytes(got), megabytes(whole)))
    want = asset.get("sha256") or ""
    if want and digest.hexdigest() != want:
        part.unlink(missing_ok=True)
        raise RuntimeError("the download does not match its published checksum (%s)" % asset["name"])
    if target.exists():
        target.unlink()
    part.replace(target)
    return target


def long_path(path):
    """A Windows path that may pass 260 characters: PrusaSlicer's zip holds preset files whose full path under the
    add-on's user data comes to 276 (FreeCAD's Python does not use Windows' long path setting), so files are written,
    listed and removed through the \\\\?\\ form. Elsewhere the path as it is."""
    path = str(Path(path).resolve()) if not str(path).startswith("\\\\?\\") else str(path)
    if os.name != "nt" or path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def remove_tree(path):
    shutil.rmtree(long_path(path), ignore_errors=True)


def _top_folder(names):
    """The one folder every name of a zip sits in ('PrusaSlicer-3.0.0-alpha14/'), or ''."""
    tops = {n.replace("\\", "/").split("/", 1)[0] for n in names if n.strip("/")}
    if len(tops) != 1:
        return ""
    top = tops.pop()
    return top + "/" if all(n.replace("\\", "/").startswith(top + "/") for n in names if n.strip("/")) else ""


def unpack(zip_path, dest):
    """Unpack a release zip into dest (each name checked to stay inside it). A zip whose files all sit in one folder
    is unpacked without that folder, so the program's own files stay short of Windows' 260-character limit: the
    slicer itself reads them with ordinary paths (PrusaSlicer 3.0 copies its preset files from resources\\presets
    on its first start and stops with "Loading presets failed" when that path is too long)."""
    dest = Path(dest)
    remove_tree(dest)
    dest.mkdir(parents=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        top = _top_folder([i.filename for i in infos])
        longest = 0
        for info in infos:
            rel = info.filename.replace("\\", "/")[len(top):]
            if not rel.strip("/"):
                continue
            target = (dest / rel).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError("unsafe file name in the download: %s" % info.filename)
            longest = max(longest, len(str(target)))
            if info.is_dir():
                os.makedirs(long_path(target), exist_ok=True)
                continue
            os.makedirs(long_path(target.parent), exist_ok=True)
            with z.open(info) as src, open(long_path(target), "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            mode = (info.external_attr >> 16) & 0o777
            if mode and os.name != "nt":
                os.chmod(target, mode)
    if os.name == "nt" and longest >= 250:
        _fw_log("slicerupdate.py:unpack", "longest path %d characters: %s" % (longest, dest))
    return longest


def short_name(tag):
    """The folder name of a release: 'version_3.0.0-alpha14' -> '3.0.0-alpha14', 'v2.3.1' -> '2.3.1'."""
    return re.sub(r"[^\w.\-]", "_", re.sub(r"^(version_|v(?=\d))", "", tag or "", flags=re.I))


def find_exe(slicer, folder):
    """The slicer's program inside an unpacked release: the shallowest file with its name."""
    names = {n.lower() + ".exe" for n in slicer.exe_names} | {n.lower() for n in slicer.exe_names}
    hits = []
    for top, _dirs, files in os.walk(long_path(folder)):
        hits += [os.path.join(top, f) for f in files if f.lower() in names]
    hits = [Path(h[4:] if h.startswith("\\\\?\\") and not h.startswith("\\\\?\\UNC") else h) for h in hits]
    hits.sort(key=lambda p: len(p.parts))
    return hits[0] if hits else None


def install(key, path, release):
    """Use a downloaded release. A zip is unpacked under slicer-apps and the add-on pointed at it:
    returns {"mode": "unpacked", "exe": path}. An installer is left for the person to run:
    {"mode": "installer", "path": path}."""
    s = backend.get(key)
    path = Path(path)
    if path.suffix.lower() != ".zip":
        return {"mode": "installer", "path": str(path)}
    dest = apps_dir(key) / (short_name(release["tag"]) or short_name(show(release["version"])))
    longest = unpack(path, dest)
    exe = find_exe(s, dest)
    if exe is None:
        remove_tree(dest)
        raise RuntimeError("the download holds no %s program" % s.title)
    try:
        path.unlink()           # dl109: the zip is not kept once unpacked (hundreds of MB per release)
    except OSError as _fw_err:
        _fw_log("slicerupdate.py:install", _fw_err)
    before = params().GetString(key + "Exe", "")
    now = str(s.exe() or "")
    params().SetString(key + "ExePrev", before or now)
    params().SetString(key + "Exe", str(exe))
    params().SetString(key + "Installed", json.dumps({"tag": release["tag"], "exe": str(exe), "when": time.time()}))
    _VERSIONS.pop(key, None)
    prune(key)
    return {"mode": "unpacked", "exe": str(exe), "longest_path": longest, "folder": str(dest)}


def roll_back(key):
    """Point the add-on at the copy it used before the last update."""
    prev = params().GetString(key + "ExePrev", "")
    if not prev or not Path(prev).is_file():
        return False
    params().SetString(key + "ExePrev", params().GetString(key + "Exe", ""))
    params().SetString(key + "Exe", prev)
    _VERSIONS.pop(key, None)
    return True


def prune(key):
    """Keep the copy in use, the one before and the newest KEEP; delete older unpacked releases."""
    used = {params().GetString(key + "Exe", ""), params().GetString(key + "ExePrev", "")}
    folders = sorted((p for p in apps_dir(key).iterdir() if p.is_dir() and p.name != "downloads"), key=lambda p: p.stat().st_mtime, reverse=True)
    for i, folder in enumerate(folders):
        if i < KEEP:
            continue
        if any(u and Path(u).is_relative_to(folder) for u in used):
            continue
        remove_tree(folder)


# ---------------------------------------------------------------------- the fast engine
def engine_current(key):
    """The fast engine was built for the version of the program in use (or nothing says otherwise)."""
    s = backend.get(key)
    have = installed_version(s)
    if not have or key not in backend.ENGINES:        # PrusaSlicer has no fast engine
        return True
    built = params().GetString(key + "EngineFor", "")
    if not built:
        # the engine on the PC was built for the program that was installed then
        params().SetString(key + "EngineFor", show(have))
        return True
    return same(version_of(built), have)


def engine_rebuilt(key, version_text=None):
    """The engine was rebuilt for the installed program (or the given version)."""
    have = version_text or show(installed_version(backend.get(key)))
    params().SetString(key + "EngineFor", have)


def engine_build_script(key):
    """The build job's .cmd for this slicer on this PC, or None."""
    for base in _homes():
        name = "slicer-engine" if key == "orca" else "slicer-engine-bambu"
        cmd = base / name / "engine" / ("run_build.cmd" if key == "orca" else "run_build_bambu.cmd")
        if cmd.is_file():
            return cmd
    return None


def engine_build_state(key):
    """(state, current step) of the engine build job on this PC, from its status.json, or None."""
    for base in _homes():
        name = "slicer-engine" if key == "orca" else "slicer-engine-bambu"
        f = base / name / "status.json"
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                return d.get("state"), d.get("current")
            except ValueError as _fw_err:
                _fw_log("slicerupdate.py:421", _fw_err)
    return None


def rebuild_engine(key):
    """Start the engine build for the installed version in the background (Windows, the build job's own
    script). Returns (ok, text)."""
    script = engine_build_script(key)
    if script is None:
        return False, "The engine build files are not on this PC."
    ver = installed_version(backend.get(key))
    if not ver:
        return False, "The installed version is not known."
    args = ["cmd", "/c", str(script), "--slicer", key, "--version", ".".join(str(n) for n in ver)]
    subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True, "Rebuilding the fast engine for %s in the background. Slicing uses the program meanwhile." % show(ver)


def _homes():
    out = []
    env = os.environ.get("SWSTYLE_HOME")
    if env:
        out.append(Path(env))
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "slicer-engine").is_dir() or (p / "slicer-engine-bambu").is_dir():
            out.append(p)
            break
    return out


# ---------------------------------------------------------------------- the box
def _qt():
    from PySide import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def _bridge_class():
    QtCore, _, _ = _qt()

    class Bridge(QtCore.QObject):
        done = QtCore.Signal(object)
        progress = QtCore.Signal(object, object)      # dl109: byte counts past 2 GB
    return Bridge


class UpdateDialog:
    """Built on first use (Qt is imported late)."""

    def __new__(cls, parent=None):
        QtCore, QtGui, QtWidgets = _qt()

        class Dialog(QtWidgets.QDialog):
            def __init__(self, parent=None):
                super().__init__(parent or _main())
                self.setWindowTitle("Slicer Updates")
                self.setMinimumWidth(560)
                self.rows = {}
                self.busy = None
                self._cancel = False
                lay = QtWidgets.QVBoxLayout(self)
                self.note = QtWidgets.QLabel(
                    "Orca Slicer, Bambu Studio and PrusaSlicer are not part of this add-on: each one is downloaded here from "
                    "its release page into the add-on's own folder and kept up to date from here. An installed copy "
                    "on this computer is left as it is.")
                self.note.setWordWrap(True)
                lay.addWidget(self.note)
                for key in REPOS:
                    box = QtWidgets.QGroupBox(backend.get(key).title)
                    box.setObjectName("SWStyle_SlicerUpdate_" + key)
                    g = QtWidgets.QGridLayout(box)
                    have = QtWidgets.QLabel()
                    new = QtWidgets.QLabel()
                    fast = QtWidgets.QLabel()
                    fast.setWordWrap(True)
                    bar = QtWidgets.QProgressBar()
                    bar.setVisible(False)
                    update = QtWidgets.QPushButton("Update")
                    update.setObjectName("SWStyle_SlicerUpdateGo_" + key)
                    update.clicked.connect(lambda _=False, k=key: self.update(k))
                    notes = QtWidgets.QPushButton("What's New")
                    notes.clicked.connect(lambda _=False, k=key: self.notes(k))
                    rebuild = QtWidgets.QPushButton("Rebuild Fast Engine")
                    rebuild.clicked.connect(lambda _=False, k=key: self.rebuild(k))
                    rebuild.setVisible(False)
                    back = QtWidgets.QPushButton("Roll Back")
                    back.clicked.connect(lambda _=False, k=key: self.back(k))
                    g.addWidget(QtWidgets.QLabel("Installed"), 0, 0)
                    g.addWidget(have, 0, 1)
                    g.addWidget(QtWidgets.QLabel("Latest"), 1, 0)
                    g.addWidget(new, 1, 1)
                    g.addWidget(fast, 2, 0, 1, 3)
                    g.addWidget(bar, 3, 0, 1, 3)
                    row = QtWidgets.QHBoxLayout()
                    if key in PREVIEW_BY_DEFAULT:
                        pre = QtWidgets.QCheckBox("Preview releases (3.0 alpha)")
                        pre.setObjectName("SWStyle_SlicerUpdatePreview_" + key)
                        pre.setToolTip("On: the newest release, previews included. Off: the newest finished release only.")
                        pre.setChecked(wants_preview(key))
                        pre.toggled.connect(lambda on, k=key: self.channel(k, on))
                        row.addWidget(pre)
                    shared = QtWidgets.QCheckBox("Use my installed slicer's settings")
                    shared.setObjectName("SWStyle_SlicerUpdateShared_" + key)
                    shared.setToolTip("Off: the add-on's copy keeps its settings, presets and sign-in in a folder of "
                                      "its own, so a copy installed on this computer is never touched.\nOn: it uses "
                                      "the installed slicer's folder (its printers, presets and sign-in).")
                    shared.setChecked(params().GetBool(key + "SharedSettings", False))
                    shared.toggled.connect(lambda on, k=key: self.shared(k, on))
                    row.addWidget(shared)
                    row.addStretch(1)
                    row.addWidget(notes)
                    row.addWidget(rebuild)
                    row.addWidget(back)
                    row.addWidget(update)
                    g.addLayout(row, 4, 0, 1, 3)
                    g.setColumnStretch(1, 1)
                    lay.addWidget(box)
                    self.rows[key] = dict(have=have, new=new, fast=fast, bar=bar, update=update, notes=notes,
                                          back=back, rebuild=rebuild, shared=shared)
                self.status = QtWidgets.QLabel()
                self.status.setWordWrap(True)
                lay.addWidget(self.status)
                buttons = QtWidgets.QHBoxLayout()
                self.check_button = QtWidgets.QPushButton("Check Now")
                self.check_button.setObjectName("SWStyle_SlicerUpdateCheck")
                self.check_button.clicked.connect(self.check)
                close = QtWidgets.QPushButton("Close")
                close.clicked.connect(self.close)
                buttons.addWidget(self.check_button)
                buttons.addStretch(1)
                buttons.addWidget(close)
                lay.addLayout(buttons)
                self.refresh()

            # ------------------------------------------------------------ what shows
            def refresh(self):
                for key, r in self.rows.items():
                    built = engine_build_state(key)
                    if built == ("done", "smoke") and not engine_current(key):
                        engine_rebuilt(key)          # the build job finished its last step for the installed version
                    st = status(key)
                    if not st["exe"]:
                        r["have"].setText("not downloaded")
                    elif st["own"]:
                        r["have"].setText(st["installed_text"])
                    else:
                        r["have"].setText("%s  (installed on this computer; FreeCAD has no copy of its own)"
                                          % show(st["installed"]))
                    if st["latest"]:
                        note = ("version unknown" if st["exe"] and not st["installed"] else
                                "newer" if st["update"] else "" if st["available"] else "up to date")
                        r["new"].setText(st["latest_text"] + ("   (%s)" % note if note else ""))
                    else:
                        r["new"].setText("not looked up yet" if not st["checked"] else "no release found")
                    asset = (st["info"] or {}).get("asset")
                    r["update"].setVisible(bool(st["available"] and asset) or self.busy == key)     # nothing to download: no button
                    r["update"].setEnabled(self.busy is None or self.busy == key)
                    size = " (%s)" % megabytes(asset.get("size")) if asset and asset.get("size") else ""
                    r["update"].setText("Cancel" if self.busy == key else
                                        ("Download %s%s" if not st["own"] else "Update to %s%s") % (st["latest_text"], size)
                                        if st["available"] else "Update")       # dl109: the size, and Cancel while it comes
                    r["notes"].setVisible(bool((st["info"] or {}).get("page")))
                    r["shared"].setVisible(bool(st["own"]))      # only the add-on's own copy has the choice
                    r["back"].setVisible(bool(st["can_roll_back"]))
                    r["back"].setEnabled(self.busy is None)
                    if st["exe"] and not engine_current(key):
                        r["fast"].setText("The fast engine is for %s: slicing goes through the program until it "
                                          "is rebuilt." % params().GetString(key + "EngineFor", "an older version"))
                        r["fast"].setVisible(True)
                        r["rebuild"].setVisible(sys.platform == "win32" and engine_build_script(key) is not None)
                    else:
                        r["rebuild"].setVisible(False)
                        r["fast"].setVisible(False)
                self.check_button.setEnabled(self.busy is None)

            def rebuild(self, key):
                ok, text = rebuild_engine(key)
                self.say(text)

            def shared(self, key, on):
                backend.get(key).set_shared_settings(on)
                self.say("%s uses %s from its next start." % (backend.get(key).title, "the installed slicer's "
                                                                  "settings folder" if on else "a settings folder of its own"))

            def channel(self, key, preview):
                """Preview or finished releases only: kept, and the release page is looked at again."""
                params().SetString(key + "Channel", "preview" if preview else "stable")
                params().SetString(key + "Latest", "")
                self.refresh()
                if self.busy is None:
                    self.check()

            def say(self, text):
                self.status.setText(text)

            # ------------------------------------------------------------ actions
            def check(self):
                self.busy = "check"
                self.check_button.setEnabled(False)
                self.say("Looking at the release pages...")
                bridge = _bridge_class()()
                bridge.done.connect(self._checked)
                self._bridge = bridge

                def run():
                    bridge.done.emit(look_all())
                threading.Thread(target=run, daemon=True).start()

            def _checked(self, result):
                self.busy = None
                errors = [str(v) for v in result.values() if isinstance(v, Exception)]
                self.say("Could not reach the release pages (is there a network connection?). Nothing was changed; "
                         "try again later." if errors else
                         "%d update%s available." % (available_count(), "" if available_count() == 1 else "s")
                         if available_count() else
                         "Download adds a slicer; the ones in use are up to date."
                         if any(status(k)["available"] for k in REPOS) else "Every slicer is up to date.")
                self.refresh()

            def update(self, key):
                if self.busy == key:            # dl109: the row's button reads Cancel while it downloads
                    self._cancel = True
                    self.say("Cancelling...")
                    return
                st = status(key)
                asset = (st["info"] or {}).get("asset")
                if not asset:
                    return
                if st["exe"] and not st["installed"]:
                    answer = QtWidgets.QMessageBox.question(
                        self, "Unknown Installed Version",
                        "The existing %s installation has an unknown version. Replace it with %s?"
                        % (st["title"], st["latest_text"]),
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                        QtWidgets.QMessageBox.No)
                    if answer != QtWidgets.QMessageBox.Yes:
                        return
                self.busy = key
                self._cancel = False
                self._first = not st["own"]
                self._asset = asset
                r = self.rows[key]
                r["bar"].setVisible(True)
                r["bar"].setRange(0, 0)
                self.say("Downloading %s..." % asset["name"])
                self.refresh()
                bridge = _bridge_class()()
                bridge.done.connect(lambda result, k=key: self._updated(k, result))
                bridge.progress.connect(lambda got, total, k=key: self._progress(k, got, total))
                self._bridge = bridge
                info = dict(st["info"])
                info["version"] = tuple(info.get("version") or ())

                def run():
                    try:
                        path = download(asset, apps_dir(key) / "downloads",
                                        progress=lambda g, t: bridge.progress.emit(g, t),
                                        cancel=lambda: self._cancel)
                        bridge.done.emit(install(key, path, info))
                    except Exception as error:
                        bridge.done.emit(error)
                threading.Thread(target=run, daemon=True).start()

            def _progress(self, key, got, total):
                bar = self.rows[key]["bar"]
                if total:
                    bar.setRange(0, 100)
                    bar.setValue(int(100.0 * got / total))
                if not self._cancel:        # dl109: how far it is, in MB
                    self.say("Downloading %s: %s of %s" % (self._asset.get("name", ""), megabytes(got), megabytes(total)))

            def _updated(self, key, result):
                self.busy = None
                self.rows[key]["bar"].setVisible(False)
                what = "Download" if getattr(self, "_first", False) else "Update"
                if isinstance(result, Cancelled):
                    self.say("%s cancelled. Nothing was kept; press %s to start again." % (what, what))
                elif isinstance(result, NoSpace):
                    self.say("<span style='color:#c00000'>%s not started: %s</span>" % (what, result))
                elif isinstance(result, Exception):
                    self.say("<span style='color:#c00000'>%s failed: %s. Nothing was changed; press %s to try "
                             "again.</span>" % (what, result, what))
                elif result["mode"] == "installer":
                    try:
                        os.startfile(result["path"])
                    except Exception as _fw_err:
                        _fw_log("slicerupdate.py:659", _fw_err)
                    self.say("Only an installer was published: it is open now. Run it, then press Check Now.")
                else:
                    self.say(("%s is ready (in %s). Slicing uses it from now on." if getattr(self, "_first", False) else
                              "%s updated (in %s). Slicing uses it from now on; roll back here if you need the old "
                              "one.") % (backend.get(key).title, result.get("folder", "")))
                    _tell_panel(key)
                self.refresh()

            def notes(self, key):
                page = (status(key)["info"] or {}).get("page")
                if page:
                    QtGui.QDesktopServices.openUrl(QtCore.QUrl(page))

            def back(self, key):
                self.say("%s is back on the version it used before." % backend.get(key).title
                         if roll_back(key) else "There is nothing to roll back to.")
                _tell_panel(key)
                self.refresh()

            def closeEvent(self, event):
                self._cancel = True
                super().closeEvent(event)

        return Dialog(parent)


def _tell_panel(key):
    """chain119: an open 3D Slicer panel of this slicer takes the new copy at once (its presets, no "not on this
    computer yet"), however Slicer Updates was opened (Slice's download offer, the tab's button, the panel's own)."""
    try:
        from . import slicerui
        panel = slicerui.SlicerPanel.current
        if panel is not None and getattr(panel, "key", None) == key:
            panel._slicer_arrived()
    except Exception as _fw_err:
        _fw_log("slicerupdate.py:tell_panel", _fw_err)


def _main():
    import FreeCADGui as Gui
    return Gui.getMainWindow()


def open_box(parent=None):
    box = UpdateDialog(parent)
    box.show()
    if due() or not any(status(k)["checked"] for k in REPOS):
        box.check()
    return box


# ---------------------------------------------------------------------- the daily look
def background_look(on_done=None):
    """When a slicer panel opens: one look at the release pages if a day has passed. Silent."""
    if not due():
        return None

    def run():
        look_all()
        if on_done is not None:
            try:
                on_done()
            except Exception as _fw_err:
                _fw_log("slicerupdate.py:708", _fw_err)
    t = threading.Thread(target=run, name="swstyle-slicer-updates", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------- command
class UpdateCommand:
    def GetResources(self):
        n = available_count()
        return {"MenuText": "Slicer Updates" + (" (%d)" % n if n else ""), "Pixmap": str(
                    Path(__file__).resolve().parent / "resources" / "slicer" / "update.svg"),
                "ToolTip": "Downloads Orca Slicer, Bambu Studio and PrusaSlicer from their release pages and updates "
                           "them. Roll Back returns to the version before."}

    def Activated(self):
        open_box()

    def IsActive(self):
        return True


COMMANDS = (("SWStyle_SlicerUpdate", UpdateCommand),)

BUTTONS = (
    ("SlicerUpdate", "Slicer Updates", "SWStyle_SlicerUpdate",
     "Downloads Orca Slicer, Bambu Studio or PrusaSlicer from their release pages, or updates them.",
     "Slicer\nUpdates", "update"),
)
