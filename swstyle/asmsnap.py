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

from . import asmcore as ac

FOLDER = "Snapshots"
TYPE = "FwSnapshot"


class Snapshot:
    def __init__(self, obj):
        obj.Proxy = self
        self.Type = TYPE
        obj.addProperty("App::PropertyString", "Camera", "Snapshot", "The view (Coin camera)")
        obj.addProperty("App::PropertyStringList", "Shown", "Snapshot", "Components showing")
        obj.addProperty("App::PropertyStringList", "Hidden", "Snapshot", "Components hidden")
        for prop in ("Camera", "Shown", "Hidden"):
            obj.setEditorMode(prop, 2)

    def dumps(self):
        return {"Type": TYPE}

    def loads(self, state):
        self.Type = TYPE

    def execute(self, obj):
        pass


class ViewProviderSnapshot:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ":/icons/Std_ViewScreenShot.svg"     # FreeCAD's camera icon

    def doubleClicked(self, vobj):
        restore(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _doc(asm):
    """asm is the assembly, or the Large Design Review window of saved graphics (a document)."""
    return asm if isinstance(asm, App.Document) else asm.Document


def _comps(asm):
    if isinstance(asm, App.Document):
        from . import asmreview
        return asmreview.components(asm)
    return ac.components(asm)


def holder(doc):
    """What snapshots go in: the assembly, or the review window of saved graphics."""
    if doc is None:
        return None
    asm = ac.assembly_of(doc)
    if asm is not None:
        return asm
    from . import asmreview
    return doc if asmreview.is_review(doc) else None


def folder(asm, make=True):
    objs = [o for o in asm.Objects if not o.InList] if isinstance(asm, App.Document) else asm.Group
    for obj in objs:
        if obj.TypeId == "App::DocumentObjectGroup" and obj.Label == FOLDER:
            return obj
    if not make:
        return None
    if isinstance(asm, App.Document):
        group = asm.addObject("App::DocumentObjectGroup", "Snapshots")
    else:
        group = asm.newObject("App::DocumentObjectGroup", "Snapshots")
    group.Label = FOLDER
    return group


def snapshots(asm):
    group = folder(asm, make=False)
    return [o for o in group.Group if getattr(getattr(o, "Proxy", None), "Type", None) == TYPE] if group else []


def take(asm, view=None):
    """Snapshot<n> of the view and the components' shown/hidden state; returns it."""
    view = view or Gui.ActiveDocument.ActiveView
    comps = _comps(asm)
    snap = add(asm, None, view.getCamera(),
               [c.Name for c in comps if c.ViewObject is not None and c.ViewObject.Visibility],
               [c.Name for c in comps if c.ViewObject is not None and not c.ViewObject.Visibility])
    try:
        from . import asmui
        asmui.refresh()
    except Exception as _fw_err:
        _fw_log("asmsnap.py:122", _fw_err)
    return snap


def add(asm, label, camera, shown, hidden):
    """A snapshot from its parts (take, and the review window's snapshots carried into the assembly)."""
    doc = _doc(asm)
    doc.openTransaction("Take Snapshot")
    try:
        group = folder(asm)
        taken = {o.Label for o in snapshots(asm)}
        if not label or label in taken:
            n = 1
            while "Snapshot%d" % n in taken:
                n += 1
            label = "Snapshot%d" % n
        snap = doc.addObject("App::FeaturePython", "Snapshot")
        Snapshot(snap)
        if App.GuiUp:
            ViewProviderSnapshot(snap.ViewObject)
        snap.Label = label
        snap.Camera = camera
        snap.Shown = list(shown)
        snap.Hidden = list(hidden)
        group.addObject(snap)
    finally:
        doc.commitTransaction()
    return snap


def restore(snap, view=None):
    view = view or Gui.ActiveDocument.ActiveView
    doc = snap.Document
    for names, on in ((snap.Shown, True), (snap.Hidden, False)):
        for name in names:
            comp = doc.getObject(name)
            if comp is not None and comp.ViewObject is not None:
                comp.ViewObject.Visibility = on
    if snap.Camera:
        view.setCamera(snap.Camera)


class TakeSnapshotCommand:
    def GetResources(self):
        return {"MenuText": "Take Snapshot", "Pixmap": "Std_ViewScreenShot",
                "ToolTip": "Saves the view and the shown components as a snapshot; double-click it to go back.",
                # pkg311: live while a PropertyManager is open (it only saves the view): FreeCAD greyed it
                "CmdType": "ForEdit"}

    def Activated(self):
        asm = holder(App.ActiveDocument)
        if asm is not None:
            take(asm)

    def IsActive(self):
        return holder(App.ActiveDocument) is not None and Gui.ActiveDocument is not None


COMMANDS = (("SWStyle_TakeSnapshot", TakeSnapshotCommand),)
