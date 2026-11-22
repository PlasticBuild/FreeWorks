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
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import checkstate
from .evaluate import Overlay, ReportWindow, _show, _solids_of, _f, visible_bodies

COMMANDS = {}


def command(name, menu, tip, checkable=False):
    def wrap(func):
        COMMANDS[name] = (menu, tip, func, checkable)
        return func
    return wrap


# ------------------------------------------------------------------ Curvature

_STOPS = [(0.0, (0.0, 0.0, 0.0)), (0.25, (0.0, 0.0, 1.0)), (0.5, (0.0, 0.85, 0.0)),
          (0.75, (1.0, 1.0, 0.0)), (1.0, (1.0, 0.0, 0.0))]
K_FLAT, K_TIGHT = 1e-3, 1.0     # 1/mm: radius 1000 mm and more is black, 1 mm and less red


def curvature_colour(k):
    k = abs(k)
    if k <= K_FLAT:
        return _STOPS[0][1]
    t = (math.log10(min(k, K_TIGHT)) - math.log10(K_FLAT)) / (math.log10(K_TIGHT) - math.log10(K_FLAT))
    for (t0, c0), (t1, c1) in zip(_STOPS, _STOPS[1:]):
        if t <= t1:
            a = (t - t0) / (t1 - t0)
            return tuple(c0[i] + (c1[i] - c0[i]) * a for i in range(3))
    return _STOPS[-1][1]


def curvature_at(face, point):
    """Largest principal curvature (1/mm) of the face at a point on it."""
    try:
        u, v = face.Surface.parameter(point)
    except Exception:
        return 0.0
    try:
        k1, k2 = face.curvatureAt(u, v)
        return max(abs(k1), abs(k2))
    except Exception:
        pass
    # a singular point (a sphere's or a cone's pole): the curvature just beside it, not flat black
    try:
        u0, u1, v0, v1 = face.ParameterRange
        du, dv = (u1 - u0) * 1e-3, (v1 - v0) * 1e-3
        uc, vc = (u0 + u1) / 2.0, (v0 + v1) / 2.0
        for uu, vv in ((u, v + (dv if v < vc else -dv)), (u + (du if u < uc else -du), v),
                       (u + (du if u < uc else -du), v + (dv if v < vc else -dv))):
            try:
                k1, k2 = face.curvatureAt(uu, vv)
                return max(abs(k1), abs(k2))
            except Exception:
                continue
    except Exception as _fw_err:
        _fw_log("evaluate2.py:curvature_at", _fw_err)
    return 0.0


_MESH_CACHE = {}


def _performance(text, default):
    try:
        from . import optionspages
        return optionspages.stored("Performance", text, default)
    except Exception:
        return default


def level_of_detail():
    """System Options > Performance > Level of detail, as the mesh the analyses draw: Less (faster)
    draws a coarser mesh, Off the finest."""
    return {"Off": 0.1, "Less (faster)": 0.5}.get(_performance("Level of detail", "More (slower)"), 0.2)


def curvature_mesh(shape, deflection=None):
    """[(points, triangles, colours)] per face, colours per point (kept per shape, so Curvature
    generation Always has it ready)."""
    deflection = level_of_detail() if deflection is None else deflection
    key = (shape.hashCode(), round(deflection, 4))
    if key in _MESH_CACHE:
        return _MESH_CACHE[key]
    out = _curvature_mesh(shape, deflection)
    if len(_MESH_CACHE) > 32:
        _MESH_CACHE.clear()
    _MESH_CACHE[key] = out
    return out


def _curvature_mesh(shape, deflection):
    out = []
    for face in shape.Faces:
        try:
            pts, tris = face.tessellate(deflection)
        except Exception:
            continue
        if not tris:
            continue
        cols = [curvature_colour(curvature_at(face, p)) for p in pts]
        out.append((pts, tris, cols))
    return out


def assembly_shapes(doc=None):
    ""

    doc = doc or App.ActiveDocument
    try:
        from . import asmcore
        asm = asmcore.assembly_of(doc)
        comps = asmcore.components(asm) if asm is not None else []
    except Exception:
        return []
    import Part
    out = []
    for comp in comps:
        vo = getattr(comp, "ViewObject", None)
        if vo is not None and not vo.Visibility:
            continue
        try:
            shape = Part.getShape(comp, "", needSubElement=False, transform=True)
        except Exception:
            continue
        if not shape.isNull() and shape.Faces:
            out.append(shape)
    return out


def visible_surfaces(doc=None):
    ""

    doc = doc or App.ActiveDocument
    out = []
    if doc is None:
        return out
    for obj in doc.Objects:
        try:
            if not obj.isDerivedFrom("Part::Feature") or obj.isDerivedFrom("Part::Part2DObject") \
                    or obj.TypeId.startswith("PartDesign::"):
                continue
            vo = getattr(obj, "ViewObject", None)
            if vo is None or not vo.Visibility:
                continue
            if any(p.isDerivedFrom("PartDesign::Body") for p in obj.InList):
                continue
            shape = obj.Shape
            if shape.isNull() or not shape.Faces or shape.Solids:
                continue
        except Exception as _fw_err:
            _fw_log("evaluate2.py:surfaces", _fw_err)
            continue
        out.append(obj)
    return out


def curvature_shapes(doc=None):
    """The shapes Curvature colours: the part's shown bodies and surface bodies, or an assembly's shown
    components."""
    comps = assembly_shapes(doc)
    if comps:
        return comps
    return [b.Shape for b in visible_bodies(doc)] + [s.Shape for s in visible_surfaces(doc)]


class _Curvature:
    def __init__(self):
        self.on = False
        self.nodes = []
        self.observer = None

    def show(self):
        from pivy import coin
        self.hide()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is not None and not hasattr(view, "getSceneGraph"):
            view = None         # a drawing sheet (TechDraw page) or another non-3D window is in front
        if view is None:
            return
        for shape in curvature_shapes():
            sep = coin.SoSeparator()
            # no polygon offset: FreeCAD already pushes the body's faces back so its edges draw
            # on top; the colours land at the true depth, in front of the faces, under the edges
            hints = coin.SoShapeHints()
            hints.vertexOrdering.setValue(coin.SoShapeHints.COUNTERCLOCKWISE)
            hints.creaseAngle.setValue(0.5)
            sep.addChild(hints)
            pick = coin.SoPickStyle()
            pick.style.setValue(coin.SoPickStyle.UNPICKABLE)    # clicks go to the body below
            sep.addChild(pick)
            for pts, tris, cols in curvature_mesh(shape):
                part = coin.SoSeparator()
                coords = coin.SoCoordinate3()
                coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                mat = coin.SoMaterial()
                mat.diffuseColor.setValues(0, len(cols), cols)
                bind = coin.SoMaterialBinding()
                bind.value = coin.SoMaterialBinding.PER_VERTEX_INDEXED
                faces = coin.SoIndexedFaceSet()
                idx = []
                for a, b, c in tris:
                    idx += [a, b, c, -1]
                faces.coordIndex.setValues(0, len(idx), idx)
                for node in (coords, mat, bind, faces):
                    part.addChild(node)
                sep.addChild(part)
            view.getSceneGraph().addChild(sep)
            self.nodes.append((view, sep))
        if self.observer is None:
            self.observer = (view, view.addEventCallback("SoLocation2Event", lambda info, v=view: _hover(v, info)))
        self.on = True

    def hide(self):
        for view, sep in self.nodes:
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as _fw_err:
                _fw_log("evaluate2.py:197", _fw_err)
        self.nodes = []
        if self.observer is not None:
            try:
                self.observer[0].removeEventCallback("SoLocation2Event", self.observer[1])
            except Exception as _fw_err:
                _fw_log("evaluate2.py:203", _fw_err)
            self.observer = None
        self.on = False


def readout_text(k):
    if k < 1e-9:
        return "Curvature = 0 1/mm (flat)"
    return "Curvature = %s 1/mm   Radius = %s mm" % (_f(k, 4), _f(1.0 / k, 2))


def _hover(view, info):
    ""
    try:
        hit = view.getObjectInfo(info["Position"])
        if not hit or not hit.get("Component", "").startswith("Face"):
            return
        obj = App.getDocument(hit["Document"]).getObject(hit["Object"])
        face = obj.getSubObject(hit["Component"])
        k = curvature_at(face, App.Vector(hit["x"], hit["y"], hit["z"]))
        Gui.getMainWindow().statusBar().showMessage(readout_text(k), 4000)
    except Exception as _fw_err:
        _fw_log("evaluate2.py:225", _fw_err)


CURVATURE = _Curvature()


class _Redraw:
    """Curvature follows the model: redrawn after each recompute while it is on."""

    def slotRecomputedDocument(self, doc):
        if CURVATURE.on and doc == App.ActiveDocument:
            CURVATURE.show()
        elif doc == App.ActiveDocument and \
                str(_performance("Curvature generation", "Only on demand")).startswith("Always"):

            # rebuild, so turning Curvature on shows at once
            QtCore.QTimer.singleShot(200, _warm)


_REDRAW = _Redraw()


def _warm():
    try:
        for shape in curvature_shapes():
            curvature_mesh(shape)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: curvature generation: %s\n" % error)


@command("SWStyle_Curvature", "Curvature", "Colours faces by how tightly they curve: black flat, red tight.", True)
def curvature():
    if CURVATURE.on:
        CURVATURE.hide()
    else:
        CURVATURE.show()
        if not getattr(_REDRAW, "added", False):
            App.addDocumentObserver(_REDRAW)
            _REDRAW.added = True


checkstate.register("SWStyle_Curvature", lambda: CURVATURE.on)


# ------------------------------------------------------------------ Zebra Stripes
def _vertex_normals(face, pts):
    out = []
    for p in pts:
        try:
            u, v = face.Surface.parameter(p)
            n = face.normalAt(u, v)
        except Exception:
            n = App.Vector(0, 0, 1)
        out.append((n.x, n.y, n.z))
    return out


class _Zebra:
    ""



    def __init__(self):
        self.on = False
        self.nodes = []
        self.stripes = 8

    _VERT = """
varying vec3 N;
varying vec3 P;
void main() {
    N = gl_NormalMatrix * gl_Normal;
    P = (gl_ModelViewMatrix * gl_Vertex).xyz;
    gl_Position = ftransform();
}
"""

    # orthographic camera, every point of a plane reflects the same way, so flat faces came out plain
    # black or white. The ray now comes from a virtual eye in front of the model (its middle, plus
    # ZEBRA_EYE model sizes toward the viewer, in eye space, so it turns with the view), and the stripe
    # is the angle of the reflected ray about the view's x axis: on a plane, each level set of that
    # angle is a straight line. Curved faces keep bands that follow the curvature.
    RAY = """
uniform vec3 centre;
uniform float eye;
vec3 zebra_ray(vec3 P, vec3 n) {
    vec3 e = (gl_ModelViewMatrix * vec4(centre, 1.0)).xyz + vec3(0.0, 0.0, eye);
    return normalize(reflect(P - e, n));
}
"""
    _FRAG = """
varying vec3 N;
varying vec3 P;
uniform float stripes;
""" + RAY + """
void main() {
    vec3 n = normalize(N);
    if (!gl_FrontFacing) n = -n;
    vec3 r = zebra_ray(P, n);
    float c = atan(r.y, -r.z) / 3.14159265;
    float t = fract(c * stripes * 0.5 + 0.5);
    float w = fwidth(t) * 1.5;
    float band = smoothstep(0.5 - w, 0.5 + w, t) - smoothstep(1.0 - w, 1.0, t);
    gl_FragColor = vec4(mix(vec3(0.04), vec3(1.0), band), 1.0);
}
"""

    def _shader(self):
        ""


        from pivy import coin
        prog = coin.SoShaderProgram()
        vs = coin.SoVertexShader()
        vs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        vs.sourceProgram.setValue(self._VERT)
        fs = coin.SoFragmentShader()
        fs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        fs.sourceProgram.setValue(self._FRAG)
        par = coin.SoShaderParameter1f()
        par.name.setValue("stripes")
        par.value.setValue(float(self.stripes))
        fs.parameter.set1Value(0, par)
        for k, par in enumerate(self.ray_parameters(), 1):
            fs.parameter.set1Value(k, par)
        prog.shaderObject.set1Value(0, vs)
        prog.shaderObject.set1Value(1, fs)
        return prog

    def ray_parameters(self):
        """The centre and eye uniforms of RAY (set by show() from the visible bodies)."""
        from pivy import coin
        c = coin.SoShaderParameter3f()
        c.name.setValue("centre")
        c.value.setValue(*getattr(self, "centre", (0.0, 0.0, 0.0)))
        e = coin.SoShaderParameter1f()
        e.name.setValue("eye")
        e.value.setValue(float(getattr(self, "eye", 100.0)))
        return [c, e]

    def show(self):
        from pivy import coin
        self.hide()
        view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        if view is not None and not hasattr(view, "getSceneGraph"):
            view = None         # a drawing sheet (TechDraw page) or another non-3D window is in front
        if view is None:
            return
        bodies = list(visible_bodies())
        box = App.BoundBox()
        for b in bodies:
            try:
                box.add(b.Shape.BoundBox)
            except Exception:
                pass
        if box.isValid():
            self.centre = (box.Center.x, box.Center.y, box.Center.z)
            self.eye = ZEBRA_EYE * max(box.DiagonalLength, 1.0)
        else:
            self.centre, self.eye = (0.0, 0.0, 0.0), 100.0
        for body in bodies:
            sep = coin.SoSeparator()
            pick = coin.SoPickStyle()
            pick.style.setValue(coin.SoPickStyle.UNPICKABLE)
            sep.addChild(pick)
            sep.addChild(self._shader())
            for face in body.Shape.Faces:
                try:
                    pts, tris = face.tessellate(getattr(self, "deflection", 0.1))
                except Exception:
                    continue
                if not tris:
                    continue
                part = coin.SoSeparator()
                coords = coin.SoCoordinate3()
                coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
                normals = coin.SoNormal()
                nv = _vertex_normals(face, pts)
                normals.vector.setValues(0, len(nv), nv)
                nbind = coin.SoNormalBinding()
                nbind.value = coin.SoNormalBinding.PER_VERTEX_INDEXED
                faces = coin.SoIndexedFaceSet()
                idx = []
                for a, b, c in tris:
                    idx += [a, b, c, -1]
                faces.coordIndex.setValues(0, len(idx), idx)
                faces.normalIndex.setValues(0, len(idx), idx)
                for node in (coords, normals, nbind, faces):
                    part.addChild(node)
                sep.addChild(part)
            view.getSceneGraph().addChild(sep)
            self.nodes.append((view, sep))
        self.on = True

    def hide(self):
        for view, sep in self.nodes:
            try:
                view.getSceneGraph().removeChild(sep)
            except Exception as _fw_err:
                _fw_log("evaluate2.py:383", _fw_err)
        self.nodes = []
        self.on = False


ZEBRA_EYE = 0.35    # the virtual eye's distance in front of the model, in model sizes (see _Zebra.RAY)
ZEBRA = _Zebra()


@command("SWStyle_ZebraStripes", "Zebra Stripes", "Shows stripes reflected in the faces to check that faces join smoothly.", True)
def zebra_stripes():
    if ZEBRA.on:
        ZEBRA.hide()
    else:
        ZEBRA.show()
        if not getattr(_ZebraRedraw, "added", False):
            App.addDocumentObserver(_ZebraRedraw())
            _ZebraRedraw.added = True


checkstate.register("SWStyle_ZebraStripes", lambda: ZEBRA.on)


class _ZebraRedraw:
    def slotRecomputedDocument(self, doc):
        if ZEBRA.on and doc == App.ActiveDocument:
            ZEBRA.show()


# ------------------------------------------------------------------ Body Compare
def compare_bodies(a, b, tol=1e-6):
    """Volumes of common / only-in-A / only-in-B and how many faces match exactly."""
    sa, sb = a.Shape, b.Shape
    common = sa.common(sb)
    only_a = sa.cut(sb)
    only_b = sb.cut(sa)

    def key(face):
        c = face.CenterOfMass
        return (round(face.Area, 4), round(c.x, 4), round(c.y, 4), round(c.z, 4))
    kb = {}
    for f in sb.Faces:
        kb.setdefault(key(f), 0)
        kb[key(f)] += 1
    same = 0
    for f in sa.Faces:
        k = key(f)
        if kb.get(k):
            kb[k] -= 1
            same += 1
    return {"common": common, "only_a": only_a, "only_b": only_b,
            "faces_same": same, "faces_a": len(sa.Faces), "faces_b": len(sb.Faces),
            "volume_a": sa.Volume, "volume_b": sb.Volume}


def all_bodies():
    """(label, object) for every body with solids in every open document."""
    out = []
    for doc in App.listDocuments().values():
        for obj in doc.Objects:
            if _solids_of(obj) and not any(p.isDerivedFrom("PartDesign::Body") for p in obj.InList) \
                    and not obj.isDerivedFrom("App::Origin"):
                out.append(("%s : %s" % (doc.Label, obj.Label), obj))
    return out


class BodyCompareWindow(ReportWindow):
    ""


    def __init__(self):
        super().__init__("Body Compare", ["Result", "Value"])
        self.overlay = Overlay()
        self.ref = QtWidgets.QComboBox()
        self.cmp = QtWidgets.QComboBox()
        self.bodies = all_bodies()
        for label, _ in self.bodies:
            self.ref.addItem(label)
            self.cmp.addItem(label)
        picked = [s.Object for s in Gui.Selection.getSelectionEx() if _solids_of(s.Object)]
        objs = [o for _, o in self.bodies]
        first = objs.index(picked[0]) if picked and picked[0] in objs else 0
        second = objs.index(picked[1]) if len(picked) > 1 and picked[1] in objs else min(1, len(objs) - 1)
        self.ref.setCurrentIndex(first)
        self.cmp.setCurrentIndex(max(0, second))
        self.options.addWidget(QtWidgets.QLabel("Reference"))
        self.options.addWidget(self.ref, 1)
        self.options.addWidget(QtWidgets.QLabel("Comparison"))
        self.options.addWidget(self.cmp, 1)
        self.ref.currentIndexChanged.connect(self.refresh)
        self.cmp.currentIndexChanged.connect(self.refresh)
        self.result = None

    def compute(self):
        self.overlay.clear()
        if len(self.bodies) < 2:
            self.summary.setText("Open or make two bodies to compare.")
            return
        a = self.bodies[self.ref.currentIndex()][1]
        b = self.bodies[self.cmp.currentIndex()][1]
        if a == b:
            self.summary.setText("Pick two different bodies.")
            return
        r = self.result = compare_bodies(a, b)
        from .evaluate import len_text
        rows = [(("Reference volume", len_text(r["volume_a"], 3, 2)), []),
                (("Comparison volume", len_text(r["volume_b"], 3, 2)), []),
                (("Common volume", len_text(r["common"].Volume, 3, 2)), []),
                (("Only in reference (blue)", len_text(r["only_a"].Volume, 3, 2)), []),
                (("Only in comparison (red)", len_text(r["only_b"].Volume, 3, 2)), []),
                (("Identical faces", "%d of %d / %d" % (r["faces_same"], r["faces_a"], r["faces_b"])), [])]
        self.set_rows(rows)
        same = r["only_a"].Volume < 1e-6 and r["only_b"].Volume < 1e-6
        self.summary.setText("The bodies are identical." if same and r["faces_same"] == r["faces_a"] == r["faces_b"]
                             else "The bodies differ.")
        if a.Document == App.ActiveDocument:
            self.overlay.add(r["only_a"], (0.1, 0.35, 1.0), 0.25)
            self.overlay.add(r["only_b"], (1.0, 0.1, 0.1), 0.25)

    def cleanup(self):
        self.overlay.clear()


@command("SWStyle_BodyCompare", "Body Compare", "Compares two bodies and shows where their volumes differ.")
def body_compare():
    return _show(BodyCompareWindow)


# ------------------------------------------------------------------ Deviation Analysis
def edge_deviation(shape, edge, samples=10):
    """Angles in degrees between the normals of the two faces that meet at an edge, at evenly
    spaced points along it (0 = the faces join tangent)."""
    faces = shape.ancestorsOfType(edge, __import__("Part").Face)
    if len(faces) != 2:
        return []
    out = []
    for k in range(samples):
        t = edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * (k + 0.5) / samples
        p = edge.valueAt(t)
        normals = []
        for f in faces:
            u, v = f.Surface.parameter(p)
            normals.append(f.normalAt(u, v))
        c = max(-1.0, min(1.0, normals[0].dot(normals[1])))
        out.append((p, math.degrees(math.acos(c))))
    return out


class DeviationWindow(ReportWindow):
    ""


    def __init__(self):
        super().__init__("Deviation Analysis", ["Edge", "Maximum", "Minimum", "Average"])
        self.samples = QtWidgets.QSpinBox()
        self.samples.setRange(2, 500)
        self.samples.setValue(10)
        self.samples.valueChanged.connect(self.refresh)
        self.options.addWidget(QtWidgets.QLabel("Number of sample points"))
        self.options.addWidget(self.samples)
        self.options.addStretch(1)
        self.picks = [(s.Object, n) for s in Gui.Selection.getSelectionEx() for n in s.SubElementNames if n.startswith("Edge")]

    def compute(self):
        picks = [(s.Object, n) for s in Gui.Selection.getSelectionEx() for n in s.SubElementNames if n.startswith("Edge")]
        if picks:
            self.picks = picks      # Recalculate takes the edges picked now
        rows, worst = [], 0.0
        for obj, sub in self.picks:
            vals = [a for _, a in edge_deviation(obj.Shape, obj.Shape.getElement(sub), self.samples.value())]
            if not vals:
                rows.append(((obj.Label + "." + sub, "-", "-", "not between two faces"), [(obj.Document.Name, obj.Name, sub)]))
                continue
            worst = max(worst, max(vals))
            rows.append(((obj.Label + "." + sub, _f(max(vals), 4) + " deg", _f(min(vals), 4) + " deg",
                          _f(sum(vals) / len(vals), 4) + " deg"), [(obj.Document.Name, obj.Name, sub)]))
        self.set_rows(rows)
        self.summary.setText("Select edges between faces, then Recalculate." if not self.picks else
                             "Largest deviation %s deg." % _f(worst, 4))


@command("SWStyle_DeviationAnalysis", "Deviation Analysis", "Measures the angle between faces along the picked edges.")
def deviation_analysis():
    return _show(DeviationWindow)


# ------------------------------------------------------------------ Sensor
SENSOR_KINDS = ["Volume", "Mass", "Surface Area", "Center of Mass X", "Center of Mass Y", "Center of Mass Z",
                "Bounding Box Length", "Bounding Box Width", "Bounding Box Height"]


def sensor_value(kind, bodies, density=7.85e-6):
    """Value of a mass property over the bodies (mm, mm^2, mm^3, kg with density in kg/mm^3)."""
    solids = []
    for b in bodies:
        solids += _solids_of(b)
    if not solids:
        return 0.0
    vol = sum(s.Volume for s in solids)
    if kind == "Volume":
        return vol
    if kind == "Mass":
        return vol * density
    if kind == "Surface Area":
        return sum(s.Area for s in solids)
    if kind.startswith("Center of Mass"):
        c = App.Vector()
        for s in solids:
            c += s.CenterOfMass * s.Volume
        c = c * (1.0 / vol) if vol else c
        return getattr(c, kind[-1].lower())
    box = solids[0].BoundBox
    for s in solids[1:]:
        box.add(s.BoundBox)
    return {"Length": box.XLength, "Width": box.YLength, "Height": box.ZLength}[kind.split()[-1]]


class Sensor:
    ""


    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyEnumeration", "Property", "Sensor", "What to watch").Property = SENSOR_KINDS
        obj.addProperty("App::PropertyLinkList", "Bodies", "Sensor", "Bodies watched; empty = every visible body")
        obj.addProperty("App::PropertyBool", "Alert", "Sensor", "Alert when the value leaves the limits").Alert = True
        obj.addProperty("App::PropertyEnumeration", "Operator", "Sensor", "Alert rule").Operator = \
            ["Is greater than", "Is less than", "Is not between", "Is between"]
        obj.addProperty("App::PropertyFloat", "Limit1", "Sensor", "Limit")
        obj.addProperty("App::PropertyFloat", "Limit2", "Sensor", "Second limit (between)")
        obj.addProperty("App::PropertyFloat", "Density", "Sensor", "Density in kg/mm^3 (Mass)").Density = 7.85e-6
        obj.addProperty("App::PropertyFloat", "Value", "Sensor", "Last value")
        obj.addProperty("App::PropertyBool", "Alerting", "Sensor", "The value is out of its limits")
        obj.setEditorMode("Value", 1)
        obj.setEditorMode("Alerting", 1)

    def execute(self, obj):
        from . import sensorpm
        v = sensorpm.value(obj)
        if v is None:

            obj.Value = 0.0
            obj.Alerting = True
            base = obj.Label.lstrip("⚠ ").strip()
            if obj.Label != "⚠ " + base:
                obj.Label = "⚠ " + base
            App.Console.PrintWarning("Sensor '%s': %s\n" % (base, sensorpm.missing(obj)))
            return
        obj.Value = v
        v, a, b = obj.Value, obj.Limit1, obj.Limit2
        rule = obj.Operator
        bad = sensorpm.alerting(rule, v, a, b)
        obj.Alerting = bool(obj.Alert and bad)
        base = obj.Label.lstrip("⚠ ").strip()
        label = ("⚠ " + base) if obj.Alerting else base
        if obj.Label != label:
            obj.Label = label
        if obj.Alerting:
            App.Console.PrintWarning("Sensor '%s': %s = %s (%s %s)\n" % (base, sensorpm.watched(obj), _f(v, 3),
                                                                        rule.lower(), _f(a, 3)))

    def dumps(self):
        return None

    def loads(self, state):
        return None


def make_sensor(prop="Mass", operator="Is greater than", limit1=0.0, limit2=0.0, bodies=None):
    doc = App.ActiveDocument
    doc.openTransaction("Sensor")
    try:
        s = doc.addObject("App::FeaturePython", "Sensor")
        Sensor(s)
        s.Label = "Sensor - " + prop
        s.Property = prop
        s.Operator = operator
        s.Limit1, s.Limit2 = limit1, limit2
        s.Bodies = list(bodies) if bodies is not None else [b for b in visible_bodies(doc)]
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return s


def measured_value(obj):
    """A Measurement sensor's value: its references measured again, in its unit."""
    from . import measure
    shapes = []
    for o, subs in obj.References:
        for s in subs or [""]:
            try:
                shapes.append(o.getSubObject(s) if s else o.Shape)
            except Exception as _fw_err:
                _fw_log("evaluate2.py:673", _fw_err)
    units = measure.Units(obj.Unit or "Millimeters", 6)
    lines, _draw = measure.measure(shapes, units, obj.ArcMode or measure.ARC_MODES[0])
    for n, v in lines:
        if n == obj.Measurement:
            x = units.value(v)
            if x is not None:
                return x
    return 0.0


def make_measure_sensor(refs, name, units, arc_mode, operator="Is greater than", limit1=0.0, limit2=0.0):
    ""
    doc = App.ActiveDocument
    doc.openTransaction("Sensor")
    try:
        s = doc.addObject("App::FeaturePython", "Sensor")
        Sensor(s)
        s.addProperty("App::PropertyString", "SensorType", "Sensor", "Mass Properties or Measurement").SensorType = "Measurement"
        s.addProperty("App::PropertyLinkSubListGlobal", "References", "Sensor", "What is measured")
        s.addProperty("App::PropertyString", "Measurement", "Sensor", "The result watched (Distance, Diameter...)")
        s.addProperty("App::PropertyString", "Unit", "Sensor", "Length unit of the value")
        s.addProperty("App::PropertyString", "ArcMode", "Sensor", "Arc/Circle Measurements")
        grouped = {}
        for o, sub in refs:
            grouped.setdefault(o, []).append(sub)
        s.References = [(o, subs) for o, subs in grouped.items()]
        s.Measurement = name
        s.Unit = units.length
        s.ArcMode = arc_mode
        s.Label = "Sensor - %s" % name
        s.Operator = operator
        s.Limit1, s.Limit2 = limit1, limit2
        doc.recompute()
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    return s


class _SensorDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(Gui.getMainWindow())
        from .widgets import ui_font
        self.setWindowTitle("Sensor")
        self.setFont(ui_font())
        form = QtWidgets.QFormLayout(self)
        self.prop = QtWidgets.QComboBox()
        self.prop.addItems(SENSOR_KINDS)
        self.prop.setCurrentText("Mass")
        self.op = QtWidgets.QComboBox()
        self.op.addItems(["Is greater than", "Is less than", "Is not between", "Is between"])
        self.l1 = QtWidgets.QDoubleSpinBox()
        self.l2 = QtWidgets.QDoubleSpinBox()
        for sb in (self.l1, self.l2):
            sb.setRange(-1e12, 1e12)
            sb.setDecimals(4)
        self.now = QtWidgets.QLabel("")
        form.addRow("Sensor type: Mass Properties", QtWidgets.QLabel(""))
        form.addRow("Property", self.prop)
        form.addRow("Current value", self.now)
        form.addRow("Alert", self.op)
        form.addRow("Limit", self.l1)
        form.addRow("Second limit", self.l2)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.prop.currentTextChanged.connect(self.update_now)
        self.update_now()

    def update_now(self):
        v = sensor_value(self.prop.currentText(), visible_bodies())
        self.now.setText(_f(v, 4))
        self.l1.setValue(v)


@command("SWStyle_Sensor", "Sensor", "Watches a mass property and alerts when it goes out of its limits.")
def sensor():
    ""
    from . import sensorpm
    return sensorpm.open_page(App.ActiveDocument)


# ------------------------------------------------------------------ registration
class _Cmd:
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        menu, tip, _, _ = COMMANDS[self.name]
        return {"MenuText": menu, "ToolTip": tip, "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        COMMANDS[self.name][2]()

    def IsActive(self):
        return App.ActiveDocument is not None


_installed = False


def install():
    global _installed
    if _installed:
        return
    for name in COMMANDS:
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(name))
    if not getattr(_REDRAW, "added", False):
        App.addDocumentObserver(_REDRAW)      # Curvature generation Always works without Curvature on
        _REDRAW.added = True
    try:
        from . import sensorpm
        sensorpm.watch()                 # sensors are checked after every rebuild
    except Exception as error:
        App.Console.PrintLog("FreeCAD: sensor watch: %s\n" % error)
    _installed = True
