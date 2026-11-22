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
from PySide import QtCore, QtGui, QtWidgets

from . import evaluate, pmboxes

V = App.Vector
PREFIX = "SWEval"
_open = [None]          # the panel in the task pane now
_kept = {}              # tool name -> window whose colours / overlay stay shown after OK


def _group(title, *items):
    """A page group: a widget whose window title is the group's title (the task view draws it)."""
    page = QtWidgets.QWidget()
    page.setWindowTitle(title)
    lay = QtWidgets.QVBoxLayout(page)
    lay.setContentsMargins(6, 2, 6, 4)
    lay.setSpacing(3)
    for item in items:
        if item is None:
            continue
        if isinstance(item, str):
            lay.addWidget(QtWidgets.QLabel(item, page))
        elif isinstance(item, QtWidgets.QLayout):
            lay.addLayout(item)
        elif isinstance(item, (tuple, list)):
            row = QtWidgets.QHBoxLayout()
            for w in item:
                if isinstance(w, str):
                    row.addWidget(QtWidgets.QLabel(w, page))
                elif w is None:
                    row.addStretch(1)
                else:
                    row.addWidget(w)
                    w.show()            # a control moved out of the hidden window
            lay.addLayout(row)
        else:
            lay.addWidget(item)
            item.show()
    return page


def _hide_all(layout):
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget()
        if w is not None:
            w.hide()
        elif item.layout() is not None:
            _hide_all(item.layout())


class _Box(QtWidgets.QListWidget):
    ""

    def __init__(self, panel, key, name, tip, height=26):
        super().__init__()
        self.panel, self.key = panel, key
        self.setObjectName(name)
        self.setFixedHeight(height)
        self.setToolTip(tip)
        self.installEventFilter(self)
        self.viewport().installEventFilter(self)
        pmboxes.bind(self, lambda row, p=panel, k=key: p.remove_pick(k, row), lambda p=panel, k=key: p.clear_picks(k))

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.active = self.key
            self.panel.show_boxes()
        return False


class _Observer:
    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, doc, obj, sub, pnt):
        if getattr(self.panel.win, "row_picking", False):
            return
        QtCore.QTimer.singleShot(0, self.panel.picked)


class EvalPanel:
    ""
    NAME = ""                   # command name
    TITLE = ""
    ICON = ""
    BOXES = ()                  # (key, label, tip, accepts) accepts: callable(obj, sub) -> bool
    NEEDED = ()                 # keys the tool cannot run without

    def __init__(self, win):
        self.win = win
        win.hide()
        self.picks = {key: [] for key, *_ in self.BOXES}
        self.boxes = {}
        self.active = self.BOXES[0][0] if self.BOXES else None
        self.form = self.build()
        for page in self.form or []:
            for spin in page.findChildren(QtWidgets.QAbstractSpinBox):
                spin.setKeyboardTracking(False)     # the tool reruns on a change: take a typed value once finished
        if self.form:
            self.form[0].setProperty("swstyle_pm_icon", self.ICON)
            self.form[0].setProperty("swstyle_pm_title", self.TITLE)
        self.observer = _Observer(self)
        Gui.Selection.addObserver(self.observer)
        self.closed = False
        self.seed_from_selection()
        self.show_boxes()

    # ---------------------------------------------------------------- building
    def build(self):
        raise NotImplementedError

    def box(self, key):
        label, tip, _accepts = [(l, t, a) for k, l, t, a in self.BOXES if k == key][0]
        b = _Box(self, key, "%s_%s_%s" % (PREFIX, type(self).__name__, key), tip)
        self.boxes[key] = b
        return b

    def results(self, *extra):
        ""
        win = self.win
        items = []
        if win.table is not None:
            win.table.setFixedHeight(120)
            items.append(win.table)
        if win.text is not None:
            win.text.setFixedHeight(120)
            items.append(win.text)
        items.extend(extra)
        items.append(win.summary)
        win.summary.setWordWrap(True)
        row = [win.copy, None]
        save = getattr(win, "save", None)
        if save is not None:
            row.insert(1, save)
        items.append(row)
        return _group("Results", *items)

    # ---------------------------------------------------------------- picks
    def seed_from_selection(self):
        ""
        for sel in Gui.Selection.getSelectionEx():
            subs = [s for s in sel.SubElementNames if s] or [""]
            for sub in subs:
                self.take(sel.Object, sub, refresh=False)

    def accepts(self, key, obj, sub):
        for k, _l, _t, accepts in self.BOXES:
            if k == key:
                return accepts(obj, sub)
        return False

    def take(self, obj, sub, refresh=True):
        key = self.active
        if key is None or not self.accepts(key, obj, sub):
            # a pick the active box refuses goes to the first box that takes it
            for k, _l, _t, accepts in self.BOXES:
                if accepts(obj, sub):
                    key = k
                    break
            else:
                return False
        single = self.single(key)
        if single:
            self.picks[key] = [(obj, sub)]
        elif (obj, sub) not in self.picks[key]:
            self.picks[key].append((obj, sub))
        else:
            self.picks[key].remove((obj, sub))
        if refresh:
            self.refresh()
        return True

    def single(self, key):
        return True

    def _gone(self):
        """The page was closed from outside (FreeCAD's closeDialog, another command) without its own close:
        its boxes are deleted. It lets go of the selection then, instead of failing on every pick."""
        try:
            for box in self.boxes.values():
                box.count()
            return False
        except RuntimeError:
            self.closed = True
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("evalpanel.py:216", _fw_err)
            if _open[0] is self:
                _open[0] = None
            return True

    def picked(self):
        if self.closed or _open[0] is not self or self._gone():
            return
        try:
            selection = Gui.Selection.getSelectionEx()
        except Exception:
            return
        if not selection:
            return
        entry = selection[-1]
        subs = [s for s in entry.SubElementNames if s]
        sub = subs[-1] if subs else ""
        if self.take(entry.Object, sub, refresh=False):
            self.refresh()
            QtCore.QTimer.singleShot(0, Gui.Selection.clearSelection)
        self.show_boxes()

    def remove_pick(self, key, row):
        if 0 <= row < len(self.picks[key]):
            self.picks[key].pop(row)
            self.refresh()

    def clear_picks(self, key):
        self.picks[key] = []
        self.refresh()

    def show_boxes(self):
        for key, box in self.boxes.items():
            box.clear()
            for obj, sub in self.picks[key]:
                box.addItem("%s%s" % (obj.Label, (": " + sub) if sub else ""))
            pmboxes.mark(box, self.active == key, need=key in self.NEEDED and not self.picks[key])

    def select_picks(self, key):
        """The box's picks put into the selection for the window's compute (it reads the selection)."""
        Gui.Selection.clearSelection()
        for obj, sub in self.picks.get(key, []):
            try:
                Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)
            except Exception as _fw_err:
                _fw_log("evalpanel.py:261", _fw_err)

    # ---------------------------------------------------------------- running
    def refresh(self):
        self.show_boxes()
        try:
            self.compute()
        except Exception as error:
            self.win.summary.setText("Could not compute: %s" % error)

    def compute(self):
        self.win.refresh()

    def keep(self):
        ""
        _kept[self.NAME] = self.win

    # ---------------------------------------------------------------- dialog
    def getStandardButtons(self):
        buttons = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        try:
            return int(buttons)
        except TypeError:
            return buttons.value

    def _close(self):
        self.closed = True
        try:
            Gui.Selection.removeObserver(self.observer)
        except Exception as _fw_err:
            _fw_log("evalpanel.py:291", _fw_err)
        if _open[0] is self:
            _open[0] = None
        Gui.Control.closeDialog()

    def accept(self):
        self.keep()
        self._close()
        return True

    def reject(self):
        try:
            self.win.cleanup()
        except Exception as _fw_err:
            _fw_log("evalpanel.py:305", _fw_err)
        self._close()
        return True


def _is_pull(obj, sub):
    """A planar face, a straight edge, or a plane: a direction of pull."""
    try:
        if sub.startswith("Face"):
            return obj.Shape.getElement(sub).Surface.__class__.__name__ == "Plane"
        if sub.startswith("Edge"):
            return obj.Shape.getElement(sub).Curve.__class__.__name__ in ("Line", "LineSegment")
        return (not sub) and (obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane")
                              or obj.isDerivedFrom("App::Line") or obj.isDerivedFrom("PartDesign::Line"))
    except Exception:
        return False


def _is_edge(obj, sub):
    return sub.startswith("Edge")


def _is_body(obj, sub):
    try:
        return bool(evaluate._solids_of(obj if obj.getParentGeoFeatureGroup() is None else obj.getParentGeoFeatureGroup()))
    except Exception:
        return bool(getattr(getattr(obj, "Shape", None), "Solids", None))


def _is_plane(obj, sub):
    try:
        if sub.startswith("Face"):
            return obj.Shape.getElement(sub).Surface.__class__.__name__ == "Plane"
        return (not sub) and (obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane"))
    except Exception:
        return False


class _PullPanel(EvalPanel):
    """The tools with a Direction of Pull box: the window takes the pull from the selection."""
    PULL_KEY = "pull"

    def compute(self):
        if self.picks.get(self.PULL_KEY):
            self.select_picks(self.PULL_KEY)
        else:
            Gui.Selection.clearSelection()
        self.win.refresh()
        Gui.Selection.clearSelection()


# ---------------------------------------------------------------------------- Draft Analysis
class DraftPanel(_PullPanel):
    NAME = "SWStyle_DraftAnalysis"
    TITLE = "Draft Analysis"
    ICON = "I3DVIEW_DRAFT_ANALYSIS"
    BOXES = (("pull", "Direction of Pull", "A planar face, a straight edge or a plane: the direction the mould pulls", _is_pull),)

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        win.angle.setObjectName(PREFIX + "DraftAngle")
        win.reverse.setText("Reverse Direction")
        win.reverse.setObjectName(PREFIX + "DraftReverse")
        win.recalc.setObjectName(PREFIX + "DraftCalculate")
        self.triad = QtWidgets.QCheckBox("Adjust Triad")
        self.triad.setObjectName(PREFIX + "DraftTriad")
        self.triad.setToolTip("Shows the direction of pull as an arrow on the part")
        self.triad.toggled.connect(self._triad)
        self.arrow = evaluate.Overlay()

        # button and no results list, the face counts sit beside the colours (Color Settings)
        win.recalc.hide()
        win.reverse.toggled.connect(lambda _on: self._triad(self.triad.isChecked()))
        params = _group("Analysis Parameters", "Direction of Pull:", self.box("pull"), win.reverse,
                        ["Draft Angle:", win.angle], self.triad)
        win.classify.setObjectName(PREFIX + "DraftClassify")
        win.steep.setObjectName(PREFIX + "DraftSteep")
        win.gradual.setObjectName(PREFIX + "DraftGradual")
        colours = _group("Color Settings", win.classify, win.steep, win.gradual, win.classes)
        win.gradual.setVisible(not win.classify.isChecked())      # only without Face classification (not greyed)
        win.classes.setTitle("")
        win.classes.setFlat(True)
        return [params, colours]

    def compute(self):
        super().compute()
        self._triad(self.triad.isChecked())

    def _triad(self, on):
        self.arrow.clear()
        if not on:
            return
        try:
            import Part
            objs = evaluate.visible_bodies()
            if not objs:
                return
            box = objs[0].Shape.BoundBox
            d = self.win.pull * (-1.0 if self.win.reverse.isChecked() else 1.0)
            start = V(box.Center)
            length = box.DiagonalLength * 0.6 or 10.0
            tip = start + d * length
            head = tip - d * length * 0.15
            side = V(0, 0, 1).cross(d)
            if side.Length < 1e-6:
                side = V(1, 0, 0).cross(d)
            side = side.normalize() * length * 0.05
            shape = Part.makeCompound([Part.makeLine(start, tip), Part.makeLine(tip, head + side),
                                       Part.makeLine(tip, head - side)])
            self.arrow.add(shape, (0.1, 0.5, 1.0), 0.0)
        except Exception as error:
            App.Console.PrintLog("Draft Analysis triad: %s\n" % error)

    def reject(self):
        self.arrow.clear()
        return super().reject()

    def accept(self):
        self.arrow.clear()
        return super().accept()


# ---------------------------------------------------------------------------- Undercut Analysis
class UndercutPanel(_PullPanel):
    NAME = "SWStyle_UndercutAnalysis"
    TITLE = "Undercut Analysis"
    ICON = "I3DVIEW_UNDERCUT_ANALYSIS"
    BOXES = (("pull", "Direction of Pull", "A planar face, a straight edge or a plane: the direction the mould pulls", _is_pull),
             ("line", "Parting Line", "The edges of the parting line: faces above it are judged against direction 1, below it against direction 2", _is_edge))

    def single(self, key):
        return key == "pull"

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        win.by_dir.setObjectName(PREFIX + "UndercutByDirection")
        win.by_line.setObjectName(PREFIX + "UndercutByLine")
        win.reverse.setText("Reverse Direction")
        win.reverse.setObjectName(PREFIX + "UndercutReverse")
        win.recalc.setObjectName(PREFIX + "UndercutCalculate")
        self.line_label = QtWidgets.QLabel("Parting Line:")
        params = _group("Analysis Parameters", win.by_dir, win.by_line, "Direction of Pull:", self.box("pull"),
                        self.line_label, self.box("line"), win.reverse, [win.recalc, None])
        win.by_line.toggled.connect(self._mode)
        self._mode(win.by_line.isChecked())
        win.classes.setTitle("")
        win.classes.setFlat(True)
        return [params, _group("Undercut Faces", win.classes), self.results()]

    def _mode(self, by_line):
        for w in (self.line_label, self.boxes["line"]):
            w.setVisible(by_line)
        self.active = "line" if by_line else "pull"
        self.show_boxes()

    def compute(self):
        if self.win.by_line.isChecked():
            self.select_picks("line")
            self.win.refresh()
            Gui.Selection.clearSelection()
        else:
            super().compute()


# ---------------------------------------------------------------------------- Parting Line Analysis
class PartingLinePanel(_PullPanel):
    NAME = "SWStyle_PartingLineAnalysis"
    TITLE = "Parting Line Analysis"
    ICON = "MOLD_PARTING_LINE_ANALYSIS"
    BOXES = (("pull", "Direction of Pull", "A planar face, a straight edge or a plane: the direction the mould pulls", _is_pull),)

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        win.reverse.setText("Reverse Direction")
        win.reverse.setObjectName(PREFIX + "PartingReverse")
        win.recalc.setObjectName(PREFIX + "PartingCalculate")
        params = _group("Mold Parameters", "Direction of Pull:", self.box("pull"), win.reverse,
                        ["Draft Angle:", win.angle], [win.recalc, None])
        self.edges = QtWidgets.QListWidget()
        self.edges.setObjectName(PREFIX + "PartingEdges")
        self.edges.setFixedHeight(80)
        self.edges.setToolTip("The edges the parting line runs along; a row selects its edge")
        self.edges.itemSelectionChanged.connect(self._edge_row)
        return [params, _group("Parting Lines", self.edges), self.results()]

    def compute(self):
        super().compute()
        self.edges.clear()
        for name, (_kinds, line) in getattr(self.win, "found", {}).items():
            obj = App.ActiveDocument.getObject(name) if App.ActiveDocument else None
            for k in line:
                self.edges.addItem("%s: Edge%d" % (obj.Label if obj is not None else name, k + 1))

    def _edge_row(self):
        items = self.edges.selectedItems()
        if not items:
            return
        label, _sep, sub = items[0].text().partition(": ")
        for obj in evaluate.visible_bodies():
            if obj.Label == label:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)
                return


# ---------------------------------------------------------------------------- Thickness Analysis
class ThicknessPanel(EvalPanel):
    NAME = "SWStyle_ThicknessAnalysis"
    TITLE = "Thickness Analysis"
    ICON = "I3DVIEW_THICKNESS_ANALYSIS"
    BOXES = (("bodies", "Faces or Bodies", "The bodies to analyse (none: every visible body)", _is_body),)

    def single(self, key):
        return False

    def build(self):
        from . import evalpm
        win = self.win
        _hide_all(win.layout_)
        win.recalc.setObjectName(PREFIX + "ThicknessCalculate")
        win.limit.setObjectName(PREFIX + "ThicknessLimit")
        self.resolution = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.resolution.setObjectName(PREFIX + "ThicknessResolution")
        self.resolution.setRange(0, 2)
        self.resolution.setValue(list(evalpm.RESOLUTION).index(win.resolution.currentText()))
        self.resolution.setToolTip("Resolution: Low, Medium or High (finer sampling takes longer)")
        self.resolution.valueChanged.connect(lambda v: win.resolution.setCurrentIndex(v))
        win.corners.setObjectName(PREFIX + "ThicknessCorners")
        params = _group("Analysis Parameters", "Faces or Bodies to analyse:", self.box("bodies"),
                        ["Target thickness:", win.target], win.thin, win.thick,
                        ["Thick region limit:", win.limit], ["Resolution:", self.resolution], win.corners, [win.recalc, None])
        win.full.setObjectName(PREFIX + "ThicknessFullRange")
        win.continuous.setObjectName(PREFIX + "ThicknessContinuous")
        win.discrete.setObjectName(PREFIX + "ThicknessDiscrete")
        win.ncolours.setObjectName(PREFIX + "ThicknessColors")
        colours = _group("Color Settings", win.full, [win.continuous, win.discrete], win.ncolours)

        self.limit_label = [l for l in params.findChildren(QtWidgets.QLabel) if l.text() == "Thick region limit:"][0]
        win.thick.toggled.connect(self._limit_shown)
        self._limit_shown(win.thick.isChecked())
        return [params, colours, self.results()]

    def _limit_shown(self, thick):
        for w in (self.limit_label, self.win.limit):
            w.setVisible(thick)

    def compute(self):
        if self.picks["bodies"]:
            self.select_picks("bodies")
        else:
            Gui.Selection.clearSelection()      # no pick: every visible body
        self.win.refresh()
        Gui.Selection.clearSelection()


# ---------------------------------------------------------------------------- Geometry Analysis
class GeometryPanel(EvalPanel):
    ""

    NAME = "SWStyle_GeometryAnalysis"
    TITLE = "Geometry Analysis"
    ICON = "TOOLS_GEOM_ANALYSIS"
    BOXES = (("bodies", "Bodies", "The bodies to check (none: every visible body)", _is_body),)

    def single(self, key):
        return False

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        checks = win.findChild(QtWidgets.QGroupBox)
        checks.setTitle("")
        checks.setFlat(True)
        checks.show()
        win.recalc.setText("Calculate")
        win.recalc.setObjectName(PREFIX + "GeometryCalculate")
        win.reset.setObjectName(PREFIX + "GeometryReset")
        params = _group("Analysis Parameters", "Bodies to check:", self.box("bodies"), checks, [win.recalc, None])
        results = self.results(win.reset)
        results.setWindowTitle("Analysis Results")
        return [params, results]

    def compute(self):
        if self.picks["bodies"]:
            self.select_picks("bodies")
        self.win.refresh()
        Gui.Selection.clearSelection()


# ---------------------------------------------------------------------------- Deviation Analysis
class DeviationPanel(EvalPanel):
    NAME = "SWStyle_DeviationAnalysis"
    TITLE = "Deviation Analysis"
    ICON = "I3DVIEW_DEVIATION_ANALYSIS"
    BOXES = (("edges", "Edges", "The edges between faces to check (the deviation of the faces' normals along them)", _is_edge),)
    NEEDED = ("edges",)

    def single(self, key):
        return False

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        win.samples.setObjectName(PREFIX + "DeviationSamples")
        win.recalc.setObjectName(PREFIX + "DeviationCheck")
        self.boxes_group = _group("Edges", self.box("edges"), ["Number of sample points:", win.samples], [win.recalc, None])
        self.maximum = QtWidgets.QLabel("Maximum deviation: -")
        self.maximum.setObjectName(PREFIX + "DeviationMaximum")
        self.minimum = QtWidgets.QLabel("Minimum deviation: -")
        self.average = QtWidgets.QLabel("Average deviation: -")
        return [self.boxes_group, _group("Analysis Results", self.maximum, self.minimum, self.average, win.table, win.summary, [win.copy, None])]

    def compute(self):
        self.win.picks = list(self.picks["edges"])
        Gui.Selection.clearSelection()
        self.win.refresh()
        vals = getattr(self.win, "values", [])
        if vals:
            self.maximum.setText("Maximum deviation: %.4f deg" % max(vals))
            self.minimum.setText("Minimum deviation: %.4f deg" % min(vals))
            self.average.setText("Average deviation: %.4f deg" % (sum(vals) / len(vals)))
        else:
            for w, t in ((self.maximum, "Maximum"), (self.minimum, "Minimum"), (self.average, "Average")):
                w.setText("%s deviation: -" % t)


# ---------------------------------------------------------------------------- Symmetry Check
class SymmetryPanel(EvalPanel):
    NAME = "SWStyle_SymmetryCheck"
    TITLE = "Symmetry Check"
    ICON = "TOOLS_SYM_CHECK"
    BOXES = (("plane", "Symmetry Plane", "A plane or a planar face the part should be symmetric about", _is_plane),
             ("bodies", "Bodies to Check", "The bodies to check (none: every visible body)", _is_body))

    def single(self, key):
        return key == "plane"

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        win.plane.setObjectName(PREFIX + "SymmetryPlaneList")
        win.recalc.setObjectName(PREFIX + "SymmetryCheck")
        self.manual = QtWidgets.QRadioButton("Manual Face Check")
        self.manual.setObjectName(PREFIX + "SymmetryManual")
        self.manual.setChecked(True)
        self.automatic = QtWidgets.QRadioButton("Automatic Symmetry Split")
        self.automatic.setObjectName(PREFIX + "SymmetryAutomatic")
        self.automatic.setToolTip("Finds the symmetry plane among the three main planes")
        self.automatic.toggled.connect(self._auto)
        options = _group("Options", self.manual, self.automatic)
        plane = _group("Symmetry Plane", win.plane, self.box("plane"))
        bodies = _group("Bodies", self.box("bodies"), win.bodies)
        win.rows_box.setTitle("")
        win.rows_box.setFlat(True)
        win.plane.activated.connect(lambda _i: self.manual.setChecked(True))     # a plane chosen by hand: manual
        return [options, plane, bodies, _group("Results", win.rows_box, win.table, win.summary, [win.recalc, win.copy, None])]

    def _auto(self, on):
        """Automatic Symmetry Split stays chosen: each Check finds the main plane with the most symmetric faces."""
        if on:
            self.picks["plane"] = []
            self.show_boxes()
            self.refresh()

    def take(self, obj, sub, refresh=True):
        took = super().take(obj, sub, refresh=False)
        if took and self.picks["plane"] and self.automatic.isChecked():
            self.manual.setChecked(True)        # a plane picked: the check is about that plane
        if took and refresh:
            self.refresh()
        return took

    def _best_plane(self):
        best = None
        for i in range(3):
            self.win.plane.blockSignals(True)
            self.win.plane.setCurrentIndex(i)
            self.win.plane.blockSignals(False)
            self.select_picks("bodies")
            self.win.refresh()
            score = getattr(self.win, "counts", {}).get("symmetric", 0)
            if best is None or score > best[0]:
                best = (score, i)
        self.win.plane.blockSignals(True)
        self.win.plane.setCurrentIndex(best[1])
        self.win.plane.blockSignals(False)

    def compute(self):
        if self.picks["plane"]:
            self.win.plane.blockSignals(True)
            self.win.plane.setCurrentIndex(3)
            self.win.plane.blockSignals(False)
            self.select_picks("plane")
            for obj, sub in self.picks["bodies"]:
                try:
                    Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)
                except Exception as _fw_err:
                    _fw_log("evalpanel.py:679", _fw_err)
        else:
            if self.automatic.isChecked():
                self._best_plane()
            elif self.win.plane.currentIndex() == 3:
                self.win.plane.blockSignals(True)
                self.win.plane.setCurrentIndex(2)
                self.win.plane.blockSignals(False)
            self.select_picks("bodies")
        self.win.refresh()
        Gui.Selection.clearSelection()


# ---------------------------------------------------------------------------- Interference Detection
class InterferencePanel(EvalPanel):
    NAME = "SWStyle_InterferenceDetection"
    TITLE = "Interference Detection"
    ICON = "ASSEMBLIES_INTERFERENCE_DETECTION"
    BOXES = (("bodies", "Selected Bodies", "The bodies to check against each other (none: every visible body)", _is_body),)

    def single(self, key):
        return False

    def build(self):
        win = self.win
        _hide_all(win.layout_)
        win.recalc.setObjectName(PREFIX + "InterferenceCalculate")
        selected = _group("Selected Bodies", self.box("bodies"), [win.recalc, None])
        self.ignore = QtWidgets.QPushButton("Ignore")
        self.ignore.setObjectName(PREFIX + "InterferenceIgnore")
        self.ignore.setToolTip("Leaves the selected interference out of the results")
        self.ignore.clicked.connect(self._ignore)
        self.ignored = set()
        results = _group("Results", win.table, win.summary, [self.ignore, win.copy, None])
        self.coincidence = QtWidgets.QCheckBox("Treat coincidence as interference")
        self.coincidence.setObjectName(PREFIX + "InterferenceCoincidence")
        self.coincidence.setToolTip("Bodies that touch without overlapping are listed too")
        self.show_ignored = QtWidgets.QCheckBox("Show ignored interferences")
        self.show_ignored.setObjectName(PREFIX + "InterferenceShowIgnored")
        self.transparent = QtWidgets.QCheckBox("Make interfering parts transparent")
        self.transparent.setObjectName(PREFIX + "InterferenceTransparent")
        self.transparent.setChecked(True)
        self.hidden = QtWidgets.QCheckBox("Ignore hidden bodies")
        self.hidden.setObjectName(PREFIX + "InterferenceIgnoreHidden")
        self.hidden.setChecked(True)
        for w in (self.coincidence, self.show_ignored, self.transparent, self.hidden):
            w.toggled.connect(lambda on: self.refresh())
        options = _group("Options", self.coincidence, self.show_ignored, self.transparent, self.hidden)
        self.non = {}
        self.saved = {}         # object -> (DisplayMode, Transparency, Visibility)
        self.found = []
        non = QtWidgets.QWidget()
        non.setWindowTitle("Non-interfering Bodies")
        lay = QtWidgets.QVBoxLayout(non)
        lay.setContentsMargins(6, 2, 6, 4)
        for key, text in (("Wireframe", "Wireframe"), ("Hidden", "Hidden"), ("Transparent", "Transparent"), ("Current", "Use current")):
            r = QtWidgets.QRadioButton(text)
            r.setObjectName(PREFIX + "InterferenceNon" + key)
            r.toggled.connect(lambda on: on and self._paint())
            lay.addWidget(r)
            self.non[key] = r
        self.non["Current"].setChecked(True)
        return [selected, results, options, non]

    def _bodies(self):
        if self.picks["bodies"]:
            out = []
            for obj, _sub in self.picks["bodies"]:
                body = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
                top = body if body is not None and body.isDerivedFrom("PartDesign::Body") else obj
                if top not in out:
                    out.append(top)
            return out
        if self.hidden.isChecked():
            return evaluate.visible_bodies()
        doc = App.ActiveDocument
        out = []
        for obj in (doc.Objects if doc else []):
            if obj.isDerivedFrom("PartDesign::Body") or (obj.isDerivedFrom("Part::Feature") and obj.getParentGeoFeatureGroup() is None):
                try:
                    if obj.Shape.Solids and obj not in out:
                        out.append(obj)
                except Exception as _fw_err:
                    _fw_log("evalpanel.py:760", _fw_err)
        return out

    def compute(self):
        win = self.win
        win.overlay.clear()
        objs = self._bodies()
        found = list(evaluate.interferences(objs))
        if self.coincidence.isChecked():
            items = [(o.Label, o, o.Shape) for o in objs]
            seen = {(a[1].Name, b[1].Name) for a, b, _c in found}
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    a, b = items[i], items[j]
                    if (a[1].Name, b[1].Name) in seen:
                        continue
                    try:
                        # bodies that touch: any overlap with volume is already in found, so these are
                        # coincident only (no second boolean on touching faces, a slow case for OCC)
                        near = App.BoundBox(a[2].BoundBox)
                        near.enlarge(1e-6)
                        if near.intersect(b[2].BoundBox) and a[2].distToShape(b[2])[0] < 1e-6:
                            import Part
                            found.append((a, b, Part.Shape()))
                    except Exception as _fw_err:
                        _fw_log("evalpanel.py:781", _fw_err)
        self.found = found
        rows = []
        for k, (a, b, common) in enumerate(found):
            key = (a[1].Name, b[1].Name)
            ignored = key in self.ignored
            if ignored and not self.show_ignored.isChecked():
                continue
            if not ignored and not common.isNull() and common.Volume > 1e-9:
                win.overlay.add(common)
            doc = a[1].Document.Name

            volume = evaluate._f(evaluate.in_doc(common.Volume, 3), 4 if evaluate.doc_unit()[1] > 1 else 2) \
                if not common.isNull() else "0.00"
            name = "Interference%d: %s, %s" % (k + 1, a[0], b[0])
            if common.isNull() or common.Volume <= 1e-9:
                name += " (coincident)"
            if ignored:
                name += " (ignored)"
            rows.append(((name, volume), [(doc, a[1].Name, ""), (doc, b[1].Name, "")]))
        win.set_rows(rows)
        live = [f for f in found if (f[0][1].Name, f[1][1].Name) not in self.ignored]
        win.summary.setText("%d bodies checked. %s" % (
            len(objs), "No interferences." if not live else "%d interference%s, shown in red." % (len(live), "" if len(live) == 1 else "s")))
        self._paint()

    def _ignore(self):
        items = self.win.table.selectedItems()
        if not items:
            return
        i = self.win.table.indexOfTopLevelItem(items[0])
        shown = [f for f in self.found if self.show_ignored.isChecked() or (f[0][1].Name, f[1][1].Name) not in self.ignored]
        if 0 <= i < len(shown):
            key = (shown[i][0][1].Name, shown[i][1][1].Name)
            if key in self.ignored:
                self.ignored.discard(key)
            else:
                self.ignored.add(key)
            self.refresh()

    def _paint(self):
        """Interfering bodies transparent; the others as the Non-interfering Bodies choice says."""
        self._restore()
        interfering = set()
        for a, b, _c in self.found:
            if (a[1].Name, b[1].Name) not in self.ignored:
                interfering.update((a[1], b[1]))
        mode = [k for k, r in self.non.items() if r.isChecked()]
        mode = mode[0] if mode else "Current"
        for obj in self._bodies():
            vo = getattr(obj, "ViewObject", None)
            if vo is None:
                continue
            try:
                self.saved[obj] = (vo.DisplayMode, vo.Transparency, vo.Visibility)
                if obj in interfering:
                    if self.transparent.isChecked():
                        vo.Transparency = 70
                elif mode == "Wireframe":
                    vo.DisplayMode = "Wireframe"
                elif mode == "Hidden":
                    vo.Visibility = False
                elif mode == "Transparent":
                    vo.Transparency = 70
            except Exception as _fw_err:
                _fw_log("evalpanel.py:844", _fw_err)

    def _restore(self):
        for obj, (mode, transparency, visible) in self.saved.items():
            try:
                vo = obj.ViewObject
                vo.DisplayMode, vo.Transparency, vo.Visibility = mode, transparency, visible
            except Exception as _fw_err:
                _fw_log("evalpanel.py:852", _fw_err)
        self.saved = {}

    def accept(self):
        self._restore()
        return super().accept()

    def reject(self):
        self._restore()
        return super().reject()


# ---------------------------------------------------------------------------- Zebra Stripes
class ZebraPanel(EvalPanel):
    NAME = "SWStyle_ZebraStripes"
    TITLE = "Zebra Stripes"
    ICON = "I3DVIEW_ZEBRA"
    BOXES = ()

    def build(self):
        from . import evalpm
        self.start = evalpm.zebra_settings()        # Cancel puts these back (OK keeps the changes)
        win = self.win
        lay = win.layout()
        rows = []
        for i in range(lay.rowCount()):
            label = lay.itemAt(i, QtWidgets.QFormLayout.LabelRole)
            field = lay.itemAt(i, QtWidgets.QFormLayout.FieldRole)
            span = lay.itemAt(i, QtWidgets.QFormLayout.SpanningRole)
            widgets = [it.widget() for it in (label, field, span) if it is not None and it.widget() is not None]
            rows.append(widgets)
        win.stripes.setObjectName(PREFIX + "ZebraStripes")
        win.width.setObjectName(PREFIX + "ZebraWidth")
        win.precision.setObjectName(PREFIX + "ZebraPrecision")
        win.horizontal.setObjectName(PREFIX + "ZebraHorizontal")
        win.vertical.setObjectName(PREFIX + "ZebraVertical")
        win.spherical.setObjectName(PREFIX + "ZebraSpherical")
        items = []
        for widgets in rows:
            if any(isinstance(w, QtWidgets.QPushButton) and w.text() == "OK" for w in widgets):
                for w in widgets:
                    w.hide()
                continue
            items.append(widgets if len(widgets) > 1 else widgets[0])
        return [_group("Settings", *items)]

    def compute(self):
        self.win.apply()

    def accept(self):
        self.win.apply()
        self.keep()
        self._close()
        return True

    def reject(self):
        from . import evaluate2, evalpm
        try:
            p, st = evalpm._p(), self.start
            p.SetInt("ZebraStripes", st["stripes"]); p.SetInt("ZebraWidth", st["width"])
            p.SetInt("ZebraPrecision", st["precision"]); p.SetBool("ZebraVertical", st["vertical"])
            p.SetBool("ZebraSpherical", st["spherical"]); p.SetString("ZebraStripeColor", st["stripe"])
            p.SetString("ZebraBackground", st["background"])
        except Exception as _fw_err:
            _fw_log("evalpanel.py:zebra", _fw_err)
        try:
            evaluate2.ZEBRA.hide()
        except Exception as _fw_err:
            _fw_log("evalpanel.py:909", _fw_err)
        self._close()
        return True


# ---------------------------------------------------------------------------- opening
def _window_factory(name):
    from . import evalpm
    if name == "SWStyle_DraftAnalysis":
        return evalpm.DraftWindow
    if name == "SWStyle_UndercutAnalysis":
        return evalpm._undercut_window()
    if name == "SWStyle_ThicknessAnalysis":
        return evalpm._thickness_window()
    if name == "SWStyle_DeviationAnalysis":
        return evalpm._deviation_window()
    if name == "SWStyle_SymmetryCheck":
        return evalpm.SymmetryWin
    if name == "SWStyle_InterferenceDetection":
        return evaluate.InterferenceWindow
    if name == "SWStyle_PartingLineAnalysis":
        from . import partingline
        return partingline.PartingLineWindow
    if name == "SWStyle_ZebraStripes":
        return evalpm.ZebraPM
    if name == "SWStyle_GeometryAnalysis":
        return evalpm.GeometryWindow
    return None


PANELS = {cls.NAME: cls for cls in (DraftPanel, UndercutPanel, PartingLinePanel, ThicknessPanel, DeviationPanel, GeometryPanel,
                                     SymmetryPanel, InterferencePanel, ZebraPanel)}


def current():
    return _open[0]


def _forget_stale():
    """A page closed without its OK or Cancel (the document closed, another tool or a macro closed the
    task dialog) is still remembered as open: forget it and put the part back, so the next click on
    the tool opens it at once instead of being taken as the click that closes it."""
    panel = _open[0]
    if panel is None or (Gui.Control.activeDialog() and not getattr(panel, "closed", False)):
        return
    _open[0] = None
    panel.closed = True
    try:
        Gui.Selection.removeObserver(panel.observer)
    except Exception as _fw_err:
        _fw_log("evalpanel.py:959", _fw_err)
    try:
        panel.win.cleanup()
    except Exception as _fw_err:
        _fw_log("evalpanel.py:963", _fw_err)


def open_panel(name):
    """The tool's PropertyManager in the task pane; run again while its analysis is shown, it clears it."""
    cls = PANELS.get(name)
    if cls is None:
        return None
    _forget_stale()
    if _open[0] is not None and _open[0].NAME == name:
        _open[0].reject()
        return None
    kept = _kept.pop(name, None)
    if kept is not None:
        try:
            kept.cleanup()
        except Exception as _fw_err:
            _fw_log("evalpanel.py:980", _fw_err)
        if name == "SWStyle_ZebraStripes":
            from . import evaluate2
            evaluate2.ZEBRA.hide()
        return None
    if Gui.Control.activeDialog():
        return None
    factory = _window_factory(name)
    if factory is None:
        return None
    if name == "SWStyle_ZebraStripes":
        from . import evalpm, evaluate2
        z = evaluate2.ZEBRA
        evalpm.apply_zebra(z)
        evalpm._tessellation(z)
        z.show()
        if not getattr(evaluate2._ZebraRedraw, "added", False):
            App.addDocumentObserver(evaluate2._ZebraRedraw())
            evaluate2._ZebraRedraw.added = True
    win = factory()
    panel = cls(win)
    _open[0] = panel
    Gui.Control.showDialog(panel)
    QtCore.QTimer.singleShot(0, panel.refresh)
    return panel


def install():
    """The nine commands open their PropertyManager instead of a window (after evalpm.install)."""
    from . import evaluate2, undercut, thickness, partingline  # noqa: F401  (their commands register on import)
    for name in PANELS:
        for table in (evaluate.COMMANDS, evaluate2.COMMANDS):
            if name in table:
                e = table[name]
                table[name] = (e[0], e[1], lambda name=name: open_panel(name)) + tuple(e[3:])
