# SPDX-License-Identifier: LGPL-2.1-or-later
""







import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .widgets import alive, scaled

Qt = QtCore.Qt
PARENT = QtGui.QColor(0, 102, 204)
CHILD = QtGui.QColor(128, 0, 160)
# links that are not a "built on" (the body holding a feature, an origin, the tip)
SKIP_TYPES = ("App::Origin", "PartDesign::Body", "App::Part", "App::DocumentObjectGroup")


def wanted(kind):
    try:
        from . import uiextras
        return uiextras.reference_visualization(kind)
    except Exception:
        return False


ORDER_ONLY = ("BaseFeature", "_Body", "Tip", "Group", "Origin", "ExpressionEngine")


def _links(value):
    if value is None:
        return []
    if isinstance(value, App.DocumentObject):
        return [value]
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            out += _links(v)
        return out
    return []


def refers(obj, other):
    """obj is built on other through something other than the tree order (BaseFeature)."""
    for prop in obj.PropertiesList:
        if prop in ORDER_ONLY:
            continue
        try:
            if obj.getTypeIdOfProperty(prop).startswith("App::PropertyLink") and \
                    any(v is other for v in _links(getattr(obj, prop))):
                return True
        except Exception:
            continue
    return False


def _once(objects):
    from .multibody import is_helper
    seen, out = set(), []
    for o in objects:
        if o.Name not in seen and not is_helper(o):
            seen.add(o.Name)
            out.append(o)
    return out


def _linked_parents(obj):
    return [o for o in getattr(obj, "OutList", []) if o.TypeId not in SKIP_TYPES and o is not obj and refers(obj, o)]


def _made_by(obj, linked):
    ""


    try:
        from . import suppress
        raw = suppress._raw_links(obj)
        owners = suppress._links(obj)
    except Exception:
        return linked
    picked, plain = set(), set()
    for target, subs in raw:
        if subs and suppress._solid_feature(target) and any(x for x in subs):
            picked.add(target.Name)
        else:
            plain.add(target.Name)
    out = [o for o in linked if o.Name not in picked or o.Name in plain or o in owners]
    for o in owners:
        if o not in out and o is not obj and o.TypeId not in SKIP_TYPES and suppress._solid_feature(o):
            out.append(o)
    return out


def parents(obj):
    return _once(_made_by(obj, _linked_parents(obj)))


def children(obj):
    users = [o for o in getattr(obj, "InList", []) if o.TypeId not in SKIP_TYPES and o is not obj and refers(o, obj)]
    try:
        from . import suppress
        users += [o for o in suppress._children(obj) if o not in users and o.TypeId not in SKIP_TYPES and o is not obj]
    except Exception:
        return _once(users)
    return _once(o for o in users if obj in _made_by(o, _linked_parents(o)))


class Arrows(QtWidgets.QWidget):
    def __init__(self, tree):
        super().__init__(tree.viewport())
        self.setObjectName("SWReferenceArrows")
        self.tree = tree
        self.hovered = None          # the object under the pointer
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        tree.viewport().setMouseTracking(True)
        tree.viewport().installEventFilter(self)
        self.resize(tree.viewport().size())
        self.show()

    def _obj(self, index):
        node = self.tree.fm.node(index) if index.isValid() else None
        return getattr(node, "obj", None)

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        t = event.type()
        if t == QtCore.QEvent.Resize:
            self.resize(event.size())
        elif t in (QtCore.QEvent.MouseMove, QtCore.QEvent.HoverMove):
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            self.hover_at(pos)
        elif t == QtCore.QEvent.Leave:
            self.hover(None)
        elif t == QtCore.QEvent.Paint:
            self.raise_()
        return False

    def hover_at(self, pos):
        self.hover(self._obj(self.tree.indexAt(pos)))

    def hover(self, obj):
        if obj is not self.hovered:
            self.hovered = obj
            self.update()

    def rows_of(self, objects):
        """[(rect)] of the shown rows of these objects."""
        names = {o.Name for o in objects}
        out = []
        for index in self.tree.fm_shown() if hasattr(self.tree, "fm_shown") else []:
            obj = self._obj(index)
            if obj is not None and obj.Name in names and not getattr(self.tree.fm.node(index), "link", False):
                r = self.tree.visualRect(index)
                if r.isValid() and r.height():
                    out.append(r)
        return out

    def lines(self):
        """[(row y, [(target y, colour)])] for checks and for painting."""
        obj = self.hovered
        if obj is None:
            return None
        here = self.rows_of([obj])
        if not here:
            return None
        y0 = here[0].center().y()
        out = []
        if wanted("Parent"):
            out += [(r.center().y(), PARENT) for r in self.rows_of(self._through(obj, parents(obj), parents))]
        if wanted("Child"):
            out += [(r.center().y(), CHILD) for r in self.rows_of(self._through(obj, children(obj), children))]
        return y0, out

    def _through(self, obj, related, step):
        ""

        out = []
        for o in related:
            if o.TypeId == "Sketcher::SketchObject" and not self.rows_of([o]):
                out += [x for x in step(o) if x is not obj and x not in related]
            else:
                out.append(o)
        return out

    def _ends(self):
        """{row centre y: x where the row's text ends} of the shown rows (drv-1120b)."""
        out = {}
        try:
            fm = self.tree.fontMetrics()
            for index in self.tree.fm_shown() if hasattr(self.tree, "fm_shown") else []:
                r = self.tree.visualRect(index)
                if r.isValid() and r.height():
                    text = str(index.data(Qt.DisplayRole) or "")
                    out[r.center().y()] = r.left() + scaled(24) + fm.horizontalAdvance(text) + scaled(6)
        except Exception as _fw_err:
            App.Console.PrintLog("FreeWorks reference arrows: %s\n" % _fw_err)
        return out

    def paintEvent(self, event):
        got = self.lines()
        if not got:
            return
        y0, targets = got
        ends = self._ends()
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        xr = self.width() - scaled(12)
        x0 = min(ends.get(y0, xr - scaled(40)), xr - scaled(10))
        grey = QtGui.QColor(110, 110, 110)
        p.setPen(QtGui.QPen(grey, 1, Qt.DotLine))
        p.drawLine(QtCore.QPointF(x0, y0), QtCore.QPointF(xr - scaled(3), y0))
        p.setPen(QtGui.QPen(grey, 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QtCore.QPointF(xr, y0), scaled(3), scaled(3))
        bend = scaled(5)
        for y1, colour in targets:
            if abs(y1 - y0) < 1:
                continue
            down = y1 > y0
            sign = 1 if down else -1
            tip = max(ends.get(y1, xr - scaled(40)) + scaled(2), scaled(20))
            tip = min(tip, xr - bend - scaled(8))
            p.setPen(QtGui.QPen(colour, scaled(1.6)))
            path = QtGui.QPainterPath(QtCore.QPointF(xr, y0 + sign * scaled(3)))
            path.lineTo(xr, y1 - sign * bend)
            path.quadTo(xr, y1, xr - bend, y1)
            path.lineTo(tip + scaled(6), y1)
            p.drawPath(path)
            head = QtGui.QPolygonF([QtCore.QPointF(tip, y1), QtCore.QPointF(tip + scaled(7), y1 - scaled(3.5)),
                                    QtCore.QPointF(tip + scaled(7), y1 + scaled(3.5))])
            p.setBrush(colour)
            p.drawPolygon(head)
            p.setBrush(Qt.NoBrush)
        p.end()


ATTACHED = {}      # id(tree) -> Arrows
_timer = [None]


def _tick():
    try:
        from . import fmtree
        for tree in Gui.getMainWindow().findChildren(fmtree.FeatureTree):
            arrows = ATTACHED.get(id(tree))
            if arrows is not None and alive(arrows):
                continue
            if not (wanted("Parent") or wanted("Child")):
                continue
            ATTACHED[id(tree)] = Arrows(tree)
        for key, arrows in list(ATTACHED.items()):
            if not alive(arrows):
                ATTACHED.pop(key, None)
    except Exception as error:
        App.Console.PrintLog("FreeCAD reference arrows: %s\n" % error)


def install():
    if _timer[0] is None:
        _timer[0] = QtCore.QTimer()
        _timer[0].setInterval(1000)
        _timer[0].timeout.connect(_tick)
        _timer[0].start()
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(_timer[0])
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)


def arrows_for(tree):
    return ATTACHED.get(id(tree))
