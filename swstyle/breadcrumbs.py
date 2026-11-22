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

from . import contextbar, icons, paths, rollbackbar, style
from .widgets import alive, ui_font

Qt = QtCore.Qt

PARAM = "Breadcrumbs"        # addon parameter (default on)
MARGIN = 8                   # from the 3D view's top left corner, like the flyout tree
HEIGHT = 22                  # a button
ICON = 16
PAD = 4                      # inside a button, before the icon and after the text
GAP = 3                      # between icon and text
CHEVRON = 9                  # the separator between buttons
ELBOW = 14                   # the hook before the sketch row
BOX = 2                      # the box's edge around the buttons
T = style.T                  # the theme's colours, read when painting
PICKED = QtGui.QColor(47, 128, 237, 72)
HOVER = QtGui.QColor(47, 128, 237, 36)
GLYPH = QtGui.QColor(47, 128, 237)
GLYPH_FILL = QtGui.QColor(111, 168, 240, 150)
SKETCH = "Sketcher::SketchObject"
BODY = "PartDesign::Body"
ORIGIN = "App::Origin"
ORIGIN_PARTS = ("App::Plane", "App::Line", "App::Origin")
ELEMENTS = ("face", "edge", "vertex")
LINKS = ("App::Link", "App::LinkElement", "App::LinkGroup")


def _is_link(obj):
    try:
        return obj.TypeId in LINKS or hasattr(obj, "LinkedObject")
    except Exception:
        return False


def resolve(obj, sub):
    """A pick through assembly components ('LinkA.Body.Pad.Face6'): the component links on the way,
    the object the path ends in and its element name; (components, obj, sub) with no components for
    a plain pick."""
    if not sub or "." not in sub:
        return [], obj, sub
    try:
        along = obj.getSubObjectList(sub)
        last = obj.getSubObject(sub, retType=1)
    except Exception:
        return [], obj, sub
    if last is None:
        return [], obj, sub
    comps = [o for o in along if o is not last and _is_link(o)]
    if obj is not last and _is_link(obj) and obj not in comps:
        comps.insert(0, obj)
    element = sub.rsplit(".", 1)[-1]
    return comps, last, element


def enabled():
    return paths.params().GetBool(PARAM, True)


def _strip():
    """The CommandManager tab row's reach over the 3D view's top (tabstrip.py), 0 when not there."""
    try:
        from . import tabstrip
        return tabstrip.top()
    except Exception:
        return 0


class Item:
    """One button of the row."""
    __slots__ = ("kind", "obj", "sub", "icon", "text", "tip", "picked")

    def __init__(self, kind, obj, sub="", icon=None, text="", tip="", picked=False):
        self.kind, self.obj, self.sub = kind, obj, sub
        self.icon = icon if icon is not None else QtGui.QIcon()
        self.text, self.tip, self.picked = text, tip, picked

    @property
    def key(self):
        obj = self.obj
        try:
            name = (obj.Document.Name, obj.Name) if hasattr(obj, "Document") else (obj.Name, "")
        except Exception:
            name = ("", "")
        return (self.kind,) + name + (self.sub,)


# --------------------------------------------------------------------------- what is picked
def body_of(obj):
    """The PartDesign body holding the object: a feature, sketch or datum in its group, its
    origin or one of the origin's planes and axes; the body itself; else None."""
    if obj.TypeId == BODY:
        return obj
    body = rollbackbar.body_of(obj)
    if body is not None:
        return body
    try:
        origin = obj if obj.TypeId == ORIGIN else next((o for o in obj.InList if o.TypeId == ORIGIN), None)
        if origin is not None:
            for parent in origin.InList:
                if parent.TypeId == BODY:
                    return parent
    except Exception as _fw_err:
        _fw_log("breadcrumbs.py:132", _fw_err)
    return None


def feature_from(sketch):
    """The solid feature made from the sketch, or None."""
    try:
        for obj in sketch.InList:
            if contextbar._solid_feature(obj) and contextbar.sketch_of(obj) is sketch:
                return obj
    except Exception as _fw_err:
        _fw_log("breadcrumbs.py:143", _fw_err)
    return None


def _label(obj):
    try:
        return obj.Label
    except Exception:
        return ""


def chain():
    """(row, second, under): the buttons of the row, the sketch hanging under row[under] or None;
    (None, None, None) when nothing, or more than one thing, is picked."""
    p = contextbar.picks()
    if len(p) != 1:
        return None, None, None
    obj, sub = p[0]
    top = obj.Document
    components, obj, sub = resolve(obj, sub)        # an assembly pick: the components on the way
    kind = contextbar.kind_of(obj, sub)
    if kind is None and obj.TypeId in ORIGIN_PARTS:
        kind = "datum"
    if kind is None and _is_link(obj) and not sub:
        kind = "component"
    if kind is None and (sub or not hasattr(obj, "Shape")):
        return None, None, None
    if kind is None:
        kind = "feature"
    doc = top
    row = [Item("part", doc, "", part_icon(doc), "", doc.Label)]

    for comp in components:
        row.append(Item("component", comp, "", obj_icon(comp), _label(comp), _label(comp)))
    if kind == "component":
        row.append(Item("component", obj, "", obj_icon(obj), _label(obj), _label(obj), picked=True))
    mated = [c for c in list(components) + [obj] if _is_link(c)]
    mates = mates_item(mated[0]) if mated else None
    if kind == "component":
        return _with_mates(row, mates), None, None
    body = body_of(obj)
    if body is not None:
        row.append(Item("body", body, "", obj_icon(body), _label(body) if kind == "body" else "", _label(body),
                        picked=kind == "body"))
    second, under = None, None
    if kind in ELEMENTS:
        owner = contextbar.owner_feature(obj, sub)
        if owner is not None and owner.TypeId != BODY:
            row.append(Item("feature", owner, "", feature_icon(owner), _label(owner), _label(owner)))
            under = len(row) - 1
            second = sketch_item(contextbar.sketch_of(owner))
        row.append(Item(kind, obj, sub, glyph(kind), "", sub, picked=True))
    elif kind == "sketch":
        feature = feature_from(obj)
        if feature is not None:
            row.append(Item("feature", feature, "", feature_icon(feature), _label(feature), _label(feature)))
        row.append(Item("sketch", obj, "", obj_icon(obj), _label(obj), _label(obj), picked=True))
    elif kind == "body":
        pass
    elif kind in ("plane", "datum"):
        row.append(Item(kind, obj, "", obj_icon(obj), _label(obj), _label(obj), picked=True))
    else:
        row.append(Item("feature", obj, "", feature_icon(obj), _label(obj), _label(obj), picked=True))
        under = len(row) - 1
        second = sketch_item(contextbar.sketch_of(obj)) if obj.TypeId != SKETCH else None
    if mates is not None:
        row = _with_mates(row, mates)
        if under is not None and under >= row.index(mates):
            under += 1
    return row, second, under


def _with_mates(row, mates):
    """The Mates button right after its component's button (before the picked item when the
    component has no button of its own)."""
    if mates is None:
        return row
    try:
        name = mates.obj.Name
    except Exception:
        return row
    at = None
    for k, it in enumerate(row):
        try:
            if it.kind not in ("mates",) + ELEMENTS and getattr(it.obj, "Name", None) == name \
                    and it.obj.Document.Name == mates.obj.Document.Name:
                at = k + 1
                break
        except Exception as _fw_err:
            _fw_log("breadcrumbs.py:232", _fw_err)
    if at is None:
        at = max(1, len(row) - 1)
    return row[:at] + [mates] + row[at:]


def component_mates(comp):
    ""
    try:
        from . import asmmenu
        comp = comp.Document.getObject(comp.Name) or comp     # the document's own object (a pick path gives a copy)
        return asmmenu.mates_of(comp) if asmmenu.assembly_of(comp) is not None else []
    except Exception:
        return []


def mates_item(comp):
    """The Mates button after a component: its mates' count; a click lists them to pick one."""
    mates = component_mates(comp)
    if not mates:
        return None
    try:
        from . import asmcore
        icon = obj_icon(asmcore.joint_group(asmcore.assembly_of(comp.Document)))
    except Exception:
        icon = None
    tip = "Mates of %s: %s" % (_label(comp), ", ".join(_label(j) for j in mates))
    return Item("mates", comp, "", icon, "Mates (%d)" % len(mates), tip)



# with the entity's relations in a row under it (a click picks the relation, a right-click
# offers Delete)
REL_ICONS = {"Coincident": "Constraint_PointOnPoint", "Horizontal": "Constraint_Horizontal",
             "Vertical": "Constraint_Vertical", "Parallel": "Constraint_Parallel",
             "Perpendicular": "Constraint_Perpendicular", "Tangent": "Constraint_Tangent",
             "Equal": "Constraint_EqualLength", "Symmetric": "Constraint_Symmetric",
             "PointOnObject": "Constraint_PointOnObject", "Block": "Constraint_Block",
             "HorizontalLine": "Constraint_Horizontal", "VerticalLine": "Constraint_Vertical"}
REL_NAMES = {"Coincident": "Coincident", "PointOnObject": "Coincident", "Horizontal": "Horizontal",
             "Vertical": "Vertical", "Parallel": "Parallel", "Perpendicular": "Perpendicular",
             "Tangent": "Tangent", "Equal": "Equal", "Symmetric": "Symmetric", "Block": "Fix"}
DIMENSIONAL = ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter", "Angle", "SnellsLaw", "Weight")


def _entity(sketch, sub):
    """(geo index, pos or None) of a picked sketch element, or None."""
    try:
        if sub.startswith("Edge"):
            return int(sub[4:]) - 1, None
        if sub.startswith("Vertex"):
            geo, pos = sketch.getGeoVertexIndex(int(sub[6:]) - 1)
            return geo, pos
    except Exception as _fw_err:
        _fw_log("breadcrumbs.py:286", _fw_err)
    return None


def relations_of(sketch, sub):
    """[(constraint index, type)] of the sketch relations the picked entity takes part in."""
    ent = _entity(sketch, sub)
    if ent is None:
        return []
    geo, pos = ent
    out = []
    for i, c in enumerate(sketch.Constraints):
        if c.Type in DIMENSIONAL or c.Type == "InternalAlignment":
            continue
        refs = ((c.First, c.FirstPos), (c.Second, c.SecondPos), (c.Third, c.ThirdPos))
        for g, p in refs:
            if g != geo or g < -2000:
                continue
            if pos is None or p == pos or (c.Type in ("PointOnObject",) and p == pos):
                out.append((i, c.Type))
                break
    return out


def relation_icon(kind):
    name = REL_ICONS.get(kind, "Constraint_Horizontal")
    for path in (":/icons/constraints/%s.svg" % name, ":/icons/%s.svg" % name):
        if QtCore.QFile.exists(path):
            return QtGui.QIcon(path)
    try:
        return Gui.getIcon(name)
    except Exception:
        return glyph("vertex")


def sketch_chain(sketch):
    """(row, seconds, under) in a sketch: the sketch, the picked entity, and its relations."""
    p = contextbar.picks()
    if len(p) != 1:
        return None, None, None
    obj, sub = p[0]
    if obj is not sketch or not (sub.startswith("Edge") or sub.startswith("Vertex")):
        return None, None, None
    kind = "edge" if sub.startswith("Edge") else "vertex"
    row = [Item("sketch", sketch, "", obj_icon(sketch), _label(sketch), _label(sketch)),
           Item(kind, sketch, sub, glyph(kind), "", sub, picked=True)]
    rels = []
    for i, t in relations_of(sketch, sub):
        name = sketch.Constraints[i].Name or "%s%d" % (REL_NAMES.get(t, t), i + 1)
        rels.append(Item("relation", sketch, "Constraint%d" % (i + 1), relation_icon(t), "", name))
    return row, (rels or None), 1


def sketch_item(sketch):
    if sketch is None:
        return None
    return Item("sketch", sketch, "", obj_icon(sketch), _label(sketch), _label(sketch))


# --------------------------------------------------------------------------- icons
_GLYPHS = {}


def obj_icon(obj):
    try:
        icon = obj.ViewObject.Icon
        if isinstance(icon, QtGui.QIcon) and not icon.isNull():
            return icon
    except Exception as _fw_err:
        _fw_log("breadcrumbs.py:355", _fw_err)
    return QtGui.QIcon()


def feature_icon(obj):
    try:
        icon = contextbar._feature_icon(obj)
        if not icon.isNull():
            return icon
    except Exception as _fw_err:
        _fw_log("breadcrumbs.py:365", _fw_err)
    return obj_icon(obj)


def part_icon(doc):
    icon = icons.family("PART")
    if not icon.isNull():
        return icon
    try:
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            if tree.metaObject().className() != "Gui::TreeWidget":
                continue
            model = tree.model()
            for row in range(model.rowCount()):
                index = model.index(row, 0)
                if index.data(Qt.DisplayRole) == doc.Label:
                    icon = index.data(Qt.DecorationRole)
                    if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                        return icon
    except Exception as _fw_err:
        _fw_log("breadcrumbs.py:385", _fw_err)
    try:
        return Gui.getIcon("Document")
    except Exception:
        return QtGui.QIcon()


def glyph(kind, dpr=None):
    """A small picture for a face, an edge or a corner: FreeCAD has none."""
    if dpr is None:
        app = QtWidgets.QApplication.instance()
        dpr = app.devicePixelRatio() if app is not None else 1.0
    key = (kind, dpr)
    icon = _GLYPHS.get(key)
    if icon is not None:
        return icon
    pm = QtGui.QPixmap(int(ICON * dpr), int(ICON * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    painter = QtGui.QPainter(pm)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(GLYPH)
    pen.setWidthF(1.4)
    painter.setPen(pen)
    if kind == "face":
        painter.setBrush(GLYPH_FILL)
        painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(2, 12.5), QtCore.QPointF(6, 3.5), QtCore.QPointF(14, 3.5),
                                             QtCore.QPointF(10, 12.5)]))
    elif kind == "edge":
        painter.drawLine(QtCore.QPointF(3, 12.5), QtCore.QPointF(13, 3.5))
        painter.setBrush(GLYPH)
        painter.drawEllipse(QtCore.QPointF(3, 12.5), 1.6, 1.6)
        painter.drawEllipse(QtCore.QPointF(13, 3.5), 1.6, 1.6)
    else:
        painter.setBrush(GLYPH)
        painter.drawEllipse(QtCore.QPointF(8, 8), 2.6, 2.6)
    painter.end()
    icon = QtGui.QIcon(pm)
    _GLYPHS[key] = icon
    return icon


# --------------------------------------------------------------------------- the widgets
class Crumb(QtWidgets.QAbstractButton):
    """One button: the item's icon, its name when it has one, blue when it is the picked item."""

    hovered = QtCore.Signal(object, bool)
    menu = QtCore.Signal(object, object)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.menu.emit(self.item, event.globalPos())
            event.accept()
            return
        super().mousePressEvent(event)

    def __init__(self, item, parent):
        super().__init__(parent)
        self.item = item
        self.setFont(ui_font())
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(item.tip)
        self.setCursor(Qt.PointingHandCursor if item.kind != "part" else Qt.ArrowCursor)
        width = PAD + ICON + PAD
        if item.text:
            width += GAP + self.fontMetrics().horizontalAdvance(item.text)
        self.setFixedSize(width, HEIGHT)

    def enterEvent(self, event):
        self.hovered.emit(self.item, True)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(self.item, False)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = PICKED if self.item.picked else (HOVER if self.underMouse() else None)
        if fill is not None:
            painter.setPen(Qt.NoPen)
            painter.setBrush(fill)
            painter.drawRoundedRect(r, 3, 3)
        icon_rect = QtCore.QRect(PAD, (HEIGHT - ICON) // 2, ICON, ICON)
        style.paint_icon(painter, self.item.icon, icon_rect)
        if self.item.text:
            painter.setPen(T.text)
            painter.setFont(self.font())
            text_rect = QtCore.QRect(PAD + ICON + GAP, 0, self.width() - PAD - ICON - GAP - PAD, HEIGHT)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self.item.text)
        painter.end()


class Trail(QtWidgets.QWidget):
    """The row of buttons in its box, and the sketch row hanging under a feature's button."""

    def __init__(self, owner):
        super().__init__(owner.shell.window)
        self.setObjectName("SWBreadcrumbs")
        self.owner = owner
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.crumbs = []
        self.boxes = []              # the painted boxes
        self.elbow = None            # (x, y) of the hook before the sketch row
        self.hide()

    def clear(self):
        for child in self.findChildren(QtWidgets.QWidget):
            child.hide()
            child.setParent(None)
            child.deleteLater()
        self.crumbs, self.boxes, self.elbow = [], [], None

    def fill(self, row, second=None, under=None):
        self.clear()
        x, y = BOX, BOX
        under_x = BOX
        for k, item in enumerate(row):
            if k:
                x += CHEVRON
            crumb = self._crumb(item, x, y)
            if k == under:
                under_x = x
            x += crumb.width()
        box = QtCore.QRect(0, 0, x + BOX, HEIGHT + 2 * BOX)
        self.boxes = [box]
        width, height = box.width(), box.height()
        if second is not None:
            ex = under_x + PAD + ICON // 2
            cy = box.bottom() + 1 + 3 + BOX
            seconds = second if isinstance(second, (list, tuple)) else [second]
            sx = ex + ELBOW + BOX
            for item in seconds:            # a sketch entity's relations sit side by side
                crumb = self._crumb(item, sx, cy)
                sx += crumb.width() + 1
            box2 = QtCore.QRect(ex + ELBOW, box.bottom() + 1 + 3, sx - 1 - (ex + ELBOW + BOX) + 2 * BOX, HEIGHT + 2 * BOX)
            self.boxes.append(box2)
            self.elbow = (ex, box.bottom() + 1, box2.top() + box2.height() // 2)
            width = max(width, box2.right() + 1)
            height = box2.bottom() + 1
        self.resize(width, height)
        self.update()

    def _crumb(self, item, x, y):
        crumb = Crumb(item, self)
        crumb.move(x, y)
        crumb.clicked.connect(lambda checked=False, it=item: self.owner.pick(it))
        crumb.hovered.connect(self.owner.hover)
        crumb.menu.connect(self.owner.menu)
        crumb.show()
        self.crumbs.append(crumb)
        return crumb

    def crumb_of(self, item):
        """The button for the item, also after the row was filled again for a new pick."""
        key = item.key
        for crumb in self.crumbs:
            if crumb.item.key == key:
                return crumb
        return None

    def texts(self):
        return [c.item.text for c in self.crumbs]

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(T.line_mid)
        pen.setCosmetic(True)
        for box in self.boxes:
            painter.setPen(pen)
            painter.setBrush(T.rgba("base", 238))
            painter.drawRoundedRect(QtCore.QRectF(box).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        # the separators
        chevron = QtGui.QPen(T.arrow_dim)
        chevron.setWidthF(1.2)
        painter.setPen(chevron)
        painter.setBrush(Qt.NoBrush)
        for k, crumb in enumerate(self.crumbs):
            if k == 0 or crumb.y() != self.crumbs[0].y():
                continue
            cx = crumb.x() - CHEVRON / 2.0
            cy = crumb.y() + HEIGHT / 2.0
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(cx - 2, cy - 4), QtCore.QPointF(cx + 1, cy),
                                                  QtCore.QPointF(cx - 2, cy + 4)]))
        if self.elbow is not None:
            ex, top, mid = self.elbow
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(ex + 0.5, top), QtCore.QPointF(ex + 0.5, mid + 0.5),
                                                  QtCore.QPointF(ex + ELBOW - 3, mid + 0.5)]))
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(ex + ELBOW - 6, mid - 2.5), QtCore.QPointF(ex + ELBOW - 3, mid + 0.5),
                                                  QtCore.QPointF(ex + ELBOW - 6, mid + 3.5)]))
        painter.end()


# --------------------------------------------------------------------------- the owner
class _Observer:
    """FreeCAD selection observer: every change asks for one later look."""

    def __init__(self, owner):
        self.owner = owner

    def addSelection(self, doc, obj, sub, pnt):
        self.owner.soon()

    def removeSelection(self, doc, obj, sub):
        self.owner.soon()

    def setSelection(self, doc):
        self.owner.soon()

    def clearSelection(self, doc):
        self.owner.soon()


def at_mouse_pointer(window):
    """Options > Display > Show breadcrumbs at mouse pointer: a new row starts just under and right of
    the pointer (None: the 3D view's top left corner)."""
    try:
        from . import optionspages
        if not optionspages.stored("Display", "Show breadcrumbs at mouse pointer", False):
            return None
    except Exception:
        return None
    pos = window.mapFromGlobal(QtGui.QCursor.pos())
    return QtCore.QPoint(pos.x() + 16, pos.y() + 16)


class Breadcrumbs(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.trail = Trail(self)
        self._sig = None
        self._due = False
        self.at_pointer = None       # where D put the row, in main window coordinates, or None
        self.picks = 0               # buttons clicked, for checks
        self.toolbars = 0            # pop-up toolbars brought up from a button, for checks
        self.error = None
        self.observer = _Observer(self)
        try:
            Gui.Selection.addObserver(self.observer)
        except Exception:
            self.observer = None
        self.mdi = shell.window.findChild(QtWidgets.QMdiArea)
        if self.mdi is not None:
            self.mdi.subWindowActivated.connect(self.soon)
        self.soon()

    def on(self):
        return bool(self.shell.enabled and enabled())

    def host(self):
        overlay = getattr(self.shell, "overlay", None)
        host = getattr(overlay, "host", None) if overlay is not None else None
        return host if host is not None and alive(host) and host.isVisible() else None

    def soon(self, *args):
        if not self._due:
            self._due = True
            QtCore.QTimer.singleShot(0, self.refresh)

    def wanted(self):
        if self.on() and App.ActiveDocument is not None and contextbar.sketch_in_edit() is not None:
            return True             # the sketch's own breadcrumbs (sketch_chain)
        return (self.on() and App.ActiveDocument is not None and not contextbar.dialog_open()
                and contextbar.sketch_in_edit() is None)

    def refresh(self):
        self._due = False
        if not alive(self.trail):
            return
        row = second = under = None
        if self.wanted():
            try:
                sk = contextbar.sketch_in_edit()
                row, second, under = sketch_chain(sk) if sk is not None else chain()
            except Exception as error:
                self.error = error
                App.Console.PrintWarning("FreeCAD: breadcrumbs: %s\n" % error)
        host = self.host()
        if not row or host is None:
            self.hide()
            return
        seconds = second if isinstance(second, (list, tuple)) else ([second] if second else [])
        sig = tuple(item.key + (item.text, item.picked) for item in row) + tuple(i.key for i in seconds) + (under,)
        if sig != self._sig:
            self._sig = sig
            self.at_pointer = at_mouse_pointer(self.shell.window)
            self.trail.fill(row, second, under)
        self.place(host)
        if self.trail.isHidden():
            self.trail.show()
        self.trail.raise_()

    def hide(self):
        self._sig = None
        self.at_pointer = None
        if alive(self.trail) and not self.trail.isHidden():
            self.trail.hide()

    def place(self, host):
        mw = self.shell.window
        if self.at_pointer is not None:
            top_left = QtCore.QPoint(self.at_pointer)
        else:
            top_left = host.mapTo(mw, QtCore.QPoint(MARGIN, MARGIN + _strip()))
        top_left.setX(max(0, min(top_left.x(), mw.width() - self.trail.width())))
        top_left.setY(max(0, min(top_left.y(), mw.height() - self.trail.height())))
        if self.trail.pos() != top_left:
            self.trail.move(top_left)

    def to_pointer(self):
        """D: the row at the pointer, and back to the corner on the next D."""
        if not alive(self.trail) or self.trail.isHidden():
            return False
        if self.at_pointer is not None:
            self.at_pointer = None
        else:
            pos = self.shell.window.mapFromGlobal(QtGui.QCursor.pos())
            self.at_pointer = QtCore.QPoint(pos.x() - PAD - ICON // 2, pos.y() - HEIGHT // 2 - BOX)
        host = self.host()
        if host is not None:
            self.place(host)
        return True

    # ------------------------------------------------------------------ the buttons
    def pick(self, item):
        """A click on a button picks that item and brings up its pop-up toolbar."""
        if item.kind == "part" or item.obj is None:
            return
        if item.kind == "mates":
            return self.mates_menu(item)
        if contextbar.sketch_in_edit() is not None:
            if item.kind == "sketch":
                return                  # the sketch being edited: nothing to pick
            try:
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(item.obj.Document.Name, item.obj.Name, item.sub or "")
            except Exception as error:
                self.error = error
            self.picks += 1
            return
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(item.obj.Document.Name, item.obj.Name, item.sub or "")
        except Exception as error:
            self.error = error
            return
        self.picks += 1
        QtCore.QTimer.singleShot(0, lambda: self._toolbar(item))

    def mates_menu(self, item, at=None):
        """The component's mates under its Mates button; picking one selects the mate (its row
        lights up and its pop-up toolbar comes, as a pick in the tree)."""
        crumb = self.trail.crumb_of(item) if alive(self.trail) else None
        menu = QtWidgets.QMenu(self.shell.window)
        menu.setObjectName("FW_BreadcrumbMates")
        for j in component_mates(item.obj):
            act = menu.addAction(obj_icon(j), _label(j))
            act.triggered.connect(lambda checked=False, jj=j: self._pick_mate(jj))
        self.mates_menus = getattr(self, "mates_menus", 0) + 1
        self.last_menu = menu
        if at is None and crumb is not None:
            at = crumb.mapToGlobal(QtCore.QPoint(0, crumb.height() + 2))
        if at is not None and not getattr(self, "no_exec", False):
            menu.popup(at)
        return menu

    def _pick_mate(self, joint):
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(joint.Document.Name, joint.Name)
        except Exception as error:
            self.error = error

    def _toolbar(self, item):
        context = getattr(self.shell, "context", None)
        if context is None or not alive(getattr(context, "bar", None)) or not alive(self.trail):
            return
        try:
            mode, entries = contextbar.entries_for_selection(self.shell)
        except Exception as error:
            self.error = error
            return
        crumb = self.trail.crumb_of(item)        # the row was filled again for the new pick
        if not entries or crumb is None:
            return
        pos = crumb.mapToGlobal(QtCore.QPoint(crumb.width() // 2, crumb.height() + 2))
        context.popup(mode, entries, pos)
        self.toolbars += 1

    def menu(self, item, global_pos):
        """A right-click on a button: the item's shortcut menu, as on its tree row (fmmenu).
        The part crumb gives the document's menu, as the tree's top row; the Mates crumb its list;
        a relation's gives Delete."""
        if item.kind == "mates":
            return self.mates_menu(item, global_pos)
        sketch = contextbar.sketch_in_edit()
        if sketch is not None:
            return self.sketch_menu(sketch, item, global_pos)
        if item.kind == "relation":
            return self.relation_menu(item, global_pos)
        if item.kind in ELEMENTS:
            menu = self.element_menu(item, global_pos)
            if menu is not None:
                return menu
        if item.kind == "part" or item.obj is None:
            doc = App.ActiveDocument
            if doc is None:
                return None
            self.menus = getattr(self, "menus", 0) + 1
            try:
                from . import fmmenu
                return fmmenu.show(self.shell, doc, global_pos)
            except Exception as error:
                self.error = error
                return None
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(item.obj.Document.Name, item.obj.Name, item.sub or "")
        except Exception as _fw_err:
            _fw_log("breadcrumbs.py:806", _fw_err)
        self.menus = getattr(self, "menus", 0) + 1
        try:
            from . import fmmenu
            return fmmenu.show(self.shell, item.obj, global_pos)
        except Exception as error:
            self.error = error
            return None

    def _picked(self, item):
        """(doc, object, element path, (x, y, z)) of the current pick when it is the item's, as
        partmenu takes it (in an assembly the path runs from the assembly down)."""
        try:
            for s in Gui.Selection.getSelectionEx("", 0):
                subs = list(s.SubElementNames)
                if len(subs) != 1 or subs[0].split(".")[-1] != (item.sub or "").split(".")[-1]:
                    continue
                pts = list(getattr(s, "PickedPoints", []) or [])
                xyz = (pts[0].x, pts[0].y, pts[0].z) if pts else (0.0, 0.0, 0.0)
                return (s.DocumentName, s.ObjectName, subs[0], xyz)
        except Exception as _fw_err:
            _fw_log("breadcrumbs.py:picked", _fw_err)
        try:
            return (item.obj.Document.Name, item.obj.Name, item.sub or "", (0.0, 0.0, 0.0))
        except Exception:
            return None

    def element_menu(self, item, global_pos):
        """A right-click on the face, edge or vertex button: that element's menu, the same one a
        right-click on it in the graphics area gives (partmenu; asmviewmenu in an assembly)."""
        target = self._picked(item)
        if target is None:
            return None
        try:
            from . import partmenu, rcmenus
            if not partmenu.enabled():
                return None
            self.menus = getattr(self, "menus", 0) + 1
            if partmenu.in_assembly():
                from . import asmviewmenu
                return asmviewmenu.show_view_menu(global_pos, target)
            partmenu.pick(target)
            name = "Part" + partmenu._leaf(target[2]).rstrip("0123456789")
            partmenu._LAST_POS[:] = [QtCore.QPoint(global_pos)]
            return rcmenus.show(rcmenus.Builder(name, partmenu.items(target) + [partmenu._freecad_item()],
                                                row=partmenu.row(target), chevron=True), global_pos)
        except Exception as error:
            self.error = error
            return None

    def sketch_menu(self, sketch, item, global_pos):
        """Inside a sketch: the sketch button gives the sketch's tree menu; the line, point or
        relation button gives the menu a right-click on that entity or relation glyph gives."""
        if item.kind == "sketch":
            self.menus = getattr(self, "menus", 0) + 1
            try:
                from . import fmmenu
                return fmmenu.show(self.shell, sketch, global_pos)
            except Exception as error:
                self.error = error
                return None
        try:
            from . import rcmenus
            path = (sketch.Document.Name, sketch.Name, item.sub or "")
            element = rcmenus._sketch_element(sketch, path) or item.sub
            self.menus = getattr(self, "menus", 0) + 1
            rcmenus.sketch_menu(sketch, path + (element,), global_pos)
            return rcmenus.LAST[0] if rcmenus.LAST else True
        except Exception as error:
            self.error = error
            if item.kind == "relation":
                return self.relation_menu(item, global_pos)
            return None

    def relation_menu(self, item, global_pos, popup=True):
        menu = QtWidgets.QMenu(self.shell.window)
        menu.setObjectName("SWBreadcrumbRelationMenu")
        menu.addAction("Delete", lambda it=item: self.delete_relation(it))
        self.menus = getattr(self, "menus", 0) + 1
        if popup:
            menu.popup(global_pos)
        return menu

    def delete_relation(self, item):
        sketch = item.obj
        try:
            index = int(item.sub[len("Constraint"):]) - 1
            doc = sketch.Document
            doc.openTransaction("Delete Relation")
            try:
                sketch.delConstraint(index)
            except BaseException:
                try:
                    doc.abortTransaction()
                except Exception:
                    pass
                raise
            doc.commitTransaction()
            sketch.recompute()
        except Exception as error:
            self.error = error
            return False
        self._sig = None
        self.soon()
        return True

    def hover(self, item, on):
        """The pointer over a button lights its item up in the 3D view, as over a tree row."""
        if item.kind == "part" or item.obj is None:
            return
        try:
            if on:
                Gui.Selection.setPreselection(item.obj, item.sub or "")
                return
            for name in ("removePreselection", "clearPreselection"):
                clear = getattr(Gui.Selection, name, None)
                if clear is not None:
                    clear()
                    return
        except Exception as _fw_err:
            _fw_log("breadcrumbs.py:854", _fw_err)

    def remove(self):
        if self.observer is not None:
            try:
                Gui.Selection.removeObserver(self.observer)
            except Exception as _fw_err:
                _fw_log("breadcrumbs.py:861", _fw_err)
            self.observer = None
        if self.mdi is not None:
            try:
                self.mdi.subWindowActivated.disconnect(self.soon)
            except Exception as _fw_err:
                _fw_log("breadcrumbs.py:867", _fw_err)
        if alive(self.trail):
            self.trail.hide()
            self.trail.setParent(None)
            self.trail.deleteLater()
