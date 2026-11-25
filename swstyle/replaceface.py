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
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
COMMAND = "SWStyle_ReplaceFace"
MARGIN = 1.0


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    n.normalize()
    return n


def _span(shape, origin, n):
    box = shape.optimalBoundingBox() if hasattr(shape, "optimalBoundingBox") else shape.BoundBox
    corners = [V(x, y, z) for x in (box.XMin, box.XMax) for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    ts = [(p - origin).dot(n) for p in corners]
    return min(ts), max(ts)


def _crossings(point, n, length, surfaces):
    """How many times the ray from point along n passes through the surfaces."""
    ray = Part.LineSegment(point, point + n * length).toShape()
    hits = []
    for s in surfaces:
        try:
            for v in ray.section(s).Vertexes:
                if not any(v.Point.distanceToPoint(h) < 1e-6 for h in hits):
                    hits.append(v.Point)
        except Exception:
            continue
    return len(hits)


def _inside_point(solid):
    """A point inside the solid: its centre of mass when that is inside (a curved slice's often is
    not), else the first inside point of a grid through its box."""
    c = solid.CenterOfMass
    if solid.isInside(c, 1e-7, False):
        return c
    box = solid.BoundBox
    for k in (3, 5, 9, 17):
        for i in range(k):
            for j in range(k):
                for m in range(k):
                    p = V(box.XMin + box.XLength * (i + 0.5) / k, box.YMin + box.YLength * (j + 0.5) / k,
                          box.ZMin + box.ZLength * (m + 0.5) / k)
                    if solid.isInside(p, 1e-7, False):
                        return p
    return c


def _samples(face, count=5):
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for i in range(count):
        for j in range(count):
            u = u0 + (u1 - u0) * (i + 0.5) / count
            v = v0 + (v1 - v0) * (j + 0.5) / count
            p = face.valueAt(u, v)
            if face.isInside(p, 1e-6, True):
                out.append(p)
    return out or [face.CenterOfMass]


def covers(face, surfaces):
    ""
    n = _normal(face)
    size = max(face.BoundBox.DiagonalLength, max(s.BoundBox.DiagonalLength for s in surfaces)) * 10 + 100
    for p in _samples(face):
        line = Part.LineSegment(p - n * size, p + n * size).toShape()
        if not any(line.section(s).Vertexes for s in surfaces):
            return False
    return True


def replace(body, face, surfaces):
    """body with face replaced by the faces surfaces."""
    n = _normal(face)
    origin = face.CenterOfMass
    lo, hi = 0.0, 0.0
    for s in surfaces:
        a, b = _span(s, origin, n)
        lo, hi = min(lo, a), max(hi, b)
    lo, hi = lo - MARGIN, hi + MARGIN
    start = face.copy()
    start.translate(n * lo)
    column = start.extrude(n * (hi - lo))
    # the column split by the surface: the pieces under it (an odd number of crossings going out
    # along the normal) are part material, the rest is air; a closed or folded surface works too
    pieces = column.generalFuse(list(surfaces))[0].Solids or [column]
    length = (hi - lo) * 2 + 10
    under = [p for p in pieces if _crossings(_inside_point(p), n, length, surfaces) % 2 == 1]
    keep = Part.makeCompound(under) if under else None
    air = column.cut(keep) if keep is not None else column
    result = body.cut(air)
    if keep is not None:
        result = result.fuse(face.copy().extrude(n * hi).common(keep))
    try:
        result = result.removeSplitter()
    except Exception as _fw_err:
        _fw_log("replaceface.py:130", _fw_err)
    if not result.Solids:
        raise RuntimeError("Nothing is left of the part")
    return result.Solids[0] if len(result.Solids) == 1 else Part.makeCompound(result.Solids)


def _away(shape, face):
    """The face's normal turned away from the faces round it (a surface body has no inside: the walls
    next to the face tell which way is out)."""
    n = _normal(face)
    lean = 0.0
    for e in face.Edges:
        mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        for f in shape.Faces:
            if f.isSame(face) or not any(e.isSame(x) for x in f.Edges):
                continue
            lean += (f.CenterOfMass - mid).dot(n)
    return n * -1 if lean > 0 else n


def _column(face, surfaces, n=None):
    """The column over the face along its normal through the surfaces, and its two parts: keep (the
    side of the surface the face is on) and air (past the surface)."""
    n = _normal(face) if n is None else n
    origin = face.CenterOfMass
    lo, hi = 0.0, 0.0
    for s in surfaces:
        a, b = _span(s, origin, n)
        lo, hi = min(lo, a), max(hi, b)
    lo, hi = lo - MARGIN, hi + MARGIN
    start = face.copy()
    start.translate(n * lo)
    column = start.extrude(n * (hi - lo))
    pieces = column.generalFuse(list(surfaces))[0].Solids or [column]
    length = (hi - lo) * 2 + 10
    under = [p for p in pieces if _crossings(_inside_point(p), n, length, surfaces) % 2 == 1]
    keep = Part.makeCompound(under) if under else None
    air = column.cut(keep) if keep is not None else column
    return n, hi, column, keep, air


def replace_surface(shape, face, surfaces):
    ""

    n, hi, column, keep, air = _column(face, surfaces, _away(shape, face))
    faces = []
    for f in shape.Faces:
        if f.isSame(face):
            continue
        try:
            cut = f.cut(air)
            faces += cut.Faces if cut.Faces else []
        except Exception:
            faces.append(f)
    for s in surfaces:          # the new face: the surface inside the column
        try:
            faces += s.common(column).Faces
        except Exception as _fw_err:
            _fw_log("replaceface.py:cap", _fw_err)
    if keep is not None and hi > 0:     # walls where the body grows past the old face
        sides = []      # only over the face's edges that have a face next to them (an open edge stays open)
        for e in face.Edges:
            if any(not f.isSame(face) and any(e.isSame(x) for x in f.Edges) for f in shape.Faces):
                try:
                    sides.append(e.copy().extrude(n * hi))
                except Exception as _fw_err:
                    _fw_log("replaceface.py:side", _fw_err)
        try:
            grow = face.copy().extrude(n * hi).common(keep)
            for g in grow.Faces:
                c = g.CenterOfMass
                if any(Part.Vertex(c).distToShape(sd)[0] < 1e-5 for sd in sides):
                    faces.append(g)
        except Exception as _fw_err:
            _fw_log("replaceface.py:walls", _fw_err)
    if not faces:
        raise RuntimeError("Nothing is left of the surface")
    from . import sewtol
    sewn = sewtol.sewn(faces, 1e-4)
    shells = sewn.Shells
    if len(shells) == 1:
        shell = shells[0]
        try:
            merged = shell.removeSplitter()
            if merged.isValid() and merged.ShapeType == "Shell" and abs(merged.Area - shell.Area) < 1e-6 * max(shell.Area, 1.0):
                shell = merged
        except Exception as _fw_err:
            _fw_log("replaceface.py:merge", _fw_err)
        return shell
    return sewn if not sewn.isNull() else Part.makeCompound(faces)


def _compute_surface(obj, base):
    """Replace Face in a part with surfaces only: the target faces' surface body is the base."""
    picked = [(o, f) for o, f in sf.elements(obj, "Targets") if f.ShapeType == "Face"]
    surfaces = []
    for _, f in sf.elements(obj, "Replacement"):
        if f.ShapeType == "Face":
            surfaces.append(f)
        elif not f.isNull() and not f.Solids:
            surfaces.extend(f.Faces)
    if not picked or not surfaces:
        return None, None
    source = picked[0][0]
    result = Part.getShape(source)
    for o, face in picked:
        if o is not source:
            raise RuntimeError("Pick target faces of one surface body")
        if not covers(face, surfaces):
            raise RuntimeError("The replacement surface must cover the target face seen square on: "
                               "extend it past the face's edges")
    for _, face in picked:
        target = next((f for f in result.Faces if f.isSame(face)), None)
        if target is None:
            target = next((f for f in result.Faces if abs(f.Area - face.Area) < 1e-6 and
                           f.CenterOfMass.distanceToPoint(face.CenterOfMass) < 1e-6), face)
        result = replace_surface(result, target, surfaces)
    return result, None


def _compute(obj, base):
    targets = [f for _, f in sf.elements(obj, "Targets") if f.ShapeType == "Face"]
    surfaces = []
    for _, f in sf.elements(obj, "Replacement"):
        if f.ShapeType == "Face":
            surfaces.append(f)
        elif not f.isNull() and not f.Solids:
            surfaces.extend(f.Faces)
    if not targets or not surfaces:
        return None, None
    result = base
    for face in targets:
        if not covers(face, surfaces):
            raise RuntimeError("The replacement surface must cover the target face seen square on: "
                               "extend it past the face's edges")
    for face in targets:
        result = replace(result, face, surfaces)
    before = base.Volume
    if abs(result.Volume - before) < 1e-9 and len(result.Faces) == len(base.Faces):
        raise RuntimeError("The surface does not cross the column over the target face: "
                           "it must cover the face seen square on")
    return result, None


class Panel(sf.Panel):
    """The plain page; the check hides the replacement surface, which the part has taken in."""

    def accept(self):
        surfaces = [o for o, _ in sf.elements(self.obj, "Replacement")]
        if getattr(self.obj, "SWStyleKind", "") == "ReplaceFaceSurface":
            surfaces += [o for o, _ in sf.elements(self.obj, "Targets")]     # the new body takes its place
        if not super().accept():
            return False
        for o in surfaces:
            if o.ViewObject is not None and o.getParentGeoFeatureGroup() is None:
                o.ViewObject.Visibility = False
        Gui.Selection.clearSelection()
        return True


SPEC = sf.Spec(
    COMMAND, "Replace Face", "Replace Face",
    "Replaces faces of the part with a surface, the part growing or shrinking to meet it.",
    "FEATURES_REPLACE_FACE", "Part_Offset",
    [Field("Targets", "pick", "Target faces for replacement", what=("Face",), many=True,
           box="Replace Parameters", tip="Faces of the part to replace"),
     Field("Replacement", "pick", "Replacement surface", what=("Face", ""), many=True,
           box="Replace Parameters", tip="The surface that takes their place: it must cover them")],
    _compute, panel=Panel)
SPEC.whole_surfaces = ("Replacement",)


SURFACE_SPEC = sf.Spec(
    COMMAND, "Replace Face", "Replace Face", SPEC.tip, SPEC.icon, SPEC.pixmap, SPEC.fields, _compute_surface,
    panel=Panel, needs_body=False)
SURFACE_SPEC.internal = "ReplaceFaceSurface"
SURFACE_SPEC.whole_surfaces = ("Replacement",)
sf.SPECS["ReplaceFaceSurface"] = SURFACE_SPEC
sf.SPECS[SPEC.internal] = SPEC


def surface_bodies(doc):
    from . import deleteface
    return [o for o in doc.Objects if deleteface.free_source(o) is not None and not Part.getShape(o).Solids]


class Command(sf.Command):
    """Replace Face on the solid when there is one, else on a surface body."""

    def IsActive(self):
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return False
        return sf.ready(self.spec, doc) or bool(surface_bodies(doc))

    def Activated(self):
        doc = App.ActiveDocument
        if doc is not None and not sf.ready(self.spec, doc) and surface_bodies(doc):
            from . import surfacefeatures as surf
            # faces picked first: those of the first surface body are the targets, the rest the replacement
            targets, replacement = [], []
            for sel in Gui.Selection.getSelectionEx("", 0):
                o = sel.Object
                for sub in sel.SubElementNames or [""]:
                    element = sub.split(".")[-1]
                    if not element.startswith("Face"):
                        continue
                    if not targets or targets[0][0] is o:
                        targets.append((o, element))
                    else:
                        replacement.append((o, element))
            picks = {}
            if targets:
                picks["Targets"] = targets
            if replacement:
                picks["Replacement"] = replacement
            surf.make(SURFACE_SPEC, picks=picks)
            return
        super().Activated()


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, Command(SPEC))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Replace Face command not added (%s)\n" % error)
