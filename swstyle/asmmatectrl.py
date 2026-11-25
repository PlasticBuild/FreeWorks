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


import json
import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import asmcore as ac
from . import selguard

KINDS = ("Distance", "Angle", "Width", "Slot", "Path Mate", "Distance Range", "Angle Range")
TYPE_PROP = "FwMateController"


def _kind(j):
    return ac.mate_type(j)


def _drivable(j):
    ""


    k = _kind(j)
    try:
        if k == "Width":
            d = ac.width_values(j)
            return d is not None and d[2] in ("dimension", "percent")
        if k == "Slot":
            return ac.slot_values(j)[0] in ("Distance Along Slot", "Percent Along Slot")
        if k == "Path Mate":
            from . import asmpath
            return asmpath.values(j)["mode"] in ("Along Path Distance", "Along Path Percent")
        if k in ac.LIMITS:
            d = ac.limit_values(j)
            return d is not None and d[0] is not None
    except Exception as _fw_err:
        _fw_log("asmmatectrl.py:60", _fw_err)
        return False
    return k in ("Distance", "Angle")


def supported(asm):
    return [j for j in ac.mates(asm) if _kind(j) in KINDS and not getattr(j, "Suppressed", False) and _drivable(j)]


def _refs(j):
    return [(j.Reference1[0], j.Reference1[1][0]), (j.Reference2[0], j.Reference2[1][0])]


def value(j):
    k = _kind(j)
    if k == "Width":
        return float(ac.width_values(j)[3])
    if k == "Slot":
        return float(ac.slot_values(j)[1])
    if k == "Path Mate":
        from . import asmpath
        return float(asmpath.values(j)["value"])
    if k in ac.LIMITS:
        v = ac.picked_value(k, _refs(j))
        return float(v) if v is not None else 0.0
    if k == "Distance":
        return ac.distance_value(j)
    return float(j.Angle if k == "Angle" else j.Distance)


def unit(j):
    k = _kind(j)
    if k in ("Angle", "Angle Range"):
        return "deg"
    try:
        if (k == "Width" and ac.width_values(j)[2] == "percent") or (k == "Slot" and ac.slot_values(j)[0] == "Percent Along Slot"):
            return "%"
        if k == "Path Mate":
            from . import asmpath
            if asmpath.values(j)["mode"] == "Along Path Percent":
                return "%"
    except Exception as _fw_err:
        _fw_log("asmmatectrl.py:100", _fw_err)
    return "mm"


def _drive(asm, j, v):
    """One mate to value v (Distance/Angle: the value only; the others re-made, which solves)."""
    k = _kind(j)
    if k == "Width":
        width, tab, mode, _v, flip = ac.width_values(j)
        ac.make_width(asm, width, tab, mode, v, flip, joint=j)
    elif k == "Slot":
        mode, _v = ac.slot_values(j)
        ac.make_slot(asm, _refs(j), mode, v, joint=j)
    elif k == "Path Mate":
        from . import asmpath
        settings = asmpath.values(j)
        settings["value"] = float(v)
        vertex, edges = asmpath.refs_of(j)
        up = getattr(j, asmpath.UP_PROP, None)
        asmpath.make(asm, vertex, edges, settings, joint=j, up=(up[0], up[1][0]) if up and up[1] else None)
    elif k in ac.LIMITS:
        lo, hi = ac.limit_values(j)[1:3]
        ac.limit_move(asm, j, k, min(max(float(v), lo), hi) if lo <= hi else float(v))
    else:
        ac.set_value(j, k, v)
        return False
    return True


def set_values(asm, values):
    """{mate name: value}: each mate set, the assembly solved."""
    doc = asm.Document
    later = []
    for name, v in values.items():
        j = doc.getObject(name)
        if j is None:
            continue
        if _kind(j) in ("Distance", "Angle"):
            ac.set_value(j, _kind(j), v)
        else:
            later.append((j, v))
    try:
        ac.solve(asm)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: mate controller solve: %s\n" % error)
    for j, v in later:
        try:
            _drive(asm, j, v)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: mate controller %s: %s\n" % (j.Label, error))
    doc.recompute()


def between(a, b, t):
    out = {}
    for k in a:
        if k in b:
            out[k] = a[k] + (b[k] - a[k]) * t
    return out


def at(positions, s):
    """The values at slider s (0 = the first position, len-1 = the last)."""
    if not positions:
        return {}
    if len(positions) == 1:
        return dict(positions[0]["values"])
    s = max(0.0, min(float(len(positions) - 1), s))
    i = min(int(s), len(positions) - 2)
    return between(positions[i]["values"], positions[i + 1]["values"], s - i)


# ----------------------------------------------------------------------------- the object
class MateController:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", TYPE_PROP, "FreeCAD", "Mate Controller")
        obj.setEditorMode(TYPE_PROP, 2)
        obj.addProperty("App::PropertyStringList", "Mates", "Mate Controller", "The mates it drives (names)")
        obj.addProperty("App::PropertyString", "Positions", "Mate Controller", "json: [{name, values}]")

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ViewProviderMateController:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        try:
            from pivy import coin
            vobj.addDisplayMode(coin.SoGroup(), "Default")
        except Exception as _fw_err:
            _fw_log("asmmatectrl.py:201", _fw_err)

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def getIcon(self):
        return "Assembly_CreateJointDistance"

    def doubleClicked(self, vobj):
        edit(vobj.Object)
        return True

    def setupContextMenu(self, vobj, menu):
        a = menu.addAction("Edit Feature")
        a.triggered.connect(lambda: edit(vobj.Object))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def controllers(asm):
    return [o for o in asm.Group if hasattr(o, TYPE_PROP)]


def positions(obj):
    try:
        return json.loads(obj.Positions or "[]")
    except ValueError:
        return []


def make(asm):
    obj = asm.newObject("App::FeaturePython", "MateController")
    MateController(obj)
    if App.GuiUp and obj.ViewObject is not None:
        ViewProviderMateController(obj.ViewObject)
    obj.Label = "MateController"
    return obj


# ----------------------------------------------------------------------------- the PM
class MateControllerPanel:
    def __init__(self, asm, obj=None):
        from . import asmpm
        self.asm, self.doc, self.obj = asm, asm.Document, obj
        self.mates = [self.doc.getObject(n) for n in (obj.Mates if obj is not None else [])]
        self.mates = [m for m in self.mates if m is not None]
        self.positions = positions(obj) if obj is not None else []
        self.start = {j.Name: value(j) for j in supported(asm)}
        self.frames = 10
        box, lay = asmpm._box("Mates", "Mate Controller", "ASSEMBLIES_MATE_CONTROLLER")
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_MCMates")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 4))
        lay.addWidget(self.list)
        self.collect = QtWidgets.QPushButton("Collect all supported mates")
        self.collect.setObjectName("FW_MCCollect")
        self.collect.clicked.connect(self.collect_all)
        lay.addWidget(self.collect)
        pbox, play = asmpm._box("Mate Positions")
        self.pos = QtWidgets.QListWidget()
        self.pos.setObjectName("FW_MCPositions")
        self.pos.setFixedHeight(asmpm._rows(self.pos, 4))
        self.pos.currentRowChanged.connect(self.go_to)
        self.pos.itemChanged.connect(self._renamed)
        self.pos.setToolTip("Double-click a position to rename it")
        play.addWidget(self.pos)
        row = QtWidgets.QHBoxLayout()
        for text, name, slot in (("Add Position", "FW_MCAdd", self.add_position),
                                 ("Update Position", "FW_MCUpdate", self.update_position),
                                 ("Delete Position", "FW_MCDelete", self.delete_position)):
            b = QtWidgets.QPushButton(text)
            b.setObjectName(name)
            b.clicked.connect(slot)
            row.addWidget(b)
            setattr(self, name.split("MC")[1].lower(), b)
        play.addLayout(row)
        vbox, vlay = asmpm._box("Mate Values")
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setObjectName("FW_MCSlider")
        self.slider.valueChanged.connect(self.slide)
        vlay.addWidget(self.slider)
        self.values = QtWidgets.QLabel("")
        self.values.setObjectName("FW_MCValues")
        self.values.setWordWrap(True)
        vlay.addWidget(self.values)

        self.value_rows = QtWidgets.QWidget()
        self.value_rows.setObjectName("FW_MCValueRows")
        self.value_form = QtWidgets.QFormLayout(self.value_rows)
        self.value_form.setContentsMargins(0, 0, 0, 0)
        vlay.addWidget(self.value_rows)
        self.value_boxes = {}
        abox, alay = asmpm._box("Animation")
        form = QtWidgets.QFormLayout()
        self.frames_box = QtWidgets.QSpinBox()
        self.frames_box.setObjectName("FW_MCFrames")
        self.frames_box.setRange(2, 500)
        self.frames_box.setValue(10)
        self.frames_label = QtWidgets.QLabel("Frames between positions:")
        form.addRow(self.frames_label, self.frames_box)
        alay.addLayout(form)
        arow = QtWidgets.QHBoxLayout()
        self.animate_button = QtWidgets.QPushButton("Calculate animation")
        self.animate_button.setObjectName("FW_MCAnimate")
        self.animate_button.clicked.connect(self.animate)
        arow.addWidget(self.animate_button)
        self.save_button = QtWidgets.QPushButton("Save Animation")
        self.save_button.setObjectName("FW_MCSave")
        self.save_button.clicked.connect(self.save_animation)
        arow.addWidget(self.save_button)
        alay.addLayout(arow)
        self.form = [box, pbox, vbox, abox]
        self.timer = None
        self.frame_list = []
        self.doc.openTransaction("Mate Controller" if obj is None else "Edit " + obj.Label)
        try:
            self._fill()
            Gui.Selection.addObserver(self, 0)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise

    # picks: a mate in the tree joins the list
    def addSelection(self, doc, obj, sub, pnt):
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self.pick(self.doc.getObject(obj), sub)))

    def removeSelection(self, *a):
        pass

    def clearSelection(self, *a):
        pass

    def setPreselection(self, *a):
        pass

    def pick(self, root, sub=""):
        target = root
        if root is not None and sub:
            try:
                target = root.getSubObject(sub, retType=1) or root
            except Exception:
                target = root
        if target in supported(self.asm) and target not in self.mates:
            self.mates.append(target)
            self._fill()
            return True
        return False

    def collect_all(self):
        for j in supported(self.asm):
            if j not in self.mates:
                self.mates.append(j)
        self._fill()

    def _fill(self):
        self.list.clear()
        for j in self.mates:
            self.list.addItem(ac.mate_text(j) if hasattr(ac, "mate_text") else j.Label)
        self.pos.blockSignals(True)
        self.pos.clear()
        for p in self.positions:
            item = QtWidgets.QListWidgetItem(p["name"])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsEditable)
            self.pos.addItem(item)
        self.pos.blockSignals(False)
        self._value_rows()
        n = len(self.positions)
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, (n - 1) * 100))
        self.slider.blockSignals(False)
        # no greyed controls: each shows once there is something for it (two positions to slide
        # or animate between, a position to update or delete, a mate to add a position of)
        self.slider.setVisible(n > 1)
        self.frames_box.setVisible(n > 1)
        for w in (self.animate_button, self.save_button):
            w.setVisible(n > 1)
        self.update.setVisible(n > 0)
        self.delete.setVisible(n > 0)
        self.add.setVisible(bool(self.mates))
        self.frames_label.setVisible(n > 1)
        self._show_values({j.Name: value(j) for j in self.mates})

    def _show_values(self, values):
        parts = []
        for j in self.mates:
            v = values.get(j.Name)
            if v is not None:
                parts.append("%s: %.2f%s" % (j.Label.split(" (")[0], v, unit(j)))
                box = self.value_boxes.get(j.Name)
                if box is not None:
                    box.blockSignals(True)
                    box.setValue(v)
                    box.blockSignals(False)
        self.values.setText("   ".join(parts))

    def _value_rows(self):
        key = [j.Name for j in self.mates]
        if key == getattr(self, "_rows_for", None):
            return          # the same mates: the boxes stay (they are refreshed by _show_values)
        self._rows_for = key
        while self.value_form.rowCount():
            self.value_form.removeRow(0)
        self.value_boxes = {}
        for j in self.mates:
            box = QtWidgets.QDoubleSpinBox()
            box.setObjectName("FW_MCValue_%s" % j.Name)
            box.setDecimals(2)
            box.setKeyboardTracking(False)
            u = unit(j)
            box.setRange(0.0 if u == "%" else -1.0e6, 100.0 if u == "%" else 1.0e6)
            box.setSuffix(u)
            box.setValue(value(j))
            box.valueChanged.connect(lambda v, jj=j: self.type_value(jj, v))
            self.value_form.addRow(j.Label.split(" (")[0] + ":", box)
            self.value_boxes[j.Name] = box

    def type_value(self, j, v):
        """A mate's value typed: the assembly moves there (Add/Update Position keeps it)."""
        set_values(self.asm, {j.Name: v})
        self._show_values(self.now())

    def _renamed(self, item):
        r = self.pos.row(item)
        name = item.text().strip()
        if 0 <= r < len(self.positions):
            if name and name not in [p["name"] for i, p in enumerate(self.positions) if i != r]:
                self.positions[r]["name"] = name
            else:
                self.pos.blockSignals(True)
                item.setText(self.positions[r]["name"])
                self.pos.blockSignals(False)

    def now(self):
        return {j.Name: value(j) for j in self.mates}

    def add_position(self):
        taken = {p["name"] for p in self.positions}
        n = 1
        while "Position%d" % n in taken:
            n += 1
        self.positions.append({"name": "Position%d" % n, "values": self.now()})
        self._fill()
        self.pos.blockSignals(True)
        self.pos.setCurrentRow(len(self.positions) - 1)
        self.pos.blockSignals(False)

    def update_position(self):
        r = self.pos.currentRow()
        if 0 <= r < len(self.positions):
            self.positions[r]["values"] = self.now()

    def delete_position(self):
        r = self.pos.currentRow()
        if 0 <= r < len(self.positions):
            del self.positions[r]
            self._fill()

    def go_to(self, row):
        if 0 <= row < len(self.positions):
            set_values(self.asm, self.positions[row]["values"])
            self.slider.blockSignals(True)
            self.slider.setValue(row * 100)
            self.slider.blockSignals(False)
            self._show_values(self.positions[row]["values"])

    def slide(self, v):
        values = at(self.positions, v / 100.0)
        set_values(self.asm, values)
        self._show_values(values)

    def animation(self):
        """The values of each frame: the positions in order, frames between each two."""
        n = len(self.positions)
        steps = self.frames_box.value()
        out = []
        for i in range(n - 1):
            for k in range(steps):
                out.append(at(self.positions, i + k / float(steps)))
        if n:
            out.append(dict(self.positions[-1]["values"]))
        return out

    def animate(self):
        self.frame_list = self.animation()
        self.played = 0
        if self.timer is None:
            self.timer = QtCore.QTimer()
            self.timer.setInterval(40)
            self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        if not self.frame_list:
            self.timer.stop()
            return
        values = self.frame_list.pop(0)
        set_values(self.asm, values)
        self._show_values(values)
        self.played += 1
        try:
            Gui.updateGui()
        except Exception as _fw_err:
            _fw_log("asmmatectrl.py:502", _fw_err)

    def save_animation(self, folder=None):
        """One picture per frame, numbered, in folder (asked for when not given)."""
        if folder is None:
            folder = QtWidgets.QFileDialog.getExistingDirectory(Gui.getMainWindow(), "Save Animation")
            if not folder:
                return 0
        os.makedirs(folder, exist_ok=True)
        view = Gui.ActiveDocument.ActiveView
        saved = 0
        for i, values in enumerate(self.animation()):
            set_values(self.asm, values)
            try:
                Gui.updateGui()
                view.saveImage(os.path.join(folder, "MateController_%04d.png" % (i + 1)), 640, 480, "Current")
                saved += 1
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: save animation frame %d: %s\n" % (i + 1, error))
        return saved

    def _close(self):
        if self.timer is not None:
            self.timer.stop()
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmmatectrl.py:529", _fw_err)

    def accept(self):
        self._close()
        obj = self.obj or make(self.asm)
        obj.Mates = [j.Name for j in self.mates]
        obj.Positions = json.dumps(self.positions)
        self.obj = obj
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        self.doc.recompute()
        return True

    def reject(self):
        self._close()
        set_values(self.asm, {k: v for k, v in self.start.items()})
        self.doc.abortTransaction()
        Gui.Control.closeDialog()
        self.doc.recompute()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


OPEN = []


def _show(panel):
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    OPEN[:] = [panel]
    Gui.Control.showDialog(panel)
    return panel


def start(asm):
    """Insert > Mate Controller: the assembly's one controller, else a new one."""
    have = controllers(asm)
    return _show(MateControllerPanel(asm, have[0] if have else None))


def edit(obj):
    asm = ac.assembly_of(obj.Document)
    return _show(MateControllerPanel(asm, obj)) if asm is not None else None
