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
import Part

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector


FACE_METHODS = ("Symmetric", "Asymmetric", "Chord Width", "Hold Line")
FACE_PROFILES = ("Circular", "Conic Rho", "Conic Radius", "Curvature Continuous")


def _own_faces(base, picked):
    """The faces of the part so far that the picks name (picks may come from a later view)."""
    out = []
    for _src, face in picked:
        if face is None or face.ShapeType != "Face":
            continue
        match = [f for f in base.Faces if abs(f.Area - face.Area) < 1e-6 * max(1.0, face.Area)
                 and f.CenterOfMass.distanceToPoint(face.CenterOfMass) < 1e-6]
        if match and not any(match[0].isSame(o) for o in out):
            out.append(match[0])
    return out


def _face_fillet(obj, base):
    set1 = _own_faces(base, sf.elements(obj, "FaceSet1"))
    set2 = _own_faces(base, sf.elements(obj, "FaceSet2"))
    if not set1 or not set2:
        return None, None
    r = float(obj.Radius)
    if r <= 0:
        raise RuntimeError("The radius must be more than 0")
    edges = []
    for a in set1:
        for b in set2:
            for e in a.Edges:
                if any(e.isSame(x) for x in b.Edges) and not any(e.isSame(x) for x in edges):
                    edges.append(e)
    if not edges:
        return gap_fillet(base, set1, set2, r), None
    own = [x for x in base.Edges if any(x.isSame(e) for e in edges)]
    method = str(getattr(obj, "Method", "Symmetric"))
    holds = [shape for _src, shape in sf.elements(obj, "HoldLine") if shape is not None] \
        if "HoldLine" in obj.PropertiesList and method == "Hold Line" else []
    if method == "Hold Line":
        if not holds:
            return None, None          # waits for the hold line
        return hold_line_fillet(base, own, holds), None
    profile = str(getattr(obj, "Profile", "Circular"))
    if method == "Chord Width":
        return chord_fillet(base, own, float(obj.ChordWidth), profile, obj), None
    if method == "Asymmetric" or profile != "Circular":
        d1, d2 = (float(obj.Distance1), float(obj.Distance2)) if method == "Asymmetric" else (r, r)
        return _conic_on_sets(base, own, set1, d1, d2, profile, obj, r if method == "Symmetric" else None), None
    from . import filletrescue      # where OpenCascade refuses: Keep features, overflow, corners, passes
    return filletrescue.constant(base, own, r, bool(getattr(obj, "KeepFeatures", True))), None


def _conic_on_sets(base, edges, set1, d1, d2, profile, obj, symmetric):
    ""


    from . import conicfillet
    flip = bool(getattr(obj, "ReverseDirection", False))
    groups = {False: [], True: []}
    for e in edges:
        faces = base.ancestorsOfType(e, Part.Face)
        first_in_set1 = bool(faces) and any(faces[0].isSame(f) for f in set1)
        groups[(not first_in_set1) != flip].append(e)
    out = base
    rho, conic_r = float(getattr(obj, "Rho", 0.5)), float(getattr(obj, "ConicRadius", d1))
    for reverse in (False, True):
        if not groups[reverse]:
            continue
        mine = []
        for e in groups[reverse]:
            mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            match = [x for x in out.Edges if abs(x.Length - e.Length) < 1e-6
                     and x.distToShape(Part.Vertex(mid))[0] < 1e-6]
            if match:
                mine.append(match[0])
        if mine:
            out = conicfillet.conic_fillet(out, mine, d1, d2, profile, rho, conic_r, symmetric, reverse)
    return out


def _opening(base, edge):
    """The angle between the normals of the two faces at an edge (0 = flat, 90 degrees = a box edge)."""
    import math
    faces = base.ancestorsOfType(edge, Part.Face)
    if len(faces) != 2:
        return None
    mid = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
    normals = []
    for f in faces:
        u, v = f.Surface.parameter(mid)
        normals.append(f.normalAt(u, v))
    return math.acos(max(-1.0, min(1.0, normals[0].dot(normals[1]))))


def chord_radius(base, edge, width):
    ""

    import math
    phi = _opening(base, edge)
    if phi is None or phi < 1e-6:
        raise RuntimeError("Chord width needs two faces that meet at an angle")
    return width / (2.0 * math.sin(phi / 2.0))


def chord_fillet(base, edges, width, profile="Circular", obj=None):
    if width <= 0:
        raise RuntimeError("The chord width must be more than 0")
    if profile != "Circular":
        from . import conicfillet
        out = base
        for e in edges:
            own = [x for x in out.Edges if x.isSame(e)] or [e]
            r = chord_radius(base, e, width)
            out = conicfillet.conic_fillet(out, own, r, r, profile, float(getattr(obj, "Rho", 0.5)),
                                           float(getattr(obj, "ConicRadius", r)), r)
        return out
    from . import multiradius
    rows = []
    for e in edges:
        index = next(i for i, x in enumerate(base.Edges, 1) if x.isSame(e))
        r = chord_radius(base, e, width)
        rows.append((index, r, r))
    return multiradius.per_edge(base, "Fillet", rows)


def gap_fillet(base, set1, set2, r):
    ""


    if len(set1) != 1 or len(set2) != 1:
        raise RuntimeError("Faces that do not meet: pick one face in each set")
    a, b = _plane(set1[0]), _plane(set2[0])
    if a is None or b is None:
        raise RuntimeError("Faces that do not meet can only be rounded here when both are flat")
    (p1, n1), (p2, n2) = a, b
    if abs(abs(n1.dot(n2)) - 1.0) < 1e-6:
        raise RuntimeError("The two faces are parallel: use Full Round Fillet")
    # convex corner (the faces turn away from each other): face 2 lies behind face 1's plane
    convex = (set2[0].CenterOfMass - p1).dot(n1) < 0
    s = -1.0 if convex else 1.0
    axis = n1.cross(n2).normalize()

    def meet(o1, o2):
        """A point on the line where plane 1 moved by o1 and plane 2 moved by o2 cross."""
        d1, d2 = p1.dot(n1) + o1, p2.dot(n2) + o2
        k = n1.dot(n2)
        det = 1.0 - k * k
        c1, c2 = (d1 - d2 * k) / det, (d2 - d1 * k) / det
        return n1 * c1 + n2 * c2
    c = meet(s * r, s * r)                     # the axis of the round
    x = meet(0.0, 0.0)                         # the sharp corner the two planes make
    t1, t2 = c - n1 * (s * r), c - n2 * (s * r)
    lo1 = min(v.Point.dot(axis) for v in set1[0].Vertexes)
    hi1 = max(v.Point.dot(axis) for v in set1[0].Vertexes)
    lo2 = min(v.Point.dot(axis) for v in set2[0].Vertexes)
    hi2 = max(v.Point.dot(axis) for v in set2[0].Vertexes)
    lo, hi = max(lo1, lo2), min(hi1, hi2)
    if hi - lo < 1e-6:
        raise RuntimeError("The two faces do not run alongside each other")
    shift = axis * (lo - c.dot(axis))
    quad = Part.Face(Part.makePolygon([q + shift for q in (c, t1, x, t2, c)]))
    region = quad.extrude(axis * (hi - lo))
    rod = Part.makeCylinder(r, hi - lo, c + shift, axis)
    for pt, face in ((t1, set1[0]), (t2, set2[0])):
        if face.distToShape(Part.Vertex(pt + axis * (0.5 * (lo + hi) - pt.dot(axis))))[0] > 1e-6:
            raise RuntimeError("The radius is too large: the round would touch a face beyond the ones picked")
    keep = region.common(rod) if convex else region.cut(rod)
    out = base.cut(region).fuse(keep)
    try:
        clean = out.removeSplitter()
        if clean.isValid():
            out = clean
    except Exception as _fw_err:
        _fw_log("filletkinds.py:216", _fw_err)
    if not out.isValid() or not out.Solids:
        raise RuntimeError("The faces could not be rounded across the gap")
    return out


def hold_line_fillet(base, edges, holds):
    ""


    from . import multiradius
    line = Part.makeCompound([h for h in holds])
    rows = []
    for edge in edges:
        index = next(i for i, x in enumerate(base.Edges, 1) if x.isSame(edge))
        ends = [edge.valueAt(edge.FirstParameter), edge.valueAt(edge.LastParameter)]
        radii = [line.distToShape(Part.Vertex(p))[0] for p in ends]
        if min(radii) < 1e-6:
            raise RuntimeError("The hold line touches the edge: pick a line on a face, away from the edge")
        rows.append((index, radii[0], radii[1]))
    return multiradius.per_edge(base, "Fillet", rows)


def _plane(face):
    if type(face.Surface).__name__ != "Plane":
        return None
    n = face.normalAt(0, 0)
    return face.Surface.Position, App.Vector(n).normalize()


def full_round(base, side1, center, side2):
    """The part with the center face replaced by a round touching all three faces. The side faces
    may lean (a drafted rib): the round is the circle touching the three faces' lines in the rib's
    section, run along the rib."""
    p1, s1 = _plane(side1) or (None, None)
    p2, s2 = _plane(side2) or (None, None)
    pc, nc = _plane(center) or (None, None)
    if s1 is None or s2 is None or nc is None:
        raise RuntimeError("Full round fillet here needs flat side and center faces")
    d = nc.cross(s1)
    if d.Length < 1e-6:
        raise RuntimeError("The center face must run across the side faces")
    d.normalize()
    if abs(s2.dot(d)) > 1e-6:
        raise RuntimeError("Full round fillet here needs the side faces to run the same way along the rib")
    # each face's normal turned into the part (the round's centre is r in from all three)
    def inward(face, n):
        return n if base.isInside(face.CenterOfMass + n * 1e-3, 1e-7, True) else n * -1
    n1, n2, ncc = inward(side1, s1), inward(side2, s2), inward(center, nc)
    u = ncc.cross(d)
    u.normalize()
    w = d.cross(u)          # the section's axes: u across the rib, w into it from the center face

    def two(v):
        return (v.dot(u), v.dot(w))
    rows = []
    for n, pt in ((n1, p1), (n2, p2), (ncc, pc)):
        a, b = two(n)
        rows.append((a, b, -1.0, a * two(pt)[0] + b * two(pt)[1]))
    # n.(c - p) = r  ->  a*cu + b*cw - r = n.p
    import numpy
    m = numpy.array([[a, b, c] for a, b, c, _k in rows])
    k = numpy.array([kk for _a, _b, _c, kk in rows])
    try:
        cu, cw, r = numpy.linalg.solve(m, k)
    except Exception:
        raise RuntimeError("The side faces are the same plane")
    if r <= 1e-6:
        raise RuntimeError("Full round fillet: no round touches the three faces")
    centre_2d = u * cu + w * cw
    ts = [v.Point.dot(d) for v in center.Vertexes]
    tmin, tmax = min(ts), max(ts)
    c0 = centre_2d + d * tmin
    # the touch points on the side faces and the corners at the center face, in the section at tmin
    t1, t2 = c0 - n1 * r, c0 - n2 * r

    def corner(na, pa):           # the side line meets the center line (in the tmin section)
        a1, b1 = two(na)
        a2, b2 = two(ncc)
        mm = numpy.array([[a1, b1], [a2, b2]])
        kk = numpy.array([a1 * two(pa)[0] + b1 * two(pa)[1], a2 * two(pc)[0] + b2 * two(pc)[1]])
        x, y = numpy.linalg.solve(mm, kk)
        return u * x + w * y + d * tmin
    k1, k2 = corner(n1, p1), corner(n2, p2)
    block = Part.Face(Part.makePolygon([t1, k1, k2, t2, t1])).extrude(d * (tmax - tmin))
    rod = Part.makeCylinder(r, tmax - tmin, c0, d)
    removed = block.cut(rod)
    result = base.cut(removed)
    try:
        result = result.removeSplitter()
    except Exception as _fw_err:
        _fw_log("filletkinds.py:307", _fw_err)
    if len(result.Solids) == 1:
        result = result.Solids[0]
    return result, removed


def tangent_faces(shape, face, tol=1e-3):
    """The face and the faces running on from it smoothly (Tangent propagation)."""
    out, todo = [face], [face]
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in shape.ancestorsOfType(e, Part.Face):
                if any(g.isSame(o) for o in out):
                    continue
                try:
                    p = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
                    n1 = f.normalAt(*f.Surface.parameter(p))
                    n2 = g.normalAt(*g.Surface.parameter(p))
                except Exception:
                    continue
                if n1.getAngle(n2) < tol:
                    out.append(g)
                    todo.append(g)
    return out


def _full_round(obj, base):
    sets = [_own_faces(base, sf.elements(obj, name)) for name in ("SideFace1", "CenterFace", "SideFace2")]
    if not all(sets):
        return None, None
    if any(len(s) != 1 for s in sets):
        raise RuntimeError("Full round fillet here takes one face in each set")
    result, removed = full_round(base, sets[0][0], sets[1][0], sets[2][0])
    return result, None



# Face Set PURPLE, Side Face Set 2 PINK, as a 14 px bar at the left of a white box (the active box pale blue);
# the faces in the view take the same colours
SET_COLOURS = {"SideFace1": ("#50a8ff", (0.31, 0.66, 1.0)),
               "CenterFace": ("#7f00fc", (0.5, 0.0, 0.99)),
               "SideFace2": ("#f57ec0", (0.96, 0.49, 0.75))}

if Gui is not None:
    class FullRoundPanel(sf.Panel):
        ""


        def __init__(self, obj):
            super().__init__(obj)
            from . import filletpm
            self.overlay = filletpm.Overlay()
            pages = self.form if isinstance(self.form, list) else [self.form]
            items = pages[0]
            items.setWindowTitle("Items To Fillet")
            self.tangent = QtWidgets.QCheckBox("Tangent propagation", items)
            self.tangent.setObjectName("SWFullRoundTangent")
            self.tangent.setChecked(filletpm.params().GetBool("FullRoundTangent", True))
            self.tangent.toggled.connect(self._tangent_toggled)
            items.layout().addRow(self.tangent)
            self.previews = []
            group = QtWidgets.QButtonGroup(items)
            chosen = filletpm.params().GetString("FilletPreview", filletpm.PREVIEWS[0])
            for text in filletpm.PREVIEWS:
                r = QtWidgets.QRadioButton(text, items)
                r.setObjectName("SWFullRound" + text.replace(" ", ""))
                r.setChecked(text == chosen)
                group.addButton(r)
                items.layout().addRow(r)
                self.previews.append(r)
                r.toggled.connect(lambda on, t=text: on and self._preview(t))
            # the Fillet Type row (back to the other fillets) is put on top by filletchamfer.py
            self._activate(self.active)
            self._paint()
            self._preview(self.preview_mode())

        def preview_mode(self):
            return next((r.text() for r in getattr(self, "previews", []) if r.isChecked()), "Full preview")

        def _tangent_toggled(self, on):
            from . import filletpm
            filletpm.params().SetBool("FullRoundTangent", on)
            self._paint()

        def _preview(self, text=None):
            # PATCH-MERGE (PM thread 11-12): sf.Panel._changed calls _preview() with no mode, which
            # raised on every field change, Delete and Clear Selections; run the page preview first
            if not isinstance(text, str):
                super()._preview(text)
                if text is not None:
                    return          # the page closing: the result shows again (sf.Panel._close)
                text = self.preview_mode()
            from . import filletpm
            filletpm.params().SetString("FilletPreview", text)
            show = text != "No preview"
            base = self.obj.BaseFeature
            try:
                self.obj.ViewObject.Visibility = show
                if base is not None:
                    base.ViewObject.Visibility = not show
            except Exception as _fw_err:
                _fw_log("filletkinds.py:406", _fw_err)

        def _activate(self, name):
            self.active = name
            for other, widget in self.lists.items():
                colour = SET_COLOURS.get(other, ("#50a8ff",))[0]
                back = "#d6ecff" if other == name else "#ffffff"
                widget.setStyleSheet("QListWidget { background: %s; color: #000000; border: 1px solid #b0b0b0;"
                                     " border-left: 14px solid %s; }" % (back, colour))

        def _show(self):
            super()._show()
            if hasattr(self, "overlay"):
                self._paint()

        def _paint(self):
            base = self.obj.BaseFeature
            if base is None or base.Shape.isNull():
                return
            painted = []
            for name, (_, rgb) in SET_COLOURS.items():
                for face in _own_faces(base.Shape, sf.elements(self.obj, name)):
                    faces = tangent_faces(base.Shape, face) if self.tangent.isChecked() else [face]
                    painted += [(f, rgb) for f in faces]
            # over the round only while there is no result yet: then the picks show on the part
            if "Invalid" in self.obj.State or not all(getattr(self.obj, n) for n in SET_COLOURS):
                self.overlay.show_paint(painted)
            else:
                self.overlay.show_paint([])

        def _close(self):
            try:
                self.overlay.remove()
            except Exception as _fw_err:
                _fw_log("filletkinds.py:439", _fw_err)
            super()._close()

        def accept(self):
            ok = super().accept()
            if ok:
                try:
                    self.obj.ViewObject.Visibility = True
                    if self.obj.BaseFeature is not None:
                        self.obj.BaseFeature.ViewObject.Visibility = False
                except Exception as _fw_err:
                    _fw_log("filletkinds.py:450", _fw_err)
            return ok
else:
    FullRoundPanel = None


FACE_FILLET = sf.Spec(
    "SWStyle_FaceFillet", "Face Fillet", "FaceFillet",
    "Rounds where two sets of faces meet, with one radius.",
    "FEATURES_FILLET", "PartDesign_Fillet",
    [Field("FaceSet1", "pick", "Face Set 1", what=("Face",), many=True, box="Items To Fillet"),
     Field("FaceSet2", "pick", "Face Set 2", what=("Face",), many=True, box="Items To Fillet"),
     Field("Method", "enum", "Fillet Method", "Symmetric", values=list(FACE_METHODS), box="Fillet Parameters",
           legacy=lambda o: "Hold Line" if getattr(o, "HoldLine", None) else "Symmetric",
           tip="Symmetric: one radius; Asymmetric: a distance on each face set; Chord Width: the width "
               "between the round's two tangent lines; Hold Line: the round runs out on picked edges"),
     Field("Radius", "length", "Radius", 2.0, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "Symmetric")) == "Symmetric"),
     Field("Distance1", "length", "Distance 1", 2.0, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "")) == "Asymmetric"),
     Field("Distance2", "length", "Distance 2", 4.0, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "")) == "Asymmetric"),
     Field("ReverseDirection", "bool", "Reverse direction", False, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "")) == "Asymmetric"),
     Field("ChordWidth", "length", "Chord width", 3.0, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "")) == "Chord Width"),
     Field("HoldLine", "pick", "Hold line", what=("Edge",), many=True, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "Hold Line")) == "Hold Line",
           tip="Edges on the faces where the fillet must end; the size then follows them (Radius is not used)"),
     Field("Profile", "enum", "Profile", "Circular", values=list(FACE_PROFILES), box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Method", "")) != "Hold Line"),
     Field("Rho", "float", "Rho", 0.5, low=0.01, high=0.99, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Profile", "")) == "Conic Rho" and str(getattr(o, "Method", "")) != "Hold Line"),
     Field("ConicRadius", "length", "Conic radius", 2.0, box="Fillet Parameters",
           shown=lambda o: str(getattr(o, "Profile", "")) == "Conic Radius" and str(getattr(o, "Method", "")) != "Hold Line"),
     Field("KeepFeatures", "bool", "Keep features", True, box="Fillet Options",
           tip="A boss or cut inside the fillet stays (off: the fillet rolls over it and it goes)")],
    _face_fillet)
FACE_FILLET.fields[0].split_to = "FaceSet2"

FULL_ROUND_FILLET = sf.Spec(
    "SWStyle_FullRoundFillet", "Full Round Fillet", "FullRoundFillet",
    "Replaces a face with a half round touching it and the two faces beside it.",
    "FEATURES_FILLET", "PartDesign_Fillet",
    [Field("SideFace1", "pick", "Side Face Set 1", what=("Face",)),
     Field("CenterFace", "pick", "Center Face Set", what=("Face",)),
     Field("SideFace2", "pick", "Side Face Set 2", what=("Face",))],
    _full_round, panel=None)

FULL_ROUND_FILLET.panel = FullRoundPanel

ALL = [FACE_FILLET, FULL_ROUND_FILLET]


def register():
    for spec in ALL:
        sf.register(spec)
