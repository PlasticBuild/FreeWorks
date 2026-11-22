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
from PySide import QtWidgets

from . import boundarysurface as bs
from . import naming
from . import simplefeature as sf

V = App.Vector
KINDS = {
    "BoundaryBoss": ("SWStyle_BoundaryBoss", "Boundary Boss/Base", "Boundary-Boss", "FEATURES_BOUNDARY_BOSS",
                     "PartDesign::FeatureAdditivePython", "PartDesign_AdditiveLoft"),
    "BoundaryCut": ("SWStyle_BoundaryCut", "Boundary Cut", "Boundary-Cut", "FEATURES_BOUNDARY_CUT",
                    "PartDesign::FeatureSubtractivePython", "PartDesign_SubtractiveLoft"),
}
SEW = (1e-4, 1e-3, 1e-2)


# --------------------------------------------------------------------------- the solid
def _profile(curve):
    wire = curve.source
    if len(wire.Edges) > 1:
        wire = Part.Wire(Part.__sortEdges__(wire.Edges))
    if not wire.isClosed():
        raise RuntimeError("%s is not closed: Direction 1 takes closed profiles" % curve.name)
    return wire


def _piece(wire, a, b):
    """The open piece of closed wire from fraction a to fraction b (going on past the end when
    b < a), as a Curve."""
    n = 240
    points = wire.discretize(Number=n + 1)[:-1]
    lengths = [0.0]
    for p, q in zip(points, points[1:] + points[:1]):
        lengths.append(lengths[-1] + (q - p).Length)
    total = lengths[-1]

    def at(f):
        f = (f % 1.0) * total
        for k in range(n):
            if lengths[k + 1] >= f:
                s = (f - lengths[k]) / max(lengths[k + 1] - lengths[k], 1e-12)
                return points[k] + (points[(k + 1) % n] - points[k]) * s
        return points[0]
    span = (b - a) % 1.0 or 1.0
    count = max(24, int(120 * span))
    pts = [at(a + span * k / (count - 1.0)) for k in range(count)]
    spline = Part.BSplineCurve()
    spline.interpolate(pts)
    return bs.Curve(Part.Wire([spline.toShape()]))


def _fraction(wire, point):
    """Fraction of the way round closed wire of its point nearest to point."""
    n = 720
    points = wire.discretize(Number=n + 1)[:-1]
    lengths = [0.0]
    for p, q in zip(points, points[1:] + points[:1]):
        lengths.append(lengths[-1] + (q - p).Length)
    best = min(range(n), key=lambda k: (points[k] - point).Length)
    return lengths[best] / lengths[-1]


def _sew(faces, tolerance):
    """faces sewn into one shell, or None."""
    from . import sewtol
    shell = sewtol.sewn(faces, tolerance)
    shells = [shell] if shell.ShapeType == "Shell" else shell.Shells
    return shells[0] if len(shells) == 1 else None


def _cap(sides, profile):
    """A flat face on the open edges of the sides at profile, or None."""
    free = [e for e in sides.Edges if len(sides.ancestorsOfType(e, Part.Face)) == 1]
    near = [e for e in free if e.distToShape(profile)[0] < 0.5 and
            max(profile.distToShape(Part.Vertex(p))[0] for p in e.discretize(9)) < 0.5]
    if not near:
        return None
    try:
        wire = Part.Wire(Part.__sortEdges__(near))
        if not wire.isClosed():
            return None
    except Exception:
        return None
    for make in (lambda: Part.Face(wire), lambda: Part.makeFilledFace(wire.Edges)):
        try:
            face = make()
            if face.isValid() and face.Area > 1e-9:
                return face
        except Exception as _fw_err:
            _fw_log("boundaryboss.py:115", _fw_err)
    raise RuntimeError("An end profile is not flat: it cannot close the solid")


def solid(first, second, obj=None):
    """The solid through the closed profiles first, steered by the guides second."""
    if len(first) < 2:
        raise RuntimeError("Pick at least two closed profiles for Direction 1")
    wires = [_profile(c) for c in first]
    if not second:
        # Direction 1 curves influence, as on Boundary Surface: Linear is straight between the
        # profiles; To Next Curve / Sharp / Edge let each profile shape the solid only to its neighbours
        mode = str(getattr(obj, "Direction1Influence", "Global")) if obj is not None else "Global"
        ruled = mode == "Linear"
        if not bs.closed(obj):
            wires = bs.influenced_sections(wires, mode)
        wires = bs.sections(wires, obj)
        loft = Part.makeLoft(wires, True, ruled, bs.closed(obj))
        if not loft.isValid() or loft.Volume == 0:
            raise RuntimeError("The profiles could not be lofted")
        return loft if loft.Volume > 0 else loft.reversed()
    if len(second) < 2:
        raise RuntimeError("Pick at least two guide curves for Direction 2, or none")
    # the guides in order round the first profile, and where each crosses each profile
    def row(c, wire):
        out = []
        for g in second:
            dist, pairs, _ = wire.distToShape(g.wire())
            if dist > bs.MEET:
                raise RuntimeError("%s and %s do not meet (%.3f mm apart)" % (c.name, g.name, dist))
            out.append(_fraction(wire, pairs[0][0]))
        return out

    def middles(wire, fractions):
        return [_piece(wire, fractions[j0], fractions[j1]).point(0.5)
                for j0, j1 in zip(order, order[1:] + order[:1])]
    crossings = [row(first[0], wires[0])]
    order = sorted(range(len(second)), key=lambda j: crossings[0][j])
    reference = middles(wires[0], crossings[0])
    for i in range(1, len(wires)):
        c, wire = first[i], wires[i]
        # each profile is walked the same way round as the first: the way whose pieces lie
        # nearest the first profile's
        best = None
        for candidate in (wire, wire.reversed()):
            fractions = row(c, candidate)
            gap = sum((p - q).Length for p, q in zip(middles(candidate, fractions), reference))
            if best is None or gap < best[0]:
                best = (gap, candidate, fractions)
        wires[i] = best[1]
        crossings.append(best[2])
    faces = []
    for k in range(len(order)):
        j0, j1 = order[k], order[(k + 1) % len(order)]
        pieces = [_piece(wire, fr[j0], fr[j1]) for wire, fr in zip(wires, crossings)]
        guides = [bs.Curve(second[j0].source, second[j0].name), bs.Curve(second[j1].source, second[j1].name)]
        span = max((fr[j1] - fr[j0]) % 1.0 for fr in crossings)
        faces.extend(bs.net(pieces, guides, grid=max(bs.GRID, int(bs.GRID * 4 * span) | 1)).Faces)
    # the sides, then the end profiles closed with flat faces on the sides' own edges
    for tolerance in SEW:
        sides = _sew(faces, tolerance)
        if sides is None:
            continue
        caps = [_cap(sides, wires[0]), _cap(sides, wires[-1])]
        if None in caps:
            continue
        shell = _sew(sides.Faces + caps, tolerance)
        if shell is not None and shell.isClosed():
            break
    else:
        raise RuntimeError("The boundary does not close: check the guides reach both end profiles")
    out = Part.Solid(shell)
    fix = Part.ShapeFix.Shape(out)
    fix.perform()
    out = fix.shape()
    if out.ShapeType != "Solid" and out.Solids:
        out = out.Solids[0]
    if out.Volume < 0:
        out.reverse()
    return out


# --------------------------------------------------------------------------- the feature
THIN = (("Thin", "App::PropertyBool", "Thin Feature: a wall of this thickness, the ends left open"),
        ("ThinThickness", "App::PropertyLength", "Thin Feature thickness"),
        ("ThinReverse", "App::PropertyBool", "Thin Feature: the wall goes outward"),
        ("ThinType", "App::PropertyEnumeration", "Thin Feature type: One-Direction, Mid-Plane, Two-Direction"),
        ("ThinThickness2", "App::PropertyLength", "Thin Feature thickness, direction 2 (Two-Direction)"))
THIN_TYPES = ["One-Direction", "Mid-Plane", "Two-Direction"]


def ensure_thin(obj):
    for name, kind, tip in THIN:
        if name not in obj.PropertiesList:
            obj.addProperty(kind, name, "Thin Feature", tip)
            if name in ("ThinThickness", "ThinThickness2"):
                setattr(obj, name, 1.0)
            if name == "ThinType":
                obj.ThinType = THIN_TYPES
                obj.ThinType = "One-Direction"


def end_caps(tool, first):
    """The tool's flat faces that close its first and last Direction 1 profiles."""
    ends = [first[0].source, first[-1].source]
    out = []
    for f in tool.Faces:
        if f.Surface.__class__.__name__ != "Plane":
            continue
        for w in ends:
            try:
                if all(w.distToShape(v)[0] < 1e-4 for v in f.Vertexes) and abs(f.Area) > 1e-9:
                    out.append(f)
                    break
            except Exception:
                continue
    return out


def thin(tool, first, obj):
    ""
    t = float(obj.ThinThickness)
    if t <= 0:
        raise RuntimeError("Thin Feature needs a thickness")
    caps = end_caps(tool, first)
    if not caps:
        raise RuntimeError("Thin Feature: the ends of the boundary could not be found")
    kind = str(getattr(obj, "ThinType", "One-Direction"))
    if kind == "One-Direction":
        # outward, as Extrude, Loft and Sweep thin walls; Reverse Direction takes it inside
        wall = tool.makeThickness(caps, -t if obj.ThinReverse else t, 1e-3, False, False, 0, 2)
    else:
        # Mid-Plane: half the thickness each side of the boundary; Two-Direction: Thickness outward
        # (inward with Reverse), Thickness 2 the other way, as Extrude, Loft and Sweep
        t_out, t_in = (t / 2.0, t / 2.0) if kind == "Mid-Plane" else (t, float(getattr(obj, "ThinThickness2", t)))
        if kind != "Mid-Plane" and obj.ThinReverse:
            t_in, t_out = t_out, t_in
        sides = [tool.makeThickness(caps, -t_in, 1e-3, False, False, 0, 2),     # join 2: sharp corners stay sharp
                 tool.makeThickness(caps, t_out, 1e-3, False, False, 0, 2)]
        wall = sides[0].fuse(sides[1]).removeSplitter()
    if not wall.Solids:
        raise RuntimeError("Thin Feature: the wall could not be made at this thickness")
    return wall.Solids[0] if len(wall.Solids) == 1 else Part.makeCompound(wall.Solids)


class Feature:
    def __init__(self, obj, kind):
        obj.addProperty("App::PropertyLinkSubListGlobal", "Direction1", "Boundary", "Direction 1: closed profiles, in order")
        obj.addProperty("App::PropertyLinkSubListGlobal", "Direction2", "Boundary",
                        "Direction 2 (optional): guide curves crossing every profile")
        obj.addProperty("App::PropertyString", "SWStyleKind", "Base", "Which FreeCAD feature this is")
        obj.SWStyleKind = kind
        obj.setEditorMode("SWStyleKind", 2)
        obj.Proxy = self

    def execute(self, obj):
        base = obj.BaseFeature.Shape if obj.BaseFeature is not None else Part.Shape()
        bs.ensure_options(obj)
        first, second = bs.curves(obj.Direction1), bs.curves(obj.Direction2)
        if len(first) < 2:
            sf.store(obj, base)
            return
        tool = solid(first, second, obj)
        ensure_thin(obj)
        if obj.Thin:
            tool = thin(tool, first, obj)
        if obj.SWStyleKind == "BoundaryCut":
            if base.isNull():
                raise RuntimeError("Boundary Cut needs a part to cut")
            result = base.cut(tool)
        else:
            result = tool if base.isNull() else base.fuse(tool)
        if getattr(obj, "MergeTangentFaces", True):
            try:
                result = result.removeSplitter()
            except Exception as _fw_err:
                _fw_log("boundaryboss.py:283", _fw_err)
        solids = result.Solids
        if not solids:
            raise RuntimeError("Nothing is left of the part")
        sf.store(obj, solids[0] if len(solids) == 1 else Part.makeCompound(solids), tool)

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def dumps(self):
        return None

    def loads(self, state):
        return None


class View(bs.View):
    def getIcon(self):
        kind = getattr(getattr(self, "Object", None), "SWStyleKind", "BoundaryBoss")
        command, menu, label, icon, typ, pixmap = KINDS.get(kind, KINDS["BoundaryBoss"])
        try:
            from . import icons
            found = icons.family(icon)
            if not found.isNull():
                return found        # a QIcon, never a QPixmap
        except Exception as _fw_err:
            _fw_log("boundaryboss.py:309", _fw_err)
        return ":/icons/%s.svg" % pixmap

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        Gui.Control.showDialog(Panel(vobj.Object))
        return True


class Panel(bs.Panel):
    def __init__(self, obj):
        super().__init__(obj)
        command, menu, label, icon, typ, pixmap = KINDS[obj.SWStyleKind]
        self.title = menu
        self.form[0].setProperty("swstyle_pm_title", menu)
        self.form[0].setProperty("swstyle_pm_icon", icon)
        self.form[0].setWindowTitle("Direction 1")
        self.form[1].setWindowTitle("Direction 2")
        # Direction 1 takes the clicks until it holds two profiles
        self.active = "Direction1" if len(bs._items(obj.Direction1)) < 2 else "Direction2"
        self._extra_boxes(obj)
        self._show()

    def _extra_boxes(self, obj):
        ""

        from . import multibody
        ensure_thin(obj)
        options = self.form[2]
        olay = options.layout()
        at = max(0, olay.count() - 1)          # before the stretch
        if obj.SWStyleKind == "BoundaryBoss" and multibody._base_solids(obj):
            self.merge = QtWidgets.QCheckBox("Merge result")
            self.merge.setObjectName("SWStyle_MergeResult")
            self.merge.setChecked(multibody.merged(obj))
            self.merge.toggled.connect(lambda on: (self._begin(), multibody.set_merge(obj, on), self._show()))
            olay.insertWidget(at, self.merge)
        if obj.SWStyleKind == "BoundaryCut" and len(multibody._base_solids(obj)) > 1:
            self.scope = multibody.ScopeBox(options, obj)
            olay.insertWidget(at, self.scope.box)
        page = QtWidgets.QWidget()
        page.setWindowTitle("Thin Feature")
        lay = QtWidgets.QVBoxLayout(page)
        self.thin = QtWidgets.QCheckBox("Thin Feature")
        self.thin.setObjectName("SWStyle_BoundaryThin")
        self.thin.setChecked(bool(obj.Thin))
        row = QtWidgets.QHBoxLayout()
        self.thin_reverse = QtWidgets.QToolButton()
        self.thin_reverse.setObjectName("SWStyle_BoundaryThinReverse")
        self.thin_reverse.setCheckable(True)
        self.thin_reverse.setText("\u21c5")
        self.thin_reverse.setToolTip("Reverse Direction: the wall goes outward")
        self.thin_reverse.setChecked(bool(obj.ThinReverse))
        self.thin_t = QtWidgets.QDoubleSpinBox()
        self.thin_t.setObjectName("SWStyle_BoundaryThinThickness")
        self.thin_t.setRange(0.01, 100000.0)
        self.thin_t.setSuffix(" mm")
        self.thin_t.setKeyboardTracking(False)
        self.thin_t.setValue(float(obj.ThinThickness))
        row.addWidget(self.thin_reverse)
        row.addWidget(self.thin_t, 1)
        self.thin_type = QtWidgets.QComboBox()
        self.thin_type.setObjectName("SWStyle_BoundaryThinType")
        self.thin_type.addItems(THIN_TYPES)
        self.thin_type.setCurrentText(str(getattr(obj, "ThinType", "One-Direction")))
        self.thin_t2 = QtWidgets.QDoubleSpinBox()
        self.thin_t2.setObjectName("SWStyle_BoundaryThinThickness2")
        self.thin_t2.setRange(0.01, 100000.0)
        self.thin_t2.setSuffix(" mm")
        self.thin_t2.setKeyboardTracking(False)
        self.thin_t2.setValue(float(getattr(obj, "ThinThickness2", 1.0)))
        self.thin_t2.setToolTip("Thickness, direction 2")
        lay.addWidget(self.thin)
        lay.addWidget(self.thin_type)
        lay.addLayout(row)
        lay.addWidget(self.thin_t2)
        self.thin_t2.setVisible(self.thin_type.currentText() == "Two-Direction")
        self.thin_type.currentIndexChanged.connect(self._thin_changed)
        self.thin_t2.valueChanged.connect(self._thin_changed)
        lay.addStretch(1)
        self._thin_rows()
        self.thin.toggled.connect(self._thin_changed)
        self.thin_reverse.toggled.connect(self._thin_changed)
        self.thin_t.valueChanged.connect(self._thin_changed)
        self.form.insert(3, page)           # after Options and Preview, before Curvature Display

    def _thin_rows(self):
        ""

        on = self.thin.isChecked()
        kind = self.thin_type.currentText()
        self.thin_type.setVisible(on)
        self.thin_t.setVisible(on)
        self.thin_reverse.setVisible(on and kind != "Mid-Plane")
        self.thin_t2.setVisible(on and kind == "Two-Direction")

    def _thin_changed(self, *args):
        if self.busy:
            return
        self._begin()
        obj = self.obj
        obj.Thin = self.thin.isChecked()
        obj.ThinReverse = self.thin_reverse.isChecked()
        obj.ThinThickness = self.thin_t.value()
        obj.ThinType = self.thin_type.currentText()
        obj.ThinThickness2 = self.thin_t2.value()
        self._thin_rows()
        obj.Document.recompute()
        self._show()

    def _begin(self):
        doc = self.obj.Document
        if not doc.HasPendingTransaction:
            doc.openTransaction(self.title if hasattr(self, "title") else "Boundary")

    def _show(self):
        super()._show()
        obj = self.obj
        if "Invalid" not in obj.State and len(bs._items(obj.Direction1)) < 2:
            self.note.setText("Pick the closed profiles for Direction 1 (sketches or edges), in order; "
                              "guide curves for Direction 2 are optional.")

    def _picked(self, name, sub):

        if self.active == "Direction1":
            doc = self.obj.Document
            holder = doc.getObject(name)
            for part in sub.split(".")[:-1]:
                found = doc.getObject(part)
                if found is not None:
                    holder = found
            if holder is not None and holder.TypeId == "Sketcher::SketchObject" and \
                    sub.split(".")[-1].startswith("Edge"):
                sub = ".".join(sub.split(".")[:-1] + [""])
        super()._picked(name, sub)

    def accept(self):
        obj = self.obj
        obj.Document.recompute()
        if "Invalid" in obj.State or len(bs._items(obj.Direction1)) < 2:
            self.note.setText(obj.getStatusString() if "Invalid" in obj.State else
                              "Pick at least two closed profiles for Direction 1.")
            return False
        for o, _ in bs._items(obj.Direction1) + bs._items(obj.Direction2):
            if o.TypeId == "Sketcher::SketchObject" and o.ViewObject is not None:
                o.ViewObject.Visibility = False
        if obj.Document.HasPendingTransaction:
            obj.Document.commitTransaction()
        self._close()
        return True



# --------------------------------------------------------------------------- making
def make(kind, doc=None, first=(), second=(), edit=True):
    doc = doc or App.ActiveDocument
    body = sf.body_of(doc) if doc is not None else None
    if body is None:
        App.Console.PrintWarning("FreeCAD: %s needs a body\n" % KINDS[kind][1])
        return None
    if kind == "BoundaryCut" and body.Tip is None:
        App.Console.PrintWarning("FreeCAD: Boundary Cut needs a part to cut\n")
        return None
    command, menu, label, icon, typ, pixmap = KINDS[kind]
    doc.openTransaction(menu)
    obj = body.newObject(typ, kind)
    Feature(obj, kind)
    ensure_thin(obj)
    if App.GuiUp and obj.ViewObject is not None:
        View(obj.ViewObject)
    obj.Label = naming.next_label(doc, label)
    if first:
        obj.Direction1 = [(o, s or "") for o, s in first]
    if second:
        obj.Direction2 = [(o, s or "") for o, s in second]
    doc.recompute()
    if edit and App.GuiUp:
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name)
    else:
        doc.commitTransaction()
    return obj


class Command:
    def __init__(self, kind):
        self.kind = kind

    def GetResources(self):
        command, menu, label, icon, typ, pixmap = KINDS[self.kind]
        return {"MenuText": menu, "Pixmap": pixmap,
                "ToolTip": "A solid through closed profiles, with optional guide curves (%s)." % (
                    "added to the part" if self.kind == "BoundaryBoss" else "cut from the part")}

    def IsActive(self):
        doc = App.ActiveDocument
        return doc is not None and not Gui.Control.activeDialog() and \
            any(o.TypeId == "PartDesign::Body" for o in doc.Objects)

    def Activated(self):
        make(self.kind, first=bs._preselected())


def register():
    for kind, (command, menu, *_rest) in KINDS.items():
        try:
            if command not in Gui.listCommands():
                Gui.addCommand(command, Command(kind))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (menu, error))
