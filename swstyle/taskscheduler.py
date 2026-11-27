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

import datetime
import glob
import json
import os
import traceback

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

KINDS = ("Update Files", "Convert Files", "Print Files", "Create Drawings", "Custom Task")
FORMATS = ("STEP", "IGES", "STL", "OBJ")
EXT = {"STEP": ".step", "IGES": ".iges", "STL": ".stl", "OBJ": ".obj"}
REPEATS = ("Once", "Daily", "Weekly", "Monthly")
FMT = "%Y-%m-%d %H:%M"
STATE = {"tasks": None, "timer": None, "running": False}


def store_path():
    return os.path.join(App.getUserAppDataDir(), "FreeWorks", "tasks.json")


def tasks():
    if STATE["tasks"] is None:
        STATE["tasks"] = []
        try:
            with open(store_path(), encoding="utf-8") as f:
                STATE["tasks"] = json.load(f)
        except Exception as _fw_err:
            _fw_log("taskscheduler.py:60", _fw_err)
    return STATE["tasks"]


def save():
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tasks(), f, indent=1)


def new_task(kind, files=(), folder="", subfolders=False, output="", when=None, repeat="Once",
             fmt="STEP", macro="", title=""):
    t = {"title": title or kind, "kind": kind, "files": list(files), "folder": folder,
         "subfolders": bool(subfolders), "output": output, "format": fmt, "macro": macro,
         "when": (when or datetime.datetime.now()).strftime(FMT), "repeat": repeat,
         "status": "Scheduled", "report": [], "last": ""}
    tasks().append(t)
    save()
    return t


def task_files(t):
    out = [f for f in t.get("files", []) if f]
    folder = t.get("folder", "")
    if folder and os.path.isdir(folder):
        pattern = os.path.join(folder, "**", "*.FCStd") if t.get("subfolders") else os.path.join(folder, "*.FCStd")
        out += sorted(glob.glob(pattern, recursive=bool(t.get("subfolders"))))
    seen, uniq = set(), []
    for f in out:
        n = os.path.normcase(os.path.abspath(f))
        if n not in seen and not n.endswith(".fcbak"):
            seen.add(n)
            uniq.append(f)
    return uniq


def _open(path):
    for d in App.listDocuments().values():
        if d.FileName and os.path.normcase(d.FileName) == os.path.normcase(os.path.abspath(path)):
            return d, False
    return App.openDocument(path), True


def _shapes(doc):
    from . import asmcore as ac
    asm = ac.assembly_of(doc)
    if asm is not None:
        return [asm]
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body" or (
        hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids and not o.InList
        and o.getParentGeoFeatureGroup() is None)]


def _output(t, path, ext):
    folder = t.get("output") or os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, os.path.splitext(os.path.basename(path))[0] + ext)


def run_file(t, path):
    """One file of a task; returns the text for the report."""
    kind = t["kind"]
    doc, opened = _open(path)
    try:
        if kind == "Update Files":
            doc.recompute()
            doc.save()
            return "updated"
        if kind == "Convert Files":
            objs = _shapes(doc)
            if not objs:
                return "nothing to convert"
            out = _output(t, path, EXT.get(t.get("format", "STEP"), ".step"))
            if t.get("format") in ("STL", "OBJ"):
                import Mesh
                Mesh.export(objs, out)
            else:
                import Import
                Import.export(objs, out)
            return "-> " + out
        if kind == "Print Files":
            pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
            if not pages:
                return "no drawing sheets"
            import TechDrawGui
            done = []
            for i, page in enumerate(pages):
                out = _output(t, path, ".pdf" if len(pages) == 1 else "-%s.pdf" % page.Label)
                page.recompute(True)
                TechDrawGui.exportPageAsPdf(page, out)
                done.append(out)
            return "-> " + ", ".join(done)
        if kind == "Create Drawings":
            out = _output(t, path, "-drawing.FCStd") if t.get("output") else os.path.splitext(path)[0] + "-drawing.FCStd"
            three_view_drawing(doc, out)
            return "-> " + out
        if kind == "Custom Task":
            macro = t.get("macro", "")
            if not os.path.isfile(macro):
                raise RuntimeError("macro not found: %s" % macro)
            App.setActiveDocument(doc.Name)
            scope = {"__name__": "__main__", "App": App, "FreeCAD": App, "Gui": Gui, "FreeCADGui": Gui,
                     "DOCUMENT": doc, "FILE": path}
            with open(macro, encoding="utf-8") as f:
                exec(compile(f.read(), macro, "exec"), scope)
            return "macro run"
        raise RuntimeError("unknown task %s" % kind)
    finally:
        if opened:
            try:
                App.closeDocument(doc.Name)
            except Exception as _fw_err:
                _fw_log("taskscheduler.py:173", _fw_err)


def _template():
    p = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files").GetString("TemplateFile", "")
    if p and os.path.isfile(p):
        return p
    folder = os.path.join(App.getResourceDir(), "Mod", "TechDraw", "Templates")
    hits = sorted(glob.glob(os.path.join(folder, "**", "A4_Landscape*.svg"), recursive=True)) or \
        sorted(glob.glob(os.path.join(folder, "**", "*.svg"), recursive=True))
    return hits[0] if hits else ""


def three_view_drawing(source, out):
    """A drawing of source on the default sheet: Front, Top and Right (third angle), saved at out,
    with no boxes asked (a batch task)."""
    shapes = _shapes(source)
    d = App.newDocument(os.path.splitext(os.path.basename(out))[0].replace("-", "_"))
    try:
        page = d.addObject("TechDraw::DrawPage", "Sheet")
        tmpl = d.addObject("TechDraw::DrawSVGTemplate", "Template")
        tp = _template()
        if tp:
            tmpl.Template = tp
        page.Template = tmpl
        d.saveAs(out)               # views link to the part's file only from a saved drawing
        group = d.addObject("TechDraw::DrawProjGroup", "ProjGroup")
        page.addView(group)
        group.XSource = shapes
        group.ProjectionType = "Third angle"
        group.ScaleType = "Automatic"
        for view in ("Front", "Top", "Right"):
            group.addProjection(view)
        try:
            group.X, group.Y = float(tmpl.Width) * 0.42, float(tmpl.Height) * 0.58
        except Exception as _fw_err:
            _fw_log("taskscheduler.py:209", _fw_err)
        d.recompute()
        d.save()
    finally:
        App.closeDocument(d.Name)
    return out


def run(t):
    """Runs a task now: Running, then Completed or Failed, with its report."""
    t["status"] = "Running"
    _changed()
    report, failed = [], False
    files = task_files(t)
    if not files:
        report.append("no files")
        failed = True
    for path in files:
        try:
            report.append("%s: %s" % (os.path.basename(path), run_file(t, path)))
        except Exception as error:
            failed = True
            report.append("%s: FAILED %s" % (os.path.basename(path), error))
            App.Console.PrintLog("Task Scheduler: %s\n" % traceback.format_exc())
    t["report"] = report
    t["last"] = datetime.datetime.now().strftime(FMT)
    t["status"] = "Failed" if failed else "Completed"
    nxt = _next_time(t)
    if nxt is not None:
        t["when"] = nxt.strftime(FMT)
        t["status"] = "Scheduled"
        t["report"] = report + ["(last run %s: %s)" % (t["last"], "Failed" if failed else "Completed")]
    save()
    _changed()
    return not failed


def _next_time(t):
    try:
        when = datetime.datetime.strptime(t["when"], FMT)
    except Exception:
        return None
    rep = t.get("repeat", "Once")
    if rep == "Once":
        return None
    now = datetime.datetime.now()
    while when <= now:
        if rep == "Daily":
            when += datetime.timedelta(days=1)
        elif rep == "Weekly":
            when += datetime.timedelta(days=7)
        else:
            m = when.month % 12 + 1
            y = when.year + (1 if m == 1 else 0)
            try:
                when = when.replace(year=y, month=m)
            except ValueError:
                when = when.replace(year=y, month=m, day=28)
    return when


def due(now=None):
    now = now or datetime.datetime.now()
    out = []
    for t in tasks():
        if t.get("status") != "Scheduled":
            continue
        try:
            if datetime.datetime.strptime(t["when"], FMT) <= now:
                out.append(t)
        except Exception as _fw_err:
            _fw_log("taskscheduler.py:280", _fw_err)
    return out


def tick():
    if STATE["running"]:
        return
    try:
        from . import recovery
        if recovery.busy():
            return          # fh259: a task opening and closing files while another file opens or rebuilds ended FreeCAD
    except Exception as _fw_err:
        _fw_log("taskscheduler.py:busy", _fw_err)
    STATE["running"] = True
    try:
        for t in due():
            run(t)
    finally:
        STATE["running"] = False


LISTENERS = []


def _changed():
    for f in list(LISTENERS):
        try:
            f()
        except Exception as _fw_err:
            _fw_log("taskscheduler.py:303", _fw_err)


def start_timer():
    if Gui is None or STATE["timer"] is not None:
        return
    timer = QtCore.QTimer()
    timer.setInterval(30000)
    timer.timeout.connect(tick)
    timer.start()
    STATE["timer"] = timer


# ---------------------------------------------------------------- the window
if Gui is not None:
    class TaskDialog(QtWidgets.QDialog):
        """A new task (or one edited): its files, options and schedule."""

        def __init__(self, kind, task=None, parent=None):
            super().__init__(parent)
            self.setObjectName("FW_TaskDialog")
            self.setWindowTitle(kind)
            self.kind = kind
            t = task or {}
            lay = QtWidgets.QVBoxLayout(self)
            files = QtWidgets.QGroupBox("Task files or folders")
            fl = QtWidgets.QVBoxLayout(files)
            self.files = QtWidgets.QListWidget()
            self.files.setObjectName("FW_TaskFiles")
            for f in t.get("files", []):
                self.files.addItem(f)
            fl.addWidget(self.files)
            row = QtWidgets.QHBoxLayout()
            add_f = QtWidgets.QPushButton("Add File...")
            add_f.clicked.connect(self._add_file)
            rem = QtWidgets.QPushButton("Remove")
            rem.clicked.connect(lambda: self.files.takeItem(self.files.currentRow()))
            row.addWidget(add_f)
            row.addWidget(rem)
            row.addStretch(1)
            fl.addLayout(row)
            frow = QtWidgets.QHBoxLayout()
            self.folder = QtWidgets.QLineEdit(t.get("folder", ""))
            self.folder.setObjectName("FW_TaskFolder")
            self.folder.setPlaceholderText("Folder")
            add_d = QtWidgets.QPushButton("Add Folder...")
            add_d.clicked.connect(lambda: self._pick_dir(self.folder))
            frow.addWidget(self.folder, 1)
            frow.addWidget(add_d)
            fl.addLayout(frow)
            self.subfolders = QtWidgets.QCheckBox("Include subfolders")
            self.subfolders.setObjectName("FW_TaskSubfolders")
            self.subfolders.setChecked(bool(t.get("subfolders")))
            fl.addWidget(self.subfolders)
            lay.addWidget(files)
            opts = QtWidgets.QGroupBox("Task options")
            of = QtWidgets.QFormLayout(opts)
            self.title = QtWidgets.QLineEdit(t.get("title", kind))
            self.title.setObjectName("FW_TaskTitle")
            of.addRow("Title:", self.title)
            self.format = QtWidgets.QComboBox()
            self.format.setObjectName("FW_TaskFormat")
            self.format.addItems(list(FORMATS))
            self.format.setCurrentText(t.get("format", "STEP"))
            if kind == "Convert Files":
                of.addRow("Convert to:", self.format)
            orow = QtWidgets.QHBoxLayout()
            self.output = QtWidgets.QLineEdit(t.get("output", ""))
            self.output.setObjectName("FW_TaskOutput")
            self.output.setPlaceholderText("Same folder as the file")
            ob = QtWidgets.QPushButton("Browse...")
            ob.clicked.connect(lambda: self._pick_dir(self.output))
            orow.addWidget(self.output, 1)
            orow.addWidget(ob)
            if kind in ("Convert Files", "Print Files", "Create Drawings"):
                of.addRow("Output folder:", orow)
            mrow = QtWidgets.QHBoxLayout()
            self.macro = QtWidgets.QLineEdit(t.get("macro", ""))
            self.macro.setObjectName("FW_TaskMacro")
            mb = QtWidgets.QPushButton("Browse...")
            mb.clicked.connect(self._pick_macro)
            mrow.addWidget(self.macro, 1)
            mrow.addWidget(mb)
            if kind == "Custom Task":
                of.addRow("Macro:", mrow)
            lay.addWidget(opts)
            sched = QtWidgets.QGroupBox("Schedule")
            sf = QtWidgets.QFormLayout(sched)
            self.repeat = QtWidgets.QComboBox()
            self.repeat.setObjectName("FW_TaskRepeat")
            self.repeat.addItems(list(REPEATS))
            self.repeat.setCurrentText(t.get("repeat", "Once"))
            sf.addRow("Running mode:", self.repeat)
            self.when = QtWidgets.QDateTimeEdit()
            self.when.setObjectName("FW_TaskWhen")
            self.when.setCalendarPopup(True)
            self.when.setDisplayFormat("yyyy-MM-dd HH:mm")
            try:
                w = datetime.datetime.strptime(t["when"], FMT)
            except Exception:
                w = datetime.datetime.now()
            self.when.setDateTime(QtCore.QDateTime(w.year, w.month, w.day, w.hour, w.minute, 0))
            sf.addRow("Start time and date:", self.when)
            lay.addWidget(sched)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def _add_file(self):
            for f in QtWidgets.QFileDialog.getOpenFileNames(self, "Add File", "", "FreeCAD (*.FCStd)")[0]:
                self.files.addItem(f)

        def _pick_dir(self, edit):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder", edit.text())
            if d:
                edit.setText(d)

        def _pick_macro(self):
            f = QtWidgets.QFileDialog.getOpenFileName(self, "Macro", "", "Macros (*.FCMacro *.py)")[0]
            if f:
                self.macro.setText(f)

        def values(self):
            q = self.when.dateTime()
            when = datetime.datetime(q.date().year(), q.date().month(), q.date().day(), q.time().hour(), q.time().minute())
            return {"title": self.title.text().strip() or self.kind, "kind": self.kind,
                    "files": [self.files.item(i).text() for i in range(self.files.count())],
                    "folder": self.folder.text().strip(), "subfolders": self.subfolders.isChecked(),
                    "output": self.output.text().strip(), "format": self.format.currentText(),
                    "macro": self.macro.text().strip(), "when": when.strftime(FMT), "repeat": self.repeat.currentText()}

    class TaskSchedulerWindow(QtWidgets.QDialog):
        def __init__(self, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.setObjectName("FW_TaskScheduler")
            self.setWindowTitle("Task Scheduler")
            lay = QtWidgets.QHBoxLayout(self)
            side = QtWidgets.QVBoxLayout()
            self.kind_buttons = {}
            for kind in KINDS:
                b = QtWidgets.QPushButton(kind + "...")
                b.setObjectName("FW_Task_" + kind.replace(" ", ""))
                b.clicked.connect(lambda _c=False, k=kind: self.add(k))
                side.addWidget(b)
                self.kind_buttons[kind] = b
            side.addStretch(1)
            lay.addLayout(side)
            right = QtWidgets.QVBoxLayout()
            self.table = QtWidgets.QTableWidget(0, 5)
            self.table.setObjectName("FW_TaskList")
            self.table.setHorizontalHeaderLabels(["Title", "Task", "Scheduled Time", "Repeat", "Status"])
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.table.itemDoubleClicked.connect(lambda *_a: self.edit())
            self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._menu)
            right.addWidget(self.table, 1)
            self.report = QtWidgets.QPlainTextEdit()
            self.report.setObjectName("FW_TaskReport")
            self.report.setReadOnly(True)
            self.report.setMaximumHeight(130)
            right.addWidget(self.report)
            row = QtWidgets.QHBoxLayout()
            for text, name, fn in (("Run Now", "FW_TaskRunNow", self.run_now), ("Edit Task...", "FW_TaskEdit", self.edit),
                                   ("Delete Task", "FW_TaskDelete", self.delete)):
                b = QtWidgets.QPushButton(text)
                b.setObjectName(name)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch(1)
            right.addLayout(row)
            lay.addLayout(right, 1)
            self.table.currentCellChanged.connect(lambda *_a: self._show_report())
            LISTENERS.append(self.refresh)
            self.refresh()
            self.resize(820, 440)

        def closeEvent(self, e):
            if self.refresh in LISTENERS:
                LISTENERS.remove(self.refresh)
            super().closeEvent(e)

        def refresh(self):
            ts = tasks()
            cur = self.table.currentRow()
            self.table.setRowCount(len(ts))
            for r, t in enumerate(ts):
                for c, v in enumerate((t["title"], t["kind"], t["when"], t.get("repeat", "Once"), t["status"])):
                    it = QtWidgets.QTableWidgetItem(v)
                    it.setFlags(it.flags() & ~QtCore.Qt.ItemIsEditable)
                    self.table.setItem(r, c, it)
            if 0 <= cur < len(ts):
                self.table.setCurrentCell(cur, 0)
            self._show_report()
            QtWidgets.QApplication.processEvents()

        def _current(self):
            r = self.table.currentRow()
            ts = tasks()
            return ts[r] if 0 <= r < len(ts) else None

        def _show_report(self):
            t = self._current()
            self.report.setPlainText("\n".join(t.get("report", [])) if t else "")

        def add(self, kind):
            d = TaskDialog(kind, None, self)
            if d.exec() != QtWidgets.QDialog.Accepted:
                return None
            v = d.values()
            when = datetime.datetime.strptime(v.pop("when"), FMT)
            t = new_task(when=when, **{k: v[k] for k in ("kind", "files", "folder", "subfolders", "output",
                                                         "repeat", "macro", "title")}, fmt=v["format"])
            self.refresh()
            self.table.setCurrentCell(len(tasks()) - 1, 0)
            return t

        def edit(self):
            t = self._current()
            if t is None:
                return
            d = TaskDialog(t["kind"], t, self)
            if d.exec() == QtWidgets.QDialog.Accepted:
                t.update(d.values())
                t["status"] = "Scheduled"
                save()
                self.refresh()

        def delete(self):
            t = self._current()
            if t is not None:
                tasks().remove(t)
                save()
                self.refresh()

        def run_now(self):
            t = self._current()
            if t is not None:
                run(t)
                self.refresh()

        def _menu(self, pos):
            m = QtWidgets.QMenu(self)
            m.addAction("Run Now", self.run_now)
            m.addAction("Edit Task...", self.edit)
            m.addAction("Delete Task", self.delete)
            m.exec(self.table.viewport().mapToGlobal(pos))


OPEN = []


def show():
    w = TaskSchedulerWindow()
    OPEN[:] = [w]
    w.show()
    return w


class TaskSchedulerCommand:
    def GetResources(self):
        return {"MenuText": "Task Scheduler...", "Pixmap": "Std_Refresh",
                "ToolTip": "Runs batch tasks on files (update, convert, print, create drawings, macros), "
                           "now or at a set time."}

    def Activated(self, *a):
        show()

    def IsActive(self):
        return True


def register():
    if Gui is None:
        return
    if "SWStyle_TaskScheduler" not in Gui.listCommands():
        Gui.addCommand("SWStyle_TaskScheduler", TaskSchedulerCommand())
    start_timer()
