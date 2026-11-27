# SPDX-License-Identifier: LGPL-2.1-or-later
""










from . import editobj

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

CUTS = {"PartDesign::Pocket", "PartDesign::Groove", "PartDesign::SubtractivePipe", "PartDesign::SubtractiveLoft",
        "PartDesign::SubtractiveHelix", "PartDesign::Hole", "PartDesign::SubtractiveBox",
        "PartDesign::SubtractiveCylinder", "PartDesign::SubtractiveSphere", "PartDesign::SubtractiveCone",
        "PartDesign::SubtractiveEllipsoid", "PartDesign::SubtractiveTorus", "PartDesign::SubtractivePrism",
        "PartDesign::SubtractiveWedge"}
BOSSES = {"PartDesign::Pad", "PartDesign::Revolution", "PartDesign::AdditivePipe", "PartDesign::AdditiveLoft",
          "PartDesign::AdditiveHelix", "PartDesign::AdditiveBox", "PartDesign::AdditiveCylinder",
          "PartDesign::AdditiveSphere", "PartDesign::AdditiveCone", "PartDesign::AdditiveEllipsoid",
          "PartDesign::AdditiveTorus", "PartDesign::AdditivePrism", "PartDesign::AdditiveWedge",
          "PartDesign::LinearPattern", "PartDesign::PolarPattern", "PartDesign::Mirrored", "PartDesign::MultiTransform"}
CUT_TRANSPARENCY = 0.55          # the cut volume: the part shows through it


def _alive(w):
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _edited():
    try:
        edit = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return editobj.of(edit) if edit is not None else None
    except Exception:
        return None


def kind_of(feature):
    """"cut", "boss" or None for the feature under edit."""
    if feature is None:
        return None
    t = feature.TypeId
    if t in CUTS:
        return "cut"
    if t in BOSSES:
        return "boss"
    if t == "PartDesign::FeaturePython" or t.endswith("FeaturePython"):
        kind = (getattr(feature, "SWStyleKind", "") or "")
        return "cut" if "Cut" in kind else ("boss" if kind else None)
    return None


def removed(feature):
    """The material a cut takes away: its base less its result."""
    base = getattr(feature, "BaseFeature", None)
    if base is None or base.Shape.isNull() or feature.Shape.isNull():
        return []
    try:
        # the cut's own tool against the base (the same material, 10-40x faster than base less result:
        # 0.11 s against 4.6 s on the Alloy Wheel)
        tool = getattr(feature, "AddSubShape", None)
        if tool is not None and not tool.isNull() and tool.Solids:
            gone = tool.common(base.Shape)
            if gone.Solids:
                return [f for f in gone.Faces if f.Area > 1e-6]
        gone = base.Shape.cut(feature.Shape)
        return [f for f in gone.Faces if f.Area > 1e-6]
    except Exception:
        return []


def added(feature):
    """The faces a boss adds (the faces of the base it only trims stay as they are)."""
    from . import filletpm
    base = getattr(feature, "BaseFeature", None)
    try:
        if base is None or base.Shape.isNull():
            return list(feature.Shape.Faces)
        return filletpm.new_faces(base.Shape, feature.Shape)
    except Exception:
        return []


def _eye_on(view):
    for box in view.findChildren(QtWidgets.QWidget, "SWStyle_DetailedPreview"):
        try:
            if box.on:
                return True
        except RuntimeError as _fw_err:
            _fw_log("pmpreview.py:110", _fw_err)
    return False


class Preview(QtCore.QObject):
    """One task view's live preview, polled."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.overlay = None
        self.key = None
        self.kind = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        view.destroyed.connect(self.stop)

    def poll(self):
        if not _alive(self.view) or not self.view.isVisible():
            self.clear()
            return
        feature = _edited()
        kind = kind_of(feature)
        if kind is None or _eye_on(self.view):
            self.clear()
            return
        try:
            shape = feature.Shape
            key = (feature.Name, kind, shape.hashCode(), len(shape.Faces),     # not Volume: a mass sum every 250 ms
                   id(Gui.ActiveDocument.ActiveView))
        except Exception:
            self.clear()
            return
        if key == self.key:
            return
        self.clear()
        self.key = key
        faces = removed(feature) if kind == "cut" else added(feature)
        if not faces:
            return
        try:
            from . import filletpm
            self.overlay = filletpm.Overlay()
            self.overlay.show_preview(faces, sections=False)    # an extrude's preview: no fillet cross-curves
            if kind == "cut":
                self._see_through()
            self._colour(kind)
            self.kind = kind
        except Exception as error:
            App.Console.PrintLog("FreeCAD: preview: %s\n" % error)
            self.overlay = None

    def _colour(self, kind):
        ""

        try:
            from . import optionspages
            rgb = optionspages.kept_color("Add Material" if kind == "boss" else "Remove Material")
            rgb = rgb or optionspages.kept_color("Temporary Graphics Shaded")
        except Exception:
            rgb = None
        if rgb is None:
            return None
        from pivy import coin
        sep = self.overlay.preview
        for i in range(sep.getNumChildren()):
            node = sep.getChild(i)
            if isinstance(node, coin.SoMaterial):
                node.diffuseColor.setValue(*rgb)
            elif isinstance(node, coin.SoBaseColor):
                node.rgb.setValue(*rgb)
        return rgb

    def _see_through(self):
        """The cut volume lets the part show through, and sits in place (no draw-over)."""
        from pivy import coin
        sep = self.overlay.preview
        for i in range(sep.getNumChildren()):
            node = sep.getChild(i)
            if isinstance(node, coin.SoMaterial):
                node.transparency = CUT_TRANSPARENCY
            elif isinstance(node, coin.SoDepthBuffer):
                node.test = True

    def faces(self):
        """How many faces are drawn (for checks)."""
        if self.overlay is None:
            return 0
        from pivy import coin
        n = 0
        sep = self.overlay.preview
        for i in range(sep.getNumChildren()):
            if isinstance(sep.getChild(i), coin.SoIndexedFaceSet):
                n += 1
        return n

    def clear(self):
        if self.overlay is not None:
            try:
                self.overlay.remove()
            except Exception as _fw_err:
                _fw_log("pmpreview.py:190", _fw_err)
        self.overlay = None
        self.key = None
        self.kind = None

    def stop(self, *args):
        try:
            self.timer.stop()
        except Exception as _fw_err:
            _fw_log("pmpreview.py:199", _fw_err)
        self.clear()


_previews = {}


def install(view):
    if id(view) in _previews and _alive(_previews[id(view)].view):
        return
    _previews[id(view)] = Preview(view)


def active():
    """The live preview drawn right now, or None (for checks)."""
    for p in _previews.values():
        if p.overlay is not None:
            return p
    return None
