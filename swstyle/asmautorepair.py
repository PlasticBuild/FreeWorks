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

from . import asmcore as ac

TOL = 1e-4
ANG = 1e-3


def _short(name):
    name = (name or "").split(".")[-1]
    if ";" in name:
        name = name.split(";")[-1].lstrip("#")
    for k in ("Face", "Edge", "Vertex"):
        i = name.rfind(k)
        if i >= 0 and name[i + len(k):].isdigit():
            return name[i:]
    return name


def _kind(name):
    for k in ("Face", "Edge", "Vertex"):
        if name.startswith(k) and name[len(k):].isdigit():
            return k
    return None


def _shape(comp):
    target = getattr(comp, "LinkedObject", None)
    if target is None or getattr(comp, "TypeId", "") != "App::Link":
        return None, None
    try:
        sh = target.Shape
    except Exception:
        return target, None
    return target, (None if sh is None or sh.isNull() else sh)


def _missing(shape, name):
    k = _kind(name)
    if k is None:
        return False
    n = int(name[len(k):])
    many = {"Face": len(shape.Faces), "Edge": len(shape.Edges), "Vertex": len(shape.Vertexes)}[k]
    return n < 1 or n > many


def missing_refs(joint):
    """[(property, comp, element name)] for each reference whose element is gone."""
    out = []
    for prop in ("Reference1", "Reference2"):
        ref = getattr(joint, prop, None)
        if not ref or not ref[1]:
            continue
        comp, subs = ref[0], list(ref[1])
        name = _short(subs[0])
        if "." in subs[0].rstrip(".") and not _kind(subs[0].split(".")[-1] or ""):
            continue        # a path into a subassembly
        _t, shape = _shape(comp)
        if shape is not None and _missing(shape, name):
            out.append((prop, comp, name))
    return out


def broken(asm):
    """The mates of asm with a missing reference."""
    if asm is None:
        return []
    return [j for j in ac.mates(asm) if hasattr(j, "Reference1") and missing_refs(j)]


def _par(a, b):
    try:
        return abs(abs(a.normalize().dot(b.normalize())) - 1) < ANG
    except Exception:
        return False


def _line_dist(p, base, axis):
    d = p - base
    a = App.Vector(axis).normalize()
    return (d - a * d.dot(a)).Length


def _by_place(shape, kind, origin, z):
    """The element of kind at origin with direction z (in the part's own coordinates)."""
    import Part
    pt = Part.Vertex(origin)
    best = []
    items = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[kind]
    for i, el in enumerate(items, 1):
        s = None
        try:
            if kind == "Vertex":
                s = (el.Point - origin).Length
            elif kind == "Face":
                surf = el.Surface
                t = surf.TypeId
                if "Plane" in t:
                    n = el.normalAt(*el.ParameterRange[0::2])
                    if _par(n, z) and abs((origin - el.CenterOfMass).dot(App.Vector(n).normalize())) < TOL:
                        s = el.distToShape(pt)[0]
                elif any(x in t for x in ("Cylinder", "Cone", "Sphere", "Torus")):
                    if "Sphere" in t:
                        s = (surf.Center - origin).Length
                    elif _par(surf.Axis, z) and _line_dist(origin, surf.Center, surf.Axis) < TOL:
                        s = abs((origin - surf.Center).dot(App.Vector(surf.Axis).normalize())) * 1e-3
                else:
                    d = el.distToShape(pt)[0]
                    if d < TOL:
                        s = d
            else:
                c = el.Curve
                t = c.TypeId
                if "Circle" in t or "Ellipse" in t:
                    if _par(c.Axis, z) and (c.Center - origin).Length < TOL:
                        s = 0.0
                elif "Line" in t:
                    d = el.distToShape(pt)[0]
                    if d < TOL:
                        s = d
                else:
                    d = el.distToShape(pt)[0]
                    if d < TOL:
                        s = d
        except Exception:
            s = None
        if s is not None and (s < TOL * 10 or "Cylinder" in getattr(getattr(el, "Surface", None), "TypeId", "")):
            best.append((s, i))
    if not best:
        return None
    best.sort()
    if len(best) > 1 and abs(best[0][0] - best[1][0]) < 1e-12:
        return None             # two alike: no clear match
    return "%s%d" % (kind, best[0][1])


def _by_memo(joint, prop, shape):
    try:
        from . import asmpersist, persistrefs as pr
    except Exception:
        return None
    memo = asmpersist._MEMO.get((joint.Document.Name, joint.Name, prop))
    if memo is None:
        return None
    try:
        return pr.find(shape, memo[2])
    except Exception:
        return None


def repair_joint(joint):
    """Auto Repair one mate. Returns [(property, old, new)] for the references put back."""
    done = []
    for prop, comp, name in missing_refs(joint):
        target, shape = _shape(comp)
        new = _by_memo(joint, prop, shape)
        if not new or _missing(shape, new) or _kind(new) != _kind(name):
            plc = getattr(joint, "Placement1" if prop == "Reference1" else "Placement2", None)
            if plc is None:
                continue
            tp = getattr(target, "Placement", App.Placement())
            local = tp.multiply(plc)            # the mate's frame where the part's shape is
            z = local.Rotation.multVec(App.Vector(0, 0, 1))
            new = _by_place(shape, _kind(name), local.Base, z)
        if not new:
            continue
        try:
            setattr(joint, prop, (comp, [new, new]))
            done.append((prop, name, new))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Auto Repair %s: %s\n" % (joint.Label, error))
    if done:
        try:
            from . import asmpersist
            asmpersist.forget(joint)
        except Exception as _fw_err:
            _fw_log("asmautorepair.py:201", _fw_err)
        joint.touch()
    return done


def auto_repair(asm, joints=None):
    """Auto Repair the mates (all of asm's with a missing reference when joints is None).
    Returns (repaired {mate label: [(property, old, new)]}, not repaired [mate label])."""
    joints = broken(asm) if joints is None else [j for j in joints if missing_refs(j)]
    fixed, left = {}, []
    if not joints:
        return fixed, left
    doc = asm.Document
    doc.openTransaction("Auto Repair")
    try:
        for j in joints:
            got = repair_joint(j)
            if got and not missing_refs(j):
                fixed[j.Label] = got
            else:
                left.append(j.Label)
    finally:
        doc.commitTransaction()
    if fixed:
        try:
            doc.recompute()
            ac.solve(asm)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Auto Repair solve: %s\n" % error)
    msg = "Auto Repair: %d mate(s) repaired" % len(fixed)
    if left:
        msg += "; no clear match for %s" % ", ".join(left)
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().statusBar().showMessage(msg, 8000)
    except Exception as _fw_err:
        _fw_log("asmautorepair.py:237", _fw_err)
    App.Console.PrintMessage("FreeCAD: %s\n" % msg)
    return fixed, left


# ---------------------------------------------------------------- component pattern references
PATTERN_SOURCES = (("src", "edge"), ("src2", "edge2"))


def pattern_missing(feat):
    """[value key] of a driven component pattern's picks (curve, sketch, chain) that are gone."""
    from . import asmcpattern, asmpattern
    if getattr(feat, asmcpattern.KIND_PROP, "") not in ("curve", "sketch", "chain"):
        return []
    v = asmcpattern.data(feat)
    out = []
    for key, _geo in PATTERN_SOURCES:
        src = v.get(key)
        if key == "src2" and not (v.get("count2", 1) > 1 and src):
            continue
        if src and asmpattern.driving_shape(src) is None:
            out.append(key)
    return out


def broken_patterns(asm):
    from . import asmcpattern
    return [f for f in asmcpattern.patterns(asm) if pattern_missing(f)] if asm is not None else []


def _split(sub):
    i = sub.rstrip(".").rfind(".")
    return (sub[:i + 1], sub[i + 1:]) if i >= 0 else ("", sub)


def _brep(text):
    import Part
    if not text:
        return None
    sh = Part.Shape()
    try:
        sh.importBrepFromString(text)
    except Exception:
        return None
    return None if sh.isNull() else sh


def _edge_like(container, ref):
    """The edge of container that is ref (same place and length; renumbered), else None."""
    import Part
    want = ref.Edges[0] if ref.Edges else None
    if want is None:
        return None
    mid = Part.Vertex(want.valueAt(0.5 * (want.FirstParameter + want.LastParameter)))
    scored = []
    for i, e in enumerate(container.Edges, 1):
        try:
            d = e.distToShape(mid)[0] + abs(e.Length - want.Length)
            d += min((e.Vertexes[0].Point - want.Vertexes[0].Point).Length + (e.Vertexes[-1].Point - want.Vertexes[-1].Point).Length,
                     (e.Vertexes[0].Point - want.Vertexes[-1].Point).Length + (e.Vertexes[-1].Point - want.Vertexes[0].Point).Length)
        except Exception:
            continue
        scored.append((d, i))
    scored.sort()
    if not scored or scored[0][0] > max(1e-4, 0.02 * want.Length):
        return None
    if len(scored) > 1 and scored[1][0] - scored[0][0] < 1e-9:
        return None
    return "Edge%d" % scored[0][1]


def _on_wire(container, wire):
    import Part
    for i, e in enumerate(container.Edges, 1):
        try:
            mid = Part.Vertex(e.valueAt(0.5 * (e.FirstParameter + e.LastParameter)))
            if wire.distToShape(mid)[0] < 1e-6:
                return "Edge%d" % i
        except Exception:
            continue
    return None


def repair_pattern(feat):
    """Auto Repair a driven component pattern: each lost pick put back on its curve, wire or
    sketch. Returns [(key, old sub, new sub)]."""
    import json
    from . import asmcpattern
    kind = getattr(feat, asmcpattern.KIND_PROP, "")
    v = asmcpattern.data(feat)
    done = []
    for key in pattern_missing(feat):
        src = list(v[key])
        prefix, elem = _split(src[2])
        try:
            top = App.getDocument(src[0]).getObject(src[1])
            path = top.getSubObjectList(prefix) if prefix else [top]
            container = top.getSubObject(prefix) if prefix else top.Shape
        except Exception:
            continue
        if container is None or container.isNull():
            continue        # the object itself is gone: nothing to put it back on
        new = None
        sketch = next((o for o in reversed(path or []) if o.isDerivedFrom("Sketcher::SketchObject")), None)
        if kind == "curve":
            ref = _brep(v.get("edge" if key == "src" else "edge2"))
            new = _edge_like(container, ref) if ref is not None else None
        elif kind == "chain":
            ref = _brep(v.get("wire"))
            new = _on_wire(container, ref) if ref is not None else None
        if new is None and sketch is not None and kind in ("sketch", "chain"):
            k = _kind(elem) or "Edge"     # the pattern takes the whole sketch: any of its elements
            many = {"Edge": container.Edges, "Vertex": container.Vertexes, "Face": container.Faces}[k]
            new = "%s1" % k if many else ("Edge1" if container.Edges else None)
        if not new:
            continue
        src[2] = prefix + new
        v[key] = src
        done.append((key, prefix + elem, src[2]))
    if done:
        setattr(feat, asmcpattern.DATA_PROP, json.dumps(v))
    return done


def auto_repair_patterns(asm, feats=None):
    """Auto Repair the component patterns. Returns (repaired {label: [...]}, not repaired [label])."""
    feats = broken_patterns(asm) if feats is None else [f for f in feats if pattern_missing(f)]
    fixed, left = {}, []
    if not feats:
        return fixed, left
    doc = asm.Document
    doc.openTransaction("Auto Repair")
    try:
        for f in feats:
            got = repair_pattern(f)
            (fixed.__setitem__(f.Label, got) if got and not pattern_missing(f) else left.append(f.Label))
    finally:
        doc.commitTransaction()
    if fixed:
        try:
            from . import asmcpattern
            asmcpattern.follow(asm)
            doc.recompute()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Auto Repair patterns: %s\n" % error)
    msg = "Auto Repair: %d pattern(s) repaired" % len(fixed)
    if left:
        msg += "; no clear match for %s" % ", ".join(left)
    try:
        import FreeCADGui as Gui
        Gui.getMainWindow().statusBar().showMessage(msg, 8000)
    except Exception as _fw_err:
        _fw_log("asmautorepair.py:389", _fw_err)
    App.Console.PrintMessage("FreeCAD: %s\n" % msg)
    return fixed, left


def pattern_rows(out, target):
    """The pattern's right-click: Auto Repair when a pick is gone (after Dissolve Pattern)."""
    from . import asmcpattern
    if not asmcpattern.is_pattern(target) or not pattern_missing(target):
        return out
    if any(e and e[0] == "AutoRepair" for e in out):
        return out
    asm = ac.assembly_of(target.Document)
    row = ("AutoRepair", "Auto Repair", lambda: auto_repair_patterns(asm, [target]), True)
    out = list(out)
    for i, e in enumerate(out):
        if e and e[0] == "DissolvePattern":
            return out[:i + 1] + [row] + out[i + 1:]
    return out + [row]


def install():
    """Auto Repair on a component pattern's right-click (the menu is the Right-click panes')."""
    try:
        from . import rcpanes
    except Exception:
        return
    if getattr(rcpanes._assembly_feature_rows, "_fw_repair", False):
        return
    original = rcpanes._assembly_feature_rows

    def _assembly_feature_rows(out, target):
        out = original(out, target)
        try:
            return pattern_rows(out, target)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: pattern Auto Repair row: %s\n" % error)
            return out
    _assembly_feature_rows._fw_repair = True
    rcpanes._assembly_feature_rows = _assembly_feature_rows
