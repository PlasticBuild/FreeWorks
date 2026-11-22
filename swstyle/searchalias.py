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

# (search name, command to run, tip)
ALIASES = (
    ("Delete Body", "SWStyle_DeleteKeepBody", "Deletes or keeps solid bodies."),
    ("Lofted Bend", "SWStyle_SMLoftedBend", "Makes a sheet metal transition between two open profiles."),
    ("Break Corner", "SWStyle_SMBreakCorner", "Chamfers or fillets sheet metal corners."),
    ("Surface Flatten", "SWStyle_Flatten", "Lays a curved face or surface out flat."),
    ("Parting Surfaces", "SWStyle_PartingSurface", "Adds a parting surface to a mould design."),
    ("Dimension Expert", "FreeWorks_SmartDimension", "Dimensions the picked geometry (Smart Dimension)."),
    ("Dimensioning", "FreeWorks_SmartDimension", "Dimensions the picked geometry (Smart Dimension)."),
) + tuple((n + " Mate", "SWStyle_Mate", "Opens Mate: pick the two faces, then the " + n.lower() + " type.")
          for n in ("Slot", "Gear", "Rack Pinion", "Cam", "Path", "Hinge", "Distance", "Angle", "Tangent", "Concentric",
                    "Coincident", "Parallel", "Perpendicular", "Lock", "Width", "Symmetric"))
FLOW = ("Flow Simulation", "Opens the CFD workbench (CfdOF when installed), else the FEM workbench.")


def _flow_workbench():
    have = Gui.listWorkbenches()
    for name in ("CfdOFWorkbench", "FemWorkbench"):
        if name in have:
            return name
    return None


def _name(label):
    return "FW_Alias_" + "".join(ch for ch in label if ch.isalnum())


class _Alias:
    def __init__(self, label, target, tip):
        self.label, self.target, self.tip = label, target, tip

    def GetResources(self):
        return {"MenuText": self.label, "ToolTip": self.tip}

    def IsActive(self):
        if self.target == "flow":
            return _flow_workbench() is not None
        if not self.target:
            return False
        try:
            return bool(Gui.Command.get(self.target).isActive())
        except Exception:
            return False           # its module is not loaded yet (greyed until it is)

    def Activated(self):
        if self.target == "flow":
            Gui.activateWorkbench(_flow_workbench())
            return
        if not self.target:
            try:
                Gui.getMainWindow().statusBar().showMessage("%s: %s" % (self.label, self.tip), 8000)
            except Exception as _fw_err:
                _fw_log("searchalias.py:76", _fw_err)
            return
        Gui.runCommand(self.target, 0)


def install():
    if Gui is None:
        return
    taken = set()
    for name in Gui.listCommands():
        try:
            taken.add((Gui.Command.get(name).getInfo().get("menuText") or "").replace("&", "").lower())
        except Exception:
            continue
    have = set(Gui.listCommands())
    n = 0
    for label, target, tip in ALIASES + ((FLOW[0], "flow", FLOW[1]),):
        if label.lower() in taken or _name(label) in have:
            continue
        Gui.addCommand(_name(label), _Alias(label, target, tip))
        n += 1
    App.Console.PrintLog("FreeCAD: %d more Search Commands names\n" % n)
