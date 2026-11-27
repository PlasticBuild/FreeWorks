


#
# Run inside FreeCAD:  SWA_ARGS="TREE_JSON|REFERENCE_SHAPE|OUT_FCSTD|REPORT_JSON" freecadcmd rebuild_api.py

import json
import math
import os
import sys

import FreeCAD as App
import Part
import Sketcher

try:
    from . import rebuild as rb
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.environ.get("SWA_DIR", "."))
    import rebuild as rb  # noqa: E402  (shared helpers: variants, mismatch, dress-ups)

V = App.Vector



SW_RELATIONS = {
    4: "horizontal", 5: "vertical", 6: "tangent", 7: "parallel", 8: "perpendicular",
    9: "coincident", 10: "concentric", 14: "same_length", 17: "fix", 27: "colinear",
    28: "coradial", 42: "merge_points",
}


def sketch_placement(to_model):
    r = to_model["rotation"]
    u, v, n = V(*r[0:3]), V(*r[3:6]), V(*r[6:9])
    return App.Placement(V(*to_model["origin"]), App.Rotation(u, v, n, "ZXY"))


class ApiRebuilder(rb.Rebuilder):
    def __init__(self, tree, ref):
        self.tree = tree
        self.ref = ref
        self.ref_vol = abs(ref.Volume)
        self.scale = ref.BoundBox.DiagonalLength
        self.made = {}
        self.log = []
        self.doc = App.newDocument("SWImport")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.body.Label = os.path.splitext(tree.get("source", "Part"))[0]
        self.last_sketch = None

        self.contour_sketches = set(p.split("<")[0] for f in tree["features"] for p in f.get("parents", []) if "<" in p)
        self.regions = {}  # sketch name -> atomic region faces (sketch coordinates)

    # -------------------------------------------------------------- sketches
    def build_sketch(self, f):
        s = f["sketch"]
        sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
        sk.Label = f["name"]
        sk.MapMode = "Deactivated"
        if "to_model" in s:
            sk.Placement = sketch_placement(s["to_model"])
        index = {}
        for seg in s["segments"]:
            g = self.segment(seg)
            if g is None:
                continue
            index[seg["index"]] = sk.addGeometry(g, bool(seg.get("construction")))
        self.auto_relations(sk)
        self.api_relations(sk, s, index)
        sk.Visibility = False
        self.made[f["name"]] = sk
        self.last_sketch = sk
        n = len(sk.Constraints)
        self.note(f["name"], "rebuilt", kind="sketch", geometry=len(index), constraints=n)

    @staticmethod
    def segment(seg):
        k = seg["kind"]
        p = lambda a: V(a[0], a[1], 0)  # noqa: E731  sketch coordinates (z = 0)
        try:
            if k == "line":
                return Part.LineSegment(p(seg["start"]), p(seg["end"]))
            if k == "arc":
                c = p(seg["center"])
                if seg.get("full_circle"):
                    return Part.Circle(c, V(0, 0, 1), seg["radius"])
                a, b = p(seg["start"]), p(seg["end"])
                if seg.get("direction", 1) < 0:
                    a, b = b, a
                a0 = math.atan2(a.y - c.y, a.x - c.x)
                a1 = math.atan2(b.y - c.y, b.x - c.x)
                while a1 <= a0:
                    a1 += 2 * math.pi
                return Part.ArcOfCircle(Part.Circle(c, V(0, 0, 1), seg["radius"]), a0, a1)
            if k == "ellipse":
                c, M, m = p(seg["center"]), p(seg["major"]), p(seg["minor"])
                e = Part.Ellipse(M, m, c)
                a = e.parameter(p(seg["start"]))
                b = e.parameter(p(seg["end"]))
                if abs(a - b) < 1e-9:
                    return e
                while b <= a:
                    b += 2 * math.pi
                return Part.ArcOfEllipse(e, a, b)
            if k == "spline":
                pts = [p(q) for q in seg["through_points"]]
                if len(pts) < 2:
                    return None
                bs = Part.BSplineCurve()
                bs.interpolate(pts)
                return bs
        except Exception:
            return None
        return None

    def api_relations(self, sk, s, index):
        ""
        cons = []
        for r in s.get("relations", []):
            ents = [index.get(e) for e in r.get("entities", []) if isinstance(e, int)]
            ents = [e for e in ents if e is not None]
            t = SW_RELATIONS.get(r.get("sw_type"), "other")
            try:
                if t in ("horizontal", "vertical") and len(ents) == 1:
                    continue  # auto_relations already added these from the geometry
                if t == "tangent" and len(ents) == 2:
                    cons.append(Sketcher.Constraint("Tangent", ents[0], ents[1]))
                elif t == "parallel" and len(ents) == 2:
                    cons.append(Sketcher.Constraint("Parallel", ents[0], ents[1]))
                elif t == "perpendicular" and len(ents) == 2:
                    cons.append(Sketcher.Constraint("Perpendicular", ents[0], ents[1]))
                elif t == "colinear" and len(ents) == 2:
                    cons.append(Sketcher.Constraint("Parallel", ents[0], ents[1]))
                elif t in ("same_length", "equal_radius") and len(ents) == 2:
                    cons.append(Sketcher.Constraint("Equal", ents[0], ents[1]))
                elif t in ("concentric", "coradial") and len(ents) == 2:
                    cons.append(Sketcher.Constraint("Coincident", ents[0], 3, ents[1], 3))
                elif t == "fix":
                    for e in ents:
                        cons.append(Sketcher.Constraint("Block", e))
            except Exception:
                pass
        for c in cons:
            before = self.geometry_points(sk)
            try:
                k = sk.addConstraint(c)
            except Exception:
                continue
            try:
                ok = sk.solve() == 0 and self.same_points(before, self.geometry_points(sk))
            except Exception:
                ok = False
            if not ok:                      # a relation read wrongly would move the sketch
                sk.delConstraint(k)
                sk.Geometry = before[1]
                sk.solve()
        # Drop any constraint that leaves the sketch conflicting
        while sk.solve() not in (0,) and sk.ConstraintCount:
            sk.delConstraint(sk.ConstraintCount - 1)

    # ------------------------------------------------------ sketch regions

    # trimming it, and a feature may use only some contours ("Sketch1<3>"). The file does not
    # say which ones, so the regions are found here and chosen against the exact solid.
    @staticmethod
    def profile_edges(sk):
        return [g.toShape() for i, g in enumerate(sk.Geometry) if not sk.getConstruction(i)]

    def face_ok(self, sk):
        """True if FreeCAD can use the sketch as it is: closed wires that do not cross."""
        wires = [Part.Wire(es) for es in Part.sortEdges(self.profile_edges(sk))]
        if not wires or not all(w.isClosed() for w in wires):
            return False
        for i in range(len(wires)):
            for j in range(i + 1, len(wires)):
                if wires[i].distToShape(wires[j])[0] < 1e-7:
                    return False
        return True

    def sketch_regions(self, sk):
        if sk.Name in self.regions:
            return self.regions[sk.Name]
        edges = self.profile_edges(sk)
        faces = []
        if edges:
            bb = Part.Compound(edges).BoundBox
            m = 0.1 * bb.DiagonalLength + 1.0
            x0, y0, x1, y1 = bb.XMin - m, bb.YMin - m, bb.XMax + m, bb.YMax + m
            frame = Part.makePolygon([V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0), V(x0, y0, 0)])
            try:
                split, _ = Part.Face(frame).generalFuse(edges)
                faces = [fc for fc in split.Faces if fc.distToShape(frame)[0] > 1e-7]
            except Exception:
                faces = []
        self.regions[sk.Name] = faces
        return faces

    def needs_regions(self, sk):
        return sk.Label in self.contour_sketches or not self.face_ok(sk)

    def interval(self, cut, rev, mode, f):
        """Where the extrusion lies along the sketch normal, as FreeCAD builds it."""
        big = 2 * self.scale
        if isinstance(mode, float):
            a, b = 0.0, mode
        elif mode == "mid_plane":
            a, b = -f["depth"] / 2, f["depth"] / 2
        elif mode == "two":
            a, b = -f.get("depth2", f["depth"]), f["depth"]
        elif mode == "through_all":
            a, b = 0.0, big
        elif mode == "through_all_both":
            a, b = -big, big
        else:
            a, b = 0.0, f["depth"]
        if mode not in ("mid_plane", "through_all_both") and rev != cut:  # a Pocket goes against the normal
            a, b = -b, -a
        return a, b

    def prism(self, sk, face, a, b):
        p = face.extrude(V(0, 0, b - a))
        p.translate(V(0, 0, a))
        p.Placement = sk.Placement.multiply(p.Placement)
        return p

    def choose_regions(self, sk, cut, a, b):
        """Regions that add material the exact solid has (boss) or remove material it lacks (cut)."""
        tip = self.tip_shape()
        keep = []
        for fc in self.sketch_regions(sk):
            pr = self.prism(sk, fc, a, b)
            if cut:
                if tip is None:
                    continue
                gone = pr.common(tip)

                if gone.Volume > 1e-9 and gone.common(self.ref).Volume < 0.5 * gone.Volume:
                    keep.append(fc)
            else:
                new = pr.cut(tip) if tip is not None else pr
                if new.Volume > 1e-9 and new.common(self.ref).Volume >= 0.75 * new.Volume:
                    keep.append(fc)
        return keep

    @staticmethod
    def edge_geometry(e):
        """A sketch geometry for a planar edge in sketch coordinates."""
        c = e.Curve
        a, b = e.FirstParameter, e.LastParameter
        p0, pm, p1 = e.valueAt(a), e.valueAt((a + b) / 2), e.valueAt(b)
        if isinstance(c, Part.Line):
            return Part.LineSegment(p0, p1)
        if isinstance(c, Part.Circle):
            if e.isClosed():
                return Part.Circle(c.Center, V(0, 0, 1), c.Radius)
            # always counter-clockwise about +z, which is how Sketcher stores arcs
            ccw = (pm - p0).cross(p1 - pm).z > 0
            s, t = (p0, p1) if ccw else (p1, p0)
            a0 = math.atan2(s.y - c.Center.y, s.x - c.Center.x)
            a1 = math.atan2(t.y - c.Center.y, t.x - c.Center.x)
            while a1 <= a0:
                a1 += 2 * math.pi
            return Part.ArcOfCircle(Part.Circle(c.Center, V(0, 0, 1), c.Radius), a0, a1)
        bs = e.Curve.toBSpline(a, b) if not isinstance(c, Part.BSplineCurve) else c.copy()
        if isinstance(c, Part.BSplineCurve):
            bs.segment(a, b)
        return bs

    def profile_sketch(self, sk, faces, label, shift=0.0):
        """A new sketch on sk's plane (moved shift along its normal) holding the outline of the given region faces."""
        shape = faces[0] if len(faces) == 1 else faces[0].fuse(faces[1:]).removeSplitter()
        p = self.body.newObject("Sketcher::SketchObject", "Sketch")
        p.Label = label
        p.MapMode = "Deactivated"
        n = sk.Placement.Rotation.multVec(V(0, 0, 1))
        p.Placement = App.Placement(sk.Placement.Base + n * shift, sk.Placement.Rotation)
        for fc in shape.Faces:
            for w in fc.Wires:
                for e in w.Edges:
                    p.addGeometry(self.edge_geometry(e), False)
        self.auto_relations(p)
        p.Visibility = False
        return p

    def region_profile(self, f, sk, cut, a, b, shift=0.0):
        ""


        if not shift and not self.needs_regions(sk):
            return sk
        if self.needs_regions(sk):
            faces = self.choose_regions(sk, cut, a + shift, b + shift)
            if not faces:
                raise RuntimeError("no sketch region of %s fits the file's shape" % sk.Label)
        else:
            wires = [Part.Wire(es) for es in Part.sortEdges(self.profile_edges(sk))]
            faces = Part.makeFace(wires, "Part::FaceMakerBullseye").Faces
        label = "%s (%s)" % (sk.Label, f["name"]) + (" offset %g" % shift if shift else "")
        return self.profile_sketch(sk, faces, label, shift)

    @staticmethod
    def set_extent(o, cut, mode, f, big):
        """Extent of a Pad/Pocket; FreeCAD 1.1 has SideType, older versions Midplane/TwoLengths."""
        sides = "SideType" in o.PropertiesList
        if isinstance(mode, float):
            o.Length = mode
        elif mode == "mid_plane":
            if sides:
                o.SideType = "Symmetric"
            else:
                o.Midplane = True
            o.Length = f["depth"]
        elif mode == "two":
            if sides:
                o.SideType = "Two sides"
                o.Type = "Length"
                o.Type2 = "Length"
            else:
                o.Type = [t for t in o.getEnumerationsOfProperty("Type") if "TwoLengths" in t][0]
            o.Length = f["depth"]
            o.Length2 = f.get("depth2", f["depth"])
        elif mode in ("through_all", "through_all_both"):
            if cut:
                o.Type = "ThroughAll"
            else:
                o.Length = big
            if mode == "through_all_both":
                if sides:
                    o.SideType = "Symmetric"
                else:
                    o.Midplane = True
                if not cut:
                    o.Length = 2 * big
        else:
            o.Length = f["depth"]

    @staticmethod
    def geometry_points(sk):
        pts = []
        for g in sk.Geometry:
            for a in ("StartPoint", "EndPoint", "Center"):
                if hasattr(g, a):
                    try:
                        pts.append(getattr(g, a))
                    except Exception:
                        pass
        return pts, [g.copy() for g in sk.Geometry]

    @staticmethod
    def same_points(a, b, tol=1e-5):
        return len(a[0]) == len(b[0]) and all((p - q).Length < tol for p, q in zip(a[0], b[0]))

    # -------------------------------------------------------------- features
    def run(self):
        for f in self.tree["features"]:
            if f.get("suppressed"):
                self.note(f["name"], "skipped (suppressed in the file)")
                continue
            kind = f.get("kind") or ("sketch" if "sketch" in f else None)
            if f["type"] in ("BaseBody", "MBimport", "ImportedBody"):
                kind = "imported"
            elif f["type"] == "MirrorSolid":
                kind = "MirrorSolid"
            elif f["type"] in ("ExtruThin", "CutThin", "ExtrusionThin"):
                kind = "thin"
            elif f["type"] == "HoleWzd":
                kind = "hole"
            elif f["type"] in ("Sweep", "SweepCut"):
                kind = "sweep"
            elif f["type"] == "SweepThread":
                kind = "thread"
            fn = getattr(self, "a_" + str(kind), None)
            if fn is None:
                if f["type"] not in ("CommentsFolder", "FavoriteFolder", "HistoryFolder", "SelectionSetFolder",
                                     "SensorFolder", "DocsFolder", "DetailCabinet", "SurfaceBodyFolder",
                                     "SolidBodyFolder", "EnvFolder", "InkMarkupFolder", "EqnFolder",
                                     "MaterialFolder", "OriginProfileFeature", "MateReferenceGroupFolder",
                                     "Attribute", "BlockFolder", "LiveSectionFolder", "MarkerHolder"):
                    self.note(f["name"], "not rebuilt", kind=f["type"])
                continue
            try:
                fn(f)
            except Exception as exc:
                self.note(f["name"], "failed", kind=kind, error=str(exc)[:200])

    def a_sketch(self, f):
        self.build_sketch(f)

    def profile(self, f):
        for p in f.get("parents", []):
            if p in self.made and self.made[p].TypeId == "Sketcher::SketchObject":
                return self.made[p]
        return self.last_sketch

    def a_extrude(self, f):
        sk = self.profile(f)
        if sk is None:
            self.note(f["name"], "not rebuilt", kind="extrude", error="no sketch")
            return
        name = f["name"].lower()
        if f["type"] in ("Cut", "CutThin") or name.startswith("cut"):
            ops = (True,)
        elif name.startswith(("boss", "base", "extrude")):
            ops = (False,)
        else:
            ops = (False, True)
        end = f.get("end")

        if f.get("thin"):
            return self.a_thin(f)

        def make(var):
            cut, rev, mode, start = var
            a, b = self.interval(cut, rev, mode, f)
            shift = start if b > 0 else -start  # the start offset runs the way the extrusion goes
            prof = self.region_profile(f, sk, cut, a, b, shift)
            o = self.body.newObject("PartDesign::Pocket" if cut else "PartDesign::Pad", "Feature")
            o.Label = f["name"]
            o.Profile = prof
            o.Refine = True
            o.Reversed = rev
            self.set_extent(o, cut, mode, f, 2 * self.scale)
            return o

        modes = self.extrude_modes(f, sk)
        want = bool(f.get("reverse"))
        before = self.mismatch(self.tip_shape())
        start0 = abs(f.get("start_offset") or 0.0) if f.get("start") == 3 else 0.0  # "From: Offset", newer exports
        variants = [(c, r, m, start0) for c in ops for m in modes for r in (want, not want)]
        obj, err, var = self.try_variants(f["name"], make, variants)
        if obj is None or err >= before - 1e-6 * self.ref_vol:
            # Nothing helps from the sketch plane: try starting at an offset (not in the export),
            # at the distances of the exact solid's faces that are parallel to the sketch
            starts = [s for s in self.reach_lengths(sk) if s < self.scale][:6]
            extra = [(c, r, m, s) for c in ops for m in modes if m not in ("mid_plane", "through_all_both")
                     for s in starts for r in (want, not want)]
            if extra:
                failed = list(self.variant_errors)
                if obj is not None:  # take it out again; it competes with the offsets below
                    keep = set(o.Name for o in self.doc.Objects) - self.new_names(obj)
                    self._drop_new(keep, obj.BaseFeature)
                obj2, err2, var2 = self.try_variants(f["name"], make, ([var] if obj is not None else []) + extra)
                obj, err, var = obj2, err2, var2
                if obj is None:
                    self.variant_errors = failed + self.variant_errors
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="cut" if var[0] else "boss",
                  end=f.get("end"), direction_as_solidworks=(var[1] == want), mismatch=self.pct(err),
                  **({"start_offset": var[3]} if var[3] else {}))

    def new_names(self, obj):
        """obj and the profile sketch made for it (a profile sketch that is not in the tree)."""
        out = {obj.Name}
        prof = getattr(obj, "Profile", None)
        prof = prof[0] if isinstance(prof, tuple) else prof
        if prof is not None and prof not in self.made.values():
            out.add(prof.Name)
        return out

    def extrude_modes(self, f, sk):
        end = f.get("end")
        if end in ("blind",) and not f.get("both_directions"):
            modes = ["blind"]
        elif f.get("both_directions") and end == "blind":
            modes = ["two"]
        elif end in ("through_all", "mid_plane"):
            modes = [end]
        elif end in ("other", "through_all_both"):  # 9 = through all, both directions
            modes = ["through_all_both", "through_all"]
        else:  # up to next / surface / vertex / body: lengths read off the exact shape
            modes = (["blind"] if f.get("depth") else []) + self.reach_lengths(sk)
        return modes

    # ------------------------------------------------------ thin features
    def a_thin(self, f):
        """Extrude-Thin / Cut-Thin: the profile wire offset into a wall, then padded or pocketed.

        Wall thickness, side and depth come from the tree when the exporter read them
        ("thin": {"thickness", "type"}); what is missing is searched against the exact solid."""
        sk = self.profile(f)
        if sk is None:
            self.note(f["name"], "not rebuilt", kind="thin", error="no sketch")
            return
        cut = f["type"] in ("CutThin", "Cut-Thin") or f["name"].lower().startswith("cut")
        thin = f.get("thin") or {}
        wires = [Part.Wire(es) for es in Part.sortEdges(self.profile_edges(sk))]
        if not wires:
            self.note(f["name"], "not rebuilt", kind="thin", error="empty sketch")
            return
        sides = {0: ("one",), 1: ("other",), 2: ("both",)}.get(thin.get("type"), ("both", "one", "other"))
        if f.get("depth"):
            exts = [(r, m) for m in self.extrude_modes(f, sk) for r in (bool(f.get("reverse")), not f.get("reverse"))]
        else:
            ls = self.reach_lengths(sk)
            exts = [(r, l) for l in ls for r in (False, True)] + [(False, ("mid", 2 * l)) for l in ls]

        def ab(ext):
            rev, m = ext
            if isinstance(m, tuple):
                return -m[1] / 2, m[1] / 2
            return self.interval(cut, rev, m, f)

        def region(t, side):
            out = []
            for w in wires:
                try:
                    if w.isClosed():
                        lo, hi = {"both": (-t / 2, t / 2), "one": (0, t), "other": (-t, 0)}[side]
                        inner = Part.Face(w.makeOffset2D(lo)) if lo else Part.Face(w)
                        outer = Part.Face(w.makeOffset2D(hi)) if hi else Part.Face(w)
                        out.append(outer.cut(inner))
                    else:  # open profile: a wall of thickness t centred on the wire
                        out.append(w.makeOffset2D(t / 2, 2, True, False))
                except Exception:
                    return None
            sh = out[0] if len(out) == 1 else out[0].fuse(out[1:])
            return sh if sh.Faces else None

        def err_of(t, side, ext):
            reg = region(t, side)
            if reg is None:
                return float("inf")
            a, b = ab(ext)
            pr = Part.Compound([self.prism(sk, fc, a, b) for fc in reg.Faces])
            tip = self.tip_shape()
            try:
                shape = (tip.cut(pr) if cut else tip.fuse(pr)) if tip is not None else (None if cut else pr)
            except Exception:
                return float("inf")
            return self.mismatch(shape)

        tlist = [thin["thickness"]] if thin.get("thickness") else [self.scale * k for k in (0.005, 0.01, 0.02, 0.04, 0.08, 0.16)]
        best = min(((err_of(t, s, e), t, s, e) for t in tlist for s in sides for e in exts), key=lambda r: r[0])
        err, t, side, ext = best
        if err == float("inf"):
            self.note(f["name"], "failed", kind="thin", error="no wall fits the file's shape")
            return
        if not thin.get("thickness"):  # refine the wall thickness (golden section)
            lo, hi = t / 2, t * 2
            g = (math.sqrt(5) - 1) / 2
            for _ in range(24):
                m1, m2 = hi - g * (hi - lo), lo + g * (hi - lo)
                if err_of(m1, side, ext) < err_of(m2, side, ext):
                    hi = m2
                else:
                    lo = m1
            t = (lo + hi) / 2
            for nd in (2, 1, 0):
                tr = round(t, nd)
                if tr > 0 and err_of(tr, side, ext) <= err_of(t, side, ext) + 1e-6 * self.ref_vol:
                    t = tr
                    break
        reg = region(t, side)
        before, tip0 = set(x.Name for x in self.doc.Objects), self.body.Tip
        prof = self.profile_sketch(sk, reg.Faces, "%s (%s wall)" % (sk.Label, f["name"]))
        rev, m = ext
        o = self.body.newObject("PartDesign::Pocket" if cut else "PartDesign::Pad", "Feature")
        o.Label = f["name"]
        o.Profile = prof
        o.Refine = True
        o.Reversed = rev
        if isinstance(m, tuple):
            self.set_extent(o, cut, "mid_plane", {"depth": m[1]}, 2 * self.scale)
        else:
            self.set_extent(o, cut, m, f, 2 * self.scale)
        if not self.recompute_ok(o):
            msg = self.status_text(o)
            self._drop_new(before, tip0)
            self.note(f["name"], "failed", kind="thin", error=msg)
            return
        self.made[f["name"]] = o
        self.note(f["name"], "rebuilt", kind="cut thin" if cut else "boss thin", wall=round(t, 4), wall_side=side,
                  wall_from_tree=bool(thin.get("thickness")), mismatch=self.pct(self.mismatch(o.Shape)))

    # ------------------------------------------------------ hole wizard
    # Older exports have no hole data, and the hole's placement sketch is a sub-feature the
    # tree walk does not see. So the holes are read off the exact solid: what it lacks
    # compared with the current Tip, split into coaxial cavities, each read as a simple,
    # counterbore or countersink hole.
    def hole_cavities(self):
        tip = self.tip_shape()
        if tip is None:
            return []
        out = []
        for s in tip.cut(self.ref).Solids:
            h = self.read_hole(s, tip)
            if h is not None:
                h["spec"] = self.hole_spec(h)
                out.append(h)
        return out

    @staticmethod
    def read_hole(solid, tip, tol=1e-4):
        """A cavity as a hole: axis (pointing into the material), entry point and profile
        [(t0, t1, r0, r1)] by depth t from the entry, or None if it is not a hole."""
        axis = center = None
        for fc in solid.Faces:
            sf = fc.Surface
            if isinstance(sf, (Part.Cylinder, Part.Cone)):
                a = V(sf.Axis).normalize()
                c = V(sf.Center) if isinstance(sf, Part.Cylinder) else V(sf.Apex)
                if axis is None:
                    axis, center = a, c
                elif abs(abs(a.dot(axis)) - 1) > 1e-6 or (c - center).cross(axis).Length > tol:
                    return None
            elif isinstance(sf, Part.Plane):
                continue  # checked below, once the axis is known
            else:
                return None
        if axis is None:
            return None
        for fc in solid.Faces:  # planes must be square to the axis
            if isinstance(fc.Surface, Part.Plane) and abs(abs(V(fc.Surface.Axis).normalize().dot(axis)) - 1) > 1e-6:
                return None

        def t(p):
            return (p - center).dot(axis)

        def rad(p):
            return (p - center).cross(axis).Length

        lo = min(t(v.Point) for v in solid.Vertexes)
        hi = max(t(v.Point) for v in solid.Vertexes)

        def opened(tt, out_sign):  # open to the air just beyond this end?
            return not tip.isInside(center + axis * (tt + out_sign * 1e-3), 1e-7, True)

        segs = []
        for fc in solid.Faces:
            if isinstance(fc.Surface, (Part.Cylinder, Part.Cone)):
                pts = [v.Point for v in fc.Vertexes]
                ts = [t(p) for p in pts]
                a0, a1 = min(ts), max(ts)
                if isinstance(fc.Surface, Part.Cylinder):
                    segs.append((a0, a1, fc.Surface.Radius, fc.Surface.Radius))
                else:
                    r0 = min((rad(p) for p in pts if abs(t(p) - a0) < 1e-6), default=0.0)
                    r1 = min((rad(p) for p in pts if abs(t(p) - a1) < 1e-6), default=0.0)
                    if not any(abs(t(p) - a1) < 1e-6 for p in pts if rad(p) > 1e-6):
                        r1 = 0.0  # cone running out to its apex (a drill point)
                    segs.append((a0, a1, r0, r1))
        if not segs:
            return None
        open_lo, open_hi = opened(lo, -1), opened(hi, +1)
        if not (open_lo or open_hi):
            return None  # a closed void, not a hole
        r_lo = max(s[2] for s in segs if s[0] <= lo + 1e-6) if any(s[0] <= lo + 1e-6 for s in segs) else 0.0
        r_hi = max(s[3] for s in segs if s[1] >= hi - 1e-6) if any(s[1] >= hi - 1e-6 for s in segs) else 0.0
        if not (open_lo and (not open_hi or r_lo >= r_hi)):  # the entry is the hi end: flip
            axis = -axis
            segs = [(-b, -a, rb, ra) for a, b, ra, rb in segs]
            lo, hi = -hi, -lo
        entry = center + axis * lo
        segs = sorted(((a - lo, b - lo, ra, rb) for a, b, ra, rb in segs), key=lambda s: s[0])
        return {"axis": axis, "entry": entry, "segments": segs, "depth": hi - lo, "through": open_lo and open_hi}

    @staticmethod
    def hole_spec(h):
        """Simple / counterbore / countersink parameters of a cavity, or None for other profiles."""
        segs = [s for s in h["segments"] if s[1] - s[0] > 1e-7]
        cyl = [s for s in segs if abs(s[2] - s[3]) < 1e-6]
        cones = [s for s in segs if abs(s[2] - s[3]) >= 1e-6]
        spec = {"through": h["through"], "depth": h["depth"], "cut": "None", "point": None}
        tail = [c for c in cones if c[3] < 1e-6 and c[1] >= h["depth"] - 1e-6]
        if tail and not h["through"]:  # drill point at the bottom
            c = tail[0]
            spec["point"] = math.degrees(2 * math.atan(c[2] / (c[1] - c[0])))
            cones = [x for x in cones if x is not c]
        radii = sorted(set(round(s[2], 6) for s in cyl), reverse=True)
        if not radii:
            return None
        spec["diameter"] = 2 * radii[-1]
        body = [s for s in cyl if round(s[2], 6) == radii[-1]]
        if len(radii) == 2 and not cones:
            cb = [s for s in cyl if round(s[2], 6) == radii[0]]
            if cb[0][0] > 1e-6:
                return None
            spec.update(cut="Counterbore", cut_diameter=2 * radii[0], cut_depth=cb[0][1])
        elif len(radii) == 1 and len(cones) == 1 and cones[0][0] < 1e-6 and cones[0][2] > cones[0][3]:
            c = cones[0]
            spec.update(cut="Countersink", cut_diameter=2 * c[2],
                        cut_angle=math.degrees(2 * math.atan((c[2] - c[3]) / (c[1] - c[0]))))
        elif not (len(radii) == 1 and not cones):
            return None
        if spec["point"] is not None:
            spec["depth"] = max(s[1] for s in body)  # FreeCAD's Depth ends where the drill point starts
        return spec

    def hole_patterns(self, f):
        """Linear patterns later in the tree that copy this hole: [(count, spacing)]."""
        out, seen = [], False
        for g in self.tree["features"]:
            if g is f:
                seen = True
            elif seen and g.get("type") == "LPattern" and f["name"] in g.get("parents", []):
                if (g.get("D1TotalInstances") or 0) > 1 and g.get("D1Spacing"):
                    out.append((int(g["D1TotalInstances"]), float(g["D1Spacing"])))
        return out

    def hole_sketch_points(self, f):
        """Placement points from the hole's own sketch, when a newer export captured it."""
        out = []
        for s in f.get("sub_sketches", []):
            if "to_model" in s:
                pl = sketch_placement(s["to_model"])
                out += [pl.multVec(V(*p["at"])) for p in s.get("points", [])]
        return out

    def hole_seeds(self, f, holes):
        """The holes this feature made, as opposed to copies a later pattern makes."""
        pts = self.hole_sketch_points(f)
        if pts:
            on = [c for c in holes if any((p - c["entry"]).cross(c["axis"]).Length < 1e-3 for p in pts)]
            if on:
                return on

        def same(a, b):
            return all(abs(a["spec"].get(k, 0) - b["spec"].get(k, 0)) < 1e-4 for k in ("diameter", "cut_diameter", "depth"))

        def found(c, p):
            return any(same(x, c) and (x["entry"] - p).Length < 1e-3 for x in holes)

        for n, s in self.hole_patterns(f):
            for d in (V(1, 0, 0), V(-1, 0, 0), V(0, 1, 0), V(0, -1, 0), V(0, 0, 1), V(0, 0, -1)):
                starts = [c for c in holes if all(found(c, c["entry"] + d * (k * s)) for k in range(1, n))
                          and not found(c, c["entry"] - d * s)]
                if starts:
                    return starts
        return holes

    def undo_profile_holes(self, f):
        for o in reversed(getattr(self, "profile_holes", [])):
            sk = o.Profile[0]
            for x in (o, sk):
                try:
                    self.body.removeObject(x)
                    self.doc.removeObject(x.Name)
                except Exception:
                    pass
        self.profile_holes = []
        self.made.pop(f["name"], None)
        self.doc.recompute()

    def a_hole(self, f):
        before = self.mismatch(self.tip_shape())
        if self.hole_from_profile(f):           # the hole's own profile and positions, from the tree
            if self.mismatch(self.tip_shape()) < before - 1e-9:
                return
            self.log.pop()
            self.undo_profile_holes(f)
        cavs = self.hole_cavities()
        if not cavs:
            self.note(f["name"], "not rebuilt", kind="hole", error="no hole-shaped cavity in the file's shape")
            return
        holes = [c for c in cavs if c["spec"] is not None]
        seeds = self.hole_seeds(f, holes) if holes else []
        if seeds:
            # one Hole feature has one size: keep the size that occurs most
            groups = {}
            for c in seeds:
                k = tuple(round(c["spec"].get(x, 0), 4) for x in ("diameter", "cut_diameter", "depth")) + (c["spec"]["cut"],)
                groups.setdefault(k, []).append(c)
            seeds = max(groups.values(), key=len)
            if self.build_hole(f, seeds):
                return
        # a profile Hole cannot express, or a Hole that did not fit: revolve the cavity profiles
        self.build_groove_holes(f, seeds or cavs)

    def hole_sketch(self, seeds, label):
        """A sketch on the first hole's entry face, normal out of the material, a circle per hole."""
        z = -seeds[0]["axis"]
        x = V(1, 0, 0) if abs(z.x) < 0.9 else V(0, 1, 0)
        x = (x - z * x.dot(z)).normalize()
        pl = App.Placement(seeds[0]["entry"], App.Rotation(x, z.cross(x), z, "ZXY"))
        sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
        sk.Label = label
        sk.MapMode = "Deactivated"
        sk.Placement = pl
        inv = pl.inverse()
        for c in seeds:
            p = inv.multVec(c["entry"])
            sk.addGeometry(Part.Circle(V(p.x, p.y, 0), V(0, 0, 1), c["spec"]["diameter"] / 2), False)
        sk.Visibility = False
        return sk

    def build_hole(self, f, seeds):
        spec = seeds[0]["spec"]
        before = self.mismatch(self.tip_shape())

        def make(rev):
            h = self.body.newObject("PartDesign::Hole", "Hole")
            h.Label = f["name"]
            h.Profile = self.hole_sketch(seeds, "%s (placement)" % f["name"])
            h.Diameter = spec["diameter"]
            if spec["through"]:
                h.DepthType = "ThroughAll"
            else:
                h.DepthType = "Dimension"
                h.Depth = spec["depth"]
            h.HoleCutType = spec["cut"]
            if spec["cut"] != "None":
                h.HoleCutDiameter = spec["cut_diameter"]
            if spec["cut"] == "Counterbore":
                h.HoleCutDepth = spec["cut_depth"]
            if spec["cut"] == "Countersink":
                h.HoleCutCountersinkAngle = spec["cut_angle"]
            h.DrillPoint = "Angled" if spec["point"] is not None else "Flat"
            if spec["point"] is not None:
                h.DrillPointAngle = spec["point"]
            h.Reversed = rev
            h.Refine = True
            return h
        obj, err, var = self.try_variants(f["name"], make, (False, True))
        if obj is None or err >= before - 1e-6 * self.ref_vol:
            if obj is not None:
                self._drop_new(set(o.Name for o in self.doc.Objects) - self.new_names(obj), obj.BaseFeature)
            return False
        self.made[f["name"]] = obj
        dims = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in spec.items()}
        self.note(f["name"], "rebuilt", kind="hole", holes=len(seeds), hole=dims,
                  at=[[round(c, 4) for c in s["entry"]] for s in seeds], mismatch=self.pct(err))
        return True

    def build_groove_holes(self, f, cavs):
        """Fallback: one Groove per cavity, revolving its profile (radius against depth)."""
        made, err = None, float("inf")
        for c in cavs:
            a = c["axis"]
            u = V(1, 0, 0) if abs(a.x) < 0.9 else V(0, 1, 0)
            u = (u - a * u.dot(a)).normalize()
            before = set(o.Name for o in self.doc.Objects)
            tip0 = self.body.Tip
            sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
            sk.Label = "%s (profile)" % f["name"]
            sk.MapMode = "Deactivated"
            sk.Placement = App.Placement(c["entry"], App.Rotation(u, a, u.cross(a), "ZXY"))  # x = radius, y = depth
            pts = [V(0, 0, 0)]
            for t0, t1, r0, r1 in c["segments"]:
                pts += [V(r0, t0, 0), V(r1, t1, 0)]
            pts.append(V(0, c["depth"], 0))
            loop = [pts[0]]
            for p in pts[1:]:
                if (p - loop[-1]).Length > 1e-7:
                    loop.append(p)
            for i, p in enumerate(loop):
                q = loop[(i + 1) % len(loop)]
                if (q - p).Length > 1e-7:
                    sk.addGeometry(Part.LineSegment(p, q), False)
            sk.Visibility = False
            g = self.body.newObject("PartDesign::Groove", "Feature")
            g.Label = f["name"]
            g.Profile = sk
            g.ReferenceAxis = (sk, ["V_Axis"])
            g.Angle = 360.0
            g.Refine = True
            if self.recompute_ok(g):
                made, err = g, self.mismatch(g.Shape)
            else:
                self._drop_new(before, tip0)
        if made is None:
            self.note(f["name"], "failed", kind="hole", error="cavities found but no hole or groove fits")
            return
        self.made[f["name"]] = made
        self.note(f["name"], "rebuilt", kind="hole (revolved profile)", holes=len(cavs), mismatch=self.pct(err))

    def a_revolve(self, f):
        sk = self.profile(f)
        if sk is None:
            self.note(f["name"], "not rebuilt", kind="revolve", error="no sketch")
            return
        axes = [i for i, g in enumerate(sk.Geometry) if isinstance(g, Part.LineSegment) and sk.getConstruction(i)]
        refs = [(sk, ["Axis%d" % k]) for k in range(len(axes))]
        if not refs:
            refs = [(sk, ["V_Axis"]), (sk, ["H_Axis"])]
            refs += [(sk, ["Edge%d" % (i + 1)]) for i, g in enumerate(sk.Geometry)
                     if isinstance(g, Part.LineSegment) and not sk.getConstruction(i)]
            refs += [(a, [""]) for a in self.body.Origin.OriginFeatures if a.TypeId == "App::Line"]
        # older exports overwrote "type" with the revolve's own Type number, so also go by the name
        cut = f["type"] == "RevCut" or f["name"].lower().startswith("cut")
        angle = math.degrees(f.get("angle", 2 * math.pi))

        def make(var):
            ax, rev = var
            o = self.body.newObject("PartDesign::Groove" if cut else "PartDesign::Revolution", "Feature")
            o.Label = f["name"]
            o.Profile = sk
            o.ReferenceAxis = ax
            o.Angle = min(angle, 360.0)
            o.Reversed = rev
            o.Refine = True
            return o

        variants = [(a, r) for a in refs for r in ((False, True) if angle < 359.99 else (False,))]
        obj, err, var = self.try_variants(f["name"], make, variants)
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="revolve", mismatch=self.pct(err))

    def a_sweep(self, f):
        sks = [self.made[p] for p in f.get("parents", []) if p in self.made
               and self.made[p].TypeId == "Sketcher::SketchObject"]
        if len(sks) < 2:
            self.note(f["name"], "not rebuilt", kind="sweep", error="needs a profile and a path sketch")
            return
        closed = [k for k in sks if k.Shape.Wires and k.Shape.Wires[0].isClosed()]
        prof = closed[0] if closed else sks[0]
        path = [k for k in sks if k is not prof][0]
        cut = f["type"] == "SweepCut"

        def make(var):
            o = self.body.newObject("PartDesign::SubtractivePipe" if cut else "PartDesign::AdditivePipe", "Feature")
            o.Label = f["name"]
            o.Profile = prof
            o.Spine = (path, ["Edge%d" % (i + 1) for i in range(len(path.Shape.Edges))])
            o.Transition = var
            o.Refine = True
            return o

        obj, err, var = self.try_variants(f["name"], make, ("Transformed", "Right corner", "Round corner"))
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="sweep", mismatch=self.pct(err))

    def thread_dims(self, f):
        ""

        out = {}
        for d in f.get("dimensions") or []:
            key = str(d.get("name", "")).split("@")[0]
            if key in ("Pitch", "Profile_Height", "Profile_Land", "Profile_Angle"):
                v = d.get("system_value")
                if v is not None:
                    out[key] = v if key == "Profile_Angle" else v * 1000.0
        return out

    def thread_edges(self, f, dims):
        """Circular edges of the shape so far that could be the thread's start edge: the thread's
        diameter dimension (D6, type 6) and an end of a cylinder of that radius."""
        dia = None
        for d in f.get("dimensions") or []:
            if d.get("type") == 6 and str(d.get("name", "")).split("@")[1:2] == [f["name"]]:
                dia = d.get("system_value", 0) * 1000.0
        tip = self.tip_shape()
        if not dia or tip is None:
            return []
        out = []
        for e in tip.Edges:
            cv = e.Curve
            if not isinstance(cv, Part.Circle) or abs(cv.Radius - dia / 2.0) > 1e-4 or not e.isClosed():
                continue
            key = (round(cv.Center.x, 4), round(cv.Center.y, 4), round(cv.Center.z, 4))
            if any(k == key for k, *_ in out):
                continue
            out.append((key, cv.Center, cv.Axis, cv.Radius))
        return [(c, n, r) for _k, c, n, r in out[:6]]

    def build_thread(self, f):
        ""




        dims = self.thread_dims(f)
        if "centre" not in f or not f.get("radius"):
            edges = self.thread_edges(f, dims)
            if not edges:
                self.note(f["name"], "not rebuilt", kind="thread", error="no thread edge in the export")
                return False
            for c_, n_, r_ in edges:
                if self.build_thread(dict(f, centre=list(c_), axis=list(n_), radius=r_)):
                    return True
            self.note(f["name"], "not rebuilt", kind="thread", error="no circular edge took the thread")
            return False
        pitch = dims.get("Pitch") or (f.get("Pitch") if f.get("PitchOverride") else None)
        height = dims.get("Profile_Height")
        if not pitch or not height:
            self.note(f["name"], "not rebuilt", kind="thread", error="no pitch or profile height")
            return False
        land = dims.get("Profile_Land", pitch / 8.0)
        half = (dims.get("Profile_Angle") or math.radians(60.0)) / 2.0
        r = f["radius"]
        if f.get("DiameterOverride") and f.get("Diameter"):
            r = f["Diameter"] / 2.0
        internal = "tap" in str(f.get("Type", "")).lower()
        cut = int(f.get("ThreadMethod", 0)) == 0
        if int(f.get("EndCondition", 0)) == 1 and f.get("Revolutions"):
            length = f["Revolutions"] * pitch
        else:
            length = f.get("BlindDepth") or 0.0
        if length <= 0:
            self.note(f["name"], "not rebuilt", kind="thread", error="no thread length")
            return False
        offset = f.get("OffsetDistance", 0.0) if f.get("Offset") else 0.0
        t = math.tan(half)
        spare = (pitch - land - 2 * height * t) / (2 * t)
        e = max(0.0, min(0.02 * pitch * 4, spare * 0.5)) if cut else 0.0   # overshoot into the air
        w0 = land / 2.0
        w1 = w0 + (height + e) * t
        side = 1.0 if internal else -1.0          # the groove goes outwards for a tapped hole
        if cut:
            prof = [(r + side * height, -w0), (r - side * e, -w1), (r - side * e, w1), (r + side * height, w0)]
        else:                                     # added thread: the tooth stands on the edge's surface
            prof = [(r, -w1), (r - side * height, -w0), (r - side * height, w0), (r, w1)]
        c = V(*f["centre"])
        n = V(*f["axis"])
        n.normalize()
        u = n.cross(V(1, 0, 0)) if abs(n.x) < 0.9 else n.cross(V(0, 1, 0))
        u.normalize()

        def make(var):
            sign, osign = var
            ax = n * sign
            start = c + ax * (offset * osign)
            sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
            sk.Label = f["name"] + " profile"
            sk.MapMode = "Deactivated"
            sk.Placement = App.Placement(start, App.Rotation(u, ax, u.cross(ax), "ZXY"))
            pts = [V(x, y, 0) for x, y in prof]
            for p, q in zip(pts, pts[1:] + pts[:1]):
                sk.addGeometry(Part.LineSegment(p, q))
            for i in range(4):
                sk.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
            sk.Visibility = False
            o = self.body.newObject("PartDesign::SubtractiveHelix" if cut else "PartDesign::AdditiveHelix", "Feature")
            o.Label = f["name"]
            o.Profile = sk
            o.ReferenceAxis = (sk, ["V_Axis"])
            o.Mode = "pitch-height-angle"
            o.Pitch = pitch
            o.Height = length
            o.LeftHanded = not f.get("RightHanded", True)
            o.Refine = False
            return o

        # the thread runs along the axis into the material: probe the solid on both sides of the
        # edge (a helix variant costs a long boolean, so only undecided ones are tried)
        signs = [1.0, -1.0]
        tip = self.tip_shape()
        if tip is not None:
            probe = r - 2.0 * height if not internal else r + 2.0 * height
            if not internal and probe <= 0:
                probe = r * 0.5
            hits = []
            for s_ in signs:
                p = c + n * (s_ * min(length, 1.0) * 0.5) + u * probe
                try:
                    hits.append(tip.isInside(p, 1e-6, True))
                except Exception:
                    hits.append(None)
            if hits.count(True) == 1:
                signs = [signs[hits.index(True)]]
        variants = [(s_, -1.0 if f.get("ReverseOffset") else 1.0) for s_ in signs]
        area = (land + height * t) * height        # groove (or tooth) cross-section, roughly
        expect = area * 2 * math.pi * (r + side * height / 2.0) * length / pitch
        base_tip = self.body.Tip
        v0 = abs(base_tip.Shape.Volume) if base_tip is not None else 0.0
        why = []
        for var in variants:
            before = set(o.Name for o in self.doc.Objects)
            try:
                obj = make(var)
                self.doc.recompute()
                shape = obj.Shape
                ok = obj.isValid() and not shape.isNull() and shape.isValid()
                dv = (v0 - abs(shape.Volume)) if cut else (abs(shape.Volume) - v0)
                if ok and 0.3 * expect <= dv <= 3.0 * expect:
                    self.made[f["name"]] = obj
                    self.note(f["name"], "rebuilt", kind="thread", volume=round(dv, 3),
                              expected=round(expect, 3))
                    return True
                why.append("%s: %s, volume %.3f (expected %.3f)" % (var, "valid" if ok else "invalid", dv, expect))
            except Exception as exc:
                why.append("%s: %s" % (var, str(exc)[:120]))
            self._drop_new(before, base_tip)
        self.variant_errors = why
        self.note(f["name"], "failed", kind="thread")
        return False

    def a_thread(self, f):
        ""

        self.pending_threads = getattr(self, "pending_threads", [])
        self.pending_threads.append(f)
        self.note(f["name"], "deferred", kind="thread")

    def add_threads(self):
        """Builds the deferred threads on the finished tree; their log rows are replaced."""
        for f in getattr(self, "pending_threads", []):
            self.log = [row for row in self.log if not (row["feature"] == f["name"] and row["status"] == "deferred")]
            try:
                self.build_thread(f)
            except Exception as exc:
                self.note(f["name"], "failed", kind="thread", error=str(exc)[:200])
        self.pending_threads = []

    def hole_from_profile(self, f):
        ""

        subs = f.get("sub_sketches") or []
        prof = [s for s in subs if s.get("segments")]
        spots = [s for s in subs if not s.get("segments") and s.get("points")]
        if not prof or not spots:
            return False
        prof = prof[0]
        pts = [V(*p["at"]) for p in spots[0]["points"]]
        base = sketch_placement(prof["to_model"])
        made = []
        for k, at in enumerate(pts):
            sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
            sk.Label = "%s profile%d" % (f["name"], k + 1)
            sk.MapMode = "Deactivated"
            sk.Placement = App.Placement(at, base.Rotation)
            for seg in prof["segments"]:
                g = self.segment(seg)
                if g is not None:
                    sk.addGeometry(g, bool(seg.get("construction")))
            sk.Visibility = False
            o = self.body.newObject("PartDesign::Groove", "Feature")
            o.Label = f["name"] if not k else "%s (%d)" % (f["name"], k + 1)
            o.Profile = sk
            o.ReferenceAxis = (sk, ["V_Axis"])
            o.Angle = 360.0
            o.Refine = True
            made.append(o)
        self.doc.recompute()
        tip = self.tip_shape()
        self.profile_holes = made
        if tip is None or not tip.isValid() or any(not o.isValid() for o in made):
            self.undo_profile_holes(f)
            return False
        self.made[f["name"]] = made[-1]
        self.note(f["name"], "rebuilt", kind="hole", holes=len(made), how="profile",
                  mismatch=self.pct(self.mismatch(self.tip_shape())))
        return True

    def edges_matching(self, samples, tol=1e-3):
        shape = self.tip_shape()
        out = []
        if shape is None:
            return out
        for pts in samples:
            for i, e in enumerate(shape.Edges):
                if all(e.distToShape(Part.Vertex(V(*q)))[0] < tol for q in pts):
                    out.append("Edge%d" % (i + 1))
                    break
        return out

    def a_fillet(self, f):
        edges = self.edges_matching(f.get("edges", []))
        if not edges:

            edges = self.dressup_edges(f["radius"], "fillet")
        self._api_dressup(f, "PartDesign::Fillet", edges, lambda o: setattr(o, "Radius", f["radius"]))

    def a_chamfer(self, f):
        edges = self.edges_matching(f.get("edges", [])) or self.dressup_edges(f.get("distance", 1.0), "chamfer")

        def setup(o):
            o.Size = f.get("distance", 1.0)
            if f.get("angle"):
                o.ChamferType = "Distance and Angle"
                o.Angle = math.degrees(f["angle"])
        self._api_dressup(f, "PartDesign::Chamfer", edges, setup)

    @staticmethod
    def ring_geometry(shape, e):
        """A circular edge where a cylinder of the same radius meets a plane square to its axis:
        (centre, axis towards the cylinder face, radius, radial side of the plane face)."""
        cv = e.Curve
        if not isinstance(cv, Part.Circle):
            return None
        faces = [fc for fc in shape.Faces if any(e.isSame(x) for x in fc.Edges)]
        cyl = [fc for fc in faces if isinstance(fc.Surface, Part.Cylinder)]
        pl = [fc for fc in faces if isinstance(fc.Surface, Part.Plane)]
        if len(cyl) != 1 or len(pl) != 1:
            return None
        c, n, rad = cv.Center, V(cv.Axis), cv.Radius
        n.normalize()
        if abs(abs(V(cyl[0].Surface.Axis).normalize().dot(n)) - 1) > 1e-6 or abs(cyl[0].Surface.Radius - rad) > 1e-6:
            return None
        h = (cyl[0].CenterOfMass - c).dot(n)
        if abs(h) < 1e-9:
            return None
        ax = n * (1.0 if h > 0 else -1.0)
        u = ax.cross(V(1, 0, 0)) if abs(ax.x) < 0.9 else ax.cross(V(0, 1, 0))
        u.normalize()
        d = min(rad * 0.25, 0.05)
        out_ = pl[0].distToShape(Part.Vertex(c + u * (rad + d)))[0]
        in_ = pl[0].distToShape(Part.Vertex(c + u * (rad - d)))[0]
        if abs(out_ - in_) < 1e-9:
            return None
        side = 1.0 if out_ < in_ else -1.0     # the plane face lies outside or inside the ring
        return (c, ax, rad, side)

    def ring_fillet(self, f, g, r):
        ""



        c, ax, rad, side = g
        u = ax.cross(V(1, 0, 0)) if abs(ax.x) < 0.9 else ax.cross(V(0, 1, 0))
        u.normalize()
        tip = self.tip_shape()
        if tip is None:
            return None
        probe = c + u * (rad + side * 0.25 * r) + ax * (0.25 * r)
        try:
            air = not tip.isInside(probe, 1e-7, True)
        except Exception:
            return None
        err0 = self.mismatch(tip)
        before = set(o.Name for o in self.doc.Objects)
        base_tip = self.body.Tip
        sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
        sk.Label = f["name"] + " ring"
        sk.MapMode = "Deactivated"
        sk.Placement = App.Placement(c, App.Rotation(u, ax, u.cross(ax), "ZXY"))
        x0, x1 = rad, rad + side * r
        p0, p1, p2 = V(x0, 0, 0), V(x1, 0, 0), V(x0, r, 0)
        sk.addGeometry(Part.LineSegment(p0, p1))
        arc = Part.ArcOfCircle(Part.Circle(V(x1, r, 0), V(0, 0, 1), r),
                               *((math.pi, 1.5 * math.pi) if side > 0 else (1.5 * math.pi, 2 * math.pi)))
        sk.addGeometry(arc)
        sk.addGeometry(Part.LineSegment(p2, p0))
        sk.Visibility = False
        o = self.body.newObject("PartDesign::Revolution" if air else "PartDesign::Groove", "Feature")
        o.Label = f["name"]
        o.Profile = sk
        o.ReferenceAxis = (sk, ["V_Axis"])
        o.Angle = 360.0
        o.Refine = True
        try:
            ok = self.recompute_ok(o) and o.Shape.isValid() and self.mismatch(o.Shape) < err0
        except Exception:
            ok = False
        if ok:
            return o
        self._drop_new(before, base_tip)
        return None

    def _dressup_subset(self, f, tid, base, edges, setup):
        ""


        kept = []
        for e in edges:
            trial = kept + [e]
            o = self.body.newObject(tid, "Feature")
            o.Base = (base, trial)
            setup(o)
            ok = self.recompute_ok(o) and o.Shape.isValid()
            self._remove(o)
            if ok:
                kept = trial
        return kept

    def _api_dressup(self, f, tid, edges, setup):
        base = self.body.Tip
        if not edges or base is None:
            self.note(f["name"], "not rebuilt", kind=tid.split("::")[1].lower(), error="edges not found")
            return
        o = self.body.newObject(tid, "Feature")
        o.Label = f["name"]
        o.Base = (base, edges)
        setup(o)
        o.Refine = True
        if not self.recompute_ok(o) or not o.Shape.isValid():
            self._remove(o)
            kind = tid.split("::")[1].lower()
            kept = self._dressup_subset(f, tid, base, edges, setup) if len(edges) > 1 else []
            # what each left-over edge looks like on the shape the dress-up was meant for
            rings = []
            if kind == "fillet":
                shp = base.Shape
                for name in edges:
                    if name not in kept:
                        g = self.ring_geometry(shp, shp.getElement(name))
                        if g is not None:
                            rings.append(g)
            if not kept and not rings:
                self.note(f["name"], "failed", kind=kind, edges=len(edges))
                return
            o = None
            if kept:
                o = self.body.newObject(tid, "Feature")
                o.Label = f["name"]
                o.Base = (base, kept)
                setup(o)
                o.Refine = True
                self.recompute_ok(o)
            made = len(kept)
            for g in rings:
                if self.ring_fillet(f, g, f["radius"]) is not None:
                    made += 1
            if not made:
                self.note(f["name"], "failed", kind=kind, edges=len(edges))
                return
            self.made[f["name"]] = self.body.Tip
            self.note(f["name"], "rebuilt", kind=kind, edges=made,
                      solidworks_edges=len(f.get("edges", [])), partial=len(edges) - made,
                      mismatch=self.pct(self.mismatch(self.tip_shape())))
            return
        self.made[f["name"]] = o
        self.note(f["name"], "rebuilt", kind=tid.split("::")[1].lower(), edges=len(edges),
                  solidworks_edges=len(f.get("edges", [])), mismatch=self.pct(self.mismatch(o.Shape)))

    def ancestors(self, name, seen=None):
        ""
        seen = set() if seen is None else seen
        rec = self.tree_by_name.get(name) if hasattr(self, "tree_by_name") else None
        if rec is None:
            self.tree_by_name = {x["name"]: x for x in self.tree["features"]}
            rec = self.tree_by_name.get(name)
        for p in (rec or {}).get("parents", []):
            if p not in seen:
                seen.add(p)
                self.ancestors(p, seen)
        return seen

    def seeds(self, f, strict=False):
        ""



        parents = f.get("parents", [])
        built_on = set()
        if strict:
            for p in parents:
                built_on |= self.ancestors(p)
        out = []
        for p in parents:
            o = self.made.get(p)
            if p in built_on:
                continue
            if o is not None and o.TypeId.startswith("PartDesign::") and o.TypeId not in (
                    "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point"):
                out.append(o)
        return out

    def seed_sets(self, f):
        sets = []
        for s in (self.seeds(f, strict=True), self.seeds(f)):
            if s and [o.Name for o in s] not in [[o.Name for o in x] for x in sets]:
                sets.append(s)
        return sets

    def keep_if_better(self, f, obj, err, before, kind):
        """A copy feature (pattern, mirror) that makes the shape worse is dropped."""
        if obj is not None and err > before + 1e-6 * self.ref_vol:
            self._drop_new(set(o.Name for o in self.doc.Objects) - {obj.Name}, obj.BaseFeature)
            self.cleanup_datums()
            self.note(f["name"], "failed", kind=kind, error="made the shape worse (%s%% -> %s%%)" % (self.pct(before), self.pct(err)))
            return False
        return True

    def mirror_planes(self, f):
        """Candidate mirror planes: datum planes among the parents, the origin planes, and the
        planes of the body's bounding-box faces (mirroring about a face is common, and a face
        is not in the parents)."""
        planes = [(V(), V(0, 0, 1)), (V(), V(0, 1, 0)), (V(), V(1, 0, 0))]
        for p in f.get("parents", []):
            o = self.made.get(p)
            if o is not None and o.TypeId == "PartDesign::Plane":
                planes.insert(0, (o.Placement.Base, o.Placement.Rotation.multVec(V(0, 0, 1))))
        tip = self.tip_shape()
        if tip is not None:
            bb = tip.BoundBox
            for n, lo, hi in ((V(1, 0, 0), bb.XMin, bb.XMax), (V(0, 1, 0), bb.YMin, bb.YMax), (V(0, 0, 1), bb.ZMin, bb.ZMax)):
                planes += [(n * lo, n), (n * hi, n)]
        return planes

    def a_MirrorPattern(self, f):
        sets = self.seed_sets(f)
        if not sets:
            self.note(f["name"], "not rebuilt", kind="mirror", error="seed features not found")
            return
        planes = [(s, pl) for s in sets for pl in self.mirror_planes(f)]

        def make(var):
            seeds, pl = var
            dp = self.body.newObject("PartDesign::Plane", "MirrorPlane")
            dp.MapMode = "Deactivated"
            dp.Placement = App.Placement(pl[0], App.Rotation(V(0, 0, 1), pl[1]))
            dp.Visibility = False
            m = self.body.newObject("PartDesign::Mirrored", "Feature")
            m.Label = f["name"]
            m.Originals = seeds
            m.MirrorPlane = (dp, [""])
            m.Refine = True
            return m
        before = self.mismatch(self.tip_shape())
        obj, err, var = self.try_variants(f["name"], make, planes)
        self.cleanup_datums()
        if not self.keep_if_better(f, obj, err, before, "mirror"):
            return
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="mirror", mismatch=self.pct(err))

    def a_LPattern(self, f):
        sets = self.seed_sets(f)
        n = f.get("D1TotalInstances") or 0
        sp = f.get("D1Spacing") or 0
        if not sets or n < 2 or not sp:
            self.note(f["name"], "not rebuilt", kind="linear pattern", error="seeds, count or spacing missing")
            return
        dirs = [(s, d) for s in sets
                for d in (V(1, 0, 0), V(-1, 0, 0), V(0, 1, 0), V(0, -1, 0), V(0, 0, 1), V(0, 0, -1))]

        def make(var):
            seeds, d = var
            ln = self.body.newObject("PartDesign::Line", "PatternDirection")
            ln.MapMode = "Deactivated"
            ln.Placement = App.Placement(V(), App.Rotation(V(0, 0, 1), d))
            ln.Visibility = False
            m = self.body.newObject("PartDesign::LinearPattern", "Feature")
            m.Label = f["name"]
            m.Originals = seeds
            m.Direction = (ln, [""])
            m.Length = sp * (n - 1)
            m.Occurrences = n
            m.Refine = True
            return m
        before = self.mismatch(self.tip_shape())
        obj, err, var = self.try_variants(f["name"], make, dirs)
        self.cleanup_datums()
        if not self.keep_if_better(f, obj, err, before, "linear pattern"):
            return
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="linear pattern", mismatch=self.pct(err))

    def a_CirPattern(self, f):
        ""

        sets = self.seed_sets(f)
        n = int(f.get("TotalInstances") or 0)
        sp = f.get("Spacing")
        if not sets or n < 2 or not sp:
            self.note(f["name"], "not rebuilt", kind="circular pattern", error="seeds, count or angle missing")
            return
        step = math.degrees(sp / 1000.0)          # the export scales every *Spacing by 1000
        total = step if f.get("EqualSpacing") else step * (n - 1)
        if f.get("EqualSpacing") and abs(step - 360.0) > 1e-6:
            total = step
        full = abs(total - 360.0) < 1e-6 or (not f.get("EqualSpacing") and abs(step * n - 360.0) < 1e-6)
        axes = []
        for d in (V(0, 0, 1), V(0, 1, 0), V(1, 0, 0)):
            axes.append((V(), d))
        tip = self.tip_shape()
        if tip is not None:
            for fc in tip.Faces:
                if isinstance(fc.Surface, Part.Cylinder):
                    a = (V(fc.Surface.Center), V(fc.Surface.Axis))
                    if not any((a[0] - b[0]).cross(a[1]).Length < 1e-6 and abs(abs(a[1].dot(b[1])) - 1) < 1e-9
                               for b in axes):
                        axes.append(a)
                if len(axes) >= 9:
                    break
        variants = [(s_, a, r) for s_ in sets for a in axes for r in (False, True)]

        def make(var):
            seeds, (pt, d), rev = var
            ln = self.body.newObject("PartDesign::Line", "PatternAxis")
            ln.MapMode = "Deactivated"
            ln.Placement = App.Placement(pt, App.Rotation(V(0, 0, 1), d))
            ln.Visibility = False
            m = self.body.newObject("PartDesign::PolarPattern", "Feature")
            m.Label = f["name"]
            m.Originals = seeds
            m.Axis = (ln, [""])
            m.Angle = 360.0 if full else total
            m.Occurrences = n
            m.Reversed = rev
            m.Refine = True
            return m
        before = self.mismatch(self.tip_shape())
        obj, err, var = self.try_variants(f["name"], make, variants)
        self.cleanup_datums()
        if not self.keep_if_better(f, obj, err, before, "circular pattern"):
            return
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="circular pattern", mismatch=self.pct(err))

    def faces_matching(self, pts, tol=1e-3):
        shape = self.tip_shape()
        out = []
        if shape is None:
            return out
        for p in pts:
            v = Part.Vertex(V(*p))
            for i, fc in enumerate(shape.Faces):
                if fc.distToShape(v)[0] < tol:
                    out.append("Face%d" % (i + 1))
                    break
        return out

    def a_Shell(self, f):
        faces = self.faces_matching(f.get("faces") or [])
        base = self.body.Tip
        if not faces or base is None or not f.get("thickness"):
            self.note(f["name"], "not rebuilt", kind="shell", error="removed faces not found")
            return

        def make(var):
            rev, join = var
            o = self.body.newObject("PartDesign::Thickness", "Feature")
            o.Label = f["name"]
            o.Base = (base, faces)
            o.Value = f["thickness"]
            o.Reversed = rev
            o.Join = join
            return o
        obj, err, var = self.try_variants(f["name"], make, [(r, j) for j in ("Intersection", "Arc") for r in (False, True)])
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="shell", mismatch=self.pct(err))

    def a_Draft(self, f):
        faces = self.faces_matching(f.get("faces") or [])
        base = self.body.Tip
        nt = f.get("neutral") or {}
        if not faces or base is None or f.get("angle") is None:
            self.note(f["name"], "not rebuilt", kind="draft", error="draft faces not found")
            return
        neutral = []
        if nt.get("point"):
            neutral = self.faces_matching([nt["point"]])
        planes = []
        if neutral:
            planes.append((base, neutral))
        if nt.get("normal") and nt.get("point"):
            dp = self.body.newObject("PartDesign::Plane", "DraftPlane")
            dp.MapMode = "Deactivated"
            dp.Placement = App.Placement(V(*nt["point"]), App.Rotation(V(0, 0, 1), V(*nt["normal"])))
            dp.Visibility = False
            self.body.Tip = base
            planes.append((dp, [""]))
        if not planes:
            self.note(f["name"], "not rebuilt", kind="draft", error="neutral plane not found")
            return

        def make(var):
            pl, rev = var
            o = self.body.newObject("PartDesign::Draft", "Feature")
            o.Label = f["name"]
            o.Base = (base, faces)
            o.NeutralPlane = pl
            o.Angle = math.degrees(f["angle"])
            o.Reversed = rev
            return o
        obj, err, var = self.try_variants(f["name"], make, [(p, r) for p in planes for r in (False, True)])
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="draft", mismatch=self.pct(err))

    def a_Blend(self, f):
        """Loft through the profile sketches, in the tree's order."""
        sks = [self.made[p] for p in f.get("parents", []) if p in self.made
               and self.made[p].TypeId == "Sketcher::SketchObject"]
        if len(sks) < 2:
            self.note(f["name"], "not rebuilt", kind="loft", error="needs two profile sketches")
            return
        cut = f["type"] == "BlendCut"
        order = [o for o in self.doc.Objects if o in sks]

        def make(var):
            seq, ruled = var
            o = self.body.newObject("PartDesign::SubtractiveLoft" if cut else "PartDesign::AdditiveLoft", "Feature")
            o.Label = f["name"]
            o.Profile = seq[0]
            o.Sections = list(seq[1:])
            o.Ruled = ruled
            o.Refine = True
            return o
        seqs = [order] if len(order) > 2 else [order, order[::-1]]
        obj, err, var = self.try_variants(f["name"], make, [(q, r) for q in seqs for r in (False, True)])
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="loft", mismatch=self.pct(err))

    def a_Rib(self, f):
        ""

        sks = [self.made[p] for p in f.get("parents", []) if p in self.made
               and self.made[p].TypeId == "Sketcher::SketchObject"]
        if not sks or self.body.Tip is None or not f.get("thickness"):
            self.note(f["name"], "not rebuilt", kind="rib", error="no rib sketch or nothing to attach to")
            return
        rib = None
        for name in ("swstyle.rib", "freeworks.rib"):
            try:
                rib = __import__(name, fromlist=["RibFeature"])
                break
            except Exception:
                continue
        if rib is None:
            self.note(f["name"], "not rebuilt", kind="rib", error="FreeCAD Rib not available")
            return
        sk = sks[0]
        normal = bool(f.get("ExtrusionDirection"))

        def make(var):
            side, flip = var
            o = self.body.newObject(rib.TYPE, "Rib")
            rib.RibFeature(o)
            try:
                if App.GuiUp:
                    rib.RibView(o.ViewObject)
            except Exception:
                pass
            o.Label = f["name"]
            o.Sketch = sk
            o.Thickness = f["thickness"]
            o.ThicknessSide = side
            o.Flip = flip
            o.ExtrusionDirection = "Normal" if normal else "Parallel"
            if f.get("EnableDraft") and f.get("DraftAngle"):
                o.DraftOn = True
                o.DraftAngle = math.degrees(f["DraftAngle"])
                o.DraftOutward = bool(f.get("DraftOutward"))
            sk.Visibility = False
            return o
        obj, err, var = self.try_variants(f["name"], make, [(sd, fl) for sd in ("Both", "First", "Second")
                                                             for fl in (False, True)])
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="rib", mismatch=self.pct(err))


    @staticmethod
    def _swstyle(name):
        for pkg in ("swstyle", "freeworks"):
            try:
                return __import__("%s.%s" % (pkg, name), fromlist=["x"])
            except Exception:
                continue
        return None

    def _sf_feature(self, f, module, spec_name, setup):
        sf = self._swstyle("simplefeature")
        mod = self._swstyle(module)
        spec = getattr(mod, spec_name, None) if mod is not None else None
        if sf is None or spec is None:
            return None

        def make(var):
            o = self.body.newObject(spec.type, spec.internal)
            sf.Feature(o, spec)
            try:
                if App.GuiUp:
                    sf.View(o.ViewObject)
            except Exception:
                pass
            o.Label = f["name"]
            setup(o, var)
            return o
        return make

    def _sf_run(self, f, kind, make, variants):
        if make is None:
            self.note(f["name"], "not rebuilt", kind=kind, error="FreeCAD %s not available" % kind)
            return
        obj, err, var = self.try_variants(f["name"], make, variants)
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind=kind, mismatch=self.pct(err))

    def a_Dome(self, f):
        faces = self.faces_matching(f.get("faces") or [])
        base = self.body.Tip
        if not faces or base is None or not f.get("height"):
            self.note(f["name"], "not rebuilt", kind="dome", error="dome faces not found")
            return

        def setup(o, rev):
            o.Faces = [(base, faces)]
            o.Distance = f["height"]
            o.Reverse = rev
            o.Elliptical = bool(f.get("elliptical"))
        r = bool(f.get("reverse"))
        self._sf_run(f, "dome", self._sf_feature(f, "directfeatures", "DOME", setup), [r, not r])

    def a_VarFillet(self, f):
        rows = f.get("edges") or []
        edges = self.edges_matching([e["points"] for e in rows])
        base = self.body.Tip
        cps = f.get("cp_radii") or []
        if f.get("control_points") and len(cps) != f["control_points"]:
            cps = None
        if not edges or base is None or cps is None:
            self.note(f["name"], "not rebuilt", kind="variable fillet",
                      error="control points" if f.get("control_points") else "edges not found")
            return
        shape = self.tip_shape()
        r0, r1 = rows[0].get("start_radius"), rows[0].get("end_radius")

        e = shape.getElement(edges[0])
        if e.valueAt(e.FirstParameter).distanceToPoint(V(*rows[0]["start"])) > \
                e.valueAt(e.FirstParameter).distanceToPoint(V(*rows[0]["end"])):
            r0, r1 = r1, r0

        def setup(o, var):
            o.Edges = [(base, edges)]
            o.StartRadius, o.EndRadius = var
            if cps:
                o.ControlPoints = len(cps)
                o.PointRadii = ", ".join("%g" % round(r, 6) for r in cps)
        self._sf_run(f, "variable fillet", self._sf_feature(f, "directfeatures", "VARIABLE_FILLET", setup),
                     [(r0, r1), (r1, r0)])

    def a_Wrap(self, f):
        faces = self.faces_matching(f.get("faces") or [])
        base = self.body.Tip
        sk = self.made.get(f.get("profile")) or self.profile(f)
        if not faces or base is None or sk is None:
            self.note(f["name"], "not rebuilt", kind="wrap", error="wrap face or sketch not found")
            return

        def setup(o, rev):
            o.Sketch = sk
            o.Face = [(base, faces[:1])]
            o.WrapType = f.get("wrap_type", "Emboss")
            o.Thickness = max(float(f.get("thickness") or 0.0), 1e-3)
            o.Reverse = rev
            sk.Visibility = False
        r = bool(f.get("reverse"))
        self._sf_run(f, "wrap", self._sf_feature(f, "wrap", "SPEC", setup), [r, not r])

    def a_Boundary(self, f):
        names = f.get("profiles") or []
        sks = [self.made[n] for n in names if n in self.made] or \
            [self.made[p] for p in f.get("parents", []) if p in self.made
             and self.made[p].TypeId == "Sketcher::SketchObject"]
        bb = self._swstyle("boundaryboss")
        if len(sks) < 2 or bb is None or f.get("guides"):
            self.note(f["name"], "not rebuilt", kind="boundary", error="needs two profiles, no guides")
            return
        kind = "BoundaryCut" if f["type"] == "BoundaryCut" else "BoundaryBoss"

        def make(seq):
            o = self.body.newObject("PartDesign::FeatureSubtractivePython" if kind == "BoundaryCut"
                                    else "PartDesign::FeatureAdditivePython", kind)
            bb.Feature(o, kind)
            try:
                if App.GuiUp:
                    bb.View(o.ViewObject)
            except Exception:
                pass
            o.Label = f["name"]
            o.Direction1 = [(sk, "") for sk in seq]
            for sk in seq:
                sk.Visibility = False
            return o
        obj, err, var = self.try_variants(f["name"], make, [sks, sks[::-1]])
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="boundary", mismatch=self.pct(err))

    def a_imported(self, f):
        ""
        if self.body.Tip is not None or self.body.BaseFeature is not None:
            self.note(f["name"], "not rebuilt", kind="imported body", error="imported body after other features")
            return
        base = self.doc.addObject("Part::Feature", "Imported")
        base.Label = f["name"]
        base.Shape = self.ref
        base.Visibility = False
        self.body.BaseFeature = base
        self.doc.recompute()
        self.made[f["name"]] = base
        self.note(f["name"], "rebuilt", kind="imported body (exact shape)")

    def a_MirrorSolid(self, f):
        if self.body.Tip is None:
            self.note(f["name"], "not rebuilt", kind="mirror body", error="nothing to mirror")
            return
        planes = self.mirror_planes(f)

        def make(pl):
            dp = self.body.newObject("PartDesign::Plane", "MirrorPlane")
            dp.MapMode = "Deactivated"
            dp.Placement = App.Placement(pl[0], App.Rotation(V(0, 0, 1), pl[1]))
            dp.Visibility = False
            m = self.body.newObject("PartDesign::Mirrored", "Feature")
            m.Label = f["name"]
            m.TransformMode = "Whole shape"
            m.MirrorPlane = (dp, [""])
            m.Refine = True
            return m
        before = self.mismatch(self.tip_shape())
        obj, err, var = self.try_variants(f["name"], make, planes)
        self.cleanup_datums()
        if not self.keep_if_better(f, obj, err, before, "mirror body"):
            return
        if obj is not None:
            self.made[f["name"]] = obj
        self.note(f["name"], "rebuilt" if obj is not None else "failed", kind="mirror body", mismatch=self.pct(err))

    def a_plane(self, f):
        p = self.body.newObject("PartDesign::Plane", "Plane")
        p.Label = f["name"]
        p.MapMode = "Deactivated"
        r = f["rotation"]
        p.Placement = App.Placement(V(*f["origin"]), App.Rotation(V(*r[0:3]), V(*r[3:6]), V(*r[6:9]), "ZXY"))
        p.Visibility = False
        self.made[f["name"]] = p
        self.note(f["name"], "rebuilt", kind="plane")


def main(argv):
    tree_path, ref_path, out, rep = argv[:4]
    tree = json.load(open(tree_path, encoding="utf-8"))
    ref = Part.Shape()
    if ref_path.lower().endswith(".brep"):
        ref.read(ref_path)
    else:
        ref = Part.read(ref_path)
    # An open shell from the reader closes into a meaningless solid: no match can be claimed against it
    closed = bool(ref.Shells) and all(sh.isClosed() for sh in ref.Shells)
    ref = rb.as_solid(ref)
    ref = ref.Solids[0] if len(ref.Solids) == 1 else Part.makeCompound(ref.Solids)
    r = ApiRebuilder(tree, ref)
    r.run()
    res = r.finish(out, ref_path)
    res["reference_closed"] = closed
    if not closed:
        res["tree_matches_solidworks"] = False
    json.dump(res, open(rep, "w", encoding="utf-8"), indent=1)
    print("RESULT", out, res["final_mismatch_pct"], res["counts"])


if os.environ.get("SWA_ARGS"):
    main(os.environ["SWA_ARGS"].split("|"))
