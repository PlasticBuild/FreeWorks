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
from . import geomkeep

SKETCH = "Sketcher::SketchObject"
PLANES = ("App::Plane", "PartDesign::Plane")


def _picks():
    """(sketch, (support object, [sub]))."""
    sketch, support = None, None
    for entry in Gui.Selection.getSelectionEx():
        obj = entry.Object
        if obj.TypeId == SKETCH and sketch is None and not entry.SubElementNames:
            sketch = obj
            continue
        subs = [s for s in entry.SubElementNames if s.startswith("Face")]
        if obj.TypeId in PLANES or obj.isDerivedFrom("App::Plane"):
            support = (obj, [""])
        elif subs:
            support = (obj, subs[:1])
        elif obj.TypeId == SKETCH and sketch is not None:
            support = None
    return sketch, support


def _body_of(obj):
    try:
        for parent in obj.InList:
            if parent.TypeId == "PartDesign::Body":
                return parent
    except Exception as _fw_err:
        _fw_log("derivedsketch.py:59", _fw_err)
    return None


def derive(parent, support):
    """The derived sketch on support (object, [sub]); raises on failure."""
    doc = parent.Document
    body = _body_of(parent)
    name = "Sketch"
    derived = body.newObject(SKETCH, name) if body is not None else doc.addObject(SKETCH, name)
    derived.Label = "%s (derived)" % parent.Label
    derived.MapMode = "Deactivated"
    derived.Placement = parent.Placement
    if derived.carbonCopy(parent.Name, False) is not None and len(derived.Geometry) == 0 and len(parent.Geometry):
        raise RuntimeError("FreeCAD refused the carbon copy")
    _float(derived)
    obj, subs = support
    derived.AttachmentSupport = [(obj, subs[0] if subs and subs[0] else "")]
    derived.MapMode = "FlatFace"
    if "SWDerivedFrom" not in derived.PropertiesList:
        derived.addProperty("App::PropertyLink", "SWDerivedFrom", "Sketch", "The sketch this one is derived from")
    derived.SWDerivedFrom = parent
    _counts(derived, parent)
    doc.recompute()
    return derived


def _counts(derived, parent):
    """What came from the parent: its geometry count, and how many of the derived sketch's
    constraints are copies (the ones after them are the user's, placing the sketch)."""
    for name, value in (("SWDerivedGeo", len(parent.Geometry)), ("SWDerivedCons", len(derived.Constraints))):
        if name not in derived.PropertiesList:
            derived.addProperty("App::PropertyInteger", name, "Sketch", "Derived sketch bookkeeping")
            derived.setPropertyStatus(name, "Hidden")
        setattr(derived, name, value)


def follow(derived):
    ""


    parent = getattr(derived, "SWDerivedFrom", None)
    if parent is None or "SWDerivedGeo" not in derived.PropertiesList:
        return False
    if len(parent.Geometry) == derived.SWDerivedGeo:
        return False
    keep = list(derived.Constraints)[derived.SWDerivedCons:]
    shift = _shift(derived, parent)
    support, mode, offset = derived.AttachmentSupport, derived.MapMode, derived.AttachmentOffset
    place = derived.Placement
    for path, _e in list(derived.ExpressionEngine):
        try:
            derived.setExpression(path, None)
        except Exception as _fw_err:
            _fw_log("derivedsketch.py:113", _fw_err)
    derived.deleteAllGeometry()
    derived.MapMode = "Deactivated"
    derived.Placement = parent.Placement
    derived.carbonCopy(parent.Name, False)
    _float(derived)
    _counts(derived, parent)
    if shift.Length > 1e-9:

        # sketch was placed, not where they sit in the parent
        moved = []
        for g in geomkeep.read(derived):
            g = g.copy()
            g.translate(shift)
            moved.append(g)
        derived.Geometry = moved
    n = len(derived.Geometry)
    for c in keep:
        refs = [getattr(c, k, -2000) for k in ("First", "Second", "Third")]
        if any(r >= n for r in refs):
            continue                # its geometry left the parent
        try:
            derived.addConstraint(c)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: derived sketch relation not kept: %s\n" % error)
    derived.AttachmentSupport, derived.MapMode, derived.AttachmentOffset = support, mode, offset
    if mode == "Deactivated":
        derived.Placement = place
    derived.recompute()
    return True


def _shift(derived, parent):
    """How far the derived sketch's copy sits from the parent's geometry (in the sketch's own plane)."""
    for i in range(min(len(derived.Geometry), len(parent.Geometry))):
        try:
            a, b = derived.getPoint(i, 1), parent.getPoint(i, 1)
        except Exception:
            continue
        return a - b
    return App.Vector()


class _Follow:
    """Watches for a parent sketch rebuilt with more or fewer pieces, and remakes its derived sketches."""

    def slotRecomputedObject(self, obj):
        try:
            if obj.TypeId != SKETCH:
                return
            kids = [o for o in obj.InList if is_derived(o) and o.SWDerivedFrom == obj]
        except Exception:
            return
        if not kids:
            return
        from PySide import QtCore
        names = [(k.Document.Name, k.Name) for k in kids]

        def run():
            for doc_name, name in names:
                try:
                    k = App.getDocument(doc_name).getObject(name)
                    if k is not None and follow(k):
                        k.Document.recompute()
                except Exception as error:
                    App.Console.PrintLog("FreeCAD: derived sketch follow: %s\n" % error)
        QtCore.QTimer.singleShot(0, run)


_OBSERVER = []


ORIGIN = (-1, -2)     # the origin point / H axis (-1) and the V axis (-2)


def _float(derived):
    ""

    tied = [i for i, c in enumerate(derived.Constraints)
            if c.First in ORIGIN or getattr(c, "Second", -2000) in ORIGIN or getattr(c, "Third", -2000) in ORIGIN]
    if not tied:
        return 0
    # the copied dimensions follow the parent's through expressions keyed by constraint index:
    # keep each one on its own dimension as the indices close up
    exprs = list(derived.ExpressionEngine)
    for path, _e in exprs:
        try:
            derived.setExpression(path, None)
        except Exception as _fw_err:
            _fw_log("derivedsketch.py:202", _fw_err)
    derived.delConstraints(sorted(tied)) if hasattr(derived, "delConstraints") else \
        [derived.delConstraint(i) for i in sorted(tied, reverse=True)]
    import re
    for path, e in exprs:
        m = re.match(r"^\.?Constraints\[(\d+)\]$", path) or re.match(r"^\.?Constraints\.Constraint(\d+)$", path)
        if m:
            k = int(m.group(1))
            if k in tied:
                continue
            k -= sum(1 for t in tied if t < k)
            path = "Constraints[%d]" % k if "[" in path else ".Constraints.Constraint%d" % k
        try:
            derived.setExpression(path, e)
        except Exception as error:
            App.Console.PrintLog("FreeCAD: derived sketch expression %s: %s\n" % (path, error))
    return len(tied)


def is_derived(obj):
    return obj is not None and obj.TypeId == SKETCH and getattr(obj, "SWDerivedFrom", None) is not None


def underive(sketch):
    ""

    for path, _expr in list(sketch.ExpressionEngine):
        try:
            sketch.setExpression(path, None)
        except Exception as _fw_err:
            _fw_log("derivedsketch.py:232", _fw_err)
    sketch.SWDerivedFrom = None
    for name in ("SWDerivedFrom", "SWDerivedGeo", "SWDerivedCons"):
        try:
            sketch.removeProperty(name)
        except Exception as _fw_err:
            _fw_log("derivedsketch.py:238", _fw_err)
    if sketch.Label.endswith(" (derived)"):
        sketch.Label = sketch.Label[:-len(" (derived)")]
    sketch.recompute()
    return sketch


class DerivedSketchCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CarbonCopy", "MenuText": "Derived Sketch",
                "ToolTip": "Copies a picked sketch onto a picked plane or face; the copy follows the "
                           "original's dimensions"}

    def IsActive(self):
        try:
            sketch, support = _picks()
        except Exception:
            return False
        return sketch is not None and support is not None

    def Activated(self):
        sketch, support = _picks()
        if sketch is None or support is None:
            return
        doc = sketch.Document
        doc.openTransaction("Derived Sketch")
        try:
            derived = derive(sketch, support)
        except Exception as error:
            doc.abortTransaction()
            App.Console.PrintWarning("FreeCAD: Derived Sketch: %s\n" % error)
            Gui.getMainWindow().statusBar().showMessage("Derived Sketch: %s" % error, 8000)
            return
        doc.commitTransaction()
        Gui.Selection.clearSelection()
        try:
            Gui.ActiveDocument.setEdit(derived.Name)
        except Exception:
            Gui.Selection.addSelection(derived)
        Gui.getMainWindow().statusBar().showMessage(
            "%s made; it follows %s's dimensions." % (derived.Label, sketch.Label), 8000)


class UnderiveCommand:
    def GetResources(self):
        return {"Pixmap": "Sketcher_CarbonCopy", "MenuText": "Underive",
                "ToolTip": "The derived sketch stops following its parent and becomes a sketch of its own"}

    def _picked(self):
        for entry in Gui.Selection.getSelectionEx():
            if is_derived(entry.Object):
                return entry.Object
        from . import contextbar
        edit = contextbar.sketch_in_edit()
        return edit if is_derived(edit) else None

    def IsActive(self):
        try:
            return self._picked() is not None
        except Exception:
            return False

    def Activated(self):
        sketch = self._picked()
        if sketch is None:
            return
        doc = sketch.Document
        doc.openTransaction("Underive")
        try:
            underive(sketch)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
        Gui.getMainWindow().statusBar().showMessage("%s no longer follows its parent." % sketch.Label, 8000)


UNDERIVE = "SWStyle_UnderiveSketch"


COMMAND = "SWStyle_DerivedSketch"


def register():
    if not _OBSERVER:
        _OBSERVER.append(_Follow())
        App.addDocumentObserver(_OBSERVER[0])
    try:
        if COMMAND not in Gui.listCommands():
            Gui.addCommand(COMMAND, DerivedSketchCommand())
        if UNDERIVE not in Gui.listCommands():
            Gui.addCommand(UNDERIVE, UnderiveCommand())
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: %s not added: %s\n" % (COMMAND, error))
