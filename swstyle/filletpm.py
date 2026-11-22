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
import time

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths, refplane
from .widgets import alive

try:
    from pivy import coin
except ImportError:
    coin = None

Qt = QtCore.Qt
SLOW_PREVIEW = 0.5      # s: a preview build at least this long can be cancelled with Esc


class _EscCatcher(QtCore.QObject):
    """Held on the application for a moment after a slow preview build: the keys pressed during the
    build arrive then, and an Esc among them cancels the preview instead of closing the page."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, obj, event):
        try:
            if event.type() in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and \
                    event.key() == Qt.Key_Escape:
                if event.type() == QtCore.QEvent.KeyPress:
                    self.panel._cancel_preview()
                return True
        except Exception as _fw_err:
            _fw_log("filletpm.py:83", _fw_err)
        return False


_CATCHER = []


def _catch_esc(panel, ms=150):
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    for old in _CATCHER:            # a newer build re-arms it
        try:
            app.removeEventFilter(old)
        except Exception as _fw_err:
            _fw_log("filletpm.py:98", _fw_err)
    _CATCHER[:] = []
    catcher = _EscCatcher(panel)
    app.installEventFilter(catcher)
    _CATCHER.append(catcher)

    def done():
        try:
            app.removeEventFilter(catcher)
        except Exception as _fw_err:
            _fw_log("filletpm.py:108", _fw_err)
        if catcher in _CATCHER:
            _CATCHER.remove(catcher)
    QtCore.QTimer.singleShot(ms, done)
NOT_YET = "Not in FreeCAD yet"
PARAMS = paths.PARAM_PATH + "/FilletChamfer"     # shared with filletchamfer.py (last values)
FILLET, CHAMFER = "PartDesign::Fillet", "PartDesign::Chamfer"
SHELL, DRAFT = "PartDesign::Thickness", "PartDesign::Draft"
PREVIEWS = ("Full preview", "Partial preview", "No preview")
FILLET_TYPES = (    # (tooltip, icon family, command): Constant Size is this page
    ("Constant Size Fillet", "FEATURES_FILLET", None),
    ("Variable Size Fillet", "FEATURES_VARIABLE_FILLET", "SWStyle_VariableFillet"),
    ("Face Fillet", "FEATURES_FACE_FILLET", "SWStyle_FaceFillet"),
    ("Full Round Fillet", "FEATURES_FULL_ROUND_FILLET", "SWStyle_FullRoundFillet"),
)
CHAMFER_TYPES = (   # (tooltip, icon family, FreeCAD can make it)
    ("Angle Distance", "FEATURES_CHAMFER", True),
    ("Distance Distance", "FEATURES_CHAMFER_DISTANCE", True),
    ("Vertex", "FEATURES_CHAMFER_VERTEX", True),
    ("Offset Face", "FEATURES_CHAMFER_OFFSET_FACE", True),
    ("Face Face", "FEATURES_CHAMFER_FACE_FACE", True),
)
PICK_BLUE = "#cfe3ff"           # an active selection box
EDGE_BLUE = (0.35, 0.65, 1.0)   # picked items in the view
PREVIEW_YELLOW = (1.0, 0.93, 0.45)
NEUTRAL_CYAN = (0.0, 0.85, 1.0)  # Draft's neutral plane, picked
FACES_PINK = (0.95, 0.35, 0.75)

_current = None
_created = {}       # "doc.name" -> when FreeCAD made a fillet or chamfer (its own command)
_observers = []


def current():
    return _current


def params():
    return App.ParamGet(PARAMS)


# --------------------------------------------------------------------------- shapes
def _features(body):
    return [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature") and hasattr(o, "AddSubShape")]


def _same_edge(a, b):
    try:
        if abs(a.Length - b.Length) > 1e-6 * max(1.0, a.Length):
            return False
        p0, p1 = a.FirstParameter, a.LastParameter
        for f in (0.25, 0.5, 0.75):
            if b.distToShape(_vertex(a.valueAt(p0 + (p1 - p0) * f)))[0] > 1e-6:
                return False
        return True
    except Exception:
        return False


def _is_sketch(obj):
    try:
        return obj.TypeId.startswith("Sketcher::") or obj.isDerivedFrom("Part::Part2DObject")
    except Exception:
        return False


def _edges_along(shape, sketch, sub):
    """Names of the shape's edges that lie on the sketch's edge (a seam the sketch split)."""
    try:
        line = sketch.Shape.getElement(sub)
    except Exception:
        return []
    out = []
    for i, e in enumerate(shape.Edges, 1):
        try:
            p0, p1 = e.FirstParameter, e.LastParameter
            if all(line.distToShape(_vertex(e.valueAt(p0 + (p1 - p0) * f)))[0] < 1e-5
                   for f in (0.0, 0.25, 0.5, 0.75, 1.0)):
                out.append("Edge%d" % i)
        except Exception:
            continue
    return out


def _same_face(a, b):
    try:
        if abs(a.Area - b.Area) > 1e-6 * max(1.0, a.Area):
            return False
        return b.distToShape(_vertex(a.CenterOfMass))[0] < 1e-6
    except Exception:
        return False


def _vertex(p):
    import Part
    return Part.Vertex(p)


def feature_edges(base, feature):
    """The edges of base that feature made (on its own added or cut shape), as base's subnames, in
    order; None when none can be told (a dress-up feature has no shape of its own). Seams are left
    out: no fillet runs along one."""
    try:
        import Part
        own = feature.AddSubShape
        if own is None or own.isNull() or not own.Faces:
            return None
        shape = base.Shape
        names = []
        for i, e in enumerate(shape.Edges, 1):
            if len({f.hashCode() for f in shape.ancestorsOfType(e, Part.Face)}) < 2:
                continue
            p = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            if own.distToShape(_vertex(p))[0] < 1e-6:
                names.append("Edge%d" % i)
        return names or None
    except Exception:
        return None


def to_base(base, obj, sub):
    """The base feature's own name for an edge or face picked on another feature's shape
    (the same edge drawn by a later feature or the fillet itself), else None."""
    if obj is base:
        return sub
    try:
        element = obj.Shape.getElement(sub)
    except Exception:
        return None
    if sub.startswith("Edge"):
        for i, e in enumerate(base.Shape.Edges, 1):
            if _same_edge(element, e):
                return "Edge%d" % i
    elif sub.startswith("Face"):
        for i, f in enumerate(base.Shape.Faces, 1):
            if _same_face(element, f):
                return "Face%d" % i
    return None


def _on_face(f, p):
    """p lies on face f (within 1e-5): projected on its surface first (microseconds), the face's own
    domain asked only when the surface holds the point; distToShape (a millisecond) only if that fails."""
    try:
        surf = f.Surface
        u, v = surf.parameter(p)
        if (App.Vector(surf.value(u, v)) - p).Length > 1e-5:
            return False
        if f.isPartOfDomain(u, v):
            return True
    except Exception as _fw_err:
        _fw_log("filletpm.py:237", _fw_err)
    try:
        return f.distToShape(_vertex(p))[0] <= 1e-5
    except Exception:
        return False


def new_faces(base_shape, result_shape):
    """The faces of the result that the fillet or chamfer made (not on the base's faces)."""
    import Part
    made = []
    # only the base faces whose box holds the point can be at 1e-5 from it: a big part's result
    # face is measured against one or two faces, not the whole skin (1.3 s on a 60-feature part)
    skin = []
    for f in base_shape.Faces:
        box = App.BoundBox(f.BoundBox)
        box.enlarge(1e-4)
        skin.append((box, f))
    kept = {}       # base faces the result still holds as they are (the boolean shares them): no measure
    for _box, f in skin:
        try:
            kept.setdefault(f.hashCode(), []).append(f)
        except Exception as _fw_err:
            _fw_log("filletpm.py:260", _fw_err)
    for face in result_shape.Faces:
        try:
            if any(face.isSame(f) for f in kept.get(face.hashCode(), ())):
                continue
            u0, u1, v0, v1 = face.ParameterRange
            p = face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            if not face.isInside(p, 1e-6, True):
                p = face.CenterOfMass
            near = [f for box, f in skin if box.isInside(p)]
            if not near:
                made.append(face)
                continue
            if not any(_on_face(f, p) for f in near):
                made.append(face)
        except Exception as _fw_err:
            _fw_log("filletpm.py:299", _fw_err)
            continue
    return made


# --------------------------------------------------------------------------- the view overlay
def _self_crossing(shape, most=400):
    """True when the solid folds through itself (OpenCascade's BOP check), on parts small
    enough to check while the page is open."""
    try:
        if shape.isNull() or len(shape.Faces) > most:
            return False
        shape.check(True)
        return False
    except Exception as error:
        return "SelfIntersect" in str(error)


def _section_curves(faces, count=6):
    ""

    out = []
    for face in faces[:60]:
        try:
            if type(face.Surface).__name__ == "Plane":
                continue
            u0, u1, v0, v1 = face.ParameterRange
            su = face.Surface
            # the short way across: compare the length of a mid u-line and a mid v-line
            mid_u = su.uIso((u0 + u1) / 2.0).toShape(v0, v1)
            mid_v = su.vIso((v0 + v1) / 2.0).toShape(u0, u1)
            across_u = mid_u.Length <= mid_v.Length
            for k in range(1, count):
                t = k / float(count)
                if across_u:
                    c = su.uIso(u0 + (u1 - u0) * t).toShape(v0, v1)
                else:
                    c = su.vIso(v0 + (v1 - v0) * t).toShape(u0, u1)
                part = c.common(face)            # trimmed to the face
                out += part.Edges or ([c] if face.isInside(c.valueAt((c.FirstParameter + c.LastParameter) / 2.0), 1e-3, True) else [])
        except Exception:
            continue
    return out


class Overlay:
    """Picked items in blue and the preview in see-through yellow, drawn over the part and
    never picked (picks go to the part under them)."""

    def __init__(self):
        self.root = None
        self.view = None
        if coin is None:
            return
        try:
            self.view = Gui.ActiveDocument.ActiveView
            self.root = coin.SoSeparator()
            style = coin.SoPickStyle()
            style.style = coin.SoPickStyle.UNPICKABLE
            self.root.addChild(style)
            self.preview = coin.SoSeparator()
            self.picks = coin.SoSeparator()
            self.hints = coin.SoSeparator()
            self.root.addChild(self.preview)
            self.root.addChild(self.picks)
            self.root.addChild(self.hints)
            self.view.getSceneGraph().addChild(self.root)
        except Exception:
            self.root = None

    def _lines(self, sep, edges, colour, width):
        for edge in edges:
            try:
                pts = edge.discretize(Deflection=0.02)
            except Exception:
                continue
            node = coin.SoSeparator()
            mat = coin.SoBaseColor()
            mat.rgb = colour
            draw = coin.SoDrawStyle()
            draw.lineWidth = width
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
            line = coin.SoLineSet()
            line.numVertices.setValue(len(pts))
            for n in (mat, draw, coords, line):
                node.addChild(n)
            sep.addChild(node)

    def show_picks(self, edges):
        if self.root is None:
            return
        self.picks.removeAllChildren()
        # On top of the part's own edge lines.
        depth = coin.SoDepthBuffer()
        depth.test = False
        self.picks.addChild(depth)
        self._lines(self.picks, edges, EDGE_BLUE, 3)

    def show_hint(self, edges):
        ""
        if self.root is None:
            return
        self.hints.removeAllChildren()
        if not edges:
            return
        depth = coin.SoDepthBuffer()
        depth.test = False
        self.hints.addChild(depth)
        from .selectiontoolbar import HINT_MAGENTA
        self._lines(self.hints, edges, HINT_MAGENTA, 3)

    def _layer(self, name):
        sep = getattr(self, name, None)
        if sep is None:
            sep = coin.SoSeparator()
            setattr(self, name, sep)
            marks = getattr(self, "marks", None)
            if name != "marks" and marks is not None:
                self.root.insertChild(sep, self.root.findChild(marks))      # labels stay on top
            else:
                self.root.addChild(sep)
        sep.removeAllChildren()
        return sep

    def show_marks(self, edges, colour, texts=()):
        """Edges in a colour of their own and text callouts [(point, text)] over the part
        (Draft: the neutral plane's whole rim in cyan with its "Neutral Plane" label)."""
        if self.root is None:
            return
        sep = self._layer("marks")
        if not edges and not texts:
            return
        depth = coin.SoDepthBuffer()
        depth.test = False
        sep.addChild(depth)
        self._lines(sep, edges, colour, 3)
        for point, text, rgb in texts:
            node = coin.SoSeparator()
            mat = coin.SoBaseColor()
            mat.rgb = rgb
            move = coin.SoTranslation()
            move.translation = (point.x, point.y, point.z)
            font = coin.SoFont()
            font.size = 15
            font.name = "Arial:Bold"
            label = coin.SoText2()
            label.string = text
            for n in (mat, move, font, label):
                node.addChild(n)
            sep.addChild(node)

    def show_paint(self, painted):
        """Faces filled each in its colour [(face, rgb)] (DraftXpert's Draft Analysis)."""
        if self.root is None:
            return
        sep = self._layer("paint")
        for face, rgb in painted:
            try:
                points, triangles = face.tessellate(0.05)
            except Exception:
                continue
            if not triangles:
                continue
            node = coin.SoSeparator()
            mat = coin.SoMaterial()
            mat.diffuseColor = rgb
            mat.emissiveColor = tuple(0.25 * c for c in rgb)
            offset = coin.SoPolygonOffset()     # over the part's own faces, not fighting them
            offset.factor = -1.0
            offset.units = -1.0
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            faceset = coin.SoIndexedFaceSet()
            index = []
            for t in triangles:
                index += [t[0], t[1], t[2], -1]
            faceset.coordIndex.setValues(0, len(index), index)
            for n in (mat, offset, coords, faceset):
                node.addChild(n)
            sep.addChild(node)

    def show_preview(self, faces, sections=True):
        ""

        if self.root is None:
            return
        self.preview.removeAllChildren()
        if not faces:
            return
        mat = coin.SoMaterial()
        mat.diffuseColor = PREVIEW_YELLOW
        mat.emissiveColor = (0.35, 0.3, 0.05)
        mat.transparency = 0.35
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        self.preview.addChild(mat)
        self.preview.addChild(hints)
        depth = coin.SoDepthBuffer()        # the new faces lie inside the part: draw them over it
        depth.test = False
        self.preview.addChild(depth)
        for face in faces:
            try:
                points, triangles = face.tessellate(0.05)
            except Exception as _fw_err:
                _fw_log("filletpm.py:504", _fw_err)
                continue
            if not triangles:
                continue
            coords = coin.SoCoordinate3()
            coords.point.setValues(0, len(points), [(p.x, p.y, p.z) for p in points])
            faceset = coin.SoIndexedFaceSet()
            index = []
            for t in triangles:
                index += [t[0], t[1], t[2], -1]
            faceset.coordIndex.setValues(0, len(index), index)
            self.preview.addChild(coords)
            self.preview.addChild(faceset)
        self._lines(self.preview, [e for f in faces for e in f.Edges] + (_section_curves(faces) if sections else []),
                    (0.85, 0.7, 0.0), 1)

    def remove(self):
        if self.root is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("filletpm.py:500", _fw_err)
            self.root = None


class Callout(QtWidgets.QFrame):
    ""


    def __init__(self, panel, view_widget):
        super().__init__(view_widget)
        self.panel = panel
        self.setObjectName("SWFilletCallout")
        self.setStyleSheet("QFrame#SWFilletCallout { background: white; border: 1px solid #7a7a7a; }"
                           "QLabel { color: black; padding: 0 3px; }"
                           "QLineEdit { border: none; border-left: 1px solid #b0b0b0; background: white;"
                           " color: black; padding: 0 3px; }")
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.rows = []          # [(label, line edit)]
        self.setters = []       # [(unit, setter)]
        self.anchor = None
        self.hide()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.place)
        self.timer.start(60)

    # the first row, kept for older callers and the tests
    @property
    def label(self):
        return self.rows[0][0] if self.rows else None

    @property
    def edit(self):
        return self.rows[0][1] if self.rows else None

    def _row(self, i):
        while len(self.rows) <= i:
            label = QtWidgets.QLabel(self)
            edit = QtWidgets.QLineEdit(self)
            edit.setObjectName("SWFilletCalloutValue" if not self.rows else "SWFilletCalloutValue%d" % (len(self.rows) + 1))
            edit.setFixedWidth(64)
            n = len(self.rows)
            edit.editingFinished.connect(lambda n=n: self._typed(n))
            self.grid.addWidget(label, n, 0)
            self.grid.addWidget(edit, n, 1)
            self.rows.append((label, edit))
        return self.rows[i]

    def set(self, name, value, anchor, unit="mm"):
        self.set_rows([(name, value, unit, self.panel.set_size)], anchor)

    def set_rows(self, rows, anchor):
        self.setters = []
        for i, (name, value, unit, setter) in enumerate(rows):
            label, edit = self._row(i)
            label.setText(name + ":")
            if not edit.hasFocus():
                # lengths in the document's units (inches in an IPS part), as the fields show them
                edit.setText(_LengthSpin.text_of(value) if unit == "mm" else _number(value) + unit)
            label.show()
            edit.show()
            self.setters.append((unit, setter))
        for label, edit in self.rows[len(rows):]:
            label.hide()
            edit.hide()
        self.unit = rows[0][2] if rows else "mm"
        self.anchor = anchor
        self.adjustSize()
        self.place()

    def _typed(self, n=0):
        if n >= len(self.setters):
            return
        unit, setter = self.setters[n]
        if unit == "mm":
            value = _LengthSpin.parse(self.rows[n][1].text())
            if value is not None:
                setter(value)
            return
        text = self.rows[n][1].text().replace(unit, "").strip()
        try:
            value = App.Units.Quantity(text if text else "0").Value if any(c.isalpha() for c in text) else float(text)
        except Exception:
            return
        setter(value)

    def place(self):
        if self.anchor is None or not alive(self):
            self.hide()
            return
        try:
            view = Gui.ActiveDocument.ActiveView
            x, y = view.getPointOnViewport(self.anchor)
        except Exception:
            self.hide()
            return
        parent = self.parentWidget()
        ratio = parent.devicePixelRatioF() if hasattr(parent, "devicePixelRatioF") else 1.0
        x, y = x / ratio, parent.height() - y / ratio
        self.move(int(x + 12), int(y + 10))
        if not self.isVisible():
            self.show()
            self.raise_()


def _number(value):
    text = ("%.2f" % value).rstrip("0").rstrip(".")
    return text or "0"


def _view_widget():
    """The 3D view's drawing widget (the QGraphicsView's viewport) of the active document."""
    mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi is not None else None
    for root in ([sub.widget()] if sub is not None else []) + [Gui.getMainWindow()]:
        for w in root.findChildren(QtWidgets.QGraphicsView):
            if w.isVisible():
                return w.viewport()
    return None


# --------------------------------------------------------------------------- page parts
def _box(title, collapsed=False, bare=False):
    ""

    w = QtWidgets.QWidget()
    w.setWindowTitle(title)
    w.setProperty("swstyle_pm_collapsed", collapsed)
    w.setProperty("swstyle_pm_bare", bare)
    QtWidgets.QVBoxLayout(w)
    return w


def box_visible(w, on):
    """Show or hide a page box with its task box frame and title row: hiding only the inner
    widget left the empty headers (FilletXpert, Change ...) on the Manual tab."""
    try:
        w.setVisible(on)
        g = w.parentWidget()
        while g is not None and not g.inherits("QSint::ActionGroup"):
            g = g.parentWidget()
        # isHidden, not isVisible: before the panel is first shown nothing is "visible", and the
        # frame was left on (PC run20: FilletXpert, Change ... headers on the Manual tab)
        if g is not None and g.isHidden() == on:
            g.setVisible(on)
    except RuntimeError as _fw_err:
        _fw_log("filletpm.py:647", _fw_err)


def name_headers(form):
    """Each task box header gets objectName "SWBoxHeader_<title>" (spaces as _), its fold button
    "SWBoxFold_<title>": checks that click like a person find them by name."""
    for w in form:
        try:
            title = (w.windowTitle() or "").replace(" ", "_")
            box = w
            while box is not None and not box.inherits("QSint::ActionGroup"):
                box = box.parentWidget()
            if box is None or not title:
                continue
            for header in box.findChildren(QtWidgets.QWidget):
                if header.inherits("QSint::TaskHeader"):
                    header.setObjectName("SWBoxHeader_" + title)
                    for b in header.findChildren(QtWidgets.QAbstractButton):
                        b.setObjectName("SWBoxFold_" + title)
                        break
                    break
        except RuntimeError:
            continue


def collapse_boxes(form):
    ""


    for w in form:
        try:
            folded, bare = w.property("swstyle_pm_collapsed"), w.property("swstyle_pm_bare")
            if not folded and not bare:
                continue
            box = w
            while box is not None and not box.inherits("QSint::ActionGroup"):
                box = box.parentWidget()
            if box is None:
                continue
            if folded and not bare and _left_open(box, w.windowTitle()):
                continue
            for header in box.findChildren(QtWidgets.QWidget):
                if not header.inherits("QSint::TaskHeader"):
                    continue
                if bare:
                    header.hide()
                    # fillettypes-1121: the group frame kept the height it had with the header (a 30 px
                    # gap above Manual | FilletXpert); it takes the bar's own height
                    frame = w.parentWidget()
                    if frame is not None and w.maximumHeight() < 200:
                        m = frame.layout().contentsMargins() if frame.layout() is not None else QtCore.QMargins()
                        frame.setFixedHeight(w.maximumHeight() + m.top() + m.bottom())
                        box.setFixedHeight(w.maximumHeight() + m.top() + m.bottom() + 1)    # + the 1 px top line
                    break
                if w.isHidden() or not w.isVisibleTo(box):
                    break       # folded already: the fold button toggles
                for b in header.findChildren(QtWidgets.QAbstractButton):
                    b.click()
                    break
                break
        except RuntimeError:
            continue


def _left_open(group, title):
    """The fold memory (propertymanager) says the user left this page's box open."""
    try:
        from . import propertymanager
        view = group.parentWidget()
        while view is not None and not view.inherits("Gui::TaskView::TaskView"):
            view = view.parentWidget()
        if view is None:
            return False
        return propertymanager.FOLDS.get((propertymanager._title(view)[0], title)) is True
    except Exception as _fw_err:
        _fw_log("filletpm.py:left_open", _fw_err)
        return False


def _greyed(widget, why=NOT_YET):
    widget.setEnabled(False)
    widget.setToolTip(why)
    return widget


FILLET_DRAWN = ("FEATURES_FILLET", "FEATURES_VARIABLE_FILLET", "FEATURES_FACE_FILLET", "FEATURES_FULL_ROUND_FILLET")
_drawn_cache = {}


def _fillet_type_icon(family):
    """pkg249: the four Fillet Type buttons drawn as shaded parts, each showing its fillet (the pack
    has one Fillet picture only, so all four looked the same). Our own drawings."""
    if family in _drawn_cache:
        return _drawn_cache[family]
    icon = QtGui.QIcon()
    for size in (24, 48):
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(size / 24.0, size / 24.0)
        top, side, front = QtGui.QColor("#c9d3de"), QtGui.QColor("#8a99ab"), QtGui.QColor("#a9b7c7")
        red = QtGui.QColor("#e0522f")
        p.setPen(QtGui.QPen(QtGui.QColor("#3c4652"), 0.8))
        path = QtGui.QPainterPath

        def poly(points, color):
            p.setBrush(color)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points]))
        if family == "FEATURES_FULL_ROUND_FILLET":
            # a rib whose top is one round from side to side
            poly([(4, 20), (14, 20), (20, 16), (20, 10), (10, 10), (4, 14)], side)
            poly([(4, 14), (4, 20), (14, 20), (14, 14)], front)
            r = path(); r.moveTo(4, 14); r.cubicTo(4, 6, 14, 6, 14, 14); r.lineTo(4, 14)
            p.setBrush(red); p.drawPath(r)
            r2 = path(); r2.moveTo(4, 14); r2.cubicTo(4, 7, 14, 7, 14, 14); r2.lineTo(20, 10); r2.cubicTo(20, 3, 10, 3, 10, 10); r2.closeSubpath()
            p.setBrush(QtGui.QColor("#f08a6c")); p.drawPath(r2)
        else:
            # an L-block with the round between its top and its upright
            poly([(3, 21), (15, 21), (21, 17), (21, 13), (9, 13), (3, 17)], side)
            poly([(3, 17), (3, 21), (15, 21), (15, 17)], front)
            poly([(9, 13), (21, 13), (21, 4), (17, 4), (9, 4)], side)
            poly([(9, 4), (9, 13), (13, 13), (13, 4)], top)
            r = path()
            if family == "FEATURES_VARIABLE_FILLET":       # the round grows along the edge
                r.moveTo(13, 12); r.quadTo(13, 13, 14, 13); r.lineTo(21, 9); r.quadTo(17, 9, 17, 5); r.closeSubpath()
            elif family == "FEATURES_FACE_FILLET":          # a wide blend between two faces
                r.moveTo(9, 9); r.quadTo(9, 15, 15, 15); r.lineTo(21, 11); r.quadTo(15, 11, 15, 5); r.closeSubpath()
            else:                                           # constant size: the same round all along
                r.moveTo(13, 11); r.quadTo(13, 13, 15, 13); r.lineTo(21, 9); r.quadTo(19, 9, 19, 7); r.closeSubpath()
            p.setBrush(red); p.drawPath(r)
        p.end()
        icon.addPixmap(pm)
    _drawn_cache[family] = icon
    return icon


CHAMFER_DRAWN = ("FEATURES_CHAMFER", "FEATURES_CHAMFER_DISTANCE", "FEATURES_CHAMFER_VERTEX",
                 "FEATURES_CHAMFER_OFFSET_FACE", "FEATURES_CHAMFER_FACE_FACE")


def _chamfer_type_icon(family):
    """The five Chamfer Type buttons when no icon pack has them (a buttons of "..." before): a block, its bevel
    red, each type's own mark. Our own drawings, in the Fillet Type pictures' style."""
    key = "drawn:" + family
    if key in _drawn_cache:
        return _drawn_cache[key]
    icon = QtGui.QIcon()
    for size in (24, 48):
        pm = QtGui.QPixmap(size, size)
        pm.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.scale(size / 24.0, size / 24.0)
        top, side, front = QtGui.QColor("#c9d3de"), QtGui.QColor("#8a99ab"), QtGui.QColor("#a9b7c7")
        red, dim = QtGui.QColor("#e0522f"), QtGui.QColor("#2f6fc4")
        p.setPen(QtGui.QPen(QtGui.QColor("#3c4652"), 0.8))

        def poly(points, color):
            p.setBrush(color)
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in points]))

        def line(x0, y0, x1, y1, color, w=1.0, dash=False):
            pen = QtGui.QPen(color, w)
            if dash:
                pen.setStyle(QtCore.Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(x1, y1))
            p.setPen(QtGui.QPen(QtGui.QColor("#3c4652"), 0.8))
        if family == "FEATURES_CHAMFER_VERTEX":
            # a block with its top corner cut off by a small triangle
            poly([(3, 9), (3, 21), (15, 21), (15, 12), (12, 9)], front)
            poly([(15, 12), (15, 21), (21, 17), (21, 5), (18, 5)], side)
            poly([(3, 9), (9, 5), (18, 5), (12, 9)], top)
            poly([(12, 9), (18, 5), (15, 12)], red)
        elif family == "FEATURES_CHAMFER_FACE_FACE":
            # an L-block, the bevel between its two inside faces
            poly([(3, 21), (15, 21), (21, 17), (21, 13), (9, 13), (3, 17)], side)
            poly([(3, 17), (3, 21), (15, 21), (15, 17)], front)
            poly([(9, 13), (21, 13), (21, 4), (17, 4), (9, 4)], side)
            poly([(9, 4), (9, 13), (13, 13), (13, 4)], top)
            poly([(13, 9), (17, 13), (21, 9), (17, 5)], red)
        else:
            # a block, its front top edge bevelled
            poly([(3, 12), (3, 21), (15, 21), (15, 12), (12, 9), (6, 9)], front)
            poly([(15, 12), (15, 21), (21, 17), (21, 8)], side)
            poly([(6, 9), (12, 5), (18, 5), (12, 9)], top)
            poly([(12, 9), (18, 5), (21, 8), (15, 12)], red)
            if family == "FEATURES_CHAMFER":                # Angle Distance: a distance and an angle arc
                line(16, 14, 22, 10, dim)
                p.setPen(QtGui.QPen(dim, 1.0))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawArc(QtCore.QRectF(11, 5, 8, 8), 200 * 16, 70 * 16)
            elif family == "FEATURES_CHAMFER_DISTANCE":     # Distance Distance: two distances
                line(16, 14, 22, 10, dim)
                line(11, 3, 17, 3, dim)
            else:                                           # Offset Face: the faces moved in (dashed)
                line(3, 14, 15, 14, dim, dash=True)
                line(17, 5, 17, 13, dim, dash=True)
        p.end()
        icon.addPixmap(pm)
    _drawn_cache[key] = icon
    return icon


def _icon_button(parent, name, tip, family):
    from . import icons
    b = QtWidgets.QToolButton(parent)
    b.setObjectName(name)
    b.setToolTip(tip)
    b.setCheckable(True)
    b.setAutoRaise(True)
    icon = icons.family(family)       # icons-exact-1122: the pack's picture first; ours only for a type it has none for
    if icon.isNull() and family in FILLET_DRAWN:
        icon = _fillet_type_icon(family)
    if icon.isNull() and family in CHAMFER_DRAWN:
        icon = _chamfer_type_icon(family)     # no pack picture: ours (all five, so each shows its own type)
    if icon.isNull() and family != "FEATURES_FILLET":
        icon = icons.family("FEATURES_CHAMFER" if "CHAMFER" in family else "FEATURES_FILLET")
    if icon.isNull():
        b.setText(tip.split()[0])
    else:
        b.setIcon(icon)
        b.setIconSize(QtCore.QSize(24, 24))
    b.setFixedSize(34, 34)
    b.setProperty("fw_type_tile", True)
    try:
        from . import style
        if style.dark():

            # line (the Light colours drew blue text on blue here, PM dark audit)
            b.setStyleSheet(DARK_TOGGLE)
        else:
            b.setStyleSheet(LIGHT_TOGGLE)
    except Exception as _fw_err:
        _fw_log("filletpm.py:782", _fw_err)
    return b


# fillettypes-1121 (desktop recording 2026-10-25): the type buttons are framed tiles set
# side by side, the pressed one filled; a greyed one has no frame
DARK_TOGGLE = ("QToolButton { color: #e8e8e8; background: #3a3a3a; border: 1px solid #626262;"
               " border-radius: 0px; }"
               " QToolButton:hover { background: #4a4a4a; border-color: #6a6a6a; }"
               " QToolButton:checked, QToolButton:pressed { color: #ffffff; background: #2f4f78;"
               " border-color: #6aa6e8; }"
               " QToolButton:disabled { color: #8a8a8a; background: transparent; border-color: transparent; }")
LIGHT_TOGGLE = ("QToolButton { color: #1e1e1e; background: #ffffff; border: 1px solid #a9a9a9; border-radius: 0px; }"
                " QToolButton:hover { background: #e5f1fb; border-color: #7eb4ea; }"
                " QToolButton:checked, QToolButton:pressed { background: #bdbdbd; border-color: #8c8c8c; }"
                " QToolButton:disabled { color: #9a9a9a; background: transparent; border-color: transparent; }")


def _xpert_tabs(tabs):
    """Manual | FilletXpert (DraftXpert): two joined buttons centred under the check and cross, the
    current one pressed (fillettypes-1121, desktop recording 2026-10-25)."""
    try:
        from . import style
        dark = style.dark()
    except Exception:
        dark = False
    line, back, down, text = (("#626262", "#3a3a3a", "#2f4f78", "#e8e8e8") if dark else
                              ("#9a9a9a", "#f4f4f4", "#c3cfdf", "#1e1e1e"))
    tabs.setStyleSheet(
        "QTabBar::tab { color: %s; background: %s; border: 1px solid %s; padding: 2px 6px; margin: 0px;"
        " min-width: 0px; } QTabBar::tab:selected { background: %s; } QTabBar::tab:!selected { border-left: 0px; }"
        " QTabBar::tab:first:!selected { border-left: 1px solid %s; }"
        " QTabBar::tab:selected:!first { border-left: 0px; }" % (text, back, line, down, line))
    tabs.setProperty("fw_xpert_tabs", True)
    bar = tabs.parentWidget()
    if bar is not None:
        bar.setFixedHeight(tabs.sizeHint().height() + 8)     # right under the check and cross, no gap


def _fw_retyped(spin):
    """True when the field's text is not what its value shows: a number typed and not taken yet.
    An untouched field is left alone (taking its rounded text again moved linked values: Flex's
    Radius 26.74 turned a typed Angle back to 89.99)."""
    try:
        return spin.text() != spin.prefix() + spin.textFromValue(spin.value()) + spin.suffix()
    except Exception:
        return True


class _LengthSpin(QtWidgets.QDoubleSpinBox):
    ""




    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(6)

    @staticmethod
    def _unit():
        ""



        try:
            text, factor, unit = App.Units.Quantity(25.4, App.Units.Length).getUserPreferred()
            factor = float(factor) or 1.0
            if "'" in text and '"' in text:           # feet and inches together: use inches
                return 25.4, "in"
            unit = {'"': "in", "'": "ft"}.get(unit.strip(), unit.strip())
            return factor, unit or "mm"
        except Exception:
            return 1.0, "mm"

    @staticmethod
    def _decimals():
        try:
            d = App.ParamGet("User parameter:BaseApp/Preferences/Units").GetInt("Decimals", 2)
        except Exception:
            d = 2
        return max(0, min(d, 6))

    @staticmethod
    def text_of(value):
        ""

        factor, unit = _LengthSpin._unit()
        try:
            v = float(value) / factor
        except Exception:
            return "%.2fmm" % value
        d = _LengthSpin._decimals()
        for extra in range(d, 7):
            if abs(round(v, extra) - v) < 1e-9:
                d = extra
                break
        return "%.*f%s" % (d, v, unit)

    @staticmethod
    def parse(text):
        """mm from typed text: a bare number is in the document's unit, else any length unit."""
        text = text.strip()
        if not text:
            return None
        try:
            return float(text) * _LengthSpin._unit()[0]
        except ValueError as _fw_err:
            _fw_log("filletpm.py:853", _fw_err)
        try:
            q = App.Units.Quantity(text)
            if q.Unit == App.Units.Length:
                return float(q.Value)
        except Exception as _fw_err:
            _fw_log("filletpm.py:859", _fw_err)
        return None

    def textFromValue(self, value):
        return self.text_of(value)

    def _parse(self, text):
        return self.parse(text)

    def valueFromText(self, text):
        v = self._parse(text)
        return self.value() if v is None else v

    def validate(self, text, pos):
        from PySide import QtGui
        if self._parse(text) is not None:
            return (QtGui.QValidator.Acceptable, text, pos)
        return (QtGui.QValidator.Intermediate, text, pos)

    def fixup(self, text):
        return self.textFromValue(self.value())


def _spin(parent, name, suffix, low, high, decimals=2):
    if suffix == "mm":
        s = _LengthSpin(parent)
        s.setObjectName(name)
        s.setRange(low, high)
        s.setKeyboardTracking(False)
        s.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        return s
    s = QtWidgets.QDoubleSpinBox(parent)
    s.setObjectName(name)
    s.setDecimals(decimals)
    s.setRange(low, high)
    s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    s.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    return s


class _ItemsList(QtWidgets.QListWidget):
    ""


    def __init__(self, panel, name):
        super().__init__()
        self.panel = panel
        self.setObjectName(name)
        self.setFixedHeight(56)
        self.setStyleSheet("QListWidget { background: %s; }" % PICK_BLUE)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        menu = QtWidgets.QMenu(self)
        clear = menu.addAction("Clear Selections")
        item = self.itemAt(pos)
        # the list is refilled by the preview while the menu is open, so the item goes: keep its row
        row = self.row(item) if item is not None else -1
        delete = menu.addAction("Delete") if item is not None else None
        chosen = menu.exec_(self.mapToGlobal(pos))
        if chosen is clear:
            self.panel.clear_items()
        elif delete is not None and chosen is delete and 0 <= row < len(self.panel.items):
            self.panel.remove_item(row)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self.currentRow() >= 0:
            self.panel.remove_item(self.currentRow())
            return
        super().keyPressEvent(event)


class _SetTwoList(_ItemsList):
    """Face Set 2 of a Face Face chamfer: its one row is the panel's second item."""

    def __init__(self, panel, name):
        super().__init__(panel, name)
        self.setFixedHeight(42)

    def _menu(self, pos):
        menu = QtWidgets.QMenu(self)
        clear = menu.addAction("Clear Selections")
        item = self.itemAt(pos)
        delete = menu.addAction("Delete") if item is not None else None
        chosen = menu.exec_(self.mapToGlobal(pos))
        if (chosen is clear or (delete is not None and chosen is delete)) and len(self.panel.items) > 1:
            self.panel.remove_item(1)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and self.count() and len(self.panel.items) > 1:
            self.panel.remove_item(1)
            return
        QtWidgets.QListWidget.keyPressEvent(self, event)


class _FaceSetClick(QtCore.QObject):
    ""

    def __init__(self, panel, n, widget):
        super().__init__(widget)
        self.panel, self.n = panel, n

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        try:
            if event.type() == QtCore.QEvent.MouseButtonPress and self.panel.mode() == "Face Face":
                self.panel.ff_set = self.n
                self.panel._fill()
        except Exception as _fw_err:
            _fw_log("filletpm.py:faceset", _fw_err)
        return False


def _seg_dist(p, a, b):
    """Screen distance from point p to segment ab (all (x, y))."""
    px, py = p[0], p[1]
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L < 1e-12 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    qx, qy = ax + t * dx, ay + t * dy
    return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5


# --------------------------------------------------------------------------- the pages
class DressUpPanel:
    """What Fillet and Chamfer share: the items, the feature, the preview, check and cross."""

    TYPE = None
    TITLE = None
    ICON = None
    ITEMS = None
    UNDO = None
    FACES_ONLY = False      # Shell and Draft take faces only
    UNIT = "mm"             # the callout's unit
    ASK_ALWAYS = False      # show what is missing even before the first pick

    def missing(self):
        """What must still be picked (shown above the first box), else None."""
        return None if self.items else "Select items."

    def __init__(self, doc, body, picks=(), feature=None, values=None, transaction=True):
        self._vis_before = _shown_now(body)
        global _current
        _current = self
        self.doc, self.body = doc, body
        self.edit = feature                 # an existing feature being edited, else None
        self.feature = feature
        self.items = []                     # base sub-element names ("Edge3", "Face2"), or "" = all edges
        self.ok = False
        self.closing = False
        self.converted = False
        if feature is not None:
            self.base = feature.Base[0] if feature.Base else feature.BaseFeature
            if getattr(feature, "UseAllEdges", False):
                self.items = [""]
            elif feature.Base:
                self.items = list(feature.Base[1])
        else:
            self.base = body.Tip
        self.before_tip = body.Tip
        if transaction and not App.getActiveTransaction():
            # the hidden scratch document the multi-radius, setback and offset fillets and chamfers
            # work in is made before this page's Undo step opens: a document made inside an open
            # step is what the Undo-step check flags (txnhook, offsetchamfer -> multiradius)
            try:
                from . import multiradius
                multiradius._scratch_doc()
            except Exception as _fw_err:
                _fw_log("filletpm.py:scratch-first", _fw_err)
        if transaction:
            doc.openTransaction("Edit " + feature.Label if feature is not None else self.UNDO)
        self.form = self.make_boxes()
        first = self.form[0]
        first.setProperty("swstyle_pm_title", feature.Label if feature is not None else self.TITLE)
        first.setProperty("swstyle_pm_icon", self.ICON)
        self.message = QtWidgets.QLabel("", first)
        self.message.setObjectName("SWDressUpMessage")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c00000;")
        self.message.hide()
        first.layout().addWidget(self.message)
        self._repair_row(first)
        if values:
            self.take_values(values)
        for obj, sub in picks:
            self._add(obj, sub)
        self.overlay = Overlay()
        view = _view_widget()
        self.callout = Callout(self, view) if view is not None else None
        self.strip = None
        if view is not None and hasattr(self, "toolbar_box"):
            from . import selectiontoolbar
            self.strip = selectiontoolbar.Strip(self, view)
        self._show_base()
        self._opening = True
        try:
            self.update()
        finally:
            self._opening = False
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        # FreeCAD can close the page without its check or cross (its "A dialog is already open"
        # Yes, a closed document): then nothing else would end this page (tester run11)
        first.destroyed.connect(self._form_gone)
        self._esc = _Escape(self)
        self._views = []
        # the task boxes exist only once the page is shown: fold boxes and hide the other tab's
        # frames then (a slow first show left them open on the PC, run20)
        self._when_shown(0)
        if view is not None:
            view.installEventFilter(self._esc)
            self._views.append(view)

    def _when_shown(self, tries):
        try:
            first = self.form[0]
            if self.closing or not alive(first) or getattr(self, "_shown_done", False):
                return
            # the page's first widget can sit in the PM title outside the task panel: wait for a
            # box of the panel itself to be on screen
            probe = self.form[1] if len(self.form) > 1 else first
            if tries == 0 and alive(probe):
                # the panel can come on screen late (a tab of the left pane shown later, a slow
                # PC): its first Show runs this too, whenever that is
                self._show_watch = _OnShow(probe, lambda: self._when_shown(-1))
            if tries >= 0 and not (alive(probe) and probe.isVisible()) and tries < 100:
                QtCore.QTimer.singleShot(50, lambda: self._when_shown(tries + 1))
                return
            if tries >= 0 and not (alive(probe) and probe.isVisible()):
                return      # never shown yet: its Show event does it
            self._shown_done = True
            name_headers(self.form)
            collapse_boxes(self.form)
            if getattr(self, "xpert", None) and hasattr(self, "tabs") and alive(self.tabs):
                index = self.tabs.currentIndex()
                if index == 0:
                    # the Manual tab the page opened on: its boxes only (the page is built already)
                    for w in self.manual:
                        box_visible(w, True)
                    for w in self.xpert:
                        box_visible(w, False)
                else:
                    self._tab(index)
            if hasattr(self, "_boxes_for_type"):
                self._boxes_for_type()      # Draft: the boxes of its type only
            QtCore.QTimer.singleShot(0, self._focus_value)
        except RuntimeError as _fw_err:
            _fw_log("filletpm.py:1058", _fw_err)


    # and its text selected, so the first keystrokes replace it
    FOCUS = None

    def _focus_value(self):
        try:
            field = getattr(self, self.FOCUS, None) if self.FOCUS else None
            if field is None or self.closing or not alive(field) or not field.isVisible() or not field.isEnabled():
                return
            field.setFocus(QtCore.Qt.OtherFocusReason)
            field.selectAll()
        except RuntimeError as _fw_err:
            _fw_log("filletpm.py:1072", _fw_err)

    # --- what each page fills in
    def make_boxes(self):
        raise NotImplementedError

    def size(self):
        raise NotImplementedError

    def set_size(self, value):
        raise NotImplementedError

    def apply(self, f):
        raise NotImplementedError

    def take_values(self, values):
        pass

    def remember(self):
        pass


    def _repair_row(self, box):
        self.repair_note = None
        if self.edit is None or self.edit.TypeId not in (FILLET, CHAMFER):
            return
        from . import dressrepair
        try:
            gone = dressrepair.missing(self.edit, self.base, [s for s in self.items if s])
        except Exception:
            gone = []
        if not gone:
            return
        row = QtWidgets.QWidget(box)
        row.setObjectName("SWDressUpRepairRow")
        lay = QtWidgets.QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.repair_note = QtWidgets.QLabel("Missing references: %s" % ", ".join(gone), row)
        self.repair_note.setObjectName("SWDressUpMissing")
        self.repair_note.setWordWrap(True)
        self.repair_note.setStyleSheet("color: #c00000;")
        self.repair_button = QtWidgets.QPushButton("Repair", row)
        self.repair_button.setObjectName("SWDressUpRepair")
        self.repair_button.setToolTip("Replace each missing edge or face by the one now in its place")
        self.repair_button.clicked.connect(self.repair_references)
        lay.addWidget(self.repair_note, 1)
        lay.addWidget(self.repair_button)
        box.layout().addWidget(row)
        self.repair_row = row

    def repair_references(self):
        from . import dressrepair
        old = [s for s in self.items if s]
        new, unmatched = dressrepair.repair(self.edit, self.base, old)
        self.items = new
        try:
            dressrepair.remap_stored(self.edit, old, new)
        except Exception as _fw_err:
            _fw_log("filletpm.py:1130", _fw_err)
        self._fill()
        self.update()
        if unmatched:
            self.repair_note.setText("No match found for: %s. Pick them again." % ", ".join(unmatched))
        else:
            self.repair_row.hide()
        return new, unmatched

    # --- visibility: the base is shown (picks land on it), the feature is drawn as the preview
    def _show_base(self):
        try:
            for f in _features(self.body):
                if f is not self.base and f.ViewObject.Visibility:
                    f.ViewObject.Visibility = False
            if self.base is not None:
                self.base.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("filletpm.py:1148", _fw_err)

    def _restore(self):
        try:
            tip = self.body.Tip
            shown = _features(self.body)
            if tip is not None and tip not in shown:
                shown.append(tip)
            for f in shown:
                want = f is tip
                if f.ViewObject.Visibility != want:
                    f.ViewObject.Visibility = want
        except Exception as _fw_err:
            _fw_log("filletpm.py:1161", _fw_err)

    # --- picks
    def addSelection(self, doc, name, sub, pnt):
        try:
            if current() is not self or self.closing or doc != self.doc.Name:
                return
        except Exception:
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        QtCore.QTimer.singleShot(0, lambda: self._picked(obj, sub, pnt))

    # --- Select through faces (Fillet and Chamfer Options): a click on a face near an edge

    def _through_box(self, parent):
        self.through = QtWidgets.QCheckBox("Select through faces", parent)
        self.through.setObjectName("SWSelectThroughFaces")
        self.through.setToolTip("Select through faces: a click picks an edge hidden behind the faces")
        self.through.setChecked(params().GetBool("SelectThroughFaces", False))
        self.through.toggled.connect(lambda on: params().SetBool("SelectThroughFaces", on))
        return self.through

    def _edge_through(self, obj, sub, pnt, reach=6.0):
        """The base's edge nearest the click on screen (hidden ones too), within reach pixels."""
        through = getattr(self, "through", None)
        if through is None or not through.isChecked() or pnt is None or not sub.startswith("Face"):
            return None
        if obj is not self.base and obj.TypeId != "PartDesign::Body" and obj not in _features(self.body):
            return None
        try:
            view = Gui.ActiveDocument.ActiveView
            click = view.getPointOnViewport(App.Vector(*pnt))
        except Exception:
            return None
        best, name = reach, None
        for i, e in enumerate(self.base.Shape.Edges, 1):
            try:
                pts = e.discretize(24)
            except Exception:
                continue
            for k in range(len(pts) - 1):
                a = view.getPointOnViewport(pts[k])
                b = view.getPointOnViewport(pts[k + 1])
                d = _seg_dist(click, a, b)
                if d < best:
                    best, name = d, "Edge%d" % i
        return name

    def _corner_near(self, obj, sub, pnt, pixels=8):
        ""

        try:
            shape = obj.Shape
            edge = shape.getElement(sub)
            view = Gui.ActiveDocument.ActiveView
            at = view.getPointOnViewport(App.Vector(*pnt))
            try:
                dpr = float(QtWidgets.QApplication.instance().devicePixelRatio() or 1.0)
            except Exception:
                dpr = 1.0
            best = None
            for v in edge.Vertexes:
                s = view.getPointOnViewport(v.Point)
                d = ((s[0] - at[0]) ** 2 + (s[1] - at[1]) ** 2) ** 0.5
                if d <= pixels * dpr and (best is None or d < best[0]):
                    best = (d, v)
            if best is None:
                return None
            return next(("Vertex%d" % i for i, v in enumerate(shape.Vertexes, 1) if v.isSame(best[1])), None)
        except Exception as _fw_err:
            _fw_log("filletpm.py:_corner_near", _fw_err)
        return None

    def _picked(self, obj, sub, pnt=None):
        if self.closing:
            return
        r_obj, r_sub = refplane.resolve(obj, sub or "")
        edge = self._edge_through(r_obj, r_sub or "", pnt)
        if edge is not None:
            obj, sub = self.base, edge
        elif r_sub and r_sub.startswith(("Edge", "Face")) and pnt is not None and getattr(self, "TYPE", None) == CHAMFER \
                and self.vertex_mode():
            vtx = self._corner_near(r_obj, r_sub, pnt)
            if vtx is not None:
                obj, sub = r_obj, vtx
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("filletpm.py:1221", _fw_err)
        if self.TYPE == FILLET and hasattr(self, "xpert_bar"):
            from . import filletxpert
            if filletxpert.picked(self, obj, sub):
                return
        if self.TYPE == DRAFT and hasattr(self, "dx_bar"):
            from . import draftxpert
            if draftxpert.picked(self, obj, sub):
                return
        before = list(self.items)
        if self._add(obj, sub):
            self.update()
            self._strip_after(before)

    def _strip_after(self, before):
        ""
        strip = getattr(self, "strip", None)
        if strip is None or not alive(strip):
            return
        added = [s for s in self.items if s not in before]
        box = getattr(self, "toolbar_box", None)
        kinds = ("Edge", "Face") if getattr(self, "face_accelerators", False) else ("Edge",)
        if box is not None and box.isChecked() and len(added) == 1 and added[0].startswith(kinds):
            strip.show_for(added[0])
        else:
            strip.close_strip()

    def _toolbar_toggled(self, name, on):
        params().SetBool(name + "SelectionToolbar", on)
        strip = getattr(self, "strip", None)
        if strip is not None and alive(strip):
            kinds = ("Edge", "Face") if getattr(self, "face_accelerators", False) else ("Edge",)
            if on and self.items and self.items[-1].startswith(kinds):
                strip.show_for(self.items[-1])
            else:
                strip.close_strip()

    def _add(self, obj, sub):
        """Adds (or, picked again, takes out) one item; True when the list changed."""
        obj, sub = refplane.resolve(obj, sub or "")
        if self.base is None:
            return False
        if self.other_pick(obj, sub):
            return True
        if not sub and self.FACES_ONLY:
            return False
        if not sub:

            # again, they come out. The body, or a feature whose edges cannot be told: all edges.
            own = feature_edges(self.base, obj) if obj is not self.body and obj in _features(self.body) else None
            if own:
                if "" in self.items:
                    self.items.remove("")
                if all(n in self.items for n in own):
                    self.items = [n for n in self.items if n not in own]
                else:
                    self.items += [n for n in own if n not in self.items]
                return True
            if obj is self.body or obj in _features(self.body):
                if "" in self.items:
                    self.items.remove("")
                else:
                    self.items = [""]
                return True
            return False
        if not (sub.startswith("Edge") or sub.startswith("Face")):
            return False
        if self.FACES_ONLY and not sub.startswith("Face"):
            return False
        if obj is not self.base and obj.TypeId != "PartDesign::Body" and obj not in _features(self.body):
            return False
        name = to_base(self.base, obj, sub)
        if name is None:
            return False
        if "" in self.items:
            self.items.remove("")
        if name in self.items:
            self.items.remove(name)
        else:
            self.items.append(name)
        return True

    def other_pick(self, obj, sub):
        """A pick for another box of the page (Draft's Neutral Plane); True when it took it."""
        return False

    def clear_items(self):
        self.items = []
        self.update()

    def remove_item(self, row):
        if 0 <= row < len(self.items):
            del self.items[row]
            self.update()

    def item_names(self):
        ""
        counts, names = {}, []
        for sub in self.items:
            if not sub:
                names.append(self.base.Label if self.base is not None else "")
                continue
            kind = "Edge" if sub.startswith("Edge") else "Face"
            counts[kind] = counts.get(kind, 0) + 1
            names.append("%s<%d>" % (kind, counts[kind]))
        return names

    # --- the feature
    def _make(self):
        if self.feature is None:
            self.feature = self._new_native()
            try:
                self.feature.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("filletpm.py:1325", _fw_err)
        return self.feature

    def _new_native(self):
        ""

        label = None
        try:
            from . import naming
            label = naming.next_label(self.doc, self.TITLE)
        except Exception as _fw_err:
            _fw_log("filletpm.py:1336", _fw_err)
        f = self.body.newObject(self.TYPE, self.TITLE)
        if label:
            f.Label = label
        return f

    def _drop(self):
        if self.feature is not None and self.edit is None:
            name = self.feature.Name
            try:
                self.body.removeObject(self.feature)
            except Exception as _fw_err:
                _fw_log("filletpm.py:1348", _fw_err)
            try:
                self.doc.removeObject(name)
            except Exception as _fw_err:
                _fw_log("filletpm.py:1352", _fw_err)
            self.feature = None
            if self.before_tip is not None and self.before_tip in self.body.Group:
                self.body.Tip = self.before_tip

    def try_passes(self, f):
        return False

    def _base_crossing(self):
        """True when the part before the fillet already fails the fold check: OpenCascade flags some
        good PartDesign cuts (the triple clamp's slit), so only a fold the round makes counts."""
        shape = self.base.Shape if self.base is not None else None
        key = (getattr(self.base, "Name", None), shape.hashCode() if shape is not None else None)
        if getattr(self, "_base_check", (None, None))[0] != key:
            self._base_check = (key, shape is not None and _self_crossing(shape))
        return self._base_check[1]

    def update(self):
        self.ok = False
        self._brep_fail = False
        text = ""
        missing = self.missing()
        if missing:
            self._drop()
            self.doc.recompute()
            text = missing if self.items or self.ASK_ALWAYS else ""
        else:
            # an edit opening on the feature as it is: it is built already, nothing to rebuild
            same = getattr(self, "_opening", False) and self.edit is not None and self.feature is self.edit
            f = self.feature if same else self._make()
            try:
                if not same:
                    if self.items == [""]:
                        f.UseAllEdges = True
                        f.Base = (self.base, [])
                    else:
                        if hasattr(f, "UseAllEdges"):
                            f.UseAllEdges = False
                        f.Base = (self.base, list(self.items))
                    self.apply(f)
                    self._build_preview()
                bad = "Invalid" in f.State or not f.isValid() or f.Shape.isNull()
                if bad and self.TYPE == FILLET and self._hair_less(f):
                    bad = False
                if not bad and not same and self.TYPE == FILLET and len(self.items) > 1 and \
                        not f.Shape.isValid():
                    # OpenCascade "made" it but the solid fails its own check (the wheel's four hub

                    bad = True
                    self._brep_fail = True
                    text = ("The %s could not be made with these items at this size: try a "
                            "smaller value, or fewer items." % self.TITLE.lower())
                if not bad and not same and self.TYPE in (FILLET, CHAMFER) and _self_crossing(f.Shape) and \
                        not self._base_crossing():
                    # OpenCascade's "valid" round wider than the wall folds through it (PM ff2):

                    bad = True
                    text = ("The %s could not be made with these items at this size: try a "
                            "smaller value, or fewer items." % self.TITLE.lower())
                status = f.getStatusString() if bad else ""
                smooth = self.TYPE in (FILLET, CHAMFER) and self.items != [""] and (
                    "No edges" in status or (not bad and self.unchanged(f)))
                if smooth:
                    # FreeCAD drops edges between tangent faces ("not C0 continuous"), then says
                    # "No edges specified" or makes nothing at all (tester run14)
                    bad = True
                    text = ("Cannot %s the picked edges: their faces meet tangentially (smooth "
                            "edges). Pick sharp edges." % self.TITLE.lower())
                elif bad and text:
                    pass
                elif bad:
                    text = status or ("The %s could not be made." % self.TITLE.lower())
                    if "BRep_API" in text or "command not done" in text:
                        # tried in passes on OK only: a live retry in passes was slow enough to eat
                        # the typed radius and Enter (PM thread, triple clamp at the default R10)
                        self._brep_fail = True
                        # OpenCascade's own words say nothing to a person (tester, hollow box)
                        text = ("The %s could not be made with these items at this size: try a "
                                "smaller value, or fewer items." % self.TITLE.lower())
                    elif self.TYPE == SHELL and any(w in text for w in ("Creation of solid failed", "failed",
                                                                         "Standard_", "OCC", "TopoDS")):
                        # OpenCascade's "Creation of solid failed: " showed in the Shell page while the
                        # default 10 mm wall was too thick for the part (features walk 418)
                        text = ("The shell could not be made at this thickness: try a smaller thickness, "
                                "or other faces to remove.")
                self.ok = not bad
                if self.ok and not text and self.TYPE in (FILLET, CHAMFER):
                    # FreeCAD leaves smooth picks out without a word (EX506: in Top view the upright's
                    # top edge, between a flat side and its round top, hides the foot edge under it)
                    soft = smooth_edges(self.base.Shape if self.base is not None else None, self.items)
                    if soft:
                        text = ("%s %s between faces that meet tangentially (smooth), so %s nothing to round "
                                "and %s left out. Rotate the view to pick the edge you meant."
                                % (", ".join(soft), "lies" if len(soft) == 1 else "lie",
                                   "it has" if len(soft) == 1 else "they have", "is" if len(soft) == 1 else "are"))
            except Exception as error:
                text = str(error)
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self.message.setStyleSheet("color: #c00000;" if self.ok is False and self.items and not missing else "")
        self._show_base()
        self._fill()
        self._draw()
        if not self.ok and getattr(self, "_brep_fail", False) and not getattr(self, "_live_retry", False):

            # (passes, overflow, corner blend) is tried at once; many edges wait for OK (slow)
            try:
                few = len(self._edges_of_items()) <= 6
            except Exception:
                few = False
            if few and self.try_passes(self.feature):
                self._live_retry = True
                try:
                    self.update()
                finally:
                    self._live_retry = False

    def _hair_less(self, f):
        ""



        prop = "Radius" if "Radius" in f.PropertiesList else None
        if prop is None:
            return False
        r = float(getattr(f, prop))
        if r <= 1e-6:
            return False
        try:
            for less in (1e-6, 1e-5):
                setattr(f, prop, r - less)
                self.doc.recompute()
                if not ("Invalid" in f.State or not f.isValid() or f.Shape.isNull()) and \
                        not _self_crossing(f.Shape):
                    return True
            setattr(f, prop, r)
            self.doc.recompute()
            return False
        except Exception as _fw_err:
            _fw_log("filletpm.py:1520", _fw_err)
            return False

    def unchanged(self, f):
        """True when the feature's solid is the base's: nothing was cut or added."""
        try:
            a, b = f.Shape, self.base.Shape
            return abs(a.Volume - b.Volume) < 1e-9 and len(a.Faces) == len(b.Faces)
        except Exception:
            return False

    def _flat_can(self):
        """conicfillet's profiles (the flat chamfer too) make straight edges between flat faces only."""
        from . import conicfillet
        if self.base is None:
            return False
        try:
            return conicfillet.supported(self.base.Shape, self._edges_of_items())
        except Exception as _fw_err:
            _fw_log("filletpm.py:1539", _fw_err)
            return False

    def _edges_of_items(self):
        edges = []
        if self.base is None:
            return edges
        shape = self.base.Shape
        for sub in self.items:
            try:
                if not sub:
                    edges += list(shape.Edges)
                else:
                    element = shape.getElement(sub)
                    edges += list(element.Edges) if sub.startswith("Face") else [element]
            except Exception as _fw_err:
                _fw_log("filletpm.py:1555", _fw_err)
                continue
        return edges

    def _build_preview(self):
        ""



        from . import rebuildstatus
        rebuildstatus.PREVIEW[0] = True
        began = time.monotonic()
        try:
            self.doc.recompute()
        finally:
            rebuildstatus.PREVIEW[0] = False
        self._preview_cancelled = False
        if time.monotonic() - began >= SLOW_PREVIEW:
            _catch_esc(self)

    def _cancel_preview(self):
        self._preview_cancelled = True
        try:
            self.overlay.show_preview([])
            Gui.getMainWindow().statusBar().showMessage("Preview cancelled", 3000)
        except Exception as _fw_err:
            _fw_log("filletpm.py:1543", _fw_err)

    def _draw(self):
        edges = self._edges_of_items()
        self.overlay.show_picks(edges)
        faces = []
        mode = self.preview_mode()
        if getattr(self, "_preview_cancelled", False):
            mode = "No preview"
        if self.ok and self.feature is not None and mode != "No preview":
            try:
                faces = new_faces(self.base.Shape, self.feature.Shape)
            except Exception:
                faces = []
            if mode == "Partial preview" and faces and self.items:
                last = self._edges_of_items_for(self.items[-1])
                reach = max(self.size(), 0.1) * 1.5
                faces = [f for f in faces if any(f.distToShape(e)[0] < reach for e in last)]
        self.overlay.show_preview(faces)
        if self.callout is not None:
            anchor = None
            if edges and self.items:
                last = self._edges_of_items_for(self.items[-1])
                if last:
                    e = last[0]
                    anchor = e.valueAt((e.FirstParameter + e.LastParameter) / 2.0)
            self.callout.set_rows(self.callout_rows(), anchor)
        try:
            # a redraw of the 3D view is asked for; Gui.updateGui() here ran the whole event loop
            # inside every preview (50-120 ms on a page open)
            Gui.ActiveDocument.ActiveView.redraw()
        except Exception as _fw_err:
            _fw_log("filletpm.py:1575", _fw_err)

    def _edges_of_items_for(self, sub):
        try:
            if not sub:
                return list(self.base.Shape.Edges)
            element = self.base.Shape.getElement(sub)
            return list(element.Edges) if sub.startswith("Face") else [element]
        except Exception as _fw_err:
            _fw_log("filletpm.py:1622", _fw_err)
            return []

    def callout_name(self):
        return "Radius"

    def callout_rows(self):
        """[(name, value, unit, setter)] shown in the callout."""
        return [(self.callout_name(), self.size(), self.UNIT, self.set_size)]

    def preview_mode(self):
        for b in self.preview_buttons:
            if b.isChecked():
                return b.text()
        return PREVIEWS[0]

    def _fill(self):
        self.list.blockSignals(True)
        self.list.clear()
        for n in self.item_names():
            self.list.addItem(n)
        if self.list.count():
            self.list.setCurrentRow(self.list.count() - 1)
        self.list.blockSignals(False)

    def _preview_rows(self, box, name):
        self.preview_buttons = []
        group = QtWidgets.QButtonGroup(box)
        chosen = params().GetString(name + "Preview", PREVIEWS[0])
        for text in PREVIEWS:
            r = QtWidgets.QRadioButton(text, box)
            r.setObjectName("SW%s%s" % (name, text.replace(" ", "")))
            r.setChecked(text == chosen)
            group.addButton(r)
            box.layout().addWidget(r)
            self.preview_buttons.append(r)
            r.toggled.connect(lambda on, t=text: on and self._preview_changed(name, t))

    def _preview_changed(self, name, text):
        params().SetString(name + "Preview", text)
        self._draw()

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _form_gone(self, *args):
        """The page's widgets were deleted by FreeCAD, not by the check or cross: end the page as
        its cross would (the feature being made goes), without touching its widgets."""
        global _current
        if self.closing:
            return
        self.closing = True
        if _current is self:
            _current = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("filletpm.py:1641", _fw_err)
        QtCore.QTimer.singleShot(0, self._after_gone)

    def _after_gone(self):
        for w in self._views:
            if alive(w):
                try:
                    w.removeEventFilter(self._esc)
                except Exception as _fw_err:
                    _fw_log("filletpm.py:1650", _fw_err)
        self._views = []
        for step in (lambda: self.overlay.remove(),
                     lambda: alive(self.strip) and self.strip.remove(),
                     lambda: alive(self.callout) and (self.callout.timer.stop(), self.callout.hide(),
                                                      self.callout.deleteLater())):
            try:
                step()
            except Exception as _fw_err:
                _fw_log("filletpm.py:1659", _fw_err)
        self.strip = self.callout = None
        if self.converted:
            return
        try:
            self.doc.abortTransaction()
            self.doc.recompute()
            self._restore()
        except Exception as _fw_err:
            _fw_log("filletpm.py:1668", _fw_err)

    def _close(self):
        global _current
        self.closing = True
        if _current is self:
            _current = None
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("filletpm.py:1678", _fw_err)
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("filletpm.py:1683", _fw_err)
        self._views = []
        self.overlay.remove()
        strip = getattr(self, "strip", None)
        if strip is not None and alive(strip):
            strip.remove()
        self.strip = None
        if self.callout is not None and alive(self.callout):
            self.callout.timer.stop()
            self.callout.hide()
            self.callout.deleteLater()
        self.callout = None
        Gui.Control.closeDialog()

    def _take_typed(self):
        ""


        try:
            from . import pmvalues as _fw_pmv
            _fw_pmv.hide_lists()
        except Exception as _fw_err:
            _fw_log("filletpm.py:lists", _fw_err)
        boxes = self.form if isinstance(getattr(self, "form", None), list) else [getattr(self, "form", None)]
        for box in boxes:
            if box is None:
                continue
            try:
                for spin in box.findChildren(QtWidgets.QAbstractSpinBox):
                    if not spin.keyboardTracking() and spin.isVisible() and spin.isEnabled() and _fw_retyped(spin):
                        spin.interpretText()
            except Exception as _fw_err:
                _fw_log("filletpm.py:typed", _fw_err)

    def accept(self):
        if self.converted:
            return True
        self._take_typed()
        if self.missing():
            return False
        if not self.ok and getattr(self, "_brep_fail", False) and self.try_passes(self.feature):
            self.update()       # OpenCascade refused the edges in one go: made in passes (multiradius)
        if not self.ok:
            return False
        self.remember()
        if self.feature is not None and self.feature.TypeId in (FILLET, CHAMFER):
            try:
                from . import dressrepair
                dressrepair.store(self.feature)     # Repair Missing References finds them again
            except Exception as error:
                App.Console.PrintLog("FreeCAD: fillet references: %s\n" % error)
        self.doc.commitTransaction()
        self._restore()
        self._close()
        return True

    def reject(self):
        if self.converted:
            return True
        self.doc.abortTransaction()
        self.doc.recompute()
        self._restore()
        _show_again(self.doc, self._vis_before)
        self._close()
        return True

    # --- Fillet <-> Chamfer
    def convert(self, other):
        """Replaces the edited feature in place by the other kind, keeping the items. It stays
        in this page's Undo step: the other page's check keeps it, its cross takes it back."""
        if self.edit is None:
            return
        self.converted = True
        old = self.edit
        items, base = list(self.items), self.base
        size = self.size()
        self._close()
        try:
            new = replace(old, other.TYPE, base, items, size)
        except Exception as error:
            self.doc.abortTransaction()
            self.doc.recompute()
            App.Console.PrintError("FreeCAD: %s could not be converted: %s\n" % (old.Label, error))
            return
        QtCore.QTimer.singleShot(0, lambda: open_page(new, transaction=False))


def _shown_now(body):
    """{name: shown} of the body's features as the page opens (a pattern left after the Tip stays shown)."""
    try:
        return {o.Name: bool(o.ViewObject.Visibility) for o in body.Group
                if o.ViewObject is not None and o.isDerivedFrom("Part::Feature")}
    except Exception as _fw_err:
        _fw_log("filletpm.py:shown_now", _fw_err)
        return {}


def _show_again(doc, shown):
    for name, on in (shown or {}).items():
        o = doc.getObject(name)
        try:
            if o is not None and o.ViewObject is not None and bool(o.ViewObject.Visibility) != on:
                o.ViewObject.Visibility = on
        except Exception as _fw_err:
            _fw_log("filletpm.py:show_again", _fw_err)


def replace(old, type_id, base, items, size):
    """A new feature of type_id in old's place in the body (same base, same items, children
    re-linked), old deleted. Returns the new feature."""
    doc = old.Document
    body = old.getParentGeoFeatureGroup()
    was_tip = body.Tip is old
    label = old.Label
    new = doc.addObject(type_id, "Chamfer" if type_id == CHAMFER else "Fillet")
    body.insertObject(new, old, True)       # right after the old one
    new.Base = (base, [] if items == [""] else [s for s in items if s])
    new.UseAllEdges = items == [""]
    if type_id == CHAMFER:
        new.ChamferType = "Distance and Angle"
        new.Size = size
        new.Angle = 45.0
    else:
        new.Radius = size
    for child in [o for o in old.InList if o is not new]:
        if getattr(child, "BaseFeature", None) is old:
            child.BaseFeature = new
    if was_tip:
        body.Tip = new
    body.removeObject(old)
    doc.removeObject(old.Name)
    new.Label = _next_label(doc, "Chamfer" if type_id == CHAMFER else "Fillet", new)
    doc.recompute()
    try:
        tip = body.Tip
        for f in _features(body):
            f.ViewObject.Visibility = f is tip
    except Exception as _fw_err:
        _fw_log("filletpm.py:1779", _fw_err)
    return new


def _next_label(doc, stem, new):
    used = {o.Label for o in doc.Objects if o is not new}
    n = 1
    while "%s%d" % (stem, n) in used:
        n += 1
    return "%s%d" % (stem, n)


class _Escape(QtCore.QObject):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == Qt.Key_Escape \
                and not (event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier)):
            if t == QtCore.QEvent.KeyPress and current() is self.panel:
                QtCore.QTimer.singleShot(0, self.panel.reject)
            return True
        return False


def _feature_type_box(panel, kind):
    ""

    box = _box("Feature Type")
    row = QtWidgets.QHBoxLayout()
    row.setSpacing(0)
    row.addStretch(1)
    group = QtWidgets.QButtonGroup(box)
    for name, family, tip, this in (
            ("SWFeatureTypeChamfer", "FEATURES_CHAMFER", "Chamfer", CHAMFER),
            ("SWFeatureTypeFillet", "FEATURES_FILLET", "Fillet", FILLET)):
        b = _icon_button(box, name, tip, family)
        group.addButton(b)
        b.setChecked(this == kind)
        if this == kind:
            b.clicked.connect(lambda checked=False, b=b: b.setChecked(True))
        else:
            other = "ChamferPanel" if this == CHAMFER else "FilletPanel"
            b.clicked.connect(lambda checked=False, o=other: panel.convert(globals()[o]))
        row.addWidget(b)
    row.addStretch(1)
    box.layout().addLayout(row)
    return box


def _keep_of(feature):
    """Keep features of a fillet being edited (on for FreeCAD's own and a new one)."""
    from . import setbackfillet
    if feature is not None and setbackfillet.is_setback_fillet(feature):
        return bool(getattr(feature, "KeepFeatures", True))
    return True


def _overflow_of(feature):
    from . import conicfillet
    if feature is not None and conicfillet.is_conic_fillet(feature):
        return str(getattr(feature, "Overflow", "Default"))
    return "Default"


def _round_of(feature):
    """Round corners of a fillet being edited (off for FreeCAD's own and a new one)."""
    from . import setbackfillet
    if feature is not None and setbackfillet.is_setback_fillet(feature):
        return bool(getattr(feature, "RoundCorners", False))
    return False


def _tangent_of(feature):
    """Tangent propagation as the edited feature has it (FreeCAD's own: always on)."""
    return bool(getattr(feature, "TangentPropagation", True)) if feature is not None else True


class _ChamferFlat:
    """The chamfer that stops where Tangent propagation is off: conicfillet's flat profile."""
    from . import conicfillet as _cf
    TYPE = _cf.TYPE

    @staticmethod
    def new(body):
        from . import conicfillet
        f = conicfillet.new(body, "Chamfer")
        f.Kind = "Chamfer"
        return f

    @staticmethod
    def setup_new(obj):
        from . import conicfillet
        conicfillet.setup_new(obj)
        obj.Kind = "Chamfer"
        return obj


class FilletPanel(DressUpPanel):
    TYPE = FILLET
    TITLE = "Fillet"
    ICON = "FEATURES_FILLET"
    UNDO = "Fillet"

    FOCUS = "radius"

    def make_boxes(self):
        self.type_buttons = []
        if self.edit is not None:

            # Type box with Chamfer and Fillet turns the fillet into a chamfer in place.
            boxes = [_feature_type_box(self, FILLET)]
        else:
            bar = _box("Fillet", bare=True)
            tabs = QtWidgets.QTabBar(bar)
            tabs.setObjectName("SWFilletTabs")
            tabs.addTab("Manual")
            tabs.addTab("FilletXpert")
            tabs.setExpanding(False)
            tabs.setDrawBase(False)
            self.tabs = tabs
            tabs.currentChanged.connect(self._tab)
            holder = QtWidgets.QHBoxLayout()
            holder.addStretch(1)
            holder.addWidget(tabs)          # centred joined buttons (fillettypes-1121, desktop recording)
            holder.addStretch(1)
            _xpert_tabs(tabs)
            bar.layout().addLayout(holder)
            top = _box("Fillet Type")
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(0)
            for i, (tip, family, command) in enumerate(FILLET_TYPES):
                b = _icon_button(top, "SWFilletType%d" % i, tip, family)
                b.setChecked(i == 0)
                if i:
                    b.clicked.connect(lambda checked=False, c=command: self.switch(c))
                else:
                    b.clicked.connect(lambda checked=False, b=b: b.setChecked(True))
                row.addWidget(b)
                self.type_buttons.append(b)
            row.addStretch(1)
            top.layout().addLayout(row)
            boxes = [bar, top]

        items = _box("Items To Fillet")
        self.list = _ItemsList(self, "SWFilletItems")
        items.layout().addWidget(self.list)
        self.toolbar_box = QtWidgets.QCheckBox("Show selection toolbar", items)
        self.toolbar_box.setObjectName("SWFilletSelectionToolbar")
        self.toolbar_box.setChecked(params().GetBool("FilletSelectionToolbar", True))
        self.toolbar_box.toggled.connect(lambda on: self._toolbar_toggled("Fillet", on))
        items.layout().addWidget(self.toolbar_box)
        tangent = QtWidgets.QCheckBox("Tangent propagation", items)
        tangent.setObjectName("SWFilletTangent")
        tangent.setChecked(_tangent_of(self.edit))
        tangent.toggled.connect(lambda on: self._tangent_toggled())
        self.tangent = tangent
        items.layout().addWidget(tangent)
        self._preview_rows(items, "Fillet")

        parms = _box("Fillet Parameters")
        kind = QtWidgets.QComboBox(parms)
        kind.setObjectName("SWFilletSymmetric")
        kind.addItems(["Symmetric", "Asymmetric"])
        self.symmetric = kind
        parms.layout().addWidget(kind)
        self.radius = _spin(parms, "SWFilletRadius", "mm", 0.001, 1e6)
        self.radius.setValue(params().GetFloat("FilletRadius", 10.0) if self.edit is None else self.edit.Radius.Value)
        self.radius.valueChanged.connect(self._radius_changed)
        self.list.currentRowChanged.connect(self._row_changed)
        r_row = QtWidgets.QHBoxLayout()
        r_icon = QtWidgets.QLabel("R", parms)
        r_icon.setToolTip("Radius")
        self.r_icon = r_icon
        r_row.addWidget(r_icon)
        r_row.addWidget(self.radius)
        parms.layout().addLayout(r_row)
        # Asymmetric: Distance 1 and Distance 2 along the two faces, Reverse direction swaps them
        p = params()
        form = QtWidgets.QFormLayout()
        self.fd1 = _spin(parms, "SWFilletDistance1", "mm", 0.001, 1e6)
        self.fd2 = _spin(parms, "SWFilletDistance2", "mm", 0.001, 1e6)
        self.fd1_label = QtWidgets.QLabel("D1", parms)
        self.fd2_label = QtWidgets.QLabel("D2", parms)
        form.addRow(self.fd1_label, self.fd1)
        form.addRow(self.fd2_label, self.fd2)
        parms.layout().addLayout(form)
        self.reverse = QtWidgets.QCheckBox("Reverse direction", parms)
        self.reverse.setObjectName("SWFilletReverse")
        parms.layout().addWidget(self.reverse)
        # Multi Radius Fillet: every item keeps a radius of its own; R is the highlighted item's
        from . import multiradius
        self.radii = {}
        self._row = None
        self.multi_box = QtWidgets.QCheckBox("Multi Radius Fillet", parms)
        self.multi_box.setObjectName("SWFilletMultiRadius")
        from . import setbackfillet

        # as the plain fillet it is
        self._split = bool(self.edit is not None and multiradius.is_multi_radius(self.edit)
                           and getattr(self.edit, "InPasses", False))
        if self.edit is not None and not self._split and (multiradius.is_multi_radius(self.edit) or (
                setbackfillet.is_setback_fillet(self.edit) and len(self.edit.ItemRadii))):
            self.multi_box.setChecked(True)
            subs = list(self.edit.Base[1]) if self.edit.Base else []
            for sub, r in zip(subs, self.edit.ItemRadii):
                self.radii[sub] = float(r)
        self.multi_box.toggled.connect(self._multi_toggled)
        parms.layout().addWidget(self.multi_box)
        parms.layout().addWidget(QtWidgets.QLabel("Profile:", parms))
        profile = QtWidgets.QComboBox(parms)
        profile.setObjectName("SWFilletProfile")
        profile.addItems(["Circular", "Conic Rho", "Conic Radius", "Curvature Continuous"])
        self.profile = profile
        parms.layout().addWidget(profile)
        form2 = QtWidgets.QFormLayout()
        self.rho = _spin(parms, "SWFilletRho", "", 0.01, 0.99)
        self.conic_radius = _spin(parms, "SWFilletConicRadius", "mm", 0.001, 1e6)
        self.rho_label = QtWidgets.QLabel("Rho", parms)
        self.conic_label = QtWidgets.QLabel("Conic radius", parms)
        form2.addRow(self.rho_label, self.rho)
        form2.addRow(self.conic_label, self.conic_radius)
        parms.layout().addLayout(form2)
        self._load_profile(p)
        for w in (self.fd1, self.fd2, self.rho, self.conic_radius):
            w.valueChanged.connect(lambda v: self.update())
        self.reverse.toggled.connect(lambda on: self.update())
        kind.activated.connect(lambda i: self._shape_changed())
        profile.activated.connect(lambda i: self._shape_changed())
        self._profile_rows()

        setback = self._setback_box()
        partial = self._partial_box()
        options = _box("Fillet Options", collapsed=True)
        for text, on in (("Select through faces", False), ("Keep features", True), ("Round corners", False)):
            if text == "Select through faces":
                options.layout().addWidget(self._through_box(options))
                continue
            c = QtWidgets.QCheckBox(text, options)
            c.setChecked(on)
            if text == "Keep features":
                # off: the fillet rolls over the bosses and cuts inside its radius (setbackfillet)
                c.setObjectName("SWFilletKeepFeatures")
                c.setChecked(_keep_of(self.edit))
                c.toggled.connect(lambda on: self.update())
                self.keep = c
                options.layout().addWidget(c)
                continue
            if text == "Round corners":
                # the fillets run round the corners where two of them meet (setbackfillet)
                c.setObjectName("SWFilletRoundCorners")
                c.setChecked(_round_of(self.edit))
                c.toggled.connect(lambda on: self.update())
                self.round = c
                options.layout().addWidget(c)
                continue
            options.layout().addWidget(_greyed(c, NOT_YET))
        options.layout().addWidget(QtWidgets.QLabel("Overflow type:", options))
        # where the fillet would run past a face's edge: Keep edge squeezes the fillet's section
        # so the edge stays, Keep surface trims the fillet at the next face (conicfillet.py)
        self.overflow_buttons = []
        group = QtWidgets.QButtonGroup(options)
        chosen = _overflow_of(self.edit)
        for i, text in enumerate(("Default", "Keep edge", "Keep surface")):
            r = QtWidgets.QRadioButton(text, options)
            r.setObjectName("SWFilletOverflow%d" % i)
            r.setChecked(text == chosen)
            group.addButton(r)
            r.toggled.connect(lambda on: on and self.update())
            options.layout().addWidget(r)
            self.overflow_buttons.append(r)
        self.manual = boxes[1:] + [items, parms, setback, partial, options]
        if self.edit is not None:
            self.xpert = []
            return boxes + self.manual
        self.xpert = self._xpert_boxes()
        for w in self.xpert:
            w.setVisible(False)
        return boxes[:1] + self.manual + self.xpert

    # --- Partial Edge Parameters (setbackfillet.partial_edge): the fillet of one edge runs only
    # between a start and an end offset along it
    def _partial_box(self):
        from . import setbackfillet
        e = self.edit if self.edit is not None and setbackfillet.is_setback_fillet(self.edit) else None
        box = _box("Partial Edge Parameters", collapsed=e is None or (getattr(e, "PartialStart", "None") == "None"
                                                                       and getattr(e, "PartialEnd", "None") == "None"))
        self.partial = {}
        for end in ("Start", "End"):
            row = QtWidgets.QHBoxLayout()
            kind = QtWidgets.QComboBox(box)
            kind.setObjectName("SWFilletPartial%s" % end)
            kind.addItems(list(setbackfillet.PARTIAL_CONDITIONS))
            kind.setToolTip("%s condition" % end)
            kind.setCurrentText(str(getattr(e, "Partial" + end, "None")) if e is not None else "None")
            value = QtWidgets.QDoubleSpinBox(box)
            value.setObjectName("SWFilletPartial%sValue" % end)
            value.setRange(0.0, 1e6)
            value.setDecimals(2)
            value.setValue(float(getattr(e, "Partial%sValue" % end, 0.0)) if e is not None else 0.0)
            row.addWidget(kind, 1)
            row.addWidget(value, 1)
            box.layout().addLayout(row)
            self.partial[end] = (kind, value)
            kind.activated.connect(lambda i: self._partial_changed())
            value.valueChanged.connect(lambda v: self._partial_changed())
        self.partial_flip = QtWidgets.QCheckBox("Flip edge direction", box)
        self.partial_flip.setObjectName("SWFilletPartialFlip")
        self.partial_flip.setChecked(bool(getattr(e, "PartialFlip", False)) if e is not None else False)
        self.partial_flip.toggled.connect(lambda on: self._partial_changed())
        box.layout().addWidget(self.partial_flip)
        self.partial_note = QtWidgets.QLabel("Pick one edge for a partial edge fillet.", box)
        self.partial_note.setWordWrap(True)
        box.layout().addWidget(self.partial_note)
        self._partial_rows()
        return box

    def _partial_rows(self):
        for kind, value in self.partial.values():
            value.setVisible(kind.currentText() != "None")
            value.setSuffix(" %" if kind.currentText() == "Percentage" else " mm")
        on = self.partial_on(False)
        self.partial_flip.setVisible(on)
        self.partial_note.setVisible(on and not self.partial_on())

    def _partial_changed(self):
        self._partial_rows()
        self.update()

    def partial_on(self, one_edge=True):
        """A start or end condition is set (and, with one_edge, the items are a single edge)."""
        parts = getattr(self, "partial", None)
        if not parts or any(not alive(k) for k, _v in parts.values()):
            return False
        if all(k.currentText() == "None" for k, _v in parts.values()):
            return False
        if not one_edge:
            return True
        return len(self.items) == 1 and self.items[0].startswith("Edge") and not self.conic()

    # --- Setback Parameters (setbackfillet.py): vertices where filleted edges meet, and one
    # setback distance per edge at each of them
    def _setback_box(self):
        from . import setbackfillet
        self.active = "items"
        self.list.installEventFilter(_Activate(self, "items", self.list))
        self.setbacks = []      # [vertex name, {edge name: distance or None}] in pick order
        e = self.edit if self.edit is not None and setbackfillet.is_setback_fillet(self.edit) else None
        if e is not None:
            for vname in e.SetbackVertices:
                self.setbacks.append([vname, {}])
            for key, d in zip(e.SetbackEdges, e.SetbackDistances):
                vname, _sep, ename = key.partition(setbackfillet.SEP)
                for entry in self.setbacks:
                    if entry[0] == vname:
                        entry[1][ename] = float(d)
        box = _box("Setback Parameters", collapsed=not self.setbacks)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("D", box))
        self.setback_distance = _spin(box, "SWFilletSetbackDistance", "mm", 0.001, 1e6)
        self.setback_distance.setToolTip("Distance")
        self.setback_distance.setValue(params().GetFloat("FilletSetbackDistance", 2.0 * self.radius.value()))
        self.setback_distance.valueChanged.connect(self._setback_value)
        row.addWidget(self.setback_distance)
        box.layout().addLayout(row)
        self.setback_list = _SetbackList(self, "SWFilletSetbackVertices", self.remove_setback, self.clear_setbacks)
        self.setback_list.setToolTip("Setback Vertices")
        self.setback_list.installEventFilter(_Activate(self, "setback", self.setback_list))
        self.setback_list.currentRowChanged.connect(lambda r: self._fill_distances())
        box.layout().addWidget(self.setback_list)
        self.distance_list = QtWidgets.QListWidget(box)
        self.distance_list.setObjectName("SWFilletSetbackDistances")
        self.distance_list.setToolTip("Setback Distances")
        self.distance_list.setFixedHeight(70)
        self.distance_list.currentRowChanged.connect(self._distance_row)
        box.layout().addWidget(self.distance_list)
        buttons = QtWidgets.QHBoxLayout()
        unassigned = QtWidgets.QPushButton("Set Unassigned", box)
        unassigned.setObjectName("SWFilletSetUnassigned")
        unassigned.clicked.connect(lambda: self._set_distances(False))
        every = QtWidgets.QPushButton("Set All", box)
        every.setObjectName("SWFilletSetAll")
        every.clicked.connect(lambda: self._set_distances(True))
        buttons.addWidget(unassigned)
        buttons.addWidget(every)
        box.layout().addLayout(buttons)
        return box

    def _vertex_name(self, obj, sub):
        """The base's own Vertex<n> for a vertex picked on any feature of the body, else None."""
        if obj is not self.base and obj.TypeId != "PartDesign::Body" and obj not in _features(self.body):
            return None
        try:
            p = obj.Shape.getElement(sub).Point
        except Exception:
            return None
        return next(("Vertex%d" % i for i, v in enumerate(self.base.Shape.Vertexes, 1)
                     if (v.Point - p).Length < 1e-7), None)

    def _edges_at(self, vname):
        """Names (in the base) of the edges that meet at the base's vertex vname."""
        from . import setbackfillet
        shape = self.base.Shape
        try:
            v = shape.getElement(vname)
        except Exception:
            return []
        out = []
        for e in setbackfillet.vertex_edges(shape, v):
            i = next((i for i, g in enumerate(shape.Edges, 1) if g.isSame(e)), None)
            if i is not None:
                out.append("Edge%d" % i)
        return out

    def other_pick(self, obj, sub):
        if getattr(self, "active", "items") != "setback":
            return False
        if not sub or not sub.startswith("Vertex") or self.base is None:
            return True         # the box takes vertices only
        name = self._vertex_name(obj, sub)
        if name is None:
            return True
        for entry in self.setbacks:
            if entry[0] == name:
                self.setbacks.remove(entry)
                return True
        self.setbacks.append([name, dict((e, None) for e in self._edges_at(name))])
        self._setback_row = len(self.setbacks) - 1
        return True

    def _current_setback(self):
        row = self.setback_list.currentRow()
        return self.setbacks[row] if 0 <= row < len(self.setbacks) else None

    def _distance_row(self, row):
        entry = self._current_setback()
        if entry is None:
            return
        names = list(entry[1])
        if 0 <= row < len(names) and entry[1][names[row]] is not None:
            self.setback_distance.blockSignals(True)
            self.setback_distance.setValue(entry[1][names[row]])
            self.setback_distance.blockSignals(False)

    def _setback_value(self, value):
        params().SetFloat("FilletSetbackDistance", value)
        entry = self._current_setback()
        row = self.distance_list.currentRow()
        if entry is not None and 0 <= row < len(entry[1]):
            entry[1][list(entry[1])[row]] = value      # the highlighted edge takes the distance
            self.update()

    def _set_distances(self, every):
        """Set Unassigned: the edges with no distance yet take D; Set All: every edge does."""
        d = self.setback_distance.value()
        for _v, rows in self.setbacks:
            for name in rows:
                if every or rows[name] is None:
                    rows[name] = d
        self.update()

    def remove_setback(self, row):
        if 0 <= row < len(self.setbacks):
            del self.setbacks[row]
            self.update()

    def clear_setbacks(self):
        self.setbacks = []
        self.update()

    def setback_rows(self):
        """(vertex names, Vertex/Edge keys, distances) when every setback is set, else None."""
        from . import setbackfillet
        if not getattr(self, "setbacks", None):
            return None
        verts, keys, dists = [], [], []
        for vname, rows in self.setbacks:
            if not rows or any(d is None for d in rows.values()):
                return None
            verts.append(vname)
            for ename, d in rows.items():
                keys.append(vname + setbackfillet.SEP + ename)
                dists.append(float(d))
        return verts, keys, dists

    def missing(self):
        text = super().missing()
        if text or not getattr(self, "setbacks", None):
            return text
        if self.setback_rows() is None:
            return "Set the setback distances: Set Unassigned or Set All."
        return None

    def _fill_distances(self):
        dl = self.distance_list
        keep = dl.currentRow()
        dl.blockSignals(True)
        dl.clear()
        entry = self._current_setback()
        if entry is not None:
            for k, (ename, d) in enumerate(entry[1].items()):
                dl.addItem("Edge<%d>: %s" % (k + 1, _LengthSpin.text_of(d) if d is not None else ""))
                dl.item(k).setToolTip(ename)
            if 0 <= keep < dl.count():
                dl.setCurrentRow(keep)
        dl.blockSignals(False)

    def overflow(self):
        for r in getattr(self, "overflow_buttons", []):
            if r.isChecked():
                return r.text()
        return "Default"

    def overflow_needed(self):
        """Keep edge or Keep surface, and the fillet runs past an edge of one of its faces."""
        if self.overflow() == "Default" or self.base is None or self.multi_radius():
            return False
        from . import conicfillet
        try:
            import Part
            shape = self.base.Shape
            for e in self._edges_of_items():
                faces = shape.ancestorsOfType(e, Part.Face)
                if len(faces) != 2:
                    continue
                if conicfillet.overflows(shape, e, faces, self.fd1.value(), self.fd2.value(),
                                         None if self.asymmetric() else self.radius.value()):
                    return True
        except Exception as _fw_err:
            _fw_log("filletpm.py:2290", _fw_err)
            return False
        return False

    def rounds_corners(self):
        """Round corners on and two picked edges meet in a mitre."""
        box = getattr(self, "round", None)
        if box is None or not box.isChecked() or self.base is None or self.conic():
            return False
        from . import multiradius, setbackfillet
        try:
            base = self.base.Shape
            r = self.radius.value()
            radii = [self.radii.get(sub, r) for sub in self.items] if self.multi_radius() else []
            pairs = multiradius.edge_radii(base, base, list(self.items), radii, r)
            return bool(setbackfillet.mitre_corners(base, pairs))
        except Exception as _fw_err:
            _fw_log("filletpm.py:2307", _fw_err)
            return False

    def keeps_over(self):
        ""


        keep = getattr(self, "keep", None)
        return keep is not None and keep.isChecked() and self._engulfs()

    def rolls_over(self):
        """Keep features off and a boss or cut inside the fillet's reach of the picked edges."""
        keep = getattr(self, "keep", None)
        return keep is not None and not keep.isChecked() and self._engulfs()

    def _engulfs(self):
        if self.base is None or self.conic():
            return False
        from . import setbackfillet
        try:
            r = self.radius.value()
            edges, radii = [], []
            for sub in self.items:
                found = self._edges_of_items_for(sub)
                edges += found
                radii += [self.radii.get(sub, r) if self.multi_radius() else r] * len(found)
            return bool(setbackfillet.engulfed_faces(self.base.Shape, edges, radii))
        except Exception:
            return False

    def _xpert_boxes(self):
        from . import filletxpert
        return filletxpert.boxes(self)

    def _tab(self, index):
        for w in self.manual:
            box_visible(w, index == 0)
        for w in self.xpert:
            box_visible(w, index == 1)
        try:
            from . import filletxpert
            filletxpert.tab_changed(self, index)
        except Exception as _fw_err:
            _fw_log("filletpm.py:2309", _fw_err)

    def size(self):
        if getattr(self, "symmetric", None) is not None and self.asymmetric():
            return max(self.fd1.value(), self.fd2.value())
        return self.radius.value()

    def set_size(self, value):
        if value > 0:
            self.radius.setValue(value)

    # --- Asymmetric and the fillet profiles (conicfillet.py)
    def _load_profile(self, p):
        from . import conicfillet
        e = self.edit if self.edit is not None and conicfillet.is_conic_fillet(self.edit) else None
        vals = ((self.fd1, e.Distance1.Value if e else p.GetFloat("FilletDistance1", 10.0)),
                (self.fd2, e.Distance2.Value if e else p.GetFloat("FilletDistance2", 5.0)),
                (self.rho, e.Rho if e else p.GetFloat("FilletRho", 0.5)),
                (self.conic_radius, e.ConicRadius.Value if e else p.GetFloat("FilletConicRadius", 10.0)))
        for w, v in vals:
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        if e is not None:
            self.symmetric.setCurrentIndex(0 if e.Symmetric else 1)
            self.profile.setCurrentIndex(max(0, self.profile.findText(e.Profile)))
            self.reverse.blockSignals(True)
            self.reverse.setChecked(bool(e.Reverse))
            self.reverse.blockSignals(False)

    def asymmetric(self):
        return self.symmetric.currentIndex() == 1

    def profile_name(self):
        return self.profile.currentText()

    def conic(self):
        ""
        return self.asymmetric() or self.profile_name() != "Circular"

    def _profile_rows(self):
        asym = self.asymmetric()
        for w in (self.r_icon, self.radius):
            w.setVisible(not asym)
        for w in (self.fd1, self.fd2, self.fd1_label, self.fd2_label, self.reverse):
            w.setVisible(asym)
        prof = self.profile_name()
        for w in (self.rho, self.rho_label):
            w.setVisible(prof == "Conic Rho")
        for w in (self.conic_radius, self.conic_label):
            w.setVisible(prof == "Conic Radius")
        # one radius per item is for the circular symmetric fillet
        self.multi_box.setVisible(not self.conic())

    def _shape_changed(self):
        self._profile_rows()
        self.update()

    def _tangent_toggled(self):
        self._profile_rows()
        self.update()

    def stops_at_tangent(self):
        ""

        if getattr(self, "tangent", None) is None or self.tangent.isChecked() or self.base is None:
            return False
        from . import conicfillet
        try:
            return conicfillet.tangent_continued(self.base.Shape, self._edges_of_items())
        except Exception as _fw_err:
            _fw_log("filletpm.py:2421", _fw_err)
            return False

    def _wanted(self):
        from . import conicfillet, multiradius
        from . import setbackfillet
        if self.conic():
            return conicfillet
        if (self.stops_at_tangent() or self.overflow_needed()) and self._flat_can():
            return conicfillet      # straight edges between flat faces; round ones stay FreeCAD's
        if self.setback_rows() is not None or self.rolls_over() or self.rounds_corners() or self.keeps_over() \
                or self.partial_on():
            return setbackfillet
        if self.multi_radius() or getattr(self, "_split", False):
            return multiradius
        return None

    def try_passes(self, f):
        ""


        if getattr(self, "_split", False) or self._wanted() is not None:
            return False
        if not any(s.startswith("Edge") or s.startswith("Face") for s in self.items):
            return False

        # refuses (an overflowing fillet, a corner of three or more edges: filletrescue.py)
        self._split = True
        return True

    @staticmethod
    def _module_of(f):
        from . import conicfillet, multiradius, setbackfillet
        if conicfillet.is_conic_fillet(f):
            return conicfillet
        if setbackfillet.is_setback_fillet(f):
            return setbackfillet
        if multiradius.is_multi_radius(f):
            return multiradius
        return None

    # --- Multi Radius Fillet
    def multi_radius(self):
        return self.multi_box.isChecked() and not self.conic()

    def _highlighted(self):
        row = getattr(self, "_row", None)
        if row is None or not (0 <= row < len(self.items)):
            row = self.list.currentRow()
        return self.items[row] if 0 <= row < len(self.items) else None

    def _radius_changed(self, value):
        if self.multi_radius():
            sub = self._highlighted()
            if sub is not None:
                self.radii[sub] = value
        self.update()

    def _row_changed(self, row):
        if not self.multi_radius() or not (0 <= row < len(self.items)):
            return
        self._row = row
        r = self.radii.get(self.items[row])
        if r is not None:
            self.radius.blockSignals(True)
            self.radius.setValue(r)
            self.radius.blockSignals(False)
        self._draw()

    def _multi_toggled(self, on):
        if on:
            for sub in self.items:
                self.radii.setdefault(sub, self.radius.value())
        self.update()

    def _add(self, obj, sub):
        before = list(self.items)
        changed = super()._add(obj, sub)
        if changed and self.multi_radius():
            for name in self.items:
                if name not in before:
                    self.radii[name] = self.radius.value()      # a new item takes the R shown
            self._row = None
        return changed

    def _fill(self):
        # the preview refills the Items box after every change: the same rows keep their scroll and their
        # highlighted row. Scrolled to the last row, the box moved one row under the pointer, so a click on
        # the first row of a Multi Radius Fillet took the second (features-433, Triple Clamp TC18)
        try:
            same = [self.list.item(i).text() for i in range(self.list.count())] == list(self.item_names())
            scroll = self.list.verticalScrollBar().value()
            was = self.list.currentRow()
        except Exception:
            same, scroll, was = False, 0, -1
        super()._fill()
        if same:
            self.list.blockSignals(True)
            if 0 <= was < self.list.count():
                self.list.setCurrentRow(was)
            self.list.verticalScrollBar().setValue(scroll)
            self.list.blockSignals(False)
        if self._row is not None and 0 <= self._row < self.list.count():
            self.list.blockSignals(True)
            self.list.setCurrentRow(self._row)
            self.list.blockSignals(False)
        sl = getattr(self, "setback_list", None)
        if sl is None or not alive(sl):
            return
        row = sl.currentRow()
        want = getattr(self, "_setback_row", None)
        self._setback_row = None
        sl.blockSignals(True)
        sl.clear()
        for i in range(len(self.setbacks)):
            sl.addItem("Vertex<%d>" % (i + 1))
            sl.item(i).setToolTip(self.setbacks[i][0])
        if want is not None:
            row = want
        if sl.count():
            sl.setCurrentRow(row if 0 <= row < sl.count() else sl.count() - 1)
        sl.blockSignals(False)
        self._fill_distances()
        self.list.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if self.active == "items" else "white"))
        sl.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if self.active == "setback" else "white"))

    def remove_item(self, row):
        self._row = None
        super().remove_item(row)

    def clear_items(self):
        self._row = None
        super().clear_items()

    def callout_rows(self):
        if self.asymmetric():
            return [("Distance 1", self.fd1.value(), self.UNIT, lambda v: v > 0 and self.fd1.setValue(v)),
                    ("Distance 2", self.fd2.value(), self.UNIT, lambda v: v > 0 and self.fd2.setValue(v))]
        if self.multi_radius():
            sub = self._highlighted()
            r = self.radii.get(sub, self.radius.value()) if sub is not None else self.radius.value()
            return [("Radius", r, self.UNIT, self.set_size)]
        return super().callout_rows()

    def _make(self):
        f = self.feature
        wanted = self._wanted()
        if f is not None and self._module_of(f) is not wanted:
            if self.edit is None:
                self._drop()
                f = None
            else:
                f = self._retype(f)
        if f is None:
            f = wanted.new(self.body) if wanted is not None else self._new_native()
            try:
                f.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("filletpm.py:2519", _fw_err)
            self.feature = f
        return f

    def _retype(self, old):
        """The edited fillet becomes the other kind in its tree place (same label, children
        re-linked), inside this page's Undo step."""
        doc, body = self.doc, self.body
        label, was_tip = old.Label, body.Tip is old
        wanted = self._wanted()
        if wanted is not None:
            new = wanted.setup_new(doc.addObject(wanted.TYPE, "Fillet"))
        else:
            new = doc.addObject(self.TYPE, "Fillet")
        body.insertObject(new, old, True)
        new.Base = (self.base, [s for s in self.items if s])
        for child in [o for o in old.InList if o is not new]:
            if getattr(child, "BaseFeature", None) is old:
                child.BaseFeature = new
        if was_tip:
            body.Tip = new
        body.removeObject(old)
        doc.removeObject(old.Name)
        new.Label = label
        self.edit = self.feature = new
        return new

    def apply(self, f):
        from . import multiradius, conicfillet, simplefeature
        simplefeature.put_value(f, "Radius", self.radius.value())    # a radius per configuration stays per configuration
        if conicfillet.is_conic_fillet(f):
            f.Kind = "Fillet"
            f.TangentPropagation = self.tangent.isChecked()
            f.Symmetric = not self.asymmetric()
            f.Distance1 = self.fd1.value()
            f.Distance2 = self.fd2.value()
            f.Reverse = self.reverse.isChecked()
            f.Profile = self.profile_name()
            f.Overflow = self.overflow()
            f.Rho = self.rho.value()
            f.ConicRadius = self.conic_radius.value()
            return
        from . import setbackfillet
        if setbackfillet.is_setback_fillet(f):
            r = self.radius.value()
            f.ItemRadii = [float(self.radii.get(sub, r)) for sub in self.items] if self.multi_radius() else []
            f.KeepFeatures = self.keep.isChecked()
            f.RoundCorners = self.round.isChecked()
            verts, keys, dists = self.setback_rows() or ([], [], [])
            f.SetbackVertices = verts
            f.SetbackEdges = keys
            f.SetbackDistances = dists
            if "PartialStart" in f.PropertiesList and getattr(self, "partial", None):
                on = self.partial_on()
                for end, (kind, value) in self.partial.items():
                    setattr(f, "Partial" + end, kind.currentText() if on else "None")
                    setattr(f, "Partial%sValue" % end, float(value.value()))
                f.PartialFlip = self.partial_flip.isChecked()
            return
        if multiradius.is_multi_radius(f):
            r = self.radius.value()
            multi = self.multi_radius()
            f.ItemRadii = [float(self.radii.get(sub, r)) if multi else float(r) for sub in self.items]
            if hasattr(f, "InPasses"):
                f.InPasses = not multi

    def take_values(self, values):
        if "Radius" in values:
            self.radius.blockSignals(True)
            self.radius.setValue(values["Radius"])
            self.radius.blockSignals(False)

    def remember(self):
        p = params()
        p.SetFloat("FilletRadius", self.radius.value())
        p.SetFloat("FilletDistance1", self.fd1.value())
        p.SetFloat("FilletDistance2", self.fd2.value())
        p.SetFloat("FilletRho", self.rho.value())
        p.SetFloat("FilletConicRadius", self.conic_radius.value())

    def switch(self, command):
        ""
        picks = [(self.base.Document.Name, self.base.Name, s) for s in self.items if s.startswith("Edge")]
        self.reject()

        def start():
            Gui.Selection.clearSelection()
            for doc, name, sub in picks:
                try:
                    Gui.Selection.addSelection(doc, name, sub)
                except Exception as _fw_err:
                    _fw_log("filletpm.py:2604", _fw_err)
            try:
                Gui.runCommand(command, 0)
            except Exception as _fw_err:
                _fw_log("filletpm.py:2608", _fw_err)
        QtCore.QTimer.singleShot(150, start)


class ChamferPanel(DressUpPanel):
    TYPE = CHAMFER
    TITLE = "Chamfer"
    ICON = "FEATURES_CHAMFER"
    UNDO = "Chamfer"

    FOCUS = "d1"

    def make_boxes(self):
        from . import vertexchamfer
        editing_vertex = self.edit is not None and vertexchamfer.is_vertex_chamfer(self.edit)
        first = [_feature_type_box(self, CHAMFER)] if self.edit is not None and not editing_vertex else []
        # The five type buttons (Angle Distance, Distance Distance, Vertex, Offset Face, Face Face) sit
        # 3 + 2 as the E1 2024 and 2026 videos and the engine video show them (chamferrows-1121; AP3's one
        # row was not from a live read).
        top = _box("Chamfer Type")
        grid = QtWidgets.QGridLayout()
        grid.setSpacing(0)
        self.type_buttons = []
        group = QtWidgets.QButtonGroup(top)
        for i, (tip, family, can) in enumerate(CHAMFER_TYPES):
            b = _icon_button(top, "SWChamferType%d" % i, tip, family)
            group.addButton(b)
            if not can:
                _greyed(b, tip + ": " + NOT_YET)
            else:
                b.clicked.connect(lambda checked=False: self._type_changed())
            grid.addWidget(b, i // 3, i % 3)
            self.type_buttons.append(b)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addLayout(grid)
        row.addStretch(1)
        top.layout().addLayout(row)

        items = _box("Items To Chamfer")
        self.list = _ItemsList(self, "SWChamferItems")
        items.layout().addWidget(self.list)

        self.set1_label = QtWidgets.QLabel("Face Set 1", items)
        self.set1_label.setObjectName("SWChamferFaceSet1Label")
        items.layout().insertWidget(items.layout().indexOf(self.list), self.set1_label)
        self.set2_label = QtWidgets.QLabel("Face Set 2", items)
        self.set2_label.setObjectName("SWChamferFaceSet2Label")
        items.layout().addWidget(self.set2_label)
        self.list2 = _SetTwoList(self, "SWChamferFaceSet2")
        items.layout().addWidget(self.list2)
        self.ff_set = 1
        def watch():
            # installed last, so it sees the click before the page's own box filters (they take it)
            for n, box in ((1, self.list), (2, self.list2)):
                if alive(box):
                    box.viewport().installEventFilter(_FaceSetClick(self, n, box))     # the clicks land there
        watch()
        QtCore.QTimer.singleShot(0, watch)
        for w in (self.set1_label, self.set2_label, self.list2):
            w.setVisible(False)
        self.toolbar_box = QtWidgets.QCheckBox("Show selection toolbar", items)
        self.toolbar_box.setObjectName("SWChamferSelectionToolbar")
        self.face_accelerators = True
        self.toolbar_box.setChecked(params().GetBool("ChamferSelectionToolbar", True))
        self.toolbar_box.toggled.connect(lambda on: self._toolbar_toggled("Chamfer", on))
        items.layout().addWidget(self.toolbar_box)
        tangent = QtWidgets.QCheckBox("Tangent propagation", items)
        tangent.setObjectName("SWChamferTangent")
        tangent.setChecked(_tangent_of(self.edit))
        tangent.toggled.connect(lambda on: self.update())
        self.tangent = tangent
        items.layout().addWidget(tangent)
        self._preview_rows(items, "Chamfer")

        parms = _box("Chamfer Parameters")
        self.flip = QtWidgets.QCheckBox("Flip direction", parms)
        self.flip.setObjectName("SWChamferFlip")
        self.flip.toggled.connect(lambda on: self.update())
        parms.layout().addWidget(self.flip)
        self.symmetric = QtWidgets.QComboBox(parms)
        self.symmetric.setObjectName("SWChamferSymmetric")
        self.symmetric.addItems(["Symmetric", "Asymmetric"])
        self.symmetric.activated.connect(lambda i: self._type_changed())
        parms.layout().addWidget(self.symmetric)
        form = QtWidgets.QFormLayout()
        self.d1 = _spin(parms, "SWChamferDistance", "mm", 0.001, 1e6)
        self.d2 = _spin(parms, "SWChamferDistance2", "mm", 0.001, 1e6)
        self.angle = _spin(parms, "SWChamferAngle", "°", 0.01, 179.99)
        for w in (self.d1, self.d2, self.angle):
            w.valueChanged.connect(lambda v: self.update())
        self.d1_label = QtWidgets.QLabel("D1", parms)
        self.d2_label = QtWidgets.QLabel("D2", parms)
        self.angle_label = QtWidgets.QLabel("A", parms)
        # Vertex: Equal distance, then Distance 1, 2, 3 along the three edges at the corner
        self.equal = QtWidgets.QCheckBox("Equal distance", parms)
        self.equal.setObjectName("SWChamferEqualDistance")
        self.equal.toggled.connect(lambda on: self._type_changed())
        parms.layout().addWidget(self.equal)
        self.d3 = _spin(parms, "SWChamferDistance3", "mm", 0.001, 1e6)
        self.d3.valueChanged.connect(lambda v: self.update())
        self.d3_label = QtWidgets.QLabel("D3", parms)
        form.addRow(self.d1_label, self.d1)
        form.addRow(self.d2_label, self.d2)
        form.addRow(self.d3_label, self.d3)
        form.addRow(self.angle_label, self.angle)
        parms.layout().addLayout(form)
        options = _box("Chamfer Options", collapsed=True)
        options.layout().addWidget(self._through_box(options))
        # off: the bosses and cuts the chamfer runs into are taken out (conicfillet's flat profile)
        c = QtWidgets.QCheckBox("Keep features", options)
        c.setObjectName("SWChamferKeepFeatures")
        c.setChecked(bool(getattr(self.edit, "KeepFeatures", True)) if self.edit is not None else True)
        c.toggled.connect(lambda on: self.update())
        self.keep = c
        options.layout().addWidget(c)

        p = params()
        self.equal.blockSignals(True)
        self.equal.setChecked(p.GetBool("ChamferVertexEqual", True))
        self.equal.blockSignals(False)
        self.d3.blockSignals(True)
        self.d3.setValue(p.GetFloat("ChamferSize3", 10.0))
        self.d3.blockSignals(False)
        from . import offsetchamfer
        if self.edit is not None and offsetchamfer.is_offset_chamfer(self.edit):
            kind = self.edit.Mode
            d1, d2, a = self.edit.Distance1.Value, self.edit.Distance2.Value, 45.0
            self.flip.blockSignals(True)
            self.flip.setChecked(bool(self.edit.FlipDirection))
            self.flip.blockSignals(False)
            sym = bool(self.edit.Symmetric)
        elif editing_vertex:
            kind = "Vertex"
            d1, d2, a = self.edit.Distance1.Value, self.edit.Distance2.Value, 45.0
            for w, v in ((self.equal, self.edit.EqualDistance),):
                w.blockSignals(True)
                w.setChecked(bool(v))
                w.blockSignals(False)
            self.d3.blockSignals(True)
            self.d3.setValue(self.edit.Distance3.Value)
            self.d3.blockSignals(False)
        elif self.edit is not None and getattr(self.edit, "Kind", "") == "Chamfer":
            kind = "Distance and Angle" if self.edit.ChamferAngle.Value else (
                "Equal distance" if self.edit.Symmetric else "Two distances")
            d1, d2 = self.edit.Distance1.Value, self.edit.Distance2.Value
            a = self.edit.ChamferAngle.Value or 45.0
            self.flip.blockSignals(True)
            self.flip.setChecked(bool(self.edit.Reverse))
            self.flip.blockSignals(False)
        elif self.edit is not None:
            kind = self.edit.ChamferType
            d1, d2, a = self.edit.Size.Value, self.edit.Size2.Value, self.edit.Angle.Value
            self.flip.blockSignals(True)
            self.flip.setChecked(bool(getattr(self.edit, "FlipDirection", False)))
            self.flip.blockSignals(False)
        else:
            kind = p.GetString("ChamferType", "Distance and Angle")
            d1, d2, a = p.GetFloat("ChamferSize", 10.0), p.GetFloat("ChamferSize2", 10.0), p.GetFloat("ChamferAngle", 45.0)
            if self.edit is None and p.GetString("ChamferMode", "") in offsetchamfer.MODES:
                kind = p.GetString("ChamferMode", "")
        for w, v in ((self.d1, d1), (self.d2, d2), (self.angle, a)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.type_buttons[{"Distance and Angle": 0, "Vertex": 2, "Offset Face": 3, "Face Face": 4}.get(kind, 1)].setChecked(True)
        if kind in offsetchamfer.MODES:
            if self.edit is None:
                sym = p.GetBool("ChamferOffsetSymmetric", True)
            self.symmetric.setCurrentIndex(0 if sym else 1)
        else:
            self.symmetric.setCurrentIndex(1 if kind == "Two distances" else 0)
        self._rows()
        return first + [top, items, parms, options]

    def vertex_mode(self):
        return len(self.type_buttons) > 2 and self.type_buttons[2].isChecked()

    def type_index(self):
        return next((i for i, b in enumerate(self.type_buttons) if b.isChecked()), 1)

    def mode(self):
        ""
        return CHAMFER_TYPES[self.type_index()][0]

    def _wanted(self):
        """The Python feature module this type needs, else None (FreeCAD's Chamfer)."""
        from . import vertexchamfer, offsetchamfer, conicfillet
        wanted = {2: vertexchamfer, 3: offsetchamfer, 4: offsetchamfer}.get(self.type_index())
        if wanted is None and not self._flat_can():
            return None             # a round edge (a hole's rim): FreeCAD's Chamfer makes it
        if wanted is None and self._engulfs_chamfer():
            return _ChamferFlat
        if wanted is None and getattr(self, "tangent", None) is not None and not self.tangent.isChecked() \
                and self.base is not None:
            try:
                if conicfillet.tangent_continued(self.base.Shape, self._edges_of_items()):
                    return _ChamferFlat
            except Exception as _fw_err:
                _fw_log("filletpm.py:2787", _fw_err)
        return wanted

    def _engulfs_chamfer(self):
        ""

        if getattr(self, "keep", None) is None or self.base is None:
            return False
        from . import setbackfillet
        try:
            edges = self._edges_of_items()
            reach = max(self.d1.value(), self.d2.value())
            return bool(setbackfillet.engulfed_faces(self.base.Shape, edges, [reach] * len(edges)))
        except Exception as _fw_err:
            _fw_log("filletpm.py:2843", _fw_err)
            return False

    @staticmethod
    def _module_of(f):
        from . import vertexchamfer, offsetchamfer, conicfillet
        if vertexchamfer.is_vertex_chamfer(f):
            return vertexchamfer
        if offsetchamfer.is_offset_chamfer(f):
            return offsetchamfer
        if conicfillet.is_conic_fillet(f):
            return _ChamferFlat
        return None

    def kind(self):
        if self.vertex_mode():
            return "Vertex"
        if self.type_buttons[0].isChecked():
            return "Distance and Angle"
        return "Two distances" if self.symmetric.currentIndex() == 1 else "Equal distance"

    def _rows(self):
        kind = self.kind()
        angle = kind == "Distance and Angle"
        vertex = kind == "Vertex"
        three = vertex and not self.equal.isChecked()
        self.symmetric.setVisible(not angle and not vertex)
        self.equal.setVisible(vertex)
        self.flip.setVisible(not vertex)
        self.d1_label.setText("D1" if kind == "Two distances" or three else "D")
        self.d2.setVisible(kind == "Two distances" or three)
        self.d2_label.setVisible(kind == "Two distances" or three)
        self.d3.setVisible(three)
        self.d3_label.setVisible(three)
        self.angle.setVisible(angle)
        self.angle_label.setVisible(angle)

    def _type_changed(self):
        # Vertex takes corners, Face Face faces, the other types edges and faces: the other kind
        # of item goes
        vertex = self.vertex_mode()
        self.items = [s for s in self.items if s.startswith("Vertex") == vertex and s]
        if self.mode() == "Face Face":
            self.items = [s for s in self.items if s.startswith("Face")]
            self.ff_set = 2 if len(self.items) == 1 else 1
        self._rows()
        self.update()
        self._fill()

    def missing(self):
        if self.vertex_mode():
            return None if self.items else "Select vertices to chamfer."
        if self.mode() == "Face Face":
            return None if len(self.items) == 2 else "Select two faces: Face Set 1, then Face Set 2."
        return super().missing()

    def _add(self, obj, sub):
        if not self.vertex_mode():
            last = (sub or "").split(".")[-1]
            if self.mode() == "Face Face":
                if not last.startswith("Face"):
                    return False
                key = to_base(self.base, *refplane.resolve(obj, sub or ""))
                if key in self.items:
                    return super()._add(obj, sub)       # picked again: it goes
                if getattr(self, "ff_set", 2) == 1 and self.items:
                    # Face Set 1 clicked first: the pick takes Face Set 1's place, Face Set 2 stays
                    rest = self.items[1:]
                    self.items = []
                    done = super()._add(obj, sub)
                    self.items = self.items[:1] + rest
                    self.ff_set = 2
                    self.update()
                    return done
                if len(self.items) >= 2:
                    self.items.pop()        # a third face takes the place of Face Set 2
                done = super()._add(obj, sub)
                self.ff_set = 2 if len(self.items) == 1 else getattr(self, "ff_set", 2)
                self._fill()
                return done
            if not last.startswith("Vertex"):
                return super()._add(obj, sub)
            if self.items or self.edit is not None:
                return False
            # a corner picked first (or before any edge): the Vertex chamfer it asks for
            self.type_buttons[2].blockSignals(True)
            self.type_buttons[2].setChecked(True)
            self.type_buttons[2].blockSignals(False)
            self._rows()
        obj, sub = refplane.resolve(obj, sub or "")
        if not sub or not sub.startswith("Vertex") or self.base is None:
            return False
        if obj is not self.base and obj.TypeId != "PartDesign::Body" and obj not in _features(self.body):
            return False
        try:
            p = obj.Shape.getElement(sub).Point
        except Exception:
            return False
        name = next(("Vertex%d" % i for i, v in enumerate(self.base.Shape.Vertexes, 1)
                     if (v.Point - p).Length < 1e-7), None)
        if name is None:
            return False
        if name in self.items:
            self.items.remove(name)
        else:
            self.items.append(name)
        return True

    def _fill(self):
        two = getattr(self, "list2", None)
        try:
            ff = two is not None and self.mode() == "Face Face"
        except Exception:
            ff = False
        if two is not None:
            for w in (self.set1_label, self.set2_label, two):
                w.setVisible(ff)
        if not ff:
            return super()._fill()
        names = self.item_names()
        for box, part, n in ((self.list, names[:1], 1), (two, names[1:2], 2)):
            box.blockSignals(True)
            box.clear()
            for x in part:
                box.addItem(x)
            box.blockSignals(False)
            on = getattr(self, "ff_set", 1) == n
            box.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if on else "white"))

    def item_names(self):
        if self.vertex_mode():
            return ["Vertex<%d>" % (i + 1) for i in range(len(self.items))]
        return super().item_names()

    def _edges_of_items(self):
        if self.vertex_mode():
            return [e for sub in self.items for e in self._edges_of_items_for(sub)]
        return super()._edges_of_items()

    def _edges_of_items_for(self, sub):
        if sub.startswith("Vertex"):
            try:
                v = self.base.Shape.getElement(sub)
                return [e for e in self.base.Shape.Edges if any(x.isSame(v) for x in e.Vertexes)]
            except Exception as _fw_err:
                _fw_log("filletpm.py:2950", _fw_err)
                return []
        return super()._edges_of_items_for(sub)

    # --- the feature: FreeCAD's Chamfer, or a Python one (Vertex, Offset Face, Face Face)
    def _make(self):
        f = self.feature
        wanted = self._wanted()
        if f is not None and self._module_of(f) is not wanted:
            if self.edit is None:
                self._drop()
                f = None
            else:
                f = self._retype(f)
        if f is None:
            f = wanted.new(self.body) if wanted is not None else self._new_native()
            try:
                f.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("filletpm.py:2925", _fw_err)
            self.feature = f
        return f

    def _retype(self, old):
        doc, body = self.doc, self.body
        label, was_tip = old.Label, body.Tip is old
        wanted = self._wanted()
        if wanted is not None:
            new = wanted.setup_new(doc.addObject(wanted.TYPE, "Chamfer"))
        else:
            new = doc.addObject(self.TYPE, "Chamfer")
        body.insertObject(new, old, True)
        new.Base = (self.base, list(self.items))
        for child in [o for o in old.InList if o is not new]:
            if getattr(child, "BaseFeature", None) is old:
                child.BaseFeature = new
        if was_tip:
            body.Tip = new
        body.removeObject(old)
        doc.removeObject(old.Name)
        new.Label = label
        self.edit = self.feature = new
        return new

    def callout_name(self):
        return "Distance"

    def callout_rows(self):
        kind = self.kind()
        if kind == "Vertex":
            if self.equal.isChecked():
                return [("Distance", self.d1.value(), "mm", self.set_size)]
            return [("Distance 1", self.d1.value(), "mm", self.set_size),
                    ("Distance 2", self.d2.value(), "mm", self._set_d2),
                    ("Distance 3", self.d3.value(), "mm", lambda v: v > 0 and self.d3.setValue(v))]
        if kind == "Distance and Angle":
            return [("Distance", self.d1.value(), "mm", self.set_size),
                    ("Angle", self.angle.value(), "deg", self._set_angle)]
        if kind == "Two distances":
            return [("Distance 1", self.d1.value(), "mm", self.set_size),
                    ("Distance 2", self.d2.value(), "mm", self._set_d2)]
        return [("Distance", self.d1.value(), "mm", self.set_size)]

    def _set_angle(self, value):
        if 0 < value < 180:
            self.angle.setValue(value)

    def _set_d2(self, value):
        if value > 0:
            self.d2.setValue(value)

    def size(self):
        return self.d1.value()

    def set_size(self, value):
        if value > 0:
            self.d1.setValue(value)

    def apply(self, f):
        from . import vertexchamfer, offsetchamfer, conicfillet
        if conicfillet.is_conic_fillet(f):
            kind = self.kind()
            f.Kind = "Chamfer"
            f.TangentPropagation = False
            if hasattr(f, "KeepFeatures"):
                f.KeepFeatures = self.keep.isChecked() if getattr(self, "keep", None) is not None else True
            f.Symmetric = kind != "Two distances"
            f.Distance1 = self.d1.value()
            f.Distance2 = self.d2.value()
            f.ChamferAngle = self.angle.value() if kind == "Distance and Angle" else 0.0
            f.Reverse = self.flip.isChecked()
            return
        if offsetchamfer.is_offset_chamfer(f):
            f.Mode = self.mode()
            f.Symmetric = self.symmetric.currentIndex() == 0
            f.Distance1 = self.d1.value()
            f.Distance2 = self.d2.value()
            f.FlipDirection = self.flip.isChecked()
            return
        if vertexchamfer.is_vertex_chamfer(f):
            f.EqualDistance = self.equal.isChecked()
            f.Distance1 = self.d1.value()
            f.Distance2 = self.d2.value()
            f.Distance3 = self.d3.value()
            return
        f.ChamferType = self.kind()
        from . import simplefeature
        simplefeature.put_value(f, "Size", self.d1.value())
        f.Size2 = self.d2.value()
        f.Angle = self.angle.value()
        if hasattr(f, "FlipDirection"):
            f.FlipDirection = self.flip.isChecked()

    def take_values(self, values):
        if "Size" in values:
            self.d1.blockSignals(True)
            self.d1.setValue(values["Size"])
            self.d1.blockSignals(False)

    def remember(self):
        p = params()
        p.SetBool("ChamferVertexEqual", self.equal.isChecked())
        p.SetFloat("ChamferSize3", self.d3.value())
        from . import offsetchamfer
        p.SetString("ChamferMode", self.mode())
        if self.mode() in offsetchamfer.MODES:
            p.SetBool("ChamferOffsetSymmetric", self.symmetric.currentIndex() == 0)
            p.SetFloat("ChamferSize", self.d1.value())
            p.SetFloat("ChamferSize2", self.d2.value())
            return
        if self.kind() == "Vertex":
            p.SetFloat("ChamferSize", self.d1.value())
            return
        p.SetString("ChamferType", self.kind())
        p.SetFloat("ChamferSize", self.d1.value())
        p.SetFloat("ChamferSize2", self.d2.value())
        p.SetFloat("ChamferAngle", self.angle.value())


class ShellPanel(DressUpPanel):
    ""




    TYPE = SHELL
    TITLE = "Shell"
    ICON = "FEATURES_SHELL"
    UNDO = "Shell"
    FACES_ONLY = True
    ASK_ALWAYS = False

    FOCUS = "thickness"

    def __init__(self, *args, **kw):
        self.multi = []         # [[base face name, thickness], ...] in pick order
        self.active = "items"
        feature = kw.get("feature")
        if feature is not None and getattr(feature, "MultiFaces", None):
            self.multi = [[n, float(t)] for n, t in zip(feature.MultiFaces, feature.MultiValues)]
        # a closed hollow shell (no faces removed) opens as itself
        self._closed_ok = feature is not None and bool(getattr(feature, "Base", None)) and not [n for n in feature.Base[1] if n]
        super().__init__(*args, **kw)

    def missing(self):

        # opening the page does not hollow the whole part at once; an edited closed shell rebuilds)
        if not self.items and getattr(self, "_closed_ok", False):
            return None
        return None if self.items else "Select faces to remove, or OK for a closed hollow part."

    def accept(self):
        if not self.items and not getattr(self, "converted", False) and not getattr(self, "_closed_ok", False):
            self._closed_ok = True
            self.update()
            if not self.ok:
                self._closed_ok = False
                return False
        return super().accept()

    def make_boxes(self):
        top = _box("Parameters")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("D1", top))
        self.thickness = _spin(top, "SWShellThickness", "mm", 0.001, 1e6)
        value = self.edit.Value.Value if self.edit is not None else params().GetFloat("ShellThickness", 10.0)
        self.thickness.setValue(value)
        self.thickness.valueChanged.connect(lambda v: self.update())
        row.addWidget(self.thickness)
        top.layout().addLayout(row)
        self.list = _ItemsList(self, "SWShellFaces")
        self.list.installEventFilter(_Activate(self, "items", self.list))
        top.layout().addWidget(self.list)
        self.outward = QtWidgets.QCheckBox("Shell outward", top)
        self.outward.setObjectName("SWShellOutward")
        self.outward.setChecked(self.edit is not None and not self.edit.Reversed)
        self.outward.toggled.connect(lambda on: self.update())
        top.layout().addWidget(self.outward)
        self.show_preview = QtWidgets.QCheckBox("Show preview", top)
        self.show_preview.setObjectName("SWShellShowPreview")
        self.show_preview.setChecked(params().GetBool("ShellPreview", False))
        self.show_preview.toggled.connect(self._preview_toggled)
        top.layout().addWidget(self.show_preview)
        self.preview_buttons = []

        multi = _box("Multi-thickness Settings", collapsed=False)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("D1", multi))
        self.multi_thickness = _spin(multi, "SWShellMultiThickness", "mm", 0.001, 1e6)
        self.multi_thickness.setToolTip("Multi-thickness(es)")
        self.multi_thickness.setValue(self.multi[-1][1] if self.multi else
                                      params().GetFloat("ShellMultiThickness", 2.0 * value))
        self.multi_thickness.valueChanged.connect(self._multi_value)
        row.addWidget(self.multi_thickness)
        multi.layout().addLayout(row)
        self.multi_list = _MultiList(self, "SWShellMultiFaces")
        self.multi_list.setToolTip("Multi-thickness Faces")
        self.multi_list.installEventFilter(_Activate(self, "multi", self.multi_list))
        self.multi_list.currentRowChanged.connect(self._multi_row)
        multi.layout().addWidget(self.multi_list)
        return [top, multi]

    # --- Multi-thickness Faces: picks go there while its box is the active one
    def other_pick(self, obj, sub):
        if self.active != "multi":
            return False
        if not sub or not sub.startswith("Face"):
            return True     # the box takes faces only
        if obj is not self.base and obj.TypeId != "PartDesign::Body" and obj not in _features(self.body):
            return True
        name = to_base(self.base, obj, sub)
        if name is None or name in self.items:
            return True     # a face to remove has no wall
        for entry in self.multi:
            if entry[0] == name:
                self.multi.remove(entry)
                return True
        self.multi.append([name, self.multi_thickness.value()])
        return True

    def _multi_value(self, value):
        row = self.multi_list.currentRow()
        if 0 <= row < len(self.multi):
            self.multi[row][1] = value
            self.update()

    def _multi_row(self, row):
        if 0 <= row < len(self.multi):
            self.multi_thickness.blockSignals(True)
            self.multi_thickness.setValue(self.multi[row][1])
            self.multi_thickness.blockSignals(False)

    def clear_multi(self):
        self.multi = []
        self.update()

    def remove_multi(self, row):
        if 0 <= row < len(self.multi):
            del self.multi[row]
            self.update()

    def _add(self, obj, sub):
        changed = super()._add(obj, sub)
        if changed:
            # a face can't be removed and a multi-thickness wall at once
            self.multi = [m for m in self.multi if m[0] not in self.items]
        return changed

    def _fill(self):
        super()._fill()
        ml = self.multi_list
        ml.blockSignals(True)
        ml.clear()
        for i, (name, t) in enumerate(self.multi):
            ml.addItem("Face<%d>" % (i + 1))
            ml.item(i).setToolTip("%s: %s" % (name, _LengthSpin.text_of(t)))
        if ml.count():
            ml.setCurrentRow(ml.count() - 1)
        ml.blockSignals(False)
        self.list.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if self.active == "items" else "white"))
        ml.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if self.active == "multi" else "white"))

    # --- the feature: FreeCAD's Thickness, or the multi-thickness shell
    def _wanted_multi(self):
        return bool(self.multi) or not self.items or self._native_fails()

    def _native_fails(self):
        ""

        from . import multishell
        try:
            if not self.items or self.base is None or self.outward.isChecked():
                return False
            key = (self.base.Name, tuple(self.items), round(self.thickness.value(), 6), self.base.Shape.hashCode())
            if getattr(self, "_native_key", None) != key:
                solid = self.base.Shape
                faces = [solid.getElement(n) for n in self.items]
                self._native_key = key
                t = self.thickness.value()
                # FreeCAD's Thickness as it is, or with Intersection on when only that gives a valid solid
                self._native_inter = multishell.native_ok(solid, faces, t, intersection=False) is None
                self._native_bad = self._native_inter and multishell.native_ok(solid, faces, t, intersection=True) is None
            return self._native_bad
        except Exception:
            return False

    def _is_multi(self, f):
        from . import multishell
        return multishell.is_multi_shell(f)

    def _make(self):
        from . import multishell
        f = self.feature
        if f is not None and self._is_multi(f) != self._wanted_multi():
            if self.edit is None:
                self._drop()
                f = None
            else:
                f = self._retype(f)
        if f is None:
            if self._wanted_multi():
                f = multishell.new(self.body, self.TITLE)
            else:
                f = self._new_native()
            try:
                f.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("filletpm.py:3213", _fw_err)
            self.feature = f
        return f

    def _retype(self, old):
        """The edited shell becomes the other kind in its tree place (same label, children
        re-linked), inside this page's Undo step."""
        from . import multishell
        doc, body = self.doc, self.body
        label, was_tip = old.Label, body.Tip is old
        if self._wanted_multi():
            new = doc.addObject(multishell.TYPE, "Shell")
            multishell.MultiShellFeature(new)
            if App.GuiUp:
                multishell.MultiShellView(new.ViewObject)
        else:
            new = doc.addObject(self.TYPE, "Shell")
        body.insertObject(new, old, True)
        new.Base = (self.base, list(self.items))
        for child in [o for o in old.InList if o is not new]:
            if getattr(child, "BaseFeature", None) is old:
                child.BaseFeature = new
        if was_tip:
            body.Tip = new
        body.removeObject(old)
        doc.removeObject(old.Name)
        new.Label = label
        self.edit = self.feature = new
        return new

    def _preview_toggled(self, on):
        params().SetBool("ShellPreview", on)
        self._draw()

    def preview_mode(self):
        return "Full preview" if self.show_preview.isChecked() else "No preview"

    def item_names(self):
        return ["Face<%d>" % (i + 1) for i in range(len(self.items))]

    def callout_name(self):
        return "Thickness"

    def callout_rows(self):
        rows = [(self.callout_name(), self.size(), self.UNIT, self.set_size)]
        if self.active == "multi" and self.multi:
            rows.append(("Multi-thickness", self.multi_thickness.value(), self.UNIT,
                         self.multi_thickness.setValue))
        return rows

    def size(self):
        return self.thickness.value()

    def set_size(self, value):
        if value > 0:
            self.thickness.setValue(value)

    def apply(self, f):
        f.Value = self.thickness.value()
        f.Reversed = not self.outward.isChecked()     # FreeCAD: Reversed = inward
        if self._is_multi(f):
            f.MultiFaces = [m[0] for m in self.multi]
            f.MultiValues = [float(m[1]) for m in self.multi]
        else:
            f.Mode = "Skin"
            f.Join = "Arc"
            self._native_fails()
            f.Intersection = bool(getattr(self, "_native_inter", False)) and not self.outward.isChecked()

    def remember(self):
        params().SetFloat("ShellThickness", self.thickness.value())
        if self.multi:
            params().SetFloat("ShellMultiThickness", self.multi_thickness.value())


class _SetbackList(QtWidgets.QListWidget):
    """The Setback Vertices box: Delete takes the vertex out, right-click Clear Selections."""

    def __init__(self, panel, name, remove, clear):
        super().__init__()
        self.panel, self.remove, self.clear_all = panel, remove, clear
        self.setObjectName(name)
        self.setFixedHeight(56)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        try:
            menu = QtWidgets.QMenu(self)
            menu.addAction("Delete", lambda: self.remove(self.currentRow()))
            menu.addAction("Clear Selections", self.clear_all)
            menu.exec_(self.mapToGlobal(pos))
        except Exception as _fw_err:
            _fw_log("filletpm.py:3304", _fw_err)

    def keyPressEvent(self, event):
        try:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.remove(self.currentRow())
                return
        except Exception as _fw_err:
            _fw_log("filletpm.py:3312", _fw_err)
        super().keyPressEvent(event)


class _MultiList(QtWidgets.QListWidget):
    """The Multi-thickness Faces box: Delete takes the face out, right-click Clear Selections."""

    def __init__(self, panel, name):
        super().__init__()
        self.panel = panel
        self.setObjectName(name)
        self.setFixedHeight(70)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        try:
            menu = QtWidgets.QMenu(self)
            menu.addAction("Delete", lambda: self.panel.remove_multi(self.currentRow()))
            menu.addAction("Clear Selections", self.panel.clear_multi)
            menu.exec_(self.mapToGlobal(pos))
        except Exception as _fw_err:
            _fw_log("filletpm.py:3334", _fw_err)

    def keyPressEvent(self, event):
        try:
            if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
                self.panel.remove_multi(self.currentRow())
                return
        except Exception as _fw_err:
            _fw_log("filletpm.py:3342", _fw_err)
        super().keyPressEvent(event)


PROPAGATIONS = ("None", "Along Tangent", "All Faces", "Inner Faces", "Outer Faces")


def _faces_at(shape, edge):
    return [i for i, f in enumerate(shape.Faces, 1) if any(e.isSame(edge) for e in f.Edges)]


def smooth_edges(shape, subs):
    """The picked Edge names whose two faces meet tangentially: there is no corner there to round."""
    out = []
    if shape is None:
        return out
    for sub in subs or ():
        if not sub or not sub.startswith("Edge"):
            continue
        try:
            e = shape.getElement(sub)
        except Exception as _fw_err:
            _fw_log("filletpm.py:3408", _fw_err)
            continue
        faces = _faces_at(shape, e)
        if len(faces) == 2 and _tangent_across(shape, e, faces[0], faces[1]):
            out.append(sub)
    return out


def _tangent_across(shape, edge, i, j):
    try:
        m = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        normals = []
        for k in (i, j):
            f = shape.Faces[k - 1]
            u, v = f.Surface.parameter(m)
            normals.append(f.normalAt(u, v))
        return normals[0].getAngle(normals[1]) < 1e-3
    except Exception as _fw_err:
        _fw_log("filletpm.py:3426", _fw_err)
        return False


def propagate(shape, picked, mode, plane=None):
    ""





    names = list(picked)
    if mode == "None":
        return names
    seeds = [int(n[4:]) for n in names if n.startswith("Face")]
    if mode in ("All Faces", "Inner Faces", "Outer Faces"):
        if plane is None:
            return names
        pf = plane.Faces[0] if plane.Faces else None
        if pf is None or pf.Surface.__class__.__name__ != "Plane":
            return names
        n = pf.normalAt(0, 0)
        p0 = pf.Vertexes[0].Point
        flat = []
        for i, f in enumerate(shape.Faces, 1):
            if f.Surface.__class__.__name__ != "Plane":
                continue
            fn = f.normalAt(0, 0)
            if fn.getAngle(n) < 1e-6 or fn.getAngle(n * -1) < 1e-6:
                if abs((f.Vertexes[0].Point - p0).dot(n)) < 1e-6:
                    flat.append(i)
        for i in flat:
            f = shape.Faces[i - 1]
            outer = f.OuterWire
            for w in f.Wires:
                is_outer = w.isSame(outer)
                if mode == "Inner Faces" and is_outer or mode == "Outer Faces" and not is_outer:
                    continue
                for e in w.Edges:
                    for j in _faces_at(shape, e):
                        g = shape.Faces[j - 1]
                        if j in flat or j in seeds:
                            continue
                        try:
                            u, v = g.Surface.parameter(e.valueAt((e.FirstParameter + e.LastParameter) / 2.0))
                            if abs(g.normalAt(u, v).dot(n)) > 0.999:
                                continue        # parallel to the neutral plane: not drafted
                        except Exception as _fw_err:
                            _fw_log("filletpm.py:3428", _fw_err)
                        seeds.append(j)
    # tangent chains
    todo = list(seeds)
    while todo:
        i = todo.pop()
        f = shape.Faces[i - 1]
        for e in f.Edges:
            for j in _faces_at(shape, e):
                if j != i and j not in seeds and _tangent_across(shape, e, i, j):
                    seeds.append(j)
                    todo.append(j)
    out = list(names)
    for i in seeds:
        name = "Face%d" % i
        if name not in out:
            out.append(name)
    return out


class DraftPanel(DressUpPanel):
    ""


    TYPE = DRAFT
    TITLE = "Draft"
    ICON = "FEATURES_DRAFT"
    UNDO = "Draft"
    FACES_ONLY = True
    ASK_ALWAYS = False      # no "Select a neutral plane." line on opening (look audit Z8): the pink box asks

    FOCUS = "angle"

    def __init__(self, *args, **kw):
        self.plane = None       # (obj, sub)
        self.active = "plane"
        super().__init__(*args, **kw)

    def missing(self):
        if getattr(self, "type_radios", None) and self.parting():
            if self.plane is None:
                return "Select a direction of pull."
            return None if self.items else "Select parting lines."
        if self.plane is None:
            return "Select a neutral plane."
        if getattr(self, "propagation", None) is not None and \
                self.propagation.currentText() in ("All Faces", "Inner Faces", "Outer Faces"):
            return None if self.drafted_faces() else "No faces run from the neutral plane."
        return None if self.items else "Select faces to draft."

    def drafted_faces(self):
        """The faces the draft takes: the picked ones, grown by Face propagation."""
        mode = self.propagation.currentText() if getattr(self, "propagation", None) is not None else "None"
        try:
            return propagate(self.base.Shape, list(self.items), mode, self._plane_shape())
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Draft face propagation: %s\n" % error)
            return list(self.items)

    def _plane_shape(self):
        if self.plane is None:
            return None
        obj, sub = self.plane
        try:
            return obj.Shape.getElement(sub) if sub else obj.Shape
        except Exception as _fw_err:
            _fw_log("filletpm.py:3540", _fw_err)
            return None

    def make_boxes(self):
        if self.edit is not None and getattr(self.edit, "SWPickedFaces", None) is not None and \
                "SWFacePropagation" in self.edit.PropertiesList:
            self.items = list(self.edit.SWPickedFaces)
        np = getattr(self.edit, "NeutralPlane", None) or getattr(self.edit, "PullPlane", None) \
            if self.edit is not None else None
        if np:
            self.plane = (np[0], np[1][0] if np[1] else "")
            self.active = "items"
        # Manual | DraftXpert at the top of the page, outside any group, as Fillet's Manual | FilletXpert
        # (look audit Z8; they sat inside Type of Draft)
        bar = _box("Draft", bare=True)
        tabs = QtWidgets.QTabBar(bar)
        tabs.setObjectName("SWDraftTabs")
        tabs.addTab("Manual")
        tabs.addTab("DraftXpert")
        tabs.setExpanding(False)
        tabs.setDrawBase(False)
        holder = QtWidgets.QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(tabs)
        holder.addStretch(1)
        _xpert_tabs(tabs)
        bar.layout().addLayout(holder)
        self.draft_tabs = tabs
        kind = _box("Type of Draft")
        self.kind_box = kind
        from . import partingdraft
        parting_edit = self.edit is not None and partingdraft.is_parting_draft(self.edit)
        self.type_radios = []
        group = QtWidgets.QButtonGroup(kind)
        for i, text in enumerate(("Neutral Plane", "Parting Line", "Step Draft")):
            r = QtWidgets.QRadioButton(text, kind)
            r.setObjectName("SWDraftType%d" % i)
            r.setChecked(i == 0 if not parting_edit else text == self.edit.Mode)
            group.addButton(r)
            r.toggled.connect(lambda on: on and self._type_changed())
            kind.layout().addWidget(r)
            self.type_radios.append(r)
            if text == "Step Draft":

                self.steps_widget = QtWidgets.QWidget(kind)
                steps_lay = QtWidgets.QVBoxLayout(self.steps_widget)
                steps_lay.setContentsMargins(24, 0, 0, 0)
                steps_group = QtWidgets.QButtonGroup(self.steps_widget)
                self.steps_radios = []
                for j, name in enumerate(partingdraft.STEPS):
                    sr = QtWidgets.QRadioButton(name, self.steps_widget)
                    sr.setObjectName("SWDraftSteps%d" % j)
                    sr.setChecked((str(self.edit.Steps) == name) if parting_edit else j == 0)
                    steps_group.addButton(sr)
                    sr.toggled.connect(lambda on: on and self.update())
                    steps_lay.addWidget(sr)
                    self.steps_radios.append(sr)
                kind.layout().addWidget(self.steps_widget)
        self.reduced = QtWidgets.QCheckBox("Allow reduced angle", kind)
        self.reduced.setObjectName("SWDraftReducedAngle")
        self.reduced.setToolTip("Where the full angle cannot be made, a smaller one is used")
        self.reduced.setChecked(bool(self.edit.ReducedAngle) if parting_edit else False)
        self.reduced.toggled.connect(lambda on: self.update())
        kind.layout().addWidget(self.reduced)
        angle_box = _box("Draft Angle")
        self.angle_box = angle_box
        self.angle = _spin(angle_box, "SWDraftAngle", "°", 0.01, 89.99)
        self.angle.setValue(self.edit.Angle.Value if self.edit is not None else params().GetFloat("DraftAngle", 1.0))
        self.angle.valueChanged.connect(lambda v: self.update())
        angle_box.layout().addWidget(self.angle)
        # parting types: Direction 2 with its own angle, Symmetrical Draft
        self.dir2_widget = QtWidgets.QWidget(angle_box)
        dir2_lay = QtWidgets.QVBoxLayout(self.dir2_widget)
        dir2_lay.setContentsMargins(0, 0, 0, 0)
        self.direction2 = QtWidgets.QCheckBox("Direction 2", self.dir2_widget)
        self.direction2.setObjectName("SWDraftDirection2")
        self.direction2.setToolTip("Drafts the faces on the other side of the parting lines too, the other way")
        self.direction2.setChecked(bool(self.edit.Direction2) if parting_edit else False)
        self.direction2.toggled.connect(lambda on: self.update())
        dir2_lay.addWidget(self.direction2)
        self.angle2 = _spin(self.dir2_widget, "SWDraftAngle2", "°", 0.01, 89.99)
        self.angle2.setValue(self.edit.Angle2.Value if parting_edit else self.angle.value())
        self.angle2.valueChanged.connect(lambda v: self.update())
        dir2_lay.addWidget(self.angle2)
        self.symmetric = QtWidgets.QCheckBox("Symmetrical Draft", self.dir2_widget)
        self.symmetric.setObjectName("SWDraftSymmetric")
        self.symmetric.setToolTip("Direction 2 uses the Direction 1 angle")
        self.symmetric.setChecked(bool(self.edit.Symmetric) if parting_edit else False)
        self.symmetric.toggled.connect(lambda on: self.update())
        dir2_lay.addWidget(self.symmetric)
        angle_box.layout().addWidget(self.dir2_widget)
        neutral = _box("Neutral Plane")
        row = QtWidgets.QHBoxLayout()
        self.reverse = QtWidgets.QToolButton(neutral)
        self.reverse.setObjectName("SWDraftReverse")
        self.reverse.setCheckable(True)
        self.reverse.setText("⇅")
        try:
            from . import pmvalues
            self.reverse.setIcon(pmvalues.reverse_icon())     # the Reverse Direction picture, as the other PMs (no "⇅" text)
            self.reverse.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        except Exception as _fw_err:
            _fw_log("filletpm.py:draft_reverse", _fw_err)
        self.reverse.setToolTip("Reverse Direction")
        self.reverse.setChecked(bool(self.edit.Reversed) if self.edit is not None else False)
        self.reverse.toggled.connect(lambda on: self.update())
        row.addWidget(self.reverse)
        self.plane_list = QtWidgets.QListWidget(neutral)
        self.plane_list.setObjectName("SWDraftNeutralPlane")
        self.plane_list.setFixedHeight(26)
        self.plane_list.installEventFilter(_Activate(self, "plane", self.plane_list))
        row.addWidget(self.plane_list)
        neutral.layout().addLayout(row)
        faces = _box("Faces to Draft")
        self.list = _ItemsList(self, "SWDraftFaces")
        self.list.installEventFilter(_Activate(self, "items", self.list))
        faces.layout().addWidget(self.list)
        faces.layout().addWidget(QtWidgets.QLabel("Face propagation:", faces))
        prop = QtWidgets.QComboBox(faces)
        prop.setObjectName("SWDraftFacePropagation")
        prop.addItems(list(PROPAGATIONS))
        chosen = getattr(self.edit, "SWFacePropagation", "None") if self.edit is not None else "None"
        prop.setCurrentIndex(max(0, prop.findText(chosen)))
        prop.activated.connect(lambda i: self.update())
        self.propagation = prop
        faces.layout().addWidget(prop)
        self.show_preview = QtWidgets.QCheckBox("Show preview", faces)
        self.show_preview.setObjectName("SWDraftShowPreview")
        self.show_preview.setChecked(params().GetBool("DraftPreview", True))
        self.show_preview.toggled.connect(self._preview_toggled)
        faces.layout().addWidget(self.show_preview)
        # Parting Line / Step Draft: Direction of Pull (a plane, Reverse) and Parting Lines (edges,
        # Other Face), Face propagation None / Along Tangent
        pull = _box("Direction of Pull")
        row = QtWidgets.QHBoxLayout()
        self.pull_reverse = QtWidgets.QToolButton(pull)
        self.pull_reverse.setObjectName("SWDraftPullReverse")
        self.pull_reverse.setCheckable(True)
        self.pull_reverse.setText("⇅")
        try:
            from . import pmvalues
            self.pull_reverse.setIcon(pmvalues.reverse_icon())     # the Reverse Direction picture, as the other PMs (no "⇅" text)
            self.pull_reverse.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        except Exception as _fw_err:
            _fw_log("filletpm.py:draft_reverse", _fw_err)
        self.pull_reverse.setToolTip("Reverse Direction")
        self.pull_reverse.setChecked(bool(self.edit.Reversed) if parting_edit else False)
        self.pull_reverse.toggled.connect(lambda on: self.update())
        row.addWidget(self.pull_reverse)
        self.pull_list = QtWidgets.QListWidget(pull)
        self.pull_list.setObjectName("SWDraftDirectionOfPull")
        self.pull_list.setFixedHeight(26)
        self.pull_list.installEventFilter(_Activate(self, "plane", self.pull_list))
        row.addWidget(self.pull_list)
        pull.layout().addLayout(row)
        lines = _box("Parting Lines")
        self.edge_list = _ItemsList(self, "SWDraftPartingLines")
        self.edge_list.installEventFilter(_Activate(self, "items", self.edge_list))
        self.edge_list.currentRowChanged.connect(lambda r: self._draw())
        lines.layout().addWidget(self.edge_list)
        self.other_face = QtWidgets.QPushButton("Other Face", lines)
        self.other_face.setObjectName("SWDraftOtherFace")
        self.other_face.setToolTip("Drafts the face on the other side of the highlighted parting line")
        self.other_face.clicked.connect(self._other_face)
        lines.layout().addWidget(self.other_face)
        lines.layout().addWidget(QtWidgets.QLabel("Face propagation:", lines))
        self.line_propagation = QtWidgets.QComboBox(lines)
        self.line_propagation.setObjectName("SWDraftLinePropagation")
        self.line_propagation.addItems(["None", "Along Tangent"])
        if parting_edit and self.edit.AlongTangent:
            self.line_propagation.setCurrentIndex(1)
        self.line_propagation.activated.connect(lambda i: self.update())
        lines.layout().addWidget(self.line_propagation)
        self.others = list(self.edit.OtherFaces) if parting_edit else []
        self.FACES_ONLY = not parting_edit
        self.neutral_boxes = [neutral, faces]
        self.parting_boxes = [pull, lines]
        self.preview_buttons = []
        out = [kind, angle_box, neutral, faces, pull, lines]
        if self.edit is None:

            from . import draftxpert
            out[1:1] = draftxpert.boxes(self)
            out.insert(0, bar)
            tabs.blockSignals(True)
            tabs.setCurrentIndex(1 if params().GetInt("DraftTab", 0) == 1 else 0)
            tabs.blockSignals(False)
            tabs.currentChanged.connect(lambda i: draftxpert.show(self))
        else:
            tabs.hide()
        return out

    # --- Parting Line / Step Draft (partingdraft.py)
    def draft_type(self):
        for r in getattr(self, "type_radios", []):
            if r.isChecked():
                return r.text()
        return "Neutral Plane"

    def parting(self):
        return self.draft_type() != "Neutral Plane"

    def _boxes_for_type(self):
        self._parting_rows()
        if getattr(self, "dx_bar", None) is not None:
            from . import draftxpert
            draftxpert.show(self)
            return
        on = self.parting()
        for w in self.neutral_boxes:
            box_visible(w, not on)
        for w in self.parting_boxes:
            box_visible(w, on)
        self._parting_rows()

    def _parting_rows(self):
        """The rows only the parting types have: steps, reduced angle, Direction 2."""
        on = self.parting()
        if getattr(self, "steps_widget", None) is not None:
            self.steps_widget.setVisible(self.draft_type() == "Step Draft")
        if getattr(self, "reduced", None) is not None:
            self.reduced.setVisible(on)
        if getattr(self, "dir2_widget", None) is not None:
            self.dir2_widget.setVisible(on)
            d2 = self.direction2.isChecked()
            self.angle2.setEnabled(d2 and not self.symmetric.isChecked())
            self.symmetric.setEnabled(d2)

    def _type_changed(self):
        # faces for Neutral Plane, edges for the parting types: the other kind of item goes
        on = self.parting()
        self.FACES_ONLY = not on
        self.items = [x for x in self.items if x.startswith("Edge" if on else "Face")]
        self._boxes_for_type()
        self.update()

    def _other_face(self):
        row = self.edge_list.currentRow()
        if not (0 <= row < len(self.items)):
            row = len(self.items) - 1
        if row < 0:
            return
        sub = self.items[row]
        if sub in self.others:
            self.others.remove(sub)
        else:
            self.others.append(sub)
        self.update()

    def _wanted(self):
        from . import partingdraft
        return partingdraft if self.parting() else None

    @staticmethod
    def _module_of(f):
        from . import partingdraft
        return partingdraft if partingdraft.is_parting_draft(f) else None

    def _make(self):
        f = self.feature
        wanted = self._wanted()
        if f is not None and self._module_of(f) is not wanted:
            if self.edit is None:
                self._drop()
                f = None
            else:
                f = self._retype(f)
        if f is None:
            f = wanted.new(self.body) if wanted is not None else self._new_native()
            try:
                f.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("filletpm.py:3742", _fw_err)
            self.feature = f
        return f

    def _retype(self, old):
        doc, body = self.doc, self.body
        label, was_tip = old.Label, body.Tip is old
        wanted = self._wanted()
        if wanted is not None:
            new = wanted.setup_new(doc.addObject(wanted.TYPE, "Draft"))
        else:
            new = doc.addObject(self.TYPE, "Draft")
        body.insertObject(new, old, True)
        new.Base = (self.base, list(self.items))
        for child in [o for o in old.InList if o is not new]:
            if getattr(child, "BaseFeature", None) is old:
                child.BaseFeature = new
        if was_tip:
            body.Tip = new
        body.removeObject(old)
        doc.removeObject(old.Name)
        new.Label = label
        self.edit = self.feature = new
        return new

    def preview_mode(self):
        box = getattr(self, "show_preview", None)
        return "No preview" if box is not None and not box.isChecked() else "Full preview"

    def _preview_toggled(self, on):
        params().SetBool("DraftPreview", on)
        self._draw()

    def _draw(self):
        super()._draw()
        self._draw_neutral()
        if getattr(self, "dx_bar", None) is not None:
            from . import draftxpert
            draftxpert.paint(self)

    def _pull_arrow(self, shape, at):
        ""
        try:
            import Part
            face = shape.Faces[0] if getattr(shape, "Faces", None) else None
            if face is None:
                return []
            u0, u1, v0, v1 = face.ParameterRange
            n = face.normalAt((u0 + u1) / 2.0, (v0 + v1) / 2.0)
            box = self.base.Shape.BoundBox if self.base is not None else shape.BoundBox
            size = max(box.DiagonalLength * 0.25, 5.0)
            button = self.pull_reverse if self.parting() else self.reverse
            if button is None or not button.isChecked():
                n = n * -1                  # a face's normal points out of the part: pull goes the other way
            tip = at + n * size
            side = n.cross(App.Vector(1, 0, 0))
            if side.Length < 1e-6:
                side = n.cross(App.Vector(0, 1, 0))
            side.normalize()
            head = size * 0.2
            back = tip - n * head
            return [Part.makeLine(at, tip), Part.makeLine(tip, back + side * head * 0.5),
                    Part.makeLine(tip, back - side * head * 0.5)]
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Draft pull arrow: %s\n" % error)
            return []

    def _draw_neutral(self):
        ""

        edges, texts = [], []
        try:
            shape = self._plane_shape()
            if self.plane is not None and shape is not None:
                if self.plane[1].startswith("Face"):
                    edges = list(shape.Edges)
                    longest = max(shape.OuterWire.Edges, key=lambda e: e.Length)
                    at = longest.valueAt((longest.FirstParameter + longest.LastParameter) / 2.0)
                elif hasattr(self.plane[0], "Placement"):
                    at = self.plane[0].Placement.Base
                    edges = [e for e in getattr(shape, "Edges", [])]
                else:
                    at = shape.BoundBox.Center
                texts.append((at, "Direction of Pull" if self.parting() else "Neutral Plane", NEUTRAL_CYAN))
                edges += self._pull_arrow(shape, at)
            if self.items and not self.parting():
                face = self.base.Shape.getElement(self.items[-1])
                u0, u1, v0, v1 = face.ParameterRange
                texts.append((face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0), "Faces to Draft", FACES_PINK))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Draft marks: %s\n" % error)
        self.overlay.show_marks(edges, NEUTRAL_CYAN, texts)

    def _fill(self):
        super()._fill()
        self.plane_list.clear()
        if self.plane is not None:
            obj, sub = self.plane
            self.plane_list.addItem("%s@%s" % (sub, obj.Label) if sub else obj.Label)
        self.plane_list.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if self.active == "plane" else "white"))   # look audit AP2: light blue as every page; the callout colour stays on the strip
        self.list.setStyleSheet("QListWidget { background: %s; }" % (PICK_BLUE if self.active == "items" else "white"))
        if hasattr(self, "pull_list"):
            self.pull_list.clear()
            for i in range(self.plane_list.count()):
                self.pull_list.addItem(self.plane_list.item(i).text())
            self.pull_list.setStyleSheet(self.plane_list.styleSheet())
            row = self.edge_list.currentRow()
            self.edge_list.blockSignals(True)
            self.edge_list.clear()
            for n in self.item_names():
                self.edge_list.addItem(n)
            if self.edge_list.count():
                self.edge_list.setCurrentRow(row if 0 <= row < self.edge_list.count() else self.edge_list.count() - 1)
            self.edge_list.blockSignals(False)
            self.edge_list.setStyleSheet(self.list.styleSheet())

    def other_pick(self, obj, sub):
        if self.active != "plane":
            return False
        if not (refplane.kind_of(obj, sub) == "plane"):
            return False
        if obj is not self.base and sub:
            name = to_base(self.base, obj, sub)
            if name is None:
                return False
            obj, sub = self.base, name
        self.plane = (obj, sub)
        self.active = "items"
        return True

    def _add(self, obj, sub):
        ""


        try:
            o, s = refplane.resolve(obj, sub or "")
        except Exception:
            o, s = obj, sub or ""
        if self.base is not None and self.active == "items" and getattr(self, "type_radios", None) and \
                self.parting() and s.startswith("Edge") and _is_sketch(o):
            names = _edges_along(self.base.Shape, o, s)
            if names:
                if all(n in self.items for n in names):
                    self.items = [n for n in self.items if n not in names]
                else:
                    self.items += [n for n in names if n not in self.items]
                return True
            return False
        return super()._add(obj, sub)

    def item_names(self):
        if getattr(self, "type_radios", None) and self.parting():
            return ["Edge<%d>" % (i + 1) for i in range(len(self.items))]
        return ["Face<%d>" % (i + 1) for i in range(len(self.items))]

    UNIT = "°"

    def callout_name(self):
        return "Angle"

    def size(self):
        return self.angle.value()

    def set_size(self, value):
        if value > 0:
            self.angle.setValue(value)

    def apply(self, f):
        obj, sub = self.plane
        from . import partingdraft
        if partingdraft.is_parting_draft(f):
            f.PullPlane = (obj, [sub] if sub else [""])
            f.Angle = self.angle.value()
            f.Reversed = self.pull_reverse.isChecked()
            f.Mode = self.draft_type()
            self.others = [x for x in self.others if x in self.items]
            f.OtherFaces = list(self.others)
            f.AlongTangent = self.line_propagation.currentIndex() == 1
            f.Steps = next((r.text() for r in getattr(self, "steps_radios", []) if r.isChecked()), partingdraft.STEPS[0])
            f.ReducedAngle = self.reduced.isChecked()
            f.Direction2 = self.direction2.isChecked()
            f.Angle2 = self.angle2.value()
            f.Symmetric = self.symmetric.isChecked()
            self._parting_rows()
            return
        mode = self.propagation.currentText()
        if "SWFacePropagation" not in f.PropertiesList:
            f.addProperty("App::PropertyString", "SWFacePropagation", "FreeCAD", "Face propagation")
            f.addProperty("App::PropertyStringList", "SWPickedFaces", "FreeCAD", "The faces picked (before propagation)")
        f.SWFacePropagation = mode
        f.SWPickedFaces = list(self.items)
        drafted = self.drafted_faces()
        if drafted != list(self.items):
            f.Base = (self.base, drafted)
        f.NeutralPlane = (obj, [sub] if sub else [""])
        f.Angle = self.angle.value()
        f.Reversed = self.reverse.isChecked()

    def remember(self):
        params().SetFloat("DraftAngle", self.angle.value())


class _OnShow(QtCore.QObject):
    """Calls back once, just after the watched widget is first shown."""

    def __init__(self, widget, callback):
        super().__init__(widget)
        self.callback = callback
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        try:
            if event.type() == QtCore.QEvent.Show and self.callback is not None:
                callback, self.callback = self.callback, None
                QtCore.QTimer.singleShot(0, callback)
        except Exception as _fw_err:
            _fw_log("filletpm.py:3960", _fw_err)
        return False


class _Activate(QtCore.QObject):
    ""

    def __init__(self, panel, key, widget):
        super().__init__(widget)
        self.panel, self.key = panel, key

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.active = self.key
            self.panel._fill()
        return False


PANELS = {FILLET: FilletPanel, CHAMFER: ChamferPanel, SHELL: ShellPanel, DRAFT: DraftPanel}


# --------------------------------------------------------------------------- starting the pages
def _body_of(obj):
    try:
        return obj.getParentGeoFeatureGroup()
    except Exception:
        return None


def open_page(feature, transaction=True):
    ""
    body = _body_of(feature)
    from . import multishell
    from . import vertexchamfer, multiradius, offsetchamfer, conicfillet, partingdraft, setbackfillet
    if multishell.is_multi_shell(feature):
        panel = ShellPanel
    elif vertexchamfer.is_vertex_chamfer(feature) or offsetchamfer.is_offset_chamfer(feature):
        panel = ChamferPanel
    elif conicfillet.is_conic_fillet(feature) and getattr(feature, "Kind", "") == "Chamfer":
        panel = ChamferPanel
    elif multiradius.is_multi_radius(feature) or conicfillet.is_conic_fillet(feature) or \
            setbackfillet.is_setback_fillet(feature):
        panel = FilletPanel
    elif partingdraft.is_parting_draft(feature):
        panel = DraftPanel
    else:
        panel = PANELS.get(feature.TypeId)
    if body is None or panel is None:
        return False
    Gui.Control.showDialog(panel(feature.Document, body, feature=feature, transaction=transaction))
    return True


def start_new(type_id, doc=None, picks=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return False
    if type_id == FILLET and picks is None:

        try:
            from . import surfacefillet, surfacefilletpm
            edges, faces = surfacefillet._preselected()
            if edges and not faces and surfacefilletpm.enabled():
                return surfacefilletpm.open_new(doc, edges)
        except Exception as _fw_err:
            _fw_log("filletpm.py:surface-fillet", _fw_err)
    body = refplane.body_of(doc)
    if body is None:
        from . import solidbody
        body = solidbody.adopt(doc)
    if body is None or (body.Tip is None and getattr(body, "BaseFeature", None) is None):
        return False
    if picks is None:
        picks = []
        for entry in Gui.Selection.getSelectionEx(doc.Name):
            for sub in (entry.SubElementNames or ("",)):
                picks.append(refplane.resolve(entry.Object, sub))
    Gui.Selection.clearSelection()
    Gui.Control.showDialog(PANELS[type_id](doc, body, picks))
    return True


def _native_cancel():
    for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        button = box.button(QtWidgets.QDialogButtonBox.Cancel)
        if button is not None and box.window() is Gui.getMainWindow():
            return button
    return None


def take_over(obj):
    """FreeCAD's own Fillet or Chamfer panel just opened for obj: close it and open this page
    with the same picks (a new feature) or on the feature (an edit)."""
    if current() is not None or obj is None:
        return
    try:
        doc, name = obj.Document, obj.Name
        made = _created.pop(doc.Name + "." + name, None)
        fresh = made is not None and time.time() - made < 0.5
        type_id = obj.TypeId
        picks = []
        values = {}
        if fresh:
            base = obj.Base[0] if obj.Base else None
            if getattr(obj, "UseAllEdges", False) and base is not None:
                picks = [(base, "")]
            elif base is not None:
                picks = [(base, s) for s in obj.Base[1]]
    except Exception:
        return
    from . import quietedit
    if fresh or not quietedit.close(obj):
        cancel = _native_cancel()
        if cancel is None:
            return
        cancel.click()      # FreeCAD's own cancel: a new feature goes, an edit is left unchanged

    def start():
        if Gui.Control.activeDialog():
            return
        if fresh:
            start_new(type_id, doc, picks)
        else:
            feature = doc.getObject(name)
            if feature is not None:
                open_page(feature)
    QtCore.QTimer.singleShot(0, start)


class _AppObserver:
    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in PANELS and current() is None and not obj.Document.Restoring:
                _created[obj.Document.Name + "." + obj.Name] = time.time()
        except Exception as _fw_err:
            _fw_log("filletpm.py:4088", _fw_err)


class _GuiObserver:
    def slotInEdit(self, view_provider):
        try:
            obj = view_provider.Object
        except Exception:
            return
        if obj.TypeId in PANELS and enabled() and "SWBreakPicks" not in obj.PropertiesList:
            # a sheet metal Break-Corner is a Chamfer/Fillet too: smbreakcorner opens its own PM
            if current() is None:
                from . import quietedit
                quietedit.note(obj)
            try:
                made = _created.get(obj.Document.Name + "." + obj.Name)
                if made is None or time.time() - made >= 0.5:
                    # an edit never starts from the last values used: filletchamfer counts a
                    # feature as new for 30 s after it is made, and one edited that soon lost its
                    # own radius or chamfer type, Cancel or not (said now: FreeCAD's panel is
                    # dressed before take_over runs)
                    from . import filletchamfer
                    filletchamfer.not_fresh(obj)
            except Exception:
                pass
            QtCore.QTimer.singleShot(0, lambda: take_over(obj))


def enabled():
    return params().GetBool("SolidWorksPages", True)


COMMANDS = {"PartDesign_Fillet": FILLET, "PartDesign_Chamfer": CHAMFER, "PartDesign_Thickness": SHELL,
            "PartDesign_Draft": DRAFT}
_passing = [False]


def _run(name):
    ""

    page = current()
    if page is not None and Gui.Control.activeDialog():
        try:
            page.reject()
        except Exception as _fw_err:
            _fw_log("filletpm.py:4122", _fw_err)
    if Gui.Control.activeDialog():
        return False
    try:
        made = start_new(COMMANDS[name])
        if made:
            _note(name)
        return made
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s page not opened: %s\n" % (name, error))
        return False


def _note(name):
    """Enter repeats it (Repeat Last Command): its button no longer reaches the view keys' hook."""
    try:
        from . import shell as shell_module
        sh = shell_module.shell()
        if sh is not None:
            sh.note_command(name)
    except Exception as _fw_err:
        _fw_log("filletpm.py:4143", _fw_err)


def run_native(name):
    original = getattr(Gui.runCommand, "freeworks_fillet_original", Gui.runCommand)
    _passing[0] = True
    try:
        original(name, 0)
    finally:
        _passing[0] = False


def _hook_commands():
    if not hasattr(Gui.runCommand, "freeworks_fillet_original"):
        original = Gui.runCommand

        def run_command(name, *args, **kw):
            if name in COMMANDS and not _passing[0] and enabled() and _run(name):
                return None
            return original(name, *args, **kw)
        run_command.freeworks_fillet_original = original
        for attr in dir(original):      # keep the marks of earlier wrappers (Confirm Delete)
            if attr.startswith("swstyle_") or attr.startswith("freeworks_"):
                try:
                    setattr(run_command, attr, getattr(original, attr))
                except Exception as _fw_err:
                    _fw_log("filletpm.py:4169", _fw_err)
        run_command.freeworks_fillet_original = original
        Gui.runCommand = run_command
    for name in COMMANDS:
        try:
            actions = Gui.Command.get(name).getAction()
        except Exception:
            actions = []
        for action in actions:
            if action is None or action.property("freeworks_fillet_page"):
                continue
            try:
                action.triggered.disconnect()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: %s not hooked: %s\n" % (name, error))
                continue
            action.setProperty("freeworks_fillet_page", True)
            action.triggered.connect(lambda checked=False, n=name: Gui.runCommand(n, 0))


def _workbench_changed(*args):
    # a workbench's command buttons (QActions) exist only once it is first opened: hook them then,
    # or the ribbon runs FreeCAD's own command first ("Chamfer1: No edges specified", run19)
    QtCore.QTimer.singleShot(0, _hook_commands)


_wb_hooked = []


def install():
    _hook_commands()
    if not _wb_hooked:
        try:
            Gui.getMainWindow().workbenchActivated.connect(_workbench_changed)
            _wb_hooked.append(True)
        except Exception as _fw_err:
            _fw_log("filletpm.py:4205", _fw_err)
    if _observers:
        return
    a, g = _AppObserver(), _GuiObserver()
    App.addDocumentObserver(a)
    Gui.addDocumentObserver(g)
    _observers.extend([a, g])


def remove():
    while _observers:
        o = _observers.pop()
        try:
            App.removeDocumentObserver(o)
        except Exception as _fw_err:
            _fw_log("filletpm.py:4220", _fw_err)
        try:
            Gui.removeDocumentObserver(o)
        except Exception as _fw_err:
            _fw_log("filletpm.py:4224", _fw_err)
