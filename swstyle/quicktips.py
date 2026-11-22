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

from . import paths
from .widgets import alive, scaled

Qt = QtCore.Qt
PARAM = "QuickTips"

# context: (heading, [(text, catalog keys to try, first one found is used)])
TIPS = {
    "part-empty": ("Getting started on a part", [
        ("Draw a sketch on a plane", ("Sketch",)),
        ("Turn a sketch into a solid", ("BossExtrude",)),
        ("Spin a sketch round an axis", ("BossRevolve",)),
        ("Add a plane to sketch on", ("Plane", "ReferenceGeometry")),
    ]),
    "part": ("Working on the part", [
        ("Sketch on a face or plane", ("Sketch",)),
        ("Cut material away with a sketch", ("CutExtrude",)),
        ("Round off edges", ("Fillet",)),
        ("Drill a hole", ("Hole",)),
        ("Hollow the part out", ("Shell",)),
        ("Change the colour", ("EditAppearance",)),
    ]),
    "sketch": ("Sketching", [
        ("Draw lines", ("Line",)),
        ("Draw a rectangle", ("CornerRectangle",)),
        ("Draw a circle", ("Circle",)),
        ("Give a size", ("SmartDimension",)),
        ("Tie entities together", ("AddRelation",)),
        ("Cut away extra lines", ("Trim",)),
        ("Leave the sketch", ("ExitSketch",)),
    ]),
    "assembly": ("Building the assembly", [
        ("Bring in a part", ("InsertComponents", "InsertComponent", "InsertPart")),
        ("Fix parts to each other", ("Mate",)),
        ("Check a distance", ("Measure",)),
        ("Pull the assembly apart", ("ExplodedView", "Explode")),
    ]),
    "drawing": ("Making a drawing", [
        ("Put views of a model on the sheet", ("DrawStandard3View", "DrawModelView")),
        ("Give a size", ("SmartDimension",)),
        ("Write a note", ("DrawNote",)),
        ("Label parts with balloons", ("DrawBalloon",)),
    ]),
}


def enabled():
    return paths.params().GetBool(PARAM, False)


def set_enabled(on):
    paths.params().SetBool(PARAM, bool(on))
    q = _quick()
    if q is not None:
        q.refresh()


def context():
    try:
        from . import gestures
        mode = gestures.mode_now()
    except Exception:
        mode = "part"
    if mode == "part":
        doc = App.ActiveDocument
        solid = False
        try:
            from . import contextbar
            solid = doc is not None and any(contextbar._solid_feature(o) for o in doc.Objects)
        except Exception as _fw_err:
            _fw_log("quicktips.py:96", _fw_err)
        return "part" if solid else "part-empty"
    return mode


def entries(ctx):
    from . import catalog
    heading, rows = TIPS.get(ctx, TIPS["part"])
    out = []
    for text, keys in rows:
        key = next((k for k in keys if k in catalog.BY_KEY), None)
        if key is not None:
            out.append((text, key))
    return heading, out


class Panel(QtWidgets.QFrame):
    def __init__(self, owner):
        super().__init__(owner.shell.window)
        self.owner = owner
        self.setObjectName("SWQuickTips")
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(3)
        top = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("<b>Quick Tips</b>")
        top.addWidget(title, 1)
        close = QtWidgets.QToolButton(self)
        close.setObjectName("SWQuickTipsClose")
        close.setText("x")
        close.setAutoRaise(True)
        close.setToolTip("Turn Quick Tips off")
        close.clicked.connect(lambda checked=False: set_enabled(False))
        top.addWidget(close)
        lay.addLayout(top)
        self.heading = QtWidgets.QLabel()
        self.heading.setObjectName("SWQuickTipsHeading")
        lay.addWidget(self.heading)
        self.rows = QtWidgets.QVBoxLayout()
        self.rows.setSpacing(1)
        lay.addLayout(self.rows)
        self.links = []
        self.ctx = None
        self.hide()

    def fill(self, ctx):
        if ctx == self.ctx:
            return
        self.ctx = ctx
        for b in self.links:
            b.setParent(None)
            b.deleteLater()
        self.links = []
        heading, rows = entries(ctx)
        self.heading.setText(heading)
        for text, key in rows:
            b = QtWidgets.QPushButton(text, self)
            b.setFlat(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton{text-align:left; color:palette(link); border:none; padding:1px 2px;}"
                            "QPushButton:hover{text-decoration:underline;}")
            b.setProperty("sw_key", key)
            b.setToolTip("Shows where the command is")
            b.clicked.connect(lambda checked=False, key=key: self.owner.point_at(key))
            self.rows.addWidget(b)
            self.links.append(b)
            b.show()                    # children added to a panel already on screen start hidden
        self.layout().activate()
        self.resize(self.layout().sizeHint().expandedTo(self.minimumSizeHint()))

    def place(self):
        host = self.owner.host()
        if host is None:
            self.hide()
            return
        mw = self.owner.shell.window
        right = host.width() - host.contentsMargins().right()
        try:
            right -= self.owner.shell.overlay.tasks.width() if not host.contentsMargins().right() else 0
        except Exception as _fw_err:
            _fw_log("quicktips.py:178", _fw_err)
        corner = host.mapTo(mw, QtCore.QPoint(right, host.height()))
        self.move(corner.x() - self.width() - scaled(8), corner.y() - self.height() - scaled(8))
        self.raise_()


class QuickTips(QtCore.QObject):
    def __init__(self, shell):
        super().__init__(shell.window)
        self.shell = shell
        self.panel = Panel(self)
        self.pointed = []               # keys pointed at, for checks
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        try:
            from . import ticks as _ticks
            _ticks.slow_when_idle(self.timer)
        except Exception as _fw_err:
            __import__("FreeCAD").Console.PrintLog("FreeCAD ticks: %s\n" % _fw_err)

    def host(self):
        overlay = getattr(self.shell, "overlay", None)
        for name in ("host", "sheet"):
            h = getattr(overlay, name, None) if overlay is not None else None
            if h is not None and alive(h) and h.isVisible():
                return h
        return None

    def refresh(self):
        if not alive(self.panel):
            return
        on = enabled() and App.ActiveDocument is not None and self.host() is not None
        if not on:
            if self.panel.isVisible():
                self.panel.hide()
            self._sync_button()
            return
        self.panel.fill(context())
        if not self.panel.isVisible():
            self.panel.show()
        self.panel.place()
        self._sync_button()

    def keep_last(self):
        ""

        b = getattr(self.shell, "status_quicktips", None)
        if b is None or not alive(b):
            return
        bar = b.parentWidget()
        if bar is None:
            return
        x = b.geometry().x()
        if any(w is not b and w.isVisible() and w.parentWidget() is bar and w.geometry().x() > x
               for w in bar.findChildren(QtWidgets.QWidget, options=Qt.FindDirectChildrenOnly)):
            bar.removeWidget(b)
            bar.addPermanentWidget(b)
            b.show()

    def _sync_button(self):
        self.keep_last()
        b = getattr(self.shell, "status_quicktips", None)
        if b is not None and alive(b) and b.isChecked() != enabled():
            b.blockSignals(True)
            b.setChecked(enabled())
            b.blockSignals(False)

    def point_at(self, key):
        self.pointed.append(key)
        try:
            from . import cmdlocate
            return cmdlocate.show(self.shell, "sw:" + key)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: quick tips: %s\n" % error)
            return None

    def remove(self):
        self.timer.stop()
        if alive(self.panel):
            self.panel.hide()
            self.panel.setParent(None)
            self.panel.deleteLater()


def button():
    b = QtWidgets.QToolButton()
    b.setObjectName("SWQuickTipsButton")
    b.setAutoRaise(True)
    b.setCheckable(True)
    b.setText("?")
    b.setToolTip("Quick Tips")
    b.setChecked(enabled())
    b.toggled.connect(set_enabled)
    return b


_state = {}


def _quick():
    q = _state.get("q")
    return q if q is not None and alive(q.panel) else None


def install(shell):
    """The ? at the right end of the status bar and the panel."""
    if shell is None or getattr(shell, "status_quicktips", None) is not None:
        return _quick()
    b = button()
    shell.window.statusBar().addPermanentWidget(b)
    shell.status_quicktips = b
    _state["q"] = QuickTips(shell)
    return _state["q"]
