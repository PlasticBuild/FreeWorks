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
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets

GROUP = "Flat-Pattern"
TITLE = "Flat-Pattern"
SLIT = 0.1          # slit width, mm
V = App.Vector
_LAST = None        # the open Flat-Pattern PropertyManager


def _doc_default(obj, text):
    try:
        from . import optionspages
        return bool(optionspages.doc_value(obj.Document, "Sheet Metal", text, True))
    except Exception:
        return True


def ensure(obj):
    """The Flat-Pattern's PropertyManager settings (also on a Flat-Pattern from an older file)."""
    add = obj.addProperty
    if not hasattr(obj, "MergeFaces"):
        add("App::PropertyVector", "FixedPoint", GROUP, "Fixed face: a point on it (folded part)")
        add("App::PropertyVector", "FixedNormal", GROUP, "Fixed face: its normal (zero: the Base Flange's)")
        add("App::PropertyBool", "MergeFaces", GROUP, "Merge the bend regions' faces with the flat walls")
        add("App::PropertyBool", "SimplifyBends", GROUP, "Curved edges in the bend regions become straight")
        add("App::PropertyBool", "ShowSlit", GROUP, "A slit at each end of every bend line")
        add("App::PropertyBool", "CornerTreatment", GROUP, "Clean the flat's corners")
        add("App::PropertyVector", "GrainDirection", GROUP, "Grain direction (zero: none)")
        add("App::PropertyVectorList", "ExcludePoints", GROUP, "Faces to Exclude: a point on each")
        obj.MergeFaces = True
        # Document Properties > Sheet Metal: Simplify bends and Corner treatment are the defaults of a new flat
        obj.SimplifyBends, obj.CornerTreatment = _doc_default(obj, "Simplify bends"), _doc_default(obj, "Corner treatment")
        for n in ("FixedPoint", "FixedNormal", "GrainDirection", "ExcludePoints"):
            obj.setEditorMode(n, 2)
    if not hasattr(obj, "FixedRef"):
        # the picked faces themselves, as links FreeCAD renames with the part: a point on a face is
        # lost when an edit moves the face (a longer base flange moves the flange wall), and the flat
        # then fell back to the Base Flange's face without a word
        add("App::PropertyLinkSubGlobal", "FixedRef", GROUP, "Fixed face as picked")
        add("App::PropertyLinkSubListGlobal", "ExcludeRefs", GROUP, "Faces to Exclude as picked, in order")
        obj.setEditorMode("FixedRef", 2)
        obj.setEditorMode("ExcludeRefs", 2)


# ================================================================ engine hooks
def _flat_refs(value):
    out = []
    for item in list(value or []):
        src, subs = item
        for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
            out.append((src, sub))
    return out


def _point_on(src, sub):
    """(a point inside, normal) of the face src.sub now, or None."""
    from .smnormalcut import inside_point
    try:
        name = sub.split(".")[-1]
        if not name or name.startswith("?"):
            return None
        face = src.Shape.getElement(name)
        if face.Surface.TypeId != "Part::GeomPlane":
            return None
        return inside_point(face), face.normalAt(0, 0)
    except Exception:
        return None


def follow(obj):
    """FixedPoint / FixedNormal and ExcludePoints from the picked faces as they are now (FixedRef,
    ExcludeRefs), so the picks stay on their faces when an edit before the flat moves them."""
    if not hasattr(obj, "FixedRef"):
        return
    try:
        ref = obj.FixedRef
        if ref is not None and ref[1]:
            got = _point_on(ref[0], ref[1][0])
            if got is not None:
                p, n = got
                if (p - obj.FixedPoint).Length > 1e-9 or (n - obj.FixedNormal).Length > 1e-9:
                    obj.FixedPoint, obj.FixedNormal = p, n
        refs = _flat_refs(obj.ExcludeRefs)
        pts = list(obj.ExcludePoints)
        if refs and len(refs) == len(pts):
            new = []
            for (src, sub), p in zip(refs, pts):
                got = _point_on(src, sub)
                new.append(got[0] if got is not None else p)
            if any((a - b).Length > 1e-9 for a, b in zip(new, pts)):
                obj.ExcludePoints = new
    except Exception as _fw_err:
        _fw_log("smflatpm.py:follow", _fw_err)


def fixed(obj, tip_shape):
    """The picked fixed face on the part, or None for the default."""
    from .smflatten import _plane_face
    n = getattr(obj, "FixedNormal", V())
    if n.Length < 1e-9:
        return None
    return _plane_face(tip_shape, n, obj.FixedPoint)


def shape_for(obj, tip, thickness):
    """The part the flat is made from: without the Faces to Exclude (and the sheet behind them)."""
    pts = list(getattr(obj, "ExcludePoints", []) or [])
    if not pts or not thickness:
        return tip
    from .smnormalcut import face_at, outward
    from .smflatten import _Part
    shape = tip.Shape
    cuts = []
    for p in pts:
        i = face_at(shape, p)
        if i is None:
            continue
        f = shape.Faces[i]
        cuts.append(f.extrude(outward(shape, f) * -float(thickness)))
    if not cuts:
        return tip
    out = shape.cut(Part.makeCompound(cuts)).removeSplitter()
    keep = obj.FixedPoint if getattr(obj, "FixedNormal", V()).Length > 1e-9 else None
    solids = out.Solids
    if len(solids) > 1:
        pick = None
        if keep is not None:
            pick = min(solids, key=lambda s: s.distToShape(Part.Vertex(keep))[0])
        out = pick or max(solids, key=lambda s: s.Volume)
    return _Part(tip, out)


def _clean(wire, simplify, corners, tol):
    """The wire with curved non-arc edges straightened and tiny edges dropped; None when nothing changes."""
    wire = Part.Wire(Part.__sortEdges__(wire.Edges))
    vs = [v.Point for v in wire.OrderedVertexes]
    edges = wire.OrderedEdges
    if len(vs) == len(edges):
        vs.append(vs[0])
    changed = False
    out = []          # (kind, edge or (a, b))
    for i, e in enumerate(edges):
        a, b = vs[i], vs[i + 1]
        kind = e.Curve.TypeId
        if simplify and kind not in ("Part::GeomLine", "Part::GeomCircle") and (a - b).Length > 1e-7:
            out.append(["line", a, b])
            changed = True
        elif kind == "Part::GeomLine":
            out.append(["line", a, b])
        else:
            out.append(["edge", e])
    if corners and len(out) > 3:
        # drop a tiny line between two lines: its neighbours meet at its middle
        i = 0
        while i < len(out) and len(out) > 3:
            cur = out[i]
            prev, nxt = out[i - 1], out[(i + 1) % len(out)]
            if cur[0] == "line" and (cur[1] - cur[2]).Length < tol and prev[0] == "line" and nxt[0] == "line":
                m = (cur[1] + cur[2]) * 0.5
                prev[2], nxt[1] = m, m
                del out[i]
                changed = True
                continue
            i += 1
        # merge straight runs
        i = 0
        while i < len(out) and len(out) > 3:
            cur, nxt = out[i], out[(i + 1) % len(out)]
            if cur[0] == nxt[0] == "line":
                d1, d2 = cur[2] - cur[1], nxt[2] - nxt[1]
                if d1.Length > 1e-9 and d2.Length > 1e-9 and d1.normalize().cross(d2.normalize()).Length < 1e-7:
                    cur[2] = nxt[2]
                    del out[(i + 1) % len(out)]
                    changed = True
                    continue
            i += 1
    if not changed:
        return None
    made = [Part.LineSegment(o[1], o[2]).toShape() if o[0] == "line" else o[1] for o in out
            if o[0] != "line" or (o[1] - o[2]).Length > 1e-9]
    return Part.Wire(Part.__sortEdges__(made))


def _slits(folds, thickness):
    cuts = []
    t = float(thickness)
    for e in folds.Edges if folds is not None and not folds.isNull() else []:
        if e.Curve.TypeId != "Part::GeomLine" or e.Length < 4 * SLIT:
            continue
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        d = (b - a).normalize()
        L = min(t, e.Length / 4)
        for p, s in ((a, d), (b, d * -1)):
            cuts.append((p, s, L))
    return cuts


def finish(obj, shape, folds, normal, point, thickness):
    """The flat after Merge faces, Simplify bends, Corner treatment and Show slit."""
    if not hasattr(obj, "MergeFaces"):
        return shape
    from .smflatten import _plane_face
    from .smnormalcut import outward
    if obj.MergeFaces:
        try:
            shape = shape.removeSplitter()
        except Exception as _fw_err:
            _fw_log("smflatpm.py:176", _fw_err)
    t = float(thickness or 0)
    if t and (obj.SimplifyBends or obj.CornerTreatment) and len(shape.Solids) == 1:
        name = _plane_face(shape, normal, point)
        if name:
            f = shape.getElement(name)
            wires = [_clean(w, obj.SimplifyBends, obj.CornerTreatment, min(0.01, t * 0.005)) for w in f.Wires]
            if any(w is not None for w in wires):
                ws = [n if n is not None else o for n, o in zip(wires, f.Wires)]
                try:
                    face = Part.Face(ws, "Part::FaceMakerBullseye")
                    solid = face.extrude(outward(shape, f) * -t)
                    if solid.isValid() and solid.Volume > 0:
                        shape = solid.removeSplitter() if obj.MergeFaces else solid
                except Exception as e:
                    App.Console.PrintWarning("Flat-Pattern: corners not cleaned (%s)\n" % e)
    if t and obj.ShowSlit:
        n = V(normal).normalize()
        boxes = []
        for p, d, L in _slits(folds, t):
            w = d.cross(n).normalize() * (SLIT / 2)
            low = p - n * (2 * t)
            corners = [low - w, low + d * L - w, low + d * L + w, low + w]
            boxes.append(Part.Face(Part.makePolygon(corners + corners[:1])).extrude(n * (4 * t)))
        if boxes:
            shape = shape.cut(Part.makeCompound(boxes))
    return shape


def grain(obj):
    g = getattr(obj, "GrainDirection", V())
    return V(g).normalize() if g.Length > 1e-9 else None


# ================================================================ PropertyManager
def _check(name, text, on):
    b = QtWidgets.QCheckBox(text)
    b.setObjectName(name)
    b.setChecked(bool(on))
    return b


class Panel:
    """The Flat-Pattern PropertyManager."""

    def __init__(self, fp):
        from .smunfold import _list, _DeleteKey
        from .smbaseflange import _box
        from .smedgeflange import error_label
        from . import smflatten
        global _LAST
        _LAST = self
        ensure(fp)
        self.fp = fp
        self.was_flat = bool(fp.SWFlattened)
        if self.was_flat:
            smflatten.set_flat(fp.Body, False)      # picks are made on the folded part
        self.saved = {n: getattr(fp, n) for n in ("FixedPoint", "FixedNormal", "MergeFaces", "SimplifyBends",
                                                  "ShowSlit", "CornerTreatment", "GrainDirection", "ExcludePoints")}
        par = _box("Parameters")
        f = par.layout()
        f.addRow(QtWidgets.QLabel("Fixed face:"))
        self.face = _list("SWSMFlatFixedFace", "#d6ecff", "Fixed face: the face that stays where it is")
        f.addRow(self.face)
        self.merge = _check("SWSMFlatMergeFaces", "Merge faces", fp.MergeFaces)
        self.simplify = _check("SWSMFlatSimplifyBends", "Simplify bends", fp.SimplifyBends)
        self.slit = _check("SWSMFlatShowSlit", "Show slit", fp.ShowSlit)
        for w in (self.merge, self.simplify, self.slit):
            f.addRow(w)
        self.recreate = QtWidgets.QPushButton("Recreate flat pattern")
        self.recreate.setObjectName("SWSMFlatRecreate")
        self.recreate.clicked.connect(self.recreate_flat)
        f.addRow(self.recreate)
        self.error = error_label()
        f.addRow(self.error)
        par.setProperty("swstyle_pm_title", TITLE)
        par.setProperty("swstyle_pm_icon", "SheetMetal_Unfold")
        cor = _box("Corner Options")
        self.corner = _check("SWSMFlatCornerTreatment", "Corner treatment", fp.CornerTreatment)
        cor.layout().addRow(self.corner)
        gr = _box("Grain Direction")
        self.grain = _list("SWSMFlatGrain", "#e6e6e6", "Grain direction: a straight edge")
        gr.layout().addRow(self.grain)
        ex = _box("Faces to Exclude")
        self.exclude = _list("SWSMFlatExclude", "#ffd6ec", "Faces to Exclude", rows=3)
        ex.layout().addRow(self.exclude)
        self.form = [par, cor, gr, ex]
        if fp.FixedNormal.Length > 1e-9:
            self.face.addItem("Face <1>")
        if fp.GrainDirection.Length > 1e-9:
            self.grain.addItem("Edge <1>")
        for k, _p in enumerate(fp.ExcludePoints, 1):
            self.exclude.addItem("Face <%d>" % k)
        for w, n in ((self.merge, "MergeFaces"), (self.simplify, "SimplifyBends"), (self.slit, "ShowSlit"),
                     (self.corner, "CornerTreatment")):
            w.toggled.connect(lambda on, n=n: self._set(n, on))
        self.keys = _DeleteKey(self)
        self.lists = (self.face, self.grain, self.exclude)
        for w in self.lists:
            w.installEventFilter(self.keys)
        self.active = self.face
        self._mark()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)

    # ---------------------------------------------------------------- lists
    def set_active(self, w):
        if w in self.lists:
            self.active = w
            self._mark()

    def _mark(self):
        for w in self.lists:
            w.setFrameShape(QtWidgets.QFrame.Box if w is self.active else QtWidgets.QFrame.StyledPanel)

    def remove_current(self, w):
        fp = self.fp
        if w is self.face:
            fp.FixedNormal, fp.FixedPoint = V(), V()
            if hasattr(fp, "FixedRef"):
                fp.FixedRef = None
            self.face.clear()
        elif w is self.grain:
            fp.GrainDirection = V()
            self.grain.clear()
        elif w is self.exclude and w.currentRow() >= 0:
            pts = list(fp.ExcludePoints)
            refs = _flat_refs(getattr(fp, "ExcludeRefs", None))
            if len(refs) == len(pts):
                del refs[w.currentRow()]
                fp.ExcludeRefs = refs
            elif hasattr(fp, "ExcludeRefs"):
                fp.ExcludeRefs = []          # (an older flat's points: they go on as points)
            del pts[w.currentRow()]
            fp.ExcludePoints = pts
            self._relist()

    def _relist(self):
        self.exclude.clear()
        for k, _p in enumerate(self.fp.ExcludePoints, 1):
            self.exclude.addItem("Face <%d>" % k)

    def _set(self, name, on):
        setattr(self.fp, name, on)

    # ---------------------------------------------------------------- picks
    def addSelection(self, doc, name, sub, point):
        at = App.Vector(*point) if point else None
        QtCore.QTimer.singleShot(0, lambda: self.pick(doc, name, sub, at))

    def pick(self, doc_name, name, sub, at=None):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("smflatpm.py:322", _fw_err)
        obj = App.getDocument(doc_name).getObject(name)
        if obj is None or obj.Shape.isNull() or not sub:
            return
        el = obj.Shape.getElement(sub)
        self.error.setText("")
        fp = self.fp
        if self.active is self.grain:
            if not sub.startswith("Edge") or el.Curve.TypeId != "Part::GeomLine":
                return self._err("The grain direction must be a straight edge.")
            fp.GrainDirection = el.Vertexes[-1].Point - el.Vertexes[0].Point
            self.grain.clear()
            self.grain.addItem("Edge <1>")
            return
        if not sub.startswith("Face"):
            return
        from .smnormalcut import inside_point
        p = at if at is not None else inside_point(el)
        if self.active is self.face:
            if el.Surface.TypeId != "Part::GeomPlane":
                return self._err("The fixed face must be a flat face.")
            fp.FixedPoint, fp.FixedNormal = p, el.normalAt(0, 0)
            if hasattr(fp, "FixedRef"):
                fp.FixedRef = (obj, [sub])
            self.face.clear()
            self.face.addItem("Face <1>")
            self.set_active(self.exclude)
        else:
            refs = _flat_refs(getattr(fp, "ExcludeRefs", None))
            if hasattr(fp, "ExcludeRefs") and len(refs) == len(fp.ExcludePoints):
                fp.ExcludeRefs = refs + [(obj, sub)]
            fp.ExcludePoints = list(fp.ExcludePoints) + [p]
            self._relist()

    def _err(self, text):
        self.error.setText(text)
        self.error.show()

    def recreate_flat(self):
        from . import smflatten
        smflatten.set_flat(self.fp.Body, True)
        self.fp.touch()
        self.fp.Document.recompute()
        ok = "Invalid" not in self.fp.State and not self.fp.Shape.isNull()
        if not ok:
            self._err("The flat pattern cannot be made with these settings.")
        smflatten.set_flat(self.fp.Body, False)
        return ok

    # ---------------------------------------------------------------- OK / Cancel
    def _close(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("smflatpm.py:371", _fw_err)
        from . import smflatten
        self.fp.touch()
        smflatten.set_flat(self.fp.Body, self.was_flat)
        self.fp.Document.recompute()
        Gui.Control.closeDialog()

    def accept(self):
        self._close()
        return True

    def reject(self):
        for n, v in self.saved.items():
            setattr(self.fp, n, v)
        self._close()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel


def edit(fp):
    Gui.Control.closeDialog()
    Gui.Control.showDialog(Panel(fp))
