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

from . import drawings as D

MAX_STEPS = 20



def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

def _keys():
    from . import drawkeys
    return drawkeys


def _page_view():
    page = D.active_page()
    return page, (D.page_view(page) if page is not None else None)


def _state(gv):
    t = gv.transform()
    return ((t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()),
            gv.horizontalScrollBar().value(), gv.verticalScrollBar().value())


def history(gv):
    """The sheet's Previous View steps: one list for the keys (F, Z, the wheel), the Heads-up View toolbar and
    View > Modify > Previous View (drawkeys keeps it)."""
    return _keys().HISTORY.setdefault(id(gv), [])


def remember(gv):
    """The sheet's zoom and position now, for Previous View (a repeat of the last one is not kept twice)."""
    if gv is not None:
        _keys().remember(gv)


def watch():
    """Called every 0.7 s: a zoom made some other way (Zoom to Fit on a toolbar) is remembered too."""
    page, gv = _page_view()
    if gv is None:
        return
    last = getattr(gv, "_sw_last_state", None)
    now = _state(gv)
    if last is not None and last != now:
        steps = history(gv)
        (m11, m12, m21, m22, dx, dy), h, v = last
        st = (QtGui.QTransform(m11, m12, m21, m22, dx, dy), h, v)
        if not steps or steps[-1][0] != st[0] or steps[-1][1:] != st[1:]:
            steps.append(st)
            del steps[:-MAX_STEPS]
    try:
        gv._sw_last_state = now
    except Exception as _fw_err:
        _fw_log("drawhud.py:84", _fw_err)


def previous_view(gv=None):
    if gv is None:
        _page, gv = _page_view()
    if gv is None:
        return False
    steps = history(gv)
    now = (gv.transform(), gv.horizontalScrollBar().value(), gv.verticalScrollBar().value())
    while steps and steps[-1][0] == now[0] and steps[-1][1:] == now[1:]:
        steps.pop()
    if not _keys().previous_view(gv):
        return False
    try:
        gv._sw_last_state = _state(gv)
    except Exception as _fw_err:
        _fw_log("drawhud.py:101", _fw_err)
    return True


def zoom_to_rect(gv, rect):
    """The sheet zoomed so the scene rectangle fills the window."""
    if rect.width() < 1 or rect.height() < 1:
        return False
    remember(gv)
    gv.fitInView(rect, QtCore.Qt.KeepAspectRatio)
    try:
        gv._sw_last_state = _state(gv)
    except Exception as _fw_err:
        _fw_log("drawhud.py:114", _fw_err)
    return True


class _ZoomArea(QtCore.QObject):
    """One box drag on the sheet's viewport."""

    def __init__(self, gv):
        super().__init__(gv.viewport())
        self.gv = gv
        self.start = None
        self.band = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, gv.viewport())
        self.band.setObjectName("SWZoomAreaBand")
        gv.viewport().installEventFilter(self)
        gv.viewport().setCursor(QtCore.Qt.CrossCursor)

    def done(self):
        try:
            self.gv.viewport().removeEventFilter(self)
            self.gv.viewport().unsetCursor()
            self.band.hide()
        except Exception as _fw_err:
            _fw_log("drawhud.py:136", _fw_err)
        if ACTIVE and ACTIVE[0] is self:
            ACTIVE[:] = []
        self.deleteLater()

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False          # a stale PySide wrapper can arrive here
        t = event.type()
        if t == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.RightButton:
                self.done()
                return True
            if event.button() == QtCore.Qt.LeftButton:
                self.start = event.position().toPoint()
                self.band.setGeometry(QtCore.QRect(self.start, QtCore.QSize()))
                self.band.show()
                return True
        elif t == QtCore.QEvent.MouseMove and self.start is not None:
            self.band.setGeometry(QtCore.QRect(self.start, event.position().toPoint()).normalized())
            return True
        elif t == QtCore.QEvent.MouseButtonRelease and self.start is not None:
            r = QtCore.QRect(self.start, event.position().toPoint()).normalized()
            self.start = None
            if r.width() > 3 and r.height() > 3:
                zoom_to_rect(self.gv, self.gv.mapToScene(r).boundingRect())
            self.done()
            return True
        elif t == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self.done()
            return True
        return False


ACTIVE = []


def zoom_area():
    page, gv = _page_view()
    if gv is None:
        return None
    if ACTIVE:
        ACTIVE[0].done()
    ACTIVE[:] = [_ZoomArea(gv)]
    return ACTIVE[0]


# --------------------------------------------------------------------------- 3D Drawing View
def _view_of_pick(page):
    for o in Gui.Selection.getSelection():
        if o.isDerivedFrom("TechDraw::DrawViewPart") and o in page.Views:
            return o
    views = [o for o in page.Views if o.isDerivedFrom("TechDraw::DrawViewPart")]
    return views[0] if len(views) == 1 else None


class DrawingView3DPanel(object):
    """3D Drawing View: the view's model turned in 3D; OK keeps the orientation on the view."""

    def __init__(self, view):
        from . import drawviews as DV
        self.view = view
        self.page_doc = view.Document
        self.form = QtWidgets.QWidget()
        self.form.setObjectName("SWDrawingView3D")
        self.form.setWindowTitle("3D Drawing View")
        self.form.setProperty("swstyle_pm_title", "3D Drawing View")
        lay = QtWidgets.QVBoxLayout(self.form)
        msg = QtWidgets.QLabel("Turn the model with the mouse to reach the edges you need, then OK to keep the "
                               "new orientation on %s (Cancel leaves the view as it was)." % view.Label)
        msg.setWordWrap(True)
        lay.addWidget(msg)
        self.save = QtWidgets.QCheckBox("Save view orientation", self.form)
        self.save.setObjectName("SWDrawingView3DSave")
        self.save.setChecked(True)
        lay.addWidget(self.save)
        lay.addStretch(1)
        self.model = None
        shapes = [o for o in (_fw_xs(view) + list(getattr(view, "Source", []) or []))]
        if shapes:
            self.model = shapes[0].Document
        self.mdi_before = None
        try:
            self.mdi_before = Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow()
        except Exception as _fw_err:
            _fw_log("drawhud.py:221", _fw_err)
        self.opened = self.show_model()

    def show_model(self):
        if self.model is None:
            return False
        gd = Gui.getDocument(self.model.Name)
        if gd is None:
            return False
        try:
            Gui.setActiveDocument(self.model.Name)
            gd.activeView()
            for w in Gui.getMainWindow().findChild(QtWidgets.QMdiArea).subWindowList():
                if w.widget() is not None and "View3DInventor" in type(w.widget()).__name__ or \
                        self.model.Label in w.windowTitle() and "TechDraw" not in w.windowTitle():
                    Gui.getMainWindow().findChild(QtWidgets.QMdiArea).setActiveSubWindow(w)
                    break
        except Exception as _fw_err:
            _fw_log("drawhud.py:239", _fw_err)
        av = gd.activeView()
        if av is None or not hasattr(av, "getCameraNode"):
            return False
        d, x, y = D.view_frame(self.view)
        try:
            rot = App.Rotation(x, y, d, "ZXY")
            cam = av.getCameraNode()
            q = rot.Q
            cam.orientation.setValue(q[0], q[1], q[2], q[3])
            av.fitAll()
        except Exception:
            try:
                av.setViewDirection((-d.x, -d.y, -d.z))
            except Exception as _fw_err:
                _fw_log("drawhud.py:254", _fw_err)
        self.av = av
        return True

    def orientation(self):
        """(direction to the viewer, X direction) of the 3D window's camera now."""
        cam = self.av.getCameraNode()
        q = cam.orientation.getValue().getValue()
        r = App.Rotation(q[0], q[1], q[2], q[3])
        return r.multVec(App.Vector(0, 0, 1)), r.multVec(App.Vector(1, 0, 0))

    def apply(self):
        d, x = self.orientation()
        v = self.view
        self.page_doc.openTransaction("3D Drawing View")
        try:
            v.Direction = d
            if "XDirection" in v.PropertiesList:
                v.XDirection = x
        except BaseException:
            try:
                self.page_doc.abortTransaction()
            except Exception:
                pass
            raise
        self.page_doc.commitTransaction()
        self.page_doc.recompute()

    def back(self):
        try:
            if self.mdi_before is not None:
                Gui.getMainWindow().findChild(QtWidgets.QMdiArea).setActiveSubWindow(self.mdi_before)
            Gui.setActiveDocument(self.page_doc.Name)
        except Exception as _fw_err:
            _fw_log("drawhud.py:281", _fw_err)

    def accept(self):
        if self.opened and self.save.isChecked():
            try:
                self.apply()
            except Exception as error:
                App.Console.PrintWarning("FreeCAD: 3D Drawing View: %s\n" % error)
        self.back()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        self.back()
        Gui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel   # no int(): PySide6 refuses it


def drawing_view_3d(view=None):
    page = D.active_page()
    if view is None and page is not None:
        view = _view_of_pick(page)
    if view is None:
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "3D Drawing View",
                                          "Select a drawing view first.")
        return None
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()
    panel = DrawingView3DPanel(view)
    Gui.Control.showDialog(panel)
    return panel


COMMANDS = {
    "FreeWorks_DrawZoomArea": ("Zoom to Area", "zoom-border", "Zooms to the area you drag a box around."),
    "FreeWorks_Draw3DDrawingView": ("3D Drawing View", "view-axonometric",
                                    "Turns a drawing view in 3D to reach its edges; OK keeps the orientation."),
}


class _Command(object):
    def __init__(self, name):
        self.name = name

    def GetResources(self):
        text, icon, tip = COMMANDS[self.name]
        return {"MenuText": text, "ToolTip": tip, "Pixmap": D.pixmap(icon)}

    def IsActive(self):
        page = D.active_page()
        if page is None:
            return False
        if self.name == "FreeWorks_Draw3DDrawingView":
            return any(o.isDerivedFrom("TechDraw::DrawViewPart") for o in page.Views)
        return True

    def Activated(self):
        if self.name == "FreeWorks_DrawZoomArea":
            zoom_area()
        elif self.name == "FreeWorks_Draw3DDrawingView":
            drawing_view_3d()


_TIMER = []


def register():
    try:
        _keys().register()            # Previous View is drawkeys' command
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Previous View: %s\n" % error)
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    if not _TIMER:
        t = QtCore.QTimer(Gui.getMainWindow())
        t.setInterval(700)
        t.timeout.connect(watch)
        t.start()
        _TIMER.append(t)
