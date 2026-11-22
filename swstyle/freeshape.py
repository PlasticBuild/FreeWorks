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

import math

import FreeCAD as App
import Part

from . import simplefeature as sf
from .simplefeature import Field

V = App.Vector
BOX = "Freeshape"
PLANES = ["Front", "Top", "Right"]
_NORMAL = {"Front": V(0, 0, 1), "Top": V(0, 1, 0), "Right": V(1, 0, 0)}


# --------------------------------------------------------------------- helpers
def _smooth(shape, level, size):
    """Rounds every edge as `level` subdivision steps would (0 = the sharp cage)."""
    if level <= 0 or shape.isNull() or not shape.Edges:
        return shape
    r = size * min(0.45, 0.12 * level)
    for factor in (1.0, 0.6, 0.35, 0.2):
        try:
            out = shape.makeFillet(r * factor, shape.Edges)
            if out.isValid():
                return out
        except Exception:
            continue
    return shape


def _add(base, tool):
    if base is None or base.isNull():
        return tool, tool
    return base.fuse(tool), tool


def _place(obj, shape):
    """The shape moved to the feature's centre point on its plane."""
    plane = getattr(obj, "Plane", "Front")
    rot = App.Rotation(V(0, 0, 1), _NORMAL.get(plane, V(0, 0, 1)))
    shape = shape.copy()
    shape.Placement = App.Placement(obj.Center, rot).multiply(shape.Placement)
    return shape


def _common(cage_label, extra):
    return [Field("Plane", "enum", "Plane", "Front", values=PLANES, box=cage_label,
                  tip="The plane the cage is drawn on"),
            Field("Center", "vector", "Center", V(0, 0, 0), box=cage_label, tip="Where the cage's centre is")] + \
        extra + [Field("Smoothing", "int", "Smoothing level", 2, low=0, high=3, box="Smoothing",
                       tip="0 keeps the cage sharp; 1 to 3 round it more, as subdivision levels")]


def _primitive(make, size):
    def compute(obj, base):
        tool = _smooth(_place(obj, make(obj)), obj.Smoothing, size(obj))
        return _add(base, tool)
    return compute


# --------------------------------------------------------------------- cage primitives
def _box(obj):
    w, d, h = obj.Width.Value, obj.Depth.Value, obj.Height.Value
    return Part.makeBox(w, d, h, V(-w / 2, -d / 2, 0))


def _quadball(obj):
    return Part.makeSphere(obj.Radius.Value)


def _cylinder(obj):
    return Part.makeCylinder(obj.Radius.Value, obj.Height.Value)


def _torus(obj):
    return Part.makeTorus(obj.Radius.Value, obj.MinorRadius.Value)


def _rectangle(obj):
    w, d, t = obj.Width.Value, obj.Depth.Value, obj.Thickness.Value
    return Part.makeBox(w, d, t, V(-w / 2, -d / 2, 0))


def _disk(obj):
    return Part.makeCylinder(obj.Radius.Value, obj.Thickness.Value)


def _ring(obj):
    outer = Part.makeCylinder(obj.Radius.Value, obj.Thickness.Value)
    inner = Part.makeCylinder(max(obj.InnerRadius.Value, 0.01), obj.Thickness.Value)
    return outer.cut(inner)


L = lambda name, label, value: Field(name, "length", label, value, box="Cage")


def _cages():
    return [
        ("Box", "Box", _box, lambda o: min(o.Width.Value, o.Depth.Value, o.Height.Value),
         [L("Width", "Width", 40.0), L("Depth", "Depth", 40.0), L("Height", "Height", 40.0)]),
        ("QuadBall", "QuadBall", _quadball, lambda o: o.Radius.Value, [L("Radius", "Radius", 20.0)]),
        ("Cylinder", "Cylinder", _cylinder, lambda o: min(o.Radius.Value * 2, o.Height.Value),
         [L("Radius", "Radius", 15.0), L("Height", "Height", 40.0)]),
        ("Torus", "Torus", _torus, lambda o: o.MinorRadius.Value * 2,
         [L("Radius", "Radius", 25.0), L("MinorRadius", "Tube radius", 6.0)]),
        ("Rectangle", "Rectangle", _rectangle, lambda o: o.Thickness.Value * 2,
         [L("Width", "Width", 60.0), L("Depth", "Depth", 40.0), L("Thickness", "Thickness", 4.0)]),
        ("Disk", "Disk", _disk, lambda o: o.Thickness.Value * 2,
         [L("Radius", "Radius", 25.0), L("Thickness", "Thickness", 4.0)]),
        ("Ring", "Ring", _ring, lambda o: min(o.Thickness.Value * 2, o.Radius.Value - o.InnerRadius.Value),
         [L("Radius", "Radius", 25.0), L("InnerRadius", "Inner radius", 15.0), L("Thickness", "Thickness", 4.0)]),
    ]


# --------------------------------------------------------------------- operations on sketches / bodies
def _profile(obj, name="Profile"):
    src = getattr(obj, name, None)
    if src is None:
        raise RuntimeError("Pick a sketch")
    shape = Part.getShape(src)
    wires = [w for w in shape.Wires if w.isClosed()]
    if not wires:
        raise RuntimeError("The sketch needs a closed contour")
    if len(wires) == 1:
        return Part.Face(wires[0])
    return Part.makeFace(wires, "Part::FaceMakerBullseye")


def _extrude(obj, base):
    face = _profile(obj)
    n = face.normalAt(0, 0) if face.Faces else V(0, 0, 1)
    tool = face.extrude(n * obj.Depth.Value)
    if obj.BothDirections:
        tool = tool.fuse(face.extrude(n * -obj.Depth.Value))
    return _add(base, _smooth(tool, obj.Smoothing, obj.Depth.Value))


def _revolve(obj, base):
    face = _profile(obj)
    axis = {"Sketch X axis": V(1, 0, 0), "Sketch Y axis": V(0, 1, 0)}[obj.Axis]
    src = obj.Profile
    place = src.getGlobalPlacement() if hasattr(src, "getGlobalPlacement") else src.Placement
    axis = place.Rotation.multVec(axis)
    tool = face.revolve(place.Base, axis, obj.Angle.Value)
    return _add(base, _smooth(tool, obj.Smoothing, max(face.BoundBox.XLength, face.BoundBox.YLength) * 0.2))


def _sweep(obj, base):
    face = _profile(obj)
    if obj.Path is None:
        raise RuntimeError("Pick the path sketch")
    path = Part.Wire(Part.__sortEdges__(Part.getShape(obj.Path).Edges))
    tool = path.makePipeShell([face.OuterWire], True, True)
    return _add(base, _smooth(tool, obj.Smoothing, face.BoundBox.DiagonalLength * 0.2))


def _merge(obj, base):
    tools = [Part.getShape(o) for o in (obj.Bodies or [])]
    tools = [t for t in tools if not t.isNull() and t.Solids]
    if not tools:
        raise RuntimeError("Pick the bodies to merge")
    out = base
    for t in tools:
        out = t if out is None or out.isNull() else out.fuse(t)
    for o in obj.Bodies:
        try:
            o.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("freeshape.py:192", _fw_err)
    return out, None


def _symmetry(obj, base):
    n = _NORMAL[obj.Plane]
    keep = Part.makeBox(1e5, 1e5, 1e5, V(-5e4, -5e4, 0))
    keep.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), n))
    if obj.FlipSide:
        keep.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), -n))
    half = base.common(keep)
    if half.isNull() or not half.Solids:
        raise RuntimeError("Nothing of the body is on that side of the plane")
    return half.fuse(half.mirror(V(0, 0, 0), n)), None


def _faces(obj, name="Faces"):
    out = [f for _, f in sf.elements(obj, name) if f.ShapeType == "Face"]
    if not out:
        raise RuntimeError("Pick faces")
    return out


def _extrude_face(obj, base):
    out = base
    for f in _faces(obj):
        u0, u1, v0, v1 = f.ParameterRange
        n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        piece = f.extrude(n * obj.Distance.Value)
        if obj.Scale != 1.0:
            top = f.copy()
            top.translate(n * obj.Distance.Value)
            top.scale(obj.Scale, top.CenterOfMass)
            try:
                piece = Part.makeLoft([f.OuterWire, top.OuterWire], True)
            except Exception as _fw_err:
                _fw_log("freeshape.py:228", _fw_err)
        out = out.fuse(piece)
    return out, None


def _subdivide(obj, base, keep=()):
    edges = [e for e in base.Edges if not any(e.isSame(k) for k in keep)]
    if not edges:
        return base, None
    size = min(base.BoundBox.XLength, base.BoundBox.YLength, base.BoundBox.ZLength) or 10.0
    r = size * min(0.45, 0.08 * obj.Levels)
    for factor in (1.0, 0.6, 0.35, 0.2, 0.1):
        try:
            out = base.makeFillet(r * factor, edges)
            if out.isValid():
                return out, None
        except Exception:
            continue
    raise RuntimeError("The edges could not be smoothed: try fewer levels")


def _crease(obj, base):
    keep = [e for _, e in sf.elements(obj, "Edges") if e.ShapeType == "Edge"]
    if not keep:
        raise RuntimeError("Pick the edges to keep sharp")
    return _subdivide(obj, base, keep)


def _defeature(obj, base):
    faces = _faces(obj)
    out = base.defeaturing(faces)
    if out.isNull() or not out.isValid() or not out.Solids:
        raise RuntimeError("Those faces could not be taken out and the body healed")
    return out, None


def _insert_loop(obj, base):
    from BOPTools import SplitAPI
    faces = _faces(obj)
    cut = []
    for f in faces:
        bb = f.BoundBox
        u0, u1, v0, v1 = f.ParameterRange
        n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        # loops across the face's longer side, evenly spaced
        along = V(1, 0, 0) if bb.XLength >= max(bb.YLength, bb.ZLength) else (
            V(0, 1, 0) if bb.YLength >= bb.ZLength else V(0, 0, 1))
        if abs(along.dot(n)) > 0.9:
            along = V(0, 1, 0) if abs(n.y) < 0.9 else V(1, 0, 0)
        span = (bb.XLength, bb.YLength, bb.ZLength)[[along.x, along.y, along.z].index(1)]
        start = (bb.XMin, bb.YMin, bb.ZMin)[[along.x, along.y, along.z].index(1)]
        for i in range(1, obj.Loops + 1):
            at = start + span * i / (obj.Loops + 1)
            p = V(along.x * at, along.y * at, along.z * at)
            plane = Part.Plane(p, along).toShape(-5e3, 5e3, -5e3, 5e3)
            cut.append(plane)
    pieces = SplitAPI.slice(base, cut, "Split")
    solids = pieces.Solids
    if len(solids) < 2:
        return base, None
    out = solids[0]
    for s in solids[1:]:
        out = out.fuse(s)                 # no refine: the loops stay as edges on the faces
    return out, None


def _align(obj, base):
    faces = _faces(obj, "Target")
    f = faces[0]
    u0, u1, v0, v1 = f.ParameterRange
    n = f.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    c = f.CenterOfMass
    bb = base.BoundBox
    low = V(bb.Center.x, bb.Center.y, bb.ZMin)
    rot = App.Rotation(V(0, 0, 1), n)
    out = base.copy()
    out.Placement = App.Placement(c, rot).multiply(App.Placement(-low, App.Rotation())).multiply(base.Placement)
    return out, None


# --------------------------------------------------------------------- the specs
SPECS = []


def _spec(command, title, tip, fields, compute, needs_body=True, refine=True):
    key = "".join(title.split())
    before = sf.SPECS.get(key)            # Spec() files itself under its title: keep any other feature's
    spec = sf.Spec("SWStyle_Freeshape" + command, title, title, tip, None, "Part_Box_Parametric", fields, compute,
                   needs_body=needs_body, refine=refine)
    if before is not None:
        sf.SPECS[key] = before
    else:
        sf.SPECS.pop(key, None)
    spec.internal = "Freeshape" + command      # its own tree kind, apart from Boss/Base features
    sf.SPECS[spec.internal] = spec
    SPECS.append(spec)
    return spec


def _build():
    if SPECS:
        return
    sketch = Field("Profile", "pick", "Sketch", what="Object", box=BOX, tip="The sketch whose contour is the cage")
    smooth = Field("Smoothing", "int", "Smoothing level", 2, low=0, high=3, box="Smoothing")
    _spec("Extrude", "Freeshape Extrude", "Extrudes a sketch into a smooth Freeshape body.",
          [sketch, Field("Depth", "length", "Depth", 20.0, box=BOX),
           Field("BothDirections", "bool", "Both directions", False, box=BOX), smooth],
          _extrude, needs_body=False)
    _spec("Revolve", "Freeshape Revolve", "Revolves a sketch into a smooth Freeshape body.",
          [sketch, Field("Axis", "enum", "Axis", "Sketch Y axis", values=["Sketch X axis", "Sketch Y axis"], box=BOX),
           Field("Angle", "angle", "Angle", 360.0, low=0.1, high=360.0, box=BOX), smooth],
          _revolve, needs_body=False)
    _spec("Sweep", "Freeshape Sweep", "Sweeps a sketch profile along a path into a Freeshape body.",
          [sketch, Field("Path", "pick", "Path", what="Object", box=BOX), smooth], _sweep, needs_body=False)
    for key, title, make, size, extra in _cages():
        _spec(key, title, "A %s Freeshape cage, made as a smooth solid." % title.lower(),
              _common("Cage", extra), _primitive(make, size), needs_body=False)
    _spec("Merge", "Merge", "Merges Freeshape bodies into one.",
          [Field("Bodies", "pick", "Bodies to merge", what="Object", many=True, box="Merge")], _merge, needs_body=False)
    _spec("Symmetry", "Symmetry", "Makes the body symmetric about a plane: one side is mirrored onto the other.",
          [Field("Plane", "enum", "Symmetry plane", "Right", values=PLANES, box="Symmetry"),
           Field("FlipSide", "bool", "Keep the other side", False, box="Symmetry")], _symmetry)
    _spec("ExtrudeFace", "Extrude Face", "Pulls the picked faces out along their normals.",
          [Field("Faces", "pick", "Faces", what=("Face",), many=True, box="Extrude Face"),
           Field("Distance", "length", "Distance", 10.0, box="Extrude Face"),
           Field("Scale", "float", "Scale of the end face", 1.0, low=0.05, high=10.0, box="Extrude Face")],
          _extrude_face)
    _spec("Subdivide", "Subdivide", "Smooths the body as one more subdivision level would.",
          [Field("Levels", "int", "Levels", 1, low=1, high=3, box="Subdivide")], _subdivide)
    _spec("Crease", "Crease", "Smooths the body but keeps the picked edges sharp.",
          [Field("Edges", "pick", "Crease edges", what=("Edge",), many=True, box="Crease"),
           Field("Levels", "int", "Levels", 1, low=1, high=3, box="Crease")], _crease)
    _spec("FillHole", "Fill Hole", "Fills a hole: its faces are taken out and the body closed over it.",
          [Field("Faces", "pick", "Faces of the hole", what=("Face",), many=True, box="Fill Hole")], _defeature)
    _spec("InsertLoop", "Insert Loop", "Adds edge loops across the picked faces.",
          [Field("Faces", "pick", "Faces", what=("Face",), many=True, box="Insert Loop"),
           Field("Loops", "int", "Number of loops", 1, low=1, high=10, box="Insert Loop")], _insert_loop, refine=False)
    _spec("DeleteLoops", "Delete Loops / Faces", "Deletes the picked faces and heals the body.",
          [Field("Faces", "pick", "Faces", what=("Face",), many=True, box="Delete")], _defeature)
    _spec("Align", "Align", "Moves the body so that its bottom sits on the picked face.",
          [Field("Target", "pick", "Target face", what=("Face",), box="Align")], _align)


ORDER = ("Extrude", "Revolve", "Sweep", "Box", "QuadBall", "Cylinder", "Torus", "Rectangle", "Disk", "Ring",
         "Merge", "EditMerge", "Symmetry", "ExtrudeFace", "Subdivide", "Crease", "FillHole", "InsertLoop",
         "DeleteLoops", "Align")


def menu():
    ""
    from .swmenus import C
    labels = {"Extrude": "Extrude...", "Revolve": "Revolve...", "Sweep": "Sweep...", "Box": "Box...",
              "QuadBall": "QuadBall...", "Cylinder": "Cylinder...", "Torus": "Torus...", "Rectangle": "Rectangle...",
              "Disk": "Disk...", "Ring": "Ring...", "Merge": "Merge...", "EditMerge": "Edit Merge...",
              "Symmetry": "Symmetry...", "ExtrudeFace": "Extrude Face...", "Subdivide": "Subdivide...",
              "Crease": "Crease...", "FillHole": "Fill Hole...", "InsertLoop": "Insert Loop...",
              "DeleteLoops": "Delete Loops / Faces...", "Align": "Align..."}
    return tuple((labels[k], C("SWStyle_Freeshape" + k)) for k in ORDER)


try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None


class _EditMerge:
    """Edit Merge: opens the last Merge again (or the picked one)."""

    def GetResources(self):
        return {"MenuText": "Edit Merge...", "ToolTip": "Opens the Merge feature again to change its bodies."}

    def _target(self):
        doc = App.ActiveDocument
        if doc is None:
            return None
        for sel in Gui.Selection.getSelection():
            if getattr(sel, "SWStyleKind", "") == "FreeshapeMerge":
                return sel
        merges = [o for o in doc.Objects if getattr(o, "SWStyleKind", "") == "FreeshapeMerge"]
        return merges[-1] if merges else None

    def IsActive(self):
        return not Gui.Control.activeDialog() and self._target() is not None

    def Activated(self):
        obj = self._target()
        if obj is not None:
            Gui.ActiveDocument.setEdit(obj.Name)


if Gui is not None:
    class _Command(sf.Command):
        ""

        def IsActive(self):
            doc = App.ActiveDocument
            if doc is None or Gui.Control.activeDialog():
                return False
            if self.spec.needs_body:
                return any(o.TypeId == "PartDesign::Body" and o.Tip is not None for o in doc.Objects)
            return not any(o.isDerivedFrom("TechDraw::DrawPage") for o in doc.Objects)

        def Activated(self):
            doc = App.ActiveDocument
            if sf.body_of(doc) is None:
                bodies = [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]
                if bodies:
                    Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", bodies[-1])
                else:
                    body = doc.addObject("PartDesign::Body", "Body")
                    Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
            super().Activated()


def register():
    if Gui is None:
        return
    _build()
    for spec in SPECS:
        if spec.command not in Gui.listCommands():
            Gui.addCommand(spec.command, _Command(spec))
    if "SWStyle_FreeshapeEditMerge" not in Gui.listCommands():
        Gui.addCommand("SWStyle_FreeshapeEditMerge", _EditMerge())
