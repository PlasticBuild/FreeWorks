
#

#     python sw_tree_export.py PART.SLDPRT [OUT.json]
#
# It opens the part read-only and silently, reads the FeatureManager tree, and

# Lengths are written in millimetres, angles in radians.
#

# try/except, so an API call that behaves differently is logged in "errors"
# instead of stopping the export.

import json
import math
import os
import sys
import traceback

import pythoncom
import win32com.client
from win32com.client import VARIANT

NOTHING = VARIANT(pythoncom.VT_DISPATCH, None)

MM = 1000.0

# swDocumentTypes_e / swOpenDocOptions_e
SW_DOC_PART = 1
SW_OPEN_SILENT = 1
SW_OPEN_READONLY = 2

# swSketchSegments_e
SEG_TYPES = {0: "line", 1: "arc", 2: "ellipse", 3: "spline", 4: "text", 5: "parabola"}

# swEndConditions_e
END_CONDITIONS = {
    0: "blind", 1: "through_all", 2: "through_next", 3: "up_to_vertex", 4: "up_to_surface",
    5: "offset_from_surface", 6: "mid_plane", 7: "up_to_body", 9: "through_all_both",
    10: "up_to_selection", 11: "up_to_next",
}

# swConstraintType_e (only the ones FreeCAD can express are named)
RELATIONS = {
    1: "distance", 2: "angle", 3: "radius", 4: "horizontal", 5: "vertical", 6: "tangent",
    7: "parallel", 8: "perpendicular", 9: "coincident", 10: "concentric", 11: "symmetric",
    12: "midpoint", 13: "intersection", 14: "same_length", 15: "diameter", 17: "fix",
    25: "horizontal_points", 26: "vertical_points", 27: "colinear", 28: "coradial", 42: "merge_points",
}


def mm(p):
    return [round(c * MM, 9) for c in p]


class Exporter:
    def __init__(self, sw):
        self.sw = sw
        self.errors = []

    def err(self, where, exc):
        self.errors.append({"where": where, "error": str(exc)[:300]})

    # --------------------------------------------------------------- open
    def open(self, path):
        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        model = self.sw.OpenDoc6(path, SW_DOC_PART, SW_OPEN_SILENT | SW_OPEN_READONLY, "", errors, warnings)
        if model is None:
            raise RuntimeError("The other CAD program could not open %s (error %s)" % (path, errors.value))
        return model

    # ------------------------------------------------------------ sketches
    def sketch(self, feat):
        sk = feat.GetSpecificFeature2
        out = {"segments": [], "points": [], "relations": [], "dimensions": []}
        try:
            xf = sk.ModelToSketchTransform.Inverse  # no-argument methods read like properties under late binding
            a = list(xf.ArrayData)  # 3x3 rotation, translation, scale
            out["to_model"] = {"rotation": a[0:9], "origin": mm(a[9:12]), "scale": a[12]}
        except Exception as exc:
            self.err("sketch transform " + feat.Name, exc)
        ids = {}
        try:
            segs = sk.GetSketchSegments or []
            for i, s in enumerate(segs):
                kind = SEG_TYPES.get(s.GetType, "other")
                rec = {"index": i, "kind": kind, "construction": bool(s.ConstructionGeometry)}
                try:
                    if kind == "line":
                        rec["start"] = mm(self.pt(s.GetStartPoint2))
                        rec["end"] = mm(self.pt(s.GetEndPoint2))
                    elif kind == "arc":
                        rec["center"] = mm(self.pt(s.GetCenterPoint2))
                        rec["start"] = mm(self.pt(s.GetStartPoint2))
                        rec["end"] = mm(self.pt(s.GetEndPoint2))
                        rec["radius"] = s.GetRadius * MM
                        rec["full_circle"] = bool(s.IsCircle)
                        try:
                            rec["direction"] = s.GetRotationDir  # 1 anticlockwise, -1 clockwise
                        except Exception:
                            pass
                    elif kind == "ellipse":
                        rec["center"] = mm(self.pt(s.GetCenterPoint2))
                        rec["major"] = mm(self.pt(s.GetMajorPoint2))
                        rec["minor"] = mm(self.pt(s.GetMinorPoint2))
                        rec["start"] = mm(self.pt(s.GetStartPoint2))
                        rec["end"] = mm(self.pt(s.GetEndPoint2))
                    elif kind == "spline":
                        pts = list(s.GetPoints2 or [])
                        rec["through_points"] = [mm(pts[j:j + 3]) for j in range(0, len(pts), 3)]
                except Exception as exc:
                    self.err("segment %d of %s" % (i, feat.Name), exc)
                ids[("s",) + tuple(self.key(s))] = i
                out["segments"].append(rec)
        except Exception as exc:
            self.err("segments " + feat.Name, exc)
        try:
            for j, p in enumerate(sk.GetSketchPoints2 or []):
                out["points"].append({"index": j, "at": mm([p.X, p.Y, p.Z])})
                ids[("p",) + tuple(self.key(p))] = "p%d" % j
        except Exception as exc:
            self.err("points " + feat.Name, exc)
        try:
            mgr = sk.RelationManager
            for r in mgr.GetRelations(0) or []:  # swAll
                t = r.GetRelationType
                ents = []
                for e in r.GetEntities or []:
                    k = tuple(self.key(e))
                    ents.append(ids.get(("s",) + k, ids.get(("p",) + k)))
                out["relations"].append({"type": RELATIONS.get(t, "sw_%d" % t), "sw_type": t, "entities": ents})
        except Exception as exc:
            self.err("relations " + feat.Name, exc)
        out["dimensions"] = self.dimensions(feat)
        return out

    @staticmethod
    def pt(p):
        return [p.X, p.Y, p.Z]

    @staticmethod
    def key(obj):
        ""
        try:
            return tuple(obj.GetID)
        except Exception:
            return (id(obj),)

    def dimensions(self, feat):
        out = []
        try:
            dd = feat.GetFirstDisplayDimension
            while dd is not None:
                d = dd.GetDimension2(0)

                out.append({"name": d.FullName, "system_value": d.SystemValue, "type": dd.Type2})
                dd = feat.GetNextDisplayDimension(dd)
        except Exception as exc:
            self.err("dimensions " + feat.Name, exc)
        return out

    # ------------------------------------------------------------ features
    def feature(self, feat, model):
        t = feat.GetTypeName2
        rec = {"name": feat.Name, "type": t, "suppressed": False}
        try:
            rec["suppressed"] = bool(feat.IsSuppressed)
        except Exception:
            pass
        try:
            if t in ("ProfileFeature", "3DProfileFeature"):
                rec["sketch"] = self.sketch(feat)
            elif t in ("Extrusion", "Cut", "Boss", "ICE", "ExtrusionThin", "ExtruThin", "CutThin"):
                rec.update(self.extrude(feat))
            elif t in ("Revolution", "RevCut", "RevolutionThin"):
                rec.update(self.revolve(feat))
            elif t in ("Fillet",):
                rec.update(self.fillet(feat, model))
            elif t in ("Chamfer",):
                rec.update(self.chamfer(feat, model))
            elif t in ("RefPlane",):
                rec.update(self.plane(feat))
            elif t in ("MirrorPattern", "LPattern", "CirPattern"):
                rec.update(self.pattern(feat))
            elif t in ("HoleWzd",):
                rec.update(self.hole(feat))
            elif t in ("SweepThread",):
                rec.update(self.thread(feat, model))
            elif t in ("Shell",):
                rec.update(self.shell(feat, model))
            elif t in ("Draft",):
                rec.update(self.draft(feat, model))
            elif t in ("Blend", "BlendCut"):
                rec.update({"kind": "Blend"})
            elif t in ("Rib",):
                rec.update(self.rib(feat))
            elif t in ("Dome",):
                rec.update(self.dome(feat, model))
            elif t in ("VarFillet",):
                rec.update(self.varfillet(feat, model))
            elif t in ("Wrap", "WrapSketch", "WrapFeature", "Emboss", "Deboss", "Engrave", "Scribe"):
                rec.update(self.wrap(feat, model))
            elif t in ("BoundaryBoss", "BoundaryCut", "Boundary"):
                rec.update(self.boundary(feat, model))
        except Exception as exc:
            self.err("feature " + feat.Name, exc)
        rec["parents"] = []
        try:
            for p in feat.GetParents or []:
                rec["parents"].append(p.Name)
        except Exception:
            pass
        rec["dimensions"] = rec.get("dimensions") or self.dimensions(feat)
        return rec

    def hole(self, feat):
        """Hole Wizard: IWizardHoleFeatureData2 sizes (mm, radians) and the placement sketch,
        which is a sub-feature the FeatureManager walk does not reach."""
        d = feat.GetDefinition
        out = {"kind": "hole", "hole": {}}
        for attr, scale in (("Type", None), ("HoleDiameter", MM), ("HoleDepth", MM), ("CounterBoreDiameter", MM),
                            ("CounterBoreDepth", MM), ("CounterSinkDiameter", MM), ("CounterSinkAngle", None),
                            ("ThruHoleDiameter", MM), ("ThruHoleDepth", MM), ("DrillAngle", None),
                            ("EndCondition", None), ("Standard", None), ("FastenerType", None)):
            try:
                v = getattr(d, attr)
                out["hole"][attr] = v * scale if scale and isinstance(v, float) else v
            except Exception as exc:
                self.err("hole %s %s" % (attr, feat.Name), exc)
        out["sub_sketches"] = []
        try:
            sub = feat.GetFirstSubFeature
            while sub is not None:
                if sub.GetTypeName2 in ("ProfileFeature", "3DProfileFeature"):
                    s = self.sketch(sub)
                    s["name"] = sub.Name
                    out["sub_sketches"].append(s)
                sub = sub.GetNextSubFeature
        except Exception as exc:
            self.err("hole sketch " + feat.Name, exc)
        return out

    def extrude(self, feat):
        d = feat.GetDefinition
        out = {"kind": "extrude"}
        out["end"] = END_CONDITIONS.get(d.GetEndCondition(True), "other")
        out["depth"] = d.GetDepth(True) * MM
        out["both_directions"] = bool(d.BothDirections)
        if out["both_directions"]:
            out["end2"] = END_CONDITIONS.get(d.GetEndCondition(False), "other")
            out["depth2"] = d.GetDepth(False) * MM
        out["reverse"] = bool(d.ReverseDirection)
        try:
            out["draft"] = d.GetDraftAngle(True) if d.GetDraftWhileExtruding(True) else 0.0
        except Exception:
            pass
        try:  # swStartConditions_e: 0 sketch plane, 1 surface/face/plane, 2 vertex, 3 offset
            out["start"] = d.FromType
            if out["start"] == 3:
                out["start_offset"] = d.FromOffsetDistance * MM * (-1 if d.FromOffsetReverse else 1)
        except Exception as exc:
            self.err("extrude start", exc)
        try:
            if d.IsThinFeature:
                out["thin"] = {"thickness": d.GetWallThickness(True) * MM}
                try:  # swThinWallType_e: 0 one direction, 1 other direction, 2 mid-plane, 3 two directions
                    out["thin"]["type"] = d.ThinWallType  # a property, not GetThinWallType
                except Exception as exc:
                    self.err("thin wall type", exc)
        except Exception as exc:
            self.err("thin wall", exc)
        return out

    def revolve(self, feat):
        d = feat.GetDefinition
        out = {"kind": "revolve", "angle": d.GetRevolutionAngle(True), "reverse": bool(d.ReverseDirection)}
        try:
            out["revolve_type"] = d.Type  # not "type": that is the feature's type name
        except Exception:
            pass
        return out

    def edges_of(self, d, model):
        """Selected edges as sample points, so FreeCAD can find the same edges."""
        out = []
        try:
            d.AccessSelections(model, VARIANT(pythoncom.VT_DISPATCH, None))
            for e in d.Edges or []:
                c = e.GetCurveParams3
                lo, hi = c.UMinValue, c.UMaxValue
                pts = []
                for t in (0.25, 0.5, 0.75):
                    ev = e.Evaluate2(lo + t * (hi - lo), 0)
                    pts.append(mm(list(ev)[0:3]))
                out.append(pts)
            d.ReleaseSelectionAccess
        except Exception as exc:
            self.err("edges", exc)
        return out

    def fillet(self, feat, model):
        d = feat.GetDefinition
        return {"kind": "fillet", "radius": d.DefaultRadius * MM, "edges": self.edges_of(d, model)}

    def chamfer(self, feat, model):
        d = feat.GetDefinition
        out = {"kind": "chamfer", "chamfer_type": d.Type, "edges": self.edges_of(d, model)}
        try:
            out["distance"] = d.GetEdgeChamferDistance(0) * MM
            out["angle"] = d.EdgeChamferAngle
        except Exception as exc:
            self.err("chamfer " + feat.Name, exc)
        return out

    @staticmethod
    def get(obj, name, *args):
        ""
        ole = obj._oleobj_
        dispid = ole.GetIDsOfNames(name)
        try:
            v = ole.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET, True, *args)
        except Exception:
            v = ole.Invoke(dispid, 0, pythoncom.DISPATCH_METHOD, True, *args)
        if isinstance(v, pythoncom.TypeIIDs[pythoncom.IID_IDispatch]):
            v = win32com.client.dynamic.Dispatch(v)
        return v

    def face_point(self, face):
        ""
        g = self.get
        box = list(g(face, "GetBox"))
        c = [(box[i] + box[i + 3]) / 2.0 for i in range(3)]
        p = list(g(face, "GetClosestPointOn", c[0], c[1], c[2]))[0:3]
        out = {"point": mm(p)}
        try:
            out["normal"] = list(g(face, "Normal"))[0:3]
        except Exception:
            pass
        return out

    def faces_of(self, d, name, feat, model):
        out = []
        try:
            for fc in self.get(d, name) or []:
                if not hasattr(fc, "_oleobj_"):
                    fc = win32com.client.dynamic.Dispatch(fc)
                out.append(self.face_point(fc)["point"])
        except Exception as exc:
            self.err("%s faces %s" % (name, feat.Name), exc)
        return out

    def shell(self, feat, model):
        g = self.get
        d = g(feat, "GetDefinition")
        out = {"kind": "Shell"}
        try:
            g(d, "AccessSelections", model, VARIANT(pythoncom.VT_DISPATCH, None))
        except Exception as exc:
            self.err("shell selections " + feat.Name, exc)
        try:
            out["thickness"] = g(d, "Thickness") * MM
            for k in ("Direction",):
                try:
                    out[k] = g(d, k)
                except Exception:
                    pass
            out["faces"] = self.faces_of(d, "FacesRemoved", feat, model)
        finally:
            try:
                g(d, "ReleaseSelectionAccess")
            except Exception:
                pass
        return out

    def draft(self, feat, model):
        g = self.get
        d = g(feat, "GetDefinition")
        out = {"kind": "Draft"}
        try:
            g(d, "AccessSelections", model, VARIANT(pythoncom.VT_DISPATCH, None))
        except Exception as exc:
            self.err("draft selections " + feat.Name, exc)
        try:
            out["angle"] = g(d, "Angle")
            for k in ("ReverseDirection", "Type"):
                try:
                    out[k] = g(d, k)
                except Exception:
                    pass
            out["faces"] = self.faces_of(d, "FacesToDraft", feat, model)
            try:
                nt = g(d, "NeutralPlane")
                if nt is not None:
                    try:
                        out["neutral"] = self.face_point(nt)
                    except Exception:
                        ref = g(nt, "GetSpecificFeature2")
                        pl = list(g(g(ref, "Transform"), "ArrayData"))
                        out["neutral"] = {"point": mm(pl[9:12]), "normal": pl[6:9], "plane": True}
            except Exception as exc:
                self.err("draft neutral " + feat.Name, exc)
        finally:
            try:
                g(d, "ReleaseSelectionAccess")
            except Exception:
                pass
        return out

    def _with_selections(self, feat, model, kind, read):
        g = self.get
        d = g(feat, "GetDefinition")
        out = {"kind": kind}
        try:
            g(d, "AccessSelections", model, VARIANT(pythoncom.VT_DISPATCH, None))
        except Exception as exc:
            self.err("%s selections %s" % (kind, feat.Name), exc)
        try:
            read(d, out)
        except Exception as exc:
            self.err("%s %s" % (kind, feat.Name), exc)
        finally:
            try:
                g(d, "ReleaseSelectionAccess")
            except Exception:
                pass
        return out

    def dome(self, feat, model):
        g = self.get

        def read(d, out):
            out["height"] = g(d, "Height") * MM
            out["reverse"] = bool(g(d, "ReverseDir"))
            out["elliptical"] = bool(g(d, "Elliptical"))
            out["faces"] = self.faces_of(d, "Faces", feat, model)
            if not out["faces"]:
                try:
                    out["faces"] = [self.face_point(g(d, "Face"))["point"]]
                except Exception:
                    pass
        return self._with_selections(feat, model, "Dome", read)

    def _edge_info(self, e):
        g = self.get
        prm = list(g(e, "GetCurveParams2"))
        t0, t1 = prm[6], prm[7]
        pts = [mm(list(g(e, "Evaluate2", t0 + (t1 - t0) * f, 0))[0:3]) for f in (0.25, 0.5, 0.75)]
        return {"start": mm(prm[0:3]), "end": mm(prm[3:6]), "points": pts}

    def varfillet(self, feat, model):
        g = self.get

        def read(d, out):
            out["default_radius"] = g(d, "DefaultRadius") * MM
            edges = []
            for i in range(int(g(d, "FilletEdgeCount") or 0)):
                e = g(d, "GetFilletEdgeAtIndex", i)
                info = self._edge_info(e)
                for end, which in (("start_radius", "GetStartVertex"), ("end_radius", "GetEndVertex")):
                    try:
                        info[end] = g(d, "GetRadius", g(e, which)) * MM
                    except Exception:
                        info[end] = out["default_radius"]
                edges.append(info)
            out["edges"] = edges
            try:
                out["control_points"] = int(g(d, "GetControlPointsCount") or 0)
            except Exception:
                pass
            radii, raw = [], []
            for i in range(out.get("control_points") or 0):
                got = None
                for args in ((i,), (i, 0.0, NOTHING), (i, 0.0, None)):
                    try:
                        got = g(d, "GetControlPointRadiusAtIndex", *args)
                        break
                    except Exception as exc:
                        raw.append(str(exc)[:60])
                raw.append(repr(got)[:80])
                v = got[0] if isinstance(got, tuple) else got
                if isinstance(v, float):
                    radii.append(v * MM)
            out["cp_radii"], out["cp_raw"] = radii, raw[:8]
        return self._with_selections(feat, model, "VarFillet", read)

    def wrap(self, feat, model):
        g = self.get

        def read(d, out):
            out["wrap_type"] = {0: "Emboss", 1: "Deboss", 2: "Scribe"}.get(int(g(d, "Type")), "Emboss")
            out["thickness"] = g(d, "Thickness") * MM
            out["reverse"] = bool(g(d, "ReverseDirection"))
            try:
                out["faces"] = [self.face_point(g(d, "Face"))["point"]]
            except Exception as exc:
                self.err("wrap face " + feat.Name, exc)
            try:
                out["profile"] = g(d, "SourceSketch").Name
            except Exception:
                pass
        out = self._with_selections(feat, model, "Wrap", read)
        out["kind"] = "Wrap"
        return out

    def boundary(self, feat, model):
        g = self.get

        def read(d, out):
            names = []
            for c in g(d, "D1Curves") or []:
                if not hasattr(c, "_oleobj_"):
                    c = win32com.client.dynamic.Dispatch(c)
                for how in ("Name", "GetSketch"):
                    try:
                        v = g(c, how)
                        names.append(v if isinstance(v, str) else v.Name)
                        break
                    except Exception:
                        continue
            out["profiles"] = names
            out["guides"] = len(g(d, "D2Curves") or [])
        return self._with_selections(feat, model, "Boundary", read)

    def rib(self, feat):
        ""
        g = self.get
        d = g(feat, "GetDefinition")
        out = {"kind": "Rib"}
        for k in ("Thickness", "ReverseThicknessDir", "FlipSide", "Type", "ExtrusionDirection",
                  "IsTwoSided", "EnableDraft", "DraftAngle", "DraftOutward"):
            try:
                out[k] = g(d, k)
            except Exception:
                pass
        if isinstance(out.get("Thickness"), float):
            out["thickness"] = out["Thickness"] * MM
        return out

    def thread(self, feat, model):
        """Thread feature (IThreadFeatureData): the circular edge it starts on and its profile."""
        g = self.get
        d = g(feat, "GetDefinition")
        out = {"kind": "thread"}
        try:
            try:
                g(d, "AccessSelections", model, VARIANT(pythoncom.VT_DISPATCH, None))
            except Exception as exc:
                self.err("thread selections " + feat.Name, exc)
            try:
                edge = g(d, "Edge")             # keep each object referenced while it is used
                curve = g(edge, "GetCurve")
                c = list(g(curve, "CircleParams"))
                out["centre"] = mm(c[0:3])
                out["axis"] = list(c[3:6])
                out["radius"] = c[6] * MM
            except Exception as exc:
                self.err("thread edge " + feat.Name, exc)
            for k in ("Offset", "ReverseOffset", "ReverseDirection", "MaintainThreadLength",
                      "MirrorProfile", "RightHanded", "MultipleStart", "TrimStartFace", "TrimEndFace",
                      "DiameterOverride", "PitchOverride"):
                try:
                    out[k] = bool(g(d, k))
                except Exception:
                    pass
            for k, scale in (("OffsetDistance", MM), ("BlindDepth", MM), ("Diameter", MM), ("Pitch", MM),
                             ("ThreadStartAngle", 1.0), ("RotationAngle", 1.0), ("Revolutions", 1.0),
                             ("EndCondition", 1), ("ThreadMethod", 1), ("MirrorType", 1),
                             ("NumberOfStarts", 1)):
                try:
                    out[k] = g(d, k) * scale
                except Exception:
                    pass
            for k in ("Type", "Size"):
                try:
                    out[k] = str(g(d, k))
                except Exception:
                    pass
        finally:
            try:
                g(d, "ReleaseSelectionAccess")
            except Exception:
                pass
        return out

    def plane(self, feat):
        p = feat.GetSpecificFeature2
        a = list(p.Transform.ArrayData)
        return {"kind": "plane", "rotation": a[0:9], "origin": mm(a[9:12])}

    def pattern(self, feat):
        d = feat.GetDefinition
        out = {"kind": feat.GetTypeName2}
        for attr in ("D1TotalInstances", "D1Spacing", "D2TotalInstances", "D2Spacing", "TotalInstances",
                     "Spacing", "EqualSpacing", "ReverseDirection"):
            try:
                v = getattr(d, attr)
                out[attr] = v * MM if attr.endswith("Spacing") and isinstance(v, float) else v
            except Exception:
                pass
        return out

    # ----------------------------------------------------------------- run
    def export(self, path):
        title = os.path.basename(path)
        already = self.sw.GetOpenDocumentByName(path)
        if already is not None:
            raise RuntimeError("%s is already open in the other CAD program; not touching it" % title)
        model = self.open(path)
        try:
            feats = []
            f = model.FirstFeature
            while f is not None:
                feats.append(self.feature(f, model))
                f = f.GetNextFeature
            return {"source": os.path.basename(path), "units": "mm", "features": feats, "errors": self.errors}
        finally:
            self.sw.CloseDoc(model.GetTitle)


def main(argv):
    """sw_tree_export.py PART.SLDPRT [OUT.json]   or   sw_tree_export.py FOLDER OUTDIR"""
    if len(argv) < 2:
        print(main.__doc__)
        return 2
    src = os.path.abspath(argv[1])
    sw = win32com.client.dynamic.Dispatch("SldWorks.Application")
    if os.path.isdir(src):
        outdir = os.path.abspath(argv[2])
        jobs = []
        for root, _dirs, files in os.walk(src):
            for fn in sorted(files):
                if fn.lower().endswith(".sldprt"):
                    rel = os.path.relpath(os.path.join(root, fn), src)
                    jobs.append((os.path.join(root, fn), os.path.join(outdir, os.path.splitext(rel)[0] + ".tree.json")))
    else:
        out = argv[2] if len(argv) > 2 else os.path.splitext(src)[0] + ".tree.json"
        jobs = [(src, os.path.abspath(out))]
    bad = 0
    for part, out in jobs:
        try:
            res = Exporter(sw).export(part)
        except Exception as exc:
            bad += 1
            print("FAILED", part, exc)
            traceback.print_exc()
            continue
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print("wrote", out, len(res["features"]), "features,", len(res["errors"]), "errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
