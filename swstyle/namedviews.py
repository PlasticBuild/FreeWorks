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

import json

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from . import paths

NAMED = "SWNamedViews"
TURN = "SWStandardViews"

# FreeCAD 1.1's camera orientations for its Std_View* commands (x, y, z, w)
STANDARD = {
    "Front": (0.707107, 0.0, 0.0, 0.707107),
    "Back": (0.0, 0.707107, 0.707107, 0.0),
    "Top": (0.0, 0.0, 0.0, 1.0),
    "Bottom": (1.0, 0.0, 0.0, 0.0),
    "Left": (-0.5, 0.5, 0.5, -0.5),
    "Right": (0.5, 0.5, 0.5, 0.5),
    "Isometric": (0.424708, 0.17592, 0.339851, 0.820473),
    "Trimetric": (0.446015, 0.119509, 0.229575, 0.856787),
    "Dimetric": (0.567952, 0.103751, 0.146726, 0.803205),
}
COMMANDS_OF = {"Front": "Std_ViewFront", "Back": "Std_ViewRear", "Top": "Std_ViewTop", "Bottom": "Std_ViewBottom",
               "Left": "Std_ViewLeft", "Right": "Std_ViewRight", "Isometric": "Std_ViewIsometric",
               "Trimetric": "Std_ViewTrimetric", "Dimetric": "Std_ViewDimetric"}
ZOOM_FIT = "ZoomFitStandardViews"
Z_UP = (0.707107, 0.0, 0.0, 0.707107)    # the turn for Z-up: 90 degrees about X
SETTABLE = ("Front", "Back", "Top", "Bottom", "Left", "Right")
_armed = []     # Update Standard Views pressed: the next standard view takes the current view


def _view():
    gdoc = Gui.ActiveDocument
    return gdoc.ActiveView if gdoc is not None else None


def _rotation(q):
    return App.Rotation(*q)


def _meta(doc, key, default):
    try:
        return doc.Meta.get(key, default)
    except Exception:
        return default


def _set_meta(doc, key, value):
    meta = dict(doc.Meta)
    if value is None:
        meta.pop(key, None)
    else:
        meta[key] = value
    doc.Meta = meta


# ---------------------------------------------------------------- named views
def views(doc=None):
    """[(name, camera)] in the order they were made."""
    doc = doc or App.ActiveDocument
    if doc is None:
        return []
    try:
        return [tuple(v) for v in json.loads(_meta(doc, NAMED, "[]"))]
    except Exception:
        return []


def _store(doc, items):
    _set_meta(doc, NAMED, json.dumps([list(v) for v in items]) if items else None)


def new_view(name, doc=None, view=None):
    doc, view = doc or App.ActiveDocument, view or _view()
    name = (name or "").strip()
    if doc is None or view is None or not name:
        return False
    items = [v for v in views(doc) if v[0] != name]
    items.append((name, view.getCamera()))
    _store(doc, items)
    return True


def go(name, doc=None, view=None):
    doc, view = doc or App.ActiveDocument, view or _view()
    for n, camera in views(doc):
        if n == name and view is not None:
            try:
                view.stopAnimating()    # a turn still running (Front just picked) took the camera back after
            except Exception as _fw_err:
                _fw_log("namedviews.py:125", _fw_err)
            view.setCamera(camera)
            try:
                from . import sectionmore
                sectionmore.on_named_view(doc, name)     # a saved section view shows its section
            except Exception as error:
                App.Console.PrintLog("FreeCAD: section view: %s\n" % error)
            return True
    return False


def delete_view(name, doc=None):
    doc = doc or App.ActiveDocument
    items = [v for v in views(doc) if v[0] != name]
    _store(doc, items)


def rename_view(old, new, doc=None):
    doc = doc or App.ActiveDocument
    new = (new or "").strip()
    items = views(doc)
    if not new or (new != old and any(n == new for n, _ in items)):
        return False
    _store(doc, [(new if n == old else n, c) for n, c in items])
    return True


def ask_new_view(parent=None):
    ""
    parent = parent or Gui.getMainWindow()
    taken = {n for n, _ in views()}
    k = 1
    while "View%d" % k in taken:
        k += 1
    name, ok = QtWidgets.QInputDialog.getText(parent, "Named View", "View name:", text="View%d" % k)
    if ok and name.strip():
        return new_view(name)
    return False


# ---------------------------------------------------------------- standard views
def turn(doc=None):
    """The turn applied to every standard view (identity when none was set)."""
    doc = doc or App.ActiveDocument
    text = _meta(doc, TURN, "") if doc is not None else ""
    try:
        return App.Rotation(*[float(x) for x in text.split(",")]) if text else App.Rotation()
    except Exception:
        return App.Rotation()


def turned(doc=None):
    return not turn(doc).isSame(App.Rotation(), 1e-6)


def standard_rotation(key, doc=None):
    return turn(doc).multiply(_rotation(STANDARD[key]))


def set_current_as(key, doc=None, view=None, ask=False):
    """Makes the current view the standard view `key`; the others turn with it."""
    doc, view = doc or App.ActiveDocument, view or _view()
    if doc is None or view is None or key not in STANDARD:
        return False
    if ask and App.GuiUp:
        from PySide import QtWidgets
        answer = QtWidgets.QMessageBox.question(
            Gui.getMainWindow(), "FreeCAD",
            "This changes the standard views of this document: the %s view becomes the view on screen "
            "and the other standard views, and the named views based on them, turn with it.\n\n"
            "Do you want to continue?" % key,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.Yes)
        if answer != QtWidgets.QMessageBox.Yes:
            return False
    try:
        view.stopAnimating()        # the view as it shows now, not a turn's end still to come
    except Exception as _fw_err:
        _fw_log("namedviews.py:202", _fw_err)
    now = view.getCameraOrientation()
    t = now.multiply(_rotation(STANDARD[key]).inverted())
    _set_meta(doc, TURN, None if t.isSame(App.Rotation(), 1e-6) else ",".join("%.9f" % x for x in t.Q))
    return True


def up_axis(doc=None):
    ""
    t = turn(doc)
    if t.isSame(App.Rotation(), 1e-6):
        return "Y"
    if t.isSame(_rotation(Z_UP), 1e-5):
        return "Z"
    return ""


def set_up_axis(axis, doc=None, view=None):
    ""
    doc, view = doc or App.ActiveDocument, view or _view()
    if doc is None or axis not in ("Y", "Z"):
        return False
    _set_meta(doc, TURN, None if axis == "Y" else ",".join("%.9f" % x for x in _rotation(Z_UP).Q))
    if view is not None:
        go_standard("Isometric", doc, view)
    return True


def reset_standard(doc=None, ask=True):
    doc = doc or App.ActiveDocument
    if doc is None:
        return False
    if ask:
        answer = QtWidgets.QMessageBox.question(Gui.getMainWindow(), "Reset Standard Views",
                                                "Reset all standard views to default settings?",
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if answer != QtWidgets.QMessageBox.Yes:
            return False
    _set_meta(doc, TURN, None)
    return True


def arm_update():
    """Update Standard Views: the next of the six standard views picked (Front ... Right) takes the current view."""
    _armed[:] = [True]
    try:
        Gui.getMainWindow().statusBar().showMessage("Select the standard view to update with the current view", 6000)
    except Exception as _fw_err:
        _fw_log("namedviews.py:250", _fw_err)


def armed():
    return bool(_armed)


def _push_current():
    """The view about to be left goes into Previous View's history at once: the sampler only keeps a
    view that stayed put for SETTLE s after its turn and zoom-to-fit, so Ctrl+1 then Ctrl+3 a second
    later lost the first view (rcmenus' probe_z: Previous View stayed greyed)."""
    try:
        from . import shell
        s = shell.shell()
        if s is not None and s.enabled:
            s.push_view()
    except Exception as _fw_err:
        _fw_log("namedviews.py:267", _fw_err)


def go_standard(key, doc=None, view=None):
    """A standard view button, key or View Selector face."""
    doc, view = doc or App.ActiveDocument, view or _view()
    if _armed:
        _armed[:] = []

        # Isometric, Trimetric and Dimetric cannot be updated: they turn as always and the update is dropped
        # (a tester saw the update's question box pop up on Isometric / Trimetric / Dimetric)
        if key in SETTABLE:
            return set_current_as(key, doc, view, ask=True)
    if key not in STANDARD or view is None:
        return False
    _push_current()
    fit = paths.params().GetBool(ZOOM_FIT, True)
    try:

        from . import camanim
        if camanim.animate_to(view, App.Rotation(*standard_rotation(key, doc).Q), fit=fit):
            return True
    except Exception as _fw_err:
        _fw_log("namedviews.py:camanim", _fw_err)
    if not turned(doc):
        Gui.runCommand(COMMANDS_OF[key], 0)
    else:
        try:
            view.stopAnimating()
        except Exception as _fw_err:
            _fw_log("namedviews.py:285", _fw_err)
        view.setCameraOrientation(standard_rotation(key, doc))
    if fit:
        fit_when_turned(view)
    return True


def fit_when_turned(view):
    """Zooms to fit once the view has turned (FreeCAD animates the turn)."""
    grp = App.ParamGet("User parameter:BaseApp/Preferences/View")
    turn = grp.GetInt("AnimationDuration", 250) if grp.GetBool("UseNavigationAnimations", True) else 0

    def fit():
        try:
            from .cleanopen import view_alive      # rcmenus pkg270: the view may be gone or hidden by now
            if not view_alive(view):
                return
            view.fitAll()
        except Exception as _fw_err:
            _fw_log("namedviews.py:301", _fw_err)
    QtCore.QTimer.singleShot(max(0, turn) + 60, fit)


# ---------------------------------------------------------------- commands
def _pixmap_of(name):
    """FreeCAD's picture for its own command (the standard views keep FreeCAD's icons)."""
    try:
        return Gui.Command.get(name).getInfo().get("pixmap", "") or ""
    except Exception:
        return ""


class _Cmd:
    def __init__(self, menu, tip, run, active=None, pixmap=""):
        self.menu, self.tip, self.run, self.active, self.pixmap = menu, tip, run, active, pixmap

    def GetResources(self):
        res = {"MenuText": self.menu, "ToolTip": self.tip, "CmdType": "ForEdit"}
        if self.pixmap:
            res["Pixmap"] = self.pixmap
        return res

    def Activated(self, checked=None):
        self.run()

    def IsActive(self):
        if App.ActiveDocument is None or Gui.ActiveDocument is None:
            return False
        return self.active() if self.active else True


def _commands():
    out = {
        "SWStyle_NewView": _Cmd("New View", "Saves the current view under a name.", ask_new_view),
        "SWStyle_UpdateStandardViews": _Cmd("Update Standard Views",
                                            "Then pick a standard view: it takes the current view, and the "
                                            "other standard views turn with it.", arm_update),
        # never greyed (no dead controls): with nothing changed it only asks and puts back what is there
        "SWStyle_ResetStandardViews": _Cmd("Reset Standard Views", "Puts back the default standard views.",
                                           reset_standard),
    }
    out["SWStyle_YUpViewOrientation"] = _Cmd("Y-Up", "Standard views with the Y axis up (Front looks at the Front Plane).",
                                              lambda: set_up_axis("Y"))
    out["SWStyle_ZUpViewOrientation"] = _Cmd("Z-Up", "Standard views with the Z axis up (Front looks at the Top Plane).",
                                              lambda: set_up_axis("Z"))
    for key in SETTABLE:
        out["SWStyle_SetCurrentViewAs" + key] = _Cmd(
            key, "Makes the current view the %s view." % key, lambda key=key: set_current_as(key, ask=True))
    for key in STANDARD:
        out["SWStyle_Standard" + key] = _Cmd(key, "Turns the view to the %s view." % key,
                                             lambda key=key: go_standard(key), pixmap=_pixmap_of(COMMANDS_OF[key]))
    return out


COMMANDS = list(_commands())
_installed = False


def install():
    global _installed
    if _installed:
        return
    for name, cmd in _commands().items():
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, cmd)
    # Y-Up and Z-Up are a pair: the one in use carries the check (it was greyed out before)
    try:
        from . import checkstate
        checkstate.register("SWStyle_YUpViewOrientation", lambda: App.ActiveDocument is not None and up_axis() == "Y")
        checkstate.register("SWStyle_ZUpViewOrientation", lambda: App.ActiveDocument is not None and up_axis() == "Z")
    except Exception as _fw_err:
        _fw_log("namedviews.py:checks", _fw_err)
    _installed = True
