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

from . import paths

PARAM = "TreeHoverOutline"     # addon parameter (default on)
VIEW = "User parameter:BaseApp/Preferences/View"
WIDTH = 2.0
STEP = 24                      # points along one round edge
KINDS = ("App::Plane", "PartDesign::Plane", "PartDesign::Line", "Sketcher::SketchObject",
         "Part::Part2DObjectPython", "PartDesign::ShapeBinder", "PartDesign::SubShapeBinder")

_drawn = {"root": None, "view": None, "name": None}
_faces = {}                    # (doc, feature, its tip and shape stamps) -> outline of its faces
MAX_FACES = 400                # a bigger model: no feature outline (a hover must stay instant)


def _inner_point(face):
    """A point inside a face (not on its edge), or None."""
    try:
        u0, u1, v0, v1 = face.ParameterRange
        for fu, fv in ((0.5, 0.5), (0.3, 0.3), (0.7, 0.7), (0.3, 0.7), (0.7, 0.3), (0.5, 0.2), (0.5, 0.8),
                       (0.2, 0.5), (0.8, 0.5), (0.15, 0.15), (0.85, 0.85)):
            p = face.Surface.value(u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv)
            if face.isInside(p, 1e-6, True):
                return p
    except Exception as _fw_err:
        _fw_log("treehover.py:inner", _fw_err)
    return None


def _on(point, faces):
    import Part
    vertex = Part.Vertex(point)
    for f in faces:
        try:
            box = f.BoundBox
            box.enlarge(1e-4)
            if not box.isInside(point):
                continue            # far off: no distance to work out
            if f.distToShape(vertex)[0] < 1e-5:
                return True
        except Exception:
            continue
    return False


def _solid_feature(obj):
    try:
        return obj.isDerivedFrom("PartDesign::Feature") and obj.Shape.Solids and obj.getParentGeoFeatureGroup() is not None
    except Exception:
        return False


def feature_faces(obj):
    ""


    body = obj.getParentGeoFeatureGroup()
    tip = getattr(body, "Shape", None)
    if tip is None or tip.isNull() or len(tip.Faces) > MAX_FACES or len(obj.Shape.Faces) > MAX_FACES:
        return []
    base = getattr(obj, "BaseFeature", None)
    old = base.Shape.Faces if base is not None and not base.Shape.isNull() else []
    made = []
    for f in obj.Shape.Faces:
        p = _inner_point(f)
        if p is not None and not (old and _on(p, old)):
            made.append(f)
    if not made:
        return []
    if tip.isPartner(obj.Shape) or tip.isSame(obj.Shape):
        return made
    out = []
    for f in tip.Faces:                 # later features may have cut or rounded them: what is left of them
        p = _inner_point(f)
        if p is not None and _on(p, made):
            out.append(f)
    return out


def _feature_lines(obj):
    body = obj.getParentGeoFeatureGroup()
    tip, own = body.Shape, obj.Shape
    key = (obj.Document.Name, obj.Name, len(tip.Faces), round(tip.Area, 6), len(own.Faces), round(own.Area, 6),
           tuple(round(v, 6) for v in body.getGlobalPlacement().Base))
    if key in _faces:
        return _faces[key]
    lines, seen = [], []
    for face in feature_faces(obj):
        for edge in face.Edges:
            if any(edge.isSame(e) for e in seen):
                continue
            seen.append(edge)
            try:
                straight = type(edge.Curve).__name__ in ("Line", "LineSegment")
                pts = edge.discretize(2 if straight else STEP)
            except Exception:
                continue
            m = body.getGlobalPlacement().toMatrix()
            lines.append([m.multVec(p) for p in pts])
    if len(_faces) > 20:
        _faces.clear()
    _faces[key] = lines
    return lines


def _origin_lines(origin):
    ""
    from . import planes
    lines = []
    size = 10.0
    for feat in getattr(origin, "OriginFeatures", []) or []:
        if feat.TypeId == "App::Plane":
            try:
                c = planes.corners(feat)
                lines.append(c + [c[0]])
                size = max(size, max((c[0] - c[2]).Length / 2.0, 1.0))
            except Exception as _fw_err:
                _fw_log("treehover.py:origin-plane", _fw_err)
    for feat in getattr(origin, "OriginFeatures", []) or []:
        if feat.TypeId == "App::Line":
            try:
                pl = feat.getGlobalPlacement()
                d = pl.Rotation.multVec(App.Vector(1, 0, 0))
                lines.append([pl.Base - d * size * 0.7, pl.Base + d * size * 0.7])
            except Exception as _fw_err:
                _fw_log("treehover.py:origin-axis", _fw_err)
    return lines


def enabled():
    return paths.params().GetBool(PARAM, True)


def _colour():
    try:
        from . import optionspages              # optioncolors-1119: Options > Colors > Highlight, as set
        own = optionspages.kept_color("Highlight")
        if own is not None:
            return own
    except Exception as _fw_err:
        _fw_log("treehover.py:highlight", _fw_err)
    packed = App.ParamGet(VIEW).GetUnsigned("HighlightColor", 0xFF8C00FF)
    return ((packed >> 24) & 255) / 255.0, ((packed >> 16) & 255) / 255.0, ((packed >> 8) & 255) / 255.0


def _hidden(obj):
    try:
        if obj.TypeId == "App::Plane":
            from . import planes
            return not planes.drawn_by_freecad(obj)     # the origin's planes hide with the origin
        return not obj.ViewObject.Visibility
    except Exception:
        return False


def outline(obj):
    """The polylines (lists of model-space points) that outline `obj`, or [] when there is nothing
    to draw for it."""
    if obj is None or obj.TypeId not in KINDS:
        return []
    if obj.TypeId in ("App::Plane", "PartDesign::Plane"):
        from . import planes        # sized to the part, as the picked planes
        c = planes.corners(obj)
        return [c + [c[0]]]
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        return []
    shape = shape.copy()
    try:
        group = obj.getParentGeoFeatureGroup()
        if group is not None:
            shape.transformShape(group.getGlobalPlacement().toMatrix())
    except Exception as _fw_err:
        _fw_log("treehover.py:76", _fw_err)
    lines = []
    for edge in shape.Edges:
        try:
            straight = type(edge.Curve).__name__ in ("Line", "LineSegment")
            lines.append(edge.discretize(2 if straight else STEP))
        except Exception:
            continue
    return lines


def hover(obj):
    ""
    name = (obj.Document.Name, obj.Name) if obj is not None else None
    if name == _drawn["name"]:
        return
    clear()
    if obj is None or not enabled():
        return

    # planes and axes from the Origin row; FreeCAD's preselection of a feature under its body draws nothing
    lines, deep = [], False
    try:
        if obj.TypeId == "App::Origin":
            lines = _origin_lines(obj)
        elif _solid_feature(obj):
            lines, deep = _feature_lines(obj), True
    except Exception as _fw_err:
        _fw_log("treehover.py:feature", _fw_err)
    if not lines:
        if not _hidden(obj):
            return
        lines = outline(obj)
    if not lines:
        return
    try:
        from pivy import coin
        view = Gui.getDocument(obj.Document.Name).ActiveView
        root = coin.SoSeparator()
        if deep:
            # the feature's edges where they show (hidden ones stay hidden), drawn over the model's own
            try:
                depth = coin.SoDepthBuffer()
                depth.function = coin.SoDepthBuffer.LEQUAL
                root.addChild(depth)
            except Exception as _fw_err:
                _fw_log("treehover.py:depth", _fw_err)
        else:
            root.addChild(coin.SoAnnotation())
        colour = coin.SoBaseColor()
        colour.rgb = _colour()
        style = coin.SoDrawStyle()
        style.lineWidth = WIDTH
        points = coin.SoCoordinate3()
        if deep:
            # a hair towards the viewer, so the lines lie on the model's own edges without breaking up
            try:
                d = App.Vector(*view.getViewDirection())
                box = obj.getParentGeoFeatureGroup().Shape.BoundBox
                shift = d * (-max(box.DiagonalLength, 1.0) * 0.002)
                lines = [[App.Vector(p) + shift for p in line] for line in lines]
            except Exception as _fw_err:
                _fw_log("treehover.py:shift", _fw_err)
            style.lineWidth = WIDTH + 1.0
        flat = [tuple(p) for line in lines for p in line]
        points.point.setValues(0, len(flat), flat)
        sets = coin.SoLineSet()
        sets.numVertices.setValues(0, len(lines), [len(line) for line in lines])
        for node in (colour, style, points, sets):
            root.addChild(node)
        view.getSceneGraph().addChild(root)
        _drawn.update(root=root, view=view, name=name)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: tree hover outline not drawn: %s\n" % error)


def clear():
    root, view = _drawn["root"], _drawn["view"]
    if root is not None:
        try:
            view.getSceneGraph().removeChild(root)
        except Exception as _fw_err:
            _fw_log("treehover.py:126", _fw_err)
    _drawn.update(root=None, view=None, name=None)


def drawn():
    """The (document, object) name drawn now, for checks."""
    return _drawn["name"]
