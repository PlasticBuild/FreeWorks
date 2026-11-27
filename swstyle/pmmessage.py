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
from PySide import QtCore, QtWidgets

INFO, WARN = "info", "warn"
BANNER = "SWStyle_Banner"

TIPS = {
    # Extrude / Cut / Revolve / Revolved Cut
    "SWStyle_EndCondition": "End condition: how far the feature goes",
    "SWStyle_Direction2": "Direction 2: go the other way as well, with its own end condition and depth",
    "SWStyle_DraftAngle1": "Draft angle: the sides lean by this angle along the feature",
    "SWStyle_DraftOutward1": "Draft outward: the sides open out instead of closing in",
    "SWStyle_DraftAngle2": "Draft angle of Direction 2",
    "SWStyle_DraftOutward2": "Draft outward in Direction 2",
    "SWStyle_FromMode": "From: where the feature starts (the sketch plane, a face, a vertex or an offset from the plane)",
    "SWStyle_ThinFeatureOn": "Thin Feature: a wall of set thickness along the sketch instead of a filled shape",
    "SWStyle_FlipSideToCut": "Flip side to cut: remove the material outside the sketch instead of inside it",
    "SWStyle_MergeResult": "Merge result: join the feature to the part (off: a separate body)",
    # Sweep / Loft
    "SWStyle_SweepStartTangency": "Start tangency: how the sweep leaves the first profile",
    "SWStyle_SweepEndTangency": "End tangency: how the sweep meets the end of the path",
    "SWStyle_SweepThin": "Thin Feature: sweep a wall of set thickness along the profile",
    "SWStyle_LoftThin": "Thin Feature: loft a wall of set thickness along the profiles",
    # Hole Wizard (the hole page's own fields)
    "ThreadType": "Thread: the standard the hole is tapped for, or none for a plain hole",
    "BaseProfileType": "Hole type: plain, counterbored or countersunk",
    "DepthType": "End condition of the hole: blind to a depth or through all",
    "DrillPointAngled": "Drill angle: the hole ends in a drill-point cone",
    "Tapered": "Tapered: the hole narrows at the pipe-thread taper",
    "showFinalCheckBox": "Show the finished hole in the part",
    "showTransparentPreviewCheckBox": "Show the hole see-through over the part while editing",
    # Linear / Circular Pattern
    "SWPatternDirection1": "Direction 1: click an edge, an axis, a plane or a dimension that sets the direction",
    "SWPatternDirection2": "Direction 2: click an edge, an axis, a plane or a dimension that sets the second direction",
    "SWPatternSpacingAndInstances1": "Spacing and instances: set the gap between instances and how many",
    "SWPatternSpacingAndInstances2": "Spacing and instances: set the gap between instances and how many",
    "SWPatternUpToReference1": "Up to reference: the instances stop at a picked edge, face or vertex",
    "SWPatternUpToReference2": "Up to reference: the instances stop at a picked edge, face or vertex",
    "SWPatternUpTo1": "Reference: click where the pattern stops",
    "SWPatternUpTo2": "Reference: click where the pattern stops",
    "SWPatternInstanceSpacing1": "Instance spacing: the angle between neighboring instances",
    "SWPatternInstanceSpacing2": "Instance spacing: the angle between neighboring instances",
    "SWPatternEqualSpacing1": "Equal spacing: the instances share the angle evenly",
    "SWPatternEqualSpacing2": "Equal spacing: the instances share the angle evenly",
    "SWPatternSpacing1": "Spacing: the distance (or angle) from one instance to the next",
    "SWPatternSpacing2": "Spacing: the distance (or angle) from one instance to the next",
    "SWPatternInstances1": "Number of instances, the original included",
    "SWPatternInstances2": "Number of instances, the original included",
    "SWPatternReverse1": "Reverse direction",
    "SWPatternReverse2": "Reverse direction",
    "SWPatternSymmetric": "Symmetric: the same instances the other way too",
    "SWPatternSeedOnly": "Pattern seed only: Direction 2 repeats the original, not the whole row",
    "SWPatternDir2On": "Use Direction 2: pattern along a second direction too",
    "SWPatternFeatures": "Features to pattern: click features in the tree or on the part",
    "SWPatternFaces": "Faces to pattern: click the faces that make up a feature",
    "SWPatternBodies": "Bodies to pattern: click a body",
    "SWPatternSkip": "Instances to skip: click the instances to leave out",
    "SWPatternInstancesToVary": "Instances to vary: the spacing or the size changes from one instance to the next",
    "SWPatternVarySketch": "Vary sketch: each instance follows the sketch of its own (needs a driving dimension)",
    "SWPatternGeometryPattern": "Geometry pattern: copy the shape as it is (off: Up To end conditions are worked out again)",
    "SWPatternPropagate": "Propagate visual properties: the copies take the color of the original",
    # Mirror
    "SWMirrorPlane": "Mirror face/plane: click the face or plane to mirror about",
    "SWMirrorPlane2": "Secondary mirror face/plane: a second face or plane the copies are mirrored about as well",
    "SWMirrorFeatures": "Features to mirror: click features in the tree or on the part",
    "SWMirrorFaces": "Faces to mirror: click the faces of a boss or a pocket",
    "SWMirrorBodies": "Bodies to mirror: click a body",
    # Fillet / Chamfer (their pages belong to the dress-up module; the tips are set here only)
    "SWFilletItems": "Items to fillet: click edges, faces, features or loops",
    "SWFilletSelectionToolbar": "Show the selection toolbar by the pointer when a face is picked",
    "SWFilletTangent": "Tangent propagation: the fillet runs on along the tangent edges",
    "SWFilletFullpreview": "Full preview: show every fillet while editing",
    "SWFilletPartialpreview": "Partial preview: show the first fillet only",
    "SWFilletNopreview": "No preview",
    "SWFilletSymmetric": "Symmetric or asymmetric: one radius, or a distance on each face",
    "SWFilletRadius": "Fillet radius",
    "SWFilletMultiRadius": "Multi radius: a radius of its own per edge",
    "SWFilletProfile": "Profile: the cross section of the fillet (circular, conic or curvature continuous)",
    "SWFilletSetUnassigned": "Give the radius to every edge that has none yet",
    "SWFilletSetAll": "Give the radius to every edge",
    "SWFilletKeepFeatures": "Keep features: features in the way of the fillet stay",
    "SWFilletRoundCorners": "Round corners: a smooth blend where three fillets meet",
    "SWFilletOverflow0": "Overflow: the fillet decides where it runs over an edge",
    "SWFilletOverflow1": "Keep edge: the edge stays, the fillet surface gives way",
    "SWFilletOverflow2": "Keep surface: the surface stays, the edge is trimmed",
    "SWChamferItems": "Items to chamfer: click edges, faces or a vertex",
    "SWChamferSelectionToolbar": "Show the selection toolbar by the pointer when a face is picked",
    "SWChamferTangent": "Tangent propagation: the chamfer runs on along the tangent edges",
    "SWChamferFullpreview": "Full preview: show every chamfer while editing",
    "SWChamferPartialpreview": "Partial preview: show the first chamfer only",
    "SWChamferNopreview": "No preview",
    "SWChamferFlip": "Flip direction: swap the sides the distance and the angle are measured on",
    "SWChamferDistance": "Chamfer distance",
    "SWChamferAngle": "Chamfer angle",
    # Shell / Draft
    "SWShellThickness": "Wall thickness",
    "SWShellFaces": "Faces to remove: click the faces that open the part up",
    "SWShellOutward": "Shell outward: the walls grow outside the part",
    "SWShellShowPreview": "Show preview",
    "SWDraftType0": "Neutral plane: the draft is measured from a face or plane",
    "SWDraftType1": "Parting line: the draft starts at a line on the part",
    "SWDraftType2": "Step draft: the draft steps along a parting line",
    "SWDraftAngle": "Draft angle",
    "SWDraftNeutralPlane": "Neutral plane: click the face or plane the angle is measured from",
    "SWDraftFaces": "Faces to draft: click the faces that lean",
    "SWDraftFacePropagation": "Face propagation: draft the tangent faces, or the inner, outer or all faces too",
    "SWDraftShowPreview": "Show preview",
}

TEXT_TIPS = {
    "Sketch Profile": "Sweep the sketch along the path",
    "Circular Profile": "Sweep a circle of the set diameter along the path",
    "Direction 1": "Direction 1",
    "Direction 2": "Direction 2",
}

_WORDY = (QtWidgets.QAbstractButton, QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox,
          QtWidgets.QLineEdit, QtWidgets.QAbstractItemView, QtWidgets.QSlider)


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError as _fw_err:
        _fw_log("pmmessage.py:152", _fw_err)
        return False


def _repolish(w):
    try:
        w.style().unpolish(w)
        w.style().polish(w)
        w.update()
    except RuntimeError as _fw_err:
        _fw_log("pmmessage.py:160", _fw_err)


# ------------------------------------------------------------------------------ tooltips
def tips(view):
    for w in view.findChildren(QtWidgets.QWidget):
        if not isinstance(w, _WORDY):
            continue
        try:
            if isinstance(w, QtWidgets.QToolButton) and w.property("class") == "header":

                # page kept FreeCAD's old title as its tip (Extrude's From bar said "Direction 1")
                if w.toolTip() and w.toolTip().replace("&", "") != w.text().replace("&", ""):
                    w.setToolTip("")
                continue
            if w.toolTip().strip():
                continue
            tip = TIPS.get(w.objectName())
            if tip is None and isinstance(w, QtWidgets.QAbstractButton):
                tip = TEXT_TIPS.get(w.text().replace("&", ""))
            if tip:
                w.setToolTip(tip)
        except RuntimeError:
            continue


# ------------------------------------------------------------------------------ message boxes
def _group_title(group):
    for label in group.findChildren(QtWidgets.QToolButton):
        if label.property("class") == "header":
            return label.text().replace("&", "")
    return ""


_TEXT = {"info": "#000000", "warn": "#a00000"}


def _mark(w, kind):
    if w.property("swMessage") != kind:
        w.setProperty("swMessage", kind)
        w.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        _repolish(w)
    # the labels inside: the dark theme's pale label text stayed on the light box (the PM sheet's
    # descendant rule loses to the theme), so each label gets the box's text colour itself
    colour = _TEXT.get(kind)
    if colour is None:
        return
    for label in w.findChildren(QtWidgets.QLabel):
        try:
            sheet = label.styleSheet()
            if sheet and label.property("swMessageText") is None:
                continue                    # a label with its own colour (an error line) keeps it
            want = "color: %s; background: transparent;" % colour
            if sheet != want:
                label.setStyleSheet(want)
                label.setProperty("swMessageText", True)
        except RuntimeError as _fw_err:
            _fw_log("pmmessage.py:213", _fw_err)
            continue


def _flush_left(frame):
    ""

    lays = [frame.layout()] + [c.layout() for c in frame.children() if isinstance(c, QtWidgets.QWidget)]
    for lay in lays:
        if lay is None or lay.property("swFlush"):
            continue
        m = lay.contentsMargins()
        lay.setContentsMargins(0, m.top(), m.right(), m.bottom())
        lay.setProperty("swFlush", True)


_RED = ("c00000", "a00000", "#ff0000", "color: red")


def _state(box):
    ""


    for label in box.findChildren(QtWidgets.QLabel):
        try:
            if label.property("swMessageText") or not label.isVisibleTo(box) or not label.text().strip():
                continue
            sheet = label.styleSheet().lower()
            if any(r in sheet for r in _RED) or label.property("swstyle_warning"):
                return WARN
        except RuntimeError:
            continue
    return INFO


def messages(view):
    ""
    for group in view.findChildren(QtWidgets.QWidget):
        try:
            if group.inherits("QSint::ActionGroup") and _group_title(group) == "Message":
                for frame in group.findChildren(QtWidgets.QFrame):
                    if frame.property("class") == "content":
                        _mark(frame, _state(frame))
                        _flush_left(frame)
            elif group.objectName() == "SWGroup_Message":
                _mark(group.body, _state(group.body))
        except (RuntimeError, AttributeError):
            continue
    for label in view.findChildren(QtWidgets.QLabel):
        try:
            name = label.objectName()
            if not name.endswith("Message") or name == BANNER:
                continue
            warn = "c00000" in label.styleSheet() or bool(label.property("swstyle_warning"))
            _mark(label, WARN if warn else INFO)
        except RuntimeError:
            continue


# ------------------------------------------------------------------------------ invalid input
_invalid = {}       # view key -> {id(box): (box, text)}


def _is_view(w):
    try:
        return w.metaObject().className() == "Gui::TaskView::TaskView"
    except RuntimeError as _fw_err:
        _fw_log("pmmessage.py:261", _fw_err)
        return False


def _view_of(box):
    w = box
    while w is not None:
        if _is_view(w):
            return w
        w = w.parentWidget()
    return box.window()


def _key(view):
    """The view's identity across wrappers (the header holds its own wrapper)."""
    try:
        import shiboken6
        return shiboken6.getCppPointer(view)[0]
    except Exception:
        return id(view)


def _banner(view, make=True):
    label = view.findChild(QtWidgets.QLabel, BANNER)
    if label is not None or not make:
        return label
    first = None
    for group in view.findChildren(QtWidgets.QWidget):
        if group.inherits("QSint::ActionGroup") and group.isVisible():
            for frame in group.findChildren(QtWidgets.QFrame):
                if frame.property("class") == "content" and frame.layout() is not None:
                    first = frame
                    break
        if first is not None:
            break
    if first is None:               # a page of plain groups (Sweep, Loft): above the first one
        for group in view.findChildren(QtWidgets.QGroupBox):
            if group.isVisible() and group.parentWidget() is not None and group.parentWidget().layout() is not None:
                first = group.parentWidget()
                break
    if first is None:
        return None
    label = QtWidgets.QLabel("", first)
    label.setObjectName(BANNER)
    label.setWordWrap(True)
    _mark(label, WARN)
    first.layout().insertWidget(0, label)
    return label


def _refresh(view):
    bad = [t for (b, t) in _invalid.get(_key(view), {}).values() if _alive(b)]
    label = _banner(view, make=bool(bad))
    if label is None:
        return
    label.setText("\n".join(bad))
    label.setVisible(bool(bad))


def invalid(box, text):
    """The field's text cannot be read: pink field, the banner says why, OK grey."""
    view = _view_of(box)
    _invalid.setdefault(_key(view), {})[id(box)] = (box, text)
    if not box.property("swInvalid"):
        box.setProperty("swInvalid", True)
        _repolish(box)
    _refresh(view)


def valid(box):
    view = _view_of(box)
    entries = _invalid.get(_key(view))
    if entries and entries.pop(id(box), None) is not None:
        _refresh(view)
    if box.property("swInvalid"):
        box.setProperty("swInvalid", False)
        _repolish(box)


def notice(window, text, msecs=4000):
    ""

    view = None
    try:
        for v in window.findChildren(QtWidgets.QWidget):
            if _is_view(v):
                view = v
                break
    except Exception as _fw_err:
        _fw_log("pmmessage.py:350", _fw_err)
        return
    if view is None:
        return
    if blocked(view):
        return
    label = _banner(view, make=True)
    if label is None:
        return
    label.setText(text)
    label.setVisible(True)
    QtCore.QTimer.singleShot(msecs, lambda: _alive(label) and not blocked(view) and label.setVisible(False))


def blocked(view):
    """OK must stay grey: a field on the page cannot be read."""
    entries = _invalid.get(_key(view), {})
    for key, (box, text) in list(entries.items()):
        if not _alive(box) or not box.isVisible():
            entries.pop(key, None)
    return bool(entries)


def blocked_any():
    """Some open page has a field that cannot be read (the confirmation corner's OK)."""
    for key in list(_invalid):
        entries = _invalid[key]
        for k, (box, text) in list(entries.items()):
            if not _alive(box) or not box.isVisible():
                entries.pop(k, None)
        if entries:
            return True
        _invalid.pop(key, None)
    return False


def install(view):
    tips(view)
    messages(view)
    if _key(view) in _invalid:
        _refresh(view)
