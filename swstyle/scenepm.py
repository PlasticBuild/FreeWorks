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
from PySide import QtCore, QtGui, QtWidgets

from . import paths

PARAMS = paths.PARAM_PATH + "/Scene"
VIEW = "User parameter:BaseApp/Preferences/View"
BACKGROUNDS = ("Use Environment", "None", "Color", "Gradient", "Image")
FLOORS = ("Bottom View Plane", "XY Plane", "YZ Plane", "ZX Plane")
NORMALS = {"Bottom View Plane": (0, 0, 1), "XY Plane": (0, 0, 1), "YZ Plane": (1, 0, 0), "ZX Plane": (0, 1, 0)}
REFLECTION_FADE = 0.7          # transparency of the mirrored model (the blend switch; the shader sets the real alpha)
REFLECTION_STRENGTH = 0.5
REFLECTION_DEPTH = 0.75        # the reflection is gone this far below the floor, in parts of the model's height
# the scenes whose floor reflects the model (style.SCENES names); their own Floor reflections choice
# is kept apart from the other scenes' one
REFLECTIVE_SCENES = ("Reflective Floor Black",)
POLL_MS = 600
LARGEST = 1e7
V = App.Vector


def params():
    return App.ParamGet(PARAMS)


def _scene_name(scene=None):
    from . import style
    i = style.current_scene() if scene is None else scene
    return style.SCENES[i][0] if 0 <= i < len(style.SCENES) else ""


def _reflections_key(scene=None):
    """Where a scene's Floor reflections choice is kept: the Reflective Floor scenes each their own
    (on until turned off), the other scenes the one they always shared (off until turned on)."""
    name = _scene_name(scene)
    if name in REFLECTIVE_SCENES:
        return "Reflections " + name, True
    return "Reflections", False


def scene_reflections(scene=None):
    key, default = _reflections_key(scene)
    return params().GetBool(key, default)


def settings():
    p = params()
    return {"background": p.GetString("Background", "Use Environment"),
            "top": p.GetUnsigned("Top", 0xFFFFFFFF), "bottom": p.GetUnsigned("Bottom", 0xC8C8C8FF),
            "image": p.GetString("Image", ""),
            "reflections": scene_reflections(),
            "lock": True,
            "align": p.GetString("Align", "Bottom View Plane"),
            "flip": p.GetBool("Flip", False), "offset": p.GetFloat("Offset", 0.0),
            "autosize": p.GetBool("AutoFloorSize", True), "aspect": p.GetBool("FixedAspect", False),
            "width": p.GetFloat("FloorWidth", 0.0), "depth": p.GetFloat("FloorDepth", 0.0),
            "floor_turn": p.GetFloat("FloorRotation", 0.0), "env_turn": p.GetFloat("EnvironmentRotation", 0.0)}


def store(values):
    p = params()
    p.SetString("Background", values["background"])
    p.SetUnsigned("Top", int(values["top"]) & 0xFFFFFFFF)
    p.SetUnsigned("Bottom", int(values["bottom"]) & 0xFFFFFFFF)
    p.SetString("Image", values["image"] or "")
    p.SetBool(_reflections_key()[0], bool(values["reflections"]))
    p.SetBool("LockEnvironment", bool(values.get("lock", True)))
    p.SetString("Align", values["align"])
    p.SetBool("Flip", bool(values["flip"]))
    p.SetFloat("Offset", float(values["offset"]))
    if "autosize" in values:
        p.SetBool("AutoFloorSize", bool(values["autosize"]))
        p.SetBool("FixedAspect", bool(values["aspect"]))
        p.SetFloat("FloorWidth", float(values["width"]))
        p.SetFloat("FloorDepth", float(values["depth"]))
        p.SetFloat("FloorRotation", float(values["floor_turn"]))
        p.SetFloat("EnvironmentRotation", float(values["env_turn"]))


# ------------------------------------------------------------------ the background
def to_rgba(colour):
    c = QtGui.QColor(colour)
    return (c.red() << 24) | (c.green() << 16) | (c.blue() << 8) | 0xFF


def to_qcolor(value):
    return QtGui.QColor((value >> 24) & 0xFF, (value >> 16) & 0xFF, (value >> 8) & 0xFF)


def image_colours(path):
    """(top, bottom) colours of a picture: the averages of its upper and lower halves."""
    img = QtGui.QImage(path)
    if img.isNull():
        return None
    small = img.scaled(16, 16, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    out = []
    for rows in (range(0, 8), range(8, 16)):
        r = g = b = n = 0
        for y in rows:
            for x in range(16):
                c = QtGui.QColor(small.pixel(x, y))
                r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
        out.append(to_rgba(QtGui.QColor(r // n, g // n, b // n)))
    return tuple(out)


def _write_view(gradient, top, bottom, mid=None):
    v = App.ParamGet(VIEW)
    v.SetBool("RadialGradient", False)
    v.SetBool("Gradient", bool(gradient))
    v.SetBool("UseBackgroundColorMid", mid is not None and gradient)
    v.SetUnsigned("BackgroundColor", top)
    v.SetUnsigned("BackgroundColor2", top)
    v.SetUnsigned("BackgroundColor3", bottom)
    if mid is not None:
        v.SetUnsigned("BackgroundColor4", mid)


def apply_background(values=None):
    values = values or settings()
    kind = values["background"]
    if kind == "Use Environment":
        from . import style
        style.apply_scene(style.current_scene())
    elif kind == "None":
        _write_view(False, 0xFFFFFFFF, 0xFFFFFFFF)
    elif kind == "Color":
        _write_view(False, values["top"], values["top"])
    elif kind == "Gradient":
        _write_view(True, values["top"], values["bottom"])
    elif kind == "Image":
        got = image_colours(values["image"]) if values["image"] else None
        if got:
            _write_view(True, got[0], got[1])
    for view in _views():
        try:
            view.redraw()
        except Exception as _fw_err:
            _fw_log("scenepm.py:129", _fw_err)


# ------------------------------------------------------------------ the floor
def _views():
    out = []
    for gdoc in [Gui.getDocument(d) for d in App.listDocuments()]:
        try:
            for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
                out.append(view)
        except Exception as _fw_err:
            _fw_log("scenepm.py:140", _fw_err)
    return out


def model_box(doc):
    box = App.BoundBox()
    for obj in doc.Objects:
        try:
            if obj.isDerivedFrom("Part::Datum") or obj.getParentGeoFeatureGroup() is not None \
                    or not obj.ViewObject.Visibility or obj.Shape.isNull():
                continue
            b = obj.Shape.BoundBox
        except Exception:
            continue
        if b.isValid() and b.DiagonalLength < LARGEST:
            box.add(b)
    return box if box.isValid() else None


def floor_plane(doc, values=None):
    """(normal, distance) of the floor: points p on it have normal . p = distance."""
    values = values or settings()
    n = V(*NORMALS.get(values["align"], (0, 0, 1)))
    d = 0.0
    if values["align"] == "Bottom View Plane":
        box = model_box(doc)
        if box is not None:
            d = box.ZMin - 0.01 * box.DiagonalLength
    if values["flip"]:
        n = -n
        d = -d
    if values["align"] == "Bottom View Plane" and values["flip"]:
        box = model_box(doc)       # flipped: the floor goes over the model, facing down
        if box is not None:
            d = -(box.ZMax + 0.01 * box.DiagonalLength)
    return n, d - float(values["offset"])


FLOOR_AUTO = 3.0      # Automatically resize floor based on model size: the floor is this many times the model across


def _floor_axes(n):
    """Two unit directions along a floor with normal n (width, depth), before Floor rotation."""
    a = V(1, 0, 0) if abs(n.x) < 0.9 else V(0, 1, 0)
    u = a - n * a.dot(n)
    u.normalize()
    w = n.cross(u)
    return u, w


def auto_floor_size(doc, values=None):
    """(width, depth) the floor takes from the model: FLOOR_AUTO times its size along the floor."""
    values = values or settings()
    box = model_box(doc) if doc is not None else None
    if box is None:
        return 0.0, 0.0
    n, _d = floor_plane(doc, values)
    u, w = _floor_axes(V(abs(n.x), abs(n.y), abs(n.z)))
    sizes = V(box.XLength, box.YLength, box.ZLength)
    along = lambda a: abs(a.x) * sizes.x + abs(a.y) * sizes.y + abs(a.z) * sizes.z
    return FLOOR_AUTO * max(along(u), 1e-3), FLOOR_AUTO * max(along(w), 1e-3)


def floor_rect(doc, values=None):
    """The floor's own rectangle when it is not sized from the model: (centre, width direction, depth
    direction, half width, half depth), the centre under the middle of the model; None for an automatic
    floor (it reaches past whatever the model casts)."""
    import math
    values = values or settings()
    if values.get("autosize", True) or values.get("width", 0.0) <= 0 or values.get("depth", 0.0) <= 0:
        return None
    n, d = floor_plane(doc, values)
    box = model_box(doc)
    mid = box.Center if box is not None else V(0, 0, 0)
    centre = mid - n * (mid.dot(n) - d)
    u, w = _floor_axes(n)
    t = math.radians(values.get("floor_turn", 0.0))
    u, w = u * math.cos(t) + w * math.sin(t), w * math.cos(t) - u * math.sin(t)
    return centre, u, w, 0.5 * values["width"], 0.5 * values["depth"]


def in_floor(rect, p):
    """Whether the point p (on or off the floor) lies over the floor rectangle."""
    if rect is None:
        return True
    centre, u, w, hu, hw = rect
    q = p - centre
    return abs(q.dot(u)) <= hu and abs(q.dot(w)) <= hw


def mirror_matrix(n, d):
    """Coin (row vector) matrix of the reflection in the plane n . p = d."""
    from pivy import coin
    x, y, z = n.x, n.y, n.z
    m = [[1 - 2 * x * x, -2 * x * y, -2 * x * z],
         [-2 * x * y, 1 - 2 * y * y, -2 * y * z],
         [-2 * x * z, -2 * y * z, 1 - 2 * z * z]]
    return coin.SbMatrix(m[0][0], m[0][1], m[0][2], 0,
                         m[1][0], m[1][1], m[1][2], 0,
                         m[2][0], m[2][1], m[2][2], 0,
                         2 * d * x, 2 * d * y, 2 * d * z, 1)


_reflections = {}      # id(view) -> _Reflection

# The reflection's shader: the mirrored faces lit per pixel by FreeCAD's own lights, fading out with

_REFLECT_VERT = """
uniform vec4 floor;          // the floor in model space: unit normal, distance from the origin
uniform mat4 view;           // the camera's matrix where the reflection starts (no model matrix yet)
uniform vec4 rect_c;         // Advanced > Floor Size: the floor's middle (w 1: a floor of its own size)
uniform vec4 rect_u;         // its width direction, w half the width
uniform vec4 rect_v;         // its depth direction, w half the depth
varying vec4 floor_eye;
varying vec2 rect_at;        // where on the floor, in half widths and half depths
varying vec3 N;
varying vec3 P;
varying float below;
varying vec4 C;
void main() {
    C = gl_Color;
    vec4 eye = gl_ModelViewMatrix * gl_Vertex;
    vec3 f = normalize((view * vec4(floor.xyz, 0.0)).xyz);
    vec4 on = view * vec4(floor.xyz * floor.w, 1.0);
    floor_eye = vec4(f, dot(f, on.xyz / on.w));
    // drawn mirrored, lit where the faces really are: the lights do not shine through the floor
    below = floor_eye.w - dot(floor_eye.xyz, eye.xyz);
    P = eye.xyz + 2.0 * below * floor_eye.xyz;
    vec3 n = gl_NormalMatrix * gl_Normal;
    N = n - 2.0 * dot(n, floor_eye.xyz) * floor_eye.xyz;
    rect_at = vec2(0.0);
    if (rect_c.w > 0.5) {
        vec4 c = view * vec4(rect_c.xyz, 1.0);
        vec3 q = eye.xyz / eye.w - c.xyz / c.w;
        rect_at = vec2(dot(q, normalize((view * vec4(rect_u.xyz, 0.0)).xyz)) / max(rect_u.w, 1e-6),
                       dot(q, normalize((view * vec4(rect_v.xyz, 0.0)).xyz)) / max(rect_v.w, 1e-6));
    }
    gl_Position = ftransform();
}
"""

_REFLECT_FRAG = """
varying vec4 floor_eye;
uniform float lights;
uniform float strength;
uniform float depth;
varying vec3 N;
varying vec3 P;
varying float below;
varying vec4 C;
varying vec2 rect_at;
void main() {
    if (below < 0.0) discard;
    if (abs(rect_at.x) > 1.0 || abs(rect_at.y) > 1.0) discard;     // past the floor's edge
    // the eye seen in the floor looks at the faces themselves
    vec3 f = normalize(floor_eye.xyz);
    vec3 v = gl_ProjectionMatrix[3][3] > 0.5 ? vec3(0.0, 0.0, 1.0) - 2.0 * f.z * f : 2.0 * floor_eye.w * f - P;
    v = normalize(v);
    vec3 n = normalize(N);
    if (dot(n, v) < 0.0) n = -n;
    vec3 colour = gl_LightModel.ambient.rgb * gl_FrontMaterial.ambient.rgb + gl_FrontMaterial.emission.rgb;
    for (int i = 0; i < 8; i++) {
        if (float(i) >= lights) break;
        vec4 lp = gl_LightSource[i].position;
        vec3 l = normalize(lp.w == 0.0 ? lp.xyz : lp.xyz - P);
        float d = max(dot(n, l), 0.0);
        vec3 h = normalize(l + v);
        float sp = pow(max(dot(n, h), 0.0), max(gl_FrontMaterial.shininess, 1.0));
        colour += gl_LightSource[i].ambient.rgb * gl_FrontMaterial.ambient.rgb
                + gl_LightSource[i].diffuse.rgb * C.rgb * d
                + gl_LightSource[i].specular.rgb * gl_FrontMaterial.specular.rgb * sp;
    }
    float fade = 1.0 - smoothstep(0.0, max(depth, 1e-6), below);
    gl_FragColor = vec4(clamp(colour, 0.0, 1.0), strength * fade);
}
"""


def _light_count():
    try:
        from . import realview
        return int(realview.light_count())
    except Exception as _fw_err:
        _fw_log("scenepm.py:lights", _fw_err)
        return 3


def _draw_style():
    try:
        from . import viewsettings
        return viewsettings.draw_style_index()
    except Exception:
        return None


def _is_kind(node, *names):
    from pivy import coin
    return any(node.isOfType(coin.SoType.fromName(n)) for n in names)


def _solid_face_sets(doc):
    """The face sets of the document's shapes, not its sketches' or other flat profiles' fills."""
    from pivy import coin
    owners = {}
    from . import realview
    # realview._roots: a linked part searched once, not through each of its links and containers
    # (300 links of one part: 5 s of the 15 the floor reflection took to turn on, vd123, 11-21)
    for obj, root in realview._roots(doc):
        flat = obj.isDerivedFrom("Part::Part2DObject") or obj.TypeId.startswith("Sketcher::")
        search = coin.SoSearchAction()
        search.setType(coin.SoType.fromName("SoBrepFaceSet"))
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(root)
        for path in search.getPaths():
            key = _address(path.getTail())
            owners[key] = owners.get(key, True) and not flat
    return {key for key, solid in owners.items() if solid}


def _face_paths(graph, doc=None):
    """Every face set of the shaded model under graph: (path nodes, the matrix to it)."""
    from pivy import coin
    keep = _solid_face_sets(doc) if doc is not None else None
    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoBrepFaceSet"))
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(False)          # only what is drawn: the switches' shown children
    search.apply(graph)
    out = []
    vp = coin.SbViewportRegion()
    for path in search.getPaths():
        if keep is not None and _address(path.getTail()) not in keep:
            continue
        nodes = [path.getNode(i) for i in range(path.getLength())]
        head = path.copy(0, path.getLength() - 1)
        get = coin.SoGetMatrixAction(vp)
        get.apply(head)
        rows = [[float(x) for x in row] for row in get.getMatrix().getValue()]   # copied: the action owns its matrix
        out.append((nodes, [path.getIndex(i) for i in range(path.getLength())], rows))
    return out


def _address(node):
    """The node itself (pivy makes a new Python wrapper each time it hands a node out)."""
    try:
        return int(node.this)
    except Exception:
        return id(node)


def _state_nodes(nodes, indices, memo=None):
    """The nodes that set up how the face set draws (its coordinates, normals, bindings, materials and
    hints), each where it stands, to be drawn again in the mirror; no transforms (the matrix has them),
    no lights, no shaders, nothing that draws. memo keeps what each parent's children were found to be:
    an assembly's group was walked again up to each component (300 links: 8 s of getChild, vd123, 11-21)."""
    out = []
    for depth in range(len(nodes) - 1):
        parent, child_at = nodes[depth], indices[depth + 1]
        if _is_kind(parent, "SoSwitch"):
            continue                   # a switch draws only its chosen child (the one on the path)
        if memo is None:
            out.extend(n for _i, n in _scan(parent, 0, child_at))
            continue
        key = _address(parent)
        upto, found = memo.get(key, (0, []))
        if child_at > upto:
            found = found + _scan(parent, upto, child_at)
            memo[key] = (child_at, found)
        out.extend(n for i, n in found if i < child_at)
    return out


def _scan(parent, start, stop):
    """(place, node) of the state nodes among parent's children start..stop-1."""
    found = []
    for i in range(start, stop):
        n = parent.getChild(i)
        if _is_kind(n, "SoSeparator", "SoShape", "SoTransformation", "SoLight", "SoCamera",
                    "SoShaderProgram", "SoCallback", "SoPolygonOffset", "SoPickStyle", "SoAnnotation"):
            continue
        if _is_kind(n, "SoGroup") and not _is_kind(n, "SoSwitch"):
            continue
        found.append((i, n))
    return found


def _unbounded():
    """A group whose content View Fit and the clipping planes leave out (the mirror is not the model)."""
    from pivy import coin
    try:
        group = coin.SoType.fromName("SoSkipBoundingGroup").createInstance()
        group.getField("mode").setValue(1)          # EXCLUDE_BBOX
        return group
    except Exception as _fw_err:
        _fw_log("scenepm.py:unbounded", _fw_err)
        return coin.SoGroup()


class _Reflection:
    def __init__(self, view, doc):
        from pivy import coin
        self.view, self.doc = view, doc
        self.doc_name = doc.Name
        self.root = view.getViewer().getSoRenderManager().getSceneGraph()
        self.switch = coin.SoSwitch()
        sep = coin.SoSeparator()
        sep.renderCaching = coin.SoSeparator.OFF
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        fade = coin.SoMaterial()
        fade.transparency = REFLECTION_FADE      # only this field is overridden: colours stay
        for field in (fade.ambientColor, fade.diffuseColor, fade.specularColor, fade.emissiveColor, fade.shininess):
            field.setIgnored(True)               # a default field would override too (Coin sends every set field)
        fade.setOverride(True)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.UNKNOWN_ORDERING    # the mirror turns faces inside out
        hints.setOverride(True)
        self.floor = coin.SoShaderParameter4f()
        self.floor.name.setValue("floor")
        view_matrix = coin.SoShaderStateMatrixParameter()     # Coin sends it as each frame draws
        view_matrix.name.setValue("view")
        view_matrix.matrixType = coin.SoShaderStateMatrixParameter.MODELVIEW
        self.params = {}
        prog = coin.SoShaderProgram()
        vs = coin.SoVertexShader()
        vs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        vs.sourceProgram.setValue(_REFLECT_VERT)
        vs.parameter.set1Value(0, self.floor)
        vs.parameter.set1Value(1, view_matrix)
        self.rect = []
        for k, name in enumerate(("rect_c", "rect_u", "rect_v")):
            par = coin.SoShaderParameter4f()
            par.name.setValue(name)
            par.value.setValue(0, 0, 0, 0)
            vs.parameter.set1Value(2 + k, par)
            self.rect.append(par)
        fs = coin.SoFragmentShader()
        fs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        fs.sourceProgram.setValue(_REFLECT_FRAG)
        for k, (name, value) in enumerate((("lights", _light_count()), ("strength", REFLECTION_STRENGTH),
                                           ("depth", 10.0))):
            par = coin.SoShaderParameter1f()
            par.name.setValue(name)
            par.value.setValue(float(value))
            fs.parameter.set1Value(k, par)
            self.params[name] = par
        prog.shaderObject.set1Value(0, vs)
        prog.shaderObject.set1Value(1, fs)
        self.models = coin.SoSeparator()
        for node in (pick, fade, hints, prog, self.models):
            sep.addChild(node)
        self.switch.addChild(sep)
        self.switch.whichChild = 0
        self.holder = _unbounded()
        self.holder.addChild(self.switch)
        self.root.addChild(self.holder)
        self.plane = None
        self.normal, self.distance = V(0, 0, 1), 0.0
        self.signature = None
        from . import scenestamp
        self.gate = scenestamp.Gate()     # the full walk only when the model, the view or the settings moved
        self.lights = []                  # the view's light nodes, found on each full walk
        self.timer = QtCore.QTimer()
        self.timer.setInterval(POLL_MS)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _lit(self):
        """How many lights are on, read from the light nodes found on the last full walk (as realview.light_count)."""
        try:
            head = next((node for name, node in self.lights if name == ""), None)
            n = 1 if head is None or head.on.getValue() else 0
            return n + sum(1 for name, node in self.lights if name in ("filllight", "backlight") and node.on.getValue())
        except Exception as _fw_err:
            _fw_log("scenepm.py:lit", _fw_err)
            return None

    def _find_lights(self):
        try:
            from . import displaymanager
            lights, _env = displaymanager._nodes()
            self.lights = list(lights.items())
        except Exception as _fw_err:
            _fw_log("scenepm.py:lights2", _fw_err)
            self.lights = []

    def _set(self, name, value):
        par = self.params[name]
        if abs(par.value.getValue() - value) > 1e-9:
            par.value.setValue(float(value))

    def _rebuild(self, n, d):
        """The mirrored copy: each shaded face set of the model, with the state it draws with, under
        the model's matrix times the mirror (no edges, no points, no overlays)."""
        from pivy import coin
        paths = _face_paths(self.view.getSceneGraph(), self.doc)
        mirror = mirror_matrix(n, d)
        signature, kept, seen = [(n.x, n.y, n.z, d)], [], set()
        for nodes, indices, rows in paths:
            # the same faces reached twice at the same place (a body shows its tip's node too) draw once
            key = (_address(nodes[-1]), tuple(round(v, 6) for row in rows for v in row))
            if key in seen:
                continue
            seen.add(key)
            kept.append((nodes, indices, rows))
            signature.append((tuple(_address(x) for x in nodes), key[1]))
        if signature == self.signature:
            return
        self.signature = signature
        self.models.removeAllChildren()
        memo = {}
        for nodes, indices, rows in kept:
            one = coin.SoSeparator()
            mt = coin.SoMatrixTransform()
            m = coin.SbMatrix(rows)
            m.multRight(mirror)
            mt.matrix = m
            one.addChild(mt)
            for node in _state_nodes(nodes, indices, memo):
                one.addChild(node)
            one.addChild(nodes[-1])
            self.models.addChild(one)

    def _alive(self):
        """The document and its view still there: after a close the scene's root and its nodes are freed, and
        touching them (removeChild, a light's on field) crashed FreeCAD."""
        try:
            if self.doc_name not in App.listDocuments():
                return False
            gdoc = Gui.getDocument(self.doc_name)
            return gdoc is not None and any(v is self.view or v == self.view for v in gdoc.mdiViewsOfType("Gui::View3DInventor"))
        except Exception:
            return False

    def refresh(self):
        if not self._alive():
            self.stop(remove=False)
            return
        try:
            values = settings()
            if not self.gate.due((tuple(sorted(values.items())), _draw_style())):
                if self.lights:
                    lit = self._lit()
                    if lit is not None:
                        self._set("lights", lit)
                return
            self._find_lights()
            n, d = floor_plane(self.doc, values)
            self.normal, self.distance = n, d
            if max(abs(a - b) for a, b in zip(self.floor.value.getValue().getValue(), (n.x, n.y, n.z, d))) > 1e-6:
                self.floor.value.setValue(n.x, n.y, n.z, d)
            self.plane = (round(n.x, 6), round(n.y, 6), round(n.z, 6), round(d, 6))
            self._rebuild(n, d)
            box = model_box(self.doc)
            height = 0.0
            if box is not None:
                height = max(abs(n.x) * box.XLength + abs(n.y) * box.YLength + abs(n.z) * box.ZLength, 1e-3)
            self._set("depth", REFLECTION_DEPTH * (height or 10.0))
            self._set("lights", _light_count())
            rect = floor_rect(self.doc, values)
            if rect is None:
                wanted = [(0, 0, 0, 0)] * 3
            else:
                c, u, w, hu, hw = rect
                wanted = [(c.x, c.y, c.z, 1.0), (u.x, u.y, u.z, hu), (w.x, w.y, w.z, hw)]
            for par, value in zip(self.rect, wanted):
                if max(abs(a - b) for a, b in zip(par.value.getValue().getValue(), value)) > 1e-9:
                    par.value.setValue(*value)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: floor reflection stopped: %s\n" % error)
            self.stop()

    def stop(self, remove=True):
        self.timer.stop()
        if remove and self._alive():
            try:
                self.root.removeChild(self.holder)
            except Exception as _fw_err:
                _fw_log("scenepm.py:238", _fw_err)
        _reflections.pop(id(self.view), None)


def reflections_on(view=None):
    view = view or _active_view()
    return view is not None and id(view) in _reflections


def set_reflections(on, view=None):
    view = view or _active_view()
    if view is None:
        return
    if on and id(view) not in _reflections:
        _reflections[id(view)] = _Reflection(view, Gui.ActiveDocument.Document)
    elif not on and id(view) in _reflections:
        _reflections[id(view)].stop()
    elif on:
        _reflections[id(view)].plane = None
        _reflections[id(view)].gate.reset()
        _reflections[id(view)].refresh()


def _active_view():
    gdoc = Gui.ActiveDocument
    view = gdoc.ActiveView if gdoc is not None else None
    return view if view is not None and hasattr(view, "getSceneGraph") else None


def shadows_on():
    try:
        from . import viewsettings
        return viewsettings.shadows_on()
    except Exception as _fw_err:
        _fw_log("scenepm.py:272", _fw_err)
        return False


def set_shadows(on):
    try:
        from . import viewsettings
        viewsettings.set_shadows(on)
        viewsettings._sync(viewsettings.SHADOW, on)
    except Exception:
        try:
            from . import viewsettings
            viewsettings.set_shadows(on)
        except Exception as _fw_err:
            _fw_log("scenepm.py:284", _fw_err)


def set_lock(on):
    try:
        from . import realview
        realview.set_locked(on)
    except Exception as _fw_err:
        _fw_log("scenepm.py:lock", _fw_err)


def apply(values=None):
    values = values or settings()
    apply_background(values)
    set_reflections(values["reflections"])
    set_lock(values.get("lock", True))
    try:            # Environment Rotation: RealView's studio
        from . import realview
        realview.sync_lock()
        for v in realview._views():
            v.redraw()
    except Exception as _fw_err:
        _fw_log("scenepm.py:envturn", _fw_err)


def scene_changed(scene=None):
    """A scene picked (Apply Scene, the Task Pane, Edit Scene): its floor reflects the model or not,
    as that scene keeps it."""
    try:
        if _active_view() is not None:
            set_reflections(scene_reflections(scene))
    except Exception as _fw_err:
        _fw_log("scenepm.py:scene", _fw_err)


# ------------------------------------------------------------------ the PropertyManager
class _ColourButton(QtWidgets.QPushButton):
    def __init__(self, value, changed):
        super().__init__()
        self.value = value
        self.changed = changed
        self.setFixedWidth(60)
        self.clicked.connect(self.pick)
        self._paint()

    def _paint(self):
        c = to_qcolor(self.value)
        self.setStyleSheet("background: %s; border: 1px solid #777;" % c.name())

    def pick(self):
        c = QtWidgets.QColorDialog.getColor(to_qcolor(self.value), self, "Color")
        if c.isValid():
            self.set(to_rgba(c))

    def set(self, value):
        self.value = value
        self._paint()
        self.changed()


class EditScenePanel:
    def __init__(self):
        from . import style
        self.before = settings()
        self.before_scene = style.current_scene()
        self.before_shadows = shadows_on()
        self.before_view = {k: App.ParamGet(VIEW).GetUnsigned(k, 0) for k in
                            ("BackgroundColor", "BackgroundColor2", "BackgroundColor3", "BackgroundColor4")}
        self.before_view.update({k: App.ParamGet(VIEW).GetBool(k, False) for k in
                                 ("Gradient", "RadialGradient", "UseBackgroundColorMid")})
        v = self.before
        w = QtWidgets.QWidget()
        w.setObjectName("SWEditScene")
        w.setWindowTitle("Edit Scene")
        outer = QtWidgets.QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("SWSceneTabs")
        outer.addWidget(self.tabs)
        basic = QtWidgets.QWidget()
        self.tabs.addTab(basic, "Basic")
        lay = QtWidgets.QVBoxLayout(basic)

        self.message = QtWidgets.QGroupBox("Message")
        self.message.setObjectName("SWSceneMessage")
        ml = QtWidgets.QVBoxLayout(self.message)
        note = QtWidgets.QLabel("Shadows in Shaded mode are currently off.")
        note.setWordWrap(True)
        ml.addWidget(note)
        lay.addWidget(self.message)

        env = QtWidgets.QGroupBox("Environment")
        el = QtWidgets.QVBoxLayout(env)
        self.scene = QtWidgets.QComboBox()
        self.scene.setObjectName("SWSceneEnvironment")
        for i in style.SCENE_MENU + style.SCENE_EXTRAS:
            self.scene.addItem(style.SCENES[i][0], i)
        self.scene.addItem("Theme Background", -1)
        self.scene.setCurrentIndex(max(0, self.scene.findData(self.before_scene)))
        self.scene.currentIndexChanged.connect(self._scene)
        el.addWidget(self.scene)

        bg = QtWidgets.QGroupBox("Background")
        bl = QtWidgets.QFormLayout(bg)
        self.background = QtWidgets.QComboBox()
        self.background.setObjectName("SWSceneBackground")
        self.background.addItems(BACKGROUNDS)
        self.background.setCurrentIndex(max(0, BACKGROUNDS.index(v["background"]) if v["background"] in BACKGROUNDS else 0))
        self.background.currentIndexChanged.connect(self.changed)
        bl.addRow(self.background)
        self.top = _ColourButton(v["top"], self.changed)
        self.top.setObjectName("SWSceneTop")
        self.bottom = _ColourButton(v["bottom"], self.changed)
        self.bottom.setObjectName("SWSceneBottom")
        self.top_label, self.bottom_label = QtWidgets.QLabel("Top gradient color"), QtWidgets.QLabel("Bottom gradient color")
        bl.addRow(self.top_label, self.top)
        bl.addRow(self.bottom_label, self.bottom)
        row = QtWidgets.QHBoxLayout()
        self.image = QtWidgets.QLineEdit(v["image"])
        self.image.setObjectName("SWSceneImage")
        self.image.editingFinished.connect(self.changed)
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.image)
        row.addWidget(browse)
        self.image_row = QtWidgets.QWidget()
        self.image_row.setLayout(row)
        bl.addRow(self.image_row)
        lay.addWidget(bg)
        lay.addWidget(env)

        fl = QtWidgets.QGroupBox("Floor")
        ff = QtWidgets.QFormLayout(fl)
        self.reflections = QtWidgets.QCheckBox("Floor reflections")
        self.reflections.setObjectName("SWSceneReflections")
        self.reflections.setChecked(v["reflections"] and reflections_on())
        self.reflections.toggled.connect(self.changed)
        self.shadows = QtWidgets.QCheckBox("Floor shadows")
        self.shadows.setObjectName("SWSceneShadows")
        self.shadows.setChecked(self.before_shadows)
        self.shadows.toggled.connect(self.changed)
        ff.addRow(self.reflections)
        ff.addRow(self.shadows)
        self.align = QtWidgets.QComboBox()
        self.align.setObjectName("SWSceneAlign")
        self.align.addItems(FLOORS)
        self.align.setCurrentIndex(FLOORS.index(v["align"]) if v["align"] in FLOORS else 0)
        self.align.currentIndexChanged.connect(self.changed)
        ff.addRow("Align floor with:", self.align)
        self.flip = QtWidgets.QCheckBox("Flip floor direction")
        self.flip.setObjectName("SWSceneFlip")
        self.flip.setChecked(v["flip"])
        self.flip.toggled.connect(self.changed)
        ff.addRow(self.flip)
        self.offset = QtWidgets.QDoubleSpinBox()
        self.offset.setObjectName("SWSceneOffset")
        self.offset.setRange(-1e5, 1e5)
        self.offset.setSuffix(" mm")
        self.offset.setValue(v["offset"])
        self.offset.valueChanged.connect(self.changed)
        ff.addRow("Floor offset:", self.offset)
        lay.addWidget(fl)
        lay.addStretch(1)
        self._advanced(v)
        self.form = w
        self._shown()

    def _advanced(self, v):
        ""
        adv = QtWidgets.QWidget()
        self.tabs.addTab(adv, "Advanced")
        lay = QtWidgets.QVBoxLayout(adv)
        fs = QtWidgets.QGroupBox("Floor Size/Rotation")
        fl = QtWidgets.QFormLayout(fs)
        self.aspect = QtWidgets.QCheckBox("Fixed aspect ratio")
        self.aspect.setObjectName("SWSceneAspect")
        self.aspect.setChecked(v["aspect"])
        self.aspect.toggled.connect(self._aspect_toggled)
        fl.addRow(self.aspect)
        self.autosize = QtWidgets.QCheckBox("Autosize floor")
        self.autosize.setObjectName("SWSceneAutoSize")
        self.autosize.setChecked(v["autosize"])
        self.autosize.toggled.connect(self._autosize_toggled)
        fl.addRow(self.autosize)
        width, depth = v["width"], v["depth"]
        if v["autosize"] or width <= 0 or depth <= 0:
            width, depth = self._auto_size()
        self.ratio = depth / width if width > 0 and depth > 0 else 1.0
        self.width = self._length("SWSceneWidth", width)
        self.depth = self._length("SWSceneDepth", depth)

        self.width.valueChanged.connect(lambda value: self._size_typed(self.width, value))
        self.depth.valueChanged.connect(lambda value: self._size_typed(self.depth, value))
        fl.addRow("Width", self.width)
        fl.addRow("Depth", self.depth)
        self.ratio_label = QtWidgets.QLabel()
        self.ratio_label.setObjectName("SWSceneAspectRatio")
        fl.addRow("Aspect ratio:", self.ratio_label)
        self._show_ratio()
        self.floor_turn = QtWidgets.QDoubleSpinBox()
        self.floor_turn.setObjectName("SWSceneFloorRotation")
        self.floor_turn.setRange(-360.0, 360.0)
        self.floor_turn.setDecimals(2)
        self.floor_turn.setSuffix(" deg")
        self.floor_turn.setValue(v["floor_turn"])
        self.floor_turn.valueChanged.connect(self.changed)
        fl.addRow("Rotation", self.floor_turn)
        lay.addWidget(fs)
        er = QtWidgets.QGroupBox("Environment Rotation")
        el = QtWidgets.QHBoxLayout(er)
        self.env_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.env_slider.setObjectName("SWSceneEnvSlider")
        self.env_slider.setRange(0, 360)
        self.env_turn = QtWidgets.QDoubleSpinBox()
        self.env_turn.setObjectName("SWSceneEnvRotation")
        self.env_turn.setRange(0.0, 360.0)
        self.env_turn.setDecimals(2)
        self.env_turn.setSuffix(" deg")
        self.env_turn.setSingleStep(3.6)
        self.env_turn.setValue(v["env_turn"] % 360.0)
        self.env_slider.setValue(int(round(v["env_turn"])) % 361)
        self.env_slider.valueChanged.connect(lambda value: self.env_turn.setValue(float(value)))
        self.env_turn.valueChanged.connect(self._env_typed)
        self.env_turn.setToolTip("Turns the studio RealView Graphics reflects about the floor's up direction")
        el.addWidget(self.env_slider, 1)
        el.addWidget(self.env_turn)
        lay.addWidget(er)
        lay.addStretch(1)

    def _length(self, name, value):
        box = QtWidgets.QDoubleSpinBox()
        box.setObjectName(name)
        box.setRange(0.01, 1e6)
        box.setDecimals(2)
        box.setSuffix(" mm")
        box.setValue(value if value > 0 else 100.0)
        return box

    def _auto_size(self):
        try:
            gdoc = Gui.ActiveDocument
            w, d = auto_floor_size(gdoc.Document if gdoc is not None else None, self.before)
        except Exception as _fw_err:
            _fw_log("scenepm.py:autosize", _fw_err)
            w, d = 0.0, 0.0
        return (w, d) if w > 0 and d > 0 else (300.0, 300.0)

    def _show_ratio(self):
        w, d = self.width.value(), self.depth.value()
        self.ratio_label.setText("%.2f : 1" % (w / d) if d > 0 else "")

    def _set_quiet(self, box, value):
        box.blockSignals(True)
        box.setValue(value)
        box.blockSignals(False)

    def _size_typed(self, box, value):
        if self.aspect.isChecked():
            other = self.depth if box is self.width else self.width
            self._set_quiet(other, value * self.ratio if box is self.width else value / self.ratio)
        else:
            self.ratio = self.depth.value() / max(self.width.value(), 1e-6)
        if self.autosize.isChecked():
            self.autosize.blockSignals(True)
            self.autosize.setChecked(False)
            self.autosize.blockSignals(False)
        self._show_ratio()
        self.changed()

    def _aspect_toggled(self, on):
        self.ratio = self.depth.value() / max(self.width.value(), 1e-6)
        self.changed()

    def _autosize_toggled(self, on):
        if on:
            w, d = self._auto_size()
            self._set_quiet(self.width, w)
            self._set_quiet(self.depth, d)
            self.ratio = d / max(w, 1e-6)
            self._show_ratio()
        self.changed()

    def _env_typed(self, value):
        self.env_slider.blockSignals(True)
        self.env_slider.setValue(int(round(value)))
        self.env_slider.blockSignals(False)
        self.changed()

    def values(self):
        out = {"background": self.background.currentText(), "top": self.top.value, "bottom": self.bottom.value,
               "image": self.image.text().strip(), "reflections": self.reflections.isChecked(),
               "lock": True,
               "align": self.align.currentText(), "flip": self.flip.isChecked(), "offset": self.offset.value()}
        if hasattr(self, "env_turn"):
            out.update({"autosize": self.autosize.isChecked(), "aspect": self.aspect.isChecked(),
                        "width": self.width.value(), "depth": self.depth.value(),
                        "floor_turn": self.floor_turn.value(), "env_turn": self.env_turn.value()})
        return out

    def _shown(self):
        try:
            self.message.setVisible(not self.shadows.isChecked())
        except Exception as _fw_err:
            _fw_log("scenepm.py:message", _fw_err)
        kind = self.background.currentText()
        self.top.setVisible(kind in ("Color", "Gradient"))
        self.top_label.setVisible(kind in ("Color", "Gradient"))
        self.top_label.setText("Color" if kind == "Color" else "Top gradient color")
        self.bottom.setVisible(kind == "Gradient")
        self.bottom_label.setVisible(kind == "Gradient")
        self.image_row.setVisible(kind == "Image")

    def _scene(self):
        from . import style
        style.apply_scene(self.scene.currentData())
        self.reflections.blockSignals(True)          # the new scene's own Floor reflections choice
        self.reflections.setChecked(scene_reflections())
        self.reflections.blockSignals(False)
        if self.background.currentText() != "Use Environment":
            self.background.setCurrentIndex(0)
        else:
            self.changed()

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self.form, "Background image", "",
                                                        "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.image.setText(path)
            self.changed()

    def changed(self, *args):
        self._shown()
        values = self.values()
        store(values)
        apply(values)
        if self.shadows.isChecked() != shadows_on():
            set_shadows(self.shadows.isChecked())

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        self.changed()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        from . import style
        if self.before_scene != style.current_scene():
            style.apply_scene(self.before_scene)
        store(self.before)          # after the scene: its own Floor reflections choice goes back
        v = App.ParamGet(VIEW)
        for k, val in self.before_view.items():
            if isinstance(val, bool):
                v.SetBool(k, val)
            else:
                v.SetUnsigned(k, val)
        set_reflections(self.before["reflections"])
        set_lock(self.before["lock"])
        if shadows_on() != self.before_shadows:
            set_shadows(self.before_shadows)
        Gui.Control.closeDialog()
        return True


LAST = [None]


def edit_scene():
    if Gui.Control.activeDialog():
        return None
    panel = EditScenePanel()
    LAST[0] = panel
    Gui.Control.showDialog(panel)
    return panel


class _Command:
    def GetResources(self):
        return {"MenuText": "Edit Scene...", "ToolTip": "Background, floor reflections and shadows, floor position",
                "CmdType": "ForEdit"}

    def IsActive(self):
        return Gui.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        edit_scene()


COMMAND = "SWStyle_EditScene"


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, _Command())
    try:
        params().SetBool("LockEnvironment", True)
    except Exception as _fw_err:
        _fw_log("scenepm.py:lockon", _fw_err)
    QtCore.QTimer.singleShot(3000, _restore)


def _restore():
    """After FreeCAD starts: a kept background other than the scene's own, and the reflections."""
    try:
        values = settings()
        if values["background"] != "Use Environment":
            apply_background(values)
    except Exception as error:
        App.Console.PrintLog("FreeCAD scene: %s\n" % error)
