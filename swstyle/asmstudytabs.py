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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac

Qt = QtCore.Qt
MODEL = "Model"
DELETE_TEXT = "Are you sure you want to delete %s?"
ASK = {"answer": None}          # checks: True/False answers the delete question
BARS = {}                       # doc name -> StudyTabs
_TIMER = []
KIND_PROP = "FwStudyKind"       # "design" on a Design Study
SIM_TYPES = ("Static", "Frequency", "Buckling", "Thermal")
SOLVER_TYPE = {"Static": "static", "Frequency": "frequency", "Buckling": "buckling", "Thermal": "thermomech"}
TYPE_PROP = "FwStudyType"
CURRENT = {}                    # doc name -> the simulation/design study whose tab is current
STATUS = {}                     # checks: the last Show Solver Status / Cancel Solver text
DELETE_ALL_TEXT = "Are you sure you want to delete all simulation studies?"


def _mo():
    from . import asmmotion
    return asmmotion


def _view_widget(doc):
    try:
        gdoc = Gui.getDocument(doc.Name)
        view = gdoc.ActiveView if gdoc is not None else None
        return view.graphicsView() if view is not None else None
    except Exception:
        return None


def _ask(text):
    if ASK["answer"] is not None:
        return ASK["answer"]
    r = QtWidgets.QMessageBox.question(Gui.getMainWindow(), "FreeCAD", text,
                                       QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    return r == QtWidgets.QMessageBox.Yes


def _shown(asm):
    """The study whose MotionManager is up for asm, else None."""
    try:
        p = _mo().pane()
        if p is not None and p.asm is asm:
            return p.sim
    except (RuntimeError, ReferenceError, AttributeError) as _fw_err:
        _fw_log("asmstudytabs.py:77", _fw_err)
    return None


# ----------------------------------------------------------------------------- study kinds
def is_simulation(obj):
    return obj is not None and obj.TypeId in ("Fem::FemAnalysis", "Fem::FemAnalysisPython")


def is_design(obj):
    return obj is not None and getattr(obj, KIND_PROP, "") == "design"


def kind_of(obj):
    return "simulation" if is_simulation(obj) else "design" if is_design(obj) else "motion"


def simulation_studies(asm):
    return [o for o in asm.Document.Objects if is_simulation(o)]


def design_studies(asm):
    return [o for o in asm.Document.Objects if is_design(o)]


def all_studies(asm):
    ""
    out = list(_mo().studies(asm)) + simulation_studies(asm) + design_studies(asm)
    return sorted(out, key=lambda o: getattr(o, "ID", 0))


def _next_label(doc, base):
    names = {o.Label for o in doc.Objects}
    n = 1
    while "%s %d" % (base, n) in names:
        n += 1
    return "%s %d" % (base, n)


def _ask_type():
    if ASK.get("type") is not None:
        return ASK["type"]
    text, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Study", "Type", list(SIM_TYPES), 0, False)
    return text if ok else None


def create_simulation(asm, study_type=None):
    """Create New Simulation Study: a FreeCAD FEM analysis of the type (Static 1, Frequency 1...)
    with its CalculiX solver set to that analysis type."""
    study_type = study_type or _ask_type()
    if study_type not in SIM_TYPES:
        return None
    import ObjectsFem
    doc = asm.Document
    doc.openTransaction("New Simulation Study")
    try:
        study = ObjectsFem.makeAnalysis(doc, "Study")
        study.Label = _next_label(doc, study_type)
        study.addProperty("App::PropertyString", TYPE_PROP, "FreeCAD", "Simulation study type")
        setattr(study, TYPE_PROP, study_type)
        try:
            make = getattr(ObjectsFem, "makeSolverCalculiXCcxTools", None) or ObjectsFem.makeSolverCalculiX
            solver = make(doc, "Solver")
            if hasattr(solver, "AnalysisType"):
                solver.AnalysisType = SOLVER_TYPE[study_type]
            study.addObject(solver)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: simulation study solver: %s\n" % error)
    finally:
        doc.commitTransaction()
    doc.recompute()
    open_any(asm, study)
    return study


def create_design(asm):
    """Create New Design Study: its tab, and the Design Study window."""
    doc = asm.Document
    doc.openTransaction("New Design Study")
    try:
        study = doc.addObject("App::FeaturePython", "DesignStudy")
        study.Label = _next_label(doc, "Design Study")
        study.addProperty("App::PropertyString", KIND_PROP, "FreeCAD", "Study kind")
        setattr(study, KIND_PROP, "design")
        study.setPropertyStatus(KIND_PROP, "Hidden")
        if App.GuiUp and study.ViewObject is not None:
            try:
                study.ViewObject.ShowInTree = False
            except Exception as _fw_err:
                _fw_log("asmstudytabs.py:166", _fw_err)
    finally:
        doc.commitTransaction()
    open_any(asm, study)
    return study


def open_any(asm, study):
    """A study's tab clicked: Motion opens its MotionManager; Simulation makes its analysis the
    active one; Design opens the Design Study."""
    kind = kind_of(study)
    if kind == "motion":
        CURRENT.pop(asm.Document.Name, None)
        return open_study(asm, study)
    to_model(asm, keep=True)
    CURRENT[asm.Document.Name] = study
    if kind == "simulation":
        try:
            import FemGui
            FemGui.setActiveAnalysis(study)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: active analysis: %s\n" % error)
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(study)
        except Exception as _fw_err:
            _fw_log("asmstudytabs.py:192", _fw_err)
    else:
        try:
            from . import designstudy
            designstudy.design_study()
        except Exception as error:
            App.Console.PrintLog("FreeCAD: design study: %s\n" % error)
    refresh()
    return study


def copy_study(asm, study):
    """Copy Study: Motion as Duplicate did; a simulation or design study with its contents."""
    if kind_of(study) == "motion":
        return duplicate(asm, study)
    doc = asm.Document
    doc.openTransaction("Copy Study")
    try:
        new = doc.copyObject(study, False)
        new.Label = "Copy[%s]" % study.Label
        if is_simulation(study):
            try:
                new.Group = []
            except Exception as _fw_err:
                _fw_log("asmstudytabs.py:216", _fw_err)
            for child in list(getattr(study, "Group", [])):
                if child.TypeId.startswith("Fem::FemResult") or "Result" in child.Name:
                    continue
                try:
                    new.addObject(doc.copyObject(child, False))
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: Copy Study: %s: %s\n" % (child.Label, error))
    finally:
        doc.commitTransaction()
    doc.recompute()
    refresh()
    return new


def delete_all_simulations(asm, ask=True):
    sims = simulation_studies(asm)
    if not sims or (ask and not _ask(DELETE_ALL_TEXT)):
        return False
    for s_ in sims:
        delete(asm, s_, ask=False)
    return True


def _has_results(study):
    return any(c.TypeId.startswith("Fem::FemResult") or c.isDerivedFrom("Fem::FemResultObject")
               for c in getattr(study, "Group", []))


def solver_status(asm):
    rows = []
    for st_ in simulation_studies(asm):
        rows.append("%s (%s): %s" % (st_.Label, getattr(st_, TYPE_PROP, "") or "Study",
                                     "results ready" if _has_results(st_) else "not run"))
    return "\n".join(rows) or "No simulation studies."


def show_solver_status(asm):
    text = solver_status(asm)
    STATUS["text"] = text
    if ASK["answer"] is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "Solver Status", text)
    return text


def cancel_solver(asm):
    """Stops a running solve (FreeCAD's solver jobs); says so when none is running."""
    stopped = 0
    try:
        from femsolver import run as femrun
        for machine in list(getattr(femrun, "_machines", {}).values()):
            try:
                if machine.running:
                    machine.abort()
                    stopped += 1
            except Exception as _fw_err:
                _fw_log("asmstudytabs.py:272", _fw_err)
    except Exception as _fw_err:
        _fw_log("asmstudytabs.py:274", _fw_err)
    text = "Solver stopped." if stopped else "No solver is running."
    STATUS["text"] = text
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 4000)
    except Exception as _fw_err:
        _fw_log("asmstudytabs.py:280", _fw_err)
    return stopped


# ----------------------------------------------------------------------------- actions
def to_model(asm, keep=False):
    """The Model tab: the MotionManager closes; the components back at the study's start."""
    mo = _mo()
    p = mo.pane()
    if p is not None:
        try:
            if p.asm is asm:
                try:
                    p.stop()
                except Exception as _fw_err:
                    _fw_log("asmstudytabs.py:295", _fw_err)
                p.timeline.set_time(0.0)
        except (RuntimeError, ReferenceError) as _fw_err:
            _fw_log("asmstudytabs.py:298", _fw_err)
        dock = mo.PANE.get("dock")
        if dock is not None:
            dock.hide()
    if not keep:
        CURRENT.pop(asm.Document.Name, None)
        refresh()


def open_study(asm, sim):
    pane = _mo().show_pane(asm, sim)
    refresh()
    return pane


def create(asm):
    mo = _mo()
    doc = asm.Document
    doc.openTransaction("New Motion Study")
    try:
        sim = mo.new_study(asm)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    return open_study(asm, sim)


def duplicate(asm, sim):
    """A copy of the study: its type, duration, keys, options, motors and loads."""
    mo = _mo()
    doc = asm.Document
    doc.openTransaction("Duplicate Motion Study")
    new = mo.new_study(asm)
    for prop in sim.PropertiesList:
        if prop in ("Label", "Label2", "Group", "ExpressionEngine", "Visibility") or prop == mo.STUDY_PROP:
            continue
        try:
            if sim.getGroupOfProperty(prop) in ("FreeWorks", "FreeCAD") and not hasattr(new, prop):
                new.addProperty(sim.getTypeIdOfProperty(prop), prop, "FreeCAD", sim.getDocumentationOfProperty(prop))
                new.setEditorMode(prop, sim.getEditorMode(prop))
            if hasattr(new, prop) and "ReadOnly" not in sim.getPropertyStatus(prop):
                setattr(new, prop, getattr(sim, prop))
        except Exception as _fw_err:
            _fw_log("asmstudytabs.py:339", _fw_err)
    for child in list(getattr(sim, "Group", [])):
        try:
            copy = doc.copyObject(child, False)
            new.addObject(copy)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Duplicate Motion Study: %s: %s\n" % (child.Label, error))
    doc.commitTransaction()
    doc.recompute()
    return new


def rename(sim, text):
    text = (text or "").strip()
    if not text or text == sim.Label:
        return False
    doc = sim.Document
    doc.openTransaction("Rename Study")
    try:
        sim.Label = text
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    try:
        dock = _mo().PANE.get("dock")
        if dock is not None and dock.widget() is not None and getattr(dock.widget(), "sim", None) is sim:
            dock.setWindowTitle(text)
    except Exception as _fw_err:
        _fw_log("asmstudytabs.py:364", _fw_err)
    refresh()
    return True


def delete(asm, sim, ask=True):
    if ask and not _ask(DELETE_TEXT % sim.Label):
        return False
    doc = asm.Document
    doc.openTransaction("Delete Study")
    try:
        names = [c.Name for c in getattr(sim, "Group", [])]
        if CURRENT.get(doc.Name) is sim:
            CURRENT.pop(doc.Name, None)
        doc.removeObject(sim.Name)                 # the MotionManager closes with it (asmmotion)
        for n in names:
            if doc.getObject(n) is not None:
                doc.removeObject(n)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    doc.recompute()
    refresh()
    return True


# ----------------------------------------------------------------------------- the tab bar
class StudyTabs(QtWidgets.QTabBar):
    def __init__(self, doc, parent):
        super().__init__(parent)
        self.setObjectName("FW_StudyTabs")
        self.doc_name = doc.Name
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setShape(QtWidgets.QTabBar.RoundedSouth)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.tabBarClicked.connect(self._clicked)
        self.tabBarDoubleClicked.connect(self._double)
        self.sims = []
        self.editor = None
        self.setAutoFillBackground(True)
        parent.installEventFilter(self)

    def asm(self):
        d = App.listDocuments().get(self.doc_name)
        return ac.assembly_of(d) if d is not None else None

    def fill(self):
        asm = self.asm()
        if asm is None:
            return
        sims = all_studies(asm)
        labels = [MODEL] + [s.Label for s in sims]
        now = [self.tabText(i) for i in range(self.count())]
        self.blockSignals(True)
        try:
            if labels != now:
                while self.count():
                    self.removeTab(0)
                for t in labels:
                    self.addTab(t)
            self.sims = sims
            shown = _shown(asm) or CURRENT.get(self.doc_name)
            want = 1 + sims.index(shown) if shown in sims else 0
            if self.currentIndex() != want:
                self.setCurrentIndex(want)
        finally:
            self.blockSignals(False)
        self.adjustSize()
        self.place()

    def place(self):
        p = self.parentWidget()
        if p is not None:
            self.move(0, max(0, p.height() - self.height()))
            self.raise_()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            if obj is self.parentWidget() and event.type() == QtCore.QEvent.Resize:
                QtCore.QTimer.singleShot(0, self.place)
        except Exception as _fw_err:
            _fw_log("asmstudytabs.py:446", _fw_err)
        return False

    def sim_at(self, i):
        return self.sims[i - 1] if 0 < i <= len(self.sims) else None

    def _clicked(self, i):
        asm = self.asm()
        if asm is None or i < 0:
            return
        if i == 0:
            to_model(asm)
        else:
            sim = self.sim_at(i)
            if sim is not None and _shown(asm) is not sim and CURRENT.get(self.doc_name) is not sim:
                open_any(asm, sim)

    def _double(self, i):
        if self.sim_at(i) is not None:
            self.start_rename(i)

    def start_rename(self, i):
        sim = self.sim_at(i)
        if sim is None:
            return None
        ed = QtWidgets.QLineEdit(sim.Label, self)
        ed.setObjectName("FW_StudyTabRename")
        ed.setGeometry(self.tabRect(i))
        ed.selectAll()
        done = {"v": False}

        def commit():
            if done["v"]:
                return
            done["v"] = True
            text = ed.text()
            ed.hide()
            ed.deleteLater()
            self.editor = None
            rename(sim, text)
        ed.editingFinished.connect(commit)
        ed.show()
        ed.setFocus()
        self.editor = ed
        return ed

    def menu_entries(self, i):
        ""

        asm = self.asm()
        if asm is None:
            return []
        out = []
        sim = self.sim_at(i)
        if sim is not None:
            out += [("Copy Study", lambda: copy_study(asm, sim)),
                    ("Rename", lambda: self.start_rename(i)),
                    ("Delete", lambda: delete(asm, sim))]
        if simulation_studies(asm):
            out += [("Cancel Solver", lambda: cancel_solver(asm)),
                    ("Show Solver Status", lambda: show_solver_status(asm)),
                    ("Delete All Simulation Studies", lambda: delete_all_simulations(asm))]
        if out:
            out.append(("-", None))
        out += [("Create New Motion Study", lambda: create(asm)),
                ("Create New Simulation Study", lambda: create_simulation(asm)),
                ("Create New Design Study", lambda: create_design(asm))]
        return out

    def _menu(self, pos):
        i = self.tabAt(pos)
        if i < 0:
            return
        m = QtWidgets.QMenu(self)
        for text, fn in self.menu_entries(i):
            if text == "-":
                m.addSeparator()
                continue
            a = m.addAction(text)
            a.triggered.connect(lambda _=False, f=fn: f())
        m.exec(self.mapToGlobal(pos))


def bar(doc):
    b = BARS.get(doc.Name)
    try:
        if b is not None:
            b.isVisible()
            return b
    except RuntimeError:
        BARS.pop(doc.Name, None)
    return None


def refresh():
    """Each open assembly's view gets its tab bar (made, refilled, or dropped with the view)."""
    for name in list(BARS):
        if name not in App.listDocuments():
            b = BARS.pop(name)
            try:
                b.deleteLater()
            except RuntimeError as _fw_err:
                _fw_log("asmstudytabs.py:548", _fw_err)
    doc = App.ActiveDocument
    if doc is None or ac.assembly_of(doc) is None:
        return None
    parent = _view_widget(doc)
    if parent is None:
        return None
    b = bar(doc)
    try:
        if b is not None and b.parentWidget() is not parent:
            b.deleteLater()
            b = None
    except RuntimeError:
        b = None
    if b is None:
        b = BARS[doc.Name] = StudyTabs(doc, parent)
    b.fill()
    if strip() is not None:

        # (Model | 3D Views | Motion Study 1...) carries the studies; this bar stays filled but hidden
        _patch_strip()
        b.hide()
    else:
        b.show()
    return b


def strip():
    """The look's bottom tab strip (chrome.ModelTabs) when it is on screen, else None."""
    try:
        from . import shell
        sh = shell.shell()
        t = getattr(sh, "model_tabs", None) if sh is not None and getattr(sh, "enabled", False) else None
        return t if t is not None and t.isVisible() else None
    except Exception:
        return None


def entries_for(asm, sim):
    """The right-click menu of a study tab (sim) or of Model (None), as StudyTabs.menu_entries."""
    out = []
    if sim is not None:
        def ask_rename():
            text, ok = QtWidgets.QInputDialog.getText(Gui.getMainWindow(), "Rename", "Study name:", text=sim.Label)
            if ok and text:
                rename(sim, text)
        out += [("Copy Study", lambda: copy_study(asm, sim)), ("Rename", ask_rename), ("Delete", lambda: delete(asm, sim))]
    if simulation_studies(asm):
        out += [("Cancel Solver", lambda: cancel_solver(asm)),
                ("Show Solver Status", lambda: show_solver_status(asm)),
                ("Delete All Simulation Studies", lambda: delete_all_simulations(asm))]
    if out:
        out.append(("-", None))
    out += [("Create New Motion Study", lambda: create(asm)),
            ("Create New Simulation Study", lambda: create_simulation(asm)),
            ("Create New Design Study", lambda: create_design(asm))]
    return out


def _patch_strip():
    from . import chrome
    cls = chrome.ModelTabs
    if getattr(cls, "_fw_studies", False):
        return
    extras0, open0, activate0, press0 = cls.extras, cls._open_extra, cls._activate, cls.mousePressEvent

    def extras(self):
        out = extras0(self)
        try:
            asm = ac.assembly_of(App.ActiveDocument)
            if asm is None:
                return out
            studies = all_studies(asm)
            if not studies:
                return out
            shown = _shown(asm) or CURRENT.get(asm.Document.Name)
            keep = [e for e in out if e[1] not in ("motion", "motion_new")]
            return keep + [(st.Label, "study", (asm, st), shown is st) for st in studies]
        except Exception:
            return out

    def _open_extra(self, title, kind, payload):
        if kind == "study":
            asm, st = payload
            try:
                if _shown(asm) is not st and CURRENT.get(asm.Document.Name) is not st:
                    open_any(asm, st)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: %s tab: %s\n" % (title, error))
            self.refresh()
            return
        return open0(self, title, kind, payload)

    def _activate(self, index):
        subs = self.subwindows()
        model_row = index < (len(subs) or (1 if App.ActiveDocument is not None else 0))
        r = activate0(self, index)
        if model_row:
            try:
                asm = ac.assembly_of(App.ActiveDocument)
                if asm is not None and (_shown(asm) is not None or CURRENT.get(asm.Document.Name) is not None):
                    to_model(asm)
            except Exception as _fw_err:
                _fw_log("asmstudytabs.py:651", _fw_err)
        return r

    def tab_entries(self, i):
        """[(text, fn)] for a right-click on tab i in an assembly, else None."""
        asm = ac.assembly_of(App.ActiveDocument)
        if asm is None:
            return None
        subs = self.subwindows()
        n = len(subs) or (1 if App.ActiveDocument is not None else 0)
        if i < n:
            return entries_for(asm, None)
        ex = self.extras()
        j = i - n
        if 0 <= j < len(ex):
            title, kind, payload, _a = ex[j]
            if kind == "study":
                return entries_for(asm, payload[1])
            if kind in ("motion_new", "motion"):
                return entries_for(asm, None)
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            hit = self._hit(e.position().x())
            if hit and hit[0] == "tab":
                items = tab_entries(self, hit[1])
                subs = self.subwindows()
                if items:
                    m = QtWidgets.QMenu(self)
                    m.setObjectName("FW_StudyTabMenu")
                    if hit[1] < len(subs):
                        m.addAction("Close").triggered.connect(lambda _=False, sub=subs[hit[1]]: (sub.close(), self.refresh()))
                        m.addSeparator()
                    for text, fn in items:
                        if text == "-":
                            m.addSeparator()
                        else:
                            m.addAction(text).triggered.connect(lambda _=False, f=fn: (f(), self.refresh()))
                    self._fw_menu = m
                    m.popup(e.globalPosition().toPoint())
                    return
        return press0(self, e)

    cls.extras, cls._open_extra, cls._activate, cls.mousePressEvent = extras, _open_extra, _activate, mousePressEvent
    cls.tab_entries = tab_entries
    cls._fw_studies = True


def _tick():
    try:
        refresh()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: study tabs: %s\n" % error)


def install():
    if _TIMER:
        return
    t = QtCore.QTimer()
    t.setInterval(1000)
    t.timeout.connect(_tick)
    t.start()
    _TIMER.append(t)
    QtCore.QTimer.singleShot(0, _tick)
