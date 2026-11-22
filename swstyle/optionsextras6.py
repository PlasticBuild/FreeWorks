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

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

DIMXPERT_TOP = ("Display", "Display DimXpert dimensions on top of model")
FACET_FINS = ("Display", "Display facet fins in Mesh BREP bodies")
SM_SELF_CHECK = ("Performance", "Ignore self-intersection check for some sheet metal features")
MAXIMIZE = ("General", "Maximize document on open")

_state = {"observer": None, "wrapped": False}


def _kept(key, default=False):
    from . import optionspages
    return bool(optionspages.stored(key[0], key[1], default))


# Mesh BREP bodies ------------------------------------------------------------------------------
def is_mesh_brep(obj):
    """A body made from a mesh: every face a flat triangle (Part > Shape from Mesh, imported STL)."""
    if getattr(obj, "TypeId", "") not in ("Part::Feature", "Part::FeaturePython"):
        return False
    # look-audit finsnull-1120: a Shape property can be a link to a part (FEM meshes), not a shape
    shape = getattr(obj, "Shape", None)
    if shape is None or not hasattr(shape, "isNull") or not hasattr(shape, "Faces"):
        return False
    if shape.isNull() or len(shape.Faces) < 4:
        return False
    for face in shape.Faces:
        if len(face.Edges) != 3 or type(face.Surface).__name__ != "Plane":
            return False
    return True


def apply_facet_fins(doc=None):
    """On: mesh BREP bodies show their facet edges (Flat Lines). Off: those shown that way go back to
    Shaded. Returns how many bodies changed."""
    docs = [doc] if doc is not None else list(App.listDocuments().values())
    on, changed = _kept(FACET_FINS, True), 0
    for d in docs:
        for obj in d.Objects:
            vo = getattr(obj, "ViewObject", None)
            if vo is None or not hasattr(vo, "DisplayMode") or not is_mesh_brep(obj):
                continue
            want = "Flat Lines" if on else "Shaded"
            if on and vo.DisplayMode == "Flat Lines" or not on and vo.DisplayMode != "Flat Lines":
                continue
            if want in vo.listDisplayModes():
                vo.DisplayMode = want
                changed += 1
    return changed


# DimXpert on top ---------------------------------------------------------------------------------
def apply_dimxpert(doc=None):
    from . import mbd
    for d in [doc] if doc is not None else list(App.listDocuments().values()):
        mbd.restyle_all(d)


# Sheet metal self-intersection check ------------------------------------------------------------
def _wrap_sheet_tree():
    if _state["wrapped"]:
        return
    import SheetMetalUnfolder as smu
    original = smu.SheetTree.__init__

    def init(self, *args, **kw):
        original(self, *args, **kw)
        try:
            if getattr(self, "error_code", None) == 4 and _kept(SM_SELF_CHECK):
                self.error_code = None
                self.failed_face_idx = None
        except Exception as _fw_err:
            _fw_log("optionsextras6.py:94", _fw_err)
    init.freeworks_original = original
    smu.SheetTree.__init__ = init
    _state["wrapped"] = True


def maximize_active():
    """General > Maximize document on open: the new window fills the graphics area (in FreeCAD's
    sub-window mode; in tab mode every document already fills it)."""
    try:
        from PySide import QtWidgets
        area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = area.activeSubWindow() if area is not None else None
        if sub is not None and area.viewMode() == QtWidgets.QMdiArea.SubWindowView and not sub.isMaximized():
            sub.showMaximized()
            return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD maximize on open: %s\n" % error)
    return False


class _Observer:
    def slotCreatedDocument(self, doc):
        try:
            if True:
                from PySide import QtCore
                QtCore.QTimer.singleShot(300, maximize_active)       # once its window is made
        except Exception as _fw_err:
            _fw_log("optionsextras6.py:122", _fw_err)

    def slotRecomputedDocument(self, doc):
        try:
            if _kept(FACET_FINS, True):
                apply_facet_fins(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD facet fins: %s\n" % error)


def refresh():
    """After the Options box is saved."""
    for fn in (apply_facet_fins, apply_dimxpert):
        try:
            fn()
        except Exception as error:
            App.Console.PrintLog("FreeCAD options6 %s: %s\n" % (fn.__name__, error))


# --------------------------------------------------------------------------- Performance > Transparency
VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
_dyn = {"moving": False, "kept": None, "timer": None}


def _dynamic_hq():
    try:
        from . import optionspages
        return optionspages.stored("Performance", "High quality for dynamic view mode", True)
    except Exception:
        return True


def _set_render(kind):
    App.ParamGet(VIEW_PARAMS).SetString("TransparentObjectRenderType", kind)


def _view_moving(obj, event):
    ""

    from PySide import QtCore
    try:
        if _dynamic_hq() or not obj.inherits("QOpenGLWidget"):
            return False
        t = event.type()
        QE = QtCore.QEvent
        params = App.ParamGet(VIEW_PARAMS)
        if t in (QE.MouseButtonPress, QE.Wheel) and not _dyn["moving"]:
            if params.GetString("TransparentObjectRenderType", "") != "Backface":
                return False        # High quality for normal view mode is off: nothing to lower
            _dyn["moving"], _dyn["kept"] = True, "Backface"
            _set_render("Auto")
        if _dyn["moving"] and t in (QE.MouseButtonRelease, QE.Wheel):
            if _dyn["timer"] is None:
                _dyn["timer"] = QtCore.QTimer()
                _dyn["timer"].setSingleShot(True)
                _dyn["timer"].timeout.connect(_view_stopped)
            _dyn["timer"].start(400 if t == QE.Wheel else 50)
    except Exception as _fw_err:
        _fw_log("optionsextras6.py:180", _fw_err)
    return False


def _view_stopped():
    from PySide import QtCore  # noqa: F401
    if _dyn["moving"]:
        _dyn["moving"] = False
        _set_render(_dyn["kept"] or "Backface")


def _install_dynamic():
    from PySide import QtCore
    from . import events
    events.register("options-dynamic-hq", (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                                           QtCore.QEvent.Wheel), _view_moving)


def install():
    try:
        _install_dynamic()
    except Exception as error:
        App.Console.PrintLog("FreeCAD dynamic view quality: %s\n" % error)
    try:
        _wrap_sheet_tree()
    except Exception as error:
        App.Console.PrintLog("FreeCAD sheet metal check: %s\n" % error)
    if Gui is None or _state["observer"] is not None:
        return
    obs = _Observer()
    App.addDocumentObserver(obs)
    _state["observer"] = obs
