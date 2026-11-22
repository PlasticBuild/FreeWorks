# SPDX-License-Identifier: LGPL-2.1-or-later
""




















_FW_SEEN = set()


def _fw_log(site, err):
    """Log a swallowed error once per place (Log level: invisible in the Report view at normal level)."""
    try:
        if site not in _FW_SEEN:
            _FW_SEEN.add(site)
            __import__("FreeCAD").Console.PrintLog("FreeWorks %s: %s\n" % (site, err))
    except Exception:
        return


import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from . import paths

PARAM = "RealView"
NODE = "SWRealViewShader"
ENV_NODE = "SWRealViewEnv"      # the photo environment's texture (unit 1), just ahead of the shader
ENV_UNIT = 1
# Apply Scene's photo scenes -> the environment they reflect (resources/environments/<name>.jpg)
SCENE_ENVIRONMENTS = {
    "Rooftop": "potsdamer_platz",
    "Courtyard Background": "venice_sunset",
    "Urban 5 Background": "potsdamer_platz",
    "Urban 5 Image 6": "potsdamer_platz",
    "Retail Store": "st_fagans_interior",
    "Villa Interior": "lebombo",
    "Warehouse": "empty_warehouse_01",
    "Factory Background": "empty_warehouse_01",
    "Modern Garage": "empty_warehouse_01",
    "Fall Street": "venice_sunset",
    "Landscape 2 Image 4": "rooitou_park",
}
GLOSS = 60.0            # specular exponent: a tight highlight, as RealView's plastic
SPECULAR = 0.22         # strength of the lights' highlights
REFLECT = 0.70          # strength of the studio reflection at a grazing angle
REFLECT_FACING = 0.30   # ... and where the face looks straight at the viewer
EYE = 0.6               # the reflection's eye, in view heights in front of an orthographic view

# stays with the model as the view turns, so a reflection stays put on the part. The model's up (Z) and X,
# as the camera sees them, go to the shader as two uniforms, set by a sensor on each view's camera when it
# turns (outside drawing: no OpenGL calls from Python while Coin draws, which faulted on Intel graphics
# with a sketch open, Reviewer 11-20). FW_NO_FRAMECB=1 (or NOFRAMECB=1) leaves the sensor out: the studio
# then turns with the camera.
FRAME_TAG = "SWStudioFrame"     # the old per-frame callback's name: taken out of views that still have it
VIEW = "User parameter:BaseApp/Preferences/View"
LIGHT_KEYS = ("EnableHeadlight", "EnableFillLight", "EnableBacklight")

_VERT = """
varying vec3 N;
varying vec3 P;
varying vec4 C;
void main() {
    N = gl_NormalMatrix * gl_Normal;
    P = (gl_ModelViewMatrix * gl_Vertex).xyz;
    C = gl_Color;
    gl_Position = ftransform();
}
"""

# The lights are FreeCAD's own (gl_LightSource 0..lights-1, as the fixed pipeline lights them), so a
# flat face keeps the tone it has without RealView; what RealView adds is the per-pixel gloss and the
# studio reflected in the faces: the scene's sky above, a darker floor below a soft horizon, seen from
# an eye just in front of the view, so a flat face in an orthographic view gets a gentle gradient.
#
# The appearance decides how the face takes the studio, from the material FreeCAD already sends

#   specular amount  (luminance of the specular colour): matte 0.1 (the look's default) up to 1
#   specular spread  (shininess): how tight the highlight is and how sharp the reflection
#   reflection amount (ambient against diffuse colour, 0.3 + 0.4 x reflection): from about 0.45
#                    the face is a metal: it reflects the studio in its own colour
#   transparency     glass: clear where it faces you, more mirror-like at a grazing angle
# The default matte part looks as with pkg10; rubber is duller, glossy plastic shinier, chrome a mirror.
#
# Shadows In Shaded Mode draws the same nodes flat and see-through in SHADOW_RGBA (viewsettings): a
# fragment in exactly that colour is left as it is.
_FRAG = """
varying vec3 N;
varying vec3 P;
varying vec4 C;
uniform float lights;
uniform float gloss;
uniform float specular;
uniform float reflect_max;
uniform float reflect_min;
uniform float eye;
uniform vec3 sky_top;
uniform vec3 sky_low;
uniform vec3 ground;
uniform vec4 shadow_rgba;
uniform float locked;
uniform float env_turn;      // Edit Scene > Advanced > Environment Rotation (radians, about the up axis)
uniform vec3 lock_up;        // the model's Z as the camera sees it (0 when not handed over)
uniform vec3 lock_ax;        // the model's X as the camera sees it
uniform sampler2D env_map;   // a photo scene's environment (equirectangular), texture unit 1
uniform float env_on;        // 1 when the scene has a photo environment

// the photo environment in direction r (studio axes). The texture holds the photo twice: sharp in its
// upper half, blurred in its lower half; sharp (0..1) mixes them (a dull finish sees the blurred one).
// No mipmaps (environment_node): the photo's left and right edges meet behind the model, and a mipmap
// drew that seam as a dotted line across a mirror.
vec3 photo(vec3 r, float sharp) {
    float u = 0.5 + atan(r.x, r.z) / 6.2831853;
    float v = clamp(0.5 + asin(clamp(r.y, -1.0, 1.0)) / 3.1415927, 0.004, 0.996);
    vec3 a = texture2D(env_map, vec2(u, 0.5 + 0.5 * v)).rgb;
    vec3 b = texture2D(env_map, vec2(u, 0.5 * v)).rgb;
    return mix(b, a, sharp);
}

// a direction seen by the camera, in the studio's own axes (x right, y up, z toward the viewer of
// the Front view): the camera's axes, or with Lock environment to model the model's
vec3 to_studio(vec3 r) {
    if (locked < 0.5) return r;
    vec3 up = lock_up;
    vec3 ax = lock_ax;
    if (dot(up, up) < 0.25) return r;
    up = normalize(up);
    ax = ax - dot(ax, up) * up;
    if (dot(ax, ax) < 0.25) return r;           // not handed over this frame: the camera's axes
    ax = normalize(ax);
    vec3 ay = cross(up, ax);
    return vec3(dot(r, ax), dot(r, up), -dot(r, ay));
}

vec3 studio(vec3 r) {
    vec3 sky = mix(sky_low, sky_top, smoothstep(0.05, 0.85, r.y));
    vec3 floor_ = mix(ground * 0.75, ground, smoothstep(-0.9, -0.1, r.y));
    // a tall soft box up and to the right: the bright streak down a cylinder, the glint on a ball
    float box = exp(-pow((r.x - 0.45) / 0.14, 2.0)) * smoothstep(-0.3, 0.2, r.y);
    return min(mix(floor_, sky, smoothstep(-0.08, 0.08, r.y)) + vec3(0.55) * box, vec3(1.0));
}

// the studio as a mirror sees it (chrome, polished steel): RealView's studio is not an even sky but
// tall light panels round the model with dark gaps between them, a dark band at the horizon and a
// bright panel overhead, so a polished rim shows sharp light and dark streaks, not a flat grey
vec3 studio_sharp(vec3 r) {
    vec3 c = studio(r);
    float az = atan(r.x, r.z);                  // 0 toward the viewer of the Front view
    // the panels stand on the floor: seen below the horizon they are dimmer (their lower part)
    float tall = mix(0.55, 1.0, smoothstep(-0.2, 0.05, r.y)) * smoothstep(-0.97, -0.88, r.y)
               * (1.0 - smoothstep(0.7, 0.92, r.y));
    float panels = exp(-pow((az - 1.05) / 0.16, 2.0)) + exp(-pow((az + 1.25) / 0.12, 2.0))
                 + 0.85 * exp(-pow((abs(az) - 2.55) / 0.2, 2.0));
    // (the dark gaps and the dark band are round the sides and behind the viewer's back: a face looking
    // straight at the viewer keeps the plain studio it had)
    float away = 1.0 - smoothstep(0.55, 0.85, r.z);
    float gaps = 1.0 - 0.45 * (1.0 - smoothstep(0.0, 0.35, panels)) * tall * away;
    float horizon = 1.0 - 0.6 * exp(-pow((r.y + 0.03) / 0.045, 2.0)) * away;
    float overhead = smoothstep(0.86, 0.96, r.y);
    return clamp(c * gaps * horizon + vec3(0.75) * min(panels, 1.0) * tall + vec3(0.35) * overhead, 0.0, 1.0);
}

void main() {
    if (abs(C.a - shadow_rgba.a) < 0.004 && all(lessThan(abs(C.rgb - shadow_rgba.rgb), vec3(0.004)))) {
        gl_FragColor = C;           // the shadow's flat pass
        return;
    }
    vec3 n = normalize(N);
    if (!gl_FrontFacing) n = -n;
    bool ortho = gl_ProjectionMatrix[3][3] > 0.5;
    vec3 v = ortho ? vec3(0.0, 0.0, 1.0) : normalize(-P);
    vec3 rv = v;
    if (ortho) {
        float h = 2.0 / gl_ProjectionMatrix[1][1];
        rv = normalize(vec3(-P.xy, eye * h));
    }
    vec3 base = C.rgb;
    float spec = clamp(dot(gl_FrontMaterial.specular.rgb, vec3(0.3333)), 0.0, 1.0);
    float shine = clamp(gl_FrontMaterial.shininess / 128.0, 0.0, 1.0);
    float glass = clamp((1.0 - C.a) * 1.25, 0.0, 1.0);
    float ratio = dot(gl_FrontMaterial.ambient.rgb, vec3(1.0)) / max(dot(base, vec3(1.0)), 0.03);
    float metal = smoothstep(0.45, 0.62, ratio) * smoothstep(0.25, 0.5, spec) * (1.0 - glass);
    float expo = mix(gloss, 400.0, smoothstep(0.2, 1.0, shine));
    float spec_k = specular * clamp(pow(spec / 0.1, 0.7), 0.25, 4.0);
    vec3 colour = gl_LightModel.ambient.rgb * gl_FrontMaterial.ambient.rgb * (1.0 - metal);
    vec3 shine_rgb = vec3(0.0);
    for (int i = 0; i < 3; ++i) {
        if (float(i) >= lights) break;
        vec4 lp = gl_LightSource[i].position;
        vec3 l = normalize(lp.w == 0.0 ? lp.xyz : lp.xyz - P);
        float d = max(dot(n, l), 0.0);
        vec3 h2 = normalize(l + v);
        float sp = d > 0.0 ? pow(max(dot(n, h2), 0.0), expo) : 0.0;
        colour += (gl_LightSource[i].ambient.rgb * gl_FrontMaterial.ambient.rgb
                + gl_LightSource[i].diffuse.rgb * base * d) * (1.0 - 0.75 * metal);
        shine_rgb += gl_LightSource[i].specular.rgb * sp;    // Specularity (lightterms.py; Coin: = diffuse)
    }
    float facing = max(dot(n, rv), 0.0);
    float fres = pow(1.0 - facing, 3.0);
    // the look's own matte grey (specular 0.1) as pkg10; a glossier dielectric only a little more,
    // so a coloured plastic keeps its colour facing the sky
    float strength = spec <= 0.1 ? clamp(0.35 + 6.5 * spec, 0.3, 1.0) : 0.8 + 0.4 * (spec - 0.1);
    float k = mix(reflect_min, reflect_max, fres) * strength;
    k = clamp(mix(k, 0.6 + 0.3 * fres, metal), 0.0, 0.95);
    // a polished metal (chrome, polished steel) is nearly a mirror, as in SolidWorks: its up faces
    // show the bright sky, its sides the darker floor, with little of its own shading left
    k = mix(k, max(k, 0.9 + 0.05 * fres), metal * smoothstep(0.6, 0.95, shine));
    vec3 r = to_studio(reflect(-rv, n));
    r = vec3(cos(env_turn) * r.x + sin(env_turn) * r.z, r.y, cos(env_turn) * r.z - sin(env_turn) * r.x);
    // a blurry (low-shine) finish sees the studio softened toward its middle tone
    vec3 env;
    if (env_on > 0.5) {
        // a photo scene: the place itself, blurred for a dull finish, sharp in a polished metal
        env = photo(r, smoothstep(0.15, 0.85, shine));
        env = mix(env, photo(r, 1.0), metal * smoothstep(0.6, 0.95, shine));
    } else {
        env = mix(mix(studio(vec3(0.0, 0.3, 0.95)), studio(r), 0.35), studio(r), smoothstep(0.15, 0.85, shine));
        env = mix(env, studio_sharp(r), metal * smoothstep(0.6, 0.95, shine));
    }
    env = mix(env, sky_low, 0.25 * metal);      // a metal never goes black where it sees the floor
    vec3 tint = mix(mix(vec3(1.0), base * 1.4, 0.65), base * 1.25 + 0.05, metal);
    k = mix(k, max(k, 0.45 + 0.5 * fres), glass);
    colour = mix(colour, env * tint, k);
    colour += shine_rgb * spec_k * mix(vec3(1.0), base + 0.2, metal);
    float alpha = mix(C.a, 1.0, glass * fres * 0.7);
    // FreeCAD's picked / hovered colour is the emissive colour: added as FreeCAD adds it
    colour += gl_FrontMaterial.emission.rgb;
    gl_FragColor = vec4(clamp(colour, 0.0, 1.0), alpha);
}
"""

_program = [None]
_lights = [None]        # the shader's light count uniform
_scene = {}             # the shader's studio colour uniforms
_lock = [None]          # the shader's Lock environment to model uniform
_turn = [None]          # the shader's Environment Rotation uniform
_axes = {}              # the shader's lock_up / lock_ax uniforms
_sensors = {}           # id(view) -> (camera node, its SoFieldSensor)
_done = {}              # document name -> signature it was last done for
_timer = [None]
_observer = [None]
stats = {"inserted": 0, "removed": 0, "skipped_textured": 0}     # for checks


def enabled():
    return paths.params().GetBool(PARAM, False)


def set_enabled(on):
    paths.params().SetBool(PARAM, bool(on))
    refresh()


def light_count():
    """How many of FreeCAD's three lights are on: the GL lights the shader reads, in order."""
    try:
        from . import displaymanager
        lights, env = displaymanager._nodes()      # the active view's own light nodes, as drawn
        if lights:
            head = lights.get("")
            n = 1 if head is None or head.on.getValue() else 0
            return n + sum(1 for k in ("filllight", "backlight") if k in lights and lights[k].on.getValue())
    except Exception as _fw_err:
        _fw_log("realview.py:lights", _fw_err)
    p = App.ParamGet(VIEW)
    return sum(1 for k in LIGHT_KEYS if p.GetBool(k, k != "EnableBacklight"))


def sync_lights():
    if _lights[0] is not None:
        n = float(light_count())
        if _lights[0].value.getValue() != n:
            _lights[0].value.setValue(n)


def _rgb(packed):
    return (((packed >> 24) & 255) / 255.0, ((packed >> 16) & 255) / 255.0, ((packed >> 8) & 255) / 255.0)


def _scene_studio():
    ""



    from . import style
    i = style.current_scene()
    _name, (top, mid, bottom), gradient = style.SCENES[i if i >= 0 else 0]
    return gradient, top, mid, bottom


def studio_colours():
    """(sky top, sky at the horizon, floor) from the scene's environment (_scene_studio): the studio
    the faces reflect is the scene the model sits in."""
    try:
        gradient, top, mid, bottom = _scene_studio()
        top, mid, bottom = _rgb(top), _rgb(mid), _rgb(bottom)
        if not gradient:
            mid = bottom = top
    except Exception as _fw_err:
        _fw_log("realview.py:scene", _fw_err)
        p = App.ParamGet(VIEW)
        top = _rgb(p.GetUnsigned("BackgroundColor2", 0xEBEDF3FF))
        bottom = _rgb(p.GetUnsigned("BackgroundColor3", 0xFEFEFEFF))
        gradient = p.GetBool("Gradient", True) or p.GetBool("RadialGradient", False)
        if not gradient:
            top = bottom = _rgb(p.GetUnsigned("BackgroundColor", 0xFFFFFFFF))
        mid = _rgb(p.GetUnsigned("BackgroundColor4", 0xDADEE9FF)) if p.GetBool("UseBackgroundColorMid", False) else \
            tuple((a + b) / 2.0 for a, b in zip(top, bottom))
    light = lambda c: max(c)
    # the sky is the scene's lightest band, the floor a darker shade of it: a white scene still
    # has a grey floor in the faces (RealView's studio floor), a dark scene a near-black one
    sky_top = max((top, mid, bottom), key=light)
    sky_low = tuple(0.5 * a + 0.5 * b for a, b in zip(sky_top, min((top, mid, bottom), key=light)))
    ground = tuple(c * 0.45 for c in min((top, mid, bottom), key=light))
    return (tuple(min(1.0, c * 1.02) for c in sky_top), sky_low, ground)


def shadow_rgba():
    try:
        from . import viewsettings
        r, g, b = viewsettings.SHADOW_COLOUR
        return (r, g, b, 1.0 - viewsettings.SHADOW_TRANSPARENCY)
    except Exception:
        return (-1.0, -1.0, -1.0, -1.0)


def sync_scene():
    if _scene:
        for name, value in zip(("sky_top", "sky_low", "ground"), studio_colours()):
            par = _scene.get(name)
            if par is not None:
                par.value.setValue(*value)
    sync_environment()


def environment_file():
    """The picked scene's photo environment (a file in resources/environments), or None for a studio scene."""
    try:
        from . import style
        i = style.current_scene()
        if i < 0:
            return None
        name = SCENE_ENVIRONMENTS.get(style.SCENES[i][0])
    except Exception as _fw_err:
        _fw_log("realview.py:env-scene", _fw_err)
        return None
    if not name:
        return None
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "environments", name + ".jpg")
    return path if os.path.isfile(path) else None


_env = {"node": None, "file": "", "on": None}


def _load_texture(tex, path):
    """The picture into the texture node, read with Qt (Coin's own image readers vary by build)."""
    from PySide import QtGui
    from pivy import coin
    if not path:
        tex.image.setValue(coin.SbVec2s(0, 0), 0, b"")
        return False
    image = QtGui.QImage(path)
    if image.isNull():
        tex.image.setValue(coin.SbVec2s(0, 0), 0, b"")
        return False
    image = image.convertToFormat(QtGui.QImage.Format_RGB888)
    w, h = image.width(), image.height()
    # the photo sharp above and blurred below (the shader's photo()): the blur is a small copy scaled up
    small = image.scaled(max(8, w // 24), max(4, h // 24), QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    blurred = small.scaled(w, h, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation)
    both = QtGui.QImage(w, 2 * h, QtGui.QImage.Format_RGB888)
    painter = QtGui.QPainter(both)
    painter.drawImage(0, 0, image)
    painter.drawImage(0, h, blurred)
    painter.end()
    image = both.mirrored(False, True)          # Coin: bottom row first
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    raw = bytes(image.constBits())[:stride * h]
    data = b"".join(raw[y * stride:y * stride + 3 * w] for y in range(h))
    tex.image.setValue(coin.SbVec2s(w, h), 3, data)
    _env["size"] = (w, h)
    return True


def environment_node():
    """The texture group that goes ahead of the shader in every part (one, shared)."""
    if _env["node"] is None:
        from pivy import coin
        group = coin.SoGroup()
        group.setName(ENV_NODE)
        unit = coin.SoTextureUnit()
        unit.unit = ENV_UNIT
        group.addChild(unit)
        tex = coin.SoTexture2()
        tex.wrapS = coin.SoTexture2.REPEAT
        tex.wrapT = coin.SoTexture2.CLAMP
        tex.model = coin.SoTexture2.REPLACE
        # no mipmaps (Coin uses them from texture quality 0.5): see the shader's photo()
        quality = coin.SoComplexity()
        quality.value.setIgnored(True)
        quality.type.setIgnored(True)
        quality.textureQuality = 0.3
        group.addChild(quality)
        group.addChild(tex)
        back = coin.SoTextureUnit()
        back.unit = 0
        group.addChild(back)
        group.ref()
        _env["node"] = group
        sync_environment()
    return _env["node"]


def sync_environment():
    """The picked scene's photo (or none) into the shared texture and the shader's env_on."""
    if _env["node"] is None:
        return
    path = environment_file() or ""
    if path != _env["file"]:
        try:
            ok = _load_texture(_env["node"].getChild(2), path)
        except Exception as _fw_err:
            _fw_log("realview.py:env-load", _fw_err)
            ok = False
        _env["file"] = path
        _env["on"] = ok
    par = _scene.get("env_on")
    if par is not None:
        par.value.setValue(1.0 if _env["on"] else 0.0)


def program():
    """The one shader program every part shares."""
    if _program[0] is None:
        from pivy import coin
        prog = coin.SoShaderProgram()
        prog.setName(NODE)
        vs = coin.SoVertexShader()
        vs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        vs.sourceProgram.setValue(_VERT)
        fs = coin.SoFragmentShader()
        fs.sourceType = coin.SoShaderObject.GLSL_PROGRAM
        fs.sourceProgram.setValue(_FRAG)
        k = 0
        for name, value in (("lights", light_count()), ("gloss", GLOSS), ("specular", SPECULAR),
                            ("reflect_max", REFLECT), ("reflect_min", REFLECT_FACING), ("eye", EYE)):
            par = coin.SoShaderParameter1f()
            par.name.setValue(name)
            par.value.setValue(float(value))
            fs.parameter.set1Value(k, par)
            k += 1
            if name == "lights":
                _lights[0] = par
        for name, value in zip(("sky_top", "sky_low", "ground"), studio_colours()):
            par = coin.SoShaderParameter3f()
            par.name.setValue(name)
            par.value.setValue(*value)
            fs.parameter.set1Value(k, par)
            k += 1
            _scene[name] = par
        par = coin.SoShaderParameter4f()
        par.name.setValue("shadow_rgba")
        par.value.setValue(*shadow_rgba())
        fs.parameter.set1Value(k, par)
        par = coin.SoShaderParameter1f()
        par.name.setValue("locked")
        par.value.setValue(1.0 if locked() else 0.0)
        fs.parameter.set1Value(k + 1, par)
        _lock[0] = par
        par = coin.SoShaderParameter1f()
        par.name.setValue("env_turn")
        par.value.setValue(env_turn())
        fs.parameter.set1Value(k + 2, par)
        _turn[0] = par
        for j, name in enumerate(("lock_up", "lock_ax")):
            par = coin.SoShaderParameter3f()
            par.name.setValue(name)
            par.value.setValue(0.0, 0.0, 0.0)
            fs.parameter.set1Value(k + 3 + j, par)
            _axes[name] = par
        par = coin.SoShaderParameter1i()
        par.name.setValue("env_map")
        par.value.setValue(ENV_UNIT)
        fs.parameter.set1Value(k + 5, par)
        par = coin.SoShaderParameter1f()
        par.name.setValue("env_on")
        par.value.setValue(0.0)
        fs.parameter.set1Value(k + 6, par)
        _scene["env_on"] = par
        prog.shaderObject.set1Value(0, vs)
        prog.shaderObject.set1Value(1, fs)
        _program[0] = prog
    return _program[0]


def locked():
    """Edit Scene's Lock environment to model (on unless turned off)."""
    return App.ParamGet(paths.PARAM_PATH + "/Scene").GetBool("LockEnvironment", True)


def set_locked(on):
    App.ParamGet(paths.PARAM_PATH + "/Scene").SetBool("LockEnvironment", bool(on))
    sync_lock()
    for v in _views():
        try:
            v.redraw()
        except Exception as _fw_err:
            _fw_log("realview.py:lockredraw", _fw_err)


def env_turn():
    ""
    import math
    return math.radians(App.ParamGet(paths.PARAM_PATH + "/Scene").GetFloat("EnvironmentRotation", 0.0))


def sync_lock():
    if _lock[0] is not None:
        value = 1.0 if locked() else 0.0
        if _lock[0].value.getValue() != value:
            _lock[0].value.setValue(value)
    if _turn[0] is not None:
        value = env_turn()
        if abs(_turn[0].value.getValue() - value) > 1e-6:
            _turn[0].value.setValue(value)


def frame_callbacks_off():
    import os
    return bool(os.environ.get("FW_NO_FRAMECB") or os.environ.get("NOFRAMECB"))


def _hand_over_axes(camera):
    """The model's Z and X as this camera sees them, into the shader (from a sensor, never while drawing)."""
    try:
        from pivy import coin
        if not _axes:
            return
        inv = camera.orientation.getValue().inverse()
        up = inv.multVec(coin.SbVec3f(0.0, 0.0, 1.0)).getValue()
        ax = inv.multVec(coin.SbVec3f(1.0, 0.0, 0.0)).getValue()
        for name, value in (("lock_up", up), ("lock_ax", ax)):
            par = _axes[name]
            old = par.value.getValue().getValue()
            if max(abs(old[i] - value[i]) for i in range(3)) > 1e-6:
                par.value.setValue(*value)
    except Exception as _fw_err:
        _fw_log("realview.py:axes", _fw_err)


def _drop_old_callback(root):
    for i in reversed(range(root.getNumChildren())):
        if root.getChild(i).getName().getString() == FRAME_TAG:
            root.removeChild(i)


def attach_frame(view):
    """A sensor on the view's camera (again when the view gets a new camera, e.g. Perspective)."""
    from pivy import coin
    try:
        _drop_old_callback(view.getViewer().getSoRenderManager().getSceneGraph())
    except Exception as _fw_err:
        _fw_log("realview.py:dropcb", _fw_err)
    if frame_callbacks_off():
        return False
    camera = view.getCameraNode()
    if camera is None:
        return False
    key = id(view)
    held = _sensors.get(key)
    if held is not None and held[0] == camera:
        return False
    if held is not None:
        try:
            held[1].detach()
        except Exception:
            pass
    sensor = coin.SoFieldSensor(lambda _data, _sensor, cam=camera: _hand_over_axes(cam), None)
    sensor.setPriority(0)        # at once, as the camera turns: before the redraw it asks for
    sensor.attach(camera.orientation)
    _sensors[key] = (camera, sensor)
    _hand_over_axes(camera)
    return True


def view_activated(view):
    """Another 3D view in front: its camera's axes (the uniforms are shared by every view)."""
    try:
        camera = view.getCameraNode()
        if camera is not None and not frame_callbacks_off():
            _hand_over_axes(camera)
    except Exception as _fw_err:
        _fw_log("realview.py:activated", _fw_err)


def _search(root, type_name=None, name=None):
    from pivy import coin
    sa = coin.SoSearchAction()
    if type_name:
        kind = coin.SoType.fromName(type_name)
        if kind.isBad():
            return []           # a type Coin doesn't know would match every node
        sa.setType(kind)
    if name:
        sa.setName(coin.SbName(name))
    sa.setInterest(coin.SoSearchAction.ALL)
    sa.setSearchingAll(True)        # through switches too: a mode not shown now gets it as well
    sa.apply(root)
    paths_ = sa.getPaths()
    out = []
    for i in range(paths_.getLength()):        # the paths go with the action: keep the nodes
        path = paths_.get(i)
        if path.getLength() >= 2:
            out.append((path.getTail(), path.getNodeFromTail(1)))
    return out


def coin_type(name):
    from pivy import coin
    return coin.SoType.fromName(name)


def _textured(root):
    """An image on the part (FreeCAD keeps an empty texture node in every part: that one doesn't count)."""
    for tex, parent in _search(root, "Texture2"):
        try:
            if parent.getName().getString() == ENV_NODE:
                continue        # RealView's own photo environment
            if parent.isOfType(coin_type("Switch")) and parent.whichChild.getValue() == -1:
                continue        # FreeCAD's texture switch, off
            image = tex.image.getValue()
            if (tex.filename.getValue() or "") or (image and image[0]):
                return True
        except Exception:
            return True
    return False


def _roots(doc):
    """(object, scene root) for each object. A link draws its part's own nodes: the part's root is
    searched once, not again through every link to it, and a container (assembly, part, body) is left
    to its members' own roots (300 links of one part: 10 s to turn RealView on, vd122, 11-21)."""
    seen = set()
    for obj in doc.Objects:
        try:
            if obj.isDerivedFrom("App::Link") or obj.TypeId == "Assembly::AssemblyLink":
                linked = obj.getLinkedObject(True)
                if linked is not None and linked is not obj:
                    key = (linked.Document.Name, linked.Name)
                    if key in seen:
                        continue
                    seen.add(key)
                    vo = getattr(linked, "ViewObject", None)
                    root = getattr(vo, "RootNode", None) if vo is not None else None
                    if root is not None:
                        yield linked, root
                    continue
            if obj.hasExtension("App::GeoFeatureGroupExtension"):
                continue        # an assembly, part or body: its members' own roots are searched
        except Exception as _fw_err:
            _fw_log("realview.py:roots", _fw_err)
        vo = getattr(obj, "ViewObject", None)
        root = getattr(vo, "RootNode", None) if vo is not None else None
        if root is not None:
            yield obj, root


def _signature(doc):
    return (len(doc.Objects), doc.UndoCount, doc.RedoCount)


def apply(doc):
    """The shader in front of each part's face set (FreeCAD's FlatRoot), once each."""
    prog = program()
    n = 0
    for obj, root in _roots(doc):
        if _textured(root):
            stats["skipped_textured"] += 1
            remove_from(root)
            continue
        for tail, parent in _search(root, "SoBrepFaceSet"):
            if parent is None or parent.getName().getString() != "FlatRoot":
                continue        # a sketch's faces or another add-on drawing: left as it is
            if any(parent.getChild(k).getName().getString() == NODE for k in range(parent.getNumChildren())):
                continue
            at = parent.findChild(tail)
            if at < 0:
                continue
            parent.insertChild(prog, at)
            parent.insertChild(environment_node(), at)
            n += 1
    stats["inserted"] += n
    _done[doc.Name] = _signature(doc)
    return n


def remove_from(root):
    n = 0
    for tail, parent in _search(root, name=NODE):
        if parent is None:
            continue
        k = parent.findChild(tail)
        if k >= 0:
            parent.removeChild(k)
            n += 1
    for tail, parent in _search(root, name=ENV_NODE):
        if parent is not None and parent.findChild(tail) >= 0:
            parent.removeChild(parent.findChild(tail))
    stats["removed"] += n
    return n


def remove(doc):
    n = 0
    for obj, root in _roots(doc):
        n += remove_from(root)
    _done.pop(doc.Name, None)
    return n


def shaded_now():
    ""

    try:
        from . import viewsettings, cartoon
        if viewsettings.draw_style_index() not in viewsettings.SHADED_STYLES:
            return False
        return not cartoon.active()
    except Exception as _fw_err:
        _fw_log("realview.py:shaded", _fw_err)
        return True


def refresh(doc=None):
    """Puts the shader on (RealView on) or takes it off, in doc or every open document."""
    docs = [doc] if doc is not None else list(App.listDocuments().values())
    on = enabled() and shaded_now()
    for d in docs:
        try:
            if on:
                apply(d)
            else:
                remove(d)
                _done.pop(d.Name, None)
        except Exception as _fw_err:
            _fw_log("realview.py:refresh", _fw_err)
    for v in _views():
        try:
            if on:
                attach_frame(v)
            v.redraw()
        except Exception as _fw_err:
            _fw_log("realview.py:redraw", _fw_err)


def _views():
    out = []
    try:
        for doc in App.listDocuments().values():
            gdoc = Gui.getDocument(doc.Name)
            for v in (gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc is not None else []):
                out.append(v)
    except Exception as _fw_err:
        _fw_log("realview.py:views", _fw_err)
    return out


def check_up():
    """Cheap: a document whose objects changed since it was done is done again (new parts, undo)."""
    if not enabled():
        return
    if not shaded_now():
        if _done:
            refresh()
        return
    sync_lights()
    sync_lock()
    for v in _views():
        try:
            attach_frame(v)
        except Exception as _fw_err:
            _fw_log("realview.py:frame", _fw_err)
    try:
        view_activated(Gui.ActiveDocument.ActiveView)
    except Exception:
        pass
    for doc in App.listDocuments().values():
        if _done.get(doc.Name) != _signature(doc):
            try:
                apply(doc)
            except Exception as _fw_err:
                _fw_log("realview.py:check_up", _fw_err)


def schedule():
    if not enabled():
        return
    if _timer[0] is None:
        t = QtCore.QTimer()
        t.setSingleShot(True)
        t.setInterval(150)
        t.timeout.connect(check_up)
        _timer[0] = t
    _timer[0].start()


class _Observer:
    def slotCreatedObject(self, obj):
        schedule()

    def slotRecomputedDocument(self, doc):
        schedule()

    def slotCreatedDocument(self, doc):
        schedule()

    def slotUndoDocument(self, doc):
        schedule()

    def slotRedoDocument(self, doc):
        schedule()

    def slotChangedObject(self, obj, prop):
        if prop in ("Shape", "DisplayMode") and enabled():
            schedule()

    def slotDeletedDocument(self, doc):
        _done.pop(doc.Name, None)


SCENE_KEYS = ("BackgroundColor", "BackgroundColor2", "BackgroundColor3", "BackgroundColor4",
              "Gradient", "RadialGradient", "UseBackgroundColorMid")


class _LightWatch:
    """A light turned on or off (DisplayManager, Options): the shader reads that many. A new scene
    or background: the studio in the faces follows."""
    def onChange(self, grp, reason):
        if reason in LIGHT_KEYS:
            sync_lights()
        elif reason in SCENE_KEYS:
            sync_scene()


def _style_changed(*args):
    if enabled():
        QtCore.QTimer.singleShot(0, refresh)


_shaded = [None]        # shaded_now() when last looked at
STYLE_POLL_MS = 400


def _poll_style():
    """A draw style picked from a toolbar, the View menu or a key (the actions' signals don't all
    reach Python), or Cartoon turned on or off: the shader follows within a moment."""
    if not enabled():
        _shaded[0] = None
        return
    now = shaded_now()
    if now != _shaded[0]:
        first = _shaded[0] is None
        _shaded[0] = now
        if not (first and now):
            refresh()


def _watch_styles():
    try:
        for action in Gui.Command.get("Std_DrawStyle").getAction():
            action.triggered.connect(_style_changed)
        return True
    except Exception as _fw_err:
        _fw_log("realview.py:styles", _fw_err)
        return False


def install():
    if _observer[0] is None:
        _watch_styles()
        t = QtCore.QTimer()
        t.setInterval(STYLE_POLL_MS)
        t.timeout.connect(_poll_style)
        t.start()
        _timer.append(t)
        _observer[0] = _Observer()
        App.addDocumentObserver(_observer[0])
        try:
            grp = App.ParamGet(VIEW)
            _observer.append(_LightWatch())
            grp.Attach(_observer[-1])
            _observer.append(grp)       # the group handle holds the observer: dropped, it detaches
        except Exception as _fw_err:
            _fw_log("realview.py:lightwatch", _fw_err)
    if enabled():
        schedule()
