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
from . import selguard

KINDS = ("Coincident", "Parallel", "Perpendicular", "Tangent", "Concentric", "Lock", "Distance", "Angle", "Width",

         "Slot", "Distance Range", "Angle Range", "Profile Center", "Gear", "Rack Pinion", "Screw",
         "Universal Joint", "Path Mate", "Linear/Linear Coupler", "Cam", "Hinge", "Symmetric")
LATER = ("Distance Range", "Angle Range")     # limits go on a mate that lets the two move: made last
YELLOW = ("Select a new reference for each mate. Or use repeat to use the same reference. "
          "Or turn off the mate so copied components will not use the mate.")
GREEN = "Component has been placed. Press OK to place another component."
MSG_STYLE = "background: %s; color: black; padding: 3px; border: 1px solid #b0a040;"


def _refs(joint):
    """[(component, element)] picks of a mate: two, or four for Width (width faces, tab faces)."""
    if ac.mate_type(joint) == "Width":
        data = ac.width_values(joint)
        return list(data[0]) + list(data[1]) if data else []
    if ac.mate_type(joint) == "Symmetric":
        return _sym_picks(joint)
    return [(r[0], r[1][0]) for r in (joint.Reference1, joint.Reference2)]


def _sym_picks(joint):
    """A Symmetric mate's three picks: [symmetry plane, first entity, second entity]."""
    first, _sign = ac.symmetric_first(joint)
    plane = (joint.Reference1[0], joint.Reference1[1][0])
    held = (joint.Reference2[0], joint.Reference2[1][0])
    return [plane, first, held] if first is not None and first[0] is not None else []


def _sides(joint):
    """The mate's picks on its two sides: a Path Mate is one vertex against its path's edges; the
    others split their picks in half."""
    if ac.mate_type(joint) == "Path Mate":
        from . import asmpath
        v, edges = asmpath.refs_of(joint)
        return [v], list(edges)
    refs = _refs(joint)
    if ac.mate_type(joint) == "Symmetric":
        return refs[:1], refs[1:]       # the plane; the two entities (copy_mates splits by component)
    half = len(refs) // 2
    return refs[:half], refs[half:]


def copy_mates(asm, comps):
    """(inner, outer) mates of the components: inner = both sides among them; outer = [{mate,
    own picks, other picks, own_first}] to the rest of the assembly."""
    if not isinstance(comps, (list, tuple, set)):
        comps = [comps]
    group = set(c.Name for c in comps)
    inner, outer = [], []
    for joint in ac.mates(asm):
        if ac.mate_type(joint) not in KINDS or getattr(joint, "Suppressed", False):
            continue
        if ac.mate_type(joint) == "Symmetric":
            picks = _sym_picks(joint)
            if len(picks) != 3:
                continue
            ins = [c.Name in group for c, _ in picks]
            if all(ins):
                inner.append(joint)
            elif any(ins):
                own = [i for i in range(3) if ins[i]]
                rest = [i for i in range(3) if not ins[i]]
                outer.append({"mate": joint, "own": [picks[i] for i in own], "other": [picks[i] for i in rest],
                              "own_first": True, "slots": own + rest})
            continue
        sides = list(_sides(joint))
        if not sides[0] or not sides[1]:
            continue
        ins = [all(c.Name in group for c, _ in s) for s in sides]
        if all(ins):
            inner.append(joint)
        elif any(ins):
            i = 0 if ins[0] else 1
            outer.append({"mate": joint, "own": sides[i], "other": sides[1 - i], "own_first": i == 0})
    return inner, outer


def value_of(joint):
    kind = ac.mate_type(joint)
    if kind == "Distance":
        return ac.distance_value(joint)
    if kind == "Angle":
        return float(getattr(joint.Angle, "Value", joint.Angle))
    return None


def full_value(joint):
    """The value add_mate takes for the mate's type, read back from the mate."""
    kind = ac.mate_type(joint)
    if kind in ("Distance", "Angle"):
        return value_of(joint)
    reverse = bool(getattr(joint, ac.REVERSE_PROP, False))
    if kind == "Gear":
        d1 = float(getattr(getattr(joint, "Distance", 0.5), "Value", getattr(joint, "Distance", 0.5)))
        d2 = float(getattr(getattr(joint, "Distance2", 0.5), "Value", getattr(joint, "Distance2", 0.5)))
        return (abs(d1) * 2.0, abs(d2) * 2.0, reverse)
    if kind in ("Rack Pinion", "Screw"):
        try:
            mode, number = (getattr(joint, ac.VALUE_PROP, "") or "").split()
            return (mode, float(number), reverse)
        except ValueError:
            return None
    if kind == "Profile Center":
        return ac._profile_values(joint)
    return None


def _clone_hinge(asm, joint, first, second):
    """A Hinge on the new picks: FreeCAD's Revolute on the two round edges, each frame moved along
    the axis by the original's offsets, with its angle limits."""
    j = ac.add_mate(asm, "Concentric", first[0], second[0])
    if j is None:
        return None
    try:
        j.Proxy.setJointType(j, "Revolute")
        setattr(j, ac.MATE_PROP, "Hinge")
        j.Label = ac._next_mate_name(asm, "Hinge")
        j.Offset1, j.Offset2 = App.Placement(joint.Offset1), App.Placement(joint.Offset2)
        for prop in ("EnableAngleMin", "EnableAngleMax", "AngleMin", "AngleMax"):
            if hasattr(joint, prop) and hasattr(j, prop):
                setattr(j, prop, getattr(joint, prop))
        ac._mark(j, bool(ac.solve(asm)))
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Copy with Mates hinge: %s\n" % error)
    return j


def _make(asm, joint, first, second, value=None, lock=None):
    kind = ac.mate_type(joint)
    if kind == "Path Mate":
        from . import asmpath
        return asmpath.make(asm, first[0], list(second), settings=asmpath.values(joint))[0]
    if kind == "Linear/Linear Coupler":
        from . import asmcoupler
        v = asmcoupler.values(joint)
        return asmcoupler.make(asm, first[0], second[0], v["r1"], v["r2"], v["reverse"],
                               asmcoupler.reference_names(joint))[0]
    if kind == "Cam":
        from . import asmcam
        return asmcam.make(asm, first[0], second[0])[0]
    if kind == "Hinge":
        return _clone_hinge(asm, joint, first, second)
    if kind == "Symmetric":
        picks = list(first) + list(second)          # plane, first entity, second entity
        if len(picks) != 3:
            return None
        return ac.make_symmetric(asm, picks[0], [picks[1], picks[2]])[0]
    if kind == "Slot":
        mode, v = ac.slot_values(joint)
        return ac.make_slot(asm, [first[0], second[0]], mode, v)[0]
    if kind in LATER:
        data = ac.limit_values(joint)
        if data is None:
            return None
        return ac.make_limit(asm, kind, [first[0], second[0]], data[1], data[2])[0]
    if value is None and kind not in ("Distance", "Angle"):
        value = full_value(joint)
    if kind == "Width":
        data = ac.width_values(joint)
        mode, wval, flip = (data[2], data[3], data[4]) if data else ("centered", 50.0, False)
        return ac.make_width(asm, list(first), list(second), mode, wval, flip)[0]
    if lock is None:
        lock = bool(getattr(joint, ac.LOCK_PROP, False))
    return ac.add_mate(asm, kind, first[0], second[0], value if value is not None else value_of(joint), lock_rotation=lock)


def copy_with_mates(asm, comps, plan, offset=None):
    """Inserts copies of comps, their mates among them, and the outer mates in plan:
    [(outer row, new other picks, value, lock)]. Returns ({old name: copy}, [new mates], [problems])."""
    if not isinstance(comps, (list, tuple)):
        comps = [comps]
    shift = offset if offset is not None else App.Vector(20, 20, 0)
    copies = {}
    for c in comps:
        placement = App.Placement(c.Placement)
        placement.Base = placement.Base + shift
        copy = ac.insert(asm, c.LinkedObject, placement)
        copy.Placement = placement
        copies[c.Name] = copy
    mapped = lambda picks: [(copies.get(c.Name, c), e) for c, e in picks]
    inner, _ = copy_mates(asm, comps)
    made, problems = [], []
    # the mates to the rest first (they place the copies), then the ones among the copies
    later = []
    for row, other, value, lock in plan:
        own = mapped(row["own"])
        first, second = (own, other) if row["own_first"] else (other, own)
        if row.get("slots"):        # Symmetric: the picks back in the mate's order
            got = list(own) + list(other)
            picks = [None] * 3
            for k, slot in enumerate(row["slots"]):
                picks[slot] = got[k]
            first, second = picks[:1], picks[1:]
        if ac.mate_type(row["mate"]) in LATER:
            later.append((row["mate"], first, second, value, lock))
            continue
        made.append(_make(asm, row["mate"], first, second, value, lock))
    for joint in inner:
        a, b = _sides(joint)
        a, b = mapped(a), mapped(b)
        if ac.mate_type(joint) in LATER:
            later.append((joint, a, b, None, None))
            continue
        made.append(_make(asm, joint, a, b))
    for joint, first, second, value, lock in later:
        made.append(_make(asm, joint, first, second, value, lock))
    for m in made:
        if m is not None and ac.mate_error(m):
            problems.append(m.Label)
    asm.Document.recompute()
    return copies, made, problems


class CopyPanel:
    def __init__(self, asm, comps=()):
        from . import asmpm
        self.asm, self.doc = asm, asm.Document
        self.comps = []
        self.placed = None      # the copy placed, waiting for OK
        self.count = 0          # copies placed in this PropertyManager
        step1, lay = asmpm._box("Step 1: Select Component", "Copy with Mates", "ASSEMBLIES_COPY_WITH_MATES")
        msg1 = QtWidgets.QLabel("Select components to copy with mates")
        msg1.setObjectName("FW_CopySelectMessage")     # the shared Message look (pmmessage), PM thread 11-27
        msg1.setWordWrap(True)
        lay.addWidget(msg1)
        lay.addWidget(QtWidgets.QLabel("Selected Components"))
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("FW_CopyComponents")
        self.list.setStyleSheet(asmpm.PICK_STYLE)
        self.list.setFixedHeight(asmpm._rows(self.list, 4))
        lay.addWidget(self.list)
        self.next = QtWidgets.QPushButton("Next")
        self.next.setObjectName("FW_CopyNext")
        self.next.setToolTip("Next (Step 2: Mates)")
        self.next.clicked.connect(self.go_next)
        lay.addWidget(self.next, 0, QtCore.Qt.AlignRight)
        step2, self.mlay = asmpm._box("Step 2: Mates")
        self.mates_box = step2
        self.message = QtWidgets.QLabel(YELLOW)
        self.message.setObjectName("FW_CopyMessage")
        self.message.setWordWrap(True)      # the shared Message look (pmmessage); green only once placed
        self.mlay.addWidget(self.message)
        self.hint = QtWidgets.QLabel("Click Next to list the components' mates.")
        self.hint.setWordWrap(True)
        self.mlay.addWidget(self.hint)
        self.error = QtWidgets.QLabel("")
        self.error.setObjectName("FW_CopyError")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d04040;")
        self.error.hide()
        self.mlay.addWidget(self.error)
        self.rows = []
        self.listed = False
        self.current = None
        self.form = [step1, step2]
        for comp in comps:
            self._add_component(comp)
        Gui.Selection.addObserver(self, 0)
        self._rmb = None
        self._install_rmb()

    # ---------------------------------------------------------------- right mouse button
    def _install_rmb(self):
        ""

        panel = self

        class F(QtCore.QObject):
            def eventFilter(self, w, e):
                try:
                    t = e.type()
                except Exception:
                    return False
                if t == QtCore.QEvent.MouseButtonPress and e.button() == QtCore.Qt.RightButton:
                    panel._rmb_at = e.pos()
                elif t == QtCore.QEvent.MouseButtonRelease and e.button() == QtCore.Qt.RightButton:
                    at = getattr(panel, "_rmb_at", None)
                    panel._rmb_at = None
                    if at is not None and (e.pos() - at).manhattanLength() < 6 and panel.listed:
                        return panel.right_click()
                elif t == QtCore.QEvent.ContextMenu and panel.listed and getattr(panel, "_ate_menu", False):
                    panel._ate_menu = False
                    return True
                return False
        try:
            from . import asmspeedpak
            view = asmspeedpak._view_widget()
        except Exception:
            view = None
        if view is None:
            return
        self._rmb = (view, F(view))
        view.installEventFilter(self._rmb[1])

    def right_click(self, pick=None):
        """The preselected entity (or pick: (object, sub)) into the active field, then the next
        field. True when used."""
        if self.placed is not None or not self.rows:
            return False
        if pick is not None:
            obj, sub = pick[0], (pick[1],)
        else:
            try:
                pre = Gui.Selection.getPreselection()
                obj = pre.Object
                sub = tuple(pre.SubElementNames or ())
            except Exception:       # nothing preselected
                obj, sub = None, ()
        if obj is not None and sub:
            self._pick(obj, sub[0])     # a full field steps on by itself
        else:
            self.next_field()           # nothing under the pointer: the next field
        self._ate_menu = True
        return True

    def next_field(self):
        """The next field that still needs an entity (after the active one, round to the first)."""
        need = [r for r in self.rows if self._needs(r)]
        if not need:
            return None
        i = self.rows.index(self.current) if self.current in self.rows else -1
        later = [r for r in self.rows[i + 1:] if r in need] + [r for r in self.rows[:i + 1] if r in need]
        self._focus(later[0])
        return later[0]

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, obj, sub, pnt):
        if doc != self.doc.Name:
            return
        self.doc.Name      # its document closed: this raises here and selguard drops the observer
        QtCore.QTimer.singleShot(0, lambda: selguard.quiet(lambda: self._pick(self.doc.getObject(obj), sub)))

    def removeSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass

    def _pick(self, root, sub):
        if root is None:
            return
        ref = ac.reference(self.asm, root, sub) if sub else None
        if not self.listed:
            comp = ref[0] if ref is not None else (root if root in ac.components(self.asm) else None)
            if comp is not None:
                self._add_component(comp)
            return
        if ref is None or ref[0] in self.comps or self.placed is not None:
            return
        row = self.current if self.current is not None and self._needs(self.current) else next(
            (r for r in self.rows if self._needs(r)), None)
        if row is None:
            return
        row["new"].append(ref)
        from .asmpm import instance_name
        row["entity"].addItem("%s@%s" % (ref[1], instance_name(ref[0].Label)))
        if not self._needs(row):
            self.current = None
            nxt = next((r for r in self.rows if self._needs(r)), None)
            if nxt is not None:
                self._focus(nxt)
        Gui.Selection.clearSelection()
        self._try_place()

    def _add_component(self, comp):
        if comp is None or comp not in ac.components(self.asm) or comp in self.comps:
            return
        self.comps.append(comp)
        self.list.addItem(comp.Label)

    # ---------------------------------------------------------------- step 2
    def go_next(self):
        if not self.comps and not self.listed:
            # never greyed: Next before a pick says what to do first (asmpkg356)
            QtWidgets.QToolTip.showText(self.next.mapToGlobal(self.next.rect().bottomLeft()),
                                        "Select the components to copy first, in the graphics area or the tree.", self.next)
            return
        if self.listed:
            return
        from .asmpm import instance_name, sw_icon
        self.listed = True
        _, outer = copy_mates(self.asm, self.comps)
        self.hint.setText("" if outer else "The components have no mates to the rest of the assembly.")
        self.hint.setVisible(not outer)
        for i, info in enumerate(outer):
            joint = info["mate"]
            kind = ac.mate_type(joint)
            box = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(box)
            col.setContentsMargins(0, 2, 0, 2)
            col.setSpacing(2)
            head = QtWidgets.QHBoxLayout()
            use = QtWidgets.QToolButton()
            use.setObjectName("FW_CopyUse_%d" % i)
            use.setIcon(sw_icon(kind))
            use.setCheckable(True)
            use.setChecked(True)
            use.setAutoRaise(True)
            use.setToolTip("Turn the mate off: the copy goes without it")
            head.addWidget(use)
            head.addWidget(QtWidgets.QLabel(joint.Label.split(" (")[0]), 1)
            col.addLayout(head)
            repeat = QtWidgets.QCheckBox("Repeat")
            repeat.setObjectName("FW_CopyRepeat_%d" % i)
            repeat.setToolTip("Use the same reference as the original's mate")
            col.addWidget(repeat)
            entity = QtWidgets.QListWidget()
            entity.setObjectName("FW_CopyEntity_%d" % i)
            n = len(info["other"])
            entity.setFixedHeight(22 * n)
            was = ", ".join("%s@%s" % (e, instance_name(c.Label)) for c, e in info["other"])
            entity.setToolTip("New Entity To Mate To (was %s)" % was)
            col.addWidget(entity)
            lock = None
            if kind == "Concentric":
                lock = QtWidgets.QCheckBox("Lock Rotation")
                lock.setObjectName("FW_CopyLock_%d" % i)
                lock.setChecked(bool(getattr(joint, ac.LOCK_PROP, False)))
                col.addWidget(lock)
            value = None
            v = value_of(joint)
            if v is not None:
                value = QtWidgets.QDoubleSpinBox()
                value.setObjectName("FW_CopyValue_%d" % i)
                value.setDecimals(2)
                value.setRange(0.0, 1.0e6 if kind == "Distance" else 360.0)
                value.setSuffix("mm" if kind == "Distance" else "deg")
                value.setValue(v)
                col.addWidget(value)
            row = dict(info, use=use, repeat=repeat, entity=entity, value=value, lock=lock, new=[], count=n)
            use.toggled.connect(lambda on, r=row: self._sync(r))
            repeat.toggled.connect(lambda on, r=row: self._sync(r))
            entity.installEventFilter(self._focus_filter(row))
            self.mlay.insertWidget(self.mlay.count() - 1, box)
            self.rows.append(row)
        first = next((r for r in self.rows if self._needs(r)), None)
        if first is not None:
            self._focus(first)

    def _needs(self, row):
        return row["use"].isChecked() and not row["repeat"].isChecked() and len(row["new"]) < row["count"]

    def _sync(self, row):
        on = row["use"].isChecked()
        for w in (row["repeat"], row["lock"], row["value"]):
            if w is not None:
                w.setEnabled(on)
        row["entity"].setEnabled(on and not row["repeat"].isChecked())
        if not self._needs(row) and self.current is row:
            self.current = None
        self._try_place()

    def _focus_filter(self, row):
        panel = self

        class F(QtCore.QObject):
            def eventFilter(self, w, e):
                if not isinstance(e, QtCore.QEvent):
                    return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
                if e.type() == QtCore.QEvent.MouseButtonPress:
                    panel._focus(row)
                return False
        return F(row["entity"])

    def _focus(self, row):
        from .asmpm import PICK_STYLE
        self.current = row
        for r in self.rows:
            r["entity"].setStyleSheet(PICK_STYLE if r is row else "")

    def plan(self):
        out, missing = [], []
        for r in self.rows:
            if not r["use"].isChecked():
                continue
            if r["repeat"].isChecked():
                other = list(r["other"])
            elif len(r["new"]) < r["count"]:
                missing.append(r["mate"].Label.split(" (")[0])
                continue
            else:
                other = list(r["new"])
            out.append((r, other, r["value"].value() if r["value"] is not None else None,
                        r["lock"].isChecked() if r["lock"] is not None else None))
        return out, missing

    def _picked_any(self):
        return any(r["new"] for r in self.rows)

    def _try_place(self, force=False):
        """Every mate has its entity: the copy is placed (at once after the last pick; with OK when
        every mate is Repeat or off)."""
        if not self.listed or self.placed is not None:
            return False
        plan, missing = self.plan()
        if missing or not (force or self._picked_any()):
            return False
        self.error.hide()
        self.doc.openTransaction("Copy with Mates")
        try:
            self.result = copy_with_mates(self.asm, self.comps, plan)
        finally:
            self.doc.commitTransaction()
        self.placed = self.result
        self.count += 1
        self.message.setText(GREEN)
        self.message.setStyleSheet(MSG_STYLE % "#a8f0a0")
        _refresh()
        return True

    def _reset(self):
        """After OK: the next copy, the same mates, new entities to pick."""
        self.placed = None
        self.message.setText(YELLOW)
        self.message.setStyleSheet("")      # back to the shared Message look
        for r in self.rows:
            r["new"] = []
            r["entity"].clear()
        first = next((r for r in self.rows if self._needs(r)), None)
        if first is not None:
            self._focus(first)

    # ---------------------------------------------------------------- OK / Cancel
    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("asmcopy.py:558", _fw_err)
        if getattr(self, "_rmb", None):
            try:
                self._rmb[0].removeEventFilter(self._rmb[1])
            except Exception as _fw_err:
                _fw_log("asmcopy.py:563", _fw_err)
            self._rmb = None

    def accept(self):
        if not self.comps:
            return self.reject()
        if not self.listed:
            self.go_next()
            return False
        if self.placed is not None:
            self._reset()
            return False
        plan, missing = self.plan()
        if self._picked_any() or (missing and not self.count):
            self.error.setText("Pick the new entity for %s, tick Repeat, or turn the mate off." % ", ".join(missing))
            self.error.show()
            return False
        if not self.count:
            self._try_place(force=True)     # every mate Repeat or off
            return False
        self._close()
        Gui.Control.closeDialog()
        _refresh()
        return True

    def reject(self):
        self._close()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def _refresh():
    try:
        from . import asmmenu
        asmmenu._refresh()
    except Exception as _fw_err:
        _fw_log("asmcopy.py:602", _fw_err)


OPEN = []


class CopyWithMatesCommand:
    def GetResources(self):
        return {"MenuText": "Copy with Mates", "Pixmap": "Assembly_InsertLink",
                "ToolTip": "Copies components together with their mates; pick the new mate entities."}

    def Activated(self):
        from . import asmtools, asmui
        asm = asmtools._assembly()
        if asm is None:
            return
        comps = asmtools._picked_components(asm)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        asmui.activate(asm)
        panel = CopyPanel(asm, comps)
        OPEN[:] = [panel]
        Gui.Control.showDialog(panel)

    def IsActive(self):
        return App.ActiveDocument is not None and ac.assembly_of(App.ActiveDocument) is not None


COMMANDS = (("SWStyle_CopyWithMates", CopyWithMatesCommand),)
