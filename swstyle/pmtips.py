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

from PySide import QtCore, QtGui, QtWidgets

TIPS = {
    "reverse direction": "Flips the feature to the other side.",
    "blind": "Goes the distance you type.",
    "through all": "Goes through the whole model.",
    "through all - both": "Goes through the whole model in both directions.",
    "up to next": "Stops at the next face it meets.",
    "up to vertex": "Stops at the plane through the vertex you pick.",
    "up to surface": "Stops at the face or surface you pick.",
    "offset from surface": "Stops a set distance from the face you pick.",
    "up to body": "Stops at the body you pick.",
    "mid plane": "Goes the same distance both ways from the sketch plane.",
    "direction 1": "Sets how far and how the feature goes in the first direction.",
    "direction 2": "Adds a second direction on the other side.",
    "depth": "How far the feature goes.",
    "distance": "The distance to use.",
    "angle": "The angle to use.",
    "radius": "The size of the round.",
    "diameter": "The size across the circle.",
    "thickness": "How thick the wall is.",
    "draft on/off": "Tapers the side faces by the draft angle.",
    "draft outward": "Tapers the faces outward instead of inward.",
    "thin feature": "Makes a wall of even thickness instead of a solid.",
    "merge result": "Joins the new feature with the bodies it touches.",
    "feature scope": "Chooses which bodies the feature changes.",
    "all bodies": "The feature changes every body it reaches.",
    "selected bodies": "The feature changes only the bodies you pick.",
    "auto-select": "Picks the bodies the feature reaches for you.",
    "selected contours": "Uses only the sketch regions you pick.",
    "flip side to cut": "Removes the material on the other side.",
    "tangent propagation": "Carries the selection on along tangent edges.",
    "full preview": "Shows the whole result while you edit.",
    "partial preview": "Shows the result on one edge only.",
    "no preview": "Shows no result until you click OK.",
    "multiple radius fillet": "Gives each picked edge its own radius.",
    "constant size fillet": "Rounds the edges with one size all along.",
    "variable size fillet": "Changes the size along the edge.",
    "face fillet": "Rounds between two sets of faces.",
    "full round fillet": "Rounds across three faces so the middle one goes.",
    "symmetric": "Uses the same value on both sides.",
    "asymmetric": "Uses a different value on each side.",
    "angle distance": "Sets the chamfer by one length and an angle.",
    "distance distance": "Sets the chamfer by two lengths.",
    "vertex": "Sets the chamfer by three lengths at a corner.",
    "equal distance": "Uses the same length on both faces.",
    "shell outward": "Adds the wall outside the body instead of inside.",
    "show preview": "Shows the result while you edit.",
    "faces to remove": "The faces that open the shell.",
    "number of instances": "How many copies the pattern makes.",
    "instances": "How many copies the pattern makes.",
    "spacing": "The gap between copies.",
    "equal spacing": "Spreads the copies evenly over the whole angle or length.",
    "instances to skip": "Copies you leave out of the pattern.",
    "geometry pattern": "Copies only the faces, not the whole feature.",
    "propagate visual properties": "Gives the copies the colors and textures of the original.",
    "mirror face/plane": "The face or plane to mirror about.",
    "features to mirror": "The features to copy across the plane.",
    "bodies to mirror": "The bodies to copy across the plane.",
    "keep visible": "Keeps this box open for the next one.",
    "for construction": "Makes the entity construction geometry.",
    "infinite length": "Makes the line go on without end.",
    "midpoint line": "Starts the line at its middle.",
    "add dimensions": "Adds dimensions to the entity as you sketch it.",
    "add relations": "Adds relations to the picked entities.",
    "existing relations": "Lists the relations the entity already has.",
    "parameters": "The sizes and positions of the entity.",
    "options": "Settings for this feature.",
    "selections": "The items this feature uses.",
    "message": "Tells you what to pick next.",
    "sketch plane": "Where the sketch starts.",
    "from": "Where the feature starts.",
    "profile": "The sketch that shapes the feature.",
    "path": "The curve the profile follows.",
    "guide curves": "Curves that steer the shape along the way.",
    "start/end constraints": "Controls how the shape starts and ends.",
    "axis of revolution": "The line the sketch turns about.",
    "revolve type": "How far the sketch turns.",
    "keep normal constant": "Keeps the profile at the same angle all along.",
    "merge tangent faces": "Joins faces that meet smoothly into one.",
    "close loft": "Joins the last profile back to the first.",
    "offset": "The distance from the item you picked.",
    "flip offset": "Puts the offset on the other side.",
    "first reference": "The first item that places the plane.",
    "second reference": "The second item that places the plane.",
    "third reference": "The third item that places the plane.",
    "coincident": "Places it on the reference.",
    "parallel": "Keeps it parallel to the reference.",
    "perpendicular": "Keeps it at a right angle to the reference.",
    "tangent": "Makes it touch the reference smoothly.",
    "mid plane ": "Places it halfway between two references.",
    "units": "The units the value is in.",
    "standard": "The standard the hole or part follows.",
    "type": "The kind of item to make.",
    "size": "The size to use.",
    "fit": "How tight the fit is.",
    "end condition": "How far the feature goes.",
    "favorite": "Saves these settings to use again.",
}


def _clean(text):
    return " ".join(text.replace("&", "").replace(":", "").split()).lower()


def _in_pm(w):
    while w is not None:
        if w.metaObject().className() in ("Gui::TaskView::TaskView", "Gui::TaskView::TaskBox"):
            return True
        w = w.parentWidget()
    return False


def _label_of(w):
    if isinstance(w, QtWidgets.QAbstractButton) and w.text().strip():
        return w.text()
    if isinstance(w, QtWidgets.QGroupBox) and w.title().strip():
        return w.title()
    parent = w.parentWidget()
    if parent is not None:
        for lab in parent.findChildren(QtWidgets.QLabel):
            if lab.buddy() is w and lab.text().strip():
                return lab.text()
        lay = parent.layout()
        if isinstance(lay, QtWidgets.QFormLayout):
            lab = lay.labelForField(w)
            if lab is not None and isinstance(lab, QtWidgets.QLabel):
                return lab.text()
        if lay is not None:
            i = lay.indexOf(w)
            if i > 0:
                prev = lay.itemAt(i - 1).widget()
                if isinstance(prev, QtWidgets.QLabel) and prev.text().strip():
                    return prev.text()
    g = w.parentWidget()
    while g is not None and not isinstance(g, QtWidgets.QGroupBox):
        g = g.parentWidget()
    return g.title() if g is not None else ""


def tip_for(w):
    if w.toolTip():
        return None
    label = _label_of(w)
    key = _clean(label)
    if not key:
        return None
    desc = TIPS.get(key)
    if desc is None and isinstance(w, QtWidgets.QComboBox):
        desc = TIPS.get(_clean(w.currentText()))
    if desc is None:
        return None
    return "<b>%s</b><br>%s" % (label.replace("&", "").rstrip(":").strip(), desc)


def _handler(obj, event):
    if event.type() != QtCore.QEvent.ToolTip or not isinstance(obj, QtWidgets.QWidget):
        return False
    try:
        if not _in_pm(obj):
            return False
        tip = tip_for(obj)
        if tip is None:
            return False
        QtWidgets.QToolTip.showText(event.globalPos(), tip, obj)
        return True
    except RuntimeError:
        return False


def fill_workbench_tips():
    """Add-in tabs added after the catalog loaded (addintabs) get a tip too."""
    try:
        from . import catalog
        for c in catalog._ALL:
            if not c.tip and c.key.startswith("WB_"):
                c.tip = "Switches to the %s tools." % c.label
    except Exception as _fw_err:
        _fw_log("pmtips.py:196", _fw_err)


def install():
    fill_workbench_tips()
    QtCore.QTimer.singleShot(4000, fill_workbench_tips)
    try:
        from . import events
        events.register("pmtips", (QtCore.QEvent.ToolTip,), _handler)
    except Exception as _fw_err:
        _fw_log("pmtips.py:206", _fw_err)
