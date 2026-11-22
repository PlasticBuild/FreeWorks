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

PREFIX = "SWStyle_SF_"

# the native commands (one per Sketch tab button) that get a wrapper
NATIVES = (
    "Sketcher_CreateLine", "SWStyle_3PointCornerRectangle", "SWStyle_3PointCenterRectangle", "SWStyle_Parallelogram",
    "Sketcher_CreateOblong", "Sketcher_CreateEllipseByCenter", "Sketcher_CreateArcOfEllipse",
    "Sketcher_CreateArcOfParabola", "SWStyle_Conic", "SWStyle_SketchText", "Sketcher_CreatePoint",
    "SWStyle_EquationDrivenCurve", "SWStyle_ConvertEntities", "SWStyle_SilhouetteEntities",
    "Sketcher_Intersection", "SWStyle_OffsetEntities",
)


def _in_sketch():
    gdoc = Gui.ActiveDocument
    try:
        vp = gdoc.getInEdit() if gdoc is not None else None
    except Exception:
        vp = None
    obj = getattr(vp, "Object", None)
    return obj is not None and obj.isDerivedFrom("Sketcher::SketchObject")


def _in_3d_sketch():
    try:
        from . import sketch3d
        return sketch3d.editing() is not None
    except Exception as _fw_err:
        _fw_log("sketchfirstlive.py:50", _fw_err)
        return False


class _Live:
    def __init__(self, native):
        self.native = native

    def GetResources(self):
        cmd = Gui.Command.get(self.native)
        info = {}
        try:
            info = cmd.getInfo() if cmd is not None else {}
        except Exception:
            info = {}
        text = info.get("menuText") or ""
        if not text or text == self.native:
            # the native may register after this wrapper: the catalog's label then (not "SWStyle_Conic")
            try:
                from . import catalog
                text = next((c.label for c in catalog.BY_KEY.values() if self.native in c.natives), "") or text
            except Exception as _fw_err:
                _fw_log("sketchfirstlive.py:70", _fw_err)
        return {"Pixmap": info.get("pixmap", "") or "", "MenuText": text or self.native,
                "ToolTip": info.get("toolTip", "") or "", "CmdType": "ForEdit"}

    def IsActive(self):
        cmd = Gui.Command.get(self.native)
        if cmd is None:
            return False
        if _in_sketch() or _in_3d_sketch():
            # a 3D sketch: the native's own state (sketch3d makes the shape tools draw in 3D)
            try:
                return bool(cmd.isActive())
            except Exception:
                return False
        from .fwsketch import sketchfirst
        return bool(sketchfirst.can_start())

    def Activated(self):
        if _in_sketch() or _in_3d_sketch():
            Gui.runCommand(self.native, 0)
            return
        from .fwsketch import sketchfirst
        sketchfirst.start_sketch_then(self.native)


def wrapper(native):
    return PREFIX + native


def register():
    have = set(Gui.listCommands())
    for native in NATIVES:
        name = wrapper(native)
        if name in have:
            continue
        try:
            Gui.addCommand(name, _Live(native))
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (name, error))
