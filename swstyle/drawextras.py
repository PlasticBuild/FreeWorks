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

import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

RES = 10.0



def _fw_unsplit(objs):
    """objs with a drawing view's model parts read back as their model (drawviews.unsplit; Drawings land151)."""
    try:
        from . import drawviews as DV
        return DV.unsplit(list(objs or []))
    except Exception:
        return list(objs or [])

def _mw():
    return Gui.getMainWindow()


def _prop(o, name, kind="App::PropertyString", doc=""):
    if name not in o.PropertiesList:
        o.addProperty(kind, name, "FreeCAD", doc)


def _transaction(doc, name, body):
    doc.openTransaction(name)
    try:
        body()
    finally:
        doc.commitTransaction()
    doc.recompute()


def _page_of(o):
    try:
        return o.findParentPage()
    except Exception as _fw_err:
        _fw_log("drawextras.py:59", _fw_err)
    for p in o.InList:
        if p.isDerivedFrom("TechDraw::DrawPage"):
            return p
    return None


# --------------------------------------------------------------------------- layers
DEFAULT_LAYERS = ["-None-|#000000|1", "FORMAT|#000000|1"]


def layers(page):
    """[[name, colour, on]]: -None-, the drawing's layers (Layer Properties, the Layer toolbar), then the sheet's
    own older ones (FORMAT)."""
    from . import drawpmparts as PP
    out = [["-None-", "#000000", "1"]]
    for L in PP.layers(page.Document):
        n = L.get("name", "")
        if n and n not in [o[0] for o in out]:
            out.append([n, L.get("color", "#000000"), "1" if L.get("on", True) else "0"])
    for line in list(getattr(page, "FWLayers", []) or []) or DEFAULT_LAYERS:
        f = line.split("|")
        if f[0] not in [o[0] for o in out]:
            out.append(f)
    return out


def layer_of(o):
    return getattr(o, "SWLayer", "") or getattr(o, "FWLayer", "") or "-None-"


def set_layer(objs, name, page):
    from . import drawpmparts as PP
    colour = next((c for n, c, _ in layers(page) if n == name), "#000000")
    known = PP.layer(page.Document, name) is not None

    def body():
        for o in objs:
            _prop(o, "FWLayer", doc="Layer")
            o.FWLayer = "" if name == "-None-" else name
            if known or name == "-None-":
                PP.apply_layer(o, name)          # the layer's colour, style, thickness; hidden while it is off
                continue
            vo = getattr(o, "ViewObject", None)
            if vo is None:
                continue
            q = QtCore.Qt
            from PySide import QtGui
            c = QtGui.QColor(colour)
            rgb = (c.redF(), c.greenF(), c.blueF())
            for p in ("Color", "LineColor", "TextColor"):
                if p in vo.PropertiesList:
                    try:
                        setattr(vo, p, rgb)
                    except Exception as _fw_err:
                        _fw_log("drawextras.py:114", _fw_err)
    _transaction(objs[0].Document, "Change Layer", body)


class LayerDialog(QtWidgets.QDialog):
    """Change Layer: the sheet's layers; New Layer adds one."""

    def __init__(self, page, objs):
        super().__init__(_mw())
        self.page, self.objs = page, objs
        self.setWindowTitle("Change Layer")
        self.setObjectName("SWChangeLayer")
        lay = QtWidgets.QVBoxLayout(self)
        self.list = QtWidgets.QListWidget(self)
        self.list.setObjectName("SWLayerList")
        lay.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        new = QtWidgets.QPushButton("New Layer...", self)
        new.setObjectName("SWNewLayer")
        new.clicked.connect(self.new_layer)
        row.addWidget(new)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill(layer_of(objs[0]))

    def fill(self, current):
        self.list.clear()
        for n, c, on in layers(self.page):
            it = QtWidgets.QListWidgetItem(n, self.list)
            if n == current:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None:
            self.list.setCurrentRow(0)

    def new_layer(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New Layer", "Name:")
        name = (name or "").strip().replace("|", "")
        if ok and name and name not in [l[0] for l in layers(self.page)]:
            from . import drawpmparts as PP           # one list of layers: Layer Properties shows it too
            PP.set_layers(self.page.Document, list(PP.layers(self.page.Document)) +
                          [{"name": name, "description": "", "color": "#000000", "style": "Solid",
                            "thickness": "Default", "on": True, "print": True}])
            self.fill(name)

    def chosen(self):
        it = self.list.currentItem()
        return it.text() if it is not None else None

    def accept(self):
        name = self.chosen()
        if name:
            set_layer(self.objs, name, self.page)
        super().accept()


def change_layer(objs):
    objs = [o for o in objs if o is not None]
    page = _page_of(objs[0]) if objs else None
    if page is None and objs and objs[0].isDerivedFrom("TechDraw::DrawPage"):
        page = objs[0]
    if page is None:
        return None
    d = LayerDialog(page, objs)
    d.show()
    return d


# --------------------------------------------------------------------------- focus, grid
def toggle_sheet_focus(page):
    _prop(page, "FWLockSheetFocus", "App::PropertyBool", "Lock Sheet Focus: new sketch items go on the sheet")
    page.FWLockSheetFocus = not page.FWLockSheetFocus
    if page.FWLockSheetFocus and "FWLockViewFocus" in page.PropertiesList:
        page.FWLockViewFocus = ""
    return page.FWLockSheetFocus


def toggle_view_focus(view):
    page = _page_of(view)
    _prop(page, "FWLockViewFocus", doc="Lock View Focus: new sketch items go in this view")
    page.FWLockViewFocus = "" if page.FWLockViewFocus == view.Name else view.Name
    if page.FWLockViewFocus and "FWLockSheetFocus" in page.PropertiesList:
        page.FWLockSheetFocus = False
    return page.FWLockViewFocus == view.Name


def view_focus_locked(view):
    page = _page_of(view)
    return page is not None and getattr(page, "FWLockViewFocus", "") == view.Name


def sheet_focus_locked(page):
    return bool(getattr(page, "FWLockSheetFocus", False))


def grid_on(page):
    try:
        return bool(page.ViewObject.ShowGrid)
    except Exception:
        return False


def toggle_grid(page):
    try:
        page.ViewObject.ShowGrid = not page.ViewObject.ShowGrid
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Display Grid: %s\n" % error)


# --------------------------------------------------------------------------- sheet
def _select_only(o):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(o.Document.Name, o.Name)


SHEET_CLIP = []      # the sheet Copy kept, for Paste (FreeCAD's Std_Copy puts nothing on the clipboard for a page)


def copy_sheet(page):
    """Copy on a sheet: Paste then adds a copy of it (format and views) after the last sheet."""
    _select_only(page)
    SHEET_CLIP[:] = [(page.Document.Name, page.Name)]
    try:
        _mw().statusBar().showMessage("%s copied." % page.Label, 3000)
    except Exception as _fw_err:
        _fw_log("drawextras.py:242", _fw_err)


def copied_sheet():
    if not SHEET_CLIP:
        return None
    d = App.listDocuments().get(SHEET_CLIP[0][0])
    o = d.getObject(SHEET_CLIP[0][1]) if d is not None else None
    return o if o is not None and o.isDerivedFrom("TechDraw::DrawPage") else None


class _PasteKey(QtCore.QObject):
    """Ctrl+V after a sheet's Copy, on the sheet or in the drawing's tree: the copied sheet comes back as a new one.
    The key is taken where it first arrives (the window), since other key filters sit between it and the sheet."""
    _last = [0.0]

    def eventFilter(self, obj, event):
        if not isinstance(event, QtCore.QEvent):
            return False        # a stale PySide wrapper can arrive here
        try:
            t = event.type()
            if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride) or not SHEET_CLIP:
                return False
            if event.key() != QtCore.Qt.Key_V or event.modifiers() != QtCore.Qt.ControlModifier:
                return False
            fw = QtWidgets.QApplication.focusWidget()
            if fw is None or isinstance(fw, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                                             QtWidgets.QAbstractSpinBox)):
                return False
            doc = App.ActiveDocument
            src = copied_sheet()
            if doc is None or src is None or src.Document.Name != doc.Name:
                return False
            w, ok = fw, False
            for _ in range(6):
                if w is None:
                    break
                if "QGVPage" in w.metaObject().className() or isinstance(w, QtWidgets.QTreeView):
                    ok = True
                    break
                w = w.parentWidget()
            if not ok:
                return False
            if t == QtCore.QEvent.ShortcutOverride:
                event.accept()          # Edit > Paste's shortcut stays out
                return True
            import time
            now = time.time()
            if now - _PasteKey._last[0] > 0.3:      # one paste per key press (the window and the sheet both see it)
                _PasteKey._last[0] = now
                QtCore.QTimer.singleShot(0, lambda: paste_sheet(doc))
            return True
        except Exception as error:
            App.Console.PrintLog("FreeCAD: sheet paste key: %s\n" % error)
            return False


_PASTE = []


def install_paste():
    if _PASTE:
        return _PASTE[0]
    f = _PasteKey(QtWidgets.QApplication.instance())
    try:
        from . import events
        events.register("drawextras.paste", (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride), f.eventFilter)
        try:        # first in line: it takes only Ctrl+V on a sheet after a sheet's Copy, the key fallbacks would run Paste
            for t in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
                lst = events._BY_TYPE.get(t, [])
                mine = [h for h in lst if h[0] == "drawextras.paste"]
                for h in mine:
                    lst.remove(h)
                lst[0:0] = mine
        except Exception as _fw_err:
            _fw_log("drawextras.py:317", _fw_err)
    except ImportError:
        QtWidgets.QApplication.instance().installEventFilter(f)
    _PASTE.append(f)
    return f


def _next_sheet_name(doc):
    names = {o.Label for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")}
    n = 1
    while "Sheet%d" % n in names:
        n += 1
    return "Sheet%d" % n


def paste_sheet(doc=None):
    """Paste: a new sheet with the copied sheet's format, scale and model views (annotations stay behind)."""
    src = copied_sheet()
    doc = doc or App.ActiveDocument
    if src is None or doc is None:
        return None
    out = []

    def body():
        page = doc.addObject("TechDraw::DrawPage", "Sheet")
        page.Label = _next_sheet_name(doc)
        tpl = getattr(src, "Template", None)
        if tpl is not None:
            t = doc.addObject(tpl.TypeId, "Template")
            for prop in ("Template", "EditableTexts"):
                if prop in tpl.PropertiesList:
                    try:
                        setattr(t, prop, getattr(tpl, prop))
                    except Exception as _fw_err:
                        _fw_log("drawextras.py:351", _fw_err)
            page.Template = t
        for prop in ("Scale", "ProjectionType", "KeepUpdated"):
            if prop in src.PropertiesList and prop in page.PropertiesList:
                try:
                    setattr(page, prop, getattr(src, prop))
                except Exception as _fw_err:
                    _fw_log("drawextras.py:358", _fw_err)
        for v in src.Views:
            if v.isDerivedFrom("TechDraw::DrawViewPart") and not v.isDerivedFrom("TechDraw::DrawViewSection") \
                    and not v.isDerivedFrom("TechDraw::DrawViewDetail") and v.TypeId != "TechDraw::DrawProjGroupItem":
                w = doc.addObject(v.TypeId, "View")
                for prop in ("Source", "XSource", "Direction", "XDirection", "Scale", "ScaleType", "X", "Y",
                             "Rotation", "HardHidden", "SmoothVisible", "SeamVisible", "Perspective", "Caption"):
                    if prop in v.PropertiesList:
                        try:
                            setattr(w, prop, getattr(v, prop))
                        except Exception as _fw_err:
                            _fw_log("drawextras.py:369", _fw_err)
                w.Label = v.Label
                page.addView(w)
        out.append(page)
    _transaction(doc, "Paste Sheet", body)
    if out:
        try:
            out[0].ViewObject.doubleClicked()
        except Exception as _fw_err:
            _fw_log("drawextras.py:378", _fw_err)
    return out[0] if out else None


def delete_object(o, ask=True):
    ""
    if ask:
        r = QtWidgets.QMessageBox.question(_mw(), "Confirm Delete", "Delete %s?" % o.Label,
                                           QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if r != QtWidgets.QMessageBox.Yes:
            return False
    doc = o.Document
    page = _page_of(o) if not o.isDerivedFrom("TechDraw::DrawPage") else None

    def body():
        Gui.Selection.clearSelection()
        if o.isDerivedFrom("TechDraw::DrawPage"):
            for v in list(o.Views):
                try:
                    doc.removeObject(v.Name)
                except Exception as _fw_err:
                    _fw_log("drawextras.py:399", _fw_err)
        doc.removeObject(o.Name)
    _transaction(doc, "Delete", body)
    return True


class TitleBlockDialog(QtWidgets.QDialog):
    """Title Block Fields: the sheet format's editable texts."""

    def __init__(self, page):
        super().__init__(_mw())
        self.page = page
        self.setWindowTitle("Title Block Fields")
        self.setObjectName("SWTitleBlockFields")
        lay = QtWidgets.QFormLayout(self)
        self.edits = {}
        t = page.Template
        texts = dict(getattr(t, "EditableTexts", {}) or {}) if t is not None else {}
        for k in sorted(texts):
            e = QtWidgets.QLineEdit(texts[k], self)
            e.setObjectName("SWTitle_" + k)
            lay.addRow(k, e)
            self.edits[k] = e
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def accept(self):
        t = self.page.Template
        if t is not None:
            texts = dict(t.EditableTexts)
            for k, e in self.edits.items():
                texts[k] = e.text()

            def body():
                t.EditableTexts = texts
            _transaction(self.page.Document, "Title Block Fields", body)
        super().accept()


def title_block_fields(page):
    d = TitleBlockDialog(page)
    d.show()
    return d


def sheet_size(page):
    try:
        from . import drawings
        return drawings.sheet_size(page)
    except Exception:
        t = page.Template
        return float(getattr(t, "Width", 420)), float(getattr(t, "Height", 297))


def automatic_border(page, cols=None, rows=None, margin=10.0):
    """Automatic Border: zone marks (1, 2, 3... across, A, B, C... up) round the sheet format."""
    from . import drawannot as DA
    w, h = sheet_size(page)
    cols = cols or max(2, int(round(w / 50.0)))
    rows = rows or max(2, int(round(h / 50.0)))
    for o in list(page.Views):
        if getattr(o, "SWAnnotation", "") == "AutoBorder":
            page.Document.removeObject(o.Name)
    cx, cy = w / 2, h / 2
    body = ['<rect x="%g" y="%g" width="%g" height="%g" fill="none" stroke="#000" stroke-width="0.5"/>'
            % (margin - cx, margin - cy, w - 2 * margin, h - 2 * margin)]
    m2 = margin / 2
    for i in range(cols):
        x = margin + (w - 2 * margin) * (i + 0.5) / cols - cx
        xe = margin + (w - 2 * margin) * (i + 1) / cols - cx
        for y in (m2 - cy, cy - m2):
            body.append('<text x="%g" y="%g" font-size="3.5" text-anchor="middle" font-family="osifont">%d</text>'
                        % (x, y + 1.2, cols - i))
        if i < cols - 1:
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.35"/>'
                        % (xe, -cy + 0, xe, -cy + margin))
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.35"/>'
                        % (xe, cy - margin, xe, cy))
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    for j in range(rows):
        y = margin + (h - 2 * margin) * (j + 0.5) / rows - cy
        ye = margin + (h - 2 * margin) * (j + 1) / rows - cy
        for x in (m2 - cx, cx - m2):
            body.append('<text x="%g" y="%g" font-size="3.5" text-anchor="middle" font-family="osifont">%s</text>'
                        % (x, y + 1.2, letters[j % len(letters)]))
        if j < rows - 1:
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.35"/>'
                        % (-cx, ye, -cx + margin, ye))
            body.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="#000" stroke-width="0.35"/>'
                        % (cx - margin, ye, cx, ye))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
           % (w, h, -cx, -cy, w, h, "".join(body)))
    doc = page.Document
    s = doc.addObject("TechDraw::DrawViewSymbol", "AutoBorder")
    s.Symbol = svg
    page.addView(s)
    s.X, s.Y = cx, cy
    s.Label = "Automatic Border"
    _prop(s, "SWAnnotation", doc="Annotation kind")
    s.SWAnnotation = "AutoBorder"
    _prop(s, "FWLayer", doc="Layer")
    s.FWLayer = "FORMAT"
    doc.recompute()
    return s


class BorderDialog(QtWidgets.QDialog):
    def __init__(self, page):
        super().__init__(_mw())
        self.page = page
        self.setWindowTitle("Automatic Border")
        self.setObjectName("SWAutomaticBorder")
        lay = QtWidgets.QFormLayout(self)
        w, h = sheet_size(page)
        self.cols = QtWidgets.QSpinBox(self)
        self.cols.setRange(1, 50)
        self.cols.setValue(max(2, int(round(w / 50.0))))
        self.cols.setObjectName("SWBorderColumns")
        self.rows = QtWidgets.QSpinBox(self)
        self.rows.setRange(1, 50)
        self.rows.setValue(max(2, int(round(h / 50.0))))
        self.rows.setObjectName("SWBorderRows")
        self.margin = QtWidgets.QDoubleSpinBox(self)
        self.margin.setRange(2, 50)
        self.margin.setValue(10)
        self.margin.setObjectName("SWBorderMargin")
        lay.addRow("Zone columns", self.cols)
        lay.addRow("Zone rows", self.rows)
        lay.addRow("Margin (mm)", self.margin)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def accept(self):
        doc = self.page.Document
        doc.openTransaction("Automatic Border")
        try:
            automatic_border(self.page, self.cols.value(), self.rows.value(), self.margin.value())
        finally:
            doc.commitTransaction()
        super().accept()


def automatic_border_dialog(page):
    d = BorderDialog(page)
    d.show()
    return d


# --------------------------------------------------------------------------- views
def page_view_widget():
    mdi = _mw().findChild(QtWidgets.QMdiArea)
    sub = mdi.activeSubWindow() if mdi is not None else None
    if sub is None or sub.widget() is None:
        return None
    for v in sub.widget().findChildren(QtWidgets.QGraphicsView):
        if v.metaObject().className() == "TechDrawGui::QGVPage" or not v.inherits("QOpenGLWidget"):
            return v
    return None


def jump_to(o):
    """Jump to ... View: picks it and brings it to the middle of the window."""
    if o is None:
        return False
    _select_only(o)
    if getattr(o, "TypeId", "") == "TechDraw::DrawPage":
        gv = page_view_widget()        # Zoom to Selection on the sheet: the whole sheet in the window
        if gv is not None and gv.scene() is not None:
            gv.fitInView(gv.scene().itemsBoundingRect(), QtCore.Qt.KeepAspectRatio)
        return True
    try:
        from . import drawmenu
        x, y = drawmenu._place(o)
        gv = page_view_widget()
        if gv is not None:
            gv.centerOn(QtCore.QPointF(x * RES, -y * RES))
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Jump to view: %s\n" % error)
    return True


def parent_view(v):
    try:
        from . import drawviewcmds
        return drawviewcmds.default_parent(v)
    except Exception:
        return getattr(v, "BaseView", None)


def section_views_of(v):
    return [o for o in v.InList if o.isDerivedFrom("TechDraw::DrawViewSection") and getattr(o, "BaseView", None) is v]


def detail_views_of(v):
    return [o for o in v.InList if o.isDerivedFrom("TechDraw::DrawViewDetail") and getattr(o, "BaseView", None) is v]


def toggle_cutting_line(section):
    base = section.BaseView
    try:
        vo = base.ViewObject
        vo.ShowSectionLine = not vo.ShowSectionLine
        return vo.ShowSectionLine
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Hide Cutting Line: %s\n" % error)
        return None


def edit_object(o):
    ""
    try:
        from . import drawselect
        if drawselect.is_view(o) or getattr(o, "TypeId", "") == "TechDraw::DrawProjGroup":
            v = getattr(o, "Anchor", None) if o.TypeId == "TechDraw::DrawProjGroup" else o
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(v)
            if drawselect.open_for(v) is not None:
                return True
    except Exception as error:
        App.Console.PrintLog("FreeCAD: edit view: %s\n" % error)
    try:
        Gui.ActiveDocument.setEdit(o.Name)
        return True
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: edit: %s\n" % error)
        return False


def model_candidates(doc):
    out = []
    for d in App.listDocuments().values():
        for o in d.Objects:
            if o.isDerivedFrom("TechDraw::DrawView") or o.isDerivedFrom("TechDraw::DrawPage"):
                continue
            if not hasattr(o, "Shape") or o.InList and any(p.isDerivedFrom("PartDesign::Body") for p in o.InList):
                continue
            try:
                if o.Shape.isNull() or not o.Shape.Solids:
                    continue
            except Exception:
                continue
            out.append(o)
    return out


def _browse_model(v):
    ""
    path, _ = QtWidgets.QFileDialog.getOpenFileName(_mw(), "Replace Model", "", "FreeCAD parts (*.FCStd)")
    if not path:
        return None
    doc = App.openDocument(path)
    App.setActiveDocument(v.Document.Name)
    cands = [o for o in model_candidates(doc) if o.Document is doc]
    if not cands:
        QtWidgets.QMessageBox.information(_mw(), "Replace Model", "%s has no solid body to show." % doc.Label)
        return None
    return cands[0]


def replace_model(v, new=None):
    """Replace Model: the view (and the views made from it) show another part."""
    if new is None:
        cands = model_candidates(v.Document)
        names = ["%s (%s)" % (o.Label, o.Document.Label) for o in cands]
        if not names:
            new = _browse_model(v)
            if new is None:
                return False
            cands, names = [new], ["%s (%s)" % (new.Label, new.Document.Label)]
        name, ok = QtWidgets.QInputDialog.getItem(_mw(), "Replace Model", "Replace the model of %s with:" % v.Label,
                                                  names, 0, False)
        if not ok:
            return False
        new = cands[names.index(name)]
    views = [v] + [o for o in v.Document.Objects if o.isDerivedFrom("TechDraw::DrawViewPart")
                   and parent_view(o) is v]

    def body():
        for w in views:
            if new.Document is w.Document:
                w.Source = [new]
                w.XSource = []
            else:
                w.XSource = [new]
                w.Source = []
    _transaction(v.Document, "Replace Model", body)
    return True


def _view_edges_sheet(v):
    from . import drawmenu
    x0, y0 = drawmenu._place(v)
    out = []
    for e in v.getVisibleEdges():
        try:
            pts = e.discretize(Deflection=0.05) if e.Curve.TypeId != "Part::GeomLine" else [e.Vertexes[0].Point,
                                                                                          e.Vertexes[-1].Point]
        except Exception:
            pts = [p.Point for p in e.Vertexes]
        if len(pts) >= 2:
            out.append([(x0 + p.x, y0 - p.y) for p in pts])
    return out


def convert_view_to_sketch(v):
    """Convert View to Sketch: the view's visible lines become a sketch on the sheet (the view goes)."""
    from . import drawannot as DA
    page = _page_of(v)
    lines = _view_edges_sheet(v)
    if page is None or not lines:
        return None
    allp = [p for l in lines for p in l]
    cx = (min(p[0] for p in allp) + max(p[0] for p in allp)) / 2
    cy = (min(p[1] for p in allp) + max(p[1] for p in allp)) / 2
    body = "".join('<polyline points="%s" fill="none" stroke="#000" stroke-width="0.35"/>'
                   % " ".join("%g,%g" % (p[0] - cx, -(p[1] - cy)) for p in l) for l in lines)
    reach = max(math.hypot(p[0] - cx, p[1] - cy) for p in allp) + 2
    result = {}

    def work():
        n = 1 + len([o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "SheetSketch"])
        s = DA.svg_symbol(page, "SheetSketch", body, reach, (cx, cy), "Sketch %d" % n, "SheetSketch")
        _prop(s, "SWSketchKind", doc="drawing sketch entity")
        s.SWSketchKind = "View"
        _prop(s, "SWFromView", doc="the view converted to this sketch")
        s.SWFromView = v.Label
        Gui.Selection.clearSelection()
        page.Document.removeObject(v.Name)
        result["s"] = s
    _transaction(page.Document, "Convert View to Sketch", work)
    return result.get("s")


def add_view_label(v):
    """Add View Label: the view's name and scale under it."""
    from . import drawannot as DA, drawmenu
    page = _page_of(v)
    box = drawmenu.view_box(v)
    if page is None or box is None:
        return None
    at = ((box[0] + box[2]) / 2, box[1] - 6)
    scale = float(getattr(v, "Scale", 1.0) or 1.0)
    text = "%s\nSCALE %s" % (v.Label.upper(), ("%g : 1" % scale) if scale >= 1 else ("1 : %g" % round(1 / scale, 3)))
    result = {}

    def work():
        body, reach = DA.note_svg(text, at, align="Center")
        n = 1 + len([o for o in page.Document.Objects if getattr(o, "SWAnnotation", "") == "Note"])
        s = DA.svg_symbol(page, "Note", body, reach, at, "Note%d" % n, "Note")
        _prop(s, "SWViewLabelOf", doc="the view this label names")
        s.SWViewLabelOf = v.Name
        _prop(s, "SWNoteText", doc="note text")
        s.SWNoteText = text
        result["s"] = s
    _transaction(page.Document, "Add View Label", work)
    return result.get("s")


def reset_sketch_visibility(v):
    """Reset sketch visibility: every hidden sketch of the view's sheet shows again."""
    page = _page_of(v)
    n = 0
    for o in (page.Views if page is not None else []):
        if getattr(o, "SWAnnotation", "") == "SheetSketch":
            try:
                if not o.ViewObject.Visibility:
                    o.ViewObject.Visibility = True
                    n += 1
            except Exception as _fw_err:
                _fw_log("drawextras.py:774", _fw_err)
    if not n:
        try:
            Gui.getMainWindow().statusBar().showMessage("Reset sketch visibility: no sketch of this sheet was hidden.", 4000)
        except Exception as _fw_err:
            _fw_log("drawextras.py:779", _fw_err)
    return n


def component_name(v):
    srcs = _fw_unsplit(getattr(v, "XSource", [])) + list(getattr(v, "Source", []) or [])
    return srcs[0].Label if srcs else None


def hide_component(v):
    """Show/Hide > Hide Component: the view stops showing the part (Show All Components brings it back)."""
    srcs = list(v.Source or [])
    xs = list(v.XSource or [])
    if not srcs and not xs:
        return False
    _prop(v, "FWHiddenComponents", "App::PropertyLinkListGlobal", "components hidden in this view")

    def body():
        hidden = list(v.FWHiddenComponents)
        if srcs:
            hidden.append(srcs[-1])
            v.Source = srcs[:-1]
        else:
            hidden.append(xs[-1])
            v.XSource = xs[:-1]
        v.FWHiddenComponents = hidden
    _transaction(v.Document, "Hide Component", body)
    return True


def hidden_components(v):
    return list(getattr(v, "FWHiddenComponents", []) or [])


def show_components(v):
    hidden = hidden_components(v)
    if not hidden:
        return False

    def body():
        src, xs = list(v.Source), list(v.XSource)
        for o in hidden:
            if o.Document is v.Document and getattr(o, "SWKind", "") != "FwModelPart":
                src.append(o)
            else:
                xs.append(o)
        v.Source, v.XSource = src, xs
        v.FWHiddenComponents = []
    _transaction(v.Document, "Show Components", body)
    return True


class LineFontDialog(QtWidgets.QDialog):
    """Component Line Font: the line thickness of the component's visible and hidden lines in this view."""

    def __init__(self, v):
        super().__init__(_mw())
        self.v = v
        self.setWindowTitle("Component Line Font")
        self.setObjectName("SWComponentLineFont")
        lay = QtWidgets.QFormLayout(self)
        vo = v.ViewObject
        self.visible = QtWidgets.QDoubleSpinBox(self)
        self.visible.setObjectName("SWLineFontVisible")
        self.hidden = QtWidgets.QDoubleSpinBox(self)
        self.hidden.setObjectName("SWLineFontHidden")
        for box, prop in ((self.visible, "LineWidth"), (self.hidden, "HiddenWidth")):
            box.setRange(0.05, 5.0)
            box.setSingleStep(0.05)
            box.setSuffix(" mm")
            try:
                box.setValue(float(getattr(vo, prop)))
            except Exception:
                box.setValue(0.35)
        lay.addRow("Visible edge thickness", self.visible)
        lay.addRow("Hidden edge thickness", self.hidden)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def accept(self):
        vo = self.v.ViewObject

        def body():
            for box, prop in ((self.visible, "LineWidth"), (self.hidden, "HiddenWidth")):
                try:
                    setattr(vo, prop, box.value())
                except Exception as _fw_err:
                    _fw_log("drawextras.py:868", _fw_err)
        _transaction(self.v.Document, "Component Line Font", body)
        super().accept()


def component_line_font(v):
    d = LineFontDialog(v)
    d.show()
    return d


# --------------------------------------------------------------------------- dimensions
def dim_value_text(dim):
    try:
        val = dim.getRawValue()
        return "%g" % round(val, 2)
    except Exception:
        return ""


def _dim_points(dim):
    try:
        pts = dim.getLinearPoints()
        if pts and len(pts) >= 2:
            return pts[0], pts[1]
    except Exception as _fw_err:
        _fw_log("drawextras.py:894", _fw_err)
    return None


def center_dimension(dim):
    """Center Dimension: the text halfway between the extension lines (it stays on its side)."""
    pts = _dim_points(dim)
    if pts is None:
        return False
    a, b = pts
    k = float(getattr(dim.References2D[0][0], "Scale", 1.0) or 1.0) if dim.References2D else 1.0

    def body():
        if dim.Type == "DistanceY":
            dim.Y = -(a.y + b.y) / 2 * k if abs(a.y) < 1e6 else dim.Y
        else:
            dim.X = (a.x + b.x) / 2 * k
        _prop(dim, "FWCentered", "App::PropertyBool", "Center Dimension")
        dim.FWCentered = True
    _transaction(dim.Document, "Center Dimension", body)
    return True


def is_centered(dim):
    return bool(getattr(dim, "FWCentered", False))


def toggle_offset_text(dim, step=5.0):
    """Offset Text: the text moves off the dimension line on a short leader (again: back)."""
    _prop(dim, "FWOffsetText", "App::PropertyBool", "Offset Text")
    on = not dim.FWOffsetText

    def body():
        d = step if on else -step
        dim.X, dim.Y = float(dim.X) + d, float(dim.Y) + d
        dim.FWOffsetText = on
    _transaction(dim.Document, "Offset Text", body)
    return on


def is_offset(dim):
    return bool(getattr(dim, "FWOffsetText", False))


def has_parentheses(dim):
    f = dim.FormatSpec or ""
    return f.startswith("(") and f.endswith(")")


def toggle_parentheses(dim):
    on = not has_parentheses(dim)

    def body():
        f = dim.FormatSpec or "%.2f"
        dim.FormatSpec = "(%s)" % f if on else f[1:-1]
    _transaction(dim.Document, "Show Parentheses", body)
    return on


def is_inspection(dim):
    return bool(getattr(dim, "FWInspection", False))


def toggle_inspection(dim):
    """Show as Inspection: the value in a frame (TechDraw's frame for exact values)."""
    _prop(dim, "FWInspection", "App::PropertyBool", "Show as Inspection")
    on = not dim.FWInspection

    def body():
        dim.FWInspection = on
        try:
            dim.TheoreticalExact = on
        except Exception as _fw_err:
            _fw_log("drawextras.py:967", _fw_err)
    _transaction(dim.Document, "Show as Inspection", body)
    return on


def set_dim_type(dim, kind, name):
    def body():
        dim.Type = kind
    _transaction(dim.Document, name, body)


def reattach(dim):
    _select_only(dim)
    Gui.runCommand("TechDraw_DimensionRepair", 0)


def format_painter():
    """Format Painter: the first picked dimension or note's look goes onto the other picked ones."""
    picked = [s.Object for s in Gui.Selection.getSelectionEx("", 0)]
    dims = [o for o in picked if o.isDerivedFrom("TechDraw::DrawViewDimension")]
    if len(dims) < 2:
        App.Console.PrintMessage("Format Painter: pick the dimension to copy from, then the ones to paint.\n")
        return False
    src = dims[0]

    def body():
        for d in dims[1:]:
            d.FormatSpec = src.FormatSpec
            for p in ("Fontsize", "Arrowsize", "Font", "Color", "LineWidth"):
                try:
                    setattr(d.ViewObject, p, getattr(src.ViewObject, p))
                except Exception as _fw_err:
                    _fw_log("drawextras.py:999", _fw_err)
    _transaction(src.Document, "Format Painter", body)
    return True


# --------------------------------------------------------------------------- notes
def edit_text(note):
    """Edit Text: the note's text, kept on the note and drawn again."""
    from . import drawannot as DA
    old = getattr(note, "SWNoteText", "") or note.Label
    text, ok = QtWidgets.QInputDialog.getMultiLineText(_mw(), "Edit Text", "Text:", old)
    if not ok:
        return False
    return set_note_text(note, text, "Edit Text")


def _note_svg(note, text):
    from . import drawannot as DA
    at = (float(note.X), float(note.Y))
    body, reach = DA.note_svg(text, at)
    R = max(5.0, reach + 5.0)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
            % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))


def set_note_text(note, text, step="Edit Text"):
    """The note's text, kept on the note and drawn again."""
    try:
        svg = _note_svg(note, text)
    except Exception:
        return False

    def work():
        note.Symbol = svg
        _prop(note, "SWNoteText", doc="note text")
        note.SWNoteText = text
    _transaction(note.Document, step, work)
    return True


def picked_notes():
    import FreeCADGui as Gui
    return [o for o in Gui.Selection.getSelection()
            if getattr(o, "SWAnnotation", "") == "Note" or hasattr(o, "SWNoteText")]


def toggle_notes_upper_case(notes=None):
    ""

    notes = picked_notes() if notes is None else notes
    done = 0
    for n in notes:
        text = getattr(n, "SWNoteText", "") or n.Label
        typed = getattr(n, "SWNoteTyped", "")
        if text == text.upper() and typed and typed.upper() == text:
            new = typed
        else:
            _prop(n, "SWNoteTyped", doc="the note's text as typed (Toggle Notes Upper Case)")
            n.SWNoteTyped = text
            new = text.upper()
        done += bool(set_note_text(n, new, "Toggle Notes Upper Case"))
    return done


def manual_view_label(note):
    """Manual View Label Text: the label stops following the view's name."""
    _prop(note, "FWManualLabel", "App::PropertyBool", "Manual view label text")
    note.FWManualLabel = not note.FWManualLabel
    return note.FWManualLabel


# --------------------------------------------------------------------------- blocks, library, tangent ends
import os


def _user_dir(*parts):
    d = os.path.join(App.getUserAppDataDir(), "FreeWorks", *parts)
    os.makedirs(d, exist_ok=True)
    return d


def _safe(name):
    return "".join(c for c in name if c.isalnum() or c in " -_").strip() or "Block"


def make_block(a, name=None):
    ""

    if name is None:
        name, ok = QtWidgets.QInputDialog.getText(_mw(), "Make Block", "Block name:", text=_safe(a.Label))
        if not ok or not name.strip():
            return None
    name = _safe(name)
    path = os.path.join(_user_dir("blocks"), name + ".svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(a.Symbol)

    def body():
        _prop(a, "FWBlock", doc="the block this annotation is an instance of")
        a.FWBlock = name
        _prop(a, "FWBlockFile", doc="the block's file")
        a.FWBlockFile = path
    _transaction(a.Document, "Make Block", body)
    return path


def add_to_library(a, name=None, folder="annotations"):
    ""

    if name is None:
        name, ok = QtWidgets.QInputDialog.getText(_mw(), "Add to Library", "File name (Design Library\\%s):" % folder,
                                                  text=_safe(a.Label))
        if not ok or not name.strip():
            return None
    path = os.path.join(_user_dir("library", folder), _safe(name) + ".svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(a.Symbol)
    return path


def tangent_ends_hidden(v):
    return bool(getattr(v, "FWTangentHideEnds", False))


def toggle_tangent_hide_ends(v):
    ""

    _prop(v, "FWTangentHideEnds", "App::PropertyBool", "Tangent Edge Hide Ends")
    on = not v.FWTangentHideEnds

    def body():
        v.FWTangentHideEnds = on
        try:
            if on:
                v.SmoothVisible = True
                v.ViewObject.IsoWidth = 0.09
            elif getattr(v, "SWTangentEdges", "") != "With Font":
                v.ViewObject.IsoWidth = 0.18
        except Exception as _fw_err:
            _fw_log("drawextras.py:1138", _fw_err)
    _transaction(v.Document, "Hide Ends", body)
    return on
