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

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import contextbar, sketchtoolpm
from .widgets import alive

COMMAND = "SWStyle_SketchPicture"
NATIVE = "Std_ViewLoadImage"
FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.svg)"
DPI = 96.0


def default_size(path):
    img = QtGui.QImage(path)
    if img.isNull():
        return 100.0, 100.0
    return img.width() * 25.4 / DPI, img.height() * 25.4 / DPI


def place(sketch, picture, x, y, angle_deg, width, height, flip_h=False, flip_v=False):
    """Puts the picture's lower left corner at (x, y) of the sketch, turned by angle, at the size;
    a flip mirrors it (a half turn about its own vertical or horizontal axis)."""
    picture.XSize = max(1e-6, width)
    picture.YSize = max(1e-6, height)
    a = math.radians(angle_deg)
    cx = x + (width / 2.0) * math.cos(a) - (height / 2.0) * math.sin(a)
    cy = y + (width / 2.0) * math.sin(a) + (height / 2.0) * math.cos(a)
    rot = App.Rotation(App.Vector(0, 0, 1), angle_deg)
    if flip_h:
        rot = rot.multiply(App.Rotation(App.Vector(0, 1, 0), 180))
    if flip_v:
        rot = rot.multiply(App.Rotation(App.Vector(1, 0, 0), 180))
    local = App.Placement(App.Vector(cx, cy, 0.01 if (flip_h != flip_v) else -0.01), rot)
    picture.Placement = sketch.getGlobalPlacement().multiply(local)
    picture.recompute()


def _set(picture, **values):
    for k, v in values.items():
        key = "SW" + k
        if key not in picture.PropertiesList:
            picture.addProperty("App::PropertyFloat" if isinstance(v, float) else "App::PropertyBool", key,
                                "Sketch Picture", "Sketch Picture " + k)
        setattr(picture, key, v)


def _get(picture, key, default):
    return getattr(picture, "SW" + key, default)


def source_file(picture):
    """The picture's own file (the shown file may be a copy with a colour keyed out)."""
    src = getattr(picture, "SWSource", "")
    return src if src and os.path.isfile(src) else picture.ImageFile


def _keep_source(picture):
    ""

    src = getattr(picture, "SWSource", "")
    if src and os.path.isfile(src):
        return src
    import shutil
    now = picture.ImageFile
    keep = os.path.join(_cache_dir(), "%s-%s" % (picture.Name, os.path.basename(now)))
    shutil.copyfile(now, keep)
    if "SWSource" not in picture.PropertiesList:
        picture.addProperty("App::PropertyString", "SWSource", "Sketch Picture", "The picture's own file")
    picture.SWSource = keep
    return keep


def _cache_dir():
    path = os.path.join(App.getUserAppDataDir(), "FreeWorks", "pictures")
    os.makedirs(path, exist_ok=True)
    return path


def _rgb(c):
    return (c >> 16) & 255, (c >> 8) & 255, c & 255


def colour_distance(a, b):
    """0 (same colour) to 100 (black against white)."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b))) / (math.sqrt(3) * 255.0) * 100.0


def keyed_image(path, colour, tolerance, transparency, flatten=False):
    ""


    img = QtGui.QImage(path).convertToFormat(QtGui.QImage.Format_ARGB32)
    alpha = int(round(255 * (1.0 - transparency / 100.0)))
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixel(x, y)
            a = 255 if flatten else (c >> 24) & 255
            if colour is not None and colour_distance(_rgb(c), colour) <= tolerance:
                a = min(a, alpha)
            img.setPixel(x, y, (a << 24) | (c & 0xFFFFFF))
    tag = "flat" if colour is None else "%02x%02x%02x-%d-%d" % (colour + (int(tolerance), int(transparency)))
    out = os.path.join(_cache_dir(), "%s-%s.png" % (os.path.splitext(os.path.basename(path))[0], tag))
    img.save(out, "PNG")
    return out


def set_transparency(picture, mode, value=0, colour=None, tolerance=10.0):
    ""


    src = _keep_source(picture)
    if "SWTransparencyMode" not in picture.PropertiesList:
        picture.addProperty("App::PropertyString", "SWTransparencyMode", "Sketch Picture", "Transparency")
    picture.SWTransparencyMode = mode
    shown, whole = src, 0
    if mode == "None":
        has_alpha = QtGui.QImage(src).hasAlphaChannel()
        shown = keyed_image(src, None, 0, 0, flatten=True) if has_alpha else src
    elif mode == "Full image":
        whole = int(value)
    elif mode == "User defined" and colour is not None:
        shown = keyed_image(src, tuple(colour), tolerance, value)
        _set(picture, KeyTolerance=float(tolerance), KeyTransparency=float(value))
        if "SWKeyColour" not in picture.PropertiesList:
            picture.addProperty("App::PropertyString", "SWKeyColour", "Sketch Picture", "User defined colour")
        picture.SWKeyColour = "%d,%d,%d" % tuple(colour)
    if os.path.basename(picture.ImageFile) != os.path.basename(shown) or mode != "From file":
        picture.ImageFile = shown
    try:
        picture.ViewObject.Transparency = whole
    except Exception as _fw_err:
        _fw_log("sketchpicture.py:158", _fw_err)


def picture_to_sketch(picture, u, v, w, h):
    """The sketch point at pixel (u, v) (from the top left) of a w x h pixel image of picture."""
    width, height = _get(picture, "Width", 1.0), _get(picture, "Height", 1.0)
    x, y = u / float(w) * width, (1.0 - v / float(h)) * height
    if _get(picture, "FlipH", False):
        x = width - x
    if _get(picture, "FlipV", False):
        y = height - y
    a = math.radians(_get(picture, "Angle", 0.0))
    return App.Vector(_get(picture, "X", 0.0) + x * math.cos(a) - y * math.sin(a),
                      _get(picture, "Y", 0.0) + x * math.sin(a) + y * math.cos(a), 0)


def sketch_to_picture(picture, p, w, h):
    """Inverse of picture_to_sketch: pixel (u, v) of the sketch point p."""
    width, height = _get(picture, "Width", 1.0), _get(picture, "Height", 1.0)
    a = math.radians(_get(picture, "Angle", 0.0))
    dx, dy = p.x - _get(picture, "X", 0.0), p.y - _get(picture, "Y", 0.0)
    x = dx * math.cos(a) + dy * math.sin(a)
    y = -dx * math.sin(a) + dy * math.cos(a)
    if _get(picture, "FlipH", False):
        x = width - x
    if _get(picture, "FlipV", False):
        y = height - y
    return x / width * w, (1.0 - y / height) * h


# ------------------------------------------------------------------ Autotrace
TRACE_PX = 320           # the picture is traced at most this many pixels across


def trace_image(path):
    img = QtGui.QImage(path)
    if img.isNull():
        raise ValueError("The picture's file cannot be read")
    if max(img.width(), img.height()) > TRACE_PX:
        img = img.scaled(TRACE_PX, TRACE_PX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return img.convertToFormat(QtGui.QImage.Format_ARGB32)


def colour_mask(img, colour, tolerance, box=None):
    """{(x, y)} of the pixels within tolerance of colour (and inside box (x0, y0, x1, y1))."""
    x0, y0, x1, y1 = box or (0, 0, img.width(), img.height())
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(img.width(), int(math.ceil(x1))), min(img.height(), int(math.ceil(y1)))
    out = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            c = img.pixel(x, y)
            if (c >> 24) & 255 > 20 and colour_distance(_rgb(c), colour) <= tolerance:
                out.add((x, y))
    return out


def outlines(mask):
    """The closed outlines round the mask's areas, as loops of pixel-corner points."""
    nxt = {}
    for x, y in mask:
        # edges with the area on their left, going round it counterclockwise on screen
        if (x, y - 1) not in mask:
            nxt.setdefault((x + 1, y), []).append((x, y))
        if (x, y + 1) not in mask:
            nxt.setdefault((x, y + 1), []).append((x + 1, y + 1))
        if (x - 1, y) not in mask:
            nxt.setdefault((x, y), []).append((x, y + 1))
        if (x + 1, y) not in mask:
            nxt.setdefault((x + 1, y + 1), []).append((x + 1, y))
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, at = [start], start
        while True:
            ends = nxt.get(at)
            if not ends:
                break
            to = ends.pop()
            if not ends:
                del nxt[at]
            if to == start:
                break
            loop.append(to)
            at = to
        if len(loop) >= 4:
            loops.append(loop)
    return loops


def _simplify(points, tol):
    """Douglas-Peucker on an open run of points."""
    if len(points) < 3:
        return list(points)
    (ax, ay), (bx, by) = points[0], points[-1]
    dx, dy = bx - ax, by - ay
    norm = math.hypot(dx, dy)
    worst, at = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        d = abs(dy * (px - ax) - dx * (py - ay)) / norm if norm > 1e-12 else math.hypot(px - ax, py - ay)
        if d > worst:
            worst, at = d, i
    if worst <= tol:
        return [points[0], points[-1]]
    return _simplify(points[:at + 1], tol)[:-1] + _simplify(points[at:], tol)


def _off_line(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = math.hypot(dx, dy)
    if norm < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    return abs(dy * (p[0] - a[0]) - dx * (p[1] - a[1])) / norm


def simplify_loop(loop, tol):
    """A closed loop with the corners that matter to within tol pixels (the loop's first point,
    where it was cut open, is dropped too when it is no corner)."""
    far = max(range(len(loop)), key=lambda i: (loop[i][0] - loop[0][0]) ** 2 + (loop[i][1] - loop[0][1]) ** 2)
    a = _simplify(loop[:far + 1], tol)
    b = _simplify(loop[far:] + loop[:1], tol)
    pts = a[:-1] + b[:-1]
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            if _off_line(pts[i], pts[i - 1], pts[(i + 1) % len(pts)]) <= tol * 0.5:
                del pts[i]
                changed = True
                break
    return pts


def _area(loop):
    return abs(sum(loop[i][0] * loop[i - 1][1] - loop[i - 1][0] * loop[i][1] for i in range(len(loop)))) / 2.0


def trace(picture, colour, tolerance=10.0, identification=1.5, smallest=4.0, box=None):
    """Autotrace: the outlines of the picture's areas of colour, as loops of sketch points.
    identification: how far (pixels) the lines may stray from the outline; smallest: areas under
    this many pixels are left out. box: (x0, y0, x1, y1) pixels to trace inside."""
    img = trace_image(source_file(picture))
    mask = colour_mask(img, colour, tolerance, box)
    w, h = img.width(), img.height()
    out = []
    for loop in outlines(mask):
        if _area(loop) < smallest:
            continue
        pts = simplify_loop(loop, identification)
        if len(pts) >= 3:
            out.append([picture_to_sketch(picture, u, v, w, h) for u, v in pts])
    return out


def add_loops(sketch, loops):
    """The loops as closed runs of lines, each corner held Coincident. Returns the new geometry ids."""
    import Part
    import Sketcher
    ids, cons = [], []
    for loop in loops:
        first = None
        prev = None
        for i, a in enumerate(loop):
            b = loop[(i + 1) % len(loop)]
            if (b - a).Length < 1e-9:
                continue
            g = sketch.addGeometry(Part.LineSegment(a, b))
            ids.append(g)
            if prev is not None:
                cons.append(Sketcher.Constraint("Coincident", prev, 2, g, 1))
            else:
                first = g
            prev = g
        if first is not None and prev is not None and prev != first:
            cons.append(Sketcher.Constraint("Coincident", prev, 2, first, 1))
    if cons:
        sketch.addConstraint(cons)
    return ids


def hidden_link(picture, sketch=None):
    ""

    sketch = sketch if sketch is not None else getattr(picture, "SWSketch", None)
    if "SWSketch" in picture.PropertiesList and picture.getTypeIdOfProperty("SWSketch") != "App::PropertyLinkHidden":
        picture.removeProperty("SWSketch")
    if "SWSketch" not in picture.PropertiesList:
        picture.addProperty("App::PropertyLinkHidden", "SWSketch", "Sketch Picture", "The sketch the picture lies on")
    if picture.SWSketch is not sketch:
        picture.SWSketch = sketch


def add_picture(sketch, path):
    doc = sketch.Document
    picture = doc.addObject("Image::ImagePlane", "SketchPicture")
    picture.Label = "Sketch Picture " + os.path.basename(path)
    picture.ImageFile = path
    w, h = default_size(path)
    _set(picture, X=0.0, Y=0.0, Angle=0.0, Width=w, Height=h, FlipH=False, FlipV=False)
    hidden_link(picture, sketch)
    place(sketch, picture, 0.0, 0.0, 0.0, w, h)
    return picture


# ------------------------------------------------------------------ dragging the picture (PM open)
HANDLES = [(hx, hy) for hx in (0.0, 0.5, 1.0) for hy in (0.0, 0.5, 1.0) if (hx, hy) != (0.5, 0.5)]


def to_local(x0, y0, angle_deg, p):
    """Sketch point p in the picture's own frame (lower left corner at 0, 0, unturned)."""
    a = math.radians(angle_deg)
    dx, dy = p.x - x0, p.y - y0
    return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)


def hit(state, p, tol):
    ""

    x0, y0, ang, w, h = state
    x, y = to_local(x0, y0, ang, p)
    best = None
    for hx, hy in HANDLES:
        d = math.hypot(x - hx * w, y - hy * h)
        if d <= tol and (best is None or d < best[0]):
            best = (d, (hx, hy))
    if best:
        return best[1]
    if -tol <= x <= w + tol and -tol <= y <= h + tol:
        return "move"
    return None


def dragged(state, grab, p0, p1, lock):
    """The picture's X, Y, W, H after dragging grab from sketch point p0 to p1 (Angle is kept)."""
    x0, y0, ang, w, h = state
    if grab == "move":
        return x0 + p1.x - p0.x, y0 + p1.y - p0.y, w, h
    hx, hy = grab
    qx, qy = to_local(x0, y0, ang, p1)
    nw = abs(qx - (1 - hx) * w) if hx != 0.5 else w
    nh = abs(qy - (1 - hy) * h) if hy != 0.5 else h
    if lock:
        k = max(nw / w if hx != 0.5 else 0.0, nh / h if hy != 0.5 else 0.0)
        nw, nh = w * k, h * k
    nw, nh = max(nw, 1e-3), max(nh, 1e-3)
    left = 0.0 if hx == 1.0 else (w - nw if hx == 0.0 else (w - nw) / 2.0)
    bottom = 0.0 if hy == 1.0 else (h - nh if hy == 0.0 else (h - nh) / 2.0)
    a = math.radians(ang)
    return (x0 + left * math.cos(a) - bottom * math.sin(a), y0 + left * math.sin(a) + bottom * math.cos(a),
            nw, nh)


class SketchPicturePage(sketchtoolpm.ToolPage):
    TITLE = "Sketch Picture"
    PIXMAP = "Std_ViewLoadImage"
    TRANSACTION = "Sketch Picture"

    def __init__(self, sketch, picture=None, path=None, parent=None):
        self.picture, self.path = picture, path
        self._filling = True
        super().__init__(sketch, parent)
        self._filling = False

    def build(self):
        if self.picture is None:
            self.begin()
            self.picture = add_picture(self.sketch, self.path)
        p = self.picture
        g = self.group("Properties")
        form = QtWidgets.QFormLayout()
        self.fields = {}
        for key, label, lo, hi, suffix in (("X", "Origin X", -1e6, 1e6, "mm"), ("Y", "Origin Y", -1e6, 1e6, "mm"),
                                           ("Angle", "Angle", -360.0, 360.0, "deg"),
                                           ("Width", "Width", 1e-4, 1e6, "mm"), ("Height", "Height", 1e-4, 1e6, "mm")):
            b = QtWidgets.QDoubleSpinBox(g.body)
            b.setRange(lo, hi)
            b.setDecimals(3)
            b.setSuffix(suffix)
            b.setKeyboardTracking(False)
            b.setObjectName("SWSketchPicture" + key)
            b.setValue(_get(p, key, 0.0))
            b.valueChanged.connect(lambda v, k=key: self._changed(k))
            form.addRow(label, b)
            self.fields[key] = b
        g.content.addLayout(form)
        self.scale_tool = QtWidgets.QCheckBox("Enable scale tool", g.body)
        self.scale_tool.setObjectName("SWSketchPictureScaleTool")              # lock aspect ratio, then the flips
        self.scale_tool.setToolTip("Click two points of the picture, then type how far apart they really are")
        self.scale_tool.toggled.connect(self._scale_mode)
        g.content.addWidget(self.scale_tool)
        self.lock = QtWidgets.QCheckBox("Lock aspect ratio", g.body)
        self.lock.setObjectName("SWSketchPictureLockAspect")
        self.lock.setChecked(True)
        g.content.addWidget(self.lock)
        self.flip_h = QtWidgets.QCheckBox("Flip horizontal", g.body)
        self.flip_h.setObjectName("SWSketchPictureFlipH")
        self.flip_h.setChecked(bool(_get(p, "FlipH", False)))
        self.flip_v = QtWidgets.QCheckBox("Flip vertical", g.body)
        self.flip_v.setObjectName("SWSketchPictureFlipV")
        self.flip_v.setChecked(bool(_get(p, "FlipV", False)))
        for b in (self.flip_h, self.flip_v):
            b.toggled.connect(lambda on: self._changed(None))
            g.content.addWidget(b)
        self.scale_points = []
        self.view = None
        g = self.group("Transparency")
        self.none = QtWidgets.QRadioButton("None", g.body)
        self.none.setObjectName("SWSketchPictureTransparencyNone")
        self.from_file = QtWidgets.QRadioButton("From file", g.body)
        self.from_file.setObjectName("SWSketchPictureTransparencyFile")
        self.full = QtWidgets.QRadioButton("Full image", g.body)
        self.full.setObjectName("SWSketchPictureTransparencyFull")
        self.user = QtWidgets.QRadioButton("User defined", g.body)
        self.user.setObjectName("SWSketchPictureTransparencyUser")
        for b in (self.none, self.from_file, self.full, self.user):
            g.content.addWidget(b)
        self.colour_button = QtWidgets.QPushButton("Select color...", g.body)
        self.colour_button.setObjectName("SWSketchPictureColour")
        self.colour_button.clicked.connect(self._pick_colour)
        g.content.addWidget(self.colour_button)
        form = QtWidgets.QFormLayout()
        self.tolerance = QtWidgets.QSlider(Qt.Horizontal, g.body)
        self.tolerance.setObjectName("SWSketchPictureMatchTolerance")
        self.tolerance.setRange(0, 100)
        self.tolerance.setValue(int(_get(p, "KeyTolerance", 10.0)))
        form.addRow("Matching tolerance", self.tolerance)
        self.slider = QtWidgets.QSlider(Qt.Horizontal, g.body)
        self.slider.setObjectName("SWSketchPictureTransparency")
        self.slider.setRange(0, 100)
        form.addRow("Transparency", self.slider)
        g.content.addLayout(form)
        self.colour = None
        key = getattr(p, "SWKeyColour", "")
        if key:
            self.colour = tuple(int(c) for c in key.split(","))
        else:
            img = QtGui.QImage(source_file(p))
            if not img.isNull():
                self.colour = _rgb(img.pixel(0, 0))     # the corner's colour: usually the background
        mode = getattr(p, "SWTransparencyMode", "") or ("Full image" if self._transparency() else "From file")
        now = self._transparency() if mode == "Full image" else int(_get(p, "KeyTransparency", 100.0))
        self.slider.setValue(now)
        {"None": self.none, "From file": self.from_file, "Full image": self.full,
         "User defined": self.user}.get(mode, self.from_file).setChecked(True)
        self._enable_transparency()
        for b in (self.none, self.from_file, self.full, self.user):
            b.toggled.connect(lambda on: on and self._transparency_mode(True))
        self.slider.valueChanged.connect(self._set_transparency)
        self.tolerance.valueChanged.connect(self._set_transparency)
        g = self.group("Autotrace")
        trace_button = QtWidgets.QPushButton("Autotrace...", g.body)
        trace_button.setObjectName("SWSketchPictureAutotrace")
        trace_button.setToolTip("Keeps the picture and goes on to trace it into sketch lines")
        trace_button.clicked.connect(self.autotrace)
        g.content.addWidget(trace_button)
        self._ratio = (_get(p, "Height", 1.0) / max(1e-9, _get(p, "Width", 1.0)))
        self.drag = None
        self._watch_view()

    def _transparency(self):
        try:
            return int(self.picture.ViewObject.Transparency)
        except Exception:
            return 0

    def mode(self):
        for b, name in ((self.none, "None"), (self.from_file, "From file"), (self.full, "Full image"),
                        (self.user, "User defined")):
            if b.isChecked():
                return name
        return "From file"

    def _enable_transparency(self):
        mode = self.mode()
        self.slider.setEnabled(mode in ("Full image", "User defined"))
        for w in (self.colour_button, self.tolerance):
            w.setEnabled(mode == "User defined")
        self._show_colour()

    def _show_colour(self):
        if self.colour is not None:
            self.colour_button.setStyleSheet("QPushButton { border-left: 14px solid rgb(%d,%d,%d); }" % self.colour)

    def _transparency_mode(self, on):
        self._enable_transparency()
        if self.mode() in ("Full image", "User defined") and self.slider.value() == 0:
            self.slider.setValue(50 if self.mode() == "Full image" else 100)
            return
        self._set_transparency()

    def _pick_colour(self):
        start = QtGui.QColor(*self.colour) if self.colour is not None else QtGui.QColor(255, 255, 255)
        c = QtWidgets.QColorDialog.getColor(start, self, "Select color")
        if c.isValid():
            self.set_colour((c.red(), c.green(), c.blue()))

    def set_colour(self, colour):
        self.colour = tuple(colour)
        self._show_colour()
        self._set_transparency()

    def _set_transparency(self, *args):
        if self._filling:
            return
        self.begin()
        try:
            set_transparency(self.picture, self.mode(), self.slider.value(), self.colour, self.tolerance.value())
        except Exception as error:
            self.show_note("Transparency: %s" % error, True)

    # ---------------------------------------------------------------- scale tool
    def _watch_view(self):
        ""

        from . import sketchtoolpm as STP
        if self.view is not None:
            return
        view = None
        try:
            from . import pmtakeover
            view = pmtakeover.view_widget()     # the visible 3D view's viewport, where clicks arrive
        except Exception as _fw_err:
            _fw_log("sketchpicture.py:581", _fw_err)
        try:
            if view is None:
                shell = STP._shell()
                view = shell.view_widget() if shell is not None else None
        except Exception:
            view = None
        if view is not None:
            self.view = view.viewport() if hasattr(view, "viewport") and view.viewport() else view
            self.view.installEventFilter(self)

    def _scale_mode(self, on):
        self.scale_points = []
        if on:
            self._watch_view()
        self.show_note("Click the first point of a known distance on the picture." if on else
                       "Drag the picture to move it, or a corner or side handle to resize it.")

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter515(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter sketchpicture.py: %s\n" % exc)
            return False

    def _fw_filter515(self, obj, event):
        if self.view is None or obj is not self.view:
            return False
        t = event.type()
        if self.scale_tool.isChecked():
            if t in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) \
                    and event.button() == Qt.LeftButton:
                if t == QtCore.QEvent.MouseButtonPress:
                    QtCore.QTimer.singleShot(0, self._scale_click)
                return True
            return False
        if t == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            return self.press(self._cursor_point(), self._pixel_mm())
        if t == QtCore.QEvent.MouseMove and self.drag is not None:
            self.move_to(self._cursor_point())
            return True
        if t == QtCore.QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self.drag is not None:
            self.move_to(self._cursor_point())
            self.drag = None
            return True
        return False

    def _state(self):
        f = self.fields
        return (f["X"].value(), f["Y"].value(), f["Angle"].value(), f["Width"].value(), f["Height"].value())

    def _pixel_mm(self):
        try:
            view = Gui.ActiveDocument.ActiveView
            x, y = view.getCursorPos()
            return max(1e-6, (view.getPoint(x + 10, y) - view.getPoint(x, y)).Length / 10.0)
        except Exception:
            return 1.0

    def press(self, p, mm_px=1.0):
        """A left press at sketch point p: grabs a handle or the picture (True) or misses it (False)."""
        grab = hit(self._state(), p, 6.0 * mm_px)
        if grab is None:
            return False
        self.drag = (grab, p, self._state())
        return True

    def move_to(self, p):
        """The grabbed handle or picture follows the pointer to sketch point p."""
        if self.drag is None:
            return
        grab, p0, state = self.drag
        x, y, w, h = dragged(state, grab, p0, p, self.lock.isChecked())
        f = self.fields
        self._filling = True
        for key, v in (("X", x), ("Y", y), ("Width", w), ("Height", h)):
            f[key].setValue(v)
        self._filling = False
        if grab != "move" and not self.lock.isChecked():
            self._ratio = h / max(1e-9, w)
        self._changed(None)

    def _cursor_point(self):
        view = Gui.ActiveDocument.ActiveView
        p = view.getPoint(*view.getCursorPos())
        local = self.sketch.getGlobalPlacement().inverse().multVec(p)
        return App.Vector(local.x, local.y, 0)

    def _scale_click(self):
        try:
            self.scale_point(self._cursor_point())
        except Exception as error:
            self.show_note("Scale tool: %s" % error, True)

    def scale_point(self, p, distance=None):
        """A scale tool click at sketch point p; the second asks the distance (or takes distance)."""
        self.scale_points.append(p)
        if len(self.scale_points) < 2:
            self.show_note("Click the second point.")
            return None
        a, b = self.scale_points[:2]
        self.scale_points = []
        now = (b - a).Length
        if now < 1e-9:
            self.show_note("Pick two different points.", True)
            return None
        if distance is None:
            distance, ok = QtWidgets.QInputDialog.getDouble(self, "Scale tool", "Distance between the points (mm):",
                                                            now, 1e-6, 1e7, 3)
            if not ok:
                self.show_note("Click the first point of a known distance on the picture.")
                return None
        return self.scale_by(distance / now)

    def scale_by(self, k):
        """The picture scaled by k about its origin, as the scale tool does."""
        f = self.fields
        self._filling = True
        f["Width"].setValue(f["Width"].value() * k)
        f["Height"].setValue(f["Height"].value() * k)
        self._filling = False
        self._changed("Width") if not self.lock.isChecked() else self._changed(None)
        self.show_note("Picture scaled by %.4g. Click two more points to scale again." % k)
        return k

    # ---------------------------------------------------------------- next: Autotrace
    def autotrace(self):
        picture, sketch = self.picture, self.sketch
        self.accept()
        QtCore.QTimer.singleShot(0, lambda: sketchtoolpm.open_page(AutotracePage(sketch, picture)))

    def closing(self):
        if self.view is not None:
            try:
                self.view.removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("sketchpicture.py:720", _fw_err)
            self.view = None

    def _changed(self, key):
        if self._filling:
            return
        self.begin()
        f = self.fields
        if self.lock.isChecked() and key in ("Width", "Height"):
            self._filling = True
            if key == "Width":
                f["Height"].setValue(f["Width"].value() * self._ratio)
            else:
                f["Width"].setValue(f["Height"].value() / self._ratio)
            self._filling = False
        elif key in ("Width", "Height"):
            self._ratio = f["Height"].value() / max(1e-9, f["Width"].value())
        v = {k: f[k].value() for k in f}
        _set(self.picture, X=v["X"], Y=v["Y"], Angle=v["Angle"], Width=v["Width"], Height=v["Height"],
             FlipH=self.flip_h.isChecked(), FlipV=self.flip_v.isChecked())
        place(self.sketch, self.picture, v["X"], v["Y"], v["Angle"], v["Width"], v["Height"],
              self.flip_h.isChecked(), self.flip_v.isChecked())
        try:
            Gui.updateGui()
        except Exception as _fw_err:
            _fw_log("sketchpicture.py:745", _fw_err)


Qt = QtCore.Qt


class AutotracePage(sketchtoolpm.ToolPage):
    ""





    TITLE = "Autotrace"
    PIXMAP = "Std_ViewLoadImage"
    TRANSACTION = "Autotrace"

    def __init__(self, sketch, picture, parent=None):
        self.picture = picture
        super().__init__(sketch, parent)

    def build(self):
        g = self.group("Message")
        label = QtWidgets.QLabel("Select Color and click the picture on the colour to trace, or type it. "
                                 "Select Rectangle to trace inside an area. Then Begin Trace.", g.body)
        label.setWordWrap(True)
        g.content.addWidget(label)
        g = self.group("Selection Tools")
        self.pick_colour = QtWidgets.QRadioButton("Select Color", g.body)
        self.pick_colour.setObjectName("SWAutotraceSelectColor")
        self.pick_rect = QtWidgets.QRadioButton("Select Rectangle", g.body)
        self.pick_rect.setObjectName("SWAutotraceSelectRectangle")
        self.pick_colour.setChecked(True)
        g.content.addWidget(self.pick_colour)
        g.content.addWidget(self.pick_rect)
        self.colour_button = QtWidgets.QPushButton("Color...", g.body)
        self.colour_button.setObjectName("SWAutotraceColor")
        self.colour_button.clicked.connect(self._choose_colour)
        g.content.addWidget(self.colour_button)
        self.box = None
        self.box_label = QtWidgets.QLabel("Area: whole picture", g.body)
        self.box_label.setObjectName("SWAutotraceArea")
        g.content.addWidget(self.box_label)
        self.rect_points = []
        g = self.group("Trace Settings")
        form = QtWidgets.QFormLayout()
        self.tolerance = QtWidgets.QSlider(Qt.Horizontal, g.body)
        self.tolerance.setObjectName("SWAutotraceColorTolerance")
        self.tolerance.setRange(0, 100)
        self.tolerance.setValue(int(App.ParamGet(PARAMS).GetInt("ColorTolerance", 15)))
        form.addRow("Color tolerance", self.tolerance)
        g.content.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        for text, name, slot in (("Begin Trace", "SWAutotraceBegin", self.begin_trace),
                                 ("Apply", "SWAutotraceApply", self.apply),
                                 ("Clear", "SWAutotraceClear", self.clear)):
            b = QtWidgets.QPushButton(text, g.body)
            b.setObjectName(name)
            b.clicked.connect(slot)
            row.addWidget(b)
        g.content.addLayout(row)
        g = self.group("Adjustments")
        form = QtWidgets.QFormLayout()
        self.identification = QtWidgets.QDoubleSpinBox(g.body)
        self.identification.setObjectName("SWAutotraceIdentification")
        self.identification.setRange(0.1, 50.0)
        self.identification.setDecimals(1)
        self.identification.setSuffix(" px")
        self.identification.setValue(App.ParamGet(PARAMS).GetFloat("Identification", 1.5))
        form.addRow("Identification tolerance", self.identification)
        self.gap = QtWidgets.QDoubleSpinBox(g.body)
        self.gap.setObjectName("SWAutotraceGap")
        self.gap.setRange(0.0, 1e5)
        self.gap.setDecimals(0)
        self.gap.setSuffix(" px²")
        self.gap.setValue(App.ParamGet(PARAMS).GetFloat("Gap", 4.0))
        form.addRow("Gap tolerance", self.gap)
        g.content.addLayout(form)
        self.colour = None
        img = QtGui.QImage(source_file(self.picture))
        if not img.isNull():
            # the colour of the picture's middle: the drawing, not the background, as a start
            self.colour = _rgb(img.pixel(img.width() // 2, img.height() // 2))
        self._show_colour()
        self.traced = []      # lines of the trace not yet applied
        self.applied = 0
        self.view = None
        shell = sketchtoolpm._shell()
        view = shell.view_widget() if shell is not None else None
        if view is not None:
            self.view = view.viewport() if hasattr(view, "viewport") and view.viewport() else view
            self.view.installEventFilter(self)

    def _show_colour(self):
        if self.colour is not None:
            self.colour_button.setStyleSheet("QPushButton { border-left: 14px solid rgb(%d,%d,%d); }" % self.colour)
            self.colour_button.setText("Color %d, %d, %d" % self.colour)

    def _choose_colour(self):
        start = QtGui.QColor(*self.colour) if self.colour is not None else QtGui.QColor(0, 0, 0)
        c = QtWidgets.QColorDialog.getColor(start, self, "Autotrace color")
        if c.isValid():
            self.colour = (c.red(), c.green(), c.blue())
            self._show_colour()

    def _pixels(self):
        img = trace_image(source_file(self.picture))
        return img, img.width(), img.height()

    def picture_click(self, p):
        """A click on the picture at sketch point p: picks the colour there (Select Color) or a
        corner of the area (Select Rectangle)."""
        img, w, h = self._pixels()
        u, v = sketch_to_picture(self.picture, p, w, h)
        if not (0 <= u < w and 0 <= v < h):
            self.show_note("Click on the picture.", True)
            return
        if self.pick_colour.isChecked():
            self.colour = _rgb(img.pixel(int(u), int(v)))
            self._show_colour()
            self.show_note("Color picked. Begin Trace traces its outlines.")
            return
        self.rect_points.append((u, v))
        if len(self.rect_points) == 2:
            (a, b), (c, d) = self.rect_points
            self.box = (min(a, c), min(b, d), max(a, c), max(b, d))
            self.rect_points = []
            self.box_label.setText("Area: %d x %d px" % (self.box[2] - self.box[0], self.box[3] - self.box[1]))
            self.show_note("Area set. Begin Trace traces inside it.")
        else:
            self.show_note("Click the opposite corner of the area.")

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False     # PySide can hand a filter a stale wrapper (QLayoutItem) instead of the event
        try:
            return self._fw_filter735(obj, event)
        except Exception as exc:
            import FreeCAD
            FreeCAD.Console.PrintWarning("FreeCAD event filter sketchpicture.py: %s\n" % exc)
            return False

    def _fw_filter735(self, obj, event):
        if self.view is not None and obj is self.view and event.type() in (
                QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease) \
                and event.button() == Qt.LeftButton:
            if event.type() == QtCore.QEvent.MouseButtonPress:
                QtCore.QTimer.singleShot(0, self._click)
            return True
        return False

    def _click(self):
        try:
            view = Gui.ActiveDocument.ActiveView
            p = view.getPoint(*view.getCursorPos())
            local = self.sketch.getGlobalPlacement().inverse().multVec(p)
            self.picture_click(App.Vector(local.x, local.y, 0))
        except Exception as error:
            self.show_note("Autotrace: %s" % error, True)

    def _remember(self):
        par = App.ParamGet(PARAMS)
        par.SetInt("ColorTolerance", self.tolerance.value())
        par.SetFloat("Identification", self.identification.value())
        par.SetFloat("Gap", self.gap.value())

    def begin_trace(self):
        if self.colour is None:
            self.show_note("Pick a color to trace first.", True)
            return []
        self._remember()
        self.clear()
        try:
            loops = trace(self.picture, self.colour, self.tolerance.value(), self.identification.value(),
                          self.gap.value(), self.box)
        except Exception as error:
            self.show_note(str(error), True)
            return []
        if not loops:
            self.show_note("Nothing of that color to trace; raise the Color tolerance.", True)
            return []
        self.begin()
        self.traced = add_loops(self.sketch, loops)
        self.sketch.solve()
        sketchtoolpm._refresh(self.sketch)
        self.show_note("%d outline(s), %d lines. Apply keeps them." % (len(loops), len(self.traced)))
        return self.traced

    def clear(self):
        """Takes back the lines of the trace not applied."""
        if self.traced:
            for g in sorted(self.traced, reverse=True):
                try:
                    self.sketch.delGeometry(g)
                except Exception as _fw_err:
                    _fw_log("sketchpicture.py:940", _fw_err)
            self.traced = []
            sketchtoolpm._refresh(self.sketch)
        self.show_note("")

    def apply(self):
        self.applied += len(self.traced)
        self.traced = []
        self.show_note("%d lines kept. Pick another color, or the check to finish." % self.applied)

    def closing(self):
        if self.view is not None:
            try:
                self.view.removeEventFilter(self)
            except Exception as _fw_err:
                _fw_log("sketchpicture.py:955", _fw_err)
            self.view = None


PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/Autotrace"


def pictures(sketch):
    return [o for o in sketch.Document.findObjects("Image::ImagePlane")
            if getattr(o, "SWSketch", None) is sketch]


def edit_picture(picture):
    sketch = getattr(picture, "SWSketch", None)
    if sketch is None or contextbar.sketch_in_edit() is not sketch:
        return False
    try:
        hidden_link(picture, sketch)
    except Exception as _fw_err:
        _fw_log("sketchpicture.py:974", _fw_err)
    return sketchtoolpm.open_page(SketchPicturePage(sketch, picture=picture))


class SketchPictureCommand:
    def GetResources(self):
        return {"MenuText": "Sketch Picture", "Pixmap": "image-open",
                "ToolTip": "Inserts a picture on the sketch plane, to trace over."}

    def IsActive(self):
        if contextbar.sketch_in_edit() is not None:
            return True
        if App.ActiveDocument is None:
            return False
        try:
            return bool(Gui.Command.get(NATIVE).isActive())
        except Exception:
            return App.ActiveDocument is not None

    def Activated(self):
        sketch = contextbar.sketch_in_edit()
        if sketch is None:
            Gui.runCommand(NATIVE, 0)
            return
        picked = [s.Object for s in Gui.Selection.getSelectionEx()
                  if s.Object.TypeId == "Image::ImagePlane" and getattr(s.Object, "SWSketch", None) is sketch]
        if picked:
            edit_picture(picked[0])
            return
        path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Sketch Picture", "", FILTER)
        if path:
            sketchtoolpm.open_page(SketchPicturePage(sketch, path=path))


def replace_pictures(doc):
    """Every sketch picture back on its sketch, where its own X, Y, Angle and size put it."""
    for o in doc.findObjects("Image::ImagePlane"):
        sketch = getattr(o, "SWSketch", None) if o.TypeId == "Image::ImagePlane" else None
        if sketch is None:
            continue
        try:
            want_args = (_get(o, "X", 0.0), _get(o, "Y", 0.0), _get(o, "Angle", 0.0),
                         _get(o, "Width", float(o.XSize)), _get(o, "Height", float(o.YSize)),
                         _get(o, "FlipH", False), _get(o, "FlipV", False))
            before = App.Placement(o.Placement)
            place(sketch, o, *want_args)
            if o.Placement.isSame(before, 1e-9):
                o.Placement = before
        except Exception as _fw_err:
            _fw_log("sketchpicture.py:1023", _fw_err)


_HAS_PICTURES = {}        # document name -> it has (or had) an Image::ImagePlane; absent: not asked yet


class _FollowSketch:
    ""



    def __init__(self):
        self.busy = False

    def slotChangedObject(self, obj, prop):
        if self.busy or prop not in ("Placement", "Visibility"):
            return
        try:
            if obj.TypeId == "Image::ImagePlane":
                return
            doc = obj.Document
            # the C++ type search first: a Python pass over doc.Objects on every Placement
            # change cost 3.8 s of a 301-part assembly's 13 s open
            has = _HAS_PICTURES.get(doc.Name)
            if has is None:         # once per document (kept up to date by slotCreatedObject): the search was quadratic in a big assembly
                has = _HAS_PICTURES[doc.Name] = bool(doc.findObjects("Image::ImagePlane"))
            if not has:
                return
            if not any(getattr(o, "SWSketch", None) is not None
                       for o in doc.findObjects("Image::ImagePlane")):
                return
            self.busy = True
            if prop == "Placement":
                replace_pictures(doc)
            elif obj.TypeId == "Sketcher::SketchObject":
                for pic in pictures(obj):
                    if bool(pic.Visibility) != bool(obj.Visibility):
                        pic.Visibility = obj.Visibility
        except Exception as _fw_err:
            _fw_log("sketchpicture.py:1054", _fw_err)
        finally:
            self.busy = False

    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId == "Image::ImagePlane":
                _HAS_PICTURES[obj.Document.Name] = True
        except Exception:
            pass

    def slotDeletedDocument(self, doc):
        try:
            _HAS_PICTURES.pop(doc.Name, None)
        except Exception:
            pass

    def slotDeletedObject(self, obj):
        try:
            if obj.TypeId != "Sketcher::SketchObject":
                return
            doc = obj.Document
            gone = [o.Name for o in pictures(obj)]
        except Exception:
            return
        for name in gone:
            # inside the delete's own step, so one Undo brings both back
            try:
                if doc.getObject(name) is not None:
                    doc.removeObject(name)
            except Exception as _fw_err:
                _fw_log("sketchpicture.py:1072", _fw_err)


_follow = None


def register():
    global _follow
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, SketchPictureCommand())
    if _follow is None:
        _follow = _FollowSketch()
        App.addDocumentObserver(_follow)
