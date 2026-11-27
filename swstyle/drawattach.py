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

from . import drawings as D

FREE = ("Note", "GeometricTolerance", "DatumFeature", "DatumTarget", "SurfaceFinish", "WeldSymbol", "Caterpillar",
        "EndTreatment", "RevisionCloud", "RevisionSymbol", "StackedBalloon", "HoleTag", "PunchTag", "BendNote",
        "MultiJogLeader", "DowelPin", "Block", "InspectionFrame", "AreaHatch", "MagneticLine", "Balloon")
ANNOT_TYPES = ("TechDraw::DrawViewDimension", "TechDraw::DrawViewBalloon", "TechDraw::DrawLeaderLine",
               "TechDraw::DrawRichAnno", "TechDraw::DrawViewAnnotation", "TechDraw::DrawWeldSymbol")
FAINT = 0.3


# --------------------------------------------------------------------------- attach
def attachable(o):
    try:
        if o.TypeId != "TechDraw::DrawViewSymbol" or getattr(o, "SWAnnotation", "") not in FREE:
            return False
        return not any(p in ("X", "Y") for p, _e in (o.ExpressionEngine or []))
    except Exception:
        return False


def page_of(o):
    for p in o.InList:
        if p.TypeId == "TechDraw::DrawPage":
            return p
    return None


def attached_to(o):
    """The view o is attached to, None when it is attached to the sheet (or never was)."""
    name = getattr(o, "SWAttachedTo", "") or ""
    return o.Document.getObject(name) if name else None


def attach(o, view):
    """o attached to view (None: the sheet)."""
    if "SWAttachedTo" not in o.PropertiesList:
        o.addProperty("App::PropertyString", "SWAttachedTo", "FreeCAD", "the view the annotation is attached to")
        o.addProperty("App::PropertyVector", "SWAttachAt", "FreeCAD", "where that view was")
        for p in ("SWAttachedTo", "SWAttachAt"):
            o.setPropertyStatus(p, ["Hidden"])
    o.SWAttachedTo = view.Name if view is not None else ""
    o.SWAttachAt = App.Vector(float(view.X), float(view.Y), 0) if view is not None else App.Vector()
    return o


def attach_new(o):
    """A new annotation: attached to the view with focus where it was made, else to the sheet."""
    from . import drawviews as DV
    page = page_of(o)
    if page is None or not attachable(o) or "SWAttachedTo" in o.PropertiesList:
        return None
    view = DV.focus_view(page, (float(o.X), float(o.Y)), margin=0.0)
    tip = getattr(o, "SWTip", None)
    if view is None and tip is not None and tip.z >= 0 and not getattr(page, "FWLockSheetFocus", False):

        # that view and moves with it
        view = DV.view_at(page, (float(tip.x), float(tip.y)), 3.0)     # an edge on the view's outline counts
    attach(o, view)
    return view


def follow(doc):
    """The sheet tick: annotations move with the views they are attached to. Returns the ones moved."""
    moved = []
    for o in doc.Objects:
        name = getattr(o, "SWAttachedTo", "") if o.TypeId == "TechDraw::DrawViewSymbol" else ""
        if not name:
            continue
        v = doc.getObject(name)
        if v is None:
            attach(o, None)                       # the view was deleted: the annotation stays, on the sheet
            continue
        try:
            _same_sheet(o, v)                     # the view went to another sheet: the annotation goes with it
            at = o.SWAttachAt
            dx, dy = float(v.X) - at.x, float(v.Y) - at.y
            if abs(dx) > 1e-6 or abs(dy) > 1e-6:
                o.X, o.Y = float(o.X) + dx, float(o.Y) + dy
                o.SWAttachAt = App.Vector(float(v.X), float(v.Y), 0)
                tip = getattr(o, "SWTip", None)
                if tip is not None and tip.z >= 0:      # its leader point went with it (drawn in its symbol)
                    o.SWTip = App.Vector(tip.x + dx, tip.y + dy, 0)
                moved.append(o)
        except Exception as _fw_err:
            _fw_log("drawattach.py:106", _fw_err)
    moved += follow_scale(doc)
    return moved


def follow_scale(doc):
    ""


    changed = []
    try:
        from . import drawviews as DV
        from . import drawings as D
    except Exception:
        return changed
    for o in doc.Objects:
        if o.TypeId != "TechDraw::DrawViewSymbol" or getattr(o, "SWAnnotation", "") != "AreaHatch":
            continue
        v = doc.getObject(getattr(o, "SWHatchView", "") or "")
        c = getattr(o, "SWHatchCentre", None)
        if v is None or c is None:
            continue
        try:
            k = float(DV.view_scale(v))
            if "SWHatchK" not in o.PropertiesList:
                o.addProperty("App::PropertyFloat", "SWHatchK", "FreeCAD", "the view scale the hatch was fitted to")
                o.setPropertyStatus("SWHatchK", ["Hidden"])
                o.SWHatchK = k
                continue
            k0 = float(o.SWHatchK)
            if k0 <= 0 or abs(k - k0) < 1e-9:
                continue
            if getattr(o, "ScaleType", "Custom") != "Custom":
                o.ScaleType = "Custom"
            o.Scale = float(o.Scale or 1.0) * k / k0
            o.SWHatchK = k
            x0, y0 = D.view_position(v)
            o.X, o.Y = x0 + c.x * k, y0 + c.y * k
            if "SWAttachAt" in o.PropertiesList:
                o.SWAttachAt = App.Vector(float(v.X), float(v.Y), 0)
            changed.append(o)
        except Exception as _fw_err:
            _fw_log("drawattach.py:follow_scale", _fw_err)
    return changed


def _page(o):
    try:
        p = o.findParentPage()
        if p is not None:
            return p
    except Exception as _fw_err:
        _fw_log("drawattach.py:116", _fw_err)
    return next((p for p in o.InList if p.TypeId == "TechDraw::DrawPage"), None)


def _same_sheet(o, v):
    ""

    pv, po = _page(v), _page(o)
    if pv is None or po is None or pv is po:
        return False
    po.removeView(o)
    pv.addView(o)
    return True


def move_to_sheet(views, page):
    """Views onto sheet page, with their dimensions, balloons and attached annotations (as dragging them onto
    the sheet in the tree). Returns the objects moved."""
    moved = []
    doc = page.Document
    for v in views:
        old = _page(v)
        if old is None or old is page:
            continue
        deps = []
        for o in v.InList:          # InList can name a dimension twice (each reference): move it once
            if o not in deps and o.isDerivedFrom("TechDraw::DrawView") and _page(o) is old and \
                    (o.isDerivedFrom("TechDraw::DrawViewDimension") or o.isDerivedFrom("TechDraw::DrawViewBalloon")):
                deps.append(o)
        for o in [v] + deps:
            old.removeView(o)
            page.addView(o)
            moved.append(o)
        for o in doc.Objects:
            if getattr(o, "SWAttachedTo", "") == v.Name and _same_sheet(o, v):
                moved.append(o)
    doc.recompute()
    return moved


def drag_done(page, p, copy):
    """Shift+drag of picked annotations that ended at sheet point p: attached to the view there, else the sheet."""
    if copy:
        return []
    from . import drawviews as DV
    out = []
    target = DV.view_at(page, p, margin=0.0)
    for o in Gui.Selection.getSelection():
        if attachable(o) and attached_to(o) is not target:
            attach(o, target)
            out.append(o)
    return out


# --------------------------------------------------------------------------- Hide/Show Annotations
def annotations(page):
    from . import drawmenus
    return [o for o in drawmenus.annotations_of(page)]


class HideShowMode(QtCore.QObject):
    """View > Hide / Show > Hide/Show Annotations."""

    current = None

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.doc = page.Document
        self.faint = set()
        for o in annotations(page):
            try:
                if not o.ViewObject.Visibility:
                    self.faint.add(o.Name)
                    o.ViewObject.Visibility = True
            except Exception as _fw_err:
                _fw_log("drawattach.py:192", _fw_err)
        self.gv = D.page_view(page)
        self.vp = self.gv.viewport() if self.gv is not None else None
        if self.vp is not None:
            self.vp.installEventFilter(self)
        QtWidgets.QApplication.instance().installEventFilter(self)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.paint)
        self.timer.start(250)
        HideShowMode.current = self
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("drawattach.py:205", _fw_err)
        _status("Hidden annotations are drawn faint. Click an annotation to hide or show it; Esc ends.")
        QtCore.QTimer.singleShot(0, self.paint)

    def items(self):
        out = {}
        if self.gv is None:
            return out
        try:
            for it in self.gv.scene().items():
                try:
                    n = it.data(1)
                except Exception:
                    continue
                if n:
                    out.setdefault(str(n), []).append(it)
        except Exception as _fw_err:
            _fw_log("drawattach.py:222", _fw_err)
        return out

    def paint(self):
        try:
            for n, its in self.items().items():
                o = self.doc.getObject(n)
                if o is None or not (o.TypeId in ANNOT_TYPES or o.TypeId == "TechDraw::DrawViewSymbol"):
                    continue
                want = FAINT if n in self.faint else 1.0
                for it in its:
                    if abs(it.opacity() - want) > 1e-3:
                        it.setOpacity(want)
        except Exception as _fw_err:
            _fw_log("drawattach.py:236", _fw_err)

    def toggle(self, o):
        if o.Name in self.faint:
            self.faint.discard(o.Name)
        else:
            self.faint.add(o.Name)
        self.paint()
        return o.Name in self.faint

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
                QtCore.QTimer.singleShot(0, self.finish)
                return True
            if obj is self.vp and t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                QtCore.QTimer.singleShot(0, self.after_click)
        except Exception as _fw_err:
            _fw_log("drawattach.py:255", _fw_err)
        return False

    def after_click(self):
        names = {o.Name for o in annotations(self.page)}
        for o in Gui.Selection.getSelection():
            if o.Name in names:
                self.toggle(o)
                break
        try:
            Gui.Selection.clearSelection()
        except Exception as _fw_err:
            _fw_log("drawattach.py:267", _fw_err)

    def finish(self):
        if HideShowMode.current is not self:
            return
        HideShowMode.current = None
        self.timer.stop()
        try:
            if self.vp is not None:
                self.vp.removeEventFilter(self)
            QtWidgets.QApplication.instance().removeEventFilter(self)
        except Exception as _fw_err:
            _fw_log("drawattach.py:279", _fw_err)
        for its in self.items().values():
            for it in its:
                try:
                    it.setOpacity(1.0)
                except Exception as _fw_err:
                    _fw_log("drawattach.py:285", _fw_err)
        self.doc.openTransaction("Hide/Show Annotations")
        try:
            for n in self.faint:
                o = self.doc.getObject(n)
                if o is not None:
                    o.ViewObject.Visibility = False
        finally:
            self.doc.commitTransaction()
        _status("")


def hide_show(page):
    """The command: starts the mode, or ends the one running."""
    if HideShowMode.current is not None:
        HideShowMode.current.finish()
        return None
    return HideShowMode(page)


def _status(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 0 if text else 1)
    except Exception as _fw_err:
        _fw_log("drawattach.py:309", _fw_err)


# --------------------------------------------------------------------------- install
class _Observer:
    def slotCreatedObject(self, obj):
        try:
            if obj.TypeId != "TechDraw::DrawViewSymbol":
                return
            dn, n = obj.Document.Name, obj.Name
        except Exception:
            return
        QtCore.QTimer.singleShot(0, lambda: _new(dn, n, 0))


def _new(dn, n, tries):
    try:
        o = App.getDocument(dn).getObject(n)
    except Exception:
        return
    if o is None:
        return
    if page_of(o) is None or not getattr(o, "SWAnnotation", ""):
        if tries < 5:
            QtCore.QTimer.singleShot(50, lambda: _new(dn, n, tries + 1))
        return
    try:
        attach_new(o)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: attach %s: %s\n" % (n, error))


_INSTALLED = []


def install():
    if _INSTALLED:
        return
    _INSTALLED.append(_Observer())
    App.addDocumentObserver(_INSTALLED[0])
    try:
        from . import drawselect as DS
        done0 = DS.drag_dimension_done

        def drag_dimension_done(page, p, copy):
            out = done0(page, p, copy)
            try:
                drag_done(page, p, copy)
            except Exception as error:
                App.Console.PrintLog("FreeCAD: attach on drag: %s\n" % error)
            return out
        DS.drag_dimension_done = drag_dimension_done
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: annotation attach: %s\n" % error)
