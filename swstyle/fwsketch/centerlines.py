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
except ImportError:  # pragma: no cover
    Gui = None

KIND = "FreeWorksCenterlines"


def _construction_edges(sketch):
    edges = []
    for i, g in enumerate(sketch.Geometry):
        try:
            if not sketch.getConstruction(i):
                continue
        except Exception:
            continue
        if type(g).__name__ not in ("LineSegment", "ArcOfCircle", "Circle"):
            continue
        try:
            edges.append(g.toShape())
        except Exception as _fw_err:
            _fw_log("fwsketch/centerlines.py:48", _fw_err)
    return edges


class Centerlines:
    def __init__(self, obj):
        obj.Proxy = self
        self.Type = KIND
        if "Source" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Source", "Base", "The sketch whose centerlines these are")

    def execute(self, obj):
        import Part
        sk = obj.Source
        if sk is None:
            obj.Shape = Part.Shape()
            return
        edges = _construction_edges(sk)
        shape = Part.makeCompound(edges)
        # beside the sketch in the same Part/assembly: its own Placement; else the global one
        same = any(sk in getattr(o, "Group", []) for o in obj.InList)
        pl = sk.Placement if same else sk.getGlobalPlacement()
        obj.Shape = shape
        obj.Placement = pl

    def onDocumentRestored(self, obj):
        self.Type = KIND

    def dumps(self):
        return {"Type": KIND}

    def loads(self, state):
        self.Type = KIND


class ViewProviderCenterlines:
    def __init__(self, vobj):
        vobj.Proxy = self
        self._style(vobj)

    def _style(self, vobj):
        for name, value in (("LineColor", (0.75, 0.75, 0.75)), ("LineWidth", 1.0),
                            ("PointSize", 1.0), ("Selectable", True)):
            try:
                setattr(vobj, name, value)
            except Exception as _fw_err:
                _fw_log("fwsketch/centerlines.py:94", _fw_err)
        try:
            vobj.DrawStyle = "Dashdot"
        except Exception as _fw_err:
            _fw_log("fwsketch/centerlines.py:98", _fw_err)

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        return ":/icons/Sketcher_CreateLine.svg"

    def claimChildren(self):
        return []

    def onDelete(self, vobj, subs):
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def all_of(sketch):
    """Every preserved legacy companion, in document order, including duplicates."""
    found = []
    for o in getattr(sketch, "InList", []):
        proxy = getattr(o, "Proxy", None)
        mine = getattr(proxy, "Type", None) == KIND or type(proxy).__name__ == "Centerlines" \
            or (o.Name.startswith("Centerlines") and o.TypeId == "Part::FeaturePython")
        if mine and getattr(o, "Source", None) is sketch:
            found.append(o)
    return found


def of(sketch):
    """The first legacy companion, preserving the existing lookup behavior."""
    found = all_of(sketch)
    return found[0] if found else None


def _container(sketch):
    for o in sketch.InList:
        if o.isDerivedFrom("App::Part") or o.TypeId.startswith("Assembly::"):
            if sketch in getattr(o, "Group", []):
                return o
    return None


def ensure(sketch):
    """The canonical sketchcenterlines companion, made when the sketch has construction geometry."""
    if sketch is None or not sketch.isDerivedFrom("Sketcher::SketchObject"):
        return None
    from .. import sketchcenterlines
    obj = sketchcenterlines.companion(sketch)
    if obj is None:
        if not sketchcenterlines.construction_ids(sketch):
            return None
        obj = sketchcenterlines.make(sketch)
    try:
        obj.touch()
        obj.recompute()
    except Exception as _fw_err:
        _fw_log("fwsketch/centerlines.py:159", _fw_err)
    sync_visibility(sketch, obj)
    return obj


def sync_visibility(sketch, obj=None):
    obj = obj or of(sketch)
    if obj is None or getattr(obj, "ViewObject", None) is None:
        return
    try:
        editing = False
        gdoc = Gui.getDocument(sketch.Document.Name)
        vp = gdoc.getInEdit()
        editing = getattr(vp, "Object", None) is sketch
    except Exception as _fw_err:
        _fw_log("fwsketch/centerlines.py:174", _fw_err)
    try:
        want = (not editing) and bool(sketch.ViewObject.Visibility)
        if obj.ViewObject.Visibility != want:
            obj.ViewObject.Visibility = want
    except Exception as _fw_err:
        _fw_log("fwsketch/centerlines.py:180", _fw_err)


class _Watcher:
    """Polls the edited sketch; when one leaves edit its centerlines are made / refreshed."""

    def __init__(self):
        try:
            from PySide import QtCore
        except ImportError:  # pragma: no cover
            from PySide6 import QtCore
        self.last = None
        self.timer = QtCore.QTimer()
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def tick(self):
        try:
            gdoc = Gui.ActiveDocument
            vp = gdoc.getInEdit() if gdoc is not None else None
            cur = getattr(vp, "Object", None)
            if cur is not None and not cur.isDerivedFrom("Sketcher::SketchObject"):
                cur = None
        except Exception:
            cur = None
        last = self.last
        if cur is not last:
            self.last = cur
            if last is not None:
                try:
                    ensure(last)
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: centerlines: %s\n" % error)
            if cur is not None:
                sync_visibility(cur)

    def stop(self):
        self.timer.stop()


_watcher = None


def start():
    global _watcher
    if _watcher is None:
        _watcher = _Watcher()
    return _watcher


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None
