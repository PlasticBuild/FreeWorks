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
import tempfile

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths

Qt = QtCore.Qt
PARAM_BACKGROUND = "ImportModelBackground"
PARAM_INTO = "ImportModelInto"            # 0 new document, 1 active document
SOLID = (".step", ".stp", ".iges", ".igs", ".brep", ".brp")
MESH = (".stl", ".obj", ".3mf", ".ply", ".off", ".amf")
FILTER = ("Neutral files (*.step *.stp *.iges *.igs *.brep *.brp *.stl *.obj *.3mf *.ply *.off *.amf);;"
          "STEP (*.step *.stp);;IGES (*.iges *.igs);;BREP (*.brep *.brp);;"
          "Meshes (*.stl *.obj *.3mf *.ply *.off *.amf);;All files (*)")
WAITING, IMPORTING, DONE, FAILED = "Waiting", "Importing", "Done", "Failed"
CHILD = r"""
import os, FreeCAD as App
src, out = os.environ["FW_IMPORT_IN"], os.environ["FW_IMPORT_OUT"]
doc = App.newDocument("FWImport")
ext = os.path.splitext(src)[1].lower()
if ext in (".brep", ".brp"):
    import Part
    shape = Part.Shape(); shape.read(src)
    doc.addObject("Part::Feature", os.path.splitext(os.path.basename(src))[0]).Shape = shape
elif ext in (".iges", ".igs"):
    import Part
    Part.insert(src, doc.Name)
else:
    import Import
    Import.insert(src, doc.Name)
doc.recompute()
doc.saveAs(out)
"""

_queue = None


def supported(path):
    return os.path.splitext(path)[1].lower() in SOLID + MESH


def freecad_cmd():
    """FreeCAD's window-less program next to this one, or None."""
    names = ("FreeCADCmd.exe", "freecadcmd.exe") if os.name == "nt" else ("FreeCADCmd", "freecadcmd")
    dirs = [os.path.join(App.getHomePath(), "bin"), os.path.dirname(QtCore.QCoreApplication.applicationFilePath())]
    for d in dirs:
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def queue():
    global _queue
    if _queue is None:
        _queue = ImportQueue()
    return _queue


class ImportQueue(QtCore.QObject):
    """The files to import, done one at a time; changed() after every step."""
    changed = QtCore.Signal()
    finished = QtCore.Signal(object)          # the job dict

    def __init__(self):
        super().__init__()
        self.jobs = []
        self.process = None
        self.current = None

    # -- the list ---------------------------------------------------------------------------
    def add(self, paths_):
        added = 0
        for p in paths_:
            if p and os.path.isfile(p) and supported(p):
                self.jobs.append({"path": p, "status": WAITING, "doc": None, "error": "",
                                  "into": paths.params().GetInt(PARAM_INTO, 0),
                                  "background": paths.params().GetBool(PARAM_BACKGROUND, True)})
                added += 1
        if added:
            self.changed.emit()
            QtCore.QTimer.singleShot(0, self._next)
        return added

    def clear_finished(self):
        self.jobs = [j for j in self.jobs if j["status"] in (WAITING, IMPORTING)]
        self.changed.emit()

    def busy(self):
        return self.current is not None

    # -- one job ----------------------------------------------------------------------------
    def _next(self):
        if self.current is not None:
            return
        job = next((j for j in self.jobs if j["status"] == WAITING), None)
        if job is None:
            return
        self.current = job
        job["status"] = IMPORTING
        self.changed.emit()
        ext = os.path.splitext(job["path"])[1].lower()
        cmd = freecad_cmd() if job["background"] and ext in SOLID else None
        if cmd is not None and self._start_child(job, cmd):
            return
        QtCore.QTimer.singleShot(50, lambda: self._here(job))       # the row shows Importing first

    def _start_child(self, job, cmd):
        fd, out = tempfile.mkstemp(prefix="fwimport_", suffix=".FCStd")
        os.close(fd)
        os.remove(out)                       # our own empty temp file; FreeCADCmd writes it fresh
        job["temp"] = out
        script = os.path.join(tempfile.gettempdir(), "fwimport_child_%d.py" % os.getpid())     # pkg321: per session
        try:
            with open(script, "w") as f:
                f.write(CHILD)
        except OSError:
            return False
        p = QtCore.QProcess(self)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("FW_IMPORT_IN", job["path"])
        env.insert("FW_IMPORT_OUT", out)
        p.setProcessEnvironment(env)
        p.finished.connect(lambda code, status, job=job: self._child_done(job, code))
        p.errorOccurred.connect(lambda err, job=job: self._child_failed(job, err))
        self.process = p
        p.start(cmd, ["-c", "exec(open(%r).read())" % script])
        return True

    def _child_failed(self, job, err):
        if err == QtCore.QProcess.FailedToStart and job is self.current:
            self.process = None
            self._here(job)                  # no second FreeCAD: import here instead

    def _child_done(self, job, code):
        self.process = None
        if job is not self.current:
            return
        out = job.get("temp")
        if code != 0 or not out or not os.path.isfile(out):
            self._here(job)                  # the background read failed: try here before giving up
            return
        try:
            doc = self._target(job)
            n0 = len(doc.Objects)
            doc.mergeProject(out)
            doc.recompute()
            if len(doc.Objects) == n0:
                raise ValueError("nothing in the file to import")
            self._done(job, doc)
        except Exception as error:
            self._fail(job, error)
        finally:
            try:
                os.remove(out)               # our own temp copy
            except OSError as _fw_err:
                _fw_log("importpane.py:187", _fw_err)

    def _target(self, job):
        if job["into"] == 1 and App.ActiveDocument is not None:
            return App.ActiveDocument
        name = os.path.splitext(os.path.basename(job["path"]))[0]
        doc = App.newDocument("".join(c if c.isalnum() else "_" for c in name) or "Imported")
        doc.Label = name
        job["made"] = doc.Name
        return doc

    def _drop_made(self, job):
        """The new, still empty document of an import that failed goes again."""
        name = job.pop("made", None)
        try:
            if name and name in App.listDocuments() and not App.getDocument(name).Objects:
                App.closeDocument(name)
        except Exception as _fw_err:
            _fw_log("importpane.py:205", _fw_err)

    def _here(self, job):
        self._drop_made(job)                 # a failed background try's empty document
        try:
            doc = self._target(job)
            n0 = len(doc.Objects)
            ext = os.path.splitext(job["path"])[1].lower()
            if ext in MESH:
                import Mesh
                Mesh.insert(job["path"], doc.Name)
            elif ext in (".brep", ".brp"):
                import Part
                Part.insert(job["path"], doc.Name)
            elif not os.path.getsize(job["path"]):
                raise ValueError("the file is empty")
            else:
                try:
                    import ImportGui
                    ImportGui.insert(job["path"], doc.Name)
                except ImportError:
                    import Import
                    Import.insert(job["path"], doc.Name)
            doc.recompute()
            if len(doc.Objects) == n0:
                raise ValueError("nothing in the file to import")
            self._done(job, doc)
        except Exception as error:
            self._fail(job, error)

    def _done(self, job, doc):
        job.pop("made", None)
        job["status"] = DONE
        job["doc"] = doc.Name
        self.current = None
        try:
            gdoc = Gui.getDocument(doc.Name)
            if gdoc is not None and gdoc.ActiveView is not None:
                gdoc.ActiveView.viewIsometric()
                gdoc.ActiveView.fitAll()
        except Exception as _fw_err:
            _fw_log("importpane.py:246", _fw_err)
        notify("%s imported" % os.path.basename(job["path"]), doc.Name)
        self.changed.emit()
        self.finished.emit(job)
        QtCore.QTimer.singleShot(0, self._next)

    def _fail(self, job, error):
        self._drop_made(job)
        job["status"] = FAILED
        job["error"] = str(error)
        self.current = None
        App.Console.PrintWarning("FreeCAD: Import Model %s: %s\n" % (job["path"], error))
        notify("%s could not be imported" % os.path.basename(job["path"]), None)
        self.changed.emit()
        self.finished.emit(job)
        QtCore.QTimer.singleShot(0, self._next)


# ------------------------------------------------------------------------------- the notice
_notes = []


def notify(text, doc_name):
    """The status bar message and a balloon at the bottom right of the graphics area for a few
    seconds; a click on the balloon brings that document's window forward."""
    mw = Gui.getMainWindow()
    if mw is None:
        return None
    try:
        mw.statusBar().showMessage("Import Model: " + text, 6000)
    except Exception as _fw_err:
        _fw_log("importpane.py:277", _fw_err)
    area = mw.findChild(QtWidgets.QMdiArea)
    host = area if area is not None else mw
    note = QtWidgets.QLabel(host)
    note.setObjectName("SWImportModelNotice")
    note.setText(text)
    note.setProperty("swDoc", doc_name or "")
    note.setStyleSheet("QLabel#SWImportModelNotice{background:palette(tooltip-base);color:palette(tooltip-text);"
                       "border:1px solid palette(mid);border-radius:3px;padding:6px 10px;}")
    note.setCursor(Qt.PointingHandCursor)
    note.adjustSize()
    r = host.rect()
    up = sum(n.height() + 6 for n in _notes if _alive(n))
    note.move(r.right() - note.width() - 12, r.bottom() - note.height() - 12 - up)
    note.show()
    note.raise_()
    note.mousePressEvent = lambda e, d=doc_name, n=note: (_open_doc(d), n.close())
    _notes.append(note)
    QtCore.QTimer.singleShot(6000, lambda n=note: _drop(n))
    return note


def _alive(w):
    try:
        return w.isVisible()
    except RuntimeError:
        return False


def _drop(n):
    try:
        n.close()
        n.deleteLater()
    except RuntimeError as _fw_err:
        _fw_log("importpane.py:311", _fw_err)
    if n in _notes:
        _notes.remove(n)


def _open_doc(name):
    if not name:
        return
    try:
        doc = App.getDocument(name)
        App.setActiveDocument(doc.Name)
        gdoc = Gui.getDocument(doc.Name)
        if gdoc is not None and gdoc.ActiveView is not None:
            Gui.getMainWindow().setActiveWindow(gdoc.ActiveView)
    except Exception as _fw_err:
        _fw_log("importpane.py:326", _fw_err)


# ------------------------------------------------------------------------------- the page
class DropList(QtWidgets.QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWImportModelList")
        self.setHeaderLabels(["File", "Status"])
        self.setRootIsDecorated(False)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        self.itemDoubleClicked.connect(lambda item, col: _open_doc(item.data(0, Qt.UserRole)))

    def _paths(self, e):
        md = e.mimeData()
        return [u.toLocalFile() for u in md.urls()] if md is not None and md.hasUrls() else []

    def dragEnterEvent(self, e):
        if any(supported(p) for p in self._paths(e)):
            e.acceptProposedAction()
        else:
            e.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        n = queue().add(self._paths(e))
        if n:
            e.acceptProposedAction()


class ImportPage(QtWidgets.QWidget):
    def __init__(self, pane=None):
        super().__init__()
        self.setObjectName("SWImportModelPage")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        intro = QtWidgets.QLabel("Drop STEP, IGES, BREP or mesh files here, or Browse, to import "
                                 "them while you keep working.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QtWidgets.QHBoxLayout()
        self.browse = QtWidgets.QPushButton("Browse...")
        self.browse.setObjectName("SWImportModelBrowse")
        self.browse.clicked.connect(self.pick)
        row.addWidget(self.browse)
        row.addStretch(1)
        self.clear = QtWidgets.QPushButton("Clear Finished")
        self.clear.setObjectName("SWImportModelClear")
        self.clear.clicked.connect(lambda checked=False: queue().clear_finished())
        row.addWidget(self.clear)
        lay.addLayout(row)
        self.list = DropList(self)
        lay.addWidget(self.list, 1)
        box = QtWidgets.QGroupBox("Options")
        form = QtWidgets.QFormLayout(box)
        self.into = QtWidgets.QComboBox()
        self.into.setObjectName("SWImportModelInto")
        self.into.addItems(["New document", "Active document"])
        self.into.setCurrentIndex(paths.params().GetInt(PARAM_INTO, 0))
        self.into.currentIndexChanged.connect(lambda i: paths.params().SetInt(PARAM_INTO, int(i)))
        form.addRow("Import into:", self.into)
        self.background = QtWidgets.QCheckBox("Import in the background")
        self.background.setObjectName("SWImportModelBackground")
        self.background.setChecked(paths.params().GetBool(PARAM_BACKGROUND, True))
        self.background.toggled.connect(lambda on: paths.params().SetBool(PARAM_BACKGROUND, bool(on)))
        if freecad_cmd() is None:
            self.background.setToolTip("FreeCADCmd was not found next to FreeCAD: files import here instead")
        form.addRow(self.background)
        lay.addWidget(box)
        queue().changed.connect(self.fill)
        self.fill()

    def pick(self):
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(Gui.getMainWindow(), "Import Model", "", FILTER)
        queue().add(files)

    def fill(self):
        try:
            self.list.clear()
        except RuntimeError:
            return
        for j in queue().jobs:
            item = QtWidgets.QTreeWidgetItem([os.path.basename(j["path"]), j["status"]])
            item.setToolTip(0, j["path"] + (("\n" + j["error"]) if j["error"] else ""))
            item.setData(0, Qt.UserRole, j["doc"] or "")
            self.list.addTopLevelItem(item)


def page(pane):
    return ImportPage(pane)
