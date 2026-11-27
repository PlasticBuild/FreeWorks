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


_FIXING = []


def follow_profile(feature):
    """The axis names a construction line of the sketch (Axis0) while the profile is already its Selected
    Contours object (an open sketch closed by the prompt): FreeCAD then looks for Axis0 on the profile
    and refuses with "Invalid shape name Axis0". The axis follows the profile (contours._axis_to)."""
    if _FIXING:
        return
    try:
        profile = getattr(feature, "Profile", None)
        profile = profile[0] if isinstance(profile, tuple) else profile
        axis = feature.ReferenceAxis
        if profile is None or not axis or not axis[0] or axis[0] is profile:
            return
        from . import contours
        if not contours.is_helper(profile) or axis[0] is not getattr(profile, "Sketch", None):
            return
        _FIXING.append(1)
        try:
            contours._axis_to(feature, axis[0], profile)
        finally:
            _FIXING.pop()
    except Exception as _fw_err:
        _fw_log("revolveaxis.py:follow_profile", _fw_err)


_FRESH = {}
_MUTED = []


def _quiet_first_compute(feature):
    ""



    import time
    try:
        if _MUTED or time.time() - _FRESH.get(feature.Document.Name + "." + feature.Name, 0) > 5.0:
            return
        sketch = getattr(feature, "Profile", None)
        sketch = sketch[0] if isinstance(sketch, tuple) else sketch
        axis = feature.ReferenceAxis
        if sketch is None or sketch.TypeId != "Sketcher::SketchObject" or centerlines(sketch):
            return
        if not axis or axis[0] is not sketch or not axis[1] or axis[1][0] not in ("V_Axis", "H_Axis"):
            return
        names = ("Console", "ReportOutput", "NotificationAreaObserver", "StatusBar")
        was = [(n, App.Console.GetStatus(n, "Err")) for n in names]
        for n, _on in was:
            if _on:
                App.Console.SetStatus(n, "Err", False)
        _MUTED.append(was)

        def restore():
            for n, on in was:
                App.Console.SetStatus(n, "Err", bool(on))
            _MUTED[:] = []
        QtCore.QTimer.singleShot(0, restore)
    except Exception as _fw_err:
        _fw_log("revolveaxis.py:quiet_first_compute", _fw_err)


class _Observer:
    def slotChangedObject(self, obj, prop):
        if prop in ("ReferenceAxis", "Profile") and getattr(obj, "TypeId", "") in TYPES:
            follow_profile(obj)
            if prop == "ReferenceAxis":
                _quiet_first_compute(obj)

    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId in TYPES and not obj.Document.Restoring:
                import time
                _FRESH[obj.Document.Name + "." + obj.Name] = time.time()
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
