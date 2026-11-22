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

from . import checkstate
from .smunfold import _icon

COMMAND = "SWStyle_SMNoBends"
ICON = "SheetMetal_UnfoldUnattended"
PROP = "SWNoBendsTip"


def _insert_bends(body):
    return next((o for o in body.Group if type(getattr(o, "Proxy", None)).__name__ == "SWInsertBends"), None)


def _body(doc=None):
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    try:
        body = Gui.ActiveDocument.ActiveView.getActiveObject("pdbody")
    except Exception:
        body = None
    if body is not None and _insert_bends(body) is not None:
        return body
    return next((o for o in doc.Objects if o.TypeId == "PartDesign::Body" and _insert_bends(o) is not None), None)


def is_rolled_back(doc=None):
    body = _body(doc)
    if body is None:
        return False
    ib = _insert_bends(body)
    return bool(getattr(ib, PROP, "")) and body.Tip is ib.BaseFeature


def set_no_bends(body, on):
    """Roll the part back to before Insert Bends (on), or forward to where it was."""
    ib = _insert_bends(body)
    if ib is None or ib.BaseFeature is None or is_rolled_back(body.Document) == bool(on):
        return
    doc = body.Document
    if PROP not in ib.PropertiesList:
        ib.addProperty("App::PropertyString", PROP, "Insert Bends", "Where No Bends rolled the part back from")
        ib.setEditorMode(PROP, 2)
    doc.openTransaction("No Bends")
    try:
        if on:
            setattr(ib, PROP, body.Tip.Name)
            body.Tip = ib.BaseFeature
        else:
            tip = doc.getObject(getattr(ib, PROP)) or ib
            setattr(ib, PROP, "")
            body.Tip = tip
        doc.recompute()
        try:
            for o in body.Group:
                if o.isDerivedFrom("PartDesign::Feature"):
                    o.ViewObject.Visibility = o is body.Tip
        except Exception as _fw_err:
            _fw_log("smnobends.py:79", _fw_err)
    except BaseException:
        try:
            doc.abortTransaction()
        except Exception:
            pass
        raise
    doc.commitTransaction()
    Gui.updateGui()


class Command:
    def GetResources(self):
        return {"Pixmap": _icon(ICON), "MenuText": "No Bends",
                "ToolTip": "Rolls the part back to before its bends were inserted. Click again to put them back.",
                "Checkable": is_rolled_back()}

    def IsActive(self):
        return _body() is not None

    def Activated(self, checked=None):
        body = _body()
        if body is not None:
            set_no_bends(body, not is_rolled_back(body.Document))


def blocked():
    """Sheet metal features grey out while the part is rolled back."""
    try:
        return is_rolled_back()
    except Exception as _fw_err:
        _fw_log("smnobends.py:112", _fw_err)
        return False


def register():
    if COMMAND not in Gui.listCommands():
        Gui.addCommand(COMMAND, Command())
    checkstate.register(COMMAND, is_rolled_back)
