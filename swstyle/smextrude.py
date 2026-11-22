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

DONE = "freeworks_smextrude"
LINK = "SWSMLinkToThickness"
NORMAL = "SWSMNormalCutBox"
GROUP = "Sheet Metal"
EPS = 1e-4


def _edited():
    try:
        vp = Gui.ActiveDocument.getInEdit() if Gui.ActiveDocument is not None else None
        return vp.Object if vp is not None else None
    except Exception:
        return None


def body_of(feat):
    return next((p for p in feat.InList if p.TypeId == "PartDesign::Body"), None)


def sheet_root(feat):
    """The Base Flange of the feature's sheet metal part, or None."""
    from . import smflatten
    body = body_of(feat)
    return smflatten.root(body) if body is not None else None


def _expr(root):
    return "%s.Thickness" % root.Name


def linked(feat):
    root = sheet_root(feat)
    return root is not None and any(p == "Length" and e.replace(" ", "") == _expr(root)
                                    for p, e in feat.ExpressionEngine)


def link_thickness(feat, on):
    root = sheet_root(feat)
    if root is None:
        return
    if on:
        feat.Type = "Length"
        feat.setExpression("Length", _expr(root))
    elif linked(feat):
        feat.setExpression("Length", None)
    feat.Document.recompute()


def _props(feat):
    if not hasattr(feat, "SWNormalCut"):
        feat.addProperty("App::PropertyBool", "SWNormalCut", GROUP, "Make the cut's walls square to the sheet")
        feat.addProperty("App::PropertyBool", "SWOptimizeGeometry", GROUP, "Merge the faces the normal cut leaves")
        feat.SWNormalCut = True
        feat.SWOptimizeGeometry = True
    if "SWNormalCutName" not in feat.PropertiesList:
        feat.addProperty("App::PropertyString", "SWNormalCutName", GROUP, "The Normal Cut doing it")
        feat.setEditorMode("SWNormalCutName", 2)


def normal_cut_of(feat):
    """The Normal Cut doing feat's Normal cut option, or None."""
    name = getattr(feat, "SWNormalCutName", "")
    if name:
        return feat.Document.getObject(name)
    return getattr(feat, "SWNormalCutFeature", None)    # parts saved before features-400


def set_normal_cut(feat, nc):
    """Keeps the Normal Cut by name: a link back to it made the cut and the Normal Cut (whose base is
    the cut) depend on each other, so after Unsuppress neither rebuilt."""
    if "SWNormalCutName" not in feat.PropertiesList:
        feat.addProperty("App::PropertyString", "SWNormalCutName", GROUP, "The Normal Cut doing it")
        feat.setEditorMode("SWNormalCutName", 2)
    feat.SWNormalCutName = nc.Name if nc is not None else ""
    if "SWNormalCutFeature" in feat.PropertiesList:
        feat.removeProperty("SWNormalCutFeature")


def cut_faces(feat):
    """Points on the faces the cut made (not on the shape before it)."""
    from . import smnormalcut
    base = feat.BaseFeature
    if base is None or feat.Shape.isNull():
        return []
    before = base.Shape
    pts = []
    for f in feat.Shape.Faces:
        p = smnormalcut.inside_point(f)
        if before.distToShape(Part_vertex(p))[0] > EPS:
            pts.append(p)
    return pts


def Part_vertex(p):
    import Part
    return Part.Vertex(p)


def finish(doc_name, name):
    """After the cut's panel closes: make, update or remove its Normal Cut."""
    try:
        doc = App.getDocument(doc_name)
        feat = doc.getObject(name)
    except Exception:
        return
    if feat is None or not hasattr(feat, "SWNormalCut"):
        return
    from . import smnormalcut
    nc = normal_cut_of(feat)
    if nc is not None and "SWNormalCutFeature" in feat.PropertiesList:
        set_normal_cut(feat, nc)
    if not feat.SWNormalCut:
        if nc is not None:
            set_normal_cut(feat, None)
            body = body_of(feat)
            tip = body is not None and body.Tip is nc
            if body is not None:
                body.removeObject(nc)
            doc.removeObject(nc.Name)
            if tip:
                body.Tip = feat
            feat.ViewObject.Visibility = True
            doc.recompute()
        return
    pts = cut_faces(feat)
    if not pts:
        return
    body = body_of(feat)
    if nc is None:
        if body.Tip is not feat:
            return
        doc.openTransaction("Normal cut")
        try:
            nc = smnormalcut.make(body)
            set_normal_cut(feat, nc)
        except BaseException:
            try:
                doc.abortTransaction()
            except Exception:
                pass
            raise
        doc.commitTransaction()
    nc.FacePoints = pts
    nc.FaceGroups = [0] * len(pts)
    nc.GroupCount = 1
    nc.OptimizeGeometry = feat.SWOptimizeGeometry
    smnormalcut.hide_row(nc)
    doc.recompute()


def _place_after(widget, new):
    if not widget.isVisible():
        # Through All hides the depth row (and anything placed in it): go under the page instead
        lay = widget.parentWidget().layout()
        if isinstance(lay, QtWidgets.QGridLayout):
            lay.addWidget(new, lay.rowCount(), 0, 1, 2)
            return
        if lay is not None:
            lay.addWidget(new)
            return
    try:
        from .extrudepm import _place_after as place
        place(widget, new)
        return
    except Exception as _fw_err:
        _fw_log("smextrude.py:161", _fw_err)
    parent = widget.parentWidget()
    lay = parent.layout()
    if isinstance(lay, QtWidgets.QGridLayout):
        lay.addWidget(new, lay.rowCount(), 0, 1, 2)
    elif lay is not None:
        lay.addWidget(new)


def _later(doc, name):
    return lambda *a: QtCore.QTimer.singleShot(0, lambda: finish(doc, name))


class Rows(QtCore.QObject):
    def __init__(self, view, feat, length):
        super().__init__(view)
        self.doc, self.name = feat.Document.Name, feat.Name
        self.length = length
        self.link = QtWidgets.QCheckBox("Link to thickness", length.parentWidget())
        self.link.setObjectName(LINK)
        self.link.setChecked(linked(feat))
        _place_after(length, self.link)
        self.link.toggled.connect(self._link)
        self._sync()
        self.box = None
        if feat.TypeId == "PartDesign::Pocket":
            _props(feat)
            self.box = QtWidgets.QWidget(length.parentWidget())
            self.box.setObjectName(NORMAL)
            lay = QtWidgets.QVBoxLayout(self.box)
            lay.setContentsMargins(0, 6, 0, 0)
            self.normal = QtWidgets.QCheckBox("Normal cut", self.box)
            self.normal.setObjectName("SWSMNormalCut")
            self.normal.setChecked(feat.SWNormalCut)
            self.optimize = QtWidgets.QCheckBox("Optimize geometry", self.box)
            self.optimize.setObjectName("SWSMOptimizeGeometry")
            self.optimize.setChecked(feat.SWOptimizeGeometry)
            self.optimize.setEnabled(feat.SWNormalCut)
            lay.addWidget(self.normal)
            row = QtWidgets.QHBoxLayout()
            row.addSpacing(18)
            row.addWidget(self.optimize)
            lay.addLayout(row)
            _place_after(self.link, self.box)
            self.normal.toggled.connect(self._normal)
            self.optimize.toggled.connect(self._optimize)
        # the Tasks view outlives each panel: FreeCAD's own depth field goes with the panel
        length.destroyed.connect(_later(self.doc, self.name))

    def feat(self):
        try:
            return App.getDocument(self.doc).getObject(self.name)
        except Exception:
            return None

    def _sync(self):
        try:
            self.length.setEnabled(not self.link.isChecked())
        except RuntimeError as _fw_err:
            _fw_log("smextrude.py:220", _fw_err)

    def _link(self, on):
        f = self.feat()
        if f is not None:
            link_thickness(f, on)
            try:
                self.length.setProperty("rawValue", float(f.Length))
            except Exception as _fw_err:
                _fw_log("smextrude.py:229", _fw_err)
        self._sync()

    def _normal(self, on):
        f = self.feat()
        if f is not None:
            f.SWNormalCut = on
        self.optimize.setEnabled(on)

    def _optimize(self, on):
        f = self.feat()
        if f is not None:
            f.SWOptimizeGeometry = on


def install(view):
    feat = _edited()
    if feat is None or feat.TypeId not in ("PartDesign::Pad", "PartDesign::Pocket") or sheet_root(feat) is None:
        return
    # the open panel's depth field (hidden with Through All: its panel is shown)
    length = next((w for w in view.findChildren(QtWidgets.QAbstractSpinBox, "lengthEdit")
                   if w.parentWidget() is not None and w.parentWidget().isVisible()), None)
    if length is None or length.property(DONE):
        return
    length.setProperty(DONE, True)
    Rows(view, feat, length)


_timer = []


def _poll():
    try:
        feat = _edited()
        if feat is not None and feat.TypeId in ("PartDesign::Pad", "PartDesign::Pocket"):
            install(Gui.getMainWindow())
    except Exception as _fw_err:
        _fw_log("smextrude.py:266", _fw_err)


class _CutGone:
    """Deleting an Extruded Cut takes its Normal Cut (which has no row of its own) with it."""

    def slotDeletedObject(self, obj):
        try:
            nc = normal_cut_of(obj) if hasattr(obj, "SWNormalCut") else None
        except Exception:
            return
        if nc is None:
            return
        doc, name = nc.Document.Name, nc.Name
        QtCore.QTimer.singleShot(0, lambda: _drop(doc, name))

    def slotFinishRestoreDocument(self, doc):
        name = doc.Name
        QtCore.QTimer.singleShot(0, lambda: _opened(name))


def _opened(doc_name):
    """A part opened: its Normal Cuts that do a cut's Normal cut option lose their rows (older parts:
    the cut's link to them becomes a name)."""
    try:
        doc = App.getDocument(doc_name)
    except Exception:
        return
    from . import smnormalcut
    for o in doc.Objects:
        if smnormalcut.is_normal_cut(o):
            smnormalcut._hide_later(doc_name, o.Name)


def _drop(doc_name, name):
    try:
        doc = App.getDocument(doc_name)
        nc = doc.getObject(name)
    except Exception:
        return
    if nc is None:
        return
    from . import smnormalcut
    if smnormalcut.owner(nc) is not None:
        return
    body = body_of(nc)
    tip = body is not None and body.Tip is nc
    base = nc.BaseFeature
    if body is not None:
        body.removeObject(nc)
    doc.removeObject(name)
    if tip and base is not None:
        body.Tip = base
        try:
            base.ViewObject.Visibility = True
        except Exception as _fw_err:
            _fw_log("smextrude._drop", _fw_err)
    doc.recompute()


def register():
    if _timer:
        return
    try:
        _timer.append(_CutGone())
        App.addDocumentObserver(_timer[-1])
    except Exception as _fw_err:
        _fw_log("smextrude.register", _fw_err)
    t = QtCore.QTimer()
    t.setInterval(300)
    t.timeout.connect(_poll)
    t.start()
    _timer.append(t)
