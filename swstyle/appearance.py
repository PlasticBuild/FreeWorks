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

TITLE = "Appearance"
PROP = "SWAppearance"
LEVELS = ("part", "body", "feature", "face")
LABELS = {"part": "Part", "body": "Body", "feature": "Feature", "face": "Face", "surface": "Surface"}

# Select Surfaces, which takes surface bodies the way Select Bodies takes solid ones; stored as body level)
BUTTON_ORDER = ("part", "face", "feature", "body", "surface")


def level_icon(level, size=20):
    ""

    from PySide import QtGui as G
    pm = G.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = G.QPainter(pm)
    p.setRenderHint(G.QPainter.Antialiasing)
    s = size / 20.0
    ink = G.QColor(70, 90, 120)
    pen = G.QPen(ink, 1.2 * s)
    p.setPen(pen)

    def poly(points, fill):
        p.setBrush(G.QBrush(fill) if fill is not None else QtCore.Qt.NoBrush)
        p.drawPolygon(G.QPolygonF([QtCore.QPointF(x * s, y * s) for x, y in points]))

    top = [(3, 7), (10, 3), (17, 7), (10, 11)]
    left = [(3, 7), (10, 11), (10, 18), (3, 14)]
    right = [(10, 11), (17, 7), (17, 14), (10, 18)]
    light, mid, dark, hot = G.QColor(225, 230, 238), G.QColor(185, 195, 210), G.QColor(150, 162, 180), G.QColor(250, 190, 60)
    if level == "part":
        poly(top, light); poly(left, mid); poly(right, dark)
        p.setPen(G.QPen(ink, 1.0 * s, QtCore.Qt.DotLine))
        p.drawLine(QtCore.QPointF(10 * s, 11 * s), QtCore.QPointF(10 * s, 18 * s))
    elif level == "face":
        poly(top, hot); poly(left, None); poly(right, None)
    elif level == "surface":
        # a thin curved sheet, no thickness
        path = G.QPainterPath(QtCore.QPointF(2 * s, 13 * s))
        path.cubicTo(QtCore.QPointF(6 * s, 6 * s), QtCore.QPointF(10 * s, 12 * s), QtCore.QPointF(13 * s, 5 * s))
        path.lineTo(QtCore.QPointF(18 * s, 8 * s))
        path.cubicTo(QtCore.QPointF(15 * s, 15 * s), QtCore.QPointF(11 * s, 9 * s), QtCore.QPointF(7 * s, 16 * s))
        path.closeSubpath()
        p.setBrush(G.QBrush(hot))
        p.drawPath(path)
    elif level == "feature":
        poly([(2, 12), (10, 8), (18, 12), (10, 16)], light)
        poly([(2, 12), (10, 16), (10, 18), (2, 14)], mid)
        poly([(10, 16), (18, 12), (18, 14), (10, 18)], dark)
        poly([(7, 7), (10, 5.5), (13, 7), (10, 8.5)], hot)
        poly([(7, 7), (10, 8.5), (10, 12), (7, 10.5)], G.QColor(230, 160, 40))
        poly([(10, 8.5), (13, 7), (13, 10.5), (10, 12)], G.QColor(200, 135, 30))
    else:
        poly(top, mid); poly(left, dark); poly(right, G.QColor(120, 132, 150))
    p.end()
    return G.QIcon(pm)


# --------------------------------------------------------------------------- the stored map
def _solid_feature(obj):
    return (obj is not None and obj.TypeId.startswith("PartDesign::") and obj.TypeId != "PartDesign::Body"
            and hasattr(obj, "BaseFeature"))


def bodies(doc):
    return [o for o in doc.Objects if o.TypeId == "PartDesign::Body"]


def is_component(obj):
    ""

    try:
        return obj is not None and obj.isDerivedFrom("App::Link") and obj.ViewObject is not None
    except Exception as _fw_err:
        _fw_log("appearance.py:61", _fw_err)
        return False


def _loose(obj):
    """Something outside any Body that Part scope can colour: a loose solid or a component."""
    if is_component(obj):
        return True
    try:
        return obj is not None and obj.isDerivedFrom("Part::Feature") \
            and not obj.isDerivedFrom("Part::Part2DObject") and obj.ViewObject is not None
    except Exception as _fw_err:
        _fw_log("appearance.py:73", _fw_err)
        return False


def own_body(obj):
    ""


    return body_of(obj) is None and _loose(obj) and not is_component(obj)


def _owners(doc):
    """Everything that keeps appearances of its own: the bodies, then the loose solids and surface bodies."""
    return bodies(doc) + [o for o in loose_features(doc) if PROP in o.PropertiesList]


def _surface(obj):
    try:
        shape = obj.Shape
        return not shape.isNull() and bool(shape.Faces) and not shape.Solids
    except Exception:
        return False


def body_of(obj):
    if obj is None:
        return None
    if obj.TypeId == "PartDesign::Body":
        return obj
    for parent in obj.InList:
        if parent.TypeId == "PartDesign::Body":
            return parent
    return None


def stored(body):
    return dict(getattr(body, PROP, {}) or {})


def store(body, values):
    if PROP not in body.PropertiesList:
        body.addProperty("App::PropertyMap", PROP, "FreeCAD", "Appearances (face, feature, body, part)")
        body.setEditorMode(PROP, 2)
    setattr(body, PROP, values)


def encode(rgbt):
    return ",".join("%.4f" % x for x in rgbt)


def decode(text, full=False):
    """r, g, b, transparency; full=True adds the Advanced illumination values when stored."""
    try:
        v = [float(x) for x in text.split(",")]
        if full and len(v) >= 4 + len(ILLUMINATION):
            return tuple(v[:4 + len(ILLUMINATION)])
        return tuple(v[:4]) if len(v) >= 4 else tuple(v[:3]) + (0.0,)
    except Exception as _fw_err:
        _fw_log("appearance.py:111", _fw_err)
        return None



ILLUMINATION = [
    ("diffuse", "Diffuse amount", 0.8),
    ("specular", "Specular amount", 0.3),
    ("spread", "Specular spread", 0.3),
    ("reflection", "Reflection amount", 0.0),
    ("blurry", "Blurry reflection", 0.0),
    ("luminous", "Luminous intensity", 0.0),
]
DEFAULT_LIGHT = tuple(d for _n, _l, d in ILLUMINATION)

PRESETS = [
    ("Plastic - high gloss", (0.8, 0.8, 0.1, 0.15, 0.0, 0.0)),
    ("Plastic - medium gloss", (0.8, 0.45, 0.3, 0.05, 0.1, 0.0)),
    ("Plastic - matte", (0.85, 0.1, 0.7, 0.0, 0.0, 0.0)),
    ("Metal - polished", (0.6, 1.0, 0.05, 0.6, 0.0, 0.0)),
    ("Metal - satin", (0.7, 0.7, 0.35, 0.3, 0.4, 0.0)),
    ("Metal - brushed", (0.7, 0.6, 0.5, 0.2, 0.6, 0.0)),
    ("Glass - clear", (0.3, 1.0, 0.02, 0.5, 0.0, 0.0)),
    ("Rubber", (0.9, 0.05, 0.9, 0.0, 0.0, 0.0)),
    ("Light - emissive", (0.8, 0.1, 0.5, 0.0, 0.0, 1.0)),
]


def appearance_name(target):
    ""

    try:
        look = current_look(target)
        light = tuple(round(x, 2) for x in look[4:4 + len(ILLUMINATION)])
        for name, values in PRESETS:
            if light and light == tuple(round(x, 2) for x in values):
                return name.lower()
    except Exception as _fw_err:
        _fw_log("appearance.py:name", _fw_err)
    return "color"


def with_light(rgbt, light):
    """rgbt plus illumination values (dropped when they are the defaults)."""
    base = tuple(rgbt[:4])
    if light is None or all(abs(a - b) < 1e-6 for a, b in zip(light, DEFAULT_LIGHT)):
        return base
    return base + tuple(light)


def key_of(level, obj=None, sub=""):
    if level in ("part", "body"):
        return level
    if level == "feature":
        return "feature:" + obj.Name
    return "face:%s:%s" % (obj.Name, sub)


# --------------------------------------------------------------------------- which face is whose
def owner_feature(obj, sub):
    try:
        from . import contextbar
        return contextbar.owner_feature(obj, sub)
    except Exception as _fw_err:
        _fw_log("appearance.py:161", _fw_err)
        return obj


def own_face(obj, sub):
    """(the feature that made the face, the face's name there)."""
    import Part
    owner = owner_feature(obj, sub)
    if owner is None or owner is obj or not _solid_feature(owner):
        return obj, sub
    face = obj.Shape.getElement(sub)
    probe = Part.Vertex(face.CenterOfMass)
    for i, f in enumerate(owner.Shape.Faces):
        try:
            if type(f.Surface) is type(face.Surface) and f.distToShape(probe)[0] < 1e-6:
                return owner, "Face%d" % (i + 1)
        except Exception as _fw_err:
            _fw_log("appearance.py:178", _fw_err)
            continue
    return obj, sub


def _samples(face):
    try:
        from . import contextbar
        return contextbar._samples(face)
    except Exception:
        return [face.CenterOfMass]


def _on(points, face):
    import Part
    for p in points:
        try:
            if face.distToShape(Part.Vertex(p))[0] > 1e-4:
                return False
        except Exception:
            return False
    return bool(points)


# --------------------------------------------------------------------------- painting
_defaults = {}      # (doc, body) -> the body's own first material, before any appearance
_painted = set()    # (doc, body) painted by us


def _template(body):
    key = (body.Document.Name, body.Name)
    if key not in _defaults:
        try:
            _defaults[key] = body.ViewObject.ShapeAppearance[0]
        except Exception:
            try:    # a component: the look of the part it links to
                _defaults[key] = body.LinkedObject.ViewObject.ShapeAppearance[0]
            except Exception:
                _defaults[key] = App.Material()
    return _defaults[key]


def _material(template, rgbt):
    m = App.Material()
    for attr in ("AmbientColor", "SpecularColor", "EmissiveColor", "Shininess", "Transparency", "DiffuseColor"):
        try:
            setattr(m, attr, getattr(template, attr))
        except Exception as _fw_err:
            _fw_log("appearance.py:220", _fw_err)
    if rgbt is not None:
        r, g, b, t = rgbt[:4]
        m.DiffuseColor = (r, g, b)
        m.AmbientColor = (r * 0.3, g * 0.3, b * 0.3)
        m.Transparency = t
        if len(rgbt) >= 4 + len(ILLUMINATION):
            diffuse, specular, spread, reflection, blurry, luminous = rgbt[4:4 + len(ILLUMINATION)]
            m.DiffuseColor = tuple(min(1.0, c * diffuse / 0.8) for c in (r, g, b))
            # a reflection shows as a brighter ambient and a sharper highlight; blurry spreads it again
            amb = 0.3 + 0.4 * reflection
            m.AmbientColor = (r * amb, g * amb, b * amb)
            m.SpecularColor = (specular, specular, specular)
            m.Shininess = max(0.0, min(1.0, (1.0 - spread) * (1.0 - 0.5 * blurry)))
            m.EmissiveColor = (r * luminous, g * luminous, b * luminous)
    return m


def face_colours(body, own=None):
    """The colour of each face of the tip (None = the body's own), from the stored map. own (a set), when
    given, gets the faces that have their own appearance (a face's or its feature's)."""
    tip = body.Tip
    values = stored(body)
    base = decode(values.get("body", ""), True) or decode(values.get("part", ""), True)
    faces = tip.Shape.Faces
    out = [base] * len(faces)
    features = {k[8:]: decode(v, True) for k, v in values.items() if k.startswith("feature:")}
    if features:
        for i in range(len(faces)):
            owner = owner_feature(tip, "Face%d" % (i + 1))
            if owner is not None and owner.Name in features:
                out[i] = features[owner.Name]
                if own is not None:
                    own.add(i)
    for k, v in values.items():
        if not k.startswith("face:"):
            continue
        _, name, sub = k.split(":", 2)
        owner = body.Document.getObject(name)
        try:
            target = owner.Shape.getElement(sub)
        except Exception as _fw_err:
            _fw_log("appearance.py:265", _fw_err)
            continue
        rgbt = decode(v, True)
        for i, f in enumerate(faces):
            if type(f.Surface) is type(target.Surface) and _on(_samples(f), target):
                out[i] = rgbt
                if own is not None:
                    own.add(i)
    return out


def tip_faces(body, key):
    """The indices of the tip's faces a "feature:Name" or "face:Name:FaceN" key covers (as face_colours)."""
    tip = body.Tip
    faces = tip.Shape.Faces
    if key.startswith("feature:"):
        name = key[8:]
        out = []
        for i in range(len(faces)):
            owner = owner_feature(tip, "Face%d" % (i + 1))
            if owner is not None and owner.Name == name:
                out.append(i)
        return out
    if key.startswith("face:"):
        _, name, sub = key.split(":", 2)
        owner = body.Document.getObject(name)
        try:
            target = owner.Shape.getElement(sub)
        except Exception as _fw_err:
            _fw_log("appearance.py:tipfaces", _fw_err)
            return []
        return [i for i, f in enumerate(faces) if type(f.Surface) is type(target.Surface) and _on(_samples(f), target)]
    return []


def _see_through(body):
    ""


    try:
        return max(0.0, min(1.0, int(body.ViewObject.Transparency) / 100.0))
    except Exception:
        return 0.0


def _thin(m, t):
    if t > m.Transparency:
        m.Transparency = t
    return m


def paint(body):
    """Paints the tip (and the features before it) from the stored map."""
    if not App.GuiUp or body is None or body.ViewObject is None:
        return
    tip = body.Tip
    key = (body.Document.Name, body.Name)
    values = stored(body)
    if not _solid_feature(tip) or tip.ViewObject is None:
        return
    template = _template(body)
    if not values and key not in _painted and PROP not in body.PropertiesList:
        return
    colours = face_colours(body)
    seen = _see_through(body)
    tip.ViewObject.ShapeAppearance = [_thin(_material(template, c), seen) for c in colours]
    base = decode(values.get("body", ""), True) or decode(values.get("part", ""), True)
    for f in body.Group:
        if f is not tip and _solid_feature(f) and f.ViewObject is not None:
            f.ViewObject.ShapeAppearance = [_thin(_material(template, base), seen)]
    if values:
        _painted.add(key)
    else:
        _painted.discard(key)
    try:
        from . import appeartex
        if appeartex.PROP in body.PropertiesList or appeartex.KEYED in body.PropertiesList:
            appeartex.apply(body)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: appearance image: %s\n" % error)
    try:
        from . import multibody
        multibody._look.colours.pop((tip.Document.Name, tip.Name), None)
        multibody.refresh(body.Document)
    except Exception as _fw_err:
        _fw_log("appearance.py:300", _fw_err)


_pending = set()


def later(body):
    if body is None:
        return
    key = (body.Document.Name, body.Name)
    if key in _pending:
        return
    _pending.add(key)

    def run():
        _pending.discard(key)
        try:
            b = App.getDocument(key[0]).getObject(key[1])
            if b is not None:
                paint(b)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: appearance not painted: %s\n" % error)
    QtCore.QTimer.singleShot(0, run)


class _Observer:
    def slotChangedObject(self, obj, prop):
        if prop in (PROP, "Tip") and obj.TypeId == "PartDesign::Body":
            try:
                if obj.Document.Restoring:
                    return      # the file holds the painted colours already: opening changes nothing
            except Exception as _fw_err:
                _fw_log("appearance.py:332", _fw_err)
            later(obj)

    def slotRecomputedDocument(self, doc):
        for b in bodies(doc):
            if PROP in b.PropertiesList:
                later(b)
            else:
                try:
                    from . import appeartex
                    if appeartex.PROP in b.PropertiesList:
                        appeartex.apply(b)
                except Exception as _fw_err:
                    _fw_log("appearance.py:345", _fw_err)
        for obj in doc.Objects:
            if PROP in obj.PropertiesList and obj.TypeId != "PartDesign::Body" and body_of(obj) is None:
                try:
                    paint_loose(obj)
                except Exception as _fw_err:
                    _fw_log("appearance.py:351", _fw_err)

    def slotUndoDocument(self, doc):
        self.slotRecomputedDocument(doc)

    def slotRedoDocument(self, doc):
        self.slotRecomputedDocument(doc)


# --------------------------------------------------------------------------- targets
class Target:
    """One appearance target: the level and what it names."""

    def __init__(self, level, body, obj=None, sub=""):
        self.level, self.body, self.obj, self.sub = level, body, obj, sub

    def key(self):
        return key_of(self.level, self.obj, self.sub)

    def name(self):
        if self.level == "part":
            return self.body.Document.Label if self.body.TypeId == "PartDesign::Body" else self.body.Label
        if self.level == "body":
            return self.body.Label
        if self.level == "feature":
            return self.obj.Label
        return "%s@%s" % (self.sub, self.obj.Label)

    def bodies(self):
        if self.level == "part" and self.body.TypeId == "PartDesign::Body":
            return bodies(self.body.Document)
        return [self.body]

    def whole_part(self):
        """Part scope of a part document: every body and loose solid, not one component."""
        return self.level == "part" and self.body.TypeId == "PartDesign::Body"

    def same(self, other):
        return self.level == other.level and self.key() == other.key() and \
            (self.level == "part" or self.body == other.body)


def target_for(level, obj, sub):
    ""

    if level == "surface":
        if body_of(obj) is not None or not own_body(obj) or not _surface(obj):
            return None
        t = Target("body", obj)
        t.pick = (obj, sub)
        return t
    body = body_of(obj)
    if body is None:
        if level == "part" and _loose(obj):
            return Target("part", obj)      # a loose solid or a component stands in for the body
        if not own_body(obj):
            return None
        if level == "body":
            t = Target("body", obj)
        elif level == "feature":
            t = Target("feature", obj, obj)
        elif sub.startswith("Face"):
            t = Target("face", obj, obj, sub)
        else:
            return None
        t.pick = (obj, sub)
        return t
    if level in ("part", "body"):
        t = Target(level, body)
    elif level == "feature":
        feature = owner_feature(obj, sub) if sub.startswith("Face") else obj
        t = Target("feature", body, feature) if _solid_feature(feature) else None
    elif not sub.startswith("Face"):
        return None
    else:
        owner, face = own_face(obj, sub)
        t = Target("face", body, owner, face)
    if t is not None:
        t.pick = (obj, sub)     # the pick itself, so Face/Feature/Body/Part can be switched back and forth
    return t


def current_look(target):
    """current_colour plus the illumination values (the defaults when none are stored)."""
    look = current_colour(target, True)
    return tuple(look[:4]) + (tuple(look[4:]) if len(look) > 4 else DEFAULT_LIGHT)


def current_colour(target, full=False):
    """The colour the target shows now (stored, or what it inherits)."""
    values = stored(target.body)
    order = {"face": ["face", "feature", "body", "part"], "feature": ["feature", "body", "part"],
             "body": ["body", "part"], "part": ["part"]}[target.level]
    for level in order:
        if level == "face":
            k = target.key()
        elif level == "feature":
            k = "feature:" + (target.obj.Name if target.level == "feature" else
                              getattr(owner_feature(target.obj, target.sub), "Name", ""))
        else:
            k = level
        if k in values:
            return decode(values[k], full)
    m = _template(target.body)
    return tuple(m.DiffuseColor[:3]) + (m.Transparency,)


def loose_features(doc):
    """Solids outside any Body (a Part::Fillet made in stock FreeCAD, an imported STEP...): Part
    scope colours them too (EX509: a stock fillet stayed grey)."""
    out = []
    for obj in doc.Objects:
        try:
            if not obj.isDerivedFrom("Part::Feature") or obj.TypeId.startswith("PartDesign::"):
                continue
            if obj.isDerivedFrom("Part::Part2DObject") or obj.ViewObject is None:
                continue
            if body_of(obj) is not None or obj.getParentGeoFeatureGroup() is not None and \
                    obj.getParentGeoFeatureGroup().TypeId == "PartDesign::Body":
                continue
            if obj.Shape.isNull() or not obj.Shape.Faces:
                continue
        except Exception as _fw_err:
            _fw_log("appearance.py:463", _fw_err)
            continue
        out.append(obj)
    return out


def paint_loose(obj):
    values = stored(obj)
    template = _template(obj)
    if PROP not in obj.PropertiesList:
        return
    base = decode(values.get("part", ""), True)
    if not is_component(obj):
        # a surface body's own levels: its faces, then the feature, the body, the part
        whole = decode(values.get("feature:" + obj.Name, ""), True) or decode(values.get("body", ""), True) or base
        prefix = "face:%s:" % obj.Name
        faces = {k[len(prefix):]: decode(v, True) for k, v in values.items() if k.startswith(prefix)}
        try:
            if faces:
                n = len(obj.Shape.Faces)
                obj.ViewObject.ShapeAppearance = [_material(template, faces.get("Face%d" % (i + 1), whole))
                                                  for i in range(n)]
            else:
                obj.ViewObject.ShapeAppearance = [_material(template, whole)]
        except Exception as error:
            App.Console.PrintLog("FreeCAD: appearance not painted: %s\n" % error)
        return
    try:
        if is_component(obj):
            # an App::Link shows its own material only with OverrideMaterial on
            vo = obj.ViewObject
            vo.OverrideMaterial = "part" in values
            if "part" in values:
                vo.ShapeMaterial = _material(template, base)
            return
        obj.ViewObject.ShapeAppearance = [_material(template, base)]
    except Exception as error:
        App.Console.PrintLog("FreeCAD: appearance not painted: %s\n" % error)


def _paint(obj):
    if obj.TypeId == "PartDesign::Body":
        paint(obj)
    else:
        paint_loose(obj)


def apply(targets, rgbt):
    for t in targets:
        for b in t.bodies():
            values = stored(b)
            values[t.key()] = encode(rgbt)
            store(b, values)
            _paint(b)
        if t.whole_part():
            for obj in loose_features(t.body.Document):
                values = stored(obj)
                values["part"] = encode(rgbt)
                store(obj, values)
                paint_loose(obj)


def remove(targets):
    for t in targets:
        for b in t.bodies():
            values = stored(b)
            had_image = False
            if t.level in ("face", "feature"):
                try:
                    from . import appeartex     # the face's or feature's own image goes with it
                    had_image = t.key() in appeartex.keyed(b)
                    if had_image:
                        appeartex.store_for(b, t.key(), {})
                except Exception as _fw_err:
                    _fw_log("appearance.py:removeimage", _fw_err)
            if t.key() in values or had_image:
                values.pop(t.key(), None)
                store(b, values)
                _paint(b)
        if t.whole_part():
            for obj in loose_features(t.body.Document):
                values = stored(obj)
                if "part" in values:
                    del values["part"]
                    store(obj, values)
                    paint_loose(obj)


# --------------------------------------------------------------------------- the PropertyManager
_current = None


def current():
    return _current


class _Escape(QtCore.QObject):
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


class _ColourPicker(QtWidgets.QWidget):
    ""





    currentColorChanged = QtCore.Signal(QtGui.QColor)
    RGB = (("R", "Red Component of Color", 255), ("G", "Green Component of Color", 255),
           ("B", "Blue Component of Color", 255))
    HSV = (("H", "Hue Component of Color", 359), ("S", "Saturation Component of Color", 255),
           ("V", "Value Component of Color", 255))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colour = QtGui.QColor(128, 128, 128)
        self._hsv = False
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # spectrum, the three sliders, then RGB / HSV
        top = QtWidgets.QHBoxLayout()
        self.dropper = QtWidgets.QToolButton(self)
        self.dropper.setObjectName("SWAppearancePickColor")
        self.dropper.setText("Pick")
        self.dropper.setIcon(_dropper_icon())
        self.dropper.setIconSize(QtCore.QSize(20, 20))
        self.dropper.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.dropper.setToolTip("Pick a Color: click anywhere on the screen to take the color there")
        self.dropper.setCheckable(True)
        self.dropper.toggled.connect(self._dropping)
        top.addWidget(self.dropper)
        self.preview = QtWidgets.QToolButton(self)
        self.preview.setObjectName("SWAppearanceColorPreview")
        self.preview.setToolTip("The color: click to define a custom color")
        self.preview.setMinimumSize(64, 28)
        self.preview.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.preview.clicked.connect(self._define)
        top.addWidget(self.preview, 1)
        lay.addLayout(top)
        self.swatch_slot = QtWidgets.QVBoxLayout()      # the swatches (appearextras) land here
        self.swatch_slot.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.swatch_slot)
        self.spectrum = _Spectrum(self)
        self.spectrum.setObjectName("SWAppearanceSpectrum")
        self.spectrum.picked.connect(self.setCurrentColor)
        lay.addWidget(self.spectrum)
        modes = QtWidgets.QHBoxLayout()
        self.mode_buttons = {}
        group = QtWidgets.QButtonGroup(self)
        for name in ("RGB", "HSV"):
            b = QtWidgets.QRadioButton(name, self)
            b.setObjectName("SWAppearanceColor" + name)
            b.setToolTip("Define colors with %s values" % ("red, green and blue" if name == "RGB" else
                                                           "hue, saturation and value"))
            b.clicked.connect(lambda _c=False, n=name: self.set_mode(n))
            group.addButton(b)
            modes.addWidget(b)
            self.mode_buttons[name] = b
        modes.addStretch(1)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self.labels, self.sliders, self.spins = [], [], []
        for i in range(3):
            label = QtWidgets.QLabel(self)
            slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
            slider.setObjectName("SWAppearanceColorSlider%d" % i)
            spin = QtWidgets.QSpinBox(self)
            spin.setObjectName("SWAppearanceColorValue%d" % i)
            spin.setFixedWidth(56)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(lambda _v: self._from_parts())
            grid.addWidget(label, i, 0)
            grid.addWidget(slider, i, 1)
            grid.addWidget(spin, i, 2)
            self.labels.append(label)
            self.sliders.append(slider)
            self.spins.append(spin)
        lay.addLayout(grid)
        lay.addLayout(modes)
        self._filter = None
        self.set_mode("RGB")

    # -- the colour --
    def currentColor(self):
        return QtGui.QColor(self._colour)

    def setCurrentColor(self, colour):
        colour = QtGui.QColor(colour)
        if not colour.isValid():
            return
        changed = colour.rgb() != self._colour.rgb()
        self._colour = colour
        self._show()
        if changed and not self.signalsBlocked():
            self.currentColorChanged.emit(QtGui.QColor(colour))

    def _parts(self):
        c = self._colour
        if self._hsv:
            h, s, v, _a = c.getHsv()
            return (max(0, h), s, v)
        return (c.red(), c.green(), c.blue())

    def _show(self):
        self.preview.setStyleSheet("QToolButton{background:%s; border:1px solid #777;}" % self._colour.name())
        for spin, value in zip(self.spins, self._parts()):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        for slider, spin in zip(self.sliders, self.spins):
            slider.blockSignals(True)
            slider.setValue(spin.value())
            slider.blockSignals(False)
        self._tint()

    def _tint(self):
        ""
        c = self._colour
        for i, slider in enumerate(self.sliders):
            if self._hsv:
                h, sat, v, _a = c.getHsv()
                h = max(h, 0)
                if i == 0:
                    stops = [QtGui.QColor.fromHsv(int(k * 359 / 6), max(sat, 160), max(v, 160)) for k in range(7)]
                elif i == 1:
                    stops = [QtGui.QColor.fromHsv(h, 0, v), QtGui.QColor.fromHsv(h, 255, v)]
                else:
                    stops = [QtGui.QColor.fromHsv(h, sat, 0), QtGui.QColor.fromHsv(h, sat, 255)]
            else:
                lo, hi = [c.red(), c.green(), c.blue()], [c.red(), c.green(), c.blue()]
                lo[i], hi[i] = 0, 255
                stops = [QtGui.QColor(*lo), QtGui.QColor(*hi)]
            n = len(stops) - 1
            grad = ", ".join("stop:%.3f %s" % (k / n, col.name()) for k, col in enumerate(stops))
            slider.setStyleSheet(
                "QSlider::groove:horizontal { height: 6px; border: 1px solid #777; border-radius: 2px;"
                " background: qlineargradient(x1:0, y1:0, x2:1, y2:0, %s); }"
                " QSlider::handle:horizontal { width: 8px; margin: -5px 0; background: #f0f0f0;"
                " border: 1px solid #555; border-radius: 2px; }" % grad)

    def _from_parts(self):
        a, b, c = (spin.value() for spin in self.spins)
        colour = QtGui.QColor.fromHsv(a, b, c) if self._hsv else QtGui.QColor(a, b, c)
        if colour.rgb() != self._colour.rgb():
            self._colour = colour
            self.preview.setStyleSheet("QToolButton{background:%s; border:1px solid #777;}" % colour.name())
            self._tint()
            self.currentColorChanged.emit(QtGui.QColor(colour))

    def set_mode(self, name):
        self._hsv = name == "HSV"
        self.mode_buttons[name].setChecked(True)
        for (short, tip, top), label, slider, spin in zip(self.HSV if self._hsv else self.RGB, self.labels,
                                                           self.sliders, self.spins):
            label.setText(short)
            label.setToolTip(tip)
            for w in (slider, spin):
                w.blockSignals(True)
                w.setRange(0, top)
                w.setToolTip(tip)
                w.blockSignals(False)
        self._show()

    def mode(self):
        return "HSV" if self._hsv else "RGB"

    # -- the full chooser and the eyedropper --
    def _define(self):
        got = QtWidgets.QColorDialog.getColor(self._colour, self, "Color")
        if got.isValid():
            self.setCurrentColor(got)

    def _dropping(self, on):
        app = QtWidgets.QApplication.instance()
        if on and self._filter is None:
            self._filter = _Dropper(self)
            app.installEventFilter(self._filter)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CrossCursor)
        elif not on and self._filter is not None:
            app.removeEventFilter(self._filter)
            self._filter = None
            QtWidgets.QApplication.restoreOverrideCursor()

    def take_screen_colour(self, pos):
        """The colour under the pointer. Inside FreeCAD's own windows the widget there is drawn into a
        picture (QWidget.grab), which gives the right pixel at any Windows display scale, also when
        FreeCAD runs unscaled and Windows stretches it; elsewhere on the screen the screen is read."""
        colour = None
        try:
            widget = _widget_at(pos)
            if widget is not None:
                local = widget.mapFromGlobal(pos)
                image = widget.grab().toImage()
                ratio = image.devicePixelRatio() or 1.0
                x, y = int(local.x() * ratio), int(local.y() * ratio)
                if image.valid(x, y):
                    colour = image.pixelColor(x, y)
            if colour is None:
                screen = QtGui.QGuiApplication.screenAt(pos) or QtGui.QGuiApplication.primaryScreen()
                image = screen.grabWindow(0, pos.x() - screen.geometry().x(), pos.y() - screen.geometry().y(), 1, 1).toImage()
                colour = QtGui.QColor(image.pixel(0, 0))
            colour.setAlpha(255)
            self.setCurrentColor(colour)
        except Exception as _fw_err:
            _fw_log("appearance.py:dropper", _fw_err)

    def hideEvent(self, event):
        self.dropper.setChecked(False)
        super().hideEvent(event)


class _Spectrum(QtWidgets.QWidget):
    ""


    picked = QtCore.Signal(QtGui.QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(48)
        self.setMaximumHeight(56)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setToolTip("Click a color in the spectrum")
        self._image = None

    def colour_at(self, x, y):
        w, h = max(1, self.width() - 1), max(1, self.height() - 1)
        hue = int(round(359 * min(max(x / w, 0.0), 1.0)))
        t = min(max(y / h, 0.0), 1.0)
        if t <= 0.5:
            return QtGui.QColor.fromHsv(hue, int(round(255 * t / 0.5)), 255)
        return QtGui.QColor.fromHsv(hue, 255, int(round(255 * (1.0 - (t - 0.5) / 0.5))))

    def paintEvent(self, event):
        size = self.size()
        if self._image is None or self._image.size() != size:
            image = QtGui.QImage(size, QtGui.QImage.Format_RGB32)
            for y in range(size.height()):
                for x in range(size.width()):
                    image.setPixel(x, y, self.colour_at(x, y).rgb())
            self._image = image
        p = QtGui.QPainter(self)
        p.drawImage(0, 0, self._image)
        p.setPen(QtGui.QColor(120, 120, 120))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)
        p.end()

    def _take(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self.picked.emit(self.colour_at(pos.x(), pos.y()))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._take(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & QtCore.Qt.LeftButton:
            self._take(event)


def _dropper_icon(size=20):
    """Our own eyedropper picture for Pick a Color."""
    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    s = size / 20.0
    p.translate(10 * s, 10 * s)
    p.rotate(45)
    p.setPen(QtGui.QPen(QtGui.QColor(60, 60, 60), 1.0 * s))
    p.setBrush(QtGui.QColor(70, 70, 75))
    p.drawRoundedRect(QtCore.QRectF(-2.5 * s, -9 * s, 5 * s, 6 * s), 1.5 * s, 1.5 * s)     # the bulb
    p.drawRect(QtCore.QRectF(-3.5 * s, -3.5 * s, 7 * s, 1.5 * s))                          # the collar
    p.setBrush(QtGui.QColor(200, 225, 245))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(-1.6 * s, -2 * s), QtCore.QPointF(1.6 * s, -2 * s),
                                   QtCore.QPointF(0.5 * s, 8 * s), QtCore.QPointF(-0.5 * s, 8 * s)]))  # the glass
    p.end()
    return QtGui.QIcon(pm)


def _widget_at(pos):
    """FreeCAD's own widget under a screen point, also where Qt's widgetAt finds none (a window
    partly off the screen, or one Windows stretches)."""
    widget = QtWidgets.QApplication.widgetAt(pos)
    if widget is not None:
        return widget
    for top in QtWidgets.QApplication.topLevelWidgets():
        if top.isVisible() and top.frameGeometry().contains(pos):
            return top.childAt(top.mapFromGlobal(pos)) or top
    return None


class _Dropper(QtCore.QObject):
    """Pick a Color: the next click anywhere takes the colour under the pointer; Esc stops."""

    def __init__(self, box):
        super().__init__(box)
        self.box = box

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.LeftButton:
                pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                box = self.box
                QtCore.QTimer.singleShot(0, lambda p=pos: (box.dropper.setChecked(False), box.take_screen_colour(p)))
            else:
                QtCore.QTimer.singleShot(0, lambda: self.box.dropper.setChecked(False))
            return True
        if t in (QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.MouseButtonDblClick):
            return True
        if t == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            QtCore.QTimer.singleShot(0, lambda: self.box.dropper.setChecked(False))
            return True
        return False


class MapHandle:
    """The image's handle on the faces (Mapping tab): a cross in the projection plane at the middle of the
    faces, drawn over the model; dragging it slides the image (Horizontal / Vertical location)."""

    NAME = "SWAppearanceMapHandle"

    def __init__(self, panel):
        from pivy import coin
        self.panel = panel
        self.view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument is not None else None
        self.root = coin.SoSeparator()
        self.root.setName(self.NAME)
        depth = coin.SoDepthBuffer()
        depth.test = False
        self.root.addChild(depth)
        self.xf = coin.SoTransform()
        self.root.addChild(self.xf)
        self.dragger = coin.SoTranslate2Dragger()
        self.root.addChild(self.dragger)
        self.dragger.addStartCallback(self._start, None)
        self.dragger.addMotionCallback(self._moved, None)
        self.dragger.addFinishCallback(self._done, None)
        self.k = 1.0
        self.axes = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        self.start = (0.0, 0.0)
        if self.view is not None:
            self.view.getSceneGraph().addChild(self.root)

    def _centre_and_size(self):
        box = None
        for t in self.panel.targets:
            try:
                if t.level == "face":
                    shape = t.obj.Shape.getElement(t.sub)
                elif t.level == "feature":
                    shape = t.obj.Shape
                else:
                    shape = t.body.Shape
                b = shape.BoundBox
            except Exception:
                continue
            if box is None:
                box = b
            else:
                box.add(b)
        if box is None or not box.isValid():
            return App.Vector(), 10.0
        return box.Center, max(box.DiagonalLength, 1.0)

    def place(self):
        """Puts the handle at the middle of the faces, in the plane the image is projected on, turned with it."""
        from pivy import coin
        import math
        from . import appeartex
        s = self.panel.texture_values()
        u, v = {"XY": ((1, 0, 0), (0, 1, 0)), "YZ": ((0, 1, 0), (0, 0, 1)),
                "ZX": ((0, 0, 1), (1, 0, 0))}[s["direction"] if s["direction"] in appeartex.DIRECTIONS else "XY"]
        a = math.radians(self.panel.tex_angle.value())
        su = tuple(math.cos(a) * x - math.sin(a) * y for x, y in zip(u, v))
        tv = tuple(math.sin(a) * x + math.cos(a) * y for x, y in zip(u, v))
        self.axes = (su, tv)
        centre, size = self._centre_and_size()
        # the image's location moves the handle with it
        p = centre + App.Vector(*su) * self.panel.hloc.value() + App.Vector(*tv) * self.panel.vloc.value()
        self.k = size * 0.04
        n = App.Vector(*su).cross(App.Vector(*tv))
        rot = App.Rotation(App.Vector(*su), App.Vector(*tv), n, "ZXY")
        self.xf.translation.setValue(p.x, p.y, p.z)
        self.xf.rotation.setValue(coin.SbRotation(*rot.Q))
        self.xf.scaleFactor.setValue(self.k, self.k, self.k)
        self.dragger.translation.setValue(0, 0, 0)

    def _start(self, *_a):
        self.start = (self.panel.hloc.value(), self.panel.vloc.value())

    def _moved(self, *_a):
        x, y, _z = self.dragger.translation.getValue().getValue()
        # the dragger moves in its own plane (the image's axes), in units of k
        self.panel.hloc.blockSignals(True)
        self.panel.vloc.blockSignals(True)
        self.panel.hloc.setValue(self.start[0] + x * self.k)
        self.panel.vloc.setValue(self.start[1] + y * self.k)
        self.panel.hloc.blockSignals(False)
        self.panel.vloc.blockSignals(False)
        QtCore.QTimer.singleShot(0, self.panel._texture_changed)

    def _done(self, *_a):
        QtCore.QTimer.singleShot(0, lambda: (self.panel._texture_changed(), self.place()))

    def remove(self):
        try:
            if self.view is not None:
                self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("appearance.py:handle-remove", _fw_err)


class AppearancePanel:
    ""



    TABS = ("Color/Image", "Mapping", "Illumination", "Surface Finish")

    def __init__(self, doc, level, targets):
        global _current
        _current = self
        self.doc, self.level = doc, level
        self.targets = list(targets)
        self.opened = False
        geometry = QtWidgets.QWidget()
        geometry.setWindowTitle("Selected Geometry")
        geometry.setProperty("swstyle_pm_title", appearance_name(targets[0]) if targets else "color")
        geometry.setProperty("swstyle_pm_icon", "I3DVIEW_EDIT_APPEAR")
        lay = QtWidgets.QVBoxLayout(geometry)
        self.mode = QtWidgets.QTabBar(geometry)
        self.mode.setObjectName("SWAppearanceMode")
        self.mode.addTab("Basic")
        self.mode.addTab("Advanced")
        lay.addWidget(self.mode)

        self.tabs = QtWidgets.QTabBar(geometry)
        self.tabs.setObjectName("SWAppearanceTabs")
        for name in self.TABS:
            self.tabs.addTab(name)
            self.tabs.setTabToolTip(self.tabs.count() - 1, name)

        self.tabs.setUsesScrollButtons(False)
        self.tabs.setExpanding(True)
        self.tabs.setElideMode(QtCore.Qt.ElideRight)
        # pkg173: tight tabs, so the four names read in full in the PM's width (they were cut to "Color/Im...", "Map...")
        self.tabs.setStyleSheet("QTabBar#SWAppearanceTabs::tab { padding: 4px 1px; margin: 0px; min-width: 0px; }")
        _f = self.tabs.font()
        _f.setPointSizeF(max(6.0, _f.pointSizeF() - 1.0))
        self.tabs.setFont(_f)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(QtCore.Qt.ElideNone)      # ElideRight cut every name even with room to spare
        self.tabs.setStyleSheet("QTabBar::tab { padding: 3px 4px; min-width: 0px; }")
        lay.addWidget(self.tabs)
        row = QtWidgets.QHBoxLayout()
        self.level_buttons = {}
        group = QtWidgets.QButtonGroup(geometry)
        for lv in BUTTON_ORDER:
            b = QtWidgets.QToolButton(geometry)
            b.setObjectName("SWAppearance%s" % LABELS[lv])
            b.setText(LABELS[lv])
            b.setIcon(level_icon(lv))
            b.setIconSize(QtCore.QSize(20, 20))
            b.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolTip("Select " + {"part": "part", "body": "bodies"}.get(lv, LABELS[lv].lower() + "s"))
            b.clicked.connect(lambda _c=False, v=lv: self.set_level(v))
            group.addButton(b)
            row.addWidget(b)
            self.level_buttons[lv] = b
        row.addStretch(1)
        lay.addLayout(row)
        self.list = QtWidgets.QListWidget(geometry)
        self.list.setObjectName("SWAppearanceSelection")
        self.list.setFixedHeight(70)
        self.list.setStyleSheet("QListWidget { background: #cfe3ff; }")
        lay.addWidget(self.list)
        self.remove_button = QtWidgets.QPushButton("Remove Appearance", geometry)
        self.remove_button.setObjectName("SWAppearanceRemove")
        self.remove_button.clicked.connect(self.remove)
        lay.addWidget(self.remove_button)
        colour = QtWidgets.QWidget()
        colour.setWindowTitle("Color")
        lay = QtWidgets.QVBoxLayout(colour)
        self.picker = _ColourPicker(colour)
        self.picker.setObjectName("SWAppearanceColor")
        lay.addWidget(self.picker)
        self.transparency = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.transparency.setObjectName("SWAppearanceTransparency")
        self.transparency.setRange(0, 100)
        self.transparency.setToolTip("Transparent amount: 0 opaque, 1 fully clear")
        # Advanced: the appearance type and Illumination
        kind = QtWidgets.QWidget()
        kind.setWindowTitle("Appearance")
        lay = QtWidgets.QVBoxLayout(kind)
        self.preset = QtWidgets.QComboBox(kind)
        self.preset.setObjectName("SWAppearancePreset")
        self.preset.addItem("Color (custom)")
        for name, _light in PRESETS:
            self.preset.addItem(name)
        self.preset.setToolTip("The kind of surface: sets the Illumination values")
        lay.addWidget(self.preset)
        light = QtWidgets.QWidget()
        light.setWindowTitle("Illumination")
        form = QtWidgets.QFormLayout(light)
        self.light = {}
        for name, label, _default in ILLUMINATION:
            spin = QtWidgets.QDoubleSpinBox(light)
            spin.setObjectName("SWAppearance_" + name)
            spin.setRange(0.0, 1.0)
            spin.setSingleStep(0.05)
            spin.setDecimals(2)
            form.addRow(label + ":", spin)
            self.light[name] = spin
            if name == "blurry":

                self.transparency.setParent(light)
                form.addRow("Transparent amount:", self.transparency)
        # Color/Image: the image
        from . import appeartex
        image = QtWidgets.QWidget()
        image.setWindowTitle("Image")
        form = QtWidgets.QFormLayout(image)
        row = QtWidgets.QHBoxLayout()
        self.image_path = QtWidgets.QLineEdit(image)
        self.image_path.setObjectName("SWAppearanceImagePath")
        self.image_path.setPlaceholderText("Image path")
        row.addWidget(self.image_path, 1)
        browse = QtWidgets.QPushButton("Browse...", image)
        browse.setObjectName("SWAppearanceImageBrowse")
        browse.clicked.connect(self._browse_image)
        row.addWidget(browse)
        form.addRow(row)
        clear = QtWidgets.QPushButton("Remove Image", image)
        clear.setObjectName("SWAppearanceImageRemove")
        clear.clicked.connect(lambda: (self.image_path.setText(""), self._texture_changed()))
        form.addRow(clear)
        # Mapping
        mapping = QtWidgets.QWidget()
        mapping.setWindowTitle("Mapping")
        form = QtWidgets.QFormLayout(mapping)
        self.mapping = QtWidgets.QComboBox(mapping)
        self.mapping.setObjectName("SWAppearanceMapping")
        self.mapping.addItems(list(appeartex.MAPPINGS))
        form.addRow("Mapping:", self.mapping)
        self.direction = QtWidgets.QComboBox(mapping)
        self.direction.setObjectName("SWAppearanceMappingDirection")
        self.direction.addItems(list(appeartex.DIRECTIONS))
        form.addRow("Projection direction:", self.direction)

        self.hloc = QtWidgets.QDoubleSpinBox(mapping)
        self.hloc.setObjectName("SWAppearanceHorizontalLocation")
        self.vloc = QtWidgets.QDoubleSpinBox(mapping)
        self.vloc.setObjectName("SWAppearanceVerticalLocation")
        for box in (self.hloc, self.vloc):
            box.setRange(-100000.0, 100000.0)
            box.setDecimals(2)
            box.setSuffix(" mm")
        form.addRow("Horizontal location:", self.hloc)
        form.addRow("Vertical location:", self.vloc)
        size = QtWidgets.QWidget()
        size.setWindowTitle("Size/Orientation")
        form = QtWidgets.QFormLayout(size)
        self.tex_width = QtWidgets.QDoubleSpinBox(size)
        self.tex_width.setObjectName("SWAppearanceWidth")
        self.tex_width.setRange(0.01, 100000.0)
        self.tex_width.setSuffix(" mm")
        form.addRow("Width:", self.tex_width)
        self.tex_height = QtWidgets.QDoubleSpinBox(size)
        self.tex_height.setObjectName("SWAppearanceHeight")
        self.tex_height.setRange(0.01, 100000.0)
        self.tex_height.setSuffix(" mm")
        form.addRow("Height:", self.tex_height)
        self.aspect = QtWidgets.QCheckBox("Fixed aspect ratio", size)
        self.aspect.setObjectName("SWAppearanceAspect")
        form.addRow(self.aspect)
        self.tex_angle = QtWidgets.QDoubleSpinBox(size)
        self.tex_angle.setObjectName("SWAppearanceAngle")
        self.tex_angle.setRange(-360.0, 360.0)
        self.tex_angle.setSuffix(" deg")
        form.addRow("Rotation:", self.tex_angle)
        self.mirror_h = QtWidgets.QCheckBox("Mirror horizontally", size)
        self.mirror_h.setObjectName("SWAppearanceMirrorH")
        self.mirror_v = QtWidgets.QCheckBox("Mirror vertically", size)
        self.mirror_v.setObjectName("SWAppearanceMirrorV")
        form.addRow(self.mirror_h)
        form.addRow(self.mirror_v)
        reset = QtWidgets.QPushButton("Reset to Default", size)
        reset.setObjectName("SWAppearanceMappingReset")
        reset.clicked.connect(self._reset_mapping)
        form.addRow(reset)
        # Surface Finish
        finish = QtWidgets.QWidget()
        finish.setWindowTitle("Surface Finish")
        form = QtWidgets.QFormLayout(finish)
        self.finish = QtWidgets.QComboBox(finish)
        self.finish.setObjectName("SWAppearanceFinish")
        self.finish.addItems(list(appeartex.FINISHES))
        form.addRow("Surface finish:", self.finish)
        row = QtWidgets.QHBoxLayout()
        self.bump_path = QtWidgets.QLineEdit(finish)
        self.bump_path.setObjectName("SWAppearanceBumpPath")
        self.bump_path.setPlaceholderText("Bump image (for Bumps)")
        row.addWidget(self.bump_path, 1)
        bump_browse = QtWidgets.QPushButton("Browse...", finish)
        bump_browse.setObjectName("SWAppearanceBumpBrowse")
        bump_browse.clicked.connect(self._browse_bump)
        row.addWidget(bump_browse)
        form.addRow(row)
        self.finish_scale = QtWidgets.QSpinBox(finish)
        self.finish_scale.setObjectName("SWAppearanceFinishScale")
        self.finish_scale.setRange(1, 1000)
        self.finish_scale.setSuffix(" %")
        form.addRow("Scale:", self.finish_scale)
        self.image_box, self.mapping_box, self.size_box, self.finish_box = image, mapping, size, finish
        self.advanced = [kind, image, mapping, size, light, finish]
        states = self._states_box()
        self.by_tab = {0: [geometry, kind, image, colour, states], 1: [geometry, mapping, size], 2: [geometry, light],
                       3: [geometry, finish]}
        self.form = [geometry, colour, states, kind, image, mapping, size, light, finish]
        self.start_maps = {o.Name: dict(stored(o)) for o in _owners(doc)}
        self._load()
        self._load_texture()
        for w in (self.image_path, self.bump_path):
            w.editingFinished.connect(self._texture_changed)
        for w in (self.mapping, self.direction, self.finish):
            w.currentIndexChanged.connect(lambda _i: self._texture_changed())
        for w in (self.hloc, self.vloc):
            w.valueChanged.connect(lambda _v: self._texture_changed())
        self.mapping.currentIndexChanged.connect(lambda _i: self._sync_handle())
        self.direction.currentIndexChanged.connect(lambda _i: self._sync_handle())
        self.tex_angle.valueChanged.connect(lambda _v: self._sync_handle())
        self.image_path.editingFinished.connect(self._sync_handle)
        for w in (self.tex_width, self.tex_height, self.tex_angle):
            # the box that changed goes along: the panel is no QObject, so it has no sender() (Fixed
            # aspect ratio never followed)
            w.valueChanged.connect(lambda _v, box=w: self._size_changed(box))
        for w in (self.aspect, self.mirror_h, self.mirror_v):
            w.toggled.connect(lambda _on: self._texture_changed())
        self.finish_scale.valueChanged.connect(lambda _v: self._texture_changed())
        self.tabs.currentChanged.connect(lambda i: self._mode())
        self.picker.currentColorChanged.connect(lambda c: self.changed())
        self.transparency.valueChanged.connect(lambda v: self.changed())
        for spin in self.light.values():
            spin.valueChanged.connect(lambda v: self._light_edited())
        self.preset.currentIndexChanged.connect(self._preset)
        self.mode.currentChanged.connect(lambda i: self._mode())
        self._mode()
        QtCore.QTimer.singleShot(0, self._mode)     # again once the task panel has made its boxes
        self._show()
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
            _fw_log("appearance.py:763", _fw_err)

    def _load(self):
        """Shows the first target's colour."""
        if not self.targets:
            return
        look = current_look(self.targets[0])
        r, g, b, t = look[:4]
        spins = list(self.light.values()) if hasattr(self, "light") else []
        for w in [self.picker, self.transparency] + spins:
            w.blockSignals(True)
        self.picker.setCurrentColor(QtGui.QColor.fromRgbF(r, g, b))
        self.transparency.setValue(int(round(t * 100)))
        for (name, _l, _d), value in zip(ILLUMINATION, look[4:]):
            if name in getattr(self, "light", {}):
                self.light[name].setValue(value)
        for w in [self.picker, self.transparency] + spins:
            w.blockSignals(False)
        if spins and len(look) > 4 and tuple(look[4:]) != DEFAULT_LIGHT:
            self.mode.setCurrentIndex(1)

    def _begin(self):
        if not self.opened:
            self.doc.openTransaction(TITLE)
            self.opened = True

    def rgbt(self):
        c = self.picker.currentColor()
        return with_light((c.redF(), c.greenF(), c.blueF(), self.transparency.value() / 100.0), self.lighting())

    def lighting(self):
        if not getattr(self, "light", None):
            return None
        return tuple(self.light[name].value() for name, _l, _d in ILLUMINATION)

    def _mode(self):
        """Basic shows Selected Geometry and Color; Advanced shows the boxes of the tab picked:
        Color/Image, Mapping, Illumination or Surface Finish."""
        advanced = self.mode.currentIndex() == 1
        self._place_swatches()

        self.tabs.setVisible(True)
        for i in range(1, self.tabs.count()):
            self.tabs.setTabVisible(i, advanced)
        if not advanced and self.tabs.currentIndex() != 0:
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(0)
            self.tabs.blockSignals(False)
        shown = self.by_tab.get(self.tabs.currentIndex(), []) if advanced else self.form[:3]
        for w in self.form:
            on = w in shown
            w.setVisible(on)
            box = w.parentWidget()
            # the task panel wraps each form widget in a box: show or hide that box too
            while box is not None and not box.inherits("Gui::TaskView::TaskBox"):
                box = box.parentWidget()
            if box is not None:
                box.setVisible(on)
        self._sync_handle()

    def _sync_handle(self):
        ""
        try:
            want = (self.mode.currentIndex() == 1 and self.tabs.currentIndex() == 1 and bool(self.image_path.text().strip())
                    and self.mapping.currentText() not in ("Spherical", "Cylindrical") and bool(self.targets))
            if not want:
                if getattr(self, "handle", None) is not None:
                    self.handle.remove()
                    self.handle = None
                return
            if getattr(self, "handle", None) is None:
                self.handle = MapHandle(self)
            self.handle.place()
        except Exception as _fw_err:
            _fw_log("appearance.py:handle", _fw_err)

    def _place_swatches(self):
        ""

        box = getattr(self, "swatches", None)
        slot = getattr(self.picker, "swatch_slot", None)
        if box is None or slot is None or slot.indexOf(box) >= 0:
            return
        try:
            old = box.parentWidget().layout() if box.parentWidget() is not None else None
            if old is not None:
                old.removeWidget(box)
            slot.addWidget(box)
            box.setTitle("")
            box.setFlat(True)
        except Exception as _fw_err:
            _fw_log("appearance.py:swatches", _fw_err)

    # --- image, mapping and surface finish (appeartex)
    def _texture_bodies(self):
        out = []
        for t in self.targets:
            for b in t.bodies():
                if b not in out:
                    out.append(b)
        return out

    def _load_texture(self):
        from . import appeartex
        bs = self._texture_bodies()
        t = self.targets[0] if self.targets else None
        if t is not None and t.level in ("face", "feature"):
            s = appeartex.settings_for(t.body, t.key())     # the face's or feature's own image
        else:
            s = appeartex.settings(bs[0]) if bs else dict(appeartex.DEFAULTS)
        widgets = (self.image_path, self.bump_path, self.mapping, self.direction, self.finish, self.tex_width,
                   self.tex_height, self.tex_angle, self.aspect, self.mirror_h, self.mirror_v, self.finish_scale,
                   self.hloc, self.vloc)
        for w in widgets:
            w.blockSignals(True)
        self.image_path.setText(s["image"])
        self.bump_path.setText(s["bump"])
        self.mapping.setCurrentText(s["mapping"])
        self.direction.setCurrentText(s["direction"])
        self.finish.setCurrentText(s["finish"])
        try:
            self.tex_width.setValue(float(s["width"]))
            self.tex_height.setValue(float(s["height"]))
            self.tex_angle.setValue(float(s["angle"]))
            self.finish_scale.setValue(int(float(s["finish_scale"])))
        except ValueError as _fw_err:
            _fw_log("appearance.py:842", _fw_err)
        self.mirror_h.setChecked(s["mirror_h"] == "1")
        self.mirror_v.setChecked(s["mirror_v"] == "1")
        try:
            self.hloc.setValue(float(s.get("hloc", "0")))
            self.vloc.setValue(float(s.get("vloc", "0")))
        except ValueError as _fw_err:
            _fw_log("appearance.py:location", _fw_err)
        for w in widgets:
            w.blockSignals(False)
        if advanced_wanted(s):
            self.mode.setCurrentIndex(1)

    def texture_values(self):
        return {"image": self.image_path.text().strip(), "bump": self.bump_path.text().strip(),
                "mapping": self.mapping.currentText(), "direction": self.direction.currentText(),
                "width": "%g" % self.tex_width.value(), "height": "%g" % self.tex_height.value(),
                "angle": "%g" % self.tex_angle.value(), "mirror_h": "1" if self.mirror_h.isChecked() else "0",
                "mirror_v": "1" if self.mirror_v.isChecked() else "0", "finish": self.finish.currentText(),
                "finish_scale": "%d" % self.finish_scale.value(),
                "hloc": "%g" % self.hloc.value(), "vloc": "%g" % self.vloc.value()}

    def _size_changed(self, box=None):
        if self.aspect.isChecked() and box in (self.tex_width, self.tex_height):
            other = self.tex_height if box is self.tex_width else self.tex_width
            other.blockSignals(True)
            other.setValue(box.value())
            other.blockSignals(False)
        self._texture_changed()

    def _texture_changed(self):
        from . import appeartex
        bs = self._texture_bodies()
        if not bs:
            return
        self._begin()
        values = self.texture_values()
        done = []
        for t in self.targets:
            if t.level in ("face", "feature"):

                appeartex.store_for(t.body, t.key(), values)
                if t.body not in done:
                    done.append(t.body)
                continue
            for b in t.bodies():
                appeartex.store(b, values)
                if b not in done:
                    done.append(b)
        for b in done:
            appeartex.apply(b)

    def _reset_mapping(self):
        from . import appeartex
        d = appeartex.DEFAULTS
        for w in (self.mapping, self.direction, self.tex_width, self.tex_height, self.tex_angle, self.mirror_h, self.mirror_v,
                  self.hloc, self.vloc):
            w.blockSignals(True)
        self.hloc.setValue(0.0)
        self.vloc.setValue(0.0)
        self.mapping.setCurrentText(d["mapping"])
        self.direction.setCurrentText(d["direction"])
        self.tex_width.setValue(float(d["width"]))
        self.tex_height.setValue(float(d["height"]))
        self.tex_angle.setValue(0.0)
        self.mirror_h.setChecked(False)
        self.mirror_v.setChecked(False)
        for w in (self.mapping, self.direction, self.tex_width, self.tex_height, self.tex_angle, self.mirror_h, self.mirror_v,
                  self.hloc, self.vloc):
            w.blockSignals(False)
        self._texture_changed()
        self._sync_handle()

    def _browse_image(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(None, "Open Image", self.image_path.text(),
                                                         "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)")
        if path:
            self.image_path.setText(path)
            self._texture_changed()

    def _browse_bump(self):
        path, _f = QtWidgets.QFileDialog.getOpenFileName(None, "Open Bump Image", self.bump_path.text(),
                                                         "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*)")
        if path:
            self.bump_path.setText(path)
            if self.finish.currentText() != "Bumps":
                self.finish.setCurrentText("Bumps")
            self._texture_changed()

    def _preset(self, index):
        if index <= 0:
            return
        values = PRESETS[index - 1][1]
        for spin in self.light.values():
            spin.blockSignals(True)
        for (name, _l, _d), v in zip(ILLUMINATION, values):
            self.light[name].setValue(v)
        for spin in self.light.values():
            spin.blockSignals(False)
        if PRESETS[index - 1][0].startswith("Glass") and self.transparency.value() < 50:
            self.transparency.setValue(80)     # changed() runs from the slider
        else:
            self.changed()

    def _light_edited(self):
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(0)
        self.preset.blockSignals(False)
        self.changed()

    def changed(self):
        if not self.targets:
            return
        self._begin()
        apply(self.targets, self.rgbt())

    def remove(self):
        if not self.targets:
            return
        self._begin()
        remove(self.targets)
        self._load()

    def set_level(self, level):
        self.level = level
        picks = [getattr(t, "pick", None) or (t.obj or t.body, t.sub) for t in self.targets]
        self.targets = []
        for obj, sub in picks:
            self._add(obj, sub)
        if level == "part" and not self.targets:
            bs = bodies(self.doc)
            if bs:
                self.targets = [Target("part", bs[0])]
        self._load()
        self._load_texture()        # a face's or feature's own image differs from the body's
        self._show()

    # --- picks
    def addSelection(self, doc, name, sub, pnt):
        if doc != self.doc.Name:
            return
        obj = self.doc.getObject(name)
        if obj is None:
            return
        from . import refplane
        obj, sub = refplane.resolve(obj, sub)
        from . import safe_later as _sl; _sl.later(0, lambda: self._picked(obj, sub), self, "list")

    def _picked(self, obj, sub):
        try:
            import shiboken6
            if not shiboken6.isValid(self.list):
                return          # the panel is closed: this call was queued before it (lifetime2-1126)
        except Exception:
            pass
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("appearance.py:971", _fw_err)
        self._add(obj, sub)
        self._load()
        self._show()

    def _add(self, obj, sub):
        t = target_for(self.level, obj, sub)
        if t is None:
            return
        for i, old in enumerate(self.targets):
            if old.same(t):
                del self.targets[i]         # a second pick takes it out
                return
        self.targets.append(t)

    def _show(self):
        try:
            import shiboken6
            if not shiboken6.isValid(self.list):
                return          # the panel is closed: this call was queued before it (lifetime2-1126)
        except Exception:
            pass
        for lv, b in self.level_buttons.items():
            b.setChecked(lv == self.level)
        self.list.clear()
        for t in self.targets:
            self.list.addItem(t.name())
        self.remove_button.setEnabled(any(t.key() in stored(b) for t in self.targets for b in t.bodies()))

    # --- check and cross
    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def _close(self):
        global _current
        _current = None
        if getattr(self, "handle", None) is not None:
            self.handle.remove()
            self.handle = None
        for w in self._views:
            try:
                w.removeEventFilter(self._esc)
            except Exception as _fw_err:
                _fw_log("appearance.py:1005", _fw_err)
        self._views = []
        try:
            Gui.Selection.removeObserver(self)
        except Exception as _fw_err:
            _fw_log("appearance.py:1010", _fw_err)
        Gui.Control.closeDialog()


    def _states_box(self):
        box = QtWidgets.QWidget()
        box.setWindowTitle("Display States")
        box.setObjectName("SWAppearanceStates")
        lay = QtWidgets.QVBoxLayout(box)
        self.state_choice = QtWidgets.QButtonGroup(box)
        for i, text in enumerate(("This display state", "All display states", "Specify display states")):
            r = QtWidgets.QRadioButton(text, box)
            r.setObjectName("SWAppearanceStates%d" % i)
            r.setChecked(i == 0)
            self.state_choice.addButton(r, i)
            lay.addWidget(r)
        self.state_list = QtWidgets.QListWidget(box)
        self.state_list.setObjectName("SWAppearanceStateList")
        self.state_list.setFixedHeight(60)
        try:
            from . import displaystates
            names = displaystates.names(self.doc) or [displaystates.default_name(self.doc)]
            here = displaystates.active(self.doc) or names[0]
        except Exception as _fw_err:
            _fw_log("appearance.py:states", _fw_err)
            names, here = [], None
        for name in names:
            item = QtWidgets.QListWidgetItem(name, self.state_list)
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if name == here else QtCore.Qt.Unchecked)
        lay.addWidget(self.state_list)
        self.state_choice.idClicked.connect(lambda i: self.state_list.setEnabled(i == 2))
        self.state_list.setEnabled(False)
        return box

    def chosen_states(self):
        """The display states (other than the active one) this appearance also goes to."""
        try:
            from . import displaystates
            names, here = displaystates.names(self.doc), displaystates.active(self.doc)
        except Exception:
            return []
        how = self.state_choice.checkedId()
        if how == 1:
            return [n for n in names if n != here]
        if how == 2:
            out = []
            for i in range(self.state_list.count()):
                item = self.state_list.item(i)
                if item.checkState() == QtCore.Qt.Checked and item.text() != here and item.text() in names:
                    out.append(item.text())
            return out
        return []

    def _spread(self):
        """The appearance changes made on this page go to the chosen display states too: each keeps its other
        appearances, only what was set or removed here changes."""
        names = self.chosen_states()
        if not names:
            return
        from . import displaystates
        data = displaystates._data(self.doc)
        states = data.get("states", {})
        for owner in _owners(self.doc):
            before, after = self.start_maps.get(owner.Name, {}), stored(owner)
            changed = {k: v for k, v in after.items() if before.get(k) != v}
            gone = [k for k in before if k not in after]
            if not changed and not gone:
                continue
            for name in names:
                item = states.get(name, {}).get(owner.Name)
                if item is None:
                    continue
                if "sw" in item:
                    kept = dict(item["sw"] or {})
                    kept.update(changed)
                    for k in gone:
                        kept.pop(k, None)
                    item["sw"] = kept
                elif "a" in item:
                    try:
                        item["a"] = [list(m.DiffuseColor[:3]) + [float(m.Transparency)]
                                     for m in owner.ViewObject.ShapeAppearance]
                    except Exception as _fw_err:
                        _fw_log("appearance.py:spread", _fw_err)
        displaystates._save(self.doc, data)

    def accept(self):
        try:
            self._spread()
        except Exception as _fw_err:
            _fw_log("appearance.py:spread-all", _fw_err)
        if self.opened:
            self.doc.commitTransaction()
        self._close()
        return True

    def reject(self):
        if self.opened:
            self.doc.abortTransaction()
            for b in bodies(self.doc):
                paint(b)
            try:
                from . import appeartex
                for b in bodies(self.doc):
                    appeartex.apply(b)
            except Exception as _fw_err:
                _fw_log("appearance.py:1029", _fw_err)
        self._close()
        return True


# --------------------------------------------------------------------------- the command
def advanced_wanted(texture_settings):
    """Advanced opens by itself when the appearance has an image, a mapping or a finish set."""
    s = texture_settings
    return bool(s.get("image")) or s.get("finish", "None") != "None" or s.get("mapping", "Automatic") != "Automatic"


def _swatch(rgbt):
    pix = QtGui.QPixmap(14, 14)
    r, g, b, _t = rgbt
    pix.fill(QtGui.QColor.fromRgbF(r, g, b))
    return QtGui.QIcon(pix)


def open_page(doc, level, picks):
    targets = []
    for obj, sub in picks:
        t = target_for(level, obj, sub)
        if t is not None and not any(t.same(o) for o in targets):
            targets.append(t)
    if not targets:
        bs = bodies(doc)
        if not bs:
            return False
        targets = [Target("part", bs[0])]
        level = "part"
    QtCore.QTimer.singleShot(0, lambda: _show_page(doc, level, targets))
    return True


def _show_page(doc, level, targets):
    ""

    Gui.Control.showDialog(AppearancePanel(doc, level, targets))
    try:
        from . import taskpane
        taskpane.open_tab(4)
    except Exception as _fw_err:
        _fw_log("appearance.py:taskpane", _fw_err)


_menu = None


def menu_for(doc, picks):
    ""
    global _menu
    obj, sub = picks[0]
    levels = ["face", "feature", "body", "part"] if sub.startswith("Face") else \
        (["feature", "body", "part"] if _solid_feature(obj) else ["body", "part"])
    menu = QtWidgets.QMenu(Gui.getMainWindow())
    menu.setObjectName("SWAppearanceMenu")
    for depth, level in enumerate(levels):
        t = target_for(level, obj, sub)
        if t is None:
            continue

        # (Face<1>@Chamfer1, Chamfer1, the body, Part2); a row with an appearance of its own shows it
        label = menu_label(t)
        if is_component(t.body):
            label = "Component (%s)" % t.name()
        icon = _swatch(current_colour(t)) if has_own(t) else QtGui.QIcon()
        action = menu.addAction(icon, "   " * depth + label)
        action.setObjectName("SWAppearance_" + level)
        action.setToolTip("Edit the appearance of %s" % label)
        action.triggered.connect(lambda _c=False, lv=level: open_page(doc, lv, picks))

    removable = [(level, t) for level, t in ((lv, target_for(lv, obj, sub)) for lv in levels)
                 if t is not None and has_own(t)]
    menu.addSeparator()
    flyout = menu.addMenu("Remove Appearance")
    flyout.setObjectName("SWAppearanceRemove")
    flyout.setEnabled(bool(removable))
    for level, t in removable:
        label = {"face": "Face", "feature": "Feature (%s)", "body": "Body (%s)", "part": "Part (%s)"}[level]
        if "%s" in label:
            label = label % t.name()
        act = flyout.addAction(_swatch(current_colour(t)), label)
        act.setObjectName("SWAppearanceRemove_" + level)
        act.triggered.connect(lambda _c=False, tt=t: remove_with_undo(doc, [tt]))
    if len(removable) > 1:
        flyout.addSeparator()
        act = flyout.addAction("All")
        act.setObjectName("SWAppearanceRemove_all")
        act.triggered.connect(lambda _c=False, tt=[t for _l, t in removable]: remove_with_undo(doc, tt))

    act_all = menu.addAction("Remove All Part Appearances")
    act_all.setObjectName("SWAppearanceRemoveAllPart")
    act_all.setEnabled(any(stored(b) for b in bodies(doc)) or any("part" in stored(o) for o in loose_features(doc)))
    act_all.triggered.connect(lambda _c=False: remove_all(doc))
    _menu = menu
    return menu


def menu_label(t):
    ""
    if t.level == "face":
        return "Face<1>@%s" % t.obj.Label
    if t.level == "feature":
        return t.obj.Label
    return t.name()


def remove_all(doc):
    """Remove All Part Appearances: every face, feature, body and part appearance of the part, one Undo step."""
    doc.openTransaction("Remove All Part Appearances")
    try:
        for b in bodies(doc):
            if stored(b):
                store(b, {})
                _paint(b)
        for obj in loose_features(doc):
            values = stored(obj)
            if "part" in values:
                del values["part"]
                store(obj, values)
                paint_loose(obj)
    finally:
        doc.commitTransaction()
    try:
        from . import displaymanager
        displaymanager.refresh_all()
    except Exception as _fw_err:
        _fw_log("appearance.py:1146", _fw_err)


def has_own(target):
    """The target carries an appearance of its own (not one it inherits)."""
    try:
        return target.key() in stored(target.body)
    except Exception as _fw_err:
        _fw_log("appearance.py:1162", _fw_err)
        return False


def remove_with_undo(doc, targets):
    doc.openTransaction("Remove Appearance")
    try:
        remove(targets)
    finally:
        doc.commitTransaction()
    try:
        from . import displaymanager
        displaymanager.refresh_all()
    except Exception as _fw_err:
        _fw_log("appearance.py:1167", _fw_err)


class AppearanceCommand:
    def GetResources(self):
        return {"Pixmap": "Std_SetAppearance", "MenuText": "Edit Appearance",
                "ToolTip": "Colors the picked face, feature or body, or the part"}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        from . import refplane
        picks = []
        for entry in Gui.Selection.getSelectionEx(doc.Name):
            for sub in (entry.SubElementNames or ("",)):
                obj, s = refplane.resolve(entry.Object, sub)
                if body_of(obj) is not None or (not bodies(doc) and _loose(entry.Object)):
                    picks.append((obj if body_of(obj) is not None else entry.Object, s))
        if not bodies(doc):
            if picks:
                menu_for(doc, picks).popup(QtGui.QCursor.pos())
            else:
                Gui.runCommand("Std_SetAppearance", 0)
            return
        if not picks:
            open_page(doc, "part", [])
            return
        menu_for(doc, picks).popup(QtGui.QCursor.pos())


def natural(obj, sub):
    """The level a pick names by itself: a face, a feature, a body."""
    if is_component(obj):
        return "part"
    if sub.startswith("Face"):
        return "face"
    if obj.TypeId == "PartDesign::Body":
        return "body"
    if own_body(obj):
        return "body"
    return "feature" if _solid_feature(obj) else None


def _picks(doc):
    from . import refplane
    out = []
    for entry in Gui.Selection.getSelectionEx(doc.Name):
        for sub in (entry.SubElementNames or ("",)):
            obj, s = refplane.resolve(entry.Object, sub)
            if body_of(obj) is not None and natural(obj, s):
                out.append((obj, s))
            elif is_component(entry.Object):
                out.append((entry.Object, ""))
    return out


_clipboard = None


class Clip:
    """A copied appearance: the look (colour, transparency and illumination values) and the image
    settings (image, mapping, finish), None when it had none of its own."""

    def __init__(self, look, texture):
        self.look, self.texture = tuple(look), (dict(texture) if texture else None)


def _texture_of(t):
    """The target's image, mapping and finish when they show on it (its own, or its body's), else None."""
    try:
        from . import appeartex
        s = appeartex.settings_for(t.body, t.key())
        if t.level in ("face", "feature") and not appeartex.keyed(t.body).get(t.key()):
            s = appeartex.settings(t.body)          # nothing of its own: the body's image shows on it
        return dict(s) if appeartex._on(s) else None
    except Exception as _fw_err:
        _fw_log("appearance.py:copy-texture", _fw_err)
        return None


def _paste_texture(targets, texture):
    """Gives each pasted target the copied image settings, or takes its own away when the copy had none."""
    try:
        from . import appeartex
    except Exception as _fw_err:
        _fw_log("appearance.py:paste-texture", _fw_err)
        return
    done = []
    for t in targets:
        for b in t.bodies():
            if texture is None and not (t.level in ("face", "feature") and t.key() in appeartex.keyed(b)):
                continue            # nothing to give and nothing of its own to take away
            appeartex.store_for(b, t.key(), texture or {})
            if b not in done:
                done.append(b)
    for b in done:
        appeartex.apply(b)


class CopyAppearanceCommand:
    """Copy Appearance: keeps the picked face's, feature's or body's colour to paste."""

    def GetResources(self):
        return {"Pixmap": "edit-copy", "MenuText": "Copy Appearance",
                "ToolTip": "Copies the appearance of the picked face, feature or body"}

    def IsActive(self):
        return App.ActiveDocument is not None and bool(_picks(App.ActiveDocument))

    def Activated(self):
        global _clipboard
        obj, sub = _picks(App.ActiveDocument)[0]
        t = target_for(natural(obj, sub), obj, sub)
        if t is not None:

            # and finish (only the colour was kept)
            _clipboard = Clip(current_colour(t, True), _texture_of(t))


class PasteAppearanceCommand:
    """Paste Appearance: gives the copied colour to each picked face, feature or body."""

    def GetResources(self):
        return {"Pixmap": "edit-paste", "MenuText": "Paste Appearance",
                "ToolTip": "Pastes the copied appearance onto the picked faces, features or bodies"}

    def IsActive(self):
        return _clipboard is not None and App.ActiveDocument is not None and bool(_picks(App.ActiveDocument)) \
            and not Gui.Control.activeDialog()

    def Activated(self):
        doc = App.ActiveDocument
        targets = []
        for obj, sub in _picks(doc):
            t = target_for(natural(obj, sub), obj, sub)
            if t is not None and not any(t.same(o) for o in targets):
                targets.append(t)
        if not targets:
            return
        doc.openTransaction("Paste Appearance")
        try:
            clip = _clipboard if isinstance(_clipboard, Clip) else Clip(_clipboard, None)
            apply(targets, clip.look)
            _paste_texture(targets, clip.texture)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()


COMMAND = "SWStyle_Appearance"
COMMANDS = {COMMAND: AppearanceCommand, "SWStyle_CopyAppearance": CopyAppearanceCommand,
            "SWStyle_PasteAppearance": PasteAppearanceCommand}
_observer = None


def register():
    global _observer
    try:
        for name, cls in COMMANDS.items():
            if name not in Gui.listCommands():
                Gui.addCommand(name, cls())
        if _observer is None:
            _observer = _Observer()
            App.addDocumentObserver(_observer)
            try:        # an opened file: the image, mapping and finish are drawn again (only their settings are saved)
                from . import appeartex, restorehook
                restorehook.on_restored(appeartex.refresh_document, delay=300)
            except Exception as _fw_err:
                _fw_log("appearance.py:restorehook", _fw_err)
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
