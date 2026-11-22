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
    if obj is None or not enabled() or not _hidden(obj):
        return
    lines = outline(obj)
    if not lines:
        return
    try:
        from pivy import coin
        view = Gui.getDocument(obj.Document.Name).ActiveView
        root = coin.SoSeparator()
        root.addChild(coin.SoAnnotation())
        colour = coin.SoBaseColor()
        colour.rgb = _colour()
        style = coin.SoDrawStyle()
        style.lineWidth = WIDTH
        points = coin.SoCoordinate3()
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
