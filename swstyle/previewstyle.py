# SPDX-License-Identifier: LGPL-2.1-or-later
""










from . import editobj

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
from PySide import QtCore

try:
    from pivy import coin
except ImportError:     # no Coin bindings: the colours still apply
    coin = None

USER_PARAMETERS = "User parameter:BaseApp/Preferences/Themes/UserParameters"
OURS = "User parameter:BaseApp/Preferences/Mod/FreeWorks/PreviewStyle"
STYLE = {
    "PreviewAdditiveColor": "#f2ec8a",
    "PreviewShapeOpacity": "0.5",
    "PreviewLineWidth": "1",
    "LinearGizmoBaseColor": "#8a8a8a",
    "LinearGizmoActiveColor": "#f5c800",
    "RotationGizmoBaseColor": "#8a8a8a",
    "RotationGizmoActiveColor": "#f5c800",
}
SKETCH_BLUE = (0.30, 0.65, 1.0)
SKETCH_FEATURES = {"PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove"}


def style_parameters():
    ""
    user = App.ParamGet(USER_PARAMETERS)
    ours = App.ParamGet(OURS)
    for name, value in STYLE.items():
        current = user.GetString(name, "")
        if current and current != ours.GetString(name, ""):
            continue    # a value of the person's own
        user.SetString(name, value)
        ours.SetString(name, value)


def _late_node():
    """FreeCAD's own So3DAnnotation: drawn in the pass after everything, where FreeCAD 1.1 draws its
    preview; added after the preview it is drawn over it. A plain SoAnnotation otherwise."""
    try:
        node = coin.SoType.fromName(coin.SbName("So3DAnnotation")).createInstance()
        if node is not None:
            node = coin.cast(node, "SoSeparator")
            if node is not None:
                return node
    except Exception as _fw_err:
        _fw_log("previewstyle.py:71", _fw_err)
    return coin.SoAnnotation()


def _overlay(sketch, feature):
    """The sketch's lines in blue with square end points, drawn over everything (SoAnnotation).

    It hangs under the feature's own node (drawn after its preview, which FreeCAD draws late), so
    it is given in the feature's coordinates."""
    shape = sketch.Shape.copy()
    if shape.isNull() or not shape.Edges:
        return None
    try:
        place = feature.getGlobalPlacement()
    except Exception:
        place = feature.Placement
    shape.transformShape(place.inverse().toMatrix())
    root = _late_node()
    root.setName("FreeWorksSketchOnTop")
    style = coin.SoDrawStyle()
    style.lineWidth = 2
    style.pointSize = 7
    colour = coin.SoBaseColor()
    colour.rgb = SKETCH_BLUE
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    depth = coin.SoDepthBuffer()
    depth.test = False      # over the see-through preview, which is drawn late too
    root.addChild(light)
    root.addChild(depth)
    root.addChild(style)
    root.addChild(colour)
    points, counts = [], []
    for edge in shape.Edges:
        run = edge.discretize(Deflection=0.05) if edge.Curve.TypeId != "Part::GeomLine" else [
            edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
        points += [(p.x, p.y, p.z) for p in run]
        counts.append(len(run))
    coords = coin.SoCoordinate3()
    coords.point.setValues(0, len(points), points)
    lines = coin.SoLineSet()
    lines.numVertices.setValues(0, len(counts), counts)
    root.addChild(coords)
    root.addChild(lines)
    corners = [(v.Point.x, v.Point.y, v.Point.z) for v in shape.Vertexes]
    if corners:
        marks = coin.SoSeparator()
        where = coin.SoCoordinate3()
        where.point.setValues(0, len(corners), corners)
        marker = coin.SoMarkerSet()
        marker.markerIndex = coin.SoMarkerSet.SQUARE_LINE_7_7
        marks.addChild(where)
        marks.addChild(marker)
        root.addChild(marks)
    return root


class _SketchOnTop:
    def __init__(self):
        self.shown = {}     # (document, feature name) -> (scene graph, overlay node)

    def slotInEdit(self, view_provider):
        try:
            feature = view_provider.Object
        except Exception:
            return
        if coin is None or feature.TypeId not in SKETCH_FEATURES:
            return
        profile = getattr(feature, "Profile", None)
        sketch = profile[0] if isinstance(profile, tuple) else profile
        if sketch is None or sketch.TypeId != "Sketcher::SketchObject":
            return
        key = (feature.Document.Name, feature.Name)
        # After FreeCAD has opened the panel and drawn the preview
        QtCore.QTimer.singleShot(300, lambda: self._show(key, sketch.Name))

    def _show(self, key, sketch_name):
        doc = App.listDocuments().get(key[0])
        gdoc = Gui.getDocument(key[0]) if doc is not None else None
        sketch = doc.getObject(sketch_name) if doc is not None else None
        try:
            edit = gdoc.getInEdit()
            if sketch is None or edit is None or getattr(editobj.of(edit), "Name", None) != key[1]:
                return
            node = _overlay(sketch, editobj.of(edit))
            if node is None:
                return
            # Inside the feature's own node, after its preview, so it is drawn last
            graph = editobj.of(edit).ViewObject.RootNode
            graph.addChild(node)
            self.shown[key] = (graph, node)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: could not draw the sketch over the preview (%s)\n" % error)

    def slotResetEdit(self, view_provider):
        try:
            feature = view_provider.Object
            key = (feature.Document.Name, feature.Name)
        except Exception:
            return
        entry = self.shown.pop(key, None)
        if entry is not None:
            try:
                entry[0].removeChild(entry[1])
            except Exception as _fw_err:
                _fw_log("previewstyle.py:176", _fw_err)


_observer = None


def install():
    """Safe to call more than once."""
    global _observer
    if _observer is None:
        style_parameters()
        _observer = _SketchOnTop()
        Gui.addDocumentObserver(_observer)
