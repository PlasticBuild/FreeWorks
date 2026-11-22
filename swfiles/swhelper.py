# SPDX-License-Identifier: LGPL-2.1-or-later
""


















import json
import math
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)          # -I leaves the script's folder out of sys.path

import pythoncom                          # noqa: E402
import win32com.client                    # noqa: E402
from win32com.client import VARIANT       # noqa: E402

M = 0.001                       # mm -> m (the API works in metres)
NOTHING = VARIANT(pythoncom.VT_DISPATCH, None)


def byref_int():
    return VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)


def method(obj, name, *args):
    """Calls a method on an object without type info (MathUtility, MathPoint): late binding
    would read obj.name as a property and then call its default member."""
    ole = obj._oleobj_
    res = ole.Invoke(ole.GetIDsOfNames(name), 0, pythoncom.DISPATCH_METHOD, True, *args)
    if isinstance(res, pythoncom.TypeIIDs[pythoncom.IID_IDispatch]):
        return win32com.client.dynamic.Dispatch(res)
    return res


def sw_get(obj, name, *args):
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


def value(v):
    """A no-argument member read as a property: objects with type info hand back the bound
    method instead of its result, so call it."""
    if isinstance(v, win32com.client.CDispatch) or hasattr(v, "_oleobj_"):
        return v                        # a COM object is callable (default member), not a method
    return v() if callable(v) else v



class _WindowHider:
    ""




    def __init__(self, pid):
        self.pid = pid
        self.seen = set()

    def start(self):
        import threading
        t = threading.Thread(target=self._run, name="sw-window-hider", daemon=True)
        t.start()

    def _run(self):
        import ctypes
        from ctypes import wintypes
        user = ctypes.windll.user32
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found = []

        def each(hwnd, _l):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid and user.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True
        callback = proto(each)
        while True:
            try:
                del found[:]
                user.EnumWindows(callback, 0)
                for hwnd in found:
                    user.ShowWindow(hwnd, 0)                # SW_HIDE
                    if hwnd not in self.seen:
                        self.seen.add(hwnd)
                        buf = ctypes.create_unicode_buffer(256)
                        user.GetWindowTextW(hwnd, buf, 256)
                        stamp("hid SolidWorks window [%s]" % buf.value)
            except Exception:
                pass
            time.sleep(0.015)


class Session:
    def __init__(self):
        pythoncom.CoInitialize()
        self.started = False
        try:
            app = win32com.client.GetActiveObject("SldWorks.Application")
        except Exception:
            app = win32com.client.DispatchEx("SldWorks.Application")
            self.started = True
        self.sw = win32com.client.dynamic.Dispatch(app)
        self.pid = None
        if self.started:
            try:
                self.sw.Visible = False
                self.sw.UserControl = False
            except Exception:
                pass
            try:
                self.pid = int(value(self.sw.GetProcessID))
            except Exception:
                pass
            if self.pid and not os.environ.get("FW_SHOW_SW_WINDOWS"):
                _WindowHider(self.pid).start()
        self.opened = []            # titles of documents this run opened
        self.notes = []             # things the user should hear about (a setting not put back)
        self.prefs = []             # (toggle, old value) switched for this run, put back in finish()
        self._c = None

    # constants from swconst.tlb, next to sldworks.exe
    def c(self, name, default=None):
        if self._c is None:
            self._c = {}
            try:
                folder = os.path.dirname(str(self.sw.GetExecutablePath))
                if not os.path.isfile(os.path.join(folder, "swconst.tlb")):
                    folder = str(self.sw.GetExecutablePath)
                lib = pythoncom.LoadTypeLib(os.path.join(folder, "swconst.tlb"))
                for i in range(lib.GetTypeInfoCount()):
                    info = lib.GetTypeInfo(i)
                    attr = info.GetTypeAttr()
                    if attr.typekind != pythoncom.TKIND_ENUM:
                        continue
                    for j in range(attr.cVars):
                        var = info.GetVarDesc(j)
                        self._c[info.GetNames(var.memid)[0]] = var.value
            except Exception as exc:
                print("swconst.tlb not read:", exc)
        return self._c.get(name, default)

    def is_open(self, path):
        try:
            return self.sw.GetOpenDocumentByName(path) is not None
        except Exception:
            return False

    def open_part(self, path, read_only=True):
        if self.is_open(path):
            return self.sw.GetOpenDocumentByName(path), False
        err, warn = byref_int(), byref_int()
        opts = 1 | (2 if read_only else 0)          # swOpenDocOptions_Silent | ReadOnly
        model = self.sw.OpenDoc6(path, 1, opts, "", err, warn)   # swDocPART
        if model is None:
            raise RuntimeError("SolidWorks could not open %s (error %s)" % (os.path.basename(path), err.value))
        self.opened.append(model.GetTitle)
        return model, True

    def close(self, model):
        try:
            title = model.GetTitle
        except Exception:
            return
        try:
            self.sw.CloseDoc(title)
        finally:
            if title in self.opened:
                self.opened.remove(title)

    def save_as(self, model, out):
        err, warn = byref_int(), byref_int()
        if os.path.exists(out) and self.is_open(out):
            raise RuntimeError("%s is open in SolidWorks; close it there first" % os.path.basename(out))
        ok = model.Extension.SaveAs(out, 0, 1, NOTHING, err, warn)    # current version, silent
        if not ok or err.value:
            raise RuntimeError("SolidWorks could not save %s (error %s)" % (os.path.basename(out), err.value))
        return warn.value

    def toggle_off(self, name):
        ""

        t = self.c(name)
        if t is None:
            return
        try:
            old = self.sw.GetUserPreferenceToggle(t)
            if old:
                self.sw.SetUserPreferenceToggle(t, False)
                self.prefs.append((t, name))
        except Exception:
            pass

    def finish(self):
        for t, name in self.prefs:
            try:
                self.sw.SetUserPreferenceToggle(t, True)
            except Exception as exc:
                self.notes.append("SolidWorks option %s could not be switched back on (%s)" % (name, exc))
        for title in list(self.opened):
            try:
                self.sw.CloseDoc(title)
            except Exception:
                pass
        if self.started:
            try:
                self.sw.ExitApp()
            except Exception:
                pass
            if self.pid and not _exited(self.pid, 30):
                # it no longer answers (after a failed call): end the copy this run started, so no

                try:
                    os.kill(self.pid, 15)
                    self.notes.append("SolidWorks stopped answering, so FreeCAD ended the hidden "
                                      "SolidWorks it had started")
                except Exception as exc:
                    self.notes.append("A hidden SolidWorks (process %s) may still be running: %s" % (self.pid, exc))


def _exited(pid, wait):
    """True once process pid has gone, waiting up to wait seconds (Windows)."""
    import ctypes
    kernel = ctypes.windll.kernel32
    handle = kernel.OpenProcess(0x00100000, False, pid)        # SYNCHRONIZE
    if not handle:
        return True
    try:
        return kernel.WaitForSingleObject(handle, int(wait * 1000)) == 0
    finally:
        kernel.CloseHandle(handle)


# ------------------------------------------------------------------ jobs
def job_probe(s, args):
    out = {"revision": str(s.sw.RevisionNumber), "started_here": s.started}
    try:
        out["executable"] = str(s.sw.GetExecutablePath)
    except Exception:
        pass
    out["constants_read"] = s.c("swDocPART") is not None
    return out


def job_tree(s, args):
    import sw_tree_export
    part = os.path.abspath(args[0])
    if s.is_open(part):
        raise RuntimeError("%s is open in SolidWorks; its tree was not read" % os.path.basename(part))
    tree = sw_tree_export.Exporter(s.sw).export(part)
    return {"tree": tree}


def _import_step(s, step):
    ""
    toggle = s.c("swMultiCAD_Enable3DInterconnect")
    old = None
    if toggle is not None:
        try:
            old = s.sw.GetUserPreferenceToggle(toggle)
            if old:
                s.sw.SetUserPreferenceToggle(toggle, False)    # plain Imported1, no link to the STEP
        except Exception:
            old = None
    try:
        err = byref_int()
        model = s.sw.LoadFile4(step, "r", NOTHING, err)
        if model is None:
            raise RuntimeError("SolidWorks could not import the shape (error %s)" % err.value)
        s.opened.append(model.GetTitle)
        return model
    finally:
        if old:
            try:
                s.sw.SetUserPreferenceToggle(toggle, True)
            except Exception as exc:
                s.notes.append("SolidWorks' 3D Interconnect option could not be switched back on (%s); "
                               "turn it on again in Tools > Options > Import" % exc)


def _units_mm(s, model):
    key, mmgs = s.c("swUnitSystem"), s.c("swUnitSystem_MMGS")
    if key is not None and mmgs is not None:
        try:
            model.Extension.SetUserPreferenceInteger(key, 0, mmgs)
        except Exception:
            pass


def save_part(s, step, out):
    model = _import_step(s, step)
    try:
        if model.GetType != 1:       # swDocPART: several solids can come in as an assembly
            raise RuntimeError("the shape came into SolidWorks as an assembly, not a part")
        _units_mm(s, model)
        model.ForceRebuild3(False)
        warnings = s.save_as(model, out)
        return {"file": out, "warnings": warnings}
    finally:
        s.close(model)


def job_save_part(s, args):
    step, out = os.path.abspath(args[0]), os.path.abspath(args[1])
    return save_part(s, step, out)


def job_export_step(s, args):
    ""

    part, step = os.path.abspath(args[0]), os.path.abspath(args[1])
    if s.is_open(part):
        model, mine = s.sw.GetOpenDocumentByName(part), False
    else:
        model, mine = s.open_part(part)
    try:
        err, warn = byref_int(), byref_int()
        ok = model.Extension.SaveAs(step, 0, 1 | 2, NOTHING, err, warn)    # silent, copy
        if not ok or err.value or not os.path.isfile(step):
            raise RuntimeError("SolidWorks could not write the shape of %s (error %s)"
                               % (os.path.basename(part), err.value))
        return {"step": step}
    finally:
        if mine:
            s.close(model)


def transform(s, m):
    ""

    data = [m[0][0], m[1][0], m[2][0], m[0][1], m[1][1], m[2][1], m[0][2], m[1][2], m[2][2],
            m[0][3] * M, m[1][3] * M, m[2][3] * M, 1.0, 0.0, 0.0, 0.0]
    arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, data)
    return method(s.sw.GetMathUtility, "CreateTransform", arr)



MATES = {"Coincident": ("swMateCOINCIDENT", 0), "Concentric": ("swMateCONCENTRIC", 1),
         "Perpendicular": ("swMatePERPENDICULAR", 2), "Parallel": ("swMatePARALLEL", 3),
         "Tangent": ("swMateTANGENT", 4), "Distance": ("swMateDISTANCE", 5), "Angle": ("swMateANGLE", 6),
         "Lock": ("swMateLOCK", 16)}
ENTITY_KIND = {"Face": ("GetFaces", "FACE"), "Edge": ("GetEdges", "EDGE"), "Vertex": ("GetVertices", "VERTEX")}


class Mater:
    ""



    def __init__(self, s, model, comps, matrices):
        self.s, self.model, self.comps, self.matrices = s, model, comps, matrices
        self.start = [self._xf(c) for c in comps]

    @staticmethod
    def _xf(c):
        try:
            return list(value(c.Transform2).ArrayData)
        except Exception:
            return None

    def moved(self):
        for c, a in zip(self.comps, self.start):
            b = self._xf(c)
            if a is None or b is None:
                continue
            if max(abs(x - y) for x, y in zip(a[:9], b[:9])) > 1e-6 or \
                    max(abs(x - y) for x, y in zip(a[9:12], b[9:12])) > 1e-6:
                return True
        return False

    def restore(self):
        for c, m in zip(self.comps, self.matrices):
            try:
                c.Transform2 = transform(self.s, m)
            except Exception:
                pass

    def fix(self, fixed):
        for i, c in enumerate(self.comps):
            want = i in fixed
            try:
                if bool(value(c.IsFixed)) == want:
                    continue
                self.model.ClearSelection2(True)
                c.Select4(False, NOTHING, False)
                if want:
                    self.model.FixComponent()
                else:
                    self.model.UnfixComponent()
            except Exception as exc:
                self.s.notes.append("component %d: fixed/float not set (%s)" % (i + 1, exc))
        self.model.ClearSelection2(True)

    def _entity(self, ref):
        ""

        c = self.comps[ref["comp"]]
        getter, _t = ENTITY_KIND[ref["kind"]]
        local = [x * M for x in ref["local"]]
        world = [x * M for x in ref["point"]]
        sources = []
        try:
            sources.append(("asm", value(c.GetBodies2(0)) or ()))      # swSolidBody
        except Exception:
            pass
        try:
            sources.append(("part", value(c.GetModelDoc2).GetBodies2(0, True) or ()))
        except Exception:
            pass
        for where, bodies in sources:
            for body in bodies:
                for e in value(getattr(body, getter)) or ():
                    for p in (local, world) if where == "asm" else (local,):
                        if ref["kind"] == "Vertex":
                            q = list(value(e.GetPoint))[:3]
                        else:
                            q = e.GetClosestPointOn(p[0], p[1], p[2])
                            q = list(q)[:3] if q is not None else None
                        if q is not None and math.dist(q, p) < 1e-6:
                            if where == "part":
                                e = c.GetCorrespondingEntity(e)
                            if e is not None:
                                return e
        return None

    def _select(self, ref, append):
        e = self._entity(ref)
        if e is not None:
            try:
                if e.Select4(append, NOTHING):
                    return True
            except Exception:
                pass
        p = [x * M for x in ref["point"]]
        return bool(self.model.Extension.SelectByID2("", ENTITY_KIND[ref["kind"]][1], p[0], p[1], p[2],
                                                     append, 0, NOTHING, 0))

    def add(self, m):
        kind = m["kind"]
        if kind not in MATES:
            return "SolidWorks has no %s mate here" % kind
        mtype = self.s.c(*MATES[kind])
        closest = self.s.c("swMateAlignCLOSEST", 2)
        dist = m.get("distance", 0.0) * M
        ang = math.radians(m.get("angle", 0.0))
        why = "SolidWorks refused it"
        for flip in ((False, True) if kind in ("Distance", "Angle") else (False,)):
            self.model.ClearSelection2(True)
            if kind == "Lock":
                ok = all(self.comps[r["comp"]].Select4(i > 0, NOTHING, False) for i, r in enumerate(m["refs"]))
            else:
                ok = all(self._select(r, i > 0) for i, r in enumerate(m["refs"]))
            if not ok:
                self.model.ClearSelection2(True)
                return "its faces or edges were not found in SolidWorks"
            err = byref_int()
            mate = self.model.AddMate5(mtype, closest, flip, dist, dist, dist, 1.0, 1.0, ang, ang, ang,
                                       False, bool(m.get("lock_rotation")), 0, err)
            self.model.ClearSelection2(True)
            if mate is None:
                why = "SolidWorks refused it (error %s)" % err.value
                continue
            value(self.model.EditRebuild3)
            if not self.moved():
                return None
            self.model.EditUndo2(1)
            self.restore()
            why = "SolidWorks would move a component to make it"
        return why


def add_mates(s, model, comps, spec):
    out = []
    if not spec.get("mates") and not spec.get("fixed"):
        return out
    mater = Mater(s, model, comps, [c["matrix"] for c in spec["components"]])
    mater.fix(set(spec.get("fixed") or [0]))
    for m in spec.get("mates", []):
        if m.get("suppressed"):
            out.append({"name": m["name"], "kind": m["kind"], "ok": False,
                        "why": "suppressed in FreeCAD, so it was left out"})
            continue
        try:
            why = mater.add(m)
        except Exception as exc:
            why = "error: %s" % exc
            mater.restore()
        out.append({"name": m["name"], "kind": m["kind"], "ok": why is None, "why": why})
    return out


def _parts_hidden(s, hide):
    ""

    try:
        s.sw.DocumentVisible(not hide, 1)           # swDocPART
        return True
    except Exception:
        return False


def stamp(what):
    ""
    print("%s %s" % (time.strftime("%H:%M:%S"), what), flush=True)


def job_save_asm(s, args):
    spec = json.load(open(args[0], encoding="utf-8"))
    out = os.path.abspath(args[1])
    parts = []
    trees = 0
    for p in spec.get("parts", []):            # parts to write first: {"step", "file", optional "tree"}
        stamp("part %s" % os.path.basename(p["file"]))
        if p.get("copy"):
            if os.path.normcase(os.path.abspath(p["copy"])) != os.path.normcase(os.path.abspath(p["file"])):
                shutil.copyfile(p["copy"], p["file"])
            parts.append(p["file"])
            continue
        if p.get("tree"):
            res = save_tree(s, p["tree"], p["step"], p["file"])
            trees += res.get("how") == "tree"
        else:
            res = save_part(s, p["step"], p["file"])
        parts.append(res["file"])
    template = s.sw.GetUserPreferenceStringValue(s.c("swDefaultTemplateAssembly", 9))
    model = s.sw.NewDocument(template, 0, 0, 0)
    if model is None:
        raise RuntimeError("SolidWorks could not make a new assembly (template %r)" % template)
    s.opened.append(model.GetTitle)
    _units_mm(s, model)
    placed, loaded, comps = [], [], []
    hidden = _parts_hidden(s, True)     # the parts load for AddComponent without a window of their own
    try:
        for comp in spec["components"]:
            stamp("component %s" % comp["name"])
            doc, mine = s.open_part(comp["file"])
            if mine:
                loaded.append(doc)
            c = model.AddComponent5(comp["file"], 0, "", False, "", 0.0, 0.0, 0.0)
            if c is None:
                raise RuntimeError("SolidWorks could not add %s" % os.path.basename(comp["file"]))
            c.Transform2 = transform(s, comp["matrix"])
            placed.append(c.Name2)
            comps.append(c)
        stamp("rebuild")
        model.ForceRebuild3(False)
        stamp("mates")
        mates = add_mates(s, model, comps, spec)
        stamp("save")
        warnings = s.save_as(model, out)
        stamp("saved")
        return {"file": out, "components": placed, "parts_written": parts, "parts_with_tree": trees,
                "mates": mates, "warnings": warnings}
    finally:
        if hidden:
            _parts_hidden(s, False)
        s.close(model)
        for doc in loaded:
            try:
                s.close(doc)
            except Exception:
                pass




class TreeUnsupported(RuntimeError):
    pass


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class TreeBuilder:
    ""


    def __init__(self, s, data):
        self.debug = []             # why a feature was made another way (tests read it)
        self.s, self.data = s, data
        template = s.sw.GetUserPreferenceStringValue(s.c("swDefaultTemplatePart", 8))
        self.model = s.sw.NewDocument(template, 0, 0, 0)
        if self.model is None:
            raise RuntimeError("SolidWorks could not make a new part (template %r)" % template)
        s.opened.append(self.model.GetTitle)
        _units_mm(s, self.model)
        self.planes = self._origin_planes()
        self.sketches = {}
        self.math = s.sw.GetMathUtility
        self.offsets = {}           # (origin plane, offset) -> reference plane already made
        self.made = {}
        self.normals = {}
        self._sketch_name = ""

    def _origin_planes(self):
        out = []
        f = self.model.FirstFeature
        while f is not None and len(out) < 3:
            if f.GetTypeName2 == "RefPlane":
                out.append(f)
            f = f.GetNextFeature
        return dict(zip(("front", "top", "right"), out))     # XY, XZ, YZ in a new part

    # ---------------------------------------------------------------- selection
    def clear(self):
        self.model.ClearSelection2(True)

    def select(self, feature, append=False, mark=0):
        return feature.Select2(append, mark)

    # ---------------------------------------------------------------- sketches
    def plane_for(self, frame):
        z, o = frame["z"], frame["origin"]
        for key, normal in (("front", [0, 0, 1]), ("top", [0, 1, 0]), ("right", [1, 0, 0])):
            d = _dot(z, normal)
            if abs(abs(d) - 1.0) < 1e-9:
                off = _dot(o, normal)
                if abs(off) < 1e-9:
                    return self.planes[key]
                return self._offset_plane(key, normal, off)
        raise TreeUnsupported("sketch on a plane that is not parallel to an origin plane")

    def _offset_plane(self, key, normal, off):
        ""

        if (key, round(off, 9)) in self.offsets:
            return self.offsets[(key, round(off, 9))]
        dist = self.s.c("swRefPlaneReferenceConstraint_Distance", 8)
        flip = self.s.c("swRefPlaneReferenceConstraint_OptionFlip", 256)
        fm = self.model.FeatureManager
        for opts in ((dist, dist | flip) if off > 0 else (dist | flip, dist)):
            self.clear()
            self.select(self.planes[key])
            plane = fm.InsertRefPlane(opts, abs(off) * M, 0, 0, 0, 0)
            if plane is None:
                continue
            at = self._plane_offset(plane, normal)
            if at is not None and abs(at - off) < 1e-6:
                self.offsets[(key, round(off, 9))] = plane
                return plane
            self.clear()
            plane.Select2(False, 0)
            self.model.EditDelete()
        raise TreeUnsupported("offset plane %+.3f mm from %s not made" % (off, key))

    def _plane_offset(self, plane, normal):
        """Where a reference plane sits along an origin normal, in mm."""
        try:
            tr = plane.GetSpecificFeature2.Transform
            a = list(tr.ArrayData)
            return _dot(a[9:12], normal) / M
        except Exception:
            return None

    def to_model(self, frame, p):
        o, x, y, z = frame["origin"], frame["x"], frame["y"], frame["z"]
        return [o[i] + p[0] * x[i] + p[1] * y[i] + p[2] * z[i] for i in range(3)]

    def _same_normal(self, sketch, frame):
        ""
        o, z = frame["origin"], frame["z"]
        q = [o[i] + z[i] for i in range(3)]
        pt = method(self.math, "CreatePoint", VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                                      [q[0] * M, q[1] * M, q[2] * M]))
        pt = method(pt, "MultiplyTransform", sketch.ModelToSketchTransform)
        return 1 if list(pt.ArrayData)[2] > 0 else -1

    def to_sketch(self, sketch, frame, p):
        q = self.to_model(frame, p)
        pt = method(self.math, "CreatePoint", VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                                      [q[0] * M, q[1] * M, q[2] * M]))
        pt = method(pt, "MultiplyTransform", sketch.ModelToSketchTransform)
        a = list(pt.ArrayData)
        if abs(a[2]) > 1e-7:        # the point is off the sketch plane: the plane is in the wrong place
            raise TreeUnsupported("sketch plane of %s is not where FreeCAD has it" % self._sketch_name)
        return a[0], a[1]

    def a_sketch(self, f):
        self._sketch_name = f["name"]
        plane = self.plane_for(f["frame"])
        self.clear()
        self.select(plane)
        sm = self.model.SketchManager
        sm.AddToDB = True
        sm.DisplayWhenAdded = False
        sm.InsertSketch(True)
        sketch = sm.ActiveSketch
        if sketch is None:
            raise TreeUnsupported("sketch not started")
        same = self._same_normal(sketch, f["frame"])
        self._sketch_sign = same
        segs, centerlines = [], 0
        try:
            for g in f["geometry"]:
                segs.append(self._segment(sm, sketch, f["frame"], g))
                if g.get("construction") and g["kind"] == "line":
                    centerlines += 1
            self._relations(segs, f)
        finally:
            sm.AddToDB = False
            sm.DisplayWhenAdded = True
            sm.InsertSketch(True)          # leaves the sketch
        feat = self.model.FeatureByPositionReverse(0)
        try:
            feat.Name = f["name"]
        except Exception:
            pass
        self.sketches[f["name"]] = (feat, f, centerlines)
        self.normals[f["name"]] = same

    def _segment(self, sm, sketch, frame, g):
        k = g["kind"]
        tp = lambda p: self.to_sketch(sketch, frame, p)
        if k == "line":
            (x1, y1), (x2, y2) = tp(g["start"]), tp(g["end"])
            seg = (sm.CreateCenterLine if g.get("construction") else sm.CreateLine)(x1, y1, 0, x2, y2, 0)
        elif k == "circle":
            (cx, cy) = tp(g["center"])
            seg = sm.CreateCircleByRadius(cx, cy, 0, g["radius"] * M)
        elif k == "arc":
            (cx, cy), (x1, y1), (x2, y2) = tp(g["center"]), tp(g["start"]), tp(g["end"])
            ccw = bool(g.get("ccw", True)) == (getattr(self, "_sketch_sign", 1) > 0)
            seg = sm.CreateArc(cx, cy, 0, x1, y1, 0, x2, y2, 0, 1 if ccw else -1)
        elif k == "ellipse_arc":
            (cx, cy), (ax, ay), (bx, by) = tp(g["center"]), tp(g["major"]), tp(g["minor"])
            (x1, y1), (x2, y2) = tp(g["start"]), tp(g["end"])
            ccw = bool(g.get("ccw", True)) == (getattr(self, "_sketch_sign", 1) > 0)
            seg = sm.CreateEllipticalArc(cx, cy, 0, ax, ay, 0, bx, by, 0, x1, y1, 0, x2, y2, 0, 1 if ccw else -1)
        elif k == "point":
            (x, y) = tp(g["at"])
            seg = sm.CreatePoint(x, y, 0)
        else:
            raise TreeUnsupported("sketch geometry %s" % k)
        if seg is None:
            raise TreeUnsupported("sketch geometry %s not made" % k)
        if g.get("construction") and k != "line":
            try:
                seg.ConstructionGeometry = True
            except Exception:
                pass
        return seg

    RELATIONS = {"horizontal": "sgHORIZONTAL2D", "vertical": "sgVERTICAL2D", "parallel": "sgPARALLEL",
                 "perpendicular": "sgPERPENDICULAR", "tangent": "sgTANGENT", "equal": "sgSAMELENGTH",
                 "fix": "sgFIXED", "on_curve": "sgCOINCIDENT", "coincident": "sgCOINCIDENT"}

    def _end(self, seg, pos):
        """The SketchPoint at a FreeCAD position (1 start, 2 end, 3 centre) of a segment."""
        try:
            if pos == 1:
                return value(seg.GetStartPoint2)
            if pos == 2:
                return value(seg.GetEndPoint2)
            if pos == 3:
                return value(seg.GetCenterPoint2)
        except Exception:
            return None
        return None

    def _relations(self, segs, f):
        ""

        self._add_relations(segs, f)
        self._dimensions(segs, f)

    DIMENSIONS = ("distance", "distance_x", "distance_y", "radius", "diameter", "angle")

    def _ent(self, segs, idx, pos):
        if idx is None or idx < 0 or idx >= len(segs):
            return None
        return segs[idx] if not pos else self._end(segs[idx], pos)

    def _dimensions(self, segs, f):
        sm = self.model.SketchManager
        frame = f["frame"]
        geo = f["geometry"]
        for c in f["constraints"]:
            if c["kind"] not in self.DIMENSIONS or not c.get("driving", True):
                continue
            a = self._ent(segs, c["first"], c["first_pos"])
            b = self._ent(segs, c["second"], c["second_pos"])
            if a is None:
                continue
            # text a little off the first entity, in model space
            g = geo[c["first"]]
            anchor = g.get("center") or g.get("start") or g.get("at") or [0, 0, 0]
            if g.get("kind") == "line":
                anchor = [(g["start"][i] + g["end"][i]) / 2.0 for i in range(3)]
            q = self.to_model(frame, [anchor[0] + 2.0, anchor[1] + 2.0, 0.0])
            self.clear()
            ok = bool(a.Select4(False, NOTHING)) and (b is None or bool(b.Select4(True, NOTHING)))
            if not ok:
                continue
            try:
                x, y, z = q[0] * M, q[1] * M, q[2] * M
                if c["kind"] == "distance_x":
                    self.model.AddHorizontalDimension2(x, y, z)
                elif c["kind"] == "distance_y":
                    self.model.AddVerticalDimension2(x, y, z)
                else:
                    self.model.AddDimension2(x, y, z)
            except Exception:
                pass
        self.clear()

    def _add_relations(self, segs, f):
        for c in f["constraints"]:
            name = self.RELATIONS.get(c["kind"])
            if name is None or c["first"] < 0 or c["first"] >= len(segs):
                continue
            ents = []
            for idx, pos in ((c["first"], c["first_pos"]), (c["second"], c["second_pos"])):
                if idx is None or idx < 0 or idx >= len(segs) or (idx == -2000):
                    continue
                ent = segs[idx] if not pos else self._end(segs[idx], pos)
                if ent is not None:
                    ents.append(ent)
            if not ents:
                continue
            self.clear()
            ok = True
            for i, e in enumerate(ents):
                ok = ok and bool(e.Select4(i > 0, NOTHING))
            if ok:
                try:
                    self.model.SketchAddConstraints(name)
                except Exception:
                    pass
        self.clear()

    # ---------------------------------------------------------------- features
    def _profile(self, name):
        if name not in self.sketches:
            raise TreeUnsupported("profile sketch %r missing" % name)
        return self.sketches[name]

    END = {"Length": 0, "ThroughAll": 1, "UpToFirst": 2, "TwoLengths": 0}

    def a_extrude(self, f):
        sk, data, _c = self._profile(f["profile"])
        end = f["end"].lstrip("?")
        if end not in self.END:
            raise TreeUnsupported("extrude end condition %s" % end)
        t1 = self.END[end]
        single = True
        t2, d2 = 0, 0.0
        if f.get("midplane") or f.get("side") == "Symmetric":
            t1 = 6 if t1 == 0 else 9
        elif end == "TwoLengths" or f.get("side") == "Two sides":
            single, t2, d2 = False, 0, f["length2"] * M
        d1 = f["length"] * M


        along = -1 if f.get("cut") else 1
        if f.get("reversed"):
            along = -along
        flip = along * self.normals.get(f["profile"], 1) < 0
        self.clear()
        self.select(sk)
        fm = self.model.FeatureManager
        if f.get("cut"):
            # FeatureCut4/FeatureExtrusion3: 2nd argument flips the side to cut (kept False), 3rd

            feat = fm.FeatureCut4(single, False, not flip, t1, t2, d1, d2, False, False, False, False,
                                  0.0, 0.0, False, False, False, False, False, True, True, True, True,
                                  False, 0, 0.0, False, False)
        else:
            feat = fm.FeatureExtrusion3(single, False, flip, t1, t2, d1, d2, False, False, False, False,
                                        0.0, 0.0, False, False, False, False, True, True, True, 0, 0.0, False)
        return self._named(feat, f)

    def a_revolve(self, f):
        sk, data, centerlines = self._profile(f["profile"])
        if centerlines != 1:
            raise TreeUnsupported("revolve needs exactly one centerline in its sketch")
        angle = math.radians(f["angle"])
        self.clear()
        self.select(sk)
        fm = self.model.FeatureManager
        feat = fm.FeatureRevolve2(not f.get("midplane"), True, False, bool(f.get("cut")), bool(f.get("reversed")),
                                  False, 6 if f.get("midplane") else 0, 0, angle, 0.0, False, False, 0.0, 0.0,
                                  0, 0.0, 0.0, True, True, True)
        return self._named(feat, f)

    def _edges(self):
        out = []
        for body in self.model.GetBodies2(0, True) or ():        # swSolidBody, visible only
            out.extend(value(body.GetEdges) or ())
        return out

    def _edge_at(self, edges, pts):
        ""
        for e in edges:
            ok = True
            for p in pts:
                q = e.GetClosestPointOn(p[0] * M, p[1] * M, p[2] * M)
                if q is None or math.dist(list(q)[:3], [p[0] * M, p[1] * M, p[2] * M]) > 1e-6:
                    ok = False
                    break
            if ok:
                return e
        return None

    def _select_edges(self, f, mark):
        self.clear()
        edges = self._edges()
        try:
            sd = value(self.model.SelectionManager.CreateSelectData)
            sd.Mark = mark
        except Exception:
            sd = NOTHING
        for i, pts in enumerate(f["edges"]):
            e = self._edge_at(edges, pts)
            if e is not None and e.Select4(i > 0, sd):
                continue
            p = pts[1]
            if not self.model.Extension.SelectByID2("", "EDGE", p[0] * M, p[1] * M, p[2] * M, i > 0, mark,
                                                    NOTHING, 0):
                raise TreeUnsupported("edge %d of %s not found (%d edges in the body)"
                                      % (i + 1, f["name"], len(edges)))

    def a_fillet(self, f):
        if not f["edges"]:
            raise TreeUnsupported("fillet without edges")
        self._select_edges(f, 1)
        feat = self.model.FeatureManager.FeatureFillet3(195, f["size"] * M, 0, 0, 0, 0, 0, NOTHING, NOTHING,
                                                        NOTHING, NOTHING, NOTHING, NOTHING, NOTHING)
        return self._named(feat, f)

    def a_chamfer(self, f):
        if not f["edges"]:
            raise TreeUnsupported("chamfer without edges")
        self._select_edges(f, 1)
        feat = self.model.FeatureManager.InsertFeatureChamfer(4, 1, f["size"] * M, math.radians(45), 0, 0, 0, 0)
        return self._named(feat, f)

    def a_hole(self, f):
        """A plain or counterbored hole: cut-extrudes of circles at the hole's diameters, at the
        centres of its sketch's circles. Countersinks and angled drill points are not made yet."""
        _sk, data, _c = self._profile(f["profile"])
        centres = [g["center"] for g in data["geometry"]
                   if g["kind"] in ("circle", "arc") and not g.get("construction")]
        if not centres:
            raise TreeUnsupported("%s: no circles in its sketch" % f["name"])
        if self._wizard_hole(f, data, centres):
            return
        if f.get("cut_type") not in ("None", "Counterbore"):
            raise TreeUnsupported("%s: %s holes are not made yet" % (f["name"], f.get("cut_type")))
        if f.get("depth_type") == "Dimension" and f.get("drill_point") == "Angled":
            raise TreeUnsupported("%s: holes with an angled drill point are not made yet" % f["name"])
        end = "ThroughAll" if f.get("depth_type") == "ThroughAll" else "Length"
        steps = [(f["name"], f["diameter"], f["depth"], end)]
        if f.get("cut_type") == "Counterbore":
            steps.append((f["name"] + " Counterbore", f["cut_diameter"], f["cut_depth"], "Length"))
        for name, dia, depth, how in steps:
            sk = {"kind": "sketch", "name": name + " Sketch", "frame": data["frame"], "constraints": [],
                  "geometry": [{"kind": "circle", "center": c, "radius": dia / 2.0, "construction": False}
                               for c in centres]}
            self.a_sketch(sk)
            self.a_extrude({"name": name, "group": f["name"], "profile": sk["name"], "cut": True, "end": how,
                            "length": depth,
                            "length2": 0.0, "midplane": False, "reversed": bool(f.get("reversed")),
                            "side": "One side"})

    def _wizard_hole(self, f, data, centres):
        ""



        cut = f.get("cut_type")
        if cut not in ("None", "Counterbore", "Countersink") or f.get("reversed"):
            return False
        frame = data["frame"]
        n = frame["z"]
        pts = [self.to_model(frame, [c[0], c[1], c[2] if len(c) > 2 else 0.0]) for c in centres]
        through = f.get("depth_type") == "ThroughAll"
        dia, depth = f["diameter"] * M, (0.0 if through else f["depth"] * M)
        fm = self.model.FeatureManager
        p = pts[0]
        angle = math.radians(f.get("drill_angle") or 118.0)
        if cut == "None":       # drill size: swWzdHole, ANSI Metric drill sizes
            kind, std, fast = 2, 1, 39
            sizes = ("\u00d8%.1f" % f["diameter"], "%.1f" % f["diameter"], "\u00d8%g" % f["diameter"])
            # where the drill angle goes is not documented the same way everywhere: each layout is
            # tried and the one that gives the right volume is kept
            layouts = [[angle] + [0] * 11, [-1, -1, -1, -1, angle] + [0] * 7,
                       [-1, -1, -1, -1, -1, -1, angle] + [0] * 5, [0] * 12]
        else:                   # ISO screw sizes, custom diameters given as values
            mm = [1.6, 2, 2.5, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24, 30]
            fit = [m for m in mm if m <= f["diameter"] + 1e-9][-2:][::-1] or [mm[0]]
            sizes = ["M%g" % m for m in fit]
            if cut == "Counterbore":     # swWzdCounterBore, swStandardISOSocketHeadCap
                kind, std, fast = 0, 8, 139
                layouts = [[f["cut_diameter"] * M, f["cut_depth"] * M, -1, -1, -1, -1, angle, 0, 0, 0, 0, 0]]
            else:                        # swWzdCounterSink, swStandardISOCTSKFlatHead
                kind, std, fast = 1, 8, 141
                layouts = [[f["cut_diameter"] * M, math.radians(f.get("cut_angle") or 90.0), -1, -1, -1, -1,
                            angle, 0, 0, 0, 0, 0]]
        if through:
            layouts = layouts[:1]
        for li, values in enumerate(layouts):
            feat, size = None, None
            try:
                for size in sizes:
                    self.clear()
                    if not self.model.Extension.SelectByID2("", "FACE", p[0] * M, p[1] * M, p[2] * M, False, 0,
                                                            NOTHING, 0) and \
                            not self.model.Extension.SelectByRay(p[0] * M + n[0] * 1e-3, p[1] * M + n[1] * 1e-3,
                                                                 p[2] * M + n[2] * 1e-3, -n[0], -n[1], -n[2],
                                                                 1e-4, 2, False, 0, 0):      # swSelFACES
                        self.debug.append("%s: no face picked at %s" % (f["name"], p))
                        return False
                    feat = fm.HoleWizard5(kind, std, fast, size, 1 if through else 0, dia, depth, -1, *values,
                                          "", False, True, True, True, True, False)
                    if feat is not None:
                        break
                if feat is None:
                    self.debug.append("%s: HoleWizard5 made nothing (layout %d)" % (f["name"], li))
                    continue
                self.debug.append("%s: HoleWizard5 made %s (%s, layout %d)" % (f["name"], value(feat.Name), size, li))
                if len(pts) > 1:
                    v0 = self.volume_mm3()
                    self._wizard_points(feat, pts[1:])
                    self.model.ForceRebuild3(False)
                    self.debug.append("%s: volume %.1f before the points, %.1f after" % (f["name"], v0, self.volume_mm3()))
                value(self.model.EditRebuild3)
                self._named(feat, f)
                if self._volume_ok(f):
                    self.debug.append("%s: kept as a Hole Wizard hole (%s)" % (f["name"], size))
                    return True
                self.debug.append("%s: wizard hole volume %.1f, want %.1f (layout %d)" % (
                    f["name"], self.volume_mm3(), f.get("volume") or 0, li))
                self.made.pop(f.get("group", f["name"]), None)
            except Exception as exc:
                self.debug.append("%s: wizard hole failed: %s" % (f["name"], str(exc)[:200]))
            if feat is not None:
                try:
                    self._delete(feat)
                    value(self.model.EditRebuild3)
                    self.debug.append("%s: deleted, volume back to %.1f" % (f["name"], self.volume_mm3()))
                except Exception:
                    pass
            self.clear()
        return False

    def _wizard_points(self, feat, pts):
        """Adds points (model mm) to a Hole Wizard feature's placement sketch."""
        sub = method(feat, "GetFirstSubFeature")
        while sub is not None and str(value(sub.GetTypeName2)) not in ("ProfileFeature", "3DProfileFeature"):
            sub = method(sub, "GetNextSubFeature")
        if sub is None:
            raise TreeUnsupported("hole placement sketch not found")
        is3d = str(value(sub.GetTypeName2)) == "3DProfileFeature"
        self.clear()
        sel = sub.Select2(False, 0)
        value(self.model.EditSketch)
        sm = self.model.SketchManager
        sketch = sm.ActiveSketch
        self.debug.append("placement sketch %s %s selected %s active %s" % (
            value(sub.Name), value(sub.GetTypeName2), sel, sketch is not None))
        sm.AddToDB = True
        try:
            for p in pts:
                if is3d:
                    made = sm.CreatePoint(p[0] * M, p[1] * M, p[2] * M)
                else:
                    q = method(self.math, "CreatePoint", VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8,
                                                                 [p[0] * M, p[1] * M, p[2] * M]))
                    a = list(method(q, "MultiplyTransform", sketch.ModelToSketchTransform).ArrayData)
                    made = sm.CreatePoint(a[0], a[1], 0)
                self.debug.append("point %s made %s" % ([round(x, 3) for x in p], made is not None))
            try:
                self.debug.append("sketch points now %s" % value(sketch.GetSketchPointsCount2))
            except Exception as exc:
                self.debug.append("sketch points not counted (%s)" % str(exc)[:80])
        finally:
            sm.AddToDB = False
            if is3d:
                sm.Insert3DSketch(True)
            else:
                sm.InsertSketch(True)

    # ------------------------------------------------- shell, draft, sweep, loft
    def _select_face(self, p, append, mark):
        x, y, z = p[0] * M, p[1] * M, p[2] * M
        return bool(self.model.Extension.SelectByID2("", "FACE", x, y, z, append, mark, NOTHING, 0))

    def a_shell(self, f):
        ""
        if not f.get("faces"):
            raise TreeUnsupported("%s: shell without removed faces" % f["name"])
        tried = []
        for outward in (bool(f.get("outward")), not f.get("outward")):
            self.clear()
            for i, p in enumerate(f["faces"]):
                if not self._select_face(p, i > 0, 0):
                    raise TreeUnsupported("%s: face %d not found" % (f["name"], i + 1))
            before = self._last_feature()
            self.model.InsertFeatureShell(f["thickness"] * M, outward)
            feat = self._last_feature()
            if feat is None or (before is not None and value(feat.Name) == value(before.Name)):
                tried.append("outward %s: no feature" % outward)
                continue
            got = self._attempt(feat, f)
            if got is True:
                return self._named(feat, f)
            tried.append("outward %s: %s" % (outward, got))
        raise TreeUnsupported("%s: SolidWorks' shell does not give FreeCAD's shape [%s]" % (f["name"], "; ".join(tried)))

    def _last_feature(self):
        try:
            return method(self.model, "FeatureByPositionReverse", 0)
        except Exception:
            return None

    def a_draft(self, f):
        ""
        nt = f.get("neutral")
        if not f.get("faces") or not nt:
            raise TreeUnsupported("%s: draft without faces or neutral plane" % f["name"])
        tried = []
        for flip in (bool(f.get("reversed")), not f.get("reversed")):
            self.clear()
            if nt.get("face"):
                ok = self._select_face(nt["point"], False, 1)
            else:
                ref = self.plane_for({"origin": nt["point"], "z": nt["normal"]})
                ok = bool(ref.Select2(False, 1))
            if not ok:
                raise TreeUnsupported("%s: neutral plane not selected" % f["name"])
            for p in f["faces"]:
                if not self._select_face(p, True, 2):
                    raise TreeUnsupported("%s: draft face not found" % f["name"])
            feat = self.model.FeatureManager.InsertMultiFaceDraft(math.radians(f["angle"]), flip, False, 0,
                                                                   False, False)
            got = self._attempt(feat, f)
            if got is True:
                return self._named(feat, f)
            tried.append("flip %s: %s" % (flip, got))
        raise TreeUnsupported("%s: SolidWorks' draft does not give FreeCAD's shape [%s]" % (f["name"], "; ".join(tried)))

    def a_sweep(self, f):
        ""


        prof, _d, _c = self._profile(f["profile"])
        path, _d2, _c2 = self._profile(f["path"])
        fm = self.model.FeatureManager
        cut = bool(f.get("cut"))
        tried = []

        def select():
            self.clear()
            if not prof.Select2(False, 1) or not path.Select2(True, 4):
                raise TreeUnsupported("%s: profile or path not selected" % f["name"])
            try:
                return method(self.model.SelectionManager, "GetSelectedObjectCount2", -1)
            except Exception:
                return "?"

        def insert(align, direction):
            if cut:
                return fm.InsertCutSwept5(False, align, 0, False, False, 0, 0, False, 0.0, 0.0, 0, 0, True, True,
                                          0.0, False, 0, False, False, False, 0.0, direction)
            return fm.InsertProtrusionSwept4(False, align, 0, False, False, 0, 0, False, 0.0, 0.0, 0, 0, True,
                                             True, True, 0.0, False, False, 0.0, direction)
        for align, direction in ((True, 0), (False, 0), (True, -1), (False, 1)):
            try:
                n = select()
                before = self._last_feature()
                feat = insert(align, direction)
                if feat is None:
                    last = self._last_feature()
                    if last is not None and (before is None or value(last.Name) != value(before.Name)):
                        feat = last
                if feat is None:
                    tried.append("insert align %s dir %s (%s selected): none" % (align, direction, n))
                    continue
                got = self._attempt(feat, f) if f.get("volume") else True
                if got is True:
                    return self._named(feat, f)
                tried.append("insert align %s dir %s: %s" % (align, direction, got))
            except TreeUnsupported:
                raise
            except Exception as exc:
                tried.append("insert align %s dir %s: %s" % (align, direction, str(exc)[:80]))
        try:                                    # swFmSweep = 17, swFmSweepCut = 18
            d = fm.CreateDefinition(18 if cut else 17)
            self.clear()
            d.Profile = prof
            d.Path = path
            feat = fm.CreateFeature(d)
            if feat is not None:
                got = self._attempt(feat, f) if f.get("volume") else True
                if got is True:
                    return self._named(feat, f)
                tried.append("definition: %s" % got)
            else:
                tried.append("definition: none")
        except Exception as exc:
            tried.append("definition: %s" % str(exc)[:80])
        self.debug.append("%s: %s" % (f["name"], "; ".join(tried)))
        raise TreeUnsupported("SolidWorks did not make %s [%s]" % (f["name"], "; ".join(tried)))

    def a_loft(self, f):
        """Additive/subtractive loft -> Lofted Boss/Cut through the profile sketches in order (mark 1)."""
        fm = self.model.FeatureManager
        self.clear()
        for i, name in enumerate(f.get("profiles") or []):
            sk, _d, _c = self._profile(name)
            if not sk.Select2(i > 0, 1):
                raise TreeUnsupported("%s: profile %s not selected" % (f["name"], name))
        closed = bool(f.get("closed"))
        if f.get("cut"):
            feat = fm.InsertCutBlend(closed, False, False, 1.0, 0, 0, False, 0.0, 0.0, 0, True, True)
        else:
            feat = fm.InsertProtrusionBlend2(closed, False, False, 1.0, 0, 0, 1.0, 1.0, True, True, False, 0.0,
                                             0.0, 0, True, True, True, 0)
        return self._named(feat, f)

    def a_rib(self, f):
        ""

        sk, _d, _c = self._profile(f["profile"])
        fm = self.model.FeatureManager
        side = f.get("side", "Both")
        draft = float(f.get("draft") or 0.0)
        tried = []
        for flip in (bool(f.get("flip")), not f.get("flip")):
            self.clear()
            if not sk.Select2(False, 0):
                raise TreeUnsupported("%s: rib sketch not selected" % f["name"])
            before = self._last_feature()
            feat = fm.InsertRib(side == "Both", side == "Second", f["thickness"] * M, 0, flip, draft > 0,
                                bool(f.get("outward")), math.radians(draft),
                                f.get("direction") == "Normal", False)
            if feat is None:            # older InsertRib returns nothing: the newest feature, if new
                feat = self._last_feature()
                if feat is None or (before is not None and value(feat.Name) == value(before.Name)):
                    tried.append("flip %s: no feature" % flip)
                    continue
            got = self._attempt(feat, f)
            if got is True:
                return self._named(feat, f)
            tried.append("flip %s: %s" % (flip, got))
        raise TreeUnsupported("%s: SolidWorks' rib does not give FreeCAD's shape [%s]" % (f["name"], "; ".join(tried)))

    # ------------------------------------------------- dome, variable fillet, wrap, boundary
    def _new_feature(self, before):
        last = self._last_feature()
        if last is None or (before is not None and value(last.Name) == value(before.Name)):
            return None
        return last

    def a_dome(self, f):
        ""
        if not f.get("faces"):
            raise TreeUnsupported("%s: dome without faces" % f["name"])

        # rectangular faces alike (runs 51-53). A dome on one round face is a spherical cap: it is
        # made as a revolve of the cap's profile instead, so the feature tree survives.
        if not f.get("force_api"):
            return self._dome_revolve(f)
        tried = []
        for rev in (bool(f.get("reverse")), not f.get("reverse")):
            self.clear()
            for i, p in enumerate(f["faces"]):
                if not self._select_face(p, i > 0, 0):
                    raise TreeUnsupported("%s: dome face not found" % f["name"])
            before = self._last_feature()
            self.model.InsertDome(f["height"] * M, rev, bool(f.get("elliptical")))
            feat = self._new_feature(before)
            got = self._attempt(feat, f)
            if got is True:
                return self._named(feat, f)
            tried.append("reverse %s: %s" % (rev, got))
        raise TreeUnsupported("%s: SolidWorks' dome does not give FreeCAD's shape [%s]" % (f["name"], "; ".join(tried)))

    @staticmethod
    def _cap_arc(r, h, elliptical):
        """The dome's profile from (r, 0) up to (0, h): a sphere's arc, or for an elliptical dome a
        quarter of the ellipse with half-axes r and h about the face centre."""
        if elliptical and abs(r - h) > 1e-9:
            major, minor = ([r, 0, 0], [0, h, 0]) if r > h else ([0, h, 0], [r, 0, 0])
            return {"kind": "ellipse_arc", "center": [0, 0, 0], "major": major, "minor": minor,
                    "start": [r, 0, 0], "end": [0, h, 0], "ccw": True, "construction": False}
        big = (r * r + h * h) / (2.0 * h) if not elliptical else r
        return {"kind": "arc", "center": [0, h - big, 0], "radius": big, "start": [r, 0, 0],
                "end": [0, h, 0], "ccw": True, "construction": False}

    def _dome_polygon(self, f):
        ""


        poly = f.get("polygon")
        if not poly or poly.get("continuous") or poly.get("point") or poly.get("direction") \
                or f.get("reverse"):
            raise TreeUnsupported("%s: SolidWorks' API cannot make this dome (a plain dome on one face only)"
                                  % f["name"])
        c, n, r, h = poly["center"], _unit(poly["normal"]), float(poly["radius"]), float(f["height"])
        if h <= 0 or r <= 0:
            raise TreeUnsupported("%s: dome without height" % f["name"])
        a = [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0]
        u = _unit([a[i] - _dot(a, n) * n[i] for i in range(3)])
        v = [n[1] * u[2] - n[2] * u[1], n[2] * u[0] - n[0] * u[2], n[0] * u[1] - n[1] * u[0]]
        frame = {"origin": list(c), "x": u, "y": v, "z": n}
        loc = lambda p: [_dot(_sub(p, c), u), _dot(_sub(p, c), v), 0.0]
        geo = []
        for e in poly["outline"]:
            if e["kind"] == "line":
                geo.append({"kind": "line", "start": loc(e["start"]), "end": loc(e["end"]), "construction": False})
            else:
                geo.append({"kind": "arc", "center": loc(e["center"]), "radius": e["radius"], "start": loc(e["start"]),
                            "end": loc(e["end"]), "ccw": _dot(e["axis"], n) > 0, "construction": False})
        base = f["name"] + "-Outline"
        self.a_sketch({"kind": "sketch", "name": base, "frame": frame, "constraints": [], "geometry": geo})
        boss = self.a_extrude({"name": f["name"], "profile": base, "end": "Length", "length": h})
        if boss is None:
            raise TreeUnsupported("%s: the dome's outline extrude was not made" % f["name"])
        z = [u[1] * n[2] - u[2] * n[1], u[2] * n[0] - u[0] * n[2], u[0] * n[1] - u[1] * n[0]]
        big = (r * r + h * h) / (2.0 * h)
        line = lambda p, q, cons=False: {"kind": "line", "start": p, "end": q, "construction": cons}
        top = h + 1.0
        cap = f["name"] + "-Sphere"
        self.a_sketch({"kind": "sketch", "name": cap, "frame": {"origin": list(c), "x": u, "y": n, "z": z},
                       "constraints": [],
                       "geometry": [self._cap_arc(r, h, bool(f.get("elliptical"))),
                                    line([r, 0, 0], [r, top, 0]), line([r, top, 0], [0, top, 0]),
                                    line([0, top, 0], [0, h, 0]),
                                    line([0, -1.0, 0], [0, top + 1.0, 0], True)]})
        feat = self.a_revolve({"name": f["name"] + "-Cap", "profile": cap, "angle": 360.0, "cut": True})
        got = self._attempt(feat, f)
        if got is True:
            self.debug.append("%s: saved as an extrude and a revolved cut (SolidWorks' dome call stops "
                              "SolidWorks)" % f["name"])
            return feat
        self._delete(boss)
        raise TreeUnsupported("%s: the dome extrude and cut do not give FreeCAD's shape (%s)" % (f["name"], got))

    def _dome_revolve(self, f):
        disc = f.get("disc")
        if not disc and f.get("polygon"):
            return self._dome_polygon(f)
        if not disc:
            raise TreeUnsupported("%s: SolidWorks' API cannot make this dome (only a round one, as a revolve)"
                                  % f["name"])
        c, n, r, h = disc["center"], _unit(disc["normal"]), disc["radius"], float(f["height"])
        if h <= 0 or r <= 0:
            raise TreeUnsupported("%s: dome without height" % f["name"])
        rev = bool(f.get("reverse"))
        if rev:
            n = [-x for x in n]
        a = [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0]
        u = _unit([a[i] - _dot(a, n) * n[i] for i in range(3)])
        z = [u[1] * n[2] - u[2] * n[1], u[2] * n[0] - u[0] * n[2], u[0] * n[1] - u[1] * n[0]]
        big = (r * r + h * h) / (2.0 * h)
        line = lambda p, q, cons=False: {"kind": "line", "start": p, "end": q, "construction": cons}
        name = f["name"] + "-Profile"
        sketch = {"kind": "sketch", "name": name, "frame": {"origin": list(c), "x": u, "y": n, "z": z},
                  "constraints": [],
                  "geometry": [line([0, 0, 0], [r, 0, 0]),
                               self._cap_arc(r, h, bool(f.get("elliptical"))),
                               line([0, h, 0], [0, 0, 0]),
                               line([0, -1.0, 0], [0, h + 1.0, 0], True)]}
        self.a_sketch(sketch)
        feat = self.a_revolve({"name": f["name"], "profile": name, "angle": 360.0, "cut": rev})
        got = self._attempt(feat, f)
        if got is True:
            self.debug.append("%s: saved as a revolve (SolidWorks' dome call stops SolidWorks)" % f["name"])
            return feat
        raise TreeUnsupported("%s: the dome revolve does not give FreeCAD's shape (%s)" % (f["name"], got))

    def a_varfillet(self, f):
        ""
        if not f.get("edges"):
            raise TreeUnsupported("%s: variable fillet without edges" % f["name"])
        n_cp = int(f.get("control_points") or 0)
        points = NOTHING
        if n_cp:
            radii_cp = list(f.get("point_radii") or [])
            where = list(f.get("point_positions") or [])
            even = [100.0 * (k + 1) / (n_cp + 1) for k in range(n_cp)]
            if len(radii_cp) != n_cp or any(r <= 0 for r in radii_cp) or \
                    (where and (len(where) != n_cp or any(abs(a - b) > 0.5 for a, b in zip(sorted(where), even)))):
                raise TreeUnsupported("%s: variable fillet control points SolidWorks cannot take (each point needs "
                                      "its own radius, evenly spaced)" % f["name"])
            points = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, [r * M for r in radii_cp] * len(f["edges"]))
        rows = {"edges": [e["points"] for e in f["edges"]], "name": f["name"]}
        r0, r1 = f["start_radius"] * M, f["end_radius"] * M
        tried = []
        for radii in ([r0, r1] * len(f["edges"]), [r1, r0] * len(f["edges"])):
            for options in ((195, 199, 194, 2) if n_cp else (195, 194, 2)):
                try:
                    self._select_edges(rows, 1)
                    arr = VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, radii)
                    before = self._last_feature()
                    feat = self.model.FeatureManager.FeatureFillet3(options, r0, 0, 0, 1, 0, 0, arr, NOTHING, NOTHING,
                                                                    NOTHING, points, NOTHING, NOTHING)
                    feat = feat or self._new_feature(before)
                    if n_cp and feat is not None:
                        have = self._fillet_points(feat, f, n_cp, radii_cp)
                        if have != n_cp:
                            self._delete(feat)
                            tried.append("%s: %s control points, want %d" % (options, have, n_cp))
                            continue
                    got = self._attempt(feat, f)
                    if got is True:
                        return self._named(feat, f)
                    tried.append("%s %s: %s" % (options, [round(x / M, 3) for x in radii[:2]], got))
                except TreeUnsupported:
                    raise
                except Exception as exc:
                    tried.append("%s: %s" % (options, str(exc)[:60]))
        raise TreeUnsupported("%s: SolidWorks' variable fillet does not give FreeCAD's shape [%s]"
                              % (f["name"], "; ".join(tried)))

    def _fillet_points(self, feat, f, n_cp, radii_cp):
        ""

        g = sw_get
        name = f["name"]
        try:
            d = g(feat, "GetDefinition")
            have = int(g(d, "GetControlPointsCount") or 0)
        except Exception as exc:
            self.debug.append("%s: control points not read: %s" % (name, str(exc)[:80]))
            return None
        self.debug.append("%s: FeatureFillet3 made %d control points" % (name, have))
        if have == n_cp:
            return have
        if not getattr(self, "_cp_names_logged", False):
            self._cp_names_logged = True
            try:
                names = [n for n in _tlb_props("IVariableFilletFeatureData2", True)
                         if "ontrol" in n or "Instance" in n or "Point" in n or "Radius" in n]
                self.debug.append("%s: IVariableFilletFeatureData2 %s" % (name, "; ".join(names)[:900]))
            except Exception as exc:
                self.debug.append("%s: tlb not read: %s" % (name, str(exc)[:80]))
        steps = []
        try:
            steps.append("access %s" % g(d, "AccessSelections", self.model, NOTHING))
        except Exception as exc:
            steps.append("access: %s" % str(exc)[:50])
        ole = d._oleobj_
        for nm in ("ControlPointsCount", "NumberOfControlPoints", "ControlPoints", "NumberOfInstances"):
            try:
                ole.Invoke(ole.GetIDsOfNames(nm), 0, pythoncom.DISPATCH_PROPERTYPUT, False, n_cp)
                steps.append("put %s ok" % nm)
            except Exception as exc:
                steps.append("put %s: %s" % (nm, str(exc)[:40]))
        for nm in ("SetControlPointsCount", "SetNumberOfControlPoints"):
            try:
                steps.append("%s %s" % (nm, method(d, nm, n_cp)))
            except Exception as exc:
                steps.append("%s: %s" % (nm, str(exc)[:40]))
        for i, r in enumerate(radii_cp):
            for args in ((i, r * M), (i, r * M, NOTHING)):
                try:
                    steps.append("SetControlPointRadiusAtIndex%d %s" % (len(args), method(
                        d, "SetControlPointRadiusAtIndex", *args)))
                    break
                except Exception as exc:
                    steps.append("SetControlPointRadiusAtIndex%d: %s" % (len(args), str(exc)[:40]))
        try:
            steps.append("modify %s" % g(feat, "ModifyDefinition", d, self.model, NOTHING))
        except Exception as exc:
            steps.append("modify: %s" % str(exc)[:50])
        try:
            have = int(g(g(feat, "GetDefinition"), "GetControlPointsCount") or 0)
        except Exception as exc:
            steps.append("reread: %s" % str(exc)[:50])
        self.debug.append("%s: definition edit %s; now %s control points" % (name, "; ".join(steps)[:700], have))
        return have

    def a_wrap(self, f):
        ""
        sk, _d, _c = self._profile(f["profile"])
        if not f.get("faces"):
            raise TreeUnsupported("%s: wrap without a face" % f["name"])
        kind = {"Emboss": 0, "Deboss": 1, "Scribe": 2}.get(f.get("wrap_type"), 0)
        method = 1 if f.get("method") == "Spline Surface" else 0
        tried = []
        for marks in ((0, 0), (4, 1), (1, 2)):
            for rev in (bool(f.get("reverse")), not f.get("reverse")):
                self.clear()
                if not sk.Select2(False, marks[0]) or not self._select_face(f["faces"][0], True, marks[1]):
                    tried.append("marks %s: not selected" % (marks,))
                    break
                before = self._last_feature()
                try:
                    feat = self.model.FeatureManager.InsertWrapFeature2(kind, f["thickness"] * M, rev, method, 8)
                except Exception as exc:
                    tried.append("marks %s: %s" % (marks, str(exc)[:60]))
                    continue
                feat = feat or self._new_feature(before)
                if feat is None:
                    tried.append("marks %s rev %s: none" % (marks, rev))
                    break
                got = self._attempt(feat, f)
                if got is True:
                    return self._named(feat, f)
                tried.append("marks %s rev %s: %s" % (marks, rev, got))
        raise TreeUnsupported("%s: SolidWorks' wrap does not give FreeCAD's shape [%s]" % (f["name"], "; ".join(tried)))

    def a_boundary(self, f):
        ""

        if f.get("guides"):
            raise TreeUnsupported("%s: boundary with direction 2 curves" % f["name"])
        fm = self.model.FeatureManager
        tried = []
        for order in (list(f.get("profiles") or []), list(f.get("profiles") or [])[::-1]):
            self.clear()
            for i, name in enumerate(order):
                sk, _d, _c = self._profile(name)
                if not sk.Select2(i > 0, 1):
                    raise TreeUnsupported("%s: profile %s not selected" % (f["name"], name))
            if f.get("cut"):
                feat = fm.InsertCutBlend(False, False, False, 1.0, 0, 0, False, 0.0, 0.0, 0, True, True)
            else:
                feat = fm.InsertProtrusionBlend2(False, False, False, 1.0, 0, 0, 1.0, 1.0, True, True, False, 0.0,
                                                 0.0, 0, True, True, True, 0)
            got = self._attempt(feat, f)
            if got is True:
                self.debug.append("%s: saved as a SolidWorks loft (no Boundary in the API)" % f["name"])
                return self._named(feat, f)
            tried.append(str(got))
        raise TreeUnsupported("%s: a loft does not give FreeCAD's boundary shape [%s]" % (f["name"], "; ".join(tried)))

    def a_reference(self, f):
        return None

    def a_plane(self, f):
        return None       # planes are made where a sketch needs one

    def _named(self, feat, f):
        if feat is None:
            raise TreeUnsupported("SolidWorks did not make %s" % f["name"])
        try:
            feat.Name = f["name"]
        except Exception:
            pass
        self.made.setdefault(f.get("group", f["name"]), []).append(feat)
        return feat

    # ---------------------------------------------------------------- patterns
    def _ref_line(self, point, direction, name):
        ""

        sm = self.model.SketchManager
        p = [point[i] * M for i in range(3)]
        q = [(point[i] + 10.0 * direction[i]) * M for i in range(3)]
        sm.Insert3DSketch(True)
        sm.AddToDB = True
        try:
            seg = sm.CreateLine(p[0], p[1], p[2], q[0], q[1], q[2])
        finally:
            sm.AddToDB = False
            sm.Insert3DSketch(True)
        if seg is None:
            raise TreeUnsupported("%s: reference line not made" % name)
        feat = self.model.FeatureByPositionReverse(0)
        try:
            feat.Name = name
        except Exception:
            pass
        return seg, feat

    def _select_line(self, line, mark, append):
        seg, feat = line
        sd = self._select_data(mark)
        if seg.Select4(append, sd):
            return True
        return bool(self.model.Extension.SelectByID2("%s@%s" % (value(seg.GetName), feat.Name), "EXTSKETCHSEGMENT",
                                                     0, 0, 0, append, mark, NOTHING, 0))

    def _select_data(self, mark):
        try:
            sd = value(self.model.SelectionManager.CreateSelectData)
            sd.Mark = mark
            return sd
        except Exception:
            return NOTHING

    def _select_seeds(self, f, mark):
        n = 0
        for name in f["seeds"]:
            for feat in self.made.get(name, []):
                if not feat.Select2(True, mark):
                    raise TreeUnsupported("%s: seed %s not selected" % (f["name"], name))
                n += 1
        if not n:
            raise TreeUnsupported("%s: none of its seed features were made" % f["name"])

    def _delete(self, feat):
        self.clear()
        feat.Select2(False, 0)
        self.model.EditDelete()

    def _volume_ok(self, f):
        want = f.get("volume")
        if not want:
            return True
        return abs(self.volume_mm3() - want) <= 0.005 * want

    def _directions(self, direction, name):
        ""

        try:
            line = self._ref_line([0, 0, 0], direction, name)
            yield (lambda mark, append: self._select_line(line, mark, append)), "3D sketch line"
        except TreeUnsupported:
            pass
        for key, normal in (("front", [0, 0, 1]), ("top", [0, 1, 0]), ("right", [1, 0, 0])):
            d = _dot(direction, normal)
            if abs(abs(d) - 1.0) < 1e-9:
                plane = self.planes[key]
                yield (lambda mark, append, plane=plane: bool(plane.Select2(append, mark))), key + " plane"

    def _selected(self):
        try:
            return int(self.model.SelectionManager.GetSelectedObjectCount2(-1))
        except Exception:
            return -1

    def _linear(self, fm, f, flip1, flip2):
        n2, s2 = f.get("count2", 1), f.get("spacing2", 0.0) * M or 0.01
        feat = None
        try:
            feat = fm.FeatureLinearPattern2(f["count"], f["spacing"] * M, n2, s2, flip1, flip2, "", "", False)
        except Exception:
            feat = None
        if feat is None:
            try:            # newer call: varied instances off, no offsets, spacing (not up to reference)
                feat = fm.FeatureLinearPattern5(f["count"], f["spacing"] * M, n2, s2, flip1, flip2, "", "",
                                                False, False, False, False, False, False, True, 0, NOTHING,
                                                False, 0, NOTHING, False)
            except Exception:
                feat = None
        return feat

    def _attempt(self, feat, f):
        ""
        if feat is None:
            return "no feature made"
        if self._volume_ok(f):
            return True
        got = self.volume_mm3()
        self._delete(feat)
        return "volume %.3f, FreeCAD %.3f" % (got, f.get("volume", 0))

    def _axes(self, line, name):
        ""

        try:
            seg = self._ref_line(line["point"], line["dir"], name)
            yield (lambda mark, append: self._select_line(seg, mark, append)), "3D sketch line"
        except TreeUnsupported:
            pass
        axes = ([1, 0, 0], [0, 1, 0], [0, 0, 1])
        d = line["dir"]
        if any(abs(abs(_dot(d, a)) - 1.0) < 1e-9 for a in axes):
            try:
                others = [a for a in axes if abs(_dot(d, a)) < 1e-9]
                planes = [self.plane_for({"origin": line["point"], "z": a}) for a in others]
                self.clear()
                planes[0].Select2(False, 0)
                planes[1].Select2(True, 0)
                if self.model.InsertAxis2(True):
                    axis = self.model.FeatureByPositionReverse(0)
                    try:
                        axis.Name = name
                    except Exception:
                        pass
                    yield (lambda mark, append: bool(axis.Select2(append, mark))), "reference axis"
            except Exception:
                pass

    def _circular(self, fm, count, step, flip):
        for call in (lambda: fm.FeatureCircularPattern4(count, step, flip, "", False, False, False),
                     lambda: fm.FeatureCircularPattern5(count, step, flip, "", False, False, False, False,
                                                        False, False, 1, 0.0, "", False),
                     lambda: fm.FeatureCircularPattern2(count, step, flip, "", False)):
            try:
                feat = call()
            except Exception:
                feat = None
            if feat is not None:
                return feat
        return None

    def a_pattern(self, f):
        kind = f.get("pattern")
        if f.get("whole") and kind != "mirror":
            raise TreeUnsupported("%s: whole-shape patterns are not made yet" % f["name"])
        fm = self.model.FeatureManager
        if kind == "linear":
            if not f.get("direction"):
                raise TreeUnsupported("%s: pattern direction not found" % f["name"])
            tried = []
            d2s = [None]
            if f.get("count2", 1) > 1:
                if not f.get("direction2"):
                    raise TreeUnsupported("%s: second direction not found" % f["name"])
                d2s = list(self._directions(f["direction2"], f["name"] + " Direction2"))
            for d1 in self._directions(f["direction"], f["name"] + " Direction"):
                for d2 in d2s:
                    flips2 = (bool(f.get("reversed2")), not f.get("reversed2")) if d2 else (False,)
                    for flip1 in (bool(f.get("reversed")), not f.get("reversed")):
                        for flip2 in flips2:
                            self.clear()
                            sel = [d1[0](1, False), d2[0](2, True) if d2 else True]
                            self._select_seeds(f, 4)
                            count = self._selected()
                            feat = self._linear(fm, f, flip1, flip2)
                            got = self._attempt(feat, f)
                            if got is True:
                                return self._named(feat, f)
                            tried.append("%s%s flip %d: %s (direction selected %s, %d selected)"
                                         % (d1[1], "/" + d2[1] if d2 else "", flip1, got, sel, count))
            raise TreeUnsupported("%s: SolidWorks' linear pattern does not give FreeCAD's shape [%s]"
                                  % (f["name"], "; ".join(tried)))
        if kind == "circular":
            line = f.get("axis_line")
            if not line:
                raise TreeUnsupported("%s: pattern axis not found" % f["name"])
            step = math.radians(f["step"])
            tried = []
            for select, label in self._axes(line, f["name"] + " Axis"):
                for flip in (bool(f.get("reversed")), not f.get("reversed")):
                    self.clear()
                    sel = select(1, False)
                    self._select_seeds(f, 4)
                    count = self._selected()
                    feat = self._circular(fm, f["count"], step, flip)
                    got = self._attempt(feat, f)
                    if got is True:
                        return self._named(feat, f)
                    tried.append("%s flip %d: %s (axis selected %s, %d selected)" % (label, flip, got, sel, count))
            raise TreeUnsupported("%s: SolidWorks' circular pattern does not give FreeCAD's shape [%s]"
                                  % (f["name"], "; ".join(tried)))
        if kind == "mirror":
            plane = f.get("plane")
            if not plane:
                raise TreeUnsupported("%s: mirror plane not found" % f["name"])
            ref = self.plane_for({"origin": plane["point"], "z": plane["normal"]})
            self.clear()
            ref.Select2(False, 2)
            whole = bool(f.get("whole"))
            if whole:
                for body in self.model.GetBodies2(0, True) or ():
                    body.Select2(True, self._select_data(1))
            else:
                self._select_seeds(f, 1)
            try:
                feat = fm.InsertMirrorFeature2(whole, False, whole, False, 0)
            except Exception:
                feat = fm.InsertMirrorFeature(whole, False, whole, False)
            got = self._attempt(feat, f)
            if got is not True:
                raise TreeUnsupported("%s: SolidWorks' mirror does not give FreeCAD's shape [%s]" % (f["name"], got))
            return self._named(feat, f)
        raise TreeUnsupported("%s: %s patterns are not made yet" % (f["name"], kind))

    def build(self):
        self.s.toggle_off("swInputDimValOnCreate")
        for f in self.data["features"]:
            fn = getattr(self, "a_" + f.get("kind", "unsupported"), None)
            if fn is None:
                raise TreeUnsupported("%s (%s) has no SolidWorks counterpart here" % (f["name"], f.get("type")))
            fn(f)
            if f.get("kind") not in ("sketch", "plane", "reference") and not self._volume_ok(f):
                raise TreeUnsupported("after %s SolidWorks has %.1f mm3, FreeCAD %.1f"
                                      % (f["name"], self.volume_mm3(), f["volume"]))
        self.model.ForceRebuild3(False)

    def volume_mm3(self):
        mp = self.model.Extension.CreateMassProperty
        return mp.Volume * 1e9


def job_save_tree(s, args):
    ""

    data = json.load(open(args[0], encoding="utf-8"))
    return save_tree(s, data, os.path.abspath(args[1]), os.path.abspath(args[2]))


def save_tree(s, data, step, out):
    want = data.get("volume")
    reason, tb = None, None
    try:
        tb = TreeBuilder(s, data)
        try:
            tb.build()
            got = tb.volume_mm3()
            if want and abs(got - want) > 0.005 * want:
                raise TreeUnsupported("SolidWorks' features give %.1f mm3, FreeCAD has %.1f" % (got, want))
            warnings = s.save_as(tb.model, out)
            return {"file": out, "how": "tree", "warnings": warnings, "debug": tb.debug}
        finally:
            s.close(tb.model)
    except TreeUnsupported as exc:
        reason = str(exc)
    res = save_part(s, step, out)
    res.update(how="solid", tree_not_saved=reason, debug=tb.debug if tb is not None else None)
    return res



def _enum_names(s, prefix, pattern=None):
    """{value: name without prefix}; pattern (a regular expression on the rest) keeps one enum
    apart from others sharing the prefix (swMateCOINCIDENT, not swMaterialModifier_None)."""
    import re
    s.c("")                                  # loads the constants
    return {v: k[len(prefix):] for k, v in (s._c or {}).items()
            if k.startswith(prefix) and (pattern is None or re.fullmatch(pattern, k[len(prefix):]))}


def job_mates(s, args):
    ""

    path = os.path.abspath(args[0])
    if s.is_open(path):
        raise RuntimeError("%s is open in SolidWorks; its mates were not read" % os.path.basename(path))
    err, warn = byref_int(), byref_int()
    model = s.sw.OpenDoc6(path, 2, 1 | 2, "", err, warn)       # swDocASSEMBLY, silent + read-only
    if model is None:
        raise RuntimeError("SolidWorks could not open %s (error %s)" % (os.path.basename(path), err.value))
    s.opened.append(model.GetTitle)
    types = _enum_names(s, "swMate", "[A-Z]+")
    refs = _enum_names(s, "swMateEntity2ReferenceType_")
    out, fixed, errors = [], [], []
    try:
        for c in value(model.GetComponents(False)) or ():
            try:
                if value(c.IsFixed):
                    fixed.append(c.Name2)
            except Exception:
                pass
        f = model.FirstFeature
        while f is not None:
            if f.GetTypeName2 == "MateGroup":
                sub = f.GetFirstSubFeature
                while sub is not None:
                    try:
                        out.append(_mate_row(sub, types, refs))
                    except Exception as exc:
                        errors.append("%s: %s" % (sub.Name, exc))
                    sub = sub.GetNextSubFeature
            f = f.GetNextFeature
    finally:
        s.close(model)
    return {"mates": out, "fixed": fixed, "errors": errors}


def _mate_row(feat, types, refs):
    mate = method(feat, "GetSpecificFeature2")
    row = {"name": feat.Name, "type": types.get(mate.Type, str(mate.Type)), "align": value(mate.Alignment),
           "flipped": bool(value(mate.Flipped)), "entities": []}
    try:
        row["suppressed"] = bool(feat.IsSuppressed2(1, NOTHING)[0])
    except Exception:
        try:
            row["suppressed"] = bool(value(feat.IsSuppressed))
        except Exception:
            row["suppressed"] = False
    for get in (lambda: method(method(mate, "DisplayDimension2", 0), "GetDimension2", 0),
                lambda: method(value(mate.DisplayDimension2(0)), "GetDimension2", 0),
                lambda: method(method(feat, "GetFirstDisplayDimension"), "GetDimension2", 0)):
        try:
            dim = get()
            if dim is not None:
                row["value"] = float(value(dim.SystemValue))      # metres or radians
                break
        except Exception:
            continue
    for i in range(2):
        try:
            e = mate.MateEntity(i)
        except Exception:
            break
        if e is None:
            break
        p = list(value(e.EntityParams))
        comp = method(e, "ReferenceComponent")
        try:                                    # swMateEntity2ReferenceType_e; ReferenceType2 is the select type
            kind = value(e.ReferenceType)
        except Exception:
            kind = method(e, "ReferenceType")
        ent = {"component": comp.Name2 if comp is not None else None,
               "ref": refs.get(kind, str(kind)),
               "point": [x / M for x in p[0:3]], "dir": p[3:6],
               "radius": p[6] / M if len(p) > 6 else 0.0, "radius2": p[7] / M if len(p) > 7 else 0.0}
        try:
            ent["sel"] = value(method(e, "Reference").GetType)
        except Exception:
            pass
        row["entities"].append(ent)
    return row


def job_modify(s, args):
    ""

    path = os.path.abspath(args[0])
    pairs = [(args[i], float(args[i + 1])) for i in range(1, len(args) - 1, 2)]
    model, mine = s.open_part(path, read_only=False)
    try:
        edits, dims = [], []
        for name, mm in pairs:
            feat = method(model, "FeatureByName", name)
            if feat is None and len(pairs) == 1:    # else the first extrude
                f = method(model, "FirstFeature")
                while f is not None and str(value(f.GetTypeName2)) != "Extrusion":
                    f = method(f, "GetNextFeature")
                feat = f
            if feat is None:
                if len(pairs) == 1:
                    raise RuntimeError("no feature %s in %s" % (name, os.path.basename(path)))
                edits.append({"feature": name, "error": "no such feature"})
                continue
            try:
                dim = method(method(feat, "GetFirstDisplayDimension"), "GetDimension2", 0)
                old = float(value(dim.SystemValue)) * 1000.0
                dim.SystemValue = mm / 1000.0
                edits.append({"feature": str(value(feat.Name)), "type": str(value(feat.GetTypeName2)),
                              "old_mm": old})
                dims.append((edits[-1], dim))
            except Exception as exc:
                if len(pairs) == 1:
                    raise
                edits.append({"feature": name, "error": str(exc)[:200]})
        value(model.EditRebuild3)
        for row, dim in dims:
            row["new_mm"] = float(value(dim.SystemValue)) * 1000.0
        err, warn = byref_int(), byref_int()
        if not model.Save3(1, err, warn) or err.value:            # swSaveAsOptions_Silent
            raise RuntimeError("SolidWorks could not save %s (error %s)" % (os.path.basename(path), err.value))
        if len(pairs) == 1 and "error" not in edits[0]:
            return {"feature": edits[0]["feature"], "old_mm": edits[0]["old_mm"], "new_mm": edits[0]["new_mm"]}
        return {"edits": edits}
    finally:
        if mine:
            s.close(model)


DUMP_IFACES = {"SweepThread": "IThreadFeatureData", "Thread": "IThreadFeatureData"}


def _tlb_props(iface, with_args=False):
    ""

    import glob
    paths = [p for r in (r"C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS",
                         r"C:\\Program Files\\SolidWorks Corp\\SolidWorks")
             for p in [os.path.join(r, "sldworks.tlb")] if os.path.exists(p)]
    if not paths:
        paths = glob.glob(r"C:\\Program Files\\**\\sldworks.tlb", recursive=True)[:1]
    tl = pythoncom.LoadTypeLib(paths[0])
    for i in range(tl.GetTypeInfoCount()):
        if tl.GetDocumentation(i)[0] != iface:
            continue
        ti = tl.GetTypeInfo(i)
        ta = ti.GetTypeAttr()
        names = []
        for k in range(ta.cFuncs):
            fd = ti.GetFuncDesc(k)
            if fd.args and not with_args:
                continue
            got = ti.GetNames(fd.memid)
            nm = "%s(%s)/%d" % (got[0], ",".join(got[1:]), fd.invkind) if with_args else got[0]
            if nm not in names:
                names.append(nm)
        return names
    return []


def _plain(v, depth=0):
    if isinstance(v, (int, float, str, bool, type(None))):
        return v
    if isinstance(v, (tuple, list)):
        return [_plain(x, depth + 1) for x in v][:64]
    out = {"_com": repr(v)[:60]}
    if depth < 1:
        for nm in ("GetCurveParams3", "GetCurve", "GetTypeName2", "Name"):
            try:
                r = method(v, nm) if nm.startswith("Get") and nm != "GetTypeName2" else getattr(v, nm)
                if nm == "GetCurve":
                    c = r
                    out["circle"] = list(method(c, "CircleParams")) if method(c, "IsCircle") else None
                    out["line"] = list(method(c, "LineParams")) if method(c, "IsLine") else None
                else:
                    out[nm] = _plain(value(r), depth + 1)
            except Exception as exc:
                out[nm] = "error: %s" % str(exc)[:60]
    return out


def job_dump_feature(s, args):
    """Diagnostics: every no-argument property of a feature's definition (GetDefinition), by
    type information or else by the interface's names in sldworks.tlb, for features the tree
    export does not read yet (threads)."""
    path, name = os.path.abspath(args[0]), args[1]
    model, mine = s.open_part(path)
    try:
        feat = method(model, "FeatureByName", name)
        if feat is None:
            raise RuntimeError("no feature %s" % name)
        t = str(value(feat.GetTypeName2))
        out = {"feature": name, "type": t}
        d = method(feat, "GetDefinition")
        props = {}
        try:
            names = _tlb_props(args[2] if len(args) > 2 else DUMP_IFACES.get(t, ""))
        except Exception as exc:
            names, props["_tlb_error"] = [], str(exc)[:200]
        try:
            method(d, "AccessSelections", model, NOTHING)
            props["_access"] = True
        except Exception as exc:
            props["_access"] = "error: %s" % str(exc)[:60]
        ole = d._oleobj_
        for nm in names:
            if nm in ("AccessSelections", "ReleaseSelectionAccess"):
                continue
            try:
                dispid = ole.GetIDsOfNames(nm)
            except Exception:
                continue
            for how in (pythoncom.DISPATCH_PROPERTYGET, pythoncom.DISPATCH_METHOD):
                try:
                    v = ole.Invoke(dispid, 0, how, True)
                    if isinstance(v, pythoncom.TypeIIDs[pythoncom.IID_IDispatch]):
                        v = win32com.client.dynamic.Dispatch(v)
                    props[nm] = _plain(v)
                    break
                except Exception as exc:
                    props[nm] = "error: %s" % str(exc)[:60]
        try:
            method(d, "ReleaseSelectionAccess")
        except Exception:
            pass
        out["definition"] = props
        out["dimensions"] = []
        try:
            dd = method(feat, "GetFirstDisplayDimension")
            while dd is not None and len(out["dimensions"]) < 20:
                dim = method(dd, "GetDimension2", 0)
                out["dimensions"].append([str(value(dim.FullName)), value(dim.Value) if not callable(dim.Value) else None])
                dd = method(feat, "GetNextDisplayDimension", dd)
        except Exception as exc:
            out["dimensions"].append("error: %s" % str(exc)[:80])
        return out
    finally:
        if mine:
            s.close(model)


JOBS = {"probe": job_probe, "tree": job_tree, "mates": job_mates, "save-part": job_save_part,
        "save-asm": job_save_asm, "save-tree": job_save_tree, "export-step": job_export_step,
        "modify": job_modify, "dump-feature": job_dump_feature}


try:                                    # assemblies with patterns, folders, advanced mates (swasm.py)
    import swasm
    JOBS.update(swasm.JOBS)
except Exception as _exc:               # noqa: BLE001
    if __name__ == "__main__":
        print("swasm not loaded:", _exc)


def main(argv):
    if len(argv) < 3 or argv[1] not in JOBS:
        print(__doc__)
        return 2
    job, result_path, args = argv[1], argv[2], argv[3:]
    result = {"ok": False}
    session = None
    try:
        session = Session()
        result.update(JOBS[job](session, args))
        result["ok"] = True
    except Exception as exc:
        traceback.print_exc()
        result["error"] = str(exc) or exc.__class__.__name__
    finally:
        if session is not None:
            session.finish()
            if session.notes:
                result["notes"] = session.notes
        with open(result_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
