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

import itertools
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import contextbar, relationspm, sketchtoolpm

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/SketchXpert"
ALWAYS = "AlwaysOpen"
UNITS = {"Angle": "deg"}


def _params():
    return App.ParamGet(PARAMS)


def flagged(sketch):
    """0-based indices FreeCAD's solver names (conflicting, redundant, malformed): often just the
    last constraint added, not everything in the clash."""
    sketch.solve()
    found = set()
    for name in ("ConflictingConstraints", "RedundantConstraints", "MalformedConstraints",
                 "PartiallyRedundantConstraints"):
        try:
            found |= {i - 1 for i in getattr(sketch, name)}
        except Exception as _fw_err:
            _fw_log("sketchxpert.py:57", _fw_err)
    return sorted(i for i in found if 0 <= i < len(sketch.Constraints))


LOCAL_FROM = 60     # constraints: from here on only those on the clashing geometry are tried (fix232)
LOCAL_MOST = 24


def problems(sketch, most=400, memo=None):
    ""



    named = flagged(sketch)
    if not named:
        return []
    found = set(named)
    cons = sketch.Constraints
    count = len(cons)
    if count > LOCAL_FROM and _clashing(sketch):
        # a large sketch with clashing values: FreeCAD names every member of the clash already,
        # and a try on one of them solves the whole sketch the slow way (half a minute in a
        # 500-line sketch). The list is what FreeCAD names (fix232).
        return named
    if count > LOCAL_FROM:
        same = _repeats(cons, named)
        if same is not None:
            # the same relation or dimension given twice: either one goes, nothing else is in it
            if memo is not None:
                for i in same:
                    memo[(i,)] = True
            return sorted(same)
    deadline = time.monotonic() + BUDGET if count > LOCAL_FROM else None
    if count <= LOCAL_FROM:
        pool = range(count)
    elif count <= most:
        pool = _near(sketch, named)
    else:
        pool = _near(sketch, named)[:LOCAL_MOST]
    for i in pool:
        if deadline is not None and time.monotonic() > deadline:
            break
        if i not in found and cons[i].IsActive and _without(sketch, (i,), memo):
            found.add(i)
    if found == set(named):
        # three or more fixing one freedom (Horizontal, a 0 vertical distance, a 0 angle): no

        # constraints on the same geometry that, in pairs, clear it (fix159)
        local = [i for i in _near(sketch, named) if i not in found and cons[i].IsActive][:PAIR_POOL]
        pool = sorted(set(local) | set(named))
        for pair in itertools.combinations(pool, 2):
            if deadline is not None and time.monotonic() > deadline:
                break
            if not (set(pair) <= found) and _without(sketch, pair, memo):
                found |= set(pair)
    return sorted(found)


PAIR_POOL = 12
BUDGET = 6.0        # s: tries in a large sketch stop here (fix232)


def _key(c):
    return (c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, getattr(c, "Third", None),
            getattr(c, "ThirdPos", None), round(c.Value, 9))


def _clashing(sketch):
    try:
        return bool(list(sketch.ConflictingConstraints))
    except Exception:
        return False


def _repeats(cons, named):
    """Every named constraint and the ones that repeat it exactly, when each named one has a
    repeat; else None."""
    keys = {}
    for i, c in enumerate(cons):
        if c.IsActive:
            keys.setdefault(_key(c), []).append(i)
    out = set()
    for i in named:
        twins = keys.get(_key(cons[i]), [])
        if len(twins) < 2:
            return None
        out |= set(twins)
    return out


def _geos(c):
    out = set()
    for g in (c.First, c.Second, getattr(c, "Third", None)):
        if g is not None and g >= 0:
            out.add(g)
    return out


def _near(sketch, indices):
    """Constraints that share geometry with the given ones (the place of the clash)."""
    cons = sketch.Constraints
    geos = set()
    for i in indices:
        geos |= _geos(cons[i])
    return [i for i, c in enumerate(cons) if _geos(c) & geos]


def healthy(sketch):
    sketch.solve()
    return not (list(sketch.ConflictingConstraints) or list(sketch.RedundantConstraints)
                or list(getattr(sketch, "MalformedConstraints", []) or []))


def _without(sketch, indices, memo=None):
    """Is the sketch healthy with these constraints switched off? Switches them back on."""
    key = tuple(sorted(indices))
    if memo is not None and key in memo:
        return memo[key]
    ok = _without_now(sketch, indices)
    if memo is not None:
        memo[key] = ok
    return ok


def _editing(sketch):
    try:
        gdoc = Gui.getDocument(sketch.Document.Name)
        vp = gdoc.getInEdit() if gdoc is not None else None
        return vp is not None and vp.Object == sketch
    except Exception:
        return False


def _without_now(sketch, indices):
    # fix232: while the sketch is open, setActive solves it by itself and the solver's lists are
    # up to date after it, so a try makes two solves, not four (each takes seconds in a large
    # fully defined sketch)
    quick = _editing(sketch)
    was = []
    changed = False
    try:
        cons = sketch.Constraints
        for i in indices:
            was.append((i, cons[i].IsActive))
            if was[-1][1]:
                sketch.setActive(i, False)
                changed = True
        if quick and changed:
            return not (list(sketch.ConflictingConstraints) or list(sketch.RedundantConstraints)
                        or list(getattr(sketch, "MalformedConstraints", []) or []))
        return healthy(sketch)
    finally:
        for i, active in was:
            if active:
                sketch.setActive(i, True)
        if not (quick and changed):
            sketch.solve()


def diagnose(sketch, most=12):
    """Solutions: tuples of constraint indices whose deletion fixes the sketch, singles first."""
    memo = {}       # fix232: a try made while listing the clash is not made again
    bad = [i for i in problems(sketch, memo=memo) if sketch.Constraints[i].IsActive]
    if len(sketch.Constraints) > LOCAL_FROM and _clashing(sketch):
        # fix232: a large sketch with clashing values. Deleting any one member of the clash
        # frees it; the newest first, as the one just added is the usual cause. Not tried
        # one by one (each try took half a minute in a 500-line sketch).
        return [(i,) for i in sorted(bad, reverse=True)][:most]
    out = [(i,) for i in bad if _without(sketch, (i,), memo)]
    deadline = time.monotonic() + BUDGET if len(sketch.Constraints) > LOCAL_FROM else None
    if not out:
        for pair in itertools.combinations(bad, 2):
            if deadline is not None and time.monotonic() > deadline:
                break
            if _without(sketch, pair, memo):
                out.append(pair)
                if len(out) >= most:
                    break
    return out[:most]


def names(sketch):
    ""
    out = {}
    try:
        for indices, name in relationspm.existing_relations(sketch, [], everything=True, merged=True):
            for i in indices:
                out[i] = name
    except Exception as _fw_err:
        _fw_log("sketchxpert.py:149", _fw_err)
    n = 0
    for i, c in enumerate(sketch.Constraints):
        if c.Type in relationspm.DIMENSIONS:
            n += 1
            if c.Type == "Angle":
                value = "%.6g deg" % (c.Value * 180.0 / 3.141592653589793)
            else:
                value = "%.6g mm" % abs(c.Value)
            out[i] = "D%d (%s %s)" % (n, c.Type, value)
        elif i not in out:
            out[i] = "%s%d" % (c.Type, i + 1)
    return out


class SketchXpertPage(sketchtoolpm.ToolPage):
    TITLE = "SketchXpert"
    ICON = "SKETCH_XPERT"
    PIXMAP = "Sketcher_SelectConflictingConstraints"
    TRANSACTION = "SketchXpert"

    def build(self):
        self.solutions = []
        self.current = 0
        g = self.group("Message")
        self.message = QtWidgets.QLabel(g.body)
        self.message.setWordWrap(True)
        self.message.setObjectName("SWXpertMessage")
        g.content.addWidget(self.message)
        g = self.group("Options")
        self.diagnose_button = QtWidgets.QPushButton("Diagnose", g.body)
        self.manual_button = QtWidgets.QPushButton("Manual Repair", g.body)
        self.diagnose_button.clicked.connect(self.run_diagnose)
        self.manual_button.clicked.connect(self.show_manual)
        g.content.addWidget(self.diagnose_button)
        g.content.addWidget(self.manual_button)
        self.results_group = g = self.group("Results")
        row = QtWidgets.QHBoxLayout()
        self.previous = QtWidgets.QToolButton(g.body)
        self.previous.setArrowType(QtCore.Qt.LeftArrow)
        self.next = QtWidgets.QToolButton(g.body)
        self.next.setArrowType(QtCore.Qt.RightArrow)
        self.counter = QtWidgets.QLabel(g.body)
        self.previous.clicked.connect(lambda: self.step(-1))
        self.next.clicked.connect(lambda: self.step(1))
        row.addWidget(self.previous)
        row.addWidget(self.counter, 1, QtCore.Qt.AlignCenter)
        row.addWidget(self.next)
        g.content.addLayout(row)
        self.solution_text = QtWidgets.QLabel(g.body)
        self.solution_text.setWordWrap(True)
        g.content.addWidget(self.solution_text)
        self.accept_button = QtWidgets.QPushButton("Accept", g.body)
        self.accept_button.clicked.connect(self.accept_solution)
        g.content.addWidget(self.accept_button)
        self.results_group.hide()
        self.manual_group = g = self.group("Conflicting Relations/Dimensions")
        self.manual_list = QtWidgets.QListWidget(g.body)
        self.manual_list.setObjectName("SWSelectedEntities")
        self.manual_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.manual_list.setMinimumHeight(100)
        self.manual_list.itemSelectionChanged.connect(self._pick_manual)
        g.content.addWidget(self.manual_list)
        row = QtWidgets.QHBoxLayout()
        self.delete_button = QtWidgets.QPushButton("Delete", g.body)
        self.delete_all_button = QtWidgets.QPushButton("Delete All", g.body)
        self.delete_button.clicked.connect(self.delete_selected)
        self.delete_all_button.clicked.connect(self.delete_all)
        row.addWidget(self.delete_button)
        row.addWidget(self.delete_all_button)
        g.content.addLayout(row)
        self.manual_group.hide()
        g = self.group("More Information/Options")
        self.always = QtWidgets.QCheckBox("Always open this dialog when sketch error occurs", g.body)
        self.always.setChecked(_params().GetBool(ALWAYS, False))
        self.always.toggled.connect(lambda on: _params().SetBool(ALWAYS, on))
        g.content.addWidget(self.always)
        self.refresh_message()

    # ------------------------------------------------------------------ state
    def refresh_message(self):
        bad = problems(self.sketch)
        if not bad:
            self.message.setText("The sketch is solved: nothing is over defined.")
        else:
            self.message.setText(
                "The sketch is over defined: %d relation%s or dimension%s clash. Click Diagnose for "
                "solutions, or Manual Repair to delete them yourself."
                % (len(bad), "" if len(bad) == 1 else "s", "" if len(bad) == 1 else "s"))
        self.diagnose_button.setEnabled(bool(bad))
        self.manual_button.setEnabled(bool(bad))
        return bad

    def _pick(self, indices):
        try:
            Gui.Selection.clearSelection()
            for i in indices:
                Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Constraint%d" % (i + 1))
        except Exception as _fw_err:
            _fw_log("sketchxpert.py:248", _fw_err)

    # ------------------------------------------------------------------ Diagnose
    def run_diagnose(self):
        self.manual_group.hide()
        self.solutions = diagnose(self.sketch)
        self.current = 0
        self.results_group.show()
        if not self.solutions:
            self.counter.setText("No solution found")
            self.solution_text.setText("No single relation or dimension, nor any pair, fixes it. "
                                       "Use Manual Repair.")
            for w in (self.previous, self.next, self.accept_button):
                w.setEnabled(False)
            return
        self.show_solution()

    def show_solution(self):
        n = len(self.solutions)
        self.current %= n
        sol = self.solutions[self.current]
        label = names(self.sketch)
        self.counter.setText("Solution %d of %d" % (self.current + 1, n))
        self.solution_text.setText("Delete: " + ", ".join(label.get(i, str(i)) for i in sol))
        self.previous.setEnabled(n > 1)
        self.next.setEnabled(n > 1)
        self.accept_button.setEnabled(True)
        self._pick(sol)

    def step(self, delta):
        if self.solutions:
            self.current += delta
            self.show_solution()

    def accept_solution(self):
        if not self.solutions:
            return
        self._delete(self.solutions[self.current])
        self.results_group.hide()
        self.solutions = []

    # ------------------------------------------------------------------ Manual Repair
    def show_manual(self):
        self.results_group.hide()
        self.manual_group.show()
        self.fill_manual()

    def fill_manual(self):
        label = names(self.sketch)
        self.manual_list.clear()
        for i in problems(self.sketch):
            item = QtWidgets.QListWidgetItem(label.get(i, str(i)))
            item.setData(QtCore.Qt.UserRole, i)
            self.manual_list.addItem(item)
        has = self.manual_list.count() > 0
        self.delete_button.setEnabled(has)
        self.delete_all_button.setEnabled(has)

    def _pick_manual(self):
        self._pick([it.data(QtCore.Qt.UserRole) for it in self.manual_list.selectedItems()])

    def delete_selected(self):
        indices = [it.data(QtCore.Qt.UserRole) for it in self.manual_list.selectedItems()]
        if indices:
            self._delete(indices)

    def delete_all(self):
        self._delete(problems(self.sketch))

    # ------------------------------------------------------------------ work
    def _delete(self, indices):
        self.begin()
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchxpert.py:323", _fw_err)
        for i in sorted(set(indices), reverse=True):
            self.sketch.delConstraint(i)
        sketchtoolpm._refresh(self.sketch)
        bad = self.refresh_message()
        if self.manual_group.isVisible():
            self.fill_manual()
        text = "Deleted %d. %s" % (len(set(indices)), "The sketch solves now." if not bad
                                   else "It is still over defined.")
        self.show_note(text, bool(bad))

    def closing(self):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("sketchxpert.py:338", _fw_err)


def open_for(sketch):
    """Open SketchXpert unless another page is up; True when it opened."""
    if sketchtoolpm.current() is None:
        sketchtoolpm.open_page(SketchXpertPage(sketch))
        return True
    return False


class SketchXpertCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_SelectConflictingConstraints", "MenuText": "SketchXpert",
                "ToolTip": "Finds ways to fix an over-defined sketch, or lets you delete the clashing "
                           "relations and dimensions", "CmdType": "ForEdit"}

    def IsActive(self):
        return contextbar.sketch_in_edit() is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            open_for(sketch)


class _Watch(QtCore.QObject):
    """Opens SketchXpert by itself when an edit over-defines the sketch and the option is on."""

    def __init__(self):
        super().__init__()
        self.last = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        if not _params().GetBool(ALWAYS, False):
            self.last = None
            return
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            self.last = None
            return
        try:
            bad = bool(list(sketch.ConflictingConstraints) or list(sketch.RedundantConstraints))
        except Exception:
            return
        key = (sketch.Document.Name, sketch.Name)
        was = self.last
        self.last = (key, bad)
        if bad and was is not None and was[0] == key and not was[1]:
            shell = sketchtoolpm._shell()
            if shell is not None and contextbar.tool_running(shell):
                self.last = (key, False)    # wait until the tool lets go
                return
            if not open_for(sketch):
                self.last = (key, False)    # another page (the Dimension PM) is up: again when it closes


COMMAND = "SWStyle_SketchXpert"
_watch = None


def register():
    global _watch
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, SketchXpertCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
    if _watch is None:
        _watch = _Watch()
