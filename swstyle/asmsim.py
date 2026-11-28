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
    from PySide import QtCore, QtWidgets
except ImportError:
    Gui = None

GEOM = "FwSimGeometry"          # on the hidden geometry: the assembly's name
OWNERS = "FwSimOwners"          # on the geometry: JSON, the component name of each solid (Solid1...)
ASM = "FwAssembly"              # on the study: the assembly's name
GLOBAL = "FwGlobalInteraction"  # on the study: Bonded / Contact / Free
GLOBAL_GAP = "FwGlobalGap"      # on the study: the global Bonded interaction's gap range for bonding, mm
AUTO = "FwAutoInteraction"      # on the Tie / Contact objects made from the interactions (remade on each run)
CONNECTOR = "FwConnector"       # on a connector: Bolt / Pin / Spring / Bearing
FORCES = "FwConnectorForces"    # on a bolt or spring after a run: its axial and shear force, bending moment and torque
SPRINGS = {}                    # study name: (.frd path, [(connector name, axis, pre-load, pairs)]) of its last input
INTERACTION = "FwInteraction"   # on a component interaction: its type
TYPES = ("Bonded", "Contact", "Free")
CONNECTORS = ("Bolt", "Pin", "Spring", "Bearing", "Rigid")
SHARED = ("Spring", "Pin", "Bolt")
CONNECTIONS = ("Rigid", "Distributed")   # a bolt's Connection Type: its ends rigid, or spread over the faces (they deform)
PRELOADS = ("Axial", "Torque")   # a bolt's pre-load: the axial force, or the tightening torque with a friction factor
STIFFNESS = ("Rigid", "Flexible")  # a bearing
TOUCH = 1e-4                    # mm
STEEL_E = 210000.0              # MPa: a bolt's shank
# the Bolt connector's Material: Library choices (elastic modulus MPa, Poisson's ratio), else Custom values
BOLT_MATERIALS = {"Alloy Steel": (210000.0, 0.28), "Plain Carbon Steel": (210000.0, 0.28),
                  "Stainless Steel": (200000.0, 0.28), "Titanium Alloy": (105000.0, 0.31),
                  "Aluminium Alloy": (69000.0, 0.33), "Brass": (100000.0, 0.33)}


# --------------------------------------------------------------------------- the study's geometry
def is_assembly_study(a):
    return a is not None and ASM in a.PropertiesList and bool(getattr(a, ASM, ""))


def assembly(a):
    return a.Document.getObject(getattr(a, ASM, "")) if is_assembly_study(a) else None


def geometry(a):
    """What the study meshes: an assembly's Simulation Geometry, a part's solid."""
    found = None
    for o in (a.Group if a is not None else []):
        if o.isDerivedFrom("Fem::FemMeshObject"):
            s = getattr(o, "Shape", None)
            if s is not None and GEOM in s.PropertiesList:
                return s
            found = found or s
    return found


def owners(geom):
    try:
        return json.loads(getattr(geom, OWNERS, "") or "[]")
    except ValueError:
        return []


def _components(asm):
    from . import asmcore as ac
    return list(ac.components(asm))


def component_solids(asm):
    """[(component, [solids where they stand in the assembly])], components with no solid left out."""
    import Part
    out = []
    for c in _components(asm):
        try:
            shp = Part.getShape(asm, c.Name + ".", needSubElement=False, transform=True)
        except Exception as _fw_err:
            _fw_log("asmsim.py:shape", _fw_err)
            continue
        solids = list(shp.Solids)
        if solids:
            out.append((c, solids))
    return out


def build_geometry(asm, geom=None):
    """The hidden Simulation Geometry: one solid per component body, in the components' order."""
    import Part
    doc = asm.Document
    found = component_solids(asm)
    solids, names = [], []
    for c, ss in found:
        for s in ss:
            solids.append(s)
            names.append(c.Name)
    if not solids:
        raise ValueError("The assembly has no solid component to study.")
    if geom is None:
        geom = doc.addObject("Part::Feature", "SimulationGeometry")
        geom.Label = "Simulation Geometry"
        geom.addProperty("App::PropertyString", GEOM, "FreeCAD", "The assembly this geometry is made from")
        geom.addProperty("App::PropertyString", OWNERS, "FreeCAD", "The component of each solid")
        for p in (GEOM, OWNERS):
            geom.setPropertyStatus(p, "Hidden")
        setattr(geom, GEOM, asm.Name)
    shape = Part.makeCompound(solids)
    old = geom.Shape
    if old.isNull() or len(old.Solids) != len(solids) or any(
            (x.CenterOfMass - y.CenterOfMass).Length > 1e-6 or abs(x.Volume - y.Volume) > 1e-6 * max(1.0, y.Volume)
            for x, y in zip(old.Solids, solids)):
        geom.Shape = shape
    setattr(geom, OWNERS, json.dumps(names))
    try:
        geom.ViewObject.Visibility = False
        geom.ViewObject.ShowInTree = False
    except Exception as _fw_err:
        _fw_log("asmsim.py:hide", _fw_err)
    return geom


def new_study(asm, kind="static", label=None):
    ""

    from . import addintabs
    doc = asm.Document
    geom = build_geometry(asm)
    a = addintabs.new_study(doc, geom, kind, label)
    a.addProperty("App::PropertyString", ASM, "FreeCAD", "The assembly this study is of")
    a.addProperty("App::PropertyString", GLOBAL, "FreeCAD", "Global Interaction: Bonded, Contact or Free")
    for p in (ASM, GLOBAL):
        a.setPropertyStatus(p, "Hidden")
    setattr(a, ASM, asm.Name)
    setattr(a, GLOBAL, "Bonded")
    _apart_mesh(a)
    doc.recompute()
    return a


def _apart_mesh(a):
    from . import simpms
    m = simpms.gmsh_of(a)
    if m is not None and getattr(m, "CoherenceMesh", False):
        m.CoherenceMesh = False


def component_of_solid(a, index):
    names = owners(geometry(a))
    return a.Document.getObject(names[index]) if 0 <= index < len(names) else None


def solid_index(geom, sub):
    """The index of the solid of geom that holds element sub (FaceN / EdgeN)."""
    el = geom.Shape.getElement(sub)
    for i, s in enumerate(geom.Shape.Solids):
        for e in (s.Faces if sub.startswith("Face") else s.Edges if sub.startswith("Edge") else s.Vertexes):
            if e.isSame(el):
                return i
    return None


def map_pick(a, doc_name, name, sub):
    """A pick on a component (doc, top object, subname) as (geometry name, its matching element), else None."""
    geom = geometry(a)
    if geom is None:
        return None
    if name == geom.Name:
        return (name, sub.split(".")[-1])
    last = (sub or "").split(".")[-1]
    if not last.startswith(("Face", "Edge", "Vertex")):
        return None
    try:
        top = App.getDocument(doc_name).getObject(name)
        el = top.getSubObject(sub)
    except Exception as _fw_err:
        _fw_log("asmsim.py:pick", _fw_err)
        return None
    if el is None or el.isNull():
        return None
    return (geom.Name, match(geom.Shape, el, last[:4]))


def match(shape, el, kind):
    """The element of shape lying where el lies: its name (FaceN, EdgeN, VertexN), else None."""
    tol = 1e-5 * max(1.0, shape.BoundBox.DiagonalLength)
    if kind == "Face":
        for i, f in enumerate(shape.Faces, 1):
            if abs(f.Area - el.Area) <= 1e-6 * max(1.0, el.Area) and (f.CenterOfMass - el.CenterOfMass).Length < tol:
                return "Face%d" % i
    elif kind == "Edge":
        for i, e in enumerate(shape.Edges, 1):
            if abs(e.Length - el.Length) <= 1e-6 * max(1.0, el.Length) and (e.CenterOfMass - el.CenterOfMass).Length < tol:
                return "Edge%d" % i
    else:
        for i, v in enumerate(shape.Vertexes, 1):
            if (v.Point - el.Point).Length < tol:
                return "Vertex%d" % i
    return None


# --------------------------------------------------------------------------- interactions
def global_type(a):
    return getattr(a, GLOBAL, "Bonded") or "Bonded"


def set_global(a, kind, gap=None):
    """The Global Interaction; gap: Bonded's gap range for bonding (mm): faces of two components that far apart
    or closer, face to face, are bonded too."""
    if kind not in TYPES:
        raise ValueError("Unknown interaction type %r." % kind)
    setattr(a, GLOBAL, kind)
    if gap is not None or GLOBAL_GAP in a.PropertiesList:
        if GLOBAL_GAP not in a.PropertiesList:
            a.addProperty("App::PropertyFloat", GLOBAL_GAP, "FreeCAD", "Global Bonded: gap range for bonding (mm)")
            a.setPropertyStatus(GLOBAL_GAP, "Hidden")
        setattr(a, GLOBAL_GAP, float(gap or 0.0))
    if Gui is not None:                  # the study tree's row reads "Global Interaction (-Contact-)" at once
        try:
            from . import simtree
            simtree.refresh()
        except Exception as _fw_err:
            App.Console.PrintLog("FreeCAD Global Interaction refresh: %s\n" % _fw_err)
    return kind


def global_gap(a):
    return float(getattr(a, GLOBAL_GAP, 0.0) or 0.0)


def interactions(a):
    """The study's Component Interactions (not the global one), in the order made."""
    return [o for o in a.Group if INTERACTION in o.PropertiesList]


def _feature(doc, a, name, label):
    o = doc.addObject("App::FeaturePython", name)
    o.Label = label
    o.addProperty("App::PropertyBool", "Suppressed", "Base", "Left out of the run")
    a.addObject(o)
    return o


def add_component_interaction(a, comps, kind="Contact", friction=None, edit=None, gap=None):
    """A Component Interaction: every touching face pair of the named components takes kind (Bonded, Contact, Free).
    gap: Bonded's gap range for bonding (mm)."""
    from . import simpms
    if kind not in TYPES:
        raise simpms.SetupError("Unknown interaction type %r." % kind)
    comps = [c if isinstance(c, str) else c.Name for c in comps]
    if not comps:
        raise simpms.SetupError("Pick the components: click them in the graphics area or the FeatureManager.")
    doc = a.Document
    o = edit
    if o is None:
        o = _feature(doc, a, "ComponentInteraction", simpms._label(a, "Component Interaction"))
        o.addProperty("App::PropertyString", INTERACTION, "FreeCAD", "Bonded, Contact or Free")
        o.addProperty("App::PropertyStringList", "Components", "FreeCAD", "The components it applies to")
        o.addProperty("App::PropertyFloat", "Friction", "FreeCAD", "Friction coefficient (Contact), 0 for none")
    setattr(o, INTERACTION, kind)
    o.Components = comps
    o.Friction = float(friction or 0.0)
    if "Gap" not in o.PropertiesList:
        o.addProperty("App::PropertyFloat", "Gap", "FreeCAD", "Bonded: gap range for bonding (mm)")
    o.Gap = float(gap or 0.0) if kind == "Bonded" else 0.0
    doc.recompute()
    return o


def _type_for(a, ca, cb):
    """(kind, friction, bonding gap mm) between components ca and cb."""
    for o in interactions(a):
        if getattr(o, "Suppressed", False):
            continue
        if ca in o.Components or cb in o.Components:
            return getattr(o, INTERACTION), o.Friction, float(getattr(o, "Gap", 0.0) or 0.0)
    return global_type(a), 0.0, global_gap(a) if global_type(a) == "Bonded" else 0.0


def _reach(a):
    """The widest bonding gap of the study's interactions (faces further apart are never paired)."""
    gaps = [float(getattr(o, "Gap", 0.0) or 0.0) for o in interactions(a) if not getattr(o, "Suppressed", False)
            and getattr(o, INTERACTION) == "Bonded"]
    if global_type(a) == "Bonded":
        gaps.append(global_gap(a))
    return max([TOUCH] + gaps)


def touching_pairs(geom, reach=TOUCH, gaps=None):
    """(solid i, face name, solid j, face name) for faces of two solids lying on each other (an area in common).
    With reach > TOUCH, faces up to reach apart face to face are listed too, and gaps (if a dict) gets their
    distance by pair."""
    shape = geom.Shape
    solids = shape.Solids
    index = {}
    for k, f in enumerate(shape.Faces, 1):
        index.setdefault(k, f)
    of_solid = []
    for i, s in enumerate(solids):
        names = []
        for f in s.Faces:
            for k, g in index.items():
                if g.isSame(f):
                    names.append("Face%d" % k)
                    break
        of_solid.append(names)
    out = []
    for i in range(len(solids)):
        for j in range(i + 1, len(solids)):
            bi, bj = solids[i].BoundBox, solids[j].BoundBox
            bi.enlarge(reach)
            if not bi.intersect(bj):
                continue
            for ni in of_solid[i]:
                fi = shape.getElement(ni)
                bfi = fi.BoundBox
                bfi.enlarge(reach)
                for nj in of_solid[j]:
                    fj = shape.getElement(nj)
                    if not bfi.intersect(fj.BoundBox):
                        continue
                    dist = fi.distToShape(fj)[0]
                    if dist > reach:
                        continue
                    if dist <= TOUCH:
                        try:
                            common = fi.common(fj)
                            area = common.Area
                        except Exception:
                            area = 0.0
                    else:
                        from . import simconnect
                        area = simconnect._shared_area(fi, fj, reach)
                    if area > 1e-6 * min(fi.Area, fj.Area):
                        out.append((i, ni, j, nj))
                        if isinstance(gaps, dict):
                            gaps[(ni, nj)] = dist
    return out


def _local_faces(a):
    """Faces already in a Contact Set (Local Interaction): they keep the set's type."""
    from . import simconnect
    out = set()
    for o in a.Group:
        if getattr(o, simconnect.SET, None) is not None and AUTO not in o.PropertiesList and not getattr(o, "Suppressed", False):
            for r in o.References:
                for s in r[1]:
                    out.add(s)
    return out


def prepare(a):
    """Before a run: the geometry where the components stand now, then the interactions' Tie / Contact objects."""
    import ObjectsFem
    from . import simconnect, simxpress as sx
    asm = assembly(a)
    doc = a.Document
    geom = build_geometry(asm, geometry(a))
    for o in [x for x in a.Group if AUTO in x.PropertiesList]:
        a.removeObject(o)
        doc.removeObject(o.Name)
    names = owners(geom)
    local = _local_faces(a)
    made = []
    e = simconnect._young_mpa(a)
    size = geom.Shape.BoundBox.DiagonalLength
    with sx.fem_safe():
        dists = {}
        for i, fi, j, fj in touching_pairs(geom, _reach(a), dists):
            if fi in local or fj in local:
                continue
            kind, friction, gap = _type_for(a, names[i], names[j])
            if kind == "Free":
                continue
            if dists.get((fi, fj), 0.0) > TOUCH and not (kind == "Bonded" and dists[(fi, fj)] <= gap):
                continue                            # apart: only a Bonded interaction's gap range joins them
            if kind == "Bonded":
                o = ObjectsFem.makeConstraintTie(doc, "Bonded")
                o.Tolerance = "%r mm" % max(0.1, 0.01 * size, 1.01 * gap)
            else:
                o = ObjectsFem.makeConstraintContact(doc, "Contact")
                slope = 10.0 * e
                o.Slope = "%r GPa/m" % slope
                if friction:
                    o.Friction = True
                    o.FrictionCoefficient = float(friction)
                    o.StickSlope = "%r GPa/m" % (slope / 10.0)
            o.References = [(geom, (fj,)), (geom, (fi,))]
            a.addObject(o)
            for p, v in ((AUTO, kind), (simconnect.SET, "Interaction")):
                o.addProperty("App::PropertyString", p, "FreeCAD", "Made from the study's interactions")
                o.setPropertyStatus(p, "Hidden")
                setattr(o, p, v)
            o.Label = "Interaction %s-%s (%s)" % (fi, fj, kind)
            try:
                o.ViewObject.ShowInTree = False
                o.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("asmsim.py:auto", _fw_err)
            made.append(o)
    _apart_mesh(a)
    doc.recompute()
    return made


# --------------------------------------------------------------------------- connectors
def connectors(a):
    return [o for o in a.Group if CONNECTOR in o.PropertiesList]


def add_connector(a, kind, faces, edit=None, **values):
    """A Bolt, Pin, Spring or Bearing between two faces of the geometry (FaceN names).
    Bolt: diameter (mm); preload (Axial: N, Torque: N.mm), preload_type (Axial / Torque), friction_factor (K, Torque);
    connection (Rigid / Distributed).
    Pin: ring (bool), key (bool). Spring: axial, tangential (N/mm, total).
    Bearing (shaft face, housing face, both round on one axis): stiffness (Rigid / Flexible), lateral, axial (N/mm,
    Flexible), align (self-aligning: the shaft may tilt), stabilize (a soft spring against free shaft rotation)."""
    from . import simpms
    if kind not in CONNECTORS:
        raise simpms.SetupError("Unknown connector %r." % kind)
    geom = geometry(a)
    faces = list(faces)
    if geom is None:
        raise simpms.SetupError("The study has no geometry.")
    if len(faces) != 2:
        raise simpms.SetupError("Pick two faces: one on each part the %s joins." % kind.lower())
    si = [solid_index(geom, f) for f in faces]
    if si[0] is None or si[1] is None or si[0] == si[1]:
        raise simpms.SetupError("The two faces must be on two different components.")
    if kind in ("Pin", "Bearing"):
        cyl = [geom.Shape.getElement(f).Surface for f in faces]
        if not all(c.TypeId == "Part::GeomCylinder" for c in cyl):
            raise simpms.SetupError("A %s joins two round (cylindrical) faces." % kind.lower())
        d = cyl[1].Center - cyl[0].Center
        axis = cyl[0].Axis
        if abs(abs(axis.dot(cyl[1].Axis)) - 1) > 1e-6 or (d.Length > 1e-6 and d.cross(axis).Length > 1e-4 * max(1.0, d.Length)):
            raise simpms.SetupError("The two round faces must share one axis.")
    if kind == "Bolt":
        dia = float(values.get("diameter") or 0.0)
        if dia <= 0:
            f = geom.Shape.getElement(faces[0])
            dia = 2.0 * f.Surface.Radius if f.Surface.TypeId == "Part::GeomCylinder" else 0.0
        if dia <= 0:
            raise simpms.SetupError("Give the bolt diameter.")
        values["diameter"] = dia
        ptype = values.get("preload_type") or "Axial"
        if ptype not in PRELOADS:
            raise simpms.SetupError("Unknown pre-load %r." % ptype)
        values["preload_type"] = ptype
        conn = values.get("connection") or "Rigid"
        if conn not in CONNECTIONS:
            raise simpms.SetupError("Unknown connection type %r." % conn)
        values["connection"] = conn
        values["preload"] = float(values.get("preload") or 0.0)
        if values["preload"] < 0:
            raise simpms.SetupError("The pre-load cannot be negative.")
        if values.get("e_mpa") is not None:
            if float(values["e_mpa"]) <= 0 or not 0.0 <= float(values.get("poisson") or 0.0) < 0.5:
                raise simpms.SetupError("Give the bolt's elastic modulus (above 0) and Poisson's ratio (0 to 0.5).")
        elif (values.get("material") or "Alloy Steel") not in BOLT_MATERIALS:
            raise simpms.SetupError("Unknown bolt material %r." % values.get("material"))
        if ptype == "Torque":
            k = float(values.get("friction_factor") or 0.0)
            if k <= 0:
                raise simpms.SetupError("Give the friction factor (K) for a torque pre-load.")
            values["friction_factor"] = k
    if kind == "Bearing":
        st = values.get("stiffness") or "Rigid"
        if st not in STIFFNESS:
            raise simpms.SetupError("Unknown bearing stiffness %r." % st)
        values["stiffness"] = st
        if st == "Flexible" and float(values.get("lateral") or 0) <= 0:
            raise simpms.SetupError("Give the bearing a lateral stiffness.")
    if kind == "Spring" and float(values.get("axial") or 0) <= 0 and float(values.get("tangential") or 0) <= 0:
        raise simpms.SetupError("Give the spring an axial or a tangential stiffness.")
    doc = a.Document
    o = edit
    if o is None:
        o = _feature(doc, a, kind + "Connector", simpms._label(a, {"Bolt": "Bolt Connector", "Pin": "Pin Connector",
                                                                       "Spring": "Spring Connector", "Bearing": "Bearing Connector",
                                                                       "Rigid": "Rigid Connector"}[kind]))
        o.addProperty("App::PropertyString", CONNECTOR, "FreeCAD", "Bolt, Pin, Spring, Bearing or Rigid")
        o.addProperty("App::PropertyLinkSubList", "References", "FreeCAD", "The two faces joined")
        o.addProperty("App::PropertyString", "Values", "FreeCAD", "The PropertyManager's values (JSON)")
    setattr(o, CONNECTOR, kind)
    o.References = [(geom, (faces[0],)), (geom, (faces[1],))]
    o.Values = json.dumps(values, sort_keys=True)
    doc.recompute()
    return o


def values_of(o):
    try:
        return json.loads(getattr(o, "Values", "") or "{}")
    except ValueError:
        return {}


def _faces_of(o):
    return [(r[0], s) for r in o.References for s in r[1]]


def _centre(face):
    s = face.Surface
    if s.TypeId == "Part::GeomCylinder":
        # the middle of the round face on its axis
        c = face.CenterOfMass
        return s.Center + s.Axis * (c - s.Center).dot(s.Axis)
    return face.CenterOfMass


def _axis(face):
    s = face.Surface
    if s.TypeId == "Part::GeomCylinder":
        return App.Vector(s.Axis).normalize()
    try:
        u0, u1, v0, v1 = face.ParameterRange
        return App.Vector(face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)).normalize()
    except Exception:
        return App.Vector(0, 0, 1)


def _perp(axis):
    t = App.Vector(1, 0, 0) if abs(axis.x) < 0.9 else App.Vector(0, 1, 0)
    e1 = axis.cross(t).normalize()
    return e1, axis.cross(e1).normalize()


def _eq_lines(terms):
    """A CalculiX *EQUATION (the first term's dof is the dependent one)."""
    terms = [t for t in terms if abs(t[2]) > 1e-12]
    if not terms:
        return []
    lines = ["*EQUATION", "%d" % len(terms)]
    for i in range(0, len(terms), 4):
        lines.append(", ".join("%d, %d, %.12g" % t for t in terms[i:i + 4]))
    return lines


def _tie(n1, n2, q2, d, vec, used):
    """vec . (u1 - u2 - theta2 x d) = 0: node n1 follows node n2 along vec, n2's rotation carrying the lever d (n1 - n2).
    The dependent dof is n1's largest component of vec not yet used."""
    v = (vec.x, vec.y, vec.z)
    order = sorted(range(3), key=lambda k: -abs(v[k]))
    first = next((k for k in order if abs(v[k]) > 1e-9 and (n1, k + 1) not in used), None)
    if first is None:
        return []
    used.add((n1, first + 1))
    dv = d.cross(vec)
    terms = [(n1, first + 1, v[first])] + [(n1, k + 1, v[k]) for k in range(3) if k != first]
    terms += [(n2, k + 1, -v[k]) for k in range(3)] + [(q2, k + 1, -c) for k, c in enumerate((dv.x, dv.y, dv.z))]
    return _eq_lines(terms)


def _same_turn(q1, q2, vec, used):
    """vec . (theta1 - theta2) = 0."""
    return _tie(q1, q2, q2, App.Vector(), vec, used)


def _offset_node(node, at, n2, q2, c2):
    """A node at `at` carried rigidly by node n2 (rotation node q2) standing at c2: its *NODE and *EQUATION lines."""
    d = at - c2
    lines = ["*NODE", "%d, %.12g, %.12g, %.12g" % (node, at.x, at.y, at.z)]
    for k in range(3):
        rot = [0.0, 0.0, 0.0]
        # (theta x d)_k
        if k == 0:
            rot = [0.0, d.z, -d.y]
        elif k == 1:
            rot = [-d.z, 0.0, d.x]
        else:
            rot = [d.y, -d.x, 0.0]
        lines += _eq_lines([(node, k + 1, 1.0), (n2, k + 1, -1.0)] + [(q2, j + 1, -rot[j]) for j in range(3)])
    return lines


def _skew(e):
    """[e]x: the matrix with [e]x u = e x u."""
    return ((0.0, -e[2], e[1]), (e[2], 0.0, -e[0]), (-e[1], e[0], 0.0))


def _distributed(femmesh, face, ids):
    """A Distributed connector end: the face's nodes with their area weights w, the weighted centre cw, and for each
    node the 3 x 3 matrix A with theta = sum A u (the face's mean rotation, the least-squares rotation of the nodes
    about cw). The end follows the face on average, and the face keeps deforming (a rigid end would hold it flat)."""
    import numpy as np
    from . import simroutes
    share = simroutes._node_areas(femmesh, face, ids)
    total = sum(share.values())
    if len(share) < 3 or total <= 0:
        raise ValueError("too few mesh nodes on the face for a distributed connection")
    nodes = sorted(share)
    w = np.array([share[n] / total for n in nodes])
    pts = np.array([[femmesh.getNodeById(n).x, femmesh.getNodeById(n).y, femmesh.getNodeById(n).z] for n in nodes])
    cw = (w[:, None] * pts).sum(0)
    d = pts - cw
    J = (w[:, None, None] * ((d * d).sum(1)[:, None, None] * np.eye(3) - d[:, :, None] * d[:, None, :])).sum(0)
    if abs(np.linalg.det(J)) < 1e-12 * max(1.0, np.trace(J)) ** 3:
        J = J + 1e-9 * max(1.0, np.trace(J)) * np.eye(3)     # nodes on one line: no turn about it
    Ji = np.linalg.inv(J)
    A = [wi * Ji.dot(np.array(_skew(di))) for wi, di in zip(w, d)]
    return {"nodes": nodes, "w": w, "cw": App.Vector(*cw), "A": A}


def _distributed_lines(node, at, end, rotation=False):
    """*NODE and *EQUATION lines of a node following a Distributed end: its rotation (rotation=True: the three dofs
    are theta) or a point at `at` carried by it (u = sum (w I - [at - cw]x A) u_i)."""
    import numpy as np
    lines = ["*NODE", "%d, %.12g, %.12g, %.12g" % (node, at.x, at.y, at.z)]
    e = at - end["cw"]
    sk = np.array(_skew((e.x, e.y, e.z)))
    coef = [a if rotation else wi * np.eye(3) - sk.dot(a) for wi, a in zip(end["w"], end["A"])]
    for k in range(3):
        terms = [(node, k + 1, 1.0)]
        for n, c in zip(end["nodes"], coef):
            terms += [(n, b + 1, -float(c[k][b])) for b in range(3) if abs(c[k][b]) > 1e-12]
        lines += _eq_lines(terms)
    return lines


def _hold_k(face, e_mpa):
    """A connector end's holding stiffness: far stiffer than the parts there (1000 E L, L the face's size) and far
    from what upsets the solver. Returns (N/mm, N.mm/rad)."""
    size = max(face.Area ** 0.5, 1e-3)
    kt = 1000.0 * e_mpa * size
    return kt, kt * size * size


def _held(es, elem, node, n1, at, vecs, k, follow):
    """Stiff axial springs (SPRINGA) holding node n1 (standing at `at`) along each of vecs: for each a new node at
    at + vec, moved by follow(new node, its place) (its *NODE and *EQUATION lines), and a spring from n1 to it.
    A spring along vec resists only the relative motion along vec, whatever the axis. Windows CalculiX crashed on
    *EQUATION lines whose dependent dof is a rigid body's own reference or rotation node, so connector ends are held
    by stiff springs, and only new nodes are dependent. Returns (lines, elem, node)."""
    lines = []
    for i, vec in enumerate(vecs):
        if vec.Length < 1e-12:
            continue
        place = at + App.Vector(vec).normalize()
        lines += follow(node, place)
        name = "%s_%d" % (es, i + 1)
        lines += ["*ELEMENT, TYPE=SPRINGA, ELSET=%s" % name, "%d, %d, %d" % (elem, n1, node), "*SPRING, ELSET=%s" % name,
                  "", repr(float("%.12g" % k))]
        elem += 1
        node += 1
    return lines, elem, node


def _same_as(q2):
    """follow() for a rotation: the new node's three dofs equal q2's."""
    def f(n, place):
        lines = ["*NODE", "%d, %.12g, %.12g, %.12g" % (n, place.x, place.y, place.z)]
        for d in (1, 2, 3):
            lines += _eq_lines([(n, d, 1.0), (q2, d, -1.0)])
        return lines
    return f


def _is(o, type_id):
    """FreeCAD 1.1 makes some constraints (Tie) as Python features: their TypeId is Fem::ConstraintPython."""
    if o.TypeId == type_id:
        return True
    return getattr(getattr(o, "Proxy", None), "Type", None) == type_id


def side_nodes(femmesh, g, sub):
    """The mesh nodes on face sub of g that belong to its own solid. FreeCAD finds a face's nodes by where they are, so
    on two parts that touch it takes both parts' nodes, which would tie the parts together."""
    face = g.Shape.getElement(sub)
    ids = set(femmesh.getNodesByFace(face))
    if len(g.Shape.Solids) < 2:
        return sorted(ids)
    from . import simconnect
    solid = simconnect._owner(g.Shape, sub)
    if solid is None:
        return sorted(ids)
    keep = set()
    for vol in femmesh.getVolumesByFace(face):
        vol = vol[0] if isinstance(vol, tuple) else vol
        nodes = femmesh.getElementNodes(vol)
        c = App.Vector()
        for n in nodes:
            c = c + femmesh.getNodeById(n)
        if solid.isInside(c * (1.0 / len(nodes)), 1e-6, True):
            keep.update(n for n in nodes if n in ids)
    return sorted(keep or ids)


def bolt_material(v):
    """A bolt's (elastic modulus MPa, Poisson's ratio): its Custom values, its Library material, else alloy steel."""
    if v.get("e_mpa"):
        return float(v["e_mpa"]), float(v.get("poisson") or 0.28)
    return BOLT_MATERIALS.get(v.get("material") or "Alloy Steel", BOLT_MATERIALS["Alloy Steel"])


def bolt_axial(v):
    """A bolt's pre-load as an axial force (N): the force itself, or the torque T / (K D)."""
    p = float(v.get("preload") or 0.0)
    if p <= 0:
        return 0.0
    if (v.get("preload_type") or "Axial") == "Torque":
        return p / (float(v.get("friction_factor") or 0.2) * float(v["diameter"]))
    return p


def connector_input(a, femmesh, node0, elem0, skip_nodes=(), step=None, record=None):
    """The CalculiX model lines for the study's connectors (before *STEP). node0 / elem0: the first free ids.
    step: a list that takes the lines for inside the step (a bolt's pre-load)."""
    lines = []
    step = [] if step is None else step
    node, elem = node0, elem0
    e_mpa = STEEL_E
    for k, o in enumerate(connectors(a), 1):
        if getattr(o, "Suppressed", False):
            continue
        kind, v = getattr(o, CONNECTOR), values_of(o)
        (g1, f1), (g2, f2) = _faces_of(o)
        face1, face2 = g1.Shape.getElement(f1), g2.Shape.getElement(f2)
        if kind == "Rigid" or (kind == "Pin" and v.get("ring") and v.get("key")):
            # held in all six ways: both faces' nodes in one rigid body (the same as two rigid ends tied by six
            # equations, without equations on a rigid body's own nodes, which a Windows CalculiX crashed on)
            ids = []
            for j in (0, 1):
                ids += [n for n in side_nodes(femmesh, (g1, g2)[j], (f1, f2)[j]) if n not in skip_nodes and n not in ids]
            if not ids:
                raise ValueError("%s: no mesh nodes on its faces." % o.Label)
            c = _centre(face2)
            ref, rot = node, node + 1
            node += 2
            nset = "FW_CN%d_1" % k
            lines += ["*NODE", "%d, %.12g, %.12g, %.12g" % (ref, c.x, c.y, c.z), "%d, %.12g, %.12g, %.12g" % (rot, c.x, c.y, c.z)]
            lines.append("*NSET, NSET=%s" % nset)
            for i in range(0, len(ids), 12):
                lines.append(", ".join(str(n) for n in ids[i:i + 12]))
            lines.append("*RIGID BODY, NSET=%s, REF NODE=%d, ROT NODE=%d" % (nset, ref, rot))
            continue
        ends = []
        spread = kind == "Bolt" and v.get("connection") == "Distributed"
        dist = []
        for j, face in enumerate((face1, face2)):
            ids = [n for n in side_nodes(femmesh, (g1, g2)[j], (f1, f2)[j]) if n not in skip_nodes]
            if not ids:
                raise ValueError("%s: no mesh nodes on its face %d." % (o.Label, j + 1))
            c = _centre(face)
            ref, rot = node, node + 1
            node += 2
            if spread:

                # coupling, written as equations: CalculiX's own *COUPLING needs element faces)
                try:
                    end = _distributed(femmesh, face, ids)
                except ValueError as error:
                    raise ValueError("%s: %s %d." % (o.Label, error, j + 1))
                lines += _distributed_lines(ref, c, end) + _distributed_lines(rot, c, end, rotation=True)
                dist.append(end)
                ends.append((ref, rot, c))
                continue
            nset = "FW_CN%d_%d" % (k, j + 1)
            lines += ["*NODE", "%d, %.12g, %.12g, %.12g" % (ref, c.x, c.y, c.z), "%d, %.12g, %.12g, %.12g" % (rot, c.x, c.y, c.z)]
            lines.append("*NSET, NSET=%s" % nset)
            for i in range(0, len(ids), 12):
                lines.append(", ".join(str(n) for n in ids[i:i + 12]))
            lines.append("*RIGID BODY, NSET=%s, REF NODE=%d, ROT NODE=%d" % (nset, ref, rot))
            ends.append((ref, rot, c))
        (r1, q1, c1), (r2, q2, c2) = ends
        axis = _axis(face1)
        used = set()
        if kind == "Pin":
            # the two ends move together across the axis (and along it with a retaining ring), the lever between
            # them carried by the second end's rotation; they turn together except about the axis (unless keyed)
            e1, e2 = _perp(axis)
            kt, kr = _hold_k(face1, e_mpa)
            carry = lambda n, place: _offset_node(n, place, r2, q2, c2)
            more, elem, node = _held("FW_CE%d_pt" % k, elem, node, r1, c1, (e1, e2) + ((axis,) if v.get("ring") else ()), kt, carry)
            lines += more
            more, elem, node = _held("FW_CE%d_pr" % k, elem, node, q1, c1, (e1, e2) + ((axis,) if v.get("key") else ()), kr, _same_as(q2))
            lines += more
            continue
        if kind == "Bearing":
            # shaft (end 1) in housing (end 2): across the axis rigid (tied) or a lateral spring; along it tied (Rigid)
            # or the axial spring; the shaft turns freely about the axis (a soft spring with Stabilize), and tilts
            # only when self-aligning
            e1, e2 = _perp(axis)
            kt, kr = _hold_k(face1, e_mpa)
            if (v.get("stiffness") or "Rigid") == "Rigid":
                carry = lambda n, place: _offset_node(n, place, r2, q2, c2)
                more, elem, node = _held("FW_CE%d_bt" % k, elem, node, r1, c1, (e1, e2, axis), kt, carry)
                lines += more
            else:
                mid = node
                node += 1
                lines += _offset_node(mid, c1, r2, q2, c2)
                ka, kl = float(v.get("axial") or 0.0), float(v.get("lateral") or 0.0)
                for dof, comp in ((1, axis.x), (2, axis.y), (3, axis.z)):
                    kk = ka * comp * comp + kl * (1.0 - comp * comp)
                    if kk <= 0:
                        continue
                    es = "FW_CE%d_b_%d" % (k, dof)
                    lines += ["*ELEMENT, TYPE=SPRING2, ELSET=%s" % es, "%d, %d, %d" % (elem, r1, mid), "*SPRING, ELSET=%s" % es,
                              "%d, %d" % (dof, dof), repr(float("%.12g" % kk))]
                    elem += 1
            if not v.get("align"):
                more, elem, node = _held("FW_CE%d_br" % k, elem, node, q1, c1, (e1, e2), kr, _same_as(q2))
                lines += more
            if v.get("stabilize"):
                rad = face1.Surface.Radius
                kt = 1e-6 * e_mpa * rad ** 3              # N.mm/rad: far below any real hold, enough to fix the turn
                for dof, comp in ((1, axis.x), (2, axis.y), (3, axis.z)):
                    kk = kt * comp * comp
                    if kk <= 1e-12 * kt:
                        continue
                    es = "FW_CE%d_s_%d" % (k, dof)
                    lines += ["*ELEMENT, TYPE=SPRING2, ELSET=%s" % es, "%d, %d, %d" % (elem, q1, q2), "*SPRING, ELSET=%s" % es,
                              "%d, %d" % (dof, dof), repr(float("%.12g" % kk))]
                    elem += 1
            continue
        end2 = r2
        # bolt and spring: a node at the first end carried rigidly by the second, the springs between it and the
        # first end (two-node springs between points apart would drop the lever's moment)
        mid = node
        node += 1
        if spread:
            lines += _distributed_lines(mid, c1, dist[1])     # straight from end 2's nodes: no equation on equations
        else:
            lines += _offset_node(mid, c1, r2, q2, c2)
        r2 = mid
        pairs_ = []                           # (node 1, node 2, along-axis stiffness, across stiffness)
        if kind == "Bolt":
            # a steel shank between the two ends: axial EA/L, shear 12EI/L^3, torsion GJ/L, bending 4EI/L
            d = float(v["diameter"])
            length = max((c2 - c1).Length, 0.25 * d)
            area = math.pi * d * d / 4.0
            inertia = math.pi * d ** 4 / 64.0
            eb, nu = bolt_material(v)
            g_mpa = eb / (2.0 * (1.0 + nu))
            if (c2 - c1).Length > 1e-6:
                axis = (c2 - c1).normalize()
            pairs_.append((r1, r2, eb * area / length, 12.0 * eb * inertia / length ** 3))
            pairs_.append((q1, q2, g_mpa * 2.0 * inertia / length, 4.0 * eb * inertia / length))
            pre = bolt_axial(v)
            if pre > 0:
                # the tightened bolt pulls the head side toward the nut side and the nut side back: its shank stretches
                n = axis
                step.append("** %s pre-load %.6g N" % (o.Label, pre))
                step.append("*CLOAD")
                for node_, sign in ((r1, 1.0), (end2, -1.0)):
                    for dof, comp in ((1, n.x), (2, n.y), (3, n.z)):
                        if abs(comp) > 1e-12:
                            step.append("%d, %d, %.12g" % (node_, dof, sign * pre * comp))
        else:
            pairs_.append((r1, r2, float(v.get("axial") or 0.0), float(v.get("tangential") or 0.0)))
        if record is not None:                # what the connector forces are read back from after the run
            record.append((o.Name, (axis.x, axis.y, axis.z), bolt_axial(v) if kind == "Bolt" else 0.0, list(pairs_)))
        for p, (n1, n2, ka, ks) in enumerate(pairs_):
            for dof, comp in ((1, axis.x), (2, axis.y), (3, axis.z)):
                kk = ka * comp * comp + ks * (1.0 - comp * comp)
                if kk <= 0:
                    continue
                es = "FW_CE%d_%d_%d" % (k, p, dof)
                lines += ["*ELEMENT, TYPE=SPRING2, ELSET=%s" % es, "%d, %d, %d" % (elem, n1, n2), "*SPRING, ELSET=%s" % es,
                          "%d, %d" % (dof, dof), repr(float("%.12g" % kk))]    # CalculiX wants a real ("100000" is no data)
                elem += 1
    return lines


def connector_forces(a):
    ""


    import os
    import numpy as np
    from . import addintabs
    frd, rec = SPRINGS.get(a.Name, (None, []))
    for o in connectors(a):
        if FORCES in o.PropertiesList:
            setattr(o, FORCES, "")            # a connector the run left out shows no stale forces
    if not frd or not rec or not os.path.exists(frd):
        return {}
    disp = addintabs._frd_disp(frd)
    out = {}
    for name, axis, pre, pairs in rec:
        o = a.Document.getObject(name)
        if o is None or len(pairs) < 1:
            continue
        ax = np.array(axis, float)
        ax = ax / (np.linalg.norm(ax) or 1.0)
        def pull(pair):
            n1, n2, ka, ks = pair
            k = np.array([ka * c * c + ks * (1.0 - c * c) for c in ax])
            return k * (np.array(disp.get(n2, (0, 0, 0))) - np.array(disp.get(n1, (0, 0, 0))))
        f = pull(pairs[0])
        axial = float(f.dot(ax)) + pre
        shear = f - f.dot(ax) * ax
        m = pull(pairs[1]) if len(pairs) > 1 else np.zeros(3)
        torque = float(m.dot(ax))
        bend = m - torque * ax
        row = lambda v_: [float(v_[0]), float(v_[1]), float(v_[2]), float(np.linalg.norm(v_))]
        res = {"axial": row(axial * ax), "axial_value": axial, "shear": row(shear), "bending": row(bend),
               "torque": row(torque * ax), "torque_value": torque}
        if FORCES not in o.PropertiesList:
            o.addProperty("App::PropertyString", FORCES, "FreeCAD", "the connector's forces after the last run (JSON)")
            o.setPropertyStatus(FORCES, ["Hidden"])
        setattr(o, FORCES, json.dumps(res))
        out[name] = res
    return out


def forces_of(o):
    try:
        return json.loads(getattr(o, FORCES, "") or "{}")
    except ValueError:
        return {}


def patch_input(a, path, femmesh):
    """Adds the connectors to the CalculiX input FreeCAD wrote (before its *STEP)."""
    if not any(not getattr(o, "Suppressed", False) for o in connectors(a)):
        return False
    text = open(path).read()
    nodes = list(femmesh.Nodes)
    elems = list(femmesh.Volumes) + list(femmesh.Faces) + list(femmesh.Edges)
    node0 = max(nodes) + 1000 if nodes else 1000
    elem0 = max(elems) + 1000 if elems else 1000
    for line in text.splitlines():           # nodes FreeCAD added itself (rigid bodies, beams)
        s = line.split(",")[0].strip()
        if s.isdigit():
            node0 = max(node0, int(s) + 1000)
            elem0 = max(elem0, int(s) + 1000)
    skip = set()
    for o in a.Group:                         # nodes already held: a tie's slave side (an equation), a fixture (fixed dofs)
        if getattr(o, "Suppressed", False) or not getattr(o, "References", None):
            continue
        if _is(o, "Fem::ConstraintTie"):
            refs = [(o.References[0][0], o.References[0][1][0])] if o.References[0][1] else []
        elif _is(o, "Fem::ConstraintFixed") or _is(o, "Fem::ConstraintDisplacement"):
            refs = [(g, s) for g, subs in o.References for s in subs]
        else:
            continue
        for g, s in refs:
            if s.startswith("Face"):
                skip.update(side_nodes(femmesh, g, s))
    step = []
    rec = []
    lines = connector_input(a, femmesh, node0, elem0, skip, step, rec)
    SPRINGS[a.Name] = (path[:-4] + ".frd", rec)
    i = text.upper().find("\n*STEP")
    if i < 0:
        raise ValueError("The solver input has no *STEP.")
    text = text[:i + 1] + "** FreeCAD connectors\n" + "\n".join(lines) + "\n" + text[i + 1:]
    if step:
        up = text.upper()
        j = up.find("\n*NODE FILE", i)
        j = j if j >= 0 else up.find("\n*END STEP", i)
        if j < 0:
            raise ValueError("The solver input has no *END STEP.")
        text = text[:j + 1] + "\n".join(step) + "\n" + text[j + 1:]
    with open(path, "w") as f:
        f.write(text)
    return True


def fix_contact(path):
    """CalculiX 2.23's surface-to-surface contact on 10-node tetrahedra (High quality mesh) gets the contact force
    wrong (two stacked blocks under 1000 N: 3000 N at the fixture, twice the shortening). Node-to-surface contact
    gives the hand answer (and a bolted lap joint between Bonded and Free), so every contact pair is written that
    way; its *CONTACT PRINT is left out, because CalculiX crashes writing it for node-to-surface pairs."""
    text = open(path).read()
    if "*CONTACT PAIR" not in text.upper():
        return False
    out, skip = [], False
    for line in text.splitlines(True):
        up = line.upper()
        if skip:
            skip = False
            if not up.lstrip().startswith("*"):
                continue                       # the print's variables line (CF, CFN, CFS)
        if up.startswith("*CONTACT PRINT"):
            skip = True
            continue
        if up.startswith("*CONTACT PAIR") and "SURFACE TO SURFACE" in up:
            i = up.index("SURFACE TO SURFACE")
            line = line[:i] + "NODE TO SURFACE" + line[i + len("SURFACE TO SURFACE"):]
        out.append(line)
    new = "".join(out)
    if new != text:
        with open(path, "w") as f:
            f.write(new)
    return True


def _patch_ccx():
    try:
        from femtools import ccxtools
    except ImportError:
        return False
    cls = ccxtools.FemToolsCcx
    if getattr(cls, "_fw_connectors", False):
        return True
    write0 = cls.write_inp_file

    def write_inp_file(self, *args, **kw):
        r = write0(self, *args, **kw)
        try:
            fix_contact(self.inp_file_name)
        except Exception as error:
            App.Console.PrintError("FreeCAD: contact input not adjusted (%s)\n" % error)
        try:
            a = self.analysis
            if is_assembly_study(a) or connectors(a):
                mesh = next((m for m in a.Group if m.isDerivedFrom("Fem::FemMeshObject")), None)
                patch_input(a, self.inp_file_name, mesh.FemMesh)
        except Exception as error:
            App.Console.PrintError("FreeCAD: connectors not written (%s)\n" % error)
            raise
        return r

    cls.write_inp_file = write_inp_file
    cls._fw_connectors = True
    return True


HOLDS = ("Fem::ConstraintFixed", "Fem::ConstraintDisplacement", "Fem::ConstraintSpring")


def unheld(a, made=()):
    ""


    geom = geometry(a)
    if geom is None:
        return []
    try:
        from . import addintabs
        kind = str(getattr(addintabs._solver(a), "AnalysisType", "static"))
    except Exception:
        kind = "static"
    if kind not in ("static", "buckling"):
        return []
    n = len(geom.Shape.Solids)
    if n < 2:
        return []

    def solids(o):
        out = set()
        for obj, subs in getattr(o, "References", None) or []:
            if obj is not geom:
                continue
            for sub in subs or ():
                try:
                    i = solid_index(geom, sub)
                except Exception:
                    i = None
                if i is not None:
                    out.add(i)
        return out
    held, links = set(), []
    for o in a.Group:
        if any(o.isDerivedFrom(t) for t in HOLDS):
            held |= solids(o)
        elif o in made or CONNECTOR in o.PropertiesList or o.isDerivedFrom("Fem::ConstraintTie") \
                or o.isDerivedFrom("Fem::ConstraintContact"):
            links.append(solids(o))
    if not held:
        return []           # no fixture at all: FreeCAD's own prerequisites say so
    grow = True
    while grow:
        grow = False
        for ss in links:
            if ss & held and not ss <= held:
                held |= ss
                grow = True
    names = owners(geom)
    loose = []
    for i in range(n):
        if i not in held:
            c = assembly(a).Document.getObject(names[i]) if i < len(names) else None
            loose.append(c.Label if c is not None else "Solid%d" % (i + 1))
    return loose


def underconstrained(a):
    ""


    geom = geometry(a)
    if geom is None or geom.Shape.isNull():
        return []
    n = len(geom.Shape.Solids)
    names = owners(geom)

    def solids(o):
        out = set()
        for obj, subs in getattr(o, "References", None) or []:
            if obj is not geom:
                continue
            for sub in subs or ():
                try:
                    i = solid_index(geom, sub)
                except Exception:
                    i = None
                if i is not None:
                    out.add(i)
        return out
    held, links = set(), []
    for o in a.Group:
        if getattr(o, "Suppressed", False) or AUTO in o.PropertiesList:
            continue
        if any(o.isDerivedFrom(t) for t in HOLDS):
            held |= solids(o)
        elif CONNECTOR in o.PropertiesList or o.isDerivedFrom("Fem::ConstraintTie") or o.isDerivedFrom("Fem::ConstraintContact"):
            links.append(solids(o))
    if n > 1:
        local = _local_faces(a)
        dists = {}
        for i, fi, j, fj in touching_pairs(geom, _reach(a), dists):
            if fi in local or fj in local:
                continue
            kind, _friction, gap = _type_for(a, names[i] if i < len(names) else "", names[j] if j < len(names) else "")
            if kind == "Free":
                continue
            if dists.get((fi, fj), 0.0) > TOUCH and not (kind == "Bonded" and dists[(fi, fj)] <= gap):
                continue
            links.append({i, j})
    grow = True
    while grow:
        grow = False
        for ss in links:
            if ss & held and not ss <= held:
                held |= ss
                grow = True
    loose = []
    for i in range(n):
        if i not in held:
            c = assembly(a).Document.getObject(names[i]) if i < len(names) else None
            loose.append(c.Label if c is not None else "Solid%d" % (i + 1))
    return loose


def _patch_run():
    from . import addintabs
    if getattr(addintabs, "_fw_asmsim", False):
        return
    run0 = addintabs.run_study

    def run_study(analysis):
        if is_assembly_study(analysis):
            made = prepare(analysis)
            loose = unheld(analysis, made)
            if loose and not getattr(addintabs, "uses_soft", lambda _a: False)(analysis):   # soft springs hold them
                raise RuntimeError(
                    "The model is not adequately restrained: %s %s held by no fixture, connector or interaction, "
                    "so the solver cannot place %s. Add a fixture, a connector (Bolt, Pin, Spring) or an "
                    "interaction (Bonded or Contact) that joins %s to a held part." % (
                        ", ".join(loose), "is" if len(loose) == 1 else "are", "it" if len(loose) == 1 else "them",
                        "it" if len(loose) == 1 else "them"))
        r = run0(analysis)
        try:
            if is_assembly_study(analysis):
                connector_forces(analysis)
        except Exception as _fw_err:
            _fw_log("asmsim.py:forces", _fw_err)
        return r

    addintabs.run_study = run_study
    addintabs._fw_asmsim = True


def _patch_sets():
    """A fixture (or displacement) on a face of a study made of several solids holds that solid's nodes only. FreeCAD
    finds a face's nodes by where they are, so a shaft passing through a fixed face's hole would be held too (and
    CalculiX stops "in cascade" when that shaft carries a connector)."""
    try:
        from femmesh import meshsetsgetter as msg
    except ImportError:
        return False
    cls = msg.MeshSetsGetter
    if getattr(cls, "_fw_own_nodes", False):
        return True
    for name in ("get_constraints_fixed_nodes", "get_constraints_displacement_nodes"):
        orig = getattr(cls, name, None)
        if orig is None:
            continue

        def wrapped(self, _orig=orig, _name=name):
            _orig(self)
            objs = self.member.cons_fixed if "fixed" in _name else self.member.cons_displacement
            for femobj in objs:
                try:
                    o = femobj["Object"]
                    refs = [(r[0], sub) for r in o.References for sub in r[1]]
                    if not refs or any(not sub.startswith("Face") or len(r.Shape.Solids) < 2 for r, sub in refs):
                        continue
                    keep = set()
                    for r, sub in refs:
                        keep.update(side_nodes(self.femmesh, r, sub))
                    femobj["Nodes"] = [n for n in femobj["Nodes"] if n in keep]
                    for k in ("NodesSolid", "NodesFaceEdge"):
                        if k in femobj:
                            femobj[k] = set(n for n in femobj[k] if n in keep)
                except Exception as _fw_err:
                    _fw_log("asmsim.py:ownnodes", _fw_err)
        setattr(cls, name, wrapped)
    cls._fw_own_nodes = True
    return True


def install_core():
    _patch_ccx()
    _patch_sets()
    _patch_run()


# --------------------------------------------------------------------------- materials per component
def _material_dict(name):
    from . import evaltools
    dens, yld, e, nu = evaltools.MATERIALS[name][:4]
    return {"Name": name, "YoungsModulus": "%g MPa" % e, "PoissonRatio": str(nu), "Density": "%g kg/m^3" % dens,
            "YieldStrength": "%g MPa" % yld}


def material_names():
    from . import evaltools
    return list(evaltools.MATERIALS)


def _solid_refs(m):
    return [s for r in (getattr(m, "References", []) or []) for s in r[1] if s.startswith("Solid")]


def material_of(a, index):
    """The study material the solid (0-based) is made of."""
    from . import simtree
    mats = simtree._materials(a)
    own = [m for m in mats if "Solid%d" % (index + 1) in _solid_refs(m)]
    common = [m for m in mats if not list(getattr(m, "References", []) or [])]
    return (own or common or [None])[0]


def set_material(a, comp, name):
    """Apply Material to one component (its solids) or, comp None, to all of them."""
    import ObjectsFem
    from . import simtree
    geom = geometry(a)
    doc = a.Document
    n = len(geom.Shape.Solids)
    names = owners(geom)
    mats = simtree._materials(a)
    if comp is None:
        for m in mats[1:]:
            a.removeObject(m)
            doc.removeObject(m.Name)
        m = mats[0] if mats else ObjectsFem.makeMaterialSolid(doc, "Material")
        if m not in a.Group:
            a.addObject(m)
        m.References = []
        m.Material = _material_dict(name)
        doc.recompute()
        return m
    mine = ["Solid%d" % (i + 1) for i, c in enumerate(names) if c == comp]
    target = None
    for m in mats:
        refs = [s for s in _solid_refs(m) if s not in mine]
        if not list(getattr(m, "References", []) or []):          # the common material: now the other solids only
            refs = ["Solid%d" % (i + 1) for i in range(n) if "Solid%d" % (i + 1) not in mine and
                    not any("Solid%d" % (i + 1) in _solid_refs(x) for x in mats if x is not m)]
        if set(_solid_refs(m)) == set(mine) and target is None:
            target = m
            continue
        if refs:
            m.References = [(geom, tuple(refs))]
        else:
            a.removeObject(m)
            doc.removeObject(m.Name)
    if target is None:
        target = ObjectsFem.makeMaterialSolid(doc, "Material")
        a.addObject(target)
    target.References = [(geom, tuple(mine))]
    target.Material = _material_dict(name)
    doc.recompute()
    return target


# --------------------------------------------------------------------------- the study tree's rows and menus
def part_rows(a, root, Row):
    ""
    from . import simtree
    folder = root.add(Row("Parts", "SIM_ApplyMaterial", None, "asmparts"))
    geom = geometry(a)
    names = owners(geom)
    seen = []
    for i, c in enumerate(names):
        if c in seen:
            continue
        seen.append(c)
        comp = a.Document.getObject(c)
        m = material_of(a, i)
        text = (comp.Label if comp is not None else c) + (" (-%s-)" % simtree._material_name(m) if m is not None else "")
        folder.add(Row(text, "SIM_ApplyMaterial", comp, "asmcomp", plot=c))
    return folder


def connection_rows(a, conn, Row):
    """Under Connections: Component Interactions (the Global Interaction first), then the connectors."""
    if is_assembly_study(a):
        ci = conn.add(Row("Component Interactions", "SIM_Interaction", None, "interactions"))
        ci.add(Row("Global Interaction (-%s-)" % global_type(a), "SIM_Interaction", None, "global"))
        for o in interactions(a):
            comps = ", ".join((a.Document.getObject(c).Label if a.Document.getObject(c) else c) for c in o.Components)
            sup = " (Suppressed)" if getattr(o, "Suppressed", False) else ""
            ci.add(Row("%s (-%s<%s>-)%s" % (o.Label, getattr(o, INTERACTION), comps, sup), "SIM_Interaction", o, "ours"))
        conn.rows.insert(0, conn.rows.pop())
    icons = {"Bolt": "SIM_Bolt", "Pin": "SIM_Pin", "Spring": "SIM_SpringConnector", "Bearing": "SIM_BearingConnector",
             "Rigid": "SIM_RigidConnector"}
    for o in connectors(a):
        sup = " (Suppressed)" if getattr(o, "Suppressed", False) else ""
        conn.add(Row(o.Label + sup, icons.get(getattr(o, CONNECTOR)), o, "ours"))


def two_solids(a):
    g = geometry(a)
    return g is not None and len(g.Shape.Solids) > 1


def menu_entries(row, a, key):
    """Entries for the rows this module adds (None: not one of them). key(text, catalog key) adds a command entry."""
    out = []
    w, o = row.what, row.obj
    if w == "interactions":
        key("Component Interaction...", "SIM_Interaction")
        return []
    if w == "global":
        return [("Edit Definition...", lambda: open_interaction(a, glob=True))]
    if w == "ours" and o is not None:
        sup = bool(getattr(o, "Suppressed", False))
        return [("Edit Definition...", lambda: edit(o)), ("Unsuppress" if sup else "Suppress", lambda: _suppress(o, not sup)),
                ("-", None), ("Delete", lambda: _delete(o))]
    if w == "asmparts":
        return [("Apply Material to All...", lambda: pick_material(a, None))]
    if w == "asmcomp":
        return [("Apply/Edit Material...", lambda: pick_material(a, row.plot))]
    return None


def connections_extra(a, key):
    """The Connections folder's entries this module backs."""
    if is_assembly_study(a):
        key("Component Interaction...", "SIM_Interaction")
    if two_solids(a):
        key("Spring...", "SIM_SpringConnector")
        key("Pin...", "SIM_Pin")
        key("Bolt...", "SIM_Bolt")
        key("Bearing...", "SIM_BearingConnector")
        key("Rigid...", "SIM_RigidConnector")
    if is_assembly_study(a) or two_solids(a):
        key("Underconstrained Bodies...", "SIM_Underconstrained")


def _suppress(o, on):
    o.Suppressed = bool(on)
    o.Document.recompute()


def _delete(o):
    from . import simtree
    return simtree.delete_objects([o])


def is_ours(o):
    return o is not None and (CONNECTOR in o.PropertiesList or INTERACTION in o.PropertiesList)


def edit(o):
    a = next((x for x in o.InList if x.isDerivedFrom("Fem::FemAnalysis")), None)
    if INTERACTION in o.PropertiesList:
        return open_interaction(a, edit_=o)
    return open_connector(a, getattr(o, CONNECTOR), o)


def pick_material(a, comp):
    names = material_names()
    m = material_of(a, owners(geometry(a)).index(comp)) if comp else None
    cur = names.index(m.Material.get("Name")) if m is not None and m.Material.get("Name") in names else 0
    pick, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Material", "Material:", names, cur, False)
    if ok:
        a.Document.openTransaction("Apply Material")
        set_material(a, comp, pick)
        a.Document.commitTransaction()
    return pick if ok else None


# =========================================================================== GUI
if Gui is not None:
    from . import simpms
    from . import simxpress as sx

    OPEN = []

    def _study():
        return simpms.active_study(App.ActiveDocument) if App.ActiveDocument is not None else None

    def _show(pm):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        del OPEN[:]
        OPEN.append(pm)
        Gui.Control.showDialog(pm)
        return pm

    class _Choice(QtCore.QObject):
        """Radio buttons read as one choice (currentText / setCurrentText / currentTextChanged)."""
        currentTextChanged = QtCore.Signal(str)

        def __init__(self, radios, parent):
            super().__init__(parent)
            self.radios = radios
            for t, r in radios.items():
                r.toggled.connect(lambda on, t=t: on and self.currentTextChanged.emit(t))

        def currentText(self):
            return next((t for t, r in self.radios.items() if r.isChecked()), "")

        def setCurrentText(self, text):
            if text in self.radios:
                self.radios[text].setChecked(True)

    class InteractionPM(simpms._PM):
        ""


        PM = "Component Interaction"

        def __init__(self, doc, edit=None, glob=False):
            super().__init__(doc, edit)
            msg = sx._box("Message", None, self.PM)
            self.hint = QtWidgets.QLabel("")
            self.hint.setWordWrap(True)
            QtWidgets.QVBoxLayout(msg).addWidget(self.hint)
            typ = sx._box("Interaction Type")
            tl = QtWidgets.QVBoxLayout(typ)
            self.radios = {}
            group = QtWidgets.QButtonGroup(typ)
            for t in ("Bonded", "Contact", "Free"):
                r = QtWidgets.QRadioButton(t)
                r.setObjectName("SWSimInteractionType_" + t)
                group.addButton(r)
                tl.addWidget(r)
                self.radios[t] = r
            self.kind = _Choice(self.radios, typ)
            comps = sx._box("Components")
            cl = QtWidgets.QVBoxLayout(comps)
            self.glob = QtWidgets.QCheckBox("Global Interaction")
            self.glob.setObjectName("SWSimInteractionGlobal")
            cl.addWidget(self.glob)
            self.comps = sx._PickList("SWSimInteractionComponents")
            self.comps.setToolTip("Components: click them; a second click takes one out")
            cl.addWidget(self.comps)
            opt = sx._box("Properties")
            ol = QtWidgets.QFormLayout(opt)
            self.gap_label = QtWidgets.QLabel("Gap range for bonding:")
            self.gap = QtWidgets.QDoubleSpinBox()
            self.gap.setObjectName("SWSimInteractionGap")
            self.gap.setRange(0.0, 100.0)
            self.gap.setDecimals(3)
            self.gap.setSingleStep(0.01)
            self.gap.setSuffix("%")
            self.gap.setValue(0.01)
            self.gap_mm = QtWidgets.QLabel("")
            grow = QtWidgets.QHBoxLayout()
            grow.addWidget(self.gap)
            grow.addWidget(self.gap_mm, 1)
            ol.addRow(self.gap_label)
            ol.addRow(grow)
            self.friction = QtWidgets.QCheckBox("Coefficient of friction")
            self.friction.setObjectName("SWSimInteractionFriction")
            self.coef = QtWidgets.QDoubleSpinBox()
            self.coef.setObjectName("SWSimInteractionCoefficient")
            self.coef.setRange(0.0, 1.0)
            self.coef.setDecimals(3)
            self.coef.setSingleStep(0.05)
            self.coef.setValue(0.05)
            ol.addRow(self.friction, self.coef)
            self.opt = opt
            self.boxes = [self.comps]
            self.form = [msg, typ, comps, opt]
            size = self._size()
            if glob:
                self.glob.setChecked(True)
                self.kind.setCurrentText(global_type(self.a))
                if global_gap(self.a) and size:
                    self.gap.setValue(100.0 * global_gap(self.a) / size)
            elif edit is not None:
                self.kind.setCurrentText(getattr(edit, INTERACTION))
                for c in edit.Components:
                    co = doc.getObject(c)
                    self.comps.addItem(co.Label if co is not None else c)
                if edit.Friction:
                    self.friction.setChecked(True)
                    self.coef.setValue(edit.Friction)
                if getattr(edit, "Gap", 0.0) and size:
                    self.gap.setValue(100.0 * edit.Gap / size)
            else:
                self.kind.setCurrentText("Bonded")
            self.glob.toggled.connect(lambda *_: self._enable())
            self.kind.currentTextChanged.connect(lambda *_: self._enable())
            self.friction.toggled.connect(lambda *_: self._enable())
            self.gap.valueChanged.connect(lambda *_: self._gap_text())
            self._gap_text()
            self._enable()
            self.current = self.comps
            self.comps.active(True)
            Gui.Selection.clearSelection()
            Gui.Selection.addObserver(self)

        def _size(self):
            try:
                g = geometry(self.a) if self.a is not None else None
                return g.Shape.BoundBox.DiagonalLength if g is not None and not g.Shape.isNull() else 0.0
            except Exception:
                return 0.0

        def _gap(self):
            return self.gap.value() / 100.0 * self._size()

        def _gap_text(self):
            self.gap_mm.setText("= %.4g mm" % self._gap())

        def _enable(self):
            # hidden, not greyed: the component list only without Global; Properties: Bonded's gap range, a
            # component Contact's friction, nothing for Free
            g, kind = self.glob.isChecked(), self.kind.currentText()
            c, b = kind == "Contact" and not g, kind == "Bonded"
            self.comps.setVisible(not g)
            for w in (self.gap_label, self.gap, self.gap_mm):
                w.setVisible(b)
            self.friction.setVisible(c)
            self.coef.setVisible(c and self.friction.isChecked())
            simpms._box_visible(self.opt, b or c)
            from . import safe_later as _sl; _sl.later(0, lambda: self._open() and simpms._box_visible(self.opt, self._props()), self, "glob")
            self.hint.setText("Pick the components or bodies that take a %s interaction wherever they touch another "
                              "component. Global Interaction gives it to every component instead." % kind)

        def _props(self):
            kind = self.kind.currentText()
            return kind == "Bonded" or (kind == "Contact" and not self.glob.isChecked())

        def addSelection(self, doc, name, sub, pnt):
            if doc != self.doc.Name or self.glob.isChecked():
                return
            first = (sub or "").split(".")[0]
            comp = self.doc.getObject(first) if first else None
            if comp is None or comp.Name not in [c.Name for c in _components(assembly(self.a))]:
                return
            QtCore.QTimer.singleShot(0, lambda: (self.comps.toggle(comp.Label), Gui.Selection.clearSelection()))

        def _names(self):
            by_label = {c.Label: c.Name for c in _components(assembly(self.a))}
            return [by_label[v] for v in self.comps.values() if v in by_label]

        def apply(self):
            kind = self.kind.currentText()
            gap = self._gap() if kind == "Bonded" else None
            if self.glob.isChecked():
                return set_global(self.a, kind, gap)
            fr = self.coef.value() if self.friction.isChecked() and kind == "Contact" else None
            return add_component_interaction(self.a, self._names(), kind, fr, self.edit, gap)

        def accept(self):
            if self.a is not None and not is_assembly_study(self.a):
                QtWidgets.QMessageBox.warning(Gui.getMainWindow(), self.PM, "Component Interactions are for an assembly's study.")
                return False
            return super().accept()

    class ConnectorPM(simpms._PM):
        """Bolt, Pin or Spring connector: the two faces it joins and its values."""

        def __init__(self, doc, kind="Bolt", edit=None, faces=None, switch=False):
            self.kind = getattr(edit, CONNECTOR, kind) if edit is not None and not switch else kind

            self.PM = {"Bolt": "Connectors", "Pin": "Connectors", "Spring": "Connectors",
                       "Bearing": "Bearing Connector", "Rigid": "Rigid Connection"}[self.kind]
            super().__init__(doc, edit)
            v = values_of(edit) if edit is not None else {}
            msg = sx._box("Message", None, self.PM)
            hint = {"Bolt": "Pick the round face of the hole on the head side, then the one on the nut side. Near the "
                            "bolt, within about its diameter, the plotted stress reads higher than in the real part.",
                    "Pin": "Pick the two round faces the pin joins (one on each part, on one axis).",
                    "Spring": "Pick a face on each part: the spring joins their centers.",
                    "Bearing": "Pick the round face of the shaft, then the round face of the housing it turns in.",
                    "Rigid": "Pick a face on each part: the two faces keep their places to each other, as if welded "
                             "through a rigid bar."}[self.kind]
            self.hint = QtWidgets.QLabel(hint)
            self.hint.setWordWrap(True)
            QtWidgets.QVBoxLayout(msg).addWidget(self.hint)
            typ = sx._box("Type")
            tl = QtWidgets.QVBoxLayout(typ)
            self.type_combo = None
            if self.kind in SHARED:
                self.type_combo = QtWidgets.QComboBox()
                self.type_combo.setObjectName("SWSimConnectorType")
                self.type_combo.addItems(list(SHARED))
                self.type_combo.setCurrentText(self.kind)
                self.type_combo.currentTextChanged.connect(self._switch)
                tl.addWidget(self.type_combo)
            self.faces = sx._PickList("SWSimConnectorFaces")
            self.faces.setToolTip("The two faces joined: click them; a second click takes one out")
            tl.addWidget(self.faces)
            opt = sx._box({"Bolt": "Bolt", "Pin": "Connection Type", "Spring": "Stiffness", "Bearing": "Stiffness",
                           "Rigid": "Options"}[self.kind])
            self.extra = []
            ol = QtWidgets.QFormLayout(opt)
            self.values = {}
            if self.kind == "Bolt":
                d = QtWidgets.QDoubleSpinBox()
                d.setObjectName("SWSimBoltDiameter")
                d.setRange(0.0, 1000.0)
                d.setDecimals(3)
                d.setSuffix(" mm")
                d.setValue(float(v.get("diameter", 0.0)))
                d.setToolTip("Shank diameter; 0 takes the hole's")
                ol.addRow("Bolt shank diameter:", d)
                self.values["diameter"] = d

                # over the faces, which deform)
                ct = sx._box("Connection Type")
                ct.setObjectName("SWSimBoltConnectionBox")
                cl = QtWidgets.QHBoxLayout(ct)
                self.conn = QtWidgets.QButtonGroup(ct)
                for i, t in enumerate(CONNECTIONS):
                    rb = QtWidgets.QRadioButton(t)
                    rb.setObjectName("SWSimBoltConnection_" + t)
                    rb.setToolTip("The bolt's ends hold the faces rigid" if t == "Rigid" else
                                  "The bolt's ends are spread over the faces, which keep deforming")
                    self.conn.addButton(rb, i)
                    cl.addWidget(rb)
                self.conn.button(CONNECTIONS.index(v.get("connection") or "Rigid")).setChecked(True)
                pre = sx._box("Pre-load")
                pl = QtWidgets.QFormLayout(pre)
                self.ptype = QtWidgets.QButtonGroup(pre)
                row = QtWidgets.QHBoxLayout()
                for i, t in enumerate(PRELOADS):
                    rb = QtWidgets.QRadioButton(t)
                    rb.setObjectName("SWSimBoltPreload_" + t)
                    self.ptype.addButton(rb, i)
                    row.addWidget(rb)
                pl.addRow(row)
                self.ptype.button(PRELOADS.index(v.get("preload_type", "Torque"))).setChecked(True)
                self.pre = QtWidgets.QDoubleSpinBox()
                self.pre.setObjectName("SWSimBoltPreload")
                self.pre.setRange(0.0, 1e12)
                self.pre.setDecimals(3)
                self.pre.setValue(float(v.get("preload", 0.0)) / (1000.0 if v.get("preload_type") == "Torque" else 1.0))
                pl.addRow(self.pre)
                self.kf = QtWidgets.QDoubleSpinBox()
                self.kf.setObjectName("SWSimBoltFriction")
                self.kf.setRange(0.01, 1.0)
                self.kf.setDecimals(3)
                self.kf.setSingleStep(0.05)
                self.kf.setValue(float(v.get("friction_factor", 0.2)))
                self.kf_label = QtWidgets.QLabel("Friction factor (K):")
                pl.addRow(self.kf_label, self.kf)
                self.ptype.buttonToggled.connect(lambda *_: self._enable())
                # Material: a Library material, or Custom elastic modulus and Poisson's ratio
                mat = sx._box("Material")
                ml = QtWidgets.QFormLayout(mat)
                self.lib = QtWidgets.QRadioButton("Library")
                self.lib.setObjectName("SWSimBoltLibrary")
                self.custom = QtWidgets.QRadioButton("Custom")
                self.custom.setObjectName("SWSimBoltCustom")
                self.material = QtWidgets.QComboBox()
                self.material.setObjectName("SWSimBoltMaterial")
                self.material.addItems(list(BOLT_MATERIALS))
                self.material.setCurrentText(v.get("material") or "Alloy Steel")
                ml.addRow(self.lib, self.material)
                ml.addRow(self.custom)
                self.e_box = QtWidgets.QDoubleSpinBox()
                self.e_box.setObjectName("SWSimBoltE")
                self.e_box.setRange(0.0, 1e7)
                self.e_box.setDecimals(1)
                self.e_box.setSuffix(" N/mm^2")
                self.nu_box = QtWidgets.QDoubleSpinBox()
                self.nu_box.setObjectName("SWSimBoltPoisson")
                self.nu_box.setRange(0.0, 0.499)
                self.nu_box.setDecimals(3)
                e0, nu0 = bolt_material(v)
                self.e_box.setValue(e0)
                self.nu_box.setValue(nu0)
                self.e_label = QtWidgets.QLabel("Elastic modulus:")
                self.nu_label = QtWidgets.QLabel("Poisson's ratio:")
                ml.addRow(self.e_label, self.e_box)
                ml.addRow(self.nu_label, self.nu_box)
                (self.custom if v.get("e_mpa") else self.lib).setChecked(True)
                self.lib.toggled.connect(lambda *_: self._enable())
                self.material.currentTextChanged.connect(self._library_values)
                self.extra.insert(0, mat)
                self.extra.insert(0, ct)
                self.extra.append(pre)
            elif self.kind == "Bearing":
                self.stiff = QtWidgets.QButtonGroup(opt)
                row = QtWidgets.QHBoxLayout()
                for i, t in enumerate(STIFFNESS):
                    rb = QtWidgets.QRadioButton(t)
                    rb.setObjectName("SWSimBearing_" + t)
                    self.stiff.addButton(rb, i)
                    row.addWidget(rb)
                ol.addRow(row)
                self.stiff.button(STIFFNESS.index(v.get("stiffness", "Rigid"))).setChecked(True)
                self.springs = []
                for key_, text in (("lateral", "Lateral stiffness:"), ("axial", "Axial stiffness:")):
                    s = QtWidgets.QDoubleSpinBox()
                    s.setObjectName("SWSimBearing_" + key_)
                    s.setRange(0.0, 1e12)
                    s.setDecimals(3)
                    s.setSuffix(" N/mm")
                    s.setValue(float(v.get(key_, 1e5 if key_ == "lateral" else 0.0)))
                    lab = QtWidgets.QLabel(text)
                    ol.addRow(lab, s)
                    self.values[key_] = s
                    self.springs += [lab, s]
                for key_, text in (("align", "Allow self-alignment"), ("stabilize", "Stabilize shaft rotation")):
                    c = QtWidgets.QCheckBox(text)
                    c.setObjectName("SWSimBearing_" + key_)
                    c.setChecked(bool(v.get(key_, False)))
                    ol.addRow(c)
                    self.values[key_] = c
                self.stiff.buttonToggled.connect(lambda *_: self._enable())
            elif self.kind == "Rigid":
                pass
            elif self.kind == "Pin":
                for key_, text in (("ring", "With retaining ring (no translation)"), ("key", "With key (no rotation)")):
                    c = QtWidgets.QCheckBox(text)
                    c.setObjectName("SWSimPin_" + key_)
                    c.setChecked(bool(v.get(key_, False)))
                    ol.addRow(c)
                    self.values[key_] = c
            else:
                for key_, text in (("axial", "Axial:"), ("tangential", "Tangential:")):
                    s = QtWidgets.QDoubleSpinBox()
                    s.setObjectName("SWSimSpring_" + key_)
                    s.setRange(0.0, 1e12)
                    s.setDecimals(3)
                    s.setSuffix(" N/mm")
                    s.setValue(float(v.get(key_, 1000.0 if key_ == "axial" else 0.0)))
                    ol.addRow(text, s)
                    self.values[key_] = s
            self.boxes = [self.faces]
            self.form = [msg, typ] + ([] if self.kind == "Rigid" else [opt]) + self.extra
            if faces is not None:
                self.faces.addItems(list(faces))
            elif edit is not None:
                self.faces.addItems([s for _g, s in _faces_of(edit)])
            self._enable()
            self._start()

        def _switch(self, kind):
            """The Type list: the PM shows that connector's fields, the picked faces kept."""
            faces, edit = self.faces.values(), self.edit
            QtCore.QTimer.singleShot(0, lambda: _show(ConnectorPM(App.ActiveDocument, kind, edit, faces, True)))

        def _library_values(self, name):
            e, nu = BOLT_MATERIALS.get(name, BOLT_MATERIALS["Alloy Steel"])
            if self.lib.isChecked():
                self.e_box.setValue(e)
                self.nu_box.setValue(nu)

        def _enable(self):
            # hidden, not greyed: K only for a torque pre-load, the springs only for a flexible bearing
            if self.kind == "Bolt":
                torque = self.ptype.checkedId() == 1
                self.pre.setSuffix(" N.m" if torque else " N")
                self.kf.setVisible(torque)
                self.kf_label.setVisible(torque)
                custom = self.custom.isChecked()            # hidden, not greyed: the values for Custom only
                for w in (self.e_box, self.nu_box, self.e_label, self.nu_label):
                    w.setVisible(custom)
                self.material.setVisible(not custom)
            elif self.kind == "Bearing":
                flex = self.stiff.checkedId() == 1
                for w in self.springs:
                    w.setVisible(flex)

        def _picked(self, name, sub):
            last = (sub or "").split(".")[-1]
            if last.startswith("Face"):
                self.faces.toggle(last)
            try:
                Gui.Selection.clearSelection()
            except Exception as _fw_err:
                _fw_log("asmsim.py:pick", _fw_err)

        def apply(self):
            vals = {}
            for k, w in self.values.items():
                vals[k] = w.isChecked() if isinstance(w, QtWidgets.QCheckBox) else w.value()
            if self.kind == "Bolt":
                torque = self.ptype.checkedId() == 1
                vals["preload_type"] = PRELOADS[1 if torque else 0]
                vals["connection"] = CONNECTIONS[max(0, self.conn.checkedId())]
                vals["preload"] = self.pre.value() * (1000.0 if torque else 1.0)      # N.m in the box, N.mm kept
                if torque:
                    vals["friction_factor"] = self.kf.value()
                if self.custom.isChecked():
                    vals["e_mpa"] = self.e_box.value()
                    vals["poisson"] = self.nu_box.value()
                else:
                    vals["material"] = self.material.currentText()
            elif self.kind == "Bearing":
                vals["stiffness"] = STIFFNESS[max(0, self.stiff.checkedId())]
            return add_connector(self.a, self.kind, self.faces.values(), self.edit, **vals)

    class ForcesDialog(QtWidgets.QDialog):
        ""


        def __init__(self, a):
            super().__init__(Gui.getMainWindow())
            self.setObjectName("SWSimConnectorForces")
            self.setWindowTitle("Pin/Bolt/Bearing Force")
            self.head = ["Connector", "Type", "X-Component", "Y-Component", "Z-Component", "Resultant"]
            self.rows = []
            for o in connectors(a):
                fv = forces_of(o)
                if not fv:
                    continue
                for label, key_, s in (("Axial Force (N)", "axial", 1.0), ("Shear Force (N)", "shear", 1.0),
                                       ("Bending moment (N.m)", "bending", 1e-3), ("Torque (N.m)", "torque", 1e-3)):
                    self.rows.append([o.Label, label] + ["%.4g" % (x * s) for x in fv[key_]])
            lay = QtWidgets.QVBoxLayout(self)
            lay.addWidget(QtWidgets.QLabel("Study name: %s" % a.Label))
            self.table = QtWidgets.QTableWidget(len(self.rows), len(self.head))
            self.table.setObjectName("SWSimConnectorForcesTable")
            self.table.setHorizontalHeaderLabels(self.head)
            self.table.verticalHeader().hide()
            self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            for r, row in enumerate(self.rows):
                for c, text in enumerate(row):
                    self.table.setItem(r, c, QtWidgets.QTableWidgetItem(text))
            self.table.resizeColumnsToContents()
            lay.addWidget(self.table)
            bb = QtWidgets.QHBoxLayout()
            self.save_btn = QtWidgets.QPushButton("Save")
            self.save_btn.setObjectName("SWSimConnectorForcesSave")
            self.save_btn.clicked.connect(lambda: self.save())
            close = QtWidgets.QPushButton("Close")
            close.clicked.connect(self.accept)
            bb.addStretch(1)
            bb.addWidget(self.save_btn)
            bb.addWidget(close)
            lay.addLayout(bb)
            self.resize(640, 320)

        def save(self, path=None):
            import csv
            if not path:
                path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Save", "Pin-Bolt-Bearing Force.csv", "CSV (*.csv)")
            if not path:
                return None
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(self.head)
                w.writerows(self.rows)
            return path

    FORCE_LISTS = []

    def list_forces(a):
        d = ForcesDialog(a)
        FORCE_LISTS[:] = [d]
        d.show()
        return d

    class UnderconstrainedPM:
        ""

        PM = "Underconstrained Bodies"

        def __init__(self, a):
            self.a = a
            msg = sx._box("Message", None, self.PM)
            hint = QtWidgets.QLabel("Calculate finds the bodies that the fixtures, interactions and connectors leave "
                                    "free to move. Each one needs a fixture, an interaction or a connector before "
                                    "the study can run.")
            hint.setWordWrap(True)
            QtWidgets.QVBoxLayout(msg).addWidget(hint)
            box = sx._box("Underconstrained Bodies")
            bl = QtWidgets.QVBoxLayout(box)
            self.calc = QtWidgets.QPushButton("Calculate")
            self.calc.setObjectName("SWSimUnderCalculate")
            self.calc.clicked.connect(self.calculate)
            bl.addWidget(self.calc)
            self.result = QtWidgets.QLabel("")
            self.result.setObjectName("SWSimUnderResult")
            self.result.setWordWrap(True)
            bl.addWidget(self.result)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("SWSimUnderList")
            self.list.itemClicked.connect(self._pick)
            self.list.setVisible(False)
            bl.addWidget(self.list)
            self.form = [msg, box]

        def calculate(self):
            self.list.clear()
            try:
                loose = underconstrained(self.a)
            except Exception as e:
                self.result.setText(str(e))
                self.list.setVisible(False)
                return []
            if loose:
                self.result.setText("%d of the bodies can move freely:" % len(loose) if len(loose) > 1
                                    else "One body can move freely:")
                self.list.addItems(loose)
            else:
                self.result.setText("No underconstrained bodies were found.")
            self.list.setVisible(bool(loose))
            return loose

        def _pick(self, item):
            try:
                asm = assembly(self.a)
                doc = asm.Document
                c = next((o for o in doc.Objects if o.Label == item.text()), None)
                if c is not None:
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(doc.Name, asm.Name, c.Name + ".")
            except Exception as _fw_err:
                _fw_log("asmsim.py:underpick", _fw_err)

        def getStandardButtons(self):
            return int(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)

        def accept(self):
            Gui.Control.closeDialog()
            return True

        def reject(self):
            Gui.Control.closeDialog()
            return True

    def open_underconstrained(a=None):
        a = a or _study()
        return _show(UnderconstrainedPM(a)) if a is not None else None

    def open_interaction(a=None, edit_=None, glob=False):
        doc = App.ActiveDocument
        return _show(InteractionPM(doc, edit_, glob))

    def open_connector(a=None, kind="Bolt", edit_=None):
        return _show(ConnectorPM(App.ActiveDocument, kind, edit_))

    class _Cmd:
        def __init__(self, text, tip, run, need):
            self.text, self.tip, self.run, self.need = text, tip, run, need

        def GetResources(self):
            return {"MenuText": self.text, "ToolTip": self.tip}

        def IsActive(self):
            a = _study()
            return a is not None and not Gui.Control.activeDialog() and self.need(a)

        def Activated(self):
            self.run()

    COMMANDS = {
        "SWStyle_SimInteraction": _Cmd("Component Interaction", "Bonded, Contact or Free between components, or the "
                                       "Global Interaction.", lambda: open_interaction(), is_assembly_study),
        "SWStyle_SimBolt": _Cmd("Bolt", "A bolt between two holes: axial and shear stiffness of its shank.",
                                lambda: open_connector(None, "Bolt"), two_solids),
        "SWStyle_SimPin": _Cmd("Pin", "A pin joining two round faces on one axis.", lambda: open_connector(None, "Pin"), two_solids),
        "SWStyle_SimSpringConnector": _Cmd("Spring", "A spring between faces of two parts: axial and tangential stiffness.",
                                           lambda: open_connector(None, "Spring"), two_solids),
        "SWStyle_SimBearingConnector": _Cmd("Bearing", "A bearing between a shaft and its housing: the shaft turns, and "
                                            "may tilt when self-aligning.", lambda: open_connector(None, "Bearing"), two_solids),
        "SWStyle_SimUnderconstrained": _Cmd("Underconstrained Bodies", "Finds the bodies that the fixtures, "
                                            "interactions and connectors leave free to move.",
                                            lambda: open_underconstrained(), lambda a: is_assembly_study(a) or two_solids(a)),
        "SWStyle_SimRigidConnector": _Cmd("Rigid", "Two faces of two parts joined rigidly (they keep their places to "
                                          "each other).", lambda: open_connector(None, "Rigid"), two_solids),
    }

    def _patch_pick():
        """A face picked on a component is the matching face of the study's geometry."""
        cls = simpms._PM
        if getattr(cls, "_fw_asmpick", False):
            return
        add0 = cls.addSelection

        def addSelection(self, doc, name, sub, pnt):
            try:
                if is_assembly_study(self.a):
                    m = map_pick(self.a, doc, name, sub)
                    if m is not None and m[1]:
                        name, sub = m
            except Exception as _fw_err:
                _fw_log("asmsim.py:addsel", _fw_err)
            return add0(self, doc, name, sub, pnt)

        cls.addSelection = addSelection
        cls._fw_asmpick = True
        picked0 = sx._picked_faces

        def _picked_faces(doc, obj):
            try:
                if obj is not None and GEOM in obj.PropertiesList:
                    a = simpms.active_study(doc)
                    out = []
                    for sel in Gui.Selection.getSelectionEx(doc.Name, 0):
                        for sub in sel.SubElementNames:
                            m = map_pick(a, doc.Name, sel.Object.Name, sub)
                            if m is not None and m[1] and m[1].startswith("Face"):
                                out.append(m[1])
                    return out
            except Exception as _fw_err:
                _fw_log("asmsim.py:prepicked", _fw_err)
            return picked0(doc, obj)

        sx._picked_faces = _picked_faces

    def _patch_asm_tab():
        """Create New Simulation Study on an assembly's tab makes a full study (geometry, material, mesh, solver)."""
        from . import asmstudytabs as st
        if getattr(st, "_fw_asmsim", False):
            return
        create0 = st.create_simulation

        def create_simulation(asm, study_type=None):
            study_type = study_type or st._ask_type()
            if study_type not in st.SIM_TYPES:
                return None
            doc = asm.Document
            doc.openTransaction("New Simulation Study")
            try:
                a = new_study(asm, st.SOLVER_TYPE[study_type], st._next_label(doc, study_type))
                a.addProperty("App::PropertyString", st.TYPE_PROP, "FreeCAD", "Simulation study type")
                setattr(a, st.TYPE_PROP, study_type)
            except ValueError as error:
                doc.abortTransaction()
                App.Console.PrintWarning("FreeCAD: %s\n" % error)
                return create0(asm, study_type)
            doc.commitTransaction()
            st.open_any(asm, a)
            return a

        st.create_simulation = create_simulation
        st._fw_asmsim = True

    KEYS = (
        ("SIM_Interaction", "Component Interaction", ("SWStyle_SimInteraction",),
         "Bonded, Contact or Free where components touch; the Global Interaction for all.", None),
        ("SIM_Bolt", "Bolt", ("SWStyle_SimBolt",), "A bolt between two holes.", None),
        ("SIM_Pin", "Pin", ("SWStyle_SimPin",), "A pin joining two round faces on one axis.", None),
        ("SIM_SpringConnector", "Spring", ("SWStyle_SimSpringConnector",), "A spring between faces of two parts.", None),
        ("SIM_BearingConnector", "Bearing", ("SWStyle_SimBearingConnector",), "A bearing between a shaft and its housing.", None),
        ("SIM_RigidConnector", "Rigid", ("SWStyle_SimRigidConnector",), "Two faces of two parts joined rigidly.", None),
        ("SIM_Underconstrained", "Underconstrained Bodies", ("SWStyle_SimUnderconstrained",),
         "Finds the bodies that the fixtures, interactions and connectors leave free to move.", None),
    )

    def install():
        install_core()
        for name, cmd in COMMANDS.items():
            if name not in Gui.listCommands():
                Gui.addCommand(name, cmd)
        from . import catalog, simicons
        for key, label, natives, tip, caption in KEYS:
            if key not in catalog.BY_KEY:
                catalog.BY_KEY[key] = catalog.c(key, label, natives, simicons.svg(key), tip, caption=caption)
        for fn in (_patch_pick, _patch_asm_tab):
            try:
                fn()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: assembly simulation (%s): %s\n" % (fn.__name__, error))
else:
    def install():
        install_core()
