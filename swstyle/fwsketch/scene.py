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

VIEW_GROUP = "User parameter:BaseApp/Preferences/View"   # FreeCAD keeps the Sketcher colours here, the add-on writes ours here too

DEFAULT_COLORS = {"SnapGuideCandidateColor": (0.90, 0.93, 0.63), "SnapGuideRelationColor": (0.41, 0.37, 0.89),
                  "SnapGuideSnapColor": (0.41, 0.37, 0.89), "CursorTextColor": (0.0, 0.0, 1.0),
                  "PreselectColor": (1.0, 0.55, 0.0), "CreateLineColor": (1.0, 1.0, 1.0),
                  "ConstructionColor": (0.0, 0.0, 0.86),

                  # preselection (tester, Beginners 1 on the dark background)
                  "SnapPointColor": (1.0, 0.55, 0.0)}

# dotted, the relation in use a SOLID blue line, an alignment that only places the point dotted blue.
CANDIDATE_PATTERN, LOCKED_PATTERN, SNAP_PATTERN = 0x9249, 0xFFFF, 0xAAAA

QUADRANT_COLOR = (1.0, 0.92, 0.16)
CONSTRUCTION_PATTERN = 0xFFCC  # dash-dot, as the look sets for construction lines

CONFLICT_COLOR = (0xD6 / 255.0, 0xE4 / 255.0, 0x0C / 255.0)


def _packed(name, default):
    """(r, g, b) 0-1 of View/<name> (0xRRGGBBAA), or default when unset."""
    try:
        packed = App.ParamGet(VIEW_GROUP).GetUnsigned(name, 0)
    except Exception:
        packed = 0
    if not packed:
        return default
    return ((packed >> 24) & 0xFF) / 255.0, ((packed >> 16) & 0xFF) / 255.0, ((packed >> 8) & 0xFF) / 255.0


def conflict_color():
    ""
    return _packed("OverDefinedColor", CONFLICT_COLOR)


def unsolvable_color():
    ""
    return _packed("UnsolvableColor", UNSOLVABLE_COLOR)


def ghost_color():
    """View/DragGhostColor (0xRRGGBBAA, package 35) as (r, g, b) 0-1; light grey when unset."""
    try:
        packed = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned("DragGhostColor", 0x9E9E9EFF)
    except Exception:
        packed = 0x9E9E9EFF
    return ((packed >> 24) & 0xFF) / 255.0, ((packed >> 16) & 0xFF) / 255.0, ((packed >> 8) & 0xFF) / 255.0
UNSOLVABLE_COLOR = (0xEB / 255.0, 0.0, 0x08 / 255.0)

DANGLING_COLOR = (0x9C / 255.0, 0x5A / 255.0, 0x1E / 255.0)


def dangling_color():
    ""
    return _packed("DanglingColor", DANGLING_COLOR)


def color(name):
    """(r, g, b) of a Sketcher view colour parameter (packed 0xRRGGBBAA), or the default."""
    try:
        packed = App.ParamGet(VIEW_GROUP).GetUnsigned(name, 0)
    except Exception:
        packed = 0
    if packed:
        return ((packed >> 24) & 0xFF) / 255.0, ((packed >> 16) & 0xFF) / 255.0, ((packed >> 8) & 0xFF) / 255.0
    return DEFAULT_COLORS[name]


def _marker(kind, size, ratio=1.0):
    ""

    from pivy import coin
    fixed = getattr(coin.SoMarkerSet, "%s_%d_%d" % (kind, size, size))
    try:
        ratio = float(ratio or 1.0)
    except Exception:
        ratio = 1.0
    if ratio <= 1.05:
        return fixed
    px = int(size * ratio + 1e-6)
    px += 0 if px % 2 else 1            # odd sizes keep the dot on the point: 9 -> 13 at 150 %, 19 at 200 %
    try:
        import FreeCADGui as Gui
        return Gui.getMarkerIndex(kind, px)
    except Exception:
        return fixed


def readout_font(ratio=1.0):
    """(family, size in device pixels) of the readout beside the pointer: the UI font."""
    try:
        from PySide import QtGui, QtWidgets
        font = QtWidgets.QApplication.font()
        px = QtGui.QFontMetricsF(font).height()
        return font.family(), float(max(12.0, px * max(1.0, float(ratio or 1.0))))
    except Exception:
        return "Sans", 14.0 * max(1.0, float(ratio or 1.0))


class Scene:
    """Line sets: candidates, relations, snaps (inference lines), preview, construction (preview
    of construction geometry), hover (the part's edge under the pointer, preselect colour). Marker
    sets: hints (hollow), active (filled), points, hover. One text readout."""

    def __init__(self, view, matrix, ratio):
        from pivy import coin
        self.coin = coin
        self.view = view
        self.matrix = matrix
        self.root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        self.root.addChild(pick)
        self.root.addChild(light)
        self.sets = {}
        for name, pattern, col, width in (
                ("candidates", CANDIDATE_PATTERN, color("SnapGuideCandidateColor"), 1),
                ("relations", LOCKED_PATTERN, color("SnapGuideRelationColor"), 1),

                # them dotted in the same blue as the relation in use, from the point to the
                # pointer (shot 34: the origin's plumb line with the white glyph)
                ("snaps", SNAP_PATTERN, color("SnapGuideSnapColor"), 1),
                ("construction", CONSTRUCTION_PATTERN, color("ConstructionColor"), 1),
                ("preview", 0xFFFF, color("CreateLineColor"), 2),
                ("hover", 0xFFFF, color("PreselectColor"), 3),
                ("conflict", 0xFFFF, conflict_color(), 2),
                ("unsolvable", 0xFFFF, unsolvable_color(), 2),
                ("dangling", 0xFFFF, dangling_color(), 2),
                ("ghost", 0xFFFF, ghost_color(), 1)):
            sep = coin.SoSeparator()
            c = coin.SoBaseColor()
            c.rgb = col
            style = coin.SoDrawStyle()
            style.lineWidth = width * ratio
            style.linePattern = pattern
            style.linePatternScaleFactor = max(1, int(round(2 * ratio)))
            co = coin.SoCoordinate3()
            co.point.setNum(0)
            ls = coin.SoLineSet()
            ls.numVertices.setNum(0)
            for n in (c, style, co, ls):
                sep.addChild(n)
            self.root.addChild(sep)
            self.sets[name] = (co, ls)
        self.markers = {}
        for name, col, marker in (("hints", color("CursorTextColor"), _marker("CIRCLE_LINE", 9, ratio)),
                                  ("quadrants", QUADRANT_COLOR, _marker("DIAMOND_FILLED", 7, ratio)),
                                  ("active", color("SnapPointColor"), _marker("CIRCLE_FILLED", 9, ratio)),
                                  ("points", color("CreateLineColor"), _marker("CIRCLE_FILLED", 7, ratio)),
                                  ("hover", color("PreselectColor"), _marker("CIRCLE_FILLED", 9, ratio)),
                                  ("conflict", conflict_color(), _marker("CIRCLE_FILLED", 7, ratio)),
                                  ("unsolvable", unsolvable_color(), _marker("CIRCLE_FILLED", 7, ratio)),
                                  ("dangling", dangling_color(), _marker("CIRCLE_FILLED", 7, ratio))):
            sep = coin.SoSeparator()
            c = coin.SoBaseColor()
            c.rgb = col
            co = coin.SoCoordinate3()
            co.point.setNum(0)
            ms = coin.SoMarkerSet()
            ms.markerIndex = marker
            ms.numPoints = 0
            for n in (c, co, ms):
                sep.addChild(n)
            self.root.addChild(sep)
            self.markers[name] = (co, ms)
        # the readout beside the pointer (length and angle, width and height, radius)
        sep = coin.SoSeparator()
        c = coin.SoBaseColor()
        c.rgb = color("CursorTextColor")
        self.text_tr = coin.SoTranslation()
        # the application's font at its own size (Coin's default is a small bitmap font that reads as

        font = coin.SoFont()
        font.name, font.size = readout_font(ratio)
        self.text = coin.SoText2()
        self.text.string = ""
        for n in (c, self.text_tr, font, self.text):
            sep.addChild(n)
        self.root.addChild(sep)
        view.getSceneGraph().addChild(self.root)

    def g(self, p):
        v = self.matrix.multVec(App.Vector(p[0], p[1], 0))
        return (v.x, v.y, v.z)

    def lines(self, name, polylines):
        """polylines: a list of point lists (a pair = one segment)."""
        co, ls = self.sets[name]
        pts, counts = [], []
        for poly in polylines:
            if len(poly) < 2:
                continue
            pts.extend(self.g(p) for p in poly)
            counts.append(len(poly))
        co.point.setValues(0, len(pts), pts)
        co.point.setNum(len(pts))
        ls.numVertices.setValues(0, len(counts), counts)
        ls.numVertices.setNum(len(counts))

    def points(self, name, pts):
        co, ms = self.markers[name]
        g = [self.g(p) for p in pts]
        co.point.setValues(0, len(g), g)
        co.point.setNum(len(g))
        ms.numPoints = len(g)

    def label(self, p, text):
        if p is None or not text:
            self.text.string = ""
            return
        self.text_tr.translation.setValue(*self.g(p))
        self.text.string = text

    def clear(self):
        for name in self.sets:
            self.lines(name, [])
        for name in self.markers:
            self.points(name, [])
        self.text.string = ""

    def remove(self):
        try:
            self.view.getSceneGraph().removeChild(self.root)
        except Exception as _fw_err:
            _fw_log("fwsketch/scene.py:243", _fw_err)
