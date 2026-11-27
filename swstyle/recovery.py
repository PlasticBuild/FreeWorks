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
import re
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets



def alive(obj):
    """The Qt object still exists (recover89b: kept here, as importing widgets this early, from startup's
    first step, broke widgets' own imports: "cannot import name 'CommandButton'")."""
    if obj is None:
        return False
    try:
        obj.objectName()
        return True
    except (RuntimeError, AttributeError):
        return False

Qt = QtCore.Qt
DOCUMENT = "User parameter:BaseApp/Preferences/Document"
META = "fc_recovery_file.xml"
FILE = "fc_recovery_file.fcstd"
FOLDER = "fc_recovery_files"
TITLE = "Document Recovery"
ICON = "DOCUMENT_RECOVERY_TAB"

_state = {"active": False, "startup": None, "timer": None, "dirty": set(), "written": {}, "observer": None, "held": []}
# recover89: recovery data the Task Pane's tab offers. FreeCAD 1.1's start box lists every status but Deprecated,
# Success and Failure, so held data is written Deprecated with a <Held> tag (FreeCAD's reader ignores the tag)
HELD = "Deprecated"
HELD_TAG = "<Held>TaskPane</Held>"


def _p():
    return App.ParamGet(DOCUMENT)


def enabled():
    return _p().GetBool("AutoSaveEnabled", True)


def minutes():
    return max(1, _p().GetInt("AutoSaveTimeout", 15) or 15)


# --------------------------------------------------------------------------- writing
def write(doc):
    """Writes doc's recovery data the way FreeCAD's auto-saver does. The file written, or None."""
    folder = getattr(doc, "TransientDir", "")
    if not folder or not os.path.isdir(folder):
        return None
    label = (doc.Label or doc.Name).replace("&", "&amp;").replace("<", "&lt;")
    name = (doc.FileName or "").replace("&", "&amp;").replace("<", "&lt;")
    with open(os.path.join(folder, META), "w", encoding="utf-8") as f:
        f.write("<?xml version='1.0' encoding='utf-8'?>\n<AutoRecovery SchemaVersion=\"1\">\n"
                "  <Status>Created</Status>\n  <Label>%s</Label>\n  <FileName>%s</FileName>\n</AutoRecovery>\n"
                % (label, name))
    path = os.path.join(folder, FILE)
    for old in [path] + [os.path.join(folder, n) for n in os.listdir(folder) if n.startswith(FILE) and n != FILE]:
        try:
            os.remove(old)          # no backup copies of the recovery file
        except OSError as _fw_err:
            _fw_log("recovery.py:79", _fw_err)
    doc.saveCopy(path)
    _state["written"][doc.Name] = time.time()
    return path


class _Observer:
    def slotChangedObject(self, obj, prop):
        if not _state["active"]:
            return              # FreeCAD's own saver is on the Options interval: nothing to track (no cost)
        try:
            name = obj.Document.Name
            _state["dirty"].add(name)
            _state["written"].setdefault(name, time.time())     # the first write one interval after the first change
        except Exception as _fw_err:
            _fw_log("recovery.py:94", _fw_err)

    def slotDeletedDocument(self, doc):
        _state["dirty"].discard(doc.Name)
        _state["written"].pop(doc.Name, None)
        try:
            from . import optionsextras2        # fh230: its Auto-recover folder copy goes with it
            optionsextras2.drop_recovery_copy(doc.Name)
        except Exception as _fw_err:
            _fw_log("recovery.py:drop_copy", _fw_err)


def own_saver_needed():
    """True while FreeCAD's saver runs on another interval than Options asks for."""
    start = _state["startup"]
    if not enabled():
        return False
    return start is None or start != (True, minutes())


def busy():
    """fh259: a document is being opened or rebuilt. FreeCAD lets timers run then (not clicks): a recovery
    copy written mid-open held half the document, and closing or reloading one then ended FreeCAD."""
    try:
        restoring = getattr(App, "isRestoring", None)
        if restoring is not None and restoring():
            return True     # fh259-v2: the application is restoring (a document may still say idle)
        return any(getattr(d, "Restoring", False) or getattr(d, "Recomputing", False)
                   for d in App.listDocuments().values())
    except Exception:
        return True         # fh259-v2: state unknown: the timer work waits for a later pass


def tick():
    """One pass of the saver: the documents changed since their last write, if their interval passed."""
    if busy():
        return []           # fh259: written on a later pass, once the open or the rebuild is over
    if not own_saver_needed():
        _state["active"] = False
        return []
    if not _state["active"]:
        _state["active"] = True         # just switched on: the documents with changes now count as changed
        for name, doc in App.listDocuments().items():
            try:
                gui = Gui.getDocument(name) if App.GuiUp else None
                if gui is not None and gui.Modified:
                    _state["dirty"].add(name)
                    _state["written"].setdefault(name, time.time())
            except Exception as _fw_err:
                _fw_log("recovery.py:123", _fw_err)
    now = time.time()
    done = []
    for name in list(_state["dirty"]):
        doc = App.listDocuments().get(name)
        if doc is None:
            _state["dirty"].discard(name)
            continue
        if now - _state["written"].get(name, 0) < minutes() * 60 - 1:
            continue
        try:
            if write(doc):
                done.append(name)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: auto-recover %s: %s\n" % (doc.Label, error))
        _state["dirty"].discard(name)
    return done


# --------------------------------------------------------------------------- finding
def _pid_alive(pid):
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
            k.GetExitCodeProcess(h, ctypes.byref(code))
            k.CloseHandle(h)
            return code.value == 259                       # STILL_ACTIVE
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


def _meta(folder):
    try:
        text = open(os.path.join(folder, META), encoding="utf-8").read()
    except OSError:
        return None
    get = lambda tag: (re.search(r"<%s>(.*?)</%s>" % (tag, tag), text, re.S) or [None, ""])[1]
    unq = lambda s: s.replace("&lt;", "<").replace("&amp;", "&")
    held = HELD_TAG in text
    return {"status": "Created" if held else get("Status"), "label": unq(get("Label")), "file": unq(get("FileName")),
            "held": held}


def _data(folder):
    f = os.path.join(folder, FILE)
    if os.path.isfile(f):
        return f
    f = os.path.join(folder, FOLDER, "Document.xml")
    return f if os.path.isfile(f) else None


def candidates(temp=None):
    """Recovery data of sessions that are gone: [{folder, label, file, data, time, status}]."""
    temp = temp or App.getTempPath()
    mine = {os.path.normcase(os.path.normpath(getattr(d, "TransientDir", "") or ""))
            for d in App.listDocuments().values()}
    out = []
    try:
        names = os.listdir(temp)
    except OSError:
        return out
    for n in names:
        folder = os.path.join(temp, n)
        if "_Doc_" not in n or not os.path.isdir(folder):
            continue
        if os.path.normcase(os.path.normpath(folder)) in mine:
            continue
        m = re.search(r"_(\d+)$", n)
        if m and _pid_alive(int(m.group(1))):
            continue                  # a FreeCAD that is still running
        meta = _meta(folder)
        data = _data(folder)
        if meta is None or data is None:
            continue
        out.append({"folder": folder, "label": meta["label"] or n, "file": meta["file"], "data": data,
                    "time": os.path.getmtime(data), "status": meta["status"], "held": meta.get("held", False)})
    out += _folder_candidates(out)
    out.sort(key=lambda c: -c["time"])
    return out


def _folder_candidates(found):
    ""

    out = []
    try:
        from . import optionsextras2
        root = optionsextras2.recover_folder()
        session_file = optionsextras2.SESSION_FILE
    except Exception:
        return out
    if not root:
        return out
    have = {(c["label"], os.path.normcase(c["file"] or "")) for c in found}
    for n in sorted(os.listdir(root)):
        folder = os.path.join(root, n)
        try:
            pid = int(open(os.path.join(folder, session_file)).read().strip())
        except (OSError, ValueError):
            continue                  # not a copy this add-on wrote (or one written before fh230)
        if _pid_alive(pid):
            continue                  # a FreeCAD still running (this one too)
        meta = _meta(folder)
        data = _data(folder)
        if meta is None or data is None:
            continue
        label = meta["label"] or n
        if (label, os.path.normcase(meta["file"] or "")) in have:
            continue                  # the same work is still in the temp folder
        out.append({"folder": folder, "label": label, "file": meta["file"], "data": data,
                    "time": os.path.getmtime(data), "status": meta["status"], "held": meta.get("held", False)})
    return out


def hold_for_task_pane(temp=None):
    ""



    n = 0
    for c in candidates(temp):
        if c["status"] == "Recovered":
            # fh199: recovered in an earlier session. FreeCAD's own recovery box took the unknown status for
            # Corrupted at the next start; saved since: the data goes; not saved: it is offered again
            try:
                saved = c["file"] and os.path.isfile(c["file"]) and os.path.getmtime(c["file"]) > c["time"]
            except OSError:
                saved = False
            if saved:
                remove(c)
            else:
                _set_status(c["folder"], "Created")
    for c in candidates(temp):
        if c["status"] == "Created" and not c.get("held"):
            _set_status(c["folder"], HELD, held=True)
            _state["held"].append(c["folder"])
            n += 1
    if n:
        try:
            app = QtWidgets.QApplication.instance()
            if app is not None and not _state.get("release_hooked"):
                app.aboutToQuit.connect(release_held)
                _state["release_hooked"] = True
        except Exception as _fw_err:
            _fw_log("recovery.py:hold", _fw_err)
    return n


def release_held():
    """Created back on the held recovery data still not recovered (see hold_for_task_pane)."""
    n = 0
    for folder in list(_state["held"]):
        m = _meta(folder)
        if m is not None and m.get("held"):
            _set_status(folder, "Created")
            n += 1
    _state["held"] = []
    return n


def _set_status(folder, status, held=False):
    p = os.path.join(folder, META)
    try:
        text = open(p, encoding="utf-8").read().replace("  " + HELD_TAG + "\n", "").replace(HELD_TAG, "")
        text = re.sub(r"<Status>.*?</Status>", "<Status>%s</Status>" % status, text)
        if held:
            text = text.replace("</AutoRecovery>", "  %s\n</AutoRecovery>" % HELD_TAG)
        open(p, "w", encoding="utf-8").write(text)
    except OSError as _fw_err:
        _fw_log("recovery.py:221", _fw_err)


def recover(c):
    """Opens a recovered document: the original's name, its file to save to, the changes not saved yet."""
    doc = App.openDocument(c["data"])
    try:
        if c["label"]:
            doc.Label = c["label"]
        try:

            # into the recovery copy in the temp folder (Reviewer 11-20 round 3)
            doc.FileName = c["file"] or ""
        except Exception as _fw_err:
            _fw_log("recovery.py:234", _fw_err)
        doc.recompute()
        for o in doc.Objects[:1]:
            o.touch()                 # the work is not saved yet
        if App.GuiUp:
            # fh199: and the window says so (title *, Save, the close prompt). cleanopen clears the modified
            # mark a file gets while it opens: this document is left to the user
            from . import cleanopen
            for watcher in Gui.getMainWindow().findChildren(QtCore.QObject):
                if isinstance(watcher, cleanopen.CleanOpen):
                    watcher.made.add(doc.Name)
                    watcher.watch.pop(doc.Name, None)
            Gui.getDocument(doc.Name).Modified = True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: recovered %s: %s\n" % (c["label"], error))
    _set_status(c["folder"], "Recovered")
    return doc


def remove(c):
    import shutil
    shutil.rmtree(c["folder"], ignore_errors=True)
    return not os.path.exists(c["folder"])


# --------------------------------------------------------------------------- the Task Pane tab
class Page(QtWidgets.QWidget):
    def __init__(self, pane=None):
        super().__init__(pane)
        self.setObjectName("SWDocumentRecovery")
        lay = QtWidgets.QVBoxLayout(self)
        self.note = QtWidgets.QLabel("These documents were open when FreeCAD last closed without saving them. "
                                     "Open one to get its work back, then save it.", self)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.list = QtWidgets.QTreeWidget(self)
        self.list.setObjectName("SWDocumentRecoveryList")
        self.list.setHeaderLabels(["Document", "Saved", "Status"])
        self.list.setRootIsDecorated(False)
        try:
            # fh199: Saved and Status whole in the narrow pane ("Not recovered" was cut off), the name takes the rest
            head = self.list.header()
            head.setStretchLastSection(False)
            head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            for col in (1, 2):
                head.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)
        except Exception as _fw_err:
            _fw_log("recovery.py:columns", _fw_err)
        self.list.itemDoubleClicked.connect(lambda *_: self.open_selected())
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        row = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton("Open", self)
        self.open_button.setObjectName("SWDocumentRecoveryOpen")
        self.open_button.clicked.connect(self.open_selected)
        self.remove_button = QtWidgets.QPushButton("Remove", self)
        self.remove_button.setObjectName("SWDocumentRecoveryRemove")
        self.remove_button.setToolTip("Delete the recovery data of the picked documents")
        self.remove_button.clicked.connect(self.remove_selected)
        row.addWidget(self.open_button)
        row.addWidget(self.remove_button)
        row.addStretch(1)
        lay.addLayout(row)
        self.items = []
        self.refresh()

    def refresh(self):
        self.items = candidates()
        self.list.clear()
        for c in self.items:
            it = QtWidgets.QTreeWidgetItem([c["label"], time.strftime("%Y-%m-%d %H:%M", time.localtime(c["time"])),
                                            "Recovered" if c["status"] == "Recovered" else "Not recovered"])
            it.setToolTip(0, c["file"] or "Never saved")
            self.list.addTopLevelItem(it)
        if self.items:
            self.list.setCurrentItem(self.list.topLevelItem(0))
        for b in (self.open_button, self.remove_button):
            b.setVisible(bool(self.items))      # no greyed buttons: with nothing to recover there are none

    def _picked(self):
        rows = sorted({self.list.indexOfTopLevelItem(i) for i in self.list.selectedItems()})
        return [self.items[r] for r in rows if 0 <= r < len(self.items)]

    def open_selected(self):
        docs = [recover(c) for c in self._picked()]
        self.refresh()
        self._left()
        return docs

    def _left(self):
        """recover89: the panel at the right goes once every document is recovered or removed."""
        if not any(c["status"] != "Recovered" for c in getattr(self, "items", [])):
            emptied = getattr(self, "emptied", None)
            if emptied is not None:
                QtCore.QTimer.singleShot(0, emptied)

    def remove_selected(self):
        picked = self._picked()
        if not picked:
            return 0
        n = sum(1 for c in picked if remove(c))
        self.refresh()
        sync_tab()
        self._left()
        return n

    def _menu(self, pos):
        m = QtWidgets.QMenu(self)
        m.addAction("Open", self.open_selected)
        m.addAction("Remove", self.remove_selected)
        m.exec(self.list.viewport().mapToGlobal(pos))


def _tabs():
    try:
        from . import chrome
        mw = Gui.getMainWindow()
        return [t for t in mw.findChildren(chrome.TaskPaneTabs) if alive(t)]
    except Exception:
        return []


def tab_index():
    from . import chrome
    return len(chrome.TaskPaneTabs.ITEMS)


def sync_tab(show=False):
    """The Document Recovery tab at the bottom of the Task Pane while there is recovery data."""
    from . import chrome, icons, taskpane
    index = tab_index()
    taskpane.register_page(index, lambda pane: Page(pane))
    want = bool(candidates())
    for tabs in _tabs():
        has = len(tabs.ITEMS) > index
        if want and not has:
            tabs.ITEMS = chrome.TaskPaneTabs.ITEMS + ((ICON, TITLE, "recovery"),)
            icon = icons.family(ICON)
            tabs.icons = list(tabs.icons[:index]) + [icon if not icon.isNull() else icons.family("STANDARD_OPEN")]
        elif not want and has:
            tabs.ITEMS = chrome.TaskPaneTabs.ITEMS
            tabs.icons = list(tabs.icons[:index])
            pane = getattr(tabs, "_pane", None)
            if pane is not None and alive(pane) and pane.index == index:
                pane.close_pane()
        tabs.resize(tabs.width(), int(len(tabs.ITEMS) * tabs.box_h + 1))
        tabs.update()
        if want and show:
            try:
                taskpane.pane_of(tabs).show_tab(index)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: Document Recovery tab: %s\n" % error)
    if want and show and not any(t.isVisible() for t in _tabs()):
        show_dock()             # recover89: no document open, so no Task Pane on a view: the same page at the right
    elif not want:
        close_dock()
    return want


DOCK = "SWDocumentRecoveryDock"


def show_dock():
    ""


    mw = Gui.getMainWindow()
    dock = mw.findChild(QtWidgets.QDockWidget, DOCK)
    if dock is None or not alive(dock):
        dock = QtWidgets.QDockWidget(TITLE, mw)
        dock.setObjectName(DOCK)
        dock.setFeatures(QtWidgets.QDockWidget.DockWidgetClosable | QtWidgets.QDockWidget.DockWidgetMovable)
        page = Page(dock)
        page.emptied = close_dock
        dock.setWidget(page)
        dock.setMinimumWidth(300)
        mw.addDockWidget(Qt.RightDockWidgetArea, dock)
    else:
        dock.widget().refresh()
    dock.show()
    dock.raise_()
    return dock


def close_dock():
    try:
        dock = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, DOCK)
        if dock is not None and alive(dock):
            dock.close()
            dock.deleteLater()
    except Exception as _fw_err:
        _fw_log("recovery.py:close_dock", _fw_err)


# --------------------------------------------------------------------------- install
def install():
    if _state["timer"] is not None:
        return
    _state["startup"] = (enabled(), minutes())
    _state["observer"] = _Observer()
    App.addDocumentObserver(_state["observer"])
    t = _state["timer"] = QtCore.QTimer()
    t.setInterval(20000)
    t.timeout.connect(tick)
    t.start()
    # after FreeCAD's own recovery at startup has had its turn
    QtCore.QTimer.singleShot(6000, lambda: _safe(lambda: sync_tab(show=True)))


def _safe(fn):
    try:
        fn()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: recovery: %s\n" % error)
