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
from PySide import QtWidgets

PROP = "FwThreadDisplay"
MODES = ("Simplified", "Cosmetic", "Schematic")
_installed = []


def mode_of(comp):
    return getattr(comp, PROP, "Simplified") or "Simplified"


def _thread_face(comp):
    """The shank: the longest cylinder of the fastener (placed shape)."""
    best = None
    try:
        faces = comp.Shape.Faces
    except Exception:
        return None
    for f in faces:
        s = f.Surface
        if s.TypeId != "Part::GeomCylinder":
            continue
        h = f.ParameterRange[3] - f.ParameterRange[2]
        if best is None or h > best[0]:
            best = (h, f)
    return best[1] if best else None


def _pitch(d):
    table = {3: .5, 4: .7, 5: .8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0}
    return table.get(int(round(d)), max(0.5, d * 0.15))


def _thread_len(comp, total):
    try:
        from . import toolbox
        kind, size, length = toolbox.info(comp)[:3]
        tl = getattr(toolbox, "thread_length", None)
        if tl is not None:
            v = tl(size, length)
            if v:
                return min(float(v), total)
    except Exception as _fw_err:
        _fw_log("asmthread.py:63", _fw_err)
    return total


def _marks_name(comp):
    return comp.Name + "_Thread"


def apply(asm, comp, mode):
    """Set the component's Thread Display and rebuild its thread marks."""
    import Part
    doc = comp.Document
    if not hasattr(comp, PROP):
        comp.addProperty("App::PropertyEnumeration", PROP, "FreeCAD", "Thread Display (Toolbox)")
        setattr(comp, PROP, list(MODES))
    setattr(comp, PROP, mode)
    old = doc.getObject(_marks_name(comp))
    if old is not None:
        doc.removeObject(old.Name)
    if mode == "Simplified":
        return None
    f = _thread_face(comp)
    if f is None:
        return None
    s = f.Surface
    ax = App.Vector(s.Axis)
    ax.normalize()
    r = s.Radius
    v0, v1 = f.ParameterRange[2], f.ParameterRange[3]
    total = v1 - v0
    tl = _thread_len(comp, total)
    p = _pitch(2 * r)
    minor = r - 0.6134 * p
    # the thread runs from the shank's free end (the end away from the head: the far end)
    start = s.Center + ax * v1
    edges = []
    steps = [0.0, tl] if mode == "Cosmetic" else [k * p for k in range(int(tl / p) + 1)]
    for t in steps:
        c = start - ax * t
        edges.append(Part.makeCircle(minor if mode == "Cosmetic" else (minor if steps.index(t) % 2 else r), c, ax))
    if mode == "Cosmetic":
        a, b = start, start - ax * tl
        n = ax.cross(App.Vector(1, 0, 0)) if abs(ax.x) < .9 else ax.cross(App.Vector(0, 1, 0))
        n.normalize()
        for sgn in (1, -1):
            edges.append(Part.makeLine(a + n * minor * sgn, b + n * minor * sgn))
    o = doc.addObject("Part::Feature", _marks_name(comp))
    o.Label = "Thread (%s)" % comp.Label
    o.Shape = Part.Compound(edges)
    o.addProperty("App::PropertyString", "FwThreadOf", "FreeCAD", "The fastener these thread marks belong to")
    o.FwThreadOf = comp.Name
    o.setEditorMode("FwThreadOf", 2)
    try:
        asm.addObject(o)
    except Exception as _fw_err:
        _fw_log("asmthread.py:118", _fw_err)
    if App.GuiUp and o.ViewObject is not None:
        o.ViewObject.LineColor = (0.35, 0.35, 0.35)
        o.ViewObject.LineWidth = 1.0
        try:
            o.ViewObject.DrawStyle = "Dashed"
        except Exception as _fw_err:
            _fw_log("asmthread.py:125", _fw_err)
        o.ViewObject.Selectable = False
    return o


def _add_row(panel):
    """The Thread Display row under Thread Length."""
    le = getattr(panel, "thread", None)
    if le is None or getattr(panel, "_fw_thread_combo", None) is not None:
        return
    combo = QtWidgets.QComboBox()
    combo.setObjectName("SWToolboxThreadDisplay")
    combo.addItems(list(MODES))
    comps = list(getattr(panel, "comps", []) or [])
    if comps and type(panel).__name__ == "FastenerPanel":
        combo.setCurrentText(mode_of(comps[0]))
    # the row goes into the QFormLayout that holds Thread Length
    target = None
    for l in panel_layouts(panel):
        if isinstance(l, QtWidgets.QFormLayout):
            for i in range(l.rowCount()):
                it = l.itemAt(i, QtWidgets.QFormLayout.FieldRole)
                if it is not None and it.widget() is le:
                    target = l
    if target is None:
        return
    row = next((i for i in range(target.rowCount()) if target.itemAt(i, QtWidgets.QFormLayout.FieldRole) is not None
                and target.itemAt(i, QtWidgets.QFormLayout.FieldRole).widget() is le), None)
    if row is None:
        target.addRow("Thread Display:", combo)
    else:
        target.insertRow(row + 1, "Thread Display:", combo)       # extapps143: right under Thread Length, as the docstring says
    panel._fw_thread_combo = combo
    if hasattr(panel, "_labels"):
        try:
            panel._labels()                 # a nut, washer or pin has no thread to show
        except Exception as _fw_err:
            _fw_log("asmthread.py:143", _fw_err)


def panel_layouts(panel):
    forms = panel.form if isinstance(panel.form, list) else [panel.form]
    out = []
    for f in forms:
        try:
            out += f.findChildren(QtWidgets.QLayout)
        except Exception as _fw_err:
            _fw_log("asmthread.py:162", _fw_err)
    return out


def _fasteners(panel):
    name = type(panel).__name__
    if name == "FastenerPanel":
        return list(panel.comps)
    out = []
    for e in getattr(panel, "entries", []) or []:
        out += [c for c in e.get("comps", []) if c is not None]
    return out


def _on_accept(panel, mode, before):
    asm = panel.asm
    for c in list(before) + [c for c in _fasteners(panel) if c not in before]:
        try:
            if c.isValid():
                apply(asm, c, mode)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: thread display: %s\n" % error)
    asm.Document.recompute()


def install():
    from . import asmpm
    if _installed:
        return
    orig = asmpm._track

    def track(panel):
        if type(panel).__name__ in ("FastenerPanel", "SmartFastenersPanel"):
            try:
                _add_row(panel)
                acc = panel.accept

                def accept(*a, _acc=acc, _p=panel):
                    combo = getattr(_p, "_fw_thread_combo", None)
                    mode = combo.currentText() if combo is not None else None
                    before = _fasteners(_p)
                    out = _acc(*a)
                    if mode is not None:
                        _on_accept(_p, mode, before)
                    return out
                panel.accept = accept
            except Exception as error:
                App.Console.PrintLog("FreeCAD: thread display row: %s\n" % error)
        return orig(panel)
    track.__wrapped__ = orig
    asmpm._track = track
    _installed.append(orig)
