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

import math

import FreeCAD as App
import FreeCADGui as Gui

from . import asmcore as ac


def picks():
    """(asm, [(component, element, shape)] two) for two picks on two components, else (None, [])."""
    try:
        sels = Gui.Selection.getSelectionEx("", 0)
    except Exception:
        return None, []
    out, asm = [], None
    for sel in sels:
        a = ac.assembly_of(sel.Object.Document)
        if a is None:
            return None, []
        asm = a
        for sub in sel.SubElementNames:
            if not sub:
                return None, []
            ref = ac.reference(asm, sel.Object, sub)
            if ref is None:
                return None, []
            shape = datum_shape(*ref) if sub.endswith(".") else ac.element(*ref)
            if shape is None:
                return None, []
            out.append((ref[0], ref[1], shape))
    if len(out) != 2 or out[0][0] is out[1][0]:
        return None, []
    return asm, out


def datum_shape(comp, sub):
    """A plane or axis picked in the FeatureManager tree (a component's Front Plane, Axis1): a face or
    edge where it lies in the assembly, so Quick Mates offer what the Mate PM would. None for a
    whole component or a feature."""
    import Part
    try:
        res = comp.getSubObject(sub, 2)     # retType 2: (sub object, its matrix in the assembly, ...)
        obj, mat = res[0], res[1]
    except Exception:
        return None
    if obj is None or mat is None or not hasattr(obj, "TypeId"):
        return None
    t = obj.TypeId
    plane = t in ("App::Plane", "PartDesign::Plane") or (t.endswith("Plane") and "Datum" in t)
    line = t in ("App::Line", "PartDesign::Line")
    if not (plane or line):
        return None
    pl = App.Placement(mat)
    base = pl.Base
    z = pl.Rotation.multVec(App.Vector(0, 0, 1))
    if plane:
        x = pl.Rotation.multVec(App.Vector(1, 0, 0))
        y = z.cross(x)
        size = 50.0
        pts = [base + x * size + y * size, base - x * size + y * size, base - x * size - y * size, base + x * size - y * size]
        return Part.Face(Part.makePolygon(pts + pts[:1]))
    d = pl.Rotation.multVec(App.Vector(1, 0, 0)) if t == "App::Line" else z     # an origin axis runs along its x
    return Part.LineSegment(base - d * 50.0, base + d * 50.0).toShape()


def kinds(s1, s2, refs=None):
    from .asmpm import POPUP_ORDER
    ok = ac.allowed(s1, s2, refs)
    return [k for k in POPUP_ORDER if k in ok]


def _direction(s):
    try:
        if s.ShapeType == "Face":
            u0, u1, v0, v1 = s.ParameterRange
            return s.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        if s.ShapeType == "Edge":
            return s.tangentAt(s.FirstParameter)
    except Exception as _fw_err:
        _fw_log("asmquickmates.py:99", _fw_err)
    return None


def current_value(kind, s1, s2):
    if kind == "Distance":
        try:
            n1, n2 = _direction(s1), _direction(s2)
            if s1.ShapeType == s2.ShapeType == "Face" and s1.Surface.TypeId == s2.Surface.TypeId == "Part::GeomPlane" \
                    and n1 is not None and n2 is not None and abs(abs(n1.dot(n2)) - 1) < 1e-9:
                return round(abs(n1.dot(s2.CenterOfMass - s1.CenterOfMass)), 6)    # parallel planes: apart along the normal
            return round(s1.distToShape(s2)[0], 6)
        except Exception:
            return 0.0
    if kind == "Angle":
        d1, d2 = _direction(s1), _direction(s2)
        if d1 is None or d2 is None:
            return 0.0
        return round(math.degrees(d1.getAngle(d2)), 6)
    return None


def make(asm, kind, p1, p2):
    doc = asm.Document
    doc.openTransaction("Quick Mate")
    try:
        joint = ac.add_mate(asm, kind, (p1[0], p1[1]), (p2[0], p2[1]), current_value(kind, p1[2], p2[2]))
        doc.recompute()
    finally:
        doc.commitTransaction()
    try:
        Gui.Selection.clearSelection()
    except Exception as _fw_err:
        _fw_log("asmquickmates.py:132", _fw_err)
    return joint


def entries(shell):
    from . import asmrefopts, contextbar, asmpm
    if not asmrefopts.customize("QuickMates"):
        return []
    asm, p = picks()
    if asm is None:
        return []
    refs = ((p[0][0], p[0][1]), (p[1][0], p[1][1]))
    out = []
    for kind in kinds(p[0][2], p[1][2], refs):
        out.append(contextbar.Entry("QuickMate" + kind, kind, asmpm.sw_icon(kind),
                                    contextbar._tip(kind, "Quick Mate: %s - %s" % (p[0][0].Label, p[1][0].Label)),
                                    lambda k=kind, a=asm, q=p: make(a, k, q[0], q[1]), True))
    return out


def install():
    from . import contextbar
    if getattr(contextbar, "_fw_quickmates", False):
        return
    original = contextbar.entries_for_selection

    def entries_for_selection(shell, *more, **named):
        try:
            if contextbar.sketch_in_edit() is None and not contextbar.dialog_open() \
                    and not contextbar.tool_running(shell):
                quick = entries(shell)
                if quick:
                    return "part", quick
        except Exception as error:
            App.Console.PrintLog("FreeCAD: quick mates: %s\n" % error)
        return original(shell, *more, **named)
    contextbar.entries_for_selection = entries_for_selection
    contextbar._fw_quickmates = True
