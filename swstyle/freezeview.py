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
from PySide import QtCore, QtGui, QtWidgets

from . import freezebar, rollbackbar
from .widgets import alive

Qt = QtCore.Qt


BAR = QtGui.QColor(245, 196, 0)
BAR_PX = 3
ROW = QtGui.QColor(255, 226, 90, 70)     # frozen rows, over the tree's own background
GRAB = 3                                 # px from the bar's middle where the hand pointer takes it
TICK = 250


class Layout:
    """One body as the tree shows it: where its freeze bar is and where it may go."""
    __slots__ = ("doc", "body", "bar_y", "gaps", "rows")

    def __init__(self, doc, body, bar_y, gaps, rows):
        self.doc, self.body = doc, body
        self.bar_y = bar_y       # viewport y of the gap the bar stands for
        self.gaps = gaps         # [(y, last frozen feature or None)]
        self.rows = rows         # [(top, bottom)] of the frozen rows

    def key(self):
        return (self.doc.Name, self.body.Name)


def layout(tree, doc, body, index):
    """Where the body's freeze bar goes, or None while the body is folded or out of sight."""
    if not tree.isExpanded(index) or rollbackbar._shown(tree, index) is None:
        return None
    items = freezebar.features(body)
    order = {obj.Name: k for k, obj in enumerate(items)}
    children = rollbackbar.body_children(tree, body, index)
    shown = []
    for child, obj, back in children:
        rect = rollbackbar._shown(tree, child)
        if rect is not None:
            shown.append((obj, back, rect.top(), rollbackbar._bottom(tree, child)))
    if not shown:
        return None
    gaps = [(shown[0][2], None)]
    rows = []
    for obj, back, top, bottom in shown:
        if obj is None or obj.Name not in order:
            continue
        if freezebar.frozen(obj):
            rows.append((top, bottom))
        if not back:
            gaps.append((bottom + 1, obj))
    last = freezebar.bar(body)
    bar_y = gaps[0][0]
    if last is not None:
        at = order.get(last.Name, -1)
        for y, obj in gaps[1:]:
            if order.get(obj.Name, -1) <= at:
                bar_y = y
    return Layout(doc, body, bar_y, gaps, rows)


def layouts(tree):
    out = []
    for doc, body, index in rollbackbar.body_rows(tree):
        try:
            lay = layout(tree, doc, body, index)
        except Exception:
            lay = None
        if lay is not None:
            out.append(lay)
    return out


def _top(y):
    """The bar's top edge for a gap at y: just above it."""
    return max(0, y - BAR_PX)


class Overlay(QtWidgets.QWidget):
    """Paints the bars and the frozen rows over the tree's viewport (a sibling, as the rollback
    bar's)."""

    def __init__(self, owner, tree):
        super().__init__(tree)
        self.owner = owner
        self.tree = tree
        self.setObjectName("SWFreezeBar")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.place()
        self.show()
        self.raise_()

    def place(self):
        viewport = self.tree.viewport()
        if self.geometry() != viewport.geometry():
            self.setGeometry(viewport.geometry())
        self.raise_()

    def paintEvent(self, event):
        try:
            bars, rows = self.owner.shown(self.tree)
        except Exception:
            return
        if not bars and not rows:
            return
        painter = QtGui.QPainter(self)
        width = self.width()
        for top, bottom in rows:
            painter.fillRect(QtCore.QRectF(0, top, width, bottom - top + 1), ROW)
        for y in bars:
            painter.fillRect(QtCore.QRectF(0, _top(y), width, BAR_PX), BAR)
        painter.end()


class FreezeBar(QtCore.QObject):
    """The freeze bars on the tree the rollback bar uses, while the Options setting is on."""

    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.tree = None
        self.overlay = None
        self.drag = None             # (body key, gaps, preview (y, feature)) while the bar is dragged
        self._cursor = False
        self._sig = None
        self.drags = 0               # for checks
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(TICK)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.tick()

    def _find_tree(self):
        bar = getattr(self.shell, "rollback", None)
        if bar is not None:
            try:
                return bar._find_tree()
            except Exception as _fw_err:
                _fw_log("freezeview.py:166", _fw_err)
        return None

    def attach(self, tree):
        if tree is self.tree and self.overlay is not None and alive(self.overlay):
            self.overlay.place()
            return
        self.detach()
        self.tree = tree
        self.overlay = Overlay(self, tree)
        tree.installEventFilter(self)
        tree.viewport().installEventFilter(self)
        tree.verticalScrollBar().valueChanged.connect(self._repaint)

    def detach(self):
        tree, overlay = self.tree, self.overlay
        self.drag = None
        if tree is not None and alive(tree):
            self._set_cursor(tree.viewport(), False)
            tree.removeEventFilter(self)
            tree.viewport().removeEventFilter(self)
            try:
                tree.verticalScrollBar().valueChanged.disconnect(self._repaint)
            except Exception as _fw_err:
                _fw_log("freezeview.py:190", _fw_err)
        self.tree = self.overlay = None
        if overlay is not None and alive(overlay):
            overlay.hide()
            overlay.setParent(None)
            overlay.deleteLater()
        self._sig = None

    def _repaint(self, *args):
        if self.overlay is not None and alive(self.overlay):
            self.overlay.update()

    def tick(self):
        if not freezebar.enabled():
            self.detach()
            return
        tree = self._find_tree()
        if tree is None or not alive(tree):
            self.detach()
            return
        self.attach(tree)
        try:
            sig = tuple((lay.key(), lay.bar_y, tuple(lay.rows)) for lay in layouts(tree))
        except Exception:
            sig = None
        sig = (sig, tree.viewport().size().width(), tree.verticalScrollBar().value())
        if sig != self._sig:
            self._sig = sig
            self._repaint()

    def shown(self, tree):
        """The bars' gap y (the dragged one where it would land) and the frozen rows."""
        bars, rows = [], []
        for lay in layouts(tree):
            bar_y = lay.bar_y
            if self.drag is not None and self.drag[0] == lay.key() and self.drag[2] is not None:
                bar_y = self.drag[2][0]
            bars.append(bar_y)
            rows.extend(lay.rows)
        return bars, rows

    # ------------------------------------------------------------ the pointer
    def _at_bar(self, y):
        tree = self.tree
        if tree is None:
            return None
        for lay in layouts(tree):
            middle = _top(lay.bar_y) + BAR_PX / 2.0
            if abs(y - middle) <= GRAB:
                return lay
        return None

    def _set_cursor(self, viewport, on, shape=Qt.OpenHandCursor):
        if on:
            viewport.setCursor(shape)
            self._cursor = True
        elif self._cursor:
            viewport.unsetCursor()
            self._cursor = False

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        tree = self.tree
        if tree is None or not alive(tree):
            return False
        t = event.type()
        if obj is tree:
            if t in (QtCore.QEvent.Resize, QtCore.QEvent.LayoutRequest, QtCore.QEvent.Show):
                if self.overlay is not None and alive(self.overlay):
                    self.overlay.place()
            return False
        if obj is not tree.viewport():
            return False
        try:
            return self._viewport_event(obj, event, t)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: freeze bar: %s\n" % error)
            self.drag = None
            return False

    def _cancel_drag(self, viewport):
        self.drag = None
        self._set_cursor(viewport, False)
        self._repaint()

    def _viewport_event(self, viewport, event, t):
        if t == QtCore.QEvent.Resize:
            if self.overlay is not None and alive(self.overlay):
                self.overlay.place()
            return False
        if t in (QtCore.QEvent.MouseMove, QtCore.QEvent.HoverMove):
            y = event.position().y()
            if self.drag is not None:
                if t == QtCore.QEvent.MouseMove:
                    if not event.buttons() & Qt.LeftButton:
                        self._cancel_drag(viewport)
                        return False
                    self._drag_to(y)
                return True
            if t == QtCore.QEvent.MouseMove and event.buttons() != Qt.NoButton:
                return False
            if self._at_bar(y) is not None and not rollbackbar.editing():
                self._set_cursor(viewport, True)
                return True          # the rollback bar's filter would take the pointer back
            self._set_cursor(viewport, False)
            return False
        if t == QtCore.QEvent.MouseButtonPress:
            if self.drag is not None:
                self._cancel_drag(viewport)
            if event.button() != Qt.LeftButton:
                return False
            lay = self._at_bar(event.position().y())
            if lay is None or rollbackbar.editing():
                return False
            self.drag = (lay.key(), lay.gaps, None)
            self._set_cursor(viewport, True, Qt.ClosedHandCursor)
            self._repaint()
            return True
        if t == QtCore.QEvent.MouseButtonRelease:
            if self.drag is not None and event.button() == Qt.LeftButton:
                self._drop()
                self._set_cursor(viewport, self._at_bar(event.position().y()) is not None)
                return True
            return False
        if t == QtCore.QEvent.MouseButtonDblClick:
            return self._at_bar(event.position().y()) is not None and not rollbackbar.editing()
        if t in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave) and self.drag is None:
            self._set_cursor(viewport, False)
        return False

    def _drag_to(self, y):
        key, gaps, preview = self.drag
        if gaps:
            best = min(gaps, key=lambda gap: abs(gap[0] - y))
            if preview is None or best[0] != preview[0]:
                self.drag = (key, gaps, best)
                self._repaint()

    def _drop(self):
        key, gaps, preview = self.drag
        self.drag = None
        self.drags += 1
        body = rollbackbar.RollbackBar._body(key)
        if body is not None and preview is not None:
            freezebar.freeze_to(preview[1], body)
        self._repaint()

    def remove(self):
        self.timer.stop()
        self.detach()
