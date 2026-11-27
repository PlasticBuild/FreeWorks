
#
# Input: the CADIR JSON that `cadmpeg dump part.sldprt` writes (feature list,
# sketches, parameters) and the part's exact final solid (a .brep from the

# the file leaves open: which way an extrude goes, which plane an unresolved
# mirror uses, and which edges a fillet or chamfer rounds.
#
# Run inside FreeCAD:  SWI_ARGS="IR_JSON|REFERENCE_SHAPE|OUT_FCSTD|REPORT_JSON" freecadcmd rebuild.py

import json
import math
import sys
import time

import FreeCAD as App
import Part
import Sketcher  # noqa: F401  (registers Sketcher types)

V = App.Vector


def vec(d):
    return V(d["x"], d["y"], d["z"])


def frame_placement(fr):
    # Matched against the exact solid: a sketch point (u, v) lies at
    # origin - u * u_axis + v * (normal x u_axis), so the sketch's own z axis
    # is the reverse of the stored normal.
    n = vec(fr["normal"]).normalize()
    u = vec(fr["u_axis"]).normalize()
    v = n.cross(u).normalize()
    rot = App.Rotation(-u, v, -n, "ZXY")
    return App.Placement(vec(fr["origin"]), rot)


class Rebuilder:
    def __init__(self, ir, ref):
        self.ir = ir
        self.m = ir["model"]
        self.ref = ref
        self.ref_vol = abs(ref.Volume) if ref is not None else 0.0
        bb = ref.BoundBox if ref is not None else None
        self.scale = bb.DiagonalLength if bb else 100.0
        for f in self.m["features"]:
            f.setdefault("name", f.get("source_tag") or "Feature")
        self.feat = {f["id"]: f for f in self.m["features"]}
        self.sk_ents = {}
        for e in self.m["sketch_entities"]:
            self.sk_ents.setdefault(e["sketch"], []).append(e)
        self.sketch_def = {s["id"]: s for s in self.m["sketches"]}
        self.made = {}  # cadmpeg feature id -> FreeCAD object
        self.sketch_objs = {}  # cadmpeg sketch id -> FreeCAD sketch
        self.log = []
        self.doc = App.newDocument("SWImport")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.body.Label = "Part"

    # ------------------------------------------------------------------ util
    def note(self, feature, status, **kw):
        row = dict(feature=feature, status=status)
        row.update(kw)
        errs = getattr(self, "variant_errors", None)
        if status == "failed" and errs:
            row.setdefault("variant_errors", errs[:6])
        self.variant_errors = []
        self.log.append(row)

    def tip_shape(self):
        t = self.body.Tip
        if t is None or not hasattr(t, "Shape") or t.Shape.isNull():
            return None
        return t.Shape

    def mismatch(self, shape):
        """Volume of the symmetric difference between shape and the reference."""
        if self.ref is None:
            return 0.0
        if shape is None or shape.isNull() or abs(shape.Volume) < 1e-12:
            return self.ref_vol
        try:
            common = abs(shape.common(self.ref).Volume)
            err = abs(shape.Volume) + self.ref_vol - 2 * common
            return err if err > -1e-6 * max(1.0, self.ref_vol) else float("inf")
        except Exception:
            return float("inf")

    def choice_score(self, shape):
        """How variants are ranked: like mismatch, but material outside the exact solid counts
        double. Judged one feature at a time, the plain mismatch prefers whichever side still
        has material for later features to add; extra material is only undone by a later cut."""
        if self.ref is None:
            return 0.0
        if shape is None or shape.isNull() or abs(shape.Volume) < 1e-12:
            return self.ref_vol
        try:
            common = abs(shape.common(self.ref).Volume)
            extra, missing = abs(shape.Volume) - common, self.ref_vol - common
            # coincident faces leave boolean noise: a solid that holds the whole reference can
            # show "common" a little above the reference volume
            if min(extra, missing) < -1e-3 * max(1.0, self.ref_vol):
                return float("inf")
            return 2 * max(extra, 0.0) + max(missing, 0.0)
        except Exception:
            return float("inf")

    def recompute_ok(self, obj):
        self.doc.recompute()
        st = obj.State
        if "Invalid" in st or "Error" in st:
            return False
        return hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Volume > 1e-12

    def try_variants(self, name, make, variants):
        """make(variant) -> new object in the body. Keep the variant that best matches the reference.

        Each variant is built on the same Tip and removed again (Body.newObject would
        otherwise stack it on the previous variant); the best one is then built for real.
        Why each variant failed is kept in self.variant_errors.
        If every variant fails, nothing is left in the body and the object returned is None."""
        base_tip = self.body.Tip
        self.variant_errors = []
        results = []
        for var in variants:
            before = set(o.Name for o in self.doc.Objects)
            err = score = float("inf")
            try:
                obj = make(var)
                if self.recompute_ok(obj):
                    err = self.mismatch(obj.Shape)
                    score = self.choice_score(obj.Shape)
                else:
                    self.variant_errors.append("%s: %s" % (var, self.status_text(obj)))
            except Exception as exc:
                self.variant_errors.append("%s: %s" % (var, str(exc)[:150]))
            self._drop_new(before, base_tip)
            results.append((score, err, var))
        ok = [r for r in results if r[1] < float("inf")]
        if not ok:
            return None, float("inf"), variants[0] if variants else None
        low = min(r[0] for r in ok)
        _s, err, var = next(r for r in ok if r[0] <= low + 1e-9)  # earliest variant wins a tie
        obj = make(var)
        if self.body.Tip != obj:  # Body.newObject leaves the Tip alone for some features (Mirrored)
            self.body.Tip = obj
        self.recompute_ok(obj)
        return obj, err, var

    def status_text(self, obj):
        msg = []
        try:
            msg.append(obj.getStatusString())
        except Exception:
            pass
        if not hasattr(obj, "Shape") or obj.Shape.isNull():
            msg.append("no shape")
        elif obj.Shape.Volume <= 1e-12:
            msg.append("zero volume")
        return "; ".join(m for m in msg if m and m != "Valid") or "state %s" % (obj.State,)

    def _drop_new(self, before, tip):
        for o in reversed(list(self.doc.Objects)):
            if o.Name not in before:
                try:
                    self.body.removeObject(o)
                except Exception:
                    pass
                self.doc.removeObject(o.Name)
        self.body.Tip = tip
        self.doc.recompute()

    def _remove(self, obj):
        prev = getattr(obj, "BaseFeature", None)
        try:
            self.body.removeObject(obj)
        except Exception:
            pass
        self.doc.removeObject(obj.Name)
        if prev is not None:
            self.body.Tip = prev
        self.doc.recompute()

    # -------------------------------------------------------------- sketches
    def sketch_for_profile(self, prof):
        if prof["kind"] == "feature":
            f = self.feat.get(prof["value"])
            if f is None or f["definition"]["definition"] != "sketch":
                return None
            sid = f["definition"]["sketch"].get("sketch")
            label = f["name"]
        else:
            sid = prof["value"]
            label = None
        return self.make_sketch(sid, label)

    def make_sketch(self, sid, label=None):
        if sid in self.sketch_objs:
            return self.sketch_objs[sid]
        sd = self.sketch_def.get(sid)
        if sd is None or sd.get("placement", {}).get("kind") != "resolved":
            return None
        sk = self.body.newObject("Sketcher::SketchObject", "Sketch")
        sk.Label = label or sd.get("name") or "Sketch"
        sk.MapMode = "Deactivated"
        sk.Placement = frame_placement(sd["placement"]["frame"])
        geos = []
        for e in self.sk_ents.get(sid, []):
            g = self.geometry(e["geometry"])
            if g is not None:
                geos.append((g, bool(e.get("construction"))))
        geos = self.mark_dangling(geos)
        for g, c in geos:
            sk.addGeometry(g, c)
        self.auto_relations(sk)
        self.sketch_objs[sid] = sk
        sk.Visibility = False
        return sk

    @staticmethod
    def mark_dangling(geos, tol=1e-5):
        """Edges with a free end cannot bound a face: keep them, as construction lines."""
        def key(v):
            return (round(v.x / tol), round(v.y / tol))

        def ends(g):
            if isinstance(g, (Part.Circle, Part.Ellipse)):
                return None
            return key(g.StartPoint), key(g.EndPoint)

        live = [i for i, (g, c) in enumerate(geos) if not c]
        while True:
            deg = {}
            for i in live:
                e = ends(geos[i][0])
                if e and e[0] != e[1]:
                    for k in e:
                        deg[k] = deg.get(k, 0) + 1
            keep = [i for i in live if not ends(geos[i][0]) or ends(geos[i][0])[0] == ends(geos[i][0])[1]
                    or (deg[ends(geos[i][0])[0]] > 1 and deg[ends(geos[i][0])[1]] > 1)]
            if len(keep) == len(live):
                break
            live = keep
        live = set(live)
        return [(g, c or i not in live) for i, (g, c) in enumerate(geos)]

    @staticmethod
    def geometry(g):
        k = g["kind"]
        z = V(0, 0, 1)
        try:
            if k == "line":
                a = V(g["start"]["u"], g["start"]["v"], 0)
                b = V(g["end"]["u"], g["end"]["v"], 0)
                if (a - b).Length < 1e-9:
                    return None
                return Part.LineSegment(a, b)
            if k == "circle":
                return Part.Circle(V(g["center"]["u"], g["center"]["v"], 0), z, g["radius"])
            if k == "arc":
                c = Part.Circle(V(g["center"]["u"], g["center"]["v"], 0), z, g["radius"])
                a0, a1 = g["start_angle"], g["end_angle"]
                while a1 <= a0:
                    a1 += 2 * math.pi
                return Part.ArcOfCircle(c, a0, a1)
            if k == "ellipse":
                c = V(g["center"]["u"], g["center"]["v"], 0)
                ang = g["major_angle"]
                ax = V(math.cos(ang), math.sin(ang), 0)
                e = Part.Ellipse(c + ax * g["major_radius"], c + V(-ax.y, ax.x, 0) * g["minor_radius"], c)
                b = g.get("bounds")
                if b:
                    return Part.ArcOfEllipse(e, b[0], b[1])
                return e
            if k == "nurbs":
                cv = g["curve"]
                pts = [V(p["u"], p["v"], 0) for p in cv["poles"]["points"]]
                knots, mults = [], []
                for kv in cv["knots"]:
                    if knots and abs(kv - knots[-1]) < 1e-12:
                        mults[-1] += 1
                    else:
                        knots.append(kv)
                        mults.append(1)
                w = cv["poles"].get("weights")
                bs = Part.BSplineCurve()
                bs.buildFromPolesMultsKnots(pts, mults, knots, False, cv["degree"], w)
                return bs
        except Exception:
            return None
        return None

    @staticmethod
    def auto_relations(sk):
        ""
        tol = 1e-6
        pts = []
        for i, g in enumerate(sk.Geometry):
            if isinstance(g, (Part.LineSegment, Part.ArcOfCircle, Part.ArcOfEllipse, Part.BSplineCurve)):
                pts.append((i, 1, g.StartPoint))
                pts.append((i, 2, g.EndPoint))
        cons = []
        used = set()
        for a in range(len(pts)):
            for b in range(a + 1, len(pts)):
                ia, pa, va = pts[a]
                ib, pb, vb = pts[b]
                if ia != ib and (va - vb).Length < tol and (ib, pb) not in used:
                    cons.append(Sketcher.Constraint("Coincident", ia, pa, ib, pb))
                    used.add((ib, pb))
                    break
        for i, g in enumerate(sk.Geometry):
            if isinstance(g, Part.LineSegment):
                d = g.EndPoint - g.StartPoint
                if abs(d.y) < tol * max(1.0, d.Length):
                    cons.append(Sketcher.Constraint("Horizontal", i))
                elif abs(d.x) < tol * max(1.0, d.Length):
                    cons.append(Sketcher.Constraint("Vertical", i))
        if cons:
            sk.addConstraint(cons)

    # -------------------------------------------------------------- features
    def run(self):
        order = sorted(self.m["features"], key=lambda f: f.get("ordinal", 0))
        for f in order:
            if f.get("suppressed"):
                self.note(f["name"], "skipped (suppressed in the file)")
                continue
            kind = f["definition"]["definition"]
            fn = getattr(self, "f_" + kind, None)
            if fn is None:
                if kind not in ("tree_node", "sketch", "datum_principal_plane"):
                    self.note(f["name"], "not rebuilt", kind=kind)
                continue
            t0 = time.time()
            try:
                fn(f)
            except Exception as exc:  # keep going: one feature must not stop the tree
                self.note(f["name"], "failed", kind=kind, error=str(exc)[:200])
            self.log[-1:] and self.log[-1].setdefault("seconds", round(time.time() - t0, 2))

    def f_datum_plane(self, f):
        p = self.body.newObject("PartDesign::Plane", "Plane")
        p.Label = f["name"]
        p.MapMode = "Deactivated"
        p.Placement = frame_placement(f["definition"]["frame"])
        p.Visibility = False
        self.made[f["id"]] = p
        self.note(f["name"], "rebuilt", kind="plane")

    def f_datum_offset_plane(self, f):
        d = f["definition"]
        ref = d["reference"]
        if ref.get("reference") == "resolved_plane":
            base = frame_placement(ref["frame"])
        else:
            rf = self.feat.get(ref.get("feature"))
            base = self.principal(rf) if rf else None
            if base is None and ref.get("feature") in self.made:
                base = self.made[ref["feature"]].Placement
        if base is None:
            self.note(f["name"], "not rebuilt", kind="plane", error="reference plane unresolved")
            return
        p = self.body.newObject("PartDesign::Plane", "Plane")
        p.Label = f["name"]
        p.MapMode = "Deactivated"
        n = base.Rotation.multVec(V(0, 0, 1))
        p.Placement = App.Placement(base.Base + n * d["distance"], base.Rotation)
        p.Visibility = False
        self.made[f["id"]] = p
        self.note(f["name"], "rebuilt", kind="plane")

    @staticmethod
    def principal(f):
        if f is None or f["definition"]["definition"] != "datum_principal_plane":
            return None
        nm = f["name"].lower()
        if "front" in nm:
            return App.Placement()
        if "top" in nm:
            return App.Placement(V(), App.Rotation(V(1, 0, 0), V(0, 0, -1), V(0, 1, 0), "ZXY"))
        if "right" in nm:
            return App.Placement(V(), App.Rotation(V(0, 0, -1), V(0, 1, 0), V(1, 0, 0), "ZXY"))
        return None

    def f_extrude(self, f):
        d = f["definition"]
        sk = self.sketch_for_profile(d["profile"])
        if sk is None:
            self.note(f["name"], "not rebuilt", kind="extrude", error="profile sketch unresolved")
            return
        cut = d.get("op") == "cut"
        ext = d["extent"]
        side = ext.get("side") or ext.get("first") or {}
        term = side.get("termination", {})
        tk = term.get("kind")
        big = self.scale * 2.0

        def make(var):
            rev, mode = var
            o = self.body.newObject("PartDesign::Pocket" if cut else "PartDesign::Pad", "Feature")
            o.Profile = sk
            o.Label = f["name"]
            o.Reversed = rev
            if mode == "through":
                if cut:
                    o.Type = "ThroughAll"
                else:
                    o.Length = big
            elif mode == "length":
                o.Length = term["length"]
            elif isinstance(mode, float):
                o.Length = mode
            if ext["kind"] in ("symmetric", "two_sided"):
                o.Midplane = True
                if mode == "length":
                    o.Length = term["length"]
            o.Refine = True
            return o

        if tk == "blind":
            modes = ["length"]
        elif tk in ("through_all",):
            modes = ["through"]
        else:
            # up to next / up to face: choose a length from the reference box
            modes = self.reach_lengths(sk)
        variants = [(r, m) for m in modes for r in ((False,) if ext["kind"] in ("symmetric", "two_sided") else (False, True))]
        obj, err, var = self.try_variants(f["name"], make, variants)
        if obj is not None:
            self.made[f["id"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="cut" if cut else "boss",
                  end=tk, reversed=var[0], mismatch=self.pct(err))

    def reach_lengths(self, sk):
        """Candidate lengths for 'up to face/next': distances from the sketch plane to reference faces."""
        n = sk.Placement.Rotation.multVec(V(0, 0, 1))
        o = sk.Placement.Base
        ds = set()
        for fc in self.ref.Faces:
            try:
                if fc.Surface.TypeId != "Part::GeomPlane":
                    continue
                nn = fc.normalAt(0, 0)
                if abs(abs(nn.dot(n)) - 1) > 1e-6:
                    continue
                dist = abs((fc.Vertexes[0].Point - o).dot(n))
                if dist > 1e-6:
                    ds.add(round(dist, 6))
            except Exception:
                pass
        return sorted(ds)[:12] or [self.scale]

    def f_revolve(self, f):
        d = f["definition"]
        c = d.get("construction", d)
        sk = self.sketch_for_profile(c["profile"])
        if sk is None or c.get("state") != "resolved":
            self.note(f["name"], "not rebuilt", kind="revolve", error="profile or axis unresolved")
            return
        inv = sk.Placement.inverse()
        p = inv.multVec(vec(c["axis"]["origin"]))
        dirv = inv.Rotation.multVec(vec(c["axis"]["direction"]))
        L = self.scale
        n_constr = sum(1 for i, g in enumerate(sk.Geometry) if isinstance(g, Part.LineSegment) and sk.getConstruction(i))
        sk.addGeometry(Part.LineSegment(V(p.x, p.y, 0) - V(dirv.x, dirv.y, 0) * L, V(p.x, p.y, 0) + V(dirv.x, dirv.y, 0) * L), True)
        angle = math.degrees(c["extent"]["termination"].get("angle", 2 * math.pi))
        cut = d.get("op") == "cut"

        def make(rev):
            o = self.body.newObject("PartDesign::Groove" if cut else "PartDesign::Revolution", "Feature")
            o.Label = f["name"]
            o.Profile = sk
            o.ReferenceAxis = (sk, ["Axis%d" % n_constr])
            o.Angle = min(angle, 360.0)
            o.Reversed = rev
            o.Refine = True
            return o

        obj, err, var = self.try_variants(f["name"], make, (False, True) if angle < 359.99 else (False,))
        if obj is not None:
            self.made[f["id"]] = obj
        self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="revolve", mismatch=self.pct(err))

    def f_pattern(self, f):
        d = f["definition"]
        pat = d["pattern"]
        seeds = [self.made.get(s["value"]) for s in d.get("seeds", [])]
        seeds = [s for s in seeds if s is not None]
        if not seeds:
            self.note(f["name"], "not rebuilt", kind="pattern", error="seed feature not rebuilt")
            return
        kind = pat.get("kind")
        if kind == "unresolved" and pat.get("form") == "mirror":
            planes = [(V(0, 0, 0), V(0, 0, 1)), (V(0, 0, 0), V(0, 1, 0)), (V(0, 0, 0), V(1, 0, 0))]
        elif kind == "mirror":
            planes = [(vec(pat["plane_origin"]), vec(pat["plane_normal"]))]
        else:
            planes = None
        if planes is not None:
            def make(pl):
                o, n = pl
                dp = self.body.newObject("PartDesign::Plane", "MirrorPlane")
                dp.MapMode = "Deactivated"
                dp.Placement = App.Placement(o, App.Rotation(V(0, 0, 1), n))
                dp.Visibility = False
                m = self.body.newObject("PartDesign::Mirrored", "Feature")
                m.Label = f["name"]
                m.Originals = seeds
                m.MirrorPlane = (dp, [""])
                m.Refine = True
                return m
            obj, err, var = self.try_variants(f["name"], make, planes)
            self.cleanup_datums()
            if obj is not None:
                self.made[f["id"]] = obj
            self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="mirror", mismatch=self.pct(err))
            return
        if kind == "linear":
            dirv = vec(pat["direction"])

            def make(sign):
                ln = self.body.newObject("PartDesign::Line", "PatternDirection")
                ln.MapMode = "Deactivated"
                ln.Placement = App.Placement(V(), App.Rotation(V(0, 0, 1), dirv * sign))
                ln.Visibility = False
                m = self.body.newObject("PartDesign::LinearPattern", "Feature")
                m.Label = f["name"]
                m.Originals = seeds
                m.Direction = (ln, [""])
                m.Length = pat["spacing"] * (pat["count"] - 1)
                m.Occurrences = pat["count"]
                m.Refine = True
                return m
            obj, err, var = self.try_variants(f["name"], make, (1, -1))
            self.cleanup_datums()
            if obj is not None:
                self.made[f["id"]] = obj
            self.note(f["name"], "rebuilt" if err < float("inf") else "failed", kind="linear pattern", mismatch=self.pct(err))
            return
        self.note(f["name"], "not rebuilt", kind="pattern " + str(kind))

    def cleanup_datums(self):
        """Remove helper datums whose feature was discarded."""
        used = set()
        for o in self.body.Group:
            for prop in ("MirrorPlane", "Direction"):
                v = getattr(o, prop, None)
                if isinstance(v, tuple) and v and hasattr(v[0], "Name"):
                    used.add(v[0].Name)
        for o in list(self.body.Group):
            if o.Label.startswith(("MirrorPlane", "PatternDirection")) and o.Name not in used:
                self.body.removeObject(o)
                self.doc.removeObject(o.Name)

    def dressup_edges(self, size, kind):
        ""
        shape = self.tip_shape()
        if shape is None:
            return []
        lo, hi = 0.15 * size, 1.25 * size
        out = []
        shell = self.ref.Shells[0] if len(self.ref.Shells) == 1 else Part.Compound(self.ref.Shells)
        for i, e in enumerate(shape.Edges):
            ok = True
            for t in (0.25, 0.5, 0.75):
                p = e.valueAt(e.FirstParameter + t * (e.LastParameter - e.FirstParameter))
                dist = shell.distToShape(Part.Vertex(p))[0]
                if not (lo <= dist <= hi):
                    ok = False
                    break
            if ok:
                out.append("Edge%d" % (i + 1))
        return out

    def f_fillet(self, f):
        g = f["definition"]["groups"][0]
        r = g.get("radius", {})
        if r.get("kind") != "constant":
            self.note(f["name"], "not rebuilt", kind="fillet", error="variable radius")
            return
        self._dressup(f, "PartDesign::Fillet", r["radius"], lambda o: setattr(o, "Radius", r["radius"]))

    def f_chamfer(self, f):
        g = f["definition"]["groups"][0]
        s = g.get("spec", {})
        dist = s.get("distance")
        if dist is None:
            self.note(f["name"], "not rebuilt", kind="chamfer", error="size unresolved")
            return

        def setup(o):
            if s.get("kind") == "distance_angle":
                o.ChamferType = "Distance and Angle"
                o.Size = dist
                o.Angle = math.degrees(s.get("angle", math.pi / 4))
            else:
                o.Size = dist
        self._dressup(f, "PartDesign::Chamfer", dist, setup)

    def _dressup(self, f, tid, size, setup):
        base = self.body.Tip
        edges = self.dressup_edges(size, tid)
        if not edges or base is None:
            self.note(f["name"], "not rebuilt", kind=tid.split("::")[1].lower(), error="no matching edges found")
            return
        before = self.mismatch(self.tip_shape())
        o = self.body.newObject(tid, "Feature")
        o.Label = f["name"]
        o.Base = (base, edges)
        setup(o)
        o.Refine = True
        if not self.recompute_ok(o):
            self._remove(o)
            self.note(f["name"], "failed", kind=tid.split("::")[1].lower(), edges=len(edges))
            return
        err = self.mismatch(o.Shape)
        if err > before + 1e-6:
            self._remove(o)
            self.note(f["name"], "failed", kind=tid.split("::")[1].lower(), error="made the shape worse", edges=len(edges))
            return
        self.made[f["id"]] = o
        want = len(f["definition"]["groups"][0].get("edges", {}).get("value", {}).get("edges", []))
        self.note(f["name"], "rebuilt", kind=tid.split("::")[1].lower(), edges=len(edges), solidworks_edge_refs=want, mismatch=self.pct(err))

    def f_shell(self, f):
        self.note(f["name"], "not rebuilt", kind="shell", error="removed faces unresolved in the file reader")

    def pct(self, err):
        if err == float("inf") or not self.ref_vol:
            return None
        return round(100.0 * err / self.ref_vol, 3)

    # ---------------------------------------------------------------- finish
    def finish(self, out, ref_path):
        final = self.tip_shape()
        err = self.mismatch(final)
        refobj = self.doc.addObject("Part::Feature", "SolidWorksGeometry")
        refobj.Label = "SolidWorks geometry (exact)"
        refobj.Shape = self.ref
        good = err <= 0.005 * self.ref_vol
        refobj.Visibility = not good
        self.body.Visibility = good
        self.doc.recompute()
        self.doc.saveAs(out)
        counts = {}
        for r in self.log:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return dict(final_mismatch_pct=self.pct(err), tree_matches_solidworks=good,
                    reference_volume=round(self.ref_vol, 3),
                    rebuilt_volume=round(final.Volume, 3) if final else 0, counts=counts, features=self.log)


def as_solid(shape):
    """The plugin sometimes gives closed shells instead of solids; close them."""
    if shape.Solids:
        return shape
    out = []
    for sh in shape.Shells:
        try:
            so = Part.Solid(sh)
            if so.Volume < 0:
                so.reverse()
            out.append(so)
        except Exception:
            pass
    return Part.makeCompound(out) if out else shape


def main(argv):
    ir_path, ref_path, out, rep = argv[:4]
    ir = json.load(open(ir_path, encoding="utf-8"))
    ref = Part.Shape()
    if ref_path.lower().endswith(".brep"):
        ref.read(ref_path)
    else:
        ref = Part.read(ref_path)
    ref = as_solid(ref)
    solids = ref.Solids
    if solids:
        ref = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
    rb = Rebuilder(ir, ref)
    rb.run()
    res = rb.finish(out, ref_path)
    json.dump(res, open(rep, "w", encoding="utf-8"), indent=1)
    print("RESULT", out, res["final_mismatch_pct"], res["counts"])


import os
if os.environ.get("SWI_ARGS"):
    main(os.environ["SWI_ARGS"].split("|"))
