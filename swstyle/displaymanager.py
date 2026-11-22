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
from PySide import QtCore, QtGui, QtWidgets

from . import icons
from .widgets import alive

Qt = QtCore.Qt
PAGE = "DisplayManager"
MODES = (("appearances", "DISPMGR_APPEAR", "View Appearances"),
         ("decals", "DISPMGR_DECAL", "View Decals"),
         ("scene", "DISPMGR_SCENE", "View Scene, Lights, and Cameras"))
VIEW = "User parameter:BaseApp/Preferences/View"

LIGHTS = (("Ambient", "AmbientLight", None),
          ("Directional1", "Headlight", ""),
          ("Directional2", "FillLight", "filllight"),
          ("Directional3", "Backlight", "backlight"))
ENABLE = {"Headlight": "EnableHeadlight", "FillLight": "EnableFillLight", "Backlight": "EnableBacklight"}
ROLE = Qt.UserRole + 1
# the link at the top of each view and the Task Pane folder it opens
LIBRARY = {"appearances": ("Open Appearance Library", "DISPMGR_APPEAR", "Appearances(color)"),
           "decals": ("Open Decal Library", "DISPMGR_DECAL", "Decals"),
           "scene": ("Open Scene Library", "DISPMGR_SCENE", "Scenes")}


def open_library(mode):
    """The Task Pane's Appearances, Scenes, and Decals tab, on the view's folder. The folder's tree
    item, or None when the Task Pane is not there."""
    try:
        from . import taskpane
        page = taskpane.open_tab(4)
        tree = getattr(page, "tree", None)
        if tree is None:
            return None
        hits = tree.findItems(LIBRARY[mode][2], Qt.MatchExactly | Qt.MatchRecursive)
        if hits:
            tree.setCurrentItem(hits[0])
            tree.scrollToItem(hits[0])
            return hits[0]
    except Exception as error:
        _fw_log("displaymanager.py:library", error)
    return None


def _params():
    return App.ParamGet(VIEW)


def _has(kind, key):
    try:
        return any(k == key for t, k, v in _params().GetContents() or () if t == kind)
    except Exception:
        return False


# --------------------------------------------------------------------------- lights
def _viewer():
    try:
        return Gui.ActiveDocument.ActiveView.getViewer()
    except Exception:
        return None


def _nodes():
    """{node name: SoDirectionalLight} and the SoEnvironment the active view lights with."""
    viewer = _viewer()
    lights, env = {}, None
    if viewer is None:
        return lights, env
    try:
        from pivy import coin
        root = viewer.getSoRenderManager().getSceneGraph()
        for kind in (coin.SoDirectionalLight, coin.SoEnvironment):
            sa = coin.SoSearchAction()
            sa.setType(kind.getClassTypeId())
            sa.setInterest(coin.SoSearchAction.ALL)
            sa.apply(root)
            paths = sa.getPaths()
            for i in range(paths.getLength()):
                node = paths[i].getTail()
                if kind is coin.SoEnvironment:
                    env = env or node
                else:
                    lights.setdefault(node.getName().getString(), node)
    except Exception as _fw_err:
        _fw_log("displaymanager.py:91", _fw_err)
    return lights, env


def _pack(rgb):
    r, g, b = (max(0, min(255, int(round(c * 255)))) for c in rgb[:3])
    return (r << 24) | (g << 16) | (b << 8) | 0xFF


def _unpack(value):
    return ((value >> 24) & 0xFF) / 255.0, ((value >> 16) & 0xFF) / 255.0, ((value >> 8) & 0xFF) / 255.0


def _direction(text):
    try:
        v = [float(x) for x in text.strip("() ").split(",")]
        return tuple(v[:3]) if len(v) >= 3 else None
    except Exception:
        return None


def to_lonlat(d):
    ""
    x, y, z = (-c for c in d)                    # where the light is, seen from the model
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    return math.degrees(math.atan2(x, -y)), math.degrees(math.asin(max(-1.0, min(1.0, z))))


def from_lonlat(lon, lat):
    lo, la = math.radians(lon), math.radians(lat)
    p = (math.cos(la) * math.sin(lo), -math.cos(la) * math.cos(lo), math.sin(la))
    return tuple(-c for c in p)


def light(name):
    """{'on', 'brightness' (0-100), 'colour' (r, g, b), 'direction' or None} of a light."""
    prefix, node_name = next((p, n) for t, p, n in LIGHTS if t == name)
    p = _params()
    lights, env = _nodes()
    node = lights.get(node_name) if node_name is not None else None
    out = {}
    if prefix == "AmbientLight":
        out["on"] = True
        out["brightness"] = p.GetInt("AmbientLightIntensity", 0) if _has("Integer", "AmbientLightIntensity") else \
            int(round((env.ambientIntensity.getValue() if env is not None else 0.2) * 100))
        out["colour"] = _unpack(p.GetUnsigned("AmbientLightColor")) if _has("Unsigned Long", "AmbientLightColor") else \
            (tuple(env.ambientColor.getValue().getValue()) if env is not None else (1.0, 1.0, 1.0))
        out["direction"] = None
        return out
    key = ENABLE[prefix]
    out["on"] = p.GetBool(key) if _has("Boolean", key) else (bool(node.on.getValue()) if node is not None
                                                              else prefix != "Backlight")
    k = prefix + "Intensity"
    out["brightness"] = p.GetInt(k, 0) if _has("Integer", k) else \
        int(round((node.intensity.getValue() if node is not None else 1.0) * 100))
    k = prefix + "Color"
    out["colour"] = _unpack(p.GetUnsigned(k)) if _has("Unsigned Long", k) else \
        (tuple(node.color.getValue().getValue()) if node is not None else (1.0, 1.0, 1.0))
    k = prefix + "Direction"
    d = _direction(p.GetString(k)) if _has("String", k) else None
    if d is None and node is not None:
        d = tuple(node.direction.getValue().getValue())
    out["direction"] = d
    return out


def set_light(name, on=None, brightness=None, colour=None, direction=None):
    prefix = next(p for t, p, n in LIGHTS if t == name)
    p = _params()
    if on is not None and prefix in ENABLE:
        p.SetBool(ENABLE[prefix], bool(on))
    if brightness is not None:
        p.SetInt(prefix + "Intensity", int(max(0, min(100, round(brightness)))))
    if colour is not None:
        p.SetUnsigned(prefix + "Color", _pack(colour))
    if direction is not None and prefix != "AmbientLight":
        p.SetString(prefix + "Direction", "(%.6f,%.6f,%.6f)" % tuple(direction))


def _saved(prefix):
    """The light's parameters as they are now (to put back on Cancel): [(kind, key, value or None)]."""
    keys = [("Boolean", ENABLE.get(prefix)), ("Integer", prefix + "Intensity"),
            ("Unsigned Long", prefix + "Color"), ("String", prefix + "Direction")]
    have = {(t, k): v for t, k, v in _params().GetContents() or ()}
    return [(t, k, have.get((t, k))) for t, k in keys if k]


def _restore(saved):
    p = _params()
    for kind, key, value in saved:
        if value is None:
            {"Boolean": p.RemBool, "Integer": p.RemInt, "Unsigned Long": p.RemUnsigned,
             "String": p.RemString}[kind](key)
        else:
            {"Boolean": p.SetBool, "Integer": p.SetInt, "Unsigned Long": p.SetUnsigned,
             "String": p.SetString}[kind](key, value)


class LightPanel:
    ""

    def __init__(self, name):
        self.name = name
        self.prefix = next(p for t, p, n in LIGHTS if t == name)
        self.saved = _saved(self.prefix)
        state = light(name)
        self.start = dict(state)
        self.colour = state["colour"]
        form = QtWidgets.QWidget()
        form.setObjectName("SWLightPM")
        form.setWindowTitle(name)
        form.setProperty("swstyle_pm_title", name)       # the PM header: the light's name and its kind's picture
        form.setProperty("swstyle_pm_icon", LIGHT_ICONS["Ambient" if self.prefix == "AmbientLight" else "Directional"])
        lay = QtWidgets.QVBoxLayout(form)
        basic = QtWidgets.QGroupBox("Basic")
        g = QtWidgets.QGridLayout(basic)
        self.on = QtWidgets.QCheckBox("On in FreeCAD")
        self.on.setChecked(state["on"])
        self.on.setVisible(self.prefix in ENABLE)
        self.on.toggled.connect(lambda v: set_light(name, on=v))
        g.addWidget(self.on, 0, 0, 1, 3)
        self.colour_button = QtWidgets.QPushButton("Edit Color...")
        self.colour_button.clicked.connect(self.pick_colour)
        g.addWidget(self.colour_button, 1, 0, 1, 3)

        self.terms = None
        if self.prefix != "AmbientLight":
            from . import lightterms
            self.terms = lightterms.builtin_terms(self.prefix)
            self.ambient = lightterms.percent_row(g, 2, "Ambient:", self.terms[0],
                                                  lambda v: lightterms.set_builtin_terms(self.prefix, ambient=v), "SWLightAmbient")
            self.specularity = lightterms.percent_row(g, 4, "Specularity:", self.terms[1],
                                                      lambda v: lightterms.set_builtin_terms(self.prefix, specularity=v),
                                                      "SWLightSpecularity")
        g.addWidget(QtWidgets.QLabel("Brightness:" if self.prefix != "AmbientLight" else "Ambient:"), 3, 0)
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.spin = QtWidgets.QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setSuffix(" %")
        self.slider.setValue(state["brightness"])
        self.spin.setValue(state["brightness"])
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)
        self.spin.valueChanged.connect(lambda v: set_light(name, brightness=v))
        g.addWidget(self.slider, 3, 1)
        g.addWidget(self.spin, 3, 2)
        lay.addWidget(basic)
        self.lon = self.lat = None
        if state["direction"] is not None:
            pos = QtWidgets.QGroupBox("Light Position")
            pg = QtWidgets.QGridLayout(pos)
            lon, lat = to_lonlat(state["direction"])
            self.lon, self.lat = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
            for row, (label, box, lim, value) in enumerate((("Longitude:", self.lon, 180, lon),
                                                            ("Latitude:", self.lat, 90, lat))):
                box.setRange(-lim, lim)
                box.setDecimals(1)
                box.setSuffix("°")
                box.setValue(value)
                box.valueChanged.connect(self.move)
                pg.addWidget(QtWidgets.QLabel(label), row, 0)
                pg.addWidget(box, row, 1)
            lay.addWidget(pos)
        lay.addStretch(1)
        self.form = form
        self.update_swatch()

    def update_swatch(self):
        pix = QtGui.QPixmap(14, 14)
        pix.fill(QtGui.QColor.fromRgbF(*self.colour[:3]))
        self.colour_button.setIcon(QtGui.QIcon(pix))

    def pick_colour(self):
        c = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*self.colour[:3]), self.form, "Edit Color")
        if c.isValid():
            self.set_colour((c.redF(), c.greenF(), c.blueF()))

    def set_colour(self, rgb):
        self.colour = tuple(rgb)
        set_light(self.name, colour=self.colour)
        self.update_swatch()

    def move(self, *args):
        set_light(self.name, direction=from_lonlat(self.lon.value(), self.lat.value()))

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        Gui.Control.closeDialog()
        refresh_all()
        return True

    def reject(self):
        # the light as it was. The views follow a parameter that is set, not one that is removed
        # (that brings FreeCAD's default, not what the view showed), so the values are set back.
        s = self.start
        set_light(self.name, on=s["on"], brightness=s["brightness"], colour=s["colour"], direction=s["direction"])
        _restore([x for x in self.saved if x[2] is not None])
        if self.terms is not None:
            from . import lightterms
            lightterms.set_builtin_terms(self.prefix, ambient=self.terms[0], specularity=self.terms[1])
        Gui.Control.closeDialog()
        refresh_all()
        return True


def edit_light(name):
    panel = LightPanel(name)
    QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(panel))
    return panel


# --------------------------------------------------------------------------- appearances
def appearance_rows(doc):
    """[(label, rgbt, level, obj, sub, stored)] for every appearance in the part, part first."""
    from . import appearance
    rows = []
    bodies = appearance.bodies(doc) if doc is not None else []
    # surface bodies (and solids outside any Body) keep their own appearances (pkg144): listed too
    loose = [o for o in appearance.loose_features(doc) if appearance.own_body(o)] if doc is not None else []
    if not bodies and not loose:
        return rows
    first = bodies[0] if bodies else loose[0]
    part = appearance.Target("part", first)
    rows.append(("Part (%s)" % doc.Label, appearance.current_colour(part), "part", first, "",
                 "part" in appearance.stored(first)))
    faces = []
    for body in bodies:
        values = appearance.stored(body)
        if "body" in values:
            rows.append(("Body (%s)" % body.Label, appearance.decode(values["body"]), "body", body, "", True))
        order = {o.Name: i for i, o in enumerate(body.Group)}
        feats = []
        for key, text in values.items():
            parts = key.split(":")
            obj = doc.getObject(parts[1]) if len(parts) > 1 else None
            if obj is None:
                continue
            if parts[0] == "feature":
                feats.append((order.get(obj.Name, 1 << 20), ("Feature (%s)" % obj.Label, appearance.decode(text),
                                                            "feature", obj, "", True)))
            elif parts[0] == "face" and len(parts) > 2:
                faces.append((order.get(obj.Name, 1 << 20), parts[2], ("Face (%s@%s)" % (parts[2], obj.Label),
                                                                        appearance.decode(text), "face", obj,
                                                                        parts[2], True)))
        rows.extend(r for _k, r in sorted(feats, key=lambda x: x[0]))
    for n, obj in enumerate(loose):
        values = appearance.stored(obj)
        if "body" in values:
            rows.append(("Body (%s)" % obj.Label, appearance.decode(values["body"]), "body", obj, "", True))
        if "feature:" + obj.Name in values:
            rows.append(("Feature (%s)" % obj.Label, appearance.decode(values["feature:" + obj.Name]), "feature",
                         obj, "", True))
        prefix = "face:%s:" % obj.Name
        for key, text in values.items():
            if key.startswith(prefix):
                sub = key[len(prefix):]
                faces.append(((1 << 21) + n, sub, ("Face (%s@%s)" % (sub, obj.Label), appearance.decode(text), "face",
                                                   obj, sub, True)))
    rows.extend(r for _k, _f, r in sorted(faces, key=lambda x: (x[0], x[1])))
    return rows


def _swatch(rgbt):
    pix = QtGui.QPixmap(14, 14)
    pix.fill(QtGui.QColor.fromRgbF(*rgbt[:3]) if rgbt else QtGui.QColor(Qt.gray))
    return QtGui.QIcon(pix)



# colour, the light's kind, a camera, the scene itself (they were flat colour squares, or nothing)
LIGHT_ICONS = {"Ambient": "FW_DM_AmbientLight", "Directional": "FW_DM_DirectionalLight", "Point": "FW_DM_PointLight",
               "Spot": "FW_DM_SpotLight", "Sun": "FW_DM_SunLight"}
LIGHTS_FOLDER_ICON = "FW_ViewLights"
CAMERA_ICON = "FW_ViewCameras"


def light_icon(kind):
    return icons.family(LIGHT_ICONS.get(kind, LIGHT_ICONS["Directional"]))


def _ball(rgbt):
    """An appearance row's picture: a small lit ball in its colour (the Task Pane's swatch)."""
    try:
        from . import appearpane
        rgb = tuple(rgbt[:3]) if rgbt else (0.5, 0.5, 0.5)
        transparency = rgbt[3] if rgbt and len(rgbt) > 3 else 0.0
        return appearpane.swatch_icon(rgb, 16, transparency)
    except Exception as _fw_err:
        _fw_log("displaymanager.py:ball", _fw_err)
        return _swatch(rgbt)


def _scene_picture(index):
    try:
        from . import appearpane
        if index >= 0 and hasattr(appearpane, "scene_icon"):
            return appearpane.scene_icon(index, 16)
    except Exception as _fw_err:
        _fw_log("displaymanager.py:scenepic", _fw_err)
    return icons.family("DISPMGR_SCENE")


def edit_appearance(level, obj, sub):
    from . import appearance
    doc = obj.Document
    return appearance.open_page(doc, level, [(obj, sub)])


def remove_appearance(level, obj, sub):
    from . import appearance
    t = appearance.target_for(level, obj, sub) if level not in ("part", "body") else \
        appearance.Target(level, appearance.body_of(obj) or obj)      # a surface body is its own body
    if t is None:
        return False
    doc = obj.Document
    doc.openTransaction("Remove Appearance")
    try:
        appearance.remove([t])
    finally:
        doc.commitTransaction()
    refresh_all()
    return True


# --------------------------------------------------------------------------- the page
_pages = []


def refresh_all():
    for page in list(_pages):
        if alive(page):
            page.refresh()
        else:
            _pages.remove(page)


class Page(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWDisplayManager")
        self.mode = "appearances"
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QtWidgets.QWidget(self)
        bar.setObjectName("SWDisplayManagerBar")
        row = QtWidgets.QHBoxLayout(bar)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(2)
        self.buttons = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for mode, icon, tip in MODES:
            b = QtWidgets.QToolButton(bar)
            b.setObjectName("SWDisplayManager_" + mode)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setIcon(icons.family(icon))
            b.setIconSize(QtCore.QSize(20, 20))
            if b.icon().isNull():
                b.setText(tip.split()[1].rstrip(","))     # Appearances / Decals / Scene, whole
            b.setToolTip(tip)
            b.clicked.connect(lambda checked=False, m=mode: self.set_mode(m))
            group.addButton(b)
            row.addWidget(b)
            self.buttons[mode] = b
        row.addStretch(1)
        lay.addWidget(bar)
        self.title = QtWidgets.QLabel(self)
        self.title.setObjectName("SWDisplayManagerTitle")
        self.title.setContentsMargins(6, 2, 6, 2)
        lay.addWidget(self.title)

        self.library = QtWidgets.QPushButton(self)
        self.library.setObjectName("SWDisplayManagerLibrary")
        self.library.setFlat(True)
        self.library.setCursor(Qt.PointingHandCursor)
        self.library.setStyleSheet("QPushButton { text-align: left; padding: 2px 6px; border: none; color: palette(link); }"
                                   "QPushButton:hover { text-decoration: underline; }")
        self.library.clicked.connect(lambda *a: open_library(self.mode))
        lay.addWidget(self.library)
        self.tree = QtWidgets.QTreeWidget(self)
        self.tree.setObjectName("SWDisplayManagerTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu_at)
        self.tree.itemDoubleClicked.connect(lambda item, col: self.activate(item))
        lay.addWidget(self.tree, 1)
        self.buttons[self.mode].setChecked(True)
        _pages.append(self)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.refresh)
        self._observer = _Observer(self)
        App.addDocumentObserver(self._observer)
        try:
            from . import lightterms      # every light's Ambient and Specularity reach the views
            lightterms.install()
        except Exception as _fw_err:
            _fw_log("displaymanager.py:lightterms", _fw_err)
        self.destroyed.connect(lambda *a, o=self._observer: _forget(o))

    # ---------------------------------------------------------------- building
    def set_mode(self, mode):
        self.mode = mode
        self.buttons[mode].setChecked(True)
        self.refresh()

    def later(self):
        if alive(self) and self.isVisible():
            self._timer.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        if not alive(self):
            return
        self.tree.clear()
        self.title.setText(next(t for m, i, t in MODES if m == self.mode))
        self.library.setText(LIBRARY[self.mode][0])
        self.library.setIcon(icons.family(LIBRARY[self.mode][1]))
        doc = App.ActiveDocument
        if self.mode == "appearances":
            for label, rgbt, level, obj, sub, stored in appearance_rows(doc):
                item = QtWidgets.QTreeWidgetItem([label])
                item.setIcon(0, _ball(rgbt))
                item.setData(0, ROLE, ("appearance", level, obj.Name, sub, stored))
                self.tree.addTopLevelItem(item)
        elif self.mode == "decals":
            found = decals(doc)
            for d in found:
                on = getattr(d.DecalOf, "Label", "") if d.DecalOf is not None else ""
                item = QtWidgets.QTreeWidgetItem([d.Label + ("  <%s>" % on if on else "")])
                item.setData(0, ROLE, ("decal", d.Name))
                if d.ViewObject is not None and not d.ViewObject.Visibility:
                    item.setForeground(0, QtGui.QBrush(QtGui.QColor(Qt.gray)))
                self.tree.addTopLevelItem(item)
        else:
            self._scene(doc)

    def _scene(self, doc):
        from . import style, cameras
        scene = QtWidgets.QTreeWidgetItem(["Scene"])
        scene.setData(0, ROLE, ("scenefolder",))
        scene.setIcon(0, icons.family("DISPMGR_SCENE"))
        i = style.current_scene()
        name = style.SCENES[i][0] if i >= 0 else "Theme Background"
        child = QtWidgets.QTreeWidgetItem([name])
        child.setIcon(0, _scene_picture(i))
        child.setData(0, ROLE, ("scene",))
        scene.addChild(child)
        self.tree.addTopLevelItem(scene)
        folder = QtWidgets.QTreeWidgetItem(["Lights"])
        folder.setIcon(0, icons.family(LIGHTS_FOLDER_ICON))
        folder.setData(0, ROLE, ("lightfolder",))
        for name, prefix, node in LIGHTS:
            state = light(name)
            item = QtWidgets.QTreeWidgetItem([name])
            item.setIcon(0, light_icon("Ambient" if prefix == "AmbientLight" else "Directional"))
            item.setData(0, ROLE, ("light", name))
            if not state["on"]:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(Qt.gray)))
                item.setToolTip(0, "Off")
            folder.addChild(item)
        try:
            from . import viewextras        # the lights Add Directional / Point / Spot Light and Add Sunlight added
            for o in viewextras.lights(doc):
                item = QtWidgets.QTreeWidgetItem([o.Label])
                item.setIcon(0, light_icon(getattr(o, "LightKind", "Directional")))
                item.setData(0, ROLE, ("xlight", o.Name))
                if not o.On:
                    item.setForeground(0, QtGui.QBrush(QtGui.QColor(Qt.gray)))
                    item.setToolTip(0, "Off")
                folder.addChild(item)
        except Exception as _fw_err:
            _fw_log("displaymanager.py:496", _fw_err)
        self.tree.addTopLevelItem(folder)
        cams = QtWidgets.QTreeWidgetItem(["Cameras"])
        cams.setIcon(0, icons.family(CAMERA_ICON))
        cams.setData(0, ROLE, ("camerafolder",))
        if doc is not None:
            for o in doc.Objects:
                if cameras.is_camera(o):
                    item = QtWidgets.QTreeWidgetItem([o.Label])
                    item.setIcon(0, icons.family(CAMERA_ICON))
                    item.setData(0, ROLE, ("camera", o.Name))
                    cams.addChild(item)
        self.tree.addTopLevelItem(cams)
        self.tree.expandAll()

    # ---------------------------------------------------------------- acting
    def item_named(self, text):
        for item in self.tree.findItems(text, Qt.MatchExactly | Qt.MatchRecursive):
            return item
        return None

    def activate(self, item):
        ""
        data = item.data(0, ROLE) or ("none",)
        doc = App.ActiveDocument
        if data[0] == "appearance" and doc is not None:
            obj = doc.getObject(data[2])
            return obj is not None and edit_appearance(data[1], obj, data[3])
        if data[0] == "light":
            return edit_light(data[1])
        if data[0] == "xlight" and doc is not None:
            return self.edit_added_light(doc.getObject(data[1]))
        if data[0] == "decal" and doc is not None:
            return edit_decal(doc.getObject(data[1]))
        if data[0] == "camera" and doc is not None:
            return self.edit_camera(doc.getObject(data[1]))       # the Camera PM, looking through it
        if data[0] == "scene":
            from . import scenepm
            return scenepm.edit_scene()
        return None

    def camera_view(self, cam):
        from . import cameras
        if cam is None or Gui.ActiveDocument is None:
            return False
        view = Gui.ActiveDocument.ActiveView
        try:
            cameras.leave(view)
            cameras.look_through(view, cam)
            view.redraw()
        except Exception as error:
            App.Console.PrintError("FreeCAD: Camera View: %s\n" % error)
            return False
        return True

    def edit_camera(self, cam):
        from . import cameras
        if cam is None or Gui.ActiveDocument is None or Gui.Control.activeDialog():
            return False
        try:
            cameras.edit_camera(cam)
        except Exception as error:
            App.Console.PrintError("FreeCAD: Edit Camera: %s\n" % error)
            return False
        return True

    def delete_camera(self, cam):
        if cam is None:
            return
        doc = cam.Document
        doc.openTransaction("Delete Camera")
        try:
            from . import cameras
            if Gui.ActiveDocument is not None:
                cameras.leave(Gui.ActiveDocument.ActiveView)
            doc.removeObject(cam.Name)
        finally:
            doc.commitTransaction()
        self.refresh()

    def scene_menu(self):
        from . import style
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWDisplayManagerScenes")
        # the heads-up Apply Scene list (favourites, preview card, Manage Favorites); the pane refreshes after
        from . import scenemenu
        scenemenu.fill(menu)
        menu.triggered.connect(lambda _act: self.later())
        return menu

    def entries(self, item):
        """The row's right-click menu: [(text, run, enabled)] (None = separator)."""
        data = (item.data(0, ROLE) if item is not None else None) or ("none",)
        doc = App.ActiveDocument
        out = []
        if data[0] == "appearance" and doc is not None:
            obj = doc.getObject(data[2])
            level, sub, stored = data[1], data[3], data[4]
            out.append(("Edit Appearance...", lambda: edit_appearance(level, obj, sub), obj is not None))
            out.append(("Remove Appearance", lambda: remove_appearance(level, obj, sub), bool(stored)))
        elif data[0] == "light":
            name = data[1]
            out.append(("Edit Light...", lambda: edit_light(name), True))
            if next(p for t, p, n in LIGHTS if t == name) in ENABLE:
                on = light(name)["on"]
                out.append(("Off in FreeCAD" if on else "On in FreeCAD",
                            lambda: (set_light(name, on=not on), self.refresh()), True))
        elif data[0] == "xlight" and doc is not None:
            o = doc.getObject(data[1])
            out.append(("Edit Light...", lambda: self.edit_added_light(o), o is not None))
            on = bool(o is not None and o.On)
            out.append(("Off in FreeCAD" if on else "On in FreeCAD",
                        lambda: (setattr(o, "On", not on), self.refresh()), o is not None))
            out.append(("Delete", lambda: (self._delete_light(o), self.refresh()), o is not None))
        elif data[0] == "lightfolder":

            for kind, text in (("Directional", "Add Directional Light"), ("Spot", "Add Spot Light"),
                               ("Point", "Add Point Light"), ("Sun", "Add Sunlight")):
                out.append((text, lambda k=kind: self.add_light(k), doc is not None and not Gui.Control.activeDialog()))
        elif data[0] in ("scene", "scenefolder"):
            from . import scenepm
            out.append(("Edit Scene...", scenepm.edit_scene, not Gui.Control.activeDialog()))
            out.append(("Apply Scene", lambda: self.scene_menu().popup(QtGui.QCursor.pos()), True))
        elif data[0] == "camera" and doc is not None:
            cam = doc.getObject(data[1])
            out.append(("Camera View", lambda: self.camera_view(cam), cam is not None))
            out.append(("Edit Camera...", lambda: self.edit_camera(cam),
                        cam is not None and not Gui.Control.activeDialog()))
            out.append(("Add Camera", self.add_camera, Gui.ActiveDocument is not None))
            out.append(("Delete", lambda: (self._delete_camera(cam), self.refresh()), cam is not None))
        elif data[0] == "decal" and doc is not None:
            d = doc.getObject(data[1])
            shown = d is not None and (d.ViewObject is None or d.ViewObject.Visibility)
            out.append(("Edit Decal...", lambda: edit_decal(d), d is not None))
            out.append(("Hide Decal" if shown else "Show Decal",
                        lambda: (show_decal(d, not shown), self.refresh()), d is not None))
            out.append(("Remove Decal", lambda: (remove_decal(d), self.refresh()), d is not None))
        elif data[0] == "camerafolder":
            out.append(("Add Camera", self.add_camera, Gui.ActiveDocument is not None))
        return out

    def add_light(self, kind):
        from . import viewextras
        doc = App.ActiveDocument
        if doc is None:
            return None
        panel = viewextras.add_and_edit(kind, done=self.refresh)
        self.refresh()
        return panel

    def edit_added_light(self, obj):
        ""
        from . import viewextras
        if obj is None or not hasattr(viewextras, "edit_light") or Gui.Control.activeDialog():
            return False
        return viewextras.edit_light(obj, done=self.refresh)

    @staticmethod
    def _delete_light(obj):
        from . import viewextras
        if obj is not None:
            viewextras.delete_light(obj)

    @staticmethod
    def _delete_camera(cam):
        if cam is None:
            return
        doc = cam.Document
        try:
            from . import cameras
            if Gui.ActiveDocument is not None and cameras.through(Gui.ActiveDocument.ActiveView):
                cameras.leave(Gui.ActiveDocument.ActiveView)
        except Exception as _fw_err:
            _fw_log("displaymanager.py:670", _fw_err)
        doc.openTransaction("Delete Camera")
        try:
            doc.removeObject(cam.Name)
        finally:
            doc.commitTransaction()

    def add_camera(self):
        from . import cameras
        cameras.register()
        Gui.runCommand("SWStyle_AddCamera", 0)
        self.refresh()

    def _menu_at(self, pos):
        item = self.tree.itemAt(pos)
        entries = self.entries(item)
        if not entries:
            return
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWDisplayManagerMenu")
        for text, run, enabled in entries:
            if not enabled:
                continue            # no greyed rows: what cannot act now is left out
            act = menu.addAction(text)
            act.triggered.connect(lambda checked=False, run=run: run())
        if not menu.actions():
            return
        menu.popup(self.tree.viewport().mapToGlobal(pos))


def decals(doc):
    """The decals Edit Decal put on the part (picture planes with a DecalOf link)."""
    if doc is None:
        return []
    return [o for o in doc.Objects if o.TypeId == "Image::ImagePlane" and hasattr(o, "DecalOf")]


def edit_decal(d):
    """Double-click on a decal (or Edit Decal...): the Decals PropertyManager (decalpm)."""
    if d is None:
        return False
    from . import decalpm
    return decalpm.edit(d) is not None


def show_decal(d, on):
    if d is not None and d.ViewObject is not None:
        d.ViewObject.Visibility = bool(on)


def remove_decal(d):
    if d is None:
        return False
    doc = d.Document
    doc.openTransaction("Remove Decal")
    try:
        doc.removeObject(d.Name)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return True


class _Observer:
    def __init__(self, page):
        self.page = page

    def _poke(self):
        if alive(self.page):
            self.page.later()

    def slotChangedObject(self, obj, prop):
        if prop in ("SWAppearance", "Label"):
            self._poke()

    def slotCreatedObject(self, obj):
        self._poke()

    def slotDeletedObject(self, obj):
        self._poke()

    def slotActivateDocument(self, doc):
        self._poke()

    def slotUndoDocument(self, doc):
        self._poke()

    def slotRedoDocument(self, doc):
        self._poke()


def _forget(observer):
    try:
        App.removeDocumentObserver(observer)
    except Exception as _fw_err:
        _fw_log("displaymanager.py:762", _fw_err)
