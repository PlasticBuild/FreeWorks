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
from PySide import QtCore, QtWidgets

try:
    from pivy import coin
except Exception:       # headless
    coin = None

from . import pmboxes, refplane
from . import simplefeature as sf


def _error_css():
    try:
        from .propertymanager import error_css
        return error_css()
    except Exception as _fw_err:
        _fw_log("mirrorpm.py:51", _fw_err)
        return "color: #c00000;"

UP_TO_KINDS = ("ThroughAll", "UpToFace", "UpToLast", "UpToFirst")
GHOST_YELLOW = (0.98, 0.84, 0.25)

TITLE = "Mirror"


class MirrorError(Exception):
    pass


def is_plane(obj, sub):
    return refplane.kind_of(obj, sub) == "plane"


def is_datum_plane(obj):
    return obj.TypeId in ("App::Plane", "PartDesign::Plane")


def features_of(body):
    """The body's solid features, in order."""
    return [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature") and hasattr(o, "AddSubShape")]


def _hole_group(obj):
    """A Hole Wizard feature holding holes on several faces (3D sketch positions, holegroup.py)."""
    try:
        from . import holegroup
        return isinstance(getattr(obj, "Proxy", None), holegroup.HoleGroup)
    except Exception:
        return False


def is_feature(obj, body):
    ""


    return obj in features_of(body) or (_hole_group(obj) and obj in body.Group)


def originals(features):
    """What FreeCAD's Mirrored / pattern copies: a Hole Wizard feature stands for its holes."""
    out = []
    for f in features:
        for o in (list(getattr(f, "Holes", []) or []) if _hole_group(f) else [f]):
            if o not in out:
                out.append(o)
    return out


PATTERN_TYPES = ("PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::MultiTransform",
                 "PartDesign::Scaled")


def is_pattern(obj, body):
    ""

    return obj is not None and obj.TypeId in PATTERN_TYPES and obj in body.Group


def feature_of_face(body, obj, sub):
    """The feature that made this face (contextbar's Edit Feature target), else the last
    feature whose added or removed shape holds it."""
    try:
        from . import contextbar
        owner = contextbar.owner_feature(obj, sub)
        if owner is not None and owner in features_of(body) and owner.TypeId != "PartDesign::Mirrored":
            return owner
    except Exception as _fw_err:
        _fw_log("mirrorpm.py:94", _fw_err)
    return _maker_by_tool(body, obj, sub)


def _maker_by_tool(body, obj, sub):
    import Part
    try:
        face = obj.Shape.getElement(sub)
    except Exception:
        return None
    if face.ShapeType != "Face":
        return None
    u0, u1, v0, v1 = face.ParameterRange
    probe = Part.Vertex(face.valueAt((u0 + u1) / 2.0, (v0 + v1) / 2.0))
    if not face.isInside(probe.Point, 1e-6, True):
        probe = Part.Vertex(face.CenterOfMass)
    feats = features_of(body)
    upto = feats.index(obj) + 1 if obj in feats else len(feats)
    best = None
    for f in feats[:upto]:
        if f.TypeId == "PartDesign::Mirrored":
            continue
        tool = f.AddSubShape
        if tool is None or tool.isNull() or not tool.Faces:
            continue
        # a primitive keeps its added shape at its own origin; a sketch-based feature in the body
        placed = tool.copy()
        placed.transformShape(f.Placement.toMatrix())
        for shape in (tool, placed):
            try:
                if any(tf.distToShape(probe)[0] < 1e-6 and type(tf.Surface) is type(face.Surface) for tf in shape.Faces):
                    best = f
                    break
            except Exception:
                continue
    return best


def own_face(body, obj, sub):
    """The face as (feature that made it, its face there): a plane that stays put when later features change."""
    import Part
    feature = feature_of_face(body, obj, sub)
    if feature is None or feature is obj:
        return obj, sub
    face = obj.Shape.getElement(sub)
    probe = Part.Vertex(face.CenterOfMass)
    n = face.normalAt(0, 0)
    for i, f in enumerate(feature.Shape.Faces):
        try:
            if type(f.Surface) is type(face.Surface) and f.distToShape(probe)[0] < 1e-6 \
                    and abs(abs(f.normalAt(0, 0).dot(n)) - 1.0) < 1e-9:
                return feature, "Face%d" % (i + 1)
        except Exception:
            continue
    return obj, sub


def body_of_obj(obj):
    try:
        import PartDesignGui  # noqa: F401
    except Exception as _fw_err:
        _fw_log("mirrorpm.py:155", _fw_err)
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def free_body(obj, body):
    ""


    try:
        if obj is None or obj is body or not hasattr(obj, "Shape") or obj.Shape.isNull() or not obj.Shape.Faces:
            return False
        if obj.TypeId.startswith("Sketcher::") or obj.TypeId in ("App::Plane", "App::Line", "App::Point",
                                                                  "App::Origin", "PartDesign::Plane"):
            return False
        if body is not None and (obj in body.Group or body_of_obj(obj) is body):
            return False
        if obj.TypeId != "PartDesign::Body" and body_of_obj(obj) is not None:
            return False        # a feature of another body: its body is the pick
        return True
    except Exception:
        return False


def check(plane, features, whole, faces=(), solids=()):
    """What is still missing, else None."""
    if plane is None:
        return "Select a face or plane to mirror about."
    if not features and not whole and not faces and not solids:
        return "Select the features, faces or the body to mirror."
    return None


class _Ghost:
    """Partial preview: the copies drawn see-through over the part as it was."""

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
            self.body = coin.SoSeparator()
            self.root.addChild(self.body)
            self.view.getSceneGraph().addChild(self.root)
        except Exception:
            self.root = None

    def show(self, shapes):
        if self.root is None:
            return
        self.body.removeAllChildren()
        if not shapes:
            return
        mat = coin.SoMaterial()
        mat.diffuseColor = GHOST_YELLOW
        mat.emissiveColor = (0.3, 0.25, 0.05)
        mat.transparency = 0.5
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        self.body.addChild(mat)
        self.body.addChild(hints)
        for shape in shapes:
            for face in shape.Faces:
                try:
                    points, triangles = face.tessellate(0.1)
                except Exception as _fw_err:
                    _fw_log("mirrorpm.py:231", _fw_err)
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
                self.body.addChild(coords)
                self.body.addChild(faceset)

    def shown(self):
        return self.root is not None and self.body.getNumChildren() > 0

    def remove(self):
        if self.root is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:250", _fw_err)
            self.root = None


class _Escape(QtCore.QObject):
    ""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) and event.key() == QtCore.Qt.Key_Escape \
                and not (event.modifiers() & (QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
            if t == QtCore.QEvent.KeyPress and current() is self.panel:
                QtCore.QTimer.singleShot(0, self.panel.reject)
            return True
        return False


_current = None


def current():
    """The open Mirror PropertyManager, or None."""
    return _current


class _PickBox(QtWidgets.QWidget):
    def __init__(self, panel, key, title, name, height=26, note=None):
        super().__init__()
        self.panel, self.key = panel, key
        self.setWindowTitle(title)
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName(name)
        self.list.setFixedHeight(height)
        self.list.installEventFilter(self)
        pmboxes.bind(self.list, lambda row, p=panel, k=key: p.remove_item(k, row), lambda p=panel, k=key: p.clear_items(k))
        lay.addWidget(self.list)
        if note:
            label = QtWidgets.QLabel(note, self)
            label.setWordWrap(True)
            label.setEnabled(False)
            lay.addWidget(label)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress):
            self.panel.active = self.key
            self.panel._show()
        return False

    def fill(self, names, active):
        self.list.clear()
        for n in names:
            self.list.addItem(n)
        pmboxes.mark(self.list, active, need=(self.key == "plane" and not names))


class MirrorPanel:
    ""

    def __init__(self, doc, body, picks=()):
        global _current
        _current = self
        self.doc, self.body = doc, body
        try:
            # Mirror Face/Plane, the second plane and Faces to Mirror take faces: a click by a face's
            # edge stays on the face
            from . import facehover
            facehover.faces_only(self, lambda me: current() is me and me.active in ("plane", "plane2", "faces"))
        except Exception:
            pass
        self.plane = None           # (obj, sub)
        self.ref_seeds = None       # planes / axes / points mirrored too (refpattern), loaded on edit
        self.plane2 = None          # Secondary Mirror Face/Plane
        self.features = []
        self.faces = []             # [(obj, sub)] Faces to Mirror
        self.whole = False
        self.solids = []            # [(obj, sub)] Bodies to Mirror: one solid of a multibody part each
        self.free = []              # Bodies to Mirror outside the active body (surface bodies ...)
        self.free_made = []         # their Part::Mirroring copies
        self.knit_made = []         # Surface-Knit of a surface body and its copy (Knit surfaces)
        self.active = "plane"
        self.mirror = None
        self.before = None
        self.opened = False
        self.ok = False
        self.ghost = _Ghost()
        self.boxes = {
            "plane": _PickBox(self, "plane", "Mirror Face/Plane", "SWMirrorPlane"),
            "plane2": _PickBox(self, "plane2", "Secondary Mirror Face/Plane", "SWMirrorPlane2"),
            "features": _PickBox(self, "features", "Features to Mirror", "SWMirrorFeatures", 56),
            "faces": _PickBox(self, "faces", "Faces to Mirror", "SWMirrorFaces", 44),
            "bodies": _PickBox(self, "bodies", "Bodies to Mirror", "SWMirrorBodies", 26),
        }

        # and Knit surfaces (a surface body and its copy become one surface)
        bodies_box = self.boxes["bodies"]
        self.merge = QtWidgets.QCheckBox("Merge solids", bodies_box)
        self.merge.setObjectName("SWMirrorMergeSolids")
        self.merge.setChecked(True)
        self.merge.setToolTip("On: the mirrored copy and the original are one body. Off: the copy is a body of its own")
        self.merge.toggled.connect(lambda on: self.update())
        bodies_box.layout().addWidget(self.merge)
        self.knit = QtWidgets.QCheckBox("Knit surfaces", bodies_box)
        self.knit.setObjectName("SWMirrorKnitSurfaces")
        self.knit.setChecked(False)
        self.knit.setToolTip("A surface body and its mirrored copy are knit into one surface")
        self.knit.toggled.connect(lambda on: self.update())
        bodies_box.layout().addWidget(self.knit)
        self.boxes["faces"].list.setToolTip("Click here, then the faces of a boss or a pocket: they are closed off and mirrored")
        self.boxes["plane2"].list.setToolTip("Click here, then a second face or plane: the copies are mirrored about it too")
        first = self.boxes["plane"]
        first.setProperty("swstyle_pm_title", TITLE)
        first.setProperty("swstyle_pm_icon", "FEATURES_MIRROR")

        self.message = QtWidgets.QLabel("", first)
        self.message.setObjectName("SWMirrorMessage")
        self.message.setWordWrap(True)
        first.layout().insertWidget(0, self.message)

        self.seed_only = QtWidgets.QCheckBox("Mirror seed only", self.boxes["plane2"])
        self.seed_only.setObjectName("SWMirrorSeedOnly")
        self.seed_only.setToolTip("Mirror only the original features about the secondary plane, not the first copy")
        self.seed_only.setVisible(False)
        self.seed_only.toggled.connect(lambda on: self.update())
        seed_row = QtWidgets.QHBoxLayout()
        seed_row.setContentsMargins(30, 0, 0, 0)
        seed_row.addWidget(self.seed_only)
        self.boxes["plane2"].layout().addLayout(seed_row)
        options = QtWidgets.QWidget()
        options.setWindowTitle("Options")
        lay = QtWidgets.QVBoxLayout(options)
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left() + 30, m.top(), m.right(), m.bottom())    # in line with the boxes
        self.geometry = QtWidgets.QCheckBox("Geometry Pattern", options)
        self.geometry.setObjectName("SWMirrorGeometryPattern")
        self.geometry.setChecked(False)
        self.geometry.setToolTip("Copy the features' geometry as it is. Off: Up To / Through All features are made again on the other side.")
        self.geometry.toggled.connect(lambda on: self.update())
        lay.addWidget(self.geometry)
        self.propagate = QtWidgets.QCheckBox("Propagate visual properties", options)
        self.propagate.setObjectName("SWMirrorPropagate")
        self.propagate.setChecked(True)
        self.propagate.setToolTip("The copies take the originals' color")
        self.propagate.toggled.connect(lambda on: self.update())
        lay.addWidget(self.propagate)
        self.full = QtWidgets.QRadioButton("Full preview", options)
        self.full.setObjectName("SWMirrorFullPreview")
        self.partial = QtWidgets.QRadioButton("Partial preview", options)
        self.partial.setObjectName("SWMirrorPartialPreview")
        self.partial.setChecked(True)
        self.full.setToolTip("Show the result")
        self.partial.setToolTip("Show the copies see-through over the part as it is")
        self.partial.toggled.connect(lambda on: self._preview())
        lay.addWidget(self.full)
        lay.addWidget(self.partial)
        self.form = [self.boxes["plane"], self.boxes["plane2"], self.boxes["features"], self.boxes["faces"],
                     self.boxes["bodies"], options]
        self.scope_page = self._scope_page()
        if self.scope_page is not None:
            self.form.append(self.scope_page)
        for obj, sub in picks:
            self._add(obj, sub)
        if self.plane is None:
            self.active = "plane"
        self.update()
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        self._views = []
        self._esc = _Escape(self)
        try:
            # stock FreeCAD 1.1: findChildren(QOpenGLWidget) finds nothing from Python
            for w in [v for v in Gui.getMainWindow().findChildren(QtWidgets.QWidget) if v.inherits("QOpenGLWidget")]:
                w.installEventFilter(self._esc)
                self._views.append(w)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:423", _fw_err)

    # --- picks
    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        try:
            self.message.objectName()
        except RuntimeError:
            # the page was closed without OK or Cancel: let go of the selection
            QtCore.QTimer.singleShot(0, lambda: Gui.Selection.removeObserver(self))
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        obj, sub = refplane.resolve(obj, sub)
        from . import safe_later as _sl; _sl.later(0, lambda: self._picked(obj, sub), self, "message")

    def _picked(self, obj, sub):
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:439", _fw_err)
        try:
            self.message.objectName()
        except RuntimeError:
            return              # the page closed before the pick came through
        self._add(obj, sub)
        self.update()

    def _part_shape(self):
        """The part before the mirror (the solids a Bodies to Mirror pick is found on)."""
        shape_of = self.before if self.mirror is not None and self.before is not None else self.body.Tip
        return shape_of.Shape if shape_of is not None else self.body.Shape

    def _solid_of(self, obj, sub):
        """The index of the solid of the part the pick is on, or None."""
        from .loftsweep import body_holds
        try:
            element = obj.Shape.getElement(sub)
            solids = self._part_shape().Solids
        except Exception:
            return None
        return next((i for i, s in enumerate(solids) if body_holds(s, element)), None)

    def _add_solid(self, obj, sub):
        ""

        if obj is self.mirror or body_of_obj(obj) is not self.body:
            return False
        i = self._solid_of(obj, sub)
        if i is None:
            return False
        if len(self._part_shape().Solids) < 2:
            self.whole = not self.whole
            self.solids = []
            return True
        same = [p for p in self.solids if self._solid_of(*p) == i]
        if same:
            self.solids.remove(same[0])
        else:
            self.solids.append((obj, sub))
            self.whole = False
        return True

    def _add(self, obj, sub):
        obj, sub = refplane.resolve(obj, sub or "")
        if self.active in ("plane", "plane2") and sub and is_plane(obj, sub) and body_of_obj(obj) is not self.body:
            dr = getattr(refplane, "datum_ref", None)    # a face of another moved body: where it is
            if dr is not None:
                obj, sub = dr(obj, sub, self.body)
        if self.active == "bodies" and sub and self.plane is not None and not is_datum_plane(obj) \
                and self._add_solid(obj, sub):
            return
        if free_body(obj, self.body) and not (self.active in ("plane", "plane2") and sub and is_plane(obj, sub)):
            if obj in self.free:
                self.free.remove(obj)
            else:
                self.free.append(obj)
            self.active = "plane" if self.plane is None else "bodies"
            return
        if obj.TypeId == "PartDesign::Body":
            if obj is self.body:
                self.whole = not self.whole
                if self.whole:
                    self.features = []
                self.active = "plane" if self.plane is None else "bodies"
            return
        from . import refpattern
        if self.active == "features" and self.plane is not None and refpattern.is_datum(obj) and \
                self.plane != (obj, "") and self.plane2 != (obj, "") and \
                not (self.mirror is not None and obj in (getattr(self.mirror, refpattern.COPIES, None) or [])):

            seeds = self._ref_seeds()
            if obj in seeds:
                seeds.remove(obj)
            else:
                seeds.append(obj)
            return
        if is_datum_plane(obj):
            if self.active == "plane2" and self.plane is not None:
                self.plane2 = None if self.plane2 == (obj, "") else (obj, "")
                return
            self.plane = None if self.plane == (obj, "") else (obj, "")
            self.active = "plane" if self.plane is None else "features"
            return
        if self.active == "plane2" and sub and is_plane(obj, sub) and self.plane is not None:
            face = own_face(self.body, obj, sub)
            self.plane2 = None if self.plane2 == face else face
            return
        if self.active == "faces" and sub.startswith("Face"):
            key = (obj, sub)
            if key in self.faces:
                self.faces.remove(key)
            else:
                self.faces.append(key)
                self.whole = False
            return
        if self.active == "plane" and sub and is_plane(obj, sub):
            self.plane = own_face(self.body, obj, sub)
            self.active = "features"
            return
        if self.plane is not None and sub and is_plane(obj, sub) and self.plane == own_face(self.body, obj, sub):
            self.plane = None
            self.active = "plane"
            return
        feature = None
        if not sub and (is_feature(obj, self.body) or is_pattern(obj, self.body)):
            feature = obj
        elif sub.startswith("Face"):
            feature = feature_of_face(self.body, obj, sub)
        if feature is None or feature.TypeId == "PartDesign::Mirrored":
            return
        if feature in self.features:
            self.features.remove(feature)
        else:
            self.features.append(feature)
            self.whole = False
        self.active = "features"

    def remove_item(self, key, row):
        ""
        if key == "plane":
            self.plane = None
            self.active = "plane"
        elif key == "plane2":
            self.plane2 = None
        elif key == "features" and 0 <= row < len(self.features):
            self.features.pop(row)
        elif key == "features" and 0 <= row - len(self.features) < len(self._ref_seeds()):
            self._ref_seeds().pop(row - len(self.features))
        elif key == "faces" and 0 <= row < len(self.faces):
            self.faces.pop(row)
        elif key == "bodies":
            if self.whole and row == 0:
                self.whole = False
            else:
                k = row - (1 if self.whole else 0)
                if 0 <= k < len(self.solids):
                    self.solids.pop(k)
                elif 0 <= k - len(self.solids) < len(self.free):
                    self.free.pop(k - len(self.solids))
        self.update()

    def clear_items(self, key):
        """Clear Selections in a box."""
        if key == "plane":
            self.plane = None
            self.active = "plane"
        elif key == "plane2":
            self.plane2 = None
        elif key == "features":
            self.features = []
            self.ref_seeds = []
        elif key == "faces":
            self.faces = []
        elif key == "bodies":
            self.whole = False
            self.solids = []
            self.free = []
        self.update()

    # --- the mirror
    def needs_own(self):
        ""

        if self.faces or self.solids or self.plane2 is not None:
            return True
        if any(is_pattern(f, self.body) for f in self.features):
            return True
        from . import patterns
        if any(patterns.odd_profile(f) for f in self.features):
            return True             # nor a Selected Contours / From Offset seed (it copies nothing)
        if not self.geometry.isChecked():
            return any(str(getattr(f, "Type", "")) in UP_TO_KINDS for f in self.features)
        return False

    def wanted_type(self):
        from . import patterns
        return patterns.MIRROR.type if self.needs_own() else "PartDesign::Mirrored"


    def _scope_page(self):
        try:
            solids = list(self.body.Tip.Shape.Solids) if self.body.Tip is not None else []
        except Exception:
            solids = []
        if len(solids) < 2:
            return None
        page = QtWidgets.QWidget()
        page.setWindowTitle("Feature Scope")
        page.setObjectName("SWMirrorFeatureScope")
        lay = QtWidgets.QVBoxLayout(page)
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left() + 30, m.top(), m.right(), m.bottom())
        self.scope_all = QtWidgets.QRadioButton("All bodies", page)
        self.scope_all.setObjectName("SWMirrorScopeAll")
        self.scope_some = QtWidgets.QRadioButton("Selected bodies", page)
        self.scope_some.setObjectName("SWMirrorScopeSelected")
        self.scope_auto = QtWidgets.QCheckBox("Auto-select", page)
        self.scope_auto.setObjectName("SWMirrorScopeAuto")
        self.scope_auto.setChecked(True)
        self.scope_list = QtWidgets.QListWidget(page)
        self.scope_list.setObjectName("SWMirrorScopeBodies")
        self.scope_list.setFixedHeight(80)
        self.scope_list.setToolTip("The bodies the mirrored features change: tick them")
        for w in (self.scope_all, self.scope_some, self.scope_auto, self.scope_list):
            lay.addWidget(w)
        self.scope_all.setChecked(True)
        self._scope_fill(solids, [])
        self._scope_loaded = False
        self.scope_all.toggled.connect(lambda on: self.update())
        self.scope_auto.toggled.connect(lambda on: self.update())
        self.scope_list.itemChanged.connect(lambda item: self.update())
        return page

    def _scope_fill(self, solids, picked):
        self.scope_solids = list(solids)
        self.scope_list.blockSignals(True)
        self.scope_list.clear()
        for i, solid in enumerate(solids):
            item = QtWidgets.QListWidgetItem("Body %d (%.0f mm\u00b3)" % (i + 1, solid.Volume))
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if any(solid.isSame(p) for p in picked) else QtCore.Qt.Unchecked)
            self.scope_list.addItem(item)
        self.scope_list.blockSignals(False)

    def _scope_shown(self):
        if self.scope_page is None:
            return
        self.scope_auto.setVisible(self.scope_some.isChecked())
        self.scope_list.setVisible(self.scope_some.isChecked() and not self.scope_auto.isChecked())

    def _apply_scope(self, m):
        if self.scope_page is None or m is None or m.TypeId != "PartDesign::Mirrored" and not hasattr(m, "Features"):
            return
        try:
            from . import multibody
            if getattr(self, "edited", None) is m and not self._scope_loaded:
                self._scope_loaded = True
                everything, auto, picked = multibody.scope_of(m)
                for w in (self.scope_all, self.scope_some, self.scope_auto):
                    w.blockSignals(True)
                (self.scope_all if everything else self.scope_some).setChecked(True)
                self.scope_auto.setChecked(auto)
                for w in (self.scope_all, self.scope_some, self.scope_auto):
                    w.blockSignals(False)
                self._scope_fill(multibody._base_solids(m), picked)
            everything = self.scope_all.isChecked()
            if everything and multibody.helper_of(m) is None:
                return
            picked = [self.scope_solids[i] for i in range(self.scope_list.count())
                      if self.scope_list.item(i).checkState() == QtCore.Qt.Checked and i < len(self.scope_solids)]
            multibody.set_scope(m, everything, self.scope_auto.isChecked(), picked)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:scope", _fw_err)

    def _drop_scope(self):
        """The Feature Scope step goes with the mirror it belongs to."""
        try:
            from . import multibody
            helper = multibody.helper_of(self.mirror) if self.mirror is not None else None
            if helper is not None:
                if self.body.Tip is helper:
                    self.body.Tip = self.mirror
                self.body.removeObject(helper)
                self.doc.removeObject(helper.Name)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:drop scope", _fw_err)

    def _make(self):
        from . import patterns
        wanted = self.wanted_type()
        if self.mirror is not None and self.mirror.TypeId != wanted:
            self._drop_scope()
            if getattr(self, "edited", None) is self.mirror:
                self.mirror = self.edited = patterns.replace_feature(self.body, self.mirror, wanted, patterns.MIRROR, "Mirror")
            else:
                self._drop()
        if self.mirror is None:
            if not self.opened:
                self.doc.openTransaction(TITLE)
                self.opened = True
            self.before = self.body.Tip
            self.mirror = self.body.newObject(wanted, "Mirror")
            if wanted == patterns.MIRROR.type:
                sf.Feature(self.mirror, patterns.MIRROR)
                if self.mirror.Label == "Mirror":
                    try:
                        from . import naming
                        self.mirror.Label = naming.next_label(self.doc, "Mirror")
                    except Exception as _fw_err:
                        _fw_log("mirrorpm.py:635", _fw_err)
                if self.mirror.ViewObject is not None:
                    sf.View(self.mirror.ViewObject)
            if self.body.Tip is not self.mirror:
                self.body.Tip = self.mirror
            try:
                self.mirror.ViewObject.Visibility = True
                if self.before is not None:
                    self.before.ViewObject.Visibility = False
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:645", _fw_err)
        return self.mirror

    def copies(self):
        """The shapes the mirror adds or takes away, in place (the ghost, the colour)."""
        from . import patterns
        out = []
        if self.plane is None:
            return out
        try:
            point, normal = patterns.mirror_plane(*self.plane)
            planes2 = [patterns.mirror_plane(*self.plane2)] if self.plane2 is not None else []
            tools = []
            for f in self.features:
                shape = patterns._tool_shape(f) if hasattr(f, "AddSubShape") else None
                if shape is not None:
                    tools.append(shape)
            if self.faces:
                tools.append(patterns.faces_solid([o.Shape.getElement(s) for o, s in self.faces]))
            if self.whole and self.before is not None:
                tools.append(self.before.Shape)
            if self.solids:
                part = self._part_shape().Solids
                for i in sorted({self._solid_of(o, s) for o, s in self.solids} - {None}):
                    tools.append(part[i])
            for shape in tools:
                first = shape.mirror(point, normal)
                out.append(first)
                for p2, n2 in planes2:
                    out.append(shape.mirror(p2, n2))
                    if not self.seed_only.isChecked():
                        out.append(first.mirror(p2, n2))
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:678", _fw_err)
        return out

    def _drop(self):
        if self.mirror is not None:
            self._drop_scope()
            name = self.mirror.Name
            self.body.removeObject(self.mirror)
            self.doc.removeObject(name)
            self.mirror = None
            if self.before is not None and self.before in self.body.Group:
                self.body.Tip = self.before
                try:
                    self.before.ViewObject.Visibility = True
                except Exception as _fw_err:
                    _fw_log("mirrorpm.py:692", _fw_err)

    def _whole_pd(self):
        """The active body mirrored by the PartDesign Mirror (fused into it): Merge solids on."""
        return self.whole and self.merge.isChecked()

    def _free_sources(self):
        return list(self.free) + ([self.body] if self.whole and not self.merge.isChecked() else [])

    def _knits(self):
        """Knit surfaces: one Surface-Knit per surface body and its copy."""
        from . import surfacepms
        want = []
        if self.knit.isChecked():
            for m in self.free_made:
                try:
                    if m.Source is not None and not m.Source.Shape.Solids and m.Source.Shape.Faces:
                        want.append(m)
                except Exception as _fw_err:
                    _fw_log("mirrorpm.py:711", _fw_err)
        for k in self.knit_made[len(want):]:
            try:
                self.doc.removeObject(k.Name)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:716", _fw_err)
        self.knit_made = self.knit_made[:len(want)]
        for i, m in enumerate(want):
            if i < len(self.knit_made):
                k = self.knit_made[i]
            else:
                k = surfacepms.make(self.doc, "SurfaceKnit")
                self.knit_made.append(k)
            k.Surfaces = [(m.Source, ""), (m, "")]
        if self.knit_made:
            self.doc.recompute()
        ok = True
        for k in self.knit_made:
            if "Invalid" in k.State or k.Shape.isNull():
                ok = False
            try:
                for o in k.Surfaces:
                    o[0].ViewObject.Visibility = False
                if self.propagate.isChecked():
                    k.ViewObject.ShapeAppearance = k.Surfaces[0][0].ViewObject.ShapeAppearance
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:737", _fw_err)
        return ok

    def _free_mirrors(self):
        """Part::Mirroring copies of the free Bodies to Mirror about the plane; True when all are
        valid."""
        from . import patterns
        try:
            from . import naming
        except Exception:
            naming = None
        sources = self._free_sources()
        for m in self.free_made[len(sources):]:
            try:
                self.doc.removeObject(m.Name)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:753", _fw_err)
        self.free_made = self.free_made[:len(sources)]
        if not self.opened and sources:
            self.doc.openTransaction(TITLE)
            self.opened = True
        point, normal = patterns.mirror_plane(*self.plane)
        ok = True
        for k, src in enumerate(sources):
            if k < len(self.free_made):
                m = self.free_made[k]
            else:
                m = self.doc.addObject("Part::Mirroring", "Mirror")
                if naming is not None:
                    try:
                        m.Label = naming.next_label(self.doc, TITLE)
                    except Exception as _fw_err:
                        _fw_log("mirrorpm.py:769", _fw_err)
                self.free_made.append(m)
            m.Source = src
            m.Base = point
            m.Normal = normal
        if self.free_made:
            self.doc.recompute()
        for m in self.free_made:
            if "Invalid" in m.State or m.Shape.isNull():
                ok = False
            try:
                if self.propagate.isChecked():
                    m.ViewObject.ShapeAppearance = m.Source.ViewObject.ShapeAppearance
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:783", _fw_err)
        return self._knits() and ok

    def _drop_free(self):
        for k in self.knit_made:
            try:
                self.doc.removeObject(k.Name)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:791", _fw_err)
        self.knit_made = []
        for m in self.free_made:
            try:
                self.doc.removeObject(m.Name)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:797", _fw_err)
        self.free_made = []

    def _ref_seeds(self):
        if self.ref_seeds is None:
            from . import refpattern
            m = getattr(self, "edited", None) or self.mirror
            self.ref_seeds = list(getattr(m, refpattern.SEEDS, None) or []) if m is not None else []
        return self.ref_seeds

    def update(self):
        missing = check(self.plane, list(self.features) + list(self.free), self.whole, self.faces, self.solids)
        if missing:
            self._drop_free()
            self._drop()
            self.doc.recompute()
            self.message.setText("")
            try:
                Gui.getMainWindow().statusBar().showMessage(missing, 0)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:817", _fw_err)
            self.message.setStyleSheet("")
            self.ok = False
        elif not (self.features or self._whole_pd() or self.faces or self.solids):
            # only bodies outside the active body: no PartDesign mirror, one copy of each
            self._drop()
            try:
                good = self._free_mirrors()
                text = "" if good else "The mirror could not be made."
            except Exception as error:
                good, text = False, str(error)
            self.message.setText(text)
            self.message.setStyleSheet("" if good else "color: #c00000;")
            self.ok = good
        else:
            if self._free_sources():
                self._free_mirrors()
            else:
                self._drop_free()
            m = self._make()
            try:
                obj, sub = self.plane
                if m.TypeId == "PartDesign::Mirrored":
                    if self._whole_pd():
                        m.Originals = []
                        m.TransformMode = "Whole shape"
                    else:
                        m.TransformMode = "Features"
                        m.Originals = originals(self.features)
                    m.MirrorPlane = (obj, [sub])
                else:
                    m.Plane = [(obj, [sub])]
                    m.Plane2 = [(self.plane2[0], [self.plane2[1]])] if self.plane2 is not None else []
                    if hasattr(m, "SeedOnly"):
                        m.SeedOnly = self.seed_only.isChecked() and self.plane2 is not None
                    m.Features = list(self.features)
                    m.Faces = [(o, [s]) for o, s in self.faces]
                    m.Whole = self._whole_pd()
                    if "Bodies" in m.PropertiesList:
                        m.Bodies = [(o, [s]) for o, s in self.solids]
                    if "MergeSolids" in m.PropertiesList:
                        m.MergeSolids = self.merge.isChecked()
                    m.GeometryPattern = self.geometry.isChecked()
                    m.Propagate = self.propagate.isChecked()
                from . import refpattern
                if self._ref_seeds() or refpattern.SEEDS in m.PropertiesList:
                    refpattern.set_seeds(m, self._ref_seeds())
                self.doc.recompute()
                if refpattern.SEEDS in m.PropertiesList:
                    refpattern.sync(m)
                bad = "Invalid" in m.State or not m.isValid()
                text = m.getStatusString() if bad else ""
            except Exception as error:
                bad, text = True, str(error)
            if bad:
                self.message.setText(text or "The mirror could not be made.")
                self.message.setStyleSheet(_error_css())
                self.ok = False
            else:
                self.message.setText("")
                self.ok = True
                self._colour(m)
                self._apply_scope(m)
        self._preview()
        self._show()

    def _preview(self):
        """Partial preview: the part as it was with the copies as a ghost; Full: the result."""
        m = self.mirror
        partial = self.partial.isChecked()
        try:
            if m is None or not self.ok:
                self.ghost.show([])
                return
            if partial:
                self.ghost.show(self.copies())
                m.ViewObject.Visibility = False
                if self.before is not None:
                    self.before.ViewObject.Visibility = True
            else:
                self.ghost.show([])
                m.ViewObject.Visibility = True
                if self.before is not None:
                    self.before.ViewObject.Visibility = False
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:901", _fw_err)

    def _colour(self, m):
        """Propagate visual properties: the copies take the originals' colour."""
        try:
            vobj = m.ViewObject
            if vobj is None:
                return
            base_app = vobj.ShapeAppearance[0]
            sources = list(self.features) + [o for o, _ in self.faces]
            if not self.propagate.isChecked() or not sources:
                vobj.ShapeAppearance = [base_app]
                return
            colour = None
            for src in sources:
                try:
                    app = src.ViewObject.ShapeAppearance[0]
                except Exception:
                    continue
                if tuple(app.DiffuseColor) != tuple(base_app.DiffuseColor):
                    colour = app
                    break
            if colour is None:
                vobj.ShapeAppearance = [base_app]
                return
            boxes = []
            for shape in self.copies():
                box = shape.BoundBox
                box.enlarge(1e-3)
                boxes.append(box)
            apps = []
            for face in m.Shape.Faces:
                c = face.CenterOfMass
                apps.append(colour if any(b.isInside(c) for b in boxes) else base_app)
            vobj.ShapeAppearance = apps
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:937", _fw_err)

    def _solid_names(self):
        """The picked bodies as the Solid Bodies folder names them."""
        try:
            from . import multibody
            names = [n.replace("\u200b", "") for n, _s in multibody.solids(self.body)]
        except Exception:
            names = []
        out = []
        for o, s in self.solids:
            i = self._solid_of(o, s)
            out.append(names[i] if i is not None and i < len(names) else "%s@%s" % (s, o.Label))
        return out

    def _show(self):
        self.message.setVisible(bool(self.message.text()))
        self._scope_shown()
        def name(pick):
            if pick is None:
                return []
            obj, sub = pick
            return ["%s@%s" % (sub, obj.Label) if sub else obj.Label]
        self.boxes["plane"].fill(name(self.plane), self.active == "plane")
        self.boxes["plane2"].fill(name(self.plane2), self.active == "plane2")
        # shown only with a secondary plane (a greyed box would be a dead control)
        self.seed_only.setVisible(self.plane2 is not None)
        self.boxes["features"].fill([f.Label for f in self.features] + [f.Label for f in self._ref_seeds()],
                                    self.active == "features")
        self.boxes["faces"].fill([n for pick in self.faces for n in name(pick)], self.active == "faces")
        self.boxes["bodies"].fill(([self.body.Label] if self.whole else []) + self._solid_names() +
                                  [o.Label for o in self.free], self.active == "bodies")
        has_bodies = bool(self.whole or self.solids or self.free)
        self.merge.setVisible(has_bodies)
        self.knit.setVisible(has_bodies)
        self.knit.setEnabled(any(not o.Shape.Solids for o in self.free if hasattr(o, "Shape")))
        if has_bodies:
            self._open_bodies()

        # check, features-416); one holding a pick opens, so an edited mirror shows what it uses
        if self.plane2 is not None:
            self._open_bodies(key="plane2")
        if self.faces:
            self._open_bodies(key="faces")

    def _open_bodies(self, tries=6, key="bodies"):
        ""

        try:
            from . import pmlayout
            box = self.boxes[key]
            if box.list.isVisible():
                return
            group = box
            while group is not None and not group.inherits("QSint::ActionGroup"):
                group = group.parentWidget()
            if group is not None and not pmlayout._group_open(group):
                pmlayout._show_hide(group)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:998", _fw_err)
            return
        if tries > 0:
            QtCore.QTimer.singleShot(250, lambda: _alive_panel(self) and self._open_bodies(tries - 1, key))

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        global _current
        _current = None
        self.ghost.remove()
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("mirrorpm.py:1004", _fw_err)
        self._views = []
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:1009", _fw_err)
        Gui.Control.closeDialog()

    def accept(self):
        if not self.ok:
            return False
        try:
            for m in self.free_made:
                m.ViewObject.Visibility = not any(m in [o for o, _s in k.Surfaces] for k in self.knit_made)
            for k in self.knit_made:
                k.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:1021", _fw_err)
        if self.mirror is None:
            self.doc.commitTransaction()
            self._close()
            return True
        try:
            self.mirror.ViewObject.Visibility = True
            if self.before is not None:
                self.before.ViewObject.Visibility = False
            from . import multibody
            helper = multibody.helper_of(self.mirror)
            if helper is not None and self.body.Tip is helper:      # Feature Scope: its step shows the part
                self.mirror.ViewObject.Visibility = False
                helper.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:1031", _fw_err)
        self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        from . import patternpm
        names = patternpm._names(self.mirror, getattr(self, "edited", None))
        if self.opened:
            self.doc.abortTransaction()
        for name in names:          # made by the Mirror spec command: Cancel leaves nothing
            sf.drop_made(self.doc, name)
        self.free_made = [m for m in self.free_made if _alive(m) and self.doc.getObject(m.Name) is not None]
        self._drop_free()
        self.doc.recompute()
        try:
            self.body.Tip.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:1045", _fw_err)
        self._close()
        return True


def _alive_panel(panel):
    try:
        return panel.boxes["bodies"].list.objectName() != ""
    except Exception:
        return False


def _alive(obj):
    try:
        obj.Name
        return True
    except Exception:
        return False


class MirrorCommand:
    def GetResources(self):
        return {"Pixmap": "PartDesign_Mirrored", "MenuText": TITLE,
                "ToolTip": "Copies features or the body across a plane or flat face"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        body = refplane.body_of(doc)
        if body is None:

            # (structure system members included) with Bodies to Mirror
            # (structure system members included) with Bodies to Mirror; a part of surface bodies only too
            if any(o.TypeId != "PartDesign::Body" and free_body(o, None) for o in doc.Objects):
                picks = preselected(doc)
                QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(BodiesMirrorPanel(doc, picks)))
                return
            Gui.runCommand("PartDesign_Mirrored", 0)
            return
        picks = preselected(doc)
        QtCore.QTimer.singleShot(0, lambda: Gui.Control.showDialog(MirrorPanel(doc, body, picks)))


def plane_of(obj, sub):
    """(base, normal) of a flat face or a plane object, or None."""
    try:
        shape = obj.getSubObject(sub) if sub else None
    except Exception:
        shape = None
    if shape is None or shape.isNull():
        faces = getattr(getattr(obj, "Shape", None), "Faces", [])
        shape = faces[0] if len(faces) == 1 else None
        if shape is None and obj.TypeId in ("App::Plane", "PartDesign::Plane"):
            pl = obj.getGlobalPlacement() if hasattr(obj, "getGlobalPlacement") else obj.Placement
            return pl.Base, pl.Rotation.multVec(App.Vector(0, 0, 1))
    if shape is None or not hasattr(shape, "Surface") or shape.Surface.TypeId != "Part::GeomPlane":
        return None
    return shape.CenterOfMass, shape.normalAt(0, 0)


def mirror_bodies(doc, plane, bodies):
    """A Part Mirror per body about plane (base, normal); a structure member's copy keeps a link to its
    source (WeldMirrorSource) so the cut list counts it with the member."""
    base, normal = plane
    made = []
    for b in bodies:
        m = doc.addObject("Part::Mirroring", "Mirror")
        m.Source = b
        m.Base = base
        m.Normal = normal
        m.Label = "Mirror-%s" % b.Label
        m.addProperty("App::PropertyLink", "WeldMirrorSource", "FreeCAD", "The body this mirrors")
        m.WeldMirrorSource = b
        m.setEditorMode("WeldMirrorSource", 2)
        made.append(m)
    doc.recompute()
    try:
        from . import wecutlist
        wecutlist.update(doc)
    except Exception as _fw_err:
        _fw_log("mirrorpm.py:1126", _fw_err)
    return made


class BodiesMirrorPanel:
    ""


    def __init__(self, doc, picks=()):
        self.doc = doc
        self.plane = None          # (obj, sub)
        self.bodies = []
        groups = []
        for title, name in (("Mirror Face/Plane", "SWMirrorBodiesPlane"), ("Bodies to Mirror", "SWMirrorBodiesList")):
            g = QtWidgets.QWidget()
            g.setWindowTitle(title)
            lay = QtWidgets.QVBoxLayout(g)
            lst = QtWidgets.QListWidget(g)
            lst.setObjectName(name)
            lst.setMaximumHeight(28 if "Plane" in name else 90)
            lay.addWidget(lst)
            groups.append(g)
        groups[0].setProperty("swstyle_pm_title", TITLE)
        groups[0].setProperty("swstyle_pm_icon", "FEATURES_MIRROR")
        self.plane_list = groups[0].findChild(QtWidgets.QListWidget)
        self.body_list = groups[1].findChild(QtWidgets.QListWidget)
        self.form = groups
        for obj, sub in [(p[0], p[1]) if isinstance(p, (tuple, list)) else (p, "") for p in picks]:
            self._take(obj, sub)
        Gui.Selection.addObserver(self)
        for ms in (300, 900, 1500, 2100):   # Bodies to Mirror starts folded on a feature page; here it is the input
            QtCore.QTimer.singleShot(ms, self._unfold)

    def _unfold(self):
        try:
            from . import pmlayout
            w = self.body_list
            while w is not None and not w.inherits("QSint::ActionGroup"):
                w = w.parentWidget()
            if w is not None and not pmlayout._group_open(w):
                pmlayout._show_hide(w)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:1168", _fw_err)

    def _take(self, obj, sub):
        if obj is None:
            return
        if self.plane is None and plane_of(obj, sub) is not None:
            self.plane = (obj, sub)
            self.plane_list.clear()
            self.plane_list.addItem("%s%s" % (obj.Label, ("@" + sub) if sub else ""))
            return
        if obj not in self.bodies and (getattr(getattr(obj, "Shape", None), "Solids", None) or free_body(obj, None)):
            self.bodies.append(obj)
            self.body_list.addItem(obj.Label)

    def addSelection(self, doc, name, sub, _pos):
        if doc != self.doc.Name:
            return
        self._take(self.doc.getObject(name), sub)

    def _done(self):
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("mirrorpm.py:1191", _fw_err)

    def accept(self):
        if self.plane is None or not self.bodies:
            App.Console.PrintWarning("Mirror: pick a face or plane and the bodies to mirror\n")
            return False
        self._done()
        self.doc.openTransaction(TITLE)
        try:
            mirror_bodies(self.doc, plane_of(*self.plane), self.bodies)
        except BaseException:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass
            raise
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self._done()
        Gui.Control.closeDialog()
        return True


def preselected(doc):
    ""


    picks = []
    try:
        entries = [e for e in Gui.Selection.getCompleteSelection() if getattr(e, "Object", None) is not None
                   and e.Object.Document is doc]
    except Exception:
        entries = []
    if not entries:
        entries = Gui.Selection.getSelectionEx(doc.Name)
    for entry in entries:
        for sub in (entry.SubElementNames or ("",)):
            p = refplane.resolve(entry.Object, sub)
            if p not in picks:
                picks.append(p)
    return picks


COMMAND = "SWStyle_Mirror"


def register():
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, MirrorCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
