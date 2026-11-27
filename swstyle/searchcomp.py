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

import time

import FreeCAD as App

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None


LABELS = ("Add SpeedPak", "Remove SpeedPak", "Replace Components", "Dissolve Subassembly", "Make Subassembly Flexible",
          "Make Subassembly Rigid", "Form New Subassembly", "Make Independent", "Make Virtual", "Temporary Fix/Group",
          "Release Temporary Fix/Group", "Set to Lightweight", "Set to Resolved", "Component Properties...", "Copy with Mates",
          "View Mates", "Reload", "Configure Component", "Add to Library", "Save Part (in External File)",
          "Edit Toolbox Definition")
HINT = "Pick a component of the assembly first. Runs the same entry as the component's right-click menu; grayed when it does not apply to it."
_cache = {"at": 0.0, "key": None, "items": None}


def selected_component():
    from . import asmmenu
    for obj in Gui.Selection.getSelection():
        try:
            if asmmenu.is_component(obj):
                return obj
        except Exception as _fw_err:
            _fw_log("searchcomp.py:49", _fw_err)
            continue
    return None


def _items(comp):
    """{label: (run, enabled)} for the component, a moment cached (the command list is asked often)."""
    key = (comp.Document.Name, comp.Name)
    now = time.time()
    if _cache["key"] == key and now - _cache["at"] < 0.4:
        return _cache["items"]
    from . import asmmenu
    items = {}
    for it in list(asmmenu.component_items(comp)) + [i[:4] for i in asmmenu.sw_component_items(comp, True)]:
        if callable(it[2]):
            items.setdefault(it[1], (it[2], bool(it[3])))
    _cache.update(at=now, key=key, items=items)
    return items


class _Cmd:
    def __init__(self, label):
        self.label = label

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": HINT}

    def _entry(self):
        try:
            comp = selected_component()
            return _items(comp).get(self.label) if comp is not None else None
        except Exception as _fw_err:
            _fw_log("searchcomp.py:81", _fw_err)
            return None

    def IsActive(self):
        entry = self._entry()
        return bool(entry and entry[1])

    def Activated(self):
        entry = self._entry()
        if not entry or not entry[1]:
            try:
                Gui.getMainWindow().statusBar().showMessage("%s: %s" % (self.label, HINT), 8000)
            except Exception as _fw_err:
                _fw_log("searchcomp.py:91", _fw_err)
            return
        try:
            entry[0]()
        except Exception as error:
            App.Console.PrintError("%s: %s\n" % (self.label, error))


def _name(label):
    return "FW_Comp_" + "".join(c for c in label if c.isalnum())


def install():
    if Gui is None:
        return
    taken = set()
    try:
        from . import catalog
        taken.update(c.label.lower() for c in catalog.ALL)
    except Exception as _fw_err:
        _fw_log("searchcomp.py:111", _fw_err)
    for name in Gui.listCommands():
        try:
            taken.add((Gui.Command.get(name).getInfo().get("menuText") or "").replace("&", "").lower())
        except Exception:
            continue
    for label in LABELS:
        if label.lower() in taken or _name(label) in Gui.listCommands():
            continue                       # a command by that name exists already
        Gui.addCommand(_name(label), _Cmd(label))
