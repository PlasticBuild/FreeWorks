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
from PySide import QtCore, QtWidgets

TYPES = ("PartDesign::Revolution", "PartDesign::Groove")
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreeWorks"


def centerlines(sketch):
    """Indexes (among construction lines, FreeCAD's Axis / Axis<n>) of the sketch's centerlines."""
    out, n = [], 0
    for i, g in enumerate(sketch.Geometry):
        if type(g).__name__ == "LineSegment" and sketch.getConstruction(i):
            out.append(n)
            n += 1
    return out


def _axis_combo():
    for cb in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "axis"):
        if cb.isVisible():
            return cb
    return None


def use_centerline(feature, tries=0):
    """Puts the panel's axis on the sketch's one centerline; retries until the panel shows."""
    try:
        if feature.Document is None or feature.TypeId not in TYPES:
            return
    except Exception:
        return
    sketch = getattr(feature, "Profile", None)
    sketch = sketch[0] if isinstance(sketch, tuple) else sketch
    if sketch is None or sketch.TypeId != "Sketcher::SketchObject":
        if sketch is None and tries < 20:
            QtCore.QTimer.singleShot(100, lambda: use_centerline(feature, tries + 1))
        return
    lines = centerlines(sketch)
    if len(lines) != 1:
        return
    axis = feature.ReferenceAxis
    if axis and axis[0] is sketch and axis[1] and axis[1][0].startswith("Axis"):
        return      # already on a centerline
    combo = _axis_combo()
    if combo is None:
        if tries < 20:
            QtCore.QTimer.singleShot(100, lambda: use_centerline(feature, tries + 1))
        return
    # the list is: vertical, horizontal, the construction lines, the base axes, select reference
    if combo.count() > 2:
        combo.setCurrentIndex(2)        # what the panel applies on OK (a set index does not apply it now)
    feature.ReferenceAxis = (sketch, ["Axis0"])
    feature.Document.recompute()


class _Observer:
    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in TYPES and not obj.Document.Restoring and \
                    App.ParamGet(PARAMS).GetBool("RevolveAboutCenterline", True):
                QtCore.QTimer.singleShot(0, lambda: use_centerline(obj))
        except Exception as _fw_err:
            _fw_log("revolveaxis.py:90", _fw_err)


_observer = None


def register():
    global _observer
    if _observer is None:
        _observer = _Observer()
        App.addDocumentObserver(_observer)
