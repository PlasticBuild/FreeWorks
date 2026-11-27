# SPDX-License-Identifier: LGPL-2.1-or-later
""























import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import paths

Qt = QtCore.Qt

VIEW = "User parameter:BaseApp/Preferences/View"
NAVIGATION = "Gui::SolidWorksNavigationStyle"
REVERSE = "ReverseWheelZoom"
ARROW_STEP = "ArrowKeyStep"          # addon parameter: degrees per arrow key
NOTCH = 120.0                        # one wheel notch, in Qt's eighths of a degree
# How fast zooming in brings the spot under the pointer to the middle: for a zoom by exp(z) its
# distance from the middle shrinks by exp(-PULL * z), 18% a notch with FreeCAD's zoom step of 0.2.

PULL = 0.0
REACH = 8.0                          # the point zoomed about stays within this many view sizes

# 0.2 gives exp(0.2) = x1.22. With FreeCAD's step at its default the notch is sent a little shorter so
# one notch is x1.2; a Zoom step the user changed in FreeCAD's preferences is used as it is.
SW_NOTCH = math.log(1.2)
FREECAD_STEP = 0.2


def reverse():
    return paths.params().GetBool(REVERSE, False)


def about_centre():
    ""
    return not App.ParamGet(VIEW).GetBool("ZoomAtCursor", True)


def set_about_centre(on):
    App.ParamGet(VIEW).SetBool("ZoomAtCursor", not bool(on))


def arrow_step():
    step = paths.params().GetFloat(ARROW_STEP, 15.0)
    return step if 0.0 < step <= 180.0 else 15.0


def plan(delta, pos, size, invert=True, step=0.2, reversed_=False, centre_only=False):
    ""




    width, height = size
    if not delta or width < 2 or height < 2:
        return None
    zoom_out = (delta > 0) != bool(reversed_)
    amount = abs(delta)
    if abs(abs(step) - FREECAD_STEP) < 1e-9:
        amount = max(1, int(round(amount * SW_NOTCH / FREECAD_STEP)))
    # FreeCAD zooms out for a positive delta, or for a negative one with Invert zoom on
    sent = amount if zoom_out != bool(invert) else -amount
    # FreeCAD's middle of the view: it divides pixel positions by the size less one
    cx, cy = (width - 1) / 2.0, (height - 1) / 2.0
    if centre_only:
        return sent, (cx, cy)
    if zoom_out:
        return sent, (cx, cy)
    z = abs(step) * amount / NOTCH          # FreeCAD zooms by exp(z)
    if z < 1e-9:
        reach = 1.0 + PULL
    else:
        # Zooming about this point leaves the pointer's spot exp(-PULL * z) as far from the middle
        reach = 1.0 + (1.0 - math.exp(-PULL * z)) / (math.exp(z) - 1.0)
    x, y = pos
    limit = REACH * max(width, height)
    zx = min(max(cx + reach * (x - cx), cx - limit), cx + limit)
    zy = min(max(cy + reach * (y - cy), cy - limit), cy + limit)
    return sent, (zx, zy)


def _navigation_ok(view):
    try:
        return view.getNavigationType() == NAVIGATION
    except Exception:
        return App.ParamGet(VIEW).GetString("NavigationStyle", "") == NAVIGATION


class WheelZoom:
    ""


    def __init__(self):
        self._sending = False
        self.count = 0                   # wheel events turned, for checks
        self.last = None                 # the last (delta, (x, y)) sent, for checks

    def filter(self, obj, event, view):
        # The GL viewport passes the wheel up to the view (a QGraphicsView), where FreeCAD reads it.
        if self._sending or view is None or not isinstance(obj, QtWidgets.QAbstractScrollArea):
            return False
        if event.buttons() != Qt.NoButton or not _navigation_ok(view):
            return False
        angle = event.angleDelta()
        dy = angle.y()
        if dy == 0 or abs(angle.x()) > abs(dy):
            return False
        grp = App.ParamGet(VIEW)
        pos = event.position()
        planned = plan(dy, (pos.x(), pos.y()), (obj.width(), obj.height()),
                       invert=grp.GetBool("InvertZoom", True), step=grp.GetFloat("ZoomStep", 0.2),
                       reversed_=reverse(), centre_only=about_centre())
        if planned is None:
            return False
        sent, (x, y) = planned
        try:
            at = QtCore.QPointF(x, y)
            glob = QtCore.QPointF(obj.mapToGlobal(at.toPoint()))
            wheel = QtGui.QWheelEvent(at, glob, QtCore.QPoint(0, 0), QtCore.QPoint(0, int(sent)), event.buttons(),
                                      event.modifiers(), Qt.NoScrollPhase, False)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: wheel zoom left to FreeCAD (%s)\n" % error)
            return False
        self._sending = True
        try:
            QtWidgets.QApplication.sendEvent(obj, wheel)
        finally:
            self._sending = False
        self.count += 1
        self.last = planned
        return True


# --------------------------------------------------------------------------- View menu
class ZoomAboutScreenCenterCommand:
    ""

    def GetResources(self):
        return {
            "MenuText": "Zoom About Screen Center",
            "ToolTip": "The mouse wheel zooms in about the middle of the screen instead of toward the pointer",
            "Checkable": about_centre(),
            "CmdType": "ForEdit",
        }

    def Activated(self, checked):
        set_about_centre(bool(checked))

    def IsActive(self):
        # Follow changes made elsewhere: the Options pages, FreeCAD's Zoom at cursor
        on = about_centre()
        try:
            actions = Gui.Command.get("SWStyle_ZoomAboutScreenCenter").getAction()
        except Exception:
            actions = []
        for action in actions:
            if action.isChecked() != on:
                blocked = action.blockSignals(True)
                action.setChecked(on)
                action.blockSignals(blocked)
        return True


def menu_items(have):
    """Workbench manipulator entries: the switch in the View menu right under its Zoom submenu.
    FreeCAD 1.1's manipulator cannot reach into a submenu (an anchor inside one finds the top
    menu), so it goes next to it; "&Zoom" is the submenu's name in FreeCAD's own menu setup."""
    if "SWStyle_ZoomAboutScreenCenter" not in have:
        return []
    return [{"insert": "SWStyle_ZoomAboutScreenCenter", "menuItem": "&Zoom", "after": ""}]


# --------------------------------------------------------------------------- Options > View
class ViewPage:
    ""



    def __init__(self):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("View")
        lay = QtWidgets.QVBoxLayout(self.form)
        self.reverse = QtWidgets.QCheckBox("Reverse mouse wheel zoom direction")
        self.reverse.setToolTip("Off: turning the wheel away from you zooms out. "
                                "On: it zooms in")
        self.centre = QtWidgets.QCheckBox("Zoom about screen center")
        self.centre.setToolTip("The wheel zooms in about the middle of the screen instead of toward the "
                               "pointer, in and out")
        rotation = QtWidgets.QGroupBox("View rotation")
        form = QtWidgets.QFormLayout(rotation)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        self.step = QtWidgets.QDoubleSpinBox()
        self.step.setMinimumWidth(90)
        self.step.setRange(1.0, 90.0)
        self.step.setDecimals(1)
        self.step.setSuffix(" °")
        self.step.setToolTip("How far an arrow key turns the view; Shift with an arrow turns it 90°")
        form.addRow("Arrow keys:", self.step)
        for widget, path, entry in ((self.reverse, "Mod/FreeWorks", REVERSE),
                                    (self.centre, "View", "ZoomAtCursor"),
                                    (self.step, "Mod/FreeWorks", ARROW_STEP)):
            # FreeCAD's Reset button removes the parameters these name
            widget.setProperty("prefPath", path)
            widget.setProperty("prefEntry", entry)
        lay.addWidget(self.reverse)
        lay.addWidget(self.centre)
        lay.addWidget(rotation)
        lay.addStretch(1)
        self.loaded = None

    def _values(self):
        return self.reverse.isChecked(), self.centre.isChecked(), self.step.value()

    def loadSettings(self):
        self.reverse.setChecked(reverse())
        self.centre.setChecked(about_centre())
        self.step.setValue(arrow_step())
        self.loaded = self._values()

    def saveSettings(self):
        if self.loaded is None:
            return
        rev, centre, step = self._values()
        if rev != self.loaded[0]:
            paths.params().SetBool(REVERSE, rev)
        if centre != self.loaded[1]:
            set_about_centre(centre)
        if step != self.loaded[2]:
            paths.params().SetFloat(ARROW_STEP, step)
        self.loaded = self._values()


def register():
    """Adds the View page to Options (FreeCAD's Display group) and the Zoom About Screen Center
    command. Call once while FreeCAD starts."""
    Gui.addCommand("SWStyle_ZoomAboutScreenCenter", ZoomAboutScreenCenterCommand())
    Gui.addPreferencePage(ViewPage, "Display")
