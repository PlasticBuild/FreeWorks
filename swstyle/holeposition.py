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
from PySide import QtCore, QtWidgets

from . import sketchtoolpm
from .widgets import alive

Qt = QtCore.Qt
TITLE = "Hole Position"


class HolePositionPage(sketchtoolpm.ToolPage):
    TITLE = TITLE
    ICON = "FEATURES_HOLE_WIZARD"
    PIXMAP = "PartDesign_Hole"
    TOOL_IS_PAGE = True     # pkg239: the Point tool runs for the whole tab; Enter is still the page's OK
    HOSTS_TOOLS = ("FreeWorks_Point",)

    def __init__(self, sketch, spec):
        self.spec = spec
        self.done = False
        super().__init__(sketch)
        self.setProperty("swstyle_pm_title", TITLE)
        self.cancel.clicked.disconnect()
        self.cancel.clicked.connect(self.cancel_holes)
        self.watch = QtCore.QTimer(self)
        self.watch.setInterval(300)
        self.watch.timeout.connect(self._count)
        self.watch.start()

        self._tab_filter = None
        if spec.get("kind") in SLOTS:
            self._tab_filter = _SlotTab(self)
            QtWidgets.QApplication.instance().installEventFilter(self._tab_filter)

    def build(self):
        self.tabs = QtWidgets.QTabBar(self.body)
        self.tabs.setObjectName("SWHolePositionTabs")
        self.tabs.addTab("Type")
        self.tabs.addTab("Positions")
        self.tabs.setCurrentIndex(1)
        self.tabs.setExpanding(True)
        self.tabs.setDrawBase(False)
        self.tabs.currentChanged.connect(self._tab)
        holder = QtWidgets.QWidget(self.body)
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(8, 0, 8, 6)
        row.addWidget(self.tabs)
        self.column.addWidget(holder)
        g = self.group("Hole Position")
        text = QtWidgets.QLabel("Click on the face for each hole. Dimensions and relations place the points "
                                "exactly; other sketch tools work here too.\nThe Type tab changes the hole.", g.body)
        text.setObjectName("SWHolePositionMessage")
        text.setWordWrap(True)
        g.content.addWidget(text)
        self.count_label = QtWidgets.QLabel("", g.body)
        self.count_label.setObjectName("SWHolePositionCount")
        g.content.addWidget(self.count_label)
        self._count()

    def points(self):
        try:
            import Part
            return sum(1 for i, g in enumerate(self.sketch.Geometry)
                       if isinstance(g, (Part.Point, Part.Circle)) and not self.sketch.getConstruction(i))
        except Exception:
            return 0

    def _count(self):
        if not alive(self) or not hasattr(self, "count_label"):
            return
        n = self.points()
        text = "Holes: %d" % n if n else "No hole placed yet."
        if self.spec.get("kind") in SLOTS:
            text += "\nSlot angle: %g\u00b0 (Tab turns it 90\u00b0 clockwise)" % slot_angle(self.spec)
        self.count_label.setText(text)

    def turn_slot(self):
        self.spec["slot_angle"] = (slot_angle(self.spec) - 90.0) % 360.0
        self._count()

    # ----------------------------------------------------------------- the three ways out
    def finish(self):
        self.done = True

    def accept(self):
        """The green check: the holes are made (holewizard makes them as the sketch closes)."""
        self.done = True
        super().accept()
        QtCore.QTimer.singleShot(0, _leave_sketch)

    def leave(self):
        self.done = True
        super().leave()

    def reject(self):
        """The host closes the page for another tool's page, or Esc: only Esc drops the holes."""
        if self.done:
            return super().reject()
        sketch_name, doc = self.sketch.Name, self.doc
        sketchtoolpm.close(self)

        def after():
            host = sketchtoolpm._host
            if host is not None and host.page is not None:
                return          # another tool's page took the pane: the points stay, the sketch is open
            _cancel(doc, sketch_name)
        QtCore.QTimer.singleShot(0, after)

    def cancel_holes(self):
        self.done = True
        doc, name = self.doc, self.sketch.Name
        sketchtoolpm.close(self)
        QtCore.QTimer.singleShot(0, lambda: _cancel(doc, name))

    def _tab(self, index):
        if index != 0:
            return
        self.done = True
        doc, name, spec = self.doc, self.sketch.Name, self.spec
        sketchtoolpm.close(self)
        QtCore.QTimer.singleShot(0, lambda: _back_to_type(doc, name, spec))

    def closing(self):
        try:
            self.watch.stop()
        except Exception as _fw_err:
            _fw_log("holeposition.py:150", _fw_err)
        if getattr(self, "_tab_filter", None) is not None:
            try:
                QtWidgets.QApplication.instance().removeEventFilter(self._tab_filter)
            except Exception as _fw_err:
                _fw_log("holeposition.py:155", _fw_err)
            self._tab_filter = None


SLOTS = ("Counterbore Slot", "Countersink Slot", "Slot")


def slot_angle(spec):
    try:
        return float(spec.get("slot_angle") or 0.0) % 360.0
    except Exception:
        return 0.0


class _SlotTab(QtCore.QObject):
    """Tab in the graphics area while slots are placed: the slot turns 90 degrees clockwise. Tab in a
    typed box (the point's X/Y fields, the pane) keeps its own meaning."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def eventFilter(self, obj, event):
        try:
            if event.type() != QtCore.QEvent.KeyPress or event.key() != QtCore.Qt.Key_Tab \
                    or event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier):
                return False
            typed = (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox, QtWidgets.QTextEdit,
                     QtWidgets.QPlainTextEdit, QtWidgets.QComboBox)
            if isinstance(obj, typed) or isinstance(QtWidgets.QApplication.focusWidget(), typed):
                return False
            if isinstance(obj, QtWidgets.QWidget) and obj.window() is not Gui.getMainWindow():
                return False            # a dialog of its own
            if not alive(self.page):
                return False
            self.page.turn_slot()
            return True
        except Exception:
            return False


def _leave_sketch():
    try:
        gdoc = Gui.ActiveDocument
        if gdoc is not None and gdoc.getInEdit() is not None:
            gdoc.resetEdit()
    except Exception as _fw_err:
        _fw_log("holeposition.py:202", _fw_err)


def _cancel(doc, name):
    from . import holewizard, sketchstart
    holewizard._pending.pop(name, None)
    holewizard._specs.pop(name, None)
    own = name in holewizard._own
    holewizard._own.discard(name)
    _leave_sketch()
    if own and doc is not None and doc.getObject(name) is not None:
        try:
            sketchstart.discard(doc, name)
        except Exception:
            try:
                doc.removeObject(name)
            except Exception as _fw_err:
                _fw_log("holeposition.py:219", _fw_err)
    try:
        Gui.getMainWindow().statusBar().showMessage("Hole Wizard canceled.", 3000)
    except Exception as _fw_err:
        _fw_log("holeposition.py:223", _fw_err)


def _back_to_type(doc, name, spec):
    """Type tab: the points stay in their sketch; the Type page opens with it, and its Positions tab
    opens the same sketch again (holespec's 'sketch picked first' way)."""
    from . import holespec, holewizard, sketchstart
    holewizard._pending.pop(name, None)
    holewizard._specs.pop(name, None)
    _leave_sketch()
    sketch = doc.getObject(name) if doc is not None else None
    body = sketchstart._body()
    if sketch is None or body is None:
        return
    try:
        if spec:
            holespec.remember(dict(spec))
    except Exception as _fw_err:
        _fw_log("holeposition.py:241", _fw_err)
    holespec.show(body, None, holewizard.start_on_face, sketch=sketch)


def open_for(sketch, spec):
    """The page for the Positions sketch just opened by holewizard.start_on_face."""
    if sketch is None or not App.GuiUp:
        return None
    page = HolePositionPage(sketch, spec)
    if not sketchtoolpm.open_page(page):
        page.deleteLater()
        return None
    return page
