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
import os
import shutil
import subprocess
import tempfile

import FreeCAD as App

try:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets
    from . import events
except ImportError:
    Gui = None

PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/View"
V = App.Vector


def _view():
    try:
        view = Gui.ActiveDocument.ActiveView
        return view if hasattr(view, "getCameraNode") else None
    except Exception:
        return None


def _sheet_widget():
    """mbar-1126: the drawing sheet's picture area, for Record Video on a sheet."""
    try:
        from . import drawextras
        w = drawextras.page_view_widget()
        return w.viewport() if w is not None and hasattr(w, "viewport") else w
    except Exception:
        return None


def _gl(view=None):
    view = view or _view()
    try:
        widget = view.getViewer().getGLWidget()
        if widget is not None:
            return widget
    except Exception as _fw_err:
        _fw_log("viewextras.py:58", _fw_err)
    try:
        from . import overridedrag
        cls = overridedrag._gl_class()
        area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = area.activeSubWindow() if area is not None else None
        scope = sub if sub is not None else Gui.getMainWindow()
        found = [w for w in scope.findChildren(QtWidgets.QWidget) if isinstance(w, cls) and w.isVisible()]
        if found:
            return max(found, key=lambda w: w.width() * w.height())
    except Exception as _fw_err:
        _fw_log("viewextras.py:69", _fw_err)
    return None


# --------------------------------------------------------------------- Rotate / Pan / Roll
def _focal(cam):
    from pivy import coin
    q = cam.orientation.getValue()
    direction = q.multVec(coin.SbVec3f(0, 0, -1))
    pos = coin.SbVec3f(cam.position.getValue())
    return pos + direction * cam.focalDistance.getValue(), q


def rotate(view, dx, dy, degrees_per_pixel=0.4):
    """Orbits the camera round its focal point: sideways about the view's up, up/down about its right."""
    from pivy import coin
    cam = view.getCameraNode()
    focal, q = _focal(cam)
    up = q.multVec(coin.SbVec3f(0, 1, 0))
    right = q.multVec(coin.SbVec3f(1, 0, 0))
    r = coin.SbRotation(up, math.radians(-dx * degrees_per_pixel)) * \
        coin.SbRotation(right, math.radians(-dy * degrees_per_pixel))
    nq = q * r
    direction = nq.multVec(coin.SbVec3f(0, 0, -1))
    cam.orientation.setValue(nq)
    cam.position.setValue(focal - direction * cam.focalDistance.getValue())


def _world_per_pixel(view, cam):
    widget = _gl(view)
    h = max(1, widget.height() if widget is not None else 600)
    if cam.getTypeId().getName() == "OrthographicCamera":
        return cam.height.getValue() / h
    return 2 * cam.focalDistance.getValue() * math.tan(cam.heightAngle.getValue() / 2) / h


def pan(view, dx, dy):
    """Moves the camera sideways with the pointer: the model follows the drag."""
    from pivy import coin
    cam = view.getCameraNode()
    q = cam.orientation.getValue()
    s = _world_per_pixel(view, cam)
    right = q.multVec(coin.SbVec3f(1, 0, 0))
    up = q.multVec(coin.SbVec3f(0, 1, 0))
    pos = coin.SbVec3f(cam.position.getValue())
    cam.position.setValue(pos - right * (dx * s) + up * (dy * s))


def roll(view, dx, degrees_per_pixel=0.4):
    """Turns the view about the line of sight."""
    from pivy import coin
    cam = view.getCameraNode()
    q = cam.orientation.getValue()
    axis = coin.SbVec3f(0, 0, 1)
    cam.orientation.setValue(q * coin.SbRotation(q.multVec(axis), math.radians(dx * degrees_per_pixel)))


if Gui is not None:
    class DragMode(QtCore.QObject):
        """While on, a left drag in the graphics area rotates, pans or rolls the view."""
        current = None
        HINT = {"rotate": "Rotate: drag to rotate the view; Esc ends",
                "pan": "Pan: drag to move the view; Esc ends",
                "roll": "Roll: drag sideways to roll the view; Esc ends"}

        def __init__(self, kind):
            super().__init__()
            self.kind = kind
            self.last = None
            events.register("viewextras-mode", (QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseMove,), self.eventFilter)
            try:
                Gui.getMainWindow().statusBar().showMessage(self.HINT[kind], 0)
            except Exception as _fw_err:
                _fw_log("viewextras.py:142", _fw_err)

        @classmethod
        def toggle(cls, kind):
            if cls.current is not None:
                same = cls.current.kind == kind
                cls.current.stop()
                if same:
                    return None
            cls.current = cls(kind)
            return cls.current

        def stop(self):
            try:
                events.unregister("viewextras-mode")
            except Exception as _fw_err:
                _fw_log("viewextras.py:158", _fw_err)
            try:
                Gui.getMainWindow().statusBar().clearMessage()
            except Exception as _fw_err:
                _fw_log("viewextras.py:162", _fw_err)
            if DragMode.current is self:
                DragMode.current = None

        def drag(self, dx, dy):
            view = _view()
            if view is None:
                return
            if self.kind == "rotate":
                rotate(view, dx, dy)
            elif self.kind == "pan":
                pan(view, dx, dy)
            else:
                roll(view, dx)

        def eventFilter(self, obj, event):
            if not isinstance(event, QtCore.QEvent):
                return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
            from . import overridedrag
            t = event.type()
            QE = QtCore.QEvent
            if t == QE.KeyPress and event.key() == QtCore.Qt.Key_Escape:
                self.stop()
                return True
            if not isinstance(obj, overridedrag._gl_class()):
                return False
            if t == QE.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self.last = event.position()
                obj.setCursor(QtGui.QCursor(QtCore.Qt.ClosedHandCursor if self.kind == "pan" else QtCore.Qt.SizeAllCursor))
                return True
            if t == QE.MouseMove and self.last is not None:
                p = event.position()
                dx, dy = p.x() - self.last.x(), p.y() - self.last.y()
                self.last = p
                try:
                    self.drag(dx, dy)
                except Exception as _fw_err:
                    _fw_log("viewextras.py:199", _fw_err)
                return True
            if t == QE.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton and self.last is not None:
                self.last = None
                obj.unsetCursor()
                return True
            return False


# --------------------------------------------------------------------- Record Video
def _ffmpeg():
    return shutil.which("ffmpeg")


class Recorder:
    """Grabs the graphics area into numbered pictures at a steady rate; Stop makes the video."""

    def __init__(self):
        self.timer = None
        self.frames = 0
        self.folder = None
        self.target = None
        self.fps = 10

    @property
    def on(self):
        return self.timer is not None

    def start(self, target, fps=10):
        self.stop(make=False)
        self.target = target
        self.fps = fps
        self.folder = tempfile.mkdtemp(prefix="fwvideo")
        self.frames = 0
        self.timer = QtCore.QTimer()
        self.timer.setInterval(int(1000 / fps))
        self.timer.timeout.connect(self.grab)
        self.timer.start()
        self.grab()
        try:
            Gui.getMainWindow().statusBar().showMessage("Recording video: View > Screen Capture > Stop Video Record ends", 4000)
        except Exception as _fw_err:
            _fw_log("viewextras.py:241", _fw_err)

    def grab(self):
        widget = _gl() or _sheet_widget()
        if widget is None:
            return
        try:
            image = widget.grabFramebuffer()
        except Exception:
            image = widget.grab().toImage()
        # video encoders want even sizes
        w, h = image.width() // 2 * 2, image.height() // 2 * 2
        image.copy(0, 0, w, h).save(os.path.join(self.folder, "frame%05d.png" % self.frames))
        self.frames += 1

    def stop(self, make=True):
        """Ends the recording; returns the file written (the video, or the pictures' folder)."""
        if self.timer is None:
            return None
        self.timer.stop()
        self.timer = None
        if not make or not self.frames:
            return None
        ff = _ffmpeg()
        if ff and not self.target.lower().endswith(os.sep):
            try:
                subprocess.run([ff, "-y", "-loglevel", "error", "-framerate", str(self.fps), "-i",
                                os.path.join(self.folder, "frame%05d.png"), "-pix_fmt", "yuv420p", self.target],
                               check=True, timeout=600)
                shutil.rmtree(self.folder, ignore_errors=True)
                return self.target
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: the video could not be made (%s); the frames are kept\n" % error)
        out = os.path.splitext(self.target)[0] + "_frames"
        if os.path.exists(out):
            out = out + "_%d" % len(os.listdir(os.path.dirname(out) or "."))
        shutil.move(self.folder, out)
        return out


RECORDER = Recorder()


# --------------------------------------------------------------------- Lights
LIGHT_KINDS = ("Directional", "Point", "Spot", "Sun")


class LightObject:
    """A scene light kept in the document."""

    def __init__(self, obj, kind):
        obj.addProperty("App::PropertyEnumeration", "LightKind", "Light", "Directional, Point, Spot or Sun")
        obj.LightKind = list(LIGHT_KINDS)
        obj.LightKind = kind
        obj.addProperty("App::PropertyBool", "On", "Light", "The light shines").On = True
        obj.addProperty("App::PropertyColor", "Color", "Light", "The light's color").Color = (1.0, 1.0, 1.0)
        obj.addProperty("App::PropertyPercent", "Brightness", "Light", "How bright, 0-100").Brightness = 35
        obj.addProperty("App::PropertyVector", "Direction", "Light", "Where a directional or spot light points")
        obj.Direction = V(-1, -1, -1)
        obj.addProperty("App::PropertyVector", "Location", "Light", "Where a point or spot light stands")
        obj.Location = V(100, 100, 100)
        obj.addProperty("App::PropertyAngle", "ConeAngle", "Light", "A spot light's cone").ConeAngle = 30
        obj.addProperty("App::PropertyAngle", "Azimuth", "Sun", "The sun's compass direction").Azimuth = 135
        obj.addProperty("App::PropertyAngle", "Elevation", "Sun", "The sun's height above the floor").Elevation = 45
        _more(obj)
        obj.Proxy = self

    def execute(self, obj):
        sync(obj.Document)

    def onChanged(self, obj, prop):
        if prop in ("On", "Color", "Brightness", "Direction", "Location", "ConeAngle", "Azimuth", "Elevation", "LightKind",
                    "LockToModel", "Ambient", "Specularity"):
            sync(obj.Document)

    def dumps(self):
        return None

    def loads(self, _state):
        return None


def _more(obj):
    ""

    if not hasattr(obj, "LockToModel"):
        obj.addProperty("App::PropertyBool", "LockToModel", "Light",
                        "On: the light keeps its place on the model as the view turns; off: its place in the view")
    try:
        from . import lightterms
        lightterms.add_properties(obj)
    except Exception as _fw_err:
        _fw_log("viewextras.py:terms", _fw_err)


def is_light(obj):
    return isinstance(getattr(obj, "Proxy", None), LightObject)


def lights(doc):
    return [o for o in doc.Objects if is_light(o)] if doc is not None else []


def _folder(doc):
    for obj in doc.Objects:
        if obj.TypeId == "App::DocumentObjectGroup" and getattr(obj, "SWLightsFolder", False):
            return obj
    group = doc.addObject("App::DocumentObjectGroup", "Lights")
    group.addProperty("App::PropertyBool", "SWLightsFolder", "FreeCAD", "")
    group.setEditorMode("SWLightsFolder", 2)
    group.SWLightsFolder = True
    return group



_DEFAULT_NAMES = ("Ambient", "Directional1", "Directional2", "Directional3")


def _next_name(doc, kind, obj=None):
    ""

    taken = set(_DEFAULT_NAMES) | {o.Label for o in lights(doc) if o is not obj}
    n = 1
    while "%s%d" % (kind, n) in taken:
        n += 1
    return "%s%d" % (kind, n)


def add_light(doc, kind, transaction=True):
    if transaction:
        doc.openTransaction("Add %s Light" % kind if kind != "Sun" else "Add Sunlight")
    try:
        obj = doc.addObject("App::FeaturePython", "Sunlight" if kind == "Sun" else "%sLight" % kind)
        LightObject(obj, kind)
        obj.Label = "Sunlight" if kind == "Sun" else _next_name(doc, kind, obj)
        if Gui is not None:
            obj.ViewObject.Proxy = 0
        _folder(doc).addObject(obj)
        doc.recompute()
    finally:
        if transaction:
            doc.commitTransaction()
    sync(doc)
    return obj


def delete_light(obj):
    doc = obj.Document
    doc.openTransaction("Delete Light")
    try:
        doc.removeObject(obj.Name)
    finally:
        doc.commitTransaction()
    sync(doc)


def _sun_direction(obj):
    az, el = math.radians(float(obj.Azimuth)), math.radians(float(obj.Elevation))
    # the sun shines down towards the floor from its compass direction
    return V(-math.cos(el) * math.cos(az), -math.cos(el) * math.sin(az), -math.sin(el))


_NODES = {}          # document name -> [(viewer root, SoGroup)]


def _light_node(obj):
    from pivy import coin
    kind = obj.LightKind
    if kind in ("Directional", "Sun"):
        node = coin.SoDirectionalLight()
        d = _sun_direction(obj) if kind == "Sun" else obj.Direction
        node.direction.setValue(d.x, d.y, d.z)
    elif kind == "Point":
        node = coin.SoPointLight()
        node.location.setValue(obj.Location.x, obj.Location.y, obj.Location.z)
    else:
        node = coin.SoSpotLight()
        node.location.setValue(obj.Location.x, obj.Location.y, obj.Location.z)
        node.direction.setValue(obj.Direction.x, obj.Direction.y, obj.Direction.z)
        node.cutOffAngle.setValue(math.radians(float(obj.ConeAngle)))
    node.color.setValue(*obj.Color[:3])
    node.intensity.setValue(obj.Brightness / 100.0)
    node.on.setValue(bool(obj.On) and shown_lights(obj.Document))
    return node


def _views(doc):
    out = []
    try:
        gdoc = Gui.getDocument(doc.Name)
        for view in gdoc.mdiViewsOfType("Gui::View3DInventor"):
            out.append(view)
    except Exception as _fw_err:
        _fw_log("viewextras.py:403", _fw_err)
    return out


def sync(doc):
    """Puts the document's lights at the top of every 3D view's scene."""
    if Gui is None or doc is None:
        return
    from pivy import coin
    open_names = set(App.listDocuments())
    for name in [doc.Name] + [n for n in _NODES if n not in open_names]:
        for root, group in _NODES.pop(name, []):
            try:
                root.removeChild(group)
            except Exception as _fw_err:
                _fw_log("viewextras.py:418", _fw_err)
            for node in (group, root):
                try:
                    node.unref()            # taken in the loop below; closed documents' roots go too
                except Exception as _fw_err:
                    _fw_log("viewextras.py:423", _fw_err)
    items = lights(doc)
    if not items:
        return
    held = []
    for view in _views(doc):
        try:
            root = view.getViewer().getSoRenderManager().getSceneGraph()
        except Exception:
            try:
                root = view.getSceneGraph()
            except Exception as _fw_err:
                _fw_log("viewextras.py:436", _fw_err)
                continue
        group = coin.SoGroup()
        group.setName("FreeWorksLights")
        for obj in items:
            # the light and, right after it, its Ambient and Specularity (lightterms.py); a plain group
            # keeps the light shining on what follows
            pair = coin.SoGroup()
            node = _light_node(obj)
            pair.addChild(node)
            try:
                from . import lightterms
                pair.addChild(lightterms.callback(node, lambda d=doc.Name, n=obj.Name: lightterms.named_terms(d, n),
                                                  ("light", doc.Name, obj.Name)))
            except Exception as _fw_err:
                _fw_log("viewextras.py:termsnode", _fw_err)
            group.addChild(pair)
        root.insertChild(group, 0)
        root.ref()
        group.ref()
        held.append((root, group))
        locked = [i for i, o in enumerate(items) if getattr(o, "LockToModel", False)]
        if locked:          # Lock to model: after the camera, in the model's scene, so they turn with it
            try:
                model = view.getSceneGraph()
                near = coin.SoGroup()
                near.setName(group.getName())
                for i in locked:
                    near.addChild(group.getChild(i))
                for i in reversed(locked):
                    group.removeChild(i)
                model.insertChild(near, 0)
                model.ref()
                near.ref()
                held.append((model, near))
            except Exception as _fw_err:
                _fw_log("viewextras.py:lockedlights", _fw_err)
    _NODES[doc.Name] = held


_HIDDEN_LIGHTS = set()


def shown_lights(doc):
    return doc is not None and doc.Name not in _HIDDEN_LIGHTS


def set_lights_shown(doc, on):
    if on:
        _HIDDEN_LIGHTS.discard(doc.Name)
    else:
        _HIDDEN_LIGHTS.add(doc.Name)
    sync(doc)


if Gui is not None:
    def _lonlat(d):
        ""
        n = d.Length or 1.0
        return (math.degrees(math.atan2(d.x, -d.y)), math.degrees(math.asin(max(-1.0, min(1.0, d.z / n)))))

    def _from_lonlat(lon, lat, length=1.0):
        lo, la = math.radians(lon), math.radians(lat)
        return V(math.cos(la) * math.sin(lo), -math.cos(la) * math.cos(lo), math.sin(la)) * length

    class LightPanel:
        ""






        def __init__(self, obj, new=False, done=None):
            _more(obj)
            self.obj, self.new, self.done = obj, new, done
            self.doc = obj.Document
            self._busy = False
            if not new:
                self.doc.openTransaction("Edit Light")
            kind = obj.LightKind
            form = QtWidgets.QWidget()
            form.setObjectName("SWLightProperties")
            form.setWindowTitle(obj.Label)
            form.setProperty("swstyle_pm_title", obj.Label)
            form.setProperty("swstyle_pm_icon", "FW_DM_%sLight" % kind)    # the light's kind (displaymanager.LIGHT_ICONS)
            lay = QtWidgets.QVBoxLayout(form)
            basic = QtWidgets.QGroupBox("Basic")
            g = QtWidgets.QGridLayout(basic)
            self.on = QtWidgets.QCheckBox("On in FreeCAD")
            self.on.setObjectName("SWLightOn")
            self.on.setChecked(bool(obj.On))
            self.on.toggled.connect(self._live)
            g.addWidget(self.on, 0, 0, 1, 3)
            self.colour = QtWidgets.QPushButton("Edit Color...")
            self.colour.setObjectName("SWLightColor")
            self.colour.clicked.connect(self._pick_colour)
            g.addWidget(self.colour, 1, 0, 1, 3)

            from . import lightterms
            lightterms.add_properties(obj)
            self.ambient = lightterms.percent_row(g, 2, "Ambient:", obj.Ambient, lambda v: self._live(), "SWLightAmbient")
            self.specularity = lightterms.percent_row(g, 4, "Specularity:", obj.Specularity, lambda v: self._live(),
                                                      "SWLightSpecularity")
            g.addWidget(QtWidgets.QLabel("Brightness:"), 3, 0)
            self.bright = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.bright.setObjectName("SWLightBrightness")
            self.bright.setRange(0, 100)
            self.bright_spin = QtWidgets.QSpinBox()
            self.bright_spin.setRange(0, 100)
            self.bright_spin.setSuffix(" %")
            self.bright.setValue(int(obj.Brightness))
            self.bright_spin.setValue(int(obj.Brightness))
            self.bright.valueChanged.connect(self.bright_spin.setValue)
            self.bright_spin.valueChanged.connect(self.bright.setValue)
            self.bright_spin.valueChanged.connect(self._live)
            g.addWidget(self.bright, 3, 1)
            g.addWidget(self.bright_spin, 3, 2)
            lay.addWidget(basic)
            place = QtWidgets.QGroupBox("Light Position")
            self.grid = pg = QtWidgets.QGridLayout(place)
            self.lock = QtWidgets.QCheckBox("Lock to model")
            self.lock.setObjectName("SWLightLockToModel")
            self.lock.setToolTip("On: the light keeps its place on the model as the view turns.\n"
                                 "Off: the light keeps its place in the view.")
            self.lock.setChecked(bool(obj.LockToModel))
            self.lock.toggled.connect(self._live)
            pg.addWidget(self.lock, 0, 0, 1, 2)
            self.row = 1
            self.spins = {}
            self.spherical = self.cartesian = None
            if kind == "Directional":
                lon, lat = _lonlat(-V(obj.Direction))
                self._spin("Longitude", "Longitude:", -180, 180, lon, "°", 1)
                self._spin("Latitude", "Latitude:", -90, 90, lat, "°", 1)
            elif kind == "Sun":
                self._spin("Azimuth", "Azimuth:", 0, 360, float(obj.Azimuth), "°", 1)
                self._spin("Elevation", "Elevation:", 0, 90, float(obj.Elevation), "°", 1)
            else:
                self.spherical = QtWidgets.QRadioButton("Spherical")
                self.spherical.setObjectName("SWLightSpherical")
                self.cartesian = QtWidgets.QRadioButton("Cartesian")
                self.cartesian.setObjectName("SWLightCartesian")
                self.cartesian.setChecked(True)
                pg.addWidget(self.spherical, self.row, 0)
                pg.addWidget(self.cartesian, self.row, 1)
                self.row += 1
                self.spherical.toggled.connect(self._coords)
                loc = V(obj.Location)
                source = "Source " if kind == "Spot" else ""
                self.cart_box = self._rows()
                for axis in "XYZ":
                    self._spin(axis, "%s%s:" % (source, axis), -1e6, 1e6, getattr(loc, axis.lower()), " mm", 2)
                lon, lat = _lonlat(loc)
                self.sph_box = self._rows()
                self._spin("Lon", "Longitude:", -180, 180, lon, "°", 1)
                self._spin("Lat", "Latitude:", -90, 90, lat, "°", 1)
                self._spin("Dist", "Distance:", 0, 1e6, loc.Length, " mm", 2)
                self._rows(None)
                if kind == "Spot":
                    target = loc + V(obj.Direction)
                    for axis in "XYZ":
                        self._spin("T" + axis, "Target %s:" % axis, -1e6, 1e6, getattr(target, axis.lower()), " mm", 2)
                    self._spin("ConeAngle", "Cone angle:", 1, 90, float(obj.ConeAngle), "°", 1)
                self._coords()
            lay.addWidget(place)
            lay.addStretch(1)
            self.form = form
            self._swatch()

        def _rows(self, box=True):
            """The next rows go on a page of their own (Spherical or Cartesian: one page shows at a
            time, in the same place); _rows(None) goes back to the Light Position group's own rows."""
            if not hasattr(self, "main"):
                self.main = self.grid
                self.pages = QtWidgets.QStackedWidget()
                self.pages.setObjectName("SWLightCoordinates")
                self.main.addWidget(self.pages, self.row, 0, 1, 2)
                self.row += 1
            if box is None:
                self.grid = self.main
                return None
            box = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(box)
            grid.setContentsMargins(0, 0, 0, 0)
            self.pages.addWidget(box)
            self.grid = grid
            return box

        def _spin(self, key, label, low, high, value, suffix, decimals):
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName("SWLight" + key)
            s.setRange(low, high)
            s.setDecimals(decimals)
            s.setSuffix(suffix)
            s.setValue(value)
            s.valueChanged.connect(lambda *a, k=key: self._live(k))
            text = QtWidgets.QLabel(label)
            if self.grid is self.main_grid():
                at = self.row
                self.row += 1
            else:
                at = self.grid.count() // 2
            self.grid.addWidget(text, at, 0)
            self.grid.addWidget(s, at, 1)
            self.spins[key] = (s, text)
            return s

        def main_grid(self):
            return getattr(self, "main", self.grid)

        def _coords(self, *_):
            """Spherical shows Longitude, Latitude and Distance for the light's place; Cartesian X, Y, Z."""
            sph = bool(self.spherical is not None and self.spherical.isChecked())
            self.pages.setCurrentWidget(self.sph_box if sph else self.cart_box)

        def _set(self, key, value):
            s = self.spins[key][0]
            s.blockSignals(True)
            s.setValue(value)
            s.blockSignals(False)

        def _value(self, key):
            return self.spins[key][0].value()

        def _swatch(self):
            pix = QtGui.QPixmap(14, 14)
            pix.fill(QtGui.QColor.fromRgbF(*self.obj.Color[:3]))
            self.colour.setIcon(QtGui.QIcon(pix))

        def _pick_colour(self):
            c = QtWidgets.QColorDialog.getColor(QtGui.QColor.fromRgbF(*self.obj.Color[:3]), self.form, "Edit Color")
            if c.isValid():
                self.obj.Color = (c.redF(), c.greenF(), c.blueF())
                self._swatch()
                self._live()

        def _live(self, key=None):
            if self._busy:
                return
            self._busy = True
            try:
                o = self.obj
                o.On = self.on.isChecked()
                o.Brightness = int(self.bright_spin.value())
                o.Ambient = int(self.ambient.value())
                o.Specularity = int(self.specularity.value())
                o.LockToModel = self.lock.isChecked()
                kind = o.LightKind
                if kind == "Directional":
                    o.Direction = -_from_lonlat(self._value("Longitude"), self._value("Latitude"))
                elif kind == "Sun":
                    o.Azimuth, o.Elevation = self._value("Azimuth"), self._value("Elevation")
                elif kind in ("Point", "Spot"):
                    old = V(o.Location)
                    target = old + V(o.Direction) if kind == "Spot" else None
                    if key in ("Lon", "Lat", "Dist"):
                        loc = _from_lonlat(self._value("Lon"), self._value("Lat"), self._value("Dist"))
                        for axis in "XYZ":
                            self._set(axis, getattr(loc, axis.lower()))
                    else:
                        loc = V(self._value("X"), self._value("Y"), self._value("Z"))
                        lon, lat = _lonlat(loc)
                        self._set("Lon", lon)
                        self._set("Lat", lat)
                        self._set("Dist", loc.Length)
                    o.Location = loc
                    if kind == "Spot":
                        target = V(self._value("TX"), self._value("TY"), self._value("TZ"))
                        d = target - loc
                        o.Direction = d if d.Length > 1e-9 else V(o.Direction)
                        o.ConeAngle = self._value("ConeAngle")
                sync(self.doc)
            except Exception as _fw_err:
                _fw_log("viewextras.py:lightpm", _fw_err)
            finally:
                self._busy = False

        def getStandardButtons(self):
            return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

        def _close(self):
            Gui.Control.closeDialog()
            sync(self.doc)
            if self.done is not None:
                try:
                    self.done()
                except Exception as _fw_err:
                    _fw_log("viewextras.py:lightdone", _fw_err)

        def accept(self):
            self._live()
            self.doc.commitTransaction()
            self._close()
            return True

        def reject(self):
            self.doc.abortTransaction()       # the light as it was (a light just added goes)
            self._close()
            return True

    def edit_light(obj, new=False, done=None):
        """Opens the light's PropertyManager in the task pane (after any open one closes)."""
        panel = LightPanel(obj, new=new, done=done)
        Gui.Control.showDialog(panel)
        return panel

    def add_and_edit(kind, done=None):
        """Add Directional / Point / Spot Light, Add Sunlight: the new light and its PropertyManager."""
        doc = App.ActiveDocument
        if doc is None or Gui.Control.activeDialog():
            return None
        doc.openTransaction("Add Sunlight" if kind == "Sun" else "Add %s Light" % kind)
        try:
            obj = add_light(doc, kind, transaction=False)
            return edit_light(obj, new=True, done=done)
        except Exception:
            doc.abortTransaction()
            raise

    class PerspectiveDialog(QtWidgets.QDialog):
        """View > Modify > Perspective...: the observer's distance, in object sizes."""

        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.setWindowTitle("Perspective View")
            self.setObjectName("SWPerspectiveDialog")
            form = QtWidgets.QFormLayout(self)
            self.distance = QtWidgets.QDoubleSpinBox()
            self.distance.setRange(1.0, 50.0)
            self.distance.setSingleStep(0.5)
            self.distance.setValue(App.ParamGet(PARAMS).GetFloat("ObserverDistance", 2.0))
            form.addRow("Observer position (object sizes away)", self.distance)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            form.addRow(buttons)

        def accept(self):
            set_perspective(self.distance.value())
            super().accept()

    class ZebraDialog(QtWidgets.QDialog):
        """Zebra Stripe Properties: the number of stripes, live."""

        def __init__(self):
            super().__init__(Gui.getMainWindow())
            from . import evaluate2
            self.zebra = evaluate2.ZEBRA
            self.setWindowTitle("Zebra Stripes")
            self.setObjectName("SWZebraProperties")
            form = QtWidgets.QFormLayout(self)
            self.count = QtWidgets.QSlider(QtCore.Qt.Horizontal)
            self.count.setRange(2, 40)
            self.count.setValue(int(self.zebra.stripes))
            self.count.valueChanged.connect(self._changed)
            form.addRow("Number of stripes", self.count)
            buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
            buttons.accepted.connect(self.accept)
            form.addRow(buttons)
            if not self.zebra.on:
                self.zebra.show()

        def _changed(self, n):
            self.zebra.stripes = n
            App.ParamGet(PARAMS).SetInt("ZebraStripes", n)
            if self.zebra.on:
                self.zebra.show()


def set_perspective(distance):
    ""
    App.ParamGet(PARAMS).SetFloat("ObserverDistance", distance)
    view = _view()
    if view is None:
        return
    try:
        view.setCameraType("Perspective")
    except Exception as _fw_err:
        _fw_log("viewextras.py:632", _fw_err)
    try:
        view.fitAll()
    except Exception as _fw_err:
        _fw_log("viewextras.py:636", _fw_err)
    cam = view.getCameraNode()
    try:
        # the same picture size, seen from further away or nearer
        old = cam.heightAngle.getValue()
        new = 2 * math.atan(0.5 / max(distance, 0.1))
        span = cam.focalDistance.getValue() * math.tan(old / 2)
        focal, q = _focal(cam)
        from pivy import coin
        direction = q.multVec(coin.SbVec3f(0, 0, -1))
        far = span / math.tan(new / 2)
        cam.heightAngle.setValue(new)
        cam.focalDistance.setValue(far)
        cam.position.setValue(focal - direction * far)
    except Exception as _fw_err:
        _fw_log("viewextras.py:651", _fw_err)


# --------------------------------------------------------------------- commands
if Gui is not None:
    def _has_view():
        return _view() is not None

    def _record():
        start = App.ParamGet(PARAMS).GetString("VideoFolder", os.path.expanduser("~"))
        path, _f = QtWidgets.QFileDialog.getSaveFileName(Gui.getMainWindow(), "Record Video",
                                                         os.path.join(start, "video.mp4"), "Video (*.mp4 *.avi)")
        if path:
            App.ParamGet(PARAMS).SetString("VideoFolder", os.path.dirname(path))
            RECORDER.start(path)

    def _stop_record():
        out = RECORDER.stop()
        if out:
            try:
                Gui.getMainWindow().statusBar().showMessage("Video saved: %s" % out, 8000)
            except Exception as _fw_err:
                _fw_log("viewextras.py:673", _fw_err)

    class _Cmd:
        def __init__(self, text, tip, active, run, checked=None):
            self.text, self.tip, self.active, self.run, self.checked = text, tip, active, run, checked

        def GetResources(self):
            out = {"MenuText": self.text, "ToolTip": self.tip, "CmdType": "ForEdit"}
            if self.checked is not None:
                out["Checkable"] = bool(self.checked())
            return out

        def IsActive(self):
            try:
                return bool(self.active())
            except Exception:
                return False

        def Activated(self, *_checked):
            self.run()

    def _kind_mode(kind):
        return lambda: DragMode.current is not None and DragMode.current.kind == kind

    COMMANDS = [
        ("SWStyle_RecordVideo", "Record Video...", "Records the graphics area as a video.",
         lambda: (_has_view() or _sheet_widget() is not None) and not RECORDER.on, _record, None),
        ("SWStyle_StopVideoRecord", "Stop Video Record", "Ends the recording and saves the video.",
         lambda: RECORDER.on, _stop_record, None),
        ("SWStyle_ViewRotate", "Rotate", "Drag to rotate the view.", _has_view,
         lambda: DragMode.toggle("rotate"), _kind_mode("rotate")),
        ("SWStyle_ViewPan", "Pan", "Drag to move the view.", _has_view,
         lambda: DragMode.toggle("pan"), _kind_mode("pan")),
        ("SWStyle_ViewRoll", "Roll", "Drag sideways to roll the view about the line of sight.", _has_view,
         lambda: DragMode.toggle("roll"), _kind_mode("roll")),
        ("SWStyle_PerspectiveSettings", "Perspective...", "Sets how far away the observer stands in perspective.",
         _has_view, lambda: PerspectiveDialog().exec_(), None),
        ("SWStyle_ZebraProperties", "Zebra Stripe Properties...", "Sets the zebra stripes.",
         _has_view, lambda: _zebra_properties(ZebraDialog), None),
    ]
    for kind, text in (("Directional", "Add Directional Light"), ("Point", "Add Point Light"),
                       ("Spot", "Add Spot Light"), ("Sun", "Add Sunlight")):
        COMMANDS.append(("SWStyle_Add%sLight" % kind, text, "Adds a light to the scene.",
                         lambda: App.ActiveDocument is not None and not Gui.Control.activeDialog(),
                         lambda kind=kind: add_and_edit(kind), None))

    def lights_menu(menu, what):
        ""


        menu.clear()
        if what == "properties" and Gui.Control.activeDialog():
            return
        items = lights(App.ActiveDocument)
        if what == "properties":
            try:
                from . import displaymanager
                for name, _prefix, _node in displaymanager.LIGHTS:
                    act = menu.addAction(name)
                    act.triggered.connect(lambda _c=False, n=name: displaymanager.edit_light(n))
            except Exception as _fw_err:
                _fw_log("viewextras.py:lightsmenu", _fw_err)
        for obj in items:
            act = menu.addAction(obj.Label)
            if what == "properties":
                act.triggered.connect(lambda _c=False, o=obj: edit_light(o))
            else:
                act.triggered.connect(lambda _c=False, o=obj: delete_light(o))


def add_types():
    """Hide/Show > Cameras, Lights, Parting Lines, Markups."""
    from . import cameras, viewtypes
    types = viewtypes.TYPES
    types.setdefault("Cameras", ("Cameras", "Shows or hides the cameras.", cameras.is_camera))
    types.setdefault("PartingLines", ("Parting Lines", "Shows or hides the parting lines.",
                                      lambda o: getattr(o, "SWStyleKind", "") == "PartingLine"))
    types.setdefault("Markups", ("Markups", "Shows or hides the markups.",
                                 lambda o: type(getattr(o, "Proxy", None)).__name__ == "MarkupObject"))


class _Watch:
    def slotCreatedDocument(self, doc):
        pass

    def slotFinishRestoreDocument(self, doc):
        if lights(doc) and Gui is not None:
            QtCore.QTimer.singleShot(500, lambda name=doc.Name: sync(App.listDocuments().get(name)))


_watch = None


def register():
    global _watch
    if Gui is None:
        return
    try:
        add_types()
        from . import checkstate, viewtypes
        for key in ("Cameras", "PartingLines", "Markups"):
            name = "SWStyle_View" + key
            if Gui.Command.get(name) is None:
                Gui.addCommand(name, viewtypes._TypeCmd(key))
                checkstate.register(name, lambda key=key: App.ActiveDocument is not None and viewtypes.shown(key))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hide/Show types not added (%s)\n" % error)
    for name, text, tip, active, run, checked in COMMANDS:
        try:
            if name not in Gui.listCommands():
                Gui.addCommand(name, _Cmd(text, tip, active, run, checked))
                if checked is not None:
                    from . import checkstate
                    checkstate.register(name, checked)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added (%s)\n" % (text, error))
    if "SWStyle_ViewLights" not in Gui.listCommands():
        class _LightsShown:
            def GetResources(self):
                return {"MenuText": "Lights", "ToolTip": "Turns the added lights on and off.",
                        "Checkable": True, "CmdType": "ForEdit"}

            def IsActive(self):
                return App.ActiveDocument is not None

            def Activated(self, checked):
                set_lights_shown(App.ActiveDocument, bool(checked))
        Gui.addCommand("SWStyle_ViewLights", _LightsShown())
        from . import checkstate
        checkstate.register("SWStyle_ViewLights", lambda: shown_lights(App.ActiveDocument))
    if _watch is None:
        _watch = _Watch()
        App.addDocumentObserver(_watch)
        # FreeCAD 1.1 sends no restore signals to Python: restorehook reports opened files instead
        from . import restorehook
        restorehook.on_restored(_watch.slotFinishRestoreDocument)


def _zebra_properties(fallback):
    ""

    try:
        from . import evalpanel
        cur = evalpanel._open[0] if getattr(evalpanel, "_open", None) else None
        if cur is not None and getattr(cur, "NAME", "") == "SWStyle_ZebraStripes":
            return
        if Gui is not None and not Gui.Control.activeDialog():
            if evalpanel.open_panel("SWStyle_ZebraStripes") is not None:
                return
    except Exception as _fw_err:
        _fw_log("viewextras.py:zebra-1121", _fw_err)
    fallback().exec_()
