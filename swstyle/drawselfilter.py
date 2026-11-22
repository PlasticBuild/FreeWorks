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


ANNOT_KINDS = {
    "Note": "note", "MarkupNote": "note", "Balloon": "note", "StackedBalloon": "note", "MultiJogLeader": "note",
    "LocationLabel": "note", "SurfaceFinish": "surface_finish", "GeometricTolerance": "gtol", "GTol": "gtol",
    "DatumFeature": "datum_feature", "DatumTarget": "datum_target", "WeldSymbol": "weld_symbol",
    "Caterpillar": "weld_bead", "EndTreatment": "weld_bead", "Block": "block", "DowelPin": "dowel_pin",
    "CenterMark": "center_mark", "Centerline": "centerline", "HoleCallout": "dimension",
}
_INSTALLED = []


def drawing_kinds(obj, sub):
    """The selfilter kinds of a pick on a drawing sheet, else None (not a drawing object)."""
    tid = getattr(obj, "TypeId", "")
    if not tid.startswith("TechDraw::"):
        return None
    kind = getattr(obj, "SWAnnotation", "")
    if kind:
        return {ANNOT_KINDS.get(kind, "any")}
    if obj.isDerivedFrom("TechDraw::DrawViewDimension") or obj.isDerivedFrom("TechDraw::DrawViewDimExtent"):
        return {"dimension"}
    if obj.isDerivedFrom("TechDraw::DrawViewBalloon") or obj.isDerivedFrom("TechDraw::DrawViewAnnotation") or \
            obj.isDerivedFrom("TechDraw::DrawRichAnno") or obj.isDerivedFrom("TechDraw::DrawLeaderLine"):
        return {"note"}
    if obj.isDerivedFrom("TechDraw::DrawWeldSymbol"):
        return {"weld_symbol"}
    if obj.isDerivedFrom("TechDraw::DrawViewPart"):
        name = (sub or "").split(".")[-1]
        if name.startswith("Edge"):
            return {"edge"}
        if name.startswith("Vertex"):
            return {"vertex"}
        if name.startswith("Face"):
            return {"face"}
        return {"any"}
    return {"any"}


def _over_sheet():
    try:
        from PySide import QtGui, QtWidgets
        app = QtWidgets.QApplication.instance()
        w = app.widgetAt(QtGui.QCursor.pos()) if app else None
        while w is not None:
            if "QGVPage" in w.metaObject().className():
                return True
            w = w.parentWidget()
    except Exception as _fw_err:
        _fw_log("drawselfilter.py:72", _fw_err)
    return False


def install():
    if _INSTALLED:
        return
    try:
        from . import selfilter as SF
    except Exception:
        return
    old_kinds, old_under = SF.kinds, SF._view_under_cursor

    def kinds(obj, sub):
        try:
            k = drawing_kinds(obj, sub)
        except Exception:
            k = None
        return k if k is not None else old_kinds(obj, sub)

    def view_under_cursor():
        return old_under() or _over_sheet()
    SF.kinds = kinds
    SF._view_under_cursor = view_under_cursor
    _INSTALLED.append((old_kinds, old_under))


# --------------------------------------------------------------------------- picking through annotation squares

# a symbol anywhere in its square, which reaches far past what it draws (a balloon's leader makes it a square

# square but off its lines picks what is under it instead: the view edge there, else the view. The press itself
# is left to TechDraw (looking at the sheet's items while it takes the press loses its pick); the pick is put
# right once the click is over.
HIT_MM = 1.0          # pick tolerance around drawn lines, sheet mm
_PENDING = {}


def drawn_at(obj, sheet_pt, tol=HIT_MM):
    """Whether symbol obj draws anything within tol (sheet mm) of sheet_pt: its SVG is drawn into a small image
    from the object's own Symbol text (the sheet's items are not touched while TechDraw takes the press)."""
    from PySide import QtCore, QtGui
    try:
        from PySide import QtSvg
    except Exception:
        return True
    k = float(getattr(obj, "Scale", 1.0) or 1.0)
    try:
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(obj.Symbol.encode("utf-8")))
    except Exception:
        return True
    if not r.isValid():
        return True
    vb = r.viewBoxF()
    # the symbol is centred on its X, Y; its SVG units are mm with Y down
    lx = (sheet_pt[0] - float(obj.X)) / k + vb.center().x()
    ly = -(sheet_pt[1] - float(obj.Y)) / k + vb.center().y()
    rot = float(getattr(obj, "Rotation", 0.0) or 0.0)
    if abs(rot) > 1e-9:
        import math
        cx, cy = vb.center().x(), vb.center().y()
        a = math.radians(rot)
        dx, dy = lx - cx, ly - cy
        lx, ly = cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)
    px = 24
    img = QtGui.QImage(px, px, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QtGui.QPainter(img)
    try:
        t = tol / k
        # the whole SVG drawn so that the square lx +- t, ly +- t fills the image
        sx = px / (2 * t)
        target = QtCore.QRectF((vb.x() - (lx - t)) * sx, (vb.y() - (ly - t)) * sx, vb.width() * sx, vb.height() * sx)
        r.render(p, target)
    finally:
        p.end()
    for y in range(0, px, 2):
        for x in range(0, px, 2):
            if QtGui.qAlpha(img.pixel(x, y)) > 20:
                return True
    return False


def view_element_at(view, sheet_pt, tol=HIT_MM):
    """The view's visible edge (else vertex) within tol of sheet point, as "EdgeN" / "VertexN", else ""."""
    import Part
    from . import drawings as D
    x0, y0 = D.view_position(view)
    q = App.Vector(sheet_pt[0] - x0, -(sheet_pt[1] - y0), 0)       # view geometry: Y points down
    probe = Part.Vertex(q)
    best = None
    try:
        for i, e in enumerate(view.getVisibleEdges()):
            dist = e.distToShape(probe)[0]
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, "Edge%d" % i)
    except Exception as _fw_err:
        _fw_log("drawselfilter.py:169", _fw_err)
    return best[1] if best else ""


def _filtering():
    try:
        from . import selfilter as SF
        return SF.state().filtering()
    except Exception:
        return False


class _PickThrough:
    def __init__(self):
        from PySide import QtCore

        class F(QtCore.QObject):
            def eventFilter(fself, obj, event):
                try:
                    t = event.type()
                    if t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                        self.press(obj, event)
                    elif t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                        self.release(obj, event)
                except Exception as _fw_err:
                    _fw_log("drawselfilter.py:194", _fw_err)
                return False
        self.f = F()

    @staticmethod
    def _pos(event):
        return event.position().toPoint() if hasattr(event, "position") else event.pos()

    def press(self, viewport, event):
        # nothing of the sheet is touched here: asking the scene for its items while TechDraw takes the press
        # lost TechDraw's pick on the bench
        _PENDING.clear()
        if event.modifiers():
            return                         # Ctrl/Shift picks: left to TechDraw
        gv = viewport.parentWidget()
        if gv is None or gv.scene() is None:
            return
        from . import drawings as D
        pos = self._pos(event)
        _PENDING.update(pos=pos, sheet=D.to_sheet(gv.mapToScene(pos)))

    def release(self, viewport, event):
        if not _PENDING:
            return
        pos = self._pos(event)
        p0 = _PENDING["pos"]
        job = dict(_PENDING)
        _PENDING.clear()
        if abs(pos.x() - p0.x()) + abs(pos.y() - p0.y()) > 4:
            return                         # a drag: TechDraw moved what it picked, as it does
        from PySide import QtCore
        QtCore.QTimer.singleShot(0, lambda: self.repick(job))

    def repick(self, job):
        import os
        if os.environ.get("SWDBG_NOREPICK"):
            return
        at = job["sheet"]
        sel = Gui.Selection.getSelectionEx("", 0)
        sym = None
        if not sel:
            # a selection filter refused what TechDraw picked (a symbol's square over an edge): the edge, if
            # the filters let it through
            if not _filtering():
                return
            from . import drawings as D
            page = D.active_page()
            if page is None:
                return
        else:
            if len(sel) != 1:
                return
            sym = sel[0].Object
            if sym.TypeId != "TechDraw::DrawViewSymbol" or not getattr(sym, "SWAnnotation", ""):
                return
            if drawn_at(sym, at):
                return                     # on what the symbol draws: its pick
            page = next((p for p in sym.InList if p.isDerivedFrom("TechDraw::DrawPage")), None)
            if page is None:
                return
        from . import drawviews as DV
        under, sub = None, ""
        for v in page.Views:
            if v is sym or not v.isDerivedFrom("TechDraw::DrawViewPart"):
                continue
            try:
                a, b, c, d = DV.view_box(v)
            except Exception:
                continue
            if a - HIT_MM <= at[0] <= c + HIT_MM and b - HIT_MM <= at[1] <= d + HIT_MM:
                el = view_element_at(v, at)
                if under is None or (el and not sub):
                    under, sub = v, el
        doc = page.Document
        try:
            if sym is not None:
                Gui.Selection.removeSelection(doc.Name, sym.Name)     # off its lines: not the symbol
            if under is not None and (sym is not None or sub):
                Gui.Selection.addSelection(doc.Name, under.Name, sub)
        except Exception as _fw_err:
            _fw_log("drawselfilter.py:274", _fw_err)


_THROUGH = []


def hook(gv):
    """Installed on each open sheet (drawselect.hook_page)."""
    import os
    if os.environ.get("SWNOTHROUGH"):
        return
    if not _THROUGH:
        _THROUGH.append(_PickThrough())
    gv.viewport().installEventFilter(_THROUGH[0].f)
