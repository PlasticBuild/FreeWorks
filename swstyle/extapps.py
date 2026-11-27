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

import functools
import http.server
import os
import socketserver
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

from . import extupdate, paths

HERE = Path(__file__).resolve().parent / "resources" / "extapps"
CHECK_EVERY = 24 * 3600
FIRST_CHECK_MS = 25000

APPS = {
    "ScanRuler": {"repo": "CNCKitchen/ScanRuler", "url": "https://scanruler.com/", "mode": "web",
                  "tip": "Inspects a 3D scan against its CAD part, fits spheres, cylinders and planes, maps wall "
                         "thickness and models the scan into a solid. By CNC Kitchen (AGPL).",
                  "download": r"(?!)"},
    "Diotopo": {"repo": "Diotopo/diotopo", "mode": "local",
                "tip": "Free topology optimization for 3D printing, by Diotopo. Optional: not part of this "
                       "download; get it from Tools > Add-Ins. Kept up to date once downloaded.",
                "download": r"(browser.*\.zip$|portable.*\.zip$|\.zip$)"},
}
ORDER_AFTER = "Add-Ins"


def _p():
    return paths.params()


def _icon(name):
    return str(HERE / (name + ".svg"))


def _root():
    return os.path.join(App.getUserAppDataDir(), "FreeWorks", "apps")


# ---------------------------------------------------------------- settings
def tab_on(app):
    return _p().GetBool("ExtApp" + app + "Tab", True)


def installed(app):
    """True for an app that needs no download (ScanRuler) or whose download is in the add-on's folder (Diotopo)."""
    return APPS[app]["mode"] != "local" or extupdate.current(_root(), APPS[app]["repo"]) is not None


def ask_download(app):
    """Diotopo is not part of this download: say what it is and fetch it only on Yes. Returns True when a download started."""
    if installed(app):
        return False
    if app in _busy:        # extapps136: it is downloading: no second question
        _status("%s: %s is already in progress" % (app, "the download" if app in _downloading else "the check"))
        return False
    box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, app,
                                # extapps163: Add-Ins buttons, no tabs of their own
                                "%s is a separate program by its author and is not part of this download.\n\n"
                                "Download it now from the author's GitHub? It is kept in this add-on's own folder "
                                "and kept up to date; Tools > Add-Ins switches its Add-Ins button off." % app,
                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, Gui.getMainWindow())
    box.setDefaultButton(QtWidgets.QMessageBox.No)
    if box.exec() != QtWidgets.QMessageBox.Yes:
        return False
    _status("%s: downloading it from the author's GitHub, it opens when done" % app)
    _open_when_installed.add(app)
    _downloading.add(app)
    _show_progress(app)
    check(app, install=True)
    if app not in _busy:            # a check already running for it: the box has nothing to show
        _close_progress(app)
    return True


def update_now(app):
    if installed(app):
        check(app, install=True, quiet=False)
    else:
        ask_download(app)


def set_tab_on(app, on):
    _p().SetBool("ExtApp" + app + "Tab", bool(on))
    QtCore.QTimer.singleShot(0, apply_tabs)


def auto_update():
    return _p().GetBool("ExtAppAutoUpdate", True)


def set_auto_update(on):
    _p().SetBool("ExtAppAutoUpdate", bool(on))


def _seen(app):
    return _p().GetString("ExtApp" + app + "Seen", "")


# ---------------------------------------------------------------- updates (worker thread -> GUI)
class _Bridge(QtCore.QObject):
    done = QtCore.Signal(str, object, object)      # app, result, error text
    progress = QtCore.Signal(str, int, int)


_bridge = None
_busy = set()
_quiet_now = set()          # apps whose running check started quietly (start-up): its failure stays in the log
_quitting = []              # set at aboutToQuit: a check that ends later says nothing (extapps/67)
_downloading = set()        # extapps136: apps whose first download the person asked for (its failure says "download", not "update check")
_cancelled = set()          # extapps136: a download the person cancelled
_dialogs = {}               # extapps136: the progress box of a download, with its Cancel button


def _show_progress(app):
    """extapps136: a download shows a box with its progress and a Cancel button (it was only a status-bar line)."""
    try:
        box = QtWidgets.QProgressDialog("Downloading %s from the author's GitHub..." % app, "Cancel", 0, 0, Gui.getMainWindow())
        box.setWindowTitle(app)
        box.setWindowModality(QtCore.Qt.NonModal)
        box.setMinimumDuration(0)
        box.setAutoClose(False)
        box.setAutoReset(False)
        box.canceled.connect(lambda a=app: _cancel(a))
        box.show()
        _dialogs[app] = box
    except Exception as _fw_err:
        _fw_log("extapps.py:136a", _fw_err)


def _close_progress(app):
    box = _dialogs.pop(app, None)
    if box is not None:
        try:
            box.canceled.disconnect()
            box.close()
            box.deleteLater()
        except Exception as _fw_err:
            _fw_log("extapps.py:136b", _fw_err)


def _cancel(app):
    """Stops a download: the worker sees it at its next block, the partial copy is removed, nothing is installed."""
    _cancelled.add(app)
    _status("%s: canceling the download" % app)


def _emit(app, result, error):
    if _quitting:
        return
    try:
        _bridge.done.emit(app, result, error)
    except RuntimeError:        # the bridge is gone: FreeCAD is closing
        return


def _status(text, ms=6000, bar=True):
    if bar:
        try:
            Gui.getMainWindow().statusBar().showMessage(text, ms)
        except Exception as _fw_err:
            _fw_log("extapps.py:118", _fw_err)
    App.Console.PrintLog("FreeCAD add-in apps: %s\n" % text)


OFFLINE_MARKS = ("certificate_verify_failed", "urlopen error", "getaddrinfo", "name or service not known",
                 "timed out", "network is unreachable", "no route to host", "connection refused",
                 "connection reset", "temporary failure in name resolution", "nodename nor servname",
                 "remote end closed", "ssl", "proxy")


def plain_error(error):
    """An update check's error in plain words: offline, certificate and DNS failures read as no connection."""
    s = str(error or "")
    low = s.lower()
    if any(m in low for m in OFFLINE_MARKS):
        return "no connection to GitHub"
    if "403" in low or "rate limit" in low:
        return "GitHub is limiting requests, try again later"
    if "404" in low:
        return "the release page was not found"
    return s.splitlines()[0][:120] if s else "unknown error"


def _progressed(app, done, total):
    _status("%s: downloading %d%s" % (app, done * 100 // total if total else done >> 20, "%" if total else " MB"), 2000)
    box = _dialogs.get(app)
    if box is not None:
        try:
            if total:
                box.setMaximum(100)
                box.setValue(min(99, done * 100 // total))
            box.setLabelText("Downloading %s from the author's GitHub... %d %s" % (
                app, done * 100 // total if total else done >> 20, "%" if total else "MB"))
        except Exception as _fw_err:
            _fw_log("extapps.py:136c", _fw_err)


def check(app, install=None, quiet=False):
    """Reads the releases page in the background. install=True also installs a newer copy of a local app;
    None follows the automatic-update option. Calls back on the GUI thread."""
    global _bridge
    if app in _busy:
        if not quiet:
            _status("%s: %s is already in progress" % (app, "the download" if app in _downloading else "the check"))
        return
    spec = APPS[app]
    if _bridge is None:
        _bridge = _Bridge()
        _bridge.done.connect(_checked)
        QtCore.QCoreApplication.instance().aboutToQuit.connect(lambda: _quitting.append(1))
        _bridge.progress.connect(_progressed)
    _busy.add(app)
    if quiet:
        _quiet_now.add(app)
    else:
        _quiet_now.discard(app)
    want_install = (spec["mode"] == "local") if install is None else install
    quiet_flag = quiet

    def work():
        try:
            info = extupdate.latest(spec["repo"])
            result = {"info": info, "installed": None, "quiet": quiet_flag}
            have = extupdate.current(_root(), spec["repo"])
            result["had"] = have[0] if have else None
            if want_install and (have is None or extupdate.is_newer(info["tag"], have[0])):
                asset = extupdate.pick_asset(info, [spec["download"]]) if info["kind"] == "release" else None
                folder = extupdate.install(_root(), spec["repo"], info, asset,
                                           progress=lambda d, t: _progress_tick(app, d, t))
                result["installed"] = folder
            _emit(app, result, "")
        except Exception as error:      # network down, GitHub limit, bad archive: said once, never fatal
            _emit(app, None, str(error))

    threading.Thread(target=work, name="FreeWorks-%s-update" % app, daemon=True).start()


def _progress_tick(app, done, total):
    if app in _cancelled:
        raise extupdate.UpdateError("cancelled")        # extapps136: the worker stops at the next block
    if not _quitting:
        _bridge.progress.emit(app, done, total)


def _checked(app, result, error):
    _busy.discard(app)
    _close_progress(app)
    was_cancelled = app in _cancelled
    _cancelled.discard(app)
    first = app in _downloading
    _downloading.discard(app)
    _p().SetFloat("ExtApp" + app + "Checked", time.time())
    if error and (was_cancelled or (first and error)):
        # extapps136: the person's own download: cancelled, or failed (with the way to try again), not "update check failed"
        _open_when_installed.discard(app)
        _quiet_now.discard(app)
        if was_cancelled:
            _status("%s: the download was canceled, nothing was installed" % app, 8000)
        else:
            _status("%s: the download failed (%s). Choose Download %s in Tools > Add-Ins to try again." % (app, plain_error(error), app), 12000)
            _tell_failed(app, plain_error(error))       # extapps161: not only a status line that goes after 12 s
        App.Console.PrintLog("FreeCAD add-in apps: %s download error: %s\n" % (app, error))
        _notify(app, "error", plain_error(error))
        return
    if error:
        _open_when_installed.discard(app)
        quiet = bool(result and result.get("quiet")) or app in _quiet_now
        _quiet_now.discard(app)
        _status("%s: update check failed (%s)" % (app, plain_error(error)), bar=not quiet)
        App.Console.PrintLog("FreeCAD add-in apps: %s check error: %s\n" % (app, error))
        _notify(app, "error", plain_error(error))
        return
    _quiet_now.discard(app)
    info = result["info"]
    quiet = result.get("quiet")
    if result["installed"]:
        QtCore.QTimer.singleShot(0, apply_tabs)
        _p().SetString("ExtApp" + app + "Seen", info["tag"])
        _status("%s updated to %s" % (app, info["tag"]))
        for panel in list(_panels.values()):
            if panel.app == app:
                panel.reload_local()
        if app in _open_when_installed:
            _open_when_installed.discard(app)
            QtCore.QTimer.singleShot(0, lambda a=app: open_app(a))
    elif APPS[app]["mode"] == "web":
        old = _seen(app)
        _p().SetString("ExtApp" + app + "Seen", info["tag"])
        if old and extupdate.is_newer(info["tag"], old):
            _status("%s %s is out: %s" % (app, info["tag"], info["page"]), 15000)
        elif not quiet:
            _status("%s is at %s, the newest release" % (app, info["tag"]))
    elif not quiet:
        _status("%s %s is installed and up to date" % (app, result.get("had") or info["tag"]))
    _p().SetString("ExtApp" + app + "Latest", info["tag"])
    _p().SetString("ExtApp" + app + "Page", info["page"])
    _notify(app, "ok", info)


def _tell_failed(app, why):
    """extapps161: the person said Yes to a download and it failed: a box they can read (the status line is gone in 12 s
    and sits behind the Add-Ins window)."""
    try:
        parent = QtWidgets.QApplication.activeModalWidget() or Gui.getMainWindow()
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, app,
                                    "%s could not be downloaded: %s.\n\nCheck the connection, then choose Download %s... "
                                    "in Tools > Add-Ins to try again." % (app, why, app),
                                    QtWidgets.QMessageBox.Ok, parent)
        box.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        box.setObjectName("FWExtDownloadFailed")
        box.open()
    except Exception as _fw_err:
        _fw_log("extapps.py:_tell_failed", _fw_err)


def _notify(app, kind, data):
    for panel in list(_panels.values()):
        if panel.app == app:
            panel.show_update(kind, data)


def startup_check():
    """Daily, quiet. A local app is only brought up to date when it was already downloaded by using its tab:
    nothing is fetched at start-up for a tab that was never opened."""
    if not auto_update() or extupdate.network_off():
        return
    for app in APPS:
        if not tab_on(app) or not installed(app):
            continue
        if time.time() - _p().GetFloat("ExtApp" + app + "Checked", 0.0) <= CHECK_EVERY:
            continue
        used = extupdate.current(_root(), APPS[app]["repo"]) is not None
        check(app, install=(used and APPS[app]["mode"] == "local"), quiet=True)


# ---------------------------------------------------------------- the local page for Diotopo
class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class _Server:
    def __init__(self, folder):
        handler = functools.partial(_Quiet, directory=folder)
        self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def find_site(folder):
    """The folder holding Diotopo's browser version (English first), found by looking, since the layout is the author's."""
    best = None
    for dirpath, dirs, files in os.walk(folder):
        if "index.html" not in files:
            continue
        low = dirpath.lower()
        score = (2 if "browser" in low else 0) + (1 if "english" in low or os.sep + "en" in low else 0) \
            - (3 if "installer" in low else 0) - (3 if "node_modules" in low else 0)
        key = (score, -len(dirpath))
        if best is None or key > best[0]:
            best = (key, dirpath)
    return best[1] if best else None


def find_portable(folder):
    for dirpath, dirs, files in os.walk(folder):
        if "portable" in dirpath.lower() or "portable" in os.path.basename(dirpath).lower():
            for f in files:
                if f.lower().endswith(".exe"):
                    return os.path.join(dirpath, f)
    return None


# ---------------------------------------------------------------- the page
_web = None


def _webengine():
    global _web
    if _web is None:
        try:
            from PySide import QtWebEngineWidgets as W, QtWebEngineCore as C
        except ImportError:
            try:
                from PySide6 import QtWebEngineWidgets as W, QtWebEngineCore as C
            except ImportError:
                W = C = False
        _web = (W, C) if W else False
    return _web


if Gui is not None and _webengine():
    _W, _C = _webengine()

    class _Page(_C.QWebEnginePage if hasattr(_C, "QWebEnginePage") else _W.QWebEnginePage):
        pending = []        # files the next Load press hands to the page (Send to ScanRuler)

        def chooseFiles(self, mode, old, accepted):
            if _Page.pending:
                files, _Page.pending = _Page.pending, []
                return files
            return super().chooseFiles(mode, old, accepted)


_panels = {}


def _style():
    return ("QToolButton{border:1px solid transparent;padding:3px 6px;background:transparent}"
            "QToolButton:hover{background:palette(midlight);border-color:palette(mid)}"
            "QToolButton:pressed{background:palette(mid)}"
            "#fwExtBar{background:palette(window);border-bottom:1px solid palette(mid)}"
            "#fwExtNote{padding:2px 8px;color:palette(text)}")


class AppPanel(QtWidgets.QWidget):
    ""

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.spec = APPS[app]
        self.server = None
        self.setWindowTitle(app)
        self.setStyleSheet(_style())
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QtWidgets.QWidget()
        bar.setObjectName("fwExtBar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(4, 2, 4, 2)
        self.view = _W.QWebEngineView()
        self.view.setPage(_Page(self.view))
        self.nav = {}
        for text, fn in (("Back", self.view.back), ("Forward", self.view.forward), ("Reload", self.view.reload)):
            b = QtWidgets.QToolButton()
            b.setText(text)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            row.addWidget(b)
            self.nav[text] = b
        # extapps93: Back and Forward show only when there is a page to go to (no button that does nothing)
        self.nav["Back"].hide()
        self.nav["Forward"].hide()
        self.view.urlChanged.connect(lambda *_: self._nav())
        self.view.loadFinished.connect(lambda *_: self._nav())
        self.note = QtWidgets.QLabel("")
        self.note.setObjectName("fwExtNote")
        row.addWidget(self.note, 1)
        browser = QtWidgets.QToolButton()
        browser.setText("Open in browser")
        browser.clicked.connect(lambda: webbrowser.open(self.view.url().toString()))
        row.addWidget(browser)
        lay.addWidget(bar)
        lay.addWidget(self.view, 1)
        try:
            self.view.page().profile().downloadRequested.connect(self._download)
        except Exception as _fw_err:
            _fw_log("extapps.py:357", _fw_err)
        self.show_update("cached", None)

    def _nav(self):
        history = self.view.history()
        self.nav["Back"].setVisible(history.canGoBack())
        self.nav["Forward"].setVisible(history.canGoForward())

    # ---- content
    def open_home(self):
        if self.spec["mode"] == "web":
            self.view.setUrl(QtCore.QUrl(self.spec["url"]))
        else:
            self.reload_local()

    def reload_local(self):
        have = extupdate.current(_root(), self.spec["repo"])
        site = find_site(have[1]) if have else None
        if not site:
            self.view.setHtml("<body style='font-family:sans-serif;padding:2em'><h3>%s</h3><p>%s</p></body>" % (
                self.app, "Downloading it from the author's GitHub..." if not have else
                "Downloaded, but no browser version (index.html) was found in it. Use Open Folder to look."))
            return
        if self.server:
            self.server.stop()
        self.server = _Server(site)
        self.view.setUrl(QtCore.QUrl("http://127.0.0.1:%d/" % self.server.port))

    def show_update(self, kind, data):
        if kind == "error":
            self.note.setText("Update check failed")
            self.note.setToolTip(str(data))
        elif kind == "ok":
            have = extupdate.current(_root(), self.spec["repo"]) if self.spec["mode"] == "local" else None
            self.note.setText("%s %s" % (self.app, have[0] if have else data["tag"]))
            self.note.setToolTip(data.get("page", ""))
        else:
            seen = (extupdate.current(_root(), self.spec["repo"]) or ("", ""))[0] if self.spec["mode"] == "local" \
                else _seen(self.app)
            self.note.setText("%s %s" % (self.app, seen) if seen else self.app)

    # ---- results back into FreeCAD
    def _download(self, item):
        folder = os.path.join(os.path.expanduser("~"), "Downloads")
        os.makedirs(folder, exist_ok=True)
        name = item.downloadFileName()
        try:
            item.setDownloadDirectory(folder)
        except Exception as _fw_err:
            _fw_log("extapps.py:401", _fw_err)
        item.accept()
        path = os.path.join(folder, name)

        def finished():
            _status("%s saved %s" % (self.app, path))
            if _result_kind(name):          # extapps101: the same kinds as the Results list (also IGES, XYZ, CSV, a .scanruler project)
                ask = QtWidgets.QMessageBox.question(Gui.getMainWindow(), self.app, "Open %s in FreeCAD?" % name)
                if ask == QtWidgets.QMessageBox.Yes:
                    open_file(path)

        item.isFinishedChanged.connect(lambda: finished() if item.isFinished() else None)

    def closeEvent(self, event):
        if self.server:
            self.server.stop()
            self.server = None
        _panels.pop(self.app, None)
        super().closeEvent(event)


def _mdi():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea)


_browser_servers = {}


def _open_in_browser(app):
    """No embedded web view in this FreeCAD (stock 1.1.4 has none): ScanRuler opens at its address, Diotopo is served
    from its downloaded folder on 127.0.0.1 and opened there (downloading it first when it is not there yet)."""
    spec = APPS[app]
    if spec["mode"] == "web":
        _show_url(app, spec["url"])
        return
    have = extupdate.current(_root(), spec["repo"])
    site = find_site(have[1]) if have else None
    if not site:
        if have is None:
            ask_download(app)
        else:
            _status("%s: no browser version found in the download: use Open Folder" % app)
        return
    server = _browser_servers.get(app)
    if server is None or server[0] != site:
        if server:
            server[1].stop()
        server = (site, _Server(site))
        _browser_servers[app] = server
    _show_url(app, "http://127.0.0.1:%d/" % server[1].port)


_open_when_installed = set()
_edge = {}


def _quote(p):
    from urllib.parse import quote
    return quote(p, safe="")


def _already_open(path):
    try:
        return any(os.path.normcase(getattr(d, "FileName", "") or "") == os.path.normcase(path)
                   for d in App.listDocuments().values())
    except Exception:
        return False


def _insert_undoable(doc, path, ext):
    """extapps/74: the file put into the document as one undo step named after it (FreeCAD's own Import does the
    same); when the insert fails nothing of it stays."""
    doc.openTransaction("Import %s" % os.path.basename(path))
    try:
        if ext in (".stl", ".obj", ".3mf", ".ply"):
            import Mesh
            Mesh.insert(path, doc.Name)
        else:
            import Import
            Import.insert(path, doc.Name)
    except Exception:
        doc.abortTransaction()
        raise
    doc.commitTransaction()


_DXF_BOOL = ("dxfShowDialog", "dxfImportAsDraft", "dxfImportAsPrimitives", "dxfImportAsShapes", "dxfImportAsFused")


def _dxf_as_shapes():
    """The DXF importer asks how to import (a dialog that waits for an answer); a sheet for a sketch is read as plain shapes, with no
    question, and the user's own import choices are put back afterwards."""
    g = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    saved = {k: g.GetBool(k, k in ("dxfShowDialog",)) for k in _DXF_BOOL}
    saved["DxfImportMode"] = g.GetInt("DxfImportMode", 2)
    for k in _DXF_BOOL:
        g.SetBool(k, k == "dxfImportAsShapes")
    g.SetInt("DxfImportMode", 2)
    return saved


def _dxf_restore(saved):
    g = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Draft")
    for k, v in saved.items():
        if k == "DxfImportMode":
            g.SetInt(k, v)
        else:
            g.SetBool(k, v)


def to_sketch(path):
    ""

    import importlib
    ext = os.path.splitext(path)[1].lower()
    label = _safe_name(os.path.splitext(os.path.basename(path))[0])
    doc = App.ActiveDocument or App.newDocument(label)
    scratch = None
    try:
        if ext == ".dxf":
            mod = importlib.import_module("importDXF")
        elif ext == ".svg":
            mod = importlib.import_module("importSVG")
        else:
            raise ValueError("a DXF or SVG sheet is needed")
        scratch = App.newDocument("fw_sheet", hidden=True)
        keep = _dxf_as_shapes() if ext == ".dxf" else {}
        try:
            mod.insert(path, scratch.Name)
        finally:
            _dxf_restore(keep)
        scratch.recompute()
        new = [o for o in scratch.Objects if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Edges]
        if not new:
            raise ValueError("no lines or arcs in %s" % os.path.basename(path))
        import Draft
        sk = Draft.make_sketch(new, autoconstraints=False, delete=False, name=label)
        if sk is None:
            raise ValueError("the sheet is not flat")
        scratch.recompute()
        doc.openTransaction("Sketch from %s" % os.path.basename(path))
        try:
            out = doc.copyObject(sk, False)
            out.Label = label
            doc.recompute()
        except Exception:
            doc.abortTransaction()
            raise
        doc.commitTransaction()
    except Exception as error:
        _status("Could not make a sketch from %s: %s" % (os.path.basename(path), error), 12000)
        return None
    finally:
        if scratch is not None:
            try:
                App.closeDocument(scratch.Name)
                App.setActiveDocument(doc.Name)
            except Exception as _fw_err:
                _fw_log("extapps.py:sheet", _fw_err)
    _status("Sketch %s made from %s" % (out.Label, os.path.basename(path)))
    return out


def open_file(path):
    """Opens a result in FreeCAD. The module that reads its type may not be loaded yet (Mesh for STL/OBJ/3MF/PLY, Import for
    STEP/IGES, Draft for DXF), so it is imported first, and the file is inserted into the active document as a last try."""
    import importlib
    ext = os.path.splitext(path)[1].lower()
    from . import scanimport        # extapps101: ScanRuler's own files (cloud XYZ / ASC, the CSV sheet, a .scanruler project)
    if scanimport.kind_of(path):
        try:
            _obj, what = scanimport.open_any(path)
            _status("%s: %s" % (os.path.basename(path), what), 12000)
            return True
        except Exception as error:
            _status("Could not open %s (%s)" % (os.path.basename(path), error), 12000)
            return False
    for mod in {".stl": ("Mesh", "MeshGui"), ".obj": ("Mesh", "MeshGui"), ".3mf": ("Mesh", "MeshGui"), ".ply": ("Mesh", "MeshGui"),
                ".step": ("Import", "ImportGui"), ".stp": ("Import", "ImportGui"), ".iges": ("Import", "ImportGui"),
                ".igs": ("Import", "ImportGui"), ".dxf": ("Import", "ImportGui"), ".svg": ("importSVG",)}.get(ext, ()):
        try:
            importlib.import_module(mod)
        except Exception as _fw_err:
            _fw_log("extapps.py:483", _fw_err)
    try:
        before = set(App.listDocuments())
        Gui.open(path)
        if set(App.listDocuments()) == before and not _already_open(path):
            raise RuntimeError("no document appeared")
        return True
    except Exception as first:
        try:
            if ext in (".stl", ".obj", ".3mf", ".ply", ".step", ".stp", ".iges", ".igs", ".dxf"):
                doc = App.ActiveDocument or App.newDocument(os.path.splitext(os.path.basename(path))[0])
                _insert_undoable(doc, path, ext)
                return True
            App.openDocument(path)
            return True
        except Exception as error:
            _status("Could not open %s (%s; %s)" % (os.path.basename(path), first, error), 12000)
            return False


_RESULT_EXT = (".step", ".stp", ".stl", ".obj", ".3mf", ".ply", ".dxf", ".svg", ".iges", ".igs", ".xyz", ".asc", ".csv")


def _result_kind(name):
    """Whether a file name is something ScanRuler saves that FreeCAD can take (extapps101: also its XYZ cloud, CSV sheet and project)."""
    from . import scanimport
    return os.path.splitext(name)[1].lower() in _RESULT_EXT or scanimport.is_project(name)


def _latest_download(since):
    """The newest file a page saved to Downloads after the tab opened, of a kind FreeCAD can open."""
    folder = os.path.join(os.path.expanduser("~"), "Downloads")
    best = None
    try:
        for n in os.listdir(folder):
            if _result_kind(n):
                p = os.path.join(folder, n)
                if os.path.getmtime(p) >= since and (best is None or os.path.getmtime(p) > os.path.getmtime(best)):
                    best = p
    except OSError as _fw_err:
        _fw_log("extapps.py:520", _fw_err)
    return best


def _show_url(app, url):
    ""
    from . import edgehost
    reason = edgehost.why_not()
    if reason:
        App.Console.PrintLog("FreeCAD add-in apps: %s gets its hub tab, the page opens in the browser (%s)\n" % (app, reason))
        _hub_tab(app, url)
        return
    old = _edge.get(app)
    if old is not None:
        try:
            _mdi().setActiveSubWindow(old.parentWidget())
            return
        except Exception:
            _edge.pop(app, None)
    opened = time.time()

    def import_latest():
        path = _latest_download(opened - 5)
        if path is None:
            _status("%s: nothing new in Downloads to open (STEP, STL, OBJ, 3MF...)" % app)
            return
        open_file(path)

    buttons = [("Open latest download in FreeCAD", import_latest), ("Open in browser", lambda: webbrowser.open(url))]
    panel = edgehost.EdgePanel(app, url, os.path.join(_root(), "webhost", app), buttons, app)
    panel.setStyleSheet(_style())
    panel.failed.connect(lambda: (_close_edge(app), webbrowser.open(url)))
    _edge[app] = panel
    sub = _mdi().addSubWindow(panel)
    sub.setWindowTitle(app)
    sub.setWindowIcon(QtGui.QIcon(_icon(app.lower())))
    sub.showMaximized()


# ---------------------------------------------------------------- the hub tab (no web view and no Chromium browser)
_HUB_ACTIONS = {
    "ScanRuler": (("launch", "Open ScanRuler"), ("send", "Send selection to ScanRuler"),
                  ("update", "Check for update"), ("notes", "Release notes")),
    "Diotopo": (("launch", "Open Diotopo"), ("portable", "Portable program"), ("update", "Update now"),
                ("folder", "Open folder"), ("notes", "Project page")),
}
_hub_open = {}
_STEPS = {"Diotopo": "<ol><li>Open Diotopo: its browser version runs from the add-on's own folder.</li>"
                     "<li>Set up the part and run the optimization in the page, then export the result.</li>"
                     "<li>Come back here: the export is listed under Results and opens in FreeCAD.</li></ol>",
          "ScanRuler": "<ol><li>Select a part or a mesh in FreeCAD and press Send to ScanRuler (a part goes as STEP, a mesh as STL, in millimetres).</li>"
                       "<li>In the page press Load (the scan) or Reference &gt; Load (the nominal part). A flatbed image stays UNCALIBRATED until you "
                       "calibrate it against something of known size.</li>"
                       "<li>Measure, align or section in the page, then export STEP, STL, DXF, SVG, an XYZ cloud, the CSV sheet or the project.</li>"
                       "<li>Come back here: the export is listed under Results. A DXF or SVG sheet can open as a sketch; a CSV sheet opens as a sketch; an XYZ file as a point cloud; a .scanruler project as its scan and reference part.</li></ol>"}


def _recent_results(limit=6):
    folder = os.path.join(os.path.expanduser("~"), "Downloads")
    out = []
    try:
        for n in os.listdir(folder):
            p = os.path.join(folder, n)
            if _result_kind(n) and time.time() - os.path.getmtime(p) < 7 * 86400:
                out.append((os.path.getmtime(p), p))
    except OSError as _fw_err:
        _fw_log("extapps.py:579", _fw_err)
    return [p for _, p in sorted(out, reverse=True)[:limit]]


class HubPanel(QtWidgets.QTextBrowser):
    ""


    def __init__(self, app, url):
        super().__init__()
        self.app, self.url, self.kind, self.data = app, url, "cached", None
        self.setWindowTitle(app)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._link)
        self.render()
        try:        # extapps100: what the page saved shows up when you come back to FreeCAD (the list was fixed at the tab's opening)
            QtWidgets.QApplication.instance().applicationStateChanged.connect(self._app_state)
        except Exception as _fw_err:
            _fw_log("extapps.py:hubstate", _fw_err)

    # same hooks as AppPanel, so the update callbacks reach it
    def show_update(self, kind, data):
        self.kind, self.data = kind, data
        self.render()

    def reload_local(self):
        self.render()

    def _app_state(self, state):
        try:
            if state == QtCore.Qt.ApplicationActive and self.isVisible():
                self.render()
        except RuntimeError:        # the panel is gone
            return

    def render(self):
        import html as H
        self._drawn = True
        pal = self.palette()
        bg, fg = pal.window().color().name(), pal.windowText().color().name()
        hi, mid = pal.highlight().color().name(), pal.mid().color().name()
        try:
            from . import style
            hi = style.T.hex("accent") or hi
        except Exception as _fw_err:
            _fw_log("extapps.py:612", _fw_err)
        spec = APPS[self.app]
        have = extupdate.current(_root(), spec["repo"]) if spec["mode"] == "local" else None
        version = have[0] if have else (_seen(self.app) or "")
        latest = _p().GetString("ExtApp" + self.app + "Latest", "")
        status = "Not checked yet" if not _p().GetFloat("ExtApp" + self.app + "Checked", 0.0) else "No answer from GitHub at the last check"       # extapps143: "Not checked yet" beside a "Last checked" time read as a contradiction
        if self.kind == "error":
            status = "Update check failed: " + H.escape(str(self.data))
        elif latest:
            status = ("Up to date" if not extupdate.is_newer(latest, version or "") or not version
                      else "New version %s is out" % H.escape(latest))
            if spec["mode"] == "web":
                status = "Newest release is %s" % H.escape(latest)
        checked = _p().GetFloat("ExtApp" + self.app + "Checked", 0.0)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(checked)) if checked else "never"
        btn = pal.button().color().name()
        # extapps133: the grey note was the palette's mid colour (near invisible on Dark): a blend of the text and the window
        f, g = pal.windowText().color(), pal.window().color()
        note = QtGui.QColor((f.red() * 3 + g.red() * 2) // 5, (f.green() * 3 + g.green() * 2) // 5,
                            (f.blue() * 3 + g.blue() * 2) // 5).name()
        # extapps93: each action is a real button (a bordered cell): Qt's HTML view ignores a link's own border and padding
        buttons = '<table cellspacing="6" cellpadding="6"><tr>%s</tr></table>' % "".join(
            '<td bgcolor="%s" style="border:1px solid %s"><a class="b" href="fw:%s" title="%s">%s</a></td>' % (
                btn, mid, k, H.escape(self._tip(k)), H.escape(t))      # extapps113: a tooltip on each button
            for k, t in _HUB_ACTIONS[self.app] if k != "portable" or _has_portable())      # extapps/75: no link that can only say there is none
        top = 0
        try:        # extapps145: the tab row sits over the top of the graphics area, and it covered the page's title
            from . import shell as _sh
            if _sh.shell().topbar.tabs_on_view:
                top = 30
        except Exception as _fw_err:
            _fw_log("extapps.py:144", _fw_err)
        self.setViewportMargins(0, top, 0, 0)
        about = spec["tip"] if not have else spec["tip"].split(" Optional:")[0].rstrip(".") + ". Kept up to date from the author's GitHub."
        recent = "".join('<li><a href="fw:open?%s">%s</a>%s</li>' % (_quote(p), H.escape(os.path.basename(p)),
                         (' &nbsp;<a href="fw:sketch?%s">as a sketch</a>' % _quote(p)) if os.path.splitext(p)[1].lower() in (".dxf", ".svg") else "")
                         for p in _recent_results()) or "<li>Nothing saved lately. Save or export in the page and it shows here.</li>"
        self.setHtml("""<style>
body{background:%s;color:%s;font-family:Segoe UI,sans-serif}
h2{margin:0 0 4px 0} .pm{border:1px solid %s;padding:8px;margin:8px 0}
.t{background:%s;color:#fff;padding:3px 8px;font-weight:bold} a.b{text-decoration:none;color:%s}
</style><body><h2>%s</h2><p>%s</p>
<div class="pm"><div class="t">Start</div><p>%s</p><p style="color:%s">The page opens in your web browser; this tab stays here with its results.</p></div>
<div class="pm"><div class="t">Steps</div>%s</div>
<div class="pm"><div class="t">Version</div><p>%s%s<br>%s<br>Last checked: %s</p></div>
<div class="pm"><div class="t">Results for FreeCAD</div><ul>%s</ul></div></body>""" % (
            bg, fg, mid, hi, fg, H.escape(self.app), H.escape(about), buttons, note, _STEPS.get(self.app, ""),
            H.escape(self.app), (" " + H.escape(version)) if version else "", status, when, recent))

    def changeEvent(self, event):
        # extapps133: a theme change re-colours the open hub (it was drawn once, in the theme it opened in)
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.PaletteChange and getattr(self, "_drawn", False) and not getattr(self, "_busy", False):
            self._busy = True
            try:
                self.render()
            finally:
                self._busy = False

    def _tip(self, action):
        """The tip of an action button: the command's own tip."""
        sr = self.app == "ScanRuler"
        name = {"launch": "FW_SR_Open" if sr else "FW_DT_Open", "send": "FW_SR_Send",
                "update": "FW_SR_Update" if sr else "FW_DT_Update", "notes": "FW_SR_Notes" if sr else "FW_DT_Page",
                "folder": "FW_DT_Folder", "portable": "FW_DT_Portable"}.get(action)
        return getattr(COMMANDS.get(name), "tip", "") or ""

    def result_menu(self, path):
        """extapps113: the right-click menu of a result: Open, Open as a Sketch (a sheet), Show in Folder, Copy Path."""
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("FW_HubResultMenu")
        menu.addAction("Open").triggered.connect(lambda *_: self.open_result(path))
        if os.path.splitext(path)[1].lower() in (".dxf", ".svg"):
            menu.addAction("Open as a Sketch").triggered.connect(lambda *_: to_sketch(path))
        menu.addAction("Show in Folder").triggered.connect(
            lambda *_: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(path))))
        menu.addAction("Copy Path").triggered.connect(lambda *_: QtWidgets.QApplication.clipboard().setText(path))
        return menu

    def contextMenuEvent(self, event):
        """Right-click: a result's menu on a result, else Refresh (not Qt's Copy / Select All)."""
        from urllib.parse import unquote
        link = self.anchorAt(event.pos())
        menu = None
        if link and link.startswith("fw:open?"):
            menu = self.result_menu(unquote(link[len("fw:open?"):]))
        else:
            menu = QtWidgets.QMenu(self)
            menu.setObjectName("FW_HubMenu")
            menu.addAction("Refresh").triggered.connect(lambda *_: self.render())
        self._fw_menu = menu
        menu.popup(event.globalPos())

    def open_result(self, path):
        """A result of the page in FreeCAD (also what a click on its link calls)."""
        return open_file(path)

    def _link(self, qurl):
        try:
            s = qurl.toString(QtCore.QUrl.FullyEncoded)
        except Exception:
            s = qurl.toString()
        if s.startswith("fw:open?"):
            from urllib.parse import unquote
            path = unquote(s[len("fw:open?"):])
            self.open_result(path)
            return
        if s.startswith("fw:sketch?"):
            from urllib.parse import unquote
            to_sketch(unquote(s[len("fw:sketch?"):]))
            return
        action = s[3:]
        if action == "launch":
            _launch_page(self.app, self.url)
        else:
            cmd = {"send": "FW_SR_Send", "update": "FW_SR_Update" if self.app == "ScanRuler" else "FW_DT_Update",
                   "notes": "FW_SR_Notes" if self.app == "ScanRuler" else "FW_DT_Page",
                   "folder": "FW_DT_Folder", "portable": "FW_DT_Portable"}.get(action)
            if cmd:
                COMMANDS[cmd].Activated()
        QtCore.QTimer.singleShot(1500, self.render)

    def closeEvent(self, event):
        _hub_open.pop(self.app, None)
        super().closeEvent(event)


def _launch_page(app, url):
    webbrowser.open(url)
    _status("%s opened in your browser" % app)


def _hub_tab(app, url):
    """Shows (or raises) the app's hub tab; the first time in a session it also opens the page."""
    panel = _hub_open.get(app)
    if panel is not None:
        try:
            _mdi().setActiveSubWindow(panel.parentWidget())
            _launch_page(app, url)
            return
        except Exception:
            _hub_open.pop(app, None)
    panel = HubPanel(app, url)
    _hub_open[app] = panel
    _panels[app] = panel
    sub = _mdi().addSubWindow(panel)
    sub.setWindowTitle(app)
    sub.setWindowIcon(QtGui.QIcon(_icon(app.lower())))
    sub.showMaximized()
    _launch_page(app, url)


def _close_edge(app):
    panel = _edge.pop(app, None)
    if panel is not None:
        panel.stop()
        try:
            panel.parentWidget().close()
        except Exception as _fw_err:
            _fw_log("extapps.py:703", _fw_err)


def open_app(app):
    """Shows the app's tab (made on first use); without QtWebEngine the page opens in the browser.
    A local app that is not downloaded asks first (extapps/56)."""
    if not installed(app):
        ask_download(app)
        return None
    if not _webengine():
        App.Console.PrintLog("FreeCAD add-in apps: no QtWebEngine, trying the browser-window tab for %s\n" % app)
        _open_in_browser(app)
        return None
    panel = _panels.get(app)
    if panel is not None:
        sub = panel.parentWidget()
        try:
            _mdi().setActiveSubWindow(sub)
            return panel
        except Exception:
            _panels.pop(app, None)
    panel = AppPanel(app)
    _panels[app] = panel
    sub = _mdi().addSubWindow(panel)
    sub.setWindowTitle(app)
    sub.setWindowIcon(QtGui.QIcon(_icon(app.lower())))
    sub.showMaximized()
    panel.open_home()
    if APPS[app]["mode"] == "local" and extupdate.current(_root(), APPS[app]["repo"]) is None:
        check(app, install=True)
    return panel


def _safe_name(text):
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in text).strip() or "selection"


def send_selection():
    """The selection handed to ScanRuler's next Load. extapps100: a CAD part goes as a STEP file (ScanRuler's reference part
    "straight from CAD": exact faces, millimetres, no units question); a mesh, or a mix, as an STL in millimetres."""
    import Mesh
    import MeshPart
    objs = [o for o in Gui.Selection.getSelection() if hasattr(o, "Shape") or hasattr(o, "Mesh")]
    if not objs:
        _status("Select a part or a mesh first")
        return
    folder = tempfile.mkdtemp(prefix="freecad-scanruler-")     # extapps/74: shown in the status bar
    name = _safe_name(objs[0].Label if len(objs) == 1 else "selection")
    cad = all(hasattr(o, "Shape") and not hasattr(o, "Mesh") and not o.Shape.isNull() for o in objs)
    path = os.path.join(folder, name + (".step" if cad else ".stl"))
    try:
        if cad:
            import Part
            Part.export([o for o in objs], path)
        elif all(hasattr(o, "Mesh") for o in objs):
            Mesh.export(objs, path)
        else:
            mesh = Mesh.Mesh()
            for o in objs:
                if hasattr(o, "Shape"):
                    mesh.addMesh(MeshPart.meshFromShape(Shape=o.Shape, LinearDeflection=0.05, AngularDeflection=0.3))
                else:
                    mesh.addMesh(o.Mesh)
            mesh.write(path)
    except Exception as error:
        _status("Could not make the mesh: %s" % error)
        return
    panel = open_app("ScanRuler")
    if panel is None:
        _status("%s saved to %s: press Load (a scan) or Reference > Load (the nominal part) in ScanRuler and pick it"
                % ("Part (STEP)" if cad else "Mesh", path), 15000)      # extapps129: a STEP part was said to be a mesh
        try:
            os.startfile(folder)
        except Exception as _fw_err:
            _fw_log("extapps.py:762", _fw_err)
        return
    _Page.pending = [path]
    _status("ScanRuler: press Load (a scan) or Reference > Load (the nominal part) and %s opens at once (millimetres)" % os.path.basename(path), 12000)


# ---------------------------------------------------------------- commands
class _Cmd:
    def __init__(self, text, tip, icon, run, active=None):
        self.text, self.tip, self.icon, self.run, self.act = text, tip, icon, run, active

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": _icon(self.icon)}

    def IsActive(self):
        return True if self.act is None else bool(self.act())

    def Activated(self):
        try:
            self.run()
        except Exception as error:
            App.Console.PrintError("FreeCAD add-in apps: %s\n" % error)
            _status("%s" % error)


def _folder(app):
    have = extupdate.current(_root(), APPS[app]["repo"])
    if not have:
        _status("%s is not downloaded yet: open it first" % app)
        return
    os.startfile(have[1]) if hasattr(os, "startfile") else webbrowser.open("file://" + have[1])
    _status("%s's folder opened" % app)     # extapps/75: a click that opens something elsewhere says so here


def _portable():
    have = extupdate.current(_root(), APPS["Diotopo"]["repo"])
    exe = find_portable(have[1]) if have else None
    if not exe:
        _status("Diotopo has no portable program in this download: use Open Diotopo (browser version)")
        return
    ok = QtCore.QProcess.startDetached(exe, [], os.path.dirname(exe))
    if isinstance(ok, tuple):       # PySide6 gives (started, pid)
        ok = ok[0]
    # extapps79: the click says what happened, as the other buttons do (extapps/75)
    _status("Diotopo's portable program started" if ok else "Diotopo's portable program did not start: %s" % exe)


def _page(app):
    webbrowser.open(_p().GetString("ExtApp" + app + "Page", "") or "https://github.com/" + APPS[app]["repo"])
    _status("%s's project page opened in your browser" % app)     # extapps/75


def _notes(app):
    webbrowser.open("https://github.com/%s/releases" % APPS[app]["repo"])
    _status("%s's release notes opened in your browser" % app)     # extapps/75


COMMANDS = {
    "FW_SR_Open": _Cmd("ScanRuler (3D Scan Inspection)", APPS["ScanRuler"]["tip"], "scanruler", lambda: open_app("ScanRuler")),
    "FW_SR_Send": _Cmd("Send Selection to ScanRuler", "Sends the selected part (as a STEP file) or mesh (as an STL, in millimetres) to ScanRuler: press Load, or "
                       "Reference > Load for the nominal part, and it opens at once.", "send", send_selection),
    "FW_SR_Update": _Cmd("ScanRuler Check for Update", "Reads ScanRuler's releases page and says when a new version is out.",
                         "update", lambda: check("ScanRuler", quiet=False)),
    "FW_SR_Notes": _Cmd("ScanRuler Release Notes", "Opens ScanRuler's releases page.", "notes", lambda: _notes("ScanRuler")),
    "FW_DT_Open": _Cmd("Diotopo (Topology Optimization)", APPS["Diotopo"]["tip"], "diotopo", lambda: open_app("Diotopo")),
    "FW_DT_Portable": _Cmd("Diotopo Portable Program", "Starts Diotopo's portable program from the download, if it has one.",
                           "diotopo", _portable),
    "FW_DT_Update": _Cmd("Diotopo Update Now", "Downloads Diotopo's newest version from the author's GitHub.", "update",
                         lambda: update_now("Diotopo")),
    "FW_DT_Folder": _Cmd("Diotopo Open Folder", "Shows the downloaded copy of Diotopo.", "folder", lambda: _folder("Diotopo")),
    "FW_DT_Page": _Cmd("Diotopo Project Page", "Opens Diotopo's GitHub page.", "notes", lambda: _page("Diotopo")),
}

# catalog key, label, command, tip, caption, icon file
KEYS = (
    ("SR_Open", "ScanRuler (3D Scan Inspection)", "FW_SR_Open", COMMANDS["FW_SR_Open"].tip, "ScanRuler", "scanruler"),
    ("SR_Send", "Send Selection to ScanRuler", "FW_SR_Send", COMMANDS["FW_SR_Send"].tip, "Send to\nScanRuler", "send"),
    ("SR_Update", "ScanRuler Check for Update", "FW_SR_Update", COMMANDS["FW_SR_Update"].tip, "Check for\nUpdate", "update"),
    ("SR_Notes", "ScanRuler Release Notes", "FW_SR_Notes", COMMANDS["FW_SR_Notes"].tip, "Release\nNotes", "notes"),
    ("DT_Open", "Diotopo (Topology Optimization)", "FW_DT_Open", COMMANDS["FW_DT_Open"].tip, "Diotopo", "diotopo"),
    ("DT_Portable", "Diotopo Portable Program", "FW_DT_Portable", COMMANDS["FW_DT_Portable"].tip, "Portable\nProgram", "diotopo"),
    ("DT_Update", "Diotopo Update Now", "FW_DT_Update", COMMANDS["FW_DT_Update"].tip, "Update\nNow", "update"),
    ("DT_Folder", "Diotopo Open Folder", "FW_DT_Folder", COMMANDS["FW_DT_Folder"].tip, "Open\nFolder", "folder"),
    ("DT_Page", "Diotopo Project Page", "FW_DT_Page", COMMANDS["FW_DT_Page"].tip, "Project\nPage", "notes"),
)

SEP = ("sep",)
LAYOUTS = {
    "ScanRuler": (("large", "SR_Open", None), ("large", "SR_Send", None), SEP,
                  ("large", "SR_Update", None), ("large", "SR_Notes", None)),
    "Diotopo": (("large", "DT_Open", None), ("large", "DT_Portable", None), SEP,
                ("large", "DT_Update", None), ("large", "DT_Folder", None), ("large", "DT_Page", None)),
}


# ---------------------------------------------------------------- tabs
def _register():
    from . import catalog
    for name, cmd in COMMANDS.items():
        if name not in Gui.listCommands():
            Gui.addCommand(name, cmd)
    for key, label, native, tip, caption, icon in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, (native,), _icon(icon), tip, caption=caption)
    catalog.ALL = tuple(catalog._ALL)


def _has_portable():
    have = extupdate.current(_root(), APPS["Diotopo"]["repo"])
    try:
        return bool(have and find_portable(have[1]))
    except Exception:
        return False


def _portable_button(app, layout):
    """extapps/75: Diotopo's Portable Program button only when the download has a portable program; without one it could
    only say so (a dead button). It comes back after DT_Open when a later download has one."""
    if app != "Diotopo":
        return layout
    keys = [e[1] for e in layout if e != SEP]
    if _has_portable():
        if "DT_Portable" in keys or "DT_Portable" not in _CUT:
            return layout
        _CUT.discard("DT_Portable")
        out = list(layout)
        at = next((i + 1 for i, e in enumerate(out) if e != SEP and e[1] == "DT_Open"), 0)
        out.insert(at, ("large", "DT_Portable", None))
        return tuple(out)
    if "DT_Portable" in keys:
        _CUT.add("DT_Portable")
        return tuple(e for e in layout if e == SEP or e[1] != "DT_Portable")
    return layout


_CUT = set()


def apply_tabs():
    """Adds the tabs that are on and removes the ones that are off, then rebuilds the CommandManager."""
    from . import catalog, cmtabs
    for app in APPS:
        # 2026-11-22 (Ati): no tab of their own: the apps are buttons of the Add-Ins tab (addinapps.py), shown while
        # on and downloaded; the Add-Ins tab is made again below
        cmtabs.TABS.pop(app, None)
        cmtabs.ORDER = tuple(t for t in cmtabs.ORDER if t != app)
        cmtabs._ALL_TABS[:] = [t for t in cmtabs._ALL_TABS if t[0] != app]
        catalog.TABS = tuple(t for t in catalog.TABS if t[0] != app)
    try:
        cmtabs.apply(rebuild=True)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD add-in apps: tabs not rebuilt (%s)\n" % error)


def _hook_assembly_tabs():
    try:
        from . import asmtabs
    except ImportError:
        return
    if getattr(asmtabs.every_tab, "_fw_extapps", False):
        return
    original = asmtabs.every_tab

    def every_tab(part_tabs):
        from . import cmtabs
        tabs = list(original(part_tabs))
        have = {t[0] for t in tabs}
        for app in APPS:
            if tab_on(app) and app in cmtabs.TABS and app not in have:
                tabs.append((app, cmtabs.TABS[app]))
        return tabs

    every_tab._fw_extapps = True
    asmtabs.every_tab = every_tab


# ---------------------------------------------------------------- Tools > Add-Ins
def _options_hook():
    try:
        from . import optionspages as op
    except ImportError:
        return
    if getattr(op.system_pages, "_fw_extapps", False) or not hasattr(op, "BoolFn"):
        return
    original = op.system_pages

    def page():
        rows = []
        for app in APPS:
            if not installed(app):
                rows.append(op.Button("Download %s..." % app, lambda _dlg, a=app: ask_download(a),
                                      tip="%s is not part of this download. This fetches it from the author's GitHub; "
                                          "its tab appears when done." % app))
                continue
            rows.append(op.BoolFn("ExtApp" + app + "Tab", "Show the %s tab" % app,
                                  lambda a=app: tab_on(a), lambda v, a=app: set_tab_on(a, v),
                                  tip="%s in the CommandManager, next to Add-Ins" % app))
            if APPS[app]["mode"] == "local":
                rows.append(op.Button("Update %s now" % app, lambda _dlg, a=app: update_now(a),
                                      tip="Downloads the newest version from the author's GitHub"))
        rows.append(op.BoolFn("ExtAppAutoUpdate", "Check for updates automatically (once a day)", auto_update,
                              set_auto_update, tip="ScanRuler: tells you when a new release is out. Diotopo: "
                                                   "downloads the new version from the author's GitHub."))
        return ("Add-In Apps", [(None, rows)], None, [])

    def system_pages(base=()):
        out = list(original(base))
        out.append(page())
        return out

    system_pages._fw_extapps = True
    op.system_pages = system_pages


# ---------------------------------------------------------------- install
def install():
    """After the add-in tabs: our commands and keys, the two tabs (when on), the Options page, the daily check."""
    if Gui is None:
        return
    try:
        _register()
        _hook_assembly_tabs()
        pass        # look-audit addinapps-1120: no Options page; Tools > Add-Ins holds these settings (addins.py)
        try:
            from . import tipwords
            tipwords.apply()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: tooltip wording not applied (%s)\n" % error)
        try:
            from . import searchmenus
            searchmenus.install()
            from . import searchcomp
            searchcomp.install()
            from . import searchalias
            searchalias.install()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: menu commands not added to Search Commands (%s)\n" % error)
        apply_tabs()
        QtCore.QTimer.singleShot(FIRST_CHECK_MS, startup_check)
    except Exception as error:
        App.Console.PrintError("FreeCAD: add-in apps not added (%s)\n" % error)
