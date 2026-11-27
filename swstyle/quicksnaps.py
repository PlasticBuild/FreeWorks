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
from PySide import QtCore

from . import checkstate

PATH = "User parameter:BaseApp/Preferences/Mod/Sketcher/Snap"
SWITCHES = ("SnapToEndPoints", "SnapToCenterPoints", "SnapToMidpoints", "SnapToQuadrants", "SnapToIntersections",
            "SnapToNearest", "SnapToTangent", "SnapToPerpendicular", "SnapToParallel", "SnapToHVLines",
            "SnapToAlignments", "SnapToLength", "SnapToAngle", "SnapToGrid", "SnapToExtensions")
DEFAULTS = {"SnapToGrid": False}
MASTER = "SnapToObjects"       # the older single switch: kept on while a Quick Snap runs

# key -> (menu text, tooltip, switches left on)
SNAPS = {
    "Point": ("Point Snap", "Snaps to endpoints and sketch points of the next entity only.", ("SnapToEndPoints",)),
    "CenterPoint": ("Center Point Snap", "Snaps to centers of arcs and circles for the next entity only.", ("SnapToCenterPoints",)),
    "Midpoint": ("Midpoint Snap", "Snaps to midpoints for the next entity only.", ("SnapToMidpoints",)),
    "Quadrant": ("Quadrant Snap", "Snaps to quadrant points of arcs and circles for the next entity only.", ("SnapToQuadrants",)),
    "Intersection": ("Intersection Snap", "Snaps to intersections for the next entity only.", ("SnapToIntersections",)),
    "Nearest": ("Nearest Snap", "Snaps to the nearest point on an entity for the next entity only.", ("SnapToNearest",)),
    "Tangent": ("Tangent Snap", "Snaps tangent to arcs and circles for the next entity only.", ("SnapToTangent",)),
    "Perpendicular": ("Perpendicular Snap", "Snaps perpendicular to lines for the next entity only.", ("SnapToPerpendicular",)),
    "Parallel": ("Parallel Snap", "Snaps parallel to lines for the next entity only.", ("SnapToParallel",)),
    "HV": ("Horizontal/Vertical Snap", "Leaves only the horizontal and vertical guides for the next entity.", ("SnapToHVLines",)),
    "HVPoint": ("Horizontal/Vertical to Points Snap", "Lines up with existing points for the next entity only.", ("SnapToAlignments",)),
    "Length": ("Length Snap", "Snaps lengths to grid steps for the next entity only.", ("SnapToLength",)),
    "Grid": ("Grid Snap", "Snaps to grid points for the next entity only.", ("SnapToGrid",)),
    "Angle": ("Angle Snap", "Snaps to angle steps for the next entity only.", ("SnapToAngle",)),
}


def _params():
    return App.ParamGet(PATH)


def read_switches():
    p = _params()
    master = p.GetBool(MASTER, True)
    out = {k: p.GetBool(k, DEFAULTS.get(k, master)) for k in SWITCHES}
    out[MASTER] = master
    return out


def write_switches(values):
    p = _params()
    for k, v in values.items():
        p.SetBool(k, bool(v))


class _OneShot:
    """The active Quick Snap: which one, the switches to put back, and when."""

    def __init__(self):
        self.key = None
        self.saved = None
        self.sketch = None
        self.count = 0
        self.timer = QtCore.QTimer()
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.poll)

    def start(self, key, sketch):
        if self.key is not None:
            self.finish()
        self.saved = read_switches()
        # kept on disk too, so a FreeCAD that closes mid-snap gets the snaps back next start
        _params().SetString("QuickSnapSaved", ",".join("%s=%d" % (k, v) for k, v in self.saved.items()))
        keep = set(SNAPS[key][2])
        values = {k: (k in keep) for k in SWITCHES}
        values[MASTER] = True
        write_switches(values)
        self.key, self.sketch = key, sketch
        self.count = len(sketch.Geometry)
        self.tool_seen = _tool_running()
        self.timer.start()
        _refresh_tool()

    def finish(self):
        self.timer.stop()
        if self.saved is not None:
            write_switches(self.saved)
        _params().RemString("QuickSnapSaved")
        self.key, self.saved, self.sketch = None, None, None
        _refresh_tool()

    def poll(self):
        from .sketchextras import sketch_in_edit
        try:
            current = sketch_in_edit()
            if current is None or current != self.sketch or len(self.sketch.Geometry) > self.count:
                # the next entity is drawn, or the sketch closed: every snap goes back
                self.finish()
                return
            running = _tool_running()
            if running:
                self.tool_seen = True
            elif self.tool_seen:
                # the sketch tool ended (Esc, another tool) with nothing drawn: back as well
                self.finish()
        except Exception:
            self.finish()


def _refresh_tool():
    """fix286: the running sketch tool takes the switches at once."""
    try:
        from .fwsketch import snap
        snap.refresh_params()
    except Exception as _fw_err:
        _fw_log("quicksnaps.py:_refresh_tool", _fw_err)


def _tool_running():
    ""
    try:
        from .fwsketch import tool
        if tool.active() is not None:
            return True
    except Exception as _fw_err:
        _fw_log("quicksnaps.py:129", _fw_err)
    return False


ONE_SHOT = _OneShot()


def recover():
    """Put back snaps a Quick Snap left off when FreeCAD closed before the next entity."""
    text = _params().GetString("QuickSnapSaved", "")
    if not text:
        return False
    values = {}
    for item in text.split(","):
        k, _, v = item.partition("=")
        if k in SWITCHES or k == MASTER:
            values[k] = v == "1"
    write_switches(values)
    _params().RemString("QuickSnapSaved")
    return True


def quick_snap(key):
    from .sketchextras import sketch_in_edit
    sketch = sketch_in_edit()
    if sketch is None:
        return
    if ONE_SHOT.key == key:
        ONE_SHOT.finish()       # pressed again: off
        return
    ONE_SHOT.start(key, sketch)


class _Cmd:
    def __init__(self, key):
        self.key = key

    def GetResources(self):
        menu, tip, _ = SNAPS[self.key]
        return {"MenuText": menu, "ToolTip": tip, "CmdType": "ForEdit"}

    def Activated(self, checked=None):
        quick_snap(self.key)

    def IsActive(self):
        from .sketchextras import sketch_in_edit
        return sketch_in_edit() is not None


COMMANDS = ["SWStyle_QuickSnap" + k for k in SNAPS]
_installed = False


def install():
    global _installed
    if _installed:
        return
    recover()
    for key in SNAPS:
        name = "SWStyle_QuickSnap" + key
        if Gui.Command.get(name) is None:
            Gui.addCommand(name, _Cmd(key))
        checkstate.register(name, lambda key=key: ONE_SHOT.key == key)
    _installed = True
