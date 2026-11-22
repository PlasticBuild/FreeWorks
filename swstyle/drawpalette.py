
"""View Palette: a panel of the open part's standard views; pick one (click, or drag it) and drop it on the sheet.
Alternate Position: the assembly in another position, drawn with phantom lines over the view."""

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
from PySide import QtCore, QtGui, QtWidgets

from . import drawings as D
from . import drawviews as DV

V = App.Vector
FLAT = "Flat pattern"
CUT_ITEM = "cutlist:"
PALETTE_VIEWS = ("Front", "Back", "Top", "Bottom", "Right", "Left", "Isometric", "Trimetric", "Dimetric")
MIME = "application/x-freeworks-view"
NAMED = "named:"
EXPLODED = "exploded:"
ASK = {}                 # checks: ASK["browse"] = a file path answers the Browse box
PHANTOM = 5           # TechDraw line style: dash-dot-dot


# --------------------------------------------------------------------------- View Palette

def _fw_xs(v):
    """v's XSource as its model(s) (drawviews.xsource: an assembly view's model parts read back as the model)."""
    from . import drawviews as DV
    return DV.xsource(v)

class ViewPalette(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SWViewPalette")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        row = QtWidgets.QHBoxLayout()
        self.source = QtWidgets.QComboBox(self)
        self.source.setObjectName("SWViewPaletteSource")
        row.addWidget(self.source, 1)
        self.refresh_button = QtWidgets.QToolButton(self)
        self.refresh_button.setObjectName("SWViewPaletteRefresh")
        self.refresh_button.setToolTip("Refresh")
        self.refresh_button.setIcon(QtGui.QIcon(":/icons/view-refresh.svg"))
        # panesweep-1121: clicked(bool) handed refresh() False as the part to prefer (AttributeError on every click)
        self.refresh_button.clicked.connect(lambda _checked=False: self.refresh())
        row.addWidget(self.refresh_button)
        self.browse_button = QtWidgets.QToolButton(self)
        self.browse_button.setObjectName("SWViewPaletteBrowse")
        self.browse_button.setText("...")
        self.browse_button.setToolTip("Browse: a part or assembly for the View Palette")
        self.browse_button.clicked.connect(self.browse)
        row.addWidget(self.browse_button)
        lay.addLayout(row)
        self.auto = QtWidgets.QCheckBox("Auto-start projected view", self)
        self.auto.setObjectName("SWViewPaletteAuto")
        self.auto.setChecked(True)
        lay.addWidget(self.auto)
        self.list = _PaletteList(self)
        lay.addWidget(self.list, 1)

        box = QtWidgets.QGroupBox("Options", self)
        box.setObjectName("SWViewPaletteOptions")
        bl = QtWidgets.QVBoxLayout(box)
        self.imp = QtWidgets.QCheckBox("Import Annotations", box)
        self.imp.setObjectName("SWViewPaletteImport")
        self.imp_design = QtWidgets.QCheckBox("Design annotations", box)
        self.imp_design.setObjectName("SWViewPaletteImportDesign")
        self.imp_design.setChecked(True)
        self.imp_dimxpert = QtWidgets.QCheckBox("DimXpert annotations", box)
        self.imp_dimxpert.setObjectName("SWViewPaletteImportDimXpert")
        self.imp_dimxpert.setChecked(True)
        self.imp_hidden = QtWidgets.QCheckBox("Include items from hidden features", box)
        self.imp_hidden.setObjectName("SWViewPaletteImportHidden")
        bl.addWidget(self.imp)
        for w in (self.imp_design, self.imp_dimxpert, self.imp_hidden):
            # live, never greyed: turning a kind on turns Import Annotations on
            w.clicked.connect(lambda *_, w=w: w.isChecked() and not self.imp.isChecked() and self.imp.setChecked(True))
            bl.addWidget(w)
        lay.addWidget(box)
        self.hint = QtWidgets.QLabel("Click a view, then click the sheet (or drag it onto the sheet).", self)
        self.hint.setObjectName("SWViewPaletteHint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.list.itemClicked.connect(self.arm)
        self.source.currentIndexChanged.connect(self.fill)
        self.armed = None
        self.clicks = None
        self.refresh()

    def browse(self, *_):
        ""
        path = ASK.pop("browse", None)
        if path is None:
            path, _f = QtWidgets.QFileDialog.getOpenFileName(Gui.getMainWindow(), "Open", "",
                                                             "Part and Assembly (*.FCStd *.fcstd);;All Files (*)")
        if not path:
            return None
        import os
        doc = None
        for d in App.listDocuments().values():
            try:
                if d.FileName and os.path.normcase(os.path.abspath(d.FileName)) == os.path.normcase(os.path.abspath(path)):
                    doc = d
                    break
            except Exception as _fw_err:
                _fw_log("drawpalette.py:117", _fw_err)
        if doc is None:
            active = App.ActiveDocument
            try:
                doc = App.openDocument(path)
            except Exception as error:
                App.Console.PrintError("FreeCAD: View Palette: %s: %s\n" % (path, error))
                return None
            try:                                 # the drawing stays the window in front
                pages = [o for o in active.Objects if o.TypeId == "TechDraw::DrawPage"] if active else []
                if pages:
                    App.setActiveDocument(active.Name)
                    Gui.ActiveDocument = Gui.getDocument(active.Name)
                    pages[0].ViewObject.doubleClicked()
            except Exception as _fw_err:
                _fw_log("drawpalette.py:132", _fw_err)
        self.refresh(prefer=doc)
        if self.source.findData(doc.Name) < 0:      # D.source_documents may skip it: list it anyway
            self.source.addItem(doc.Label, doc.Name)
            self.source.setCurrentIndex(self.source.count() - 1)
        return doc

    def imports(self):
        """None, or (Design annotations, DimXpert annotations, Include items from hidden features)."""
        if not self.imp.isChecked():
            return None
        return self.imp_design.isChecked(), self.imp_dimxpert.isChecked(), self.imp_hidden.isChecked()

    def refresh(self, prefer=None):
        ""

        cur = prefer.Name if prefer is not None else self.source.currentData()
        populate = prefer is not None or bool(_drawing_option("Automatically populate View Palette with views", True))
        if prefer is None and populate:
            want = preferred_source()
            if want is not None:
                cur = want.Name
        self.source.blockSignals(True)
        self.source.clear()
        for doc in D.source_documents():
            self.source.addItem(doc.Label, doc.Name)
        n = self.source.findData(cur)
        if n >= 0:
            self.source.setCurrentIndex(n)
        elif not populate:
            self.source.setCurrentIndex(-1)     # extapps83: empty until a model is picked (Populate off)
        self.source.blockSignals(False)
        self.fill()

    def fill(self, *args):
        self.list.clear()
        doc = self.document()
        if doc is None:
            return
        shapes = D.model_shapes(doc)
        for name in PALETTE_VIEWS:
            it = QtWidgets.QListWidgetItem(preview_icon(shapes, name, dx=orientation(doc, name)), "*" + name)
            it.setData(QtCore.Qt.UserRole, name)
            it.setToolTip("*%s of %s: click, then click the sheet, or drag it onto the sheet" % (name, doc.Label))
            self.list.addItem(it)
        for vname, cam in named_views(doc):
            it = QtWidgets.QListWidgetItem(preview_icon(shapes, vname, dx=camera_axes(cam)), vname)
            it.setData(QtCore.Qt.UserRole, NAMED + vname)
            it.setToolTip("%s of %s: click, then click the sheet, or drag it onto the sheet" % (vname, doc.Label))
            self.list.addItem(it)
        for ename, elabel, eshapes in exploded_entries(doc):
            it = QtWidgets.QListWidgetItem(preview_icon(eshapes or shapes, "Isometric", dx=orientation(doc, "Isometric")),
                                           elabel)
            it.setData(QtCore.Qt.UserRole, EXPLODED + ename)
            it.setToolTip("%s of %s: click, then click the sheet, or drag it onto the sheet" % (elabel, doc.Label))
            self.list.addItem(it)
        try:
            from . import smflatview
            sm = smflatview.available(doc)
        except Exception:
            sm = False
        if sm:
            try:
                fv = smflatview.flat_view(doc, create=False)
                icon = preview_icon([fv], "Top") if fv is not None else QtGui.QIcon()
            except Exception:
                icon = QtGui.QIcon()
            it = QtWidgets.QListWidgetItem(icon, "(A) Flat pattern")
            it.setData(QtCore.Qt.UserRole, FLAT)
            it.setToolTip("(A) Flat pattern of %s: click, then click the sheet, or drag it onto the sheet" % doc.Label)
            self.list.addItem(it)
        for item in cut_list_items(doc):
            try:
                icon = preview_icon(list(item.Bodies[:1]), "Front")
            except Exception:
                icon = QtGui.QIcon()
            it = QtWidgets.QListWidgetItem(icon, item.Label)
            it.setData(QtCore.Qt.UserRole, CUT_ITEM + item.Name)
            it.setToolTip("%s of %s: click, then click the sheet, or drag it onto the sheet" % (item.Label, doc.Label))
            self.list.addItem(it)

    def document(self):
        name = self.source.currentData()
        try:
            return App.getDocument(name) if name else None
        except Exception as _fw_err:
            _fw_log("drawpalette.py:210", _fw_err)
            return None

    def arm(self, item):
        page = D.active_page()
        if page is None:
            self.hint.setText("Open a drawing sheet first.")
            return
        self.disarm()
        self.armed = (page, item.data(QtCore.Qt.UserRole))
        self.clicks = D.SheetClicks(page, self)
        self.hint.setText("Click the sheet to place the %s view." % item.text().lstrip("*"))

    def disarm(self):
        if self.clicks is not None:
            self.clicks.stop()
        self.clicks = None
        self.armed = None

    def sheet_move(self, p):
        pass

    def sheet_click(self, p):
        if self.armed is None:
            return False
        page, name = self.armed
        self.disarm()
        place(page, self.document(), name, p, self.auto.isChecked(), imports=self.imports())
        self.hint.setText("Click a view, then click the sheet (or drag it onto the sheet).")
        return True


LAST_SOURCE = []


def note_source(doc):
    """Remembers the part or assembly window used last (the View Palette's default model)."""
    try:
        if doc is not None and not any(o.TypeId == "TechDraw::DrawPage" for o in doc.Objects) and D.model_shapes(doc):
            LAST_SOURCE[:] = [doc.Name]
    except Exception as _fw_err:
        _fw_log("drawpalette.py:249", _fw_err)


def _drawing_option(text, default):
    """extapps83: Tools > Options > System Options > Drawings: that row's kept value."""
    try:
        from . import optionspages
        return optionspages.stored("Drawings", text, default)
    except Exception:
        return default


def preferred_source():
    """The model the active drawing's views show, else the last part window used."""
    page = D.active_page()
    if page is not None:
        for v in D.views_of(page) + [o for p in page.Views if p.TypeId == "TechDraw::DrawProjGroup" for o in p.Views]:
            for o in _fw_xs(v) + list(getattr(v, "Source", []) or []):
                if o.Document is not page.Document:
                    return o.Document
    if LAST_SOURCE:
        try:
            return App.getDocument(LAST_SOURCE[0])
        except Exception as _fw_err:
            _fw_log("drawpalette.py:264", _fw_err)
    return None


def camera_axes(camera):
    """(direction to the viewer, view X) of an Inventor camera text (its orientation axis + angle)."""
    import re
    m = re.search(r"orientation\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", camera or "")
    if not m:
        return None
    ax = V(*[float(m.group(i)) for i in (1, 2, 3)])
    if ax.Length < 1e-12:
        r = App.Rotation()
    else:
        r = App.Rotation(ax, math.degrees(float(m.group(4))))
    return r.multVec(V(0, 0, 1)), r.multVec(V(1, 0, 0))


def named_views(doc):
    """[(name, camera)] the model keeps (View Orientation > New View), [] without any."""
    try:
        from . import namedviews
        return [v for v in namedviews.views(doc) if len(v) >= 2 and camera_axes(v[1]) is not None]
    except Exception as _fw_err:
        _fw_log("drawpalette.py:290", _fw_err)
        return []


def exploded_entries(doc):
    """[(exploded view name, palette label, [shapes as it shows them])] of the assembly in doc: one
    "*Isometric Exploded" entry for each exploded view (named after it when there are several)."""
    try:
        from . import asmdrawing as AD
        asm = AD.assembly_in(doc)
        views = AD.exploded_views(asm) if asm is not None else []
        order = {o.Name: i for i, o in enumerate(doc.Objects)}
        views = sorted(views, key=lambda o: order.get(o.Name, 0))      # in the order they were made
    except Exception as _fw_err:
        _fw_log("drawpalette.py:exploded", _fw_err)
        return []
    out = []
    for ev in views:
        label = "*Isometric Exploded" if len(views) == 1 else "*Isometric Exploded (%s)" % ev.Label
        shapes = []
        try:
            got = AD.component_shapes(asm, exploded=ev.Name, switch=False)
            if got:
                import types
                shapes = [types.SimpleNamespace(Shape=sh) for _c, sh in got[0]]
        except Exception as _fw_err:
            _fw_log("drawpalette.py:exploded shapes", _fw_err)
        out.append((ev.Name, label, shapes))
    return out


def orientation(doc, name):
    ""

    if name.startswith(NAMED):
        for n, cam in named_views(doc):
            if n == name[len(NAMED):]:
                return camera_axes(cam)
    try:
        from . import namedviews
        if doc is not None and namedviews.turned(doc) and name in namedviews.STANDARD:
            r = namedviews.standard_rotation(name, doc)
            return r.multVec(V(0, 0, 1)), r.multVec(V(1, 0, 0))
    except Exception as _fw_err:
        _fw_log("drawpalette.py:304", _fw_err)
    return D.ORIENTATIONS[name]


def _edges2d(shapes, name, dx=None):
    d, x = dx or D.ORIENTATIONS[name]
    d, x = D._unit(d), D._unit(x)
    y = d.cross(x)
    lines = []
    for o in shapes:
        try:
            shape = o.Shape
        except Exception:
            continue
        for e in shape.Edges[:4000]:
            try:
                pts = e.discretize(Deflection=max(shape.BoundBox.DiagonalLength / 200.0, 1e-3))
            except Exception:
                continue
            lines.append([(p.dot(x), p.dot(y)) for p in pts])
    return lines


def preview_icon(shapes, name, size=64, dx=None):
    ""
    from . import hidpi as _hidpi   # hidpi-1119: drawn at the screen's scale
    pix = _hidpi.canvas(size, size)
    pix.fill(QtCore.Qt.white)
    try:
        lines = _edges2d(shapes, name, dx)
        xs = [p[0] for l in lines for p in l]
        ys = [p[1] for l in lines for p in l]
        if xs:
            w, h = max(xs) - min(xs), max(ys) - min(ys)
            k = (size - 10) / max(w, h, 1e-9)
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            painter = QtGui.QPainter(pix)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1.0))
            for l in lines:
                poly = QtGui.QPolygonF([QtCore.QPointF(size / 2 + (p[0] - cx) * k, size / 2 - (p[1] - cy) * k) for p in l])
                painter.drawPolyline(poly)
            painter.end()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: palette preview %s: %s\n" % (name, error))
    return QtGui.QIcon(pix)


class _PaletteList(QtWidgets.QListWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SWViewPaletteList")
        self.setViewMode(QtWidgets.QListView.IconMode)
        self.setIconSize(QtCore.QSize(64, 64))
        self.setResizeMode(QtWidgets.QListView.Adjust)
        self.setMovement(QtWidgets.QListView.Static)
        self.setDragEnabled(True)
        self.setSpacing(4)

    def startDrag(self, actions):
        it = self.currentItem()
        if it is None:
            return
        page = D.active_page()
        if page is not None:
            DropTarget.on(page)
        md = QtCore.QMimeData()
        md.setData(MIME, it.data(QtCore.Qt.UserRole).encode())
        drag = QtGui.QDrag(self)
        drag.setMimeData(md)
        drag.setPixmap(it.icon().pixmap(64, 64))
        drag.exec_(QtCore.Qt.CopyAction)


class DropTarget(QtCore.QObject):
    """Takes a dropped palette view on a sheet."""
    _all = {}

    @classmethod
    def on(cls, page):
        gv = D.page_view(page)
        if gv is None:
            return None
        key = id(gv)
        if key not in cls._all:
            t = cls(page, gv)
            cls._all[key] = t
            gv.destroyed.connect(lambda *a, k=key: cls._all.pop(k, None))
        return cls._all[key]

    def __init__(self, page, gv):
        super().__init__()
        self.page = page
        self.gv = gv
        gv.setAcceptDrops(True)
        gv.viewport().setAcceptDrops(True)
        gv.viewport().installEventFilter(self)
        gv.installEventFilter(self)

    def eventFilter(self, obj, event):
        try:
            if not isinstance(event, QtCore.QEvent):
                return False
            t = event.type()
            if t in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove) and event.mimeData().hasFormat(MIME):
                event.acceptProposedAction()
                return True
            if t == QtCore.QEvent.Drop and event.mimeData().hasFormat(MIME):
                name = bytes(event.mimeData().data(MIME)).decode()
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if obj is self.gv:
                    pos = self.gv.viewport().mapFrom(self.gv, pos)
                p = D.to_sheet(self.gv.mapToScene(pos))
                pal = palette()
                doc = pal.document() if pal is not None else None
                auto = pal.auto.isChecked() if pal is not None else False
                imports = pal.imports() if pal is not None and hasattr(pal, "imports") else None
                event.acceptProposedAction()
                # placed once the drop is over (a part save box inside the drop would hang the drag on Windows)
                QtCore.QTimer.singleShot(0, lambda: place(self.page, doc, name, p, auto, imports=imports))
                return True
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: View Palette drop: %s\n" % error)
        return False


def place(page, doc, name, at, auto_projected=True, imports=None):
    """A palette view of doc on page at sheet point at; with auto_projected, Projected View starts from it;
    imports (design, dimxpert, hidden): the model's annotations brought into the view, as the palette's Import
    Annotations."""
    if doc is None:
        return None
    drawing = page.Document
    if not D.saved_source(doc, drawing):
        return None
    if name == FLAT:
        from . import smflatview
        fv = smflatview.flat_view(doc)
        if fv is None:
            return None
        v = D.new_view(page, [fv], D._unit(fv.Normal), D._unit(fv.XAxis), at)
        v.Label = "Flat pattern"
        v.addProperty("App::PropertyBool", "SWFlatPattern", "FreeCAD", "A flat pattern view")
        v.SWFlatPattern = True
        drawing.recompute()
        from . import drawtables
        drawtables.flat_pattern_placed(page, v)
        return v                                 # no Projected View from a flat pattern
    if name.startswith(CUT_ITEM):
        return cut_list_item_view(page, doc, doc.getObject(name[len(CUT_ITEM):]), at)
    exploded = name[len(EXPLODED):] if name.startswith(EXPLODED) else ""
    if exploded:
        name = "Isometric"
    d, x = orientation(doc, name)
    v = D.new_view(page, D.model_shapes(doc), D._unit(d), D._unit(x), at)
    try:
        D.sheet_defaults(page)
    except Exception as _fw_err:
        _fw_log("drawpalette.py:458", _fw_err)
    v.addProperty("App::PropertyString", "SWOrientation", "FreeCAD", "named view")
    v.SWOrientation = name[len(NAMED):] if name.startswith(NAMED) else name
    if name.startswith(NAMED):
        v.Label = name[len(NAMED):]
    if exploded:                        # the view shown exploded (Drawing View PM: Show in exploded state)
        try:
            from . import asmdrawing as AD
            AD.apply_view(v, exploded=exploded)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: exploded view: %s\n" % error)
    drawing.recompute()
    if imports and (imports[0] or imports[1]):
        try:
            from . import drawannot as DA
            for prop, on in (("SWImportAnnotations", True), ("SWImportDesign", imports[0]),
                             ("SWImportDimXpert", imports[1]), ("SWImportHidden", imports[2])):
                if prop not in v.PropertiesList:
                    v.addProperty("App::PropertyBool", prop, "FreeCAD", "Drawing View option")
                setattr(v, prop, bool(on))
            DA.model_items(page, [v], marked=bool(imports[0]), hidden=bool(imports[2]))
            drawing.recompute()
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: View Palette Import Annotations: %s\n" % error)
    if auto_projected:
        try:
            panel = D.ProjectedViewPanel(page, v)
            panel.keep_placing = True
            D._show(panel)
        except Exception as error:
            App.Console.PrintWarning("FreeCAD: Projected View: %s\n" % error)
    return v


def cut_list_items(doc):
    """The weldment's cut list items that have a body (wecutlist), else []."""
    try:
        from . import wecutlist
        box = wecutlist.folder(doc)
        if box is None:
            return []
        return [i for i in box.Items if list(getattr(i, "Bodies", []) or []) and not getattr(i, "Excluded", False)]
    except Exception as _fw_err:
        _fw_log("drawpalette.py:498", _fw_err)
        return []


def cut_list_item_view(page, doc, item, at):
    ""

    if item is None or not list(getattr(item, "Bodies", []) or []):
        return None
    body = item.Bodies[0]
    bb = body.Shape.BoundBox
    axes = sorted(((bb.XLength, V(1, 0, 0)), (bb.YLength, V(0, 1, 0)), (bb.ZLength, V(0, 0, 1))),
                  key=lambda t: -t[0])
    x = axes[0][1]
    d = V(0, 0, 1) if x != V(0, 0, 1) else axes[2][1]      # a frame lying flat: seen from the top
    v = D.new_view(page, [body], D._unit(d), D._unit(x), at)
    v.Label = item.Label
    v.addProperty("App::PropertyString", "SWCutListItem", "FreeCAD", "the cut list item the view shows")
    v.SWCutListItem = item.Name
    page.Document.recompute()
    return v


_PALETTE = []


def palette():
    return _PALETTE[0] if _PALETTE else None


def show_palette(source=None):
    ""

    if source is not None:
        note_source(source)
    try:
        from . import taskpane
        w = taskpane.open_tab(3)
        if w is not None:
            if isinstance(w, QtWidgets.QWidget) and not isinstance(w, ViewPalette) and \
                    w.objectName() not in ("SWViewPalette", "SWTaskPaneViewPalette") and \
                    not w.findChildren(ViewPalette):
                # the Task Pane tab came up without the palette in it (PC batch 224): put one there
                pal = ViewPalette(w)
                lay = w.layout() or QtWidgets.QVBoxLayout(w)
                lay.addWidget(pal)
                pal.show()
                _PALETTE[:] = [pal]
            if _PALETTE:
                _PALETTE[0].refresh(source)
            return w
    except Exception as _fw_err:
        _fw_log("drawpalette.py:546", _fw_err)
    mw = Gui.getMainWindow()
    dock = mw.findChild(QtWidgets.QDockWidget, "SWViewPaletteDock")
    if dock is None:
        dock = QtWidgets.QDockWidget("View Palette", mw)
        dock.setObjectName("SWViewPaletteDock")
        pal = ViewPalette(dock)
        dock.setWidget(pal)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        _PALETTE[:] = [pal]
        pal.refresh(source)
    else:
        _PALETTE[0].refresh(source)
    dock.show()
    dock.raise_()
    return dock


# --------------------------------------------------------------------------- Alternate Position
def components(view):
    """The parts a view of an assembly shows: (object, global placement)."""
    out = []
    for src in DV.source_shapes(view):
        if src.TypeId == "Assembly::AssemblyObject":
            for o in src.OutListRecursive:
                if o.Document is not src.Document:
                    continue                # a component's part in its own file (the Link stands for it)
                if hasattr(o, "Shape") and not o.Shape.isNull() and o.Shape.Solids and \
                        o.TypeId not in ("Assembly::AssemblyObject",) and not o.TypeId.startswith("Assembly::Joint"):
                    if not any(i in src.OutListRecursive and hasattr(i, "Shape") and i.TypeId == "PartDesign::Body"
                               for i in o.InList):
                        out.append(o)
        elif hasattr(src, "Shape"):
            out.append(src)
    seen, uniq = set(), []
    for o in out:
        if o.Name not in seen:
            seen.add(o.Name)
            uniq.append(o)
    return uniq


def alternate_position(page, view, moves, name=None):
    """A phantom-line view of view's model with components moved: moves = {object: Placement (extra, global)}.
    The moved copies live in the model's file (saved), the view sits over view, aligned to its model."""
    parts = components(view)
    if not parts:
        return None
    doc = parts[0].Document
    n = 1 + len([o for o in page.Document.Objects if getattr(o, "SWAlternateOf", "")])
    name = name or "Alternate Position%d" % n
    grp = doc.addObject("App::DocumentObjectGroup", "AltPosition")
    grp.Label = name
    shapes = []
    for o in parts:
        sh = o.Shape.copy()
        if o in moves:
            sh.transformShape(moves[o].toMatrix())
        f = doc.addObject("Part::Feature", "AltPos_" + o.Name)
        f.Shape = sh
        f.Label = "%s (%s)" % (o.Label, name)
        f.Visibility = False
        grp.addObject(f)
        shapes.append(f)
    grp.Visibility = False
    grp.addProperty("App::PropertyBool", "SWAltPosition", "FreeCAD", "an alternate position configuration")
    grp.SWAltPosition = True
    doc.recompute()
    try:
        doc.save()
    except Exception as error:
        App.Console.PrintWarning("FreeCAD: Alternate Position: %s not saved: %s\n" % (doc.Label, error))
    v = _alt_view(page, view, shapes, name)
    if v is not None:
        v.addProperty("App::PropertyStringList", "SWAltMoves", "FreeCAD", "the components in another place")
        v.SWAltMoves = [o.Label for o in parts if o in moves]
    return v


def solved_moves(view, moves):
    ""


    if not moves:
        return moves
    asm = next((s for s in DV.source_shapes(view) if s.TypeId == "Assembly::AssemblyObject"), None)
    if asm is None:
        return moves
    try:
        from . import asmcore as ac
    except Exception:
        return moves
    parts = [o for o in components(view) if hasattr(o, "Placement")]
    if not all(hasattr(o, "Placement") for o in moves):
        return moves
    keep = {o.Name: App.Placement(o.Placement) for o in parts}
    doc = asm.Document
    out = moves
    try:
        for o, m in moves.items():
            o.Placement = m.multiply(o.Placement)
        with ac.temp_ground(asm, list(moves)):
            ok = ac.solve(asm)
        doc.recompute()
        if ok:
            out = {}
            for o in parts:
                new = App.Placement(o.Placement)
                if not new.isSame(keep[o.Name], 1e-7):
                    out[o] = new.multiply(keep[o.Name].inverse())
            for o, m in moves.items():
                out.setdefault(o, m)
    except Exception as error:
        App.Console.PrintLog("FreeCAD: Alternate Position: the mates were not solved: %s\n" % error)
        out = moves
    finally:
        for o in parts:
            try:
                o.Placement = keep[o.Name]
            except Exception as _fw_err:
                _fw_log("drawpalette.py:666", _fw_err)
        try:
            doc.recompute()
        except Exception as _fw_err:
            _fw_log("drawpalette.py:670", _fw_err)
    return out


def alt_configurations(view):
    """The alternate position configurations already in the view's model (Existing configuration)."""
    parts = components(view)
    if not parts:
        return []
    return [o for o in parts[0].Document.Objects if getattr(o, "SWAltPosition", False)]


def existing_position(page, view, grp):
    """Alternate Position from an existing configuration: its moved copies shown again over view."""
    shapes = [o for o in grp.Group if hasattr(o, "Shape")]
    return _alt_view(page, view, shapes, grp.Label) if shapes else None


def _alt_view(page, view, shapes, name):
    d, x, y = D.view_frame(view)
    c0 = DV.model_centre(view)
    box = None
    for f in shapes:
        b = f.Shape.BoundBox
        if box is None:
            box = App.BoundBox(b)
        else:
            box.add(b)
    off = box.Center - c0
    k = DV.view_scale(view)
    x0, y0 = D.view_position(view)
    at = (x0 + off.dot(x) * k, y0 + off.dot(y) * k)
    v = D.new_view(page, shapes, view.Direction, view.XDirection, at, k, label=name)
    v.LockPosition = True
    v.addProperty("App::PropertyString", "SWAlternateOf", "FreeCAD", "the view this is the alternate of")
    v.SWAlternateOf = view.Name
    page.Document.recompute()
    phantom_later(v)
    return v


def phantom_later(view, tries=40):
    """TechDraw finds a view's lines in the background: style them once they are there."""
    def step(n=tries):
        try:
            view.getEdgeByIndex(0)
            ready = True
        except Exception:
            ready = False
        if ready:
            phantom(view)
        elif n > 0:
            QtCore.QTimer.singleShot(250, lambda: step(n - 1))
    step()


def phantom(view):
    ""


    from . import drawannot as DA
    page = next((o for o in view.InList if o.TypeId == "TechDraw::DrawPage"), None)
    if page is None:
        return 0
    paths = []
    for e in view.getVisibleEdges():
        try:
            pts = e.discretize(Deflection=0.02)
        except Exception:
            continue
        paths.append("M" + " L".join("%g %g" % (q.x, -q.y) for q in pts))
    bb = None
    for e in view.getVisibleEdges():
        b = e.BoundBox
        bb = App.BoundBox(b) if bb is None else (bb.add(b) or bb)
    x, y = D.view_position(view)
    box = crop_box(view)
    if box is not None:                  # the base view is cropped: its alternate position is cropped with it
        paths = []
        for e in view.getVisibleEdges():
            try:
                pts = [(q.x, q.y) for q in e.discretize(Deflection=0.02)]
            except Exception:
                continue
            for run in clip_polyline(pts, (box[0] - x, box[1] - y, box[2] - x, box[3] - y)):
                paths.append("M" + " L".join("%g %g" % (u, -v) for u, v in run))
    if not paths:
        return 0
    body = ('<path d="%s" fill="none" stroke="#000" stroke-width="0.25" stroke-dasharray="6 1.2 1 1.2 1 1.2"/>'
            % " ".join(paths))
    reach = max(abs(bb.XMin), abs(bb.XMax), abs(bb.YMin), abs(bb.YMax)) if bb else 5
    old = [o for o in page.Views if getattr(o, "SWPhantomOf", "") == view.Name]
    if old:
        s = old[0]
        s.Symbol = _svg(body, reach)
        s.X, s.Y = x, y
    else:
        s = DA.svg_symbol(page, "AltPositionLines", body, reach, (x, y), view.Label + " lines", "AlternatePosition")
        s.addProperty("App::PropertyString", "SWPhantomOf", "FreeCAD", "the alternate position view")
        s.SWPhantomOf = view.Name
    if "SWPhantomEdges" not in view.PropertiesList:
        view.addProperty("App::PropertyInteger", "SWPhantomEdges", "FreeCAD", "edges drawn phantom")
    view.SWPhantomEdges = len(paths)
    try:
        view.ViewObject.Visibility = False
    except Exception as _fw_err:
        _fw_log("drawpalette.py:776", _fw_err)
    page.Document.recompute()
    return len(paths)


def crop_box(view):
    ""

    doc = view.Document
    base = doc.getObject(getattr(view, "SWAlternateOf", "") or "")
    if base is None:
        return None
    for o in base.InList:
        if o.TypeId != "TechDraw::DrawViewClip" or base not in list(o.Views):
            continue
        if o.Label.endswith(" Crop") or "SWCropProfile" in o.PropertiesList:
            cx, cy = float(o.X), float(o.Y)
            w, h = float(o.Width) / 2, float(o.Height) / 2
            return cx - w, cy - h, cx + w, cy + h
    return None


def clip_polyline(pts, box):
    """The runs of polyline pts inside box (x0, y0, x1, y1), each a list of points (Liang-Barsky per segment)."""
    x0, y0, x1, y1 = box
    runs, cur = [], []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        t0, t1 = 0.0, 1.0
        ok = True
        for p, q in ((-dx, ax - x0), (dx, x1 - ax), (-dy, ay - y0), (dy, y1 - ay)):
            if abs(p) < 1e-12:
                if q < 0:
                    ok = False
                    break
                continue
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                ok = False
                break
        if not ok:
            if len(cur) > 1:
                runs.append(cur)
            cur = []
            continue
        a = (ax + t0 * dx, ay + t0 * dy)
        b = (ax + t1 * dx, ay + t1 * dy)
        if cur and (abs(cur[-1][0] - a[0]) > 1e-9 or abs(cur[-1][1] - a[1]) > 1e-9):
            if len(cur) > 1:
                runs.append(cur)
            cur = []
        if not cur:
            cur = [a]
        cur.append(b)
        if t1 < 1.0:
            runs.append(cur)
            cur = []
    if len(cur) > 1:
        runs.append(cur)
    return runs


def alternates_of(view):
    doc = view.Document
    return [o for o in doc.Objects if getattr(o, "SWAlternateOf", "") == view.Name]


def _hook_crop():
    """Crop View and Remove Crop redraw the view's alternate positions cropped (or whole again)."""
    if getattr(DV.make_crop, "_fw_alt", False):
        return
    make, remove = DV.make_crop, DV.remove_crop

    def make_crop(page, base, a, b):
        clip = make(page, base, a, b)
        for v in alternates_of(base):
            phantom(v)
        return clip

    def remove_crop(clip):
        bases = list(clip.Views)
        remove(clip)
        for base in bases:
            for v in alternates_of(base):
                phantom(v)
    make_crop._fw_alt = remove_crop._fw_alt = True
    DV.make_crop, DV.remove_crop = make_crop, remove_crop


def _svg(body, reach):
    R = max(5.0, reach + 5.0)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" viewBox="%g %g %g %g">%s</svg>'
            % (2 * R, 2 * R, -R, -R, 2 * R, 2 * R, body))


class AlternatePositionPanel(D._Panel):
    TITLE = "Alternate Position"
    PIXMAP = "TechDraw_ProjectShape"

    def build(self):
        self.say("Click the assembly view, choose a component and move it, then OK.")
        box, lay = D._group("Configuration", self.form)
        self.new = QtWidgets.QRadioButton("New configuration", box)
        self.new.setObjectName("SWAltNew")
        self.new.setChecked(True)
        self.config = QtWidgets.QLineEdit("", box)
        self.config.setObjectName("SWAltName")
        self.existing = QtWidgets.QRadioButton("Existing configuration", box)
        self.existing.setObjectName("SWAltExisting")
        self.existing_list = QtWidgets.QComboBox(box)
        self.existing_list.setObjectName("SWAltExistingList")
        # shown once the view's model has an alternate position to pick (never a greyed radio and list)
        self.existing.setVisible(False)
        self.existing_list.setVisible(False)
        self.existing_list.activated.connect(lambda *_: self.existing.setChecked(True))   # a pick there is the choice
        self.config.textEdited.connect(lambda *_: self.new.setChecked(True))     # a name typed is New configuration
        lay.addWidget(self.new)
        lay.addWidget(self.config)
        lay.addWidget(self.existing)
        lay.addWidget(self.existing_list)
        self.lay.addWidget(box)
        box, lay = D._group("Move Component", self.form)
        self.component = QtWidgets.QComboBox(box)
        self.component.setObjectName("SWAltComponent")
        lay.addWidget(self.component)
        grid = QtWidgets.QGridLayout()
        self.dx, self.dy, self.dz, self.rotx, self.roty, self.rot = [QtWidgets.QDoubleSpinBox(box) for _ in range(6)]
        for n, (w, lab, nm) in enumerate(((self.dx, "ΔX:", "SWAltDX"), (self.dy, "ΔY:", "SWAltDY"),
                                          (self.dz, "ΔZ:", "SWAltDZ"), (self.rotx, "Rotate about X:", "SWAltRotX"),
                                          (self.roty, "Rotate about Y:", "SWAltRotY"),
                                          (self.rot, "Rotate about Z:", "SWAltRot"))):
            w.setObjectName(nm)
            w.setRange(-100000, 100000)
            w.setSuffix("°" if w in (self.rot, self.rotx, self.roty) else "mm")
            w.setKeyboardTracking(False)
            try:
                from . import optionsextras
                optionsextras.apply_step(w)
            except Exception as _fw_err:
                _fw_log("drawpalette.py:918", _fw_err)
            grid.addWidget(QtWidgets.QLabel(lab, box), n, 0)
            grid.addWidget(w, n, 1)
        lay.addLayout(grid)
        self.lay.addWidget(box)
        self.view = None
        self.moves = {}
        self.component.currentIndexChanged.connect(self.load)
        for w in (self.dx, self.dy, self.dz, self.rotx, self.roty, self.rot):
            w.valueChanged.connect(self.store)
        sel = [o for o in Gui.Selection.getSelection() if o.isDerivedFrom("TechDraw::DrawViewPart")]
        if sel:
            self.pick(sel[0])

    def pick(self, view):
        self.view = view
        self.parts = components(view)
        n = 1 + len([o for o in self.doc.Objects if getattr(o, "SWAlternateOf", "")])
        self.config.setText("AltPosition_Config%d" % n)
        self.component.blockSignals(True)
        self.component.clear()
        for o in self.parts:
            self.component.addItem(o.Label, o.Name)
        self.component.blockSignals(False)
        self.existing_list.clear()
        for g in alt_configurations(view):
            self.existing_list.addItem(g.Label, g.Name)
        has = self.existing_list.count() > 0
        self.existing.setVisible(has)
        self.existing_list.setVisible(has)
        self.load()
        self.say("Move a component with the boxes, then OK.")

    def current(self):
        name = self.component.currentData()
        return next((o for o in self.parts if o.Name == name), None) if self.view else None

    def load(self, *args):
        o = self.current()
        vals = self.moves.get(o.Name if o else None, (0, 0, 0, 0, 0, 0))
        for w, val in zip((self.dx, self.dy, self.dz, self.rotx, self.roty, self.rot), vals):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)

    def store(self, *args):
        o = self.current()
        if o is not None:
            self.moves[o.Name] = (self.dx.value(), self.dy.value(), self.dz.value(), self.rotx.value(),
                                  self.roty.value(), self.rot.value())

    def sheet_click(self, p):
        v = DV.view_at(self.page, p)
        if v is None:
            self.say("Click a drawing view of the assembly.")
            return True
        self.pick(v)
        return True

    def finish(self):
        if self.view is None:
            return
        if self.existing.isChecked() and self.existing_list.count():
            parts = components(self.view)
            grp = parts[0].Document.getObject(self.existing_list.currentData()) if parts else None
            if grp is not None:
                existing_position(self.page, self.view, grp)
            return
        self.store()
        moves = {}
        for o in self.parts:
            dx, dy, dz, rx, ry, r = self.moves.get(o.Name, (0, 0, 0, 0, 0, 0))
            if dx or dy or dz or rx or ry or r:
                # about the component's own origin (a part's axis is usually there), else its middle
                c = o.Placement.Base if hasattr(o, "Placement") else o.Shape.BoundBox.Center
                turn = App.Rotation(V(0, 0, 1), r).multiply(App.Rotation(V(0, 1, 0), ry)).multiply(
                    App.Rotation(V(1, 0, 0), rx))
                rot = App.Placement(V(0, 0, 0), turn, c)
                moves[o] = App.Placement(V(dx, dy, dz), App.Rotation()).multiply(rot)
        if not moves:
            return
        moves = solved_moves(self.view, moves)
        alternate_position(self.page, self.view, moves, self.config.text() or None)


# --------------------------------------------------------------------------- commands
COMMANDS = {
    "FreeWorks_DrawViewPalette": ("View Palette", "TechDraw_View", "Shows the View Palette: drag a part's views "
                                                                    "onto the sheet."),
    "FreeWorks_DrawAlternatePosition": ("Alternate Position", "TechDraw_ProjectShape",
                                        "Shows an assembly in another position, with phantom lines."),
}


class _Command:
    def __init__(self, name):
        self.name = name
        self.text, self.pixmap, self.tip = COMMANDS[name]

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": D.pixmap(self.pixmap)}

    def IsActive(self):
        if self.name == "FreeWorks_DrawViewPalette":
            return App.ActiveDocument is not None
        page = D.active_page()
        if page is None or D.busy() or not D.sheet_shown(page):
            return False
        return any(DV.source_shapes(v) for v in D.views_of(page))     # live with any model view

    def Activated(self):
        if self.name == "FreeWorks_DrawViewPalette":
            show_palette()
            return
        page = D.active_page()
        if page is not None:
            D._show(AlternatePositionPanel(page))


def _sheet_press(obj, event):
    ""

    try:
        if event.type() != QtCore.QEvent.MouseButtonPress or not isinstance(obj, QtWidgets.QWidget):
            return False
        gv = obj.parentWidget()
        if not isinstance(gv, QtWidgets.QGraphicsView) or gv.viewport() is not obj:
            return False
        host = gv.parentWidget()
        while host is not None and "MDIViewPage" not in host.metaObject().className():
            host = host.parentWidget()
        if host is None:
            return False
        try:
            g = event.globalPosition().toPoint()
        except Exception:
            g = event.globalPos()
        for pane in host.findChildren(QtWidgets.QWidget):
            if not (hasattr(pane, "pinned") and hasattr(pane, "close_pane")) or not pane.isVisible():
                continue
            if pane.pinned() or pane.rect().contains(pane.mapFromGlobal(g)):
                continue
            pane.close_pane()
    except Exception as _fw_err:
        _fw_log("drawpalette.py:1060", _fw_err)
    return False


def register():
    for name in COMMANDS:
        if name not in Gui.listCommands():
            Gui.addCommand(name, _Command(name))
    try:
        _hook_crop()
    except Exception as error:
        App.Console.PrintLog("FreeCAD: crop of alternate positions: %s\n" % error)
    try:
        from . import events
        events.register("drawpanes", (QtCore.QEvent.MouseButtonPress,), _sheet_press)
    except Exception as _fw_err:
        _fw_log("drawpalette.py:1076", _fw_err)
