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
from PySide import QtCore

V = App.Vector
SIZE = 8.0


class CameraObject:
    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyVector", "Position", "Camera", "Where the camera stands")
        obj.addProperty("App::PropertyVector", "Target", "Camera", "The point it looks at")
        obj.addProperty("App::PropertyAngle", "FieldOfView", "Camera", "How wide it sees (vertically)")
        obj.FieldOfView = 45.0
        obj.Target = V(0, 0, 0)
        obj.Position = V(100, -100, 100)
        _more_properties(obj)

    def execute(self, obj):
        import Part
        d = obj.Target - obj.Position
        if d.Length < 1e-9:
            d = V(0, 0, -1)
        d.normalize()
        side = d.cross(V(0, 0, 1))
        if side.Length < 1e-6:
            side = d.cross(V(0, 1, 0))
        side.normalize()
        up = side.cross(d)
        r = math.radians(roll(obj))
        if r:
            side, up = side * math.cos(r) + up * math.sin(r), up * math.cos(r) - side * math.sin(r)
        half = SIZE * math.tan(math.radians(float(obj.FieldOfView) / 2.0))
        base = obj.Position + d * SIZE
        corners = [base + side * sx * half * 1.33 + up * sy * half for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
        apex = obj.Position
        edges = [Part.LineSegment(apex, c).toShape() for c in corners]
        edges += [Part.LineSegment(corners[i], corners[(i + 1) % 4]).toShape() for i in range(4)]
        obj.Shape = Part.Compound(edges)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class CameraView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return "view-perspective"

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        edit_camera(vobj.Object)
        return True

    def unsetEdit(self, vobj, mode=0):
        return None

    def doubleClicked(self, vobj):
        edit_camera(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None



LENSES = (("24mm", 24.0), ("35mm", 35.0), ("50mm", 50.0), ("85mm", 85.0), ("135mm", 135.0))
CUSTOM = "Custom angle"


def lens_angle(mm):
    return math.degrees(2.0 * math.atan(12.0 / mm))


def lens_of(angle):
    return next((name for name, mm in LENSES if abs(lens_angle(mm) - float(angle)) < 0.05), CUSTOM)


def _more_properties(obj):
    """Perspective, Roll, Floating and Lock camera position (cameras saved before they came look as
    they did: perspective, no roll, aimed at the target, not locked)."""
    if not hasattr(obj, "Perspective"):
        obj.addProperty("App::PropertyBool", "Perspective", "Camera", "Off: the camera sees orthographic")
        obj.Perspective = True
    if not hasattr(obj, "Roll"):
        obj.addProperty("App::PropertyAngle", "Roll", "Camera", "Turn of the camera about its line of sight")
    if not hasattr(obj, "Floating"):
        obj.addProperty("App::PropertyBool", "Floating", "Camera",
                        "Camera Type: on, Floating (moving it moves the target too); off, Aimed at target")
    if not hasattr(obj, "LockPosition"):
        obj.addProperty("App::PropertyBool", "LockPosition", "Camera",
                        "Lock camera position except when editing: in Camera View the view cannot move it")


def perspective(obj):
    return bool(getattr(obj, "Perspective", True))


def roll(obj):
    return float(getattr(obj, "Roll", 0.0))


def add_camera(doc, view=None):
    """A Camera object standing where view's camera stands and looking where it looks."""
    obj = doc.addObject("Part::FeaturePython", "Camera")
    CameraObject(obj)
    if App.GuiUp:
        CameraView(obj.ViewObject)
        obj.ViewObject.LineColor = (0.2, 0.2, 0.2)
        try:
            obj.ViewObject.ShowInTree = False
        except Exception as _fw_err:
            _fw_log("cameras.py:107", _fw_err)
    if view is not None:
        from pivy import coin
        cam = view.getCameraNode()
        pos = V(*cam.position.getValue())
        look = cam.orientation.getValue().multVec(coin.SbVec3f(0, 0, -1))
        look = V(look[0], look[1], look[2])
        dist = cam.focalDistance.getValue()
        target = pos + look * dist
        if hasattr(cam, "heightAngle"):
            obj.FieldOfView = math.degrees(cam.heightAngle.getValue())
        else:
            # an orthographic view: its eye can sit right at (or inside) the model, so the camera stands
            # back from the target as far as a 45 degree lens needs to see what the view shows
            height = cam.height.getValue() if hasattr(cam, "height") else 2.0 * dist
            dist = max(height / 2.0 / math.tan(math.radians(float(obj.FieldOfView) / 2.0)), 1.0)
            pos = target - look * dist
        obj.Position = pos
        obj.Target = target
    obj.Label = "Camera%d" % (1 + sum(1 for o in doc.Objects if is_camera(o) and o is not obj))
    doc.recompute()
    return obj


def _lonlat(d):
    ""
    n = d.Length or 1.0
    return math.degrees(math.atan2(d.x, -d.y)), math.degrees(math.asin(max(-1.0, min(1.0, d.z / n))))


def _from_lonlat(lon, lat, length):
    lo, la = math.radians(lon), math.radians(lat)
    return V(math.cos(la) * math.sin(lo), -math.cos(la) * math.cos(lo), math.sin(la)) * length


def _picked_point(doc, obj, sub, pnt):
    """The point picked on a vertex, edge or face: a vertex is its own point, else where it was clicked."""
    if sub and sub.split(".")[-1].startswith("Vertex"):
        try:
            return V(App.getDocument(doc).getObject(obj).getSubObject(sub).Point)
        except Exception as _fw_err:
            _fw_log("cameras.py:vertex", _fw_err)
    return V(*pnt)


class CameraPanel:
    ""






    def __init__(self, obj, new=False):
        from PySide import QtWidgets
        self.obj, self.new = obj, new
        _more_properties(obj)
        self.start = (V(obj.Position), V(obj.Target), float(obj.FieldOfView), perspective(obj), roll(obj),
                      bool(obj.Floating), bool(obj.LockPosition))
        self.view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
        self._busy = False
        self.picking = None          # "Target" or "Position" while its by-selection box is on
        form = QtWidgets.QWidget()
        form.setObjectName("SWCameraPM")
        form.setWindowTitle(obj.Label)
        form.setProperty("swstyle_pm_title", obj.Label)
        form.setProperty("swstyle_pm_icon", "FW_ViewCameras")      # a camera, not the name's initial
        lay = QtWidgets.QVBoxLayout(form)
        kind = QtWidgets.QGroupBox("Camera Type")
        kl = QtWidgets.QVBoxLayout(kind)
        self.aimed = QtWidgets.QRadioButton("Aimed at target")
        self.floating = QtWidgets.QRadioButton("Floating")
        (self.floating if obj.Floating else self.aimed).setChecked(True)
        self.aimed.setToolTip("Moving the camera keeps it looking at the target point.")
        self.floating.setToolTip("Moving the camera moves the target with it: it keeps looking the same way.")
        self.floating.toggled.connect(lambda *a: self.changed("Floating"))
        self.numeric = QtWidgets.QCheckBox("Show numeric controls")
        self.numeric.setObjectName("SWCameraNumeric")
        self.numeric.setChecked(_numeric())
        self.numeric.toggled.connect(self._show_numbers)
        self.lock = QtWidgets.QCheckBox("Lock camera position except when editing")
        self.lock.setObjectName("SWCameraLock")
        self.lock.setToolTip("On: in Camera View, turning or moving the view does not move the camera.\n"
                             "Off: the camera follows the view.")
        self.lock.setChecked(bool(obj.LockPosition))
        self.lock.toggled.connect(lambda *a: self.changed("LockPosition"))
        for w in (self.aimed, self.floating, self.numeric, self.lock):
            kl.addWidget(w)
        lay.addWidget(kind)
        self.boxes, self.by_sel, self.picked, self.numbers = {}, {}, {}, {}
        for title, prop, check in (("Target Point", "Target", "Target by selection"),
                                   ("Camera Position", "Position", "Position by selection")):
            group = QtWidgets.QGroupBox(title)
            gl = QtWidgets.QVBoxLayout(group)
            by = QtWidgets.QCheckBox(check)
            by.setObjectName("SWCamera%sBySelection" % prop)
            by.setToolTip("Pick a vertex, edge or face in the graphics area: the %s goes to the picked point."
                          % ("target" if prop == "Target" else "camera"))
            by.toggled.connect(lambda on, prop=prop: self._by_selection(prop, on))
            gl.addWidget(by)
            self.by_sel[prop] = by
            picked = QtWidgets.QLineEdit()
            picked.setObjectName("SWCamera%sPicked" % prop)
            picked.setReadOnly(True)
            picked.setPlaceholderText("Pick a vertex, edge or face")
            picked.setVisible(False)
            gl.addWidget(picked)
            self.picked[prop] = picked
            numbers = QtWidgets.QWidget()
            g = QtWidgets.QGridLayout(numbers)
            g.setContentsMargins(0, 0, 0, 0)
            value = getattr(obj, prop)
            row = []
            first = 0
            if prop == "Position":
                self.spherical = QtWidgets.QRadioButton("Spherical")
                self.spherical.setObjectName("SWCameraSpherical")
                self.cartesian = QtWidgets.QRadioButton("Cartesian")
                self.cartesian.setObjectName("SWCameraCartesian")
                self.spherical.setChecked(True)
                g.addWidget(self.spherical, 0, 0)
                g.addWidget(self.cartesian, 0, 1)
                self.spherical.toggled.connect(self._coords)
                first = 1
                self.pages = QtWidgets.QStackedWidget()
                cart, sph = QtWidgets.QWidget(), QtWidgets.QWidget()
                cg, sg = QtWidgets.QGridLayout(cart), QtWidgets.QGridLayout(sph)
                for x in (cg, sg):
                    x.setContentsMargins(0, 0, 0, 0)
                self.pages.addWidget(cart)
                self.pages.addWidget(sph)
                self.cart_page, self.sph_page = cart, sph
                g.addWidget(self.pages, 1, 0, 1, 2)
                self.sph = {}
                d = obj.Position - obj.Target
                lon, lat = _lonlat(d)
                for i, (key, label, low, high, v, suffix) in enumerate(
                        (("Lon", "Longitude:", -180.0, 180.0, lon, "°"), ("Lat", "Latitude:", -90.0, 90.0, lat, "°"),
                         ("Dist", "Distance:", 0.0, 1e7, d.Length, " mm"))):
                    box = QtWidgets.QDoubleSpinBox()
                    box.setObjectName("SWCamera" + key)
                    box.setRange(low, high)
                    box.setDecimals(2)
                    box.setSuffix(suffix)
                    box.setValue(v)
                    box.valueChanged.connect(lambda *a: self.changed("Spherical"))
                    sg.addWidget(QtWidgets.QLabel(label), i, 0)
                    sg.addWidget(box, i, 1)
                    self.sph[key] = box
                g, first = cg, 0
            for i, axis in enumerate("XYZ"):
                box = QtWidgets.QDoubleSpinBox()
                box.setObjectName("SWCamera%s%s" % (prop, axis))
                box.setRange(-1e7, 1e7)
                box.setDecimals(2)
                box.setSuffix(" mm")
                box.setValue(getattr(value, axis.lower()))
                box.valueChanged.connect(lambda *a, prop=prop: self.changed(prop))
                g.addWidget(QtWidgets.QLabel(axis + ":"), first + i, 0)
                g.addWidget(box, first + i, 1)
                row.append(box)
            self.boxes[prop] = row
            gl.addWidget(numbers)
            self.numbers[prop] = numbers
            lay.addWidget(group)
        self._coords()
        turn = QtWidgets.QGroupBox("Camera Rotation")
        tg = QtWidgets.QGridLayout(turn)
        self.roll = QtWidgets.QDoubleSpinBox()
        self.roll.setObjectName("SWCameraRoll")
        self.roll.setRange(-180.0, 180.0)
        self.roll.setDecimals(1)
        self.roll.setSuffix("°")
        self.roll.setValue(roll(obj))
        self.roll.setToolTip("Roll: turns the camera about its line of sight.")
        self.roll.valueChanged.connect(lambda *a: self.changed("Roll"))
        tg.addWidget(QtWidgets.QLabel("Roll:"), 0, 0)
        tg.addWidget(self.roll, 0, 1)
        lay.addWidget(turn)
        fov = QtWidgets.QGroupBox("Field of View")
        fg = QtWidgets.QGridLayout(fov)
        self.perspective = QtWidgets.QCheckBox("Perspective")
        self.perspective.setObjectName("SWCameraPerspective")
        self.perspective.setChecked(perspective(obj))
        self.perspective.toggled.connect(lambda *a: self.changed("Perspective"))
        fg.addWidget(self.perspective, 0, 0, 1, 2)
        self.lens = QtWidgets.QComboBox()
        self.lens.setObjectName("SWCameraLens")
        self.lens.addItems([name for name, mm in LENSES] + [CUSTOM])
        self.lens.setCurrentText(lens_of(obj.FieldOfView))
        self.lens.activated.connect(self._lens_picked)
        self.lens.currentIndexChanged.connect(self._lens_picked)
        fg.addWidget(self.lens, 1, 0, 1, 2)
        self.angle = QtWidgets.QDoubleSpinBox()
        self.angle.setObjectName("SWCameraAngle")
        self.angle.setRange(1.0, 170.0)
        self.angle.setDecimals(1)
        self.angle.setSuffix("°")
        self.angle.setValue(float(obj.FieldOfView))
        self.angle.valueChanged.connect(lambda *a: self.changed("FieldOfView"))
        self.distance = QtWidgets.QDoubleSpinBox()
        self.distance.setObjectName("SWCameraDistance")
        self.distance.setRange(0.01, 1e7)
        self.distance.setDecimals(2)
        self.distance.setSuffix(" mm")
        self.distance.setToolTip("Distance from the camera to the target: the camera moves along its line of sight.")
        self.distance.valueChanged.connect(lambda *a: self.changed("Distance"))
        self.height = QtWidgets.QDoubleSpinBox()
        self.height.setObjectName("SWCameraHeight")
        self.height.setRange(0.01, 1e7)
        self.height.setDecimals(2)
        self.height.setSuffix(" mm")
        self.height.setToolTip("Height of the view rectangle at the target: sets the angle.")
        self.height.valueChanged.connect(lambda *a: self.changed("Height"))
        for r, (label, box) in enumerate((("Angle:", self.angle), ("Distance to target:", self.distance),
                                          ("Height of view rectangle:", self.height))):
            fg.addWidget(QtWidgets.QLabel(label), 2 + r, 0)
            fg.addWidget(box, 2 + r, 1)
        lay.addWidget(fov)
        lay.addStretch(1)
        self.form = form
        self._show_numbers(self.numeric.isChecked())
        self._show()
        _PANEL["open"] = self

    # ---------------------------------------------------------------- by selection
    def _by_selection(self, prop, on):
        other = "Position" if prop == "Target" else "Target"
        if on:
            self.by_sel[other].setChecked(False)
            self.picking = prop
            Gui.Selection.clearSelection()
            if self not in _OBSERVERS:
                Gui.Selection.addObserver(self)
                _OBSERVERS.append(self)
        elif self.picking == prop:
            self.picking = None
        self.picked[prop].setVisible(on)

    def addSelection(self, doc, obj, sub, pnt):
        if self.picking is None:
            return
        try:
            point = _picked_point(doc, obj, sub, pnt)
            prop = self.picking
            label = App.getDocument(doc).getObject(obj).Label
            from . import pmboxes
            self.picked[prop].setText(pmboxes.sw_name("%s of %s" % (sub.split(".")[-1], label) if sub else label))
            self._set_boxes(prop, point)
            self.changed(prop)
        except Exception as _fw_err:
            _fw_log("cameras.py:pick", _fw_err)

    def _unobserve(self):
        if self in _OBSERVERS:
            try:
                Gui.Selection.removeObserver(self)
            except Exception as _fw_err:
                _fw_log("cameras.py:observer", _fw_err)
            _OBSERVERS.remove(self)

    # ---------------------------------------------------------------- numbers
    def _show_numbers(self, on):
        from .viewextras import PARAMS
        App.ParamGet(PARAMS).SetBool("CameraNumericControls", bool(on))
        for w in self.numbers.values():
            w.setVisible(bool(on))

    def _coords(self, *args):
        self.pages.setCurrentWidget(self.sph_page if self.spherical.isChecked() else self.cart_page)

    def _lens_picked(self, *args):
        name = self.lens.currentText()
        mm = next((m for n, m in LENSES if n == name), None)
        if mm is not None and abs(self.angle.value() - lens_angle(mm)) > 0.05:
            self.angle.setValue(lens_angle(mm))

    def _vec(self, prop):
        return V(*(b.value() for b in self.boxes[prop]))

    @staticmethod
    def _quiet(box, value):
        box.blockSignals(True)
        box.setValue(value)
        box.blockSignals(False)

    def _set_boxes(self, prop, v):
        for b, x in zip(self.boxes[prop], (v.x, v.y, v.z)):
            self._quiet(b, x)

    def from_object(self):
        """The boxes show the camera as it is (after the view moved it, in Camera View)."""
        o = self.obj
        self._set_boxes("Position", o.Position)
        self._set_boxes("Target", o.Target)
        self._show()

    def changed(self, prop):
        if self._busy:
            return
        self._busy = True
        try:
            o = self.obj
            if prop == "Spherical":
                pos = self._vec("Target") + _from_lonlat(self.sph["Lon"].value(), self.sph["Lat"].value(),
                                                         self.sph["Dist"].value())
                self._set_boxes("Position", pos)      # round the target, which stays
            elif prop == "Distance":
                look = o.Target - o.Position
                if look.Length > 1e-9:
                    look.normalize()
                    self._set_boxes("Position", o.Target - look * self.distance.value())
                # the target stays: the camera moves along its line of sight
            elif prop == "Height":
                d = max((o.Target - o.Position).Length, 1e-9)
                self._quiet(self.angle, max(1.0, min(170.0, math.degrees(2.0 * math.atan(self.height.value() / 2.0 / d)))))
            if prop == "Position" and self.floating.isChecked():
                move = self._vec("Position") - o.Position
                o.Target = o.Target + move
                self._set_boxes("Target", o.Target)
            o.Position, o.Target = self._vec("Position"), self._vec("Target")
            o.FieldOfView = self.angle.value()
            o.Perspective = self.perspective.isChecked()
            o.Roll = self.roll.value()
            o.Floating = self.floating.isChecked()
            o.LockPosition = self.lock.isChecked()
            if prop in ("FieldOfView", "Height"):
                self.lens.blockSignals(True)
                self.lens.setCurrentText(lens_of(o.FieldOfView))
                self.lens.blockSignals(False)
            o.recompute()
            self._show()
        finally:
            self._busy = False

    def _show(self):
        o = self.obj
        d = o.Position - o.Target
        self._quiet(self.distance, max(d.Length, 0.01))
        self._quiet(self.height, max(2.0 * d.Length * math.tan(math.radians(float(o.FieldOfView)) / 2.0), 0.01))
        if hasattr(self, "sph"):
            lon, lat = _lonlat(d)
            self._quiet(self.sph["Lon"], lon)
            self._quiet(self.sph["Lat"], lat)
            self._quiet(self.sph["Dist"], d.Length)
        if self.view is not None:
            try:
                look_through(self.view, o)
            except Exception as _fw_err:
                _fw_log("cameras.py:225", _fw_err)

    def getStandardButtons(self):
        from PySide import QtWidgets
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        self._unobserve()
        _PANEL.pop("open", None)
        Gui.Control.closeDialog()
        if self.view is not None:
            leave(self.view)

    def accept(self):
        if self.new:
            self.obj.Document.commitTransaction()
        self._close()
        return True

    def reject(self):
        doc = self.obj.Document
        if self.new:
            doc.abortTransaction()
        else:
            p, t, f, persp, r, floating, lock = self.start
            self.obj.Position, self.obj.Target, self.obj.FieldOfView = p, t, f
            self.obj.Perspective, self.obj.Roll = persp, r
            self.obj.Floating, self.obj.LockPosition = floating, lock
            doc.recompute()
        self._close()
        return True


_PANEL = {}          # "open" -> the Camera PropertyManager open now
_OBSERVERS = []


def _numeric():
    ""
    from .viewextras import PARAMS
    return App.ParamGet(PARAMS).GetBool("CameraNumericControls", False)


def edit_camera(obj, new=False):
    panel = CameraPanel(obj, new=new)
    Gui.Control.showDialog(panel)
    return panel


def is_camera(obj):
    return type(getattr(obj, "Proxy", None)).__name__ == "CameraObject"


_saved = {}         # view id -> the camera as it was before Camera View
_looking = {}       # view id -> (document name, camera name, the view's camera as last put)
FOLLOW_MS = 250


def _view_state(view):
    cam = view.getCameraNode()
    size = cam.heightAngle.getValue() if hasattr(cam, "heightAngle") else cam.height.getValue()
    return tuple(cam.position.getValue()) + tuple(cam.orientation.getValue().getValue()) + (size,)


def _same(a, b):
    return a is not None and b is not None and len(a) == len(b) and all(abs(x - y) < 1e-4 * max(1.0, abs(x)) for x, y in zip(a, b))


def _follow(view):
    ""

    from pivy import coin
    key = id(view)
    entry = _looking.get(key)
    if entry is None or key not in _saved:
        return
    doc_name, cam_name, last = entry
    doc = App.listDocuments().get(doc_name)
    obj = doc.getObject(cam_name) if doc is not None else None
    try:
        now = _view_state(view)
    except Exception:
        _looking.pop(key, None)          # the view closed
        _saved.pop(key, None)
        return
    if obj is None:
        _looking.pop(key, None)
        return
    if not _same(now, last):
        panel = _PANEL.get("open")
        if bool(getattr(obj, "LockPosition", False)) and (panel is None or panel.obj is not obj):
            look_through(view, obj)
        else:
            _take(view, obj)
            if panel is not None and panel.obj is obj:
                panel.from_object()
            else:
                look_through(view, obj)
    QtCore.QTimer.singleShot(FOLLOW_MS, lambda: _follow(view))


def _take(view, obj):
    """The Camera object stands, looks and sees as the view's camera does now."""
    from pivy import coin
    cam = view.getCameraNode()
    pos = V(*cam.position.getValue())
    rot = cam.orientation.getValue()
    look = rot.multVec(coin.SbVec3f(0, 0, -1))
    look = V(look[0], look[1], look[2])
    dist = (obj.Target - obj.Position).Length if getattr(obj, "Floating", False) else cam.focalDistance.getValue()
    target = pos + look * max(dist, 1e-6)
    obj.Position, obj.Target = pos, target
    if hasattr(cam, "heightAngle"):
        obj.FieldOfView = math.degrees(cam.heightAngle.getValue())
    # the roll: the turn of the view's up from the up a camera at no roll would have
    plain = coin.SoPerspectiveCamera()
    plain.position.setValue(pos.x, pos.y, pos.z)
    up = V(0, 0, 1) if abs(look.z) < 0.99 else V(0, 1, 0)
    plain.pointAt(coin.SbVec3f(target.x, target.y, target.z), coin.SbVec3f(up.x, up.y, up.z))
    a = plain.orientation.getValue().multVec(coin.SbVec3f(0, 1, 0))
    b = rot.multVec(coin.SbVec3f(0, 1, 0))
    a, b = V(a[0], a[1], a[2]), V(b[0], b[1], b[2])
    r = math.degrees(math.atan2(a.cross(b).dot(look * -1.0), a.dot(b)))
    obj.Roll = r
    obj.recompute()


def look_through(view, camera):
    from pivy import coin
    key = id(view)
    if key not in _saved:
        _saved[key] = view.getCamera()
    persp = perspective(camera)
    view.setCameraType("Perspective" if persp else "Orthographic")
    cam = view.getCameraNode()
    p, t = camera.Position, camera.Target
    cam.position.setValue(p.x, p.y, p.z)
    d = t - p
    up = V(0, 0, 1) if abs(V(d).normalize().z) < 0.99 else V(0, 1, 0)
    cam.pointAt(coin.SbVec3f(t.x, t.y, t.z), coin.SbVec3f(up.x, up.y, up.z))
    r = math.radians(roll(camera))
    if r:
        cam.orientation.setValue(coin.SbRotation(coin.SbVec3f(0, 0, 1), r) * cam.orientation.getValue())
    cam.focalDistance.setValue(d.Length)
    half = math.radians(float(camera.FieldOfView)) / 2.0
    if persp:
        cam.heightAngle.setValue(2.0 * half)
    else:
        cam.height.setValue(2.0 * d.Length * math.tan(half))     # what the lens sees at the target
    following = key in _looking
    _looking[key] = (camera.Document.Name, camera.Name, _view_state(view))
    if not following:
        QtCore.QTimer.singleShot(FOLLOW_MS, lambda: _follow(view))


def leave(view):
    _looking.pop(id(view), None)
    saved = _saved.pop(id(view), None)
    if saved is not None:
        view.setCamera(saved)
        return True
    return False


def through(view):
    return id(view) in _saved


class _Add:
    def GetResources(self):
        return {"Pixmap": "view-perspective", "MenuText": "Add Camera",
                "ToolTip": "Adds a camera standing where the view's eye is, looking where it looks",
                "CmdType": "ForEdit"}      # extapps77: also while a sketch is open

    def IsActive(self):
        return Gui.ActiveDocument is not None

    def Activated(self):
        doc = App.ActiveDocument
        doc.openTransaction("Add Camera")
        try:
            obj = add_camera(doc, Gui.ActiveDocument.ActiveView)
        except Exception:
            doc.abortTransaction()
            raise
        try:
            edit_camera(obj, new=True)
        except Exception as error:
            doc.commitTransaction()
            App.Console.PrintWarning("FreeCAD: Camera PropertyManager: %s\n" % error)


class _View:
    def GetResources(self):
        return {"Pixmap": "view-perspective", "MenuText": "Camera View",
                "ToolTip": "Looks through the picked camera; again goes back to the view as it was"}

    def IsActive(self):
        return App.ActiveDocument is not None and Gui.ActiveDocument is not None     # never greyed

    def Activated(self):
        view = Gui.ActiveDocument.ActiveView
        if leave(view):
            return
        picked = [o for o in Gui.Selection.getSelection() if is_camera(o)]
        cams = picked or [o for o in App.ActiveDocument.Objects if is_camera(o)]
        if cams:
            look_through(view, cams[0])
        elif not Gui.Control.activeDialog():
            Gui.runCommand("SWStyle_AddCamera", 0)      # no camera yet: Add Camera, then the view looks through it


def register():
    if "SWStyle_AddCamera" not in Gui.listCommands():
        Gui.addCommand("SWStyle_AddCamera", _Add())
    if "SWStyle_CameraView" not in Gui.listCommands():
        Gui.addCommand("SWStyle_CameraView", _View())
