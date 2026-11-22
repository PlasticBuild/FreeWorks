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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .widgets import alive

Qt = QtCore.Qt
ROLE = Qt.UserRole + 1
MIME = "application/x-freeworks-view"
s3 = 1 / math.sqrt(3)
VIEWS = (("*Front", (0, -1, 0)), ("*Top", (0, 0, 1)), ("*Right", (1, 0, 0)), ("*Back", (0, 1, 0)),
         ("*Bottom", (0, 0, -1)), ("*Left", (-1, 0, 0)), ("*Isometric", (s3, -s3, s3)),
         ("*Dimetric", (0.5735, -0.5735, 0.5848)), ("*Trimetric", (0.6930, -0.4803, 0.5377)))


def sources():
    """The open documents with something to draw."""
    from . import newdoc
    out = []
    for doc in App.listDocuments().values():
        if any(o.TypeId.startswith("TechDraw::DrawPage") for o in doc.Objects):
            continue
        if newdoc._source_shape(doc):
            out.append(doc)
    return out


def page_of(doc=None):
    """The drawing sheet that is open: the active sheet window's, else the active document's first."""
    try:
        view = Gui.activeView()
        if view is not None and hasattr(view, "getPage"):
            return view.getPage()
    except Exception as _fw_err:
        _fw_log("viewpalette.py:59", _fw_err)
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    pages = [o for o in doc.Objects if o.TypeId == "TechDraw::DrawPage"]
    return pages[0] if pages else None


def _size(page):
    try:
        return float(page.Template.Width), float(page.Template.Height)
    except Exception:
        return 279.4, 215.9


def place(source, name, page=None, at=None, ask=True):
    """Puts the view named name ('*Front' ...) of source on the sheet. at = (fx, fy) in 0..1 of the sheet,
    from its top left (None = the middle)."""
    from . import newdoc
    page = page or page_of()
    if page is None or source is None:
        return None
    drawing = page.Document
    if ask:
        if not newdoc._saved(source, "a drawing view"):
            return None
        if not drawing.FileName and not newdoc._saved(drawing, "a view of another file on it"):
            return None
    direction = dict(VIEWS).get(name)
    shapes = newdoc._source_shape(source)
    if direction is None or not shapes:
        return None
    drawing.openTransaction("Drawing View")
    try:
        view = drawing.addObject("TechDraw::DrawViewPart", "View")
        page.addView(view)
        view.XSource = shapes
        view.Direction = App.Vector(*direction)
        view.Label = name.lstrip("*")
        view.ScaleType = "Page"
        w, h = _size(page)
        fx, fy = at if at is not None else (0.5, 0.5)
        view.X, view.Y = w * fx, h * (1.0 - fy)
        drawing.recompute()
    finally:
        drawing.commitTransaction()
    return view


class _Dropper(QtCore.QObject):
    """Takes view drops on the sheet windows."""

    def __init__(self, page_widget, parent=None):
        super().__init__(parent)
        self.page_widget = page_widget

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper (QLayoutItem etc.) can arrive here
        t = event.type()
        if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove) and event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
            return True
        if t == QtCore.QEvent.Drop and event.mimeData().hasFormat(MIME):
            text = bytes(event.mimeData().data(MIME)).decode()
            doc_name, name = text.split("\n", 1)
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            fx = pos.x() / max(1, obj.width())
            fy = pos.y() / max(1, obj.height())
            src = App.listDocuments().get(doc_name)
            QtCore.QTimer.singleShot(0, lambda: place(src, name, at=(fx, fy)))
            event.acceptProposedAction()
            return True
        return False


def watch_sheets():
    for w in Gui.getMainWindow().findChildren(QtWidgets.QGraphicsView):
        if w.metaObject().className().endswith("QGVPage") and not w.property("swViewDrops"):
            vp = w.viewport()
            vp.setAcceptDrops(True)
            w.setAcceptDrops(True)
            d = _Dropper(w, w)
            vp.installEventFilter(d)
            w.setProperty("swViewDrops", True)


class Views(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWViewPaletteViews")
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(48, 48))
        self.setGridSize(QtCore.QSize(80, 76))
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Static)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.source = None

    def mimeData(self, items):
        data = QtCore.QMimeData()
        if items and self.source is not None:
            data.setData(MIME, QtCore.QByteArray(("%s\n%s" % (self.source.Name, items[0].text())).encode()))
        return data

    def mimeTypes(self):
        return [MIME]

    def startDrag(self, actions):
        watch_sheets()
        super().startDrag(actions)


def _icon(direction):
    ""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(48, 48)
    pix.fill(Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtGui.QPen(QtGui.QColor(60, 60, 60), 1.5))
    d = App.Vector(*direction)
    up = App.Vector(0, 0, 1) if abs(d.z) < 0.99 else App.Vector(0, 1, 0)
    right = up.cross(d)
    right.normalize()
    up = d.cross(right)
    up.normalize()
    corners = [App.Vector(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    pts = [QtCore.QPointF(24 + 11 * c.dot(right), 24 - 11 * c.dot(up)) for c in corners]
    for i in range(8):
        for j in range(i + 1, 8):
            if sum(a != b for a, b in zip((corners[i].x, corners[i].y, corners[i].z),
                                          (corners[j].x, corners[j].y, corners[j].z))) == 1:
                p.drawLine(pts[i], pts[j])
    p.end()
    return QtGui.QIcon(pix)


def page(pane):
    """The View Palette tab: the drawings' palette (drawpalette.py, land212) when it is there, else this one."""
    try:
        from . import drawpalette
        w = drawpalette.ViewPalette()
        w.setObjectName("SWTaskPaneViewPalette")
        drawpalette._PALETTE[:] = [w]       # drawpalette.palette() and show_palette() find the hosted one
        return w
    except ImportError:
        pass
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: View Palette tab: %s\n" % error)
    return _own_page(pane)


def _own_page(pane):
    w = QtWidgets.QWidget()
    w.setObjectName("SWTaskPaneViewPalette")
    lay = QtWidgets.QVBoxLayout(w)
    lay.setContentsMargins(4, 4, 4, 4)
    row = QtWidgets.QHBoxLayout()
    combo = QtWidgets.QComboBox()
    combo.setObjectName("SWViewPaletteSource")
    browse = QtWidgets.QToolButton()
    browse.setText("...")
    browse.setToolTip("Browse")
    refresh_btn = QtWidgets.QToolButton()
    refresh_btn.setText("Refresh")
    refresh_btn.setToolTip("Refresh")
    row.addWidget(combo, 1)
    row.addWidget(browse)
    row.addWidget(refresh_btn)
    lay.addLayout(row)
    views = Views()
    lay.addWidget(views, 1)
    note = QtWidgets.QLabel()
    note.setWordWrap(True)
    lay.addWidget(note)
    w.combo, w.views, w.note = combo, views, note

    def fill_views():
        views.clear()
        name = combo.currentData()
        views.source = App.listDocuments().get(name) if name else None
        if views.source is None:
            note.setText("Open a part or assembly to see its views.")
            return
        for label, d in VIEWS:
            it = QtWidgets.QListWidgetItem(_icon(d), label)
            it.setData(ROLE, label)
            views.addItem(it)
        note.setText("" if page_of() is not None else "Open a drawing sheet, then drag a view onto it.")

    def refresh():
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for doc in sources():
            combo.addItem(doc.Label, doc.Name)
        i = combo.findData(current)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)
        fill_views()
        watch_sheets()

    def do_browse():
        path, _ = QtWidgets.QFileDialog.getOpenFileName(w, "Open", "", "FreeCAD files (*.FCStd)")
        if path:
            active = App.ActiveDocument
            doc = App.openDocument(path, hidden=True)
            if active is not None:
                App.setActiveDocument(active.Name)
            refresh()
            combo.setCurrentIndex(max(0, combo.findData(doc.Name)))
    combo.currentIndexChanged.connect(lambda *a: fill_views())
    refresh_btn.clicked.connect(lambda checked=False: refresh())
    browse.clicked.connect(lambda checked=False: do_browse())
    views.itemDoubleClicked.connect(lambda it: place(views.source, it.data(ROLE)))
    w.refresh = refresh
    refresh()
    return w
