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

try:
    import FreeCADGui as Gui
    from PySide import QtWidgets
except Exception:   # pragma: no cover
    Gui = None

from . import asmcore as ac

INSIDE, CROSSING, OUTSIDE = "inside", "crossing", "outside"
SPECIAL = "Envelope Select"
CONDITIONS = ("is inside", "is crossing", "is outside")
LEAVE, SHOW, HIDE = "Leave its show/hide state as it is", "Show it", "Hide it"


def _shape(comp):
    from . import asmtools
    try:
        s = asmtools._global_shape(comp)
        return None if s is None or s.isNull() else s
    except Exception as _fw_err:
        _fw_log("asmenvelope.py:47", _fw_err)
        return None


def envelopes(asm):
    from . import asminsert
    return [c for c in ac.components(asm) if asminsert.is_envelope(c)]


def relation(comp, env, tol=1e-6):
    """Where comp is against the envelope env: inside, crossing or outside (None: no solid)."""
    a, e = _shape(comp), _shape(env)
    if a is None or e is None:
        return None
    if not a.BoundBox.intersect(e.BoundBox):
        return OUTSIDE
    try:
        vol = a.Volume
        if vol > tol and e.Solids:
            common = a.common(e).Volume
            if common <= tol * max(1.0, vol):
                return OUTSIDE
            return INSIDE if common >= vol * (1 - 1e-6) - tol else CROSSING
    except Exception as _fw_err:
        _fw_log("asmenvelope.py:69", _fw_err)
    b, eb = a.BoundBox, e.BoundBox
    inside = eb.isInside(b.getPoint(0)) and eb.isInside(b.getPoint(6)) if hasattr(b, "getPoint") else False
    return INSIDE if inside else CROSSING


def using(asm, env, inside=True, crossing=False, outside=False):
    """The components (not envelopes) in the asked places against env."""
    from . import asminsert
    want = {INSIDE: inside, CROSSING: crossing, OUTSIDE: outside}
    out = []
    for c in ac.components(asm):
        if c is env or asminsert.is_envelope(c):
            continue
        r = relation(c, env)
        if r is not None and want.get(r):
            out.append(c)
    return out


def select_using(asm, env, inside=True, crossing=False, outside=False):
    comps = using(asm, env, inside, crossing, outside)
    if Gui is not None:
        Gui.Selection.clearSelection()
        for c in comps:
            Gui.Selection.addSelection(c.Document.Name, c.Name)
    return comps


def show_hide_using(asm, env, actions):
    """actions: {inside/crossing/outside: LEAVE, SHOW or HIDE}. Returns {component: shown}."""
    from . import asminsert
    done = {}
    for c in ac.components(asm):
        if c is env or asminsert.is_envelope(c):
            continue
        act = actions.get(relation(c, env), LEAVE)
        if act == LEAVE:
            continue
        vo = getattr(c, "ViewObject", None)
        if vo is not None:
            vo.Visibility = act == SHOW
            done[c] = act == SHOW
    return done


# ---------------------------------------------------------------- Advanced Component Selection
def install_advanced_select():
    from . import asmreorg as ar
    if getattr(ar, "_fw_envelope", False):
        return
    ar._fw_envelope = True
    if SPECIAL not in ar.PROPERTIES:
        ar.PROPERTIES = tuple(ar.PROPERTIES) + (SPECIAL,)
    ar.CONDITIONS = tuple(ar.CONDITIONS) + tuple(c for c in CONDITIONS if c not in ar.CONDITIONS)
    old = ar.test

    def test(asm, comp, prop, cond, value):
        if prop != SPECIAL:
            return old(asm, comp, prop, cond, value)
        from . import asminsert
        if asminsert.is_envelope(comp):
            return False
        name = str(value).strip().lower()
        envs = [e for e in envelopes(asm) if not name or e.Label.lower() == name or ac.part_name(e).lower() == name]
        place = {"is inside": INSIDE, "is crossing": CROSSING, "is outside": OUTSIDE}.get(cond)
        if place is None or not envs:
            return False
        return any(relation(comp, e) == place for e in envs)
    ar.test = test


# ---------------------------------------------------------------- drawing BOMs
def install_drawing_bom():
    """Drawing BOM tables: envelope components (and Exclude from bill of materials) left out."""
    try:
        from . import drawtables
    except Exception:
        return
    if getattr(drawtables, "_fw_envelope", False):
        return
    drawtables._fw_envelope = True
    old = drawtables.bom_items

    def bom_items(view, bom_type="Top-level only", *args, **kwargs):
        items = old(view, bom_type, *args, **kwargs)
        from . import asminsert
        try:
            sources = list(drawtables.DV.source_shapes(view))
        except Exception:
            sources = []
        drop = {}           # the part object (what an item carries in row[4]) -> how many to take off
        for src in sources:
            if getattr(src, "TypeId", "") != "Assembly::AssemblyObject":
                continue
            for c in ac.components(src):
                if asminsert._out_of_bom(c):
                    base = getattr(c, "LinkedObject", None) or c
                    k = (base.Document.Name, base.Name)
                    drop[k] = drop.get(k, 0) + 1
        if not drop:
            return items
        out = []
        for row in items:
            key = (row[4].Document.Name, row[4].Name) if len(row) > 4 and row[4] is not None else None
            n = drop.get(key, 0)
            if n and row[3] == 0:
                row = list(row)
                take = min(n, row[2])
                row[2] -= take
                drop[key] = n - take
                if row[2] <= 0:
                    continue
            out.append(row)
        return out
    drawtables.bom_items = bom_items


# ---------------------------------------------------------------- the dialogs
if Gui is not None:
    class SelectUsingEnvelope(QtWidgets.QDialog):
        """Select Using Envelope: the components inside / crossing / outside the envelope."""

        def __init__(self, asm, env, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.asm, self.env = asm, env
            self.setObjectName("SWSelectUsingEnvelope")
            self.setWindowTitle("Select Using Envelope")
            lay = QtWidgets.QVBoxLayout(self)
            lay.addWidget(QtWidgets.QLabel("Envelope: %s" % env.Label))
            box = QtWidgets.QGroupBox("Select components that are")
            bl = QtWidgets.QVBoxLayout(box)
            self.inside = QtWidgets.QCheckBox("Inside the envelope")
            self.inside.setObjectName("SWEnvelopeInside")
            self.inside.setChecked(True)
            self.crossing = QtWidgets.QCheckBox("Crossing the envelope")
            self.crossing.setObjectName("SWEnvelopeCrossing")
            self.outside = QtWidgets.QCheckBox("Outside the envelope")
            self.outside.setObjectName("SWEnvelopeOutside")
            for w in (self.inside, self.crossing, self.outside):
                bl.addWidget(w)
            lay.addWidget(box)
            self.count = QtWidgets.QLabel("")
            self.count.setObjectName("SWEnvelopeCount")
            lay.addWidget(self.count)
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def accept(self):
            self.picked = select_using(self.asm, self.env, self.inside.isChecked(), self.crossing.isChecked(),
                                       self.outside.isChecked())
            self.count.setText("%d component(s) selected" % len(self.picked))
            super().accept()

    class ShowHideUsingEnvelope(QtWidgets.QDialog):
        """Show/Hide Using Envelope: for each place against the envelope, leave, show or hide."""

        def __init__(self, asm, env, parent=None):
            super().__init__(parent or Gui.getMainWindow())
            self.asm, self.env = asm, env
            self.setObjectName("SWShowHideUsingEnvelope")
            self.setWindowTitle("Show/Hide Using Envelope")
            lay = QtWidgets.QVBoxLayout(self)
            lay.addWidget(QtWidgets.QLabel("Envelope: %s" % env.Label))
            self.combos = {}
            defaults = {INSIDE: SHOW, CROSSING: LEAVE, OUTSIDE: HIDE}
            for place, title in ((INSIDE, "If a component is inside the envelope"),
                                 (CROSSING, "If a component is crossing the envelope"),
                                 (OUTSIDE, "If a component is outside the envelope")):
                box = QtWidgets.QGroupBox(title)
                bl = QtWidgets.QVBoxLayout(box)
                combo = QtWidgets.QComboBox()
                combo.setObjectName("SWEnvelope_%s" % place)
                combo.addItems([LEAVE, SHOW, HIDE])
                combo.setCurrentText(defaults[place])
                bl.addWidget(combo)
                lay.addWidget(box)
                self.combos[place] = combo
            bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)

        def actions(self):
            return {p: c.currentText() for p, c in self.combos.items()}

        def accept(self):
            doc = self.asm.Document
            doc.openTransaction("Show/Hide Using Envelope")
            try:
                self.done_ = show_hide_using(self.asm, self.env, self.actions())
            finally:
                doc.commitTransaction()
            super().accept()


def open_select(comp):
    asm = ac.assembly_of(comp.Document)
    dlg = SelectUsingEnvelope(asm, comp)
    dlg.open()
    return dlg


def open_show_hide(comp):
    asm = ac.assembly_of(comp.Document)
    dlg = ShowHideUsingEnvelope(asm, comp)
    dlg.open()
    return dlg


def menu_items(comp):
    """An envelope component's right-click entries."""
    from . import asminsert
    if not asminsert.is_envelope(comp):
        return []
    return [("SelectUsingEnvelope", "Select Using Envelope...", lambda: open_select(comp), True),
            ("ShowHideUsingEnvelope", "Show/Hide Using Envelope...", lambda: open_show_hide(comp), True)]


def install():
    install_advanced_select()
    install_drawing_bom()
