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

TYPE = "PartDesign::FeaturePython"
ICON = "FEATURES_SHELL"
TOL = 1e-3


def is_multi_shell(obj):
    try:
        return obj.TypeId == TYPE and isinstance(obj.Proxy, MultiShellFeature)
    except Exception:
        return False


def _same(a, b):
    if a.isSame(b):
        return True
    try:
        return abs(a.Area - b.Area) < 1e-7 and (a.CenterOfMass - b.CenterOfMass).Length < 1e-7
    except Exception:
        return False


def _slab(face, t, solid, outward=False):
    """The solid between a face of solid and that face moved t inward, inside solid (outward:
    moved t outward, outside solid)."""
    slab = face.makeOffsetShape(t if outward else -t, 1e-6, fill=True)   # a solid's face normal points out
    return slab.cut(solid) if outward else slab.common(solid)


def native_ok(solid, removed, t, outward=False, intersection=None):
    """FreeCAD's makeThickness, or None when it fails or hands the solid back unchanged (it does that
    when an open face is tangent to a fillet next to it). An invalid result is tried again with
    Intersection on (a Dome on the part: the plain shell was not a valid solid); intersection=False or
    True asks for that one only."""
    for inter in ((False, True) if intersection is None else (bool(intersection),)):
        try:
            out = solid.makeThickness(removed, t if outward else -t, TOL, inter)
        except Exception:
            continue
        if out.isNull() or not out.Solids or abs(out.Volume - solid.Volume) <= 1e-7 * max(1.0, solid.Volume):
            continue
        if out.isValid():
            return out
    return None


def _offset_hollow(solid, removed, t, inside_of=None):
    """Inward shell another way: the solid less its inside (the solid offset inward by t), opened
    through each removed flat face. inside_of: the shape whose inward offset is the inside (features-481:
    the solid with its thin outside rounds taken off, see _sharp_hollow)."""
    import Part
    inner = (inside_of or solid).Solids[0].makeOffsetShape(-t, TOL, False, False, 0, 0, False)
    if not inner.Solids:
        inner = Part.Solid(Part.Shell(inner.Faces))
    tools = [inner]
    for rf in removed:
        if rf.Surface.TypeId != "Part::GeomPlane":
            raise RuntimeError("The shell could not be made: try a smaller thickness.")
        n = rf.normalAt(*rf.Surface.parameter(rf.CenterOfMass))
        lids = [f for f in inner.Faces if f.Surface.TypeId == "Part::GeomPlane" and f.normalAt(0, 0).dot(n) > 1 - 1e-6
                and abs((rf.CenterOfMass - f.CenterOfMass).dot(n) - t) < 1e-4 * max(1.0, t)]
        if not lids:
            raise RuntimeError("The shell could not be made: try a smaller thickness.")
        tools.append(max(lids, key=lambda f: f.Area).extrude(n * (t * 1.5)))
    out = solid.cut(inner.fuse(tools[1:]) if len(tools) > 1 else inner)
    try:
        out = out.removeSplitter()
    except Exception as _fw_err:
        _fw_log("multishell.py:89", _fw_err)
    if len(out.Solids) != 1 or not out.isValid():
        raise RuntimeError("The shell could not be made: try a smaller thickness.")
    return out.Solids[0]


def _kinks(surface, face):
    """(u values, v values) inside the face where its BSpline surface is only C0 (a knot as often as
    the degree). Some fillet faces FreeCAD builds are like that though they look smooth, and nothing
    can be offset across such a line."""
    if surface.TypeId != "Part::GeomBSplineSurface":
        return [], []
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for knots, mults, degree, low, high in ((surface.getUKnots(), surface.getUMultiplicities(), surface.UDegree, u0, u1),
                                            (surface.getVKnots(), surface.getVMultiplicities(), surface.VDegree, v0, v1)):
        eps = 1e-9 * max(1.0, abs(high - low))
        out.append([k for k, m in zip(knots[1:-1], mults[1:-1]) if m >= degree and low + eps < k < high - eps])
    return out[0], out[1]


def _smooth_pieces(face):
    """face as it is, or, when its surface is only C0 along some lines, one face per smooth part of
    the surface, so that each can be offset. Only for a face that is its whole surface patch (fillet
    faces are): the parts are then the patch's own rectangles."""
    surface = face.Surface
    try:
        us, vs = _kinks(surface, face)
    except Exception:
        return [face]
    if not us and not vs:
        return [face]
    u0, u1, v0, v1 = face.ParameterRange
    b = surface.bounds()
    span = max(abs(u1 - u0), abs(v1 - v0), 1.0)
    if max(abs(u0 - b[0]), abs(u1 - b[1]), abs(v0 - b[2]), abs(v1 - b[3])) > 1e-6 * span or len(face.Wires) != 1:
        return [face]
    out = []
    ucuts, vcuts = [u0] + list(us) + [u1], [v0] + list(vs) + [v1]
    for a in range(len(ucuts) - 1):
        for c in range(len(vcuts) - 1):
            part = surface.copy()
            part.segment(ucuts[a], ucuts[a + 1], vcuts[c], vcuts[c + 1])
            piece = part.toShape()
            if face.Orientation == "Reversed":
                piece.reverse()
            out.append(piece)
    if abs(sum(p.Area for p in out) - face.Area) > 2e-3 * max(1.0, face.Area) or not all(p.isValid() for p in out):
        return [face]
    return out


def _built_slab(face, t):
    """_slab's solid built by hand, for a face FreeCAD does not offset: the face, the same face on its
    surface moved t inward, and a ruled wall between each edge and its moved twin."""
    import Part
    sign = 1.0 if face.Orientation == "Reversed" else -1.0      # inward is against the face's normal
    moved = Part.OffsetSurface(face.Surface, t * sign)
    walls, wires = [], []
    for wire in face.Wires:
        edges = []
        for edge in wire.OrderedEdges:
            curve, first, last = face.curveOnSurface(edge)[:3]
            twin = curve.toShape(moved, first, last)
            edges.append(twin)
            if edge.Length > 1e-7 and twin.Length > 1e-7:
                walls.append(Part.makeRuledSurface(edge, twin))
        wires.append(Part.Wire(Part.sortEdges(edges)[0]))
    outer = max(wires, key=lambda w: w.BoundBox.DiagonalLength)
    inner_face = Part.Face(moved, [outer] + [w for w in wires if w is not outer])
    from . import sewtol
    shell = sewtol.sewn([face.copy(), inner_face] + walls, 1e-4)
    shell = shell if shell.ShapeType == "Shell" else shell.Shells[0]
    solid = Part.Solid(shell)
    if solid.Volume < 0:
        solid.reverse()
    if not solid.isValid() or solid.Volume <= 0:
        raise RuntimeError("no slab")
    return solid


def _walls(face, t):
    """The stuff within t behind a face (not yet kept inside the solid), as one or more solids."""
    out = []
    for piece in _smooth_pieces(face):
        try:
            slab = piece.makeOffsetShape(-t, 1e-6, fill=True)
            if slab.Solids and slab.Volume > 0 and slab.isValid():
                out.append(slab)
                continue
        except Exception:
            pass
        out.append(_built_slab(piece, t))
    return out


def _inside_corners(solid, kept, t):
    """Round fills for the inside corners between kept faces: there the two walls leave a gap that the
    stuff within t of the edge closes (the arc join of FreeCAD's own shell)."""
    import Part
    out, seen = [], []
    for i, face in enumerate(kept):
        for edge in face.Edges:
            if any(edge.isSame(e) for e in seen):
                continue
            other = next((g for g in kept[i + 1:] if any(edge.isSame(x) for x in g.Edges)), None)
            if other is None:
                continue
            seen.append(edge)
            try:
                a, b = edge.ParameterRange
                mid = edge.valueAt(0.5 * (a + b))
                n1 = face.normalAt(*face.Surface.parameter(mid))
                n2 = other.normalAt(*other.Surface.parameter(mid))
                if n1.dot(n2) > 0.9999:
                    continue                        # tangent: the walls meet
                step = (n1 - n2) * min(1e-3, t * 0.05)
                if not (solid.isInside(mid + step, 1e-7, False) and solid.isInside(mid - step, 1e-7, False)):
                    continue                        # an outside corner: the walls overlap there
                start = edge.valueAt(a)
                ring = Part.Wire(Part.Circle(start, edge.tangentAt(a), t).toShape())
                pipe = Part.Wire([edge]).makePipeShell([ring], True, True)
                if pipe.Solids and pipe.isValid():
                    out.append(pipe)
            except Exception:
                continue
    return out


def _wall_hollow(solid, removed, t):
    """Inward shell a third way, for bodies neither of FreeCAD's offsets can do (drafted walls with
    fillets, the everyday plastic part): the wall is built face by face. Every kept face gives the
    stuff within t behind it; together, kept inside the solid, they are the shell. Open faces give
    nothing, so they are open."""
    solid = solid.Solids[0]
    kept = [f for f in solid.Faces if not any(_same(f, r) for r in removed)]
    if not kept:
        raise RuntimeError("The shell could not be made: try a smaller thickness.")
    walls = [w for f in kept for w in _walls(f, t)] + _inside_corners(solid, kept, t)
    stuff = walls[0].fuse(walls[1:]) if len(walls) > 1 else walls[0]
    out = solid.common(stuff)
    try:
        out = out.removeSplitter()
    except Exception:
        pass
    if len(out.Solids) != 1 or not out.isValid() or not (0 < out.Volume < solid.Volume * (1 - 1e-9)):
        raise RuntimeError("The shell could not be made: try a smaller thickness.")
    return out.Solids[0]


def closed_hollow(solid, t, outward=False):
    ""

    import Part
    piece = solid.Solids[0] if solid.Solids else solid
    if outward:
        outer = piece.makeOffsetShape(t, TOL, False, False, 0, 0, False)
        if not outer.Solids:
            outer = Part.Solid(Part.Shell(outer.Faces))
        out = outer.cut(piece)
    else:
        inner = piece.makeOffsetShape(-t, TOL, False, False, 0, 0, False)
        if not inner.Solids:
            inner = Part.Solid(Part.Shell(inner.Faces))
        if inner.isNull() or inner.Volume <= 0 or inner.Volume >= piece.Volume:
            raise RuntimeError("The shell could not be made: try a smaller thickness.")
        out = piece.cut(inner)
    if len(out.Solids) != 1 or not out.isValid() or abs(out.Volume - piece.Volume) < 1e-9:
        raise RuntimeError("The shell could not be made: try a smaller thickness.")
    return out.Solids[0]


def _round_radius(face):
    """The radius of a round face that bulges out of the solid (an outside fillet, a boss's side), or None: an
    inward wall at least that thick folds the face's offset onto itself."""
    surface = face.Surface
    kind = surface.TypeId
    if kind not in ("Part::GeomCylinder", "Part::GeomSphere", "Part::GeomToroid"):
        return None
    u0, u1, v0, v1 = face.ParameterRange
    u, v = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
    p = face.valueAt(u, v)
    n = face.normalAt(u, v)                 # out of the solid
    if kind == "Part::GeomCylinder":
        axis = surface.Axis
        c = surface.Center + axis * (p - surface.Center).dot(axis)
        r = surface.Radius
    elif kind == "Part::GeomSphere":
        c, r = surface.Center, surface.Radius
    else:
        axis = surface.Axis
        rel = p - surface.Center
        flat = rel - axis * rel.dot(axis)
        if flat.Length < 1e-12:
            return None
        c = surface.Center + flat.normalize() * surface.MajorRadius
        r = surface.MinorRadius
    out = p - c
    return r if out.Length > 1e-12 and out.dot(n) > 0 else None


def _sharp_hollow(solid, removed, t):
    ""



    rounds = []
    for f in solid.Solids[0].Faces:
        if any(_same(f, r) for r in removed):
            continue
        r = _round_radius(f)
        if r is not None and t >= r - 1e-9:
            rounds.append(f)
    if not rounds:
        return None
    try:
        sharp = solid.Solids[0].defeaturing(rounds)
        if sharp.isNull() or not sharp.isValid():
            # one round at a time: a round that cannot come off (a boss's whole side) is left, and refused below
            sharp = solid.Solids[0]
            for f in rounds:
                g = next((g for g in sharp.Faces if _same(g, f)), None)
                if g is None:
                    continue
                try:
                    trial = sharp.defeaturing([g])
                    if not trial.isNull() and trial.Solids and trial.isValid():
                        sharp = trial
                except Exception:
                    continue
        if sharp.isNull() or not sharp.Solids or not sharp.isValid() or any(_round_radius(f) is not None and t >= _round_radius(f) - 1e-9
                                                                            for f in sharp.Faces):
            return None
        return _offset_hollow(solid, removed, t, inside_of=sharp)
    except Exception as _fw_err:
        _fw_log("multishell.py:sharp_hollow", _fw_err)
        return None


def too_thick(solid, removed, t):
    ""


    try:
        for f in solid.Faces:
            if any(_same(f, r) for r in removed):
                continue
            r = _round_radius(f)
            if r is not None and t >= r - 1e-9:
                return r
    except Exception as _fw_err:
        _fw_log("multishell.py:too_thick", _fw_err)
    return None


def hollow(solid, removed, t, outward=False):
    if not removed:
        return closed_hollow(solid, t, outward)
    out = native_ok(solid, removed, t, outward)
    if out is not None:
        return out
    if outward:
        raise RuntimeError("The shell could not be made: try a smaller thickness.")
    radius = too_thick(solid, removed, t)
    if radius is not None:
        out = _sharp_hollow(solid, removed, t)
        if out is not None:
            return out
        raise RuntimeError("The shell could not be made: the thickness is more than the %.2fmm radius of a round "
                           "face. Try a smaller thickness." % radius)
    try:
        return _offset_hollow(solid, removed, t)
    except Exception:
        return _wall_hollow(solid, removed, t)


def multi_shell(solid, removed, d1, multi, outward=False):
    ""

    import Part
    thick = [t for f, t in multi]
    if min([d1] + thick) <= 0:
        raise RuntimeError("Thicknesses must be more than zero.")
    tmin = min([d1] + thick)
    out = hollow(solid, removed, tmin, outward)
    adds = []
    for f in solid.Faces:
        if any(_same(f, r) for r in removed):
            continue
        t = next((t for g, t in multi if _same(g, f)), d1)
        if t > tmin + 1e-9:
            adds.append(_slab(f, t, solid, outward))
    if adds:
        out = out.fuse(adds) if len(adds) > 1 else out.fuse(adds[0])
        try:
            out = out.removeSplitter()
        except Exception as _fw_err:
            _fw_log("multishell.py:127", _fw_err)
        if len(out.Solids) == 1:
            out = out.Solids[0]
    if out.isNull() or not out.isValid():
        raise RuntimeError("The shell could not be made with these thicknesses.")
    return out


def _follow_names(obj, source):
    """MultiFaces names faces as text: they follow an edit before the shell (elementrefs)."""
    from . import elementrefs

    def apply(moved):
        names = [moved.get((source.Name, n.split(".")[-1].lstrip("?")), n) for n in obj.MultiFaces]
        if names != list(obj.MultiFaces):
            obj.MultiFaces = names
    elementrefs.follow(obj, lambda: [(source, n.split(".")[-1].lstrip("?")) for n in obj.MultiFaces], apply)


class MultiShellFeature:
    def __init__(self, obj):
        self.setup(obj)
        obj.Proxy = self

    def setup(self, obj):
        props = obj.PropertiesList
        if "Base" not in props:
            obj.addProperty("App::PropertyLinkSub", "Base", "Shell", "Faces to Remove")
        if "Value" not in props:
            obj.addProperty("App::PropertyLength", "Value", "Shell", "Wall thickness")
            obj.Value = 1.0
        if "Reversed" not in props:

            obj.addProperty("App::PropertyBool", "Reversed", "Shell", "Walls go inward")
            obj.Reversed = True
        if "MultiFaces" not in props:
            obj.addProperty("App::PropertyStringList", "MultiFaces", "Multi-thickness Settings",
                            "Faces with a thickness of their own (faces of Base)")
        if "MultiValues" not in props:
            obj.addProperty("App::PropertyFloatList", "MultiValues", "Multi-thickness Settings",
                            "Their thicknesses, in mm, in the same order")

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else None
        if base is None or base.isNull():
            raise RuntimeError("Shell needs a part")
        source = obj.Base[0] if obj.Base else obj.BaseFeature
        subs = list(obj.Base[1]) if obj.Base else []
        _follow_names(obj, source)
        shape = source.Shape

        def faces_of(names):
            out = []
            for sub in names:
                try:
                    g = shape.getElement(sub.split(".")[-1].lstrip("?"))
                except Exception:
                    continue
                f = next((f for f in base.Faces if _same(f, g)), None)
                if f is not None:
                    out.append(f)
            return out

        removed = faces_of(subs)
        multi = []
        for sub, t in zip(obj.MultiFaces, obj.MultiValues):
            found = faces_of([sub])
            if found:
                multi.append((found[0], float(t)))
        obj.Shape = multi_shell(base, removed, obj.Value.Value, multi, outward=not obj.Reversed)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        obj.Proxy = self
        try:        # an older file: link the names while they still name the saved part
            _follow_names(obj, obj.Base[0] if obj.Base else obj.BaseFeature)
        except Exception as _fw_err:
            _fw_log("multishell.py:restore", _fw_err)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class MultiShellView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        try:
            from . import icons
            icon = icons.family(ICON)
            if not icon.isNull():
                return icon
        except Exception as _fw_err:
            _fw_log("multishell.py:211", _fw_err)
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


def new(body, name="Shell"):
    """A multi-thickness shell after the body's tip."""
    label = None
    try:
        from . import naming

        # label "Shell001" read as Shell1 and made it Shell2)
        label = naming.next_label(body.Document, "Shell")
    except Exception as _fw_err:
        _fw_log("multishell.py:252", _fw_err)
    obj = body.newObject(TYPE, name)
    MultiShellFeature(obj)
    if App.GuiUp:
        MultiShellView(obj.ViewObject)
    if label:
        obj.Label = label
    return obj
