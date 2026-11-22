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

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

from . import naming, smedgegeom, smflatten
from . import smlive
from .smbaseflange import _box, _spin
from .smedgeflange import _radio, error_label
from .smunfold import _DeleteKey, _body_of, _icon, _list, _sheet_body

COMMAND = "SWStyle_SMClosedCorner"
TITLE = "Closed Corner"
GROUP = "Closed Corner"
TYPES = ("Butt", "Overlap", "Underlap")
V = App.Vector
NOT_END = "Select the end face of a flat flange at the corner."
NO_MATCH = "No flange to close against was found for {}. Pick the face to match."


# ================================================================ geometry
def _plane(f):
    return f.Surface.TypeId == "Part::GeomPlane"


def face_normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)


def wall_of(shape, face):
    """For the end face of a flat wall: the wall's two faces (normal m, a point on each), thickness T."""
    n = face_normal(face)
    cand = []
    for e in face.Edges:
        for g in shape.ancestorsOfType(e, Part.Face):
            if not g.isSame(face) and _plane(g) and abs(face_normal(g).dot(n)) < 1e-3:
                cand.append(g)
    best = None
    for i, g in enumerate(cand):
        for h in cand[i + 1:]:
            mg = face_normal(g)
            if mg.dot(face_normal(h)) < -0.999:
                d = abs((h.CenterOfMass - g.CenterOfMass).dot(mg))
                if d > 1e-4 and (best is None or g.Area + h.Area > best[3]):
                    best = (g, h, d, g.Area + h.Area)
    if best is None:
        return None
    g, h, d, _a = best
    return {"m": face_normal(g), "pa": g.CenterOfMass, "pb": h.CenterOfMass, "T": d,
            "big": g if g.Area >= h.Area else h, "face": face, "n": n}


def coplanar(shape, face):
    """The face and the planar faces in its plane that touch it, one after the other (bend ends, split walls)."""
    n, c = face_normal(face), face.CenterOfMass
    out, todo = [face], [face]
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in shape.ancestorsOfType(e, Part.Face):
                if any(g.isSame(x) for x in out) or not _plane(g):
                    continue
                if face_normal(g).dot(n) > 1 - 1e-6 and abs((g.CenterOfMass - c).dot(n)) < 1e-6:
                    out.append(g)
                    todo.append(g)
    return out


def match(shape, face, wall):
    """The end face of the flange this end runs into: (face, its wall), else None."""
    n, c = wall["n"], face.CenterOfMass
    reach = 20 * wall["T"] + 20
    best = None
    for g in shape.Faces:
        if not _plane(g) or g.isSame(face):
            continue
        nb = face_normal(g)
        cb = g.CenterOfMass
        if abs(nb.dot(n)) > 0.99 or (cb - c).dot(n) <= 0 or (cb - c).Length > reach:
            continue
        wb = wall_of(shape, g)
        if wb is None or abs(wb["T"] - wall["T"]) > 1e-4:
            continue
        if abs(wb["m"].dot(n)) < 0.5 or abs(wall["m"].dot(nb)) < 0.5:
            continue
        dist = face.distToShape(g)[0]
        if best is None or dist < best[0]:
            best = (dist, g, wb)
    return (best[1], best[2]) if best else None


def _inner(wall, other):
    """(inner point, outer point) of a wall: its inner face is the one nearer the other flange."""
    m, q = wall["m"], other["big"].CenterOfMass
    da, db = abs((q - wall["pa"]).dot(m)), abs((q - wall["pb"]).dot(m))
    return (wall["pa"], wall["pb"]) if da < db else (wall["pb"], wall["pa"])


def _both(m1, p1, m2, p2):
    """A point on both planes (normal m1 through p1, normal m2 through p2)."""
    d1, d2, c = p1.dot(m1), p2.dot(m2), m1.dot(m2)
    det = 1 - c * c
    return m1 * ((d1 - c * d2) / det) + m2 * ((d2 - c * d1) / det)


def limits(A, B, kind, gap, ratio):
    """The plane each flange ends at: (point, normal toward the side the flange keeps), for A and B."""
    ai, ao = _inner(A, B)
    bi, bo = _inner(B, A)

    def side(q, m, keep):
        return q, (m if (keep - q).dot(m) > 0 else m * -1)

    if kind == "Butt":
        ma = A["m"] if (B["big"].CenterOfMass - ai).dot(A["m"]) > 0 else A["m"] * -1
        mb = B["m"] if (A["big"].CenterOfMass - bi).dot(B["m"]) > 0 else B["m"] * -1
        return side(bi + mb * gap, B["m"], A["big"].CenterOfMass), side(ai + ma * gap, A["m"], B["big"].CenterOfMass)
    if kind == "Diagonal":
        u = A["m"].cross(B["m"]).normalize()
        p_in, p_out = _both(A["m"], ai, B["m"], bi), _both(A["m"], ao, B["m"], bo)
        s = u.cross(p_in - p_out).normalize()
        qa, ka = side(p_in, s, A["big"].CenterOfMass)
        qb, kb = side(p_in, s, B["big"].CenterOfMass)
        return (qa + ka * (gap / 2), ka), (qb + kb * (gap / 2), kb)
    cover, under = (A, B) if kind == "Overlap" else (B, A)
    ci = ai if cover is A else bi
    ui, uo = (bi, bo) if cover is A else (ai, ao)
    mu = under["m"] if (uo - ui).dot(under["m"]) > 0 else under["m"] * -1
    lc = side(ui + mu * (ratio * A["T"]), under["m"], cover["big"].CenterOfMass)
    mc = cover["m"] if (under["big"].CenterOfMass - ci).dot(cover["m"]) > 0 else cover["m"] * -1
    lu = side(ci + mc * gap, cover["m"], under["big"].CenterOfMass)
    return (lc, lu) if cover is A else (lu, lc)


def _halfspace(q, k, size):
    box = Part.makeBox(2 * size, 2 * size, size, V(-size, -size, 0))
    box.Placement = App.Placement(q, App.Rotation(V(0, 0, 1), k))
    return box


def corners(shape, faces, matches=None, auto=True):
    """Pair each face to extend with its face to match: [(fa, A, fb, B)]. A pair picked from both
    sides counts once."""
    out = []
    for i, fa in enumerate(faces):
        A = wall_of(shape, fa)
        if A is None:
            raise ValueError(NOT_END)
        fb = None
        if not auto:
            fb = matches[i] if matches and i < len(matches) else None
            B = wall_of(shape, fb) if fb is not None else None
            if B is None:
                raise ValueError(NO_MATCH.format("face %d" % (i + 1)))
        else:
            found = match(shape, fa, A)
            if found is None:
                raise ValueError(NO_MATCH.format("face %d" % (i + 1)))
            fb, B = found
        if any(fb.isSame(x[0]) and fa.isSame(x[2]) for x in out):
            continue
        out.append((fa, A, fb, B))
    return out


def bend_radius(shape, faces):
    """The inside radius of the bends whose end faces are among faces (0 when none)."""
    radii = [e.Curve.Radius for g in faces if wall_of(shape, g) is None for e in g.Edges
             if e.Curve.TypeId == "Part::GeomCircle"]
    return min(radii) if radii else 0.0


def close(shape, pairs, kind="Overlap", gap=0.1, ratio=1.0, open_bend=False, coplanar_faces=True, narrow=False):
    """The shape with each corner closed."""
    size = shape.BoundBox.DiagonalLength * 4 + 100
    adds, cuts = [], []
    for fa, A, fb, B in pairs:
        walls = limits(A, B, kind, gap, ratio)
        # the bend ends close on the corner's diagonal whatever the corner type, so the two bends
        # never run into each other; without Narrow corner their gap is wider by the bend radius
        bend_gap = gap
        if not open_bend and not narrow:
            ends = (coplanar(shape, fa) if coplanar_faces else [fa]) + (coplanar(shape, fb) if coplanar_faces else [fb])
            bend_gap = gap + bend_radius(shape, ends)
        bends = limits(A, B, "Diagonal", bend_gap, ratio)
        for wall, f0, lw, lb in ((A, fa, walls[0], bends[0]), (B, fb, walls[1], bends[1])):
            group = coplanar(shape, f0) if coplanar_faces else [f0]
            n = wall["n"]
            for g in group:
                flat = g.isSame(f0) or wall_of(shape, g) is not None
                if not flat and open_bend:
                    continue
                q, k = lw if flat else lb
                keep = _halfspace(q, k, size)
                den = n.dot(k)
                t = (q - g.CenterOfMass).dot(k) / den if abs(den) > 1e-9 else 0.0
                length = abs(t) + 4 * wall["T"] + 10
                adds.append(g.extrude(n * length).common(keep))
                cuts.append(g.extrude(n * -length).cut(keep))
    out = shape
    for c in cuts:
        if c.Volume > 1e-9:
            out = out.cut(c)
    for a in adds:
        if a.Volume > 1e-9:
            out = out.fuse(a)
    return out.removeSplitter()


def face_at(shape, p, normal=None):
    """The planar face of shape holding point p; for a point on a face this feature moved, the face
    facing the same way that p slid along its normal from."""
    hit = next(("Face%d" % i for i, f in enumerate(shape.Faces, 1)
                if _plane(f) and f.isInside(p, 1e-5, True)), None)
    if hit is not None or normal is None:
        return hit
    best = None
    for i, f in enumerate(shape.Faces, 1):
        if _plane(f) and face_normal(f).dot(normal) > 1 - 1e-6:
            d = (p - f.CenterOfMass).dot(normal)
            if f.isInside(p - normal * d, 1e-5, True) and (best is None or abs(d) < best[0]):
                best = (abs(d), "Face%d" % i)
    return best[1] if best else None


def inside_point(face):
    u0, u1, v0, v1 = face.ParameterRange
    p = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
    return p if face.isInside(p, 1e-7, True) else face.Vertexes[0].Point


# ================================================================ feature
_LAST = None        # the open Closed Corner PropertyManager


class SWClosedCorner:
    def __init__(self, obj):
        add = obj.addProperty
        add("App::PropertyStringList", "FacesToExtend", GROUP, "Faces to extend, as picked")
        add("App::PropertyVectorList", "ExtendPoints", GROUP, "A point on each face to extend")
        add("App::PropertyStringList", "FacesToMatch", GROUP, "Faces to match, as picked (Auto propagation off)")
        add("App::PropertyVectorList", "MatchPoints", GROUP, "A point on each face to match")
        add("App::PropertyEnumeration", "CornerType", GROUP, "Butt, Overlap or Underlap")
        add("App::PropertyLength", "GapDistance", GROUP, "Gap between the two flanges")
        add("App::PropertyFloat", "OverlapRatio", GROUP, "Overlap/underlap ratio (1 = the full thickness)")
        add("App::PropertyBool", "OpenBendRegion", GROUP, "Leave the bend ends open")
        add("App::PropertyBool", "CoplanarFaces", GROUP, "Extend the faces in the plane of a picked face too")
        add("App::PropertyBool", "NarrowCorner", GROUP, "Narrow the gap at large bend radii")
        add("App::PropertyBool", "AutoPropagation", GROUP, "Find the faces to match")
        obj.CornerType = list(TYPES)
        obj.CornerType = "Overlap"
        obj.GapDistance = 0.1
        obj.OverlapRatio = 1.0
        obj.OpenBendRegion = True      # closed bend ends cannot be flattened yet
        obj.CoplanarFaces = True
        obj.AutoPropagation = True
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature
        if base is None:
            raise ValueError("Closed Corner: needs a sheet metal part")
        from . import pointrefs        # the picked faces follow an edit before the corner
        pointrefs.follow(obj, base, "ExtendPoints", "face")
        pointrefs.follow(obj, base, "MatchPoints", "face")
        shape, kept = smedgegeom.corner_base(base)
        if not obj.ExtendPoints:
            obj.Shape = smedgegeom.corner_result(obj, shape, shape, kept)
            return
        obj.Shape = smedgegeom.corner_result(obj, shape, closed(obj, shape), kept)

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _on_part(shape, source, p):
    ""



    if source is None:
        return None
    on = next((f for f in source.Faces if _plane(f) and f.isInside(p, 1e-5, True)), None)
    if on is None:
        return None
    n = face_normal(on)
    vp = Part.Vertex(p)
    best = None
    for i, f in enumerate(shape.Faces, 1):
        if _plane(f) and face_normal(f).dot(n) > 1 - 1e-6 and abs((p - f.CenterOfMass).dot(n)) < 1e-5:
            d = f.distToShape(vp)[0]
            if d < on.BoundBox.DiagonalLength and (best is None or d < best[0]):
                best = (d, "Face%d" % i)
    return best[1] if best else None


def _faces(shape, points, source=None):
    out = []
    for p in points:
        name = face_at(shape, p) or _on_part(shape, source, p)
        if name is None:
            raise ValueError("Closed Corner: a picked face is gone; edit the feature and pick it again")
        out.append(shape.getElement(name))
    return out


def pairs_of(obj, shape):
    base = getattr(obj, "BaseFeature", None)
    source = base.Shape if base is not None and not base.Shape.isNull() else None
    faces = _faces(shape, obj.ExtendPoints, source)
    matches = None if obj.AutoPropagation else _faces(shape, obj.MatchPoints, source)
    return corners(shape, faces, matches, obj.AutoPropagation)


def closed(obj, shape):
    ratio = 1.0 if obj.CornerType == "Butt" else min(max(obj.OverlapRatio, 0.0), 1.0)
    return close(shape, pairs_of(obj, shape), obj.CornerType, float(obj.GapDistance), ratio,
                 obj.OpenBendRegion, obj.CoplanarFaces, obj.NarrowCorner)


class ViewProviderClosedCorner:
    ICON = "SheetMetal_Extrude"

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return _icon(self.ICON)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        obj = vobj.Object
        obj.Document.openTransaction("Edit " + obj.Label)
        try:
            Gui.Control.showDialog(Panel(obj, False))
        except BaseException:
            try:
                obj.Document.abortTransaction()
            except Exception:
                pass
            raise
        return True

    def unsetEdit(self, vobj, mode=0):
        return False

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def is_closed_corner(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "SWClosedCorner"


def make(body):
    doc = body.Document
    base = body.Tip
    obj = doc.addObject("PartDesign::FeaturePython", "ClosedCorner")
    SWClosedCorner(obj)
    if App.GuiUp:
        ViewProviderClosedCorner(obj.ViewObject)
    body.addObject(obj)
    obj.Label = naming.next_label(doc, "Closed Corner")
    if base is not None:
        try:
            base.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("smclosedcorner.py:384", _fw_err)
    return obj


# ================================================================ PropertyManager
class Panel:
    """The Closed Corner PropertyManager."""
    HINT = "Select the end faces of the flanges to extend."

    def __init__(self, obj, new):
        global _LAST
        _LAST = self
        self.obj = obj
        self.new = new
        box = _box("Faces to Extend")
        f = box.layout()
        f.addRow(QtWidgets.QLabel("Faces to extend:"))
        self.extend = _list("SWSMCornerExtend", "#ffd6ec", "Faces to Extend: the end faces of the flanges", rows=3)
        f.addRow(self.extend)
        self.match_label = QtWidgets.QLabel("Faces to match:")
        f.addRow(self.match_label)
        self.match = _list("SWSMCornerMatch", "#d6ecff", "Faces to Match: the flanges the extended faces close against",
                           rows=3)
        f.addRow(self.match)
        f.addRow(QtWidgets.QLabel("Corner type:"))
        row = QtWidgets.QHBoxLayout()
        self.types = {}
        for t in TYPES:
            b = _radio("SWSMCorner" + t, t)
            self.types[t] = b
            row.addWidget(b)
        f.addRow(row)
        self.gap = _spin("SWSMCornerGap", float(obj.GapDistance), 0.0, 1000.0, step=0.1)
        self.gap.setToolTip("Gap distance")
        f.addRow("Gap distance:", self.gap)
        self.ratio = _spin("SWSMCornerRatio", obj.OverlapRatio, 0.0, 1.0, suffix="", step=0.1)
        self.ratio.setToolTip("Overlap/underlap ratio: how far the covering flange runs across the other's thickness")
        f.addRow("Overlap/underlap ratio:", self.ratio)
        self.open_bend = QtWidgets.QCheckBox("Open bend region")
        self.open_bend.setObjectName("SWSMCornerOpenBend")
        self.open_bend.setToolTip("Off: the bend ends close on the corner's diagonal too, but the part can no "
                                  "longer be flattened.")
        self.coplanar = QtWidgets.QCheckBox("Coplanar faces")
        self.coplanar.setObjectName("SWSMCornerCoplanar")
        self.narrow = QtWidgets.QCheckBox("Narrow corner")
        self.narrow.setObjectName("SWSMCornerNarrow")
        self.narrow.setToolTip("Closes the bend ends up to the gap distance (with Open bend region off); off, "
                               "their gap is wider by the bend radius")
        self.auto = QtWidgets.QCheckBox("Auto propagation")
        self.auto.setObjectName("SWSMCornerAuto")
        for w, v in ((self.open_bend, obj.OpenBendRegion), (self.coplanar, obj.CoplanarFaces),
                     (self.narrow, obj.NarrowCorner), (self.auto, obj.AutoPropagation)):
            w.setChecked(bool(v))
            f.addRow(w)
        self.error = error_label()
        f.addRow(self.error)
        box.setProperty("swstyle_pm_title", TITLE)
        box.setProperty("swstyle_pm_icon", "SheetMetal_Extrude")
        self.form = [box]
        self.types[obj.CornerType].setChecked(True)
        smlive.row(self.ratio, obj.CornerType != "Butt")      # hidden where it doesn't apply, never greyed
        smlive.row(self.narrow, not obj.OpenBendRegion)
        for b in self.types.values():
            b.toggled.connect(self._changed)
        self.gap.valueChanged.connect(self._changed)
        self.ratio.valueChanged.connect(self._changed)
        for w in (self.open_bend, self.coplanar, self.narrow, self.auto):
            w.toggled.connect(self._changed)
        self.keys = _DeleteKey(self)
        for w in (self.extend, self.match):
            w.installEventFilter(self.keys)
        self.active = self.extend
        self._mark()
        self._fill()
        self._report()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w is self.extend or (w is self.match and not self.auto.isChecked()):
            self.active = w
            self._mark()

    def _mark(self):
        for w in (self.extend, self.match):
            w.setProperty("swstyle_active", w is self.active)
            w.setFrameShape(QtWidgets.QFrame.Box if w is self.active else QtWidgets.QFrame.StyledPanel)

    def remove_current(self, w):
        row = w.currentRow()
        if row < 0:
            return
        if w is self.extend:
            names, points = list(self.obj.FacesToExtend), list(self.obj.ExtendPoints)
            del names[row], points[row]
            self.obj.FacesToExtend, self.obj.ExtendPoints = names, points
        elif not self.auto.isChecked():
            names, points = list(self.obj.FacesToMatch), list(self.obj.MatchPoints)
            del names[row], points[row]
            self.obj.FacesToMatch, self.obj.MatchPoints = names, points
        self._apply()

    def _fill(self):
        self.extend.clear()
        for n in self.obj.FacesToExtend:
            self.extend.addItem(n)
        self.match.clear()
        if self.auto.isChecked():
            try:
                shape = smedgegeom.trimmed_shape(self.obj.BaseFeature)
                found = [fb for _fa, _A, fb, _B in pairs_of(self.obj, shape)]
                names = {f.hashCode(): "Face%d" % i for i, f in enumerate(shape.Faces, 1)}
                for fb in found:
                    self.match.addItem(names.get(fb.hashCode(), "Face"))
            except Exception as _fw_err:
                _fw_log("smclosedcorner.py:499", _fw_err)
        else:
            for n in self.obj.FacesToMatch:
                self.match.addItem(n)

        # found (PM thread pkg349b; drawings-land281 had hidden the label with the box)

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        if sub.startswith("Face"):
            at = App.Vector(*point) if point else None
            QtCore.QTimer.singleShot(0, lambda: self._picked(doc, name, sub, at))

    def _picked(self, doc_name, name, sub, at):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smclosedcorner.py:515", _fw_err)
        picked = App.getDocument(doc_name).getObject(name)
        if picked is None or picked.Shape.isNull():
            return
        face = picked.Shape.getElement(sub)
        if not _plane(face):
            self.error.setText(NOT_END)
            self.error.show()
            return
        if at is None or face.distToShape(Part.Vertex(at))[0] > 1e-3:   # no picked point (a scripted or tree pick)
            at = inside_point(face)
        base = smedgegeom.trimmed_shape(self.obj.BaseFeature)
        fname = face_at(base, at, face_normal(face))
        if fname is None:
            return
        p = at if base.getElement(fname).isInside(at, 1e-5, True) else inside_point(base.getElement(fname))
        if self.active is self.match:
            names, points = list(self.obj.FacesToMatch), list(self.obj.MatchPoints)
            prop = ("FacesToMatch", "MatchPoints")
        else:
            names, points = list(self.obj.FacesToExtend), list(self.obj.ExtendPoints)
            prop = ("FacesToExtend", "ExtendPoints")
        if fname in names:          # picked again: take it out
            i = names.index(fname)
            del names[i], points[i]
        else:
            names.append(fname)
            points.append(p)
        setattr(self.obj, prop[0], names)
        setattr(self.obj, prop[1], points)
        if self.active is self.extend and not self.auto.isChecked() and len(self.obj.MatchPoints) < len(names):
            self.set_active(self.match)
        elif self.active is self.match and len(names) >= len(self.obj.ExtendPoints):
            self.set_active(self.extend)
        self._apply()

    # ---------------------------------------------------------------- result
    def _changed(self, *_a):
        obj = self.obj
        obj.CornerType = next(t for t, b in self.types.items() if b.isChecked()) if any(
            b.isChecked() for b in self.types.values()) else "Overlap"
        obj.GapDistance = self.gap.value()
        obj.OverlapRatio = self.ratio.value()
        obj.OpenBendRegion = self.open_bend.isChecked()
        obj.CoplanarFaces = self.coplanar.isChecked()
        obj.NarrowCorner = self.narrow.isChecked()
        obj.AutoPropagation = self.auto.isChecked()
        smlive.row(self.ratio, obj.CornerType != "Butt")      # hidden where it doesn't apply, never greyed
        smlive.row(self.narrow, not obj.OpenBendRegion)
        if self.auto.isChecked() and self.active is self.match:
            self.set_active(self.extend)
        self._apply()

    def _apply(self):
        self.obj.touch()
        self.obj.Document.recompute()
        self._fill()
        self._report()

    def _report(self):
        if "Invalid" in self.obj.State:
            self.error.setText(self.obj.getStatusString())
        elif not self.obj.ExtendPoints:
            self.error.setText(self.HINT)
        else:
            self.error.setText("")
        self.error.setVisible(bool(self.error.text()))
        return not self.error.text()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smclosedcorner.py:591", _fw_err)
        Gui.Control.closeDialog()
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                Gui.ActiveDocument.resetEdit()
        except Exception as _fw_err:
            _fw_log("smclosedcorner.py:597", _fw_err)

    def accept(self):
        if not self._report():
            return False
        self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        base = self.obj.BaseFeature if self.new else None
        doc.abortTransaction()
        doc.recompute()
        if base is not None:
            try:
                base.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("smclosedcorner.py:615", _fw_err)
        self._close()
        return True


# ================================================================ command
def start():
    body = _sheet_body()
    if body is None:
        return
    doc = body.Document
    picked = [(o.Document.Name, o.Object.Name, sub, App.Vector(p)) for o in Gui.Selection.getSelectionEx()
              for sub, p in zip(o.SubElementNames, o.PickedPoints) if sub.startswith("Face")]
    doc.openTransaction(TITLE)
    try:
        obj = make(body)
        doc.recompute()
        panel = Panel(obj, True)
        Gui.Control.showDialog(panel)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    for doc_name, name, sub, at in picked:     # faces selected before the command count as picked
        panel._picked(doc_name, name, sub, at)


class Command:
    def GetResources(self):
        return {"Pixmap": _icon("SheetMetal_Extrude"), "MenuText": TITLE,
                "ToolTip": "Extends flange faces to close the gap at a corner."}

    def IsActive(self):
        return _sheet_body() is not None

    def Activated(self):
        start()


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
