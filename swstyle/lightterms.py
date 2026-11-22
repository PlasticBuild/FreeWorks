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


import ctypes
import math
import sys

import FreeCAD as App

AMBIENT_DEFAULT = 0          # % of the light's colour, added everywhere
SPECULARITY_DEFAULT = 100    # % of its Brightness, in the highlights (Coin's own behaviour)
TAG = "SWLightTerms"         # the callback nodes' name
# FreeCAD's own lights: Coin node name -> parameter prefix (displaymanager.LIGHTS)
BUILTIN = {"": "Headlight", "filllight": "FillLight", "backlight": "Backlight"}

GL_LIGHT0 = 0x4000
GL_AMBIENT, GL_DIFFUSE, GL_SPECULAR, GL_POSITION = 0x1200, 0x1201, 0x1202, 0x1203
GL_MAX_LIGHTS = 0x0D31
GL_MODELVIEW_MATRIX = 0x0BA6

_gl = []         # [library] once loaded, [None] when there is none
_F4 = ctypes.c_float * 4
_F16 = ctypes.c_float * 16


def _params():
    from .viewextras import PARAMS
    return App.ParamGet(PARAMS)


def builtin_terms(prefix):
    """(Ambient %, Specularity %) of one of FreeCAD's own lights (Headlight, FillLight, Backlight)."""
    p = _params()
    return (p.GetInt(prefix + "Ambient", AMBIENT_DEFAULT), p.GetInt(prefix + "Specularity", SPECULARITY_DEFAULT))


def set_builtin_terms(prefix, ambient=None, specularity=None):
    p = _params()
    if ambient is not None:
        p.SetInt(prefix + "Ambient", int(max(0, min(100, round(ambient)))))
    if specularity is not None:
        p.SetInt(prefix + "Specularity", int(max(0, min(100, round(specularity)))))
    redraw()


def object_terms(obj):
    return (int(getattr(obj, "Ambient", AMBIENT_DEFAULT)), int(getattr(obj, "Specularity", SPECULARITY_DEFAULT)))


def named_terms(doc_name, obj_name):
    """object_terms of a document's light found by name (a closed document's: the defaults)."""
    try:
        obj = App.getDocument(doc_name).getObject(obj_name)
    except Exception:
        obj = None
    return object_terms(obj) if obj is not None else (AMBIENT_DEFAULT, SPECULARITY_DEFAULT)


def add_properties(obj):
    """The two amounts on a light added from the DisplayManager (lights saved before keep Coin's look)."""
    if not hasattr(obj, "Ambient"):
        obj.addProperty("App::PropertyPercent", "Ambient", "Light",
                        "Light the light adds from everywhere, 0-100 % of its colour").Ambient = AMBIENT_DEFAULT
    if not hasattr(obj, "Specularity"):
        obj.addProperty("App::PropertyPercent", "Specularity", "Light",
                        "How much highlight the light puts on shiny faces, 0-100 % of its Brightness"
                        ).Specularity = SPECULARITY_DEFAULT


def _library():
    if _gl:
        return _gl[0]
    lib = None
    try:
        if sys.platform.startswith("win"):
            lib = ctypes.WinDLL("opengl32")
        elif sys.platform == "darwin":
            lib = ctypes.CDLL("/System/Library/Frameworks/OpenGL.framework/OpenGL")
        else:
            lib = ctypes.CDLL("libGL.so.1")
        lib.glIsEnabled.restype = ctypes.c_ubyte
        lib.glIsEnabled.argtypes = [ctypes.c_uint]
        lib.glGetLightfv.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_float)]
        lib.glLightfv.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_float)]
        lib.glGetFloatv.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_float)]
        lib.glGetIntegerv.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
    except Exception as error:
        _fw_log("lightterms.py:gl", error)
        lib = None
    _gl.append(lib)
    return lib


def _light_vector(node):
    """The light's place as OpenGL keeps it: (x, y, z, w) before the model-view matrix."""
    from pivy import coin
    if node.isOfType(coin.SoDirectionalLight.getClassTypeId()):
        d = node.direction.getValue()
        return (-d[0], -d[1], -d[2], 0.0)
    loc = node.location.getValue()
    return (loc[0], loc[1], loc[2], 1.0)


def _gl_index(lib, node):
    """The OpenGL light Coin has just set up for this node: the enabled light whose colour and place
    are this node's (the last one, if two are alike), or None."""
    colour = node.color.getValue()
    k = node.intensity.getValue()
    want = (colour[0] * k, colour[1] * k, colour[2] * k)
    m = _F16()
    lib.glGetFloatv(GL_MODELVIEW_MATRIX, m)
    x, y, z, w = _light_vector(node)
    eye = [m[0] * x + m[4] * y + m[8] * z + m[12] * w, m[1] * x + m[5] * y + m[9] * z + m[13] * w,
           m[2] * x + m[6] * y + m[10] * z + m[14] * w]
    count = ctypes.c_int(8)
    lib.glGetIntegerv(GL_MAX_LIGHTS, ctypes.byref(count))
    found = None
    v = _F4()
    for i in range(max(1, min(count.value, 32))):
        if not lib.glIsEnabled(GL_LIGHT0 + i):
            continue
        lib.glGetLightfv(GL_LIGHT0 + i, GL_DIFFUSE, v)
        if max(abs(v[j] - want[j]) for j in range(3)) > 0.01:
            continue
        lib.glGetLightfv(GL_LIGHT0 + i, GL_POSITION, v)
        if (v[3] == 0.0) != (w == 0.0):
            continue
        if w == 0.0:
            a = math.sqrt(sum(c * c for c in eye)) or 1.0
            b = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
            if sum(eye[j] * v[j] for j in range(3)) / (a * b) < 0.999:
                continue
        elif max(abs(eye[j] - v[j]) for j in range(3)) > 1e-3 * (1.0 + max(abs(c) for c in eye)):
            continue
        found = i
    return found


def callbacks_off():
    """FW_NO_LIGHTCB=1 (or NOLIGHTCB=1): no light callbacks at all, for fault hunting."""
    import os
    return bool(os.environ.get("FW_NO_LIGHTCB") or os.environ.get("NOLIGHTCB"))


def _light_before(action):
    """The light right before the callback node being traversed, or None."""
    from pivy import coin
    path = action.getCurPath()
    if path is None or path.getLength() < 2:
        return None
    index = path.getIndexFromTail(0)
    if index < 1:
        return None
    node = path.getNodeFromTail(1).getChild(index - 1)
    for kind in (coin.SoDirectionalLight, coin.SoPointLight, coin.SoSpotLight):
        if node.isOfType(kind.getClassTypeId()):
            return coin.cast(node, kind.__name__)
    return None


def _apply_after(terms, action):
    try:
        from pivy import coin
        if not action.isOfType(coin.SoGLRenderAction.getClassTypeId()) or callbacks_off():
            return
        if tuple(terms()) == (AMBIENT_DEFAULT, SPECULARITY_DEFAULT):
            return
        node = _light_before(action)
        if node is not None:
            _apply(node, terms, action)
    except Exception as error:
        _fw_log("lightterms.py:after", error)


def _apply(node, terms, action):
    """The callback after a light: its ambient and specular parts, as the light's amounts say."""
    try:
        from pivy import coin
        if not action.isOfType(coin.SoGLRenderAction.getClassTypeId()) or not node.on.getValue():
            return
        if callbacks_off():
            return
        ambient, specularity = terms()
        if ambient == AMBIENT_DEFAULT and specularity == SPECULARITY_DEFAULT:
            return
        lib = _library()
        if lib is None:
            return
        i = _gl_index(lib, node)
        if i is None:
            return
        colour = node.color.getValue()
        k = node.intensity.getValue()
        a, s = ambient / 100.0, k * specularity / 100.0
        lib.glLightfv(GL_LIGHT0 + i, GL_AMBIENT, _F4(colour[0] * a, colour[1] * a, colour[2] * a, 1.0))
        lib.glLightfv(GL_LIGHT0 + i, GL_SPECULAR, _F4(colour[0] * s, colour[1] * s, colour[2] * s, 1.0))
    except Exception as error:
        _fw_log("lightterms.py:apply", error)


_CALLBACKS = {}     # key -> the function a callback node calls (pivy keeps it for good: one per key)


def callback(node, terms, key=None):
    """A callback node to go right after a light node: terms() gives (Ambient %, Specularity %).
    The function finds its light as the node before it in the path being drawn and keeps no node:
    pivy never lets go of a callback's function, so one that held the light kept every light of
    every closed document (Reviewer soak 11-20: +8 lights a round). Functions are shared by key."""
    from pivy import coin
    if callbacks_off():
        g = coin.SoGroup()
        g.setName(TAG)
        return g
    cb = coin.SoCallback()
    cb.setName(TAG)
    fn = _CALLBACKS.get(key) if key is not None else None
    if fn is None:
        def fn(data, action, terms=terms):
            _apply_after(terms, action)
        if key is not None:
            _CALLBACKS[key] = fn
    cb.setCallback(fn)
    return cb


def attach_builtin(root):
    """FreeCAD's own lights in a view's top scene get the callback after them only while their
    Ambient or Specularity is not the default (with the defaults the callback has nothing to do, and
    it called OpenGL from Python on every frame, which faulted on Intel graphics, Reviewer 11-20); it
    comes out again when they go back to the defaults or with FW_NO_LIGHTCB."""
    from pivy import coin
    added = 0
    i = 0
    off = callbacks_off()
    while i < root.getNumChildren():
        node = root.getChild(i)
        if node.isOfType(coin.SoDirectionalLight.getClassTypeId()):
            name = node.getName().getString()
            prefix = BUILTIN.get(name)
            nxt = root.getChild(i + 1) if i + 1 < root.getNumChildren() else None
            has = nxt is not None and nxt.getName().getString() == TAG
            want = prefix is not None and not off and \
                builtin_terms(prefix) != (AMBIENT_DEFAULT, SPECULARITY_DEFAULT)
            if want and not has:
                root.insertChild(callback(node, lambda p=prefix: builtin_terms(p), ("builtin", prefix)), i + 1)
                added += 1
                i += 1
            elif has and not want:
                root.removeChild(i + 1)
        i += 1
    return added


def _views():
    import FreeCADGui as Gui
    out = []
    for doc in App.listDocuments().values():
        try:
            gdoc = Gui.getDocument(doc.Name)
            out.extend(gdoc.mdiViewsOfType("Gui::View3DInventor") if gdoc is not None else [])
        except Exception as _fw_err:
            _fw_log("lightterms.py:views", _fw_err)
    return out


def ensure_all():
    """Every open 3D view: FreeCAD's own lights carry their callbacks."""
    for view in _views():
        try:
            attach_builtin(view.getViewer().getSoRenderManager().getSceneGraph())
        except Exception as _fw_err:
            _fw_log("lightterms.py:ensure", _fw_err)


def redraw():
    ensure_all()
    for view in _views():
        try:
            view.redraw()
        except Exception as _fw_err:
            _fw_log("lightterms.py:redraw", _fw_err)


def percent_row(grid, row, label, value, changed, name=None):
    """A PropertyManager row: label, slider and % box kept together; changed(value) on each move."""
    from PySide import QtCore, QtWidgets
    slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
    slider.setRange(0, 100)
    spin = QtWidgets.QSpinBox()
    spin.setRange(0, 100)
    spin.setSuffix(" %")
    if name:
        slider.setObjectName(name)
        spin.setObjectName(name + "Value")
    slider.setValue(int(value))
    spin.setValue(int(value))
    slider.valueChanged.connect(spin.setValue)
    spin.valueChanged.connect(slider.setValue)
    spin.valueChanged.connect(changed)
    grid.addWidget(QtWidgets.QLabel(label), row, 0)
    grid.addWidget(slider, row, 1)
    grid.addWidget(spin, row, 2)
    return spin


class _Watch:
    """A new document's 3D view: FreeCAD's own lights get their callbacks once it is there."""
    def slotCreatedDocument(self, doc):
        _later()

    def slotActivateDocument(self, doc):
        _later()


_installed = []


def _later():
    try:
        from PySide import QtCore
        QtCore.QTimer.singleShot(300, ensure_all)
    except Exception as _fw_err:
        _fw_log("lightterms.py:later", _fw_err)


def install():
    if not _installed:
        _installed.append(_Watch())
        App.addDocumentObserver(_installed[0])
    _later()
