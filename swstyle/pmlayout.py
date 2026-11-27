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
from PySide import QtCore, QtGui, QtWidgets

from . import pmfields

Qt = QtCore.Qt
DONE = "swlayout"
CHEVRON = "SWStyle_LayoutChevron"
HEADER_CHECK = "SWStyle_HeaderCheck"
SIZE = 18
BLUE = QtGui.QColor(0x2f, 0x6f, 0xc4)
GREY = QtGui.QColor(0x5a, 0x5a, 0x5a)
BLUE_DARK = QtGui.QColor(0x7f, 0xb2, 0xf0)      # the same glyphs on the dark look (pkg98)
GREY_DARK = QtGui.QColor(0xc8, 0xc8, 0xc8)
GLYPH = "swlayout_glyph"                        # label property: the glyph it shows, for retheme


def _dark():
    try:
        from . import style
        return style.dark()
    except Exception:
        return False


def _theme_key():
    try:
        from . import style
        return style.current_theme()
    except Exception:
        return "Light"
_pix = {}

# label text -> glyph (text labels left of a field, or above a selection box)
LABELS = {
    "Depth": "depth1", "Length": "depth1", "Offset": "depth1", "Angle": "angle", "Angle:": "angle",
    "Spacing:": "spacing", "Number of instances:": "count", "Number of planes to create:": "planes",
    "Thickness:": "thickness", "Reference:": "reference", "Radius": "radius",
    "Features to Pattern:": "features", "Faces to Pattern:": "faces", "Bodies to Pattern:": "bodies",
    # fieldglyph-1121: the one-letter field labels (Chamfer D / A, Shell D1, Fillet R) are glyphs (E1 2026 video)
    "D": "distance", "A": "angle", "D1": "depth1", "D2": "depth2", "R": "radius",
}
BUTTONS = {"Draft": "draft"}

BOXES = {
    "SWStyle_AxisOfRevolution": "axis", "SWStyle_DirectionOfExtrusion": "direction",
    "SWMirrorPlane": "plane", "SWMirrorPlane2": "plane", "SWMirrorFeatures": "features",
    "SWMirrorFaces": "faces", "SWMirrorBodies": "bodies",
    "SWPlaneRef1": "reference", "SWPlaneRef2": "reference", "SWPlaneRef3": "reference",
    "SWAxisSelections": "reference", "SWStyle_SweepProfile": "profile", "SWStyle_SweepPath": "path",
    "SWStyle_SweepGuides": "guide", "SWStyle_LoftProfiles": "profile", "SWStyle_LoftGuides": "guide",
    "SWSectionReference": "plane", "SWSection2Reference": "plane", "SWSection3Reference": "plane",
    "SWDraftNeutralPlane": "plane", "SWSectionLabel": "label",
    "SWFilletItems": "edges", "SWChamferItems": "edges", "SWShellFaces": "faces",
    # surfpm-1121: the surface PropertyManagers' boxes (Surfaces video: Surface-Loft, Knit, Fill, Untrim...)
    "SWSurfProfiles": "profile", "SWSurfProfile": "profile", "SWSurfPath": "path", "SWSurfGuides": "guide",
    "SWSurfCenterline": "path", "SWSurfSurfaces": "faces", "SWSurfFaces": "faces", "SWSurfEdges": "edges",
    "SWStyle_Boundary": "edges", "SWStyle_Curves": "guide", "SWStyle_Points": "axis", "SWStyle_UntrimFace": "faces",
    "SWStyle_TrimTool": "faces", "SWStyle_TrimPieces": "faces",
}

CLOSED = {
    ("Linear Pattern", "Bodies"), ("Linear Pattern", "Instances to Skip"),
    ("Linear Pattern", "Instances to Vary"),

    # read 16, pm-heights-1120/linearpattern-top.jpg: Symmetric, the box, Spacing and instances, 1 instance,
    # Pattern seed only); Circular Pattern's Direction 2 is the one with a tick that starts folded
    # look audit AA1: the surface Extrude / Revolve fold Direction 2 and Selected Contours, as Boss-Extrude
    ("Surface-Extrude", "Direction 2"), ("Surface-Extrude", "Selected Contours"),
    ("Surface-Revolve", "Direction2"), ("Surface-Revolve", "Selected Contours"),
    ("Circular Pattern", "Direction 2"), ("Circular Pattern", "Bodies"), ("Circular Pattern", "Instances to Skip"),
    ("Circular Pattern", "Instances to Vary"),
    ("Mirror", "Bodies to Mirror"),

    # without a scroll; a ticked Thin Feature opens the group again. Mirror's Secondary Mirror

    ("Boundary Boss/Base", "Thin Feature"), ("Boundary Boss/Base", "Curvature Display"),
    ("Boundary Cut", "Thin Feature"), ("Boundary Cut", "Curvature Display"),
    ("Sweep", "Guide Curves"), ("Loft", "Guide Curves"),
    # surfpm-1121: the surface Loft and Sweep start with these folded (Surfaces video)
    ("Surface-Loft", "Start/End Constraints"), ("Surface-Loft", "Centerline Parameters"),
    ("Surface-Loft", "Curvature Display"), ("Surface-Loft", "Sketch Tools"), ("Surface-Sweep", "Guide Curves"), ("Surface-Sweep", "Options"),
    ("Surface-Sweep", "Start and End Tangency"), ("Surface-Sweep", "Curvature Display"),
    ("Section View", "Section 2"), ("Section View", "Section 3"),
    # insertcomp-1121: Thumbnail Preview starts folded (2025 video)
    ("Insert Component", "Thumbnail Preview"), ("Begin Assembly", "Thumbnail Preview"),
}
# a check box in the group header: ("inner", object name of the check box it stands for) or
# ("pair", key) for the Features and Faces / Bodies pair (one of the two is on)
HEADER_CHECKS = {
    ("Circular Pattern", "Direction 2"): ("inner", "SWPatternDir2On"),
    # features-416: Boundary's Thin Feature is ticked in its header, as Sweep and Loft
    ("Boundary Boss/Base", "Thin Feature"): ("inner", "SWStyle_BoundaryThin"),
    ("Boundary Cut", "Thin Feature"): ("inner", "SWStyle_BoundaryThin"),
    # look audit AA1 / AA2: ticked in the title, not by a second box of the same name inside
    ("Surface-Extrude", "Direction 2"): ("inner", "SWSurfDirection2"),
    ("Surface-Revolve", "Direction2"): ("inner", "SWSurfDirection2"),
    ("Knit Surface", "Gap Control"): ("inner", "SWSurfGapControl"),
    ("Linear Pattern", "Features and Faces"): ("pair", "features"),
    ("Linear Pattern", "Bodies"): ("pair", "bodies"),
    ("Circular Pattern", "Features and Faces"): ("pair", "features"),
    ("Circular Pattern", "Bodies"): ("pair", "bodies"),
    ("Linear Pattern", "Instances to Vary"): ("inner", "SWPatternInstancesToVary"),
    ("Circular Pattern", "Instances to Vary"): ("inner", "SWPatternInstancesToVary"),

    ("Section View", "Section 2"): ("inner", "SWSection2On"),
    ("Section View", "Section 3"): ("inner", "SWSection3On"),
    ("Section View", "Section by Body"): ("inner", "SWSectionByBodyOn"),
    ("Section View", "Section by Component"): ("inner", "SWSectionByBodyOn"),     # the same box in an assembly
    # Base Flange: Bend Allowance / Auto Relief are ticked in their header (unticked: the sheet metal defaults)
    ("Base Flange", "Bend Allowance"): ("inner", "SWSMUseAllowance"),
    ("Base Flange", "Auto Relief"): ("inner", "SWSMUseRelief"),
    # Simulation Mesh: Mesh Parameters is ticked in its header (unticked: the density slider's Standard size)
    ("Mesh", "Mesh Parameters"): ("inner", "SWSimMeshUseParams"),

    ("Interference Detection", "Excluded Components"): ("inner", "FW_InterferenceUseExcluded"),
}

# flange pages' Custom Bend Allowance / Custom Relief Type, End Cap's Corner Treatment
HEADER_CHECKS_ANY = {
    "Custom Bend Allowance": ("inner", "SWSMCustomAllowance"),
    "Custom Relief Type": ("inner", "SWSMCustomRelief"),
    "Corner Treatment": ("inner", "SWWECapCorner"),

    # read 16, fillet-manual-dark.jpg; features-464)
    "Partial Edge Parameters": ("inner", "SWFilletPartialOn"),
    # Simulation plot PMs (Stress, Displacement, Strain...): Deformed shape is ticked in its title
    "Deformed shape": ("inner", "SWSimPlotDeformed"),
}
_pairs = {}         # id(view) -> {"features": check box, "bodies": check box}
_seeded = False


# ---------------------------------------------------------------- glyphs
def _font(p, size=7, bold=True):
    f = p.font()
    f.setPixelSize(size)
    f.setBold(bold)
    p.setFont(f)


def _arrow(p, x1, y1, x2, y2, heads=2):
    p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))
    v = QtGui.QVector2D(x2 - x1, y2 - y1).normalized()
    n = QtGui.QVector2D(-v.y(), v.x())
    for tip, sign in (((x2, y2), -1), ((x1, y1), 1))[: heads]:
        tx, ty = tip
        b = QtCore.QPointF(tx + sign * v.x() * 3.5, ty + sign * v.y() * 3.5)
        p.drawLine(QtCore.QPointF(tx, ty), QtCore.QPointF(b.x() + n.x() * 2.2, b.y() + n.y() * 2.2))
        p.drawLine(QtCore.QPointF(tx, ty), QtCore.QPointF(b.x() - n.x() * 2.2, b.y() - n.y() * 2.2))


def _cube(p, x, y, s):
    d = s * 0.4
    p.drawRect(QtCore.QRectF(x, y + d, s - d, s - d))
    p.drawLine(QtCore.QPointF(x, y + d), QtCore.QPointF(x + d, y))
    p.drawLine(QtCore.QPointF(x + d, y), QtCore.QPointF(x + s, y))
    p.drawLine(QtCore.QPointF(x + s, y), QtCore.QPointF(x + s, y + s - d))
    p.drawLine(QtCore.QPointF(x + s, y + s - d), QtCore.QPointF(x + s - d, y + s))
    p.drawLine(QtCore.QPointF(x + s - d, y + d), QtCore.QPointF(x + s, y))


def _draw(name, p):
    BLUE, GREY = (BLUE_DARK, GREY_DARK) if _dark() else (globals()["BLUE"], globals()["GREY"])
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(BLUE, 1.2)
    p.setPen(pen)
    _font(p)
    if name in ("depth1", "depth2", "distance"):
        _arrow(p, 4, 15, 4, 2)
        p.setPen(GREY)
        p.drawText(QtCore.QRectF(7, 8, 11, 10), Qt.AlignRight | Qt.AlignBottom,
                   {"depth1": "D1", "depth2": "D2"}.get(name, "D"))      # fieldglyph-1121: "distance" reads D
    elif name == "angle":
        p.drawLine(QtCore.QPointF(2, 16), QtCore.QPointF(16, 16))
        p.drawLine(QtCore.QPointF(2, 16), QtCore.QPointF(12, 3))
        p.drawArc(QtCore.QRectF(2 - 7, 16 - 7, 14, 14), 0 * 16, 52 * 16)
        p.setPen(GREY)
        p.drawText(QtCore.QRectF(9, 1, 9, 9), Qt.AlignRight | Qt.AlignTop, "A")
    elif name == "spacing":
        p.drawLine(QtCore.QPointF(2.5, 2), QtCore.QPointF(2.5, 16))
        p.drawLine(QtCore.QPointF(15.5, 2), QtCore.QPointF(15.5, 16))
        _arrow(p, 3.5, 9, 14.5, 9)
    elif name == "count":
        for i, x in enumerate((1.5, 7, 12.5)):
            p.drawRect(QtCore.QRectF(x, 11, 4.5, 4.5))
        p.setPen(GREY)
        _font(p, 9)
        p.drawText(QtCore.QRectF(4, 0, 12, 10), Qt.AlignCenter, "#")
    elif name == "planes":
        for k in range(3):
            o = k * 3.5
            p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2 + o, 14 - o), QtCore.QPointF(9 + o, 14 - o),
                                           QtCore.QPointF(12 + o, 10 - o), QtCore.QPointF(5 + o, 10 - o)]))
    elif name == "thickness":
        p.drawLine(QtCore.QPointF(2, 4), QtCore.QPointF(16, 4))
        p.drawLine(QtCore.QPointF(2, 14), QtCore.QPointF(16, 14))
        _arrow(p, 5, 5.5, 5, 12.5)
        p.setPen(GREY)
        p.drawText(QtCore.QRectF(7, 5, 11, 9), Qt.AlignRight | Qt.AlignVCenter, "T1")
    elif name == "radius":
        p.drawArc(QtCore.QRectF(2, 2, 22, 22), 90 * 16, 90 * 16)
        p.drawLine(QtCore.QPointF(13, 13), QtCore.QPointF(5, 5))
        p.setPen(GREY)
        p.drawText(QtCore.QRectF(8, 8, 10, 10), Qt.AlignRight | Qt.AlignBottom, "R")
    elif name == "draft":
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2, 16), QtCore.QPointF(16, 16),
                                       QtCore.QPointF(12.5, 3), QtCore.QPointF(5.5, 3)]))
        p.drawLine(QtCore.QPointF(9, 3), QtCore.QPointF(9, 16))
    elif name in ("reference", "bodies"):
        _cube(p, 2, 2, 14)
    elif name == "axis":
        p.drawLine(QtCore.QPointF(3, 15), QtCore.QPointF(15, 3))
        p.setBrush(BLUE)
        p.drawEllipse(QtCore.QPointF(3, 15), 2, 2)
        p.drawEllipse(QtCore.QPointF(15, 3), 2, 2)
    elif name == "direction":
        _arrow(p, 4, 14, 14, 4, 1)
    elif name == "plane":
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(1, 14), QtCore.QPointF(11, 14),
                                       QtCore.QPointF(17, 4), QtCore.QPointF(7, 4)]))
    elif name == "profile":
        p.drawRoundedRect(QtCore.QRectF(3, 5, 12, 9), 4, 4)
    elif name == "path":
        path = QtGui.QPainterPath(QtCore.QPointF(2, 15))
        path.cubicTo(QtCore.QPointF(4, 2), QtCore.QPointF(14, 16), QtCore.QPointF(16, 3))
        p.drawPath(path)
    elif name == "guide":
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        path = QtGui.QPainterPath(QtCore.QPointF(2, 15))
        path.cubicTo(QtCore.QPointF(4, 2), QtCore.QPointF(14, 16), QtCore.QPointF(16, 3))
        p.drawPath(path)
    elif name == "label":
        p.setPen(GREY)
        _font(p, 8)
        p.drawText(QtCore.QRectF(0, 0, 9, 9), Qt.AlignCenter, "A")
        p.drawText(QtCore.QRectF(0, 9, 9, 9), Qt.AlignCenter, "A")
        p.setPen(pen)
        _arrow(p, 9, 4.5, 16, 4.5, 1)
        _arrow(p, 9, 13.5, 16, 13.5, 1)
    elif name in ("move_up", "move_down"):
        # loftpm-1121: the block arrows under a list's glyph (Move Up / Move Down)
        pts = [(9, 2), (15.5, 8.5), (11.5, 8.5), (11.5, 16), (6.5, 16), (6.5, 8.5), (2.5, 8.5)]
        if name == "move_down":
            pts = [(x, 18 - y) for x, y in pts]
        p.setPen(QtGui.QPen(BLUE, 1.3))
        p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in pts]))
    elif name in ("chevron_up", "chevron_down"):
        pen = QtGui.QPen(GREY, 1.5)
        p.setPen(pen)
        if name == "chevron_up":
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(4, 12), QtCore.QPointF(9, 7), QtCore.QPointF(14, 12)]))
        else:
            p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(4, 7), QtCore.QPointF(9, 12), QtCore.QPointF(14, 7)]))
    elif name == "features":
        _cube(p, 1, 3, 12)
        p.setPen(QtGui.QPen(QtGui.QColor(0x2a, 0x9d, 0x3a), 1.4))
        p.drawEllipse(QtCore.QRectF(10, 9, 7, 7))
    elif name == "edges":
        _cube(p, 2, 2, 14)
        p.setPen(QtGui.QPen(QtGui.QColor(0x3a, 0x8f, 0xe0), 2.4))
        p.drawLine(QtCore.QPointF(2, 7.6), QtCore.QPointF(10.4, 7.6))
    elif name == "faces":
        _cube(p, 2, 2, 14)
        p.fillRect(QtCore.QRectF(2.6, 8.2, 8, 8), QtGui.QColor(0x3a, 0x8f, 0xe0, 170))
    else:
        p.drawRect(QtCore.QRectF(3, 3, 12, 12))


def pixmap(name):
    ""
    key = (name, _theme_key())
    pm = _pix.get(key)
    if pm is None:
        dpr = 2
        pm = QtGui.QPixmap(SIZE * dpr, SIZE * dpr)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        try:
            _draw(name, p)
        finally:
            p.end()
        _pix[key] = pm
    return pm


def icon(name):
    return QtGui.QIcon(pixmap(name))


# ---------------------------------------------------------------- helpers
def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _title(view):
    from . import propertymanager
    try:
        cached = propertymanager._current_title
        if cached is not None and cached[0] == id(view):
            return cached[1]
        return propertymanager._title(view)[0]
    except Exception:
        return ""


def _group_title(group):
    for label in group.findChildren(QtWidgets.QWidget):
        if label.inherits("QSint::ActionLabel") and callable(getattr(label, "text", None)):
            return label.text()
    return ""


def _group_open(group):
    frames = [c for c in group.children() if isinstance(c, QtWidgets.QFrame) and not c.inherits("QSint::TaskHeader")]
    content = frames[-1] if frames else None
    return content is not None and not content.isHidden()


def _show_hide(group):
    try:
        QtCore.QMetaObject.invokeMethod(group, "showHide")
    except Exception as _fw_err:
        _fw_log("pmlayout.py:295", _fw_err)


def _holder(widget):
    parent = widget.parentWidget()
    if parent is None or parent.layout() is None:
        return None
    return pmfields._holder(parent.layout(), widget)


def _chevron(parent):
    b = QtWidgets.QToolButton(parent)
    b.setObjectName(CHEVRON)
    b.setAutoRaise(True)
    b.setFixedSize(18, 18)
    b.setFocusPolicy(Qt.NoFocus)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0px; }")
    return b


def set_chevron(button, open_):
    ""
    button.setArrowType(Qt.NoArrow)
    button.setIcon(icon("chevron_up" if open_ else "chevron_down"))
    button.setIconSize(QtCore.QSize(SIZE, SIZE))
    button.setToolTip("Collapse" if open_ else "Expand")


def _chevron_beside(widget, is_open, on_click):
    ""
    if widget.property(CHEVRON):
        return widget.property(CHEVRON)
    lay = _holder(widget)
    if lay is None:
        return None
    b = _chevron(widget.parentWidget())
    if isinstance(lay, QtWidgets.QGridLayout):
        r, c, rs, cs = lay.getItemPosition(lay.indexOf(widget))
        lay.addWidget(b, r, max(c + 1, lay.columnCount() - 1), 1, 1, Qt.AlignRight | Qt.AlignVCenter)
    else:
        i = lay.indexOf(widget)
        lay.removeWidget(widget)
        line = QtWidgets.QHBoxLayout()
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(widget)
        line.addStretch(1)
        line.addWidget(b, 0, Qt.AlignRight | Qt.AlignVCenter)
        lay.insertLayout(i, line)

    def _sync(*a):
        if not _alive(b) or not _alive(widget):
            return
        set_chevron(b, bool(is_open()))
    b.clicked.connect(lambda *a: (on_click(), _sync()))
    if hasattr(widget, "toggled"):
        widget.toggled.connect(_sync)
    _sync()
    widget.setProperty(CHEVRON, b)
    return b


# ---------------------------------------------------------------- icons
def _box_icons(view):
    ""
    for box in view.findChildren(QtWidgets.QWidget):
        glyph = BOXES.get(box.objectName())
        if not glyph or box.property(DONE) or not isinstance(box, (QtWidgets.QAbstractItemView, QtWidgets.QLineEdit)):
            continue
        lay = _holder(box)
        if lay is None:
            continue
        label = QtWidgets.QLabel(box.parentWidget())
        label.setObjectName("SWStyle_BoxGlyph")
        label.setPixmap(pixmap(glyph))
        label.setProperty(GLYPH, glyph)
        label.setFixedWidth(SIZE + 6)
        label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        label.setToolTip(box.toolTip())
        if isinstance(lay, QtWidgets.QGridLayout):
            r, c, rs, cs = lay.getItemPosition(lay.indexOf(box))
            if c == 0:
                # the box fills its row from the left edge (Extrude's Direction of Extrusion):
                # the glyph and the box share the cell
                lay.removeWidget(box)
                row = QtWidgets.QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(label, 0, Qt.AlignTop)
                row.addWidget(box)
                lay.addLayout(row, r, c, rs, cs)
            elif lay.itemAtPosition(r, c - 1) is not None:
                label.deleteLater()
                continue
            else:
                lay.addWidget(label, r, c - 1, 1, 1, Qt.AlignLeft | Qt.AlignTop)
        elif isinstance(lay, QtWidgets.QBoxLayout) and lay.direction() in (QtWidgets.QBoxLayout.TopToBottom, QtWidgets.QBoxLayout.BottomToTop):
            i = lay.indexOf(box)
            lay.removeWidget(box)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(label, 0, Qt.AlignTop)
            row.addWidget(box)
            lay.insertLayout(i, row)
        elif isinstance(lay, QtWidgets.QBoxLayout):
            i = lay.indexOf(box)
            if i > 0 and isinstance(pmfields.sub_widget(lay, i - 1), QtWidgets.QAbstractButton):
                label.deleteLater()
                continue
            lay.insertWidget(i, label, 0, Qt.AlignTop)
        elif isinstance(lay, QtWidgets.QFormLayout):
            # fillicons-1121: a box in a form row (the Field pages: Fill Surface's Patch Boundary and Constraint
            # Curves): the glyph and the box share the box's cell
            pos = lay.getWidgetPosition(box)
            row, role = (pos[0], pos[1]) if isinstance(pos, (tuple, list)) else (-1, None)
            if row < 0:
                label.deleteLater()
                continue
            lay.removeWidget(box)
            cell = QtWidgets.QWidget(box.parentWidget())
            cell.setObjectName("SWStyle_BoxGlyphCell")
            line = QtWidgets.QHBoxLayout(cell)
            line.setContentsMargins(0, 0, 0, 0)
            label.setParent(cell)
            line.addWidget(label, 0, Qt.AlignTop)
            line.addWidget(box)
            lay.setWidget(row, role, cell)
            cell.show()
            label.show()
            box.show()
        else:
            label.deleteLater()
            continue
        box.setProperty(DONE, True)
        box.setSizePolicy(QtWidgets.QSizePolicy.Expanding, box.sizePolicy().verticalPolicy())


def _label_icons(view):
    for label in view.findChildren(QtWidgets.QLabel):
        done = label.property(DONE)
        if done and label.text():
            # someone re-labelled it (Corner Trim swaps D and R): the glyph follows the new text
            new = label.text().replace("&", "")
            if new in LABELS:
                done = new
                label.setProperty(DONE, new)
                label.setToolTip(new)
            label.setText("")
            label.setPixmap(pixmap(LABELS[done]))
            label.setProperty(GLYPH, LABELS[done])
            continue
        if done or label.pixmap() is not None and not label.pixmap().isNull():
            continue
        text = label.text().replace("&", "")
        glyph = LABELS.get(text)
        if not glyph or label.isHidden():
            continue
        lay = _holder(label)
        label.setProperty(DONE, text)
        label.setToolTip(text)
        label.setPixmap(pixmap(glyph))
        label.setProperty(GLYPH, glyph)
        label.setFixedWidth(SIZE + 6)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if isinstance(lay, QtWidgets.QBoxLayout) and lay.direction() in (QtWidgets.QBoxLayout.TopToBottom, QtWidgets.QBoxLayout.BottomToTop):

            i = lay.indexOf(label)
            nxt = pmfields.sub_widget(lay, i + 1)
            if isinstance(nxt, (QtWidgets.QAbstractItemView, QtWidgets.QLineEdit)):
                label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                lay.removeWidget(label)
                lay.removeWidget(nxt)
                row = QtWidgets.QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(label)
                row.addWidget(nxt)
                lay.insertLayout(i, row)
    for button in view.findChildren(QtWidgets.QToolButton):
        if button.property(DONE):
            continue
        glyph = BUTTONS.get(button.text().replace("&", ""))
        if not glyph:
            continue
        button.setProperty(DONE, button.text())
        if not button.toolTip():
            button.setToolTip(button.text())
        button.setIcon(icon(glyph))
        button.setIconSize(QtCore.QSize(SIZE, SIZE))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setText("")


# ---------------------------------------------------------------- folds
def _seed_folds(view, title):
    ""

    global _seeded
    from . import propertymanager
    if not _seeded:
        _seeded = True
        for key in CLOSED:
            propertymanager.FOLDS.setdefault(key, False)
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup") or group.isHidden() or group.property("swlayout_fold"):
            continue
        key = (title, _group_title(group))
        if key not in CLOSED or not group.property("expandable"):
            continue
        group.setProperty("swlayout_fold", True)
        # a fold already running (the page memory folded it a moment ago) is not toggled again: a second
        # showHide while the first still animates opened the group back up (features-464)
        if propertymanager.FOLDS.get(key) is False and _group_open(group) and not propertymanager._settling(group):
            propertymanager.settle_fold(group)
            _show_hide(group)
            propertymanager._FOLD_SEEN[id(group)] = (key, False)


# ---------------------------------------------------------------- header check boxes
def _header_of(group):
    for h in group.children():
        if h.inherits("QSint::TaskHeader"):
            return h
    return None


def _header_check(group, name):
    header = _header_of(group)
    if header is None or header.layout() is None:
        return None
    cb = QtWidgets.QCheckBox(header)
    cb.setObjectName(HEADER_CHECK + "_" + name.replace(" ", ""))
    cb.setToolTip(name)
    cb.setFocusPolicy(Qt.NoFocus)
    lay = header.layout()
    title = pmfields.sub_widget(lay, 0)
    lay.insertWidget(0, cb)
    lay.setSpacing(2)
    if title is not None:
        title.setSizePolicy(QtWidgets.QSizePolicy.Preferred, title.sizePolicy().verticalPolicy())
        lay.insertStretch(2, 1)
    return cb


def _header_checks(view, title):
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup") or group.property(DONE):
            continue
        name = _group_title(group)
        spec = HEADER_CHECKS.get((title, name)) or HEADER_CHECKS_ANY.get(name)
        if spec is None:
            continue
        group.setProperty(DONE, True)
        kind, arg = spec
        if kind == "inner":
            inner = group.findChild(QtWidgets.QCheckBox, arg)
            if inner is None:
                continue
            cb = _header_check(group, name)
            if cb is None:
                continue
            inner.hide()
            cb.setChecked(inner.isChecked())
            if inner.isChecked() and not _group_open(group):
                _show_hide(group)       # a group that starts folded opens when its box is already ticked (Edit Feature)

            def _down(on, inner=inner, cb=cb, group=group):
                if _alive(inner) and inner.isChecked() != on:
                    inner.setChecked(on)
                if on and _alive(group) and not _group_open(group):
                    _show_hide(group)

            def _up(on, cb=cb, group=group):
                if _alive(cb) and cb.isChecked() != on:
                    cb.blockSignals(True)
                    cb.setChecked(on)
                    cb.blockSignals(False)
                if on and _alive(group) and not _group_open(group):
                    _show_hide(group)      # ticked from the page (Edit Feature, a script): unfold
            cb.toggled.connect(_down)
            inner.toggled.connect(_up)
        else:
            cb = _header_check(group, name)
            if cb is None:
                continue
            pair = _pairs.setdefault(id(view), {})
            pair[arg] = (cb, group)
            cb.setChecked(arg == "features")

            def _pick(on, arg=arg, view=view):
                pair = _pairs.get(id(view), {})
                mine = pair.get(arg)
                other = pair.get("bodies" if arg == "features" else "features")
                if not on:

                    if other is None or not _alive(other[0]) or not other[0].isChecked():
                        mine[0].blockSignals(True)
                        mine[0].setChecked(True)
                        mine[0].blockSignals(False)
                    return
                if other is not None and _alive(other[0]) and other[0].isChecked():
                    other[0].blockSignals(True)
                    other[0].setChecked(False)
                    other[0].blockSignals(False)
                    if _alive(other[1]) and _group_open(other[1]):
                        _show_hide(other[1])
                if mine is not None and _alive(mine[1]) and not _group_open(mine[1]):
                    _show_hide(mine[1])
            cb.toggled.connect(_pick)
            group.destroyed.connect(lambda *a, k=id(view): _pairs.pop(k, None))


# ---------------------------------------------------------------- section titles
def _section_chevrons(view):
    for name in ("SWStyle_Direction2", "SWStyle_ThinFeatureOn"):
        for cb in view.findChildren(QtWidgets.QCheckBox, name):
            if cb.isHidden() or cb.property(CHEVRON):
                continue
            _chevron_beside(cb, cb.isChecked, cb.toggle)
    header = view.findChild(QtWidgets.QToolButton, "SWStyle_SelectedContoursHeader")
    if header is not None and not header.property(DONE):
        header.setProperty(DONE, True)
        header.setAutoRaise(True)
        header.setArrowType(Qt.NoArrow)
        header.setToolButtonStyle(Qt.ToolButtonTextOnly)
        header.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        header.setStyleSheet("QToolButton { border: none; background: transparent; font-weight: bold; text-align: left; padding: 2px 0px; }")
        _chevron_beside(header, header.isChecked, header.click)
    for fold in view.findChildren(QtWidgets.QToolButton, "SWStyle_SectionFold"):
        if not fold.property(DONE):
            fold.setProperty(DONE, True)
            fold.setStyleSheet("QToolButton { border: none; background: transparent; padding: 0px; }")

            def _glyph(*a, fold=fold):
                if _alive(fold):
                    set_chevron(fold, fold.arrowType() != Qt.DownArrow and fold.toolTip() != "Expand")
            fold.clicked.connect(_glyph)        # after the fold's own toggle (connected first)
            _glyph()


def _end_condition_row(view):
    ""
    box = view.findChild(QtWidgets.QLineEdit, "SWStyle_DirectionOfExtrusion")
    if box is not None and box.placeholderText():
        box.setPlaceholderText("")
    if box is not None and box.minimumHeight() < 54:
        box.setFixedHeight(54)
        box.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    end = view.findChild(QtWidgets.QComboBox, "SWStyle_EndCondition")
    if end is None or end.property(DONE):
        return
    end.setProperty(DONE, True)
    end.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    lay = _holder(end)
    if isinstance(lay, QtWidgets.QGridLayout):
        r, c, rs, cs = lay.getItemPosition(lay.indexOf(end))
        lay.setColumnStretch(c, 1)
        for col in range(c):
            lay.setColumnStretch(col, 0)


def _revolve_merge(view, title):
    ""

    if title not in ("Revolve", "Cut-Revolve", "Revolved Cut"):
        return
    merge = view.findChild(QtWidgets.QCheckBox, "SWStyle_MergeResult")
    angle = view.findChild(QtWidgets.QAbstractSpinBox, "revolveAngle")
    if merge is None or angle is None or merge.property(DONE):
        return
    outer = _holder(merge)
    if not isinstance(outer, QtWidgets.QBoxLayout):
        return
    at = None
    for i in range(outer.count()):
        w = pmfields.sub_widget(outer, i)
        sub = pmfields.sub_layout(outer, i)
        if w is angle or sub is not None and sub.indexOf(angle) >= 0:
            at = i
            break
    if at is None:
        return
    merge.setProperty(DONE, True)
    k = outer.indexOf(merge)
    outer.removeWidget(merge)
    outer.insertWidget(at + (1 if k > at else 0), merge)


# ---------------------------------------------------------------- sweep / loft groups
GROUP_BOXES = {
    "SWStyle_StartEndTangency": "Start and End Tangency", "SWStyle_StartEndConstraints": "Start/End Constraints",
    "SWStyle_GuideCurves": "Guide Curves", "SWStyle_CenterlineParameters": "Centerline Parameters",
    "SWStyle_ThinFeature": "Thin Feature", "SWStyle_FeatureScope": "Feature Scope",
    "SWStyle_SketchTools": "Sketch Tools", "SWStyle_CurvatureDisplay": "Curvature Display",   # features/91
}
GROUP_CLOSED = {"SWStyle_StartEndTangency", "SWStyle_StartEndConstraints", "SWStyle_GuideCurves",
                "SWStyle_CenterlineParameters", "SWStyle_FeatureScope", "SWStyle_CurvatureDisplay"}

THIN_CHECKS = {"SWStyle_ThinFeature": ("SWStyle_SweepThin", "SWStyle_LoftThin")}


GROUP_QSS = ("QGroupBox { border: none; border-top: 1px solid palette(mid); margin-top: 6px; padding: 22px 0px 0px 0px; font-weight: bold; }"
             "QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left; left: 0px; top: 3px; padding: 0px 2px; }"
             "QGroupBox::indicator { width: 13px; height: 13px; }")
FOLDED_HEIGHT = 30


class _GroupFold(QtCore.QObject):
    ""


    def __init__(self, box, closed, key=None):
        super().__init__(box)
        self.box = box
        self.key = key          # (page, group title): the fold is remembered as for QSint groups
        self.folded = False
        self.hidden = []
        self.button = _chevron(box)
        self.button.clicked.connect(lambda *_: self.toggle())
        box.installEventFilter(self)
        box.setStyleSheet(GROUP_QSS)
        box.setProperty("swstyle_section", True)        # an extrudepm fold stops at a group
        self._place()
        set_chevron(self.button, True)
        if key is not None:
            try:
                from . import propertymanager
                left = propertymanager.FOLDS.get(key)
                if left is not None:
                    closed = not left
            except Exception as _fw_err:
                _fw_log("pmlayout.py:groupfold", _fw_err)
        if closed:
            self.toggle(remember=False)

    def eventFilter(self, obj, event):
        if isinstance(event, QtCore.QEvent) and event.type() == QtCore.QEvent.Resize:
            self._place()
        return False

    def _place(self):
        self.button.move(self.box.width() - self.button.width() - 2, 8)
        self.button.raise_()

    def _rows(self):
        lay = self.box.layout()
        out = []
        if lay is None:
            return out
        for i in range(lay.count()):
            w = pmfields.sub_widget(lay, i)
            sub = pmfields.sub_layout(lay, i)
            if w is not None:
                out.append(w)
            elif sub is not None:
                out.extend(_widgets_in(sub))
        return out

    def toggle(self, remember=True):
        self.folded = not self.folded
        if remember and self.key is not None and self.key[0]:
            try:
                from . import propertymanager
                propertymanager.FOLDS[self.key] = not self.folded
                propertymanager._save_fold(self.key, not self.folded)
            except Exception as _fw_err:
                _fw_log("pmlayout.py:groupfold", _fw_err)
        if self.folded:
            self.hidden = [w for w in self._rows() if not w.isHidden()]
            for w in self.hidden:
                w.hide()
            self.box.setFixedHeight(FOLDED_HEIGHT)
        else:
            self.box.setMinimumHeight(0)
            self.box.setMaximumHeight(16777215)
            for w in self.hidden:
                if _alive(w):
                    w.show()
            self.hidden = []
        set_chevron(self.button, not self.folded)


def _widgets_in(lay):
    out = []
    for i in range(lay.count()):
        w = pmfields.sub_widget(lay, i)
        if w is not None:
            out.append(w)
        else:
            sub = pmfields.sub_layout(lay, i)
            if sub is not None:
                out.extend(_widgets_in(sub))
    return out


def _group_boxes(view, title):
    for box in view.findChildren(QtWidgets.QGroupBox):
        name = box.objectName()
        if name not in GROUP_BOXES or box.property(DONE):
            continue
        box.setProperty(DONE, True)
        box.setTitle(GROUP_BOXES[name])
        inner = None
        for cb_name in THIN_CHECKS.get(name, ()):
            inner = box.findChild(QtWidgets.QCheckBox, cb_name)
            if inner is not None:
                break
        if inner is not None:

            box.setCheckable(True)
            box.setChecked(inner.isChecked())
            inner.hide()
            box.toggled.connect(lambda on, inner=inner: _alive(inner) and inner.isChecked() != on and inner.setChecked(on))
            inner.toggled.connect(lambda on, box=box: _alive(box) and box.isChecked() != on and box.setChecked(on))
            box.setStyleSheet(GROUP_QSS)
            box.setProperty("swstyle_section", True)
        else:
            _GroupFold(box, name in GROUP_CLOSED, (title, GROUP_BOXES[name]))


def _loft_order(view, title):
    ""

    if title not in ("Loft", "Cut-Loft"):
        return
    head = view.findChild(QtWidgets.QLabel, "SWStyle_LoftOptionsTitle")
    thin = view.findChild(QtWidgets.QGroupBox, "SWStyle_ThinFeature")
    if head is None or thin is None:
        return
    lay = _holder(thin)
    if not isinstance(lay, QtWidgets.QBoxLayout):
        return
    merge = view.findChild(QtWidgets.QCheckBox, "SWStyle_MergeResult")
    closed = view.findChild(QtWidgets.QCheckBox, "checkBoxClosed")
    ruled = view.findChild(QtWidgets.QCheckBox, "checkBoxRuled")
    if closed is None or ruled is None or _holder(closed) is not lay:
        return
    # loftpm-1121: a first feature has no Merge result, and the Options stayed under the Profiles box; they
    # go before Thin Feature without it, and again with it once it shows
    if merge is not None and _holder(merge) is not lay:
        merge = None
    done = head.property("swlayout_loft")
    if done and (done == "merge" or merge is None):
        return
    head.setProperty("swlayout_loft", "merge" if merge is not None else "plain")
    # the title sits in a line layout (title + chevron) made by extrudepm's fold
    line = None
    for i in range(lay.count()):
        sub = pmfields.sub_layout(lay, i)
        if sub is not None and sub.indexOf(head) >= 0:
            line = sub
            break
    items = []
    if line is not None:
        items.append(("layout", line))
    # look audit Z7: Merge tangent faces, Show preview and Micro tolerance are Options too (they sat under

    extra = {n: view.findChild(QtWidgets.QCheckBox, "SWStyle_Loft" + n) for n in ("MergeTangent", "ShowPreview", "MicroTolerance")}
    for w in (extra["MergeTangent"], closed, ruled, extra["ShowPreview"], merge, extra["MicroTolerance"]):
        if w is not None:
            items.append(("widget", w))
    for kind, it in items:
        if kind == "layout":
            lay.removeItem(it)
        else:
            old = _holder(it)
            if old is not None:
                old.removeWidget(it)
            if it.parentWidget() is not thin.parentWidget():
                it.setParent(thin.parentWidget())
                it.show()
    at = lay.indexOf(thin)
    for kind, it in items:
        if kind == "layout":
            lay.insertLayout(at, it)
        else:
            lay.insertWidget(at, it)
        at += 1


def _layout_parent(root, target):
    """(layout, index) of the layout under root that holds the layout target, or (None, -1)."""
    if root is None:
        return None, -1
    for i in range(root.count()):
        sub = pmfields.sub_layout(root, i)
        if sub is None:
            continue
        if sub is target:
            return root, i
        found = _layout_parent(sub, target)
        if found[0] is not None:
            return found
    return None, -1


class _ArrowButton(QtWidgets.QAbstractButton):
    """loftpm-1121: a flat 22 px button that draws its glyph at full size (no frame; a light square under the
    pointer), so no style or icon-size rule shrinks it."""

    def __init__(self, parent, glyph):
        super().__init__(parent)
        self.setProperty(GLYPH, glyph)
        self.setFixedSize(SIZE + 4, SIZE + 4)
        self.setCursor(Qt.ArrowCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover, True)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        try:
            if self.isEnabled() and (self.underMouse() or self.isDown()):
                c = QtGui.QColor(BLUE_DARK if _dark() else BLUE)
                c.setAlpha(70 if self.isDown() else 40)
                p.fillRect(self.rect(), c)
            if not self.isEnabled():
                p.setOpacity(0.35)
            p.drawPixmap(2, 2, pixmap(self.property(GLYPH)))
        finally:
            p.end()


def _arrow_button(parent, glyph, original):
    b = _ArrowButton(parent, glyph)
    b.setObjectName(original.objectName() + "Arrow" if original.objectName() else "SWStyle_OrderArrow")
    b.setToolTip(original.toolTip() or original.text().replace("&", ""))
    b.setAccessibleName(original.text().replace("&", ""))
    b.setEnabled(original.isEnabled())
    b.clicked.connect(lambda *_a, o=original: _alive(o) and o.click())
    return b


class _EnabledMirror(QtCore.QObject):
    """The arrow follows its text button's enabled state."""

    def __init__(self, original, arrow):
        super().__init__(arrow)
        self.arrow = arrow
        original.installEventFilter(self)

    def eventFilter(self, obj, event):
        try:
            if event.type() == QtCore.QEvent.EnabledChange and _alive(self.arrow):
                self.arrow.setEnabled(obj.isEnabled())
        except Exception as _fw_err:
            _fw_log("pmlayout.arrows", _fw_err)
        return False


def _order_arrows(view):
    """loftpm-1121: Move Up / Move Down under a selection list are two block-arrow buttons stacked under the
    list's glyph at its left (as in the Loft video's Profiles and Guide Curves), not a row of text buttons below
    it. The text buttons stay (hidden) and do the work, so every caller of them is unchanged."""
    for up in view.findChildren(QtWidgets.QPushButton):
        if up.property(DONE) or up.text().replace("&", "") != "Move Up" or up.isHidden() and not up.property("swarrow_wait"):
            continue
        row = _holder(up)
        if row is None or not isinstance(row, QtWidgets.QBoxLayout):
            continue
        down = None
        for i in range(row.count()):
            w = pmfields.sub_widget(row, i)
            if isinstance(w, QtWidgets.QPushButton) and w.text().replace("&", "") == "Move Down":
                down = w
        if down is None:
            continue
        others = [pmfields.sub_widget(row, i) for i in range(row.count())]
        if any(w is not None and w is not up and w is not down for w in others):
            continue
        # the row of the two buttons: a widget of its own, or a layout, in a vertical layout
        holder_widget = up.parentWidget() if up.parentWidget() is not None and up.parentWidget().layout() is row else None
        outer, at = None, -1
        if holder_widget is not None and holder_widget is not view:
            outer = _holder(holder_widget)
            at = outer.indexOf(holder_widget) if outer is not None else -1
        if outer is None:
            outer, at = _layout_parent(up.parentWidget().layout() if up.parentWidget() is not None else None, row)
            holder_widget = None
        if outer is None or at < 1 or not isinstance(outer, QtWidgets.QBoxLayout) \
                or outer.direction() not in (QtWidgets.QBoxLayout.TopToBottom, QtWidgets.QBoxLayout.BottomToTop):
            continue
        # the list just above: in a row with its glyph (_box_icons), or on its own
        above_lay = pmfields.sub_layout(outer, at - 1)
        above_w = pmfields.sub_widget(outer, at - 1)
        box = glyph = None
        if above_lay is not None:
            for i in range(above_lay.count()):
                w = pmfields.sub_widget(above_lay, i)
                if isinstance(w, QtWidgets.QAbstractItemView):
                    box = w
                elif isinstance(w, QtWidgets.QLabel) and w.objectName() == "SWStyle_BoxGlyph":
                    glyph = w
        elif isinstance(above_w, QtWidgets.QAbstractItemView):
            box = above_w
        if box is None:
            continue
        if above_lay is not None and glyph is None:
            up.setProperty("swarrow_wait", True)
            continue                    # its glyph is not there yet: the next dressing
        parent = box.parentWidget()
        column = QtWidgets.QWidget(parent)
        column.setObjectName("SWStyle_OrderColumn")
        col = QtWidgets.QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        a_up = _arrow_button(column, "move_up", up)
        a_down = _arrow_button(column, "move_down", down)
        _EnabledMirror(up, a_up)
        _EnabledMirror(down, a_down)
        if glyph is not None:
            i = above_lay.indexOf(glyph)
            above_lay.removeWidget(glyph)
            glyph.setParent(column)
            col.addWidget(glyph, 0, Qt.AlignLeft | Qt.AlignTop)
            above_lay.insertWidget(i, column, 0, Qt.AlignTop)
        else:
            i = outer.indexOf(box)
            outer.removeWidget(box)
            line = QtWidgets.QHBoxLayout()
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(column, 0, Qt.AlignTop)
            line.addWidget(box)
            outer.insertLayout(i, line)
        col.addWidget(a_up, 0, Qt.AlignLeft)
        col.addWidget(a_down, 0, Qt.AlignLeft)
        col.addStretch(1)
        column.setFixedWidth(max(SIZE + 6, a_up.width()))
        column.show()
        up.setProperty(DONE, True)
        down.setProperty(DONE, True)
        up.hide()
        down.hide()
        if holder_widget is not None:
            holder_widget.hide()


def _sweep_order(view, title):
    ""

    if title not in ("Sweep", "Cut-Sweep"):
        return
    guides = options = None
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup"):
            continue
        name = _group_title(group)
        if name == "Guide Curves":
            guides = group
        elif name == "Options":
            options = group
    if guides is None or options is None or guides.property(DONE):
        return
    lay = _holder(guides)
    if lay is None or _holder(options) is not lay:
        return
    guides.setProperty(DONE, True)
    i_opt = lay.indexOf(options)
    i_gui = lay.indexOf(guides)
    if i_gui > i_opt:
        lay.removeWidget(guides)
        lay.insertWidget(i_opt, guides)
    merge = view.findChild(QtWidgets.QCheckBox, "SWStyle_MergeResult")
    form = options.findChild(QtWidgets.QWidget, "PartDesignGui__TaskPipeOrientation")
    if merge is not None and form is not None and form.layout() is not None and _holder(merge) is not form.layout():
        old = _holder(merge)
        if old is not None:
            old.removeWidget(merge)
        merge.setParent(form)
        flay = form.layout()
        n = flay.count()
        last = flay.itemAt(n - 1) if n else None
        at = n - 1 if last is not None and last.spacerItem() is not None else n
        if isinstance(flay, QtWidgets.QBoxLayout):
            flay.insertWidget(at, merge)
        elif isinstance(flay, QtWidgets.QGridLayout):
            flay.addWidget(merge, flay.rowCount(), 0, 1, max(1, flay.columnCount()))
        else:
            flay.addWidget(merge)
        merge.show()
    # look audit Z6: Merge tangent faces and Show preview before Merge result, Align with end faces after
    # it, in the Options (they sat under the Path box)
    # sweepopts-1121: on a first feature (no Merge result) they go to the end of the Options too
    if form is not None and form.layout() is not None and isinstance(form.layout(), QtWidgets.QBoxLayout):
        flay = form.layout()
        for name, after in (("SWStyle_SweepMergeTangent", False), ("SWStyle_SweepShowPreview", False), ("SWStyle_SweepAlignEnds", True)):
            cb = view.findChild(QtWidgets.QCheckBox, name)
            if cb is None or _holder(cb) is flay:
                continue
            old = _holder(cb)
            if old is not None:
                old.removeWidget(cb)
            cb.setParent(form)
            if merge is not None and _holder(merge) is flay:
                at = flay.indexOf(merge)
                flay.insertWidget(at + 1 if after else at, cb)
            else:
                n = flay.count()
                last = flay.itemAt(n - 1) if n else None
                flay.insertWidget(n - 1 if last is not None and last.spacerItem() is not None else n, cb)
            cb.show()

    if form is not None and form.layout() is not None:
        for name in ("SWStyle_StartEndTangency", "SWStyle_ThinFeature", "SWStyle_FeatureScope", "SWStyle_CurvatureDisplay"):
            box = view.findChild(QtWidgets.QGroupBox, name)
            if box is None or box.parentWidget() is form:
                continue
            old = _holder(box)
            if old is not None:
                old.removeWidget(box)
            box.setParent(form)
            flay = form.layout()
            n = flay.count()
            last = flay.itemAt(n - 1) if n else None
            at = n - 1 if last is not None and last.spacerItem() is not None else n
            if isinstance(flay, QtWidgets.QBoxLayout):
                flay.insertWidget(at, box)
            elif isinstance(flay, QtWidgets.QGridLayout):
                flay.addWidget(box, flay.rowCount(), 0, 1, max(1, flay.columnCount()))
            else:
                flay.addWidget(box)
            box.show()


def retheme(view):
    """The look switched theme: the glyphs and chevrons are drawn again in the new colours."""
    if view is None:
        return
    for label in view.findChildren(QtWidgets.QLabel):
        glyph = label.property(GLYPH)
        if glyph:
            label.setPixmap(pixmap(glyph))
    for button in view.findChildren(QtWidgets.QToolButton):
        if button.objectName() == CHEVRON:
            set_chevron(button, button.toolTip() != "Expand")
        elif button.objectName() == "SWStyle_SectionFold" and button.property(DONE):
            set_chevron(button, button.toolTip() != "Expand")
        elif button.objectName() == TOP_CHEVRON:
            button.setProperty("swopen", None)      # drawn again at the next dressing


INDENT = "swlayout_indent"
_FIELDS = (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox, QtWidgets.QLineEdit, QtWidgets.QListWidget)


def _is_title(w):
    """A box title drawn in the page (a section check box, a header check)."""
    return bool(w.property("swstyle_section")) or w.objectName() == HEADER_CHECK or w.objectName().endswith("Title")


def _field_column(container):
    ""
    xs = []
    lefts = []
    for w in container.children():
        if not isinstance(w, QtWidgets.QWidget) or not w.isVisible():
            continue
        lefts.append(w.x())
        if isinstance(w, _FIELDS) and not isinstance(w.parentWidget(), (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
            xs.append(w.x())
    if not lefts or not xs:
        return None, None
    left = min(lefts)
    inner = [x for x in xs if 12 <= x - left <= 60]
    if not inner:
        return left, None
    return left, max(set(inner), key=inner.count)


def _check_column(view):
    ""


    seen = {}
    for w in view.findChildren(QtWidgets.QAbstractButton):
        if not isinstance(w, (QtWidgets.QCheckBox, QtWidgets.QRadioButton)) or not w.isVisible():
            continue
        if w.property(INDENT) is not None or _is_title(w) or _inside_header(w):
            continue
        c = w.parentWidget()
        if c is None:
            continue
        if id(c) not in seen:
            seen[id(c)] = _field_column(c)
        left, col = seen[id(c)]
        if col is None or abs(w.x() - left) > 3:
            continue
        pad = col - w.x()
        w.setProperty(INDENT, pad)
        w.setStyleSheet(w.styleSheet() + "\n%s { margin-left: %dpx; }" % (type(w).__name__, pad))


def _inside_header(w):
    p = w.parentWidget()
    while p is not None:
        if p.property("class") == "header" or p.objectName() == "SWStyle_PMHeader":
            return True
        p = p.parentWidget()
    return False


def _align_titles(view):
    ""

    for content in view.findChildren(QtWidgets.QFrame):
        if content.property("class") != "content" or not content.isVisible():
            continue
        group = content.parentWidget()
        header = next((f for f in group.children() if isinstance(f, QtWidgets.QFrame)
                       and f.property("class") == "header"), None) if group is not None else None
        page = next((w for w in content.children() if isinstance(w, QtWidgets.QWidget) and w.isVisible()
                     and w.layout() is not None), None)
        if header is None or page is None or header.layout() is None:
            continue
        rows = [w for w in page.children() if isinstance(w, QtWidgets.QWidget) and w.isVisible()]
        if not rows:
            continue
        x = min(w.mapTo(group, QtCore.QPoint(0, 0)).x() for w in rows)
        kids = [w for w in header.children() if isinstance(w, QtWidgets.QWidget) and w.isVisible()
                and w.objectName() != CHEVRON]
        if not kids:
            continue
        first = min(kids, key=lambda w: w.x())
        text_x = first.mapTo(group, QtCore.QPoint(0, 0)).x() + (2 if isinstance(first, QtWidgets.QToolButton) or first.inherits("QSint::ActionLabel") else 0)
        diff = x - text_x
        if abs(diff) < 2 or not -20 <= diff <= 30:
            continue
        lay = header.layout()
        m = lay.contentsMargins()
        lay.setContentsMargins(max(0, m.left() + diff), m.top(), m.right(), m.bottom())
    _folded_titles(view)


def _folded_titles(view):
    """sweepopts-1121: a folded box has no rows to line its title up with, so it kept FreeCAD's own
    margin and sat 7 px left of its open neighbours (Sweep's Guide Curves). It takes the margin most
    open boxes of the page have; opened, _align_titles corrects it from there."""
    open_m, folded = [], []
    for group in view.findChildren(QtWidgets.QWidget):
        if not group.inherits("QSint::ActionGroup") or not group.isVisible():
            continue
        header = next((f for f in group.children() if isinstance(f, QtWidgets.QFrame)
                       and f.property("class") == "header"), None)
        content = next((f for f in group.children() if isinstance(f, QtWidgets.QFrame)
                        and f.property("class") == "content"), None)
        if header is None or header.layout() is None or content is None:
            continue
        if content.isVisible():
            open_m.append(header.layout().contentsMargins().left())
        else:
            folded.append(header)
    if not open_m or not folded:
        return
    want = max(set(open_m), key=open_m.count)
    for header in folded:
        lay = header.layout()
        m = lay.contentsMargins()
        if m.left() != want:
            lay.setContentsMargins(want, m.top(), m.right(), m.bottom())



TOP_CHEVRON = "SWStyle_TopChevron"


def _no_tab_on_folds(view):
    ""

    changed = False
    for b in view.findChildren(QtWidgets.QToolButton):
        name = b.objectName()
        parent = b.parentWidget()
        header = parent is not None and "Header" in parent.metaObject().className()
        if header or name == TOP_CHEVRON or name.startswith("SWBoxFold_") or name in (
                "SWStyle_SectionFold", "SWStyle_SelectedContoursHeader"):
            if b.focusPolicy() != QtCore.Qt.NoFocus:
                b.setFocusPolicy(QtCore.Qt.NoFocus)
                changed = True
    if changed:
        # the page's tab cycle was made with these buttons in it: make it again without them, or Tab
        # from the last field left the page (Axis: into the status bar)
        from . import propertymanager
        view.setProperty("swTabChain", None)
        propertymanager._tab_order(view)


def _top_chevrons(view):
    ""


    for header in view.findChildren(QtWidgets.QFrame):
        if header.property("class") != "header" or not header.isVisible():
            continue
        group = header.parentWidget()
        content = next((f for f in group.children() if isinstance(f, QtWidgets.QFrame)
                        and f.property("class") == "content"), None) if group is not None else None
        title = next((w for w in header.children() if isinstance(w, QtWidgets.QToolButton)), None)
        native = [w for w in header.children() if type(w) is QtWidgets.QLabel and w.pixmap() is not None
                  and not w.pixmap().isNull()]
        if content is None or title is None or not native:
            continue
        mark = native[-1]
        button = header.findChild(QtWidgets.QToolButton, TOP_CHEVRON)
        if button is None:
            button = _chevron(header)
            button.setObjectName(TOP_CHEVRON)
            button.clicked.connect(lambda *a, t=title: _alive(t) and t.click())
        mark.setVisible(False)
        g = mark.geometry()
        # chevx-1121: the hidden mark keeps the place it had when the header was last laid out with it, so
        # a header that grew later (Edit Sketch: the pane was narrower when it opened) left the chevron in
        # the middle of the row. Its place is worked out from the header's width: where the mark goes, at
        # the right end, inside the header's right margin.
        lay = header.layout()
        right = lay.contentsMargins().right() if lay is not None else 4
        mark_w = max(mark.sizeHint().width(), g.width(), 1)
        want = header.width() - right - mark_w // 2 - button.width() // 2
        # FreeCAD's header can lay its mark out past its own right edge (Base Flange): the chevron then
        # showed cut in half, as a slash. It is kept inside the header.
        x = min(want, header.width() - button.width() - 2)
        button.move(x, g.center().y() - button.height() // 2)
        button.show()
        button.raise_()
        open_ = content.isVisible() and content.maximumHeight() > 0
        if button.property("swopen") != open_:
            button.setProperty("swopen", open_)
            set_chevron(button, open_)



UNIT_GAP = "swlayout_unitgap"
_UNIT_TEXT = __import__("re").compile(r"^(\s*[-+]?[0-9][0-9.,'eE+-]*) ((?:mm|cm|m|in|ft|µm|um|nm|mil|thou|°|deg|rad|gon|kg|g|N|s)(?:\^\d)?)$")


def _close_unit(edit):
    ""


    if not _alive(edit) or edit.property("swtyping"):
        return
    text = edit.text()
    m = _UNIT_TEXT.match(text)
    if not m:
        return
    new = m.group(1) + m.group(2)
    cut = len(m.group(1))
    pos, start, length = edit.cursorPosition(), edit.selectionStart(), len(edit.selectedText())
    shift = lambda i: i - 1 if i > cut else i
    old = edit.blockSignals(True)
    try:
        edit.setText(new)
        if start >= 0 and length:
            edit.setSelection(shift(start), shift(start + length) - shift(start))
        else:
            edit.setCursorPosition(shift(pos))
    finally:
        edit.blockSignals(old)


def _unit_gaps(view):
    for spin in view.findChildren(QtWidgets.QAbstractSpinBox):
        if spin.property(UNIT_GAP) or not spin.inherits("Gui::QuantitySpinBox"):
            continue
        edit = spin.findChild(QtWidgets.QLineEdit)
        if edit is None:
            continue
        spin.setProperty(UNIT_GAP, True)
        # the user's own typing is left as typed until the field takes it
        edit.textEdited.connect(lambda *a, e=edit: e.setProperty("swtyping", True))
        spin.editingFinished.connect(lambda e=edit: (_alive(e) and e.setProperty("swtyping", False),
                                                     QtCore.QTimer.singleShot(0, lambda: _close_unit(e))))
        edit.textChanged.connect(lambda *a, e=edit: QtCore.QTimer.singleShot(0, lambda: _close_unit(e)))
        _close_unit(edit)


def install(view):
    if view is None:
        return
    title = _title(view)
    _seed_folds(view, title)
    _label_icons(view)
    _box_icons(view)
    try:
        _order_arrows(view)         # loftpm-1121
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PM layout arrows: %r\n" % error)
    _header_checks(view, title)
    _section_chevrons(view)
    _end_condition_row(view)
    _revolve_merge(view, title)
    _group_boxes(view, title)
    _loft_order(view, title)
    _sweep_order(view, title)
    for step in (_align_titles, _check_column, _top_chevrons, _unit_gaps):
        try:
            step(view)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: PM layout %s: %r\n" % (step.__name__, error))
    for step in (_no_tab_on_folds,):
        try:
            step(view)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: PM layout %s: %r\n" % (step.__name__, error))
    try:
        from . import pmlast
        pmlast.remember(view, title)
        pmlast.restore(view, title)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: PM last values: %r\n" % (error,))
