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

import json
import math

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
except ImportError:
    Gui = None

from . import simxpress as sx

STANDARD = ("Fixed Geometry", "Roller/Slider", "Fixed Hinge")
ADVANCED = ("Symmetry", "Cyclic Symmetry", "Use Reference Geometry", "On Flat Faces", "On Cylindrical Faces",
            "On Spherical Faces")
LABELS = {"Fixed Geometry": "Fixed", "Roller/Slider": "Roller/Slider", "Fixed Hinge": "Fixed Hinge",
          "Use Reference Geometry": "Reference Geometry", "On Flat Faces": "On Flat Faces", "Symmetry": "Symmetry",
          "Cyclic Symmetry": "Cyclic Symmetry", "On Cylindrical Faces": "On Cylindrical Faces",
          "On Spherical Faces": "On Spherical Faces"}

DIRECTIONS = {"Use Reference Geometry": ("Along Dir 1", "Along Dir 2", "Normal"),
              "On Flat Faces": ("Along Dir 1", "Along Dir 2", "Normal"),
              "On Cylindrical Faces": ("Radial", "Circumferential", "Axial"),
              "On Spherical Faces": ("Radial", "Latitude", "Longitude")}
SYMBOL_SIZE = 100
LENGTH_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}


def inch_part(doc=None):
    ""

    try:
        from . import addintabs
        a = active_study(doc or App.ActiveDocument)
        return bool(addintabs._inch_units(a)) if a is not None else False
    except Exception as _fw_err:
        _fw_log("simpms.py:inch", _fw_err)
        return False
ACCEL_UNITS = {"m/s^2": 1000.0, "in/s^2": 25.4, "ft/s^2": 304.8}         # to mm/s^2
AXES = ("x", "y", "z")
KEEP = "FwSimPM"


def _box_visible(w, on):
    """A PM box with its task-pane frame and title (hiding only the box leaves an empty header)."""
    try:
        w.setVisible(on)
        g = w.parentWidget()
        while g is not None and not g.inherits("QSint::ActionGroup"):
            g = g.parentWidget()
        if g is not None and g.isHidden() == on:
            g.setVisible(on)
    except RuntimeError as _fw_err:
        _fw_log("simpms.py:box", _fw_err)


class SetupError(ValueError):
    """What the PM says when FreeCAD cannot do what was picked."""


# --------------------------------------------------------------------------- the study and its part
def active_study(doc):
    from . import addintabs
    return addintabs._active_analysis(doc) if doc is not None else None


def target(doc, a=None):
    """The solid the study is on: its mesh's shape, else the part's main body."""
    for o in (a.Group if a is not None else []):
        shp = getattr(o, "Shape", None)
        if o.isDerivedFrom("Fem::FemMeshObject") and shp is not None:
            return shp
    from . import evaltools
    return evaltools._main(doc)


def _element(obj, sub):
    return obj.Shape.getElement(sub)


def _axis(vec, tol=1e-6):
    """0, 1, 2 when vec runs along X, Y or Z (either way), else None."""
    v = App.Vector(vec)
    if v.Length < 1e-12:
        return None
    v.normalize()
    for i, c in enumerate((v.x, v.y, v.z)):
        if abs(abs(c) - 1.0) < tol:
            return i
    return None


def _normal(face):
    u0, u1, v0, v1 = face.ParameterRange
    return face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)


def reference_axes(obj, sub):
    """The three directions of a reference as global axis indices: a plane or flat face gives
    (Dir 1, Dir 2, Normal), an edge gives (Along Edge, None, None)."""
    if obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane") or not sub:
        n = obj.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        d1 = obj.Placement.Rotation.multVec(App.Vector(1, 0, 0))
        d2 = obj.Placement.Rotation.multVec(App.Vector(0, 1, 0))
    else:
        el = _element(obj, sub)
        if sub.startswith("Edge"):
            if el.Curve.TypeId != "Part::GeomLine":
                raise SetupError("Pick a straight edge, a flat face or a plane as the reference.")
            a = _axis(el.Curve.Direction)
            if a is None:
                raise SetupError("The reference edge must run along X, Y or Z.")
            return (a, None, None)
        if el.Surface.TypeId != "Part::GeomPlane":
            raise SetupError("Pick a flat face, a straight edge or a plane as the reference.")
        n = _axis(_normal(el))
        if n is None:
            raise SetupError("The reference must be square to X, Y and Z (FreeCAD holds a part along X, Y and Z).")
        rest = [i for i in range(3) if i != n]
        return (rest[0], rest[1], n)
    out = (_axis(d1), _axis(d2), _axis(n))
    if None in out:
        raise SetupError("The reference must be square to X, Y and Z (FreeCAD holds a part along X, Y and Z).")
    return out


def _keep(o, **values):
    if KEEP not in o.PropertiesList:
        o.addProperty("App::PropertyString", KEEP, "FreeCAD", "What the PropertyManager was given")
        o.setPropertyStatus(KEEP, "Hidden")
    setattr(o, KEEP, json.dumps(values, sort_keys=True))


def kept(o):
    try:
        k = json.loads(getattr(o, KEEP, "") or "{}")
    except ValueError:
        return {}
    if k.get("kind") == "Circular Symmetry":
        k["kind"] = "Cyclic Symmetry"
    return k


def _label(a, base):
    used = {study_name(o) for o in a.Group}
    n = 1
    while "%s-%d" % (base, n) in used:
        n += 1
    return "%s-%d" % (base, n)



# document, so a second study's Fixed-1 is labelled Fixed-001. The study's own name is kept beside FreeCAD's label
# ("Fixed-1|Fixed-001") and shown while the label is still the one FreeCAD gave; a rename shows the user's label.
STUDY_NAME = "FwStudyName"


def study_name(o):
    ""
    label = getattr(o, "Label", "") or ""
    want, _sep, auto = (getattr(o, STUDY_NAME, "") or "").partition("|")
    return want if want and auto == label else label


def _set_label(o, want):
    o.Label = want
    try:
        if o.Label != want:
            if STUDY_NAME not in o.PropertiesList:
                o.addProperty("App::PropertyString", STUDY_NAME, "FreeCAD", "The row name in its study")
                o.setPropertyStatus(STUDY_NAME, "Hidden")
            setattr(o, STUDY_NAME, "%s|%s" % (want, o.Label))
        elif STUDY_NAME in o.PropertiesList:
            setattr(o, STUDY_NAME, "")
    except Exception as _fw_err:
        _fw_log("simpms.py:studyname", _fw_err)


def _swap(a, old, new):
    """An edited fixture whose kind changed: the new object takes the old one's name and place."""
    label = study_name(old)
    a.removeObject(old)
    old.Document.removeObject(old.Name)
    _set_label(new, label)



SYMBOL_COLOUR = {"Fem::ConstraintFixed": (0.0, 0.62, 0.0), "Fem::ConstraintDisplacement": (0.0, 0.62, 0.0),
                 "Fem::ConstraintForce": (0.58, 0.0, 0.62), "Fem::ConstraintPressure": (0.58, 0.0, 0.62),
                 "Fem::ConstraintBearing": (0.58, 0.0, 0.62)}


def _add(a, o, kind_label, edit):
    if edit is None or edit is o:
        if edit is None:
            a.addObject(o)
            _set_label(o, _label(a, kind_label))
            if o.TypeId in SYMBOL_COLOUR:
                symbol(o, SYMBOL_COLOUR[o.TypeId])
    else:
        a.addObject(o)
        _swap(a, edit, o)
        if o.TypeId in SYMBOL_COLOUR:
            symbol(o, SYMBOL_COLOUR[o.TypeId])
    return o


# --------------------------------------------------------------------------- fixtures
def _drop_helpers(doc, a, o):
    """The solver objects an edited fixture made besides itself (On Cylindrical / Spherical Faces' local frame)."""
    for name in (kept(o).get("helpers") or []) if o is not None else []:
        h = doc.getObject(name)
        if h is not None:
            try:
                if a is not None and h in a.Group:
                    a.removeObject(h)
                doc.removeObject(h.Name)
            except Exception as _fw_err:
                _fw_log("simpms.py:helpers", _fw_err)


def _round_axis(els, what):
    """(centre, unit axis) shared by round faces (cylinders) or (centre, axis, radius) of spheres."""
    c0, ax = els[0].Surface.Center, App.Vector(els[0].Surface.Axis).normalize()
    for e in els[1:]:
        d = e.Surface.Center - c0
        if abs(abs(App.Vector(e.Surface.Axis).normalize().dot(ax)) - 1) > 1e-6 or (
                what == "cylinder" and d.Length > 1e-6 and abs(abs(App.Vector(d).normalize().dot(ax)) - 1) > 1e-6):
            raise SetupError("All the faces must share one axis.")
        if what == "sphere" and d.Length > 1e-6:
            raise SetupError("All the spherical faces must share one center.")
    return c0, ax


def _touches_axis(els, centre, axis):
    import Part
    span = max(e.BoundBox.DiagonalLength for e in els) * 4 + 1.0
    line = Part.LineSegment(centre - axis * span, centre + axis * span).toShape()
    return any(e.distToShape(line)[0] < 1e-6 for e in els)


def _sectors(obj, side1, side2, axis_ref):
    """Cyclic Symmetry: the sector count from the angle between the two cut faces about the axis."""
    import math
    if len(side1) != 1 or len(side2) != 1:
        raise SetupError("Cyclic Symmetry ties one face on each side: pick one face in each box.")
    if axis_ref is None:
        raise SetupError("Pick the axis of symmetry: an axis, a straight edge or a round face.")
    ro, rs = axis_ref
    if ro.isDerivedFrom("PartDesign::Line") or ro.isDerivedFrom("App::Line"):
        base = ro.Placement.Base
        axis = ro.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    else:
        el = _element(ro, rs)
        if rs.startswith("Edge") and el.Curve.TypeId == "Part::GeomLine":
            base, axis = el.Vertexes[0].Point, App.Vector(el.Curve.Direction)
        elif rs.startswith("Face") and el.Surface.TypeId == "Part::GeomCylinder":
            base, axis = el.Surface.Center, App.Vector(el.Surface.Axis)
        else:
            raise SetupError("The axis of symmetry is an axis, a straight edge or a round face.")
    axis.normalize()
    vs = []
    for f in (side1[0], side2[0]):
        el = _element(obj, f)
        if el.Surface.TypeId != "Part::GeomPlane":
            raise SetupError("Cyclic Symmetry ties the flat faces the sector was cut along.")
        v = el.CenterOfMass - base
        v = v - axis * v.dot(axis)
        if v.Length < 1e-9:
            raise SetupError("The cut faces must lie off the axis.")
        vs.append(v.normalize())
    angle = math.degrees(math.acos(max(-1.0, min(1.0, vs[0].dot(vs[1])))))
    if angle < 1e-3:
        raise SetupError("The two faces are on the same side of the axis.")
    n = 360.0 / angle
    if abs(n - round(n)) > 0.01 or round(n) < 2:
        raise SetupError("The sector angle (%.3f deg) must divide 360 deg evenly." % angle)
    return int(round(n)), base, axis


def add_fixture(doc, a, obj, faces, kind="Fixed Geometry", translations=None, unit="mm", ref=None, edit=None,
                faces2=None, color=None, size=None):
    ""




    if kind == "Circular Symmetry":
        kind = "Cyclic Symmetry"
    import ObjectsFem
    if kind not in STANDARD + ADVANCED:
        raise SetupError("Unknown fixture type %r." % kind)
    if not faces:
        raise SetupError("Pick the faces to hold.")
    els = [_element(obj, f) for f in faces]
    scale = LENGTH_UNITS.get(unit, 1.0)
    helpers = []
    with sx.fem_safe():
        _drop_helpers(doc, a, edit)
        if kind == "Cyclic Symmetry":
            n, base, axis = _sectors(obj, faces, list(faces2 or []), ref)
            tie = edit is not None and getattr(getattr(edit, "Proxy", None), "Type", "") == "Fem::ConstraintTie"
            o = edit if tie else ObjectsFem.makeConstraintTie(doc, "CircularSymmetry")
            o.References = [(obj, faces[0]), (obj, list(faces2)[0])]
            o.CyclicSymmetry = True
            o.Sectors = n
            o.ConnectedSectors = 1
            o.SymmetryAxis = App.Placement(base, App.Rotation(App.Vector(0, 0, 1), axis))
            _add(a, o, LABELS[kind], edit)
        elif kind in ("On Cylindrical Faces", "On Spherical Faces"):
            cyl = kind == "On Cylindrical Faces"
            want = "Part::GeomCylinder" if cyl else "Part::GeomSphere"
            if any(e.Surface.TypeId != want for e in els):
                raise SetupError("%s holds %s faces: pick only those." % (kind, "round (cylindrical)" if cyl else "spherical"))
            trans = tuple(translations or (None, None, None))
            if all(t is None for t in trans):
                raise SetupError("Give at least one translation (tick a direction and its value).")
            centre, axis = _round_axis(els, "cylinder" if cyl else "sphere")
            if cyl:
                local = trans                              # CalculiX's cylindrical frame: radial, tangential, axial
            else:
                rad, lat, lon = trans
                if rad is not None and lat is not None and lon is not None and not any((rad, lat, lon)):
                    local = None                           # all three at 0: the faces are held, no frame needed
                elif (rad is None) != (lat is None) or (rad is not None and (rad or lat)):
                    raise SetupError("On spherical faces FreeCAD's solver holds Radial and Latitude together and at 0 "
                                     "(tick both with 0, or neither); Longitude takes any value.")
                else:
                    local = (rad, lon, lat)                # meridian plane (radial + axial) and the turn about the axis
            if local is not None and not cyl and _touches_axis(els, centre, axis):
                raise SetupError("This spherical face reaches its own axis (its pole), where Latitude and Longitude "
                                 "have no direction. Hold all three at 0, or split the face at the pole (Split tab).")
            o = edit if edit is not None and edit.TypeId == "Fem::ConstraintDisplacement" else ObjectsFem.makeConstraintDisplacement(doc, "Displacement")
            for i, ax in enumerate(AXES):
                v = (local or (0.0, 0.0, 0.0))[i]
                setattr(o, ax + "Free", v is None)
                setattr(o, ax + "Displacement", "%r mm" % (float(v or 0.0) * scale))
                setattr(o, "rot" + ax + "Free", True)
            o.References = [(obj, list(faces))]
            _add(a, o, LABELS[kind], edit)
            if local is not None:
                t = ObjectsFem.makeConstraintTransform(doc, "LocalFrame")
                t.TransformType = "Cylindrical"
                t.References = [(obj, list(faces))]
                doc.recompute()
                t.BasePoint = centre
                t.Axis = axis
                t.Label = o.Label + " frame"
                a.addObject(t)
                if t.ViewObject is not None:
                    t.ViewObject.Visibility = False
                    try:
                        t.ViewObject.ShowInTree = False
                    except Exception as _fw_err:
                        _fw_log("simpms.py:frame", _fw_err)
                helpers.append(t.Name)
        elif kind == "Fixed Geometry":
            o = edit if edit is not None and edit.TypeId == "Fem::ConstraintFixed" else ObjectsFem.makeConstraintFixed(doc, "Fixed")
        elif kind == "Fixed Hinge":
            cyl = [e for e in els if e.Surface.TypeId == "Part::GeomCylinder"]
            if len(cyl) != len(els):
                raise SetupError("Fixed Hinge holds round (cylindrical) faces: pick only round faces.")
            axis = cyl[0].Surface.Axis
            ai = _axis(axis)
            if ai is None:
                raise SetupError("The hinge axis must run along X, Y or Z (FreeCAD holds a part along X, Y and Z).")
            centre = cyl[0].Surface.Center
            for c in cyl[1:]:
                d = c.Surface.Center - centre
                if _axis(c.Surface.Axis) != ai or (d.Length > 1e-6 and abs(abs(d.normalize().dot(axis)) - 1) > 1e-6):
                    raise SetupError("All the hinge's faces must share one axis.")
            o = edit if edit is not None and edit.TypeId == "Fem::ConstraintRigidBody" else ObjectsFem.makeConstraintRigidBody(doc, "FixedHinge")
            o.ReferenceNode = centre
            for i, ax in enumerate(AXES):
                setattr(o, "TranslationalMode" + ax.upper(), "Constraint")
                setattr(o, "RotationalMode" + ax.upper(), "Free" if i == ai else "Constraint")
            o.Displacement = App.Vector(0, 0, 0)
        else:
            if kind in ("Roller/Slider", "Symmetry"):
                # Symmetry: solids hold the translation normal to the cut, as Roller/Slider (rotations are shells')
                trans = (None, None, 0.0)
                axes_of = None
            else:
                trans = tuple(translations or (None, None, None))
                if all(t is None for t in trans):
                    raise SetupError("Give at least one translation (tick a direction and its value).")
            if kind == "Use Reference Geometry":
                if ref is None:
                    raise SetupError("Pick the reference: a plane, a flat face or a straight edge.")
                axes_of = reference_axes(ref[0], ref[1])
            else:
                flat = [e for e in els if e.Surface.TypeId == "Part::GeomPlane"]
                if len(flat) != len(els):
                    raise SetupError("%s holds flat faces: pick only flat faces." % kind)
                ns = {_axis(_normal(e)) for e in flat}
                if None in ns:
                    raise SetupError("The faces must be square to X, Y or Z (FreeCAD holds a part along X, Y and Z).")
                if len(ns) != 1:
                    raise SetupError("The faces must all face the same way.")
                n = ns.pop()
                rest = [i for i in range(3) if i != n]
                axes_of = (rest[0], rest[1], n)
            o = edit if edit is not None and edit.TypeId == "Fem::ConstraintDisplacement" else ObjectsFem.makeConstraintDisplacement(doc, "Displacement")
            held = {}
            for value, ai in zip(trans, axes_of):
                if value is not None and ai is not None:
                    held[ai] = float(value) * scale
            for i, ax in enumerate(AXES):
                setattr(o, ax + "Free", i not in held)
                setattr(o, ax + "Displacement", "%r mm" % held.get(i, 0.0))
                setattr(o, "rot" + ax + "Free", True)
        if kind not in ("Cyclic Symmetry", "On Cylindrical Faces", "On Spherical Faces"):
            o.References = [(obj, list(faces))]
            _add(a, o, LABELS[kind], edit)
    symbol(o, color if color is not None else FIXTURE_COLOR, size)
    _keep(o, kind=kind, translations=list(translations) if translations else None, unit=unit,
          ref=[ref[0].Name, ref[1]] if ref else None, faces2=list(faces2) if faces2 else None,
          helpers=helpers or None, color=list(color) if color else None, size=size)
    doc.recompute()
    return o


def cyclic_inp(fea, analysis):
    ""



    import Part
    ties = [o for o in (analysis.Group if analysis is not None else [])
            if getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::ConstraintTie" and getattr(o, "CyclicSymmetry", False)
            and not getattr(o, "Suppressed", False) and o.References]
    path = getattr(fea, "inp_file_name", None)
    if not path:
        return 0
    if not ties:
        with open(path) as fh:
            lines = fh.readlines()
        lines, n = _carried_loads(fea, analysis, lines)
        if n:
            with open(path, "w") as fh:
                fh.writelines(lines)
        return 0
    faces = []
    for t in ties:
        ro, subs = t.References[0]
        for sub in ([subs] if isinstance(subs, str) else subs):
            faces.append(_element(ro, sub))
    with open(path) as fh:
        lines = fh.readlines()
    nodes, i = {}, 0
    while i < len(lines):
        if lines[i].upper().startswith("*NODE,") or lines[i].upper().startswith("*NODE\n"):
            i += 1
            while i < len(lines) and not lines[i].startswith("*"):
                parts = lines[i].split(",")
                if len(parts) >= 4:
                    nodes[int(parts[0])] = App.Vector(float(parts[1]), float(parts[2]), float(parts[3]))
                i += 1
            break
        i += 1
    tol = 1e-4
    dep = set()
    for f in faces:
        bb = f.BoundBox
        bb.enlarge(tol)
        for nid, pt in nodes.items():
            if bb.isInside(pt) and f.distToShape(Part.Vertex(pt))[0] < tol:
                dep.add(nid)
    if not dep:
        lines, n = _carried_loads(fea, analysis, lines)
        if n:
            with open(path, "w") as fh:
                fh.writelines(lines)
        return 0
    held = set()
    for o in analysis.Group:
        if o.isDerivedFrom("Fem::ConstraintDisplacement") or o.isDerivedFrom("Fem::ConstraintFixed"):
            held.add(o.Name.upper())
        elif o.isDerivedFrom("Fem::ConstraintTransform"):
            held.update(("CYLIN" + o.Name.upper(), "RECT" + o.Name.upper()))     # a local frame on those nodes too
    out, dropped, in_set = [], 0, False
    for line in lines:
        up = line.upper().replace(" ", "")
        if line.startswith("*"):
            in_set = up.startswith("*NSET,NSET=") and up.split("NSET=", 1)[1].strip().split(",")[0] in held
            out.append(line)
            continue
        if in_set:
            ids = [x.strip() for x in line.split(",") if x.strip()]
            keep = [x for x in ids if not (x.isdigit() and int(x) in dep)]
            dropped += len(ids) - len(keep)
            if keep:
                out.append(",".join(keep) + ",\n")
            continue
        out.append(line)
    out, _n = _carried_loads(fea, analysis, out)
    with open(path, "w") as fh:
        fh.writelines(out)
    return dropped


FIXTURE_COLOR = (0.0, 160 / 255.0, 0.0)       # the fixture symbols' green (Symbol Settings > Edit Color... starts here)


def symbol(o, color=None, size=None):
    ""
    if size is not None and "Scale" in o.PropertiesList:
        try:
            o.Scale = max(20, min(500, int(size))) / 100.0
        except Exception as _fw_err:
            _fw_log("simpms.py:symbolsize", _fw_err)
    vo = getattr(o, "ViewObject", None)
    if color is not None and vo is not None and "ShapeAppearance" in vo.PropertiesList:
        try:
            mat = App.Material()
            mat.DiffuseColor = tuple(float(c) for c in color[:3])
            vo.ShapeAppearance = [mat]
        except Exception as _fw_err:
            _fw_log("simpms.py:symbolcolor", _fw_err)


def add_split(doc, a, tool):
    ""


    import Part
    from BOPTools import SplitAPI
    if tool is None:
        raise SetupError("Pick the splitting tool: a plane, a flat face or a sketch.")
    base = target(doc, a)
    if base is None:
        raise SetupError("Make a study first (Simulation > New Study).")
    shape = base.Shape
    bb = shape.BoundBox
    span = bb.DiagonalLength * 2 + 10.0
    to, ts = tool
    cut = []
    if to.isDerivedFrom("Sketcher::SketchObject"):
        n = to.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        wires = [w for w in to.Shape.Wires if w.isClosed()]
        if not wires:
            raise SetupError("The sketch needs a closed profile to split along.")
        for w in wires:
            f = Part.Face(w)
            f.translate(n * -span)
            cut.extend(f.extrude(n * 2 * span).Faces)
    else:
        if to.isDerivedFrom("PartDesign::Plane") or to.isDerivedFrom("App::Plane"):
            c, n = to.Placement.Base, to.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        else:
            el = _element(to, ts) if ts else None
            if el is None or not ts.startswith("Face") or el.Surface.TypeId != "Part::GeomPlane":
                raise SetupError("The splitting tool is a plane, a flat face or a sketch.")
            c, n = el.CenterOfMass, _normal(el)
        cut.append(Part.Plane(c, n).toShape(-span, span, -span, span))
    pieces = SplitAPI.slice(shape, [Part.Shell(cut) if len(cut) > 1 else cut[0]], "CompSolid")
    solids = pieces.Solids
    if len(solids) < 2:
        raise SetupError("The tool does not cross the part: nothing to split.")
    used = {o.Label for o in doc.Objects}
    k = 1
    while "Split Line%d" % k in used:
        k += 1
    split = doc.addObject("Part::Feature", "SplitLine")
    split.Label = "Split Line%d" % k
    split.Shape = pieces
    m = gmsh_of(a)
    if m is not None:
        m.Shape = split
        try:
            import Fem
            m.FemMesh = Fem.FemMesh()       # meshed again on the split part at the next run
        except Exception as _fw_err:
            _fw_log("simpms.py:splitmesh", _fw_err)
    moved = 0
    for o in (a.Group if a is not None else []):
        refs = getattr(o, "References", None)
        if not refs or not any(r[0] == base for r in refs):
            continue
        new = []
        for ro, subs in refs:
            if ro != base:
                new.append((ro, subs))
                continue
            names = []
            for sub in (subs if isinstance(subs, (list, tuple)) else [subs]):
                if not sub.startswith("Face"):
                    continue
                old = _element(base, sub)
                for i, f in enumerate(pieces.Faces, 1):
                    if old.distToShape(Part.Vertex(f.CenterOfMass))[0] < 1e-6 and ("Face%d" % i) not in names:
                        names.append("Face%d" % i)
            if names:
                new.append((split, names))
        if new:
            o.References = new
            moved += 1
        elif "Material" in o.PropertiesList:
            o.References = []           # a material on the whole part: the whole split part
    if base.ViewObject is not None:
        base.ViewObject.Visibility = False
    doc.recompute()
    return split


# --------------------------------------------------------------------------- loads
def add_force(doc, a, obj, faces, value, unit="N", direction=None, reverse=False, per_item=False, edit=None):
    import ObjectsFem
    if not faces:
        raise SetupError("Pick the faces the force acts on.")
    newtons = float(value) * sx.FORCE_UNITS.get(unit, 1.0) * (len(faces) if per_item else 1)
    with sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeConstraintForce(doc, "Force")
        o.References = [(obj, list(faces))]
        o.Suppressed = False                # an edited Torque / Bearing / Distributed Mass turned back into a force
        if CARRIER in o.PropertiesList:
            setattr(o, CARRIER, "")
        o.Force = "%r N" % newtons
        o.Direction = (direction[0], [direction[1]]) if direction else None
        o.Reversed = False                  # an edited force: its normal is read unflipped, then Reverse applies
        _add(a, o, "Force", edit)
    doc.recompute()
    flip = sx._outward_push(o, obj, faces[0]) if direction is None else False
    o.Reversed = bool(reverse) != flip
    _keep(o, value=float(value), unit=unit, reverse=bool(reverse), per_item=bool(per_item),
          direction=[direction[0].Name, direction[1]] if direction else None)
    doc.recompute()
    return o



PRESSURE_UNITS = {"N/m^2": 1e-6, "psi": 1 / 145.0377, "kgf/cm^2": 1 / 10.19716, "N/mm^2 (MPa)": 1.0,
                  "ksi": 1000.0 / 145.0377}
PRESSURE_ALIASES = {"MPa": "N/mm^2 (MPa)"}
PRESSURE_TYPES = ("Normal to selected face", "Use reference geometry")


def _pressure_mpa(value, unit):
    unit = PRESSURE_ALIASES.get(unit, unit)
    return float(value) * PRESSURE_UNITS.get(unit, sx.PRESSURE_UNITS.get(unit, 1.0))


def add_pressure(doc, a, obj, faces, value, unit="N/m^2", reverse=False, edit=None, ref=None):
    """Pressure. Normal to selected face: FEM's pressure (into each face). Use reference geometry: the pressure
    acts along the reference (a plane's or flat face's normal, or an edge / axis) on every picked face, so each face
    carries pressure x its area in that direction: FEM's force on the faces (spread by area) of pressure x the
    faces' total area."""
    import ObjectsFem
    if not faces:
        raise SetupError("Pick the faces the pressure acts on.")
    mpa = _pressure_mpa(value, unit)
    want = "Fem::ConstraintForce" if ref is not None else "Fem::ConstraintPressure"
    if ref is not None and (ref[0] is None or (ref[1] and ref[1].startswith("Vertex"))):
        raise SetupError("Pick the reference: a plane, a flat face, an edge or an axis.")
    with sx.fem_safe():
        reuse = edit if edit is not None and edit.TypeId == want else None
        if ref is not None:
            o = reuse if reuse is not None else ObjectsFem.makeConstraintForce(doc, "Pressure")
            area = sum(_element(obj, f).Area for f in faces)
            o.References = [(obj, list(faces))]
            o.Force = "%r N" % (mpa * area)
            o.Direction = (ref[0], [ref[1]])
            o.Reversed = bool(reverse)
        else:
            o = reuse if reuse is not None else ObjectsFem.makeConstraintPressure(doc, "Pressure")
            o.References = [(obj, list(faces))]
            o.Pressure = "%r MPa" % mpa
            o.Reversed = bool(reverse)
        _add(a, o, "Pressure", edit if reuse is None else o)      # a changed Type: the old object is swapped out
    _keep(o, kind="Pressure", value=float(value), unit=PRESSURE_ALIASES.get(unit, unit), reverse=bool(reverse),
          type=PRESSURE_TYPES[1 if ref is not None else 0],
          ref=[ref[0].Name, ref[1]] if ref is not None else None)
    doc.recompute()
    return o


def gravity_direction(ref):
    """Down the reference: a plane's or flat face's normal, or along an edge."""
    obj, sub = ref
    if obj.isDerivedFrom("App::Plane") or obj.isDerivedFrom("PartDesign::Plane") or not sub:
        return obj.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    el = _element(obj, sub)
    if sub.startswith("Edge"):
        if el.Curve.TypeId != "Part::GeomLine":
            raise SetupError("Pick a straight edge, a flat face or a plane for the direction of gravity.")
        return App.Vector(el.Curve.Direction)
    if el.Surface.TypeId != "Part::GeomPlane":
        raise SetupError("Pick a flat face, a straight edge or a plane for the direction of gravity.")
    return _normal(el)


def add_gravity(doc, a, ref, value=9.81, unit="m/s^2", reverse=False, edit=None):
    import ObjectsFem
    if ref is None:
        raise SetupError("Pick the reference: a plane, a flat face or a straight edge.")
    d = gravity_direction(ref)
    d.normalize()
    if reverse:
        d = -d
    with sx.fem_safe():
        o = edit if edit is not None else ObjectsFem.makeConstraintSelfWeight(doc, "Gravity")
        o.GravityDirection = d
        o.GravityAcceleration = "%r mm/s^2" % (float(value) * ACCEL_UNITS.get(unit, 1000.0))
        _add(a, o, "Gravity", edit)
    _keep(o, value=float(value), unit=unit, reverse=bool(reverse), ref=[ref[0].Name, ref[1]])
    doc.recompute()
    return o


# --------------------------------------------------------------------------- the other External Loads
TORQUE_UNITS = {"N.m": 1000.0, "N.mm": 1.0, "lbf.in": 112.9848, "lbf.ft": 1355.818, "kgf.cm": 98.0665}   # to N*mm

UNIT_SYSTEMS = ("SI", "English (IPS)", "Metric (G)")
SYSTEM_FORCE = {"SI": "N", "English (IPS)": "lbf", "Metric (G)": "kgf"}
SYSTEM_TORQUE = {"SI": "N.m", "English (IPS)": "lbf.in", "Metric (G)": "kgf.cm"}
MASS_UNITS = {"kg": 1e-3, "g": 1e-6, "lb": 0.45359237e-3}                               # to tonne (CalculiX mm-N-t)
SPIN_UNITS = {"rad/s": 1.0, "RPM": 2 * 3.141592653589793 / 60.0, "Hz": 2 * 3.141592653589793}  # to rad/s
DISTRIBUTIONS = ("Sinusoidal", "Parabolic")
CARRIER = "FwSimLoad"       # kept kind of a load CalculiX gets from cyclic_inp (torque, bearing, mass)


def axis_of(ref, faces_of=None):
    """(point, unit direction) of an axis reference: a datum axis, a straight edge, a round face; with no
    reference, the round faces' own axis (faces_of = (object, [faces]))."""
    if ref is None:
        if faces_of is None:
            raise SetupError("Pick the axis: an axis, a straight edge or a round face.")
        els = [_element(faces_of[0], f) for f in faces_of[1]]
        if not els or any(e.Surface.TypeId != "Part::GeomCylinder" for e in els):
            raise SetupError("Pick the axis (an axis, a straight edge or a round face): the faces are not all round.")
        c, ax = _round_axis(els, "cylinder")
        return c, ax
    ro, rs = ref
    if ro.isDerivedFrom("PartDesign::Line") or ro.isDerivedFrom("App::Line"):
        return ro.Placement.Base, ro.Placement.Rotation.multVec(App.Vector(0, 0, 1)).normalize()
    el = _element(ro, rs) if rs else None
    if el is not None and rs.startswith("Edge") and el.Curve.TypeId == "Part::GeomLine":
        return el.Vertexes[0].Point, App.Vector(el.Curve.Direction).normalize()
    if el is not None and rs.startswith("Face") and el.Surface.TypeId == "Part::GeomCylinder":
        return el.Surface.Center, App.Vector(el.Surface.Axis).normalize()
    raise SetupError("The axis is an axis, a straight edge or a round face.")


def direction_of(ref):
    """A unit direction: a plane's or flat face's normal, or along a straight edge."""
    d = gravity_direction(ref)
    return App.Vector(d).normalize()


def _carrier(doc, a, obj, faces, name, label, edit):
    """A suppressed FEM force on the faces: FreeCAD's writer skips it, cyclic_inp writes the real nodal loads."""
    import ObjectsFem
    if not faces:
        raise SetupError("Pick the faces the load acts on.")
    with sx.fem_safe():
        o = edit if edit is not None and edit.TypeId == "Fem::ConstraintForce" else ObjectsFem.makeConstraintForce(doc, name)
        o.References = [(obj, list(faces))]
        o.Force = "1 N"
        o.Direction = None
        o.Suppressed = True
        _add(a, o, label, edit)
    return o


def add_torque(doc, a, obj, faces, value, unit="N.m", axis=None, reverse=False, edit=None):
    ""

    if not faces:
        raise SetupError("Pick the faces the torque acts on.")
    base, ax = axis_of(axis, (obj, list(faces)))
    nmm = float(value) * TORQUE_UNITS.get(unit, 1000.0)
    o = _carrier(doc, a, obj, faces, "Torque", "Torque", edit)
    _keep(o, kind="Torque", value=float(value), unit=unit, reverse=bool(reverse),
          axis=[axis[0].Name, axis[1]] if axis else None)
    setattr_carrier(o, {"load": "torque", "nmm": nmm * (-1 if reverse else 1), "base": list(base), "axis": list(ax)})
    doc.recompute()
    return o


def add_bearing(doc, a, obj, faces, value, unit="N", direction=None, distribution="Sinusoidal", reverse=False, edit=None):
    ""

    if not faces:
        raise SetupError("Pick the round faces the bearing pushes on.")
    if direction is None:
        raise SetupError("Pick the load direction: a plane, a flat face or a straight edge.")
    if distribution not in DISTRIBUTIONS:
        raise SetupError("Unknown distribution %r." % distribution)
    base, ax = axis_of(None, (obj, list(faces)))
    d = direction_of(direction)
    d = d - ax * d.dot(ax)
    if d.Length < 1e-6:
        raise SetupError("A bearing load pushes across the axis: pick a direction that is not along it.")
    d.normalize()
    if reverse:
        d = -d
    n = float(value) * sx.FORCE_UNITS.get(unit, 1.0)
    o = _carrier(doc, a, obj, faces, "BearingLoad", "Bearing Load", edit)
    _keep(o, kind="Bearing Load", value=float(value), unit=unit, reverse=bool(reverse), distribution=distribution,
          direction=[direction[0].Name, direction[1]])
    setattr_carrier(o, {"load": "bearing", "n": n, "base": list(base), "axis": list(ax), "dir": list(d),
                        "distribution": distribution})
    doc.recompute()
    return o


def add_distributed_mass(doc, a, obj, faces, value, unit="kg", edit=None):
    """Distributed Mass: a mass spread over the faces by area (CalculiX MASS elements on their nodes): it weighs
    under Gravity, spins under Centrifugal and lowers the frequencies, adding no stiffness."""
    if not faces:
        raise SetupError("Pick the faces the mass sits on.")
    t = float(value) * MASS_UNITS.get(unit, 1e-3)
    if t <= 0:
        raise SetupError("Give the mass.")
    o = _carrier(doc, a, obj, faces, "DistributedMass", "Distributed Mass", edit)
    _keep(o, kind="Distributed Mass", value=float(value), unit=unit)
    setattr_carrier(o, {"load": "mass", "t": t})
    doc.recompute()
    return o


def setattr_carrier(o, data):
    data = dict(data)
    data.setdefault("suppressed", bool(carrier(o).get("suppressed")))     # an edit keeps the item's Suppress state
    if CARRIER not in o.PropertiesList:
        o.addProperty("App::PropertyString", CARRIER, "FreeCAD", "The load CalculiX gets for this item")
        o.setPropertyStatus(CARRIER, "Hidden")
    setattr(o, CARRIER, json.dumps(data, sort_keys=True))


def carrier(o):
    try:
        return json.loads(getattr(o, CARRIER, "") or "{}")
    except ValueError:
        return {}


def suppress_carrier(o, on):
    """Suppress / Unsuppress for Torque, Bearing Load and Distributed Mass: the FEM object stays Suppressed (so
    FreeCAD's writer leaves it to cyclic_inp); this flag says whether cyclic_inp writes it."""
    c = carrier(o)
    if not c:
        return False
    c["suppressed"] = bool(on)
    setattr_carrier(o, c)
    return True


ACCEL_SPIN_UNITS = {"rad/s^2": 1.0, "RPM/s": 2 * 3.141592653589793 / 60.0}                    # to rad/s^2


def add_centrifugal(doc, a, axis, value, unit="rad/s", edit=None, accel=0.0, accel_unit="rad/s^2"):
    """Centrifugal: the whole part spun at an angular velocity about an axis (CalculiX CENTRIF), and sped up at an
    angular acceleration (its inertia forces -rho (alpha x r), written as nodal forces by cyclic_inp)."""
    import ObjectsFem
    import math
    import Part
    if axis is None:
        raise SetupError("Pick the axis: an axis, a straight edge or a round face.")
    w = float(value) * SPIN_UNITS.get(unit, 1.0)
    al = float(accel or 0.0) * ACCEL_SPIN_UNITS.get(accel_unit, 1.0)
    if w < 0 or (w == 0 and al == 0):
        raise SetupError("Give the angular velocity or the angular acceleration.")
    base, ax = axis_of(axis)
    with sx.fem_safe():
        _drop_helpers(doc, a, edit)
        o = edit if edit is not None and edit.TypeId == "Fem::ConstraintPython" and "RotationFrequency" in edit.PropertiesList \
            else ObjectsFem.makeConstraintCentrif(doc, "Centrifugal")
        line = doc.addObject("Part::Feature", "CentrifugalAxis")
        line.Shape = Part.LineSegment(base, base + ax * 10.0).toShape()
        line.Label = "Centrifugal axis"
        if line.ViewObject is not None:
            line.ViewObject.Visibility = False
            try:
                line.ViewObject.ShowInTree = False
            except Exception as _fw_err:
                _fw_log("simpms.py:centaxis", _fw_err)
        o.RotationAxis = [(line, ["Edge1"])]
        o.RotationFrequency = "%r Hz" % (w / (2 * math.pi))
        o.References = []
        _add(a, o, "Centrifugal", edit)
    _keep(o, kind="Centrifugal", value=float(value), unit=unit, axis=[axis[0].Name, axis[1]], helpers=[line.Name],
          accel=float(accel or 0.0), accel_unit=accel_unit, alpha=al, base=list(base), dir=list(ax))
    doc.recompute()
    return o


REMOTE_TYPES = ("Load/Mass", "Displacement")
CONNECTIONS = ("Rigid", "Distributed")
INERTIA_UNITS = {"kg.m^2": 1e3, "g.mm^2": 1e-9, "lb.in^2": 0.45359237e-3 * 645.16}         # to t*mm^2
ANGLE_UNITS = {"deg": 3.141592653589793 / 180.0, "rad": 1.0}


def add_remote(doc, a, obj, faces, location, force=(0.0, 0.0, 0.0), moment=(0.0, 0.0, 0.0), unit="mm",
               force_unit="N", moment_unit="N.m", edit=None, connection="Rigid", rtype="Load/Mass", mass=0.0,
               mass_unit="kg", inertia=(0.0,) * 6, inertia_unit="kg.m^2", translation=(None,) * 3,
               rotation=(None,) * 3, angle_unit="deg"):
    """Remote Loads/Mass at a point (location), joined to the faces Rigid (a rigid arm) or Distributed (direct
    transfer: statically equivalent nodal forces, the faces free to deform).
    Load/Mass: force and moment there; Remote Mass: a mass with its moments of inertia (Ixx Iyy Izz Ixy Iyz Ixz,
    products as +integral(xy dm); the inertia needs Rigid).
    Displacement: translations (unit) and rotations (angle_unit) of the point, None leaving that component free
    (rotations need Rigid). Written by cyclic_inp."""
    if not faces:
        raise SetupError("Pick the faces the remote load acts on.")
    if connection not in CONNECTIONS or rtype not in REMOTE_TYPES:
        raise SetupError("Unknown remote load %r / %r." % (rtype, connection))
    k = LENGTH_UNITS.get(unit, 1.0)
    fk = sx.FORCE_UNITS.get(force_unit, 1.0)
    mk = TORQUE_UNITS.get(moment_unit, 1000.0)
    data = {"load": "remote", "conn": connection, "type": rtype, "p": [float(c) * k for c in location]}
    if rtype == "Load/Mass":
        t = float(mass or 0.0) * MASS_UNITS.get(mass_unit, 1e-3)
        inn = [float(x or 0.0) * INERTIA_UNITS.get(inertia_unit, 1e3) for x in inertia]
        if t < 0 or min(inn[:3]) < 0:
            raise SetupError("The mass and the moments of inertia cannot be negative.")
        if connection == "Distributed" and any(inn):
            raise SetupError("Moments of inertia need a Rigid connection.")
        if any(inn) and t <= 0:
            raise SetupError("Give the mass that has the moments of inertia.")
        if not any(force) and not any(moment) and t <= 0:
            raise SetupError("Give a force, a moment or a mass.")
        if any(inn):
            _cross(t, inn)                                  # checks the inertia is one a body can have
        data.update(f=[float(x) * fk for x in force], m=[float(x) * mk for x in moment], t=t, I=inn)
    else:
        ak = ANGLE_UNITS.get(angle_unit, 1.0)
        u = [None if x is None else float(x) * k for x in translation]
        r = [None if x is None else float(x) * ak for x in rotation]
        if connection == "Distributed" and any(x is not None for x in r):
            raise SetupError("Rotations need a Rigid connection.")
        if all(x is None for x in u + r):
            raise SetupError("Give at least one translation or rotation.")
        data.update(u=u, r=r)
    label = None
    if edit is not None and edit.TypeId == "Fem::ConstraintRigidBody":     # one made before Distributed / Mass
        label = edit.Label
        a.removeObject(edit)
        doc.removeObject(edit.Name)
        edit = None
    o = _carrier(doc, a, obj, faces, "RemoteLoad", "Remote Load", edit)
    if label:
        o.Label = label
    _keep(o, kind="Remote Load", location=list(location), force=list(force), moment=list(moment), unit=unit,
          force_unit=force_unit, moment_unit=moment_unit, connection=connection, rtype=rtype, mass=float(mass or 0.0),
          mass_unit=mass_unit, inertia=[float(x or 0.0) for x in inertia], inertia_unit=inertia_unit,
          translation=list(translation), rotation=list(rotation), angle_unit=angle_unit)
    setattr_carrier(o, data)
    doc.recompute()
    return o


def _cross(t, inn):
    """A remote mass's inertia as point masses: (centre mass, [(offset vector, mass)]) on a cross along the principal
    axes (CalculiX has no rotary inertia on a node): the six arm masses give the principal moments, the rest stays at
    the centre."""
    import numpy as np
    ixx, iyy, izz, ixy, iyz, ixz = inn
    T = np.array([[ixx, -ixy, -ixz], [-ixy, iyy, -iyz], [-ixz, -iyz, izz]], dtype=float)
    P, E = np.linalg.eigh(T)
    if P.min() < -1e-9 * max(1.0, P.max()):
        raise SetupError("Those moments of inertia are not ones a body can have.")
    P = np.clip(P, 0.0, None)
    tot = P.sum()
    if tot <= 0:
        return t, []
    for i in range(3):
        if P[i] > P[(i + 1) % 3] + P[(i + 2) % 3] + 1e-9 * tot:
            raise SetupError("Those moments of inertia are not ones a body can have (each is at most the sum of the "
                             "other two).")
    a2 = 1.2 * tot / (2.0 * t)
    arm = []
    for i in range(3):
        mi = max(0.0, (P[(i + 1) % 3] + P[(i + 2) % 3] - P[i]) / (4.0 * a2))
        e = E[:, i] * a2 ** 0.5
        for sgn in (1.0, -1.0):
            arm.append((App.Vector(*(sgn * e)), mi))
    return t - sum(m for _v, m in arm), arm


def _node_weights(femmesh, o):
    """The faces' nodes and their share of the faces' area (FreeCAD's own force spreading, 1 N in all)."""
    from femmesh import meshtools

    class _One:
        References = o.References
        Force = App.Units.Quantity("1 N")
    table = meshtools.get_force_obj_face_nodeload_table(femmesh, meshtools.get_femelement_table(femmesh),
                                                        femmesh.Nodes, _One())
    w = {}
    for _name, loads in table:
        for nid, q in loads.items():
            w[nid] = w.get(nid, 0.0) + float(getattr(q, "Value", q))
    return w


def _carried_loads(fea, analysis, lines):
    """Torque, Bearing Load and Distributed Mass into the CalculiX input: nodal forces in the step, MASS elements
    in the model."""
    import math
    loads = [o for o in (analysis.Group if analysis is not None else [])
             if o.isDerivedFrom("Fem::ConstraintForce") and carrier(o) and o.References
             and not carrier(o).get("suppressed")]
    spins = [o for o in (analysis.Group if analysis is not None else [])
             if kept(o).get("kind") == "Centrifugal" and kept(o).get("alpha") and not getattr(o, "Suppressed", False)]
    if not loads and not spins:
        return lines, 0
    mesh = getattr(fea, "mesh", None)
    femmesh = getattr(mesh, "FemMesh", None)
    if femmesh is None:
        return lines, 0
    nodes = femmesh.Nodes
    cload, model, mass_sets, bound = [], [], [], []
    eid = max(list(femmesh.Volumes) + list(femmesh.Faces) + list(femmesh.Edges) + [0])
    nid0 = max(list(nodes) + [0])
    for line in lines:                       # ids others added to the input (rigid bodies, connectors)
        head = line.split(",")[0].strip()
        if head.isdigit():
            eid = max(eid, int(head))
            nid0 = max(nid0, int(head))
    eid += 1000
    nid0 += 1000
    for o in spins:
        cload.append("** %s angular acceleration\n*CLOAD\n" % o.Label)
        for nid, v in sorted(_angular_loads(femmesh, analysis, kept(o)).items()):
            for dof, comp in enumerate((v.x, v.y, v.z), 1):
                if abs(comp) > 1e-15:
                    cload.append("%d,%d,%.13G\n" % (nid, dof, comp))
    for o in loads:
        c = carrier(o)
        w = _node_weights(femmesh, o)
        if not w:
            continue
        if c["load"] == "remote":
            nid0, eid = _remote_lines(o, c, w, nodes, nid0, eid, model, cload, bound, mass_sets)
            continue
        cload.append("** %s\n*CLOAD\n" % o.Label) if c["load"] in ("torque", "bearing") else None
        if c["load"] == "torque":
            base, ax = App.Vector(*c["base"]), App.Vector(*c["axis"]).normalize()
            vecs = {}
            for nid, wi in w.items():
                r = nodes[nid] - base
                r = r - ax * r.dot(ax)
                vecs[nid] = ax.cross(r) * wi                     # tangential, growing with the radius
            denom = sum(w[n] * ((nodes[n] - base) - ax * (nodes[n] - base).dot(ax)).Length ** 2 for n in w)
            if denom < 1e-12:
                raise RuntimeError("%s: the faces lie on the torque's axis." % o.Label)
            k = c["nmm"] / denom
        elif c["load"] == "bearing":
            base, ax, d = App.Vector(*c["base"]), App.Vector(*c["axis"]).normalize(), App.Vector(*c["dir"]).normalize()
            vecs = {}
            for nid, wi in w.items():
                r = nodes[nid] - base
                r = r - ax * r.dot(ax)
                if r.Length < 1e-12:
                    continue
                r.normalize()
                cos = max(-1.0, min(1.0, r.dot(d)))
                if cos <= 0:
                    continue
                th = math.acos(cos)
                s = cos if c["distribution"] == "Sinusoidal" else 1.0 - (th / (math.pi / 2)) ** 2
                vecs[nid] = r * (wi * s)
            total = sum((v.dot(d) for v in vecs.values()), 0.0)
            if total < 1e-12:
                raise RuntimeError("%s: no face area faces the load direction." % o.Label)
            k = c["n"] / total
        else:
            tot = sum(w.values())
            name = "FWMASS%s" % o.Name.upper()
            ids = []
            for nid, wi in sorted(w.items()):
                eid += 1
                ids.append(eid)
                model.append("*ELEMENT, TYPE=MASS, ELSET=%s_%d\n%d,%d\n*MASS, ELSET=%s_%d\n%.13G\n"
                             % (name, eid, eid, nid, name, eid, c["t"] * wi / tot))
            model.append("*ELSET, ELSET=%s\n" % name + "".join("%d,\n" % i for i in ids))
            mass_sets.append(name)
            continue
        for nid in sorted(vecs):
            v = vecs[nid] * k
            for dof, comp in enumerate((v.x, v.y, v.z), 1):
                if abs(comp) > 1e-15:
                    cload.append("%d,%d,%.13G\n" % (nid, dof, comp))
    out, in_step, put_loads, in_dload = [], False, False, False
    for line in lines:
        up = line.upper()
        if up.startswith("*STEP") and not in_step:
            out.extend(model)
            in_step = True
        if in_step and not put_loads and (up.startswith("*NODE FILE") or up.startswith("*END STEP")):
            out.extend(bound)
            out.extend(cload)
            put_loads = True
        if in_dload and mass_sets and not line.startswith("*") and (",GRAV," in up or ",CENTRIF," in up):
            out.append(line)
            rest = line.split(",", 1)[1]
            for m in mass_sets:
                out.append("%s,%s" % (m, rest))
            continue
        if line.startswith("*") and not line.startswith("**"):
            in_dload = up.startswith("*DLOAD")
        out.append(line)
    return out, len(loads) + len(spins)


def _remote_lines(o, c, w, nodes, nid, eid, model, cload, bound, mass_sets):
    """One Remote Loads/Mass item: Rigid (a CalculiX rigid body from the point to the faces, the mass and its inertia
    cross on it) or Distributed (nodal forces / masses / displacements spread over the faces by area)."""
    import numpy as np
    p = App.Vector(*c["p"])
    tot = sum(w.values()) or 1.0
    w = {n: x / tot for n, x in w.items()}
    tag = "FWREMOTE%s" % o.Name.upper()
    masses = []                                        # (node, tonnes)
    if c["conn"] == "Rigid":
        ref, rot = nid + 1, nid + 2
        nid += 2
        model.append("*NODE\n%d,%.13G,%.13G,%.13G\n%d,%.13G,%.13G,%.13G\n" % (ref, p.x, p.y, p.z, rot, p.x, p.y, p.z))
        extra = []
        if c["type"] == "Load/Mass" and c.get("t"):
            centre, arm = _cross(c["t"], c.get("I") or [0.0] * 6) if any(c.get("I") or []) else (c["t"], [])
            masses.append((ref, centre))
            for v, m in arm:
                nid += 1
                q = p + v
                model.append("*NODE\n%d,%.13G,%.13G,%.13G\n" % (nid, q.x, q.y, q.z))
                extra.append(nid)
                masses.append((nid, m))
        ids = sorted(w) + extra
        model.append("*NSET, NSET=%s\n" % tag + "".join("%d,\n" % n for n in ids))
        model.append("*RIGID BODY, NSET=%s, REF NODE=%d, ROT NODE=%d\n" % (tag, ref, rot))
        if c["type"] == "Load/Mass":
            cl = ["%d,%d,%.13G\n" % (ref, k + 1, v) for k, v in enumerate(c["f"]) if abs(v) > 1e-15]
            cl += ["%d,%d,%.13G\n" % (rot, k + 1, v) for k, v in enumerate(c["m"]) if abs(v) > 1e-15]
            if cl:
                cload.append("** %s\n*CLOAD\n" % o.Label)
                cload.extend(cl)
        else:
            bl = ["%d,%d,%d,%.13G\n" % (ref, k + 1, k + 1, v) for k, v in enumerate(c["u"]) if v is not None]
            bl += ["%d,%d,%d,%.13G\n" % (rot, k + 1, k + 1, v) for k, v in enumerate(c["r"]) if v is not None]
            bound.append("** %s\n*BOUNDARY\n" % o.Label)
            bound.extend(bl)
    else:
        pts = {n: nodes[n] for n in w}
        ctr = App.Vector()
        for n, x in w.items():
            ctr = ctr + pts[n] * x
        if c["type"] == "Load/Mass":
            F = App.Vector(*c["f"])
            M = App.Vector(*c["m"]) + (p - ctr).cross(F)
            S = np.zeros((3, 3))
            for n, x in w.items():
                d = np.array(tuple(pts[n] - ctr))
                S += x * (d.dot(d) * np.eye(3) - np.outer(d, d))
            th = App.Vector(*np.linalg.lstsq(S, np.array(tuple(M)), rcond=None)[0]) if M.Length > 0 else App.Vector()
            cl = []
            for n in sorted(w):
                v = F * w[n] + th.cross(pts[n] - ctr) * w[n]
                cl += ["%d,%d,%.13G\n" % (n, k + 1, x) for k, x in enumerate((v.x, v.y, v.z)) if abs(x) > 1e-15]
            if cl:
                cload.append("** %s\n*CLOAD\n" % o.Label)
                cload.extend(cl)
            if c.get("t"):
                masses += [(n, c["t"] * w[n]) for n in sorted(w)]
        else:
            bound.append("** %s\n*BOUNDARY\n" % o.Label)
            for n in sorted(w):
                bound += ["%d,%d,%d,%.13G\n" % (n, k + 1, k + 1, v) for k, v in enumerate(c["u"]) if v is not None]
    if masses:
        ids = []
        for n, m in masses:
            if m <= 0:
                continue
            eid += 1
            ids.append(eid)
            model.append("*ELEMENT, TYPE=MASS, ELSET=%s_%d\n%d,%d\n*MASS, ELSET=%s_%d\n%.13G\n" % (tag, eid, eid, n, tag, eid, m))
        model.append("*ELSET, ELSET=%s\n" % tag + "".join("%d,\n" % i for i in ids))
        mass_sets.append(tag)
    return nid, eid


def _density(analysis):
    for o in analysis.Group:
        mat = getattr(o, "Material", None)
        if isinstance(mat, dict) and mat.get("Density"):
            try:
                return App.Units.Quantity(mat["Density"]).getValueAs("t/mm^3").Value
            except Exception as _fw_err:
                _fw_log("simpms.py:rho", _fw_err)
    return 7.85e-9


def _angular_loads(femmesh, analysis, k):
    """Nodal inertia forces of an angular acceleration alpha about the axis: -rho (alpha x r) over every solid
    element, integrated with its shape functions (4 points for a 10-node, 1 for a 4-node tetrahedron)."""
    import numpy as np
    rho = _density(analysis)
    base, ax = np.array(k["base"], dtype=float), np.array(k["dir"], dtype=float)
    ax = ax / np.linalg.norm(ax)
    al = ax * float(k["alpha"])
    out = {}
    a_, b_ = 0.5854101966249685, 0.1381966011250105
    gauss = [tuple(a_ if i == j else b_ for i in range(4)) for j in range(4)]
    dl = ((-1.0, -1.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    pairs = None
    for v in femmesh.Volumes:
        n = femmesh.getElementNodes(v)
        X = np.array([tuple(femmesh.getNodeById(i)) for i in n])
        if len(n) == 4:
            vol = abs(np.dot(X[1] - X[0], np.cross(X[2] - X[0], X[3] - X[0]))) / 6.0
            c = X.mean(axis=0)
            r = (c - base) - ax * np.dot(c - base, ax)
            f = -rho * np.cross(al, r) * vol / 4.0
            for i in n:
                out[i] = out.get(i, np.zeros(3)) + f
            continue
        if len(n) != 10:
            continue
        if pairs is None:
            pairs = []
            for m in range(4, 10):
                pairs.append(min(((i, j) for i in range(4) for j in range(i + 1, 4)),
                                 key=lambda ij: np.linalg.norm((X[ij[0]] + X[ij[1]]) / 2 - X[m])))
        for L in gauss:
            N = [L[i] * (2 * L[i] - 1) for i in range(4)] + [4 * L[i] * L[j] for i, j in pairs]
            D = [[(4 * L[i] - 1) * dl[i][c] for c in range(3)] for i in range(4)]
            D += [[4 * (L[i] * dl[j][c] + L[j] * dl[i][c]) for c in range(3)] for i, j in pairs]
            J = X.T.dot(np.array(D))
            x = np.array(N).dot(X)
            r = (x - base) - ax * np.dot(x - base, ax)
            f = -rho * np.cross(al, r) * abs(np.linalg.det(J)) / 24.0
            for i, Ni in zip(n, N):
                out[i] = out.get(i, np.zeros(3)) + Ni * f
    return {i: App.Vector(*f) for i, f in out.items()}


# --------------------------------------------------------------------------- mesh
def gmsh_of(a):
    for o in (a.Group if a is not None else []):
        if getattr(getattr(o, "Proxy", None), "Type", "") == "Fem::FemMeshGmsh":
            return o
    return None


def default_size(shape):
    ""
    return max(shape.BoundBox.DiagonalLength / 25.0, 0.5)


def size_at(shape, density):
    """The density slider, 0 Coarse ... 10 Fine: twice the default size at Coarse, half at Fine."""
    return default_size(shape) * 2.0 ** ((5 - max(0, min(10, int(density)))) / 5.0)


def _gmsh(a, m):
    """Gmsh on m (through the run window when there is one), timed for Mesh Details. Returns Gmsh's error or ""."""
    import time
    t0 = time.time()
    try:
        from . import simrun
    except ImportError:
        simrun = None
    if simrun is not None:
        try:
            if simrun.begin(a):
                w = simrun.STATE.get("window")
                if w is not None:
                    w.setWindowTitle("Mesh Progress")
            err = simrun.mesh(m)
        finally:
            simrun.end()
    else:
        from femmesh.gmshtools import GmshTools
        err = GmshTools(m).create_mesh()
    try:
        from . import simmeshinfo
        simmeshinfo.TIMES[m.Name] = time.time() - t0
    except Exception as _fw_err:
        _fw_log("simpms.py:meshtime", _fw_err)
    if not err and not m.FemMesh.VolumeCount and not m.FemMesh.FaceCount and not m.FemMesh.EdgeCount:   # a beam: edges
        err = "Gmsh made no elements"
    return err or ""


def set_mesh(a, kind="Standard", size=None, tolerance=None, max_size=None, min_size=None, circle=8, draft=False,
             unit="mm", mesh_now=True, run=False, jacobian="16 points", trials=False, warn=True, transition=False):
    ""






    m = gmsh_of(a)
    if m is None:
        raise SetupError("The study has no mesh to set up (it was made without one).")
    k = LENGTH_UNITS.get(unit, 1.0)
    if kind == "Standard":
        if not size or size <= 0:
            raise SetupError("Give the global element size.")
        if tolerance is not None and (tolerance <= 0 or tolerance >= size):
            raise SetupError("The tolerance is above zero and below the global size.")
        m.CharacteristicLengthMax = "%r mm" % (size * k)
        m.CharacteristicLengthMin = "0 mm"
        m.MeshSizeFromCurvature = 8 if transition else 0
    elif kind == "Curvature-based":
        if not max_size or max_size <= 0 or min_size is None or min_size < 0 or min_size > max_size:
            raise SetupError("Give a maximum element size, and a minimum no bigger than it.")
        m.CharacteristicLengthMax = "%r mm" % (max_size * k)
        m.CharacteristicLengthMin = "%r mm" % (min_size * k)
        m.MeshSizeFromCurvature = max(1, int(circle))
    else:
        raise SetupError("Unknown mesh type %r." % kind)
    from . import simmeshq
    if jacobian not in simmeshq.POINTS:
        raise SetupError("Unknown Jacobian points %r." % jacobian)
    m.ElementOrder = "1st" if draft else "2nd"
    _keep(m, kind=kind, size=size, tolerance=tolerance if kind == "Standard" else None, max_size=max_size,
          min_size=min_size, circle=int(circle), draft=bool(draft), unit=unit, jacobian=jacobian, trials=bool(trials),
          warn=bool(warn), transition=bool(transition) if kind == "Standard" else False)
    if mesh_now or run:
        err = _gmsh(a, m)
        tries = 0
        while err and trials and tries < 3:
            tries += 1
            for p in ("CharacteristicLengthMax", "CharacteristicLengthMin"):
                q = App.Units.Quantity(getattr(m, p)).getValueAs("mm").Value
                setattr(m, p, "%r mm" % (q * 0.8))
            App.Console.PrintMessage("FreeCAD: mesh trial %d with the element size x%.3g\n" % (tries + 1, 0.8 ** tries))
            err = _gmsh(a, m)
        if err:
            raise SetupError("Meshing failed: %s" % err)
        from . import addintabs
        addintabs.mark_meshed(m)
        if not draft and warn:
            s = simmeshq.summary(m)
            if s["distorted"]:
                raise SetupError("The mesh has %d distorted element(s): a Jacobian at or below zero at the %s. Try a "
                                 "smaller element size or a curvature-based mesh (Mesh Quality Plot > Jacobian shows "
                                 "them in red)." % (s["distorted"], jacobian))
    a.Document.recompute()
    if run:
        from . import addintabs
        addintabs.run_study(a)
    return m


RESULT_TYPES = ("Fem::FemResultObject", "Fem::FemPostPipeline")


def study_results(a):
    """The study's result objects (what a remesh throws away)."""
    if a is None:
        return []
    return [o for o in a.Group if any(o.isDerivedFrom(t) for t in RESULT_TYPES)]


def drop_results(a):
    ""
    try:
        from . import simplots
        simplots.clear()
    except Exception as _fw_err:
        _fw_log("simpms.py:drop_plots", _fw_err)
    for o in study_results(a):
        try:
            a.Document.removeObject(o.Name)
        except Exception as _fw_err:
            _fw_log("simpms.py:drop_results", _fw_err)


# =========================================================================== GUI
if Gui is not None:

    class _PM:
        """Shared parts: pick boxes that take picks while light blue, OK / Cancel, one Undo step."""
        PM = "Fixture"
        ICON = None

        def __init__(self, doc, edit=None):
            self.doc, self.edit = doc, edit
            self.a = active_study(doc)
            self.obj = target(doc, self.a)
            self.boxes = []
            self.current = None
            self.faces_only = [True]

        def _activate(self, box):
            self.current = box
            for b in self.boxes:
                b.active(b is box)

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name or self.current is None:
                return
            QtCore.QTimer.singleShot(0, lambda: self._picked(name, sub) if self._open() else None)

        def _open(self):
            """False once the panel is gone without OK or Cancel (another command took the task pane): the pick
            listener is dropped then, so a later pick does not reach a closed panel."""
            try:
                form = list(self.form) if isinstance(self.form, (list, tuple)) else [self.form]
                for w in form + list(getattr(self, "boxes", None) or []) + [getattr(self, "ref", None)]:
                    if w is not None:
                        w.objectName()
                return True
            except RuntimeError:
                try:
                    Gui.Selection.removeObserver(self)
                except Exception as _fw_err:
                    _fw_log("simpms.py:stale", _fw_err)
                return False

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            box = self.current
            if box is None:
                return
            if box is self.boxes[0]:
                if last.startswith("Face"):
                    box.toggle(last)
            else:
                box.clear()
                box.addItem("%s:%s" % (name, last))
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simpms.py:pick", _fw_err)

        def _start(self):
            first = self.boxes[0]
            if self.edit is None:
                for f in sx._picked_faces(self.doc, self.obj):
                    if not first.findItems(f, QtCore.Qt.MatchExactly):
                        first.addItem(f)
            for b in self.boxes:
                b.activated_box.connect(self._activate)
                b.model().rowsInserted.connect(lambda *_: self.preview())
                b.model().rowsRemoved.connect(lambda *_: self.preview())
            self._activate(first)
            QtCore.QTimer.singleShot(0, self.preview)
            self._mesh_unpickable()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _mesh_unpickable(self):
            ""


            self._unpickable = []
            for o in (self.a.Group if self.a is not None else []):
                try:
                    if o.isDerivedFrom("Fem::FemMeshObject") and o.ViewObject is not None and \
                            "Selectable" in o.ViewObject.PropertiesList and o.ViewObject.Selectable:
                        o.ViewObject.Selectable = False
                        self._unpickable.append(o)
                except Exception as _fw_err:
                    _fw_log("simpms.py:unpickable", _fw_err)

        def _mesh_pickable(self):
            for o in getattr(self, "_unpickable", None) or []:
                try:
                    o.ViewObject.Selectable = True
                except Exception as _fw_err:
                    _fw_log("simpms.py:pickable", _fw_err)
            self._unpickable = []


        PREVIEW_FACE = (0.35, 0.6, 1.0)
        ARROW = (0.55, 0.1, 0.75)                   # the load symbols' purple

        def _arrows(self):
            """[(tip, unit direction)] of the load symbols to draw; none on the base PM."""
            return []

        def preview(self):
            """Draw the picked faces (light blue) and the arrows again; called on every change of the page."""
            try:
                self._unpreview()
                if self.obj is None or not self.boxes:
                    return
                from pivy import coin
                root = coin.SoSeparator()
                shape = self.obj.Shape
                pts, tris = [], []
                for name in self.boxes[0].values():
                    if not name.startswith("Face"):
                        continue
                    f = shape.getElement(name)
                    vs, ts = f.tessellate(max(0.05, shape.BoundBox.DiagonalLength / 400.0))
                    k = len(pts)
                    pts += [(v.x, v.y, v.z) for v in vs]
                    for t in ts:
                        tris += [k + t[0], k + t[1], k + t[2], -1]
                if tris:
                    face = coin.SoSeparator()
                    m = coin.SoMaterial()
                    m.diffuseColor = self.PREVIEW_FACE
                    m.emissiveColor = tuple(c * 0.5 for c in self.PREVIEW_FACE)
                    m.transparency = 0.35
                    face.addChild(m)
                    off = coin.SoPolygonOffset()
                    off.factor = -2.0
                    off.units = -2.0
                    face.addChild(off)
                    c = coin.SoCoordinate3()
                    c.point.setValues(0, len(pts), pts)
                    face.addChild(c)
                    fs = coin.SoIndexedFaceSet()
                    fs.coordIndex.setValues(0, len(tris), tris)
                    face.addChild(fs)
                    root.addChild(face)
                size = shape.BoundBox.DiagonalLength * 0.12 or 10.0
                for tip, d in self._arrows():
                    root.addChild(self._arrow(coin, tip, d, size))
                if root.getNumChildren():
                    sg = Gui.ActiveDocument.ActiveView.getSceneGraph()
                    sg.addChild(root)
                    self._preview_node = (sg, root)
            except Exception as _fw_err:
                _fw_log("simpms.py:preview", _fw_err)

        def _arrow(self, coin, tip, d, size):
            """A shaft and a cone head ending at tip, pointing along d."""
            sep = coin.SoSeparator()
            m = coin.SoMaterial()
            m.diffuseColor = self.ARROW
            m.emissiveColor = self.ARROW
            sep.addChild(m)
            tail = tip - d * size
            c = coin.SoCoordinate3()
            c.point.setValues(0, 2, [(tail.x, tail.y, tail.z), (tip.x, tip.y, tip.z)])
            sep.addChild(c)
            ds = coin.SoDrawStyle()
            ds.lineWidth = 2.0
            sep.addChild(ds)
            ls = coin.SoLineSet()
            ls.numVertices.setValue(2)
            sep.addChild(ls)
            head = coin.SoSeparator()
            tr = coin.SoTransform()
            h = size * 0.28
            at = tip - d * (h / 2.0)
            tr.translation.setValue(at.x, at.y, at.z)
            rot = App.Rotation(App.Vector(0, 1, 0), d)
            tr.rotation.setValue(*rot.Q)
            head.addChild(tr)
            cone = coin.SoCone()
            cone.height = h
            cone.bottomRadius = h * 0.35
            head.addChild(cone)
            sep.addChild(head)
            return sep

        def _unpreview(self):
            node = getattr(self, "_preview_node", None)
            self._preview_node = None
            if node is not None:
                try:
                    node[0].removeChild(node[1])
                except Exception as _fw_err:
                    _fw_log("simpms.py:unpreview", _fw_err)

        def _ref(self, box):
            vals = box.values()
            if not vals:
                return None
            name, sub = vals[0].split(":", 1)
            return (self.doc.getObject(name), sub)

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def reject(self):
            self._close()
            return True

        def _close(self):
            self._unpreview()
            self._mesh_pickable()
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("simpms.py:close", _fw_err)
            Gui.Control.closeDialog()

        def accept(self):
            if self.a is None or self.obj is None:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, "Make a study first (Simulation > New Study).")
                return False
            self.doc.openTransaction(self.PM)
            try:
                self.made = self.apply()
            except SetupError as e:
                self.doc.abortTransaction()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            except Exception:
                self.doc.abortTransaction()
                raise
            self.doc.commitTransaction()
            self._close()
            return True

    class FixturesPM(_PM):
        PM = "Fixture"

        def __init__(self, doc, kind="Fixed Geometry", edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            kind = k.get("kind", kind)

            msg = sx._box("Example", "TOOLS_SENSOR", self.PM)
            self.example = QtWidgets.QLabel()
            self.example.setObjectName("SWSimFixExample")
            self.example.setAlignment(QtCore.Qt.AlignCenter)
            self.example.setMinimumHeight(110)
            QtWidgets.QVBoxLayout(msg).addWidget(self.example)
            std = sx._box("Standard (%s)" % kind if kind in STANDARD else "Standard")
            sl = QtWidgets.QVBoxLayout(std)
            self.kinds = {}
            group = QtWidgets.QButtonGroup(std)
            group.setExclusive(True)
            for name in STANDARD:
                b = _type_button(name, "SWSimFix_" + name.replace("/", "").replace(" ", ""))
                group.addButton(b)
                self.kinds[name] = b
            sl.addLayout(_button_grid([self.kinds[n] for n in STANDARD]))
            self.faces = sx._PickList("SWSimFixFaces")
            self.faces.setToolTip("The faces held: click them in the graphics area; a second click takes one out")
            sl.addWidget(self.faces)
            adv = sx._box("Advanced")
            al = QtWidgets.QVBoxLayout(adv)
            self.std, self.adv, self.std_layout, self.adv_layout = std, adv, sl, al
            for name in ADVANCED:
                b = _type_button(name, "SWSimFix_" + name.replace(" ", ""))
                group.addButton(b)
                self.kinds[name] = b
            al.addLayout(_button_grid([self.kinds[n] for n in ADVANCED]))
            self.faces2 = sx._PickList("SWSimFixFaces2")
            self.faces2.setToolTip("Cyclic Symmetry: the face on the other side of the sector")
            al.addWidget(self.faces2)
            self.ref = sx._PickList("SWSimFixRef")
            self.ref.setFixedHeight(26)
            self.ref.setToolTip("A plane, a flat face or a straight edge: the directions the faces are held along")
            al.addWidget(self.ref)
            tr = sx._box("Translations")
            tl = QtWidgets.QFormLayout(tr)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimFixUnit")
            self.unit.addItems(list(LENGTH_UNITS))
            tl.addRow("Units:", self.unit)
            self.trans = []
            self.trans_labels = []
            for i, text in enumerate(("Along Dir 1", "Along Dir 2", "Normal")):
                on = QtWidgets.QCheckBox(text)
                on.setObjectName("SWSimFixOn%d" % i)
                v = QtWidgets.QDoubleSpinBox()
                v.setObjectName("SWSimFixValue%d" % i)
                v.setRange(-1e6, 1e6)
                v.setDecimals(3)
                v.setVisible(False)                    # no greyed box: the value shows once its direction is ticked
                on.toggled.connect(v.setVisible)
                tl.addRow(on, v)
                self.trans.append((on, v))
            self.tr_box = tr

            sym = sx._box("Symbol Settings")
            sy = QtWidgets.QFormLayout(sym)
            self.color = tuple(k["color"]) if k.get("color") else None
            self.color_button = QtWidgets.QPushButton("Edit Color...")
            self.color_button.setObjectName("SWSimFixColor")
            self.color_button.clicked.connect(self._pick_color)
            sy.addRow(self.color_button)
            self.size = QtWidgets.QSpinBox()
            self.size.setObjectName("SWSimFixSymbolSize")
            self.size.setRange(20, 500)
            self.size.setValue(int(k.get("size") or SYMBOL_SIZE))
            sy.addRow("Symbol size:", self.size)
            self._show_color()

            tabs = QtWidgets.QWidget()
            tabs.setProperty("swstyle_no_box_header", True)
            tb = QtWidgets.QVBoxLayout(tabs)
            tb.setContentsMargins(0, 0, 0, 0)
            self.tabs = QtWidgets.QTabBar()
            self.tabs.setObjectName("SWSimFixTabs")
            self.tabs.addTab("Type")
            self.tabs.addTab("Split")
            tb.addWidget(self.tabs)
            split = sx._box("Split")
            spl = QtWidgets.QVBoxLayout(split)
            self.split_hint = QtWidgets.QLabel("Pick a plane, a flat face or a sketch, then Create Split: the part is "
                                               "split along it, so the fixture can hold a part of a face.")
            self.split_hint.setWordWrap(True)
            spl.addWidget(self.split_hint)
            self.split_tool = sx._PickList("SWSimFixSplitTool")
            self.split_tool.setFixedHeight(26)
            self.split_tool.setToolTip("Splitting tool: a plane, a flat face or a sketch")
            spl.addWidget(self.split_tool)
            self.split_button = QtWidgets.QPushButton("Create Split")
            self.split_button.setObjectName("SWSimFixCreateSplit")
            self.split_button.clicked.connect(self._split)
            spl.addWidget(self.split_button)
            self.split_box = split
            self.type_boxes = [msg, std, adv, tr, sym]
            self.tabs.currentChanged.connect(self._tab_changed)
            self.kinds[kind].setChecked(True)
            group.buttonToggled.connect(lambda *_: self._kind_changed())
            self.boxes = [self.faces, self.faces2, self.ref, self.split_tool]
            self.form = [tabs, msg, std, adv, tr, sym, split]
            if edit is not None:
                for _o, subs in edit.References[:1] if k.get("kind") == "Cyclic Symmetry" else edit.References:
                    self.faces.addItems([subs] if isinstance(subs, str) else list(subs))
                for f in k.get("faces2") or []:
                    self.faces2.addItem(f)
                if k.get("ref"):
                    self.ref.addItem("%s:%s" % tuple(k["ref"]))
                self.unit.setCurrentText(k.get("unit") or "mm")
                for (on, v), t in zip(self.trans, k.get("translations") or (None, None, None)):
                    on.setChecked(t is not None)
                    v.setValue(t or 0.0)
            self.accordion = _Accordion(std, adv)
            self._kind_changed()
            self._start()
            from . import safe_later as _sl; _sl.later(0, self._shown, self, "tabs")

        def _shown(self):
            if self._open():
                self._tab_changed(self.tabs.currentIndex())
                QtCore.QTimer.singleShot(500, lambda: self._first_fold() if self._open() else None)   # after the page's layout passes

        def _first_fold(self):
            """Only the chosen type's box open (an Advanced type: Standard folded), then the accordion runs."""
            adv = self.kind() in ADVANCED
            self._titles(self.kind())
            _fold(self.std, not adv)
            _fold(self.adv, adv)
            QtCore.QTimer.singleShot(400, lambda: self.accordion.watch() if self._open() else None)

        def _titles(self, k):
            ""

            adv = k in ADVANCED
            _retitle(self.std, "Standard (%s)" % k if not adv else "Standard")
            _retitle(self.adv, "Advanced(%s)" % k if adv else "Advanced")
            src, dst = (self.std_layout, self.adv_layout) if adv else (self.adv_layout, self.std_layout)
            if src.indexOf(self.faces) >= 0:
                src.removeWidget(self.faces)
                dst.insertWidget(1, self.faces)                 # under the type buttons
            if getattr(self.accordion, "ready", False):
                _fold(self.adv if adv else self.std, True)
                _fold(self.std if adv else self.adv, False)

        def kind(self):
            return next(n for n, b in self.kinds.items() if b.isChecked())

        def _kind_changed(self):
            k = self.kind()
            if hasattr(self, "accordion"):
                self._titles(k)
            if not self._split_tab():

                ref = k in ("Use Reference Geometry", "Cyclic Symmetry")
                self.ref.setVisible(ref)
                self.faces2.setVisible(k == "Cyclic Symmetry")
                if (self.current is self.ref and not ref) or (self.current is self.faces2 and k != "Cyclic Symmetry"):
                    self._activate(self.faces)
                _box_visible(self.tr_box, k in DIRECTIONS)
                QtCore.QTimer.singleShot(0, lambda: self._open() and not self._split_tab()
                                         and _box_visible(self.tr_box, self.kind() in DIRECTIONS))
            for (on, _v), text in zip(self.trans, DIRECTIONS.get(k, ("Along Dir 1", "Along Dir 2", "Normal"))):
                on.setText(text)
            self.ref.setToolTip("The axis of symmetry: an axis, a straight edge or a round face" if k == "Cyclic Symmetry"
                                else "A plane, a flat face or a straight edge: the directions the faces are held along")
            self.faces.setToolTip("Cyclic Symmetry: the face on one side of the sector" if k == "Cyclic Symmetry"
                                  else "The faces held: click them in the graphics area; a second click takes one out")
            words = {"Fixed Geometry": "The faces do not move or turn.",
                     "Roller/Slider": "Flat faces slide in their own plane; they do not move off it.",
                     "Fixed Hinge": "Round faces turn about their own axis only.",
                     "Symmetry": "The flat faces the part was cut along at a plane of symmetry: they do not move off it.",
                     "Cyclic Symmetry": "One sector of a round part: pick the cut face on each side and the axis. "
                                          "The sector angle must divide 360 deg evenly.",
                     "Use Reference Geometry": "The faces are held along the reference's directions you tick.",
                     "On Flat Faces": "Flat faces held along the directions you tick (Normal: off the face).",
                     "On Cylindrical Faces": "Round faces held along the directions you tick: Radial (off the axis), "
                                             "Circumferential (around it), Axial (along it).",
                     "On Spherical Faces": "Spherical faces held along the directions you tick: Radial and Latitude go "
                                           "together at 0; Longitude turns about the sphere's axis."}
            self.example.setPixmap(_type_picture(k, 220, 141))
            self.example.setToolTip(words[k])
            self.faces.setStatusTip(words[k])

        def _split_tab(self):
            return getattr(self, "tabs", None) is not None and self.tabs.currentIndex() == 1

        def _tab_changed(self, i):
            on = i == 1
            for b in self.type_boxes:
                _box_visible(b, not on)
            _box_visible(self.split_box, on)
            if on:
                self._activate(self.split_tool)
            else:
                self._activate(self.faces)
                self._kind_changed()

        def _picked(self, name, sub):
            box = self.current
            if box is self.faces2:
                last = (sub or "").split(".")[-1]
                if last.startswith("Face"):
                    box.clear() if box.count() and box.item(0).text() != last else None
                    box.toggle(last)
                try:
                    Gui.Selection.clearSelection()
                except Exception as _fw_err:
                    _fw_log("simpms.py:pick2", _fw_err)
                return
            if box is self.split_tool and not (sub or "").split(".")[-1]:
                box.clear()
                box.addItem("%s:" % name)              # a sketch or a plane, picked whole
                try:
                    Gui.Selection.clearSelection()
                except Exception as _fw_err:
                    _fw_log("simpms.py:picktool", _fw_err)
                return
            super()._picked(name, sub)

        def _pick_color(self):
            c = QtGui.QColor.fromRgbF(*self.color) if self.color else QtGui.QColor(0, 160, 0)
            got = QtWidgets.QColorDialog.getColor(c, Gui.getMainWindow(), "Symbol Color")
            if got.isValid():
                self.color = (got.redF(), got.greenF(), got.blueF())
                self._show_color()

        def _show_color(self):
            if self.color:
                c = QtGui.QColor.fromRgbF(*self.color)
                self.color_button.setStyleSheet("QPushButton { border-left: 14px solid %s; }" % c.name())
            else:
                self.color_button.setStyleSheet("")

        def _split(self):
            vals = self.split_tool.values()
            tool = None
            if vals:
                name, sub = vals[0].split(":", 1)
                tool = (self.doc.getObject(name), sub)
            self.doc.openTransaction("Split Line")
            try:
                split = add_split(self.doc, self.a, tool)
            except SetupError as e:
                self.doc.abortTransaction()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return None
            self.doc.commitTransaction()
            self.obj = split
            self.faces.clear()
            self.faces2.clear()
            self.split_tool.clear()
            self.split_hint.setText("%s made: pick the faces to hold on the Type tab." % split.Label)
            self.tabs.setCurrentIndex(0)
            return split

        def apply(self):
            k = self.kind()
            trans = tuple(v.value() if on.isChecked() else None for on, v in self.trans) if k in DIRECTIONS else None
            ref = self._ref(self.ref) if k in ("Use Reference Geometry", "Cyclic Symmetry") else None
            return add_fixture(self.doc, self.a, self.obj, self.faces.values(), k, trans, self.unit.currentText(), ref,
                               self.edit, faces2=self.faces2.values() if k == "Cyclic Symmetry" else None,
                               color=self.color, size=self.size.value())

    class ForcePM(_PM):
        PM = "Force/Torque"

        def __init__(self, doc, edit=None, torque=False):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            torque = torque or k.get("kind") == "Torque"
            box = sx._box("Force/Torque", None, self.PM)
            form = QtWidgets.QFormLayout(box)

            self.is_force = _type_button("Force", "SWSimLoadForce")
            self.is_torque = _type_button("Torque", "SWSimLoadTorque")
            form.addRow(_button_grid([self.is_force, self.is_torque], 2))
            self._kind_group = QtWidgets.QButtonGroup(box)      # its own group: the radios below are another choice
            self._kind_group.addButton(self.is_force)
            self._kind_group.addButton(self.is_torque)
            self.faces = sx._PickList("SWSimForceFaces")
            self.normal = QtWidgets.QRadioButton("Normal")
            self.normal.setObjectName("SWSimForceNormal")
            self.selected = QtWidgets.QRadioButton("Selected direction")
            self.selected.setObjectName("SWSimForceSelected")
            self.normal.setChecked(True)
            self.direction = sx._PickList("SWSimForceDirection")
            self.direction.setFixedHeight(26)
            self.direction.setToolTip("An edge, face or plane: the force runs along it (normal to a face or plane)")
            self.unit = QtWidgets.QComboBox()          # the unit system; the value shows its unit (N, lbf, kgf)
            self.unit.setObjectName("SWSimForceUnit")
            self.unit.addItems(list(UNIT_SYSTEMS))
            from .pmspin import TrimSpin        # two decimals unless the value needs more (100.00, 0.125)
            self.value = TrimSpin()
            self.value.setObjectName("SWSimForceValue")
            self.value.setRange(0.0, 1e12)
            self.value.setDecimals(3)
            self.value.setValue(100.0)
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            self.reverse.setObjectName("SWSimForceReverse")
            self.per_item = QtWidgets.QRadioButton("Per item")
            self.per_item.setObjectName("SWSimForcePerItem")
            self.total = QtWidgets.QRadioButton("Total")
            self.total.setObjectName("SWSimForceTotal")
            self.per_item.setChecked(True)
            form.addRow(self.faces)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.normal)
            row.addWidget(self.selected)
            form.addRow(row)
            form.addRow("Direction:", self.direction)
            form.addRow("Unit system:", self.unit)
            form.addRow("Force:", self.value)
            form.addRow(self.reverse)
            row2 = QtWidgets.QHBoxLayout()
            row2.addWidget(self.per_item)
            row2.addWidget(self.total)
            form.addRow(row2)
            self.dir_label = form.labelForField(self.direction)
            self.value_label = form.labelForField(self.value)
            self._dir_group = QtWidgets.QButtonGroup(box)
            self._dir_group.addButton(self.normal)
            self._dir_group.addButton(self.selected)
            self._amount_group = QtWidgets.QButtonGroup(box)
            self._amount_group.addButton(self.per_item)
            self._amount_group.addButton(self.total)
            self.mode_row = (self.normal, self.selected)
            self.amount_row = (self.per_item, self.total)

            def _dir(on):                              # the direction box shows for Selected direction only
                tq = self.is_torque.isChecked()
                show = tq or not on
                self.direction.setVisible(show)
                if self.dir_label is not None:
                    self.dir_label.setVisible(show)
                if not show and self.current is self.direction:
                    self._activate(self.faces)
            self.normal.toggled.connect(_dir)
            self._dir = _dir

            # direction goes in the Direction box)
            self.selected.toggled.connect(lambda on: self._activate(self.direction) if on and not self.direction.count() else None)
            self.normal.toggled.connect(lambda *_: self.preview())
            self.reverse.toggled.connect(lambda *_: self.preview())
            (self.is_torque if torque else self.is_force).setChecked(True)
            self.is_torque.toggled.connect(lambda *_: (self._mode(), self.preview()))
            self.unit.currentTextChanged.connect(lambda *_: self._suffix())
            self.faces.model().rowsInserted.connect(lambda *_: self._amount())
            self.faces.model().rowsRemoved.connect(lambda *_: self._amount())
            self.boxes = [self.faces, self.direction]
            self.form = [box]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
                self._set_unit(k.get("unit", "N"), k.get("value", edit.Force.Value / 1000.0), sx.FORCE_UNITS, SYSTEM_FORCE)
                self.reverse.setChecked(k.get("reverse", False))
                (self.per_item if k.get("per_item") else self.total).setChecked(True)
                if k.get("direction"):
                    self.selected.setChecked(True)
                    self.direction.addItem("%s:%s" % tuple(k["direction"]))
                if k.get("axis"):
                    self.direction.addItem("%s:%s" % tuple(k["axis"]))
            if edit is None and inch_part(doc):
                self.unit.setCurrentText("English (IPS)")
            self._mode(first=True)
            if edit is not None and k.get("kind") == "Torque":
                self._set_unit(k.get("unit", "N.m"), k.get("value", 1.0), TORQUE_UNITS, SYSTEM_TORQUE)
            self._start()
            self._dir(self.normal.isChecked())
            self._amount()

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            if self.current is self.faces and last.startswith(("Edge", "Vertex")):

                # read, Loads); a force along a selected direction on edges or vertices is not made here either
                try:
                    Gui.Selection.clearSelection()
                except Exception as _fw_err:
                    _fw_log("simpms.py:force_edge", _fw_err)
                text = ("A normal force or a torque goes on faces only, not on an edge or a vertex. Pick faces."
                        if self.normal.isChecked() or self.is_torque.isChecked() else
                        "Pick faces: here a force goes on faces only, not on an edge or a vertex.")
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, text)
                return
            super()._picked(name, sub)

        def _arrows(self):
            ""

            if self.is_torque.isChecked():
                return []
            out = []
            fixed = None
            if self.selected.isChecked():
                ref = self._ref(self.direction)
                if ref is None:
                    return []
                fixed = direction_of(ref)
            for name in self.faces.values():
                try:
                    f = self.obj.Shape.getElement(name)
                    tip = f.CenterOfMass
                    if fixed is None:
                        u, v = f.Surface.parameter(tip)
                        d = -App.Vector(f.normalAt(u, v)).normalize()
                    else:
                        d = App.Vector(fixed)
                    if self.reverse.isChecked():
                        d = -d
                    out.append((tip, d))
                except Exception as _fw_err:
                    _fw_log("simpms.py:arrows", _fw_err)
            return out

        def _units(self):
            return SYSTEM_TORQUE if self.is_torque.isChecked() else SYSTEM_FORCE

        def _unit(self):
            """The unit the value is in: the unit system's force (N, lbf, kgf) or torque (N.m, lbf.in, kgf.cm)."""
            return self._units().get(self.unit.currentText(), "N")

        def _suffix(self):

            self.value.setSuffix("")
            self.value.setToolTip("%s (%s)" % ("Torque" if self.is_torque.isChecked() else "Force", self._unit()))

        def _set_unit(self, unit, value, table, systems):
            """An edited load: its system, and the value in that system's unit (an older N.mm / lbf.ft torque is
            shown in the SI or IPS unit)."""
            sysname = next((k for k, u in systems.items() if u == unit), None)
            if sysname is None:
                sysname = "English (IPS)" if unit.startswith("lbf") else "Metric (G)" if unit.startswith("kgf") else "SI"
                value = float(value) * table.get(unit, 1.0) / table[systems[sysname]]
            self.unit.setCurrentText(sysname)
            self.value.setValue(value)
            self._suffix()

        def _amount(self):

            many = self.faces.count() >= 2 and not self.is_torque.isChecked()
            for w in self.amount_row:
                w.setVisible(many)

        def _mode(self, first=False):
            """Force: Normal / Selected direction, newtons, Per item / Total. Torque: an axis (optional on round
            faces: their own axis), N.m, about the axis by the right-hand rule."""
            tq = self.is_torque.isChecked()
            for w in self.mode_row:
                w.setVisible(not tq)
            if not first:
                self.value.setValue(1.0 if tq else 100.0)
            self._suffix()
            if hasattr(self, "amount_row") and hasattr(self.faces, "count"):
                self._amount()
            if self.dir_label is not None:
                self.dir_label.setText("Axis:" if tq else "Direction:")
            if self.value_label is not None:
                self.value_label.setText("Torque:" if tq else "Force:")
            self.direction.setToolTip("The axis the torque turns about: an axis, a straight edge or a round face "
                                      "(none: the picked round faces' own axis)" if tq else
                                      "An edge, face or plane: the force runs along it (normal to a face or plane)")
            self.faces.setToolTip("Faces for Torque: pick them, then the axis below" if tq else "Faces for a normal force")
            self._dir(self.normal.isChecked())

        def apply(self):
            if self.is_torque.isChecked():
                return add_torque(self.doc, self.a, self.obj, self.faces.values(), self.value.value(),
                                  self._unit(), self._ref(self.direction), self.reverse.isChecked(), self.edit)
            direction = None
            if self.selected.isChecked():
                direction = self._ref(self.direction)
                if direction is None:
                    raise SetupError("Pick the direction (an edge, face or plane).")
            return add_force(self.doc, self.a, self.obj, self.faces.values(), self.value.value(), self._unit(),
                             direction, self.reverse.isChecked(),
                             self.per_item.isChecked() and len(self.faces.values()) > 1, self.edit)

    class PressurePM(_PM):
        ""

        PM = "Pressure"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            typ = sx._box("Type", None, self.PM)
            tl = QtWidgets.QFormLayout(typ)
            self.normal = QtWidgets.QRadioButton(PRESSURE_TYPES[0])
            self.normal.setObjectName("SWSimPressureNormal")
            self.use_ref = QtWidgets.QRadioButton(PRESSURE_TYPES[1])
            self.use_ref.setObjectName("SWSimPressureUseRef")
            self.normal.setChecked(True)
            tl.addRow(self.normal)
            tl.addRow(self.use_ref)
            self.faces = sx._PickList("SWSimPressureFaces")
            self.faces.setToolTip("Faces for Pressure")
            tl.addRow(self.faces)
            self.ref = sx._PickList("SWSimPressureRef")
            self.ref.setFixedHeight(26)
            self.ref.setToolTip("The direction: a plane or flat face (its normal), or an edge or axis (along it)")
            tl.addRow(self.ref)
            box = sx._box("Pressure Value")
            form = QtWidgets.QFormLayout(box)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimPressureUnit")
            self.unit.addItems(list(PRESSURE_UNITS))
            self.value = QtWidgets.QDoubleSpinBox()
            self.value.setObjectName("SWSimPressureValue")
            self.value.setRange(0.0, 1e12)
            self.value.setDecimals(3)
            self.value.setValue(1.0)
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            self.reverse.setObjectName("SWSimPressureReverse")
            form.addRow("Units:", self.unit)
            form.addRow("Pressure:", self.value)
            form.addRow(self.reverse)
            self.boxes = [self.faces, self.ref]
            self.form = [typ, box]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
                mpa = float(edit.Pressure.getValueAs("MPa")) if edit.TypeId == "Fem::ConstraintPressure" else 1.0
                self.value.setValue(k.get("value", mpa))
                self.unit.setCurrentText(PRESSURE_ALIASES.get(k.get("unit"), k.get("unit") or "N/mm^2 (MPa)"))
                self.reverse.setChecked(k.get("reverse", False))
                if k.get("ref"):
                    self.use_ref.setChecked(True)
                    self.ref.addItem("%s:%s" % tuple(k["ref"]))
            else:
                self.unit.setCurrentText("psi" if inch_part(doc) else "N/m^2")
            self.use_ref.toggled.connect(lambda *_: self._type())
            self._start()
            self._type()

        def _type(self):
            on = self.use_ref.isChecked()
            self.ref.setVisible(on)                    # hidden, not greyed, for Normal to selected face
            if not on and self.current is self.ref:
                self._activate(self.faces)

        def apply(self):
            ref = None
            if self.use_ref.isChecked():
                ref = self._ref(self.ref)
                if ref is None:
                    raise SetupError("Pick the reference: a plane, a flat face, an edge or an axis.")
            return add_pressure(self.doc, self.a, self.obj, self.faces.values(), self.value.value(), self.unit.currentText(),
                                self.reverse.isChecked(), self.edit, ref)

    class GravityPM(_PM):
        PM = "Gravity"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            msg = sx._box("Message", None, self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel(
                "Pick a plane or flat face (gravity acts along its normal) or a straight edge."))
            box = sx._box("Reference")
            form = QtWidgets.QFormLayout(box)
            self.ref = sx._PickList("SWSimGravityRef")
            self.ref.setFixedHeight(26)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimGravityUnit")
            self.unit.addItems(list(ACCEL_UNITS))
            self.value = QtWidgets.QDoubleSpinBox()
            self.value.setObjectName("SWSimGravityValue")
            self.value.setRange(0.0, 1e9)
            self.value.setDecimals(3)
            self.value.setValue(9.81)
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            self.reverse.setObjectName("SWSimGravityReverse")
            form.addRow(self.ref)
            form.addRow("Units:", self.unit)
            form.addRow("Gravity:", self.value)
            form.addRow(self.reverse)
            self.boxes = [self.ref]
            self.form = [msg, box]
            if edit is not None:
                if k.get("ref"):
                    self.ref.addItem("%s:%s" % tuple(k["ref"]))
                self.value.setValue(k.get("value", 9.81))
                self.unit.setCurrentText(k.get("unit", "m/s^2"))
                self.reverse.setChecked(k.get("reverse", False))
            self._start()

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            self.ref.clear()
            self.ref.addItem("%s:%s" % (name, last))
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simpms.py:gravity", _fw_err)

        def _start(self):
            sel = Gui.Selection.getSelectionEx(self.doc.Name, 0)
            if self.edit is None and sel:
                s = sel[0]
                sub = (s.SubElementNames[0].split(".")[-1] if s.SubElementNames else "")
                self.ref.addItem("%s:%s" % (s.Object.Name, sub))
            self.ref.activated_box.connect(self._activate)
            self._activate(self.ref)
            self._mesh_unpickable()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def apply(self):
            return add_gravity(self.doc, self.a, self._ref(self.ref), self.value.value(), self.unit.currentText(),
                               self.reverse.isChecked(), self.edit)

    def _spin(name, value, lo=0.0, hi=1e12, dec=3):
        w = QtWidgets.QDoubleSpinBox()
        w.setObjectName(name)
        w.setRange(lo, hi)
        w.setDecimals(dec)
        w.setValue(value)
        return w

    def _combo(name, items, current=None):
        w = QtWidgets.QComboBox()
        w.setObjectName(name)
        w.addItems(list(items))
        if current:
            w.setCurrentText(current)
        return w

    class BearingPM(_PM):
        PM = "Bearing Load"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            msg = sx._box("Message", None, self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel(
                "Pick the round faces (a shaft or a housing), then a plane, flat face or edge for the load's direction."))
            box = sx._box("Selection")
            form = QtWidgets.QFormLayout(box)
            self.faces = sx._PickList("SWSimBearingFaces")
            self.faces.setToolTip("The round faces the bearing pushes on")
            self.direction = sx._PickList("SWSimBearingDirection")
            self.direction.setFixedHeight(26)
            self.direction.setToolTip("The load's direction: a plane's or flat face's normal, or along an edge")
            form.addRow(self.faces)
            form.addRow("Direction:", self.direction)
            load = sx._box("Bearing Load")
            lf = QtWidgets.QFormLayout(load)
            self.unit = _combo("SWSimBearingUnit", sx.FORCE_UNITS, k.get("unit"))
            self.value = _spin("SWSimBearingValue", k.get("value", 1000.0))
            self.reverse = QtWidgets.QCheckBox("Reverse direction")
            self.reverse.setObjectName("SWSimBearingReverse")
            self.reverse.setChecked(bool(k.get("reverse")))
            self.sinus = QtWidgets.QRadioButton("Sinusoidal distribution")
            self.sinus.setObjectName("SWSimBearingSinusoidal")
            self.parab = QtWidgets.QRadioButton("Parabolic distribution")
            self.parab.setObjectName("SWSimBearingParabolic")
            (self.parab if k.get("distribution") == "Parabolic" else self.sinus).setChecked(True)
            lf.addRow("Units:", self.unit)
            lf.addRow("Force:", self.value)
            lf.addRow(self.reverse)
            lf.addRow(self.sinus)
            lf.addRow(self.parab)
            self.boxes = [self.faces, self.direction]
            self.form = [msg, box, load]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
                if k.get("direction"):
                    self.direction.addItem("%s:%s" % tuple(k["direction"]))
            self._start()

        def apply(self):
            return add_bearing(self.doc, self.a, self.obj, self.faces.values(), self.value.value(), self.unit.currentText(),
                               self._ref(self.direction), "Parabolic" if self.parab.isChecked() else "Sinusoidal",
                               self.reverse.isChecked(), self.edit)

    class DistributedMassPM(_PM):
        PM = "Distributed Mass"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            msg = sx._box("Message", None, self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel(
                "Pick the faces a mass sits on (a part left out of the study): it is spread over them by area."))
            box = sx._box("Distributed Mass")
            form = QtWidgets.QFormLayout(box)
            self.faces = sx._PickList("SWSimMassFaces")
            self.unit = _combo("SWSimMassUnit", MASS_UNITS, k.get("unit"))
            self.value = _spin("SWSimMassValue", k.get("value", 1.0))
            form.addRow(self.faces)
            form.addRow("Units:", self.unit)
            form.addRow("Mass:", self.value)
            self.boxes = [self.faces]
            self.form = [msg, box]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
            self._start()

        def apply(self):
            return add_distributed_mass(self.doc, self.a, self.obj, self.faces.values(), self.value.value(),
                                        self.unit.currentText(), self.edit)

    class CentrifugalPM(_PM):
        PM = "Centrifugal"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            msg = sx._box("Message", None, self.PM)
            QtWidgets.QVBoxLayout(msg).addWidget(QtWidgets.QLabel(
                "Pick the axis the whole part spins about: an axis, a straight edge or a round face."))
            box = sx._box("Selection")
            form = QtWidgets.QFormLayout(box)
            self.axis = sx._PickList("SWSimCentrifugalAxis")
            self.axis.setFixedHeight(26)
            form.addRow(self.axis)
            spin = sx._box("Centrifugal Force")
            sf = QtWidgets.QFormLayout(spin)
            self.unit = _combo("SWSimCentrifugalUnit", SPIN_UNITS, k.get("unit"))
            self.value = _spin("SWSimCentrifugalValue", k.get("value", 100.0))
            sf.addRow("Units:", self.unit)
            sf.addRow("Angular velocity:", self.value)
            self.accel_unit = _combo("SWSimCentrifugalAccelUnit", ACCEL_SPIN_UNITS, k.get("accel_unit"))
            self.accel = _spin("SWSimCentrifugalAccel", k.get("accel", 0.0), -1e9, 1e9)
            self.accel.setToolTip("Speeding up (negative: slowing down) about the axis: the part's inertia forces")
            sf.addRow("Acceleration units:", self.accel_unit)
            sf.addRow("Angular acceleration:", self.accel)
            self.boxes = [self.axis]
            self.form = [msg, box, spin]
            if edit is not None and k.get("axis"):
                self.axis.addItem("%s:%s" % tuple(k["axis"]))
            self._start()

        def _picked(self, name, sub):
            self.axis.clear()
            self.axis.addItem("%s:%s" % (name, (sub or "").split(".")[-1]))
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("simpms.py:centrif", _fw_err)

        def _start(self):
            sel = Gui.Selection.getSelectionEx(self.doc.Name, 0)
            if self.edit is None and sel:
                s0 = sel[0]
                self.axis.addItem("%s:%s" % (s0.Object.Name, s0.SubElementNames[0].split(".")[-1] if s0.SubElementNames else ""))
            self.axis.activated_box.connect(self._activate)
            self._activate(self.axis)
            self._mesh_unpickable()
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def apply(self):
            return add_centrifugal(self.doc, self.a, self._ref(self.axis), self.value.value(), self.unit.currentText(),
                                   self.edit, self.accel.value(), self.accel_unit.currentText())

    class RemoteLoadPM(_PM):
        """Remote Loads/Mass: Type (Load/Mass, Displacement) and Connection (Rigid, Distributed); the faces; the
        location; Translational / Rotational Components (force and moment, or translations and rotations, each one
        on its own check box); Remote Mass (mass, and the moments of inertia for Rigid)."""
        PM = "Remote Loads/Mass"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            k = kept(edit) if edit is not None else {}
            msg = sx._box("Message", None, self.PM)
            self.hint = QtWidgets.QLabel("")
            self.hint.setWordWrap(True)
            QtWidgets.QVBoxLayout(msg).addWidget(self.hint)
            typ = sx._box("Type")
            tl = QtWidgets.QFormLayout(typ)
            self.rtype = _combo("SWSimRemoteType", REMOTE_TYPES, k.get("rtype"))
            tl.addRow(self.rtype)
            self.conn = QtWidgets.QButtonGroup(typ)
            row = QtWidgets.QHBoxLayout()
            for i, t in enumerate(CONNECTIONS):
                rb = QtWidgets.QRadioButton(t)
                rb.setObjectName("SWSimRemote" + t)
                self.conn.addButton(rb, i)
                row.addWidget(rb)
            tl.addRow("Connection:", row)
            self.conn.button(CONNECTIONS.index(k.get("connection") or "Rigid")).setChecked(True)
            box = sx._box("Selection")
            form = QtWidgets.QFormLayout(box)
            self.faces = sx._PickList("SWSimRemoteFaces")
            form.addRow(self.faces)
            loc = sx._box("Location")
            lf = QtWidgets.QFormLayout(loc)
            self.len_unit = _combo("SWSimRemoteLengthUnit", LENGTH_UNITS, k.get("unit"))
            lf.addRow("Units:", self.len_unit)
            self.loc = []
            c = self.obj.Shape.BoundBox.Center if self.obj is not None else App.Vector()
            for i, ax in enumerate("XYZ"):
                w = _spin("SWSimRemoteLoc" + ax, (k.get("location") or list(c))[i], -1e9, 1e9)
                lf.addRow(ax + ":", w)
                self.loc.append(w)
            frc = sx._box("Translational Components")
            ff = QtWidgets.QFormLayout(frc)
            self.force_unit = _combo("SWSimRemoteForceUnit", sx.FORCE_UNITS, k.get("force_unit"))
            self.force_unit_label = QtWidgets.QLabel("Force units:")
            ff.addRow(self.force_unit_label, self.force_unit)
            self.force, self.trans = [], []
            tr = k.get("translation") or [None] * 3
            for i, ax in enumerate("XYZ"):
                w = _spin("SWSimRemoteForce" + ax, (k.get("force") or (0, 0, 0))[i], -1e12, 1e12)
                lab = QtWidgets.QLabel(ax + ":")
                ff.addRow(lab, w)
                self.force.append((lab, w))
            for i, ax in enumerate("XYZ"):
                cb = QtWidgets.QCheckBox("Translation " + ax)
                cb.setObjectName("SWSimRemoteHoldT" + ax)
                cb.setChecked(tr[i] is not None)
                w = _spin("SWSimRemoteTrans" + ax, tr[i] or 0.0, -1e9, 1e9)
                ff.addRow(cb, w)
                cb.toggled.connect(lambda *_: self._enable())
                self.trans.append((cb, w))
            mom = sx._box("Rotational Components")
            mf = QtWidgets.QFormLayout(mom)
            self.moment_unit = _combo("SWSimRemoteMomentUnit", TORQUE_UNITS, k.get("moment_unit"))
            self.moment_unit_label = QtWidgets.QLabel("Moment units:")
            mf.addRow(self.moment_unit_label, self.moment_unit)
            self.angle_unit = _combo("SWSimRemoteAngleUnit", ANGLE_UNITS, k.get("angle_unit"))
            self.angle_unit_label = QtWidgets.QLabel("Angle units:")
            mf.addRow(self.angle_unit_label, self.angle_unit)
            self.moment, self.rot = [], []
            ro = k.get("rotation") or [None] * 3
            for i, ax in enumerate("XYZ"):
                w = _spin("SWSimRemoteMoment" + ax, (k.get("moment") or (0, 0, 0))[i], -1e12, 1e12)
                lab = QtWidgets.QLabel(ax + ":")
                mf.addRow(lab, w)
                self.moment.append((lab, w))
            for i, ax in enumerate("XYZ"):
                cb = QtWidgets.QCheckBox("Rotation " + ax)
                cb.setObjectName("SWSimRemoteHoldR" + ax)
                cb.setChecked(ro[i] is not None)
                w = _spin("SWSimRemoteRot" + ax, ro[i] or 0.0, -1e9, 1e9)
                mf.addRow(cb, w)
                cb.toggled.connect(lambda *_: self._enable())
                self.rot.append((cb, w))
            self.mom_box = mom
            ms = sx._box("Remote Mass")
            sf = QtWidgets.QFormLayout(ms)
            self.mass_unit = _combo("SWSimRemoteMassUnit", MASS_UNITS, k.get("mass_unit"))
            sf.addRow("Mass units:", self.mass_unit)
            self.mass = _spin("SWSimRemoteMass", k.get("mass", 0.0))
            sf.addRow("Mass:", self.mass)
            self.inertia_unit = _combo("SWSimRemoteInertiaUnit", INERTIA_UNITS, k.get("inertia_unit"))
            self.inertia_rows = [(QtWidgets.QLabel("Inertia units:"), self.inertia_unit)]
            self.inertia = []
            for i, name in enumerate(("Ixx", "Iyy", "Izz", "Ixy", "Iyz", "Ixz")):
                w = _spin("SWSimRemote" + name, (k.get("inertia") or [0.0] * 6)[i], 0.0 if i < 3 else -1e12, 1e12, 6)
                self.inertia.append(w)
                self.inertia_rows.append((QtWidgets.QLabel(name + ":"), w))
            for lab, w in self.inertia_rows:
                sf.addRow(lab, w)
            self.mass_box = ms
            self.boxes = [self.faces]
            self.form = [msg, typ, box, loc, frc, mom, ms]
            if edit is not None:
                for _o, subs in edit.References:
                    self.faces.addItems(list(subs))
            self.rtype.currentTextChanged.connect(lambda *_: self._enable())
            self.conn.buttonToggled.connect(lambda *_: self._enable())
            self._enable()
            self._start()

        def _enable(self):
            # hidden, not greyed: each type and connection shows only the fields CalculiX gets
            load = self.rtype.currentText() == "Load/Mass"
            rigid = self.conn.checkedId() == 0
            for lab, w in self.force + self.moment:
                lab.setVisible(load)
                w.setVisible(load)
            for w in (self.force_unit, self.force_unit_label, self.moment_unit, self.moment_unit_label):
                w.setVisible(load)
            for cb, w in self.trans:
                cb.setVisible(not load)
                w.setVisible(not load and cb.isChecked())
            for cb, w in self.rot:
                cb.setVisible(not load and rigid)
                w.setVisible(not load and rigid and cb.isChecked())
            for w in (self.angle_unit, self.angle_unit_label):
                w.setVisible(not load and rigid)
            box_rot = load or rigid
            for lab, w in self.inertia_rows:
                lab.setVisible(rigid)
                w.setVisible(rigid)
            self.hint.setText(("Forces, moments and a mass at a point, " if load else "The point moved and turned, ")
                              + ("joined to the faces by a rigid arm (the faces keep their shape)." if rigid else
                                 "spread straight onto the faces (the faces deform freely)."))
            box_visible = (self.mom_box, box_rot), (self.mass_box, load)
            for b, on in box_visible:
                _box_visible(b, on)
            QtCore.QTimer.singleShot(0, lambda: self._open() and [_box_visible(b, on) for b, on in box_visible])

        def apply(self):
            load = self.rtype.currentText() == "Load/Mass"
            return add_remote(self.doc, self.a, self.obj, self.faces.values(), [w.value() for w in self.loc],
                              [w.value() for _l, w in self.force] if load else (0.0,) * 3,
                              [w.value() for _l, w in self.moment] if load else (0.0,) * 3,
                              self.len_unit.currentText(), self.force_unit.currentText(),
                              self.moment_unit.currentText(), self.edit, CONNECTIONS[max(0, self.conn.checkedId())],
                              self.rtype.currentText(), self.mass.value() if load else 0.0, self.mass_unit.currentText(),
                              [w.value() for w in self.inertia] if load and self.conn.checkedId() == 0 else (0.0,) * 6,
                              self.inertia_unit.currentText(),
                              [w.value() if cb.isChecked() else None for cb, w in self.trans] if not load else (None,) * 3,
                              [w.value() if cb.isChecked() and self.conn.checkedId() == 0 else None for cb, w in self.rot]
                              if not load else (None,) * 3, self.angle_unit.currentText())

    # ------------------------------------------------------------------ the fixture / load pictures
    # Drawn here (original art, nothing from another program): the Fixture PM's Example picture and the type buttons.
    GREEN, BLUE, PINK = "#1f9d3a", "#9cc8f0", "#d0408a"

    def _arrow(p, x0, y0, x1, y1, colour, head=None):
        from PySide import QtGui
        pen = QtGui.QPen(QtGui.QColor(colour))
        pen.setWidthF(max(1.0, p.device().width() / 90.0))
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y1))
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy) or 1.0
        h = head if head is not None else max(2.5, p.device().width() / 22.0)
        ux, uy = dx / n, dy / n
        for s in (1, -1):
            p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x1 - h * (ux - s * 0.55 * uy), y1 - h * (uy + s * 0.55 * ux)))

    def _poly(p, pts, fill, edge="#6b7a8c"):
        from PySide import QtGui
        p.setPen(QtGui.QPen(QtGui.QColor(edge), 1.0))
        p.setBrush(QtGui.QColor(fill))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts]))

    def _block(p, s, face=True):
        """A block seen from above-right; its right face is the picked face (blue)."""
        _poly(p, [(s(18, 26)), s(66, 26), s(66, 56), s(18, 56)], "#d6dbe2")
        _poly(p, [s(18, 26), s(34, 12), s(82, 12), s(66, 26)], "#eceff3")
        _poly(p, [s(66, 26), s(82, 12), s(82, 42), s(66, 56)], BLUE if face else "#c3c9d1")
        return [s(74, 22), s(74, 34), s(74, 46)]

    def _cylinder(p, s, face=True):
        from PySide import QtGui
        p.setPen(QtGui.QPen(QtGui.QColor("#6b7a8c"), 1.0))
        p.setBrush(QtGui.QColor(BLUE if face else "#d6dbe2"))
        x0, y0 = s(30, 18)
        x1, y1 = s(70, 52)
        rx, ry = (x1 - x0) / 2.0, (y1 - y0) / 7.0
        p.drawRect(QtCore.QRectF(x0, y0, x1 - x0, y1 - y0))
        p.setBrush(QtGui.QColor("#eceff3"))
        p.drawEllipse(QtCore.QRectF(x0, y0 - ry, 2 * rx, 2 * ry))
        p.setBrush(QtGui.QColor(BLUE if face else "#d6dbe2"))
        p.drawChord(QtCore.QRectF(x0, y1 - ry, 2 * rx, 2 * ry), 180 * 16, 180 * 16)
        return (x0 + x1) / 2.0, y0, y1, rx, ry

    def _type_picture(kind, w, h):
        """A QPixmap w x h of fixture or load type kind: the part, the picked face in blue, the symbols in green."""
        from PySide import QtGui
        pm = QtGui.QPixmap(w, h)
        pm.fill(QtGui.QColor(0, 0, 0, 0))
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        sx_, sy_ = w / 100.0, h / 64.0

        def s(x, y):
            return (x * sx_, y * sy_)
        L = 9.0 * sx_
        try:
            if kind in ("Fixed Hinge", "On Cylindrical Faces"):
                cx, y0, y1, rx, ry = _cylinder(p, s)
                p.setBrush(QtCore.Qt.NoBrush)
                if kind == "Fixed Hinge":
                    pen = QtGui.QPen(QtGui.QColor(GREEN), max(1.0, w / 90.0))
                    p.setPen(pen)
                    p.drawArc(QtCore.QRectF(cx - rx * 1.25, (y0 + y1) / 2 - ry * 1.6, rx * 2.5, ry * 3.2), 200 * 16, 300 * 16)
                    _arrow(p, cx + rx * 1.1, (y0 + y1) / 2 - ry * 0.9, cx + rx * 1.25, (y0 + y1) / 2 + 0.1, GREEN)
                    dash = QtGui.QPen(QtGui.QColor("#555"), 1.0, QtCore.Qt.DashLine)
                    p.setPen(dash)
                    p.drawLine(QtCore.QPointF(cx, y0 - ry * 2), QtCore.QPointF(cx, y1 + ry * 2))
                else:
                    ym = (y0 + y1) / 2
                    _arrow(p, cx + rx + L, ym, cx + rx, ym, GREEN)                    # radial
                    _arrow(p, cx + rx * 0.4, y1 + ry * 1.6, cx + rx * 0.95, y1 + ry * 0.4, GREEN)   # circumferential
                    _arrow(p, cx - rx - L * 0.2, y1 - L * 0.2, cx - rx - L * 0.2, y0 + L * 0.6, GREEN)  # axial
            elif kind == "On Spherical Faces":
                p.setPen(QtGui.QPen(QtGui.QColor("#6b7a8c"), 1.0))
                p.setBrush(QtGui.QColor(BLUE))
                (x0, y0), (x1, y1) = s(32, 10), s(68, 56)
                r = min(x1 - x0, y1 - y0) / 2.0
                cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
                p.drawEllipse(QtCore.QPointF(cx, cy), r, r)
                for ang in (20, 140, 260):
                    a = math.radians(ang)
                    _arrow(p, cx + (r + L) * math.cos(a), cy - (r + L) * math.sin(a), cx + r * math.cos(a), cy - r * math.sin(a), GREEN)
            elif kind == "Cyclic Symmetry":
                p.setPen(QtGui.QPen(QtGui.QColor("#6b7a8c"), 1.0))
                p.setBrush(QtGui.QColor("#d6dbe2"))
                (x0, y0), (x1, y1) = s(18, 6), s(82, 70)
                rect = QtCore.QRectF(x0, y0, x1 - x0, (y1 - y0))
                p.drawPie(rect, 45 * 16, 90 * 16)
                cx, cy = rect.center().x(), rect.center().y()
                rr = rect.width() / 2.0
                for ang in (45, 135):
                    a = math.radians(ang)
                    pen = QtGui.QPen(QtGui.QColor("#2a7fd0"), max(2.0, w / 40.0))
                    p.setPen(pen)
                    p.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(cx + rr * math.cos(a), cy - rr * math.sin(a)))
                p.setPen(QtGui.QPen(QtGui.QColor(GREEN), max(1.0, w / 90.0)))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawArc(QtCore.QRectF(cx - rr * 0.55, cy - rr * 0.55, rr * 1.1, rr * 1.1), 50 * 16, 80 * 16)
            else:
                pts = _block(p, s)
                if kind == "Symmetry":
                    dash = QtGui.QPen(QtGui.QColor(PINK), 1.2, QtCore.Qt.DashLine)
                    p.setPen(dash)
                    a, b = s(90, 6), s(90, 48)
                    p.drawLine(QtCore.QPointF(*a), QtCore.QPointF(*b))
                    for x, y in pts:
                        _arrow(p, x + L, y, x, y, GREEN)
                elif kind == "Roller/Slider":
                    for x, y in pts:
                        _arrow(p, x + L, y - L * 0.6, x, y, GREEN)
                    _arrow(p, s(88, 52)[0], s(88, 52)[1], s(88, 40)[0], s(88, 40)[1], GREEN)
                    _arrow(p, s(88, 40)[0], s(88, 40)[1], s(88, 52)[0], s(88, 52)[1], GREEN)
                elif kind == "Use Reference Geometry":
                    p.setPen(QtGui.QPen(QtGui.QColor(PINK), 1.2))
                    p.setBrush(QtGui.QColor(208, 64, 138, 40))
                    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(*s(4, 8)), QtCore.QPointF(*s(22, 2)),
                                                   QtCore.QPointF(*s(22, 22)), QtCore.QPointF(*s(4, 28))]))
                    for x, y in pts:
                        _arrow(p, x + L, y, x, y, GREEN)
                        _arrow(p, x + L * 0.5, y + L * 0.7, x, y, GREEN, head=0)
                elif kind == "On Flat Faces":
                    for x, y in pts:
                        _arrow(p, x + L, y - L * 0.6, x, y, GREEN)
                        _arrow(p, x, y + L * 0.9, x, y, GREEN, head=0)
                elif kind == "Force":
                    for x, y in pts:
                        _arrow(p, x + L * 1.3, y - L * 0.8, x, y, "#c2302a")
                elif kind == "Torque":
                    pen = QtGui.QPen(QtGui.QColor("#c2302a"), max(1.0, w / 90.0))
                    p.setPen(pen)
                    p.setBrush(QtCore.Qt.NoBrush)
                    cx, cy = s(74, 34)
                    rr = L * 1.4
                    p.drawArc(QtCore.QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr), 30 * 16, 290 * 16)
                    _arrow(p, cx + rr * 0.95, cy + rr * 0.15, cx + rr * 0.86, cy - rr * 0.5, "#c2302a")
                else:                                       # Fixed Geometry: held in every direction
                    for x, y in pts:
                        _arrow(p, x + L, y - L * 0.6, x, y, GREEN)
                        _arrow(p, x, y - L, x, y, GREEN, head=0)
                        _arrow(p, x + L * 0.9, y + L * 0.2, x, y, GREEN, head=0)
        finally:
            p.end()
        return pm

    def _type_button(name, key, size=34):
        ""

        from PySide import QtGui
        b = QtWidgets.QToolButton()
        b.setObjectName(key)
        b.setText(name)
        b.setToolTip(name)
        b.setCheckable(True)
        b.setAutoRaise(True)
        b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        b.setIcon(QtGui.QIcon(_type_picture(name, size * 2, int(size * 2 * 0.64))))
        b.setIconSize(QtCore.QSize(size, int(size * 0.64)))
        return b

    def _button_grid(buttons, per_row=3):
        g = QtWidgets.QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(4)
        for i, b in enumerate(buttons):
            g.addWidget(b, i // per_row, i % per_row)
        g.setColumnStretch(per_row, 1)
        return g

    def _group_of(w):
        g = w.parentWidget() if w is not None else None
        while g is not None and not g.inherits("QSint::ActionGroup"):
            g = g.parentWidget()
        return g

    def _retitle(w, text):
        ""
        w.setWindowTitle(text)
        g = _group_of(w)
        for lab in (g.findChildren(QtWidgets.QWidget) if g is not None else []):
            if lab.inherits("QSint::ActionLabel") and callable(getattr(lab, "setText", None)):
                lab.setText(text)
                return True
        return False

    def _fold(w, open_, tries=8):
        """Open or fold w's PM box. A box still folding or unfolding ignores the click, so it is tried again."""
        from . import pmlayout
        try:
            g = _group_of(w)
            # a hidden box (the Split tab is showing, the page is closing) is left alone: QSint's fold of a hidden
            # group renders an empty picture, which aborted FreeCAD on Windows (sim370 on the PC)
            if g is None or pmlayout._group_open(g) == open_:
                return
            shown = g.isVisible()
        except RuntimeError:
            return
        if shown:
            pmlayout._show_hide(g)
        if tries > 1:
            QtCore.QTimer.singleShot(350, lambda: _fold(w, open_, tries - 1))

    class _Accordion(QtCore.QObject):
        ""



        def __init__(self, first, second):
            super().__init__(first)
            self.pair = (first, second)
            self.ready = False
            self.was = {}

        def watch(self):
            from . import pmlayout
            for i, w in enumerate(self.pair):
                g = _group_of(w)
                h = pmlayout._header_of(g) if g is not None else None
                if h is None or h.property("fw_accordion") is not None:
                    continue
                # which box a title belongs to is kept on the widgets themselves (PySide's wrappers come and go, so
                # their id() cannot be a key)
                for c in [h] + list(h.findChildren(QtWidgets.QWidget)):
                    c.setProperty("fw_accordion", i)
                    c.installEventFilter(self)
            self.ready = True

        def _then_fold(self, w, other, tries):
            from . import pmlayout
            try:
                if pmlayout._group_open(_group_of(w)):
                    _fold(other, False)
                elif tries > 1:
                    QtCore.QTimer.singleShot(250, lambda: self._then_fold(w, other, tries - 1))
            except (RuntimeError, AttributeError):
                pass

        def eventFilter(self, obj, ev):
            try:
                i = obj.property("fw_accordion") if self.ready else None
                if i is None:
                    return False
                w = self.pair[int(i)]
                from . import pmlayout
                if ev.type() == QtCore.QEvent.MouseButtonPress:
                    self.was[int(i)] = pmlayout._group_open(_group_of(w))
                elif ev.type() == QtCore.QEvent.MouseButtonRelease and self.was.pop(int(i), True) is False:
                    # the other box folds once this one has really opened (a click during a fold is ignored by
                    # the task pane, and then nothing should fold)
                    other = self.pair[1 - int(i)]
                    QtCore.QTimer.singleShot(250, lambda: self._then_fold(w, other, 12))
            except RuntimeError:
                pass
            return False

    def _bodies(a):
        ""

        try:
            from . import asmsim
            if asmsim.is_assembly_study(a):
                names = []
                for n in asmsim.owners(asmsim.geometry(a)):
                    c = a.Document.getObject(n)
                    lab = c.Label if c is not None else n
                    if lab not in names:
                        names.append(lab)
                return names
        except Exception as _fw_err:
            _fw_log("simpms.py:bodies", _fw_err)
        o = target(a.Document, a) if a is not None else None
        return [o.Label] if o is not None else []

    class MeshPM(_PM):
        ""




        PM = "Mesh"

        def __init__(self, doc, edit=None):
            super().__init__(doc, edit)
            from . import simmeshq
            self.mesh = gmsh_of(self.a)
            k = kept(self.mesh) if self.mesh is not None else {}
            shape = self.obj.Shape if self.obj is not None else None
            self.base = default_size(shape) if shape is not None else 5.0
            tabs = QtWidgets.QWidget()
            tabs.setProperty("swstyle_no_box_header", True)
            tb = QtWidgets.QVBoxLayout(tabs)
            tb.setContentsMargins(0, 0, 0, 0)
            self.tabs = QtWidgets.QTabBar()
            self.tabs.setObjectName("SWSimMeshTabs")
            self.tabs.addTab("Definition")
            self.tabs.addTab("Mesh Quality")
            tb.addWidget(self.tabs)
            dens = sx._box("Mesh Density", None, self.PM)
            dl = QtWidgets.QVBoxLayout(dens)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel("Coarse"))
            self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.slider.setObjectName("SWSimMeshDensity")
            self.slider.setRange(0, 10)
            self.slider.setValue(5)
            self.slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
            try:                                # look-audit SIM-9: Dark's groove was a faint line with no fill
                from . import style
                if style.dark():
                    self.slider.setStyleSheet(
                        "QSlider#SWSimMeshDensity::groove:horizontal{height:4px;background:#5a606a;border-radius:2px}"
                        "QSlider#SWSimMeshDensity::sub-page:horizontal{background:#3d8ee8;border-radius:2px}"
                        "QSlider#SWSimMeshDensity::handle:horizontal{background:#e6e9ee;border:1px solid #9aa3ad;"
                        "width:10px;margin:-6px 0;border-radius:3px}")
            except Exception as _fw_err:
                _fw_log("simpms.py:meshslider", _fw_err)
            row.addWidget(self.slider, 1)
            row.addWidget(QtWidgets.QLabel("Fine"))
            dl.addLayout(row)
            self.reset = QtWidgets.QPushButton("Reset")
            self.reset.setObjectName("SWSimMeshReset")
            dl.addWidget(self.reset)
            self.warn = QtWidgets.QCheckBox("Issue warning for distorted elements")
            self.warn.setObjectName("SWSimMeshWarn")
            self.warn.setChecked(True)
            dl.addWidget(self.warn)
            par = sx._box("Mesh Parameters")
            pl = QtWidgets.QFormLayout(par)
            self.use_params = QtWidgets.QCheckBox("Mesh Parameters")      # moved into the box title by pmlayout
            self.use_params.setObjectName("SWSimMeshUseParams")
            pl.addRow(self.use_params)
            self.curved = QtWidgets.QRadioButton("Curvature-based mesh")
            self.curved.setObjectName("SWSimMeshCurvature")
            self.standard = QtWidgets.QRadioButton("Standard mesh")
            self.standard.setObjectName("SWSimMeshStandard")
            pl.addRow(self.curved)
            pl.addRow(self.standard)
            self.unit = QtWidgets.QComboBox()
            self.unit.setObjectName("SWSimMeshUnit")
            self.unit.addItems(["mm", "in"])
            pl.addRow("Units:", self.unit)

            def spin(name, value):
                s = QtWidgets.QDoubleSpinBox()
                s.setObjectName(name)
                s.setRange(0.0, 1e6)
                s.setDecimals(3)
                s.setValue(value)
                return s
            self.size = spin("SWSimMeshSize", self.base)
            self.tol = spin("SWSimMeshTolerance", round(self.base * 0.05, 4))
            self.tol.setDecimals(4)
            self.transition = QtWidgets.QCheckBox("Automatic transition")
            self.transition.setObjectName("SWSimMeshTransition")
            self.transition.setToolTip("Finer elements where the part curves (holes, fillets), under the global size")
            self.max_size = spin("SWSimMeshMax", self.base)
            self.min_size = spin("SWSimMeshMin", round(self.base / 5.0, 3))
            self.circle = QtWidgets.QSpinBox()
            self.circle.setObjectName("SWSimMeshCircle")
            self.circle.setRange(1, 100)
            self.circle.setValue(8)
            self.cur_rows = ((QtWidgets.QLabel("Max element size:"), self.max_size),
                             (QtWidgets.QLabel("Min element size:"), self.min_size),
                             (QtWidgets.QLabel("Min number of elements in a circle:"), self.circle))
            self.std_rows = ((QtWidgets.QLabel("Global size:"), self.size), (QtWidgets.QLabel("Tolerance:"), self.tol))
            for lab, w in self.cur_rows + self.std_rows:
                pl.addRow(lab, w)
            pl.addRow(self.transition)
            adv = sx._box("Advanced")
            al = QtWidgets.QFormLayout(adv)
            self.jac = QtWidgets.QComboBox()
            self.jac.setObjectName("SWSimMeshJacobian")
            self.jac.addItems(list(simmeshq.POINTS))
            self.jac.setCurrentText(simmeshq.DEFAULT_POINTS)
            self.jac_label = QtWidgets.QLabel("Jacobian Points:")
            al.addRow(self.jac_label, self.jac)
            self.adv = adv
            opt = sx._box("Options")
            ol = QtWidgets.QVBoxLayout(opt)
            self.save_only = QtWidgets.QCheckBox("Save settings without meshing")
            self.save_only.setObjectName("SWSimMeshSaveOnly")
            self.run = QtWidgets.QCheckBox("Run (solve) the analysis")
            self.run.setObjectName("SWSimMeshRun")
            ol.addWidget(self.save_only)
            ol.addWidget(self.run)
            # Mesh Quality tab: Specify High / Draft per body, with the four move buttons
            spec = sx._box("Specify")
            sl = QtWidgets.QVBoxLayout(spec)
            sl.addWidget(QtWidgets.QLabel("High:"))
            self.high = QtWidgets.QListWidget()
            self.high.setObjectName("SWSimMeshHigh")
            self.high.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            sl.addWidget(self.high)
            brow = QtWidgets.QHBoxLayout()
            self.moves = {}
            for key, text, tip in (("down", "↓", "Move the selected to Draft"), ("all_down", "⇊", "Move all to Draft"),
                                   ("up", "↑", "Move the selected to High"), ("all_up", "⇈", "Move all to High")):
                b = QtWidgets.QToolButton()
                b.setObjectName("SWSimMeshMove_" + key)
                b.setText(text)
                b.setToolTip(tip)
                b.clicked.connect(lambda *_, key=key: self._move(key))
                brow.addWidget(b)
                self.moves[key] = b
            brow.addStretch(1)
            sl.addLayout(brow)
            sl.addWidget(QtWidgets.QLabel("Draft:"))
            self.draft_list = QtWidgets.QListWidget()
            self.draft_list.setObjectName("SWSimMeshDraftList")
            self.draft_list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
            sl.addWidget(self.draft_list)
            self.spec = spec
            self.def_boxes = [dens, par, adv, opt]
            self.form = [tabs, dens, par, adv, opt, spec]
            draft = bool(k.get("draft")) if k else (self.mesh is not None and self.mesh.ElementOrder == "1st")
            for b in _bodies(self.a):
                (self.draft_list if draft else self.high).addItem(b)
            self.curved.setChecked(True)
            if self.mesh is not None and not k and not self.mesh.MeshSizeFromCurvature:
                self.standard.setChecked(True)
            if k:
                self.use_params.setChecked(True)
                (self.curved if k.get("kind") == "Curvature-based" else self.standard).setChecked(True)
                self.unit.setCurrentText(k.get("unit") or "mm")
                for w, key in ((self.size, "size"), (self.max_size, "max_size"), (self.min_size, "min_size")):
                    if k.get(key) is not None:
                        w.setValue(k[key])
                self.circle.setValue(k.get("circle") or 8)
                if k.get("tolerance"):
                    self.tol.setValue(k["tolerance"])
                self.jac.setCurrentText(k.get("jacobian") or simmeshq.DEFAULT_POINTS)
                self.warn.setChecked(k.get("warn", True))
                self.transition.setChecked(bool(k.get("transition")))
            self.trials = bool(k.get("trials"))
            self._shown_unit = self.unit.currentText()
            self.unit.currentTextChanged.connect(self._unit_changed)
            if not k and inch_part(doc):
                self.unit.setCurrentText("in")          # an inch part: sizes in inches (converted, not retyped)
            self.slider.valueChanged.connect(self._density)
            self.reset.clicked.connect(lambda: self.slider.setValue(5) if self.slider.value() != 5 else self._density(5))
            self.standard.toggled.connect(lambda *_: self._kind())
            self.save_only.toggled.connect(lambda on: self.run.setVisible(not on))   # hidden, not greyed
            self.run.setVisible(not self.save_only.isChecked())
            self.tabs.currentChanged.connect(self._tab)
            for lw in (self.high, self.draft_list):
                lw.model().rowsInserted.connect(lambda *_: self._quality())
                lw.model().rowsRemoved.connect(lambda *_: self._quality())
            self._kind()
            self._quality()
            from . import safe_later as _sl; _sl.later(0, lambda: self._open() and self._tab(self.tabs.currentIndex()), self, "tabs")

        def _unit_changed(self, unit):
            ""
            k = LENGTH_UNITS.get(self._shown_unit, 1.0) / LENGTH_UNITS.get(unit, 1.0)
            self._shown_unit = unit
            for w in (self.size, self.tol, self.max_size, self.min_size):
                w.setDecimals(4 if unit == "in" else 3 if w is not self.tol else 4)
                w.setValue(w.value() * k)

        def _density(self, d):
            k = 1.0 / LENGTH_UNITS.get(self.unit.currentText(), 1.0)
            size = size_at(self.obj.Shape, d) * k if self.obj is not None else self.size.value()
            self.size.setValue(size)
            self.tol.setValue(round(size * 0.05, 4))
            self.max_size.setValue(size)
            self.min_size.setValue(size / 5.0)

        def _kind(self):
            std = self.standard.isChecked()
            for lab, w in self.std_rows:
                lab.setVisible(std)
                w.setVisible(std)
            self.transition.setVisible(std)
            for lab, w in self.cur_rows:
                lab.setVisible(not std)
                w.setVisible(not std)

        def _draft(self):
            return self.high.count() == 0 and self.draft_list.count() > 0

        def _quality(self):
            # Jacobian points concern curved (high quality) elements only: hidden while every body is Draft
            on = not self._draft()
            self.jac.setVisible(on)
            self.jac_label.setVisible(on)
            if self._open() and self.tabs.currentIndex() == 0:
                _box_visible(self.adv, on)

        def _move(self, key):
            src, dst = (self.high, self.draft_list) if key in ("down", "all_down") else (self.draft_list, self.high)
            items = [src.item(i) for i in range(src.count())] if key.startswith("all") else src.selectedItems()
            for it in items:
                dst.addItem(src.takeItem(src.row(it)).text())

        def _tab(self, i):
            q = i == 1
            for b in self.def_boxes:
                _box_visible(b, not q)
            _box_visible(self.spec, q)
            if not q:
                self._quality()

        def _start(self):
            return

        def accept(self):
            if self.a is None or self.mesh is None:
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, "Make a study first (Simulation > New Study).")
                return False
            if self.high.count() and self.draft_list.count():
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, "FreeCAD meshes every body at one quality: "
                                              "move them all to High or all to Draft (Mesh Quality tab).")
                return False
            own = self.use_params.isChecked()
            kind = ("Standard" if self.standard.isChecked() else "Curvature-based") if own else "Standard"
            if not own:
                self.unit.setCurrentText("mm")
                self._density(self.slider.value())
            drop = False
            if not self.save_only.isChecked() and study_results(self.a) and self.mesh.FemMesh.NodeCount:

                ask = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "Simulation",
                                            "Remeshing will delete the results for study: %s." % self.a.Label,
                                            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel, Gui.getMainWindow())
                ask.setObjectName("SWSimRemesh")
                ask.setDefaultButton(QtWidgets.QMessageBox.Ok)
                if ask.exec_() != QtWidgets.QMessageBox.Ok:
                    return False
                drop = True
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                if drop:
                    drop_results(self.a)
                set_mesh(self.a, kind, self.size.value(), self.tol.value(), self.max_size.value(), self.min_size.value(),
                         self.circle.value(), self._draft(), self.unit.currentText(),
                         not self.save_only.isChecked(), self.run.isChecked() and not self.save_only.isChecked(),
                         self.jac.currentText(), self.trials, self.warn.isChecked(),
                         own and kind == "Standard" and self.transition.isChecked())
            except (SetupError, RuntimeError) as e:
                QtWidgets.QApplication.restoreOverrideCursor()
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, str(e))
                return False
            QtWidgets.QApplication.restoreOverrideCursor()
            Gui.Control.closeDialog()
            return True

    OPEN = []

    def show(pm):
        del OPEN[:]
        OPEN.append(pm)
        Gui.Control.showDialog(pm)
        return pm

    def edit_definition(o):
        """Edit Definition: the PM that made o, filled in (FreeCAD's own panel for anything else)."""
        from . import simmeshq
        if simmeshq.CONTROL in o.PropertiesList:
            return simmeshq.edit_definition(o)
        k = kept(o)
        doc = o.Document
        kind = k.get("kind")
        loads = {"Torque": lambda: ForcePM(doc, edit=o, torque=True), "Bearing Load": lambda: BearingPM(doc, edit=o),
                 "Pressure": lambda: PressurePM(doc, edit=o),
                 "Distributed Mass": lambda: DistributedMassPM(doc, edit=o),
                 "Centrifugal": lambda: CentrifugalPM(doc, edit=o), "Remote Load": lambda: RemoteLoadPM(doc, edit=o)}
        if kind in loads:
            return show(loads[kind]())
        if kind in STANDARD + ADVANCED:
            return show(FixturesPM(doc, edit=o))
        if o.TypeId == "Fem::ConstraintForce" and k:
            return show(ForcePM(doc, edit=o))
        if o.TypeId == "Fem::ConstraintPressure" and k:
            return show(PressurePM(doc, edit=o))
        if k and "GravityDirection" in o.PropertiesList:
            return show(GravityPM(doc, edit=o))
        return None

    class _Cmd:
        def __init__(self, text, tip, make, pixmap):
            self.text, self.tip, self.make, self.pixmap = text, tip, make, pixmap

        def GetResources(self):
            pix = self.pixmap
            if pix == "FEM_ConstraintSelfWeight":       # FEM's icons may not be loaded yet (an assembly's Motion Study)
                try:
                    from . import simicons
                    pix = simicons.svg("SIM_Gravity") or pix
                except Exception as _fw_err:
                    _fw_log("simpms.py:gravityicon", _fw_err)
            return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": pix}

        def IsActive(self):
            doc = App.ActiveDocument
            return doc is not None and not Gui.Control.activeDialog() and active_study(doc) is not None

        def Activated(self):
            show(self.make(App.ActiveDocument))

    COMMANDS = {
        "SWStyle_SimFixed": _Cmd("Fixed Geometry", "Faces that do not move or turn.",
                                 lambda d: FixturesPM(d, "Fixed Geometry"), "FEM_ConstraintFixed"),
        "SWStyle_SimRoller": _Cmd("Roller/Slider", "Flat faces that slide in their own plane.",
                                  lambda d: FixturesPM(d, "Roller/Slider"), "FEM_ConstraintDisplacement"),
        "SWStyle_SimHinge": _Cmd("Fixed Hinge", "Round faces that turn about their own axis only.",
                                 lambda d: FixturesPM(d, "Fixed Hinge"), "FEM_ConstraintPlaneRotation"),
        "SWStyle_SimForce": _Cmd("Force", "A force on faces: normal to them or along a direction.",
                                 lambda d: ForcePM(d), "FEM_ConstraintForce"),
        "SWStyle_SimPressure": _Cmd("Pressure", "A pressure on faces.", lambda d: PressurePM(d), "FEM_ConstraintPressure"),
        "SWStyle_SimMesh": _Cmd("Create Mesh", "The Mesh PM: density, Standard or Curvature-based, then mesh (and run).",
                                lambda d: MeshPM(d), "FEM_MeshGmshFromShape"),
        "SWStyle_SimGravity": _Cmd("Gravity", "Gravity along a plane's normal or an edge.", lambda d: GravityPM(d),
                                   "FEM_ConstraintSelfWeight"),
        "SWStyle_SimTorque": _Cmd("Torque", "A torque on faces about an axis.", lambda d: ForcePM(d, torque=True),
                                  "FEM_ConstraintForce"),
        "SWStyle_SimCentrifugal": _Cmd("Centrifugal Force", "The part spun about an axis at an angular velocity.",
                                       lambda d: CentrifugalPM(d), "FEM_ConstraintCentrif"),
        "SWStyle_SimBearing": _Cmd("Bearing Load", "A bearing's push on round faces, sinusoidal or parabolic.",
                                   lambda d: BearingPM(d), "FEM_ConstraintBearing"),
        "SWStyle_SimRemoteLoad": _Cmd("Remote Load/Mass", "Forces and moments at a point, carried to faces rigidly.",
                                      lambda d: RemoteLoadPM(d), "FEM_ConstraintRigidBody"),
        "SWStyle_SimDistributedMass": _Cmd("Distributed Mass", "A mass spread over faces by area.",
                                           lambda d: DistributedMassPM(d), "FEM_ConstraintForce"),
    }

# key, label, natives (FreeCAD's own panel after ours), tip, caption: these replace addintabs' keys (installed after)
KEYS = (
    ("SIM_Fixed", "Fixed Geometry", ("SWStyle_SimFixed", "FEM_ConstraintFixed"), "Faces that do not move or turn.", None),
    ("SIM_Roller", "Roller/Slider", ("SWStyle_SimRoller", "FEM_ConstraintDisplacement"),
     "Flat faces that slide in their own plane.", None),
    ("SIM_Hinge", "Fixed Hinge", ("SWStyle_SimHinge", "FEM_ConstraintPlaneRotation"),
     "Round faces that turn about their own axis only.", None),
    ("SIM_Force", "Force", ("SWStyle_SimForce", "FEM_ConstraintForce"), "A force on faces.", None),
    ("SIM_Pressure", "Pressure", ("SWStyle_SimPressure", "FEM_ConstraintPressure"), "A pressure on faces.", None),
    ("SIM_Mesh", "Create Mesh", ("SWStyle_SimMesh", "FEM_MeshGmshFromShape", "FEM_MeshNetgenFromShape"),
     "The Mesh PM: density, Standard or Curvature-based mesh, then mesh (and run).", "Create\nMesh"),
    ("SIM_Gravity", "Gravity", ("SWStyle_SimGravity", "FEM_ConstraintSelfWeight"), "Gravity on the part.", None),
    ("SIM_Torque", "Torque", ("SWStyle_SimTorque",), "A torque on faces about an axis.", None),
    ("SIM_Centrifugal", "Centrifugal Force", ("SWStyle_SimCentrifugal", "FEM_ConstraintCentrif"),
     "Spins the part about an axis.", None),
    ("SIM_Bearing", "Bearing Load", ("SWStyle_SimBearing", "FEM_ConstraintBearing"),
     "A bearing load on round faces.", None),
    ("SIM_RemoteLoad", "Remote Load/Mass", ("SWStyle_SimRemoteLoad",),
     "Forces and moments at a point, carried to faces rigidly.", None),
    ("SIM_DistributedMass", "Distributed Mass", ("SWStyle_SimDistributedMass",), "A mass spread over faces.", None),
    ("SIM_MeshControl", "Mesh Control", ("SWStyle_SimMeshControl", "FEM_MeshRegion"),
     "A finer mesh on chosen faces, edges or vertices, growing by a ratio to the global size.", None),
    ("SIM_MeshQuality", "Mesh Quality Plot", ("SWStyle_SimMeshQuality",),
     "The mesh colored by element aspect ratio or Jacobian.", None),
)


def install():
    """The commands and their catalog keys (called from studytools.install, before addintabs' keys)."""
    if Gui is None:
        return
    from . import catalog, simmeshq
    simmeshq.install()                  # Mesh Control and Mesh Quality Plot commands, the Gmsh tolerance / field writer
    have = set(Gui.listCommands())
    for name, cmd in COMMANDS.items():
        if name not in have:
            Gui.addCommand(name, cmd)
    for key, label, natives, tip, caption in KEYS:
        if key not in catalog.BY_KEY:
            catalog.BY_KEY[key] = catalog.c(key, label, natives, None, tip, caption=caption)
