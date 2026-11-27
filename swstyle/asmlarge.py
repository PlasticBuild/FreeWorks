# SPDX-License-Identifier: LGPL-2.1-or-later
""







_FW_SEEN = set()



def _qt_safe(fn):
    """A tree Model override that never lets an error out into Qt (FreeCAD on Windows aborts):
    rows of objects deleted while a document closes give no data."""
    def data(self, index, role=0):
        try:
            return fn(self, index, role)
        except Exception as error:
            if not isinstance(error, (ReferenceError, RuntimeError)):
                App.Console.PrintLog("FreeCAD: tree row: %r\n" % (error,))
            return None
    return data

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
from PySide import QtCore, QtGui

from . import checkstate

PARAM = "User parameter:BaseApp/Preferences/Mod/SWStyle/LargeAssembly"
DOC_PARAM = "User parameter:BaseApp/Preferences/Document"
SETTINGS = (
    ("NoAutoRecover", "Do not save auto recover info", False),
    ("NoRebuildSwitch", "Do not rebuild when switching to assembly window", False),
    ("HideRefs", "Hide all planes, axes, sketches, curves, annotations, etc.", True),
    ("NoEdges", "Do not display edges in shaded mode", True),
    ("NoPreview", "Do not preview hidden components", False),
    ("NoVerify", "Disable verification on rebuild", False),
    ("Optimize", "Optimize image quality for better performance", False),
    ("Suspend", "Suspend automatic rebuild", False),
)
CHECK_PARAM = "User parameter:BaseApp/Preferences/Mod/Part/Boolean"
FAST_DEVIATION = 2.0
FAST_ANGULAR = 28.5
                            # which is most of what a curved part costs to draw (bench, 144 parts: 37 -> 30 ms a frame)
REF_TYPES = ("App::Origin", "App::Line", "App::Plane", "App::Point", "App::DatumLine", "App::DatumPlane",
             "App::DatumPoint", "PartDesign::Plane", "PartDesign::Line", "PartDesign::Point",
             "PartDesign::CoordinateSystem", "Part::Datum", "Sketcher::SketchObject", "Part::Part2DObjectPython")
SHADED, FLAT_LINES, AS_IS = 5, 6, 0     # FreeCAD's Std_DrawStyle list

STATE = {"on": False, "hidden": [], "draw": None, "autosave": None, "check": None, "deviation": {},
         "frozen": []}


def _p():
    return App.ParamGet(PARAM)


def setting(key):
    return _p().GetBool(key, dict((k, d) for k, _t, d in SETTINGS)[key])


def is_on():
    return STATE["on"]


# ---------------------------------------------------------------- the three settings
def _docs():
    """The active document and the part documents its components come from."""
    doc = App.ActiveDocument
    if doc is None:
        return []
    out = [doc]
    for o in doc.Objects:
        linked = getattr(o, "LinkedObject", None)
        if linked is not None and linked is not o and linked.Document not in out:
            out.append(linked.Document)
    return out


def _is_ref(obj):
    if obj.TypeId in REF_TYPES or obj.isDerivedFrom("Sketcher::SketchObject"):
        return True
    return obj.isDerivedFrom("Part::Datum") or obj.isDerivedFrom("App::DatumElement")


def hide_refs(on):
    if on:
        for doc in _docs():
            for obj in doc.Objects:
                vo = getattr(obj, "ViewObject", None)
                if vo is not None and _is_ref(obj) and vo.Visibility:
                    vo.Visibility = False
                    STATE["hidden"].append((doc.Name, obj.Name))
    else:
        for dname, oname in STATE["hidden"]:
            try:
                obj = App.getDocument(dname).getObject(oname)
            except Exception:
                obj = None
            if obj is not None and getattr(obj, "ViewObject", None) is not None:
                obj.ViewObject.Visibility = True
        STATE["hidden"] = []


def draw_style():
    ""


    try:
        for i, act in enumerate(Gui.Command.get("Std_DrawStyle").getAction()):
            if act.isChecked():
                if i == FLAT_LINES:
                    try:
                        from . import hlv
                        if hlv.shaded():
                            return SHADED
                    except Exception as _fw_err:
                        _fw_log("asmlarge.py:hlv shaded", _fw_err)
                return i
    except Exception as _fw_err:
        _fw_log("asmlarge.py:107", _fw_err)
    return None


def set_draw_style(index):
    """runCommand("Std_DrawStyle", n) leaves the view as it is: the group's action is triggered."""
    try:
        Gui.Command.get("Std_DrawStyle").getAction()[index].trigger()
    except Exception as error:
        App.Console.PrintError("FreeCAD: draw style %d: %s\n" % (index, error))


def no_edges(on):
    if Gui.ActiveDocument is None:
        return
    if on:
        now = draw_style()
        if now in (AS_IS, FLAT_LINES, None):
            STATE["draw"] = now if now is not None else AS_IS
            set_draw_style(SHADED)
    elif STATE["draw"] is not None:
        if draw_style() == SHADED:
            set_draw_style(STATE["draw"])
        STATE["draw"] = None


def no_auto_recover(on):
    p = App.ParamGet(DOC_PARAM)
    if on:
        if STATE["autosave"] is None:
            STATE["autosave"] = p.GetBool("AutoSaveEnabled", True)
        p.SetBool("AutoSaveEnabled", False)
    elif STATE["autosave"] is not None:
        p.SetBool("AutoSaveEnabled", STATE["autosave"])
        STATE["autosave"] = None


def no_rebuild_switch(on):
    """Do not rebuild when switching to assembly window: _SwitchWatch asks rebuild_on_switch()."""
    return None


def rebuild_on_switch():
    return not (STATE["on"] and setting("NoRebuildSwitch"))


def _stamp(asm):
    """What the assembly's parts were when it was last rebuilt: each part document's last change."""
    from . import asmcore as ac
    out = []
    for comp in ac.components(asm):
        target = getattr(comp, "LinkedObject", None)
        d = getattr(target, "Document", None)
        if d is None or d is asm.Document:
            continue
        try:
            out.append((d.Name, str(getattr(target, "Shape", None) and target.Shape.hashCode()),
                        tuple(sorted(o.Name for o in d.Objects if "Touched" in o.State))))
        except Exception:
            out.append((d.Name, "?", ()))
    return tuple(sorted(out))


SWITCH = {}     # assembly document name -> _stamp when its window was left


def switch_to(doc):
    ""

    from . import asmcore as ac
    asm = ac.assembly_of(doc) if doc is not None else None
    if asm is None:
        return None
    before = SWITCH.get(doc.Name)
    now = _stamp(asm)
    SWITCH[doc.Name] = now
    if before is None or before == now:
        return None
    if not rebuild_on_switch():
        try:
            asm.touch()
        except Exception as _fw_err:
            _fw_log("asmlarge.py:189", _fw_err)
        return False
    try:
        from . import asmextref
        asmextref.rebind(asm)       # in-context sketches keep their converted edges
    except Exception:
        pass
    for name in {n for n, *_r in now}:
        d = App.listDocuments().get(name)
        if d is not None:
            try:
                d.recompute()
            except Exception as _fw_err:
                _fw_log("asmlarge.py:197", _fw_err)
    try:
        ac.solve(asm)
        doc.recompute()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: rebuild on switch: %s\n" % error)
    SWITCH[doc.Name] = _stamp(asm)
    return True


class _SwitchWatch:
    def slotActivateDocument(self, doc):
        try:
            switch_to(doc)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: switch watch: %s\n" % error)

    def slotDeletedDocument(self, doc):
        # closed: a file opened again under the same name starts afresh (it was rebuilt and
        # solved twice on its first activation: 30 s for a 300-mate assembly)
        try:
            SWITCH.pop(doc.Name, None)
        except Exception as _fw_err:
            _fw_log("asmlarge.py:closed", _fw_err)


_SWITCH_WATCH = []


def no_preview(on):
    """Do not preview hidden components: asmfmoptions asks preview_blocked()."""
    return None


def preview_blocked():
    return STATE["on"] and setting("NoPreview")


def no_verify(on):
    """Disable verification on rebuild: FreeCAD's check of the shape after each Boolean."""
    p = App.ParamGet(CHECK_PARAM)
    if on:
        if STATE["check"] is None:
            STATE["check"] = p.GetBool("CheckModel", True)
        p.SetBool("CheckModel", False)
    elif STATE["check"] is not None:
        p.SetBool("CheckModel", STATE["check"])
        STATE["check"] = None


def optimize(on):
    """Optimize image quality for better performance: the parts drawn with a coarser mesh."""
    if on:
        for doc in _docs():
            for obj in doc.Objects:
                vo = getattr(obj, "ViewObject", None)
                if vo is None or not hasattr(vo, "Deviation"):
                    continue
                key = (doc.Name, obj.Name)
                if key not in STATE["deviation"]:
                    STATE["deviation"][key] = (vo.Deviation, _angular(vo))
                try:
                    if vo.Deviation < FAST_DEVIATION:
                        vo.Deviation = FAST_DEVIATION
                    ang = _angular(vo)
                    if ang is not None and ang < FAST_ANGULAR:
                        vo.AngularDeflection = FAST_ANGULAR
                except Exception as _fw_err:
                    _fw_log("asmlarge.py:254", _fw_err)
    else:
        for (dname, oname), kept in STATE["deviation"].items():
            dev, ang = kept if isinstance(kept, tuple) else (kept, None)
            try:
                vo = App.getDocument(dname).getObject(oname).ViewObject
                vo.Deviation = dev
                if ang is not None and hasattr(vo, "AngularDeflection"):
                    vo.AngularDeflection = ang
            except Exception as _fw_err:
                _fw_log("asmlarge.py:260", _fw_err)
        STATE["deviation"] = {}


def _angular(vo):
    """The view object's angular deviation in degrees, None when it has none."""
    try:
        a = vo.AngularDeflection
    except Exception:
        return None
    return a.Value if hasattr(a, "Value") else float(a)


def suspend(on):
    """Suspend automatic rebuild: nothing rebuilds on its own, our PMs' OK included (FreeCAD's
    doc.recompute() does nothing on a frozen document); the changed features and the top row show
    the rebuild mark until Rebuild (Ctrl+B) or Forced Rebuild (Ctrl+Q)."""
    if on:
        _patch_tree()
        for doc in _docs():
            if hasattr(doc, "RecomputesFrozen") and not doc.RecomputesFrozen:
                doc.RecomputesFrozen = True
                STATE["frozen"].append(doc.Name)
        _patch_rebuild()
    else:
        for name in STATE["frozen"]:
            d = App.listDocuments().get(name)
            if d is not None:
                d.RecomputesFrozen = False
        STATE["frozen"] = []


def needs_rebuild(obj):
    """The rebuild mark: a frozen document's feature waiting for Rebuild."""
    try:
        doc = obj.Document
        return bool(getattr(doc, "RecomputesFrozen", False)) and "Touched" in obj.State
    except Exception:
        return False


def _rebuild_icon(icon):
    """The row's icon with a small amber circular-arrow rebuild mark at its lower right."""
    size = 16
    pm = icon.pixmap(size, size) if isinstance(icon, QtGui.QIcon) else QtGui.QPixmap(size, size)
    if not isinstance(icon, QtGui.QIcon):
        pm.fill(QtCore.Qt.transparent)
    pm = QtGui.QPixmap(pm)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#f2b01e"))
    p.drawEllipse(QtCore.QRectF(7, 7, 9, 9))
    pen = QtGui.QPen(QtGui.QColor("#202020"), 1.4)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    p.drawArc(QtCore.QRectF(9, 9, 5, 5), 60 * 16, 270 * 16)
    p.end()
    return QtGui.QIcon(pm)


def _patch_tree():
    try:
        from . import fmtree
    except Exception:
        return
    if getattr(fmtree.Model, "_fw_rebuild_mark", False):
        return
    data0 = fmtree.Model.data

    def data(self, index, role=QtCore.Qt.DisplayRole):
        value = data0(self, index, role)
        if role == QtCore.Qt.DecorationRole and index.isValid() and STATE["frozen"] and getattr(self, "_fw_asm", True):
            node = self.node(index)
            obj = getattr(node, "obj", None) if node is not None else None
            try:
                if obj is not None and needs_rebuild(obj):
                    return _rebuild_icon(value)
                if node is not None and node is getattr(self, "part", None):
                    doc = getattr(self, "doc", None)
                    if doc is not None and getattr(doc, "RecomputesFrozen", False) \
                            and any("Touched" in o.State for o in doc.Objects):
                        return _rebuild_icon(value)
            except ReferenceError as _fw_err:
                _fw_log("asmlarge.py:335", _fw_err)
        return value
    fmtree.Model.data = _qt_safe(data)
    fmtree.Model._fw_rebuild_mark = True


def _patch_rebuild():
    try:
        from . import keys
    except Exception:
        return
    if getattr(keys, "_fw_large_patched", False):
        return
    original = keys.rebuild

    def rebuild(*a, **k):
        frozen = [d for d in App.listDocuments().values() if getattr(d, "RecomputesFrozen", False)]
        for d in frozen:
            d.RecomputesFrozen = False
        try:
            return original(*a, **k)
        finally:
            for d in frozen:
                d.RecomputesFrozen = True
    keys.rebuild = rebuild
    keys._fw_large_patched = True


PIXMAPS = {"NoRebuildSwitch": "view-refresh", "HideRefs": "Std_HideSelection", "NoEdges": "DrawStyleShaded", "NoAutoRecover": "document-save",
           "NoPreview": "Std_ToggleVisibility", "NoVerify": "Part_CheckGeometry", "Optimize": "DrawStyleAsIs",
           "Suspend": "view-refresh"}
APPLY = {"NoRebuildSwitch": no_rebuild_switch, "HideRefs": hide_refs, "NoEdges": no_edges, "NoAutoRecover": no_auto_recover, "NoPreview": no_preview,
         "NoVerify": no_verify, "Optimize": optimize, "Suspend": suspend}


def set_mode(on):
    on = bool(on)
    if on == STATE["on"]:
        return
    STATE["on"] = on
    for key, _t, _d in SETTINGS:
        if setting(key):
            APPLY[key](on)
    App.Console.PrintMessage("Large Assembly Mode %s\n" % ("on" if on else "off"))


def set_setting(key, value):
    _p().SetBool(key, bool(value))
    if STATE["on"]:
        APPLY[key](bool(value))


# ---------------------------------------------------------------- commands
class _Toggle:
    def __init__(self, text, tip, get, put, pixmap):
        self.text, self.tip, self.get, self.put, self.pixmap = text, tip, get, put, pixmap

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": self.pixmap}

    def Activated(self, *args):
        self.put(not self.get())

    def IsActive(self):
        return App.ActiveDocument is not None


def _mode_cmd():
    return _Toggle("Large Assembly Mode", "Turns on the checked settings below for a faster assembly.",
                   is_on, set_mode, "Assembly_InsertLink")


def _setting_cmd(key, text):
    return _Toggle(text, text + ".", lambda k=key: setting(k), lambda v, k=key: set_setting(k, v), PIXMAPS[key])


COMMANDS = [("SWStyle_LargeAssemblyMode", _mode_cmd())] + \
    [("SWStyle_Large" + key, _setting_cmd(key, text)) for key, text, _d in SETTINGS]
CATALOG = [("LargeAssemblyMode", "Large Assembly Mode", "SWStyle_LargeAssemblyMode",
            "Turns on the checked settings below for a faster assembly.")] + \
    [("Large" + key, text, "SWStyle_Large" + key, text + ".") for key, text, _d in SETTINGS]
FLYOUT = tuple(k for k, *_ in CATALOG)


def register():
    for name, cmd in COMMANDS:
        try:
            Gui.addCommand(name, cmd)
        except Exception as _fw_err:
            _fw_log("asmlarge.py:424", _fw_err)
        checkstate.register(name, cmd.get)
    if not _SWITCH_WATCH:
        _SWITCH_WATCH.append(_SwitchWatch())
        App.addDocumentObserver(_SWITCH_WATCH[0])
