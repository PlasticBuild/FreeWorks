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

from .widgets import alive

Qt = QtCore.Qt
CELL = 20            # px per column
COLUMNS = ("hide", "mode", "appearance", "transparency")
TIPS = {"hide": "Hide/Show", "mode": "Display Mode", "appearance": "Appearance", "transparency": "Transparency"}

MODES = (("Wireframe", "Wireframe"), ("Shaded With Edges", "Flat Lines"), ("Shaded", "Shaded"),
         ("Default", None))
DATUMS = ("App::Plane", "PartDesign::Plane", "App::Line", "PartDesign::Line", "App::Point", "PartDesign::Point",
          "PartDesign::CoordinateSystem", "App::LocalCoordinateSystem")
BODY = "PartDesign::Body"


def _type(obj):
    try:
        return obj.TypeId
    except Exception:
        return ""


def _solid_feature(obj):
    t = _type(obj)
    return t.startswith("PartDesign::") and t != BODY and hasattr(obj, "BaseFeature")


def _curve(obj):
    ""

    try:
        from . import viewtypes
        return bool(viewtypes.TYPES["Curves"][2](obj))
    except Exception:
        return False


def _solid_row(obj):
    try:
        from . import multibody
        return getattr(getattr(obj, "Proxy", None), "Type", None) == multibody.ROW_TYPE
    except Exception:
        return False


class _Many(object):
    ""


    def __init__(self, items):
        self.items = list(items)
        self.Document = self.items[0].Document
        self.TypeId = "SWStyle::PartRow"

    @property
    def ViewObject(self):
        return _ManyView(self.items)


class _ManyView(object):
    def __init__(self, items):
        object.__setattr__(self, "_items", items)

    def __getattr__(self, name):
        return getattr(self._items[0].ViewObject, name)

    def __setattr__(self, name, value):
        for o in self._items:
            try:
                vo = o.ViewObject
                if name == "DisplayMode" and value not in vo.listDisplayModes():
                    continue
                setattr(vo, name, value)
            except Exception as _fw_err:
                _fw_log("displaypane.py:many", _fw_err)


def _loose_root(obj):
    """A solid outside any Body that no other shape uses (a Part primitive, a Boolean's result, an
    imported shape): one of the part's bodies."""
    try:
        if not obj.isDerivedFrom("Part::Feature") or obj.isDerivedFrom("Part::Part2DObject"):
            return False
        if _type(obj) in DATUMS or _solid_row(obj) or obj.ViewObject is None:
            return False
        from . import appearance
        if not appearance.own_body(obj):
            return False
        # used by a Boolean, an extrusion ... : that one is the body, this is its input
        return not any(p.isDerivedFrom("Part::Feature") for p in obj.InList)
    except Exception:
        return False


def part_items(doc):
    """The bodies the part row stands for when the part has no single Body (look audit BB29 DP-1)."""
    out = []
    try:
        objs = doc.Objects if doc is not None else []
    except (ReferenceError, RuntimeError):
        return out      # dpclose-1127: the document closed while the pane painted it
    for o in objs:
        t = _type(o)
        if t == BODY or _loose_root(o):
            out.append(o)
    return out


def _part_row_object(fm):
    if fm.flat is not None:
        return fm.flat
    items = part_items(getattr(fm, "doc", None) or App.ActiveDocument)
    if not items:
        return None
    return items[0] if len(items) == 1 else _Many(items)


def cells(view, node):
    ""
    fm = view.fm
    if node is None or node.link:
        return {}
    obj, level = node.obj, None
    if node is fm.part:
        obj, level = _part_row_object(fm), "part"
        if obj is None:
            return {}
        if fm.flat is None:

            return {"mode": (obj, None), "appearance": (obj, level), "transparency": (obj, None)}
    if obj is None:
        return {}
    t = _type(obj)
    out = {}
    if _solid_row(obj):
        # a body in the Solid Bodies folder: its eye and its colour (multibody keeps both on the row;
        # the eye hides the body on screen since features/349)
        try:
            from . import multibody
            fixed = hasattr(multibody, "without_hidden")     # features/349 is in
        except Exception:
            fixed = False
        return {"hide": (obj, None), "appearance": (obj, "row")} if fixed else {"appearance": (obj, "row")}
    if t == BODY:
        level = level or "body"
        out = {"hide": (obj, None), "mode": (obj, None), "appearance": (obj, level), "transparency": (obj, None)}
        if level == "part":
            del out["hide"]
    elif t == "Sketcher::SketchObject" or t in DATUMS or _curve(obj):
        out = {"hide": (obj, None)}
    elif _solid_feature(obj) or _loose_root(obj):

        out = {"appearance": (obj, "feature")}
    return out


def _origin_of(obj):
    try:
        from . import originaxes
        return originaxes._origin_of(obj)
    except Exception:
        return None


def shown(obj):
    """On screen: FreeCAD keeps an origin's planes, axes and point at Visibility on while the Origin
    itself is hidden, so they count as shown only when their Origin is shown too."""
    try:
        if not obj.ViewObject.Visibility:
            return False
        origin = _origin_of(obj)
        return origin is None or origin.ViewObject is None or bool(origin.ViewObject.Visibility)
    except Exception:
        return False


def mode(obj):
    try:
        return obj.ViewObject.DisplayMode
    except Exception:
        return ""


def transparent(obj):
    try:
        return obj.ViewObject.Transparency >= 50
    except Exception:
        return False


def colour(obj, level):
    if isinstance(obj, _Many):
        obj = obj.items[0]
    if level == "row":
        # a Solid Bodies row: its own colour, else the colour the solid shows (its Body's), so the
        # row always draws its appearance circle (look audit AP1, 11-21)
        try:
            if obj.UseColour:
                return tuple(obj.Colour[:3]) + (0.0,)
            body = obj.Document.getObject(obj.Body) if obj.Body else None
        except Exception:
            return None
        return colour(body, "body") if body is not None else None
    try:
        from . import appearance
        target = appearance.target_for(level, obj, "")
        if target is not None:
            return appearance.current_colour(target)
    except Exception as _fw_err:
        _fw_log("displaypane.py:140", _fw_err)
    try:
        m = obj.ViewObject.ShapeAppearance[0]
        return tuple(m.DiffuseColor[:3]) + (m.Transparency,)
    except Exception:
        return None


# ---- what a click does (also called by checks)
def toggle_hide(obj):
    on = not shown(obj)
    origin = _origin_of(obj)
    if origin is None or origin.ViewObject is None:
        obj.ViewObject.Visibility = on
        return
    # an origin plane, axis or point: show that one item (its Origin with it), as Hide/Show Items does
    from . import originaxes
    originaxes.allow(obj, on)
    originaxes._guard.append(1)
    try:
        if on and not origin.ViewObject.Visibility:
            for f in origin.OriginFeatures:
                f.ViewObject.Visibility = f is obj
            origin.ViewObject.Visibility = True
        else:
            obj.ViewObject.Visibility = on
    finally:
        originaxes._guard.pop()
    if originaxes._active is not None:
        originaxes._active.soon()


def set_mode(obj, freecad_mode):
    vo = obj.ViewObject
    if freecad_mode is None:
        freecad_mode = "Flat Lines"
    if freecad_mode in vo.listDisplayModes():
        vo.DisplayMode = freecad_mode


def toggle_transparency(obj):
    obj.ViewObject.Transparency = 0 if transparent(obj) else 75


def edit_appearance(obj, level):
    if level == "row":
        from . import multibody
        return multibody.pick_colour(obj)
    from . import appearance
    items = obj.items if isinstance(obj, _Many) else [obj]
    return appearance.open_page(obj.Document, level, [(o, "") for o in items])


def _target(obj, level):
    """The appearance target of a Display Pane row (part, body or feature), or None."""
    if level not in ("part", "body", "feature"):
        return None
    try:
        from . import appearance
        if isinstance(obj, _Many):
            obj = obj.items[0]
        if level == "part":
            body = obj if obj.TypeId == BODY else appearance.body_of(obj)
            return appearance.Target("part", body) if body is not None else appearance.target_for("part", obj, "")
        return appearance.target_for(level, obj, "")
    except Exception as _fw_err:
        _fw_log("displaypane.py:target", _fw_err)
        return None


class Pane(QtWidgets.QWidget):
    """The cells, in the tree's right margin."""

    def __init__(self, view):
        super().__init__(view)
        self.setObjectName("SWDisplayPane")
        self.view = view
        self.setMouseTracking(True)
        self.k = max(1.0, view.fontMetrics().height() / 16.0)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)          # visibility and colours change outside the tree too
        self.timer.timeout.connect(self.update)
        view.verticalScrollBar().valueChanged.connect(self.update)
        view.expanded.connect(self.update)
        view.collapsed.connect(self.update)
        view.fm.rebuilt.connect(self.update)
        self.hide()

    def width_needed(self):
        return int(CELL * self.k) * len(COLUMNS)

    def header_needed(self):
        """The strip over the rows with the column headings (and the << button)."""
        return int(CELL * self.k) + 2

    def place(self):
        view = self.view
        vp = view.viewport().geometry()
        w, h = self.width_needed(), self.header_needed()
        self.setGeometry(vp.right() + 1, vp.top() - h, w, vp.height() + h)

    def rows(self):
        """(model index, top, height) of the rows on screen, in the pane's own coordinates."""
        view = self.view
        out = []
        index = view.indexAt(QtCore.QPoint(1, 1))
        h = view.viewport().height()
        off = self.header_needed()
        while index.isValid():
            r = view.visualRect(index)
            if r.top() > h:
                break
            out.append((index, r.top() + off, r.height()))
            index = view.indexBelow(index)
        return out

    def cell_point(self, index, column):
        """The middle of a row's cell, in the pane's coordinates (checks click there)."""
        r = self.view.visualRect(index)
        w = int(CELL * self.k)
        return QtCore.QPoint(COLUMNS.index(column) * w + w // 2, r.center().y() + self.header_needed())

    def cell_at(self, pos):
        c = int(pos.x() // int(CELL * self.k))
        if c < 0 or c >= len(COLUMNS):
            return None, None
        for index, top, height in self.rows():
            if top <= pos.y() < top + height:
                return index, COLUMNS[c]
        return None, None

    # ---- drawing
    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pal = self.view.palette()
        p.fillRect(self.rect(), pal.base())
        line = QtGui.QColor(pal.mid().color())
        p.setPen(line)
        p.drawLine(0, 0, 0, self.height())
        w = int(CELL * self.k)
        text = pal.text().color()
        # the headings: the same marks the cells use, greyed
        head = QtGui.QColor(text)
        head.setAlphaF(0.55)
        hh = self.header_needed()
        p.drawLine(0, hh - 1, self.width(), hh - 1)

        # has to sit in the heading strip itself (no tab row) is the last heading under it
        under = getattr(self.view, "_dp_button_in_strip", False)
        for c, column in enumerate(COLUMNS[:-1] if under else COLUMNS):
            rect = QtCore.QRectF(c * w + 3, (hh - (w - 6)) / 2.0, w - 6, w - 6)
            self._heading(p, column, rect, head)
        for index, top, height in self.rows():
            node = self.view.fm.node(index)
            for c, column in enumerate(COLUMNS):
                try:
                    got = cells(self.view, node).get(column)
                except Exception as _fw_err:     # dpclose-1127: a row of a document closing under the paint
                    _fw_log("displaypane.py:paint-cells", _fw_err)
                    got = None
                if got is None:
                    continue
                rect = QtCore.QRectF(c * w + 3, top + (height - (w - 6)) / 2.0, w - 6, w - 6)
                self._draw(p, column, got, rect, text)
        p.end()

    def _heading(self, p, column, rect, colour):
        p.setPen(QtGui.QPen(colour, 1.2))
        p.setBrush(Qt.NoBrush)
        c = rect.center()
        if column == "hide":
            p.drawEllipse(c, rect.width() / 2.2, rect.height() / 4.0)
            p.setBrush(colour)
            p.drawEllipse(c, rect.width() / 7.0, rect.height() / 7.0)
        elif column == "mode":
            p.drawRect(rect.adjusted(2, 2, -2, -2))
        elif column == "appearance":
            p.drawEllipse(rect.adjusted(2, 2, -2, -2))
        elif column == "transparency":
            # a square seen through another: the see-through mark
            r = rect.adjusted(2, 2, -2, -2)
            k = r.width() * 0.32
            p.drawRect(r.adjusted(0, 0, -k, -k))
            p.drawRect(r.adjusted(k, k, 0, 0))

    def _draw(self, p, column, got, rect, text):
        obj, level = got
        pen = QtGui.QPen(text, 1.2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if column == "hide":
            eye = QtGui.QPainterPath()
            c = rect.center()
            eye.moveTo(rect.left(), c.y())
            eye.quadTo(c.x(), rect.top(), rect.right(), c.y())
            eye.quadTo(c.x(), rect.bottom(), rect.left(), c.y())
            p.drawPath(eye)
            if shown(obj):
                p.setBrush(text)
                p.drawEllipse(c, rect.width() / 6.0, rect.height() / 6.0)
            else:
                p.drawLine(rect.topLeft(), rect.bottomRight())
        elif column == "mode":
            m = mode(obj)
            box = rect.adjusted(2, 2, -2, -2)
            if m in ("Shaded", "Flat Lines"):
                p.setBrush(QtGui.QColor(150, 155, 170))
            p.setPen(QtGui.QPen(text, 1.6 if m != "Shaded" else 0.0) if m != "Shaded" else Qt.NoPen)
            p.drawRect(box)
        elif column == "appearance":
            rgbt = colour(obj, level)
            if rgbt is not None:
                p.setBrush(QtGui.QColor.fromRgbF(rgbt[0], rgbt[1], rgbt[2]))
                p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        elif column == "transparency":
            box = rect.adjusted(2, 2, -2, -2)
            p.drawRect(box)
            fill = QtGui.QColor(text)
            fill.setAlphaF(0.25 if transparent(obj) else 1.0)
            p.fillRect(box.adjusted(2, 2, -2, -2), fill)

    # ---- clicks
    def mouseMoveEvent(self, event):
        index, column = self.cell_at(event.position())
        tip = ""
        if index is not None and cells(self.view, self.view.fm.node(index)).get(column):
            tip = TIPS[column]
        self.setToolTip(tip)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._right_click(event)
            return
        if event.button() != Qt.LeftButton:
            return
        index, column = self.cell_at(event.position())
        if index is None:
            return
        got = cells(self.view, self.view.fm.node(index)).get(column)
        if got is None:
            return
        obj, level = got
        try:
            if column == "hide":
                toggle_hide(obj)
            elif column == "transparency":
                toggle_transparency(obj)
            elif column == "appearance":
                edit_appearance(obj, level)
            elif column == "mode":
                self.mode_menu(obj).popup(event.globalPosition().toPoint())
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Display Pane: %s\n" % error)
        self.update()
        event.accept()

    def _right_click(self, event):
        ""

        index, column = self.cell_at(event.position())
        got = cells(self.view, self.view.fm.node(index)).get(column) if index is not None else None
        if column != "appearance" or got is None:
            return
        obj, level = got
        menu = self.appearance_menu(obj, level)
        if menu is not None and menu.actions():
            menu.popup(event.globalPosition().toPoint())
        event.accept()

    def appearance_menu(self, obj, level):
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWDisplayPaneAppearanceMenu")
        a = menu.addAction("Edit Appearance...")
        a.triggered.connect(lambda checked=False: (edit_appearance(obj, level), self.update()))
        target = _target(obj, level)
        if target is not None:
            from . import appearance
            if appearance.has_own(target):
                r = menu.addAction("Remove Appearance")
                r.setObjectName("SWDisplayPaneRemoveAppearance")
                r.triggered.connect(lambda checked=False, t=target: (
                    appearance.remove_with_undo(t.body.Document, [t]), self.update()))
        return menu

    def mode_menu(self, obj):
        menu = QtWidgets.QMenu(self)
        menu.setObjectName("SWDisplayModeMenu")
        now = mode(obj)
        for label, freecad_mode in MODES:
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(freecad_mode == now)
            a.triggered.connect(lambda checked=False, m=freecad_mode: (set_mode(obj, m), self.update()))
        return menu


class Toggle(QtWidgets.QToolButton):
    """The >> / << button at the top right of the tree."""

    def __init__(self, view, pane):
        super().__init__(view)
        self.setObjectName("SWDisplayPaneButton")
        self.view, self.pane = view, pane
        self.setAutoRaise(True)
        self.setToolTip("Show Display Pane")
        self.setText(">")
        self.clicked.connect(self.flip)

    def flip(self):
        set_open(self.view, not self.pane.isVisible())


def set_open(view, on):
    pane, button = view._display_pane
    view._pane_margin = pane.width_needed() if on else 0
    view._pane_top = pane.header_needed() if on else 0
    view.setViewportMargins(0, view._pane_top, view._pane_margin, 0)
    view.updateGeometries()
    pane.setVisible(on)
    if on:
        pane.place()
        pane.raise_()
        pane.timer.start()
    else:
        pane.timer.stop()
    button.setText("<" if on else ">")
    button.setToolTip("Hide Display Pane" if on else "Show Display Pane")
    place_button(view)


def _tab_header(view):
    """The manager tabs above the tree (leftpane.PaneHeader), or None."""
    w = view.parentWidget()
    while w is not None:
        for c in w.findChildren(QtWidgets.QWidget, options=Qt.FindDirectChildrenOnly):
            if type(c).__name__ == "PaneHeader":
                return c
        w = w.parentWidget()
    return None


def place_button(view):
    pane, button = view._display_pane
    header = _tab_header(view)
    if header is not None:

        if button.parent() is not header:
            button.setParent(header)
        k = getattr(header, "k", 1.0)
        top = getattr(header, "TAB_TOP", 22.0) * k
        side = int(round(getattr(header, "TAB_H", 25.0) * k))
        button.setGeometry(header.width() - int(round(16 * k)) - 2, int(round(top)), int(round(16 * k)), side)
        button.setVisible(view.isVisible())
        button.raise_()
        if getattr(view, "_dp_button_in_strip", False):
            view._dp_button_in_strip = False
            pane.update()
        return
    size = button.sizeHint()
    vp = view.viewport().geometry()
    view._dp_button_in_strip = True
    if pane.isVisible():     # in the heading strip, over the Transparency column
        side = pane.header_needed()
        button.setGeometry(vp.right() + pane.width_needed() - side + 1, vp.top() - side, side, side)
    else:
        button.setGeometry(vp.right() - size.width(), vp.top(), size.width(), size.height())
    button.raise_()


class _Resize(QtCore.QObject):
    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show, QtCore.QEvent.Hide):
            view = obj
            if hasattr(view, "_display_pane") and alive(view):
                pane, _button = view._display_pane
                if pane.isVisible():
                    pane.place()
                place_button(view)
        return False


def attach(view):
    ""
    if getattr(view, "_display_pane", None) is not None:
        return
    pane = Pane(view)
    button = Toggle(view, pane)
    view._display_pane = (pane, button)
    view._display_resize = _Resize(view)
    view.installEventFilter(view._display_resize)
    place_button(view)
