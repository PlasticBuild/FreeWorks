# SPDX-License-Identifier: LGPL-2.1-or-later
""















import json
import math
import os
import shutil
import sys

import pythoncom
from win32com.client import VARIANT


def _helper():
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "TreeBuilder"):
        return main
    import swhelper
    return swhelper


H = _helper()
M, NOTHING, method, value, byref_int = H.M, H.NOTHING, H.method, H.value, H.byref_int

PATTERN_TYPES = {"LocalLPattern": "linear", "LocalCirPattern": "circular", "MirrorComponent": "mirror",
                 "DerivedLPattern": "driven", "DerivedCirPattern": "driven", "LocalSketchPattern": "sketch",
                 "LocalCurvePattern": "curve", "LocalChainPattern": "chain"}
CUT_TYPES = ("ICE", "Cut", "CutExtrude", "AsmCut", "ExtrudeCut")
MATE_DATA_ATTRS = ("GearRatioNumerator", "GearRatioDenominator", "Reverse", "PinionPitchDiameter",
                   "RackTravelPerRevolution", "Distance", "DistancePerRevolution", "Revolutions",
                   "RevolutionsPerLength", "ConstraintType", "Constraint", "MaximumDistance", "MinimumDistance",
                   "MaximumAngle", "MinimumAngle", "FlipDimension", "MateAlignment", "Angle", "LockRotation")


def arr(items):
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, list(items))


def _try(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def matrix_of(comp):
    """FreeCAD 4x4 rows (mm) of a component's Transform2."""
    xf = comp.Transform2
    a = list(xf.ArrayData)
    return [[a[i], a[3 + i], a[6 + i], a[9 + i] / M] for i in range(3)] + [[0.0, 0.0, 0.0, 1.0]]


def get(obj, name):
    """A no-argument COM member: called as a method first (GetDefinition, GetEdges...), else read."""
    try:
        return method(obj, name)
    except Exception:
        return value(getattr(obj, name))


def short(name):
    return str(name).split("/")[-1]


def features(model):
    f = model.FirstFeature
    while f is not None:
        yield f
        f = f.GetNextFeature


def subs(feat):
    f = feat.GetFirstSubFeature
    while f is not None:
        yield f
        f = f.GetNextSubFeature


def suppressed(feat):
    try:
        return bool(feat.IsSuppressed2(1, NOTHING)[0])
    except Exception:
        return bool(_try(lambda: value(feat.IsSuppressed), False))


def own_dim(feat):
    """The feature's own D1 (D1@Name@...), else its first dimension."""
    dd = _try(lambda: method(feat, "GetFirstDisplayDimension"))
    while dd is not None:
        dim = _try(lambda: method(dd, "GetDimension2", 0))
        name = str(_try(lambda: dim.FullName, ""))
        if name.startswith("D1@" + feat.Name + "@"):
            return dim
        dd = _try(lambda: method(feat, "GetNextDisplayDimension", dd))
    return first_dim(feat)


def first_dim(feat):
    """The feature's first dimension (IDimension), else None."""
    for get in (lambda: method(method(feat, "GetFirstDisplayDimension"), "GetDimension2", 0),
                lambda: value(feat.GetFirstDisplayDimension).GetDimension2(0)):
        d = _try(get)
        if d is not None:
            return d
    return None



class Reader:
    def __init__(self, s):
        self.s = s
        self.types = H._enum_names(s, "swMate", "[A-Z]+")
        self.refs = H._enum_names(s, "swMateEntity2ReferenceType_")
        self.out = {}           # normcased path -> tree
        self.errors = []

    def read(self, model, path):
        key = os.path.normcase(os.path.abspath(path))
        if key in self.out:
            return
        tree = {"file": path, "components": [], "mates": [], "mate_folders": [], "comp_folders": [],
                "patterns": [], "features": []}
        self.out[key] = tree
        comps = list(value(model.GetComponents(True)) or ())
        subs_to_read = []
        for c in comps:
            row = self.component(c)
            tree["components"].append(row)
            if row["kind"] == "asm" and not row["suppressed"]:
                sub = _try(lambda: method(c, "GetModelDoc2"))
                if sub is None:
                    sub = _try(lambda: self.s.sw.GetOpenDocumentByName(row["file"]))
                if sub is None:
                    e2, w2 = byref_int(), byref_int()
                    sub = _try(lambda: self.s.sw.OpenDoc6(row["file"], 2, 1 | 2, "", e2, w2))
                    if sub is not None:
                        self.s.opened.append(sub.GetTitle)
                if sub is None:
                    self.errors.append("%s: no model for subassembly" % row["name"])
                else:
                    subs_to_read.append((sub, row["file"]))
        for f in features(model):
            t = f.GetTypeName2
            try:
                if t == "MateGroup":
                    self.mate_group(f, tree)
                elif t in PATTERN_TYPES:
                    tree["patterns"].append(self.pattern(f, model, t))
                elif t == "FtrFolder" and "___EndTag___" not in f.Name:
                    tree["comp_folders"].append(self.folder(f))
                elif t in CUT_TYPES:
                    tree["features"].append(self.cut(f, model))
            except Exception as exc:
                self.errors.append("%s: %s" % (f.Name, exc))
        try:
            mp = model.Extension.CreateMassProperty
            tree["volume"] = mp.Volume * 1e9
        except Exception:
            pass
        for sub, file in subs_to_read:
            self.read(sub, file)

    def component(self, c):
        path = str(value(c.GetPathName))
        row = {"name": short(c.Name2), "file": path,
               "kind": "asm" if path.lower().endswith(".sldasm") else "part",
               "matrix": matrix_of(c),
               "fixed": bool(_try(lambda: value(c.IsFixed), False)),
               "hidden": _try(lambda: int(value(c.Visible)), 1) == 0,
               "suppressed": bool(_try(lambda: value(c.IsSuppressed), False)),
               "flexible": _try(lambda: int(value(c.Solving)), 0) == 1,
               "instance": bool(_try(lambda: value(c.IsPatternInstance), False))}
        return row

    def folder(self, f):
        spec = method(f, "GetSpecificFeature2")
        names = []
        for item in value(spec.GetFeatures) or ():
            names.append(short(item.Name))
        comps = []
        try:
            for item in value(spec.GetComponents) or ():
                comps.append(short(item.Name2))
        except Exception:
            pass
        return {"name": f.Name, "features": names, "components": comps}

    def mate_group(self, group, tree):
        seen = set()
        folders = []
        for sub in subs(group):
            t = sub.GetTypeName2
            if t.endswith("Folder"):
                if "___EndTag___" in sub.Name:
                    continue
                fold = self.folder(sub)
                folders.append(fold)
                for item in value(method(sub, "GetSpecificFeature2").GetFeatures) or ():
                    if item.Name not in seen:
                        seen.add(item.Name)
                        self.mate(item, tree)
                continue
            if sub.Name in seen:
                continue
            seen.add(sub.Name)
            self.mate(sub, tree)
        tree["mate_folders"] = folders

    def mate(self, feat, tree):
        try:
            row = H._mate_row(feat, self.types, self.refs)
        except Exception as exc:
            self.errors.append("%s: %s" % (feat.Name, exc))
            return
        mate = method(feat, "GetSpecificFeature2")
        n = _try(lambda: int(value(mate.GetMateEntityCount)), 2)
        for i in range(2, n):           # Width (4), Symmetric (3), Hinge (4) have more sides
            try:
                e = mate.MateEntity(i)
                p = list(value(e.EntityParams))
                comp = method(e, "ReferenceComponent")
                kind = _try(lambda: value(e.ReferenceType), None)
                row["entities"].append({"component": comp.Name2 if comp is not None else None,
                                        "ref": self.refs.get(kind, str(kind)),
                                        "point": [x / M for x in p[0:3]], "dir": p[3:6],
                                        "radius": p[6] / M if len(p) > 6 else 0.0})
            except Exception as exc:
                self.errors.append("%s side %d: %s" % (feat.Name, i + 1, exc))
        for name in ("MaximumVariation", "MinimumVariation"):
            v = _try(lambda: value(getattr(mate, name)))
            if v is not None:
                row[name] = float(v)
        data = {}
        d = _try(lambda: get(feat, "GetDefinition"))
        if d is not None:
            for name in MATE_DATA_ATTRS:
                v = _try(lambda: value(getattr(d, name)))
                if isinstance(v, (int, float, bool)):
                    data[name] = v
        row["data"] = data
        row["feature_type"] = feat.GetTypeName2
        tree["mates"].append(row)

    def pattern(self, f, model, t):
        row = {"name": f.Name, "type": t, "kind": PATTERN_TYPES[t], "suppressed": suppressed(f),
               "seeds": [], "instances": []}
        d = _try(lambda: get(f, "GetDefinition"))
        if d is not None:
            _try(lambda: d.AccessSelections(model, NOTHING))
            for name in ("D1TotalInstances", "D1Spacing", "D2TotalInstances", "D2Spacing", "D1ReverseDirection",
                         "D2ReverseDirection", "PatternSeedOnly", "TotalInstances", "Spacing", "EqualSpacing",
                         "ReverseDirection"):
                v = _try(lambda: value(getattr(d, name)))
                if isinstance(v, (int, float, bool)):
                    row[name] = v
            for name in ("SeedComponentArray", "ComponentsToMirror", "ComponentsToInstance"):
                items = _try(lambda: value(getattr(d, name)))
                if items:
                    row["seeds"] = [short(c.Name2) for c in items if hasattr(c, "Name2")]
                    break
            _try(lambda: d.ReleaseSelectionAccess())
        for child in _try(lambda: get(f, "GetChildren"), None) or ():
            name = _try(lambda: child.Name2) or _try(lambda: child.Name)
            if name:
                row["instances"].append(short(name))
        return row

    def cut(self, f, model):
        import sw_tree_export
        ex = sw_tree_export.Exporter(self.s.sw)
        rec = ex.feature(f, model)
        rec["sketches"] = []
        for p in rec.get("parents", []):
            sk = _try(lambda: model.FeatureByName(p))
            if sk is not None and sk.GetTypeName2 == "ProfileFeature":
                rec["sketches"].append(dict(ex.sketch(sk), name=p))
        rec["errors"] = ex.errors
        scope = []
        d = _try(lambda: get(f, "GetDefinition"))
        if d is not None:
            _try(lambda: d.AccessSelections(model, NOTHING))
            rec["auto_select"] = bool(_try(lambda: value(d.AutoSelectComponents), True))
            for c in _try(lambda: value(d.FeatureScopeBodies), None) or ():
                pass
            for c in _try(lambda: value(d.AssemblyFeatureScopeComponents), None) or ():
                n = _try(lambda: short(c.Name2))
                if n:
                    scope.append(n)
            _try(lambda: d.ReleaseSelectionAccess())
        rec["scope"] = scope
        return rec


def job_asm_tree(s, args):
    path = os.path.abspath(args[0])
    if s.is_open(path):
        raise RuntimeError("%s is open in the other CAD program; it was not read" % os.path.basename(path))
    err, warn = byref_int(), byref_int()
    model = s.sw.OpenDoc6(path, 2, 1 | 2, "", err, warn)       # swDocASSEMBLY, silent + read-only
    if model is None:
        raise RuntimeError("The other CAD program could not open %s (error %s)" % (os.path.basename(path), err.value))
    s.opened.append(model.GetTitle)
    try:
        _try(lambda: model.ResolveAllLightWeightComponents(False))
        r = Reader(s)
        r.read(model, path)
        return {"top": os.path.normcase(path), "assemblies": r.out, "errors": r.errors}
    finally:
        s.close(model)


# ================================================================== asm-edit (tests)
def job_asm_edit(s, args):
    ""




    path = os.path.abspath(args[0])
    edits = json.load(open(args[1], encoding="utf-8"))
    if s.is_open(path):
        raise RuntimeError("%s is open in the other CAD program" % os.path.basename(path))
    err, warn = byref_int(), byref_int()
    model = s.sw.OpenDoc6(path, 2, 1, "", err, warn)           # silent, writable
    if model is None:
        raise RuntimeError("The other CAD program could not open %s (error %s)" % (os.path.basename(path), err.value))
    s.opened.append(model.GetTitle)
    done = []
    try:
        for e in edits:
            feat = model.FeatureByName(e["name"])
            if feat is None:
                feat = _find_mate(model, e["name"])
            if feat is None:
                done.append({"edit": e, "ok": False, "why": "not found"})
                continue
            try:
                ok = False
                if e["op"] == "cut":
                    d = _try(lambda: get(feat, "GetDefinition"))
                    if d is not None:
                        _try(lambda: d.AccessSelections(model, NOTHING))
                        _try(lambda: d.SetDepth(True, e["value"] * M))
                        ok = bool(_try(lambda: feat.ModifyDefinition(d, model, NOTHING), False))
                        if not ok:
                            _try(lambda: d.ReleaseSelectionAccess())
                if ok:
                    pass
                elif e["op"] in ("mate", "cut"):
                    dim = first_dim(feat) if e["op"] == "mate" else own_dim(feat)
                    if dim is None:
                        raise RuntimeError("no dimension")
                    unit = math.radians(1) if e.get("angle") else M
                    ok = dim.SetSystemValue3(e["value"] * unit, 1, NOTHING) == 0      # swSetValue_InThisConfiguration
                    if not ok:
                        ok = dim.SetSystemValue2(e["value"] * unit, 1) == 0
                elif e["op"] == "pattern":
                    d = get(feat, "GetDefinition")
                    d.AccessSelections(model, NOTHING)
                    for name in ("D1TotalInstances", "TotalInstances"):
                        if _try(lambda: value(getattr(d, name))) is not None:
                            setattr(d, name, int(e["count"]))
                            break
                    ok = bool(feat.ModifyDefinition(d, model, NOTHING))
                elif e["op"] == "suppress-mate":
                    model.ClearSelection2(True)
                    feat.Select2(False, 0)
                    ok = bool(model.EditSuppress2)
                else:
                    raise RuntimeError("unknown op")
                done.append({"edit": e, "ok": bool(ok)})
            except Exception as exc:
                done.append({"edit": e, "ok": False, "why": str(exc)})
        value(model.EditRebuild3)
        err, warn = byref_int(), byref_int()
        saved = bool(model.Save3(1 | 4, err, warn))      # silent, save referenced docs
        return {"edits": done, "saved": saved, "save_error": err.value, "save_warnings": warn.value}
    finally:
        s.close(model)


def _find_mate(model, name):
    for f in features(model):
        if f.GetTypeName2 == "MateGroup":
            for sub in subs(f):
                if sub.Name == name:
                    return sub
                if sub.GetTypeName2.endswith("Folder"):
                    for item in value(method(sub, "GetSpecificFeature2").GetFeatures) or ():
                        if item.Name == name:
                            return item
    return None



ADV = {"Symmetric": "swMateSYMMETRIC", "Width": "swMateWIDTH", "Gear": "swMateGEAR",
       "Rack Pinion": "swMateRACKPINION", "Screw": "swMateSCREW", "Hinge": "swMateHINGE",
       "Distance Range": "swMateDISTANCE", "Angle Range": "swMateANGLE", "Universal Joint": "swMateUNIVERSALJOINT",
       "Profile Center": "swMatePROFILECENTER", "Slot": "swMateSLOT"}


class AsmMater(H.Mater):
    ""
    driven = ()         # pattern instances: neither fixed nor floated here

    def fix(self, fixed):
        keep = list(self.comps)
        mine = [i for i in range(len(keep)) if i not in self.driven]
        self.comps = [keep[i] for i in mine]
        try:
            H.Mater.fix(self, {mine.index(i) for i in fixed if i in mine})
        finally:
            self.comps = keep

    def mate_features(self):
        out = []
        for f in features(self.model):
            if f.GetTypeName2 == "MateGroup":
                for sub in subs(f):
                    out.append(sub)
                    if sub.GetTypeName2.endswith("Folder"):
                        out.extend(value(method(sub, "GetSpecificFeature2").GetFeatures) or ())
        return out

    def _names(self):
        return {f.Name for f in self.mate_features()}

    def add_named(self, m):
        before = self._names()
        if m["kind"] in ADV:
            why = self.add_adv(m)
        else:
            why = self.add(m)
        new = [f for f in self.mate_features() if f.Name not in before and not f.GetTypeName2.endswith("Folder")]


        drop = new[:-1]
        for f in drop:
            self.model.ClearSelection2(True)
            if _try(lambda: f.Select2(False, 0), False):
                _try(lambda: self.model.Extension.DeleteSelection2(0))
        self.model.ClearSelection2(True)
        if drop:
            value(self.model.EditRebuild3)
            _try(self.restore)
        if why is not None and new:


            value(self.model.EditRebuild3)
            if _try(self.moved, True):
                last = new[-1]
                self.model.ClearSelection2(True)
                if _try(lambda: last.Select2(False, 0), False):
                    _try(lambda: self.model.Extension.DeleteSelection2(0))
                self.model.ClearSelection2(True)
                value(self.model.EditRebuild3)
                _try(self.restore)
                new = []
            else:
                why = None
        if why is None and new and m.get("name"):
            _try(lambda: setattr(new[-1], "Name", m["name"]))
        return why

    def _entities(self, refs):
        ents = []
        for r in refs:
            e = self._entity(r)
            if e is None:
                return None
            ents.append(e)
        return ents

    def add_adv(self, m):
        kind = m["kind"]
        mtype = self.s.c(ADV[kind])
        if mtype is None:
            return "this program has no %s mate" % kind
        ents = self._entities(m["refs"])
        if ents is None:
            return "its faces or edges were not found in the model"
        tries = []
        why = self._create_mate_data(m, mtype, ents, tries)
        if why is None:
            return None
        why2 = self._add_mate5(m, mtype, ents, tries)
        if why2 is None:
            return None
        return "It was refused (%s)" % "; ".join(tries)

    def _create_mate_data(self, m, mtype, ents, tries):
        kind, v = m["kind"], m.get("values", {})
        try:
            data = self.model.CreateMateData(mtype)
        except Exception as exc:
            tries.append("CreateMateData: %s" % exc)
            return "x"
        if data is None:
            tries.append("CreateMateData gave nothing")
            return "x"
        sets = []
        if kind == "Symmetric":
            sets = [("EntitiesToMate", arr(ents[:2])), ("SymmetryPlane", ents[2])]
        elif kind == "Width":
            sets = [("WidthSelection", arr(ents[:2])), ("TabSelection", arr(ents[2:4])),
                    ("Constraint", self.s.c("swMateWidthOptions_Centered", 0))]
        elif kind == "Gear":
            sets = [("EntitiesToMate", arr(ents)), ("GearRatioNumerator", v.get("d1", 1.0) * M),
                    ("GearRatioDenominator", v.get("d2", 1.0) * M), ("Reverse", bool(v.get("reverse")))]
        elif kind == "Rack Pinion":
            sets = [("EntitiesToMate", arr(ents)), ("PinionPitchDiameter", v.get("diameter", 10.0) * M),
                    ("Reverse", bool(v.get("reverse")))]
        elif kind == "Screw":
            sets = [("EntitiesToMate", arr(ents)), ("DistancePerRevolution", v.get("distance", 1.0) * M),
                    ("Reverse", bool(v.get("reverse")))]
        elif kind == "Distance Range":
            sets = [("EntitiesToMate", arr(ents)), ("Distance", v.get("now", 0.0) * M),
                    ("MaximumDistance", v.get("max", 0.0) * M), ("MinimumDistance", v.get("min", 0.0) * M)]
        elif kind == "Angle Range":
            sets = [("EntitiesToMate", arr(ents)), ("Angle", math.radians(v.get("now", 0.0))),
                    ("MaximumAngle", math.radians(v.get("max", 0.0))), ("MinimumAngle", math.radians(v.get("min", 0.0)))]
        else:
            sets = [("EntitiesToMate", arr(ents))]
        bad = []
        for name, val in sets:
            try:
                setattr(data, name, val)
            except Exception as exc:
                bad.append("%s (%s)" % (name, str(exc)[:60]))
        try:
            feat = self.model.CreateMate(data)
        except Exception as exc:
            feat = None
            bad.append("CreateMate: %s" % str(exc)[:80])
        if feat is None:
            tries.append("CreateMateData: not made%s" % (" [%s]" % ", ".join(bad) if bad else ""))
            return "x"
        value(self.model.EditRebuild3)
        if self.moved():
            self.model.EditUndo2(1)
            self.restore()
            tries.append("CreateMateData: would move a component")
            return "x"
        return None

    def _add_mate5(self, m, mtype, ents, tries):
        kind, v = m["kind"], m.get("values", {})
        marks = {"Symmetric": (1, 1, 2), "Width": (1, 1, 2, 2)}.get(kind, (0,) * len(ents))
        self.model.ClearSelection2(True)
        for i, (e, mark) in enumerate(zip(ents, marks)):
            sd = self.model.SelectionManager.CreateSelectData
            sd.Mark = mark
            e.Select4(i > 0, sd)
        closest = self.s.c("swMateAlignCLOSEST", 2)
        dist = upper = lower = 0.0
        ang = aupper = alower = 0.0
        num = den = 1.0
        if kind == "Distance Range":
            dist, upper, lower = v.get("now", 0.0) * M, v.get("max", 0.0) * M, v.get("min", 0.0) * M
        elif kind == "Angle Range":
            ang, aupper, alower = (math.radians(v.get(k, 0.0)) for k in ("now", "max", "min"))
        elif kind == "Gear":
            num, den = v.get("d1", 1.0) * M, v.get("d2", 1.0) * M
        elif kind == "Rack Pinion":
            dist = v.get("diameter", 10.0) * M
        elif kind == "Screw":
            dist = v.get("distance", 1.0) * M
        err = byref_int()
        try:
            mate = self.model.AddMate5(mtype, closest, bool(v.get("reverse")), dist, upper, lower, num, den,
                                       ang, aupper, alower, False, False, 0, err)
        except Exception as exc:
            mate = None
            tries.append("AddMate5: %s" % str(exc)[:80])
        self.model.ClearSelection2(True)
        if mate is None:
            tries.append("AddMate5 error %s" % err.value)
            return "x"
        value(self.model.EditRebuild3)
        if self.moved():
            self.model.EditUndo2(1)
            self.restore()
            tries.append("AddMate5: would move a component")
            return "x"
        return None


def _select_features(model, feats):
    model.ClearSelection2(True)
    n = 0
    for f in feats:
        if f is not None and f.Select2(n > 0, 0):
            n += 1
    return n


def _new_folder(s, model, name):
    """Puts the selected features or components in a new folder named name."""
    kind = s.c("swFeatureTreeFolder_Containing", 2)
    folder = None
    try:
        folder = model.FeatureManager.InsertFeatureTreeFolder2(kind)
    except Exception:
        pass
    model.ClearSelection2(True)
    if folder is None:
        return False
    _try(lambda: setattr(folder, "Name", name))
    return True


class Writer:
    def __init__(self, s, spec, out):
        self.s, self.spec, self.out = s, spec, out
        self.report = {"file": out, "components": [], "mates": [], "patterns": [], "folders": [], "features": [],
                       "notes": []}

    def write(self):
        s, spec = self.s, self.spec
        template = s.sw.GetUserPreferenceStringValue(s.c("swDefaultTemplateAssembly", 9))
        model = s.sw.NewDocument(template, 0, 0, 0)
        if model is None:
            raise RuntimeError("The other CAD program could not make a new assembly (template %r)" % template)
        s.opened.append(model.GetTitle)
        self.model = model
        H._units_mm(s, model)
        comps = [None] * len(spec["components"])
        loaded = []
        hidden = H._parts_hidden(s, True)
        try:
            for i, comp in enumerate(spec["components"]):
                if comp.get("instance_of") is not None:
                    continue
                H.stamp("component %s" % comp["name"])
                if comp["file"].lower().endswith(".sldasm"):
                    err, warn = byref_int(), byref_int()
                    doc = s.sw.OpenDoc6(comp["file"], 2, 1 | 2, "", err, warn)
                    if doc is not None:
                        s.opened.append(doc.GetTitle)
                        loaded.append(doc)
                else:
                    doc, mine = s.open_part(comp["file"])
                    if mine:
                        loaded.append(doc)
                c = model.AddComponent5(comp["file"], 0, "", False, "", 0.0, 0.0, 0.0)
                if c is None:
                    raise RuntimeError("The other CAD program could not add %s" % os.path.basename(comp["file"]))
                c.Transform2 = H.transform(s, comp["matrix"])
                comps[i] = c
                self.report["components"].append(short(c.Name2))
            model.ForceRebuild3(False)
            self.patterns(comps)
            loose = set()
            for i, comp in enumerate(spec["components"]):
                if comp.get("instance_of") is None or comps[i] is not None:
                    continue
                c = model.AddComponent5(comp["file"], 0, "", False, "", 0.0, 0.0, 0.0)
                if c is None:
                    continue
                c.Transform2 = H.transform(s, comp["matrix"])
                comps[i] = c
                loose.add(i)
                self.report["components"].append(short(c.Name2))
            if loose:
                self.report.setdefault("notes", []).append(
                    "%d pattern instances were placed as fixed components, since the pattern was not made" % len(loose))
            real = [i for i, c in enumerate(comps) if c is not None]
            where = {i: k for k, i in enumerate(real)}
            mater = AsmMater(s, model, [comps[i] for i in real], [spec["components"][i]["matrix"] for i in real])
            mater.driven = {where[i] for i in real if spec["components"][i].get("instance_of") is not None and i not in loose}
            mater.fix({where[i] for i in (spec.get("fixed") or [0]) if i in where} | {where[i] for i in loose})
            for m in spec.get("mates", []):
                row = {"name": m["name"], "kind": m["kind"], "ok": False}
                if m.get("suppressed"):
                    row["why"] = "suppressed in FreeCAD, so it was left out"
                elif any(r is not None and r["comp"] not in where for r in m["refs"]):
                    row["why"] = "it mates a component that could not be placed"
                else:
                    mm = dict(m, refs=[dict(r, comp=where[r["comp"]]) if r else r for r in m["refs"]])
                    try:
                        why = mater.add_named(mm)
                    except Exception as exc:
                        why = "error: %s" % exc
                        mater.restore()
                    row.update(ok=why is None, why=why)
                self.report["mates"].append(row)
            self.mate_folders(mater)
            self.state(comps)
            self.comp_folders(comps)
            self.features()
            model.ForceRebuild3(False)
            self.report["warnings"] = s.save_as(model, self.out)
            try:
                self.report["volume"] = model.Extension.CreateMassProperty.Volume * 1e9
            except Exception:
                pass
            return self.report
        finally:
            if hidden:
                H._parts_hidden(s, False)
            s.close(model)
            for doc in loaded:
                _try(lambda: s.close(doc))

    # ---------------------------------------------------------------- state and folders
    def state(self, comps):
        for i, comp in enumerate(self.spec["components"]):
            c = comps[i]
            if c is None:
                continue
            if comp.get("hidden"):
                _try(lambda: setattr(c, "Visible", 0))
            if comp.get("flexible"):
                _try(lambda: setattr(c, "Solving", 1))
            if comp.get("suppressed"):
                _try(lambda: c.SetSuppression2(0))

    def mate_folders(self, mater):
        by_name = {f.Name: f for f in mater.mate_features()}
        for fold in self.spec.get("mate_folders", []):
            feats = [by_name.get(n) for n in fold["mates"]]
            ok = _select_features(self.model, feats) and _new_folder(self.s, self.model, fold["name"])
            self.report["folders"].append({"name": fold["name"], "ok": bool(ok), "kind": "mates"})

    def comp_folders(self, comps):
        for fold in self.spec.get("comp_folders", []):
            items = [comps[i] for i in fold["members"] if 0 <= i < len(comps) and comps[i] is not None]
            self.model.ClearSelection2(True)
            n = sum(1 for k, c in enumerate(items) if c.Select4(k > 0, NOTHING, False))
            ok = n and _new_folder(self.s, self.model, fold["name"])
            self.report["folders"].append({"name": fold["name"], "ok": bool(ok), "kind": "components"})

    # ---------------------------------------------------------------- component patterns
    def _builder(self):
        b = AsmSketcher(self.s, self.model)
        return b

    def patterns(self, comps):
        for p in self.spec.get("patterns", []):
            row = {"name": p["name"], "kind": p["kind"], "ok": False}
            try:
                why = self.pattern(p, comps)
                row.update(ok=why is None, why=why)
            except Exception as exc:
                row["why"] = "error: %s" % exc
            self.report["patterns"].append(row)
        self.model.ClearSelection2(True)

    def _all_comps(self):
        return list(value(self.model.GetComponents(True)) or ())

    def pattern(self, p, comps):
        seeds = [comps[i] for i in p["seeds"] if comps[i] is not None]
        if not seeds:
            return "its seed components were not placed"
        fm = self.model.FeatureManager
        names = {"linear": "swFmLocalLPattern", "circular": "swFmLocalCirPattern", "mirror": "swFmMirrorComponent"}
        if p["kind"] not in names:
            return "%s patterns are not made in the saved file yet" % p["kind"]
        tries = []
        b = self._builder()
        if p["kind"] == "linear":
            ways = self._edge_ways(seeds, p["d1"]) + list(b._directions(p["d1"], p["name"] + " Direction"))
        elif p["kind"] == "circular":
            ways = list(b._axes({"point": p["axis_point"], "dir": p["axis"]}, p["name"] + " Axis"))
        else:
            plane = b.plane_for({"origin": p["point"], "z": p["normal"]})
            ways = [((lambda mark, append, plane=plane: bool(plane.Select2(append, mark))), "plane")]
        before = {short(c.Name2) for c in self._all_comps()}
        for select, label in ways:
            for rev in (False, True):
                d = _try(lambda: fm.CreateDefinition(self.s.c(names[p["kind"]])))
                if d is None:
                    return "No %s definition came back" % names[p["kind"]]
                self.model.ClearSelection2(True)
                select(0, False)
                ent = _try(lambda: value(self.model.SelectionManager.GetSelectedObject6(1, -1)))
                self.model.ClearSelection2(True)
                bad = []
                for name, val in self._pattern_values(p, seeds, ent, rev):
                    try:
                        setattr(d, name, val)
                    except Exception:
                        try:
                            import pythoncom, win32com.client as wc
                            setattr(d, name, wc.VARIANT(pythoncom.VT_DISPATCH, val))
                        except Exception:
                            bad.append(name)
                if bad:
                    self.model.ClearSelection2(True)
                    select(1, False)
                    for c in seeds:
                        _try(lambda: c.Select4(True, NOTHING, False))
                feat = _try(lambda: fm.CreateFeature(d))
                if feat is None and p["kind"] == "linear":
                    self.model.ClearSelection2(True)
                    select(1, False)
                    for c in seeds:
                        _try(lambda: c.Select4(True, NOTHING, False))
                    n2 = int(p.get("n2", 1))
                    feat = _try(lambda: fm.FeatureLinearPattern2(int(p["n1"]), p["s1"] * M, n2, p.get("s2", 0.0) * M or 0.01, rev, False, "", "", False))
                if feat is None:
                    tries.append("%s rev %d: not made%s" % (label, rev, " (%s)" % ",".join(bad) if bad else ""))
                    continue
                _try(lambda: setattr(feat, "Name", p["name"]))
                new = [c for c in self._all_comps() if short(c.Name2) not in before]
                miss = self._compare(p, new)
                if miss is None:
                    self._map_instances(p, new, comps)
                    return None
                tries.append("%s rev %d: %s" % (label, rev, miss))
                self.model.ClearSelection2(True)
                feat.Select2(False, 0)
                self.model.Extension.DeleteSelection2(1 | 2)       # absorbed features + children
                if p["kind"] == "mirror":
                    break
        return "; ".join(tries) or "not made"

    def _edge_ways(self, seeds, d1):
        n = math.sqrt(sum(x * x for x in d1)) or 1.0
        u = [x / n for x in d1]
        out = []
        for c in seeds:
            for body in _try(lambda: list(method(c, "GetBodies3", 0, NOTHING) or ()), []) or []:
                for e in _try(lambda: list(get(body, "GetEdges") or ()), []) or []:
                    cv = _try(lambda: method(e, "GetCurve"))
                    if cv is None or not _try(lambda: bool(get(cv, "IsLine")), False):
                        continue
                    lp = _try(lambda: list(value(cv.LineParams)))
                    if not lp or not lp[5:6]:
                        continue
                    v = lp[3:6]
                    m = math.sqrt(sum(x * x for x in v)) or 1.0
                    if math.isclose(abs(sum(a_ * b_ / m for a_, b_ in zip(u, v))), 1.0, abs_tol=1e-6):
                        out.append(((lambda mark, append, e=e: self._select_edge(e, mark, append)), "seed edge"))
                        return out
        return out

    def _select_edge(self, e, mark, append):
        sd = _try(lambda: self.model.SelectionManager.CreateSelectData)
        if sd is not None:
            _try(lambda: setattr(sd, "Mark", mark))
        return bool(_try(lambda: e.Select4(append, sd if sd is not None else NOTHING), False))

    def _pattern_values(self, p, seeds, ent, rev):
        if p["kind"] == "linear":
            out = [("D1Axis", ent), ("D1Spacing", p["s1"] * M), ("D1TotalInstances", int(p["n1"])),
                   ("D1ReverseDirection", rev), ("SeedComponentArray", arr(seeds))]
            if p.get("n2", 1) > 1:
                out += [("D2TotalInstances", int(p["n2"])), ("D2Spacing", p["s2"] * M)]
            return out
        if p["kind"] == "circular":
            return [("Axis", ent), ("Spacing", math.radians(p["step"])), ("TotalInstances", int(p["count"])),
                    ("EqualSpacing", False), ("ReverseDirection", rev), ("SeedComponentArray", arr(seeds))]
        return [("MirrorPlane", ent), ("ComponentsToInstance", arr(seeds)), ("ComponentsToMirror", arr(seeds))]

    def _compare(self, p, new):
        want = [self.spec["components"][i]["matrix"] for i in p["instances"]]
        if len(new) != len(want):
            return "%d instances, FreeCAD has %d" % (len(new), len(want))
        got = [matrix_of(c) for c in new]
        for w in want:
            if not any(_same(w, g) for g in got):
                return "an instance lands somewhere else"
        return None

    def _map_instances(self, p, new, comps):
        got = [(matrix_of(c), c) for c in new]
        for i in p["instances"]:
            w = self.spec["components"][i]["matrix"]
            for g, c in got:
                if _same(w, g):
                    comps[i] = c
                    break

    # ---------------------------------------------------------------- assembly features
    def features(self):
        feats = self.spec.get("features", [])
        if not feats:
            return
        b = self._builder()
        for f in feats:
            row = {"name": f["name"], "ok": False}
            try:
                b.a_sketch(f["sketch"])
                ok = None
                start = _try(lambda: self.model.Extension.CreateMassProperty.Volume * 1e9)
                for rev in (bool(f.get("reversed")), not f.get("reversed")):
                    feat = b.a_extrude({"name": f["name"], "profile": f["sketch"]["name"], "cut": True,
                                        "end": f.get("end", "Length"), "length": f.get("depth", 10.0),
                                        "reversed": rev})
                    if feat is None:
                        continue
                    got = _try(lambda: self.model.Extension.CreateMassProperty.Volume * 1e9)
                    if got is None or start is None or start - got > 1e-3:
                        ok = True
                        row["volume"] = got
                        break
                    self.model.ClearSelection2(True)
                    feat.Select2(False, 0)
                    self.model.EditDelete()
                    row["tried"] = row.get("tried", []) + ["volume %.3f, FreeCAD %.3f" % (got, f["volume"])]
                row["ok"] = bool(ok)
            except Exception as exc:
                row["why"] = str(exc)
            self.report["features"].append(row)


def _same(a, b, tol=1e-4):
    return all(abs(a[i][j] - b[i][j]) < (tol * 100 if j == 3 else tol) for i in range(3) for j in range(4))


class AsmSketcher(H.TreeBuilder):
    """TreeBuilder's sketches, reference lines and cuts in an open assembly."""

    def __init__(self, s, model):
        self.s, self.data, self.model = s, {}, model
        self.planes = self._origin_planes()
        self.sketches, self.offsets, self.made, self.normals = {}, {}, {}, {}
        self.math = s.sw.GetMathUtility
        self._sketch_name = ""

    def _named(self, feat, f):
        if feat is not None:
            _try(lambda: setattr(feat, "Name", f["name"]))
        return feat


def job_save_asm2(s, args):
    spec = json.load(open(args[0], encoding="utf-8"))
    out = os.path.abspath(args[1])
    s.toggle_off("swInputDimValOnCreate")
    written, trees = [], 0
    for p in spec.get("parts", []):
        H.stamp("part %s" % os.path.basename(p["file"]))
        if p.get("copy"):
            if os.path.normcase(os.path.abspath(p["copy"])) != os.path.normcase(os.path.abspath(p["file"])):
                shutil.copyfile(p["copy"], p["file"])
            written.append(p["file"])
            continue
        res = H.save_tree(s, p["tree"], p["step"], p["file"]) if p.get("tree") else H.save_part(s, p["step"], p["file"])
        trees += res.get("how") == "tree"
        written.append(res["file"])
    subs_out = []
    for sub in spec.get("assemblies", []):          # innermost first
        H.stamp("subassembly %s" % os.path.basename(sub["file"]))
        subs_out.append(Writer(s, sub, sub["file"]).write())
    rep = Writer(s, spec, out).write()
    rep.update(parts_written=written, parts_with_tree=trees, subassemblies=subs_out)
    return rep


JOBS = {"asm-tree": job_asm_tree, "asm-edit": job_asm_edit, "save-asm2": job_save_asm2}
