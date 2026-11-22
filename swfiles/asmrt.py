# SPDX-License-Identifier: LGPL-2.1-or-later
""

















import json
import math
import os
import shutil
import tempfile

import FreeCAD as App

from . import doc_name, msg, params, swapp, tell, warn

V = App.Vector


def available():
    return swapp.use_solidworks() and params().GetBool("AssemblyTree", True)


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _placement(m):
    mat = App.Matrix(*[x for row in m for x in row])
    return App.Placement(mat)


def _label(sw_name):
    base, _, n = sw_name.rpartition("-")
    return "%s<%s>" % (base, n) if base and n.isdigit() else sw_name


# =================================================================== open
class Opener:
    def __init__(self, res, read_tree_api):
        self.trees = res["assemblies"]
        self.read_tree_api = read_tree_api
        self.notes = list(res.get("errors", []))
        self.built = {}             # path key -> assembly object
        self.links_of = {}
        self.parts_of = {}          # document Name -> (Parts folder, {part file: body})
        self.top_doc = None
        self.counts = {"components": 0, "mates": 0, "mates_made": 0, "patterns": 0, "folders": 0,
                       "features": 0, "subassemblies": 0}

    def build(self, path, doc=None, top=True):
        ""



        from . import assembly
        key = _key(path)
        if key in self.built:
            return self.built[key]
        tree = self.trees.get(key) or next((t for k, t in self.trees.items() if k == key.lower()), None)
        if tree is None:
            raise RuntimeError("SolidWorks gave no tree for %s" % os.path.basename(path))
        base = os.path.splitext(os.path.basename(path))[0]
        if top:
            if doc is None:
                doc = App.newDocument(doc_name(base))
            doc.Label = base
            self.top_doc = doc
        else:
            doc = App.newDocument(doc_name(base), base, True, False)
            doc.Label = base
        self._hold(doc, top)
        asm = assembly._make_assembly(doc, base)
        parts = doc.addObject("App::DocumentObjectGroup", "Parts")
        parts.Label = "Parts"
        self.parts_of[doc.Name] = (parts, {})
        self.built[key] = asm
        links = {}
        self.links_of[self._asm_key(asm)] = links
        for c in tree["components"]:
            try:
                link = self.component(asm, c)
            except Exception as exc:
                self.notes.append("%s: %s" % (c["name"], exc))
                continue
            links[c["name"]] = link
        doc.recompute()
        from swstyle import asmcore
        fixed = [c for c in tree["components"] if c.get("fixed") and c["name"] in links]
        for c in fixed or tree["components"][:1]:
            if c["name"] in links:
                asmcore.fix(asm, links[c["name"]])
        self.patterns(asm, tree, links)
        joints = self.mates(asm, tree, links)
        self.folders(asm, tree, links, joints)
        self.features(asm, tree, links)
        for c in tree["components"]:
            if c.get("suppressed") and c["name"] in links:
                try:
                    from swstyle import asmcomp
                    asmcomp.suppress(links[c["name"]], True)
                except Exception as exc:
                    self.notes.append("%s: not suppressed (%s)" % (c["name"], exc))
        if not top:
            self._save(doc)
        if top:
            meta = dict(doc.Meta)
            meta.update({"FreeWorksSource": os.path.abspath(path), "FreeWorksSourceKind": "sldasm"})
            doc.Meta = meta
        doc.recompute()
        return asm

    def component(self, asm, c):
        from . import assembly
        doc = asm.Document
        if c["kind"] == "asm":
            sub = self.build(c["file"], top=False)
            link = asm.newObject("Assembly::AssemblyLink", "Component")
            link.LinkedObject = sub
            link.Rigid = not c.get("flexible")
            self.counts["subassemblies"] += 1
        else:
            parts, bodies = self.parts_of[doc.Name]
            body = bodies.get(_key(c["file"]))
            if body is None:
                body, _how = assembly._part_body(doc, c["file"], self.read_tree_api)
                parts.addObject(body)
                body.Visibility = False
                bodies[_key(c["file"])] = body
            link = asm.newObject("App::Link", "Component")
            link.LinkedObject = body
        link.Label = _label(c["name"])
        link.Placement = _placement(c["matrix"])
        if c.get("hidden"):
            link.Visibility = False
        self.counts["components"] += 1
        return link

    def _hold(self, doc, top):
        try:
            from swstyle import asmpm
            asmpm.hold(doc)
            if not top:
                asmpm.hold_with(self.top_doc, doc)
            return
        except Exception as exc:
            App.Console.PrintLog("FreeCAD files: holding file not made by asmpm (%s)\n" % exc)
        import tempfile as _t
        folder = os.path.join(_t.gettempdir(), "FreeWorks-open")
        os.makedirs(folder, exist_ok=True)
        doc.saveAs(os.path.join(folder, "%s-%s.FCStd" % (doc.Label, doc.Name)))

    @staticmethod
    def _asm_key(asm):
        return "%s#%s" % (asm.Document.Name, asm.Name) if asm is not None else ""

    @staticmethod
    def _save(doc):
        try:
            doc.save()
        except Exception as exc:
            App.Console.PrintLog("FreeCAD files: %s not saved to its holding file (%s)\n" % (doc.Label, exc))

    def resolve(self, links, name):
        ""


        import Part
        parts = str(name).split("/")
        top = links.get(parts[0])
        if top is None:
            return None
        holder, prefix = top, ""
        for seg in parts[1:]:
            sub = getattr(holder, "LinkedObject", None)
            mine = self.links_of.get(self._asm_key(sub), {})
            target = mine.get(seg)
            if target is None:
                return None
            kids = [o for o in (getattr(holder, "Group", None) or []) if o.TypeId in ("App::Link", "Assembly::AssemblyLink")]
            inner = next((o for o in kids if getattr(o, "LinkedObject", None) is target or
                          (target.TypeId == "Assembly::AssemblyLink" and getattr(o, "LinkedObject", None) is target.LinkedObject)),
                         None)
            if inner is None:                   # by order, as FreeCAD copies them
                order = list(mine.values())
                if target in order and len(kids) == len(order):
                    inner = kids[order.index(target)]
            if inner is None:
                return None
            prefix += inner.Name + "."
            holder = inner
        shape = Part.getShape(top, prefix, needSubElement=False, transform=True)
        return top, prefix, shape

    # ---------------------------------------------------------------- component patterns
    def patterns(self, asm, tree, links):
        from swstyle import asmcpattern
        claimed = set()
        files = {c["name"]: _key(c["file"]) for c in tree["components"]}
        flagged = {c["name"] for c in tree["components"] if c.get("instance")}
        for p in tree.get("patterns", []):
            try:
                seeds = [links[n] for n in p.get("seeds", []) if n in links]
                if not seeds:
                    self.notes.append("%s: its seed components were not found" % p["name"])
                    continue
                entries, values = self._pattern_entries(p, seeds, links, files, flagged, claimed)
                if not entries:
                    self.notes.append("%s: its instances were not found" % p["name"])
                    continue
                feat = asmcpattern.make_feature(asm, p["kind"], entries, values)
                feat.Label = p["name"]
                self.counts["patterns"] += 1
            except Exception as exc:
                self.notes.append("%s: %s" % (p["name"], exc))

    def _pattern_entries(self, p, seeds, links, files, flagged, claimed):
        by_link = {v: k for k, v in links.items()}
        entries = []
        values = {"seeds": [s.Name for s in seeds], "skip": []}
        named = [links[n] for n in p.get("instances", []) if n in links and links[n] not in seeds]
        for seed in seeds:
            sname = by_link[seed]
            pool = [l for n, l in links.items() if files.get(n) == files.get(sname) and l not in seeds
                    and n not in claimed and (not flagged or n in flagged)]
            if named:
                pool = [l for l in named if files.get(by_link[l]) == files.get(sname)]
            found = []
            if p["kind"] == "linear":
                n1 = int(p.get("D1TotalInstances", 0) or (len(pool) + 1))
                s1 = float(p.get("D1Spacing", 0.0)) * 1000.0
                found, d1 = _linear(seed, pool, n1, s1, named)
                values.update(d1=list(d1), s1=s1, n1=n1, d2=[0, 0, 0], s2=0.0, n2=1, seed_only=False)
            elif p["kind"] == "circular":
                n = int(p.get("TotalInstances", 0) or (len(pool) + 1))
                step = math.degrees(float(p.get("Spacing", 0.0))) if p.get("Spacing") else None
                found, axis, point, step = _circular(seed, pool, n, step, named)
                values.update(axis=list(axis), axis_point=list(point), axis_label="", reverse=False,
                              angle=step, count=n, equal=False, symmetric=False, angle2=0.0, count2=1, equal2=False)
            else:
                found = [(i + 2, l) for i, l in enumerate(pool)] if named else []
            for idx, l in found:
                claimed.add(by_link[l])
                entries.append((seed, "(%d)" % idx, l, None))
        return entries, values

    # ---------------------------------------------------------------- mates
    def mates(self, asm, tree, links):
        from swstyle import asmcore
        from . import mates as matesmod
        joints = {}
        rows = list(tree.get("mates", []))
        later = []
        for row in rows:
            self.counts["mates"] += 1
            kind = row["type"]
            limit = kind in ("DISTANCE", "ANGLE") and _limits(row) is not None
            if limit or kind in ("SYMMETRIC", "WIDTH", "GEAR", "RACKPINION", "SCREW", "HINGE"):
                later.append(row)
                continue
            before = set(o.Name for o in asmcore.joint_group(asm).Group)
            try:
                why = self.standard(asmcore, asm, links, row)
            except Exception as exc:
                why = "error: %s" % exc
            if why is None:
                self._named(asm, before, row, joints)
            else:
                self.notes.append("%s: %s" % (row["name"], why))
        for row in later:               # the mates a limit or a mechanical mate rides on come first
            before = set(o.Name for o in asmcore.joint_group(asm).Group)
            try:
                why = self.advanced(asmcore, asm, links, row)
            except Exception as exc:
                why = "error: %s" % exc
            if why is None:
                self._named(asm, before, row, joints)
            else:
                self.notes.append("%s: %s" % (row["name"], why))
        if later or rows:
            asmcore.solve(asm)
        return joints

    def _named(self, asm, before, row, joints):
        from swstyle import asmcore
        new = [o for o in asmcore.joint_group(asm).Group if o.Name not in before
               and not getattr(o, asmcore.PART_OF_PROP, "")]
        if new:
            new[0].Label = row["name"]
            joints[row["name"]] = new[0]
            self.counts["mates_made"] += 1
            if row.get("suppressed"):
                try:
                    from swstyle import asmmenu
                    asmmenu.suppress(new[0], True)
                except Exception:
                    pass

    def _refs(self, links, row, kind=None):
        from . import mates as matesmod
        out = []
        for e in row["entities"]:
            got = self.resolve(links, e["component"]) if e.get("component") else None
            if got is None:
                return None, "component %s is not in the assembly" % e.get("component")
            comp, prefix, shape = got
            sub = "Face1" if kind == "Lock" else matesmod.find(shape, e)
            if sub is None:
                return None, "its %s on %s was not found" % (e["ref"].lower(), e["component"])
            out.append((comp, prefix + sub))
        return out, None

    def standard(self, ac, asm, links, row):
        """mates.make with components inside subassemblies found too."""
        from . import mates as matesmod
        kind = matesmod.KINDS.get(row["type"])
        if kind is None:
            return "%s mates are not made in FreeCAD yet" % row["type"].title()
        ents = row["entities"][:2]
        if len(ents) != 2:
            return "SolidWorks gave %d sides for it" % len(ents)
        refs, why = self._refs(links, dict(row, entities=ents), kind)
        if refs is None:
            return why
        if refs[0][0] is refs[1][0]:
            return "both sides are on %s" % refs[0][0].Label
        a, b = ents
        value = None
        if kind == "Distance":
            if row.get("value") is not None:
                value = row["value"] * 1000.0
            else:
                n = V(*a["dir"])
                value = abs((V(*b["point"]) - V(*a["point"])).dot(n.normalize())) if n.Length else 0.0
        elif kind == "Angle":
            value = math.degrees(row["value"]) if row.get("value") is not None else \
                math.degrees(V(*a["dir"]).getAngle(V(*b["dir"])))
        before = {c: App.Placement(c.Placement) for c in ac.components(asm)}
        joint = ac.add_mate(asm, kind, refs[0], refs[1], value=value)
        if not matesmod._moved(before):
            return None
        for flip in (False, True):
            matesmod._restore(asm, before)
            if flip:
                joint.Proxy.flipOnePart(joint)
                matesmod._restore(asm, before)
            if ac.solve(asm) and not matesmod._moved(before) and ac.satisfied(joint):
                return None
        asm.Document.removeObject(joint.Name)
        matesmod._restore(asm, before)
        return "FreeCAD would move a component to make it"

    def advanced(self, ac, asm, links, row):
        refs, why = self._refs(links, row)
        if refs is None:
            return why
        kind, d = row["type"], row.get("data", {})
        ents = row["entities"]
        if kind in ("DISTANCE", "ANGLE"):
            low, high = _limits(row)
            joint, why = ac.make_limit(asm, "Distance Range" if kind == "DISTANCE" else "Angle Range", refs[:2], low, high)
            return None if joint is not None else why
        if kind == "SYMMETRIC":
            if len(refs) < 3:
                return "SolidWorks gave %d sides for it" % len(refs)
            k = _symmetry_plane(ents)
            plane = refs[k]
            others = [r for i, r in enumerate(refs[:3]) if i != k]
            ac.make_symmetric(asm, plane, others)
            return None
        if kind == "WIDTH":
            if len(refs) < 4:
                return "SolidWorks gave %d sides for it" % len(refs)
            width, tab = _width_pairs(ents, refs)
            ac.make_width(asm, width, tab, mode="centered")
            return None
        rev = bool(d.get("Reverse"))
        if kind == "GEAR":
            num = float(d.get("GearRatioNumerator", 0) or 0) * 1000.0
            den = float(d.get("GearRatioDenominator", 0) or 0) * 1000.0
            if num <= 0 or den <= 0:
                num, den = (2 * ents[0].get("radius", 1.0) or 1.0), (2 * ents[1].get("radius", 1.0) or 1.0)
            ac.add_mate(asm, "Gear", refs[0], refs[1], value=(num, den, rev))
            return None
        if kind == "RACKPINION":
            dia = float(d.get("PinionPitchDiameter", 0) or 0) * 1000.0
            if dia <= 0 and d.get("RackTravelPerRevolution"):
                dia = float(d["RackTravelPerRevolution"]) * 1000.0 / math.pi
            ac.add_mate(asm, "Rack Pinion", refs[0], refs[1], value=("diameter", dia or 10.0, rev))
            return None
        if kind == "SCREW":
            dist = float(d.get("DistancePerRevolution", 0) or d.get("Distance", 0) or 0) * 1000.0
            if dist <= 0 and d.get("RevolutionsPerLength"):
                dist = 1.0 / (float(d["RevolutionsPerLength"]) / 1000.0)
            ac.add_mate(asm, "Screw", refs[0], refs[1], value=("distance", dist or 1.0, rev))
            return None
        if kind == "HINGE":
            ac.add_mate(asm, "Hinge", refs[0], refs[1])
            return None
        return "%s mates are not made in FreeCAD yet" % kind.title()

    # ---------------------------------------------------------------- folders
    def folders(self, asm, tree, links, joints):
        from swstyle import asmfolder
        for f in tree.get("mate_folders", []):
            mates = [joints[n] for n in f.get("features", []) if n in joints]
            if mates:
                folder = asmfolder.make_folder(asm, mates)
                folder.Label = f["name"]
                self.counts["folders"] += 1
        for f in tree.get("comp_folders", []):
            comps = [links[n] for n in (f.get("components") or f.get("features", [])) if n in links]
            if not comps and (f.get("features") or f.get("components")):
                continue                # a folder of other features, not of components
            folder = asmfolder.make_component_folder(asm, comps)
            folder.Label = f["name"]
            self.counts["folders"] += 1

    # ---------------------------------------------------------------- assembly cuts
    def features(self, asm, tree, links):
        for f in tree.get("features", []):
            try:
                why = self.cut(asm, tree, links, f)
            except Exception as exc:
                why = "error: %s" % exc
            if why:
                self.notes.append("%s: %s" % (f["name"], why))
            else:
                self.counts["features"] += 1

    def cut(self, asm, tree, links, f):
        from swstyle import asmfeature
        if f.get("kind") != "extrude" or not f.get("sketches"):
            return "%s assembly features are not made in FreeCAD yet" % f.get("type")
        sk = _sketch(asm, f["sketches"][0])
        end = {"blind": "Blind", "through_all": "Through All", "through_all_both": "Through All",
               "up_to_next": "Up To Next", "mid_plane": "Mid Plane"}.get(f.get("end"), None)
        if end is None:
            return "end condition %s is not made yet" % f.get("end")
        scope = [links[n] for n in f.get("scope", []) if n in links]
        auto = f.get("auto_select", True) or not scope
        want = tree.get("volume")
        best = None
        for rev in (bool(f.get("reverse")), not f.get("reverse")):
            feat = asmfeature.make(asm, "Extrude", sk, end=end, depth=float(f.get("depth", 10.0)),
                                   reversed_=rev, auto=auto, scope=scope)
            feat.Label = f["name"]
            got = _volume(asm)
            if want is None or abs(got - want) <= max(1e-2, 1e-4 * want):
                return None
            if best is None:
                best = got
            asmfeature_delete(asm, feat)
        return "its cut does not take away what SolidWorks' does (FreeCAD %.1f mm3, SolidWorks %.1f mm3)" % (best or 0, want)


def asmfeature_delete(asm, feat):
    try:
        feat.Document.removeObject(feat.Name)
    finally:
        asm.Document.recompute()


def _volume(asm):
    import Part
    from swstyle import asmcore
    total = 0.0
    for c in asmcore.components(asm):
        try:
            from swstyle import asmcomp
            if asmcomp.is_suppressed(c):
                continue
        except Exception:
            pass
        try:
            total += Part.getShape(c, "", needSubElement=False, transform=True).Volume
        except Exception:
            pass
    return total


def _sketch(asm, s):
    ""
    import Part
    import Sketcher
    sk = asm.Document.addObject("Sketcher::SketchObject", "Sketch")
    sk.Label = s.get("name", "Sketch")
    asm.addObject(sk)
    t = s.get("to_model")
    if t:
        a = t["rotation"]
        mat = App.Matrix(a[0], a[3], a[6], t["origin"][0], a[1], a[4], a[7], t["origin"][1],
                         a[2], a[5], a[8], t["origin"][2], 0, 0, 0, 1)
        sk.Placement = App.Placement(mat)
    for g in s.get("segments", []):
        try:
            k = g["kind"]
            if k == "line":
                geo = Part.LineSegment(V(*g["start"][:2], 0), V(*g["end"][:2], 0))
            elif k == "arc" and g.get("full_circle"):
                geo = Part.Circle(V(*g["center"][:2], 0), V(0, 0, 1), g["radius"])
            elif k == "arc":
                c, a, b = V(*g["center"][:2], 0), V(*g["start"][:2], 0), V(*g["end"][:2], 0)
                if g.get("direction", 1) < 0:
                    a, b = b, a
                circle = Part.Circle(c, V(0, 0, 1), g["radius"])
                geo = Part.ArcOfCircle(circle, circle.parameter(a), circle.parameter(b))
            else:
                continue
            sk.addGeometry(geo, bool(g.get("construction")))
        except Exception as exc:
            warn("sketch %s: segment not made (%s)" % (sk.Label, exc))
    asm.Document.recompute()
    return sk


def _limits(row):
    d = row.get("data", {})
    if d.get("MaximumDistance") is not None and d.get("MinimumDistance") is not None and \
            abs(d["MaximumDistance"] - d["MinimumDistance"]) > 1e-12:
        return d["MinimumDistance"] * 1000.0, d["MaximumDistance"] * 1000.0
    if d.get("MaximumAngle") is not None and d.get("MinimumAngle") is not None and \
            abs(d["MaximumAngle"] - d["MinimumAngle"]) > 1e-12:
        return math.degrees(d["MinimumAngle"]), math.degrees(d["MaximumAngle"])
    hi, lo = row.get("MaximumVariation"), row.get("MinimumVariation")
    if hi is None or lo is None or abs(hi) + abs(lo) < 1e-12:
        return None
    unit = (lambda x: x * 1000.0) if row["type"] == "DISTANCE" else math.degrees
    now = row.get("value") or 0.0
    if hi >= now >= lo:                     # absolute limits
        return unit(lo), unit(hi)
    return unit(now - abs(lo)), unit(now + abs(hi))


def _symmetry_plane(ents):
    """Which of the three sides is the symmetry plane: the plane the other two mirror about."""
    for k in (2, 0, 1):
        e = ents[k]
        if e["ref"] != "Plane":
            continue
        n, p = V(*e["dir"]), V(*e["point"])
        if n.Length < 1e-12:
            continue
        n.normalize()
        a, b = [V(*ents[i]["point"]) for i in range(3) if i != k]
        if abs((a - p).dot(n) + (b - p).dot(n)) < 1e-3:
            return k
    return 2


def _width_pairs(ents, refs):
    """(width picks, tab picks): the outer two planes along their normal, then the inner two."""
    n = V(*ents[0]["dir"])
    if n.Length < 1e-12:
        return refs[:2], refs[2:4]
    n.normalize()
    at = sorted(range(4), key=lambda i: V(*ents[i]["point"]).dot(n))
    outer = [at[0], at[3]]
    inner = [at[1], at[2]]
    if sorted(outer) == [0, 1] or sorted(inner) == [2, 3]:
        return refs[:2], refs[2:4]
    return [refs[i] for i in outer], [refs[i] for i in inner]


def _linear(seed, pool, n1, s1, named):
    """[(index, link)] of seed's instances along one direction, and the direction."""
    rot = seed.Placement.Rotation
    cands = [l for l in pool if l.Placement.Rotation.isSame(rot, 1e-6)]
    deltas = [(l, l.Placement.Base - seed.Placement.Base) for l in cands]
    deltas = [(l, d) for l, d in deltas if d.Length > 1e-6]
    if not deltas:
        return [], V(1, 0, 0)
    if s1 <= 0:
        s1 = min(d.Length for _l, d in deltas)
    first = min(deltas, key=lambda x: abs(x[1].Length - s1))
    d1 = V(first[1]).normalize()
    out = []
    for l, d in deltas:
        k = d.dot(d1) / s1
        if (d - d1 * d.dot(d1)).Length < 1e-3 and abs(k - round(k)) < 1e-4 and 1 <= round(k) < n1:
            out.append((int(round(k)) + 1, l))
    out.sort(key=lambda x: x[0])
    return out, d1


def _circular(seed, pool, n, step, named):
    """[(index, link)] of seed's instances round one axis, the axis, a point on it and the step."""
    import numpy
    sp = seed.Placement
    rows = []
    for l in pool:
        rel = l.Placement.multiply(sp.inverse())
        ang = math.degrees(rel.Rotation.Angle)
        if ang < 1e-6:
            continue
        rows.append((l, rel, ang))
    if not rows:
        return [], V(0, 0, 1), V(), step or 0.0
    first = min(rows, key=lambda r: r[2])
    axis = V(first[1].Rotation.Axis).normalize()
    if step is None:
        step = first[2]
    m = first[1].toMatrix()
    a = numpy.array([[1 - m.A11, -m.A12, -m.A13], [-m.A21, 1 - m.A22, -m.A23], [-m.A31, -m.A32, 1 - m.A33],
                     [axis.x, axis.y, axis.z]])
    b = numpy.array([m.A14, m.A24, m.A34, 0.0])
    p = numpy.linalg.lstsq(a, b, rcond=None)[0]
    point = V(*p)
    out = []
    for l, rel, ang in rows:
        ax = V(rel.Rotation.Axis)
        signed = ang if ax.dot(axis) > 0 else 360.0 - ang
        k = signed / step
        if abs(k - round(k)) < 1e-4 and 1 <= round(k) < n:
            out.append((int(round(k)) + 1, l))
    out.sort(key=lambda x: x[0])
    return out, axis, point, step


def open_assembly(path, doc=None, read_tree_api=None):
    res = swapp.run("asm-tree", [os.path.abspath(path)], "Reading the assembly from SolidWorks...", timeout=1800)
    op = Opener(res, read_tree_api)
    asm = op.build(path, doc)
    c = op.counts
    msg("%s: %d components (%d subassemblies), %d of %d mates, %d patterns, %d folders, %d assembly features" % (
        os.path.basename(path), c["components"], c["subassemblies"], c["mates_made"], c["mates"], c["patterns"],
        c["folders"], c["features"]))
    for note in op.notes:
        warn(note)
    asm.Document.Meta = dict(asm.Document.Meta, FreeWorksOpenReport=json.dumps({"counts": c, "notes": op.notes}))
    return asm.Document


# =================================================================== save
def _mate_ref(ref, index):
    ""

    from . import save
    import Part
    row = save._mate_ref(ref, index)
    if row is None or row["kind"] == "Vertex":
        return row
    obj, subs = ref[0], ref[1]
    sub = subs[0] if isinstance(subs, (list, tuple)) else subs
    comp = obj
    if obj not in index:
        first = sub.split(".")[0]
        comp = obj.Document.getObject(first)
        sub = sub[len(first) + 1:]
    shape = comp.getSubObject(sub)
    try:
        q = shape.distToShape(Part.Vertex(V(*row["point"])))[1][0][0]
    except Exception:
        return row
    local = index[comp][1].inverse().multVec(q)
    row["point"], row["local"] = [q.x, q.y, q.z], [local.x, local.y, local.z]
    return row


class Spec:
    def __init__(self, folder, tmp):
        self.folder, self.tmp = folder, tmp
        self.parts, self.files = [], {}
        self.assemblies = []        # subassembly specs, innermost first
        self.sub_files = {}         # assembly object -> .SLDASM path
        self.notes = []

    def part_file(self, link):
        from . import save
        from . import fctree
        try:
            from swstyle import asmfeature
            target = asmfeature.own_part(link)
        except Exception:
            target = link.LinkedObject
        key = (target.Document.Name, target.Name)
        if key in self.files:
            return self.files[key], target
        try:
            from swstyle import asmcore
            own = asmcore.part_object(target.Document) is target
        except Exception:
            own = False
        # a part document's own body is saved under the document's name, other objects under theirs
        name = target.Document.Label if own and target.Document is not link.Document else target.Label
        part_file = os.path.join(self.folder, save._safe(name) + ".SLDPRT")
        source = save._unchanged_source(target)
        if source:
            if os.path.normcase(source) != os.path.normcase(os.path.abspath(part_file)):
                save._backup(part_file)
            self.parts.append({"copy": source, "file": part_file})
            self.files[key] = part_file
            return part_file, target
        import Import
        step = os.path.join(self.tmp, "p%d.step" % len(self.parts))
        row = {"step": step, "file": part_file}
        saved = target.Placement
        try:
            target.Placement = App.Placement()
            Import.export([target], step)
            body = save._tree_body(target)
            if body is not None and params().GetBool("SaveFeatureTree", True):
                try:
                    row["tree"] = fctree.body_data(body)
                    row["tree"]["volume"] = body.Shape.Volume
                except Exception as exc:
                    msg("%s: feature tree not exported (%s)" % (name, exc))
        finally:
            target.Placement = saved
        save._backup(part_file)
        self.parts.append(row)
        self.files[key] = part_file
        return part_file, target

    def build(self, asm, out):
        from . import save
        from swstyle import asmcore
        comps, index = [], {}
        pattern_of = {}
        try:
            from swstyle import asmcpattern
            pats = asmcpattern.patterns(asm)
        except Exception:
            asmcpattern, pats = None, []
        for k, feat in enumerate(pats):
            for inst in asmcpattern.instances(feat):
                pattern_of[inst.Name] = k
        for c in asmcore.components(asm):
            if c.TypeId == "Assembly::AssemblyLink":
                sub = c.LinkedObject
                if sub not in self.sub_files:
                    path = os.path.join(self.folder, save._safe(sub.Document.Label if sub.Document is not asm.Document
                                                                 else sub.Label) + ".SLDASM")
                    self.sub_files[sub] = path
                    save._backup(path)
                    self.assemblies.append(self.build(sub, path))
                where = c.Placement
                file = self.sub_files[sub]
            elif c.TypeId == "App::Link" and c.LinkedObject is not None:
                file, target = self.part_file(c)
                where = c.Placement.multiply(target.Placement)
            else:
                self.notes.append("%s: not saved (not a part or subassembly)" % c.Label)
                continue
            row = {"file": file, "name": c.Label, "matrix": save._rows(where), "hidden": not c.Visibility,
                   "flexible": asmcore.is_flexible(c)}
            try:
                from swstyle import asmcomp
                row["suppressed"] = asmcomp.is_suppressed(c)
            except Exception:
                pass
            if c.Name in pattern_of:
                row["instance_of"] = pattern_of[c.Name]
            index[c] = (len(comps), where.toMatrix())
            comps.append(row)
        spec = {"file": out, "components": comps}
        spec["fixed"] = [index[c][0] for c in asmcore.grounded(asm) if c in index]
        spec["mates"] = self.mates(asm, index)
        spec["patterns"] = self.patterns(asm, pats, index) if asmcpattern else []
        spec["mate_folders"], spec["comp_folders"] = self.folders(asm, index)
        spec["features"] = self.features(asm)
        return spec

    # ---------------------------------------------------------------- mates
    def mates(self, asm, index):
        from . import save
        from swstyle import asmcore as ac
        rows = []
        for j in ac.joint_group(asm).Group:
            if getattr(j, "ObjectToGround", None) is not None or getattr(j, ac.PART_OF_PROP, ""):
                continue
            if getattr(j, "FwMateFolder", False) or not hasattr(j, "Reference1"):
                continue
            name = j.Label.split(" (")[0]
            kind = save._mate_kind(j) or getattr(j, ac.MATE_PROP, "")
            try:
                from swstyle import asmmenu
                off = bool(asmmenu.suppressed(j))
            except Exception:
                off = bool(getattr(j, "Suppressed", False)) and not getattr(j, ac.ERROR_PROP, False)
            row = {"name": name, "kind": kind, "suppressed": off, "values": {},
                   "distance": float(getattr(j, "Distance", 0) or 0), "angle": float(getattr(j, "Angle", 0) or 0),
                   "lock_rotation": bool(getattr(j, ac.LOCK_PROP, False)) or getattr(j, "JointType", "") == "Slider"}

            def ref(obj_name, sub):
                obj = j.Document.getObject(obj_name)
                return _mate_ref((obj, [sub]), index) if obj is not None else None

            refs = [_mate_ref(j.Reference1, index), _mate_ref(j.Reference2, index)]
            if kind == "Width":
                data = list(getattr(j, ac.WIDTH_PROP, []) or [])
                refs = [ref(*item.split(" ", 1)) for item in data[:4]]
            elif kind == "Symmetric":
                first = (getattr(j, ac.SYMMETRIC_PROP, []) or [""])[0].split(" ", 1)
                refs = [ref(*first) if len(first) == 2 else None, refs[1], refs[0]]
            elif kind in ac.LIMITS:
                lim = list(getattr(j, ac.LIMIT_PROP, []) or [])
                low, high = float(lim[1]), float(lim[2])
                try:
                    now = ac.picked_value(kind, [(j.Reference1[0], j.Reference1[1][0]), (j.Reference2[0], j.Reference2[1][0])])
                    now = abs(now) if kind == "Distance Range" else now
                except Exception:
                    now = (low + high) / 2.0
                row["values"] = {"min": low, "max": high, "now": min(max(now, low), high)}
            elif kind == "Gear":
                row["values"] = {"d1": 2 * float(j.Distance), "d2": 2 * float(j.Distance2),
                                 "reverse": bool(getattr(j, ac.REVERSE_PROP, False))}
            elif kind in ("Rack Pinion", "Screw"):
                mode, number = (getattr(j, ac.VALUE_PROP, "") or "x 0").split()
                number = float(number)
                rev = bool(getattr(j, ac.REVERSE_PROP, False))
                if kind == "Rack Pinion":
                    row["values"] = {"diameter": number if mode == "diameter" else number / math.pi, "reverse": rev}
                else:
                    row["values"] = {"distance": number if mode == "distance" else 1.0 / number, "reverse": rev}
            elif kind == "Hinge":
                kind = row["kind"] = "Concentric"
                self.notes.append("%s: Hinge saved as a Concentric mate" % name)
            if kind == "Lock":
                if not all(refs):
                    self.notes.append("%s: its components were not found" % name)
                    continue
            elif kind in ("Width", "Symmetric") and None in refs:
                self.notes.append("%s: a picked face was not found" % name)
                continue
            elif None in refs:
                self.notes.append("%s: a picked face or edge was not found" % name)
                continue
            row["refs"] = refs
            rows.append(row)
        return rows

    # ---------------------------------------------------------------- patterns
    def patterns(self, asm, pats, index):
        from swstyle import asmcpattern
        out = []
        by_name = {c.Name: v[0] for c, v in index.items()}
        for feat in pats:
            kind = getattr(feat, asmcpattern.KIND_PROP, "")
            d = asmcpattern.data(feat)
            seeds = [by_name[s.Name] for s in asmcpattern.seeds(feat) if s.Name in by_name]
            insts = [by_name[i.Name] for i in asmcpattern.instances(feat) if i.Name in by_name]
            row = {"name": feat.Label, "kind": kind, "seeds": seeds, "instances": insts}
            if kind == "linear":
                row.update(d1=list(d.get("d1", [1, 0, 0])), s1=float(d.get("s1", 10.0)), n1=int(d.get("n1", 2)),
                           d2=list(d.get("d2", [0, 1, 0])), s2=float(d.get("s2", 0.0)), n2=int(d.get("n2", 1)))
            elif kind == "circular":
                count, angle = int(d.get("count", 2)), float(d.get("angle", 360.0))
                step = angle if not d.get("equal", True) else (angle / count if abs(angle - 360.0) < 1e-9
                                                                else angle / max(1, count - 1))
                row.update(axis=list(d.get("axis", [0, 0, 1])), axis_point=list(d.get("axis_point", [0, 0, 0])),
                           step=step, count=count)
            elif kind == "mirror":
                row.update(point=list(d.get("point", [0, 0, 0])), normal=list(d.get("normal", [1, 0, 0])))
            if d.get("skip"):
                self.notes.append("%s: skipped instances are not saved yet (SolidWorks makes them all)" % feat.Label)
            out.append(row)
        return out

    def folders(self, asm, index):
        try:
            from swstyle import asmfolder
        except Exception:
            return [], []
        mates = [{"name": f.Label, "mates": [m.Label.split(" (")[0] for m in asmfolder.members(f)]}
                 for f in asmfolder.folders(asm)]
        comps = [{"name": f.Label, "members": [index[c][0] for c in asmfolder.component_members(f) if c in index]}
                 for f in asmfolder.component_folders(asm)]
        return mates, comps

    # ---------------------------------------------------------------- assembly features
    def features(self, asm):
        from . import fctree
        try:
            from swstyle import asmfeature
        except Exception:
            return []
        out = []
        feats = asmfeature.features(asm)
        for f in feats:
            kind = getattr(f, asmfeature.FEATURE_PROP, "")
            if kind != "Extrude" or f.Profile is None:
                self.notes.append("%s: %s assembly features are not saved yet" % (f.Label, kind))
                continue
            end = {"Blind": "Length", "Through All": "ThroughAll"}.get(f.EndCondition)
            if end is None:
                self.notes.append("%s: end condition %s is not saved yet" % (f.Label, f.EndCondition))
                continue
            sk = fctree.sketch_data(f.Profile)
            sk["name"] = f.Profile.Label
            out.append({"name": f.Label, "sketch": sk, "end": end, "depth": float(f.Depth),
                        "reversed": bool(f.Reversed)})
        if out:
            out[-1]["volume"] = _volume(asm)
        return out


def export_assembly(asm, path):
    from . import save
    folder = os.path.dirname(os.path.abspath(path))
    tmp = tempfile.mkdtemp(prefix="fw-sw-")
    try:
        sp = Spec(folder, tmp)
        top = sp.build(asm, os.path.abspath(path))
        top["parts"] = sp.parts
        top["assemblies"] = sp.assemblies
        spec = os.path.join(tmp, "spec.json")
        with open(spec, "w", encoding="utf-8") as fh:
            json.dump(top, fh)
        if params().GetBool("KeepSpec", False):
            shutil.copyfile(spec, os.path.abspath(path) + ".spec.json")
        save._backup(path)
        res = swapp.run("save-asm2", [spec, os.path.abspath(path)],
                        "SolidWorks is saving %s..." % os.path.basename(path), timeout=3600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    notes = list(sp.notes) + list(res.get("notes", []))
    for rep in [res] + list(res.get("subassemblies", [])):
        where = os.path.basename(rep.get("file", ""))
        notes += ["%s %s: %s" % (where, m["name"], m.get("why") or "not made") for m in rep.get("mates", []) if not m.get("ok")]
        notes += ["%s %s: %s" % (where, p["name"], p.get("why") or "not made") for p in rep.get("patterns", []) if not p.get("ok")]
        notes += ["%s %s: folder not made" % (where, f["name"]) for f in rep.get("folders", []) if not f.get("ok")]
        notes += ["%s %s: %s" % (where, f["name"], f.get("why") or "; ".join(f.get("tried", [])) or "not made")
                  for f in rep.get("features", []) if not f.get("ok")]
    made = sum(1 for m in res.get("mates", []) if m.get("ok"))
    msg("SolidWorks wrote %s (%d components, %d subassemblies, %d of %d mates, %d patterns, %d folders, %d features)" % (
        path, len(res.get("components", [])), len(res.get("subassemblies", [])), made, len(res.get("mates", [])),
        sum(1 for p in res.get("patterns", []) if p.get("ok")), sum(1 for f in res.get("folders", []) if f.get("ok")),
        sum(1 for f in res.get("features", []) if f.get("ok"))))
    if notes:
        tell("%s was saved. Not everything came across:\n\n%s" % (os.path.basename(path), "\n".join(notes)),
             icon="warning")
    return res
