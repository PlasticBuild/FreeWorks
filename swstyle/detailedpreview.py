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

from .widgets import alive

TIP = "Detailed Preview"


def target():
    """(feature, base) of the feature the open PropertyManager makes or edits, else None."""
    try:
        from . import filletpm
        page = filletpm.current()
        if page is not None and not page.closing:
            f = page.feature
            if f is not None and page.base is not None:
                return f, page.base
            return None
    except Exception as _fw_err:
        _fw_log("detailedpreview.py:49", _fw_err)
    try:
        edit = Gui.ActiveDocument.getInEdit()
        obj = editobj.of(edit) if edit is not None else None
    except Exception:
        return None
    if obj is None or not obj.TypeId.startswith("PartDesign::") or obj.TypeId == "PartDesign::Body":
        return None
    base = getattr(obj, "BaseFeature", None)
    return (obj, base) if hasattr(obj, "Shape") else None


def changed_faces(feature, base):
    """The faces of the feature's solid that its base does not have."""
    from . import filletpm
    shape = feature.Shape
    if shape.isNull():
        return []
    if base is None or base.Shape.isNull():
        return list(shape.Faces)
    old = base.Shape
    made = filletpm.new_faces(old, shape)
    # modified: on a face of the base but not that face any more (a boss on it, a hole in it)
    for face in shape.Faces:
        if any(face.isSame(m) for m in made):
            continue
        try:
            same = any(abs(face.Area - g.Area) < 1e-6 and (face.CenterOfMass - g.CenterOfMass).Length < 1e-6
                       for g in old.Faces)
        except Exception:
            same = True
        if not same:
            made.append(face)
    return made


def _body_of(obj):
    try:
        return obj.getParentGeoFeatureGroup()
    except Exception:
        return None


class DetailedPreview(QtWidgets.QWidget):
    """The box the eye button opens, and the drawing it does."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWStyle_DetailedPreview")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        title = QtWidgets.QLabel(TIP, self)
        font = title.font()
        font.setBold(True)
        title.setFont(font)
        lay.addWidget(title)
        self.highlight = QtWidgets.QCheckBox("Highlight new or modified faces", self)
        self.highlight.setObjectName("SWStyle_DetailedHighlight")
        self.highlight.setChecked(True)
        self.only = QtWidgets.QCheckBox("Show only new or modified bodies", self)
        self.only.setObjectName("SWStyle_DetailedShowOnly")
        lay.addWidget(self.highlight)
        lay.addWidget(self.only)
        lay.addStretch(1)       # the options sit under the title while the page is hidden
        self.highlight.toggled.connect(lambda on: self.refresh(force=True))
        self.only.toggled.connect(lambda on: self._bodies())
        self.overlay = None
        self.hidden = []        # (doc name, object name) this preview hid
        self.page = []          # the PropertyManager's own widgets this preview hid
        self.key = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.hide()

    @property
    def on(self):
        return self.isVisibleTo(self.parentWidget()) if self.parentWidget() else False

    def _page(self, on):
        ""
        header = self.parentWidget()
        view = getattr(header, "view", None)
        lay = view.layout() if alive(view) else None
        if not on:
            page, self.page = self.page, []
            for w in page:
                if alive(w):
                    w.show()
            return
        if lay is None:
            return

        def walk(layout):
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget()
                if w is not None:
                    if w is not header and not w.isHidden():
                        w.hide()
                        self.page.append(w)
                elif item.layout() is not None:
                    walk(item.layout())
        walk(lay)

    def start(self):
        self.show()
        self._page(True)
        self.timer.start()
        self.refresh(force=True)
        self._bodies()

    def stop(self):
        self.timer.stop()
        self.hide()
        self._page(False)
        self._clear()
        self._show_bodies()

    def _clear(self):
        if self.overlay is not None:
            try:
                self.overlay.remove()
            except Exception as _fw_err:
                _fw_log("detailedpreview.py:173", _fw_err)
        self.overlay = None
        self.key = None

    def refresh(self, force=False):
        hit = target()
        if hit is None:
            self._clear()
            return
        feature, base = hit
        try:
            shape = feature.Shape
            key = (feature.Name, round(shape.Volume, 6), len(shape.Faces), self.highlight.isChecked())
        except Exception:
            key = None
        if key == self.key and not force:
            return
        self._clear()
        self.key = key
        if not self.highlight.isChecked():
            return
        try:
            from . import filletpm
            self.overlay = filletpm.Overlay()
            self.overlay.show_preview(changed_faces(feature, base))
        except Exception as error:
            App.Console.PrintLog("FreeCAD: Detailed Preview: %s\n" % error)

    def _bodies(self):
        if not self.only.isChecked():
            self._show_bodies()
            return
        hit = target()
        if hit is None:
            return
        feature = hit[0]
        keep = _body_of(feature)
        doc = feature.Document
        for obj in doc.Objects:
            try:
                if obj is keep or obj is feature or _body_of(obj) is not None:
                    continue        # inside a body (or the body itself): its tip shows for it
                if not hasattr(obj, "Shape") or obj.Shape.isNull() or not obj.Shape.Solids:
                    continue
                vo = obj.ViewObject
                if vo is not None and vo.Visibility:
                    vo.Visibility = False
                    self.hidden.append((doc.Name, obj.Name))
            except Exception:
                continue

    def _show_bodies(self):
        hidden, self.hidden = self.hidden, []
        for doc_name, name in hidden:
            try:
                obj = App.getDocument(doc_name).getObject(name)
                if obj is not None:
                    obj.ViewObject.Visibility = True
            except Exception:
                continue


def make_button(header):
    """The eye button for a PropertyManager header (propertymanager.Header)."""
    button = header._tool("PM_DETAILED_PREVIEW", TIP)
    button.setObjectName("SWStyle_DetailedPreviewButton")
    button.setCheckable(True)
    box = DetailedPreview(header)

    def toggled(on):
        if on:
            box.start()
        else:
            box.stop()
    button.toggled.connect(toggled)
    return button, box



# Cut-Extrude, Revolve, Revolved Cut, Sweep, Swept Cut, Loft, Lofted Cut, Boundary, and Draft
# (its Detailed Preview box shows which faces the draft turns). Fillet and Chamfer have Full /
# Partial / No preview, Shell and Dome a Show preview box, the rest nothing.
EYE_TYPES = {"PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Revolution", "PartDesign::Groove",
             "PartDesign::Draft",
             "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
             "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft",
             "PartDesign::AdditiveHelix", "PartDesign::SubtractiveHelix"}
EYE_KINDS = {"BoundaryBoss", "BoundaryCut", "BoundaryBase", "Boundary"}


def feature_page():
    ""
    try:
        from . import filletpm
        page = filletpm.current()
        if page is not None and type(page).__name__ == "DraftPanel":
            return True
    except Exception as _fw_err:
        _fw_log("detailedpreview.py:271", _fw_err)
    try:
        edit = Gui.ActiveDocument.getInEdit()
        obj = editobj.of(edit) if edit is not None else None
        if obj is None:
            return False
        if obj.TypeId in EYE_TYPES:
            return True
        kind = getattr(obj, "SWStyleKind", "") or type(getattr(obj, "Proxy", None)).__name__
        return kind in EYE_KINDS
    except Exception:
        return False


def sync(button, box, open_):
    """Each header sync: the eye shows while a part feature's PropertyManager is open and there is a
    preview to show (hidden until then, never greyed); it pops out when the PropertyManager closes."""
    if not (alive(button) and alive(box)):
        return
    show = bool(open_) and feature_page() and (button.isChecked() or target() is not None)
    if button.isHidden() == show:
        button.setVisible(show)
    if show:
        button.setEnabled(True)
    elif button.isChecked():
        button.setChecked(False)
