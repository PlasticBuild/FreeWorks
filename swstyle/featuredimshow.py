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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import events, paths

PARAM = "DoubleClickShowsDimensions"
NODE = "FWShownFeatureDims"
SKETCH = "Sketcher::SketchObject"
DATUMS = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle")
# a feature's own dimensions: (property, kind, label prefix)
OWN = (("Length", "Distance", ""), ("Length2", "Distance", ""), ("Angle", "Angle", ""),
       ("Angle2", "Angle", ""), ("Radius", "Radius", "R"), ("Size", "Distance", ""),
       ("Size2", "Distance", ""), ("Value", "Distance", ""), ("Offset", "Distance", ""),
       ("Height", "Distance", ""), ("Pitch", "Distance", ""))
_HIDDEN_LENGTH = ("ThroughAll", "UpToFirst", "UpToFace", "UpToShape", "UpToLast")


def enabled():
    return paths.params().GetBool(PARAM, True)


def _color(key, default):
    try:
        u = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned(key, 0)
    except Exception:
        u = 0
    if not u:
        return default
    return (((u >> 24) & 255) / 255.0, ((u >> 16) & 255) / 255.0, ((u >> 8) & 255) / 255.0)


def driving_color():
    return _color("ConstrainedDimColor", (0.0, 0.0, 0.0))


def driven_color():
    return _color("NonDrivingConstrDimColor", (0.5, 0.5, 0.5))


# ------------------------------------------------------------------ what a feature's dimensions are
class Dim:
    def __init__(self, obj, text, point, driving, index=None, prop=None, kind="Distance"):
        self.obj, self.text, self.point, self.driving = obj, text, point, driving
        self.index, self.prop, self.kind = index, prop, kind

    def __repr__(self):
        return "Dim(%s %s %s)" % (self.obj.Label, self.prop if self.prop else self.index, self.text)


def profile_sketches(feature):
    out = []
    for prop in ("Profile", "Sections", "Spine"):
        value = getattr(feature, prop, None)
        if value is None:
            continue
        links = value if isinstance(value, list) else [value]
        for link in links:
            obj = link[0] if isinstance(link, tuple) else link
            if getattr(obj, "TypeId", "") == SKETCH and obj not in out:
                out.append(obj)
    return out


def sketch_dims(sk):
    from . import featuredims
    doc = sk.Document
    pl = sk.getGlobalPlacement()
    out = []
    for i, c in enumerate(sk.Constraints):
        if c.Type not in DATUMS or c.First < 0 and c.Type not in ("DistanceX", "DistanceY"):
            continue
        try:
            if c.Type in ("Distance", "DistanceX", "DistanceY") and c.Second >= 0 and c.Second != c.First:
                a = featuredims._geo_point(sk, c.First, c.FirstPos)
                b = featuredims._geo_point(sk, c.Second, c.SecondPos)
                p = (a + b) * 0.5 if a is not None and b is not None else a or b
            elif c.Type in ("Distance", "DistanceX", "DistanceY") and c.FirstPos and c.Second >= 0:
                p = featuredims._geo_point(sk, c.First, c.FirstPos)
            else:
                p = featuredims._geo_point(sk, c.First, 0)
        except Exception:
            p = None
        if p is None:
            continue
        p = featuredims._off(sk, p)
        out.append(Dim(sk, featuredims._styled(doc, sk, i, c), pl.multVec(p), bool(getattr(c, "Driving", True)),
                       index=i, kind=c.Type))
    return out


def _own_point(feature, prop, k):
    """Where a feature's own dimension stands: out along a depth, at a fillet's first edge."""
    try:
        if prop in ("Radius", "Size", "Size2") and getattr(feature, "Base", None):
            base, subs = feature.Base
            edge = base.Shape.getElement(subs[0])
            return edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2.0)
        sks = profile_sketches(feature)
        if sks:
            sk = sks[0]
            centre = sk.Shape.BoundBox.Center
            n = sk.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
            if feature.TypeId in ("PartDesign::Pocket",) or getattr(feature, "Reversed", False):
                n = n * -1
            if prop in ("Length", "Length2"):
                depth = getattr(feature, prop).Value
                if prop == "Length2":
                    n, depth = n * -1, depth
                if getattr(feature, "Midplane", False):
                    depth /= 2.0
                return centre + n * (depth / 2.0)
            bb = sk.Shape.BoundBox
            return App.Vector(bb.XMax, bb.YMax, bb.ZMax) + n * 2.0 * (k + 1)
        bb = feature.Shape.BoundBox
        return App.Vector(bb.XMax, bb.YMax, bb.ZMax)
    except Exception:
        return None


def own_dims(feature):
    from . import featuredims
    out = []
    if feature.TypeId == SKETCH or not feature.isDerivedFrom("PartDesign::Feature"):
        return out
    k = 0
    for prop, kind, prefix in OWN:
        if prop not in feature.PropertiesList:
            continue
        try:
            value = getattr(feature, prop)
        except Exception:
            continue
        if not hasattr(value, "Value") or not hasattr(value, "UserString"):
            continue
        if prop == "Length" and (getattr(feature, "Type", "") in _HIDDEN_LENGTH or getattr(feature, "SWUpToNext", False)):
            continue
        if prop == "Length2" and getattr(feature, "Type", "") != "TwoLengths":
            continue
        if prop == "Angle2" and getattr(feature, "Type", "") != "TwoAngles":
            continue
        if prop == "Size2" and getattr(feature, "ChamferType", "") == "Equal distance":
            continue
        if prop == "Offset" and abs(value.Value) < 1e-9:
            continue
        if feature.getEditorMode(prop) and "Hidden" in feature.getEditorMode(prop):
            continue
        p = _own_point(feature, prop, k)
        if p is None:
            continue
        number = value.Value
        text = featuredims._styled_value(feature.Document, number, kind, value.UserString, prefix)
        driving = not feature.getExpression(prop) if hasattr(feature, "getExpression") else True
        out.append(Dim(feature, text, p, driving, prop=prop, kind=kind))
        k += 1
    return out


def dims_of(feature):
    if feature is None:
        return []
    if feature.TypeId == SKETCH:
        return sketch_dims(feature)
    out = []
    for sk in profile_sketches(feature):
        out += sketch_dims(sk)
    return out + own_dims(feature)


def all_dims(doc):
    out = []
    for o in doc.Objects:
        if o.isDerivedFrom("PartDesign::Feature") and o.TypeId != "PartDesign::Body":
            out += dims_of(o)
    return out


# ------------------------------------------------------------------ which feature made a face
def _point_on(face):
    try:
        pts, tris = face.tessellate(0.5)
        if tris:
            a, b, c = (pts[i] for i in tris[0])
            return (a + b + c) * (1.0 / 3.0)
    except Exception as _fw_err:
        _fw_log("featuredimshow.py:215", _fw_err)
    return face.CenterOfMass


def _on(shape, p, tol=1e-4):
    """p lies on one of the shape's faces (not merely inside the solid)."""
    try:
        import Part
        if shape is None or shape.isNull() or not shape.Faces:
            return False
        return Part.Compound(shape.Faces).distToShape(Part.Vertex(p))[0] < tol
    except Exception:
        return False


def feature_of(obj, sub):
    ""
    if obj is None:
        return None
    body = obj if obj.TypeId == "PartDesign::Body" else None
    if body is None:
        try:
            body = obj.getParentGeoFeatureGroup()
        except Exception:
            body = None
    if body is None or body.TypeId != "PartDesign::Body":
        return obj if obj.isDerivedFrom("PartDesign::Feature") else None
    try:
        face = obj.Shape.getElement(sub) if sub else None
    except Exception:
        face = None
    if face is None:
        return obj if obj is not body else body.Tip
    p = _point_on(face)
    features = [f for f in body.Group if f.isDerivedFrom("PartDesign::Feature") and f.TypeId != "PartDesign::Body"]
    tip = body.Tip
    if tip in features:
        features = features[:features.index(tip) + 1]
    for f in features:
        base = getattr(f, "BaseFeature", None)
        if _on(f.Shape, p) and not (base is not None and _on(base.Shape, p)):
            return f
    return obj if obj is not body else tip


# ------------------------------------------------------------------ drawing
class _Shown:
    def __init__(self):
        self.feature = None
        self.dims = []
        self.root = None
        self.view = None

    def show(self, feature):
        self.hide()
        dims = dims_of(feature)
        if not dims:
            return []
        try:
            from pivy import coin
            view = Gui.getDocument(feature.Document.Name).ActiveView
            graph = view.getSceneGraph()
        except Exception:
            return []
        root = coin.SoAnnotation()
        root.setName(NODE)
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        root.addChild(pick)
        font = coin.SoFont()
        font.size = 14
        root.addChild(font)
        for d in dims:
            sep = coin.SoSeparator()
            col = coin.SoBaseColor()
            col.rgb.setValue(*(driving_color() if d.driving else driven_color()))
            at = coin.SoTranslation()
            at.translation.setValue(d.point.x, d.point.y, d.point.z)
            text = coin.SoText2()
            lines = shown_lines(d)
            text.string.setValues(0, len(lines), lines)
            text.justification = coin.SoText2.CENTER
            for n in (col, at, text):
                sep.addChild(n)
            root.addChild(sep)
        graph.addChild(root)
        self.feature, self.dims, self.root, self.view = feature.Name, dims, root, view
        return dims

    def hide(self):
        if self.root is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception as _fw_err:
                _fw_log("featuredimshow.py:309", _fw_err)
        self.feature, self.dims, self.root, self.view = None, [], None, None

    def again(self):
        """After a rebuild the dimensions move with the model."""
        doc = App.ActiveDocument
        name = self.feature
        if name and doc is not None and doc.getObject(name) is not None:
            self.show(doc.getObject(name))


SHOWN = _Shown()


def show(feature):
    return SHOWN.show(feature)


def hide():
    SHOWN.hide()


# ------------------------------------------------------------------ editing
class _Adapter:
    """A feature's own dimension dressed as a one-relation sketch for the Modify box."""

    class _C:
        def __init__(self, name, value, kind, driving):
            self.Name, self.Value, self.Type, self.Driving = name, value, kind, driving

    def __init__(self, feature, prop, kind):
        self.feature, self.prop = feature, prop
        value = getattr(feature, prop).Value

        # sketch.Label, which this stand-in lacked: Enter then failed and the box stayed open)
        self.Label = feature.Label
        short = prop
        try:
            from . import equations
            short = equations.sw_name(feature, prop).rsplit("@", 1)[0] or prop
        except Exception as _fw_err:
            _fw_log("featuredimshow.py:dim name", _fw_err)
        self.Name = feature.Name
        self.Constraints = [self._C(short,      # "D1@Boss-Extrude1" is refused as a name here
                                    math.radians(value) if kind == "Angle" else value,
                                    "Angle" if kind == "Angle" else "Distance", True)]
        self.Document = feature.Document
        self.PropertiesList = []
        self.Geometry = []      # the Modify box's no-shape check (rv30) looks at the sketch's lines: a feature has none

    def setDatum(self, _index, quantity):
        q = App.Units.Quantity(quantity) if not isinstance(quantity, App.Units.Quantity) else quantity
        setattr(self.feature, self.prop, q.Value)
        self.Constraints[0].Value = math.radians(q.Value) if self.Constraints[0].Type == "Angle" else q.Value

    def getDatum(self, _index):
        return getattr(self.feature, self.prop)

    @property
    def ExpressionEngine(self):
        ""


        expr = dict(getattr(self.feature, "ExpressionEngine", []) or []).get(self.prop)
        return [("Constraints[0]", expr)] if expr else []

    def setExpression(self, _path, expr):
        self.feature.setExpression(self.prop, expr)

    def renameConstraint(self, _index, _name):
        pass

    def solve(self):
        self.Document.recompute()
        return 0

    def recompute(self):
        self.Document.recompute()

    def addProperty(self, *_args):
        return self

    def setEditorMode(self, *_args):
        pass


def _box_class():
    from .fwsketch import modifybox

    class PartModify(modifybox.ModifyBox):
        """The Modify box in a part: its rebuild button rebuilds the part, not just the sketch."""

        def rebuild(self):
            try:
                self.apply_value()
                self.sketch.Document.recompute()
            except Exception as error:
                self.value_failed(error)
            self.select_number()

        def apply_to_configurations(self):
            """A feature's own dimension (Depth, Angle...): This / All / Specify Configurations go to the
            feature's property, not to a sketch constraint (the adapter has no name or table column)."""
            target = self.sketch
            if not isinstance(target, _Adapter):
                return super().apply_to_configurations()
            from . import configs
            unit = "deg" if self.angle else "mm"
            configs.set_value(target.feature, target.prop, App.Units.Quantity(self.quantity_text()),
                              self.config_scope, old=App.Units.Quantity("%.8g %s" % (self.initial, unit)))
    return PartModify


seen = []              # double-clicks the filter saw (for checks)
modified = []          # (object label, what, new text) for checks
auto_answer = None     # for checks: a value the box takes without showing


def modify(dim):
    """The Modify box on a shown dimension; True when the value was kept (the part rebuilt)."""
    if not dim.driving:
        try:
            Gui.getMainWindow().statusBar().showMessage(
                "A driven dimension shows a value; it cannot be changed.", 4000)
        except Exception as _fw_err:
            _fw_log("featuredimshow.py:415", _fw_err)
        return False
    doc = dim.obj.Document
    doc.openTransaction("Modify")
    try:
        target = dim.obj if dim.prop is None else _Adapter(dim.obj, dim.prop, dim.kind)
        index = dim.index if dim.prop is None else 0
        box = _box_class()(target, index)
        # the "Modify" step above holds only this box's change: Enter with the value as it was, or the
        # cross, drops it (no empty Undo step, Redo kept), as for a sketch dimension
        box.own_transaction = True
        if auto_answer is not None:
            box.set_value(auto_answer)
            box.accept()
            ok = box.success
        else:
            ok = box.run()
        if ok:
            doc.recompute()
            modified.append((dim.obj.Label, dim.prop if dim.prop else dim.index, box.quantity_text()))
        QtCore.QTimer.singleShot(0, SHOWN.again)
        return ok
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise


# ------------------------------------------------------------------ the mouse
def _viewport():
    from .instant3d import _viewport as vp
    return vp()


def _coin_pos(widget, event):
    g = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
    q = widget.mapFromGlobal(g)
    r = widget.devicePixelRatioF()
    return q.x() * r, (widget.height() - q.y()) * r, r


def dim_at(view, x, y, ratio, dims):
    best, near = None, None
    for d in dims:
        try:
            px, py = view.getPointOnScreen(d.point)
        except Exception:
            continue
        w = max(22.0, len(d.text) * 4.5) * ratio
        dx, dy = abs(px - x), abs(py - y)
        if dx <= w and dy <= 12 * ratio:
            score = dx + dy
            if near is None or score < near:
                best, near = d, score
    return best


def _busy():
    try:
        gdoc = Gui.ActiveDocument
        if gdoc is None or gdoc.getInEdit() is not None:
            return True
        return Gui.Control.activeDialog()
    except Exception:
        return True


def _handle(obj, event):
    t = event.type()
    QE = QtCore.QEvent
    if t == QE.KeyPress:
        if event.key() == QtCore.Qt.Key_Escape and SHOWN.root is not None and not _busy():
            hide()
        return False
    widget = _viewport()
    if t == QE.MouseButtonDblClick and len(seen) < 50:
        seen.append((type(obj).__name__, obj is widget, busy_reason()))
    if widget is None or obj is not widget or not enabled() or _busy():
        return False
    if hasattr(event, "button") and event.button() == QtCore.Qt.RightButton and SHOWN.root is not None:
        return _right(widget, event, t)
    if t == QE.ContextMenu and _swallow[0]:
        return True
    if not hasattr(event, "button") or event.button() != QtCore.Qt.LeftButton:
        return False
    doc = App.ActiveDocument
    if doc is None:
        return False
    view = Gui.ActiveDocument.ActiveView
    x, y, ratio = _coin_pos(widget, event)
    g = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
    local = widget.mapFromGlobal(g)
    lx, ly = local.x(), local.y()
    if t == QE.MouseButtonPress:
        if SHOWN.root is not None and _picked_at(view, lx, ly)[0] is None \
                and dim_at(view, x, y, ratio, SHOWN.dims) is None:
            hide()             # a click in empty space takes the dimensions away
        return False
    if t != QE.MouseButtonDblClick:
        return False
    dims = list(SHOWN.dims)
    try:
        from . import featuredims
        if featuredims.on(doc):
            dims += all_dims(doc)
    except Exception as _fw_err:
        _fw_log("featuredimshow.py:513", _fw_err)
    d = dim_at(view, x, y, ratio, dims)
    if d is not None:
        QtCore.QTimer.singleShot(0, lambda: modify(d))
        return True
    picked, sub = _picked_at(view, lx, ly)
    if picked is None:
        return False
    feature = feature_of(picked, sub)
    if feature is None or not dims_of(feature):
        return False
    show(feature)
    return True


_swallow = [False]
LAST_MENU = [None]


def path_of(d):
    """(object, expression path) of a shown dimension."""
    if d.prop is not None:
        return d.obj, d.prop
    return d.obj, "Constraints[%d]" % d.index


def _right(widget, event, t):
    ""
    QE = QtCore.QEvent
    if t == QE.MouseButtonRelease and _swallow[0]:
        return True
    if t != QE.MouseButtonPress:
        return False
    view = Gui.ActiveDocument.ActiveView
    x, y, ratio = _coin_pos(widget, event)
    d = dim_at(view, x, y, ratio, SHOWN.dims)
    if d is not None and not d.driving:
        from . import equations
        if equations.linked_name(*path_of(d)) is None:
            d = None
    if d is None:
        _swallow[0] = False
        return False
    _swallow[0] = True
    g = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
    QtCore.QTimer.singleShot(0, lambda: dim_menu(d, g))
    QtCore.QTimer.singleShot(400, lambda: _swallow.__setitem__(0, False))
    return True


def dim_menu(d, global_pos=None):
    from . import equations
    obj, path = path_of(d)
    menu = QtWidgets.QMenu(Gui.getMainWindow())
    menu.setObjectName("SWFeatureDimensionMenu")
    linked = equations.linked_name(obj, path)
    act = menu.addAction("Link Values...")
    act.setObjectName("LinkValues")
    act.triggered.connect(lambda: link_dialog(d))
    un = menu.addAction("Unlink Value")
    un.setObjectName("UnlinkValue")
    un.setEnabled(linked is not None)
    un.triggered.connect(lambda: _do(obj.Document, "Unlink Value", lambda: equations.unlink_value(obj, path)))
    LAST_MENU[0] = menu
    menu.popup(global_pos or QtGui.QCursor.pos())
    return menu


def _do(doc, title, fn):
    doc.openTransaction(title)
    try:
        fn()
    except Exception as error:
        doc.abortTransaction()
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), title, str(error))
        return
    doc.commitTransaction()
    SHOWN.again()


def link_dialog(d, name=None):
    ""
    from . import equations
    obj, path = path_of(d)
    doc = obj.Document
    if name is None:
        names = equations.linked_values(doc)
        name, ok = QtWidgets.QInputDialog.getItem(Gui.getMainWindow(), "Shared Values", "Name:",
                                                  names or [""], 0, True)
        if not ok:
            return
    name = (name or "").strip()
    if name:
        _do(doc, "Link Values", lambda: equations.link_value(obj, path, name))


def _picked_at(view, x, y):
    """The object and face under the pointer (the preselection, else a pick at the point).
    x, y: the pointer in the viewport widget, from its top left (getObjectInfo's way)."""
    doc = App.ActiveDocument
    pre = Gui.Selection.getPreselection()
    try:
        if pre.ObjectName:
            return doc.getObject(pre.ObjectName), (pre.SubElementNames[0] if pre.SubElementNames else "")
    except Exception as _fw_err:
        _fw_log("featuredimshow.py:618", _fw_err)
    try:
        info = view.getObjectInfo((int(x), int(y)))
    except Exception:
        info = None
    if not info:
        return None, ""
    obj = doc.getObject(info.get("Object", "")) if doc is not None else None
    sub = info.get("Component", "") or ""
    # a pick in an assembly or a link may name the sub path: keep the last element
    if "." in sub:
        sub = sub.split(".")[-1]
    return obj, sub


def busy_reason():
    try:
        gdoc = Gui.ActiveDocument
        if gdoc is None:
            return "no document"
        if gdoc.getInEdit() is not None:
            return "editing"
        if Gui.Control.activeDialog():
            return "task dialog"
    except Exception as error:
        return repr(error)
    return ""


def tree_double_click(obj):
    """fmtree: a double-click on a feature or sketch row shows its dimensions. True when shown."""
    if not enabled() or obj is None or _busy():
        return False
    if not (obj.TypeId == SKETCH or obj.isDerivedFrom("PartDesign::Feature")) or obj.TypeId == "PartDesign::Body":
        return False
    return bool(show(obj))


class _Watch:
    def slotRecomputedDocument(self, doc):
        if SHOWN.root is not None:
            QtCore.QTimer.singleShot(0, SHOWN.again)

    def slotDeletedDocument(self, doc):
        hide()


_watch = []


def install():
    if _watch:
        return
    _watch.append(_Watch())
    App.addDocumentObserver(_watch[0])
    events.register("featuredimshow", (QtCore.QEvent.MouseButtonDblClick, QtCore.QEvent.MouseButtonPress,
                                       QtCore.QEvent.KeyPress), _handle)


def _equation_driven(d):
    """The dimension's value comes from an equation (an expression on its property or constraint)."""
    try:
        obj, path = path_of(d)
        names = {path}
        if d.prop is None:
            c = obj.Constraints[d.index]
            if c.Name:
                names.add("Constraints." + c.Name)
        return any(p.lstrip(".") in names for p, _e in (obj.ExpressionEngine or []))
    except Exception:
        return False


def names_on():
    """System Options > General > Show dimension names, the same switch as View > Hide/Show > Dimension
    Names (FreeCAD's Sketcher ShowDimensionalName, which the sketches in edit follow)."""
    try:
        return App.ParamGet("User parameter:BaseApp/Preferences/Mod/Sketcher").GetBool("ShowDimensionalName", False)
    except Exception:
        return False


def dim_name(d):
    ""
    try:
        from . import equations
        return equations.sw_name(*path_of(d))
    except Exception:
        return ""


def shown_lines(d):
    """The text of a shown dimension, line by line: its name above the value with Show dimension names."""
    text = shown_text(d) if d.driving else "(%s)" % shown_text(d)
    name = dim_name(d) if names_on() else ""
    return [name, text] if name else [text]


def shown_text(d):
    ""


    from . import optionspages as op
    text = d.text
    try:
        inch = text.rstrip().endswith('"') or text.rstrip().endswith(" in")
        if inch and not op.doc_value(App.ActiveDocument, "Dimensions", 'Include leading zero for values less than 1"', False):
            text = re.sub(r"(?<![\d.])0(\.\d)", r"\1", text)
        if _equation_driven(d) and op.stored("Display", "Display unique equation identifier", True):
            text = "\u03a3" + text
    except Exception as _fw_err:
        _fw_log("featuredimshow.py:729", _fw_err)
    return text
