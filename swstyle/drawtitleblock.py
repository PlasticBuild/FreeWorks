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

import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D

PAD = 3.0
ASK = {}            # tests: "texts": {field: text} answered by the fill-in at once


# --------------------------------------------------------------------------- fields and hotspot
_TEXT = re.compile(r'<text\b([^>]*freecad:editable="([^"]+)"[^>]*)>', re.S)
_ATTR = re.compile(r'\b(x|y)="(-?[\d.]+)')


def field_positions(page):
    """{field: (x, y) sheet mm} of the sheet format's fields (from the format's SVG)."""
    from . import drawsheet
    path = drawsheet.page_template_path(page)
    try:
        with open(path, encoding="utf-8") as f:
            svg = f.read()
    except Exception as _fw_err:
        _fw_log("drawtitleblock.py:49", _fw_err)
        return {}
    try:
        h = float(page.Template.Height)
    except Exception:
        h = 0.0
    out = {}
    for m in _TEXT.finditer(svg):
        attrs = dict(_ATTR.findall(m.group(1)))
        if "x" in attrs and "y" in attrs:
            out[m.group(2)] = (float(attrs["x"]), h - float(attrs["y"]))
    return out


def fields(page):
    """The fields in fill-in order: SWTitleFieldOrder first, then the rest top to bottom, left to right."""
    texts = dict(getattr(page.Template, "EditableTexts", {}) or {}) if page.Template is not None else {}
    pos = field_positions(page)
    order = [k for k in (getattr(page, "SWTitleFieldOrder", []) or []) if k in texts]
    rest = sorted((k for k in texts if k not in order), key=lambda k: (-round(pos.get(k, (0, 0))[1], 1),
                                                                         pos.get(k, (0, 0))[0], k))
    return order + rest


def set_order(page, names):
    if "SWTitleFieldOrder" not in page.PropertiesList:
        page.addProperty("App::PropertyStringList", "SWTitleFieldOrder", "FreeCAD", "Title Block Fields: Tab order")
    page.SWTitleFieldOrder = list(names)


def hotspot(page):
    """(x0, y0, x1, y1) sheet mm of the title block hotspot, else None."""
    hs = list(getattr(page, "SWTitleHotspot", []) or [])
    if len(hs) == 4 and hs[2] > hs[0] and hs[3] > hs[1]:
        return tuple(hs)
    pos = list(field_positions(page).values())
    if not pos:
        return None
    xs, ys = [p[0] for p in pos], [p[1] for p in pos]
    try:
        w = float(page.Template.Width)
    except Exception:
        w = max(xs) + 40.0
    return (min(xs) - PAD, min(ys) - PAD, min(max(xs) + 40.0, w - 2 * PAD), max(ys) + PAD + 3.0)


def set_hotspot(page, rect):
    if "SWTitleHotspot" not in page.PropertiesList:
        page.addProperty("App::PropertyFloatList", "SWTitleHotspot", "FreeCAD", "Title Block Fields: hotspot")
    page.SWTitleHotspot = list(rect) if rect else []


def in_hotspot(page, p):
    hs = hotspot(page)
    return hs is not None and hs[0] <= p[0] <= hs[2] and hs[1] <= p[1] <= hs[3]


# --------------------------------------------------------------------------- the fill-in

CAPTIONS = {"TolLinear": "Linear tolerance", "TolAngular": "Angular tolerance", "DrawnBy": "Drawn by",
            "Date": "Drawn date", "CheckedBy": "Checked by", "CheckedDate": "Checked date",
            "EngApproval": "Eng. approval", "EngApprovalDate": "Eng. approval date", "MfgApproval": "Mfg. approval",
            "MfgApprovalDate": "Mfg. approval date", "QA": "Q.A.", "QADate": "Q.A. date",
            "CompanyName": "Company name", "Title2": "Title, second line", "DrawingNumber": "Dwg. no.",
            "GeneralTolerance": "General tolerance", "SurfaceFinish": "Surface finish"}


def caption(name):
    """A field's name as the fill-in shows it: CompanyName -> Company name (the caption table first)."""
    if name in CAPTIONS:
        return CAPTIONS[name]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|_", " ", name).split()
    return " ".join([words[0]] + [w.lower() if not w.isupper() else w for w in words[1:]]) if words else name


class FillInDialog(QtWidgets.QDialog):
    """The title block fill-in: one box per field, in the Title Block Fields order."""

    def __init__(self, page, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        from . import drawlayout
        self.setObjectName("SWTitleBlockFillIn")
        self.setWindowTitle("Title Block")
        self.page = page
        texts = dict(getattr(page.Template, "EditableTexts", {}) or {})
        links = drawlayout.field_links(page)
        lay = QtWidgets.QFormLayout(self)
        self.boxes = {}
        for k in fields(page):
            w = QtWidgets.QLineEdit(links.get(k, texts.get(k, "")), self)
            w.setObjectName("SWTitleField_" + re.sub(r"\W", "_", k))
            if k in links:
                w.setToolTip("Linked to a property: %s" % links[k])
            lay.addRow(caption(k) + ":", w)
            self.boxes[k] = w
        prev = None
        for w in self.boxes.values():
            if prev is not None:
                QtWidgets.QWidget.setTabOrder(prev, w)
            prev = w
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        if self.boxes:
            QtCore.QTimer.singleShot(0, lambda: list(self.boxes.values())[0].setFocus())

    def values(self):
        return {k: w.text() for k, w in self.boxes.items()}

    def apply(self):
        write(self.page, self.values())
        self.accept()


def write(page, values):
    """The fields take values; a "$PRP..." value links the field to that property (as Title Block Fields)."""
    from . import drawlayout
    texts = dict(getattr(page.Template, "EditableTexts", {}) or {})
    links = drawlayout.field_links(page)
    for k, t in values.items():
        if k not in texts:
            continue
        if "$PRP" in t:
            links[k] = t
        else:
            links.pop(k, None)
        texts[k] = t
    doc = page.Document
    doc.openTransaction("Title Block")
    try:
        drawlayout.set_field_links(page, links)
        page.Template.EditableTexts = drawlayout.resolve_fields(page, texts)
    finally:
        doc.commitTransaction()
    doc.recompute()
    return page.Template.EditableTexts


def fill_in(page):
    """A click on the hotspot: zoom to the title block, the fill-in, then back."""
    gv = D.page_view(page)
    before = None
    hs = hotspot(page)
    if gv is not None and hs is not None:
        before = (QtGui.QTransform(gv.transform()), gv.horizontalScrollBar().value(), gv.verticalScrollBar().value())
        r = QtCore.QRectF(D.to_scene(hs[0], hs[3]), D.to_scene(hs[2], hs[1])).normalized()
        gv.fitInView(r.adjusted(-200, -200, 200, 200), QtCore.Qt.KeepAspectRatio)
    try:
        answer = ASK.pop("texts", None)
        if answer is not None:
            write(page, answer)
            return True
        return FillInDialog(page).exec_() == QtWidgets.QDialog.Accepted
    finally:
        if gv is not None and before is not None:
            try:                           # the sheet window may have closed while the fill-in was open
                gv.setTransform(before[0])
                gv.horizontalScrollBar().setValue(before[1])
                gv.verticalScrollBar().setValue(before[2])
            except RuntimeError as _fw_err:
                _fw_log("drawtitleblock.py:191", _fw_err)


# --------------------------------------------------------------------------- the sheet: hover and click
class _Hotspot(QtCore.QObject):
    def __init__(self, page, gv):
        super().__init__(gv)
        self.page_name = (page.Document.Name, page.Name)
        self.gv = gv
        self.box = None
        self.down = None

    def page(self):
        try:
            return App.getDocument(self.page_name[0]).getObject(self.page_name[1])
        except Exception as _fw_err:
            _fw_log("drawtitleblock.py:209", _fw_err)
            return None

    def _box(self, show, page=None):
        sc = self.gv.scene()
        if show and self.box is None and page is not None:
            hs = hotspot(page)
            if hs is None:
                return
            it = QtWidgets.QGraphicsRectItem(QtCore.QRectF(D.to_scene(hs[0], hs[3]), D.to_scene(hs[2], hs[1])).normalized())
            pen = QtGui.QPen(QtGui.QColor(255, 140, 0))
            pen.setCosmetic(True)
            pen.setWidth(2)
            it.setPen(pen)
            it.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            it.setZValue(1e6)
            it.setData(0, "SWTitleHotspot")
            sc.addItem(it)
            self.box = it
        elif not show and self.box is not None:
            try:
                sc.removeItem(self.box)
            except Exception as _fw_err:
                _fw_log("drawtitleblock.py:229", _fw_err)
            self.box = None

    def _active(self, page):
        from . import drawsheet
        return page is not None and not drawsheet.editing_format(page) and not Gui.Control.activeDialog()

    def eventFilter(self, obj, event):
        try:
            t = event.type()
            if t not in (QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease,
                         QtCore.QEvent.Leave):
                return False
            page = self.page()
            if t == QtCore.QEvent.Leave or page is None or not self._active(page):
                self._box(False)
                return False
            pt = event.position().toPoint() if hasattr(event, "position") else event.pos()
            p = D.to_sheet(self.gv.mapToScene(pt))
            p = (p.x(), p.y()) if hasattr(p, "x") else p
            inside = in_hotspot(page, p)
            if t == QtCore.QEvent.MouseMove:
                self._box(inside and not (event.buttons() & QtCore.Qt.LeftButton), page)
            elif t == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                self.down = (pt.x(), pt.y()) if inside else None
            elif t == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                if self.down is not None and inside and abs(pt.x() - self.down[0]) + abs(pt.y() - self.down[1]) <= 4:
                    QtCore.QTimer.singleShot(0, lambda q=QtCore.QPoint(pt): self.clicked(q))
                self.down = None
        except Exception as _fw_err:
            _fw_log("drawtitleblock.py:259", _fw_err)
        return False

    def clicked(self, pt=None):
        page = self.page()
        if page is None:
            return
        if Gui.Selection.getSelection():
            return                         # the click picked something in the title block area (a note, a table)
        try:
            if pt is not None and any("TemplateTextField" in type(it).__name__ for it in self.gv.items(pt)):
                return                     # TechDraw's own field marker: it edits that field
        except Exception as _fw_err:
            _fw_log("drawtitleblock.py:272", _fw_err)
        self._box(False)
        fill_in(page)


def hook(page):
    gv = D.page_view(page)
    if gv is None:
        return None
    f = gv.findChild(QtCore.QObject, "SWTitleHotspotFilter")
    if f is not None:
        return f
    f = _Hotspot(page, gv)
    f.setObjectName("SWTitleHotspotFilter")
    gv.viewport().installEventFilter(f)
    gv.viewport().setMouseTracking(True)
    return f
