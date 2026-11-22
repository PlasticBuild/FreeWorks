# -*- coding: utf-8 -*-
""










import os
import subprocess
import threading
import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    Gui = None

_FW_SEEN = set()


def _fw_log(site, err):
    key = (site, type(err).__name__)
    if key in _FW_SEEN:
        return
    _FW_SEEN.add(key)
    try:
        App.Console.PrintLog("FreeCAD %s: %s\n" % (site, err))
    except Exception:
        pass


class Cancelled(RuntimeError):
    """The user pressed Cancel in the run window."""

    def __init__(self):
        super().__init__("Run cancelled.")


STATE = {"window": None, "depth": 0, "cancel": False, "paused": False, "proc": None, "study": None, "lines": []}
# Results > Solver Messages...: the last run's messages of each study, (document name, study name) -> text
MESSAGES = {}

# the stages of a run and where each starts on the progress bar (the solve fills the rest as CalculiX reports)
STAGES = {"Meshing": 0, "Writing the input file": 25, "Solving": 30, "Reading the results": 92}


def _gui():
    try:
        return Gui is not None and App.GuiUp and Gui.getMainWindow() is not None
    except Exception:
        return False


def _config(doc):
    try:
        from . import simtree
        return simtree.config_name(doc)
    except Exception:
        return "Default"


def solver_name(analysis):
    for o in getattr(analysis, "Group", []) or []:
        t = getattr(getattr(o, "Proxy", None), "Type", "") or o.TypeId
        if "Ccx" in t or "CalculiX" in t:
            return "CalculiX"
        if "Elmer" in t:
            return "Elmer"
    return "CalculiX"


if Gui is not None:
    class RunWindow(QtWidgets.QDialog):
        ""




        def __init__(self, analysis):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWSimRunWindow")
            self.analysis = analysis
            self.setWindowTitle(analysis.Label)
            self.setWindowModality(QtCore.Qt.ApplicationModal)
            self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
            self.start = time.time()
            self.paused_for = 0.0
            self.paused_at = None
            self.memory_k = 0
            self.thermal = _is_thermal(analysis)
            lay = QtWidgets.QVBoxLayout(self)
            self.stage = QtWidgets.QLabel("Starting")
            self.stage.setObjectName("SWSimRunStage")
            self.bar = QtWidgets.QProgressBar()
            self.bar.setObjectName("SWSimRunBar")
            self.bar.setRange(0, 100)
            self.bar.setValue(0)

            self.progress = QtWidgets.QLabel("")
            self.progress.setObjectName("SWSimRunProgress")
            self.progress.hide()
            self.memory = QtWidgets.QLabel("Memory Usage:0K")
            self.memory.setObjectName("SWSimRunMemory")
            self.elapsed = QtWidgets.QLabel("Elapsed Time:0s")
            self.elapsed.setObjectName("SWSimRunTime")
            for w in (self.stage, self.bar, self.progress, self.memory, self.elapsed):
                lay.addWidget(w)
            # More>>: the current task, the study's size and the solver
            self.details = QtWidgets.QWidget()
            self.details.setObjectName("SWSimRunDetails")
            dl = QtWidgets.QVBoxLayout(self.details)
            dl.setContentsMargins(0, 0, 0, 0)
            self.task = QtWidgets.QLabel("Current Task:")
            self.task.setObjectName("SWSimRunTask")
            self.task_bar = QtWidgets.QProgressBar()
            self.task_bar.setObjectName("SWSimRunTaskBar")
            self.task_bar.setRange(0, 100)
            dl.addWidget(self.task)
            dl.addWidget(self.task_bar)
            study = QtWidgets.QGroupBox("Study")
            study.setObjectName("SWSimRunStudy")
            sl = QtWidgets.QVBoxLayout(study)
            self.dof = QtWidgets.QLabel("Degrees of Freedom:")
            self.dof.setObjectName("SWSimRunDof")
            self.nodes = QtWidgets.QLabel("Number of Nodes:")
            self.nodes.setObjectName("SWSimRunNodes")
            self.elements = QtWidgets.QLabel("Number of Elements:")
            self.elements.setObjectName("SWSimRunElements")
            for w in (self.dof, self.nodes, self.elements):
                sl.addWidget(w)
            dl.addWidget(study)
            solver = QtWidgets.QGroupBox("Solver")
            solver.setObjectName("SWSimRunSolverGroup")
            vl = QtWidgets.QVBoxLayout(solver)
            self.solver = QtWidgets.QLabel("Type:%s" % solver_name(analysis))
            self.solver.setObjectName("SWSimRunSolver")
            vl.addWidget(self.solver)
            vl.addWidget(QtWidgets.QLabel("Warnings:"))
            self.warnings = QtWidgets.QListWidget()
            self.warnings.setObjectName("SWSimRunWarnings")
            self.warnings.setMinimumHeight(70)
            vl.addWidget(self.warnings)
            dl.addWidget(solver)
            self.details.hide()
            lay.addWidget(self.details)
            row = QtWidgets.QHBoxLayout()
            self.pause = QtWidgets.QPushButton("Pause")
            self.pause.setObjectName("SWSimRunPause")
            self.cancel = QtWidgets.QPushButton("Cancel")
            self.cancel.setObjectName("SWSimRunCancel")
            self.more = QtWidgets.QPushButton("More>>")
            self.more.setObjectName("SWSimRunMore")
            row.addWidget(self.pause)
            row.addWidget(self.cancel)
            row.addWidget(self.more)
            lay.addLayout(row)
            self.pause.clicked.connect(self.toggle_pause)
            self.cancel.clicked.connect(self.ask_cancel)
            self.more.clicked.connect(self.toggle_more)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.tick)
            self.timer.start(250)
            self.setMinimumWidth(360)
            self.study_size()
            self.adjustSize()

        def tick(self):
            now = self.paused_at or time.time()
            t = int(max(0.0, now - self.start - self.paused_for))
            self.elapsed.setText("Elapsed Time:%s" % elapsed_text(t))
            k = _memory_k(STATE.get("proc"))
            if k:
                self.memory_k = max(self.memory_k, k)
                self.memory.setText("Memory Usage:{:,}K".format(k))
            self.study_size()              # kept current behind More>> too (a mesh made during the run fills in)

        def study_size(self):
            """The Study group: the mesh's nodes and elements, and the degrees of freedom (3 a node, 1 for thermal)."""
            n, e = _mesh_size(self.analysis)
            if n:
                self.nodes.setText("Number of Nodes:{:,}".format(n))
                self.elements.setText("Number of Elements:{:,}".format(e))
                self.dof.setText("Degrees of Freedom:{:,}".format(n * (1 if self.thermal else 3)))

        def set_task(self, text, percent=None):
            task = text.split(":", 1)[1].strip() if ":" in text else text
            self.task.setText("Current Task:%s" % (task[:1].upper() + task[1:]))
            if percent is None:
                self.task_bar.setRange(0, 0)               # busy: the solver gives no per-task percentage
            else:
                self.task_bar.setRange(0, 100)
                self.task_bar.setValue(int(max(0, min(100, percent))))

        def warn(self, line):
            self.warnings.addItem(line.strip())

        def toggle_pause(self):
            on = not STATE["paused"]
            if not _suspend(STATE.get("proc"), on):
                return
            STATE["paused"] = on
            if on:
                self.paused_at = time.time()
                self.pause.setText("Resume")
                self.stage.setText(self.stage.text() + " (paused)")
            else:
                self.paused_for += time.time() - (self.paused_at or time.time())
                self.paused_at = None
                self.pause.setText("Pause")
                self.stage.setText(self.stage.text().replace(" (paused)", ""))

        def ask_cancel(self):
            STATE["cancel"] = True
            if STATE["paused"]:
                self.toggle_pause()
            self.cancel.setText("Cancelling")
            self.pause.hide()

        def toggle_more(self):
            show = self.details.isHidden()
            if show:
                self.study_size()
            self.details.setVisible(show)
            self.more.setText("Less<<" if show else "More>>")
            self.adjustSize()

        def closeEvent(self, e):           # the title bar's X cancels, as Cancel does
            if STATE["depth"] > 0:
                if e.spontaneous():        # the user's click; a script's close() leaves the run going
                    self.ask_cancel()
                e.ignore()
            else:
                e.accept()

        def reject(self):                  # Esc does not stop a run (only Cancel or the title bar's X do)
            if STATE["depth"] == 0:
                super().reject()


def elapsed_text(t):
    ""
    h, m, sec = t // 3600, t // 60 % 60, t % 60
    if h:
        return "%dh:%02dm:%02ds" % (h, m, sec)
    if m:
        return "%dm:%02ds" % (m, sec)
    return "%ds" % sec


def _is_thermal(analysis):
    try:
        return any(getattr(o, "AnalysisType", "") == "thermomech" and getattr(o, "ThermoMechType", "") == "pure heat transfer"
                   for o in analysis.Group)
    except Exception:
        pass
    return False


def _mesh_size(analysis):
    """(nodes, elements) of the study's mesh, (0, 0) before it is meshed."""
    try:
        group = list(analysis.Group)
    except Exception:
        return 0, 0
    for o in group:                      # one object that cannot answer (an assembly study's geometry) skips only itself
        try:
            if not o.isDerivedFrom("Fem::FemMeshObject"):
                continue
            m = o.FemMesh
            if m is not None and m.NodeCount:
                return m.NodeCount, (m.VolumeCount or m.FaceCount or m.EdgeCount)
        except Exception:
            continue
    return 0, 0


def _memory_k(proc):
    """The running solver's (or mesher's) memory in K, 0 when unknown."""
    try:
        if proc is None:
            return 0
        pid = int(proc.processId()) if hasattr(proc, "processId") else proc.pid
        if not pid:
            return 0
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(0x1000 | 0x0010, False, pid)      # QUERY_LIMITED_INFORMATION | VM_READ
            if not h:
                return 0
            try:
                c = PMC()
                c.cb = ctypes.sizeof(PMC)
                if not ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(c), c.cb):
                    return 0
                return int(c.PagefileUsage // 1024)
            finally:
                k32.CloseHandle(h)
        with open("/proc/%d/status" % pid) as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return 0


def _suspend(proc, on):
    """Stops (on) or lets go on the solver process. False when it cannot (no process running)."""
    pid = None
    try:
        if proc is None:
            return False
        if hasattr(proc, "processId"):            # QProcess
            pid = int(proc.processId())
        else:
            pid = proc.pid
        if not pid:
            return False
        if os.name == "nt":
            import ctypes
            k32, nt = ctypes.windll.kernel32, ctypes.windll.ntdll
            h = k32.OpenProcess(0x0800, False, pid)      # PROCESS_SUSPEND_RESUME
            if not h:
                return False
            try:
                (nt.NtSuspendProcess if on else nt.NtResumeProcess)(h)
            finally:
                k32.CloseHandle(h)
        else:
            import signal
            os.kill(pid, signal.SIGSTOP if on else signal.SIGCONT)
        return True
    except Exception as _fw_err:
        _fw_log("simrun.py:suspend", _fw_err)
        return False


def begin(analysis):
    """Opens the run window (nested runs share it). Returns True when this call opened it."""
    STATE["depth"] += 1
    if STATE["depth"] > 1:
        return False
    STATE.update(cancel=False, paused=False, proc=None, lines=[], start=time.time(), ccx={}, total=_total_time(analysis))
    try:
        STATE["study"] = (analysis.Document.Name, analysis.Name)
    except Exception:
        STATE["study"] = None
    if not _gui():
        return False
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        STATE["sub"] = mdi.activeSubWindow() if mdi is not None else None
    except Exception:
        STATE["sub"] = None
    try:
        w = RunWindow(analysis)
        STATE["window"] = w
        w.show()
        w.raise_()
        _pump()
    except Exception as _fw_err:
        _fw_log("simrun.py:begin", _fw_err)
    return True


def _total_time(analysis):
    """The solution's end time (s) of a time-stepped study (nonlinear, transient), else None."""
    try:
        for o in analysis.Group:
            if getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::SolverCcxTools":
                nonlinear = getattr(o, "GeometricalNonlinearity", "") == "nonlinear" or \
                    getattr(o, "MaterialNonlinearity", "") == "nonlinear" or getattr(o, "ThermoMechSteadyState", True) is False
                if nonlinear and "TimePeriod" in o.PropertiesList:
                    return float(App.Units.Quantity(o.TimePeriod).getValueAs("s").Value) or None
    except Exception as _fw_err:
        _fw_log("simrun.py:total", _fw_err)
    return None


def track(line):
    """CalculiX's step / increment / iteration lines -> (progress text, percent) for the run window, or (None, None)."""
    import re
    st = STATE.setdefault("ccx", {})
    low = line.strip().lower()
    m = re.match(r"step\s+(\d+)$", low)
    if m:
        st.update(step=int(m.group(1)), inc=None, it=None)
    m = re.match(r"increment\s+(\d+)\s+attempt\s+(\d+)", low)
    if m:
        st.update(inc=int(m.group(1)), attempt=int(m.group(2)), it=None)
    m = re.match(r"iteration\s+(\d+)", low)
    if m:
        st["it"] = int(m.group(1))
    m = re.match(r"actual (?:total|step) time\s*=\s*([-+0-9.eE]+)", low)
    if m:
        try:
            st["time"] = float(m.group(1))
        except ValueError:
            pass
    if st.get("inc") is None:
        return None, None
    parts = ["Step %d" % st.get("step", 1), "Increment %d" % st["inc"]]
    if st.get("attempt", 1) > 1:
        parts.append("attempt %d" % st["attempt"])
    if st.get("it"):
        parts.append("Iteration %d" % st["it"])
    total = STATE.get("total")
    pct = None
    if st.get("time") is not None:
        parts.append("Solution time: %.4g%s" % (st["time"], " of %.4g s" % total if total else " s"))
        if total:
            pct = 35 + 50.0 * max(0.0, min(1.0, st["time"] / total))
    return ", ".join(parts), pct


def end():
    STATE["depth"] = max(0, STATE["depth"] - 1)
    if STATE["depth"] > 0:
        return
    if STATE.get("study") is not None and STATE.get("lines"):
        took = int(time.time() - STATE.get("start", time.time()))
        MESSAGES[STATE["study"]] = "\n".join(STATE["lines"] + ["Total solution time: %02d:%02d:%02d"
                                                                 % (took // 3600, took // 60 % 60, took % 60)])
    STATE["study"] = None
    w = STATE.get("window")
    STATE.update(window=None, proc=None, paused=False)
    if w is not None:
        try:
            w.timer.stop()
            w.hide()
            w.deleteLater()
        except RuntimeError:
            pass
        _give_back()


def _give_back():
    """The 3D view active again as before the run (the modal window took the activation away from the MDI area,
    and the plots' legend and title look for the active view)."""
    sub, STATE["sub"] = STATE.get("sub"), None
    try:
        mw = Gui.getMainWindow()
        mw.activateWindow()
        mdi = mw.findChild(QtWidgets.QMdiArea)
        if mdi is not None and sub is not None and sub in mdi.subWindowList():
            mdi.setActiveSubWindow(sub)
        QtWidgets.QApplication.processEvents()
    except Exception as _fw_err:
        _fw_log("simrun.py:giveback", _fw_err)


def messages(analysis):
    """The study's last run messages, or None."""
    try:
        return MESSAGES.get((analysis.Document.Name, analysis.Name))
    except Exception:
        return None


def window():
    return STATE.get("window")


def stage(text, percent=None):
    """The stage line (and the bar) of the run window; the status bar too when there is no window."""
    w = STATE.get("window")
    if w is not None:
        try:
            w.stage.setText(text)
            w.set_task(text, None if text.startswith("Solving") else percent)
            p = STAGES.get(text, percent)
            if percent is not None:
                p = percent
            if p is not None:
                w.bar.setValue(int(max(w.bar.value(), min(100, p))))
        except RuntimeError:
            pass
    say(text)
    _pump()
    check_cancel()


def say(line):
    """A line of the solver's messages (More>>'s Warnings box shows the warnings; all are kept for Results > Solver Messages...)."""
    if line and STATE.get("depth", 0) > 0:
        STATE["lines"].append(line.rstrip("\n"))
        del STATE["lines"][:-4000]
    w = STATE.get("window")
    if w is not None and line and "warning" in line.lower():
        try:
            w.warn(line)                   # More>>'s Warnings box; every line is in Results > Solver Messages
        except RuntimeError:
            pass


def check_cancel():
    if STATE.get("cancel"):
        STATE["cancel"] = False
        raise Cancelled()


def _pump():
    if _gui():
        try:
            QtWidgets.QApplication.processEvents()
        except Exception as _fw_err:
            _fw_log("simrun.py:pump", _fw_err)


# CalculiX's progress lines -> what the stage line says
def _ccx_stage(line, step):
    s = line.strip()
    low = s.lower()
    if low.startswith("step "):
        return "Solving: step %s" % s.split()[-1], 35
    if low.startswith("increment") or " increment " in " %s " % low:
        return "Solving: %s" % s, None
    if "factoring" in low:
        return "Solving: factoring the equations", 55
    if "calculating the stress" in low or "stress calculation" in low:
        return "Solving: calculating stresses", 80
    if "eigenvalue" in low or "frequency" in low and "calculat" in low:
        return "Solving: eigenvalues", 60
    if low.startswith("job finished"):
        return "Solving: finished", 90
    return None, None


def _readers(p, out, err):
    def read(stream, into):
        try:
            for raw in iter(stream.readline, b""):
                into.append(raw)
        except Exception:
            pass
    ts = []
    for stream, into in ((p.stdout, out), (p.stderr, err)):
        if stream is not None:
            t = threading.Thread(target=read, args=(stream, into), daemon=True)
            t.start()
            ts.append(t)
    return ts


def run_process(args, cwd, env, label="Solving", timeout=None, merge=False, startupinfo=None):
    """Runs a solver process with the run window live. Returns (returncode, stdout bytes, stderr bytes); merge puts
    stderr into stdout. Cancel ends the process and raises Cancelled; a timeout ends it and raises TimeoutExpired."""
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000           # CREATE_NO_WINDOW: no console flashes up
    p = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT if merge else subprocess.PIPE, shell=False, **kw)
    STATE["proc"] = p
    out, err = [], []
    ts = _readers(p, out, err)
    seen = 0
    t0 = time.time()
    stage(label)
    try:
        while p.poll() is None:
            if STATE.get("cancel"):
                STATE["cancel"] = False
                _end(p)
                raise Cancelled()
            if timeout and time.time() - t0 > timeout and not STATE.get("paused"):
                _end(p)
                raise subprocess.TimeoutExpired(args, timeout)
            seen = _show_lines(out, seen, label)
            _pump()
            time.sleep(0.03)
        for t in ts:
            t.join(2.0)
        _show_lines(out, seen, label)
    finally:
        STATE["proc"] = None
    o, e = b"".join(out), b"".join(err)
    return p.returncode, o, e


def _show_lines(out, seen, label):
    n = len(out)
    for raw in out[seen:n]:
        line = raw.decode(errors="replace").rstrip()
        if not line.strip():
            continue
        say(line)
        text, pct = _ccx_stage(line, None)
        ptext, ppct = track(line)
        w = STATE.get("window")
        if ptext and w is not None:
            try:
                w.progress.setText(ptext)
                w.progress.show()
                if ppct is not None:
                    w.bar.setValue(max(w.bar.value(), int(ppct)))
            except RuntimeError:
                pass
        if text and w is not None:
            try:
                if not STATE.get("paused"):
                    w.stage.setText(text)
                    w.set_task(text)
                if pct is not None and not STATE.get("total"):     # a timed run's bar follows its time
                    w.bar.setValue(max(w.bar.value(), pct))
            except RuntimeError:
                pass
    return n


def _end(p):
    try:
        if STATE.get("paused"):
            _suspend(p, False)
            STATE["paused"] = False
        p.terminate()
        try:
            p.wait(5)
        except Exception:
            p.kill()
    except Exception as _fw_err:
        _fw_log("simrun.py:end", _fw_err)


def mesh(m):
    """Gmsh for the mesh object m with the window live (GmshTools' own QProcess, waited for by the event loop).
    Raises RuntimeError when Gmsh made no mesh."""
    from femmesh.gmshtools import GmshTools

    part = getattr(getattr(m, "Shape", None), "Label", "") or getattr(m, "Label", "")
    stage("Meshing: %s (1 of 1)" % part if part else "Meshing", 0)
    t = GmshTools(m)
    if not _gui():
        t.create_mesh()
    else:
        t.run(False)
        STATE["proc"] = t.process
        try:
            proc = t.process
            from PySide import QtCore as _QC
            while proc.state() != _QC.QProcess.NotRunning:
                if STATE.get("cancel"):
                    STATE["cancel"] = False
                    proc.kill()
                    proc.waitForFinished(3000)
                    raise Cancelled()
                try:
                    data = bytes(proc.readAllStandardOutput()) + bytes(proc.readAllStandardError())
                    for line in data.decode(errors="replace").splitlines():
                        if line.strip():
                            say(line)
                except Exception:
                    pass
                _pump()
                time.sleep(0.03)
            _pump()
        finally:
            STATE["proc"] = None
    try:
        ok = bool(m.FemMesh.NodeCount)
    except Exception:
        ok = False
    if not ok:
        raise RuntimeError("Meshing failed: Gmsh made no mesh of %s." % getattr(getattr(m, "Shape", None), "Label", "the part"))
    say("Mesh: %d nodes, %d elements" % (m.FemMesh.NodeCount, m.FemMesh.VolumeCount or m.FemMesh.FaceCount))
