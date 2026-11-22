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

TYPE = "PartDesign::FeaturePython"
MODES = ("Parting Line", "Step Draft")


def is_parting_draft(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, PartingDraftFeature)
    except Exception:
        return False


def pull_of(obj, sub):
    """(point, unit normal) of the Direction of Pull: a flat face or a datum / origin plane."""
    try:
        shape = obj.Shape.getElement(sub) if sub else obj.Shape
        face = shape.Faces[0]
        if face.Surface.__class__.__name__ != "Plane":
            raise RuntimeError("The direction of pull must be a plane or a flat face.")
        n = face.normalAt(0, 0)
        p = face.CenterOfMass
    except RuntimeError:
        raise
    except Exception:
        pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
        n = pl.Rotation.multVec(App.Vector(0, 0, 1))
        p = pl.Base
    n.normalize()
    return p, n


def _same_edge(a, b):
    try:
        return a.Length > 0 and abs(a.Length - b.Length) < 1e-6 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-6
    except Exception:
        return False


def _is_face(a, b):
    """The same face by its place: coplanar, same normal, and the centre of the picked face
    lies on the live one (so a coplanar neighbour across the parting line does not match, and
    a face trimmed by an earlier wall still does)."""
    try:
        if a.normalAt(0, 0).getAngle(b.normalAt(0, 0)) > 1e-6:
            return False
        c = a.CenterOfMass
        if abs((c - b.CenterOfMass).dot(b.normalAt(0, 0))) > 1e-6:
            return False
        return b.isInside(c, 1e-6, True)
    except Exception:
        return False


def _same_face(a, b):
    try:
        if a.Surface.__class__.__name__ != b.Surface.__class__.__name__:
            return False
        return b.distToShape(a)[0] < 1e-6 and abs(a.normalAt(0, 0).getAngle(b.normalAt(0, 0))) < 1e-6 \
            if a.Surface.__class__.__name__ == "Plane" else \
            (abs(a.Area - b.Area) < 1e-6 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-6)
    except Exception:
        return False


def drafted_face(shape, edge, d, other=False):
    """The face next to the parting edge that is drafted: the one on the pull side (other: the
    other one). Faces square to the pull (a top or a bottom) are never drafted."""
    import Part
    faces = shape.ancestorsOfType(edge, Part.Face)
    m = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
    walls = []
    for f in faces:
        try:
            u, v = f.Surface.parameter(m)
            if abs(f.normalAt(u, v).dot(d)) > 0.999:
                continue
        except Exception as _fw_err:
            _fw_log("partingdraft.py:110", _fw_err)
        walls.append(f)
    if not walls:
        return None
    walls.sort(key=lambda f: -(f.CenterOfMass - m).dot(d))       # pull side first
    if other:
        return walls[1] if len(walls) > 1 else None
    return walls[0]


def _height(edge, d):
    hs = [v.Point.dot(d) for v in edge.Vertexes] + [edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * t).dot(d)
                                                     for t in (0.25, 0.5, 0.75)]
    if max(hs) - min(hs) > 1e-6:
        raise RuntimeError("Parting lines must lie square to the direction of pull for now.")
    return hs[0]


def _tangent_grow(shape, faces):
    out = list(faces)
    todo = list(faces)
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in shape.Faces:
                if any(x.isSame(g) for x in out) or not any(e.isSame(x) for x in g.Edges):
                    continue
                try:
                    m = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
                    n1 = f.normalAt(*f.Surface.parameter(m))
                    n2 = g.normalAt(*g.Surface.parameter(m))
                    if n1.getAngle(n2) < 1e-3:
                        out.append(g)
                        todo.append(g)
                except Exception:
                    continue
    return out


def _scratch_body():
    from . import multiradius
    doc = multiradius._scratch_doc()
    body = doc.getObject("DraftBody")
    if body is None:
        base = doc.addObject("Part::Feature", "DraftBase")
        body = doc.addObject("PartDesign::Body", "DraftBody")
        body.BaseFeature = base
        doc.recompute()
        plane = body.newObject("PartDesign::Plane", "DraftPlane")
        plane.MapMode = "Deactivated"
        body.newObject("PartDesign::Draft", "Draft")
    return doc, body


def _draft(shape, faces, point, d, angle):
    """shape with faces drafted by angle about the plane through point square to d, narrowing
    along d: FreeCAD's PartDesign Draft."""
    from . import multiradius
    doc, body = _scratch_body()
    base = doc.getObject("DraftBase")
    base.Shape = shape
    doc.recompute()
    fb = next(o for o in body.Group if o.TypeId == "PartDesign::FeatureBase")
    plane = doc.getObject("DraftPlane")
    plane.Placement = App.Placement(point, App.Rotation(App.Vector(0, 0, 1), d))
    names = []
    for f in faces:
        i = next((i for i, g in enumerate(fb.Shape.Faces, 1) if _same_face(f, g)), None)
        if i is not None:
            names.append("Face%d" % i)
    if not names:
        return shape
    draft = doc.getObject("Draft")
    draft.Base = (fb, names)
    draft.NeutralPlane = (plane, [""])
    draft.PullDirection = None
    draft.Angle = angle
    draft.Reversed = False
    doc.recompute()
    out = draft.Shape.copy()
    ok = draft.isValid() and not out.isNull() and out.isValid()
    status = draft.getStatusString()
    base.Shape = multiradius.Part_empty()
    doc.recompute()
    multiradius._not_modified(doc)
    if not ok:
        raise RuntimeError("The draft could not be made: %s" % status)
    return out


STEPS = ("Tapered steps", "Perpendicular steps")


def _edge_line(edge):
    """(point, unit direction) of a straight parting edge, else None."""
    try:
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        v = b - a
        if v.Length < 1e-9 or edge.Curve.__class__.__name__ not in ("Line", "LineSegment"):
            return None
        return a, v.normalize()
    except Exception:
        return None


def _hinge(n, d, line, angle, outward=False):
    ""


    import math
    if line is None:
        return None
    t = App.Vector(line[1])
    t.normalize()
    if abs(t.dot(d)) < 1e-9:
        return None             # level: the plain turn about the line square to d does it
    lean = t.cross(n).dot(d)
    if lean < 0:
        t, lean = t * -1, -lean
    want = math.sin(math.radians(angle)) * (-1.0 if outward else 1.0)
    have = n.dot(d)
    # n turned by phi about t: n.d cos(phi) + lean sin(phi) = want
    r = math.hypot(have, lean)
    if r < 1e-9 or abs(want) > r:
        raise RuntimeError("The parting line runs too close to the direction of pull for this draft angle.")
    phi = math.asin(want / r) - math.atan2(have, lean)
    return t, math.degrees(phi)


def _turned(solid, face, pivot_point, d, angle, outward=False, steps="Perpendicular steps", seam=(), refine=True,
            line=None):
    """solid with one flat face turned by angle about the line where the plane through
    pivot_point square to d meets the face's plane, so the part narrows towards d (outward:
    widens). Material outside the turned plane is cut off, material inside it is added, each
    bounded by the face's own outline pushed straight through the face (Perpendicular steps) or
    along the turned normal (Tapered steps): where the parting line steps, the steps come out
    that way."""
    import Part
    n = App.Vector(face.normalAt(0, 0))
    n.normalize()
    if abs(n.dot(d)) > 0.999:
        return solid
    axis = n.cross(d)
    axis.normalize()
    centre = face.CenterOfMass
    pivot = centre + d * ((pivot_point - centre).dot(d))
    reach = solid.BoundBox.DiagonalLength * 2 + 10.0
    # +angle about n x d tilts the pull direction towards -n: the part narrows towards d
    turn = App.Rotation(axis, (-angle if outward else angle))
    hinge = _hinge(n, d, line, angle, outward)
    if hinge is not None:
        # a climbing parting edge: the face turns about the edge, which stays on the part
        turn = App.Rotation(hinge[0], hinge[1])
        pivot = App.Vector(line[0])
    n2 = turn.multVec(n)
    big = Part.makePlane(reach * 2, reach * 2)
    big.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), n2))
    big.translate(pivot - big.CenterOfMass)
    outside = big.extrude(n2 * reach * 2)          # the half space outside the turned plane
    column_in = face.extrude(n * -reach)
    column_out = face.extrude(n * reach)
    if steps == "Tapered steps":
        # the outline is pushed square to the face, except along the parting edges, where the
        # step walls lean with the turned normal: widen the columns by the leaning push and
        # trim them back to the leaning wall through each parting edge on this face
        column_in = column_in.fuse(face.extrude(n2 * -reach))
        column_out = column_out.fuse(face.extrude(n2 * reach))
        for e in face.Edges:
            if not any(_same_edge(e, g) for g in seam):
                continue
            try:
                t = e.tangentAt(e.FirstParameter)
                if abs(t.dot(d)) > 0.999:
                    continue            # a step along the pull: its wall is the same either way
                mid = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
                m0 = t.cross(n)         # in the face, square to the edge, towards the face
                m0.normalize()
                if not face.isInside(mid + m0 * 0.01, 1e-6, True):
                    m0 = m0 * -1
                m = t.cross(n2)         # square to the leaning wall, towards the face
                m.normalize()
                if m.dot(m0) < 0:
                    m = m * -1
                patch = e.copy()
                patch.translate(n2 * -reach)
                patch = patch.extrude(n2 * reach * 2)       # the leaning wall through this edge
                beyond = patch.extrude(m * -reach)          # the part of the column past that wall
                column_in = column_in.cut(beyond)
                column_out = column_out.cut(beyond)
            except Exception as _fw_err:
                _fw_log("partingdraft.py:270", _fw_err)
    result = solid
    cut = column_in.common(outside)
    if cut.Volume > 1e-6:
        result = result.cut(cut)
    add = column_out.cut(outside)
    if add.Volume > 1e-6:
        result = result.fuse(add)
    if refine:
        try:
            result = result.removeSplitter()
        except Exception as _fw_err:
            _fw_log("partingdraft.py:282", _fw_err)
    if result.isNull() or not result.isValid() or not result.Solids:
        raise RuntimeError("The draft could not be made.")
    return result


def parting_draft(solid, edges, pull_point, d, angle, mode, others=(), tangent=False,
                  steps="Tapered steps", angle2=None, reduced=False):
    """solid drafted along its parting edges (edges of solid); others: the edges whose other
    face is drafted; angle2: Direction 2, the faces on the other side of the parting lines
    drafted the other way; reduced: Allow reduced angle (a smaller angle when it cannot be
    made at the full one)."""
    import math
    jobs = []           # [face, pivot point, direction, angle]
    for e in edges:
        other = any(e.isSame(o) for o in others)
        for which, (dd, a) in enumerate(((d, angle), (d * -1, angle2))):
            if a is None:
                continue
            f = drafted_face(solid, e, d, other != (which == 1))
            if f is None:
                continue
            line = None
            if mode == "Step Draft":
                point = pull_point
            else:
                line = _edge_line(e)
                point = line[0] if line else e.CenterOfMass
                if line is None:
                    hs = [e.valueAt(e.FirstParameter + (e.LastParameter - e.FirstParameter) * k / 4.0).dot(dd)
                          for k in range(5)]
                    if max(hs) - min(hs) > 1e-6:
                        raise RuntimeError("A curved parting line has to be level (square to the direction "
                                           "of pull); a straight one may climb.")
            job = next((j for j in jobs if j[0].isSame(f) and j[2] == dd), None)
            if job is None:
                jobs.append([f, point, dd, a, line])
            elif mode != "Step Draft" and point.dot(dd) > job[1].dot(dd):
                job[1] = point          # a stepped parting line: the face turns about its edge nearest the pull
    if not jobs:
        if edges:
            raise RuntimeError("The faces along the parting lines are square to the Direction of Pull. "
                               "Pick a direction across them (a side face or a plane through the part).")
        raise RuntimeError("Select parting lines.")
    out = solid
    for f, point, dd, a, line in jobs:
        faces = _tangent_grow(solid, [f]) if tangent else [f]
        for face in faces:
            live = next((g for g in out.Faces if _is_face(face, g)), None)
            if live is None:
                continue
            tries = [a] + ([a / 2.0, a / 4.0, a / 8.0] if reduced else [])
            last = None
            for value in tries:
                try:
                    out = _turned(out, live, point, dd, value, outward=False,
                                  steps=steps if mode == "Step Draft" else "Perpendicular steps",
                                  seam=edges, refine=False, line=line)
                    # no refine between faces: it would join the wall halves on either side of
                    # a parting line still to be drafted (the next face would be the whole wall)
                    last = None
                    break
                except Exception as error:
                    last = error
            if last is not None:
                # FreeCAD's own Draft as the fallback
                out = _draft(out, [live], point, dd, a)
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("partingdraft.py:345", _fw_err)
    solids = [s for s in out.Solids if s.Volume > 1e-6 * out.Volume]   # E13-24: tapered steps can leave
    if len(solids) == 1:                                       # zero-volume slivers behind
        out = solids[0]
    elif len(solids) > 1 and len(solids) < len(out.Solids):
        out = Part.makeCompound(solids)
    return out


class PartingDraftFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Draft", "Parting lines")
        if "PullPlane" not in props:
            obj.addProperty("App::PropertyLinkSub", "PullPlane", "Draft", "Direction of pull")
        if "Angle" not in props:
            obj.addProperty("App::PropertyAngle", "Angle", "Draft", "Draft angle")
            obj.Angle = 1.0
        if "Reversed" not in props:
            obj.addProperty("App::PropertyBool", "Reversed", "Draft", "Reverse the direction of pull")
        if "Mode" not in props:
            obj.addProperty("App::PropertyEnumeration", "Mode", "Draft", "Type of draft")
            obj.Mode = list(MODES)
        if "OtherFaces" not in props:
            obj.addProperty("App::PropertyStringList", "OtherFaces", "Draft",
                            "Parting edges whose other face is drafted")
        if "AlongTangent" not in props:
            obj.addProperty("App::PropertyBool", "AlongTangent", "Draft", "Face propagation Along Tangent")
        if "Steps" not in props:
            obj.addProperty("App::PropertyEnumeration", "Steps", "Draft", "Step Draft: Tapered or Perpendicular steps")
            obj.Steps = list(STEPS)
        if "Direction2" not in props:
            obj.addProperty("App::PropertyBool", "Direction2", "Draft", "Draft the other side of the parting lines too")
        if "Angle2" not in props:
            obj.addProperty("App::PropertyAngle", "Angle2", "Draft", "Direction 2 draft angle")
            obj.Angle2 = 1.0
        if "Symmetric" not in props:
            obj.addProperty("App::PropertyBool", "Symmetric", "Draft", "Symmetrical Draft: Direction 2 uses the same angle")
        if "ReducedAngle" not in props:
            obj.addProperty("App::PropertyBool", "ReducedAngle", "Draft", "Allow reduced angle where the full one cannot be made")

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Draft needs a part")
        if not obj.PullPlane:
            raise RuntimeError("Select a direction of pull.")
        from . import multiradius
        pobj, psubs = obj.PullPlane
        point, d = pull_of(pobj, psubs[0] if psubs else "")
        if obj.Reversed:
            d = d * -1
        _follow_names(obj)
        source = obj.Base[0].Shape if obj.Base else base
        edges, others = [], []
        for sub in (obj.Base[1] if obj.Base else []):
            name = sub.split(".")[-1].lstrip("?")
            try:
                g = source.getElement(name)
            except Exception:
                continue
            b = next((b for b in base.Edges if multiradius._same_edge(b, g)), None)
            if b is None:
                continue
            edges.append(b)
            if sub in obj.OtherFaces or name in obj.OtherFaces:
                others.append(b)
        angle2 = None
        if obj.Direction2:
            angle2 = obj.Angle.Value if obj.Symmetric else obj.Angle2.Value
        obj.Shape = parting_draft(base, edges, point, d, obj.Angle.Value, obj.Mode, others, obj.AlongTangent,
                                  str(obj.Steps), angle2, obj.ReducedAngle)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self
        try:        # an older file: link the names while they still name the saved part
            _follow_names(obj)
        except Exception as _fw_err:
            _fw_log("partingdraft.py:restore", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class PartingDraftView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family("FEATURES_DRAFT")
            if not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("partingdraft.py:447", _fw_err)
        return ""

    def claimChildren(self):
        return []

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        import FreeCADGui as Gui
        from . import filletpm
        if Gui.Control.activeDialog():
            return False
        return bool(filletpm.open_page(vobj.Object))

    def unsetEdit(self, vobj, mode=0):
        return True

    def doubleClicked(self, vobj):
        import FreeCADGui as Gui
        from . import filletpm
        if not Gui.Control.activeDialog():
            filletpm.open_page(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def setup_new(obj):
    PartingDraftFeature(obj)
    if App.GuiUp:
        PartingDraftView(obj.ViewObject)
    return obj


def _follow_names(obj):
    """OtherFaces names parting edges as text: they follow an edit before the draft (elementrefs)."""
    from . import elementrefs
    if not obj.Base:
        return
    source = obj.Base[0]

    def apply(moved):
        names = [moved.get((source.Name, n.split(".")[-1].lstrip("?")), n) for n in obj.OtherFaces]
        if names != list(obj.OtherFaces):
            obj.OtherFaces = names
    elementrefs.follow(obj, lambda: [(source, n.split(".")[-1].lstrip("?")) for n in obj.OtherFaces], apply)


def new(body, name="Draft"):
    label = None
    try:
        from . import naming
        label = naming.next_label(body.Document, "Draft")     # counted before it exists
    except Exception as _fw_err:
        _fw_log("partingdraft.py:492", _fw_err)
    obj = body.newObject(TYPE, name)
    setup_new(obj)
    if label:
        obj.Label = label
    return obj
